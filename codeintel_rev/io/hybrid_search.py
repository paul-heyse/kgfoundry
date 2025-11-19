"""Thin Stage-0 hybrid search coordinator."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from codeintel_rev.io.bm25_engine import BM25Engine
from codeintel_rev.io.splade_engine import SPLADEEngine
from codeintel_rev.retrieval.fusion.api import (
    FusionInput,
    FusionOptions,
    FusionProtocol,
    RRFWeighter,
)
from codeintel_rev.retrieval.types import HybridResultDoc, HybridSearchResult


@dataclass(frozen=True, slots=True)
class HybridSearchOptions:
    """Coordinator options expressed in terms of channel budgets and fusion weights."""

    weights: Mapping[str, float] | None = None
    per_channel_k: int = 100
    fusion_k: int = 50
    rrf_base: int = 60


@dataclass(slots=True)
class HybridSearchEngine:
    """Stage-0 coordinator that delegates to BM25/SPLADE engines and fuses the results."""

    bm25: BM25Engine
    splade: SPLADEEngine
    fusion: FusionProtocol = field(default_factory=RRFWeighter, repr=False)

    def search(
        self,
        *,
        query: str,
        semantic_hits: Sequence[tuple[int, float]] | None,
        limit: int,
        options: HybridSearchOptions | None = None,
    ) -> HybridSearchResult:
        """Search across BM25, SPLADE, and semantic channels, then fuse results.

        Parameters
        ----------
        query : str
            Query text to search for.
        semantic_hits : Sequence[tuple[int, float]] | None
            Optional pre-computed semantic search results (doc_id, score) pairs.
        limit : int
            Maximum number of results to return after fusion.
        options : HybridSearchOptions | None, optional
            Optional search configuration (fusion_k, per_channel_k, etc.).

        Returns
        -------
        HybridSearchResult
            Fused search results with warnings and metadata.
        """
        opts = options or HybridSearchOptions()
        fusion_limit = max(1, min(int(opts.fusion_k), int(limit)))
        per_channel_k = max(fusion_limit, int(opts.per_channel_k))
        channel_pairs, warnings = self._collect_sparse_channels(query, per_channel_k)

        semantic_pairs = _normalize_inputs(semantic_hits, per_channel_k)
        if semantic_pairs:
            channel_pairs["semantic"] = semantic_pairs

        if not channel_pairs:
            return HybridSearchResult(
                docs=[],
                contributions={},
                channels=[],
                warnings=warnings or ["hybrid_search:no_candidates"],
                method={
                    "retrieval": [],
                    "coverage": "hybrid sparse retrieval (no candidates)",
                    "notes": warnings or ["hybrid_search:no_candidates"],
                    "fusion": {"type": "weighted_rrf", "k": fusion_limit, "base": opts.rrf_base},
                    "budget": {"per_channel_k": per_channel_k, "fusion_k": fusion_limit},
                    "explainability": {
                        "weights": dict(opts.weights or {}),
                        "contributions": {},
                    },
                },
            )

        weights = dict(opts.weights or {})
        normalized_weights = {
            channel: float(weights.get(channel, 1.0)) for channel in channel_pairs
        }
        fusion_config = _FusionConfig(
            fusion_k=fusion_limit,
            per_channel_k=per_channel_k,
            rrf_base=int(opts.rrf_base),
        )
        fused_pairs = self.fusion.fuse(
            [
                FusionInput(channel=name, candidates=pairs)
                for name, pairs in channel_pairs.items()
            ],
            options=FusionOptions(weights=weights, k=fusion_limit, base=int(opts.rrf_base)),
        )
        docs = [
            HybridResultDoc(doc_id=str(doc_id), score=float(score))
            for doc_id, score in fused_pairs[:limit]
        ]
        method, contributions, retrieval_channels = _build_method_payload(
            channel_pairs=channel_pairs,
            warnings=warnings,
            normalized_weights=normalized_weights,
            fusion_config=fusion_config,
        )
        return HybridSearchResult(
            docs=docs,
            contributions=contributions,
            channels=retrieval_channels,
            warnings=warnings,
            method=method,
        )

    def _collect_sparse_channels(
        self,
        query: str,
        per_channel_k: int,
    ) -> tuple[dict[str, list[tuple[int, float]]], list[str]]:
        warnings: list[str] = []
        channel_pairs: dict[str, list[tuple[int, float]]] = {}
        for label, engine in (("bm25", self.bm25), ("splade", self.splade)):
            pairs, warning = _run_sparse_channel(label, engine, query, per_channel_k)
            if pairs:
                channel_pairs[label] = pairs
            if warning:
                warnings.append(warning)
        return channel_pairs, warnings


def _run_sparse_channel(
    label: str,
    engine: BM25Engine | SPLADEEngine,
    query: str,
    limit: int,
) -> tuple[list[tuple[int, float]], str | None]:
    try:
        hits = engine.search(query, k=limit)
    except (RuntimeError, ValueError, OSError) as exc:  # pragma: no cover - defensive
        return [], f"{label}_channel_error:{exc}"
    pairs = [(int(doc_id), float(score)) for doc_id, score in hits]
    return pairs, None


def _normalize_inputs(
    hits: Sequence[tuple[int, float]] | None,
    limit: int,
) -> list[tuple[int, float]]:
    if not hits:
        return []
    normalized: list[tuple[int, float]] = []
    for doc_id, score in hits[:limit]:
        try:
            normalized.append((int(doc_id), float(score)))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            continue
    return normalized

@dataclass(frozen=True, slots=True)
class _FusionConfig:
    fusion_k: int
    per_channel_k: int
    rrf_base: int


def _build_method_payload(
    *,
    channel_pairs: dict[str, list[tuple[int, float]]],
    warnings: list[str],
    normalized_weights: Mapping[str, float],
    fusion_config: _FusionConfig,
) -> tuple[dict[str, object], dict[str, dict[str, object]], list[str]]:
    fusion_limit = fusion_config.fusion_k
    per_channel_k = fusion_config.per_channel_k
    rrf_base = fusion_config.rrf_base
    contributions: dict[str, dict[str, object]] = {
        channel: {
            "candidates": len(pairs),
            "weight": float(normalized_weights[channel]),
        }
        for channel, pairs in channel_pairs.items()
    }
    retrieval_channels = list(channel_pairs.keys())
    weights_payload = dict(normalized_weights)
    method: dict[str, object] = {
        "retrieval": retrieval_channels,
        "coverage": f"hybrid sparse retrieval ({len(retrieval_channels)} channels)",
        "notes": list(warnings),
        "fusion": {
            "type": "weighted_rrf",
            "k": fusion_limit,
            "base": rrf_base,
        },
        "budget": {
            "per_channel_k": per_channel_k,
            "fusion_k": fusion_limit,
        },
        "explainability": {
            "weights": weights_payload,
            "contributions": contributions,
        },
    }
    return method, contributions, retrieval_channels


__all__ = ["HybridSearchEngine", "HybridSearchOptions"]
