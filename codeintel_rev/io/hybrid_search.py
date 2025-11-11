"""Hybrid retrieval utilities combining FAISS, BM25, and SPLADE."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from codeintel_rev.evaluation.hybrid_pool import Hit, HybridPoolEvaluator
from codeintel_rev.observability import metrics as retrieval_metrics
from codeintel_rev.observability.timeline import Timeline, current_timeline
from codeintel_rev.plugins.channels import Channel, ChannelContext, ChannelError
from codeintel_rev.plugins.registry import ChannelRegistry
from codeintel_rev.retrieval.boosters import RecencyConfig, apply_recency_boost
from codeintel_rev.retrieval.gating import (
    StageGateConfig,
    analyze_query,
    decide_budgets,
    describe_budget_decision,
)
from codeintel_rev.retrieval.rm3_heuristics import RM3Heuristics, RM3Params
from codeintel_rev.retrieval.types import (
    ChannelHit,
    HybridResultDoc,
    HybridSearchResult,
)
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from codeintel_rev.app.capabilities import Capabilities
    from codeintel_rev.app.config_context import ResolvedPaths
    from codeintel_rev.config.settings import Settings, SpladeConfig
    from codeintel_rev.io.duckdb_manager import DuckDBManager

LOGGER = get_logger(__name__)


class BM25SearchProvider:
    """Pyserini-backed BM25 searcher with optional RM3 heuristics."""

    def __init__(
        self,
        index_dir: Path,
        *,
        k1: float,
        b: float,
        rm3_params: RM3Params | None = None,
        heuristics: RM3Heuristics | None = None,
        enable_rm3: bool = False,
        auto_rm3: bool = False,
    ) -> None:
        if not index_dir.exists():
            msg = f"BM25 index not found: {index_dir}"
            raise FileNotFoundError(msg)
        self._index_dir = index_dir
        self._lucene_module = import_module("pyserini.search.lucene")
        self._lucene_searcher_cls = self._lucene_module.LuceneSearcher
        self._k1 = float(k1)
        self._b = float(b)
        self._rm3_params = rm3_params or RM3Params()
        self._heuristics = heuristics if auto_rm3 else None
        self._rm3_enabled_default = enable_rm3
        self._auto_rm3 = auto_rm3

        self._base_searcher = self._create_searcher()
        self._rm3_searcher = None

    def _create_searcher(self) -> object:
        searcher = self._lucene_searcher_cls(str(self._index_dir))
        try:
            searcher.set_bm25(self._k1, self._b)
        except TypeError:
            searcher.set_bm25(k1=self._k1, b=self._b)
        return searcher

    def _ensure_rm3_searcher(self) -> object:
        if self._rm3_searcher is not None:
            return self._rm3_searcher
        searcher = self._create_searcher()
        params = self._rm3_params
        try:
            searcher.set_rm3(params.fb_docs, params.fb_terms, params.orig_weight)
        except TypeError:
            searcher.set_rm3(
                fb_docs=params.fb_docs,
                fb_terms=params.fb_terms,
                original_query_weight=params.orig_weight,
            )
        self._rm3_searcher = searcher
        return searcher

    def _should_use_rm3(self, query: str) -> bool:
        if self._rm3_enabled_default and not self._auto_rm3:
            return True
        if not self._auto_rm3:
            return False
        if self._heuristics is None:
            return self._rm3_enabled_default
        return self._heuristics.should_enable(query)

    def search(self, query: str, top_k: int, *, force_rm3: bool | None = None) -> list[ChannelHit]:
        """Return BM25 hits for ``query``, optionally applying RM3 when heuristics fire.

        Parameters
        ----------
        query : str
            Search query string.
        top_k : int
            Maximum number of results to return. Must be positive.
        force_rm3 : bool | None, optional
            Optional override to force RM3 usage. If None, uses heuristics to decide.
            Defaults to None.

        Returns
        -------
        list[ChannelHit]
            List of search results with document IDs and BM25 scores, sorted by
            relevance descending. Returns empty list if top_k <= 0.
        """
        if top_k <= 0:
            return []
        use_rm3 = self._should_use_rm3(query)
        if force_rm3 is not None:
            use_rm3 = force_rm3
        if use_rm3:
            searcher = self._ensure_rm3_searcher()
        else:
            searcher = self._base_searcher
        hits = searcher.search(query, k=top_k)
        return [ChannelHit(doc_id=hit.docid, score=float(hit.score)) for hit in hits]


class SpladeSearchProvider:
    """SPLADE query encoder and Lucene impact searcher for learned sparse retrieval.

    This class combines a SPLADE (Sparse Lexical and Expansion) query encoder
    with a Lucene impact searcher to perform learned sparse retrieval. SPLADE
    learns to expand queries with relevant terms and assign importance weights,
    creating sparse representations that are more effective than traditional
    keyword matching while maintaining the efficiency of sparse retrieval.

    The provider initializes a SPLADE encoder model (typically loaded from ONNX
    format for efficiency) and a Lucene impact searcher that uses learned term
    weights for ranking. The encoder expands queries into weighted term vectors,
    which are then converted to bag-of-words representations for Lucene search.

    Parameters
    ----------
    config : SpladeConfig
        SPLADE configuration containing model settings, quantization parameters,
        and maximum term limits. Used to configure encoder behavior and search
        parameters.
    model_dir : Path
        Directory containing the SPLADE model files. The model directory should
        contain the encoder weights and tokenizer configuration.
    onnx_dir : Path
        Directory containing ONNX-exported model files. If an ONNX file exists
        (specified in config.onnx_file), it will be used instead of the PyTorch
        model for faster inference. Falls back to PyTorch model if ONNX not found.
    index_dir : Path
        Directory path containing the Lucene impact index. The index must be
        created using Pyserini's indexing tools with SPLADE-encoded document
        vectors. Each document should have term weights matching the SPLADE
        encoding scheme.

    Raises
    ------
    FileNotFoundError
        If the SPLADE impact index directory does not exist or is not accessible.
    """

    def __init__(
        self,
        config: SpladeConfig,
        *,
        model_dir: Path,
        onnx_dir: Path,
        index_dir: Path,
    ) -> None:
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
        self._max_query_terms = max(0, config.max_query_terms)
        self._prune_below = max(0.0, float(config.prune_below))
        self._static_prune_pct = min(max(0.0, float(config.static_prune_pct)), 1.0)

    def search(self, query: str, top_k: int) -> list[ChannelHit]:
        """Return SPLADE impact hits for ``query``.

        Encodes the query using the SPLADE encoder to generate a sparse term
        vector with learned importance weights. The vector is decoded into a
        bag-of-words representation with term repetitions based on quantized
        weights, then searched against the Lucene impact index. Results are
        ranked by learned relevance scores.

        Parameters
        ----------
        query : str
            Search query string to encode and search. The SPLADE encoder will
            expand this query with relevant terms and assign importance weights
            based on learned patterns from training data.
        top_k : int
            Maximum number of results to return. The searcher returns the top-k
            highest-scoring documents based on learned SPLADE relevance. Must be
            a positive integer.

        Returns
        -------
        list[ChannelHit]
            List of ranked SPLADE results, ordered by learned relevance score
            (highest first). Each ChannelHit contains a document ID and SPLADE
            impact score. Returns empty list if encoding fails, no terms are
            generated, or top_k is 0.
        """
        embeddings = self._encoder.encode_query([query])
        decoded = self._encoder.decode(embeddings, top_k=None)
        if not decoded or not decoded[0]:
            return []
        filtered_pairs = self._filter_pairs(decoded[0])
        if not filtered_pairs:
            return []
        bow = self._build_bow(filtered_pairs)
        if not bow:
            return []
        hits = self._searcher.search(bow, k=top_k)
        return [ChannelHit(doc_id=hit.docid, score=float(hit.score)) for hit in hits]

    def _filter_pairs(self, pairs: Sequence[tuple[str, float]]) -> list[tuple[str, float]]:
        filtered = [(token, weight) for token, weight in pairs if weight > 0]
        if self._prune_below > 0.0:
            filtered = [
                (token, weight) for token, weight in filtered if weight >= self._prune_below
            ]
        if self._static_prune_pct > 0.0 and filtered:
            keep = max(1, int(round(len(filtered) * (1.0 - self._static_prune_pct))))
            filtered = sorted(filtered, key=lambda item: item[1], reverse=True)[:keep]
        if self._max_query_terms > 0:
            filtered = filtered[: self._max_query_terms]
        return filtered

    def _build_bow(self, pairs: Sequence[tuple[str, float]]) -> str:
        tokens: list[str] = []
        query_cap = self._max_query_terms or self._max_terms
        remaining = min(self._max_terms, query_cap) if query_cap else self._max_terms
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


@dataclass(slots=True, frozen=True)
class HybridSearchTuning:
    """Runtime overrides for FAISS search metadata."""

    k: int | None = None
    nprobe: int | None = None


@dataclass(slots=True, frozen=True)
class HybridSearchOptions:
    """Optional knobs influencing hybrid fusion."""

    extra_channels: Mapping[str, Sequence[ChannelHit]] | None = None
    weights: Mapping[str, float] | None = None
    tuning: HybridSearchTuning | None = None


@dataclass(slots=True, frozen=True)
class _MethodStats:
    fused_count: int
    limit: int
    faiss_k: int | None
    nprobe: int | None
    weights: Mapping[str, float]


class HybridSearchEngine:
    """Combine dense (FAISS) and sparse channel plugins via RRF."""

    def __init__(
        self,
        settings: Settings,
        paths: ResolvedPaths,
        *,
        capabilities: Capabilities | None = None,
        registry: ChannelRegistry | None = None,
        duckdb_manager: DuckDBManager | None = None,
    ) -> None:
        self._settings = settings
        self._paths = paths
        self._capabilities = capabilities
        self._duckdb_manager = duckdb_manager
        if registry is None:
            channel_context = ChannelContext(
                settings=settings,
                paths=paths,
                capabilities=capabilities,
            )
            self._registry = ChannelRegistry.discover(channel_context)
        else:
            self._registry = registry
        self._pool_weights = self._compute_pool_weights()
        self._pooler = self._make_pooler()
        self._explain_last: dict[str, object] = {}

    def _make_stage_gate_config(self) -> StageGateConfig:
        default_depths = dict(self._settings.index.hybrid_prefetch)
        default_depths.setdefault("semantic", self._settings.index.hybrid_top_k_per_channel)
        default_depths.setdefault("bm25", self._settings.index.hybrid_top_k_per_channel)
        default_depths.setdefault("splade", self._settings.index.hybrid_top_k_per_channel)

        literal_depths = dict(default_depths)
        literal_depths["bm25"] = max(5, int(literal_depths.get("bm25", 0) * 1.5) or 0)
        literal_depths["splade"] = max(5, int(literal_depths.get("splade", 0) * 0.6) or 0)

        vague_depths = dict(default_depths)
        vague_depths["semantic"] = max(10, int(vague_depths.get("semantic", 0) * 1.3) or 0)
        vague_depths["splade"] = max(10, int(vague_depths.get("splade", 0) * 1.4) or 0)

        prf_cfg = self._settings.index.prf
        bm25_cfg = self._settings.bm25
        return StageGateConfig(
            default_depths=default_depths,
            literal_depths=literal_depths,
            vague_depths=vague_depths,
            rrf_k_default=self._settings.index.rrf_k,
            rrf_k_literal=max(10, self._settings.index.rrf_k // 2),
            rrf_k_vague=max(self._settings.index.rrf_k + 30, self._settings.index.rrf_k),
            rm3_auto=prf_cfg.enable_auto,
            rm3_min_len=prf_cfg.short_query_max_terms,
            rm3_max_len=max(prf_cfg.short_query_max_terms * 3, prf_cfg.short_query_max_terms),
            rm3_fb_docs=bm25_cfg.rm3_fb_docs,
            rm3_fb_terms=bm25_cfg.rm3_fb_terms,
            rm3_original_weight=bm25_cfg.rm3_original_query_weight,
        )

    def _recency_config(self) -> RecencyConfig:
        return RecencyConfig(
            enabled=self._settings.index.recency_enabled,
            half_life_days=self._settings.index.recency_half_life_days,
            max_boost=self._settings.index.recency_max_boost,
            table=self._settings.index.recency_table,
        )

    def _rrf_fuse(
        self,
        runs: Mapping[str, Sequence[ChannelHit]],
        *,
        limit: int,
        rrf_k: int,
    ) -> tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]]]:
        aggregated: dict[str, float] = {}
        for channel, hits in runs.items():
            for rank, hit in enumerate(hits, start=1):
                doc_id = str(hit.doc_id)
                aggregated.setdefault(doc_id, 0.0)
                aggregated[doc_id] += 1.0 / (rrf_k + rank)
        ranked = sorted(aggregated.items(), key=lambda item: item[1], reverse=True)[:limit]
        docs = [HybridResultDoc(doc_id=doc_id, score=score) for doc_id, score in ranked]
        contributions = self._build_contribution_map(runs)
        contributions_for_docs = {doc.doc_id: contributions.get(doc.doc_id, []) for doc in docs}
        return docs, contributions_for_docs

    def _build_debug_bundle(
        self,
        query: str,
        budget_info: Mapping[str, object],
        channels: Mapping[str, Sequence[ChannelHit]],
        rrf_k: int,
    ) -> dict[str, object]:
        return {
            "query": query,
            "budget": dict(budget_info),
            "per_channel_top": {
                name: [{"doc_id": hit.doc_id, "score": float(hit.score)} for hit in hits[:10]]
                for name, hits in channels.items()
            },
            "rrf_k": rrf_k,
        }

    def search(
        self,
        query: str,
        *,
        semantic_hits: Sequence[tuple[int, float]],
        limit: int,
        options: HybridSearchOptions | None = None,
    ) -> HybridSearchResult:
        """Fuse dense and sparse retrieval results for ``query`` using adaptive budgets."""
        timeline = current_timeline()
        retrieval_metrics.QUERIES_TOTAL.labels(kind="search").inc()
        gate_cfg = self._make_stage_gate_config()
        profile = analyze_query(query, gate_cfg)
        retrieval_metrics.QUERY_AMBIGUITY.observe(profile.ambiguity_score)
        budget_decision = decide_budgets(profile, gate_cfg)
        budget_info = describe_budget_decision(profile, budget_decision)
        retrieval_metrics.RRF_K.set(float(budget_decision.rrf_k))
        retrieval_metrics.observe_budget_depths(budget_decision.per_channel_depths.items())
        if timeline is not None:
            timeline.event(
                "hybrid.query_profile",
                "query_profile",
                attrs=budget_info,
            )

        runs, warnings = self._gather_channel_hits(
            query,
            semantic_hits,
            channel_limits=budget_decision.per_channel_depths,
        )

        opts = options or HybridSearchOptions()
        extra_channels = opts.extra_channels or {}
        extra_channel_names = tuple(extra_channels.keys())
        weights_used = self._resolve_pool_weights(opts.weights, extra_channel_names)
        needs_custom_pooler = bool(extra_channel_names) or opts.weights is not None
        pooler = (
            self._pooler
            if not needs_custom_pooler
            else self._make_pooler(opts.weights, extra_channels=extra_channel_names)
        )
        for name, hits in extra_channels.items():
            if hits:
                runs[name] = list(hits)

        active_channels = [channel for channel, hits in runs.items() if hits] or ["semantic"]
        if timeline is not None and runs:
            total_candidates = sum(len(hits) for hits in runs.values())
            timeline.event(
                "hybrid.fuse.start",
                "fusion",
                attrs={
                    "channels": list(runs.keys()),
                    "rrf_k": budget_decision.rrf_k,
                    "total": total_candidates,
                },
            )

        docs: list[HybridResultDoc]
        contributions_for_docs: dict[str, list[tuple[str, int, float]]]
        runtime = opts.tuning or HybridSearchTuning()

        if not runs:
            method = self._compose_method_metadata(
                active_channels,
                warnings,
                stats=_MethodStats(
                    fused_count=0,
                    limit=limit,
                    faiss_k=runtime.k,
                    nprobe=runtime.nprobe,
                    weights=weights_used,
                ),
                fusion={"type": "rrf" if self._settings.index.hybrid_use_rrf else "pool"},
                budget=budget_info,
            )
            self._explain_last = method
            return HybridSearchResult(
                docs=[],
                contributions={},
                channels=active_channels,
                warnings=warnings,
                method=method,
            )

        if self._settings.index.hybrid_use_rrf:
            start_rrf = perf_counter()
            docs, contributions_for_docs = self._rrf_fuse(
                runs,
                limit=limit,
                rrf_k=budget_decision.rrf_k,
            )
            retrieval_metrics.RRF_DURATION_SECONDS.observe(perf_counter() - start_rrf)
            method = self._compose_method_metadata(
                active_channels,
                warnings,
                stats=_MethodStats(
                    fused_count=len(docs),
                    limit=limit,
                    faiss_k=runtime.k,
                    nprobe=runtime.nprobe,
                    weights=weights_used,
                ),
                fusion={"type": "rrf", "K": budget_decision.rrf_k},
                budget=budget_info,
            )
            if timeline is not None:
                timeline.event(
                    "hybrid.fuse.rrf",
                    "fusion",
                    attrs={"rrf_k": budget_decision.rrf_k, "returned": len(docs)},
                )
        else:
            flattened = self._flatten_hits_for_pool(runs)
            contributions = self._build_contribution_map(runs)
            if flattened:
                pooled_hits = pooler.pool(flattened, k=limit)
                docs = [
                    HybridResultDoc(doc_id=pooled.doc_id, score=pooled.blended_score)
                    for pooled in pooled_hits
                ]
                contributions_for_docs = {
                    doc.doc_id: contributions.get(doc.doc_id, []) for doc in docs
                }
            else:
                docs = []
                contributions_for_docs = {}
            method = self._compose_method_metadata(
                active_channels,
                warnings,
                stats=_MethodStats(
                    fused_count=len(docs),
                    limit=limit,
                    faiss_k=runtime.k,
                    nprobe=runtime.nprobe,
                    weights=weights_used,
                ),
                fusion={"type": "pool"},
                budget=budget_info,
            )
            if timeline is not None:
                timeline.event(
                    "hybrid.fuse.pool",
                    "fusion",
                    attrs={"returned": len(docs)},
                )

        recency_cfg = self._recency_config()
        boost_count = 0
        if recency_cfg.enabled and docs:
            docs, boost_count = apply_recency_boost(
                docs,
                recency_cfg,
                duckdb_manager=self._duckdb_manager,
            )
            if boost_count:
                retrieval_metrics.RECENCY_BOOSTED_TOTAL.inc(boost_count)

        debug_bundle = self._build_debug_bundle(query, budget_info, runs, budget_decision.rrf_k)
        retrieval_metrics.DEBUG_BUNDLE_TOTAL.inc()
        if timeline is not None:
            timeline.event("hybrid.debug_bundle", "debug", attrs={"bundle": debug_bundle})

        retrieval_metrics.RESULTS_TOTAL.inc(len(docs))
        self._explain_last = method
        return HybridSearchResult(
            docs=docs,
            contributions=contributions_for_docs,
            channels=active_channels,
            warnings=warnings,
            method=method,
        )

    def _gather_channel_hits(
        self,
        query: str,
        semantic_hits: Sequence[tuple[int, float]],
        *,
        channel_limits: Mapping[str, int] | None = None,
    ) -> tuple[dict[str, list[ChannelHit]], list[str]]:
        """Collect per-channel search hits and warnings for ``query``.

        This internal method coordinates retrieval across all enabled channels,
        collecting results from semantic (FAISS), BM25, and SPLADE channels.
        Each channel is queried independently, and errors are captured as warnings
        rather than exceptions to ensure robust multi-channel retrieval.

        The semantic channel is always included (converting IDs and scores to
        ChannelHit objects). BM25 and SPLADE channels are conditionally enabled
        based on settings and availability. Channel initialization errors are
        captured as warnings and included in the return value.

        Parameters
        ----------
        query : str
            Search query string. Used for sparse retrieval channels (BM25, SPLADE).
            The semantic channel uses pre-computed results, so query is only
            relevant for sparse channels.
        semantic_hits : Sequence[tuple[int, float]]
            Dense retrieval hits expressed as ``(doc_id, score)`` pairs.

        Returns
        -------
        tuple[dict[str, list[ChannelHit]], list[str]]
            Tuple containing:
            - Dictionary mapping channel identifiers ("semantic", "bm25", "splade")
              to lists of ChannelHit objects. Only channels that successfully
              returned results are included.
            - List of warning messages accumulated during channel retrieval. Includes
              initialization errors, search failures, and availability issues.
        """
        runs: dict[str, list[ChannelHit]] = {}
        warnings: list[str] = []
        timeline = current_timeline()

        semantic_limit = channel_limits.get("semantic") if channel_limits else None
        semantic_channel_hits = self._build_semantic_channel_hits(
            semantic_hits, limit=semantic_limit
        )
        if semantic_channel_hits:
            runs["semantic"] = semantic_channel_hits
        if timeline is not None:
            timeline.event(
                "hybrid.semantic.run",
                "semantic",
                attrs={"hits": len(semantic_channel_hits)},
            )

        default_limit = self._settings.index.hybrid_top_k_per_channel
        for channel in self._registry.channels():
            limit = default_limit
            if channel_limits and channel.name in channel_limits:
                limit = channel_limits[channel.name]
            hits, warning = self._collect_channel_hits(channel, query, limit, timeline)
            if warning:
                warnings.append(warning)
            if hits:
                runs[channel.name] = hits

        return runs, warnings

    def _channel_disabled_reason(self, channel: Channel) -> str | None:
        if channel.name == "bm25" and (
            not self._settings.index.enable_bm25_channel or not self._settings.bm25.enabled
        ):
            return "disabled"
        if channel.name == "splade" and (
            not self._settings.index.enable_splade_channel or not self._settings.splade.enabled
        ):
            return "disabled"
        return None

    def _missing_capabilities(self, channel: Channel) -> set[str]:
        if not channel.requires or self._capabilities is None:
            return set()
        missing: set[str] = set()
        for requirement in channel.requires:
            if not bool(getattr(self._capabilities, requirement, False)):
                missing.add(requirement)
        return missing

    def _collect_channel_hits(
        self,
        channel: Channel,
        query: str,
        limit: int,
        timeline: Timeline | None,
    ) -> tuple[list[ChannelHit], str | None]:
        disabled_reason = self._channel_disabled_reason(channel)
        if disabled_reason is not None:
            self._emit_channel_skip(channel.name, timeline, {"reason": disabled_reason})
            return [], None
        missing = self._missing_capabilities(channel)
        if missing:
            self._emit_channel_skip(
                channel.name,
                timeline,
                {"reason": "capability_off", "missing": sorted(missing)},
            )
            return [], None
        start = perf_counter()
        try:
            hits = list(channel.search(query, limit))
        except ChannelError as exc:
            warning = str(exc)
            retrieval_metrics.QUERY_ERRORS_TOTAL.labels(kind="search", channel=channel.name).inc()
            self._emit_channel_skip(
                channel.name,
                timeline,
                {"reason": exc.reason, "message": str(exc)},
            )
            return [], warning
        except (OSError, RuntimeError, ValueError, ImportError) as exc:  # pragma: no cover
            warning = f"{channel.name} channel failed: {exc}"
            LOGGER.warning(warning, exc_info=exc)
            retrieval_metrics.QUERY_ERRORS_TOTAL.labels(kind="search", channel=channel.name).inc()
            self._emit_channel_skip(
                channel.name,
                timeline,
                {"reason": "provider_error", "message": str(exc)},
            )
            return [], warning
        duration = perf_counter() - start
        retrieval_metrics.CHANNEL_LATENCY_SECONDS.labels(channel=channel.name).observe(duration)
        self._emit_channel_run(channel, hits, timeline)
        return hits, None

    @staticmethod
    def _emit_channel_skip(
        name: str,
        timeline: Timeline | None,
        attrs: dict[str, object],
    ) -> None:
        if timeline is None:
            return
        timeline.event(f"hybrid.{name}.skip", name, attrs=attrs)

    @staticmethod
    def _emit_channel_run(
        channel: Channel,
        hits: Sequence[ChannelHit],
        timeline: Timeline | None,
    ) -> None:
        if timeline is None:
            return
        timeline.event(
            f"hybrid.{channel.name}.run",
            channel.name,
            attrs={"hits": len(hits), "cost": getattr(channel, "cost", 1.0)},
        )

    def resolve_path(self, value: str) -> Path:
        """Resolve a path string to an absolute Path.

        Parameters
        ----------
        value : str
            Path string that may be absolute, relative, or use ~ expansion.

        Returns
        -------
        Path
            Absolute resolved path. If input is absolute, returns as-is.
            If relative, resolves relative to repository root.
        """
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            return candidate
        return (self._paths.repo_root / candidate).resolve()

    def _build_semantic_channel_hits(
        self,
        hits: Sequence[tuple[int, float]],
        *,
        limit: int | None = None,
    ) -> list[ChannelHit]:
        limit = limit or self._settings.index.hybrid_top_k_per_channel
        top_k = min(len(hits), limit) or len(hits)
        return [
            ChannelHit(doc_id=str(chunk_id), score=float(score)) for chunk_id, score in hits[:top_k]
        ]

    def _compute_pool_weights(self) -> dict[str, float]:
        weights = {
            "semantic": 1.0,
            "bm25": 1.0,
            "splade": 1.0,
            "warp": 1.0,
            "xtr": 1.0,
        }
        configured = getattr(self._settings.index, "rrf_weights", {}) or {}
        weights.update({k: float(v) for k, v in configured.items()})
        return weights

    def _resolve_pool_weights(
        self,
        weights_override: Mapping[str, float] | None = None,
        extra_channels: Sequence[str] | None = None,
    ) -> dict[str, float]:
        weights = dict(self._pool_weights)
        if extra_channels:
            for name in extra_channels:
                weights.setdefault(name, 1.0)
        if weights_override:
            weights.update({k: float(v) for k, v in weights_override.items()})
        return weights

    def _make_pooler(
        self,
        weights_override: Mapping[str, float] | None = None,
        *,
        extra_channels: Sequence[str] | None = None,
    ) -> HybridPoolEvaluator:
        weights = self._resolve_pool_weights(weights_override, extra_channels)
        threshold = getattr(self._settings.index, "semantic_min_score", 0.0)
        return HybridPoolEvaluator(weights=weights, sim_threshold=threshold)

    def _select_pooler(
        self,
        options: HybridSearchOptions,
    ) -> tuple[HybridPoolEvaluator, Mapping[str, float]]:
        extra_channels = tuple((options.extra_channels or {}).keys())
        weights = self._resolve_pool_weights(options.weights, extra_channels)
        if extra_channels or options.weights is not None:
            pooler = self._make_pooler(options.weights, extra_channels=extra_channels)
        else:
            pooler = self._pooler
        return pooler, weights

    @staticmethod
    def _flatten_hits_for_pool(runs: Mapping[str, Sequence[ChannelHit]]) -> list[Hit]:
        flattened: list[Hit] = []
        for source, hits in runs.items():
            for rank, hit in enumerate(hits, start=1):
                flattened.append(
                    Hit(
                        doc_id=str(hit.doc_id),
                        score=float(hit.score),
                        source=source,
                        meta={"score": float(hit.score), "rank": rank},
                    )
                )
        return flattened

    @staticmethod
    def _build_contribution_map(
        runs: Mapping[str, Sequence[ChannelHit]],
    ) -> dict[str, list[tuple[str, int, float]]]:
        contributions: dict[str, list[tuple[str, int, float]]] = {}
        for channel, hits in runs.items():
            for rank, hit in enumerate(hits, start=1):
                contributions.setdefault(hit.doc_id, []).append((channel, rank, float(hit.score)))
        return contributions

    def _compose_method_metadata(
        self,
        active_channels: Sequence[str],
        warnings: Sequence[str],
        stats: _MethodStats,
        fusion: Mapping[str, object] | None = None,
        budget: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        default_k = stats.faiss_k or self._settings.index.default_k
        default_nprobe = stats.nprobe or self._settings.index.default_nprobe
        coverage = (
            f"Hybrid pool fused {stats.fused_count}/{max(1, stats.limit)} results "
            f"(faiss k={default_k}, nprobe={default_nprobe})"
        )
        explainability = {
            "pool": {
                "weights": dict(stats.weights),
                "sim_threshold": getattr(self._settings.index, "semantic_min_score", 0.0),
            }
        }
        retrieval = list(dict.fromkeys(active_channels or ["semantic"]))
        notes = list(dict.fromkeys(warnings)) if warnings else []
        method = {
            "retrieval": retrieval,
            "coverage": coverage,
            "notes": notes,
            "explainability": explainability,
        }
        if fusion is not None:
            method["fusion"] = dict(fusion)
        if budget is not None:
            method["budget"] = dict(budget)
        return method


__all__ = [
    "BM25SearchProvider",
    "ChannelHit",
    "HybridResultDoc",
    "HybridSearchEngine",
    "HybridSearchOptions",
    "HybridSearchResult",
    "HybridSearchTuning",
    "SpladeSearchProvider",
]
