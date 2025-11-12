"""Adapter for the optional WARP/XTR late interaction executor."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from codeintel_rev.typing import gate_import
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from types import ModuleType

LOGGER = get_logger(__name__)


class WarpExecutorProtocol(Protocol):
    """Protocol describing the WARP executor search surface."""

    def search(
        self,
        *,
        query: str,
        candidates: Sequence[int],
        top_k: int,
    ) -> Sequence[object]:
        """Return ranked candidate tuples."""
        ...


WarpExecutorFactory = Callable[[str, str], WarpExecutorProtocol]


class WarpUnavailableError(RuntimeError):
    """Raised when the WARP executor or index artifacts are missing."""


class WarpEngine:
    """Encapsulates interactions with the optional ``xtr-warp`` executor."""

    def __init__(self, *, index_dir: Path, device: str) -> None:
        self.index_dir = Path(index_dir)
        if not self.index_dir.exists():
            msg = f"WARP index directory not found: {self.index_dir}"
            raise WarpUnavailableError(msg)
        self.device = device
        self._executor_cls: WarpExecutorFactory = self._load_executor_cls()
        self._executor: WarpExecutorProtocol | None = None

    def rerank(
        self,
        *,
        query: str,
        candidate_ids: Sequence[int],
        top_k: int,
    ) -> list[tuple[int, float]]:
        """Return WARP scores for candidate document IDs.

        Parameters
        ----------
        query : str
            Natural language search query string.
        candidate_ids : Sequence[int]
            Sequence of document/chunk IDs to rerank using WARP late-interaction
            scoring. These are typically top-k results from an initial retrieval stage.
        top_k : int
            Maximum number of results to return. Must be positive.

        Returns
        -------
        list[tuple[int, float]]
            List of (doc_id, score) tuples ranked by WARP scores in descending order.
            Length is min(len(candidate_ids), top_k).

        Raises
        ------
        WarpUnavailableError
            If WARP executor is unavailable or search fails.
        """
        if not candidate_ids:
            return []
        executor = self._ensure_executor()
        try:
            results = executor.search(
                query=query,
                candidates=[int(cid) for cid in candidate_ids],
                top_k=int(top_k),
            )
        except AttributeError as exc:  # pragma: no cover - upstream API drift
            msg = "WARP executor search API changed; update WarpEngine."
            raise WarpUnavailableError(msg) from exc
        except Exception as exc:
            msg = f"WARP search failed: {exc}"
            raise WarpUnavailableError(msg) from exc

        normalized: list[tuple[int, float]] = []
        for item in results:
            if isinstance(item, dict):
                doc_id_value = _safe_int(item.get("doc_id"))
                score_value = _safe_float(item.get("score", 0.0))
                normalized.append((doc_id_value, score_value))
            elif isinstance(item, Sequence) and len(item) >= 2:
                doc_id = item[0]
                score = item[1]
                normalized.append((_safe_int(doc_id), _safe_float(score)))
        return normalized

    def _load_executor_cls(self) -> WarpExecutorFactory:
        """Import the WARP executor class via ``gate_import``.

        Returns
        -------
        WarpExecutorFactory
            The WarpExecutor factory class from xtr_warp.executor module.

        Raises
        ------
        WarpUnavailableError
            If the WarpExecutor class is not found in the module.
        """
        module = self._import_warp_executor_module()
        executor_cls = getattr(module, "WarpExecutor", None)
        if executor_cls is None:
            msg = "xtr_warp.executor does not expose WarpExecutor"
            raise WarpUnavailableError(msg)
        return cast("WarpExecutorFactory", executor_cls)

    @staticmethod
    def _import_warp_executor_module() -> ModuleType:
        purpose = "WARP/XTR reranking (install `xtr-warp` and build the index)"
        module = gate_import("xtr_warp.executor", purpose)
        return cast("ModuleType", module)

    def _ensure_executor(self) -> WarpExecutorProtocol:
        """Ensure the WARP executor is initialized and return it.

        Returns
        -------
        object
            The initialized WARP executor instance.

        Raises
        ------
        WarpUnavailableError
            If executor initialization fails.
        """
        cached = self._executor
        if cached is not None:
            return cached
        try:
            self._executor = self._executor_cls(
                str(self.index_dir),
                self.device,
            )
        except Exception as exc:
            msg = f"Failed to initialize WARP executor: {exc}"
            raise WarpUnavailableError(msg) from exc
        LOGGER.info(
            "Initialized WARP executor",
            extra={"index_dir": str(self.index_dir), "device": self.device},
        )
        return self._executor


def _safe_int(value: object | None, default: int = 0) -> int:
    """Convert an object to int safely, falling back to the provided default.

    Parameters
    ----------
    value : object | None
        Value to convert to int. Can be int, float, or str. If None or
        conversion fails, returns default.
    default : int, optional
        Fallback value returned if conversion fails. Defaults to 0.

    Returns
    -------
    int
        Integer representation of value or the fallback default.
    """
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return default


def _safe_float(value: object | None, default: float = 0.0) -> float:
    """Convert an object to float safely, falling back to the provided default.

    Parameters
    ----------
    value : object | None
        Value to convert to float. Can be int, float, or str. If None or
        conversion fails, returns default.
    default : float, optional
        Fallback value returned if conversion fails. Defaults to 0.0.

    Returns
    -------
    float
        Float representation of value or the fallback default.
    """
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    return default
