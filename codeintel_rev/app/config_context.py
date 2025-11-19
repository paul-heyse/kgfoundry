"""Application-level configuration context manager.

This module provides centralized configuration lifecycle management for the
CodeIntel MCP application. Instead of loading settings repeatedly from environment
variables on each request, configuration is loaded exactly once during FastAPI
application startup and shared across all request handlers via explicit dependency
injection.

Key Components
--------------
ResolvedPaths : dataclass
    Canonicalized absolute filesystem paths for all application resources.
ApplicationContext : dataclass
    Application-wide context holding configuration and long-lived clients.
resolve_application_paths : function
    Validates and resolves all configured paths relative to repository root.

Design Principles
-----------------
- **Load Once**: Configuration parsed from environment exactly once at startup
- **Explicit Injection**: Context passed as parameter (no global state)
- **Fail-Fast**: Invalid configuration prevents application startup
- **Immutable**: Settings frozen after creation (thread-safe)
- **RFC 9457**: All errors use Problem Details format

Example Usage
-------------
During FastAPI application startup:

>>> # In lifespan() function
>>> context = ApplicationContext.create()
>>> app.state.context = context

In request handlers:

>>> # In MCP tool wrapper
>>> context = request.app.state.context
>>> files_adapter.list_paths(context, path="src")

See Also
--------
codeintel_rev.app.runtime_readiness : Readiness probe system for health checks
codeintel_rev.config.settings : Settings dataclasses and environment loading
"""

from __future__ import annotations

import importlib
import logging
import os
import warnings
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Lock
from types import ModuleType
from typing import TYPE_CHECKING, Any, TypeVar, cast

import numpy as np

from codeintel_rev.app import readiness as fs_readiness
from codeintel_rev.app.scope_store import ScopeStore
from codeintel_rev.config.api import (
    AppConfig,
    FAISSSettings,
    IndexSettings,
    LoggingSettings,
    SearchSettings,
    SpladeSettings,
)
from codeintel_rev.config.loader import load_app_config
from codeintel_rev.config.paths import ResolvedPaths, resolve_application_paths
from codeintel_rev.config.settings import Settings, load_settings
from codeintel_rev.errors import RuntimeLifecycleError, RuntimeUnavailableError
from codeintel_rev.evaluation.offline_recall import OfflineRecallEvaluator
from codeintel_rev.indexing.index_lifecycle import IndexLifecycleManager
from codeintel_rev.io.bm25_engine import (
    BM25Backend,
    BM25Engine,
    BM25Rm3Config,
    PyseriniBM25Backend,
)
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.duckdb_manager import DuckDBConfig, DuckDBManager
from codeintel_rev.io.faiss_manager import FAISSManager, FAISSRuntimeOptions
from codeintel_rev.io.git_client import AsyncGitClient, GitClient
from codeintel_rev.io.splade_engine import (
    SpladeBackend,
    SPLADEEngine,
    SpladeImpactBackend,
    SpladeImpactBackendConfig,
    SpladeQueryRepresentation,
)
from codeintel_rev.io.vllm_client import VLLMClient, build_vllm_client
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Options
from codeintel_rev.retrieval.rm3_heuristics import RM3Heuristics, RM3Params
from codeintel_rev.runtime import (
    NullRuntimeCellObserver,
    RuntimeCell,
    RuntimeCellObserver,
    allow_runtime_cell_seeding,
)
from codeintel_rev.runtime.factory_adjustment import (
    DefaultFactoryAdjuster,
    FactoryAdjuster,
    NoopFactoryAdjuster,
)
from codeintel_rev.runtime.imports import gate_import
from codeintel_rev.runtime.multiprocessing import ensure_spawn_start_method
from codeintel_rev.typing import NDArrayF32
from kgfoundry_common.errors import ConfigurationError
from kgfoundry_common.logging import setup_logging

ensure_spawn_start_method()

if TYPE_CHECKING:
    from collections.abc import Iterator

    from codeintel_rev.app.scope_store import SupportsAsyncRedis
    from codeintel_rev.io.hybrid_search import HybridSearchEngine
    from codeintel_rev.io.splade_onnx_encoder import (
        OnnxSpladeConfig,
        OnnxSpladeMapEncoder,
        OnnxSpladeQueryEncoder,
    )
    from codeintel_rev.io.xtr_manager import XTRIndex
else:  # pragma: no cover - runtime only; annotations are postponed
    HybridSearchEngine = Any
    XTRIndex = Any
    try:
        from codeintel_rev.io.splade_onnx_encoder import (
            OnnxSpladeConfig,
            OnnxSpladeMapEncoder,
            OnnxSpladeQueryEncoder,
        )
    except ImportError:
        OnnxSpladeConfig = None
        OnnxSpladeMapEncoder = None
        OnnxSpladeQueryEncoder = None

_RUNTIME_FAILURE_TTL_S = 15.0
_AUTOTUNE_SAMPLE_LIMIT = 128
_MIN_AUTOTUNE_SAMPLES = 4


__all__ = [
    "ApplicationContext",
    "ApplicationContextOverrides",
    "GateConfig",
    "ResolvedPaths",  # re-export during transition to codeintel_rev.config.paths
    "merge_paths_with_app_config",
    "override_gate_config",
    "paths",
    "resolve_application_paths",
    "set_paths",
]


@dataclass(slots=True, frozen=True)
class ApplicationContextOverrides:
    """Optional dependency overrides for :meth:`ApplicationContext.create`.

    Attributes
    ----------
    runtime_observer : RuntimeCellObserver | None
        Observer installed on runtime cells for instrumentation. When ``None``,
        :class:`NullRuntimeCellObserver` is used.
    factory_adjuster : FactoryAdjuster | None
        Override for the runtime factory adjuster. Defaults to an instance built
        from :class:`Settings`.
    vllm_client : VLLMClient | None
        Preconstructed vLLM client. When omitted, :func:`build_vllm_client`
        constructs one using ``app_config.vllm``.
    faiss_manager : FAISSManager | None
        FAISS manager override. The default is constructed from ``settings`` and
        the resolved paths.
    scope_store : ScopeStore | None
        Scope store implementation (Redis-backed). Defaults to the production
        implementation configured via settings.
    duckdb_manager : DuckDBManager | None
        Manager responsible for DuckDB catalog lifecycle. Defaults to
        :class:`DuckDBManager`.
    git_client : GitClient | None
        Synchronous Git client override. When omitted, the default builder loads
        a GitPython-backed client rooted at ``settings.paths.repo_root``.
    async_git_client : AsyncGitClient | None
        Async Git client override that wraps the synchronous client.
    faiss_manager_factory : Callable[..., FAISSManager] | None
        Factory for constructing the FAISS manager. When provided, overrides the
        default import/path resolution. Factories may accept either two arguments
        ``(settings, resolved_paths)`` or three arguments
        ``(settings, resolved_paths, app_config)``; the latter is preferred.
    duckdb_catalog_factory : Callable[[ResolvedPaths, Settings, DuckDBManager], DuckDBCatalog] | None
        Factory for creating DuckDB catalog instances inside :meth:`open_catalog`.
    """

    runtime_observer: RuntimeCellObserver | None = None
    factory_adjuster: FactoryAdjuster | None = None
    vllm_client: VLLMClient | None = None
    faiss_manager: FAISSManager | None = None
    scope_store: ScopeStore | None = None
    duckdb_manager: DuckDBManager | None = None
    git_client: GitClient | None = None
    async_git_client: AsyncGitClient | None = None
    faiss_manager_factory: Callable[..., FAISSManager] | None = None
    duckdb_catalog_factory: (
        Callable[[ResolvedPaths, Settings, DuckDBManager], DuckDBCatalog] | None
    ) = None


@dataclass(slots=True, frozen=True)
class GateConfig:
    """Overrides for runtime dependency gates.

    Attributes
    ----------
    gate_import : Callable[[str, str], object] | None, optional
        Optional override function for gate_import calls. If provided, replaces
        the default gate_import implementation. Used primarily for testing.
        Defaults to None.
    """

    gate_import: Callable[[str, str], object] | None = None


_GATE_CONFIG_STACK: list[GateConfig] = [GateConfig()]


def _configure_logging_from_app(logging_cfg: LoggingSettings) -> None:
    """Configure root logging handlers from AppConfig logging settings."""
    if getattr(_configure_logging_from_app, "configured", False):
        return
    level_name = (logging_cfg.level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    if logging_cfg.json:
        setup_logging(level=level)
    else:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            force=True,
        )
    _configure_logging_from_app.configured = True  # type: ignore[attr-defined]


@contextmanager
def override_gate_config(**kwargs: object) -> Iterator[None]:
    """Temporarily override dependency gate configuration."""
    config = replace(_GATE_CONFIG_STACK[-1], **kwargs)
    _GATE_CONFIG_STACK.append(config)
    try:
        yield
    finally:
        _GATE_CONFIG_STACK.pop()


