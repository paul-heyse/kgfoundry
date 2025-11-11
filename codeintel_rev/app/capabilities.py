"""Capability snapshot helpers for conditional tool registration and /capz."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Final, cast

from kgfoundry_common.logging import get_logger
from kgfoundry_common.prometheus import GaugeLike, build_gauge
from kgfoundry_common.typing.heavy_deps import EXTRAS_HINT

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

from codeintel_rev.errors import RuntimeLifecycleError

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
    "lucene_importable": _build_capability_gauge(
        "lucene_importable", "Pyserini Lucene module import succeeded"
    ),
    "onnxruntime_importable": _build_capability_gauge(
        "onnxruntime_importable", "onnxruntime module import succeeded"
    ),
    "faiss_gpu_available": _build_capability_gauge(
        "faiss_gpu_available", "FAISS GPU symbols detected"
    ),
}

__all__ = ["Capabilities"]


_CAPABILITY_HINT_ATTRS: Final[dict[str, str]] = {
    "faiss": "faiss_importable",
    "duckdb": "duckdb_importable",
    "torch": "torch_importable",
    "onnxruntime": "onnxruntime_importable",
    "lucene": "lucene_importable",
}


def _import_optional(module_name: str) -> ModuleType | None:
    """Return imported module when available, otherwise ``None``.

    Parameters
    ----------
    module_name : str
        Name of the module to import (e.g., "faiss", "duckdb").

    Returns
    -------
    ModuleType | None
        Imported module instance or ``None`` when unavailable (module not found
        or import error occurred). Import errors are logged at debug level.

    Notes
    -----
    This helper safely imports optional dependencies without raising exceptions.
    Used for capability detection to determine which features are available
    at runtime. Time complexity: O(1) for cached imports, O(module_load_time)
    for first-time imports.
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

    Parameters
    ----------
    module : ModuleType | None
        FAISS module instance. If None, returns (False, "faiss-missing").

    Returns
    -------
    tuple[bool, str | None]
        Availability flag and optional reason string. Returns (True, None) if GPU
        is available, (False, reason) otherwise. Reason codes include:
        "faiss-missing", "gpu-symbols-missing", "no-gpu-visible", "gpu-probe-error:<class>".

    Notes
    -----
    This helper probes FAISS GPU support by checking for required GPU symbols
    (StandardGpuResources, GpuClonerOptions, index_cpu_to_gpu) and attempting
    to query GPU count. Handles various failure modes gracefully without raising.
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

    Parameters
    ----------
    path : Path | None
        Filesystem path to check. If None, returns False.

    Returns
    -------
    bool
        ``True`` when the path exists, otherwise ``False``. Returns False if
        path is None or if the path does not exist on the filesystem.

    Notes
    -----
    This helper safely checks path existence without raising exceptions.
    Used for capability detection to verify index files and other resources.
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
    lucene_importable: bool = False
    onnxruntime_importable: bool = False
    faiss_gpu_available: bool = False
    faiss_gpu_disabled_reason: str | None = None
    active_index_version: str | None = None
    versions_available: int = 0

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

    @property
    def has_reranker(self) -> bool:
        """Return ``True`` when XTR reranking is available."""
        return self.xtr_index_present and self.torch_importable

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
            "lucene_importable": self.lucene_importable,
            "onnxruntime_importable": self.onnxruntime_importable,
            "faiss_gpu_available": self.faiss_gpu_available,
            "faiss_gpu_disabled_reason": self.faiss_gpu_disabled_reason,
            "has_semantic": self.has_semantic,
            "has_symbols": self.has_symbols,
            "active_index_version": self.active_index_version,
            "versions_available": self.versions_available,
        }
        hints: dict[str, str] = {}
        for hint_key, attr in _CAPABILITY_HINT_ATTRS.items():
            if not bool(getattr(self, attr, False)):
                suggestion = EXTRAS_HINT.get(hint_key)
                if suggestion:
                    hints[hint_key] = suggestion
        if hints:
            payload["hints"] = hints
        _record_metrics(payload)
        return payload

    def stamp(self, payload: dict[str, object] | None = None) -> str:
        """Return a stable hash representing the current capability snapshot.

        Parameters
        ----------
        payload : dict[str, object] | None, optional
            Capability payload to hash. If None, uses `self.model_dump()`.

        Returns
        -------
        str
            Hex-encoded SHA-256 digest of the capability payload. The hash is
            deterministic and stable for identical capability configurations.

        Notes
        -----
        This method computes a stable hash of the capability snapshot for
        versioning and change detection. The payload is JSON-serialized with
        sorted keys to ensure deterministic hashing. Time complexity: O(n) where
        n is the size of the serialized payload.
        """
        snapshot = payload or self.model_dump()
        encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def from_context(cls, context: ApplicationContext) -> Capabilities:
        """Build a capability snapshot from the provided application context.

        Parameters
        ----------
        context : ApplicationContext
            Application context containing paths, clients, and managers used
            to detect available capabilities.

        Returns
        -------
        Capabilities
            Snapshot computed from the context, including detected features
            (FAISS index, DuckDB, SCIP index, vLLM client, GPU support, etc.)
            and optional hints for missing capabilities.

        Notes
        -----
        This class method probes the application context to determine which
        features are available. It checks for index files, optional module
        imports, GPU availability, and index version information. The resulting
        snapshot is used for MCP tool gating and the /capz endpoint. Time
        complexity: O(1) for most checks, O(module_load_time) for optional imports.
        """
        paths = getattr(context, "paths", None)
        faiss_module = _import_optional("faiss")
        duckdb_module = _import_optional("duckdb")
        httpx_module = _import_optional("httpx")
        torch_module = _import_optional("torch")
        lucene_module = _import_optional("pyserini.search.lucene")
        onnxruntime_module = _import_optional("onnxruntime")
        faiss_gpu_available, faiss_gpu_reason = _probe_faiss_gpu(faiss_module)
        active_version: str | None = None
        version_count = 0
        index_manager = getattr(context, "index_manager", None)
        if index_manager is not None:
            try:
                active_version = index_manager.current_version()
                version_count = len(index_manager.list_versions())
            except RuntimeLifecycleError:
                active_version = None

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
            lucene_importable=lucene_module is not None,
            onnxruntime_importable=onnxruntime_module is not None,
            faiss_gpu_available=faiss_gpu_available,
            faiss_gpu_disabled_reason=faiss_gpu_reason,
            active_index_version=active_version,
            versions_available=version_count,
        )

        payload = snapshot.model_dump()
        LOGGER.info("capabilities.snapshot", extra={"capabilities": payload})
        return snapshot
