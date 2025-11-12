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
codeintel_rev.app.readiness : Readiness probe system for health checks
codeintel_rev.config.settings : Settings dataclasses and environment loading
"""

from __future__ import annotations

import importlib
import os
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from types import ModuleType
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, cast

from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.scope_store import ScopeStore
from codeintel_rev.config.settings import IndexConfig, Settings, load_settings
from codeintel_rev.errors import RuntimeLifecycleError, RuntimeUnavailableError
from codeintel_rev.evaluation.offline_recall import OfflineRecallEvaluator
from codeintel_rev.indexing.index_lifecycle import IndexLifecycleManager
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.faiss_manager import FAISSManager, FAISSRuntimeOptions
from codeintel_rev.io.git_client import AsyncGitClient, GitClient
from codeintel_rev.io.vllm_client import VLLMClient
import codeintel_rev.observability.metrics as _retrieval_metrics
from codeintel_rev.runtime import (
    NullRuntimeCellObserver,
    RuntimeCell,
    RuntimeCellObserver,
)
from codeintel_rev.runtime.factory_adjustment import (
    DefaultFactoryAdjuster,
    FactoryAdjuster,
    NoopFactoryAdjuster,
)
from codeintel_rev.typing import gate_import
from kgfoundry_common.errors import ConfigurationError
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from codeintel_rev.app.scope_store import SupportsAsyncRedis
    from codeintel_rev.io.hybrid_search import HybridSearchEngine
    from codeintel_rev.io.xtr_manager import XTRIndex
else:  # pragma: no cover - runtime only; annotations are postponed
    HybridSearchEngine = Any
    XTRIndex = Any

LOGGER = get_logger(__name__)
_RUNTIME_FAILURE_TTL_S = 15.0


class _RetrievalMetrics(Protocol):
    def set_index_version(self, name: str, version: str | None) -> None: ...


retrieval_metrics = cast("_RetrievalMetrics", _retrieval_metrics)

__all__ = ["ApplicationContext", "ResolvedPaths", "resolve_application_paths"]


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


def _build_factory_adjuster(settings: Settings) -> FactoryAdjuster:
    """Return a DefaultFactoryAdjuster derived from settings.

    Parameters
    ----------
    settings : Settings
        Application settings containing index configuration defaults.

    Returns
    -------
    FactoryAdjuster
        Adjuster informed by ``settings.index`` defaults. If settings are invalid
        or missing required attributes, returns `NoopFactoryAdjuster()` as fallback.

    Notes
    -----
    This helper extracts FAISS and hybrid search tuning parameters from settings
    and constructs a factory adjuster that applies these defaults when creating
    runtime cells. Defensively handles missing or malformed settings by falling
    back to a no-op adjuster.
    """
    try:
        rrf_weights = getattr(settings.index, "rrf_weights", {})
        return DefaultFactoryAdjuster(
            faiss_nprobe=getattr(settings.index, "faiss_nprobe", None),
            hybrid_rrf_k=getattr(settings.index, "rrf_k", None),
            hybrid_bm25_weight=rrf_weights.get("bm25"),
            hybrid_splade_weight=rrf_weights.get("splade"),
        )
    except (AttributeError, TypeError, ValueError):  # pragma: no cover - defensive
        return NoopFactoryAdjuster()


def _build_faiss_manager(settings: Settings, paths: ResolvedPaths) -> FAISSManager:
    """Construct and log the FAISS manager for the main index.

    Parameters
    ----------
    settings : Settings
        Application settings containing index configuration.
    paths : ResolvedPaths
        Resolved filesystem paths including FAISS index path.

    Returns
    -------
    manager : FAISSManager
        Configured FAISS manager instance.

    Raises
    ------
    ConfigurationError
        If IndexConfig.nlist is None during context creation.
    """
    faiss_manager_cls = _import_faiss_manager_cls()
    runtime_opts = _faiss_runtime_options_from_index(settings.index)
    nlist_value = settings.index.nlist
    if nlist_value is None:
        msg = "IndexConfig.nlist cannot be None during context creation"
        raise ConfigurationError(msg)
    manager = faiss_manager_cls(
        index_path=paths.faiss_index,
        vec_dim=settings.index.vec_dim,
        nlist=nlist_value,
        use_cuvs=settings.index.use_cuvs,
        runtime=runtime_opts,
    )
    try:
        LOGGER.info(
            "faiss.compile",
            extra={"opts": manager.get_compile_options(), "component": "app_start"},
        )
    except (RuntimeError, OSError, ValueError):
        LOGGER.debug("Unable to fetch FAISS compile options at startup", exc_info=True)
    return manager


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
        gate_import("redis.asyncio", "Session scope store requires redis extra"),
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
    LOGGER.debug(
        "Initialized Git clients",
        extra={"repo_path": str(paths.repo_root)},
    )
    return git_client, async_git_client


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


def _faiss_runtime_options_from_index(index_cfg: IndexConfig) -> FAISSRuntimeOptions:
    """Materialize FAISS runtime options from the structured index config.

    Parameters
    ----------
    index_cfg : IndexConfig
        Structured index configuration containing FAISS parameters (family, PQ
        settings, HNSW parameters, GPU options, etc.).

    Returns
    -------
    FAISSRuntimeOptions
        Instance of ``FAISSRuntimeOptions`` matching ``index_cfg`` parameters.
        The returned object is used to configure FAISS manager runtime behavior.

    Notes
    -----
    This helper converts structured `IndexConfig` (from settings or index manifest)
    into FAISS-specific runtime options. It dynamically imports the FAISS runtime
    options class and instantiates it with values from the config.
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
        use_gpu=index_cfg.use_gpu,
        gpu_clone_mode=index_cfg.gpu_clone_mode,
        autotune_on_start=index_cfg.autotune_on_start,
        enable_range_search=index_cfg.enable_range_search,
        semantic_min_score=index_cfg.semantic_min_score,
    )


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
    Uses `gate_import()` from `kgfoundry_common.typing` to safely
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
        gate_import(module, purpose)
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


