"""Hybrid retrieval with RRF fusion.

Fuses results from BM25, SPLADE, and FAISS using Reciprocal Rank Fusion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from codeintel_rev.retrieval.types import SearchHit

if TYPE_CHECKING:
    from collections.abc import Sequence


def reciprocal_rank_fusion(
    result_lists: Sequence[Sequence[SearchHit]],
    k: int = 60,
    top_k: int = 50,
) -> list[tuple[str, float]]:
    """Fuse multiple ranked lists using RRF.

    Parameters
    ----------
    result_lists : Sequence[Sequence[SearchHit]]
        Lists of search hits from different retrieval systems.
    k : int
        RRF K parameter (higher = more weight to lower ranks).
    top_k : int
        Number of results to return.

    Returns
    -------
    list[tuple[str, float]]
        Fused results as (doc_id, rrf_score) sorted by score descending.

    Notes
    -----
    RRF score for document d is:
        RRF(d) = sum over all systems S of: 1 / (k + rank_S(d))

    where rank_S(d) is the rank of d in system S (1-indexed).
    """
    # Aggregate scores
    scores: dict[str, float] = {}

    for result_list in result_lists:
        for hit in result_list:
            # Rank is 1-indexed for RRF formula
            rank_one_indexed = hit.rank + 1
            rrf_score = 1.0 / (k + rank_one_indexed)

            if hit.doc_id in scores:
                scores[hit.doc_id] += rrf_score
            else:
                scores[hit.doc_id] = rrf_score

    # Sort by score descending
    sorted_results = sorted(scores.items(), key=lambda x: -x[1])

    return sorted_results[:top_k]


def create_hit_list(
    doc_ids: Sequence[str],
    scores: Sequence[float],
    source: str,
) -> list[SearchHit]:
    """Create SearchHit list from retrieval results.

    Parameters
    ----------
    doc_ids : Sequence[str]
        Document IDs in rank order.
    scores : Sequence[float]
        Scores for each document.
    source : str
        Source identifier (e.g., "bm25", "faiss").

    Returns
    -------
    list[SearchHit]
        Search hits with ranks.
    """
    return [
        SearchHit(doc_id=doc_id, score=score, rank=rank, source=source)
        for rank, (doc_id, score) in enumerate(zip(doc_ids, scores, strict=True))
    ]


__all__ = [
    "SearchHit",
    "create_hit_list",
    "reciprocal_rank_fusion",
]
