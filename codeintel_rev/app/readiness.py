"""Application readiness checks for Kubernetes health probes.

This module provides comprehensive readiness checks for all critical application
resources including filesystem paths, FAISS indexes, DuckDB catalogs, and
external services (vLLM). The ReadinessProbe class manages these checks and
exposes results via the /readyz endpoint for Kubernetes integration.

Key Components
--------------
CheckResult : dataclass
    Immutable result of a single readiness check with healthy status and detail.
ReadinessProbe : class
    Manages readiness checks across all dependencies with async refresh.

Design Principles
-----------------
- **Comprehensive**: Checks all critical resources (files, directories, services)
- **Non-blocking**: HTTP checks use short timeouts to prevent blocking
- **Graceful Degradation**: Optional resources (SCIP index) don't fail readiness
- **Structured Results**: CheckResult provides JSON-serializable payloads

Example Usage
-------------
During application startup:

>>> # In lifespan() function
>>> readiness = ReadinessProbe(context)
>>> await readiness.initialize()
>>> app.state.readiness = readiness

In readiness endpoint:

>>> # In /readyz handler
>>> results = await readiness.refresh()
>>> return {"ready": all(r.healthy for r in results.values()), "checks": results}

See Also
--------
codeintel_rev.app.config_context : ApplicationContext with configuration
codeintel_rev.app.main : FastAPI application with /readyz endpoint
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import duckdb
import httpx

from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

LOGGER = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class CheckResult:
    """Outcome of a single readiness check.

    Attributes
    ----------
    healthy : bool
        Whether the resource is ready for use.
    detail : str | None
        Diagnostic detail when unhealthy or degraded. None when healthy.

    Examples
    --------
    >>> result = CheckResult(healthy=True)
    >>> result.as_payload()
    {'healthy': True}

    >>> result = CheckResult(healthy=False, detail="FAISS index not found")
    >>> result.as_payload()
    {'healthy': False, 'detail': 'FAISS index not found'}
    """

    healthy: bool
    detail: str | None = None

    def as_payload(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary.

        Returns
        -------
        dict[str, Any]
            Dictionary with "healthy" boolean and optional "detail" string.
        """
        payload: dict[str, Any] = {"healthy": self.healthy}
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


