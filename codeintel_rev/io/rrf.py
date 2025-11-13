"""Reciprocal Rank Fusion utilities (legacy compatibility wrappers)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from codeintel_rev.retrieval.fusion import fuse_weighted_rrf
from codeintel_rev.retrieval.types import SearchHit


def weighted_rrf(
    channels: Mapping[str, Sequence[tuple[int, float]]],
    *,
    weights: Mapping[str, float],
    k: int,
    top_k: int,
    normalize: Literal["none", "minmax", "z"] = "none",
) -> tuple[list[int], dict[int, list[tuple[str, int, float]]], dict[int, float]]:
    """Apply weighted Reciprocal Rank Fusion to channel hits.

    Extended Summary
    ----------------
    This function performs weighted Reciprocal Rank Fusion (RRF) across multiple
    retrieval channels, combining ranked lists from different search methods (e.g.,
    CodeRank, WARP, BM25) into a single unified ranking. It serves as a legacy
    compatibility wrapper that converts integer-based channel hits into the internal
    SearchHit format, optionally normalizes scores per-channel (minmax or z-score),
    delegates to the core fusion engine, and converts results back to integer document
    IDs. The function is used by the hybrid search pipeline to merge semantic and
    sparse retrieval signals with configurable per-channel weights and normalization.

    Parameters
    ----------
    channels : Mapping[str, Sequence[tuple[int, float]]]
        Per-channel ranked lists mapping channel names to sequences of (doc_id, score)
        tuples. Each channel represents a distinct retrieval method (e.g., "coderank",
        "warp", "bm25"). Document IDs must be convertible to integers.
    weights : Mapping[str, float]
        Per-channel fusion weights. Channels not present in this mapping default to
        weight 1.0. Zero-weighted channels are excluded from fusion. Weights control
        the relative influence of each channel in the final ranking.
    k : int
        RRF damping constant. Controls how quickly reciprocal rank contributions decay
        with position. Higher values reduce the impact of lower-ranked items. Typical
        values range from 20 to 100.
    top_k : int
        Maximum number of documents to return in the fused ranking. Must be positive.
        The function returns the top_k highest-scoring documents after fusion.
    normalize : Literal["none", "minmax", "z"], optional
        Optional per-channel score normalization applied before fusion. Use "minmax"
        to scale raw scores to [0, 1] or "z" for z-score normalization. Defaults to
        "none", preserving incoming scores.

    Returns
    -------
    tuple[list[int], dict[int, list[tuple[str, int, float]]], dict[int, float]]
        A 3-tuple containing:
        - Ranked list of document IDs (integers) sorted by fused RRF score (descending).
        - Per-document contribution map: doc_id -> list of (channel, rank, score) tuples
          showing which channels contributed to each document's final score.
        - Per-document fused score map: doc_id -> final fused RRF score.

    Raises
    ------
    ValueError
        If a document ID cannot be converted to an integer, or if top_k is not positive.

    Notes
    -----
    Time complexity O(n * m) where n is total hits across channels and m is the number
    of channels. Space complexity O(n) for the fused score map and contributions.
    The function performs no I/O and has no side effects. Thread-safe if input mappings
    are immutable or accessed read-only.

    Examples
    --------
    >>> channels = {"coderank": [(1, 0.9), (2, 0.8)], "warp": [(2, 0.85), (1, 0.75)]}
    >>> weights = {"coderank": 1.0, "warp": 0.5}
    >>> doc_ids, contribs, scores = weighted_rrf(channels, weights=weights, k=60, top_k=2)
    >>> len(doc_ids) <= 2
    True
    >>> 1 in doc_ids and 2 in doc_ids
    True
    """
    if top_k <= 0:
        msg = f"top_k must be positive, got {top_k}"
        raise ValueError(msg)
    converted = {
        channel: [
            SearchHit(
                doc_id=str(doc_id),
                rank=rank,
                score=float(score),
                source=channel,
                explain={"normalized_score": float(score)},
            )
            for rank, (doc_id, score) in enumerate(_normalize_channel_hits(hits, normalize))
        ]
        for channel, hits in channels.items()
    }
    docs, contributions = fuse_weighted_rrf(
        converted,
        weights=weights,
        k=k,
        limit=top_k,
    )
    fused_ids = [_to_int(doc.doc_id) for doc in docs]
    fused_contrib = {doc_id: contributions.get(str(doc_id), []) for doc_id in fused_ids}
    fused_scores = {doc_id: docs[idx].score for idx, doc_id in enumerate(fused_ids)}
    return fused_ids, fused_contrib, fused_scores


def _normalize_channel_hits(
    hits: Sequence[tuple[int, float]],
    mode: Literal["none", "minmax", "z"],
) -> list[tuple[int, float]]:
    """Normalize channel hit scores using the specified mode.

    Parameters
    ----------
    hits : Sequence[tuple[int, float]]
        Original hits as (doc_id, score) tuples.
    mode : Literal["none", "minmax", "z"]
        Normalization mode: "none" returns hits unchanged, "minmax" scales to [0, 1],
        "z" applies z-score normalization.

    Returns
    -------
    list[tuple[int, float]]
        Normalized hits with same doc_ids but transformed scores.
    """
    if mode == "none":
        return [(int(doc_id), float(score)) for doc_id, score in hits]
    values = [float(score) for _doc_id, score in hits]
    if not values:
        return []
    if mode == "minmax":
        min_value = min(values)
        max_value = max(values)
        if max_value == min_value:
            normalized = [0.0 for _ in values]
        else:
            span = max_value - min_value
            normalized = [(value - min_value) / span for value in values]
    else:  # mode == "z"
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        if variance == 0.0:
            normalized = [0.0 for _ in values]
        else:
            std = variance**0.5
            normalized = [(value - mean) / std for value in values]
    return [
        (int(doc_id), float(value))
        for (doc_id, _score), value in zip(hits, normalized, strict=False)
    ]


def _to_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive path
        msg = f"Channel doc_id should be convertible to int, got {value!r}"
        raise ValueError(msg) from exc


__all__ = ["weighted_rrf"]
