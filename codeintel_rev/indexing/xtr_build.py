"""Utilities for building and verifying XTR token indexes."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config.settings import Settings, load_settings
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.xtr_manager import XTRIndex
from codeintel_rev.typing import NDArrayAny
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    import numpy as np
else:
    np = cast("np", LazyModule("numpy", "XTR build pipeline"))

LOGGER = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class XTRBuildSummary:
    """Metadata describing a freshly built XTR token index."""

    chunk_count: int
    token_count: int
    dim: int
    dtype: str
    token_path: str
    meta_path: str


def _iter_chunk_text(
    catalog: DuckDBCatalog, *, batch_size: int = 1024
) -> Iterable[tuple[int, str]]:
    """Yield (chunk_id, content) pairs from the DuckDB catalog.

    Extended Summary
    ----------------
    This generator function efficiently streams chunk data from the DuckDB catalog
    in batches to minimize memory usage. It queries the chunks table ordered by ID,
    fetches rows in configurable batch sizes, and yields (chunk_id, content) tuples.
    This is used during XTR index building to process chunks incrementally without
    loading the entire catalog into memory.

    Parameters
    ----------
    catalog : DuckDBCatalog
        DuckDB catalog instance containing the chunks table. The catalog connection
        is opened within this function and closed when iteration completes.
    batch_size : int, optional
        Number of rows to fetch per database query. Larger batches reduce query
        overhead but increase memory usage. Defaults to 1024.

    Yields
    ------
    tuple[int, str]
        Chunk identifier and raw content string. Chunks with None IDs are skipped.
        Empty content strings are converted to empty strings.

    Notes
    -----
    Time complexity O(N) where N is total chunk count, amortized across batch queries.
    Space complexity O(batch_size) for temporary row storage. The function performs
    database I/O and manages catalog connection lifecycle. Thread-safe if catalog
    connection is thread-safe. Chunks are yielded in ID order.
    """
    with catalog.connection() as conn:
        cursor = conn.execute("SELECT id, content FROM chunks ORDER BY id")
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            for chunk_id, content in rows:
                if chunk_id is None:
                    continue
                yield int(chunk_id), str(content or "")


def _gather_chunk_vectors(
    index: XTRIndex,
    catalog: DuckDBCatalog,
    dtype: np.dtype[Any],
) -> tuple[list[NDArrayAny], list[int], list[int], list[int], int]:
    """Collect encoded vectors and offsets for all chunks.

    Extended Summary
    ----------------
    This function processes all chunks from the catalog, encodes their text content
    into token-level embeddings using the XTR index encoder, and collects the
    resulting vectors along with metadata (chunk IDs, offsets, lengths). The vectors
    are converted to the specified dtype for memory efficiency. This is a core step
    in XTR index building, transforming raw chunk text into the token embeddings
    that will be stored in the memory-mapped index.

    Parameters
    ----------
    index : XTRIndex
        XTR index instance used for encoding chunk text into token embeddings.
        The index's encode_query_tokens method is called for each chunk.
    catalog : DuckDBCatalog
        DuckDB catalog containing chunks to encode. Chunks are iterated via
        _iter_chunk_text helper.
    dtype : np.dtype[Any]
        NumPy dtype for the encoded vectors (typically float32 or float16).
        Vectors are cast to this dtype after encoding to reduce memory usage.

    Returns
    -------
    tuple[list[NDArrayAny], list[int], list[int], list[int], int]
        Five-element tuple containing:
        - List of token embedding arrays, one per chunk
        - List of chunk IDs corresponding to each buffer
        - List of token offsets (cumulative token count before each chunk)
        - List of token lengths (number of tokens per chunk)
        - Total token count across all chunks

    Notes
    -----
    Time complexity O(N * T * D) where N is chunk count, T is average tokens per
    chunk, and D is embedding dimension. Space complexity O(N * T * D) for all
    buffers. The function performs I/O to read chunks from catalog and GPU/CPU
    computation for encoding. Thread-safe if index encoder is thread-safe.
    Dimension mismatches are logged as warnings but processing continues.
    """
    buffers: list[NDArrayAny] = []
    chunk_ids: list[int] = []
    offsets: list[int] = []
    lengths: list[int] = []
    total_tokens = 0
    for chunk_id, content in _iter_chunk_text(catalog):
        vecs = index.encode_query_tokens(content)
        if vecs.shape[1] != index.config.dim:
            LOGGER.warning(
                "xtr_build_dimension_mismatch",
                extra={
                    "chunk_id": chunk_id,
                    "expected_dim": index.config.dim,
                    "observed_dim": vecs.shape[1],
                },
            )
        buffered = vecs.astype(dtype, copy=False)
        chunk_ids.append(chunk_id)
        offsets.append(total_tokens)
        lengths.append(buffered.shape[0])
        buffers.append(buffered)
        total_tokens += buffered.shape[0]
    return buffers, chunk_ids, offsets, lengths, total_tokens


def _write_token_matrix(
    buffers: Sequence[NDArrayAny],
    *,
    dtype: np.dtype[Any],
    dim: int,
    root: Path,
    total_tokens: int,
) -> Path:
    """Persist buffered token vectors to memmap storage.

    Extended Summary
    ----------------
    This function writes token embedding vectors to a memory-mapped NumPy array file
    for efficient random access during XTR search. It creates a memmap file with the
    specified shape and dtype, then copies vectors from the input buffers into the
    memmap in order. Vectors are truncated or zero-padded to match the target dimension.
    The resulting file can be memory-mapped read-only for fast access during search
    operations without loading the entire index into RAM.

    Parameters
    ----------
    buffers : Sequence[NDArrayAny]
        Sequence of token embedding arrays, one per chunk. Each array has shape
        (tokens_per_chunk, embedding_dim). Arrays are concatenated in order.
    dtype : np.dtype[Any]
        NumPy dtype for the memmap file (typically float32 or float16). Determines
        file size and precision trade-off.
    dim : int
        Target embedding dimension for the memmap. Vectors are truncated or
        zero-padded to this dimension. Must match the XTR index configuration.
    root : Path
        Directory path where the token matrix file will be written. The directory
        must exist or be creatable.
    total_tokens : int
        Total number of tokens across all buffers. Used to allocate the memmap
        shape as (total_tokens, dim).

    Returns
    -------
    Path
        Path to the persisted token matrix file. Filename is "tokens.f32" for
        float32 or "tokens.f16" for float16, based on dtype.

    Notes
    -----
    Time complexity O(N * D) where N is total_tokens and D is dim, due to memmap
    writes. Space complexity O(N * D) for the memmap file on disk. The function
    performs file I/O and flushes the memmap to ensure data is persisted. Thread-safe
    if buffers are not modified concurrently. Vectors shorter than dim are zero-padded;
    vectors longer than dim are truncated.
    """
    token_path = root / ("tokens.f32" if dtype is np.float32 else "tokens.f16")
    token_memmap = np.memmap(
        token_path,
        mode="w+",
        dtype=dtype,
        shape=(total_tokens, dim),
    )
    cursor = 0
    for chunk_vecs in buffers:
        rows = chunk_vecs.shape[0]
        cols = min(chunk_vecs.shape[1], dim)
        token_memmap[cursor : cursor + rows, :cols] = chunk_vecs[:, :cols]
        if cols < dim:
            token_memmap[cursor : cursor + rows, cols:] = 0.0
        cursor += rows
    token_memmap.flush()
    return token_path


def build_xtr_index(settings: Settings | None = None) -> XTRBuildSummary:
    """Build XTR token artifacts from DuckDB chunks.

    Extended Summary
    ----------------
    This function orchestrates the complete XTR index building process, reading chunks
    from the DuckDB catalog, encoding them into token-level embeddings, and persisting
    the results as memory-mapped files. It creates the XTR index directory structure,
    encodes all chunks using the configured XTR model, writes token embeddings and
    metadata, and returns a summary of the generated artifacts. This is the primary
    entry point for building XTR indexes from existing chunk data.

    Parameters
    ----------
    settings : Settings | None, optional
        Application settings containing XTR configuration, paths, and model settings.
        If None, settings are loaded from the default location. Defaults to None.

    Returns
    -------
    XTRBuildSummary
        Summary describing the generated artifacts, including chunk count, token count,
        embedding dimension, dtype, and file paths for the token matrix and metadata.

    Raises
    ------
    RuntimeError
        If no chunks are available to encode in the catalog. This indicates the
        catalog is empty or chunks table is missing, and index building cannot proceed.

    Notes
    -----
    Time complexity O(N * T * D) where N is chunk count, T is average tokens per
    chunk, and D is embedding dimension. Space complexity O(N * T * D) for buffers
    and memmap files. The function performs database I/O, GPU/CPU encoding computation,
    and file I/O. Not thread-safe due to catalog and file system operations.
    The function creates the XTR directory if it doesn't exist.
    """
    settings = settings or load_settings()
    paths = resolve_application_paths(settings)
    catalog = DuckDBCatalog(
        paths.duckdb_path,
        paths.vectors_dir,
        materialize=settings.index.duckdb_materialize,
    )
    catalog.open()

    xtr_dir = paths.xtr_dir
    xtr_dir.mkdir(parents=True, exist_ok=True)
    index = XTRIndex(root=xtr_dir, config=settings.xtr)

    dtype = np.dtype(np.float32 if settings.xtr.dtype == "float32" else np.float16)
    buffers, chunk_ids, offsets, lengths, total_tokens = _gather_chunk_vectors(
        index=index,
        catalog=catalog,
        dtype=dtype,
    )

    if total_tokens == 0:
        msg = "No tokens produced from catalog; ensure chunks exist before building XTR."
        raise RuntimeError(msg)

    token_path = _write_token_matrix(
        buffers=buffers,
        dtype=dtype,
        dim=settings.xtr.dim,
        root=xtr_dir,
        total_tokens=total_tokens,
    )

    doc_count = len(chunk_ids)
    dim_value = settings.xtr.dim
    dtype_label = "float32" if dtype is np.float32 else "float16"
    meta = {
        "dim": dim_value,
        "dtype": dtype_label,
        "total_tokens": int(total_tokens),
        "doc_count": doc_count,
        "chunk_ids": chunk_ids,
        "offsets": offsets,
        "lengths": lengths,
    }
    meta_path = xtr_dir / "index.meta.json"
    with meta_path.open("w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)

    LOGGER.info(
        "xtr_build_complete",
        extra={
            "doc_count": doc_count,
            "tokens": total_tokens,
            "dim": dim_value,
            "dtype": dtype_label,
            "root": str(xtr_dir),
        },
    )
    return XTRBuildSummary(
        chunk_count=doc_count,
        token_count=total_tokens,
        dim=dim_value,
        dtype=dtype_label,
        token_path=str(token_path),
        meta_path=str(meta_path),
    )


def main() -> None:
    """Entry point allowing ``python -m codeintel_rev.indexing.xtr_build``."""
    summary = build_xtr_index()
    LOGGER.info(
        "xtr_build_summary",
        extra={
            "chunk_count": summary.chunk_count,
            "token_count": summary.token_count,
            "token_path": summary.token_path,
            "meta_path": summary.meta_path,
        },
    )


if __name__ == "__main__":  # pragma: no cover - manual execution entry point
    main()
