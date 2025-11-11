"""Factory adjustment hooks for RuntimeCell initialization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Protocol, TypeVar

T = TypeVar("T")


class FactoryAdjuster(Protocol):
    """Protocol for wrapping runtime cell factory functions."""

    def adjust(
        self, *, cell: str, factory: Callable[[], T]
    ) -> Callable[[], T]:  # pragma: no cover - protocol
        """Return a possibly wrapped factory for the given runtime.

        Returns
        -------
        Callable[[], T]
            Factory callable invoked by :class:`RuntimeCell`.
        """
        ...


@dataclass(slots=True, frozen=True)
class NoopFactoryAdjuster:
    """Default adjuster that returns the original factory."""

    def adjust(self, *, cell: str, factory: Callable[[], T]) -> Callable[[], T]:
        """Return ``factory`` unchanged.

        Returns
        -------
        Callable[[], T]
            Original factory callable.
        """
        _ = (self, cell)
        return factory


@dataclass(slots=True)
class DefaultFactoryAdjuster:
    """Reference adjuster that tunes common runtimes after creation."""

    faiss_nprobe: int | None = None
    faiss_gpu_preference: bool | None = None
    hybrid_rrf_k: int | None = None
    hybrid_bm25_weight: float | None = None
    hybrid_splade_weight: float | None = None
    vllm_mode: str | None = None
    vllm_timeout_s: float | None = None

    def adjust(self, *, cell: str, factory: Callable[[], T]) -> Callable[[], T]:
        """Return a wrapped factory when tuning hooks are known.

        Returns
        -------
        Callable[[], T]
            Either the original or wrapped factory.
        """
        normalized = cell.replace("_", "-")
        if normalized.startswith("coderank-faiss"):
            return self._wrap_faiss(factory)
        if normalized.startswith("hybrid"):
            return self._wrap_hybrid(factory)
        if normalized.startswith("xtr"):
            return self._wrap_xtr(factory)
        return factory

    def _wrap_faiss(self, base: Callable[[], T]) -> Callable[[], T]:
        """Apply FAISS-specific tuning hooks.

        Returns
        -------
        Callable[[], T]
            Wrapped factory that enforces FAISS settings.
        """

        def _wrapped() -> T:
            obj: Any = base()
            if self.faiss_nprobe is not None:
                if hasattr(obj, "set_nprobe"):
                    with SuppressException():
                        obj.set_nprobe(self.faiss_nprobe)  # type: ignore[attr-defined]
                elif hasattr(obj, "nprobe"):
                    with SuppressException():
                        obj.nprobe = self.faiss_nprobe
            if self.faiss_gpu_preference is not None and hasattr(obj, "set_gpu_preference"):
                with SuppressException():
                    obj.set_gpu_preference(self.faiss_gpu_preference)  # type: ignore[attr-defined]
            return obj  # type: ignore[return-value]

        return _wrapped

    def _wrap_hybrid(self, base: Callable[[], T]) -> Callable[[], T]:
        """Apply hybrid-channel tuning hooks.

        Returns
        -------
        Callable[[], T]
            Wrapped factory applying hybrid weights.
        """

        def _wrapped() -> T:
            obj: Any = base()
            if self.hybrid_rrf_k is not None and hasattr(obj, "set_rrf_k"):
                with SuppressException():
                    obj.set_rrf_k(self.hybrid_rrf_k)  # type: ignore[attr-defined]
            if self.hybrid_bm25_weight is not None and hasattr(obj, "set_bm25_weight"):
                with SuppressException():
                    obj.set_bm25_weight(self.hybrid_bm25_weight)  # type: ignore[attr-defined]
            if self.hybrid_splade_weight is not None and hasattr(obj, "set_splade_weight"):
                with SuppressException():
                    obj.set_splade_weight(self.hybrid_splade_weight)  # type: ignore[attr-defined]
            return obj  # type: ignore[return-value]

        return _wrapped

    @staticmethod
    def _wrap_xtr(base: Callable[[], T]) -> Callable[[], T]:
        """Return the base factory; placeholder for future tuning.

        Returns
        -------
        Callable[[], T]
            Unmodified factory.
        """
        return base


class SuppressException:
    """Context manager that suppresses adjustment failures."""

    def __enter__(self) -> None:  # pragma: no cover - no-op
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:  # pragma: no cover - trivial
        return True


__all__ = ["DefaultFactoryAdjuster", "FactoryAdjuster", "NoopFactoryAdjuster"]
