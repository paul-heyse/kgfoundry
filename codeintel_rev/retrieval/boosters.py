"""Score boosters applied after fusion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Callable
import time

from codeintel_rev.retrieval.types import HybridResultDoc

try:
    from codeintel_rev.io.duckdb_manager import DuckDBManager
except Exception:  # pragma: no cover - optional dependency
    DuckDBManager = None  # type: ignore[assignment]

__all__ = ["RecencyConfig", "apply_recency_boost"]


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


def _fetch_commit_ts_duckdb(
    manager: "DuckDBManager",
    ids: Iterable[str],
    cfg: RecencyConfig,
) -> Mapping[str, float]:
    if manager is None:
        return {}
    id_list = list(ids)
    if not id_list:
        return {}
    try:
        with manager.connection() as conn:
            qmarks = ",".join(["?"] * len(id_list))
            query = (
                f"SELECT {cfg.chunk_id_column}, {cfg.commit_ts_column} "
                f"FROM {cfg.table} "
                f"WHERE {cfg.chunk_id_column} IN ({qmarks})"
            )
            rows = conn.execute(query, id_list).fetchall()
    except Exception:
        return {}
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
    duckdb_manager: "DuckDBManager | None" = None,
    commit_ts_lookup: Callable[[Iterable[str]], Mapping[str, float]] | None = None,
) -> tuple[list[HybridResultDoc], int]:
    """Return a new doc list with an exponential recency boost applied."""

    if not cfg.enabled or not docs:
        return docs, 0

    lookup = commit_ts_lookup
    if lookup is None:
        if duckdb_manager is None or DuckDBManager is None:
            return docs, 0

        def _lookup(ids: Iterable[str]) -> Mapping[str, float]:
            return _fetch_commit_ts_duckdb(duckdb_manager, ids, cfg)

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

