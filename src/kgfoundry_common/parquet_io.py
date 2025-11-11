"""Overview of parquet io.

This module bundles parquet io logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

import pyarrow as pa
import pyarrow.parquet as pq

from kgfoundry_common.errors import DeserializationError
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.typing import gate_import

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pandas import DataFrame

else:
    DataFrame = Any

__all__ = [
    "ChunkDocTags",
    "ChunkRow",
    "ParquetChunkWriter",
    "ParquetVectorWriter",
    "read_table",
    "read_table_to_dataframe",
    "validate_table_schema",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor ChunkDocTags]
class ChunkDocTags(TypedDict, total=False):
    """Structured metadata describing a chunk's doctags span."""

    node_id: str
    start: int
    end: int


# [nav:anchor ChunkRow]
class ChunkRow(TypedDict, total=False):
    """Row expected by :class:`ParquetChunkWriter`."""

    chunk_id: str
    doc_id: str
    section: str
    start_char: int
    end_char: int
    doctags_span: NotRequired[ChunkDocTags | None]
    text: str
    tokens: int
    created_at: NotRequired[int]


ZSTD_LEVEL = 6
ROW_GROUP_SIZE = 4096


# [nav:anchor ParquetVectorWriter]
class ParquetVectorWriter:
    """Writer for embedding vectors in Parquet format.

    Provides utilities for writing dense and sparse (SPLADE) embedding vectors
    to Parquet files with Hive-style partitioning. Supports partitioning by
    model, run_id, and shard for efficient querying.

    Initializes the Parquet vector writer with root directory.

    Parameters
    ----------
    root : str
        Root directory path for Parquet output. Converted to Path object
        and stored for use by write methods. Vectors will be written to
        subdirectories partitioned by model, run_id, and shard.

    Notes
    -----
    The writer creates Hive-style partitioned directories:
    ``root/model={model}/run_id={run_id}/shard={shard:05d}/part-00000.parquet``

    Files are compressed with ZSTD compression (level 6) and use a row group
    size of 4096 bytes for optimal read performance.
    """

    @staticmethod
    def dense_schema(dim: int) -> pa.Schema:
        """Create PyArrow schema for dense vector embeddings.

        Defines the schema for dense embedding vectors with fixed dimension.
        Includes chunk_id, model, run_id, vector array, L2 norm, and timestamp.

        Parameters
        ----------
        dim : int
            Vector dimension (must match the length of vector arrays).

        Returns
        -------
        pa.Schema
            PyArrow schema with fields: chunk_id (string), model (dictionary),
            run_id (dictionary), dim (int16), vector (list<float32>), l2_norm
            (float32), created_at (timestamp).
        """
        return pa.schema(
            [
                pa.field("chunk_id", pa.string()),
                pa.field("model", pa.dictionary(pa.int32(), pa.string())),
                pa.field("run_id", pa.dictionary(pa.int32(), pa.string())),
                pa.field("dim", pa.int16()),
                pa.field("vector", pa.list_(pa.float32(), list_size=dim)),
                pa.field("l2_norm", pa.float32()),
                pa.field("created_at", pa.timestamp("ms")),
            ]
        )

    def __init__(self, root: str) -> None:
        """Initialize the Parquet vector writer. See class docstring for full details."""
        self.root = Path(root)

    def write_dense(
        self,
        model: str,
        run_id: str,
        dim: int,
        records: Iterable[tuple[str, list[float], float]],
        shard: int = 0,
    ) -> str:
        """Write dense embedding vectors to Parquet file.

        Writes dense embedding vectors (fixed-dimension float arrays) to a
        Parquet file with Hive-style partitioning. Each record consists of
        chunk_id, vector array, and L2 norm.

        Parameters
        ----------
        model : str
            Model identifier used for partitioning (e.g., "qwen3", "sentence-transformers").
        run_id : str
            Run identifier used for partitioning (e.g., "dev", "prod-v1").
        dim : int
            Vector dimension. Must match the length of all vector arrays in records.
        records : Iterable[tuple[str, list[float], float]]
            Iterable of (chunk_id, vector, l2_norm) tuples. Each vector must
            be a list of floats with length equal to dim.
        shard : int, optional
            Shard number for partitioning. Used to distribute data across
            multiple files. Defaults to 0.

        Returns
        -------
        str
            Root directory path where the Parquet file was written.

        Notes
        -----
        Creates a timestamp (milliseconds since epoch) for all records in this
        batch. The output file is written to:
        ``root/model={model}/run_id={run_id}/shard={shard:05d}/part-00000.parquet``
        """
        part_dir = self.root / f"model={model}" / f"run_id={run_id}" / f"shard={shard:05d}"
        part_dir.mkdir(parents=True, exist_ok=True)
        now = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
        rows = [
            {
                "chunk_id": cid,
                "model": model,
                "run_id": run_id,
                "dim": dim,
                "vector": vec,
                "l2_norm": float(l2),
                "created_at": now,
            }
            for cid, vec, l2 in records
        ]
        table = pa.Table.from_pylist(rows, schema=self.dense_schema(dim))
        pq.write_table(
            table,
            part_dir / "part-00000.parquet",
            compression="zstd",
            compression_level=ZSTD_LEVEL,
            data_page_size=ROW_GROUP_SIZE,
        )
        return str(self.root)

    @staticmethod
    def splade_schema() -> pa.Schema:
        """Create PyArrow schema for SPLADE sparse vectors.

        Defines the schema for SPLADE (Sparse Lexical and Expansion) sparse
        embedding vectors. Includes vocab_ids, weights, and non-zero count.

        Returns
        -------
        pa.Schema
            PyArrow schema with fields: chunk_id (string), model (dictionary),
            run_id (dictionary), vocab_ids (list<int32>), weights
            (list<float32>), nnz (int16), created_at (timestamp).
        """
        splade_fields = (
            pa.field("chunk_id", pa.string()),
            pa.field("model", pa.dictionary(pa.int32(), pa.string())),
            pa.field("run_id", pa.dictionary(pa.int32(), pa.string())),
            pa.field("vocab_ids", pa.list_(pa.int32())),
            pa.field("weights", pa.list_(pa.float32())),
            pa.field("nnz", pa.int16()),
            pa.field("created_at", pa.timestamp("ms")),
        )
        return pa.schema(splade_fields)

    def write_splade(
        self,
        model: str,
        run_id: str,
        records: Iterable[tuple[str, list[int], list[float]]],
        shard: int = 0,
    ) -> str:
        """Write SPLADE sparse vectors to Parquet file.

        Writes SPLADE (Sparse Lexical and Expansion) sparse embedding vectors
        to a Parquet file with Hive-style partitioning. Each record consists of
        chunk_id, vocabulary IDs, and corresponding weights.

        Parameters
        ----------
        model : str
            Model identifier used for partitioning (e.g., "splade-v2").
        run_id : str
            Run identifier used for partitioning (e.g., "dev", "prod-v1").
        records : Iterable[tuple[str, list[int], list[float]]]
            Iterable of (chunk_id, vocab_ids, weights) tuples. vocab_ids and
            weights must have the same length (non-zero elements).
        shard : int, optional
            Shard number for partitioning. Used to distribute data across
            multiple files. Defaults to 0.

        Returns
        -------
        str
            Root directory path where the Parquet file was written.

        Notes
        -----
        The nnz (number of non-zeros) field is automatically computed from the
        length of vocab_ids. Creates a timestamp (milliseconds since epoch) for
        all records in this batch.
        """
        part_dir = self.root / f"model={model}" / f"run_id={run_id}" / f"shard={shard:05d}"
        part_dir.mkdir(parents=True, exist_ok=True)
        now = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
        rows = [
            {
                "chunk_id": cid,
                "model": model,
                "run_id": run_id,
                "vocab_ids": ids,
                "weights": wts,
                "nnz": len(ids),
                "created_at": now,
            }
            for cid, ids, wts in records
        ]
        table = pa.Table.from_pylist(rows, schema=self.splade_schema())
        pq.write_table(
            table,
            part_dir / "part-00000.parquet",
            compression="zstd",
            compression_level=ZSTD_LEVEL,
            data_page_size=ROW_GROUP_SIZE,
        )
        return str(self.root)


