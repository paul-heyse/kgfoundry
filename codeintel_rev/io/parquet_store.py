"""Parquet storage for chunks and vectors using Arrow.

Stores chunks and embeddings in columnar Parquet format with FixedSizeList
for efficient vector storage and querying via DuckDB.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pyarrow as pa
import pyarrow.parquet as pq

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import NDArrayF32

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy as np

    from codeintel_rev.indexing.cast_chunker import Chunk
else:
    np = cast("np", LazyModule("numpy", "Parquet embedding storage"))


def get_chunks_schema(vec_dim: int) -> pa.Schema:
    """Get Arrow schema for chunks table.

    Parameters
    ----------
    vec_dim : int
        Embedding dimension.

    Returns
    -------
    pa.Schema
        Arrow schema for chunks with embeddings.
    """
    return pa.schema(
        [
            pa.field("id", pa.int64()),
            pa.field("uri", pa.string()),
            pa.field("start_line", pa.int32()),
            pa.field("end_line", pa.int32()),
            pa.field("start_byte", pa.int64()),
            pa.field("end_byte", pa.int64()),
            pa.field("preview", pa.string()),
            pa.field("content", pa.string()),
            pa.field("lang", pa.string()),
            pa.field("embedding", pa.list_(pa.float32(), vec_dim)),
        ]
    )


@dataclass(slots=True, frozen=True)
class ParquetWriteOptions:
    """Configuration for Parquet persistence."""

    start_id: int = 0
    vec_dim: int = 2560
    preview_max_chars: int = 240


def write_chunks_parquet(
    output_path: Path,
    chunks: Sequence[Chunk],
    embeddings: NDArrayF32,
    *,
    options: ParquetWriteOptions | None = None,
) -> None:
    """Write chunks and embeddings to Parquet.

    Parameters
    ----------
    output_path : Path
        Output Parquet file path.
    chunks : Sequence[Chunk]
        Chunk metadata.
    embeddings : NDArrayF32
        Embeddings array of shape (len(chunks), vec_dim).
    options : ParquetWriteOptions | None, optional
        Configuration for chunk identifiers, embedding dimension, and preview
        truncation length. Defaults to :class:`ParquetWriteOptions`.

    Raises
    ------
    ValueError
        If chunks and embeddings length mismatch.
    """
    if options is None:
        options = ParquetWriteOptions()

    if len(chunks) != len(embeddings):
        msg = f"Chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch"
        raise ValueError(msg)

    # Prepare data
    ids = list(range(options.start_id, options.start_id + len(chunks)))
    uris = [c.uri for c in chunks]
    start_lines = [c.start_line for c in chunks]
    end_lines = [c.end_line for c in chunks]
    start_bytes = [c.start_byte for c in chunks]
    end_bytes = [c.end_byte for c in chunks]
    previews = [c.text[: options.preview_max_chars] for c in chunks]
    contents = [c.text for c in chunks]
    languages = [c.language for c in chunks]

    # Convert embeddings to FixedSizeList
    embeddings_flat = embeddings.astype(np.float32).ravel()
    embedding_array = pa.FixedSizeListArray.from_arrays(
        pa.array(embeddings_flat, type=pa.float32()),
        options.vec_dim,
    )

    # Create table
    table = pa.table(
        {
            "id": ids,
            "uri": uris,
            "start_line": start_lines,
            "end_line": end_lines,
            "start_byte": start_bytes,
            "end_byte": end_bytes,
            "preview": previews,
            "content": contents,
            "lang": languages,
            "embedding": embedding_array,
        },
        schema=get_chunks_schema(options.vec_dim),
    )

    # Write with compression
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        output_path,
        compression="snappy",
        use_dictionary=True,
    )


def read_chunks_parquet(parquet_path: Path) -> pa.Table:
    """Read chunks from Parquet file.

    Parameters
    ----------
    parquet_path : Path
        Parquet file path.

    Returns
    -------
    pa.Table
        Chunks table.
    """
    return pq.read_table(parquet_path)


def extract_embeddings(table: pa.Table) -> NDArrayF32:
    """Extract embeddings from chunks table.

    Parameters
    ----------
    table : pa.Table
        Chunks table with embedding column.

    Returns
    -------
    NDArrayF32
        Embeddings array of shape (num_rows, vec_dim).

    Raises
    ------
    TypeError
        If the embedding column is not stored as a FixedSizeListArray.
    """
    chunked = table.column("embedding")
    dense_array = chunked.combine_chunks()
    if not isinstance(dense_array, pa.FixedSizeListArray):
        msg = "Embedding column is not a FixedSizeListArray"
        raise TypeError(msg)

    fixed_array = cast("pa.FixedSizeListArray", dense_array)
    # Convert list_size (which is a _Size type) to int for numpy.reshape
    vec_dim = int(getattr(fixed_array.type, "list_size", 0))
    flat_values = fixed_array.values.to_numpy(zero_copy_only=False)
    return flat_values.reshape(-1, vec_dim)


__all__ = [
    "ParquetWriteOptions",
    "extract_embeddings",
    "get_chunks_schema",
    "read_chunks_parquet",
    "write_chunks_parquet",
]
