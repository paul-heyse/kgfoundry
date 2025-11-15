"""Lightweight Parquet writer for evaluator pools."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Literal, cast

from codeintel_rev.retrieval.types import SearchPoolRow

if TYPE_CHECKING:
    import pyarrow as pa
    import pyarrow.parquet as pq
else:  # pragma: no cover - dependency optional at import time
    pa: ModuleType | None
    pq: ModuleType | None
    try:
        import pyarrow as _pyarrow
        import pyarrow.parquet as _pyarrow_parquet
    except ModuleNotFoundError:
        pa = None
        pq = None
    else:
        pa = cast("ModuleType", _pyarrow)
        pq = cast("ModuleType", _pyarrow_parquet)

Channel = Literal[
    "faiss",
    "faiss_refine",
    "bm25",
    "splade",
    "ann",
    "oracle",
    "xtr",
    "xtr_oracle",
]


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
            pa.array([], type=pa.string()),
            pa.array([], type=pa.int32()),
            pa.array([], type=pa.int64()),
            pa.array([], type=pa.float32()),
            pa.StructArray.from_arrays(
                [
                    pa.array([], type=pa.list_(pa.string())),
                    pa.array([], type=pa.string()),
                    pa.array([], type=pa.list_(pa.string())),
                ],
                fields=[
                    pa.field("matched_symbols", pa.list_(pa.string())),
                    pa.field("ast_kind", pa.string()),
                    pa.field("cst_hits", pa.list_(pa.string())),
                ],
            ),
        ],
        names=[
            "query_id",
            "channel",
            "rank",
            "chunk_id",
            "score",
            "reason",
        ],
    )


def write_pool(rows: Iterable[SearchPoolRow], out_path: Path, *, overwrite: bool = True) -> int:
    """Write `(query_id, channel, rank, chunk_id, score, uri, ...)` rows to Parquet.

    Parameters
    ----------
    rows : Iterable[SearchPoolRow]
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

    matched_symbols: list[list[str] | None] = []
    ast_kinds: list[str | None] = []
    cst_hits: list[list[str] | None] = []
    for row in materialized:
        reason = dict(row.reason or {})
        symbols = reason.get("matched_symbols")
        cst = reason.get("cst_hits")
        matched_symbols.append([str(item) for item in symbols] if symbols else [])
        ast_value = reason.get("ast_kind")
        ast_kinds.append(str(ast_value) if ast_value else None)
        cst_hits.append([str(item) for item in cst] if cst else None)

    reason_struct = pa.StructArray.from_arrays(
        [
            pa.array(matched_symbols, type=pa.list_(pa.string())),
            pa.array(ast_kinds, type=pa.string()),
            pa.array(cst_hits, type=pa.list_(pa.string())),
        ],
        fields=[
            pa.field("matched_symbols", pa.list_(pa.string())),
            pa.field("ast_kind", pa.string()),
            pa.field("cst_hits", pa.list_(pa.string())),
        ],
    )
    table = pa.Table.from_arrays(
        [
            pa.array([row.query_id for row in materialized], type=pa.string()),
            pa.array([row.channel for row in materialized], type=pa.string()),
            pa.array([int(row.rank) for row in materialized], type=pa.int32()),
            pa.array([int(row.chunk_id) for row in materialized], type=pa.int64()),
            pa.array([float(row.score) for row in materialized], type=pa.float32()),
            reason_struct,
        ],
        names=[
            "query_id",
            "channel",
            "rank",
            "chunk_id",
            "score",
            "reason",
        ],
    )
    pq.write_table(table, out_path, compression="zstd", use_dictionary=True)
    return len(materialized)


__all__ = ["Channel", "SearchPoolRow", "write_pool"]
