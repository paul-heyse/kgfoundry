"""Weighted reciprocal rank fusion utilities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from codeintel_rev.retrieval.types import ChannelHit, HybridResultDoc


def fuse_weighted_rrf(
    runs: Mapping[str, Sequence[ChannelHit]],
    *,
    weights: Mapping[str, float],
    k: int,
    limit: int,
) -> tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]]]:
    """Apply weighted RRF across ``runs`` and return fused docs plus contributions.

    Returns
    -------
    tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]]]
        Final documents with fused scores and contribution metadata.

    Raises
    ------
    ValueError
        If ``limit`` is not positive.
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
        for rank, hit in enumerate(hits, start=1):
            rr = weight * (1.0 / (k + rank))
            fused_scores[hit.doc_id] = fused_scores.get(hit.doc_id, 0.0) + rr
            contributions.setdefault(hit.doc_id, []).append((channel, rank, hit.score))

    ordered = sorted(fused_scores.items(), key=lambda item: item[1], reverse=True)
    sliced = ordered[:limit]
    docs = [HybridResultDoc(doc_id=doc_id, score=score) for doc_id, score in sliced]
    filtered = {doc_id: contributions.get(doc_id, []) for doc_id, _ in sliced}
    return docs, filtered


__all__ = ["fuse_weighted_rrf"]
