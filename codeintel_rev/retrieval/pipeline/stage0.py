"""Stage-0 hybrid retrieval helpers shared across MCP adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from codeintel_rev.io.hybrid_search import HybridSearchEngine, HybridSearchOptions
from codeintel_rev.retrieval.types import HybridSearchResult


@dataclass(frozen=True, slots=True)
class Stage0Options:
    """Optional knobs passed to the hybrid search engine."""

    weights: Mapping[str, float] | None = None


@dataclass(frozen=True, slots=True)
class Stage0Result:
    """Normalized Stage-0 fusion outputs."""

    ids: list[int]
    scores: list[float]
    warnings: list[str]
    method: dict[str, object]


def run_stage0(
    engine: HybridSearchEngine,
    *,
    query: str,
    semantic_hits: Sequence[tuple[int, float]] | None,
    limit: int,
    options: Stage0Options | None = None,
) -> Stage0Result:
    """Execute Stage-0 fusion via the provided hybrid search engine.

    Returns
    -------
    Stage0Result
        Normalized identifiers, scores, warnings, and method metadata.
    """
    opts = options or Stage0Options()
    hybrid_options = HybridSearchOptions(weights=opts.weights)  # type: ignore[arg-type]
    fused: HybridSearchResult = engine.search(
        query=query,
        semantic_hits=list(semantic_hits or []),
        limit=int(limit),
        options=hybrid_options,
    )
    ids = [int(doc.doc_id) for doc in fused.docs]
    scores = [float(doc.score) for doc in fused.docs]
    warnings = list(fused.warnings or [])
    method = dict(fused.method or {})
    return Stage0Result(ids=ids, scores=scores, warnings=warnings, method=method)


__all__ = ["Stage0Options", "Stage0Result", "run_stage0"]
