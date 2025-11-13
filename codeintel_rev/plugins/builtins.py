"""Built-in retrieval channel implementations (BM25, SPLADE)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from threading import Lock

from codeintel_rev.io.hybrid_search import BM25Rm3Config, BM25SearchProvider, SpladeSearchProvider
from codeintel_rev.plugins.channels import Channel, ChannelContext, ChannelError
from codeintel_rev.retrieval.rm3_heuristics import RM3Heuristics, RM3Params
from codeintel_rev.retrieval.types import SearchHit
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)

__all__ = ["bm25_factory", "splade_factory"]


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
    name = "bm25"
    cost = 1.0
    requires = frozenset({"warp_index_present", "lucene_importable"})

    def __init__(self, context: ChannelContext) -> None:
        self._settings = context.settings
        self._paths = context.paths
        self._provider_cls = BM25SearchProvider
        self._provider: BM25SearchProvider | None = None
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
        provider = self._ensure_provider()
        if provider is None:
            raise ChannelError(
                self._provider_error or "BM25 channel unavailable",
                reason=self._skip_reason or "provider_error",
            )
        try:
            return provider.search(query, limit)
        except Exception as exc:  # pragma: no cover - defensive logging
            message = f"BM25 search failed: {exc}"
            raise ChannelError(message, reason="provider_error") from exc

    def _ensure_provider(self) -> BM25SearchProvider | None:
        if self._provider is not None:
            return self._provider
        if self._provider_error is not None:
            return None
        if not self._settings.bm25.enabled:
            self._provider_error = "BM25 channel disabled by configuration"
            self._skip_reason = "disabled"
            return None
        with self._lock:
            if self._provider is not None:
                return self._provider
            try:
                bm25_settings = self._settings.bm25
                prf_settings = self._settings.index.prf
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
                provider = self._provider_cls(
                    index_dir=_resolve_path(self._paths.repo_root, self._settings.bm25.index_dir),
                    k1=self._settings.index.bm25_k1,
                    b=self._settings.index.bm25_b,
                    rm3=BM25Rm3Config(
                        params=rm3_params,
                        heuristics=heuristics,
                        enable_rm3=bm25_settings.rm3_enabled,
                        auto_rm3=prf_settings.enable_auto,
                    ),
                )
            except (OSError, RuntimeError, ValueError, ImportError) as exc:
                self._provider_error = f"BM25 initialization failed: {exc}"
                self._skip_reason = _classify_skip_reason(exc)
                LOGGER.warning(
                    "bm25.channel.init_failed",
                    extra={"reason": self._skip_reason, "error": repr(exc)},
                )
                return None
            self._provider = provider
            self._provider_error = None
            self._skip_reason = None
            return provider


class _SpladeChannel(Channel):
    name = "splade"
    cost = 3.0
    requires = frozenset({"lucene_importable", "onnxruntime_importable"})

    def __init__(self, context: ChannelContext) -> None:
        self._settings = context.settings
        self._paths = context.paths
        self._provider_cls = SpladeSearchProvider
        self._provider: SpladeSearchProvider | None = None
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
        provider = self._ensure_provider()
        if provider is None:
            raise ChannelError(
                self._provider_error or "SPLADE channel unavailable",
                reason=self._skip_reason or "provider_error",
            )
        try:
            return provider.search(query, limit)
        except Exception as exc:  # pragma: no cover - defensive logging
            message = f"SPLADE search failed: {exc}"
            raise ChannelError(message, reason="provider_error") from exc

    def _ensure_provider(self) -> SpladeSearchProvider | None:
        if self._provider is not None:
            return self._provider
        if self._provider_error is not None:
            return None
        if not self._settings.splade.enabled:
            self._provider_error = "SPLADE channel disabled by configuration"
            self._skip_reason = "disabled"
            return None
        with self._lock:
            if self._provider is not None:
                return self._provider
            try:
                splade = self._settings.splade
                provider = self._provider_cls(
                    splade,
                    model_dir=_resolve_path(self._paths.repo_root, splade.model_dir),
                    onnx_dir=_resolve_path(self._paths.repo_root, splade.onnx_dir),
                    index_dir=_resolve_path(self._paths.repo_root, splade.index_dir),
                )
            except (OSError, RuntimeError, ValueError, ImportError) as exc:
                self._provider_error = f"SPLADE initialization failed: {exc}"
                self._skip_reason = _classify_skip_reason(exc)
                LOGGER.warning(
                    "splade.channel.init_failed",
                    extra={"reason": self._skip_reason, "error": repr(exc)},
                )
                return None
            self._provider = provider
            self._provider_error = None
            self._skip_reason = None
            return provider


def _resolve_path(repo_root: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    return (repo_root / candidate).resolve()


def _classify_skip_reason(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "missing_assets"
    message = str(exc).lower()
    if "capability" in message or "disabled" in message:
        return "capability_off"
    return "provider_error"
