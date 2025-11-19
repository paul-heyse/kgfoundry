"""Built-in retrieval channel implementations (BM25, SPLADE)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from threading import Lock

from codeintel_rev.config.api import SpladeSettings
from codeintel_rev.io.bm25_engine import BM25Engine, BM25Rm3Config, PyseriniBM25Backend
from codeintel_rev.io.splade_engine import (
    SPLADEEngine,
    SpladeImpactBackend,
    SpladeImpactBackendConfig,
)
from codeintel_rev.io.splade_onnx_encoder import (
    OnnxSpladeConfig,
    OnnxSpladeMapEncoder,
    OnnxSpladeQueryEncoder,
)
from codeintel_rev.plugins.channels import Channel, ChannelContext, ChannelError
from codeintel_rev.retrieval.rm3_heuristics import RM3Heuristics, RM3Params
from codeintel_rev.retrieval.types import SearchHit

__all__ = ["bm25_factory", "splade_factory"]

logger = logging.getLogger(__name__)


def bm25_factory(context: ChannelContext) -> Channel:
    """Return the built-in BM25 channel.

    Extended Summary
    ----------------
    This factory function creates a BM25 (Best Matching 25) retrieval channel
    using the built-in BM25 index. BM25 is a sparse retrieval method that ranks
    documents based on term frequency and inverse document frequency. Used in
    hybrid search pipelines to provide keyword-based retrieval alongside dense
    vector search.

    Parameters
    ----------
    context : ChannelContext
        Channel context providing BM25 index path and configuration. The context
        must have a valid BM25 index directory.

    Returns
    -------
    Channel
        Channel implementation wrapping the BM25 provider. The channel performs
        BM25 retrieval and returns ranked document hits.

    Notes
    -----
    This factory is registered as a built-in channel plugin. The BM25 channel
    requires a BM25 index to be available in the context. Time complexity: O(n)
    for BM25 search where n is the number of documents in the index.
    """
    return _BM25Channel(context)


def splade_factory(context: ChannelContext) -> Channel:
    """Return the built-in SPLADE impact channel.

    Extended Summary
    ----------------
    This factory function creates a SPLADE (Sparse Lexical and Expansion) retrieval
    channel using the built-in SPLADE index. SPLADE is a learned sparse retrieval
    method that generates high-dimensional sparse vectors with learned term weights.
    Used in hybrid search pipelines to provide learned sparse retrieval alongside
    dense vector search.

    Parameters
    ----------
    context : ChannelContext
        Channel context providing SPLADE index path and configuration. The context
        must have a valid SPLADE index directory.

    Returns
    -------
    Channel
        Channel implementation wrapping the SPLADE provider. The channel performs
        SPLADE retrieval and returns ranked document hits.

    Notes
    -----
    This factory is registered as a built-in channel plugin. The SPLADE channel
    requires a SPLADE index to be available in the context. SPLADE provides better
    semantic matching than BM25 while maintaining sparse retrieval efficiency. Time
    complexity: O(n) for SPLADE search where n is the number of documents in the index.
    """
    return _SpladeChannel(context)


class _BM25Channel(Channel):
    """Built-in BM25 retrieval channel implementation.

    This channel wraps the BM25SearchProvider to provide keyword-based sparse
    retrieval. BM25 ranks documents based on term frequency and inverse document
    frequency, providing effective keyword matching for code search. The channel
    lazily initializes the provider on first search call and handles provider
    errors gracefully.

    Attributes
    ----------
    name : str
        Channel name identifier ("bm25").
    cost : float
        Relative cost factor for this channel (1.0).
    requires : frozenset[str]
        Set of capability requirements: "warp_index_present", "lucene_importable".
    """

    name = "bm25"
    cost = 1.0
    requires = frozenset({"warp_index_present", "lucene_importable"})

    def __init__(self, context: ChannelContext) -> None:
        self._app_config = context.app_config
        self._paths = context.paths
        self._legacy_settings = context.settings
        self._engine: BM25Engine | None = None
        self._provider_error: str | None = None
        self._skip_reason: str | None = None
        self._lock = Lock()

    def search(self, query: str, limit: int) -> Sequence[SearchHit]:
        """Perform BM25 search and return ranked document hits.

        Extended Summary
        ----------------
        This method executes BM25 (Best Matching 25) keyword-based search using the
        built-in BM25 provider. It ensures the provider is initialized, performs the
        search operation, and returns ranked results. BM25 is a sparse retrieval
        method that ranks documents based on term frequency and inverse document
        frequency, providing effective keyword matching for code search. Used in
        hybrid search pipelines to complement dense vector search with keyword
        signals.

        Parameters
        ----------
        query : str
            Search query string. Will be tokenized and processed by the BM25 provider.
            Supports natural language queries and code-like queries (identifiers,
            keywords).
        limit : int
            Maximum number of results to return. Must be positive. Results are
            ranked by BM25 score in descending order.

        Returns
        -------
        Sequence[SearchHit]
            Ranked sequence of channel hits containing document IDs and BM25 scores.
            Results are sorted by score descending. Length is min(limit, total_documents).

        Raises
        ------
        ChannelError
            If the BM25 provider is unavailable (disabled, initialization failed,
            missing assets) or if search execution fails (provider errors, I/O errors).

        Notes
        -----
        Time complexity O(n * m) where n is query terms and m is documents matching
        query terms. Space complexity O(k) where k is limit (result storage). Performs
        I/O to read BM25 index files. Thread-safe if provider is initialized (provider
        initialization is protected by lock). The method lazily initializes the provider
        on first search call. Returns empty sequence if limit <= 0.
        """
        engine = self._ensure_engine()
        if engine is None:
            raise ChannelError(
                self._provider_error or "BM25 channel unavailable",
                reason=self._skip_reason or "provider_error",
            )
        try:
            hits = engine.search(query, k=max(limit, 0))
        except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover - defensive logging
            message = f"BM25 search failed: {exc}"
            raise ChannelError(message, reason="provider_error") from exc
        return _to_search_hits("bm25", hits)

    def _ensure_engine(self) -> BM25Engine | None:
        """Ensure BM25 engine is initialized, returning it if available.

        Returns
        -------
        BM25Engine | None
            Initialized BM25 engine if available, None if disabled or
            initialization failed. Sets _provider_error and _skip_reason
            on failure.

        Notes
        -----
        Thread-safe lazy initialization. Checks configuration, initializes
        provider with RM3 settings if enabled, and handles initialization
        errors. Provider is cached after successful initialization.
        """
        if self._engine is not None:
            return self._engine
        if self._provider_error is not None:
            return None
        if not self._app_config.bm25.enabled:
            self._provider_error = "BM25 channel disabled by configuration"
            self._skip_reason = "disabled"
            return None
        with self._lock:
            if self._engine is not None:
                return self._engine
            try:
                bm25_settings = self._app_config.bm25
                prf_settings = self._legacy_settings.index.prf
                rm3_params = RM3Params(
                    fb_docs=bm25_settings.rm3_fb_docs,
                    fb_terms=bm25_settings.rm3_fb_terms,
                    orig_weight=bm25_settings.rm3_original_query_weight,
                )
                heuristics: RM3Heuristics | None = None
                if prf_settings.enable_auto:
                    head_terms: list[str] = []
                    if prf_settings.head_terms_csv:
                        head_terms = [
                            term.strip()
                            for term in prf_settings.head_terms_csv.split(",")
                            if term.strip()
                        ]
                    heuristics = RM3Heuristics(
                        short_query_max_terms=prf_settings.short_query_max_terms,
                        symbol_like_regex=prf_settings.symbol_like_regex,
                        head_terms=head_terms,
                        default_params=rm3_params,
                    )
                backend = PyseriniBM25Backend(
                    index_dir=_resolve_path(self._paths.repo_root, bm25_settings.index_dir),
                    k1=bm25_settings.k1,
                    b=bm25_settings.b,
                    rm3=BM25Rm3Config(
                        params=rm3_params,
                        heuristics=heuristics,
                        enable_rm3=bm25_settings.rm3_enabled,
                        auto_rm3=prf_settings.enable_auto,
                    ),
                )
                engine = BM25Engine(backend=backend)
            except (OSError, RuntimeError, ValueError, ImportError) as exc:
                self._provider_error = f"BM25 initialization failed: {exc}"
                self._skip_reason = _classify_skip_reason(exc)
                return None
            self._engine = engine
            self._provider_error = None
            self._skip_reason = None
            return engine


class _SpladeChannel(Channel):
    """Built-in SPLADE retrieval channel implementation.

    This channel wraps the SpladeSearchProvider to provide learned sparse
    retrieval. SPLADE generates high-dimensional sparse vectors with learned
    term weights, providing better semantic matching than BM25 while maintaining
    sparse retrieval efficiency. The channel lazily initializes the provider
    on first search call and handles provider errors gracefully.

    Attributes
    ----------
    name : str
        Channel name identifier ("splade").
    cost : float
        Relative cost factor for this channel (3.0, higher than BM25 due to
        ONNX inference overhead).
    requires : frozenset[str]
        Set of capability requirements: "lucene_importable", "onnxruntime_importable".
    """

    name = "splade"
    cost = 3.0
    requires = frozenset({"lucene_importable", "onnxruntime_importable"})

    def __init__(self, context: ChannelContext) -> None:
        self._config = context.app_config.splade
        self._paths = context.paths
        self._engine: SPLADEEngine | None = None
        self._provider_error: str | None = None
        self._skip_reason: str | None = None
        self._lock = Lock()

    def search(self, query: str, limit: int) -> Sequence[SearchHit]:
        """Perform SPLADE search and return ranked document hits.

        Extended Summary
        ----------------
        This method executes SPLADE (Sparse Lexical and Expansion) learned sparse
        retrieval using the built-in SPLADE provider. It ensures the provider is
        initialized, encodes the query into a high-dimensional sparse vector, performs
        sparse retrieval against the SPLADE index, and returns ranked results. SPLADE
        provides better semantic matching than BM25 while maintaining sparse retrieval
        efficiency. Used in hybrid search pipelines to complement dense vector search
        with learned sparse signals.

        Parameters
        ----------
        query : str
            Search query string. Will be tokenized, encoded into sparse vector, and
            matched against the SPLADE index. Supports natural language queries with
            semantic understanding.
        limit : int
            Maximum number of results to return. Must be positive. Results are
            ranked by SPLADE score in descending order.

        Returns
        -------
        Sequence[SearchHit]
            Ranked sequence of channel hits containing document IDs and SPLADE scores.
            Results are sorted by score descending. Length is min(limit, total_documents).

        Raises
        ------
        ChannelError
            If the SPLADE provider is unavailable (disabled, initialization failed,
            missing assets) or if search execution fails (provider errors, ONNX runtime
            errors, I/O errors).

        Notes
        -----
        Time complexity O(n * m) where n is query tokens and m is documents in index.
        Space complexity O(k) where k is limit (result storage). Performs I/O to read
        SPLADE index files and ONNX model inference for query encoding. Thread-safe if
        provider is initialized (provider initialization is protected by lock). The method
        lazily initializes the provider on first search call. Returns empty sequence if
        limit <= 0.
        """
        engine = self._ensure_engine()
        if engine is None:
            raise ChannelError(
                self._provider_error or "SPLADE channel unavailable",
                reason=self._skip_reason or "provider_error",
            )
        try:
            hits = engine.search(query, k=max(limit, 0))
        except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover - defensive logging
            message = f"SPLADE search failed: {exc}"
            raise ChannelError(message, reason="provider_error") from exc
        return _to_search_hits("splade", hits)

    def _ensure_engine(self) -> SPLADEEngine | None:
        """Ensure SPLADE engine is initialized, returning it if available.

        Returns
        -------
        SPLADEEngine | None
            Initialized SPLADE engine if available, None if disabled or
            initialization failed. Sets _provider_error and _skip_reason
            on failure.

        Notes
        -----
        Thread-safe lazy initialization. Checks configuration, initializes
        provider with model/ONNX/index directories, and handles initialization
        errors. Provider is cached after successful initialization.
        """
        if self._engine is not None:
            return self._engine
        if self._provider_error is not None:
            return None
        if not self._config.enabled:
            self._provider_error = "SPLADE channel disabled by configuration"
            self._skip_reason = "disabled"
            return None
        with self._lock:
            if self._engine is not None:
                return self._engine
            try:
                splade = self._config
                config = SpladeImpactBackendConfig(
                    model_dir=_resolve_path(self._paths.repo_root, splade.model_dir),
                    onnx_dir=_resolve_path(self._paths.repo_root, splade.onnx_dir),
                    onnx_file=splade.onnx_file,
                    provider=splade.provider,
                    index_dir=_resolve_path(self._paths.repo_root, splade.index_dir),
                    quantization=splade.quantization,
                    max_terms=splade.max_terms,
                    max_query_terms=splade.max_query_terms,
                    prune_below=splade.prune_below,
                    static_prune_pct=splade.static_prune_pct,
                )
                encoder = _build_onnx_encoder(splade, self._paths.repo_root, logger)
                engine = SPLADEEngine(SpladeImpactBackend(config, onnx_encoder=encoder))
            except (OSError, RuntimeError, ValueError, ImportError) as exc:
                self._provider_error = f"SPLADE initialization failed: {exc}"
                self._skip_reason = _classify_skip_reason(exc)
                return None
            self._engine = engine
            self._provider_error = None
            self._skip_reason = None
            return engine


def _resolve_path(repo_root: Path, value: Path | str) -> Path:
    """Resolve a path string relative to repo root or as absolute.

    Parameters
    ----------
    repo_root : Path
        Repository root directory for resolving relative paths.
    value : Path | str
        Path to resolve. May be absolute, relative, or contain ~ expansion.

    Returns
    -------
    Path
        Resolved absolute path. If value is absolute, returns it as-is.
        If relative, resolves it relative to repo_root.
    """
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    return (repo_root / candidate).resolve()


def _build_onnx_encoder(
    splade_settings: SpladeSettings,
    repo_root: Path,
    logger: logging.Logger,
) -> object | None:
    cfg = splade_settings.onnx_query
    if cfg is None or not cfg.enabled:
        return None
    base_dir = _resolve_path(repo_root, splade_settings.onnx_dir)
    model_path = cfg.model_path or (splade_settings.onnx_dir / splade_settings.onnx_file)
    if not model_path.is_absolute():
        model_path = base_dir / model_path
    model_path = model_path.resolve()
    if not model_path.exists():
        logger.warning("SPLADE ONNX model not found: %s", model_path)
        return None
    tokenizer_name = cfg.tokenizer_name or splade_settings.model_id
    try:
        onnx_cfg = OnnxSpladeConfig(
            model_path=model_path,
            tokenizer_name=tokenizer_name,
            output_name=cfg.output_name,
            input_ids_name=cfg.input_ids_name,
            attention_mask_name=cfg.attention_mask_name,
            providers=cfg.providers,
            topn=cfg.topn,
            min_weight=cfg.min_weight,
            normalize=cfg.normalize,
        )
        encoder_cls = OnnxSpladeMapEncoder if cfg.format == "map" else OnnxSpladeQueryEncoder
        return encoder_cls(onnx_cfg)
    except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover - defensive guard
        logger.warning("Failed to initialize SPLADE ONNX encoder: %s", exc)
        return None


def _classify_skip_reason(exc: Exception) -> str:
    """Classify exception into a skip reason code.

    Parameters
    ----------
    exc : Exception
        Exception raised during provider initialization.

    Returns
    -------
    str
        Skip reason code: "missing_assets" for FileNotFoundError,
        "capability_off" for capability/disabled errors, "provider_error"
        for other errors.
    """
    if isinstance(exc, FileNotFoundError):
        return "missing_assets"
    message = str(exc).lower()
    if "capability" in message or "disabled" in message:
        return "capability_off"
    return "provider_error"


def _to_search_hits(channel: str, pairs: Sequence[tuple[int, float]]) -> list[SearchHit]:
    """Convert engine tuples into SearchHit records.

    Returns
    -------
    list[SearchHit]
        Ranked hits annotated with channel metadata.
    """
    hits: list[SearchHit] = []
    for rank, (doc_id, score) in enumerate(pairs):
        hits.append(
            SearchHit(
                doc_id=str(int(doc_id)),
                rank=rank,
                score=float(score),
                source=channel,
            )
        )
    return hits