@dataclass(slots=True, frozen=True)
class ResolvedPaths:
    """Canonicalized filesystem paths for runtime operations.

    All paths are absolute and resolved relative to repo_root. This eliminates
    ambiguity and ensures consistent path handling throughout the application.
    Path resolution is performed once at application startup rather than on
    each request.

    Attributes
    ----------
    repo_root : Path
        Absolute path to repository root directory. This is the base directory
        for all source code and must exist before application startup.
    data_dir : Path
        Absolute path to base data directory containing indexes and databases.
    vectors_dir : Path
        Absolute path to directory containing Parquet files with vector embeddings.
    faiss_index : Path
        Absolute path to FAISS IVF-PQ index file (CPU version).
    duckdb_path : Path
        Absolute path to DuckDB catalog database file.
    scip_index : Path
        Absolute path to SCIP index file (JSON or protobuf format).
    coderank_vectors_dir : Path
        Directory storing CodeRank chunk embeddings or shards.
    coderank_faiss_index : Path
        Path to the CodeRank FAISS index used for Stage-A retrieval.
    warp_index_dir : Path
        Directory containing WARP/XTR index artifacts.
    xtr_dir : Path
        Directory containing XTR token-level artifacts (memmaps + metadata).

    Examples
    --------
    Paths are created during application startup:

    >>> settings = load_settings()
    >>> paths = resolve_application_paths(settings)
    >>> paths.repo_root
    PosixPath('/home/user/kgfoundry')
    >>> paths.faiss_index
    PosixPath('/home/user/kgfoundry/data/faiss/code.ivfpq.faiss')
    """

    repo_root: Path
    data_dir: Path
    vectors_dir: Path
    faiss_index: Path
    duckdb_path: Path
    scip_index: Path
    coderank_vectors_dir: Path
    coderank_faiss_index: Path
    warp_index_dir: Path
    xtr_dir: Path


