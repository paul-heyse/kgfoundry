"""Hybrid retrieval utilities combining FAISS, BM25, and SPLADE."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from codeintel_rev.evaluation.hybrid_pool import Hit, HybridPoolEvaluator
from codeintel_rev.plugins.channels import Channel, ChannelContext, ChannelError
from codeintel_rev.plugins.registry import ChannelRegistry
from codeintel_rev.retrieval.boosters import RecencyConfig, apply_recency_boost
from codeintel_rev.retrieval.gating import (
    BudgetDecision,
    StageGateConfig,
    analyze_query,
    decide_budgets,
    describe_budget_decision,
)
from codeintel_rev.retrieval.rm3_heuristics import RM3Heuristics, RM3Params
from codeintel_rev.retrieval.types import HybridResultDoc, HybridSearchResult, SearchHit

if TYPE_CHECKING:
    from codeintel_rev.app.capabilities import Capabilities
    from codeintel_rev.config.paths import ResolvedPaths
    from codeintel_rev.config.settings import Settings, SpladeConfig
    from codeintel_rev.io.duckdb_manager import DuckDBManager


class _LuceneHit(Protocol):
    """Protocol for Lucene search result hits.

    This protocol defines the interface for search hits returned by Lucene-based
    searchers (Pyserini). It specifies the minimum attributes required to work
    with search results: document ID and relevance score. Used for type checking
    and ensuring compatibility with Lucene search implementations.

    Attributes
    ----------
    docid : str
        Document identifier string uniquely identifying the retrieved document.
        Typically corresponds to a chunk ID or document path in the index.
    score : float
        Relevance score assigned by the search algorithm. Higher scores indicate
        greater relevance to the query. Score ranges depend on the search algorithm
        (BM25, impact scoring, etc.).
    """

    docid: str
    score: float


class _LuceneSearcher(Protocol):
    """Protocol for Lucene-based search implementations.

    This protocol defines the interface for Lucene searchers used by Pyserini,
    enabling type-safe interaction with BM25 and impact search implementations.
    The protocol supports configuration of BM25 parameters and RM3 pseudo-relevance
    feedback, as well as executing searches and retrieving ranked results.

    Methods
    -------
    set_bm25(*args, **kwargs) -> None
        Configure BM25 ranking parameters (k1, b) for the searcher. Parameters
        may be passed positionally or as keywords depending on implementation.
    set_rm3(*args, **kwargs) -> None
        Configure RM3 pseudo-relevance feedback parameters (fb_docs, fb_terms,
        original_query_weight). Enables query expansion based on top retrieved
        documents.
    search(query, k) -> Sequence[_LuceneHit]
        Execute search for the given query and return top-k ranked results.
        Results are ordered by relevance score (highest first).
    """

    def set_bm25(self, *args: object, **kwargs: object) -> None:
        """Configure BM25 parameters for the searcher."""
        ...

    def set_rm3(self, *args: object, **kwargs: object) -> None:
        """Configure RM3 pseudo-relevance feedback parameters."""
        ...

    def search(self, query: str, k: int) -> Sequence[_LuceneHit]:
        """Execute search and return Lucene hits."""
        ...


@dataclass(slots=True, frozen=True)
class BM25Rm3Config:
    """Bundle RM3 parameters and heuristics for BM25 search."""

    params: RM3Params | None = None
    heuristics: RM3Heuristics | None = None
    enable_rm3: bool = False
    auto_rm3: bool = False


class BM25SearchProvider:
    """Pyserini-backed BM25 searcher with optional RM3 heuristics."""

    def __init__(
        self,
        index_dir: Path,
        *,
        k1: float,
        b: float,
        rm3: BM25Rm3Config | None = None,
    ) -> None:
        """Initialize BM25 search provider.

        Parameters
        ----------
        index_dir : Path
            Path to BM25 Lucene index directory.
        k1 : float
            BM25 k1 parameter (term frequency saturation).
        b : float
            BM25 b parameter (length normalization).
        rm3 : BM25Rm3Config | None, optional
            RM3 query expansion configuration. If None, RM3 is disabled.

        Raises
        ------
        FileNotFoundError
            If the BM25 index directory does not exist.
        """
        if not index_dir.exists():
            msg = f"BM25 index not found: {index_dir}"
            raise FileNotFoundError(msg)
        rm3_cfg = rm3 or BM25Rm3Config()
        self._index_dir = index_dir
        self._lucene_module = import_module("pyserini.search.lucene")
        self._lucene_searcher_cls = self._lucene_module.LuceneSearcher
        self._k1 = float(k1)
        self._b = float(b)
        self._rm3_params = rm3_cfg.params or RM3Params()
        self._heuristics = rm3_cfg.heuristics if rm3_cfg.auto_rm3 else None
        self._rm3_enabled_default = rm3_cfg.enable_rm3
        self._auto_rm3 = rm3_cfg.auto_rm3

        self._base_searcher: _LuceneSearcher = self._create_searcher()
        self._rm3_searcher: _LuceneSearcher | None = None

    def _create_searcher(self) -> _LuceneSearcher:
        """Create and configure a new Lucene searcher instance.

        This method instantiates a Lucene searcher from Pyserini and configures
        it with BM25 parameters. The method handles both positional and keyword
        argument styles for set_bm25 to ensure compatibility across Pyserini
        versions. The searcher is initialized with the BM25 index directory and
        configured with k1 and b parameters for ranking.

        Returns
        -------
        _LuceneSearcher
            Configured Lucene searcher instance ready for BM25 search operations.
            The searcher is bound to the BM25 index directory and has BM25
            parameters set according to the provider configuration.

        Notes
        -----
        This method creates a fresh searcher instance each time it's called,
        enabling isolation between search operations. The method handles API
        variations in Pyserini by trying both positional and keyword argument
        styles for BM25 configuration.
        """
        searcher = self._lucene_searcher_cls(str(self._index_dir))
        try:
            searcher.set_bm25(self._k1, self._b)
        except TypeError:
            searcher.set_bm25(k1=self._k1, b=self._b)
        return searcher

    def _ensure_rm3_searcher(self) -> _LuceneSearcher:
        """Get or create a Lucene searcher configured for RM3 pseudo-relevance feedback.

        This method lazily creates and caches an RM3-configured searcher instance.
        RM3 (Relevance Model 3) expands queries by extracting terms from top retrieved
        documents, improving recall for short or ambiguous queries. The searcher is
        configured with RM3 parameters (feedback documents, feedback terms, original
        query weight) and cached for reuse across multiple searches.

        Returns
        -------
        _LuceneSearcher
            Lucene searcher instance configured with RM3 parameters. The searcher
            is cached after first creation to avoid repeated initialization overhead.
            Subsequent calls return the cached instance.

        Notes
        -----
        RM3 searcher creation is deferred until needed, reducing initialization
        overhead when RM3 is not used. The method handles API variations in
        Pyserini by trying both positional and keyword argument styles for RM3
        configuration. The cached searcher is reused for all RM3-enabled searches.
        """
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
        """Determine whether RM3 pseudo-relevance feedback should be enabled for a query.

        This method implements the RM3 decision logic, supporting three modes:
        always enabled, always disabled, and automatic (heuristic-based). When
        auto_rm3 is enabled, heuristics analyze the query to determine if RM3
        would be beneficial (e.g., for short queries that benefit from expansion).
        When auto_rm3 is disabled, the decision is based on the default enable
        setting.

        Parameters
        ----------
        query : str
            Search query string to analyze for RM3 eligibility. The query is
            evaluated by heuristics if auto_rm3 is enabled.

        Returns
        -------
        bool
            True if RM3 should be enabled for this query, False otherwise. The
            decision considers the default enable setting, auto_rm3 mode, and
            heuristic analysis when applicable.

        Notes
        -----
        RM3 is most beneficial for short or ambiguous queries that lack sufficient
        terms for effective keyword matching. Heuristics typically enable RM3
        for queries below a certain length threshold or with specific characteristics.
        The method provides flexible control over RM3 usage while enabling automatic
        optimization when appropriate.
        """
        if self._rm3_enabled_default and not self._auto_rm3:
            return True
        if not self._auto_rm3:
            return False
        if self._heuristics is None:
            return self._rm3_enabled_default
        return self._heuristics.should_enable(query)

    def search(self, query: str, top_k: int, *, force_rm3: bool | None = None) -> list[SearchHit]:
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
        list[SearchHit]
            List of search results with document IDs and BM25 scores, sorted by
            relevance descending. Returns empty list if top_k <= 0.

        Raises
        ------
        RuntimeError
            Raised when the underlying Pyserini searcher fails.
        """
        if top_k <= 0:
            return []
        use_rm3 = self._should_use_rm3(query)
        if force_rm3 is not None:
            use_rm3 = force_rm3
        searcher = self._ensure_rm3_searcher() if use_rm3 else self._base_searcher
        try:
            hits = searcher.search(query, k=top_k)
        except Exception as exc:
            msg = "BM25 search failed"
            raise RuntimeError(msg) from exc
        return [
            SearchHit(
                doc_id=str(hit.docid),
                rank=rank,
                score=float(hit.score),
                source="bm25",
                explain={"bm25_score": float(hit.score), "rm3": use_rm3},
            )
            for rank, hit in enumerate(hits)
        ]


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
        """Initialize SPLADE search provider.

        Parameters
        ----------
        config : SpladeConfig
            SPLADE configuration settings.
        model_dir : Path
            Directory containing SPLADE model files.
        onnx_dir : Path
            Directory containing ONNX model files.
        index_dir : Path
            Path to SPLADE impact index directory.

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
        self._max_query_terms = max(0, config.max_query_terms)
        self._prune_below = max(0.0, float(config.prune_below))
        self._static_prune_pct = min(max(0.0, float(config.static_prune_pct)), 1.0)

    def search(self, query: str, top_k: int) -> list[SearchHit]:
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
        list[SearchHit]
            List of ranked SPLADE results, ordered by learned relevance score
            (highest first). Each hit contains a document ID and SPLADE impact
            score. Returns empty list if encoding fails, no terms are generated,
            or top_k is 0.

        Raises
        ------
        RuntimeError
            Raised when the SPLADE encoder or impact searcher fails.
        """
        if top_k <= 0:
            return []
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
        try:
            hits = self._searcher.search(bow, k=top_k)
        except Exception as exc:
            msg = "SPLADE search failed"
            raise RuntimeError(msg) from exc
        return [
            SearchHit(
                doc_id=str(hit.docid),
                rank=rank,
                score=float(hit.score),
                source="splade",
                explain={"splade_score": float(hit.score)},
            )
            for rank, hit in enumerate(hits)
        ]

    def _filter_pairs(self, pairs: Sequence[tuple[str, float]]) -> list[tuple[str, float]]:
        """Filter and prune SPLADE token-weight pairs based on configuration thresholds.

        This method applies multiple filtering strategies to reduce the number of
        terms in the SPLADE query representation: removing zero-weight terms,
        applying minimum weight thresholds, static percentage pruning, and maximum
        term limits. The filtering improves search efficiency by focusing on the
        most important terms while reducing query complexity.

        Parameters
        ----------
        pairs : Sequence[tuple[str, float]]
            Sequence of (token, weight) pairs from SPLADE encoding. Each pair
            represents a term and its learned importance weight from the encoder.

        Returns
        -------
        list[tuple[str, float]]
            Filtered list of (token, weight) pairs after applying all pruning
            strategies. Terms are sorted by weight (descending) after static
            pruning, and the list is truncated to max_query_terms if configured.

        Notes
        -----
        The filtering pipeline applies multiple strategies in sequence: zero-weight
        removal, minimum threshold pruning, static percentage pruning (keeping top
        N% by weight), and maximum term limit. This ensures queries remain focused
        on the most important terms while respecting configuration limits. Static
        pruning helps remove noise from low-weight terms that may not contribute
        meaningfully to retrieval.
        """
        filtered = [(token, weight) for token, weight in pairs if weight > 0]
        if self._prune_below > 0.0:
            filtered = [
                (token, weight) for token, weight in filtered if weight >= self._prune_below
            ]
        if self._static_prune_pct > 0.0 and filtered:
            keep = max(1, round(len(filtered) * (1.0 - self._static_prune_pct)))
            filtered = sorted(filtered, key=lambda item: item[1], reverse=True)[:keep]
        if self._max_query_terms > 0:
            filtered = filtered[: self._max_query_terms]
        return filtered

    def _build_bow(self, pairs: Sequence[tuple[str, float]]) -> str:
        """Convert filtered token-weight pairs into a bag-of-words query string.

        This method converts SPLADE token-weight pairs into a bag-of-words (BOW)
        representation suitable for Lucene impact search. Weights are quantized
        and converted to term repetitions, where higher weights result in more
        repetitions of the term. This enables Lucene to use term frequency for
        ranking while preserving the learned importance weights from SPLADE.

        Parameters
        ----------
        pairs : Sequence[tuple[str, float]]
            Filtered sequence of (token, weight) pairs from SPLADE encoding.
            Pairs should already be filtered by _filter_pairs to remove low-weight
            terms and respect term limits.

        Returns
        -------
        str
            Space-separated bag-of-words query string with term repetitions based
            on quantized weights. Higher-weight terms appear more frequently in
            the string, enabling Lucene impact scoring to reflect SPLADE importance.
            Returns empty string if no valid pairs remain after quantization.

        Notes
        -----
        The quantization process converts continuous weights into discrete term
        repetitions, enabling compatibility with Lucene's term-frequency-based
        scoring. The method respects maximum term limits to prevent excessively
        long queries while preserving the relative importance of terms through
        repetition counts. This approach bridges learned sparse retrieval (SPLADE)
        with traditional term-frequency ranking (Lucene).
        """
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

    extra_channels: Mapping[str, Sequence[SearchHit]] | None = None
    weights: Mapping[str, float] | None = None
    tuning: HybridSearchTuning | None = None
    faiss_ready: bool = True


