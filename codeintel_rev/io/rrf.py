"""Reciprocal Rank Fusion utilities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def weighted_rrf(
    channels: Mapping[str, Sequence[tuple[int, float]]],
    *,
    weights: Mapping[str, float],
    k: int,
    top_k: int,
) -> tuple[list[int], dict[int, list[tuple[str, int, float]]], dict[int, float]]:
    """Apply weighted Reciprocal Rank Fusion to channel hits.

    Returns
    -------
    tuple[list[int], dict[int, list[tuple[str, int, float]]], dict[int, float]]
        Tuple containing:
        - Ranked list of document IDs (highest score first)
        - Per-document contribution breakdown by channel
        - Per-document final RRF scores

    Raises
    ------
    ValueError
        If top_k is not positive.
    """
    if top_k <= 0:
        msg = "top_k must be positive for weighted_rrf."
        raise ValueError(msg)
    scores: dict[int, float] = {}
    contributions: dict[int, list[tuple[str, int, float]]] = {}
    for channel, hits in channels.items():
        weight = weights.get(channel, 1.0)
        if weight == 0:
            continue
        for rank, (doc_id, raw_score) in enumerate(hits, start=1):
            rr = weight * (1.0 / (k + rank))
            scores[doc_id] = scores.get(doc_id, 0.0) + rr
            contributions.setdefault(doc_id, []).append(
                (channel, rank, float(raw_score))
            )
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    fused_ids = [doc_id for doc_id, _ in ordered[:top_k]]
    fused_contrib = {doc_id: contributions.get(doc_id, []) for doc_id in fused_ids}
    fused_scores = {doc_id: scores[doc_id] for doc_id in fused_ids}
    return fused_ids, fused_contrib, fused_scores
