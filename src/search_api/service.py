"""Search service layer for orchestration and ranking.

This module provides typed service-layer functions for search operations, including reciprocal rank
fusion, knowledge graph boosting, and result deduplication.
"""

# [nav:section public-api]

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from kgfoundry_common.errors.exceptions import VectorSearchError
from kgfoundry_common.navmap_loader import load_nav_metadata

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
    scores: dict[str, float] = {}
    for ranked in rankers:
        for rank, (item_id, _score) in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k_rrf + rank)
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
    if kg_concepts is None:
        return cands

    q_concepts: set[str] = set()
    for word in query.lower().split():
        if word.startswith("concept"):
            q_concepts.add(f"C:{word.replace('concept', '')}")

    boosted = dict(cands)
    for cand_id, base_score in cands.items():
        linked = kg_concepts.get(cand_id, set())
        boost = 0.0
        if linked & q_concepts:
            boost += direct
        else:
            for concept in linked:
                if concept in q_concepts:
                    boost += one_hop
                    break
        boosted[cand_id] = base_score + boost

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
    seen: set[str] = set()
    deduped: list[tuple[str, float]] = []
    for item_id, score in results:
        if item_id not in seen:
            seen.add(item_id)
            deduped.append((item_id, score))
    return deduped


# [nav:anchor search_service]
def search_service(results: list[VectorSearchResultTypedDict]) -> AgentSearchResponse:
    """Create typed search response from results.

    Wraps search results in an AgentSearchResponse envelope with metadata and duration fields.

    Parameters
    ----------
    results : list[VectorSearchResultTypedDict]
        List of typed search results.

    Returns
    -------
    AgentSearchResponse
        Typed search response with results and metadata.

    Raises
    ------
    VectorSearchError
        Raised when result packaging fails. The original exception is chained for diagnostics.
    """
    start_time = time.time()

    try:
        took_ms = int((time.time() - start_time) * 1000)
        metadata: Mapping[str, JsonValue] = {
            "backend": "search_api",
            "result_count": len(results),
        }
        response: AgentSearchResponse = {
            "results": results,
            "total": len(results),
            "took_ms": took_ms,
            "metadata": metadata,
        }
    except Exception as error:  # pragma: no cover - defensive guard
        context = {"result_count": len(results)}
        message = "Search service failed to package results"
        raise VectorSearchError(message, cause=error, context=context) from error
    return response
