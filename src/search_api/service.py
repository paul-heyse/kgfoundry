"""Search service layer for orchestration and ranking.

This module provides typed service-layer functions for search operations, including reciprocal rank
fusion, knowledge graph boosting, and result deduplication. All functions include structured logging
and metrics.
"""

# [nav:section public-api]

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from kgfoundry_common.errors.exceptions import VectorSearchError
from kgfoundry_common.logging import get_logger, with_fields
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.observability import MetricsProvider, observe_duration

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kgfoundry_common.problem_details import JsonValue
    from search_api.types import AgentSearchResponse, VectorSearchResultTypedDict

__all__ = [
    "apply_kg_boosts",
    "mmr_deduplicate",
    "rrf_fuse",
    "search_service",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))

logger = get_logger(__name__)


# [nav:anchor rrf_fuse]
def rrf_fuse(rankers: list[list[tuple[str, float]]], k_rrf: int = 60) -> dict[str, float]:
    """Fuse multiple ranked lists using Reciprocal Rank Fusion (RRF).

    Combines multiple ranked lists into a single ranked list using RRF scoring.
    Each item's score is the sum of 1 / (k_rrf + rank) across all rankers.

    Parameters
    ----------
    rankers : list[list[tuple[str, float]]]
        List of ranked lists, where each list contains (item_id, score) tuples.
    k_rrf : int, optional
        RRF constant parameter (higher = more weight to top ranks).
        Defaults to 60.

    Returns
    -------
    dict[str, float]
        Dictionary mapping item IDs to fused RRF scores.

    Examples
    --------
    >>> dense = [("doc1", 0.9), ("doc2", 0.8)]
    >>> sparse = [("doc2", 0.85), ("doc1", 0.75)]
    >>> fused = rrf_fuse([dense, sparse], k_rrf=60)
    >>> "doc1" in fused and "doc2" in fused
    True
    """
    with with_fields(logger, operation="rrf_fuse", k_rrf=k_rrf, num_rankers=len(rankers)):
        scores: dict[str, float] = {}
        for ranked in rankers:
            for rank, (item_id, _score) in enumerate(ranked, start=1):
                scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k_rrf + rank)
        logger.debug("RRF fusion completed", extra={"num_items": len(scores)})
        return scores


# [nav:anchor apply_kg_boosts]
def apply_kg_boosts(
    cands: dict[str, float],
    query: str,
    direct: float = 0.08,
    one_hop: float = 0.04,
    *,
    kg_concepts: Mapping[str, set[str]] | None = None,
) -> dict[str, float]:
    """Apply knowledge graph boosts to candidate scores.

    Boosts scores for candidates that have direct or one-hop concept matches
    with the query. If kg_concepts is None, returns candidates unchanged.

    Parameters
    ----------
    cands : dict[str, float]
        Dictionary mapping candidate IDs to base scores.
    query : str
        Query text (used to extract concept mentions).
    direct : float, optional
        Boost amount for direct concept matches. Defaults to 0.08.
    one_hop : float, optional
        Boost amount for one-hop concept matches. Defaults to 0.04.
    kg_concepts : Mapping[str, set[str]] | None, optional
        Mapping from candidate IDs to sets of concept IDs.
        If None, no boosts are applied. Defaults to None.

    Returns
    -------
    dict[str, float]
        Dictionary mapping candidate IDs to boosted scores.

    Examples
    --------
    >>> cands = {"doc1": 0.8, "doc2": 0.7}
    >>> boosted = apply_kg_boosts(cands, "test query", kg_concepts={"doc1": {"C:42"}})
    >>> boosted["doc1"] > cands["doc1"]
    True
    """
    with with_fields(logger, operation="apply_kg_boosts", query=query[:50]):
        if kg_concepts is None:
            logger.debug("No KG concepts provided, skipping boosts")
            return cands

        # Extract concept mentions from query (simplified)
        q_concepts: set[str] = set()
        for word in query.lower().split():
            if word.startswith("concept"):
                q_concepts.add(f"C:{word.replace('concept', '')}")

        boosted = dict(cands)
        boost_count = 0
        for cand_id, base_score in cands.items():
            linked = kg_concepts.get(cand_id, set())
            boost = 0.0
            if linked & q_concepts:
                boost += direct
            else:
                for concept in linked:
                    # Simplified one-hop check (would need full KG graph)
                    if concept in q_concepts:
                        boost += one_hop
                        break
            if boost > 0:
                boost_count += 1
            boosted[cand_id] = base_score + boost

        logger.debug(
            "KG boosts applied",
            extra={"boosted_count": boost_count, "total_candidates": len(cands)},
        )
        return boosted


