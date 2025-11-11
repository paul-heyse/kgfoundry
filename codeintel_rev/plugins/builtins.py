"""Built-in retrieval channel implementations (BM25, SPLADE)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from threading import Lock

from codeintel_rev.io.hybrid_search import BM25SearchProvider, SpladeSearchProvider
from codeintel_rev.plugins.channels import Channel, ChannelContext, ChannelError
from codeintel_rev.retrieval.types import ChannelHit
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)

__all__ = ["bm25_factory", "splade_factory"]


def bm25_factory(context: ChannelContext) -> Channel:
    """Return the built-in BM25 channel.

    Returns
    -------
    Channel
        Channel implementation wrapping the BM25 provider.
    """
    return _BM25Channel(context)


def splade_factory(context: ChannelContext) -> Channel:
    """Return the built-in SPLADE impact channel.

    Returns
    -------
    Channel
        Channel implementation wrapping the SPLADE provider.
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

    def search(self, query: str, limit: int) -> Sequence[ChannelHit]:
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
        with self._lock:
            if self._provider is not None:
                return self._provider
            try:
                provider = self._provider_cls(
                    index_dir=_resolve_path(self._paths.repo_root, self._settings.bm25.index_dir),
                    k1=self._settings.index.bm25_k1,
                    b=self._settings.index.bm25_b,
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

    def search(self, query: str, limit: int) -> Sequence[ChannelHit]:
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