def _call_gate_import(module: str, purpose: str) -> object:
    """Call gate_import with optional override from gate config stack.

    Parameters
    ----------
    module : str
        Module name to import via gate.
    purpose : str
        Purpose string describing why the module is needed.

    Returns
    -------
    object
        Imported module (or stub) from override if configured, otherwise
        result from gate_import().
    """
    override = _GATE_CONFIG_STACK[-1].gate_import
    if override is not None:
        return override(module, purpose)
    return gate_import(module, purpose)


_PATH_CACHE: ContextVar[ResolvedPaths | None] = ContextVar("_PATH_CACHE", default=None)


def set_paths(resolved: ResolvedPaths) -> None:
    """Install ``resolved`` for backwards-compatible global access.

    Parameters
    ----------
    resolved : ResolvedPaths
        Canonical filesystem layout produced by :func:`resolve_application_paths`.
    """
    _PATH_CACHE.set(resolved)


def _ensure_filesystem_readiness(paths: ResolvedPaths) -> None:
    """Validate filesystem readiness."""
    readiness_results = fs_readiness.validate_paths(paths)
    fs_readiness.raise_on_errors(readiness_results)


def paths() -> ResolvedPaths:
    """Return the cached :class:`ResolvedPaths` for legacy callers.

    Returns
    -------
    ResolvedPaths
        The most recently installed paths object.

    Raises
    ------
    RuntimeLifecycleError
        Raised when the paths cache is empty, meaning
        :func:`ApplicationContext.create` has not been invoked yet.
    """
    cached = _PATH_CACHE.get()
    if cached is None:
        msg = "paths() called before ApplicationContext initialization"
        raise RuntimeLifecycleError(msg, runtime="config-context")
    warnings.warn(
        "config_context.paths() is deprecated; inject ResolvedPaths explicitly",
        DeprecationWarning,
        stacklevel=2,
    )
    return cached


@dataclass(slots=True)
class RuntimeFactoryOverrides:
    """Test-only overrides for runtime factory callables.

    Attributes
    ----------
    hybrid_engine_factory : Callable[[], HybridSearchEngine] | None, optional
        Optional factory function for creating HybridSearchEngine instances.
        If provided, replaces the default factory. Used primarily for testing.
        Defaults to None.
    """

    hybrid_engine_factory: Callable[[], HybridSearchEngine] | None = None


def _infer_index_root(paths: ResolvedPaths) -> Path:
    """Return the directory that stores versioned index assets.

    Parameters
    ----------
    paths : ResolvedPaths
        Resolved application paths containing FAISS index location.

    Returns
    -------
    Path
        Directory containing the lifecycle manifest and versions. If
        `CODEINTEL_INDEXES_DIR` environment variable is set, uses that path.
        Otherwise infers from `paths.faiss_index` parent directory structure.

    Notes
    -----
    This helper determines the index root directory for versioned index lifecycle
    management. The root contains subdirectories for each version and a manifest
    tracking published/active versions.
    """
    env_override = os.getenv("CODEINTEL_INDEXES_DIR")
    if env_override:
        return Path(env_override).expanduser().resolve()
    faiss_parent = paths.faiss_index.parent
    if faiss_parent.name == "current":
        return faiss_parent.parent
    return faiss_parent


def _build_factory_adjuster(index_cfg: IndexSettings) -> FactoryAdjuster:
    """Return a DefaultFactoryAdjuster derived from index settings.

    Parameters
    ----------
    index_cfg : IndexSettings
        Immutable index configuration sourced from :class:`AppConfig`.

    Returns
    -------
    FactoryAdjuster
        Adjuster informed by AppConfig defaults. If configuration is invalid,
        returns :class:`NoopFactoryAdjuster`.
    """
    try:
        rrf_weights = dict(index_cfg.rrf_weights)
        return DefaultFactoryAdjuster(
            faiss_nprobe=index_cfg.faiss_nprobe,
            hybrid_rrf_k=index_cfg.rrf_k,
            hybrid_bm25_weight=rrf_weights.get("bm25"),
            hybrid_splade_weight=rrf_weights.get("splade"),
        )
    except (AttributeError, TypeError, ValueError):  # pragma: no cover - defensive
        return NoopFactoryAdjuster()


def _build_faiss_manager(
    settings: Settings,
    paths: ResolvedPaths,
    app_config: AppConfig,
    *,
    factory: Callable[..., FAISSManager] | None = None,
) -> FAISSManager:
    """Construct and log the FAISS manager for the main index.

    Parameters
    ----------
    settings : Settings
        Application settings containing index configuration.
    paths : ResolvedPaths
        Resolved filesystem paths including FAISS index path.
    app_config : AppConfig
        Immutable configuration containing FAISS-specific defaults (paths,
        runtime tuning values).
    factory : Callable[..., FAISSManager] | None, optional
        Optional override factory. When provided, takes precedence over the default
        FAISS manager construction logic.

    Returns
    -------
    manager : FAISSManager
        Configured FAISS manager instance.

    Raises
    ------
    ConfigurationError
        If IndexSettings.nlist is None during context creation.
    """
    if factory is not None:
        try:
            return factory(settings, paths, app_config)
        except TypeError:
            return factory(settings, paths)
    faiss_manager_cls = _import_faiss_manager_cls()
    index_cfg = app_config.index
    runtime_opts = _faiss_runtime_options_from_config(index_cfg, app_config.faiss)
    nlist_value = index_cfg.nlist
    if nlist_value is None:
        msg = "IndexSettings.nlist cannot be None during context creation"
        raise ConfigurationError(msg)
    return faiss_manager_cls(
        index_path=app_config.faiss.index_path,
        vec_dim=index_cfg.vec_dim,
        nlist=nlist_value,
        runtime=runtime_opts,
    )


def _build_duckdb_catalog_from_app_config(
    paths: ResolvedPaths,
    app_config: AppConfig,
    manager: DuckDBManager,
    *,
    log_queries: bool,
) -> DuckDBCatalog:
    """Return a DuckDB catalog configured from AppConfig data."""

    catalog = DuckDBCatalog(
        paths.duckdb_path,
        paths.vectors_dir,
        materialize=app_config.index.duckdb_materialize,
        manager=manager,
        log_queries=log_queries,
        repo_root=paths.repo_root,
    )
    catalog.set_idmap_path(paths.faiss_idmap_path)
    return catalog


def _build_scope_store(settings: Settings) -> ScopeStore:
    """Return the session scope store backed by redis.asyncio.

    Parameters
    ----------
    settings : Settings
        Application settings containing Redis configuration.

    Returns
    -------
    store : ScopeStore
        Configured scope store instance.
    """
    redis_asyncio = cast(
        "ModuleType",
        _call_gate_import("redis.asyncio", "Session scope store requires redis extra"),
    )
    redis_client = redis_asyncio.from_url(settings.redis.url)
    return ScopeStore(
        cast("SupportsAsyncRedis", redis_client),
        l1_maxsize=settings.redis.scope_l1_size,
        l1_ttl_seconds=settings.redis.scope_l1_ttl_seconds,
        l2_ttl_seconds=settings.redis.scope_l2_ttl_seconds,
    )


def _build_git_clients(paths: ResolvedPaths) -> tuple[GitClient, AsyncGitClient]:
    """Initialize Git clients for blame and history operations.

    Parameters
    ----------
    paths : ResolvedPaths
        Resolved filesystem paths including repository root.

    Returns
    -------
    clients : tuple[GitClient, AsyncGitClient]
        Pair of synchronous and asynchronous Git clients.
    """
    git_client = GitClient(repo_path=paths.repo_root)
    async_git_client = AsyncGitClient(git_client)
    return git_client, async_git_client


def _select_git_clients(
    paths: ResolvedPaths,
    overrides: ApplicationContextOverrides,
) -> tuple[GitClient, AsyncGitClient]:
    """Return Git clients, applying overrides when provided.

    Parameters
    ----------
    paths : ResolvedPaths
        Resolved path configuration.
    overrides : ApplicationContextOverrides
        Optional client overrides.

    Returns
    -------
    tuple[GitClient, AsyncGitClient]
        Tuple of (sync, async) Git clients.
    """
    if overrides.git_client and overrides.async_git_client:
        return overrides.git_client, overrides.async_git_client
    if overrides.git_client:
        return overrides.git_client, AsyncGitClient(overrides.git_client)
    primary_git_client, primary_async_client = _build_git_clients(paths)
    if overrides.async_git_client:
        return primary_git_client, overrides.async_git_client
    return primary_git_client, primary_async_client


_FROZEN_SETATTR = object.__setattr__


def _assign_frozen(instance: object, name: str, value: object) -> None:
    """Assign attribute on a frozen dataclass instance."""
    _FROZEN_SETATTR(instance, name, value)