# [nav:anchor ParquetChunkWriter]
class ParquetChunkWriter:
    """Writer for document chunks in Parquet format.

    Provides utilities for writing document chunks (text segments with metadata)
    to Parquet files with Hive-style partitioning. Supports chunk text, character
    offsets, section information, and optional doctags spans.

    Initializes the Parquet chunk writer with root directory and partitioning parameters.

    Parameters
    ----------
    root : str
        Root directory path for Parquet output. Converted to Path object
        and combined with model and run_id partitioning. Chunks will be written to
        subdirectories partitioned by model and run_id.
    model : str, optional
        Model identifier used for partitioning. Defaults to "docling_hybrid".
    run_id : str, optional
        Run identifier used for partitioning. Defaults to "dev".

    Notes
    -----
    The writer creates Hive-style partitioned directories:
    ``root/model={model}/run_id={run_id}/shard=00000/part-00000.parquet``

    Files are compressed with ZSTD compression (level 6) and use a row group
    size of 4096 bytes for optimal read performance.
    """

    @staticmethod
    def chunk_schema() -> pa.Schema:
        """Create PyArrow schema for document chunks.

        Defines the schema for document chunks with text, metadata, and optional
        doctags spans. Includes chunk_id, doc_id, section, character offsets,
        text content, token count, and timestamp.

        Returns
        -------
        pa.Schema
            PyArrow schema with fields: chunk_id (string), doc_id (string),
            section (string), start_char (int32), end_char (int32), doctags_span
            (struct, nullable), text (string), tokens (int32), created_at
            (timestamp).
        """
        doctags_fields = (
            pa.field("node_id", pa.string()),
            pa.field("start", pa.int32()),
            pa.field("end", pa.int32()),
        )
        chunk_fields = (
            pa.field("chunk_id", pa.string()),
            pa.field("doc_id", pa.string()),
            pa.field("section", pa.string()),
            pa.field("start_char", pa.int32()),
            pa.field("end_char", pa.int32()),
            pa.field("doctags_span", pa.struct(doctags_fields), nullable=True),
            pa.field("text", pa.string()),
            pa.field("tokens", pa.int32()),
            pa.field("created_at", pa.timestamp("ms")),
        )
        return pa.schema(chunk_fields)

    def __init__(self, root: str, model: str = "docling_hybrid", run_id: str = "dev") -> None:
        """Initialize the Parquet chunk writer. See class docstring for full details."""
        self.root = Path(root) / f"model={model}" / f"run_id={run_id}" / "shard=00000"
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, rows: Iterable[ChunkRow]) -> str:
        """Write document chunks to Parquet file.

        Writes an iterable of chunk rows to a Parquet file. Automatically adds
        created_at timestamp if not present in rows. Validates rows against the
        chunk schema before writing.

        Parameters
        ----------
        rows : Iterable[ChunkRow]
            Iterable of chunk row dictionaries. Each row must conform to
            :class:`ChunkRow` TypedDict structure. Missing created_at fields
            are automatically populated with current timestamp.

        Returns
        -------
        str
            Root directory path (two levels up from the actual file location)
            where the Parquet file was written.

        Notes
        -----
        The created_at timestamp is set to the current UTC time in milliseconds
        if not provided in the row. All rows are validated against the chunk
        schema before writing.
        """
        timestamp_ms = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
        prepared: list[ChunkRow] = []
        for row in rows:
            materialized: ChunkRow = {**row}
            materialized.setdefault("created_at", timestamp_ms)
            prepared.append(materialized)
        table = pa.Table.from_pylist(prepared, schema=self.chunk_schema())
        pq.write_table(
            table,
            self.root / "part-00000.parquet",
            compression="zstd",
            compression_level=ZSTD_LEVEL,
            data_page_size=ROW_GROUP_SIZE,
        )
        return str(self.root.parent.parent)