@dataclass(slots=True, frozen=True)
class HybridSearchProviders:
    """Optional channel provider overrides for hybrid search."""

    bm25: Callable[[str, int], Sequence[SearchHit]] | None = None
    splade: Callable[[str, int], Sequence[SearchHit]] | None = None
    semantic: Callable[[Sequence[tuple[int, float]], int | None], Sequence[SearchHit]] | None = None


@dataclass(slots=True, frozen=True)
class HybridSearchContext:
    """Dependency overrides for :class:`HybridSearchEngine`."""

    capabilities: Capabilities | None = None
    registry: ChannelRegistry | None = None
    duckdb_manager: DuckDBManager | None = None
    providers: HybridSearchProviders | None = None


@dataclass(slots=True, frozen=True)
class _MethodStats:
    """Statistics about hybrid search execution method and parameters.

    This dataclass captures metadata about how hybrid search was executed,
    including fusion results, limits, FAISS parameters, and channel weights.
    Used for explainability and debugging, enabling analysis of search behavior
    and performance characteristics.

    Attributes
    ----------
    fused_count : int
        Number of documents successfully fused and returned in the final result set.
        May be less than limit if insufficient results were available.
    limit : int
        Maximum number of results requested. The fused_count indicates how many
        results were actually returned, which may be less than limit.
    faiss_k : int | None
        FAISS search parameter k (number of nearest neighbors retrieved). None
        indicates default k was used. Used for explainability and debugging.
    nprobe : int | None
        FAISS nprobe parameter (number of clusters to probe). None indicates default
        nprobe was used. Higher nprobe improves recall at the cost of latency.
    weights : Mapping[str, float]
        Channel weights used for fusion (RRF or pool). Maps channel names to their
        fusion weights, enabling analysis of how different channels contributed
        to final results.
    """

    fused_count: int
    limit: int
    faiss_k: int | None
    nprobe: int | None
    weights: Mapping[str, float]


@dataclass(slots=True, frozen=True)
class _FusionContext:
    """All inputs required to fuse dense and sparse channel runs."""

    query: str
    runs: dict[str, list[SearchHit]]
    warnings: Sequence[str]
    limit: int
    options: HybridSearchOptions
    budget_decision: BudgetDecision
    budget_info: Mapping[str, object]


