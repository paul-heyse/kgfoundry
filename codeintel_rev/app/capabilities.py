"""Capability snapshot helpers for conditional tool registration and /capz."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Final, cast

from kgfoundry_common.logging import get_logger
from kgfoundry_common.prometheus import GaugeLike, build_gauge

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

LOGGER = get_logger(__name__)


def _build_capability_gauge(metric: str, description: str) -> GaugeLike:
    metric_name = f"codeintel_capability_{metric}"
    return build_gauge(metric_name, description)


_CAPABILITY_GAUGES: Final[dict[str, GaugeLike]] = {
    "faiss_index_present": _build_capability_gauge(
        "faiss_index_present", "FAISS index file available on disk"
    ),
    "duckdb_catalog_present": _build_capability_gauge(
        "duckdb_catalog_present", "DuckDB catalog file available on disk"
    ),
    "scip_index_present": _build_capability_gauge(
        "scip_index_present", "SCIP index file available on disk"
    ),
    "coderank_index_present": _build_capability_gauge(
        "coderank_index_present", "CodeRank FAISS index available on disk"
    ),
    "warp_index_present": _build_capability_gauge(
        "warp_index_present", "WARP/BM25 index directory available"
    ),
    "xtr_index_present": _build_capability_gauge(
        "xtr_index_present", "XTR token index directory available"
    ),
    "vllm_client_ready": _build_capability_gauge(
        "vllm_client_ready", "vLLM client configured in ApplicationContext"
    ),
    "faiss_importable": _build_capability_gauge(
        "faiss_importable", "faiss module import succeeded"
    ),
    "duckdb_importable": _build_capability_gauge(
        "duckdb_importable", "duckdb module import succeeded"
    ),
    "httpx_importable": _build_capability_gauge(
        "httpx_importable", "httpx module import succeeded"
    ),
    "torch_importable": _build_capability_gauge(
        "torch_importable", "torch module import succeeded"
    ),
    "faiss_gpu_available": _build_capability_gauge(
        "faiss_gpu_available", "FAISS GPU symbols detected"
    ),
}

__all__ = ["Capabilities"]


def _import_optional(module_name: str) -> ModuleType | None:
    """Return imported module when available, otherwise ``None``.

    Returns
    -------
    ModuleType | None
        Imported module instance or ``None`` when unavailable.
    """
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return None
    try:
        return importlib.import_module(module_name)
    except ImportError:  # pragma: no cover - import errors are expected
        LOGGER.debug(
            "Optional module import failed",
            extra={"capability_module": module_name},
            exc_info=True,
        )
        return None


def _probe_faiss_gpu(module: ModuleType | None) -> tuple[bool, str | None]:
    """Return FAISS GPU availability and optional reason for failure.

    Returns
    -------
    tuple[bool, str | None]
        Availability flag and optional reason string.
    """
    if module is None:
        return False, "faiss-missing"
    required_attrs = ("StandardGpuResources", "GpuClonerOptions", "index_cpu_to_gpu")
    if not all(hasattr(module, attr) for attr in required_attrs):
        return False, "gpu-symbols-missing"
    get_num_gpus = getattr(module, "get_num_gpus", None)
    if callable(get_num_gpus):
        gpu_fn = cast("Callable[[], int]", get_num_gpus)
        try:
            if gpu_fn() > 0:
                return True, None
        except (OSError, RuntimeError, ValueError, TypeError) as exc:  # pragma: no cover
            return False, f"gpu-probe-error:{exc.__class__.__name__}"
    return False, "no-gpu-visible"


def _path_exists(path: Path | None) -> bool:
    """Return True when ``path`` is populated and exists on the filesystem.

    Returns
    -------
    bool
        ``True`` when the path exists, otherwise ``False``.
    """
    return bool(path and path.exists())


def _record_metrics(payload: dict[str, object]) -> None:
    """Update Prometheus gauges with the latest capability snapshot."""
    for key, gauge in _CAPABILITY_GAUGES.items():
        gauge.set(1.0 if payload.get(key) else 0.0)


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Capability snapshot used for MCP tool gating and the /capz endpoint."""

    faiss_index: bool = False
    duckdb: bool = False
    scip_index: bool = False
    vllm_client: bool = False
    coderank_index_present: bool = False
    warp_index_present: bool = False
    xtr_index_present: bool = False
    faiss_importable: bool = False
    duckdb_importable: bool = False
    httpx_importable: bool = False
    torch_importable: bool = False
    faiss_gpu_available: bool = False
    faiss_gpu_disabled_reason: str | None = None

    @property
    def has_semantic(self) -> bool:
        """Return ``True`` when semantic MCP tools can be registered safely.

        Returns
        -------
        bool
            Semantic capability flag.
        """
        return self.faiss_index and self.duckdb and self.vllm_client

    @property
    def has_symbols(self) -> bool:
        """Return ``True`` when symbol MCP tools can be registered safely.

        Returns
        -------
        bool
            Symbol capability flag.
        """
        return self.duckdb and self.scip_index

    def model_dump(self) -> dict[str, object]:
        """Return a JSON-serializable payload suitable for `/capz` responses.

        Returns
        -------
        dict[str, object]
            Structured capability payload.
        """
        payload = {
            "faiss_index_present": self.faiss_index,
            "duckdb_catalog_present": self.duckdb,
            "scip_index_present": self.scip_index,
            "vllm_client_ready": self.vllm_client,
            "coderank_index_present": self.coderank_index_present,
            "warp_index_present": self.warp_index_present,
            "xtr_index_present": self.xtr_index_present,
            "faiss_importable": self.faiss_importable,
            "duckdb_importable": self.duckdb_importable,
            "httpx_importable": self.httpx_importable,
            "torch_importable": self.torch_importable,
            "faiss_gpu_available": self.faiss_gpu_available,
            "faiss_gpu_disabled_reason": self.faiss_gpu_disabled_reason,
            "has_semantic": self.has_semantic,
            "has_symbols": self.has_symbols,
        }
        _record_metrics(payload)
        return payload

    @classmethod
    def from_context(cls, context: ApplicationContext) -> Capabilities:
        """Build a capability snapshot from the provided application context.

        Returns
        -------
        Capabilities
            Snapshot computed from the context.
        """
        paths = getattr(context, "paths", None)
        faiss_module = _import_optional("faiss")
        duckdb_module = _import_optional("duckdb")
        httpx_module = _import_optional("httpx")
        torch_module = _import_optional("torch")
        faiss_gpu_available, faiss_gpu_reason = _probe_faiss_gpu(faiss_module)

        snapshot = cls(
            faiss_index=_path_exists(getattr(paths, "faiss_index", None)) and bool(faiss_module),
            duckdb=_path_exists(getattr(paths, "duckdb_path", None)),
            scip_index=_path_exists(getattr(paths, "scip_index", None)),
            vllm_client=getattr(context, "vllm_client", None) is not None,
            coderank_index_present=_path_exists(getattr(paths, "coderank_faiss_index", None)),
            warp_index_present=_path_exists(getattr(paths, "warp_index_dir", None)),
            xtr_index_present=_path_exists(getattr(paths, "xtr_dir", None)),
            faiss_importable=faiss_module is not None,
            duckdb_importable=duckdb_module is not None,
            httpx_importable=httpx_module is not None,
            torch_importable=torch_module is not None,
            faiss_gpu_available=faiss_gpu_available,
            faiss_gpu_disabled_reason=faiss_gpu_reason,
        )

        payload = snapshot.model_dump()
        LOGGER.info("capabilities.snapshot", extra={"capabilities": payload})
        return snapshot
