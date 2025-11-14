"""Lightweight Parquet writer for evaluator pools."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Literal, Protocol, cast, runtime_checkable

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


@runtime_checkable
class _SupportsToList(Protocol):
    """Protocol describing array-like objects exposing ``tolist``."""

    def tolist(self) -> object:
        """Convert the array-like object to a Python list.

        This method is part of the Protocol interface for array-like objects
        that can be converted to lists. Implementations should return a nested
        list structure representing the array's contents.

        Returns
        -------
        object
            A Python list (or nested list structure) representing the array's
            contents. The exact structure depends on the array's dimensionality
            and element types.
        """
        ...


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
            pa.array([], type=pa.string()),
            pa.array([], type=pa.list_(pa.string())),
            pa.array([], type=pa.string()),
        ],
        names=[
            "query_id",
            "channel",
            "rank",
            "id",
            "score",
            "uri",
            "symbol_hits",
            "meta",
        ],
    )


def _normalize_meta(meta: Mapping[str, object]) -> dict[str, object]:
    """Return a JSON-serialisable copy of ``meta``.

    Parameters
    ----------
    meta : Mapping[str, object]
        Metadata dictionary to normalize. Values are coerced to JSON-serializable
        types (str, int, float, bool, None, dict, list). Non-serializable types
        are converted to strings.

    Returns
    -------
    dict[str, object]
        Normalized metadata ready for JSON serialization. All values are
        JSON-serializable types.
    """

    def _coerce(value: object) -> object:
        if value is None:
            result: object = None
        elif isinstance(value, (str, int, float, bool)):
            result = value
        elif isinstance(value, Mapping):
            result = {str(key): _coerce(val) for key, val in value.items()}
        elif isinstance(value, (list, tuple, set)):
            result = [_coerce(item) for item in value]
        elif isinstance(value, _SupportsToList):
            try:
                result = value.tolist()
            except (ValueError, TypeError, RuntimeError):  # pragma: no cover - best effort
                result = str(value)
        else:
            result = str(value)
        return result

    return {str(key): _coerce(val) for key, val in meta.items()}


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

    normalized_meta = [
        _normalize_meta(row.meta) if row.meta else {}
        for row in materialized
    ]
    meta_payloads = [json.dumps(meta, sort_keys=True) if meta else "{}" for meta in normalized_meta]
    uris: list[str] = []
    symbol_hits: list[list[str]] = []
    for meta in normalized_meta:
        uri = str(meta.get("uri", ""))
        hits = meta.get("symbol_hits", [])
        if isinstance(hits, list):
            coerced_hits = [str(item) for item in hits]
        else:
            coerced_hits = [str(hits)] if hits not in (None, "") else []
        uris.append(uri)
        symbol_hits.append(coerced_hits)
    table = pa.Table.from_arrays(
        [
            pa.array([row.query_id for row in materialized], type=pa.string()),
            pa.array([row.channel for row in materialized], type=pa.string()),
            pa.array([int(row.rank) for row in materialized], type=pa.int32()),
            pa.array([int(row.id) for row in materialized], type=pa.int64()),
            pa.array([float(row.score) for row in materialized], type=pa.float32()),
            pa.array(uris, type=pa.string()),
            pa.array(symbol_hits, type=pa.list_(pa.string())),
            pa.array(meta_payloads, type=pa.string()),
        ],
        names=[
            "query_id",
            "channel",
            "rank",
            "id",
            "score",
            "uri",
            "symbol_hits",
            "meta",
        ],
    )
    pq.write_table(table, out_path, compression="zstd", use_dictionary=True)
    return len(materialized)


__all__ = ["Channel", "SearchPoolRow", "write_pool"]
