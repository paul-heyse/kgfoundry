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

        Extended Summary
        ----------------
        This protocol method adjusts factory functions for runtime cells by wrapping
        them with tuning hooks. Implementations may apply runtime-specific configuration
        (e.g., FAISS nprobe, hybrid search weights) after object creation. Used by
        RuntimeCell to customize runtime initialization based on application settings.

        Parameters
        ----------
        cell : str
            Runtime cell identifier (e.g., "coderank-faiss", "hybrid", "xtr"). Used
            to determine which tuning hooks to apply.
        factory : Callable[[], T]
            Original factory function that creates the runtime object. May be wrapped
            or returned unchanged.

        Returns
        -------
        Callable[[], T]
            Factory callable invoked by :class:`RuntimeCell`. May be the original
            factory or a wrapped version that applies tuning hooks.
        """
        ...


@dataclass(slots=True, frozen=True)
class NoopFactoryAdjuster:
    """Default adjuster that returns the original factory."""

    def adjust(self, *, cell: str, factory: Callable[[], T]) -> Callable[[], T]:
        """Return ``factory`` unchanged.

        Extended Summary
        ----------------
        This no-op adjuster returns the factory function unchanged without applying
        any tuning hooks. Used when factory adjustment is disabled or not needed.

        Parameters
        ----------
        cell : str
            Runtime cell identifier (unused by this adjuster).
        factory : Callable[[], T]
            Original factory function to return unchanged.

        Returns
        -------
        Callable[[], T]
            Original factory callable, returned without modification.
        """
        _ = (self, cell)
        return factory


@dataclass(slots=True, frozen=True)
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

        Extended Summary
        ----------------
        This adjuster wraps factory functions with runtime-specific tuning hooks based
        on the cell identifier. It applies FAISS tuning (nprobe, GPU preference), hybrid
        search tuning (RRF k, channel weights), or XTR tuning based on the cell name.
        Used to customize runtime initialization from application settings.

        Parameters
        ----------
        cell : str
            Runtime cell identifier (e.g., "coderank-faiss", "hybrid", "xtr"). Determines
            which tuning hooks to apply. Underscores are normalized to hyphens.
        factory : Callable[[], T]
            Original factory function that creates the runtime object. Wrapped with
            tuning hooks if the cell matches known patterns.

        Returns
        -------
        Callable[[], T]
            Either the original factory (if no tuning hooks match) or a wrapped factory
            that applies runtime-specific configuration after object creation.
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

        Extended Summary
        ----------------
        This helper wraps a FAISS factory function with tuning hooks that apply
        nprobe and GPU preference settings after object creation. It handles both
        setter methods and attribute assignment, suppressing errors if tuning fails.

        Parameters
        ----------
        base : Callable[[], T]
            Original FAISS factory function that creates the FAISS manager or index.

        Returns
        -------
        Callable[[], T]
            Wrapped factory that enforces FAISS settings (nprobe, GPU preference)
            after object creation. Tuning failures are suppressed.
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

        Extended Summary
        ----------------
        This helper wraps a hybrid search factory function with tuning hooks that
        apply RRF (Reciprocal Rank Fusion) k and channel weights (BM25, SPLADE) after
        object creation. It handles setter methods and suppresses errors if tuning fails.

        Parameters
        ----------
        base : Callable[[], T]
            Original hybrid search factory function that creates the hybrid search manager.

        Returns
        -------
        Callable[[], T]
            Wrapped factory that applies hybrid search settings (RRF k, BM25 weight,
            SPLADE weight) after object creation. Tuning failures are suppressed.
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

        Extended Summary
        ----------------
        This static helper is a placeholder for future XTR tuning hooks. Currently
        returns the factory unchanged, but may be extended to apply XTR-specific
        configuration in the future.

        Parameters
        ----------
        base : Callable[[], T]
            Original XTR factory function that creates the XTR index or manager.

        Returns
        -------
        Callable[[], T]
            Unmodified factory. Future versions may wrap with XTR tuning hooks.
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
