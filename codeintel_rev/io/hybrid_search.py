"""Hybrid retrieval utilities combining FAISS, BM25, and SPLADE."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ResolvedPaths
    from codeintel_rev.config.settings import Settings, SpladeConfig

LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class ChannelHit:
    """Single channel result used for Reciprocal Rank Fusion."""

    doc_id: str
    score: float


@dataclass(frozen=True)
class HybridResultDoc:
    """Fused result produced by the hybrid engine."""

    doc_id: str
    score: float


@dataclass(frozen=True)
class HybridSearchResult:
    """Hybrid search output with fused documents and contribution metadata."""

    docs: Sequence[HybridResultDoc]
    contributions: dict[str, list[tuple[str, int, float]]]
    channels: list[str]
    warnings: list[str]


class BM25SearchProvider:
    """Thin wrapper around Pyserini's LuceneSearcher."""

    def __init__(self, index_dir: Path, *, k1: float, b: float) -> None:
        """Initialize the Lucene searcher for BM25 queries.

        Raises
        ------
        FileNotFoundError
            If the BM25 index directory does not exist.
        """
        if not index_dir.exists():
            msg = f"BM25 index not found: {index_dir}"
            raise FileNotFoundError(msg)
        self._index_dir = index_dir
        lucene_module = import_module("pyserini.search.lucene")
        lucene_searcher_cls = lucene_module.LuceneSearcher
        self._searcher = lucene_searcher_cls(str(index_dir))
        self._searcher.set_bm25(k1, b)

    def search(self, query: str, top_k: int) -> list[ChannelHit]:
        """Return top-k BM25 hits for ``query``.

        Returns
        -------
        list[ChannelHit]
            Ranked BM25 results.
        """
        hits = self._searcher.search(query, k=top_k)
        return [ChannelHit(doc_id=hit.docid, score=float(hit.score)) for hit in hits]


class SpladeSearchProvider:
    """SPLADE query encoder and Lucene impact searcher."""

    def __init__(
        self,
        config: SpladeConfig,
        *,
        model_dir: Path,
        onnx_dir: Path,
        index_dir: Path,
    ) -> None:
        """Prepare SPLADE encoder and Lucene impact searcher.

        Raises
        ------
        FileNotFoundError
            If the SPLADE impact index directory does not exist.
        """
        if not index_dir.exists():
            msg = f"SPLADE impact index not found: {index_dir}"
            raise FileNotFoundError(msg)
        resolved_model_dir = model_dir
        resolved_onnx_path = onnx_dir / config.onnx_file
        model_kwargs: dict[str, str] = {"provider": config.provider}
        if resolved_onnx_path.exists():
            try:
                relative = resolved_onnx_path.relative_to(resolved_model_dir)
                model_kwargs["file_name"] = str(relative)
            except ValueError:
                model_kwargs["file_name"] = str(resolved_onnx_path)

        encoder_cls = import_module("sentence_transformers").SparseEncoder
        self._encoder = encoder_cls(
            str(resolved_model_dir),
            backend="onnx",
            model_kwargs=model_kwargs,
        )
        impact_module = import_module("pyserini.search.lucene")
        lucene_impact_searcher_cls = impact_module.LuceneImpactSearcher
        self._searcher = lucene_impact_searcher_cls(str(index_dir))
        self._quantization = config.quantization
        self._max_terms = config.max_terms

    def search(self, query: str, top_k: int) -> list[ChannelHit]:
        """Return SPLADE impact hits for ``query``.

        Returns
        -------
        list[ChannelHit]
            Ranked SPLADE results.
        """
        embeddings = self._encoder.encode_query([query])
        decoded = self._encoder.decode(embeddings, top_k=None)
        if not decoded or not decoded[0]:
            return []
        bow = self._build_bow(decoded[0])
        if not bow:
            return []
        hits = self._searcher.search(bow, k=top_k)
        return [ChannelHit(doc_id=hit.docid, score=float(hit.score)) for hit in hits]

    def _build_bow(self, pairs: Sequence[tuple[str, float]]) -> str:
        tokens: list[str] = []
        remaining = self._max_terms
        for token, weight in pairs:
            if weight <= 0 or remaining <= 0:
                continue
            impact = round(weight * self._quantization)
            if impact <= 0:
                continue
            repetitions = min(impact, remaining)
            tokens.extend([token] * repetitions)
            remaining -= repetitions
            if remaining <= 0:
                break
        return " ".join(tokens)


