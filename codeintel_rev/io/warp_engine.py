"""Adapter for the optional WARP/XTR late interaction executor."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

from kgfoundry_common.logging import get_logger
from kgfoundry_common.typing import gate_import

if TYPE_CHECKING:
    from types import ModuleType

LOGGER = get_logger(__name__)


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
        self._executor_cls = self._load_executor_cls()
        self._executor = None

    def rerank(
        self,
        *,
        query: str,
        candidate_ids: Sequence[int],
        top_k: int,
    ) -> list[tuple[int, float]]:
        """Return WARP scores for ``candidate_ids``.

        Returns
        -------
        list[tuple[int, float]]
            List of (doc_id, score) tuples ranked by WARP scores.

        Raises
        ------
        WarpUnavailableError
            If WARP executor is unavailable or search fails.
        """
        if not candidate_ids:
            return []
        executor = self._ensure_executor()
        try:
            results = executor.search(  # type: ignore[attr-defined]
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
                normalized.append(
                    (
                        int(item.get("doc_id")),
                        float(item.get("score", 0.0)),
                    )
                )
            else:
                doc_id, score = item
                normalized.append((int(doc_id), float(score)))
        return normalized

    def _load_executor_cls(self) -> type[object]:
        """Import the WARP executor class via ``gate_import``.

        Returns
        -------
        type[object]
            The WarpExecutor class from xtr_warp.executor module.

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
        return executor_cls

    def _import_warp_executor_module(self) -> ModuleType:
        purpose = "WARP/XTR reranking (install `xtr-warp` and build the index)"
        module = gate_import("xtr_warp.executor", purpose)
        return cast("ModuleType", module)

    def _ensure_executor(self) -> object:
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
        if self._executor is not None:
            return self._executor
        try:
            self._executor = self._executor_cls(  # type: ignore[call-arg]
                index_dir=str(self.index_dir),
                device=self.device,
            )
        except Exception as exc:
            msg = f"Failed to initialize WARP executor: {exc}"
            raise WarpUnavailableError(msg) from exc
        LOGGER.info(
            "Initialized WARP executor",
            extra={"index_dir": str(self.index_dir), "device": self.device},
        )
        return self._executor