# [nav:anchor read_table]
def read_table(
    path: str | Path,
    *,
    schema: pa.Schema | None = None,
    validate_schema: bool = True,
) -> pa.Table:
    """Read a Parquet file and return a typed Table.

    Loads a Parquet file or directory and returns a PyArrow Table. Optionally
    validates the table schema against an expected schema.

    Parameters
    ----------
    path : str | Path
        Path to Parquet file or directory containing Parquet files.
    schema : pa.Schema | None, optional
        Expected schema for validation. If provided and validate_schema=True,
        raises DeserializationError if the table schema does not match.
        Defaults to None.
    validate_schema : bool, optional
        Whether to validate against the provided schema. Only used if schema
        is not None. Defaults to True.

    Returns
    -------
    pa.Table
        PyArrow Table with concrete schema. Contains all rows from the Parquet
        file(s).

    Raises
    ------
    FileNotFoundError
        If the Parquet file or directory does not exist.
    DeserializationError
        If schema validation fails (when schema is provided and validation
        enabled) or if the file is corrupted or invalid.

    Examples
    --------
    >>> from pathlib import Path
    >>> from kgfoundry_common.parquet_io import read_table
    >>> # Note: requires existing Parquet file
    >>> # table = read_table("data.parquet")
    >>> # assert table.num_rows > 0
    """
    path_obj = Path(path)
    if not path_obj.exists():
        msg = f"Parquet file not found: {path_obj}"
        raise FileNotFoundError(msg)

    try:
        table = pq.read_table(path_obj)
    except Exception as exc:
        msg = f"Failed to read Parquet file {path_obj}: {exc}"
        raise DeserializationError(msg) from exc

    if schema is not None and validate_schema:
        validate_table_schema(table, schema)

    return table


