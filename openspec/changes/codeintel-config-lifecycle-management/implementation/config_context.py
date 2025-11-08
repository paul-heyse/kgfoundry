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

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from codeintel_rev.config.settings import Settings, load_settings
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.vllm_client import VLLMClient

from kgfoundry_common.errors import ConfigurationError
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

LOGGER = get_logger(__name__)


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
            msg, context={"repo_root": str(repo_root), "source": "REPO_ROOT env var"}
        )

    if not repo_root.is_dir():
        msg = f"Repository root is not a directory: {repo_root}"
        raise ConfigurationError(msg, context={"repo_root": str(repo_root)})

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

    return ResolvedPaths(
        repo_root=repo_root,
        data_dir=_resolve(settings.paths.data_dir),
        vectors_dir=_resolve(settings.paths.vectors_dir),
        faiss_index=_resolve(settings.paths.faiss_index),
        duckdb_path=_resolve(settings.paths.duckdb_path),
        scip_index=_resolve(settings.paths.scip_index),
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
    _faiss_lock: Lock = field(default_factory=Lock, init=False)
    _faiss_loaded: bool = field(default=False, init=False)
    _faiss_gpu_attempted: bool = field(default=False, init=False)

    @classmethod
    def create(cls) -> ApplicationContext:
        """Create application context from environment variables.

        This is the primary way to create an ApplicationContext. It:
        1. Loads settings from environment variables (via load_settings())
        2. Resolves and validates all filesystem paths
        3. Creates long-lived HTTP and index manager clients
        4. Logs successful initialization with key configuration values

        This method should be called exactly once during application startup
        (typically in the FastAPI lifespan() function). Configuration errors
        cause ConfigurationError to be raised, preventing application startup.

        Returns
        -------
        ApplicationContext
            Initialized context with all clients and configuration ready.

        Raises
        ------
        ConfigurationError
            If configuration is invalid (missing repo root, invalid paths, etc.).
            This exception is raised by `resolve_application_paths()` when paths
            cannot be resolved or validated, and propagates through this method.
            Error includes RFC 9457 Problem Details with context for debugging.

        Notes
        -----
        The `ConfigurationError` is raised by `resolve_application_paths()` when
        path validation fails and propagates through this method. This ensures
        fail-fast behavior during application startup.

        Examples
        --------
        >>> # In FastAPI lifespan() function
        >>> @asynccontextmanager
        >>> async def lifespan(app: FastAPI):
        ...     context = ApplicationContext.create()
        ...     app.state.context = context
        ...     yield

        See Also
        --------
        load_settings : Loads Settings from environment variables
        resolve_application_paths : Validates and resolves paths
        """
        LOGGER.info("Loading application configuration from environment")
        settings = load_settings()
        try:
            paths = resolve_application_paths(settings)
        except ConfigurationError as exc:
            raise exc  # noqa: TRY201

        vllm_client = VLLMClient(settings.vllm)
        faiss_manager = FAISSManager(
            index_path=paths.faiss_index,
            vec_dim=settings.index.vec_dim,
            nlist=settings.index.faiss_nlist,
            use_cuvs=settings.index.use_cuvs,
        )

        LOGGER.info(
            "Application context created",
            extra={
                "repo_root": str(paths.repo_root),
                "faiss_index": str(paths.faiss_index),
                "vllm_url": settings.vllm.base_url,
            },
        )

        return cls(
            settings=settings,
            paths=paths,
            vllm_client=vllm_client,
            faiss_manager=faiss_manager,
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

        if not self.paths.faiss_index.exists():
            return False, limits, f"FAISS index not found at {self.paths.faiss_index}"

        with self._faiss_lock:
            if not self._faiss_loaded:
                try:
                    self.faiss_manager.load_cpu_index()
                except (FileNotFoundError, RuntimeError) as exc:
                    return False, limits, f"FAISS index load failed: {exc}"
                self._faiss_loaded = True

            if self.faiss_manager.gpu_index is None and not self._faiss_gpu_attempted:
                self._faiss_gpu_attempted = True
                try:
                    gpu_enabled = self.faiss_manager.clone_to_gpu()
                except RuntimeError as exc:
                    limits.append(str(exc))
                    gpu_enabled = False
                if not gpu_enabled and self.faiss_manager.gpu_disabled_reason:
                    limits.append(self.faiss_manager.gpu_disabled_reason)
            elif (
                self.faiss_manager.gpu_disabled_reason
                and limits.count(self.faiss_manager.gpu_disabled_reason) == 0
            ):
                limits.append(self.faiss_manager.gpu_disabled_reason)

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
        catalog = DuckDBCatalog(self.paths.duckdb_path, self.paths.vectors_dir)
        try:
            catalog.open()
            yield catalog
        finally:
            catalog.close()