def resolve_application_paths(settings: Settings) -> ResolvedPaths:
    """Resolve all configured paths to absolute paths.

    Converts relative paths to absolute paths relative to repo_root, validates
    that repo_root exists and is a directory, and returns a frozen dataclass
    containing all resolved paths.

    This function is called once during application startup. Path resolution
    failures cause ConfigurationError to be raised, which prevents the
    application from starting.

    Parameters
    ----------
    settings : Settings
        Application settings containing path configuration loaded from
        environment variables.

    Returns
    -------
    ResolvedPaths
        Fully resolved absolute paths for all application resources.

    Raises
    ------
    ConfigurationError
        If repo_root does not exist, is not a directory, or cannot be accessed.
        Error includes RFC 9457 Problem Details with context fields for
        debugging (repo_root value, source environment variable).

    Examples
    --------
    >>> settings = Settings(
    ...     paths=PathsConfig(
    ...         repo_root="/home/user/kgfoundry",
    ...         data_dir="data",
    ...         faiss_index="data/faiss/code.ivfpq.faiss",
    ...     ),
    ...     # ... other settings
    ... )
    >>> paths = resolve_application_paths(settings)
    >>> paths.data_dir.is_absolute()
    True
    >>> paths.data_dir.parent == paths.repo_root
    True
    """
    repo_root = Path(settings.paths.repo_root).expanduser().resolve()

    if not repo_root.exists():
        msg = f"Repository root does not exist: {repo_root}"
        raise ConfigurationError(
            msg,
            context={"repo_root": str(repo_root), "source": "REPO_ROOT env var"},
        )

    if not repo_root.is_dir():
        msg = f"Repository root is not a directory: {repo_root}"
        raise ConfigurationError(
            msg,
            context={"repo_root": str(repo_root)},
        )

    def _resolve(path_str: str) -> Path:
        """Resolve a path string relative to repo_root.

        Parameters
        ----------
        path_str : str
            Path string that may be relative or absolute.

        Returns
        -------
        Path
            Absolute resolved path.
        """
        path = Path(path_str)
        if path.is_absolute():
            return path.expanduser().resolve()
        return (repo_root / path).resolve()

    paths = ResolvedPaths(
        repo_root=repo_root,
        data_dir=_resolve(settings.paths.data_dir),
        vectors_dir=_resolve(settings.paths.vectors_dir),
        faiss_index=_resolve(settings.paths.faiss_index),
        duckdb_path=_resolve(settings.paths.duckdb_path),
        scip_index=_resolve(settings.paths.scip_index),
        coderank_vectors_dir=_resolve(settings.paths.coderank_vectors_dir),
        coderank_faiss_index=_resolve(settings.paths.coderank_faiss_index),
        warp_index_dir=_resolve(settings.paths.warp_index_dir),
        xtr_dir=_resolve(settings.paths.xtr_dir),
    )

    for directory in (
        paths.data_dir,
        paths.vectors_dir,
        paths.coderank_vectors_dir,
        paths.warp_index_dir,
        paths.xtr_dir,
    ):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            msg = f"Failed to ensure required directory exists: {directory}"
            raise ConfigurationError(
                msg,
                context={"path": str(directory), "source": "resolve_application_paths"},
            ) from exc
        else:
            LOGGER.debug("Ensured directory exists", extra={"path": str(directory)})

    return paths


T = TypeVar("T")


class _FaissRuntimeState:
    """Runtime bookkeeping for FAISS initialization."""

    __slots__ = ("gpu_attempted", "loaded", "lock")

    def __init__(self) -> None:
        self.lock = Lock()
        self.loaded = False
        self.gpu_attempted = False


