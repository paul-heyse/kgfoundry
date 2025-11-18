"""Thread-safe DuckDB connection manager."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Full, LifoQueue
from threading import Lock
from time import perf_counter
from typing import TYPE_CHECKING, Protocol, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.io.duckdb_dao import DuckDBQueryBuilder, DuckDBQueryOptions

if TYPE_CHECKING:
    import duckdb
else:
    duckdb = cast("duckdb", LazyModule("duckdb", "DuckDB connection management"))

__all__ = [
    "DuckDBConfig",
    "DuckDBManager",
    "DuckDBManagerContext",
    "DuckDBQueryBuilder",
    "DuckDBQueryOptions",
]


@dataclass(slots=True, frozen=True)
class DuckDBConfig:
    """Configuration parameters controlling DuckDB connections.

    Attributes
    ----------
    threads : int
        Number of DuckDB worker threads to use for queries executed on the
        returned connection. Defaults to ``4`` which offers good parallelism for
        local development while remaining conservative for CI environments.
    enable_object_cache : bool
        Enable DuckDB's object cache to reuse parsed query plans and cached
        Parquet metadata across connections. Enabled by default for repeated
        catalog queries.
    log_queries : bool
        Deprecated toggle retained for backwards compatibility. No effect.
    pool_size : int | None
        Maximum number of DuckDB connections to keep in the optional connection
        pool. ``None`` or ``0`` disables pooling (default). When enabled,
        connections are reused across requests up to the configured limit.
    """

    threads: int = 4
    enable_object_cache: bool = True
    log_queries: bool = False
    pool_size: int | None = None


class DuckDBConnector(Protocol):
    """Callable protocol describing DuckDB connection factories."""

    def __call__(
        self, database: str, *, read_only: bool
    ) -> duckdb.DuckDBPyConnection:  # pragma: no cover - protocol
        ...


@dataclass(slots=True, frozen=True)
class DuckDBManagerContext:
    """Dependency providers for DuckDBManager."""

    connector: DuckDBConnector

    @classmethod
    def production(cls) -> DuckDBManagerContext:
        """Return context using the real duckdb.connect factory.

        Returns
        -------
        DuckDBManagerContext
            Context configured to call :func:`duckdb.connect`.
        """

        def _connector(database: str, *, read_only: bool) -> duckdb.DuckDBPyConnection:
            return duckdb.connect(database, read_only=read_only)

        return cls(connector=_connector)


class _InstrumentedDuckDBConnection:
    """Proxy connection that instruments DuckDB execute calls."""

    __slots__ = ("_config", "_conn")

    def __init__(self, conn: duckdb.DuckDBPyConnection, config: DuckDBConfig) -> None:
        self._conn = conn
        self._config = config

    def execute(
        self,
        query: duckdb.Statement | str,
        parameters: object | None = None,
    ) -> duckdb.DuckDBPyConnection:
        """Execute a SQL query while tracking execution time.

        This method wraps DuckDB connection execution with logging,
        recording query execution time, SQL length, and optionally the SQL
        text itself.

        Parameters
        ----------
        query : duckdb.Statement | str
            SQL query to execute. Accepts raw SQL strings or DuckDB ``Statement``
            objects that expose precompiled statements.
        parameters : object | None, optional
            Optional parameter payload bound to the statement before execution.

        Returns
        -------
        duckdb.DuckDBPyConnection
            Instrumented connection (self) to support chaining follow-up calls
            such as ``fetchall()`` without breaking existing code.

        Notes
        -----
        The method tracks execution time and records it in milliseconds. When
        log_queries is enabled in the config, the SQL text (truncated to 5000
        characters) is included in log messages.
        """
        start = perf_counter()
        if parameters is not None:
            self._conn.execute(query, parameters)
        else:
            self._conn.execute(query)
        _ = round((perf_counter() - start) * 1000, 2)
        return cast("duckdb.DuckDBPyConnection", self)

    def __getattr__(self, name: str) -> object:
        """Delegate attribute access to the underlying DuckDB connection.

        This method allows transparent access to DuckDB connection methods
        and attributes that are not explicitly wrapped by this class.

        Parameters
        ----------
        name : str
            Name of the attribute or method to access from the underlying
            DuckDB connection.

        Returns
        -------
        object
            The requested attribute or method from the underlying connection.
            Can be any attribute or method available on the DuckDB connection
            object.

        Notes
        -----
        This method enables transparent delegation to the underlying DuckDB
        connection, allowing callers to use DuckDB-specific methods and
        attributes without explicit wrapper methods. Used for methods like
        fetchone(), fetchall(), etc. that are not explicitly wrapped.
        """
        return getattr(self._conn, name)


class DuckDBManager:
    """Factory for DuckDB connections with consistent pragmas.

    Parameters
    ----------
    db_path : Path
        Path to the DuckDB catalog database file.
    config : DuckDBConfig | None, optional
        Connection configuration controlling threading and caching pragmas.
        If ``None``, uses default configuration. Defaults to ``None``.
    context : DuckDBManagerContext | None, optional
        Dependency overrides controlling how DuckDB connections are created.
        Tests can pass a custom connector to observe connection counts or stub
        DuckDB entirely. Defaults to :meth:`DuckDBManagerContext.production`.
    """

    def __init__(
        self,
        db_path: Path,
        config: DuckDBConfig | None = None,
        *,
        context: DuckDBManagerContext | None = None,
    ) -> None:
        self._db_path = db_path
        self._config = config or DuckDBConfig()
        self._context = context or DuckDBManagerContext.production()
        pool_size = self._config.pool_size or 0
        self._pool_size = max(pool_size, 0)
        self._pool: LifoQueue[duckdb.DuckDBPyConnection] | None = (
            LifoQueue(maxsize=self._pool_size) if self._pool_size else None
        )
        self._pool_lock: Lock | None = Lock() if self._pool_size else None
        self._connections_created = 0

    @contextmanager
    def connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Yield a configured DuckDB connection.

        Yields
        ------
        duckdb.DuckDBPyConnection
            Connection configured with requested pragmas and telemetry hooks.
            The underlying DuckDB connection is automatically released when the
            context manager exits.

        Notes
        -----
        When ``DuckDBConfig.pool_size`` is greater than zero, connections are
        taken from and returned to an in-process pool, ensuring bounded
        concurrency without reopening the database file for every request.
        """
        conn = self._acquire_connection()
        instrumented = _InstrumentedDuckDBConnection(conn, self._config)
        try:
            yield cast("duckdb.DuckDBPyConnection", instrumented)
        finally:
            self._release_connection(conn)

    @contextmanager
    def readonly_connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Yield a dedicated read-only DuckDB connection (non pooled).

        Yields
        ------
        duckdb.DuckDBPyConnection
            Instrumented connection opened in read-only mode.
        """
        conn = self._create_connection(read_only=True)
        instrumented = _InstrumentedDuckDBConnection(conn, self._config)
        try:
            yield cast("duckdb.DuckDBPyConnection", instrumented)
        finally:
            conn.close()

    @property
    def config(self) -> DuckDBConfig:
        """Return the active DuckDB configuration."""
        return self._config

    @property
    def connections_created(self) -> int:
        """Return the number of pooled connections created."""
        if self._pool_lock is not None:
            with self._pool_lock:
                return self._connections_created
        return self._connections_created

    def close(self) -> None:
        """Close all pooled connections and reset pool counters."""
        if self._pool is None:
            return
        while True:
            try:
                conn = self._pool.get_nowait()
            except Empty:
                break
            conn.close()
        pool_lock = self._pool_lock
        if pool_lock is not None:
            with pool_lock:
                self._connections_created = 0

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        """Ensure pooled connections are released during garbage collection."""
        with suppress(Exception):
            self.close()

    def _create_connection(self, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        connector = self._context.connector
        conn = connector(str(self._db_path), read_only=read_only)
        if self._config.enable_object_cache:
            conn.execute("PRAGMA enable_object_cache = true")
        conn.execute(f"SET threads = {self._config.threads}")
        return conn

    def _acquire_connection(self) -> duckdb.DuckDBPyConnection:
        if self._pool is None:
            return self._create_connection()
        try:
            return self._pool.get_nowait()
        except Empty:
            pass

        pool_lock = self._pool_lock
        if pool_lock is None:
            return self._create_connection()
        with pool_lock:
            if self._connections_created < self._pool_size:
                conn = self._create_connection()
                self._connections_created += 1
                return conn

        # Pool exhausted, block until one is returned.
        return self._pool.get()

    def _release_connection(self, conn: duckdb.DuckDBPyConnection) -> None:
        if self._pool is None:
            conn.close()
            return
        try:
            self._pool.put_nowait(conn)
        except Full:
            conn.close()
            pool_lock = self._pool_lock
            if pool_lock is not None:
                with pool_lock:
                    self._connections_created = max(self._connections_created - 1, 0)
