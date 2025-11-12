"""Score boosters applied after fusion."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from codeintel_rev.retrieval.types import HybridResultDoc

try:
    import duckdb
except ImportError:  # pragma: no cover - optional dependency
    duckdb = None

if TYPE_CHECKING:
    from codeintel_rev.io.duckdb_manager import DuckDBManager as DuckDBManagerType
else:  # pragma: no cover - typing only
    DuckDBManagerType = Any

try:
    from codeintel_rev.io.duckdb_manager import DuckDBManager
except ImportError:  # pragma: no cover - optional dependency
    DuckDBManager = None

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection as DuckConnection
else:  # pragma: no cover - typing only
    DuckConnection = Any

__all__ = ["RecencyConfig", "apply_recency_boost"]

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class RecencyConfig:
    """Configuration parameters controlling recency boosts."""

    enabled: bool = False
    half_life_days: float = 30.0
    max_boost: float = 0.15
    table: str = "chunks"
    chunk_id_column: str = "chunk_id"
    commit_ts_column: str = "commit_ts"


def _now() -> float:
    return time.time()


def _exp_decay(age_days: float, half_life_days: float) -> float:
    if half_life_days <= 0:
        return 0.0
    return 0.5 ** (age_days / half_life_days)


def _safe_identifier(value: str) -> str:
    if not _IDENTIFIER_RE.match(value):
        msg = f"Invalid identifier: {value}"
        raise ValueError(msg)
    return value


def _normalize_ids(source: Iterable[str]) -> list[int]:
    normalized: list[int] = []
    for identifier in source:
        try:
            normalized.append(int(identifier))
        except (TypeError, ValueError):
            continue
    return normalized


def _create_recency_view(
    conn: DuckConnection,
    table_name: str,
    chunk_col: str,
    commit_col: str,
) -> None:
    relation = conn.table(table_name).project(
        f"{chunk_col} AS recency_chunk_id, {commit_col} AS recency_commit_ts"
    )
    relation.create_view("recency_source", replace=True)


def _populate_id_table(conn: DuckConnection, ids: Sequence[int]) -> None:
    conn.execute("CREATE TEMPORARY TABLE recency_ids(id BIGINT)")
    conn.executemany("INSERT INTO recency_ids VALUES (?)", [(identifier,) for identifier in ids])


def _fetch_commit_ts_duckdb(
    manager: DuckDBManagerType,
    ids: Iterable[str],
    cfg: RecencyConfig,
) -> Mapping[str, float]:
    if manager is None:
        return {}
    id_list = list(ids)
    if not id_list:
        return {}
    chunk_col = _safe_identifier(cfg.chunk_id_column)
    commit_col = _safe_identifier(cfg.commit_ts_column)
    table_name = _safe_identifier(cfg.table)
    rows: list[tuple[Any, float | None]] = []
    try:
        normalized_ids = _normalize_ids(id_list)
        if not normalized_ids:
            return {}
        with manager.connection() as conn:
            _create_recency_view(conn, table_name, chunk_col, commit_col)
            try:
                _populate_id_table(conn, normalized_ids)
                rows = conn.execute(
                    "SELECT recency_chunk_id, recency_commit_ts "
                    "FROM recency_source "
                    "WHERE recency_chunk_id IN (SELECT id FROM recency_ids)"
                ).fetchall()
            finally:
                conn.execute("DROP TABLE IF EXISTS recency_ids")
                conn.execute("DROP VIEW IF EXISTS recency_source")
    except (RuntimeError, ValueError):
        return {}
    except Exception as exc:  # pragma: no cover - defensive cascade
        if duckdb is not None and isinstance(exc, duckdb.Error):
            return {}
        raise
    result: dict[str, float] = {}
    for chunk_id, commit_ts in rows:
        if commit_ts is None:
            continue
        try:
            result[str(chunk_id)] = float(commit_ts)
        except (TypeError, ValueError):
            continue
    return result


def apply_recency_boost(
    docs: list[HybridResultDoc],
    cfg: RecencyConfig,
    *,
    duckdb_manager: DuckDBManagerType | None = None,
    commit_ts_lookup: Callable[[Iterable[str]], Mapping[str, float]] | None = None,
) -> tuple[list[HybridResultDoc], int]:
    """Return a new doc list with an exponential recency boost applied.

    Parameters
    ----------
    docs : list[HybridResultDoc]
        Ranked documents to boost.
    cfg : RecencyConfig
        Recency boosting configuration.
    duckdb_manager : DuckDBManagerType | None, optional
        DuckDB manager used to look up commit timestamps when ``commit_ts_lookup``
        is not provided. Must be an instance of ``DuckDBManager`` when DuckDB
        is available, or None when DuckDB is not installed.
    commit_ts_lookup : Callable[[Iterable[str]], Mapping[str, float]] | None, optional
        Custom lookup function that maps chunk IDs to commit timestamps.

    Returns
    -------
    tuple[list[HybridResultDoc], int]
        Boosted documents (preserving order) and the number of documents whose
        scores changed due to the recency multiplier.
    """
    if not cfg.enabled or not docs:
        return docs, 0

    lookup = commit_ts_lookup
    if lookup is None:
        if duckdb_manager is None or DuckDBManager is None:
            return docs, 0
        assert duckdb_manager is not None
        assert DuckDBManager is not None
        concrete_manager = duckdb_manager

        def _lookup(ids: Iterable[str]) -> Mapping[str, float]:
            return _fetch_commit_ts_duckdb(concrete_manager, ids, cfg)

        lookup = _lookup

    doc_ids = [doc.doc_id for doc in docs]
    ts_map = lookup(doc_ids)
    if not ts_map:
        return docs, 0

    now = _now()
    boosted: list[HybridResultDoc] = []
    boost_count = 0
    for doc in docs:
        score = doc.score
        ts = ts_map.get(doc.doc_id)
        if ts is None:
            boosted.append(doc)
            continue
        age_days = max(0.0, (now - ts) / 86400.0)
        boost = cfg.max_boost * _exp_decay(age_days, cfg.half_life_days)
        new_score = score * (1.0 + boost)
        if new_score != score:
            boost_count += 1
        boosted.append(HybridResultDoc(doc_id=doc.doc_id, score=new_score))
    return boosted, boost_count
