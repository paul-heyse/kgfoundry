"""Utilities for building and verifying XTR token indexes."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config.settings import Settings, load_settings
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.xtr_manager import XTRIndex
from kgfoundry_common.logging import get_logger

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
    """Yield ``(chunk_id, content)`` pairs from the DuckDB catalog.

    Yields
    ------
    tuple[int, str]
        Chunk identifier and raw content string.
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
) -> tuple[list[np.ndarray], list[int], list[int], list[int], int]:
    """Collect encoded vectors and offsets for all chunks.

    Returns
    -------
    tuple
        Buffers, chunk ids, offsets, lengths, and total token count.
    """
    buffers: list[np.ndarray] = []
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
    buffers: Sequence[np.ndarray],
    *,
    dtype: np.dtype[Any],
    dim: int,
    root: Path,
    total_tokens: int,
) -> Path:
    """Persist buffered token vectors to memmap storage.

    Returns
    -------
    Path
        Path to the persisted token matrix file.
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

    Returns
    -------
    XTRBuildSummary
        Summary describing the generated artifacts.

    Raises
    ------
    RuntimeError
        If no chunks are available to encode.
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

    meta = {
        "dim": settings.xtr.dim,
        "dtype": "float32" if dtype is np.float32 else "float16",
        "total_tokens": int(total_tokens),
        "doc_count": len(chunk_ids),
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
            "doc_count": meta["doc_count"],
            "tokens": total_tokens,
            "dim": meta["dim"],
            "dtype": meta["dtype"],
            "root": str(xtr_dir),
        },
    )
    return XTRBuildSummary(
        chunk_count=meta["doc_count"],
        token_count=total_tokens,
        dim=meta["dim"],
        dtype=meta["dtype"],
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