class ReadinessProbe:
    """Manages readiness checks across core dependencies.

    This class performs comprehensive health checks on all critical application
    resources including filesystem paths, indexes, databases, and external
    services. Checks are performed synchronously in a thread pool to avoid
    blocking the event loop.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing configuration and clients.

    Examples
    --------
    Initialize during application startup:

    >>> readiness = ReadinessProbe(context)
    >>> await readiness.initialize()

    Refresh checks on demand:

    >>> results = await readiness.refresh()
    >>> all_healthy = all(r.healthy for r in results.values())

    Get cached snapshot:

    >>> snapshot = readiness.snapshot()
    >>> faiss_status = snapshot["faiss_index"]

    Notes
    -----
    The probe maintains a cache of check results to avoid recomputing on every
    request. The cache is updated atomically via async lock during refresh().

    Internal attributes (not part of public API):
    - ``_context``: Application context with configuration and paths
    - ``_lock``: Lock protecting _last_checks cache during concurrent refresh calls
    - ``_last_checks``: Cache of most recent check results keyed by resource name
    """

    def __init__(self, context: ApplicationContext) -> None:
        self._context = context
        self._lock = asyncio.Lock()
        self._last_checks: dict[str, CheckResult] = {}

    async def initialize(self) -> None:
        """Prime readiness state on application startup.

        Performs initial readiness checks and caches results. This should be
        called once during application startup before serving requests.

        Examples
        --------
        >>> readiness = ReadinessProbe(context)
        >>> await readiness.initialize()
        """
        await self.refresh()

    async def refresh(self) -> Mapping[str, CheckResult]:
        """Recompute readiness checks asynchronously.

        Runs all checks in a thread pool to avoid blocking the event loop.
        Updates the internal cache atomically and returns the latest results.

        Returns
        -------
        Mapping[str, CheckResult]
            Latest readiness results keyed by resource name. Keys include:
            - "repo_root": Repository root directory check
            - "data_dir": Data directory check (created if missing)
            - "vectors_dir": Vectors directory check (created if missing)
            - "faiss_index": FAISS index file check
            - "duckdb_catalog": DuckDB catalog file check
            - "scip_index": SCIP index file check (optional)
            - "vllm_service": vLLM service connectivity check

        Examples
        --------
        >>> results = await readiness.refresh()
        >>> faiss_healthy = results["faiss_index"].healthy
        """
        checks = await asyncio.to_thread(self._run_checks)
        async with self._lock:
            self._last_checks = checks
            return dict(self._last_checks)

    async def shutdown(self) -> None:
        """Clear readiness state on shutdown.

        Clears the internal cache of check results. Should be called during
        application shutdown to free resources.

        Examples
        --------
        >>> await readiness.shutdown()
        """
        async with self._lock:
            self._last_checks.clear()

    def snapshot(self) -> Mapping[str, CheckResult]:
        """Return the latest readiness snapshot.

        Returns the cached check results without performing new checks. Use
        refresh() to update the cache with fresh results.

        Returns
        -------
        Mapping[str, CheckResult]
            Most recent readiness results from the last refresh() call.

        Raises
        ------
        RuntimeError
            If the probe has not been initialized yet (no refresh() called).

        Examples
        --------
        >>> snapshot = readiness.snapshot()
        >>> if snapshot["faiss_index"].healthy:
        ...     # FAISS is ready
        ...     pass
        """
        if not self._last_checks:
            msg = "Readiness probe not initialized"
            raise RuntimeError(msg)
        return dict(self._last_checks)

    def _run_checks(self) -> dict[str, CheckResult]:
        """Execute all readiness checks synchronously.

        Performs checks on all critical resources including filesystem paths,
        index files, and external services. This method runs in a thread pool
        to avoid blocking the event loop.

        Returns
        -------
        dict[str, CheckResult]
            Check results keyed by resource name.
        """
        results: dict[str, CheckResult] = {}
        paths = self._context.paths

        # Check 1: Repository root exists
        results["repo_root"] = self.check_directory(paths.repo_root)

        # Check 2: Data directories exist (create if missing)
        results["data_dir"] = self.check_directory(paths.data_dir, create=True)
        results["vectors_dir"] = self.check_directory(paths.vectors_dir, create=True)

        # Check 3: FAISS index exists
        results["faiss_index"] = self.check_file(
            paths.faiss_index,
            description="FAISS index",
            optional=False,
        )

        # Check 4: DuckDB catalog exists (and is materialized when configured)
        results["duckdb_catalog"] = self._check_duckdb_catalog(paths.duckdb_path)

        # Check 5: SCIP index exists (optional - may be regenerated)
        results["scip_index"] = self.check_file(
            paths.scip_index,
            description="SCIP index",
            optional=True,
        )

        # Check 6: vLLM service reachable
        results["vllm_service"] = self.check_vllm_connection()

        # Check 7: Search tooling available (ripgrep preferred, grep fallback)
        results["search_cli"] = self._check_search_tools()

        # Check 8: XTR artifacts (optional late-interaction)
        results["xtr_artifacts"] = self._check_xtr_artifacts()

        return results

    @staticmethod
    def check_directory(path: Path, *, create: bool = False) -> CheckResult:
        """Ensure a directory exists (creating it if requested).

        Parameters
        ----------
        path : Path
            Directory path to validate.
        create : bool, optional
            When True, create the directory hierarchy if it is missing.
            Defaults to False.

        Returns
        -------
        CheckResult
            Healthy status and diagnostic detail when unavailable.

        Examples
        --------
        >>> result = ReadinessProbe.check_directory(Path("/tmp/test"))
        >>> result.healthy
        True

        >>> result = ReadinessProbe.check_directory(Path("/nonexistent"), create=True)
        >>> result.healthy
        True  # Directory was created
        """
        try:
            if create:
                path.mkdir(parents=True, exist_ok=True)
            exists = path.is_dir()
        except OSError as exc:
            return CheckResult(healthy=False, detail=f"Cannot access directory {path}: {exc}")

        if not exists:
            return CheckResult(healthy=False, detail=f"Directory missing: {path}")
        return CheckResult(healthy=True)

    @staticmethod
    def check_file(path: Path, *, description: str, optional: bool = False) -> CheckResult:
        """Validate existence of a filesystem resource.

        Parameters
        ----------
        path : Path
            Target filesystem path.
        description : str
            Human-readable resource description for diagnostics.
        optional : bool, optional
            When True, missing resources mark the check as healthy but include
            detail. Defaults to False (missing resources fail the check).

        Returns
        -------
        CheckResult
            Healthy status and contextual detail.

        Examples
        --------
        >>> result = ReadinessProbe.check_file(
        ...     Path("/tmp/test.txt"), description="test file", optional=False
        ... )
        >>> result.healthy
        False  # File doesn't exist

        >>> result = ReadinessProbe.check_file(
        ...     Path("/tmp/test.txt"), description="test file", optional=True
        ... )
        >>> result.healthy
        True  # Optional file missing is OK
        >>> result.detail
        'test file not found at /tmp/test.txt'
        """
        try:
            exists = path.is_file()
        except OSError as exc:
            return CheckResult(
                healthy=False,
                detail=f"Cannot access {description} at {path}: {exc}",
            )

        if exists:
            return CheckResult(healthy=True)

        detail = f"{description} not found at {path}"
        if optional:
            return CheckResult(healthy=True, detail=detail)
        return CheckResult(healthy=False, detail=detail)

    def _check_duckdb_catalog(self, path: Path) -> CheckResult:
        """Validate DuckDB catalog presence and optional materialization state.

        Parameters
        ----------
        path : Path
            Path to the DuckDB catalog file.

        Returns
        -------
        CheckResult
            Healthy status and diagnostic detail when validation fails.
        """
        file_result = self.check_file(path, description="DuckDB catalog", optional=False)
        if not file_result.healthy:
            return file_result

        if not self._context.settings.index.duckdb_materialize:
            return file_result

        try:
            conn = duckdb.connect(str(path))
        except duckdb.Error as exc:
            return CheckResult(healthy=False, detail=f"Unable to open DuckDB catalog: {exc}")

        detail: str | None = None
        try:
            if not self._duckdb_table_exists(conn):
                detail = (
                    "DuckDB materialization enabled but chunks_materialized table missing. "
                    "Re-run the indexing pipeline to refresh the catalog."
                )
            elif not self._duckdb_index_exists(conn):
                detail = (
                    "DuckDB materialization enabled but idx_chunks_materialized_uri index missing. "
                    "Re-run the indexing pipeline to rebuild indexes."
                )
        except duckdb.Error as exc:
            detail = f"DuckDB catalog validation failed: {exc}"
        finally:
            conn.close()

        if detail is not None:
            return CheckResult(healthy=False, detail=detail)
        return CheckResult(healthy=True)

    def _check_xtr_artifacts(self) -> CheckResult:
        """Verify that XTR token artifacts are present when enabled.

        Returns
        -------
        CheckResult
            Healthy status describing artifact availability.
        """
        cfg = self._context.settings.xtr
        xtr_dir = self._context.paths.xtr_dir
        token_name = "tokens.f32" if cfg.dtype == "float32" else "tokens.f16"
        token_path = xtr_dir / token_name
        meta_path = xtr_dir / "index.meta.json"
        expected = [token_path, meta_path]
        missing = [path for path in expected if not path.exists()]
        if not missing:
            return CheckResult(healthy=True)
        detail = f"Missing XTR artifacts: {', '.join(str(path) for path in missing)}"
        if cfg.enable:
            return CheckResult(healthy=False, detail=detail)
        return CheckResult(healthy=True, detail=detail)

    @staticmethod
    def _duckdb_table_exists(conn: duckdb.DuckDBPyConnection) -> bool:
        """Return True when `chunks_materialized` table exists.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB database connection.

        Returns
        -------
        bool
            ``True`` when the materialized table exists, ``False`` otherwise.
        """
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'main'
              AND table_name = 'chunks_materialized'
            """
        ).fetchone()
        return bool(row and row[0])

    @staticmethod
    def _duckdb_index_exists(conn: duckdb.DuckDBPyConnection) -> bool:
        """Return True when `idx_chunks_materialized_uri` index exists.

        Parameters
        ----------
        conn : duckdb.DuckDBPyConnection
            DuckDB database connection.

        Returns
        -------
        bool
            ``True`` when the index exists, ``False`` otherwise.
        """
        row = conn.execute(
            """
            SELECT COUNT(*) FROM duckdb_indexes
            WHERE table_name = 'chunks_materialized'
              AND index_name = 'idx_chunks_materialized_uri'
            """
        ).fetchone()
        return bool(row and row[0])

    @staticmethod
    def _check_search_tools() -> CheckResult:
        """Ensure either ripgrep or grep is available for text search.

        Returns
        -------
        CheckResult
            Healthy status if ripgrep or grep is available, otherwise error detail.
        """
        rg_path = shutil.which("rg")
        grep_path = shutil.which("grep")

        if rg_path:
            return CheckResult(healthy=True)

        if grep_path:
            detail = f"ripgrep (rg) not found; using grep fallback at {grep_path}"
            return CheckResult(healthy=True, detail=detail)

        return CheckResult(
            healthy=False,
            detail="Search tooling unavailable: install ripgrep (rg) or provide grep on PATH.",
        )

    def check_vllm_connection(self) -> CheckResult:
        """Verify vLLM service is reachable with a lightweight health check.

        Performs a two-phase check:
        1. Validates URL format (scheme and netloc)
        2. Attempts HTTP GET to /health endpoint with short timeout

        Returns
        -------
        CheckResult
            Healthy status reflecting vLLM service availability.

        Examples
        --------
        >>> result = readiness.check_vllm_connection()
        >>> if result.healthy:
        ...     # vLLM is reachable
        ...     pass
        """
        vllm_url = self._context.settings.vllm.base_url
        parsed = urlparse(vllm_url)

        # Phase 1: URL validation
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return CheckResult(
                healthy=False,
                detail=f"Invalid vLLM endpoint URL: {vllm_url}",
            )

        # Phase 2: HTTP reachability check (non-blocking, short timeout)
        try:
            with httpx.Client(timeout=2.0) as client:
                response = client.get(f"{vllm_url}/health", follow_redirects=True)
                if response.is_success:
                    return CheckResult(healthy=True)
                return CheckResult(
                    healthy=False,
                    detail=f"vLLM health check failed: HTTP {response.status_code}",
                )
        except httpx.HTTPError as exc:
            return CheckResult(
                healthy=False,
                detail=f"vLLM service unreachable: {exc}",
            )
