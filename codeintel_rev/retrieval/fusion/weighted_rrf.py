"""Weighted reciprocal rank fusion utilities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from codeintel_rev.retrieval.types import HybridResultDoc, SearchHit


def fuse_weighted_rrf(
    runs: Mapping[str, Sequence[SearchHit]],
    *,
    weights: Mapping[str, float],
    k: int,
    limit: int,
) -> tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]]]:
    """Apply weighted RRF across runs and return fused docs plus contributions.

    Extended Summary
    ----------------
    This function performs weighted Reciprocal Rank Fusion (RRF) across multiple
    retrieval channels, combining ranked lists with channel-specific weights. It computes
    fused scores using the RRF formula (weight * 1/(k + rank)) and tracks contribution
    metadata showing which channels contributed to each document's final score. This is
    used in hybrid search pipelines to combine results from different retrieval methods
    (e.g., dense vectors, sparse BM25, semantic search) into a single ranked list.

    Parameters
    ----------
    runs : Mapping[str, Sequence[SearchHit]]
        Dictionary mapping channel names to their ranked hit lists. Each channel
        provides a sequence of SearchHit objects with doc_id, rank, and score.
        Empty sequences are skipped.
    weights : Mapping[str, float]
        Dictionary mapping channel names to their fusion weights. Channels not
        present in weights default to weight 1.0. Channels with weight 0.0 are
        excluded from fusion.
    k : int
        RRF constant used in the formula 1/(k + rank). Larger k values reduce the
        impact of rank differences. Typical values range from 20 to 100.
    limit : int
        Maximum number of fused documents to return. Must be positive. Results are
        sorted by fused score in descending order and truncated to this limit.

    Returns
    -------
    tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]]]
        Two-element tuple containing:
        - List of HybridResultDoc objects with fused scores, sorted descending
        - Dictionary mapping doc_id to list of (channel, rank, score) contributions

    Raises
    ------
    ValueError
        If limit is not positive. This ensures the function returns at least one
        result when limit > 0.

    Notes
    -----
    Time complexity O(C * N) where C is channel count and N is average hits per channel.
    Space complexity O(N) for fused scores and contributions. The function performs
    no I/O and has no side effects. Thread-safe as it operates on input data only.
    RRF formula: fused_score = sum(weight[channel] * 1/(k + rank[channel])) for all channels.
    """
    if limit <= 0:
        msg = "limit must be positive for weighted RRF fusion."
        raise ValueError(msg)

    fused_scores: dict[str, float] = {}
    contributions: dict[str, list[tuple[str, int, float]]] = {}

    for channel, hits in runs.items():
        if not hits:
            continue
        weight = float(weights.get(channel, 1.0))
        if weight == 0.0:
            continue
        for hit in hits:
            rr = weight * (1.0 / (k + hit.rank + 1))
            fused_scores[hit.doc_id] = fused_scores.get(hit.doc_id, 0.0) + rr
            contributions.setdefault(hit.doc_id, []).append((channel, hit.rank + 1, hit.score))

    ordered = sorted(fused_scores.items(), key=lambda item: item[1], reverse=True)
    sliced = ordered[:limit]
    docs = [HybridResultDoc(doc_id=doc_id, score=score) for doc_id, score in sliced]
    filtered = {doc_id: contributions.get(doc_id, []) for doc_id, _ in sliced}
    return docs, filtered


__all__ = ["fuse_weighted_rrf"]