def _faiss_module() -> ModuleType:
    """Return the cached FAISS manager module.

    Returns
    -------
    ModuleType
        Imported FAISS manager module.
    """
    cached = globals().get("_FAISS_MODULE")
    if cached is not None:
        return cast("ModuleType", cached)
    module = importlib.import_module("codeintel_rev.io.faiss_manager")
    globals()["_FAISS_MODULE"] = module
    return module


def _import_faiss_manager_cls() -> type[FAISSManager]:
    """Import ``FAISSManager`` lazily to keep module import costs low.

    Returns
    -------
    type[FAISSManager]
        Resolved manager class.
    """
    module = _faiss_module()
    return cast("type[FAISSManager]", module.FAISSManager)


def _import_faiss_runtime_opts_cls() -> type:
    """Return the FAISS runtime options dataclass.

    Returns
    -------
    type
        Runtime options dataclass exported by ``codeintel_rev.io.faiss_manager``.
    """
    module = _faiss_module()
    return module.FAISSRuntimeOptions


def _faiss_runtime_options_from_index(index_cfg: IndexSettings) -> FAISSRuntimeOptions:
    """Materialize FAISS runtime options from the structured index config.

    Parameters
    ----------
    index_cfg : IndexConfig
        Structured index configuration containing FAISS parameters (family, PQ
        settings, and HNSW parameters).

    Returns
    -------
    FAISSRuntimeOptions
        Instance of ``FAISSRuntimeOptions`` matching ``index_cfg`` parameters.
        The returned object is used to configure FAISS manager runtime behavior.

    Notes
    -----
    This helper converts structured ``IndexSettings`` (from AppConfig or index
    manifest) into FAISS-specific runtime options for the CPU-only runtime. It
    dynamically imports the FAISS runtime options class and instantiates it with
    values from the config.
    """
    runtime_cls = _import_faiss_runtime_opts_cls()
    return runtime_cls(
        faiss_family=index_cfg.faiss_family,
        pq_m=index_cfg.pq_m,
        pq_nbits=index_cfg.pq_nbits,
        opq_m=index_cfg.opq_m,
        default_nprobe=index_cfg.default_nprobe,
        default_k=index_cfg.default_k,
        hnsw_m=index_cfg.hnsw_m,
        hnsw_ef_construction=index_cfg.hnsw_ef_construction,
        hnsw_ef_search=index_cfg.hnsw_ef_search,
        refine_k_factor=index_cfg.refine_k_factor,
        autotune_on_start=index_cfg.autotune_on_start,
        enable_range_search=index_cfg.enable_range_search,
        semantic_min_score=index_cfg.semantic_min_score,
    )


def _faiss_runtime_options_from_config(
    index_cfg: IndexSettings,
    faiss_cfg: FAISSSettings,
) -> FAISSRuntimeOptions:
    """Return runtime options merged from Settings and AppConfig.

    Parameters
    ----------
    index_cfg : IndexSettings
        Index configuration from AppConfig.
    faiss_cfg : FAISSSettings
        FAISS-specific settings from AppConfig.

    Returns
    -------
    FAISSRuntimeOptions
        Runtime configuration with AppConfig overrides applied.
    """
    opts = _faiss_runtime_options_from_index(index_cfg)
    return replace(
        opts,
        default_k=int(faiss_cfg.default_k),
        default_nprobe=faiss_cfg.default_nprobe or opts.default_nprobe,
        refine_k_factor=float(faiss_cfg.refine_k_factor),
    )


def _duckdb_config_from_app(app_config: AppConfig) -> DuckDBConfig:
    """Convert structured DuckDB settings to manager configuration.

    Parameters
    ----------
    app_config : AppConfig
        Immutable application configuration produced by :func:`load_app_config`.

    Returns
    -------
    DuckDBConfig
        Manager configuration mirroring the DuckDB settings contained in
        :class:`AppConfig`.
    """
    duckdb_settings = app_config.duckdb
    defaults = DuckDBConfig()
    threads = duckdb_settings.threads if duckdb_settings.threads is not None else defaults.threads
    pool_size = duckdb_settings.pool_size if duckdb_settings.pool_size else None
    return DuckDBConfig(
        threads=threads,
        enable_object_cache=duckdb_settings.object_cache,
        log_queries=defaults.log_queries,
        pool_size=pool_size,
    )


def _parse_head_terms(csv_value: str | None) -> list[str]:
    """Return normalized head terms parsed from an optional CSV string.

    Parameters
    ----------
    csv_value : str | None
        Optional comma-separated string of head terms.

    Returns
    -------
    list[str]
        Ordered list of normalized head terms (empty when ``csv_value`` is falsy).
    """
    if not csv_value:
        return []
    terms = [part.strip() for part in csv_value.split(",")]
    return [term for term in terms if term]


def _import_hybrid_engine_cls() -> type[HybridSearchEngine]:
    """Import ``HybridSearchEngine`` lazily for runtime cell initialization.

    Returns
    -------
    type[HybridSearchEngine]
        Hybrid search engine class.
    """
    existing = globals().get("HybridSearchEngine")
    if existing is not None and existing is not Any:
        return cast("type[HybridSearchEngine]", existing)
    module = importlib.import_module("codeintel_rev.io.hybrid_search")
    engine_cls = module.HybridSearchEngine
    globals()["HybridSearchEngine"] = engine_cls
    return engine_cls


def _import_xtr_index_cls() -> type[XTRIndex]:
    """Import ``XTRIndex`` lazily to avoid eager heavy dependencies.

    Returns
    -------
    type[XTRIndex]
        XTR index class.
    """
    existing = globals().get("XTRIndex")
    if existing is not None and existing is not Any:
        return cast("type[XTRIndex]", existing)
    module = importlib.import_module("codeintel_rev.io.xtr_manager")
    index_cls = module.XTRIndex
    globals()["XTRIndex"] = index_cls
    return index_cls


def _require_dependency(module: str, *, runtime: str, purpose: str) -> None:
    """Ensure a heavy dependency is available, raising RuntimeUnavailableError.

    Extended Summary
    ----------------
    Validates that an optional runtime dependency can be imported before
    constructing runtime components. This function gates access to heavy
    dependencies (e.g., FAISS, CUDA libraries) that may not be installed
    in all deployment environments. Used during ApplicationContext
    initialization to fail-fast when required runtimes are unavailable.

    Parameters
    ----------
    module : str
        Python module name to import (e.g., "faiss", "cupy").
        Must be importable via `importlib.import_module()`.
    runtime : str
        Human-readable runtime identifier for error messages
        (e.g., "coderank-faiss", "xtr-index").
    purpose : str
        Brief description of why this dependency is needed,
        included in error messages for diagnostics.

    Raises
    ------
    RuntimeUnavailableError
        If ``module`` cannot be imported. The error includes the
        runtime identifier, purpose, and underlying ImportError detail.

    Notes
    -----
    Uses `gate_import()` from :mod:`codeintel_rev.runtime.imports` to safely
    attempt the import. Time O(1); no I/O or state mutations.
    This is a fail-fast validation helper, not a lazy loader.

    Examples
    --------
    >>> # doctest: +SKIP
    >>> # Example requires faiss to be installed
    >>> _require_dependency("faiss", runtime="test", purpose="vector search")
    >>> # If module is not installed:
    >>> _require_dependency("nonexistent_module_xyz", runtime="test", purpose="demo")
    Traceback (most recent call last):
        ...
    RuntimeUnavailableError: ...test runtime unavailable: demo...
    """
    try:
        _call_gate_import(module, purpose)
    except ImportError as exc:  # pragma: no cover - exercised via unit tests
        detail = str(exc)
        message = f"{runtime} runtime unavailable: {purpose}"
        raise RuntimeUnavailableError(
            message,
            runtime=runtime,
            detail=detail,
            cause=exc,
        ) from exc


def _ensure_path_exists(path: Path, *, runtime: str, description: str) -> None:
    """Validate that a filesystem path exists for a given runtime.

    Extended Summary
    ----------------
    Checks filesystem existence of a required resource path (index files,
    data directories, etc.) before constructing runtime components.
    Used during ApplicationContext initialization to fail-fast when
    configured resources are missing. This prevents runtime errors
    during request handling by catching missing resources at startup.

    Parameters
    ----------
    path : Path
        Filesystem path to validate. Must be absolute or relative
        to the repository root. Resolved via `pathlib.Path.resolve()`.
    runtime : str
        Human-readable runtime identifier for error messages
        (e.g., "coderank-faiss", "xtr-index").
    description : str
        Brief description of what the path represents,
        included in error messages (e.g., "CodeRank FAISS index").

    Raises
    ------
    RuntimeUnavailableError
        If ``path`` does not exist. The error includes the runtime
        identifier, description, and the absolute path string.

    Notes
    -----
    Time O(1) filesystem stat; no I/O beyond existence check.
    This is a fail-fast validation helper, not a lazy loader.
    Paths are expected to be pre-resolved by `resolve_application_paths()`.

    Examples
    --------
    >>> from pathlib import Path
    >>> import tempfile
    >>> # doctest: +SKIP
    >>> # Example with existing path (requires temp directory)
    >>> with tempfile.TemporaryDirectory() as tmpdir:
    ...     _ensure_path_exists(Path(tmpdir), runtime="test", description="temp")
    >>> # Missing path raises error:
    >>> _ensure_path_exists(Path("/nonexistent/path/xyz"), runtime="test", description="index")
    Traceback (most recent call last):
        ...
    RuntimeUnavailableError: ...index not found...
    """
    if path.exists():
        return
    message = f"{description} not found"
    raise RuntimeUnavailableError(
        message,
        runtime=runtime,
        detail=str(path),
    )