@dataclass(slots=True, frozen=True)
class _ContextRuntimeState:
    """Mutable runtime state backing the frozen ApplicationContext."""

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
        FAISS index manager that handles CPU and GPU indexes. GPU resources are
        lazily initialized on first search or optionally pre-loaded at startup.
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

    settings: Settings
    paths: ResolvedPaths
    vllm_client: VLLMClient
    faiss_manager: FAISSManager
    scope_store: ScopeStore
    duckdb_manager: DuckDBManager
    git_client: GitClient
    async_git_client: AsyncGitClient
    runtime_observer: RuntimeCellObserver = field(
        default_factory=NullRuntimeCellObserver, repr=False
    )
    factory_adjuster: FactoryAdjuster = field(default_factory=NoopFactoryAdjuster, repr=False)
    _runtime: _ContextRuntimeState = field(
        default_factory=_ContextRuntimeState, init=False, repr=False
    )
    index_manager: IndexLifecycleManager = field(init=False, repr=False)
    _offline_evaluator: OfflineRecallEvaluator | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Attach the configured observer to all runtime cells."""
        self._runtime.attach_observer(self.runtime_observer)
        self._runtime.attach_adjuster(self.factory_adjuster)
        index_root = _infer_index_root(self.paths)
        _assign_frozen(self, "index_manager", IndexLifecycleManager(index_root))
        LOGGER.debug(
            "Initialized index lifecycle manager",
            extra={"index_root": str(index_root)},
        )
        self._update_index_version_metrics()

    @classmethod
    def create(
        cls,
        *,
        runtime_observer: RuntimeCellObserver | None = None,
        factory_adjuster: FactoryAdjuster | None = None,
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
        runtime_observer : RuntimeCellObserver | None, optional
            Observer instance that receives lifecycle callbacks from runtime cells
            (hybrid engine, FAISS manager, XTR index). Used for instrumentation,
            monitoring, and diagnostics. If None (default), uses NullRuntimeCellObserver
            which suppresses all callbacks. Defaults to None.
        factory_adjuster : FactoryAdjuster | None, optional
            Optional adjuster applied to runtime factories. When ``None``, a default
            adjuster derived from ``settings.index`` is used.

        Returns
        -------
        ApplicationContext
            Initialized context with all clients and configuration ready. The context
            is frozen after creation and thread-safe for concurrent access.

        Examples
        --------
        >>> # In FastAPI lifespan() function
        >>> @asynccontextmanager
        >>> async def lifespan(app: FastAPI):
        ...     context = ApplicationContext.create()
        ...     app.state.context = context
        ...     yield

        >>> # With custom observer for instrumentation
        >>> observer = MyCustomObserver()
        >>> context = ApplicationContext.create(runtime_observer=observer)

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

        Raises
        ------
        ConfigurationError
            Raised when index configuration is invalid (e.g., ``nlist`` is None) or
            when path resolution fails. The exception includes RFC 9457 Problem Details
            with context fields for debugging.

        See Also
        --------
        load_settings : Loads Settings from environment variables
        resolve_application_paths : Validates and resolves paths
        """
        LOGGER.info("Loading application configuration from environment")
        settings = load_settings()
        # resolve_application_paths() raises ConfigurationError if paths are invalid
        # This exception propagates to the caller, causing application startup to fail
        paths = resolve_application_paths(settings)

        vllm_client = VLLMClient(settings.vllm)
        faiss_manager = _build_faiss_manager(settings, paths)
        scope_store = _build_scope_store(settings)
        git_client, async_git_client = _build_git_clients(paths)
        duckdb_manager = DuckDBManager(paths.duckdb_path, settings.duckdb)

        LOGGER.info(
            "Application context created",
            extra={
                "repo_root": str(paths.repo_root),
                "faiss_index": str(paths.faiss_index),
                "vllm_url": settings.vllm.base_url,
            },
        )

        observer = runtime_observer or NullRuntimeCellObserver()

        adjuster = factory_adjuster or _build_factory_adjuster(settings)
        return cls(
            settings=settings,
            paths=paths,
            vllm_client=vllm_client,
            faiss_manager=faiss_manager,
            scope_store=scope_store,
            duckdb_manager=duckdb_manager,
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
        LOGGER.info("Reloading runtime cells after index lifecycle change")
        for name, cell in self._iter_runtime_cells():
            try:
                cell.close()
            except (RuntimeError, OSError, ValueError):  # pragma: no cover - defensive logging
                LOGGER.warning("runtime.reload_failed", extra={"cell": name}, exc_info=True)
        faiss_state = self._runtime.faiss
        with faiss_state.lock:
            faiss_state.loaded = False
            faiss_state.gpu_attempted = False
        self.faiss_manager.cpu_index = None
        self.faiss_manager.gpu_index = None
        self.faiss_manager.secondary_gpu_index = None
        self.faiss_manager.gpu_resources = None
        self._update_index_version_metrics()

    def _update_index_version_metrics(self) -> None:
        """Expose the active index version via Prometheus gauges."""
        version: str | None = None
        with suppress(RuntimeLifecycleError):
            version = self.index_manager.current_version()
        retrieval_metrics.set_index_version("faiss", version)
        retrieval_metrics.set_index_version("bm25", version)
        retrieval_metrics.set_index_version("splade", version)

    def apply_factory_adjuster(self, adjuster: FactoryAdjuster) -> None:
        """Update runtime tuning knobs and reset cells to pick up changes."""
        LOGGER.info("Applying runtime factory adjuster")
        _assign_frozen(self, "factory_adjuster", adjuster)
        self._runtime.attach_adjuster(adjuster)
        for name, cell in self._iter_runtime_cells():
            try:
                cell.close()
            except (RuntimeError, OSError, ValueError):  # pragma: no cover - defensive
                LOGGER.warning("runtime.adjuster.reset_failed", extra={"cell": name}, exc_info=True)

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
            return self._build_hybrid_engine()

        engine = self._runtime.hybrid.get_or_initialize(_factory)
        if engine is None:  # pragma: no cover - defensive
            msg = "HybridSearchEngine failed to initialize"
            raise RuntimeError(msg)
        return engine

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
        if not self.settings.eval.enabled:
            msg = "Offline evaluation is disabled in configuration"
            raise RuntimeError(msg)
        evaluator = self._offline_evaluator
        if evaluator is not None:
            return evaluator

        faiss_manager = self.get_coderank_faiss_manager(self.settings.index.vec_dim)
        evaluator = OfflineRecallEvaluator(
            settings=self.settings,
            paths=self.paths,
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
        if not self.settings.xtr.enable:
            return None
        cell = self._runtime.xtr
        existing = cell.peek()
        if existing is not None:
            if existing.ready:
                return existing
            cell.close()

        def _factory() -> XTRIndex:
            return self._build_xtr_index()

        try:
            index = cell.get_or_initialize(_factory)
        except RuntimeUnavailableError as exc:
            cell.record_failure(exc, _RUNTIME_FAILURE_TTL_S)
            cell.close()
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            LOGGER.warning(
                "Failed to initialize XTR index; continuing without late interaction",
                extra={"xtr_dir": str(self.paths.xtr_dir)},
                exc_info=exc,
            )
            cell.close()
            return None
        if index.ready:
            return index
        LOGGER.warning(
            "XTR index not ready after initialization attempt",
            extra={"xtr_dir": str(self.paths.xtr_dir)},
        )
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
        application settings (nlist, cuvs preference) and loaded
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
            GPU support is enabled if `use_cuvs` is True and CUDA is available.

        Notes
        -----
        Time O(1) for validation; index loading time depends on index size.
        The manager loads the index synchronously; no lazy loading.
        GPU support (cuvs) is determined by application settings and
        runtime availability. This method is called during ApplicationContext
        initialization, not per-request.

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
        runtime_opts = _faiss_runtime_options_from_index(self.settings.index)
        nlist_value = self.settings.index.nlist
        if nlist_value is None:
            msg = "IndexConfig.nlist cannot be None when building CodeRank FAISS manager"
            raise ConfigurationError(msg)
        nlist = nlist_value
        manager = manager_cls(
            index_path=index_path,
            vec_dim=vec_dim,
            nlist=nlist,
            use_cuvs=self.settings.index.use_cuvs,
            runtime=runtime_opts,
        )
        manager.load_cpu_index()
        try:
            LOGGER.info(
                "faiss.compile",
                extra={"opts": manager.get_compile_options(), "component": runtime},
            )
        except (RuntimeError, OSError, ValueError):
            LOGGER.debug("Unable to fetch FAISS compile options", exc_info=True)
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
        if not self.settings.xtr.enable:
            message = "XTR runtime disabled in configuration"
            raise RuntimeUnavailableError(
                message,
                runtime=runtime,
                detail="settings.xtr.enable is False",
            )
        root = self.paths.xtr_dir
        _ensure_path_exists(root, runtime=runtime, description="XTR artifact directory")
        _require_dependency("torch", runtime=runtime, purpose="XTR encoder runtime")
        index_cls = _import_xtr_index_cls()
        index = index_cls(root=root, config=self.settings.xtr)
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
        """Construct the hybrid search engine with dependency gates per channel.

        Returns
        -------
        HybridSearchEngine
            Configured hybrid search engine instance.
        """
        engine_cls = _import_hybrid_engine_cls()
        capabilities = None
        try:
            capabilities = Capabilities.from_context(self)
        except RuntimeLifecycleError:  # pragma: no cover - defensive logging
            LOGGER.warning("capabilities.detect_failed", exc_info=True)
        return engine_cls(
            self.settings,
            self.paths,
            capabilities=capabilities,
            duckdb_manager=self.duckdb_manager,
        )

    def ensure_faiss_ready(self) -> tuple[bool, list[str], str | None]:
        """Load FAISS index (once) and attempt GPU clone.

        This method is thread-safe and idempotent. On first call, it loads the
        CPU index from disk. On subsequent calls, it returns cached state.
        GPU cloning is attempted once (if not already done during pre-loading).

        The method is typically called from semantic search adapter on first
        search request (lazy loading) or optionally during application startup
        (eager loading controlled by FAISS_PRELOAD environment variable).

        Returns
        -------
        tuple[bool, list[str], str | None]
            Three-element tuple:
            - ready (bool): True if FAISS index is available for searching
            - limits (list[str]): Warning messages about degraded mode (e.g.,
              "GPU unavailable", "Index not found"). Empty list if fully ready.
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

        GPU initialization failures are non-fatal - the method returns ready=True
        with a warning in the limits list. Semantic search will fall back to
        CPU index automatically.
        """
        limits: list[str] = []
        runtime = self._runtime

        if not self.paths.faiss_index.exists():
            return False, limits, f"FAISS index not found at {self.paths.faiss_index}"

        faiss_state = runtime.faiss

        with faiss_state.lock:
            if not faiss_state.loaded:
                try:
                    self.faiss_manager.load_cpu_index()
                except (FileNotFoundError, RuntimeError) as exc:
                    return False, limits, f"FAISS index load failed: {exc}"
                faiss_state.loaded = True

            if self.faiss_manager.gpu_index is None and not faiss_state.gpu_attempted:
                faiss_state.gpu_attempted = True
                try:
                    gpu_enabled = self.faiss_manager.clone_to_gpu()
                except RuntimeError as exc:
                    limits.append(str(exc))
                    gpu_enabled = False
                if not gpu_enabled and self.faiss_manager.gpu_disabled_reason:
                    limits.append(self.faiss_manager.gpu_disabled_reason)
            elif self.faiss_manager.gpu_disabled_reason:
                limits.append(self.faiss_manager.gpu_disabled_reason)

        limits = list(dict.fromkeys(limits))
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
        catalog = DuckDBCatalog(
            self.paths.duckdb_path,
            self.paths.vectors_dir,
            materialize=self.settings.index.duckdb_materialize,
            manager=self.duckdb_manager,
            log_queries=self.settings.duckdb.log_queries,
        )
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
        **components : object
            Keyword arguments for component overrides. Accepted keys are:
            ``vllm_client``, ``faiss_manager``, ``scope_store``, ``duckdb_manager``,
            ``git_client``, ``async_git_client``. Each override replaces the corresponding
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
        }
        unknown = set(components) - allowed
        if unknown:
            message = f"Unsupported context override(s): {sorted(unknown)}"
            raise ValueError(message)

        def _component_value[TOverride](name: str, default: TOverride) -> TOverride:
            return cast("TOverride", components.get(name, default))

        return ApplicationContext(
            settings=settings or self.settings,
            paths=paths or self.paths,
            vllm_client=_component_value("vllm_client", self.vllm_client),
            faiss_manager=_component_value("faiss_manager", self.faiss_manager),
            scope_store=_component_value("scope_store", self.scope_store),
            duckdb_manager=_component_value("duckdb_manager", self.duckdb_manager),
            git_client=_component_value("git_client", self.git_client),
            async_git_client=_component_value("async_git_client", self.async_git_client),
            runtime_observer=self.runtime_observer,
        )

    def close_all_runtimes(self) -> None:
        """Best-effort shutdown for mutable runtimes."""
        LOGGER.info("Closing runtime resources")
        runtime = self._runtime
        for name, cell in self._iter_runtime_cells():
            with suppress(Exception):
                LOGGER.debug("closing_runtime_cell", extra={"cell": name})
                cell.close()
        with suppress(Exception):
            self.vllm_client.close()
        with suppress(Exception):
            self.duckdb_manager.close()
        with suppress(Exception):
            self.faiss_manager.cpu_index = None
            self.faiss_manager.gpu_index = None
            self.faiss_manager.secondary_gpu_index = None
            self.faiss_manager.gpu_resources = None
            runtime.faiss.loaded = False
            runtime.faiss.gpu_attempted = False