class HybridSearchEngine:
    """Combine dense (FAISS) and sparse channels (BM25, SPLADE) via RRF."""

    def __init__(self, settings: Settings, paths: ResolvedPaths) -> None:
        self._settings = settings
        self._paths = paths
        self._bm25_provider: BM25SearchProvider | None = None
        self._splade_provider: SpladeSearchProvider | None = None
        self._bm25_error: str | None = None
        self._splade_error: str | None = None
        self._bm25_lock = Lock()
        self._splade_lock = Lock()

    def search(
        self,
        query: str,
        *,
        semantic_ids: Sequence[int],
        semantic_scores: Sequence[float],
        limit: int,
    ) -> HybridSearchResult:
        """Fuse dense and sparse retrieval results for ``query``.

        Returns
        -------
        HybridSearchResult
            Fused retrieval output with channel metadata.
        """
        runs, warnings = self._gather_channel_hits(query, semantic_ids, semantic_scores)
        if not runs:
            return HybridSearchResult(
                docs=[],
                contributions={},
                channels=[],
                warnings=warnings,
            )

        docs, contributions = _rrf_fuse(
            runs,
            k=self._settings.index.rrf_k,
            limit=limit,
        )
        active_channels = [channel for channel, hits in runs.items() if hits]
        filtered_contributions = {doc.doc_id: contributions.get(doc.doc_id, []) for doc in docs}
        return HybridSearchResult(
            docs=docs,
            contributions=filtered_contributions,
            channels=active_channels,
            warnings=warnings,
        )

    def _gather_channel_hits(
        self,
        query: str,
        semantic_ids: Sequence[int],
        semantic_scores: Sequence[float],
    ) -> tuple[dict[str, list[ChannelHit]], list[str]]:
        """Collect per-channel search hits and warnings for ``query``.

        Returns
        -------
        tuple[dict[str, list[ChannelHit]], list[str]]
            Mapping of channel identifiers to hits and accumulated warnings.
        """
        runs: dict[str, list[ChannelHit]] = {}
        warnings: list[str] = []

        semantic_hits = self._build_semantic_hits(semantic_ids, semantic_scores)
        if semantic_hits:
            runs["semantic"] = semantic_hits

        if self._settings.index.enable_bm25_channel:
            self._maybe_add_bm25_hits(query, runs, warnings)
        if self._settings.index.enable_splade_channel:
            self._maybe_add_splade_hits(query, runs, warnings)

        return runs, warnings

    def _maybe_add_bm25_hits(
        self,
        query: str,
        runs: dict[str, list[ChannelHit]],
        warnings: list[str],
    ) -> None:
        """Populate BM25 hits when the channel is available."""
        provider = self._ensure_bm25_provider()
        if provider is None:
            if self._bm25_error:
                warnings.append(self._bm25_error)
            return

        try:
            hits = provider.search(query, self._settings.index.hybrid_top_k_per_channel)
        except (RuntimeError, ValueError) as exc:  # pragma: no cover - defensive logging
            msg = f"BM25 channel unavailable: {exc}"
            warnings.append(msg)
            LOGGER.warning(msg, exc_info=exc)
            return

        if hits:
            runs["bm25"] = hits

    def _maybe_add_splade_hits(
        self,
        query: str,
        runs: dict[str, list[ChannelHit]],
        warnings: list[str],
    ) -> None:
        """Populate SPLADE hits when the channel is available."""
        provider = self._ensure_splade_provider()
        if provider is None:
            if self._splade_error:
                warnings.append(self._splade_error)
            return

        try:
            hits = provider.search(query, self._settings.index.hybrid_top_k_per_channel)
        except (RuntimeError, ValueError) as exc:  # pragma: no cover - defensive logging
            msg = f"SPLADE channel unavailable: {exc}"
            warnings.append(msg)
            LOGGER.warning(msg, exc_info=exc)
            return

        if hits:
            runs["splade"] = hits

    def _ensure_bm25_provider(self) -> BM25SearchProvider | None:
        if self._bm25_provider is not None:
            return self._bm25_provider
        if self._bm25_error is not None:
            return None
        with self._bm25_lock:
            if self._bm25_provider is not None:
                return self._bm25_provider
            try:
                provider = self._create_bm25_provider()
            except (RuntimeError, OSError, ValueError, ImportError) as exc:
                self._bm25_error = f"BM25 initialization failed: {exc}"
                LOGGER.warning("Failed to initialize BM25 search provider", exc_info=exc)
                return None
            self._bm25_provider = provider
            return provider

    def _ensure_splade_provider(self) -> SpladeSearchProvider | None:
        if self._splade_provider is not None:
            return self._splade_provider
        if self._splade_error is not None:
            return None
        with self._splade_lock:
            if self._splade_provider is not None:
                return self._splade_provider
            try:
                provider = self._create_splade_provider()
            except (RuntimeError, OSError, ValueError, ImportError) as exc:
                self._splade_error = f"SPLADE initialization failed: {exc}"
                LOGGER.warning("Failed to initialize SPLADE search provider", exc_info=exc)
                return None
            self._splade_provider = provider
            return provider

    def _create_bm25_provider(self) -> BM25SearchProvider:
        index_dir = self._resolve_path(self._settings.bm25.index_dir)
        return BM25SearchProvider(
            index_dir=index_dir,
            k1=self._settings.index.bm25_k1,
            b=self._settings.index.bm25_b,
        )

    def _create_splade_provider(self) -> SpladeSearchProvider:
        splade = self._settings.splade
        return SpladeSearchProvider(
            splade,
            model_dir=self._resolve_path(splade.model_dir),
            onnx_dir=self._resolve_path(splade.onnx_dir),
            index_dir=self._resolve_path(splade.index_dir),
        )

    def _resolve_path(self, value: str) -> Path:
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            return candidate
        return (self._paths.repo_root / candidate).resolve()

    def _build_semantic_hits(
        self,
        ids: Sequence[int],
        scores: Sequence[float],
    ) -> list[ChannelHit]:
        top_k = min(len(ids), self._settings.index.hybrid_top_k_per_channel) or len(ids)
        hits: list[ChannelHit] = []
        for chunk_id, score in zip(ids[:top_k], scores[:top_k], strict=True):
            hits.append(ChannelHit(doc_id=str(chunk_id), score=float(score)))
        return hits


def _rrf_fuse(
    runs: dict[str, list[ChannelHit]],
    *,
    k: int,
    limit: int,
) -> tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]]]:
    fused_scores: dict[str, float] = {}
    contributions: dict[str, list[tuple[str, int, float]]] = {}

    for channel, hits in runs.items():
        for rank, hit in enumerate(hits, start=1):
            contribution = 1.0 / (k + rank)
            fused_scores[hit.doc_id] = fused_scores.get(hit.doc_id, 0.0) + contribution
            contributions.setdefault(hit.doc_id, []).append((channel, rank, hit.score))

    sorted_docs = sorted(fused_scores.items(), key=lambda item: item[1], reverse=True)
    top_docs = sorted_docs[:limit]
    docs = [HybridResultDoc(doc_id=doc_id, score=score) for doc_id, score in top_docs]
    filtered = {doc_id: contributions.get(doc_id, []) for doc_id, _ in top_docs}
    return docs, filtered


__all__ = [
    "BM25SearchProvider",
    "ChannelHit",
    "HybridResultDoc",
    "HybridSearchEngine",
    "HybridSearchResult",
    "SpladeSearchProvider",
]