class _DisabledBM25Backend(BM25Backend):
    """No-op BM25 backend used when the BM25 channel is disabled."""

    def search(self, query_text: str, k: int) -> list[tuple[int, float]]:
        """Return an empty result set regardless of inputs.

        Parameters
        ----------
        query_text : str
            Query text (ignored).
        k : int
            Maximum results (ignored).

        Returns
        -------
        list[tuple[int, float]]
            Empty list.
        """
        _ = self, query_text, k
        return []


class _DisabledSpladeBackend(SpladeBackend):  # type: ignore[misc]
    """No-op SPLADE backend used when the SPLADE channel is disabled."""

    def encode_query(self, text: str) -> SpladeQueryRepresentation:
        """Return a zero vector to satisfy the SPLADE contract.

        Parameters
        ----------
        text : str
            Query text (ignored).

        Returns
        -------
        SpladeQueryRepresentation
            Zero vector of shape (1,) wrapped in a SpladeQueryRepresentation.
        """
        _ = self, text
        return cast("NDArrayF32", np.zeros((1,), dtype=np.float32))

    def search(self, query_vec: SpladeQueryRepresentation, k: int) -> list[tuple[int, float]]:
        """Return an empty result set regardless of inputs.

        Parameters
        ----------
        query_vec : SpladeQueryRepresentation
            Query vector (ignored).
        k : int
            Maximum results (ignored).

        Returns
        -------
        list[tuple[int, float]]
            Empty list.
        """
        _ = self, query_vec, k
        return []


T = TypeVar("T")


class _FaissRuntimeState:
    """Runtime bookkeeping for FAISS initialization.

    Creates a new state tracker with a lock for thread-safe initialization
    tracking and a loaded flag indicating whether FAISS has been initialized.
    """

    __slots__ = ("loaded", "lock")

    def __init__(self) -> None:
        """Initialize FAISS runtime state tracker.

        Creates a new state tracker with a lock for thread-safe initialization
        tracking and a loaded flag indicating whether FAISS has been initialized.
        """
        self.lock = Lock()
        self.loaded = False


@dataclass(slots=True, frozen=True)
class _ContextRuntimeState:
    """Mutable runtime state backing the frozen ApplicationContext.

    Attributes
    ----------
    hybrid : RuntimeCell[HybridSearchEngine]
        Runtime cell for the hybrid search engine. Lazily initialized on first
        access and shared across requests.
    coderank_faiss : RuntimeCell[FAISSManager]
        Runtime cell for the CodeRank FAISS index manager. Lazily initialized
        on first access.
    xtr : RuntimeCell[XTRIndex]
        Runtime cell for the XTR token-level index. Lazily initialized on first
        access.
    faiss : _FaissRuntimeState
        FAISS runtime state tracker for initialization bookkeeping and thread
        safety.
    """

    hybrid: RuntimeCell[HybridSearchEngine] = field(
        default_factory=lambda: RuntimeCell(name="hybrid-engine")
    )
    coderank_faiss: RuntimeCell[FAISSManager] = field(
        default_factory=lambda: RuntimeCell(name="coderank-faiss")
    )
    xtr: RuntimeCell[XTRIndex] = field(default_factory=lambda: RuntimeCell(name="xtr-index"))
    faiss: _FaissRuntimeState = field(default_factory=_FaissRuntimeState)

    def attach_observer(self, observer: RuntimeCellObserver) -> None:
        """Attach observer to each runtime cell."""
        self.hybrid.configure_observer(observer)
        self.coderank_faiss.configure_observer(observer)
        self.xtr.configure_observer(observer)

    def attach_adjuster(self, adjuster: FactoryAdjuster) -> None:
        """Attach a factory adjuster to each runtime cell."""
        self.hybrid.configure_adjuster(adjuster)
        self.coderank_faiss.configure_adjuster(adjuster)
        self.xtr.configure_adjuster(adjuster)

    def iter_cells(self) -> tuple[tuple[str, RuntimeCell[Any]], ...]:
        """Return ordered tuples of runtime cell names and instances.

        Returns
        -------
        tuple[tuple[str, RuntimeCell[Any]], ...]
            Ordered collection of runtime cell name/value pairs.
        """
        return (
            ("hybrid", cast("RuntimeCell[Any]", self.hybrid)),
            ("coderank-faiss", cast("RuntimeCell[Any]", self.coderank_faiss)),
            ("xtr", cast("RuntimeCell[Any]", self.xtr)),
        )


