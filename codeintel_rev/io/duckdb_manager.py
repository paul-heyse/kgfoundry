"""Thread-safe DuckDB connection manager."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import duckdb

__all__ = ["DuckDBConfig", "DuckDBManager"]


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
    """

    threads: int = 4
    enable_object_cache: bool = True


class DuckDBManager:
    """Factory for DuckDB connections with consistent pragmas.

    Parameters
    ----------
    db_path : Path
        Path to the DuckDB catalog database file.
    config : DuckDBConfig
        Connection configuration controlling threading and caching pragmas.
    """

    def __init__(self, db_path: Path, config: DuckDBConfig | None = None) -> None:
        self._db_path = db_path
        self._config = config or DuckDBConfig()

    @contextmanager
    def connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Yield a configured DuckDB connection.

        Returns
        -------
        Iterator[duckdb.DuckDBPyConnection]
            Connection configured with the requested pragmas. The connection is
            automatically closed when the context manager exits.
        """
        conn = duckdb.connect(str(self._db_path))
        try:
            if self._config.enable_object_cache:
                conn.execute("PRAGMA enable_object_cache")
            conn.execute(f"SET threads = {self._config.threads}")
            yield conn
        finally:
            conn.close()