# [nav:anchor read_table_to_dataframe]
def read_table_to_dataframe(
    path: str | Path,
    *,
    schema: pa.Schema | None = None,
    validate_schema: bool = True,
) -> DataFrame:
    """Read a Parquet file and return a typed DataFrame.

    Loads a Parquet file or directory and converts it to a pandas DataFrame.
    Optionally validates the table schema before conversion. Requires pandas
    to be installed.

    Parameters
    ----------
    path : str | Path
        Path to Parquet file or directory containing Parquet files.
    schema : pa.Schema | None, optional
        Expected schema for validation. If provided and validate_schema=True,
        raises DeserializationError if the table schema does not match.
        Defaults to None.
    validate_schema : bool, optional
        Whether to validate against the provided schema. Only used if schema
        is not None. Defaults to True.

    Returns
    -------
    DataFrame
        Pandas DataFrame with schema metadata preserved. Contains all rows
        from the Parquet file(s).

    Raises
    ------
    ImportError
        If pandas is not installed.

    Notes
    -----
    This function wraps :func:`read_table` and converts the result to a pandas
    DataFrame. Schema validation or file-related errors raised by
    :func:`read_table` propagate unchanged.

    Examples
    --------
    >>> from pathlib import Path
    >>> from kgfoundry_common.parquet_io import read_table_to_dataframe
    >>> # Note: requires existing Parquet file and pandas
    >>> # df = read_table_to_dataframe("data.parquet")
    >>> # assert len(df) > 0
    """
    try:
        gate_import("pandas", "Parquet DataFrame conversion")
    except ImportError as exc:
        msg = "pandas is required for DataFrame conversion"
        raise ImportError(msg) from exc
    table = read_table(path, schema=schema, validate_schema=validate_schema)
    return table.to_pandas()


# [nav:anchor validate_table_schema]
def validate_table_schema(table: pa.Table, expected_schema: pa.Schema) -> None:
    """Validate that a table matches an expected schema.

    Compares the schema of a PyArrow Table against an expected schema and
    raises an exception if they do not match exactly.

    Parameters
    ----------
    table : pa.Table
        PyArrow Table to validate.
    expected_schema : pa.Schema
        Expected schema that the table should match.

    Raises
    ------
    DeserializationError
        If the table schema does not match the expected schema. The error
        message includes both schemas for debugging.

    Examples
    --------
    >>> import pyarrow as pa
    >>> from kgfoundry_common.parquet_io import validate_table_schema
    >>> schema = pa.schema([pa.field("id", pa.string())])
    >>> table = pa.Table.from_pylist([{"id": "test"}], schema=schema)
    >>> validate_table_schema(table, schema)  # No error
    """
    if not table.schema.equals(expected_schema):
        msg = f"Schema mismatch: expected {expected_schema}, got {table.schema}"
        raise DeserializationError(msg)
