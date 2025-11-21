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


@dataclass(slots=True)
class HybridSearchOptions:
    """Coordinator options expressed in terms of channel budgets and fusion weights.

    Attributes
    ----------
    weights : Mapping[str, float] | None, optional
        Optional channel weight overrides. Keys are channel names ("bm25", "splade"),
        values are fusion weights. None means use default weights. Defaults to None.
    per_channel_k : int, optional
        Maximum number of results to retrieve from each channel before fusion.
        Must be positive. Defaults to 100.
    fusion_k : int, optional
        Maximum number of results to return after fusion. Must be positive.
        Defaults to 50.
    rrf_base : int, optional
        Reciprocal Rank Fusion (RRF) base parameter. Higher values reduce the
        impact of rank differences. Must be positive. Defaults to 60.
    """

    weights: Mapping[str, float] | None = None
    per_channel_k: int = 100
    fusion_k: int = 50
    rrf_base: int = 60


@dataclass(slots=True)
class HybridSearchEngine:
    """Stage-0 coordinator that delegates to BM25/SPLADE engines and fuses the results.

    Attributes
    ----------
    bm25 : BM25Engine
        BM25 search engine backend for keyword-based retrieval.
    splade : SPLADEEngine
        SPLADE search engine backend for learned sparse retrieval.
    fusion : FusionProtocol
        Fusion algorithm for combining BM25 and SPLADE results. Defaults to
        RRFWeighter. Not included in repr for brevity.
    """

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
            [FusionInput(channel=name, candidates=pairs) for name, pairs in channel_pairs.items()],
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
        """Collect search results from BM25 and SPLADE sparse channels.

        Parameters
        ----------
        query : str
            Query text to search for across sparse channels.
        per_channel_k : int
            Maximum number of results to retrieve from each channel.

        Returns
        -------
        tuple[dict[str, list[tuple[int, float]]], list[str]]
            A tuple containing:
            - Dictionary mapping channel names ("bm25", "splade") to lists
              of (doc_id, score) pairs
            - List of warning messages from channel execution
        """
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
    """Execute search on a single sparse channel (BM25 or SPLADE).

    Parameters
    ----------
    label : str
        Channel label for error reporting (e.g., "bm25", "splade").
    engine : BM25Engine | SPLADEEngine
        Search engine instance to execute the query on.
    query : str
        Query text to search for.
    limit : int
        Maximum number of results to return.

    Returns
    -------
    tuple[list[tuple[int, float]], str | None]
        A tuple containing:
        - List of (doc_id, score) pairs from the search
        - Warning message string if an error occurred, None otherwise
    """
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
    """Normalize semantic search hits to a list of (doc_id, score) pairs.

    Parameters
    ----------
    hits : Sequence[tuple[int, float]] | None
        Optional sequence of (doc_id, score) pairs from semantic search.
        Can be None or empty.
    limit : int
        Maximum number of hits to include in the normalized result.

    Returns
    -------
    list[tuple[int, float]]
        Normalized list of (doc_id, score) pairs. Returns empty list if
        hits is None or empty. Invalid entries are skipped silently.
    """
    if not hits:
        return []
    normalized: list[tuple[int, float]] = []
    for doc_id, score in hits[:limit]:
        try:
            normalized.append((int(doc_id), float(score)))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            continue
    return normalized


@dataclass(slots=True)
class _FusionConfig:
    """Configuration parameters for hybrid search fusion.

    Attributes
    ----------
    fusion_k : int
        Maximum number of results to return after fusion.
    per_channel_k : int
        Maximum number of results to retrieve from each channel before fusion.
    rrf_base : int
        Base value for Reciprocal Rank Fusion (RRF) scoring.
    """

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
    """Build method metadata payload and contribution tracking for hybrid search.

    Parameters
    ----------
    channel_pairs : dict[str, list[tuple[int, float]]]
        Dictionary mapping channel names to their (doc_id, score) result pairs.
    warnings : list[str]
        List of warning messages from channel execution.
    normalized_weights : Mapping[str, float]
        Normalized fusion weights for each channel.
    fusion_config : _FusionConfig
        Fusion configuration containing k values and RRF base.

    Returns
    -------
    tuple[dict[str, object], dict[str, dict[str, object]], list[str]]
        A tuple containing:
        - Method metadata dictionary with retrieval channels, fusion details,
          budget information, and explainability data
        - Contributions dictionary mapping channel names to their candidate
          counts and weights
        - List of retrieval channel names
    """
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