@dataclass(slots=True, frozen=True)
class ApplicationContext:
    """Application-wide context holding all configuration and long-lived clients.

    This is the single source of truth for configuration throughout the application.
    It's initialized once during FastAPI startup (in lifespan() function) and
    injected into request handlers via app.state.

    The context is NOT a global singleton - it's explicitly passed as a parameter
    to all functions that need it. This makes dependencies explicit and testing
    straightforward.

    Attributes
    ----------
    app_config : AppConfig
        Immutable configuration loaded via :func:`load_app_config` that captures
        path, DuckDB, FAISS, search, and logging settings external to the legacy
        ``Settings`` model.
    settings : Settings
        Immutable application settings loaded from environment variables. Frozen
        after creation to ensure thread-safe access.
    paths : ResolvedPaths
        Canonicalized filesystem paths for all resources (repo root, indexes, etc.).
        All paths are absolute.
    vllm_client : VLLMClient
        vLLM embedding service client with persistent HTTP connection pool.
        Shared across all requests for efficiency.
    faiss_manager : FAISSManager
        FAISS index manager backed by the CPU-only runtime. Index data is preloaded
        into host memory during startup when configured to minimize cold-start cost.
    scope_store : ScopeStore
        Redis-backed scope store for session-scoped query filters with L1/L2 caching.
    duckdb_manager : DuckDBManager
        DuckDB manager for managing the DuckDB catalog database.
    git_client : GitClient
        Typed Git operations client using GitPython. Provides structured APIs for
        blame and history operations without subprocess overhead. Lazy-initializes
        Git repository on first access.
    async_git_client : AsyncGitClient
        Async wrapper around git_client for non-blocking Git operations. Runs
        synchronous GitPython operations in threadpool via asyncio.to_thread.
    duckdb_catalog_factory : Callable[[ResolvedPaths, Settings, DuckDBManager], DuckDBCatalog]
        Factory used to construct catalog instances when :meth:`open_catalog` is invoked.
    runtime_observer : RuntimeCellObserver
        Observer instance that receives lifecycle callbacks from runtime cells
        (hybrid engine, FAISS manager, XTR index). Defaults to NullRuntimeCellObserver
        when not provided. Used for instrumentation, monitoring, and diagnostics.
    factory_adjuster : FactoryAdjuster
        Adjuster applied to runtime cell factories to inject tuning parameters
        (e.g., FAISS nprobe, hybrid RRF weights). Defaults to NoopFactoryAdjuster
        if not provided. Can be updated at runtime via `apply_factory_adjuster()`.
    index_manager : IndexLifecycleManager
        Manager for versioned index lifecycle operations (stage, publish, rollback).
        Initialized during context setup with index root inferred from paths.
        Provides APIs for managing index versions and manifests.

    Examples
    --------
    Create context during application startup:

    >>> context = ApplicationContext.create()
    >>> context.settings.paths.repo_root
    '/home/user/kgfoundry'

    Use context in adapter functions:

    >>> def list_paths(context: ApplicationContext, ...) -> dict:
    ...     repo_root = context.paths.repo_root
    ...     # ... use repo_root for file operations

    Access from FastAPI request handler:

    >>> @app.get("/api/endpoint")
    >>> async def handler(request: Request):
    ...     context = request.app.state.context
    ...     # ... use context

    Notes
    -----
    The context is designed to be immutable after creation (settings and paths
    are frozen dataclasses). The FAISS manager and vLLM client maintain internal
    state (connection pools, loaded indexes) but their configuration cannot be
    changed after initialization.

    See Also
    --------
    resolve_application_paths : Creates ResolvedPaths from Settings
    ApplicationContext.create : Factory method for creating context
    """

    app_config: AppConfig
    settings: Settings
    paths: ResolvedPaths
    vllm_client: VLLMClient
    faiss_manager: FAISSManager
    scope_store: ScopeStore
    duckdb_manager: DuckDBManager
    git_client: GitClient
    async_git_client: AsyncGitClient
    duckdb_catalog_factory: Callable[
        [ResolvedPaths, Settings, DuckDBManager], DuckDBCatalog
    ] | None = field(default=None, repr=False)
    runtime_observer: RuntimeCellObserver = field(
        default_factory=NullRuntimeCellObserver, repr=False
    )
    factory_adjuster: FactoryAdjuster = field(default_factory=NoopFactoryAdjuster, repr=False)
    _runtime: _ContextRuntimeState = field(
        default_factory=_ContextRuntimeState, init=False, repr=False
    )
    index_manager: IndexLifecycleManager = field(init=False, repr=False)
    _offline_evaluator: OfflineRecallEvaluator | None = field(default=None, init=False, repr=False)
    _runtime_factories: RuntimeFactoryOverrides | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Attach the configured observer to all runtime cells."""
        self._runtime.attach_observer(self.runtime_observer)
        self._runtime.attach_adjuster(self.factory_adjuster)
        index_root = _infer_index_root(self.paths)
        _assign_frozen(self, "index_manager", IndexLifecycleManager(index_root))
        if self.duckdb_catalog_factory is None:
            log_queries = getattr(self.settings.duckdb, "log_queries", False)

            def _factory(
                resolved: ResolvedPaths,
                _legacy_settings: Settings,
                manager: DuckDBManager,
            ) -> DuckDBCatalog:
                return _build_duckdb_catalog_from_app_config(
                    resolved,
                    self.app_config,
                    manager,
                    log_queries=log_queries,
                )

            _assign_frozen(self, "duckdb_catalog_factory", _factory)

    @classmethod
    def create(
        cls,
        *,
        settings: Settings | None = None,
        overrides: ApplicationContextOverrides | None = None,
        app_config: AppConfig | None = None,
    ) -> ApplicationContext:
        """Create application context from environment variables.

        Extended Summary
        ----------------
        This is the primary way to create an ApplicationContext. It loads settings
        from environment variables, resolves and validates all filesystem paths,
        creates long-lived HTTP and index manager clients, and logs successful
        initialization with key configuration values. The method is designed to
        be called exactly once during application startup (typically in the FastAPI
        lifespan() function). Configuration errors cause ConfigurationError to be
        raised by resolve_application_paths(), preventing application startup with
        clear error messages including RFC 9457 Problem Details.

        Parameters
        ----------
        settings : Settings | None, optional
            Preconstructed settings object. When None (default), settings are
            loaded via ``load_settings()``.
        overrides : ApplicationContextOverrides | None, optional
            Optional dependency overrides. Useful for injecting fakes in tests
            or for swapping runtime observers, factory adjusters, and storage
            adapters. When ``None`` (default) the method constructs all components
            using production builders.
        app_config : AppConfig | None, optional
            Immutable configuration loaded from environment variables and optional
            configuration files. When ``None`` (default), this method loads the
            config via :func:`load_app_config`, honoring the
            ``CODEINTEL_CONFIG_FILE`` environment variable.

        Returns
        -------
        ApplicationContext
            Initialized context with all clients and configuration ready. The context
            is frozen after creation and thread-safe for concurrent access.

        Raises
        ------
        ConfigurationError
            Raised when filesystem readiness checks fail (for example, when the
            repository root does not exist).

        Examples
        --------
        >>> # In FastAPI lifespan() function
        >>> @asynccontextmanager
        >>> async def lifespan(app: FastAPI):
        ...     context = ApplicationContext.create()
        ...     app.state.context = context
        ...     yield

        >>> # With custom observer for instrumentation
        >>> from codeintel_rev.app.config_context import ApplicationContextOverrides
        >>> observer = MyCustomObserver()
        >>> overrides = ApplicationContextOverrides(runtime_observer=observer)
        >>> context = ApplicationContext.create(overrides=overrides)

        Notes
        -----
        Time complexity O(1) for context creation; I/O occurs during path resolution
        and client initialization. The method performs filesystem operations to validate
        paths and may establish network connections for HTTP clients. Thread-safe after
        creation due to frozen dataclass design. The method is idempotent in the sense
        that calling it multiple times creates independent contexts, but it should only
        be called once per application lifecycle.

        This method may propagate ConfigurationError from resolve_application_paths()
        if paths cannot be resolved or validated. The exception includes RFC 9457 Problem
        Details with context fields for debugging (repo_root value, source environment
        variable) and causes application startup to fail.

        See Also
        --------
        load_settings : Loads Settings from environment variables
        resolve_application_paths : Validates and resolves paths
        """
        effective_overrides = overrides or ApplicationContextOverrides()
        app_config = app_config or load_app_config(file=os.environ.get("CODEINTEL_CONFIG_FILE"))
        if settings is None:
            settings = load_settings()
            paths = resolve_application_paths(app_config)
        else:
            paths = merge_paths_with_app_config(resolve_application_paths(settings), app_config)
        try:
            _ensure_filesystem_readiness(paths)
        except fs_readiness.ReadinessError as exc:
            message = f"Repository root does not exist or failed readiness checks; details: {exc}"
            raise ConfigurationError(message) from exc
        set_paths(paths)
        _configure_logging_from_app(app_config.logging)

        vllm_client = effective_overrides.vllm_client or build_vllm_client(app_config.vllm)
        faiss_manager = effective_overrides.faiss_manager or _build_faiss_manager(
            settings,
            paths,
            app_config,
            factory=effective_overrides.faiss_manager_factory,
        )
        scope_store = effective_overrides.scope_store or _build_scope_store(settings)
        duckdb_manager = effective_overrides.duckdb_manager or DuckDBManager(
            app_config.duckdb.database, _duckdb_config_from_app(app_config)
        )
        if effective_overrides.duckdb_catalog_factory is not None:
            duckdb_catalog_factory = effective_overrides.duckdb_catalog_factory
        else:
            log_queries = settings.duckdb.log_queries

            def _factory(
                resolved: ResolvedPaths,
                legacy_settings: Settings,
                manager: DuckDBManager,
            ) -> DuckDBCatalog:
                return _build_duckdb_catalog_from_app_config(
                    resolved,
                    app_config,
                    manager,
                    log_queries=log_queries,
                )

            duckdb_catalog_factory = _factory
        git_client, async_git_client = _select_git_clients(paths, effective_overrides)

        observer = effective_overrides.runtime_observer or NullRuntimeCellObserver()

        adjuster = effective_overrides.factory_adjuster or _build_factory_adjuster(app_config.index)
        return cls(
            app_config=app_config,
            settings=settings,
            paths=paths,
            vllm_client=vllm_client,
            faiss_manager=faiss_manager,
            scope_store=scope_store,
            duckdb_manager=duckdb_manager,
            duckdb_catalog_factory=duckdb_catalog_factory,
            git_client=git_client,
            async_git_client=async_git_client,
            runtime_observer=observer,
            factory_adjuster=adjuster,
        )

    def _iter_runtime_cells(self) -> tuple[tuple[str, RuntimeCell[Any]], ...]:
        """Return managed runtime cells for diagnostics and cleanup.

        Returns
        -------
        tuple[tuple[str, RuntimeCell[Any]], ...]
            Tuple of runtime cell name/value pairs.
        """
        return self._runtime.iter_cells()

    def reload_indices(self) -> None:
        """Close runtime cells so they reopen against the active index version."""
        for _, cell in self._iter_runtime_cells():
            try:
                cell.close()
            except (
                RuntimeError,
                OSError,
                ValueError,
            ):  # pragma: no cover - defensive logging
                continue
        faiss_state = self._runtime.faiss
        with faiss_state.lock:
            faiss_state.loaded = False
        self.faiss_manager.cpu_index = None

    def _autotune_if_requested(self) -> None:
        """Run a quick ParameterSpace sweep when enabled and no profile exists."""
        if not self.app_config.index.autotune_on_start:
            return
        legacy_path = getattr(self.faiss_manager, "_legacy_autotune_profile_path", None)
        if self.faiss_manager.autotune_profile_path.exists() or (
            legacy_path and legacy_path.exists()
        ):
            return
        try:
            with self.open_catalog() as catalog:
                samples = catalog.sample_query_vectors(limit=_AUTOTUNE_SAMPLE_LIMIT)
        except (OSError, RuntimeError, ValueError):  # pragma: no cover - defensive
            return
        if len(samples) < _MIN_AUTOTUNE_SAMPLES:
            return
        vectors = np.stack([vec for _, vec in samples], dtype=np.float32)
        queries = vectors[: min(32, vectors.shape[0])]
        try:
            self.faiss_manager.autotune(
                queries,
                vectors,
            k=min(self.app_config.index.default_k, queries.shape[0]),
            )
        except (RuntimeError, ValueError):  # pragma: no cover - defensive logging
            return

    def apply_factory_adjuster(self, adjuster: FactoryAdjuster) -> None:
        """Update runtime tuning knobs and reset cells to pick up changes."""
        _assign_frozen(self, "factory_adjuster", adjuster)
        self._runtime.attach_adjuster(adjuster)
        for _, cell in self._iter_runtime_cells():
            try:
                cell.close()
            except (RuntimeError, OSError, ValueError):  # pragma: no cover - defensive
                continue

    def get_hybrid_engine(self) -> HybridSearchEngine:
        """Return the hybrid search engine, instantiating it lazily.

        Returns
        -------
        HybridSearchEngine
            Shared hybrid retrieval engine configured for the current settings.

        Raises
        ------
        RuntimeError
            If the engine fails to initialize.
        """

        def _factory() -> HybridSearchEngine:
            """Build and return a new HybridSearchEngine instance.

            Returns
            -------
            HybridSearchEngine
                Newly constructed hybrid search engine.
            """
            return self._build_hybrid_engine()

        engine = self._runtime.hybrid.get_or_initialize(_factory)
        if engine is None:  # pragma: no cover - defensive
            msg = "HybridSearchEngine failed to initialize"
            raise RuntimeError(msg)
        return engine

    def hybrid_fusion_weights(self) -> dict[str, float]:
        """Return per-channel weights used during hybrid fusion.

        Returns
        -------
        dict[str, float]
            Mapping from channel name to fusion weight derived from AppConfig.
        """
        search_cfg = self.hybrid_search_settings()
        return {
            "bm25": float(search_cfg.bm25_weight),
            "splade": float(search_cfg.splade_weight),
            "semantic": float(search_cfg.faiss_weight),
        }

    def hybrid_search_settings(self) -> SearchSettings:
        """Return immutable hybrid search settings sourced from AppConfig.

        Returns
        -------
        SearchSettings
            Hybrid search configuration defined in AppConfig.
        """
        return self.app_config.search

    def clamp_hybrid_limit(self, requested: int) -> int:
        """Clamp requested Stage-0 limit to the configured bounds.

        Parameters
        ----------
        requested : int
            Caller-supplied limit value.

        Returns
        -------
        int
            Value clamped to ``[1, search.max_results]``.
        """
        max_results = int(self.app_config.search.max_results)
        return max(1, min(int(requested), max_results))

    def build_stage0_options(self, *, weights: Mapping[str, float]) -> Stage0Options:
        """Return Stage-0 options derived from AppConfig search settings.

        Parameters
        ----------
        weights : Mapping[str, float]
            Channel weights applied during fusion.

        Returns
        -------
        Stage0Options
            Options configured with AppConfig search tunables.
        """
        search_cfg = self.hybrid_search_settings()
        return Stage0Options(
            weights=dict(weights),
            per_channel_k=int(search_cfg.per_channel_k),
            fusion_k=int(search_cfg.fusion_k),
            rrf_base=int(search_cfg.rrf_base),
        )

    def get_offline_recall_evaluator(self) -> OfflineRecallEvaluator:
        """Return the offline recall evaluator for diagnostic runs.

        Returns
        -------
        OfflineRecallEvaluator
            Evaluator bound to the current FAISS manager and catalog paths.

        Raises
        ------
        RuntimeError
            If offline evaluation has been disabled via configuration.
        """
        eval_settings = self.app_config.eval
        if not eval_settings.enabled:
            msg = "Offline evaluation is disabled in configuration"
            raise RuntimeError(msg)
        evaluator = self._offline_evaluator
        if evaluator is not None:
            return evaluator

        faiss_manager = self.get_coderank_faiss_manager(self.app_config.index.vec_dim)
        evaluator = OfflineRecallEvaluator(
            eval_settings=eval_settings,
            repo_root=self.paths.repo_root,
            faiss_manager=faiss_manager,
            vllm_client=self.vllm_client,
            duckdb_manager=self.duckdb_manager,
        )
        _assign_frozen(self, "_offline_evaluator", evaluator)
        return evaluator

    def get_coderank_faiss_manager(self, vec_dim: int) -> FAISSManager:
        """Return a lazily loaded FAISS manager for CodeRank search.

        Parameters
        ----------
        vec_dim : int
            Expected embedding dimension for the CodeRank index.

        Returns
        -------
        FAISSManager
            Configured FAISS manager instance pointing to the CodeRank index.

        Raises
        ------
        ValueError
            If ``vec_dim`` is non-positive or mismatched with the cached index.
        """
        if vec_dim <= 0:
            msg = "vec_dim must be positive for CodeRank FAISS manager."
            raise ValueError(msg)
        cell = self._runtime.coderank_faiss
        existing = cell.peek()
        if existing is not None:
            if existing.vec_dim != vec_dim:
                existing_dim = existing.vec_dim
                msg = (
                    "Existing CodeRank index dimension "
                    f"{existing_dim} does not match requested {vec_dim}."
                )
                raise ValueError(msg)
            return existing

        def _factory() -> FAISSManager:
            """Build and return a new CodeRank FAISS manager instance.

            Returns
            -------
            FAISSManager
                Newly constructed FAISS manager for CodeRank index.
            """
            return self._build_coderank_faiss_manager(vec_dim=vec_dim)

        manager = cell.get_or_initialize(_factory)
        if manager.vec_dim != vec_dim:  # pragma: no cover - defensive double-check
            existing_dim = manager.vec_dim
            msg = (
                "Existing CodeRank index dimension "
                f"{existing_dim} does not match requested {vec_dim}."
            )
            raise ValueError(msg)
        return manager

    def get_xtr_index(self) -> XTRIndex | None:
        """Return the lazily initialized XTR token index when enabled.

        Returns
        -------
        XTRIndex | None
            Ready XTR index instance or ``None`` when disabled/unavailable.

        Raises
        ------
        RuntimeUnavailableError
            If configuration enables XTR but artifacts or dependencies are missing.
        """
        if not self.app_config.xtr.enable:
            return None
        cell = self._runtime.xtr
        existing = cell.peek()
        if existing is not None:
            if existing.ready:
                return existing
            cell.close()

        def _factory() -> XTRIndex:
            """Build and return a new XTR index instance.

            Returns
            -------
            XTRIndex
                Newly constructed XTR token index.
            """
            return self._build_xtr_index()

        try:
            index = cell.get_or_initialize(_factory)
        except RuntimeUnavailableError as exc:
            cell.record_failure(exc, _RUNTIME_FAILURE_TTL_S)
            cell.close()
            raise
        except (OSError, RuntimeError, ValueError):
            cell.close()
            return None
        if index.ready:
            return index
        return None

    def _build_coderank_faiss_manager(self, *, vec_dim: int) -> FAISSManager:
        """Construct the CodeRank FAISS manager with dependency gates.

        Extended Summary
        ----------------
        Builds a FAISSManager instance for CodeRank vector search by
        validating the index path exists, ensuring FAISS is importable,
        and loading the pre-built index from disk. This method gates
        access to the CodeRank runtime, failing fast if dependencies
        or resources are missing. The manager is configured with
        application settings (nlist and runtime tuning) and loaded
        into CPU memory for immediate use.

        Parameters
        ----------
        vec_dim : int
            Vector dimensionality expected by the CodeRank index.
            Must match the dimension used when the index was built.
            Typically 768 or 1536 for transformer-based embeddings.

        Returns
        -------
        FAISSManager
            Ready-to-use FAISS manager configured for the CodeRank index.
            The index is loaded into CPU memory and ready for search queries.

        Notes
        -----
        Time O(1) for validation; index loading time depends on index size.
        The manager loads the index synchronously; no lazy loading. This method
        is called during ApplicationContext initialization, not per-request.

        May propagate `RuntimeUnavailableError` from `_ensure_path_exists()`
        if the index path does not exist, or from `_require_dependency()`
        if the FAISS library cannot be imported.

        Raises
        ------
        ConfigurationError
            Raised when index configuration is invalid (e.g., ``nlist`` is None).
            The exception includes context about the missing configuration value.

        See Also
        --------
        ApplicationContext._build_xtr_index : Similar pattern for XTR index
        codeintel_rev.io.faiss_manager.FAISSManager : Manager implementation
        """
        runtime = "coderank-faiss"
        index_path = self.paths.coderank_faiss_index
        _ensure_path_exists(index_path, runtime=runtime, description="CodeRank FAISS index")
        _require_dependency("faiss", runtime=runtime, purpose="CodeRank FAISS manager")
        manager_cls = _import_faiss_manager_cls()
        index_cfg = self.app_config.index
        runtime_opts = _faiss_runtime_options_from_index(index_cfg)
        nlist_value = index_cfg.nlist
        if nlist_value is None:
            msg = "IndexSettings.nlist cannot be None when building CodeRank FAISS manager"
            raise ConfigurationError(msg)
        nlist = nlist_value
        manager = manager_cls(
            index_path=index_path,
            vec_dim=vec_dim,
            nlist=nlist,
            runtime=runtime_opts,
        )
        manager.load_cpu_index()
        return manager

    def _build_xtr_index(self) -> XTRIndex:
        """Construct the XTR index runtime with artifact and dependency gates.

        Returns
        -------
        XTRIndex
            Ready XTR index instance.

        Raises
        ------
        RuntimeUnavailableError
            If configuration disables XTR or required artifacts/dependencies are missing.
        """
        runtime = "xtr"
        if not self.app_config.xtr.enable:
            message = "XTR runtime disabled in configuration"
            raise RuntimeUnavailableError(
                message,
                runtime=runtime,
                detail="app_config.xtr.enable is False",
            )
        root = self.paths.xtr_dir
        _ensure_path_exists(root, runtime=runtime, description="XTR artifact directory")
        _require_dependency("torch", runtime=runtime, purpose="XTR encoder runtime")
        index_cls = _import_xtr_index_cls()
        index = index_cls(root=root, config=self.app_config.xtr)
        index.open()
        if not index.ready:
            message = "XTR artifacts incomplete"
            raise RuntimeUnavailableError(
                message,
                runtime=runtime,
                detail=str(root),
            )
        return index

    def _build_hybrid_engine(self) -> HybridSearchEngine:
        """Construct the hybrid search engine using narrow BM25/SPLADE engines.

        Returns
        -------
        HybridSearchEngine
            Configured hybrid search engine instance.
        """
        factories = self._runtime_factories
        if factories and factories.hybrid_engine_factory is not None:
            return factories.hybrid_engine_factory()
        engine_cls = _import_hybrid_engine_cls()
        bm25_engine = self._build_bm25_engine()
        splade_engine = self._build_splade_engine()
        return engine_cls(bm25=bm25_engine, splade=splade_engine)

    def _build_bm25_engine(self) -> BM25Engine:
        """Return configured BM25 engine or a disabled stub.

        Returns
        -------
        BM25Engine
            Configured BM25 engine instance or disabled stub.
        """
        bm25_cfg = self.app_config.bm25
        index_cfg = self.app_config.index
        if not (bm25_cfg.enabled and index_cfg.enable_bm25_channel):
            return BM25Engine(_DisabledBM25Backend())
        rm3_params = RM3Params(
            fb_docs=bm25_cfg.rm3_fb_docs,
            fb_terms=bm25_cfg.rm3_fb_terms,
            orig_weight=bm25_cfg.rm3_original_query_weight,
        )
        heuristics: RM3Heuristics | None = None
        prf_cfg = index_cfg.prf
        if prf_cfg.enable_auto:
            heuristics = RM3Heuristics(
                short_query_max_terms=prf_cfg.short_query_max_terms,
                symbol_like_regex=prf_cfg.symbol_like_regex,
                head_terms=_parse_head_terms(prf_cfg.head_terms_csv),
                default_params=rm3_params,
            )
        rm3_cfg = BM25Rm3Config(
            params=rm3_params,
            heuristics=heuristics,
            enable_rm3=bm25_cfg.rm3_enabled,
            auto_rm3=prf_cfg.enable_auto,
        )
        index_dir = self._resolve_repo_path(bm25_cfg.index_dir)
        try:
            backend = PyseriniBM25Backend(
                index_dir=index_dir,
                k1=bm25_cfg.k1,
                b=bm25_cfg.b,
                rm3=rm3_cfg,
            )
        except FileNotFoundError:
            warnings.warn(
                f"BM25 index not found at {index_dir}, falling back to disabled backend.",
                stacklevel=2,
            )
            return BM25Engine(_DisabledBM25Backend())
        return BM25Engine(backend=backend)

    def _build_splade_engine(self) -> SPLADEEngine:
        """Return configured SPLADE engine or a disabled stub.

        Returns
        -------
        SPLADEEngine
            Configured SPLADE engine instance or disabled stub.
        """
        splade_cfg = self.app_config.splade
        index_cfg = self.app_config.index
        if not (splade_cfg.enabled and index_cfg.enable_splade_channel):
            return SPLADEEngine(_DisabledSpladeBackend())
        backend_config = SpladeImpactBackendConfig(
            model_dir=self._resolve_repo_path(splade_cfg.model_dir),
            onnx_dir=self._resolve_repo_path(splade_cfg.onnx_dir),
            onnx_file=splade_cfg.onnx_file,
            provider=splade_cfg.provider,
            index_dir=self._resolve_repo_path(splade_cfg.index_dir),
            quantization=splade_cfg.quantization,
            max_terms=splade_cfg.max_terms,
            max_query_terms=splade_cfg.max_query_terms,
            prune_below=splade_cfg.prune_below,
            static_prune_pct=splade_cfg.static_prune_pct,
        )
        onnx_encoder = self._build_splade_query_encoder(splade_cfg)
        try:
            backend = SpladeImpactBackend(backend_config, onnx_encoder=onnx_encoder)
        except FileNotFoundError:
            warnings.warn(
                f"SPLADE impact index not found at {backend_config.index_dir},"
                " falling back to disabled backend.",
                stacklevel=2,
            )
            return SPLADEEngine(_DisabledSpladeBackend())
        return SPLADEEngine(backend=backend)

    def _build_splade_query_encoder(self, splade_cfg: SpladeSettings) -> object | None:
        """Build a SPLADE ONNX query encoder from configuration.

        Parameters
        ----------
        splade_cfg : SpladeSettings
            SPLADE configuration containing ONNX model paths and encoder settings.

        Returns
        -------
        object | None
            An OnnxSpladeQueryEncoder instance if ONNX query encoding is enabled
            and dependencies are available, None otherwise. Returns None if
            the encoder is disabled, dependencies are missing, or the model
            file does not exist.

        Notes
        -----
        This method performs lazy loading of the ONNX encoder. If optional
        dependencies (onnxruntime, transformers) are missing, a warning is
        emitted and None is returned. The model path is resolved relative
        to the repository root if not absolute.
        """
        cfg = splade_cfg.onnx_query
        if cfg is None or not cfg.enabled:
            return None
        if OnnxSpladeConfig is None or OnnxSpladeQueryEncoder is None:
            warnings.warn(
                "SPLADE ONNX encoder unavailable; missing optional dependency",
                stacklevel=2,
            )
            return None
        model_dir = self._resolve_repo_path(splade_cfg.onnx_dir)
        model_path = cfg.model_path or Path(splade_cfg.onnx_file)
        if not model_path.is_absolute():
            model_path = model_dir / model_path
        model_path = model_path.expanduser().resolve()
        if not model_path.exists():
            warnings.warn(
                f"SPLADE ONNX model not found: {model_path}",
                stacklevel=2,
            )
            return None
        tokenizer_name = cfg.tokenizer_name or splade_cfg.model_id
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
        except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover - defensive
            warnings.warn(
                f"SPLADE ONNX encoder initialization failed: {exc}",
                stacklevel=2,
            )
            return None

    def _resolve_repo_path(self, value: str | Path) -> Path:
        """Resolve a path relative to the repository root.

        Parameters
        ----------
        value : str | Path
            Path to resolve. If absolute, returned as-is. If relative, resolved
            relative to the repository root from context paths.

        Returns
        -------
        Path
            Absolute resolved path. If the input was absolute, returns it
            expanded and resolved. If relative, returns it resolved relative
            to the repository root.
        """
        base = Path(self.paths.repo_root).expanduser()
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            return candidate
        return (base / candidate).resolve()

    def ensure_faiss_ready(self) -> tuple[bool, list[str], str | None]:
        """Load FAISS index (once) in a thread-safe manner.

        This method is thread-safe and idempotent. On first call, it loads the
        CPU index from disk. On subsequent calls, it returns cached state.

        The method is typically called from semantic search adapter on first
        search request (lazy loading) or optionally during application startup
        (eager loading controlled by FAISS_PRELOAD environment variable).

        Returns
        -------
        tuple[bool, list[str], str | None]
            Three-element tuple:
            - ready (bool): True if FAISS index is available for searching
            - limits (list[str]): Warning messages about degraded mode (e.g.,
              "Index not found"). Empty list if fully ready.
            - error (str | None): Error message if index loading failed, None
              if successful or already loaded.

        Examples
        --------
        >>> context = ApplicationContext.create()
        >>> ready, limits, error = context.ensure_faiss_ready()
        >>> if ready:
        ...     # Proceed with search
        ...     results = context.faiss_manager.search(query_vector, k=20)
        ... else:
        ...     # Handle error (return error response to client)
        ...     print(f"FAISS unavailable: {error}")

        Notes
        -----
        The method uses a threading.Lock to ensure only one thread loads the
        index even under concurrent requests. Subsequent calls skip loading
        and immediately return the cached state.
        """
        limits: list[str] = []
        runtime = self._runtime

        if not self.paths.faiss_index.exists():
            return False, limits, f"FAISS index not found at {self.paths.faiss_index}"

        faiss_state = runtime.faiss

        with faiss_state.lock:
            if not faiss_state.loaded:
                try:
                    self.faiss_manager.load_cpu_index(
                        export_idmap=self.paths.faiss_idmap_path,
                        profile_path=self.faiss_manager.autotune_profile_path,
                    )
                except (FileNotFoundError, RuntimeError) as exc:
                    return False, limits, f"FAISS index load failed: {exc}"
                faiss_state.loaded = True

        limits = list(dict.fromkeys(limits))
        self._autotune_if_requested()
        return True, limits, None

    @contextmanager
    def open_catalog(self) -> Iterator[DuckDBCatalog]:
        """Yield a DuckDB catalog context manager.

        Opens a connection to the DuckDB catalog containing chunk metadata,
        yields the catalog instance for querying, and ensures the connection
        is closed even if an exception occurs.

        The catalog provides SQL access to chunk metadata (URIs, line numbers,
        preview text) stored in Parquet files. It's used to hydrate FAISS
        search results with full chunk information.

        Yields
        ------
        DuckDBCatalog
            Catalog instance with active database connection. Supports querying
            by chunk IDs, URIs, and other metadata fields.

        Examples
        --------
        >>> with context.open_catalog() as catalog:
        ...     chunks = catalog.query_by_ids([1, 2, 3])
        ...     for chunk in chunks:
        ...         print(chunk["uri"], chunk["preview"])

        Notes
        -----
        The catalog connection is automatically closed when the context manager
        exits, even if an exception is raised. This ensures no connection leaks.

        See Also
        --------
        codeintel_rev.io.duckdb_catalog.DuckDBCatalog : Catalog implementation
        """
        catalog = self.duckdb_catalog_factory(self.paths, self.settings, self.duckdb_manager)
        try:
            catalog.open()
            yield catalog
        finally:
            catalog.close()

    def with_overrides(
        self,
        *,
        settings: Settings | None = None,
        paths: ResolvedPaths | None = None,
        app_config: AppConfig | None = None,
        **components: object,
    ) -> ApplicationContext:
        """Return a new context with the provided overrides.

        Extended Summary
        ----------------
        This method creates a new ApplicationContext instance with selective overrides
        to the current context's dependencies. It is used for testing, dependency injection,
        and creating specialized contexts (e.g., with mocked components or different
        configuration). The method preserves all non-overridden dependencies from the
        current context, allowing incremental customization without full reinitialization.
        This is particularly useful in test fixtures where specific components need to
        be replaced while keeping the rest of the context intact.

        Parameters
        ----------
        settings : Settings | None, optional
            Application settings to override. If None, uses the current context's
            settings. Defaults to None.
        paths : ResolvedPaths | None, optional
            Resolved file system paths to override. If None, uses the current context's
            paths. Defaults to None.
        app_config : AppConfig | None, optional
            Immutable application configuration override. When None, reuses the
            active :class:`AppConfig`.
        **components : object
            Keyword arguments for component overrides. Accepted keys are:
            ``vllm_client``, ``faiss_manager``, ``scope_store``, ``duckdb_manager``,
            ``git_client``, ``async_git_client``, ``factory_adjuster``. Each override replaces the corresponding
            component in the new context. Unsupported keys raise ValueError.

        Returns
        -------
        ApplicationContext
            Fresh context instance sharing the existing dependencies unless
            overridden via keyword arguments. The new context is independent of the
            original and can be modified without affecting it.

        Raises
        ------
        ValueError
            If unsupported override keys are supplied in **components. Only the
            accepted component names listed in Parameters are allowed.

        Notes
        -----
        Time complexity O(1) for context creation. Space complexity O(1) aside from
        the new context object and any overridden components. The method performs no
        I/O and has no side effects. Thread-safe if all components are thread-safe.
        Overrides are shallow; nested component dependencies are not automatically
        updated to match overridden components.
        """
        allowed = {
            "vllm_client",
            "faiss_manager",
            "scope_store",
            "duckdb_manager",
            "git_client",
            "async_git_client",
            "factory_adjuster",
            "duckdb_catalog_factory",
        }
        unknown = set(components) - allowed
        if unknown:
            message = f"Unsupported context override(s): {sorted(unknown)}"
            raise ValueError(message)

        def _component_value[TOverride](name: str, default: TOverride) -> TOverride:
            """Get component value from override dict or return default.

            Parameters
            ----------
            name : str
                Component name to look up in override dictionary.
            default : TOverride
                Default value to return if component not in override dict.

            Returns
            -------
            TOverride
                Override value if present, otherwise default value.
            """
            return cast("TOverride", components.get(name, default))

        return ApplicationContext(
            app_config=app_config or self.app_config,
            settings=settings or self.settings,
            paths=paths or self.paths,
            vllm_client=_component_value("vllm_client", self.vllm_client),
            faiss_manager=_component_value("faiss_manager", self.faiss_manager),
            scope_store=_component_value("scope_store", self.scope_store),
            duckdb_manager=_component_value("duckdb_manager", self.duckdb_manager),
            duckdb_catalog_factory=_component_value(
                "duckdb_catalog_factory", self.duckdb_catalog_factory
            ),
            git_client=_component_value("git_client", self.git_client),
            async_git_client=_component_value("async_git_client", self.async_git_client),
            runtime_observer=self.runtime_observer,
            factory_adjuster=_component_value("factory_adjuster", self.factory_adjuster),
        )

    def close_all_runtimes(self) -> None:
        """Best-effort shutdown for mutable runtimes."""
        runtime = self._runtime
        for _, cell in self._iter_runtime_cells():
            with suppress(Exception):
                cell.close()
        with suppress(Exception):
            self.vllm_client.close()
        with suppress(Exception):
            self.duckdb_manager.close()
        with suppress(Exception):
            self.faiss_manager.cpu_index = None
            runtime.faiss.loaded = False

    def set_runtime_factories_for_tests(
        self,
        *,
        hybrid_engine_factory: Callable[[], HybridSearchEngine] | None = None,
    ) -> None:
        """Install factory overrides for runtime components during tests."""
        factories = self._runtime_factories
        if factories is None:
            factories = RuntimeFactoryOverrides()
            _assign_frozen(self, "_runtime_factories", factories)
        if hybrid_engine_factory is not None:
            factories.hybrid_engine_factory = hybrid_engine_factory

    def seed_runtime_cells_for_tests(
        self,
        *,
        coderank_faiss: FAISSManager | None = None,
        hybrid_engine: HybridSearchEngine | None = None,
        xtr_index: XTRIndex | None = None,
        hybrid_engine_factory: Callable[[], HybridSearchEngine] | None = None,
    ) -> None:
        """Seed runtime cells with test doubles.

        Parameters
        ----------
        coderank_faiss : FAISSManager | None, optional
            Stub FAISS manager to cache for ``get_coderank_faiss_manager`` calls.
        hybrid_engine : HybridSearchEngine | None, optional
            Stub hybrid search engine injected into the hybrid runtime cell.
        xtr_index : XTRIndex | None, optional
            Stub XTR index injected into the XTR runtime cell.
        hybrid_engine_factory : Callable[[], HybridSearchEngine] | None, optional
            Override factory used when lazily constructing hybrid engines.
        """
        with allow_runtime_cell_seeding():
            if coderank_faiss is not None:
                self._runtime.coderank_faiss.seed(coderank_faiss)
            if hybrid_engine is not None:
                self._runtime.hybrid.seed(hybrid_engine)
            if xtr_index is not None:
                self._runtime.xtr.seed(xtr_index)
        if hybrid_engine_factory is not None:
            self.set_runtime_factories_for_tests(hybrid_engine_factory=hybrid_engine_factory)


def merge_paths_with_app_config(paths: ResolvedPaths, app_config: AppConfig) -> ResolvedPaths:
    """Return paths updated with AppConfig overrides for storage locations.

    Parameters
    ----------
    paths : ResolvedPaths
        Canonical filesystem paths derived from :func:`resolve_application_paths`.
    app_config : AppConfig
        Immutable configuration containing DuckDB and FAISS paths.

    Returns
    -------
    ResolvedPaths
        Resolved paths with DuckDB and FAISS entries overridden by AppConfig.
    """
    return replace(
        paths,
        duckdb_path=app_config.duckdb.database,
        faiss_index=app_config.faiss.index_path,
    )