@dataclass(slots=True, frozen=True)
class _FusionWork:
    """Resolved fusion parameters after pooler/weights are selected."""

    runs: Mapping[str, Sequence[SearchHit]]
    warnings: Sequence[str]
    limit: int
    runtime: HybridSearchTuning
    weights_used: Mapping[str, float]
    active_channels: Sequence[str]
    budget_info: Mapping[str, object]
    budget_decision: BudgetDecision


class HybridSearchEngine:
    """Combine dense (FAISS) and sparse channel plugins via RRF."""

    def __init__(
        self,
        settings: Settings,
        paths: ResolvedPaths,
        *,
        context: HybridSearchContext | None = None,
    ) -> None:
        """Initialize hybrid search engine.

        Parameters
        ----------
        settings : Settings
            Application settings.
        paths : ResolvedPaths
            Resolved application paths.
        context : HybridSearchContext | None, optional
            Optional context for dependency injection. If None, creates default context.
        """
        ctx = context or HybridSearchContext()
        self._settings = settings
        self._paths = paths
        self._capabilities = ctx.capabilities
        self._duckdb_manager = ctx.duckdb_manager
        self._providers = ctx.providers or HybridSearchProviders()
        if ctx.registry is None:
            channel_context = ChannelContext(
                settings=settings,
                paths=paths,
                capabilities=ctx.capabilities,
            )
            self._registry = ChannelRegistry.discover(channel_context)
        else:
            self._registry = ctx.registry
        self._pool_weights = self._compute_pool_weights()
        self._pooler = self._make_pooler()
        self._explain_last: dict[str, object] = {}

    def _make_stage_gate_config(self) -> StageGateConfig:
        """Create stage gate configuration for adaptive hybrid search budgets.

        This method constructs a StageGateConfig that defines adaptive search
        budgets based on query characteristics. The configuration includes default,
        literal, and vague query depth profiles, RRF parameters, and RM3 settings.
        Literal queries (code-like) get increased BM25 depth, while vague queries
        (natural language) get increased semantic and SPLADE depth. This enables
        adaptive resource allocation based on query type.

        Returns
        -------
        StageGateConfig
            Configuration object defining per-channel search depths, RRF parameters,
            and RM3 settings for adaptive hybrid search. The configuration enables
            the gating system to allocate search resources efficiently based on
            query characteristics.

        Notes
        -----
        Adaptive budgets improve search efficiency by allocating more resources
        to channels that are most effective for a given query type. Literal queries
        benefit from increased BM25 depth (keyword matching), while vague queries
        benefit from increased semantic and SPLADE depth (learned retrieval). The
        configuration is derived from settings and provides sensible defaults for
        all parameters.
        """
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
        """Create recency boost configuration from settings.

        This method constructs a RecencyConfig object from application settings,
        enabling time-based score boosting for recently modified documents. Recency
        boosting helps surface more recently updated code, which is often more
        relevant for developers searching for current implementations.

        Returns
        -------
        RecencyConfig
            Configuration object specifying recency boost parameters including
            enable flag, half-life period, maximum boost factor, and database
            table name for commit timestamps. The configuration is ready for use
            with apply_recency_boost.

        Notes
        -----
        Recency boosting applies exponential decay based on document modification
        time, with more recent documents receiving higher boosts. The half-life
        parameter controls how quickly the boost decays over time, while max_boost
        caps the maximum boost factor to prevent recency from overwhelming relevance.
        """
        return RecencyConfig(
            enabled=self._settings.index.recency_enabled,
            half_life_days=self._settings.index.recency_half_life_days,
            max_boost=self._settings.index.recency_max_boost,
            table=self._settings.index.recency_table,
        )

    @staticmethod
    def _profile_query(
        query: str,
        gate_cfg: StageGateConfig,
    ) -> tuple[BudgetDecision, dict[str, object]]:
        """Analyze query characteristics and determine adaptive search budgets.

        This static method performs query analysis to determine optimal search
        budgets for hybrid retrieval. The method analyzes query characteristics
        (code-like vs natural language, length, etc.) and selects appropriate
        per-channel depths and RRF parameters. The analysis enables adaptive
        resource allocation that improves both efficiency and effectiveness.

        Parameters
        ----------
        query : str
            Search query string to analyze. The query is examined for characteristics
            such as code-like patterns, length, and keyword density to determine
            optimal search strategy.
        gate_cfg : StageGateConfig
            Stage gate configuration defining depth profiles and parameters for
            different query types. Used to select appropriate budgets based on
            query analysis.

        Returns
        -------
        tuple[BudgetDecision, dict[str, object]]
            Tuple containing:
            - BudgetDecision specifying per-channel search depths and RRF parameters
              selected based on query analysis.
            - Dictionary of budget decision metadata for explainability, including
              query profile, selected budgets, and reasoning.

        Notes
        -----
        Query profiling enables adaptive hybrid search by allocating resources
        based on query characteristics. Code-like queries benefit from increased
        BM25 depth, while natural language queries benefit from increased semantic
        depth. The profiling process analyzes query patterns and selects budgets
        that optimize both recall and efficiency.
        """
        profile = analyze_query(query, gate_cfg)
        decision = decide_budgets(profile, gate_cfg)
        budget_info = describe_budget_decision(profile, decision)
        return decision, budget_info

    def _rrf_fuse(
        self,
        runs: Mapping[str, Sequence[SearchHit]],
        *,
        limit: int,
        rrf_k: int,
    ) -> tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]]]:
        """Fuse multiple channel runs using Reciprocal Rank Fusion (RRF).

        This method combines search results from multiple channels (semantic, BM25,
        SPLADE) using RRF, which aggregates scores based on reciprocal rank positions.
        RRF is rank-based rather than score-based, making it robust to different score
        distributions across channels. Each document's RRF score is the sum of
        1/(rrf_k + rank) across all channels where it appears, enabling effective
        fusion of heterogeneous retrieval systems.

        Parameters
        ----------
        runs : Mapping[str, Sequence[SearchHit]]
            Dictionary mapping channel names to their search result lists. Each
            channel's results are ranked by relevance score (highest first).
        limit : int
            Maximum number of fused results to return. The top-ranked documents
            by RRF score are selected up to this limit.
        rrf_k : int
            RRF smoothing parameter that controls how rank differences affect scores.
            Higher values reduce the impact of rank position, making fusion more
            uniform. Typical values range from 10 to 100.

        Returns
        -------
        tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]]]
            Tuple containing:
            - List of HybridResultDoc objects ranked by RRF score (highest first),
              limited to the specified limit.
            - Dictionary mapping document IDs to their channel contributions, where
              each contribution is a tuple of (channel_name, rank, score).

        Notes
        -----
        RRF is particularly effective for hybrid retrieval because it doesn't require
        score normalization and works well with heterogeneous scoring systems. The
        method aggregates scores across channels and ranks documents by their combined
        RRF scores, enabling effective fusion of dense and sparse retrieval results.
        """
        aggregated: dict[str, float] = {}
        for hits in runs.values():
            for hit in hits:
                doc_id = str(hit.doc_id)
                aggregated.setdefault(doc_id, 0.0)
                aggregated[doc_id] += 1.0 / (rrf_k + hit.rank + 1)
        ranked = sorted(aggregated.items(), key=lambda item: item[1], reverse=True)[:limit]
        docs = [HybridResultDoc(doc_id=doc_id, score=score) for doc_id, score in ranked]
        contributions = self._build_contribution_map(runs)
        contributions_for_docs = {doc.doc_id: contributions.get(doc.doc_id, []) for doc in docs}
        return docs, contributions_for_docs

    def _fuse_runs(self, ctx: _FusionContext) -> HybridSearchResult:
        """Fuse channel runs and produce final hybrid search result.

        This method orchestrates the fusion process by selecting the appropriate
        pooler and weights, applying extra channels, executing fusion (RRF or pool),
        and applying recency boosting if enabled. The method handles the complete
        fusion pipeline from raw channel runs to final ranked results with
        explainability metadata.

        Parameters
        ----------
        ctx : _FusionContext
            Fusion context containing all inputs required for fusion: query, channel
            runs, warnings, limits, options, budget decision, and budget info. The
            context encapsulates all fusion parameters in a single immutable object.

        Returns
        -------
        HybridSearchResult
            Complete hybrid search result with fused documents, per-document channel
            contributions, active channels, warnings, and method metadata. The result
            includes explainability information about how fusion was performed.

        Notes
        -----
        This method is the central fusion orchestrator, coordinating pooler selection,
        weight resolution, fusion execution, and post-processing (recency boosting).
        The method ensures all fusion steps are executed in the correct order and
        that explainability metadata is properly captured for debugging and analysis.
        """
        pooler, weights_used = self._select_pooler(ctx.options)
        runs = self._apply_extra_channels(ctx.runs, ctx.options.extra_channels)
        active_channels = self._resolve_active_channels(runs)
        runtime = ctx.options.tuning or HybridSearchTuning()
        work = _FusionWork(
            runs=runs,
            warnings=ctx.warnings,
            limit=ctx.limit,
            runtime=runtime,
            weights_used=weights_used,
            active_channels=active_channels,
            budget_info=ctx.budget_info,
            budget_decision=ctx.budget_decision,
        )
        docs, contributions_for_docs, method = self._execute_fusion(
            work=work,
            pooler=pooler,
        )
        docs = self._apply_recency_boost_if_needed(docs)
        self._explain_last = method
        return HybridSearchResult(
            docs=docs,
            contributions=contributions_for_docs,
            channels=active_channels,
            warnings=list(ctx.warnings),
            method=method,
        )

    @staticmethod
    def _apply_extra_channels(
        runs: dict[str, list[SearchHit]],
        extra_channels: Mapping[str, Sequence[SearchHit]] | None,
    ) -> dict[str, list[SearchHit]]:
        """Merge extra channel results into the main channel runs dictionary.

        This static method adds or overrides channel results from the extra_channels
        mapping into the main runs dictionary. Extra channels enable external
        retrieval systems to contribute results to hybrid fusion, supporting
        extensibility and integration with custom retrieval pipelines.

        Parameters
        ----------
        runs : dict[str, list[SearchHit]]
            Main dictionary of channel runs from standard retrieval channels (semantic,
            BM25, SPLADE). This dictionary is updated with extra channel results.
        extra_channels : Mapping[str, Sequence[SearchHit]] | None
            Optional mapping of additional channel names to their search results.
            If provided, these channels are merged into runs, overriding any
            existing channels with the same name. Empty sequences are ignored.

        Returns
        -------
        dict[str, list[SearchHit]]
            Updated runs dictionary containing both standard and extra channel results.
            Channels from extra_channels override existing channels with the same name.
            The dictionary is ready for fusion operations.

        Notes
        -----
        Extra channels enable flexible hybrid search by allowing external retrieval
        systems to contribute results. This is useful for integrating custom search
        pipelines, domain-specific retrievers, or experimental channels. The method
        preserves the original runs dictionary structure while adding or overriding
        channels as specified.
        """
        if not extra_channels:
            return runs
        updated = dict(runs)
        for name, hits in extra_channels.items():
            if hits:
                updated[name] = list(hits)
        return updated

    @staticmethod
    def _resolve_active_channels(runs: Mapping[str, Sequence[SearchHit]]) -> list[str]:
        """Identify channels that produced non-empty search results.

        This static method determines which channels successfully returned results
        by checking for non-empty hit lists. Active channels are those that
        contributed to the final fusion result, enabling explainability and
        debugging. If no channels produced results, defaults to ["semantic"] to
        ensure at least one channel is reported.

        Parameters
        ----------
        runs : Mapping[str, Sequence[SearchHit]]
            Dictionary mapping channel names to their search result lists. Channels
            with empty lists are considered inactive.

        Returns
        -------
        list[str]
            List of channel names that produced non-empty results, ordered by
            appearance in runs. Returns ["semantic"] if no channels produced results,
            ensuring at least one channel is always reported for explainability.

        Notes
        -----
        Active channel identification is important for explainability and debugging,
        as it shows which retrieval systems contributed to the final results. The
        method ensures that at least one channel is always reported, even when all
        channels fail, to maintain consistent result structure.
        """
        return [channel for channel, hits in runs.items() if hits] or ["semantic"]

    def _execute_fusion(
        self,
        *,
        work: _FusionWork,
        pooler: HybridPoolEvaluator,
    ) -> tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]], dict[str, object]]:
        """Execute fusion using RRF or pool-based methods based on configuration.

        This method performs the actual fusion operation, selecting between RRF
        (Reciprocal Rank Fusion) and pool-based fusion based on settings. RRF is
        rank-based and works well for heterogeneous score distributions, while pool
        fusion uses learned similarity thresholds and weighted blending. The method
        handles empty runs gracefully and composes method metadata for explainability.

        Parameters
        ----------
        work : _FusionWork
            Resolved fusion work object containing all fusion parameters: channel
            runs, warnings, limits, runtime tuning, weights, active channels, and
            budget information. The work object encapsulates all fusion inputs.
        pooler : HybridPoolEvaluator
            Pool evaluator for pool-based fusion. Used when hybrid_use_rrf is False.
            The pooler applies learned similarity thresholds and weighted blending
            to combine channel results.

        Returns
        -------
        tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]], dict[str, object]]
            Tuple containing:
            - List of fused HybridResultDoc objects ranked by fusion score.
            - Dictionary mapping document IDs to channel contributions.
            - Method metadata dictionary explaining how fusion was performed,
              including fusion type, statistics, and budget information.

        Notes
        -----
        The method selects fusion strategy based on settings.hybrid_use_rrf, enabling
        flexible fusion configuration. RRF is simpler and more robust to score
        variations, while pool fusion provides more sophisticated blending with
        learned thresholds. Both methods produce ranked results with explainability
        metadata for debugging and analysis.
        """
        stats = self._method_stats(0, work.limit, work.runtime, work.weights_used)
        fusion_type = "rrf" if self._settings.index.hybrid_use_rrf else "pool"
        if not work.runs:
            method = self._compose_method_metadata(
                work.active_channels,
                work.warnings,
                stats=stats,
                fusion={"type": fusion_type},
                budget=work.budget_info,
            )
            return [], {}, method

        if self._settings.index.hybrid_use_rrf:
            docs, contributions_for_docs = self._run_rrf(
                work.runs,
                limit=work.limit,
                rrf_k=work.budget_decision.rrf_k,
            )
            method = self._compose_method_metadata(
                work.active_channels,
                work.warnings,
                stats=self._method_stats(len(docs), work.limit, work.runtime, work.weights_used),
                fusion={"type": "rrf", "K": work.budget_decision.rrf_k},
                budget=work.budget_info,
            )
            return docs, contributions_for_docs, method

        docs, contributions_for_docs = self._run_pool(
            work.runs,
            pooler=pooler,
            limit=work.limit,
        )
        method = self._compose_method_metadata(
            work.active_channels,
            work.warnings,
            stats=self._method_stats(len(docs), work.limit, work.runtime, work.weights_used),
            fusion={"type": "pool"},
            budget=work.budget_info,
        )
        return docs, contributions_for_docs, method

    def _run_rrf(
        self,
        runs: Mapping[str, Sequence[SearchHit]],
        *,
        limit: int,
        rrf_k: int,
    ) -> tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]]]:
        """Execute RRF fusion and return fused results with contributions.

        This method is a convenience wrapper around _rrf_fuse that provides a
        consistent interface for RRF-based fusion. It delegates to _rrf_fuse to
        perform the actual fusion and returns the results in the standard format
        expected by the fusion pipeline.

        Parameters
        ----------
        runs : Mapping[str, Sequence[SearchHit]]
            Dictionary mapping channel names to their search result lists. Each
            channel's results are ranked by relevance score.
        limit : int
            Maximum number of fused results to return.
        rrf_k : int
            RRF smoothing parameter controlling rank sensitivity.

        Returns
        -------
        tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]]]
            Tuple containing fused documents and channel contributions, as returned
            by _rrf_fuse.

        Notes
        -----
        This method provides a clean interface for RRF fusion execution, separating
        the fusion logic from the orchestration code. The method ensures consistent
        return format for integration with the broader fusion pipeline.
        """
        docs, contributions_for_docs = self._rrf_fuse(
            runs,
            limit=limit,
            rrf_k=rrf_k,
        )
        return docs, contributions_for_docs

    def _run_pool(
        self,
        runs: Mapping[str, Sequence[SearchHit]],
        *,
        pooler: HybridPoolEvaluator,
        limit: int,
    ) -> tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]]]:
        """Execute pool-based fusion using learned similarity thresholds.

        This method performs pool-based fusion by flattening channel hits into a
        unified pool, applying learned similarity thresholds and weighted blending
        via the pooler, and returning ranked results. Pool fusion uses score-based
        blending with learned thresholds, enabling more sophisticated fusion than
        rank-based RRF when score distributions are well-calibrated.

        Parameters
        ----------
        runs : Mapping[str, Sequence[SearchHit]]
            Dictionary mapping channel names to their search result lists. Results
            are flattened into a unified pool for fusion.
        pooler : HybridPoolEvaluator
            Pool evaluator that applies learned similarity thresholds and weighted
            blending. The pooler filters and ranks documents based on blended scores
            and channel weights.
        limit : int
            Maximum number of fused results to return. The pooler selects top-k
            documents based on blended scores.

        Returns
        -------
        tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]]]
            Tuple containing:
            - List of HybridResultDoc objects ranked by blended pool scores.
            - Dictionary mapping document IDs to channel contributions, showing
              how each channel contributed to the final ranking.

        Notes
        -----
        Pool-based fusion provides more sophisticated blending than RRF by using
        learned similarity thresholds and weighted score combination. The method
        flattens all channel hits into a unified pool, applies the pooler's blending
        logic, and returns ranked results with contribution tracking for explainability.
        """
        flattened = self._flatten_hits_for_pool(runs)
        contributions = self._build_contribution_map(runs)
        if not flattened:
            return [], {}
        pooled_hits = pooler.pool(flattened, k=limit)
        docs = [
            HybridResultDoc(doc_id=pooled.doc_id, score=pooled.blended_score)
            for pooled in pooled_hits
        ]
        contributions_for_docs = {doc.doc_id: contributions.get(doc.doc_id, []) for doc in docs}
        return docs, contributions_for_docs

    def _apply_recency_boost_if_needed(
        self,
        docs: list[HybridResultDoc],
    ) -> list[HybridResultDoc]:
        """Apply recency boost to search results if enabled in configuration.

        This method conditionally applies time-based score boosting to search
        results based on document modification times. Recency boosting helps
        surface recently updated code, which is often more relevant for developers.
        The boosting uses exponential decay based on modification time, with more
        recent documents receiving higher boosts.

        Parameters
        ----------
        docs : list[HybridResultDoc]
            List of search results to potentially boost. The list is modified
            in-place if recency boosting is enabled and applicable.

        Returns
        -------
        list[HybridResultDoc]
            List of search results with recency boosts applied if enabled. If
            recency is disabled or no documents are provided, returns the input
            list unchanged. Results are re-ranked by boosted scores.

        Notes
        -----
        Recency boosting is applied after fusion to ensure it affects the final
        ranking. The method checks configuration and document availability before
        applying boosts, ensuring efficient operation when recency is disabled.
        Boosting uses commit timestamps from DuckDB to determine document age.
        """
        recency_cfg = self._recency_config()
        if not recency_cfg.enabled or not docs:
            return docs
        boosted_docs, _ = apply_recency_boost(
            docs,
            recency_cfg,
            duckdb_manager=self._duckdb_manager,
        )
        return boosted_docs

    def search(
        self,
        query: str,
        *,
        semantic_hits: Sequence[tuple[int, float]],
        limit: int,
        options: HybridSearchOptions | None = None,
    ) -> HybridSearchResult:
        """Fuse dense and sparse retrieval results for ``query`` using adaptive budgets.

        Parameters
        ----------
        query : str
            Natural language or code search query.
        semantic_hits : Sequence[tuple[int, float]]
            Dense FAISS hits expressed as ``(chunk_id, score)`` pairs.
        limit : int
            Maximum number of fused results to return.
        options : HybridSearchOptions | None, optional
            Optional overrides for channel weights, additional channels, and FAISS
            runtime metadata.

        Returns
        -------
        HybridSearchResult
            Structured result set containing fused documents, per-document channel
            contributions, warnings, and explainability metadata.
        """
        opts = options or HybridSearchOptions()
        normalized_hits, readiness_warnings = self._filter_semantic_hits(
            semantic_hits,
            faiss_ready=opts.faiss_ready,
        )
        result = self._execute_hybrid_search(
            query=query,
            semantic_hits=normalized_hits,
            limit=limit,
            options=opts,
        )
        method_payload = result.method
        enriched = HybridSearchResult(
            docs=result.docs,
            contributions=result.contributions,
            channels=result.channels,
            warnings=result.warnings,
            method=method_payload,
        )
        if readiness_warnings:
            enriched = HybridSearchResult(
                docs=enriched.docs,
                contributions=enriched.contributions,
                channels=enriched.channels,
                warnings=[*readiness_warnings, *enriched.warnings],
                method=enriched.method,
            )
        return enriched

    def _execute_hybrid_search(
        self,
        *,
        query: str,
        semantic_hits: Sequence[tuple[int, float]],
        limit: int,
        options: HybridSearchOptions,
    ) -> HybridSearchResult:
        """Execute the complete hybrid search pipeline with adaptive budgets.

        This method orchestrates the full hybrid search process: query profiling
        for adaptive budgets, gathering channel hits, and fusing results. The
        method performs query analysis to determine optimal search depths and RRF
        parameters, collects results from all enabled channels, and fuses them
        into a final ranked result set.

        Parameters
        ----------
        query : str
            Search query string to execute across all channels. The query is
            analyzed for characteristics to determine adaptive budgets.
        semantic_hits : Sequence[tuple[int, float]]
            Pre-computed dense retrieval hits from FAISS. These hits are converted
            to SearchHit objects and included in the semantic channel.
        limit : int
            Maximum number of fused results to return. The final result set is
            limited to this number of documents.
        options : HybridSearchOptions
            Search options including extra channels, weight overrides, tuning
            parameters, and FAISS readiness flag. Options enable runtime
            customization of search behavior.

        Returns
        -------
        HybridSearchResult
            Complete hybrid search result with fused documents, channel contributions,
            active channels, warnings, and method metadata. The result includes
            explainability information about query profiling, budget decisions, and
            fusion strategy.

        Notes
        -----
        This method is the core hybrid search executor, coordinating query analysis,
        multi-channel retrieval, and fusion. The method enables adaptive resource
        allocation based on query characteristics, improving both efficiency and
        effectiveness. All steps are executed with error handling and warning
        collection to ensure robust operation.
        """
        gate_cfg = self._make_stage_gate_config()
        budget_decision, budget_info = self._profile_query(query, gate_cfg)
        runs, warnings = self._gather_channel_hits(
            query,
            semantic_hits,
            channel_limits=budget_decision.per_channel_depths,
        )
        ctx = _FusionContext(
            query=query,
            runs=runs,
            warnings=warnings,
            limit=limit,
            options=options,
            budget_decision=budget_decision,
            budget_info=budget_info,
        )
        return self._fuse_runs(ctx)

    def _gather_channel_hits(
        self,
        query: str,
        semantic_hits: Sequence[tuple[int, float]],
        *,
        channel_limits: Mapping[str, int] | None = None,
    ) -> tuple[dict[str, list[SearchHit]], list[str]]:
        """Collect per-channel search hits and warnings for ``query``.

        This internal method coordinates retrieval across all enabled channels,
        collecting results from semantic (FAISS), BM25, and SPLADE channels.
        Each channel is queried independently, and errors are captured as warnings
        rather than exceptions to ensure robust multi-channel retrieval.

        The semantic channel is always included (converting IDs and scores to
        SearchHit objects). BM25 and SPLADE channels are conditionally enabled
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
        channel_limits : Mapping[str, int] | None, optional
            Optional per-channel depth overrides derived from budget decisions.
            Keys correspond to channel names (e.g., "semantic", "bm25"). When
            provided, each channel fetches at most the specified number of hits.

        Returns
        -------
        tuple[dict[str, list[SearchHit]], list[str]]
            Tuple containing:
            - Dictionary mapping channel identifiers ("semantic", "bm25", "splade")
              to lists of SearchHit objects. Only channels that successfully
              returned results are included.
            - List of warning messages accumulated during channel retrieval. Includes
              initialization errors, search failures, and availability issues.
        """
        runs: dict[str, list[SearchHit]] = {}

        semantic_limit = channel_limits.get("semantic") if channel_limits else None
        semantic_channel_hits = self._build_semantic_channel_hits(
            semantic_hits, limit=semantic_limit
        )
        if semantic_channel_hits:
            runs["semantic"] = semantic_channel_hits

        warnings: list[str] = []
        default_limit = self._settings.index.hybrid_top_k_per_channel
        for channel in self._registry.channels():
            limit = default_limit
            if channel_limits and channel.name in channel_limits:
                limit = channel_limits[channel.name]
            hits, warning = self._collect_channel_hits(channel, query, limit)
            if warning:
                warnings.append(warning)
            if hits:
                runs[channel.name] = hits

        return runs, warnings

    def _channel_disabled_reason(self, channel: Channel) -> str | None:
        """Determine if a channel is disabled and return the reason.

        This method checks whether a channel is disabled based on settings and
        configuration. Channels can be disabled globally (via settings) or
        individually (via channel-specific flags). The method returns a reason
        string if disabled, or None if the channel is enabled.

        Parameters
        ----------
        channel : Channel
            Channel to check for disabled status. The channel's name is used
            to look up relevant settings flags.

        Returns
        -------
        str | None
            Disabled reason string ("disabled") if the channel is disabled,
            or None if the channel is enabled and should be used. The reason
            string can be used for logging and explainability.

        Notes
        -----
        Channel disabling enables fine-grained control over which retrieval
        systems participate in hybrid search. BM25 and SPLADE channels can be
        disabled independently, allowing fallback to semantic-only search when
        sparse indexes are unavailable or undesired.
        """
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
        """Identify capabilities required by a channel that are not available.

        This method checks whether a channel's required capabilities are satisfied
        by the current system capabilities. Channels can declare capability
        requirements (e.g., "faiss", "bm25_index") that must be available for
        the channel to function. Missing capabilities prevent channel execution.

        Parameters
        ----------
        channel : Channel
            Channel to check for capability requirements. The channel's requires
            attribute specifies which capabilities are needed.

        Returns
        -------
        set[str]
            Set of capability names that are required by the channel but not
            available in the current system. Empty set indicates all required
            capabilities are available. Capability names correspond to attributes
            on the Capabilities object.

        Notes
        -----
        Capability checking enables graceful degradation when optional components
        are unavailable. Channels that require unavailable capabilities are skipped
        rather than causing errors, ensuring robust hybrid search operation even
        when some retrieval systems are missing.
        """
        if not channel.requires or self._capabilities is None:
            return set()
        missing: set[str] = set()
        for requirement in channel.requires:
            if not bool(getattr(self._capabilities, requirement, False)):
                missing.add(requirement)
        return missing

    def _channel_override(
        self,
        name: str,
    ) -> Callable[[str, int], Sequence[SearchHit]] | None:
        """Get provider override function for a channel if available.

        This method retrieves custom provider functions that override default
        channel implementations. Provider overrides enable injection of custom
        retrieval logic for testing, integration, or specialized use cases.
        Overrides take precedence over default channel implementations.

        Parameters
        ----------
        name : str
            Channel name to look up override for. Supported names are "bm25"
            and "splade". Other channel names return None.

        Returns
        -------
        Callable[[str, int], Sequence[SearchHit]] | None
            Provider override function if available, or None if no override
            is configured. The function takes (query, limit) and returns
            SearchHit objects. Returns None for unsupported channel names or
            when no override is configured.

        Notes
        -----
        Provider overrides enable flexible channel implementation injection,
        supporting testing with mock providers and integration with external
        retrieval systems. Overrides are checked before default channel
        implementations, allowing complete replacement of channel behavior.
        """
        if name == "bm25":
            return self._providers.bm25
        if name == "splade":
            return self._providers.splade
        return None

    def _collect_channel_hits(
        self,
        channel: Channel,
        query: str,
        limit: int,
    ) -> tuple[list[SearchHit], str | None]:
        """Collect search hits from a channel with error handling and validation.

        This method executes search on a channel, handling disabled channels,
        missing capabilities, provider overrides, and errors gracefully. The
        method checks channel availability before execution and captures errors
        as warnings rather than exceptions, ensuring robust multi-channel retrieval.

        Parameters
        ----------
        channel : Channel
            Channel to execute search on. The channel's search method is called
            if the channel is enabled and capabilities are available.
        query : str
            Search query string to pass to the channel's search method.
        limit : int
            Maximum number of results to request from the channel.

        Returns
        -------
        tuple[list[SearchHit], str | None]
            Tuple containing:
            - List of SearchHit objects from the channel, or empty list if the
              channel is disabled, missing capabilities, or encounters an error.
            - Warning message string if an error occurred, or None if search
              succeeded or channel was intentionally skipped.

        Notes
        -----
        This method provides robust channel execution with comprehensive error
        handling. Disabled channels and missing capabilities result in empty
        results without warnings, while execution errors are captured as warnings
        for explainability. Provider overrides take precedence over default
        channel implementations, enabling flexible testing and integration.
        """
        disabled_reason = self._channel_disabled_reason(channel)
        if disabled_reason is not None:
            return [], None
        missing = self._missing_capabilities(channel)
        if missing:
            return [], None
        override = self._channel_override(channel.name)
        if override is not None:
            hits = list(override(query, limit))
            return hits, None
        try:
            hits = list(channel.search(query, limit))
        except ChannelError as exc:
            warning = str(exc)
            return [], warning
        except (OSError, RuntimeError, ValueError, ImportError) as exc:  # pragma: no cover
            warning = f"{channel.name} channel failed: {exc}"
            return [], warning
        return hits, None

    @staticmethod
    def _with_stage_metadata(
        method: Mapping[str, object] | None,
        stages: Sequence[dict[str, object]],
    ) -> Mapping[str, object] | None:
        """Merge stage metadata into method metadata dictionary.

        This static method adds stage information to method metadata, enabling
        explainability about multi-stage search execution. Stage metadata
        describes individual stages of the search pipeline (e.g., initial
        retrieval, reranking, fusion) and their characteristics.

        Parameters
        ----------
        method : Mapping[str, object] | None
            Existing method metadata dictionary to merge stages into. If None,
            a new dictionary is created with only the stages key.
        stages : Sequence[dict[str, object]]
            Sequence of stage metadata dictionaries describing individual search
            stages. Each dictionary contains stage-specific information such as
            stage name, parameters, and results.

        Returns
        -------
        Mapping[str, object] | None
            Updated method metadata dictionary with stages key added, or None
            if both inputs are None/empty. The stages are stored as a list
            under the "stages" key.

        Notes
        -----
        Stage metadata enables detailed explainability for multi-stage search
        pipelines, showing how results flow through different stages (initial
        retrieval, reranking, fusion). The method preserves existing metadata
        while adding stage information, enabling comprehensive result explanation.
        """
        if not stages:
            return method
        merged = dict(method) if method else {}
        merged["stages"] = list(stages)
        return merged

    def resolve_path(
        self,
        value: str,
        *,
        path_expander: Callable[[Path], Path] | None = None,
    ) -> Path:
        """Resolve a path string to an absolute Path.

        Parameters
        ----------
        value : str
            Path string that may be absolute, relative, or use ~ expansion.
        path_expander : Callable[[Path], Path] | None, optional
            Custom path expander applied before resolution. Defaults to ``Path.expanduser``.

        Returns
        -------
        Path
            Absolute resolved path. If input is absolute, returns as-is.
            If relative, resolves relative to repository root.
        """
        expander = path_expander or (lambda candidate: candidate.expanduser())
        candidate = expander(Path(value))
        if candidate.is_absolute():
            return candidate
        return (self._paths.repo_root / candidate).resolve()

    def _build_semantic_channel_hits(
        self,
        hits: Sequence[tuple[int, float]],
        *,
        limit: int | None = None,
    ) -> list[SearchHit]:
        """Convert FAISS semantic hits into SearchHit objects for fusion.

        This method transforms dense retrieval results (chunk IDs and scores)
        into SearchHit objects compatible with the hybrid fusion pipeline. The
        method supports provider overrides for custom semantic hit processing
        and applies limits to control result set size.

        Parameters
        ----------
        hits : Sequence[tuple[int, float]]
            Sequence of (chunk_id, score) pairs from FAISS semantic search.
            Results should be ranked by score (highest first).
        limit : int | None, optional
            Maximum number of hits to include. If None, uses the configured
            hybrid_top_k_per_channel setting. Limits are applied before
            conversion to SearchHit objects.

        Returns
        -------
        list[SearchHit]
            List of SearchHit objects representing semantic retrieval results.
            Each hit includes document ID, rank, score, source ("semantic"),
            and explainability metadata. Results are limited to the specified
            limit or default channel depth.

        Notes
        -----
        This method bridges dense retrieval (FAISS) with the hybrid fusion
        pipeline by converting FAISS results into the standard SearchHit format.
        Provider overrides enable custom semantic hit processing for testing or
        specialized use cases. The method ensures semantic hits are properly
        formatted for fusion with sparse retrieval results.
        """
        provider = self._providers.semantic
        if provider is not None:
            provided = provider(hits, limit)
            return list(provided)
        limit = limit or self._settings.index.hybrid_top_k_per_channel
        top_k = min(len(hits), limit) or len(hits)
        semantic_hits: list[SearchHit] = []
        for rank, (chunk_id, score) in enumerate(hits[:top_k]):
            semantic_hits.append(
                SearchHit(
                    doc_id=str(chunk_id),
                    rank=rank,
                    score=float(score),
                    source="semantic",
                    explain={"semantic_score": float(score)},
                )
            )
        return semantic_hits

    def _compute_pool_weights(self) -> dict[str, float]:
        """Compute default channel weights for pool-based fusion.

        This method determines default fusion weights for all supported channels
        (semantic, BM25, SPLADE, warp, xtr) by combining base weights with
        configuration overrides. Default weights are 1.0 for all channels,
        providing equal contribution unless overridden by settings.

        Returns
        -------
        dict[str, float]
            Dictionary mapping channel names to their fusion weights. Default
            weights are 1.0 for all channels, with configuration overrides
            applied from settings.index.rrf_weights. Weights control how much
            each channel contributes to final fusion scores.

        Notes
        -----
        Channel weights enable fine-tuning of fusion behavior by controlling
        the relative contribution of each retrieval system. Higher weights
        increase a channel's influence on final rankings. Default weights
        provide balanced fusion, while configuration overrides enable optimization
        for specific use cases or query types.
        """
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
        """Resolve final pool weights by combining defaults, extra channels, and overrides.

        This method computes final fusion weights by starting with default weights,
        adding weights for extra channels (defaulting to 1.0), and applying runtime
        overrides. The resolution order ensures that overrides take precedence while
        maintaining defaults for unspecified channels.

        Parameters
        ----------
        weights_override : Mapping[str, float] | None, optional
            Runtime weight overrides to apply. These overrides take precedence
            over default weights and are merged into the final weight dictionary.
        extra_channels : Sequence[str] | None, optional
            Additional channel names that should be included in the weight dictionary.
            Extra channels receive default weight 1.0 if not specified in overrides.

        Returns
        -------
        dict[str, float]
            Final weight dictionary combining defaults, extra channels, and overrides.
            All channels (standard and extra) are included with appropriate weights.
            Override weights take precedence over defaults.

        Notes
        -----
        Weight resolution enables flexible fusion configuration at runtime while
        maintaining sensible defaults. Extra channels are automatically included
        with default weights, ensuring they participate in fusion even without
        explicit weight specification. Overrides enable per-query weight adjustment
        for optimization or experimentation.
        """
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
        """Create a HybridPoolEvaluator with resolved weights and similarity threshold.

        This method constructs a pool evaluator for pool-based fusion using resolved
        channel weights and configured similarity threshold. The pooler applies
        learned similarity thresholds and weighted blending to combine channel results,
        enabling sophisticated fusion beyond simple rank-based methods.

        Parameters
        ----------
        weights_override : Mapping[str, float] | None, optional
            Runtime weight overrides to apply when resolving pool weights. These
            overrides are combined with defaults and extra channel weights.
        extra_channels : Sequence[str] | None, optional
            Additional channel names to include in weight resolution. Extra channels
            receive default weight 1.0 if not specified in overrides.

        Returns
        -------
        HybridPoolEvaluator
            Pool evaluator configured with resolved weights and similarity threshold.
            The pooler is ready to fuse channel results using learned thresholds
            and weighted blending.

        Notes
        -----
        Pool evaluator creation involves resolving weights (combining defaults,
        extra channels, and overrides) and retrieving the similarity threshold
        from settings. The pooler uses these parameters to filter and rank documents
        based on blended scores, providing more sophisticated fusion than rank-based
        RRF when score distributions are well-calibrated.
        """
        weights = self._resolve_pool_weights(weights_override, extra_channels)
        threshold = getattr(self._settings.index, "semantic_min_score", 0.0)
        return HybridPoolEvaluator(weights=weights, sim_threshold=threshold)

    def _select_pooler(
        self,
        options: HybridSearchOptions,
    ) -> tuple[HybridPoolEvaluator, Mapping[str, float]]:
        """Select appropriate pooler and weights based on search options.

        This method determines which pool evaluator to use and what weights to
        apply based on search options. If options specify extra channels or weight
        overrides, a new pooler is created with updated weights. Otherwise, the
        default pooler is reused for efficiency.

        Parameters
        ----------
        options : HybridSearchOptions
            Search options containing optional weight overrides and extra channels.
            Options enable runtime customization of fusion behavior without
            modifying the engine's default configuration.

        Returns
        -------
        tuple[HybridPoolEvaluator, Mapping[str, float]]
            Tuple containing:
            - Pool evaluator to use for fusion (either default or newly created
              with updated weights).
            - Final weight dictionary used by the pooler, including defaults,
              extra channels, and overrides.

        Notes
        -----
        Pooler selection optimizes for both flexibility and efficiency. When
        options don't require weight changes, the default pooler is reused to
        avoid unnecessary object creation. When options specify custom weights
        or extra channels, a new pooler is created with updated configuration.
        This approach balances runtime customization with performance.
        """
        extra_channels = tuple((options.extra_channels or {}).keys())
        weights = self._resolve_pool_weights(options.weights, extra_channels)
        if extra_channels or options.weights is not None:
            pooler = self._make_pooler(options.weights, extra_channels=extra_channels)
        else:
            pooler = self._pooler
        return pooler, weights

    @staticmethod
    def _method_stats(
        fused_count: int,
        limit: int,
        runtime: HybridSearchTuning,
        weights: Mapping[str, float],
    ) -> _MethodStats:
        """Create method statistics object for explainability metadata.

        This static method constructs a _MethodStats object capturing execution
        statistics about hybrid search execution. The statistics include fusion
        results, limits, FAISS parameters, and channel weights, enabling detailed
        explainability and debugging of search behavior.

        Parameters
        ----------
        fused_count : int
            Number of documents successfully fused and returned in the final result.
            May be less than limit if insufficient results were available.
        limit : int
            Maximum number of results requested. Used to compute coverage metrics
            and understand result completeness.
        runtime : HybridSearchTuning
            Runtime tuning parameters including FAISS k and nprobe values. These
            parameters are extracted for explainability metadata.
        weights : Mapping[str, float]
            Channel weights used for fusion. Captured for explainability to show
            how different channels contributed to final results.

        Returns
        -------
        _MethodStats
            Statistics object containing all execution metadata for explainability.
            The object is used to compose method metadata dictionaries that describe
            how search was performed.

        Notes
        -----
        Method statistics enable comprehensive explainability by capturing all
        relevant execution parameters. The statistics are included in result
        metadata, enabling analysis of search behavior, performance characteristics,
        and fusion effectiveness. This information is valuable for debugging,
        optimization, and understanding system behavior.
        """
        return _MethodStats(
            fused_count=fused_count,
            limit=limit,
            faiss_k=runtime.k,
            nprobe=runtime.nprobe,
            weights=weights,
        )

    @staticmethod
    def _flatten_hits_for_pool(runs: Mapping[str, Sequence[SearchHit]]) -> list[Hit]:
        """Flatten channel runs into a unified pool format for pool-based fusion.

        This static method converts channel-specific SearchHit objects into a
        unified Hit format required by the pool evaluator. The flattening process
        preserves all hit metadata (scores, ranks, explanations) while standardizing
        the format across channels. Each hit is tagged with its source channel for
        contribution tracking.

        Parameters
        ----------
        runs : Mapping[str, Sequence[SearchHit]]
            Dictionary mapping channel names to their search result lists. Each
            channel's hits are converted to Hit objects with source channel
            information preserved.

        Returns
        -------
        list[Hit]
            Flattened list of Hit objects from all channels, ready for pool-based
            fusion. Each hit includes document ID, score, source channel, and
            metadata extracted from the original SearchHit's explain dictionary.

        Notes
        -----
        Hit flattening enables pool-based fusion by converting heterogeneous
        SearchHit objects into a unified format. The pool evaluator operates
        on this unified format, applying learned thresholds and weighted blending
        to produce final rankings. Source channel information is preserved for
        contribution tracking and explainability.
        """
        flattened: list[Hit] = []
        for source, hits in runs.items():
            for hit in hits:
                meta_payload: dict[str, object] = {"score": float(hit.score), "rank": hit.rank}
                if hit.explain:
                    meta_payload.update(hit.explain)
                flattened.append(
                    Hit(
                        doc_id=str(hit.doc_id),
                        score=float(hit.score),
                        source=source,
                        meta=meta_payload,
                    )
                )
        return flattened

    @staticmethod
    def _build_contribution_map(
        runs: Mapping[str, Sequence[SearchHit]],
    ) -> dict[str, list[tuple[str, int, float]]]:
        """Build a map of document contributions from each channel.

        This static method creates a contribution map showing how each document
        was ranked and scored by each channel. The map enables explainability
        by showing which channels found each document and at what rank/score,
        helping users understand why documents appear in results.

        Parameters
        ----------
        runs : Mapping[str, Sequence[SearchHit]]
            Dictionary mapping channel names to their search result lists. Each
            channel's hits are analyzed to extract document contributions.

        Returns
        -------
        dict[str, list[tuple[str, int, float]]]
            Dictionary mapping document IDs to lists of channel contributions.
            Each contribution is a tuple of (channel_name, rank, score) showing
            how the document was ranked by that channel. Documents appearing in
            multiple channels have multiple contributions.

        Notes
        -----
        Contribution maps enable detailed explainability by showing how each
        channel contributed to final results. This information helps users
        understand why documents appear in results and which retrieval systems
        found them. The map is included in HybridSearchResult for comprehensive
        result explanation.
        """
        contributions: dict[str, list[tuple[str, int, float]]] = {}
        for channel, hits in runs.items():
            for hit in hits:
                contributions.setdefault(hit.doc_id, []).append(
                    (channel, hit.rank + 1, float(hit.score))
                )
        return contributions

    def _compose_method_metadata(
        self,
        active_channels: Sequence[str],
        warnings: Sequence[str],
        stats: _MethodStats,
        fusion: Mapping[str, object] | None = None,
        budget: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Compose comprehensive method metadata dictionary for explainability.

        This method assembles a complete method metadata dictionary describing
        how hybrid search was executed. The metadata includes retrieval channels,
        fusion strategy, coverage metrics, explainability details, warnings, and
        budget information. This comprehensive metadata enables detailed analysis
        and debugging of search behavior.

        Parameters
        ----------
        active_channels : Sequence[str]
            List of channel names that produced results. Used to show which
            retrieval systems participated in fusion.
        warnings : Sequence[str]
            List of warning messages accumulated during search execution. Warnings
            indicate non-fatal issues like channel failures or fallbacks.
        stats : _MethodStats
            Execution statistics including fused count, limits, FAISS parameters,
            and channel weights. Used to compute coverage metrics and explain
            execution parameters.
        fusion : Mapping[str, object] | None, optional
            Fusion-specific metadata (e.g., fusion type, RRF k parameter). Included
            in method metadata to explain how fusion was performed.
        budget : Mapping[str, object] | None, optional
            Budget decision metadata from query profiling. Includes information
            about adaptive budget selection and reasoning.

        Returns
        -------
        dict[str, object]
            Complete method metadata dictionary with all explainability information.
            Includes retrieval channels, coverage metrics, explainability details,
            warnings, fusion metadata, and budget information. The dictionary is
            suitable for inclusion in HybridSearchResult for comprehensive result
            explanation.

        Notes
        -----
        Method metadata composition enables comprehensive explainability by
        capturing all relevant execution details in a single dictionary. The
        metadata helps users understand how search was performed, which channels
        participated, what fusion strategy was used, and why certain decisions
        were made. This information is essential for debugging, optimization,
        and user trust in search results.
        """
        default_k = stats.faiss_k or self._settings.index.default_k
        default_nprobe = stats.nprobe or self._settings.index.default_nprobe
        coverage = (
            f"Hybrid pool fused {stats.fused_count}/{max(1, stats.limit)} results "
            f"(faiss k={default_k}, nprobe={default_nprobe})"
        )
        explainability: dict[str, object] = {
            "pool": {
                "weights": dict(stats.weights),
                "sim_threshold": getattr(self._settings.index, "semantic_min_score", 0.0),
            }
        }
        retrieval = list(dict.fromkeys(active_channels or ["semantic"]))
        notes = list(dict.fromkeys(warnings)) if warnings else []
        method: dict[str, object] = {
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

    def _filter_semantic_hits(
        self,
        semantic_hits: Sequence[tuple[int, float]],
        *,
        faiss_ready: bool,
    ) -> tuple[list[tuple[int, float]], list[str]]:
        """Drop semantic hits when FAISS is unavailable or below score threshold.

        This method filters semantic search results based on FAISS availability and
        minimum score thresholds. It is called during hybrid search execution to
        ensure only valid semantic hits are included in the final results. When FAISS
        is unavailable or scores are too low, warnings are generated.

        Parameters
        ----------
        semantic_hits : Sequence[tuple[int, float]]
            Sequence of (chunk_id, score) tuples from semantic search.
        faiss_ready : bool
            Whether FAISS index is available and ready for use.

        Returns
        -------
        tuple[list[tuple[int, float]], list[str]]
            Filtered list of (chunk_id, score) tuples and list of warning strings
            indicating why hits were filtered (e.g., "faiss_fallback:unavailable" or
            "faiss_fallback:low_score").
        """
        hits = list(semantic_hits)
        warnings: list[str] = []
        if not faiss_ready:
            warnings.append("faiss_fallback:unavailable")
            return [], warnings
        if not hits:
            return hits, warnings
        threshold = float(getattr(self._settings.index, "semantic_min_score", 0.0) or 0.0)
        if threshold <= 0.0:
            return hits, warnings
        top_score = float(hits[0][1]) if hits and len(hits[0]) > 1 else None
        if top_score is None or math.isnan(top_score):
            return hits, warnings
        if top_score < threshold:
            warnings.append("faiss_fallback:low_score")
            return [], warnings
        return hits, warnings


__all__ = [
    "BM25SearchProvider",
    "HybridResultDoc",
    "HybridSearchContext",
    "HybridSearchEngine",
    "HybridSearchOptions",
    "HybridSearchProviders",
    "HybridSearchResult",
    "HybridSearchTuning",
    "SpladeSearchProvider",
]
