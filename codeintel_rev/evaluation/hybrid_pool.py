"""Feature-normalized hybrid pooling utilities."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter

_SOURCE_ALIAS = {
    "semantic": "faiss",
    "faiss": "faiss",
    "bm25": "bm25",
    "splade": "splade",
    "warp": "xtr",
    "xtr": "xtr",
}


@dataclass(slots=True, frozen=True)
class Hit:
    """Individual retrieval hit provided to the hybrid pool."""

    doc_id: str
    score: float
    source: str
    meta: Mapping[str, object]


@dataclass(slots=True, frozen=True)
class PooledHit:
    """Result after pooling with per-source component scores."""

    doc_id: str
    blended_score: float
    components: Mapping[str, float]
    meta: Mapping[str, object]


def _minmax_norm(scores: Sequence[float]) -> list[float]:
    if not scores:
        return []
    lo = min(scores)
    hi = max(scores)
    if hi <= lo:
        return [1.0 for _ in scores]
    span = hi - lo
    return [(val - lo) / span for val in scores]


def _softmax_norm(scores: Sequence[float]) -> list[float]:
    if not scores:
        return []
    max_score = max(scores)
    exps = [math.exp(s - max_score) for s in scores]
    denom = sum(exps) or 1.0
    return [val / denom for val in exps]


class HybridPoolEvaluator:
    """Blend multi-channel hits with configurable normalization and weights."""

    def __init__(
        self,
        weights: Mapping[str, float],
        *,
        norm: str = "minmax",
        sim_threshold: float = 0.0,
    ) -> None:
        self._weights = {k: max(0.0, float(v)) for k, v in weights.items()}
        self._norm_fn = _softmax_norm if norm == "softmax" else _minmax_norm
        self._sim_threshold = sim_threshold

    def pool(self, hits: Iterable[Hit], k: int) -> list[PooledHit]:
        """Pool hits across channels using feature normalization.

        Extended Summary
        ----------------
        This method performs hybrid search result fusion by normalizing scores
        across retrieval channels (BM25, SPLADE, FAISS) and blending them using
        configured weights. It groups hits by document ID, normalizes scores
        within each channel (using softmax or min-max normalization), applies
        channel weights, and ranks documents by blended scores. Used by the
        hybrid search engine to combine results from multiple retrieval methods.

        Parameters
        ----------
        hits : Iterable[Hit]
            Hits from multiple retrieval channels (BM25, SPLADE, FAISS). Each hit
            contains source channel, document ID, score, and metadata.
        k : int
            Number of top-ranked documents to return after pooling. Documents
            are ranked by blended scores (weighted sum of normalized channel scores).

        Returns
        -------
        list[PooledHit]
            Ranked hits with blended scores and per-channel contributions. Each
            PooledHit contains the document ID, blended score, and normalized
            scores per channel. Results are sorted by blended score (descending).

        Notes
        -----
        This method implements hybrid search fusion with configurable normalization
        (softmax or min-max) and channel weights. Documents appearing in multiple
        channels have their scores blended; documents appearing in only one channel
        still receive weighted scores. Time complexity: O(n * m) where n is the
        number of hits and m is the number of channels.
        """
        start = perf_counter()
        by_source: dict[str, list[Hit]] = {}
        meta_by_doc: dict[str, dict[str, object]] = {}
        for hit in hits:
            by_source.setdefault(hit.source, []).append(hit)
            doc_meta = meta_by_doc.setdefault(hit.doc_id, {})
            doc_meta[hit.source] = hit.meta

        normalized: dict[str, dict[str, float]] = {}
        for source, group in by_source.items():
            normed = self._norm_fn([item.score for item in group])
            for idx, item in enumerate(group):
                normalized.setdefault(item.doc_id, {})[source] = normed[idx]

        weight_total = sum(self._weights.values()) or 1.0
        blended: list[PooledHit] = []
        for doc_id, components in normalized.items():
            blended_score = 0.0
            for source, value in components.items():
                blended_score += (self._weights.get(source, 0.0) / weight_total) * value
            blended.append(
                PooledHit(
                    doc_id=doc_id,
                    blended_score=blended_score,
                    components=components,
                    meta=meta_by_doc.get(doc_id, {}),
                )
            )

        blended.sort(key=lambda hit: hit.blended_score, reverse=True)
        top_hits = blended[:k]
        return top_hits


__all__ = ["Hit", "HybridPoolEvaluator", "PooledHit"]
