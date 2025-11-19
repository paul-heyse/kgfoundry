"""Stage-0 hybrid retrieval helpers shared across MCP adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from codeintel_rev.io.hybrid_search import HybridSearchEngine, HybridSearchOptions
from codeintel_rev.retrieval.types import HybridSearchResult


@dataclass(frozen=True, slots=True)
class Stage0Options:
    """Optional knobs passed to the hybrid search engine."""

    weights: Mapping[str, float] | None = None
    per_channel_k: int | None = None
    fusion_k: int | None = None
    rrf_base: int | None = None


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

    Parameters
    ----------
    engine : HybridSearchEngine
        Hybrid search engine instance to use for Stage-0 retrieval.
    query : str
        Query text to search for.
    semantic_hits : Sequence[tuple[int, float]] | None, optional
        Optional pre-computed semantic search hits to include in fusion.
        If None, semantic search is performed as part of Stage-0.
    limit : int
        Maximum number of results to return. Clamped to at least 1.
    options : Stage0Options | None, optional
        Optional configuration for fusion weights, per-channel k values,
        fusion k, and RRF base. If None, uses default options.

    Returns
    -------
    Stage0Result
        Normalized identifiers, scores, warnings, and method metadata.
    """
    opts = options or Stage0Options()
    hybrid_options = HybridSearchOptions()
    if opts.weights is not None:
        hybrid_options = replace(hybrid_options, weights=opts.weights)
    if opts.per_channel_k is not None:
        hybrid_options = replace(hybrid_options, per_channel_k=opts.per_channel_k)
    if opts.fusion_k is not None:
        hybrid_options = replace(hybrid_options, fusion_k=opts.fusion_k)
    if opts.rrf_base is not None:
        hybrid_options = replace(hybrid_options, rrf_base=opts.rrf_base)
    clamped_limit = max(1, int(limit))
    fusion_k = min(int(hybrid_options.fusion_k), clamped_limit)
    if fusion_k != hybrid_options.fusion_k:
        hybrid_options = replace(hybrid_options, fusion_k=fusion_k)
    per_channel_k = max(int(hybrid_options.per_channel_k), fusion_k)
    if per_channel_k != hybrid_options.per_channel_k:
        hybrid_options = replace(hybrid_options, per_channel_k=per_channel_k)
    fused: HybridSearchResult = engine.search(
        query=query,
        semantic_hits=list(semantic_hits or []),
        limit=clamped_limit,
        options=hybrid_options,
    )
    ids = [int(doc.doc_id) for doc in fused.docs]
    scores = [float(doc.score) for doc in fused.docs]
    warnings = list(fused.warnings or [])
    method = dict(fused.method or {})
    return Stage0Result(ids=ids, scores=scores, warnings=warnings, method=method)


__all__ = ["Stage0Options", "Stage0Result", "run_stage0"]
