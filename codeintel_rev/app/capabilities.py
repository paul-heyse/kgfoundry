"""Capability snapshot helpers for conditional tool registration and /capz."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Final

from codeintel_rev.io.faiss_compat import load_faiss_module
from kgfoundry_common.typing.heavy_deps import EXTRAS_HINT

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

from codeintel_rev.errors import RuntimeLifecycleError

__all__ = ["Capabilities", "override_capabilities", "override_capability_imports"]


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
    if module_name == "faiss":
        try:
            return load_faiss_module("capabilities detection")
        except ImportError:
            return None
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return None
    try:
        return importlib.import_module(module_name)
    except ImportError:  # pragma: no cover - import errors are expected
        return None


_OPTIONAL_IMPORTER_STACK: list[Callable[[str], ModuleType | None]] = [_import_optional]
_CAPABILITIES_OVERRIDE_STACK: list[Callable[[ApplicationContext], Capabilities] | None] = [None]


@contextmanager
def override_capability_imports(
    overrides: Mapping[str, ModuleType | None] | Callable[[str], ModuleType | None],
) -> Iterator[None]:
    """Temporarily override optional imports used for capability detection.

    Parameters
    ----------
    overrides : Mapping[str, ModuleType | None] | Callable[[str], ModuleType | None]
        Either a mapping of module names to modules (or None), or a callable
        function that takes a module name and returns a module (or None).

    Yields
    ------
    None
        This context manager yields None. While the context is active, optional
        imports used for capability detection are overridden according to the
        provided mapping or callable.
    """

    def _from_mapping(
        mapping: Mapping[str, ModuleType | None],
        fallback: Callable[[str], ModuleType | None],
    ) -> Callable[[str], ModuleType | None]:
        """Create a patched importer function from a mapping.

        Parameters
        ----------
        mapping : Mapping[str, ModuleType | None]
            Mapping of module names to modules (or None) to override imports.
        fallback : Callable[[str], ModuleType | None]
            Fallback importer function to use when module name is not in mapping.

        Returns
        -------
        Callable[[str], ModuleType | None]
            Patched importer function that checks mapping first, then falls back.
        """

        def _patched(name: str) -> ModuleType | None:
            """Return module from mapping if present, otherwise use fallback.

            Parameters
            ----------
            name : str
                Module name to import.

            Returns
            -------
            ModuleType | None
                Module from mapping if present, otherwise result from fallback.
            """
            if name in mapping:
                return mapping[name]
            return fallback(name)

        return _patched

    previous = _OPTIONAL_IMPORTER_STACK[-1]
    if callable(overrides):
        _OPTIONAL_IMPORTER_STACK.append(overrides)
    else:
        _OPTIONAL_IMPORTER_STACK.append(_from_mapping(overrides, previous))
    try:
        yield
    finally:
        _OPTIONAL_IMPORTER_STACK.pop()


@contextmanager
def override_capabilities(
    factory: Callable[[ApplicationContext], Capabilities] | None,
) -> Iterator[None]:
    """Temporarily override the capability snapshot factory.

    Parameters
    ----------
    factory : Callable[[ApplicationContext], Capabilities] | None
        Optional factory function that takes an ApplicationContext and returns
        a Capabilities instance. If None, the override is cleared.

    Yields
    ------
    None
        This context manager yields None. While the context is active, the
        capability snapshot factory is overridden with the provided factory
        function.
    """
    _CAPABILITIES_OVERRIDE_STACK.append(factory)
    try:
        yield
    finally:
        _CAPABILITIES_OVERRIDE_STACK.pop()


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


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Capability snapshot used for MCP tool gating and the /capz endpoint.

    Attributes
    ----------
    faiss_index : bool, optional
        Whether a FAISS vector index is available and loaded. Defaults to False.
    duckdb : bool, optional
        Whether a DuckDB catalog is available and accessible. Defaults to False.
    scip_index : bool, optional
        Whether a SCIP symbol index is available and loaded. Defaults to False.
    vllm_client : bool, optional
        Whether a vLLM embedding client is available and configured. Defaults to False.
    coderank_index_present : bool, optional
        Whether a CodeRank FAISS index is present on the filesystem. Defaults to False.
    warp_index_present : bool, optional
        Whether a WARP XTR index is present on the filesystem. Defaults to False.
    xtr_index_present : bool, optional
        Whether an XTR token-level index is present on the filesystem. Defaults to False.
    faiss_importable : bool, optional
        Whether the FAISS library can be imported. Defaults to False.
    duckdb_importable : bool, optional
        Whether the DuckDB library can be imported. Defaults to False.
    httpx_importable : bool, optional
        Whether the httpx HTTP client library can be imported. Defaults to False.
    torch_importable : bool, optional
        Whether PyTorch can be imported. Defaults to False.
    lucene_importable : bool, optional
        Whether Lucene/Pyserini libraries can be imported. Defaults to False.
    onnxruntime_importable : bool, optional
        Whether ONNX Runtime can be imported. Defaults to False.
    active_index_version : str | None, optional
        Version identifier of the currently active index (e.g., "v1", "2024-01-01").
        None if no index version is active. Defaults to None.
    versions_available : int, optional
        Number of index versions available in the lifecycle directory. Defaults to 0.
    """

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
        payload: dict[str, object] = {
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
            (FAISS index, DuckDB, SCIP index, vLLM client, etc.) and optional
            hints for missing capabilities.

        Notes
        -----
        This class method probes the application context to determine which
        features are available. It checks for index files, optional module
        imports, and index version information. The resulting snapshot is used
        for MCP tool gating and the /capz endpoint. Time
        complexity: O(1) for most checks, O(module_load_time) for optional imports.
        """
        override_factory = _CAPABILITIES_OVERRIDE_STACK[-1]
        if override_factory is not None:
            return override_factory(context)
        paths = getattr(context, "paths", None)
        importer = _OPTIONAL_IMPORTER_STACK[-1]
        faiss_module = importer("faiss")
        duckdb_module = importer("duckdb")
        httpx_module = importer("httpx")
        torch_module = importer("torch")
        lucene_module = importer("pyserini.search.lucene")
        onnxruntime_module = importer("onnxruntime")
        active_version: str | None = None
        version_count = 0
        index_manager = getattr(context, "index_manager", None)
        if index_manager is not None:
            try:
                active_version = index_manager.current_version()
                version_count = len(index_manager.list_versions())
            except RuntimeLifecycleError:
                active_version = None

        return cls(
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
            active_index_version=active_version,
            versions_available=version_count,
        )
