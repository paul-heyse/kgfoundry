"""Parquet storage for chunks and vectors using Arrow.

Stores chunks and embeddings in columnar Parquet format with FixedSizeList
for efficient vector storage and querying via DuckDB.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import pyarrow as pa
import pyarrow.parquet as pq

try:  # pragma: no cover - optional accelerator
    import xxhash  # type: ignore[import]
except ModuleNotFoundError:  # pragma: no cover - fallback to hashlib
    xxhash = None  # type: ignore[assignment]

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.indexing.chunk_ids import stable_chunk_id
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
            pa.field("content_hash", pa.uint64()),
            pa.field("symbols", pa.list_(pa.string())),
            pa.field(
                "embedding",
                pa.list_(pa.field("item", pa.float32()), list_size=vec_dim),
            ),
        ]
    )


EMBEDDINGS_RANK: int = 2


@dataclass(slots=True, frozen=True)
class ParquetWriteOptions:
    """Configuration for Parquet persistence."""

    start_id: int = 0
    vec_dim: int = 2560
    preview_max_chars: int = 240
    id_strategy: Literal["sequence", "stable_hash"] = "sequence"
    id_hash_salt: str = ""
    table_meta: dict[str, str] | None = None


def _hash_content(text: str) -> int:
    """Return stable 64-bit hash of chunk content.

    This function computes a deterministic hash of text content using xxhash when
    available, or falls back to a built-in hash function. The hash is used for
    content deduplication and change detection in chunk processing pipelines.

    Parameters
    ----------
    text : str
        Text content to hash. The text is encoded as UTF-8 (with error handling)
        before hashing. Used to generate a stable identifier for chunk content.

    Returns
    -------
    int
        Unsigned 64-bit hash value derived from the UTF-8 encoded text. The hash
        is deterministic for the same input text and suitable for use as a content
        fingerprint or deduplication key.
    """
    encoded = text.encode("utf-8", errors="ignore")
    if xxhash is not None:
        return xxhash.xxh64_intdigest(encoded) & 0xFFFFFFFFFFFFFFFF
    digest = hashlib.blake2b(encoded, digest_size=8)
    return int.from_bytes(digest.digest(), byteorder="little", signed=False)


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

    vec_dim = int(options.vec_dim)
    if embeddings.ndim != EMBEDDINGS_RANK:
        msg = f"Embeddings must be 2D (got shape {embeddings.shape})"
        raise ValueError(msg)
    if embeddings.shape[1] != vec_dim:
        msg = f"Embedding dimension mismatch: expected {vec_dim}, got {embeddings.shape[1]}"
        raise ValueError(msg)

    # Convert embeddings to FixedSizeList
    embeddings_view = np.asarray(embeddings, dtype=np.float32)
    embeddings_flat = embeddings_view.ravel()
    embedding_array = pa.FixedSizeListArray.from_arrays(
        pa.array(embeddings_flat, type=pa.float32()),
        vec_dim,
    )

    # Prepare IDs
    if options.id_strategy == "stable_hash":
        ids = [
            stable_chunk_id(
                chunk.uri,
                int(chunk.start_byte),
                int(chunk.end_byte),
                salt=options.id_hash_salt,
            )
            for chunk in chunks
        ]
    else:
        ids = list(range(options.start_id, options.start_id + len(chunks)))

    # Create table
    table = pa.table(
        {
            "id": ids,
            "uri": [chunk.uri for chunk in chunks],
            "start_line": [chunk.start_line for chunk in chunks],
            "end_line": [chunk.end_line for chunk in chunks],
            "start_byte": [chunk.start_byte for chunk in chunks],
            "end_byte": [chunk.end_byte for chunk in chunks],
            "preview": [chunk.text[: options.preview_max_chars] for chunk in chunks],
            "content": [chunk.text for chunk in chunks],
            "lang": [chunk.language for chunk in chunks],
            "content_hash": [_hash_content(chunk.text) for chunk in chunks],
            "symbols": [list(chunk.symbols) for chunk in chunks],
            "embedding": embedding_array,
        },
        schema=get_chunks_schema(vec_dim),
    )
    if options.table_meta:
        existing_meta = table.schema.metadata or {}
        encoded = existing_meta.copy()
        for key, value in options.table_meta.items():
            encoded[str(key).encode("utf-8")] = str(value).encode("utf-8")
        table = table.replace_schema_metadata(encoded)

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

    fixed_array = dense_array
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
