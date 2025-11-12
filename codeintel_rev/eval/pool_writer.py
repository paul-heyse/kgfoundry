"""Lightweight Parquet writer for evaluator pools."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

try:  # pragma: no cover - dependency optional at import time
    import pyarrow as pa
    import pyarrow.parquet as pq
except ModuleNotFoundError:  # pragma: no cover
    pa = None  # type: ignore[assignment]
    pq = None  # type: ignore[assignment]

Source = Literal["faiss", "bm25", "splade", "ann", "oracle"]


@dataclass(frozen=True)
class PoolRow:
    """Single evaluator pool row."""

    query_id: str
    source: Source
    rank: int
    chunk_id: int
    score: float


def _empty_table() -> pa.Table:
    """Return an empty evaluator table with the expected schema.

    Returns
    -------
    pa.Table
        Empty table with the evaluator schema.

    Raises
    ------
    RuntimeError
        If pyarrow is not available.
    """
    if pa is None:  # pragma: no cover
        msg = "pyarrow is required to build evaluator tables"
        raise RuntimeError(msg)
    return pa.Table.from_arrays(
        [
            pa.array([], type=pa.string()),
            pa.array([], type=pa.dictionary(pa.int32(), pa.string())),
            pa.array([], type=pa.int32()),
            pa.array([], type=pa.int64()),
            pa.array([], type=pa.float32()),
        ],
        names=["query_id", "source", "rank", "chunk_id", "score"],
    )


def write_pool(rows: Iterable[PoolRow], out_path: Path, *, overwrite: bool = True) -> int:
    """Write `(query_id, source, rank, chunk_id, score)` tuples to Parquet.

    Parameters
    ----------
    rows : Iterable[PoolRow]
        Pool rows to persist.
    out_path : Path
        Destination Parquet file.
    overwrite : bool, optional
        When True (default) any existing file is replaced.

    Returns
    -------
    int
        Number of rows written.

    Raises
    ------
    RuntimeError
        If pyarrow is not available.
    """
    if pa is None or pq is None:  # pragma: no cover
        msg = "pyarrow is required to write evaluator pools"
        raise RuntimeError(msg)

    materialized = list(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite and out_path.exists():
        out_path.unlink()

    if not materialized:
        pq.write_table(_empty_table(), out_path, compression="zstd")
        return 0

    table = pa.Table.from_arrays(
        [
            pa.array([row.query_id for row in materialized], type=pa.string()),
            pa.array([row.source for row in materialized]),
            pa.array([int(row.rank) for row in materialized], type=pa.int32()),
            pa.array([int(row.chunk_id) for row in materialized], type=pa.int64()),
            pa.array([float(row.score) for row in materialized], type=pa.float32()),
        ],
        names=["query_id", "source", "rank", "chunk_id", "score"],
    )
    pq.write_table(table, out_path, compression="zstd", use_dictionary=True)
    return len(materialized)


__all__ = ["PoolRow", "write_pool"]