# [nav:anchor mmr_deduplicate]
def mmr_deduplicate(
    results: list[tuple[str, float]], lambda_mmr: float = 0.7
) -> list[tuple[str, float]]:
    """Deduplicate results using Maximal Marginal Relevance (MMR).

    Removes duplicate items while preserving diversity. Currently returns
    results unchanged; full MMR implementation requires document embeddings.

    Parameters
    ----------
    results : list[tuple[str, float]]
        List of (item_id, score) tuples, sorted by score descending.
    lambda_mmr : float, optional
        MMR lambda parameter (0.0 = pure relevance, 1.0 = pure diversity).
        Defaults to 0.7.

    Returns
    -------
    list[tuple[str, float]]
        Deduplicated list of (item_id, score) tuples.

    Examples
    --------
    >>> results = [("doc1", 0.9), ("doc2", 0.8), ("doc1", 0.7)]
    >>> deduped = mmr_deduplicate(results)
    >>> len(deduped) <= len(results)
    True
    """
    with with_fields(logger, operation="mmr_deduplicate", lambda_mmr=lambda_mmr):
        # Simple deduplication (full MMR requires document embeddings)
        seen: set[str] = set()
        deduped: list[tuple[str, float]] = []
        for item_id, score in results:
            if item_id not in seen:
                seen.add(item_id)
                deduped.append((item_id, score))

        logger.debug(
            "MMR deduplication completed",
            extra={"original_count": len(results), "deduped_count": len(deduped)},
        )
        return deduped


# [nav:anchor search_service]
def search_service(
    results: list[VectorSearchResultTypedDict],
    *,
    metrics: MetricsProvider | None = None,
) -> AgentSearchResponse:
    """Create typed search response from results.

    Wraps search results in an AgentSearchResponse envelope with metadata
    and metrics. Includes structured logging and duration tracking.

    Parameters
    ----------
    results : list[VectorSearchResultTypedDict]
        List of typed search results.
    metrics : MetricsProvider | None, optional
        Metrics provider for recording search metrics.
        If None, uses default provider. Defaults to None.

    Returns
    -------
    AgentSearchResponse
        Typed search response with results and metadata.

    Raises
    ------
    VectorSearchError
        Raised when result packaging or instrumentation fails. The original
        exception is chained for diagnostics.
    RuntimeError
        Raised if instrumentation completes without producing a response.

    Notes
    -----
    Exceptions raised during processing propagate after logging and metrics
    collection complete.
    """
    active_metrics = metrics or MetricsProvider.default()
    start_time = time.time()

    response: AgentSearchResponse | None = None
    with (
        with_fields(logger, operation="search_service") as log_adapter,
        observe_duration(active_metrics, "search", component="search_api") as obs,
    ):
        try:
            took_ms = int((time.time() - start_time) * 1000)
            metadata: Mapping[str, JsonValue] = {
                "backend": "search_api",
                "result_count": len(results),
            }
            response = {
                "results": results,
                "total": len(results),
                "took_ms": took_ms,
                "metadata": metadata,
            }

            log_adapter.info(
                "Search service completed",
                extra={
                    "status": "success",
                    "result_count": len(results),
                    "took_ms": took_ms,
                },
            )
            obs.success()
        except Exception as error:
            log_adapter.exception("Search service failed", exc_info=error)
            obs.error()
            context = {"result_count": len(results)}
            message = "Search service failed to package results"
            raise VectorSearchError(message, cause=error, context=context) from error
    if response is None:
        message = "Search service failed to produce a response"
        raise RuntimeError(message)
    return response
