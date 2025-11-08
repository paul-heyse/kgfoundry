"""Thread-safe DuckDB connection manager."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import duckdb

__all__ = ["DuckDBConfig", "DuckDBManager", "DuckDBQueryBuilder", "DuckDBQueryOptions"]


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
        Emit debug-level logs for every executed SQL statement. Disabled by
        default to avoid noise in production environments.
    """

    threads: int = 4
    enable_object_cache: bool = True
    log_queries: bool = False


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

        Yields
        ------
        duckdb.DuckDBPyConnection
            Connection configured with the requested pragmas. The connection is
            automatically closed when the context manager exits.
        """
        conn = duckdb.connect(str(self._db_path))
        try:
            if self._config.enable_object_cache:
                conn.execute("PRAGMA enable_object_cache = true")
            conn.execute(f"SET threads = {self._config.threads}")
            yield conn
        finally:
            conn.close()

    @property
    def config(self) -> DuckDBConfig:
        """Return the active DuckDB configuration."""
        return self._config


@dataclass(slots=True, frozen=True)
class DuckDBQueryOptions:
    """Options controlling DuckDB query generation."""

    include_globs: Sequence[str] | None = None
    exclude_globs: Sequence[str] | None = None
    languages: Sequence[str] | None = None
    select_columns: Sequence[str] | None = None
    preserve_order: bool = False


class DuckDBQueryBuilder:
    """Helper for building parameterized DuckDB queries with scope filters."""

    def build_filter_query(
        self,
        *,
        chunk_ids: Sequence[int],
        options: DuckDBQueryOptions | None = None,
    ) -> tuple[str, dict[str, list[int] | list[str] | str]]:
        """Return SQL and parameters for scoped chunk retrieval.

        Parameters
        ----------
        chunk_ids : Sequence[int]
            Chunk identifiers to hydrate. Must not be empty.
        options : DuckDBQueryOptions | None, optional
            Query generation options including include/exclude globs, language
            filters, select columns, and ordering behavior.

        Returns
        -------
        tuple[str, dict[str, list[int] | list[str] | str]]
            SQL query string and mapping of named parameters to values.

        Raises
        ------
        ValueError
            If ``chunk_ids`` is empty.
        """
        ids = list(chunk_ids)
        if not ids:
            msg = "chunk_ids must contain at least one identifier"
            raise ValueError(msg)

        opts = options or DuckDBQueryOptions()

        params: dict[str, list[int] | list[str] | str] = {"ids": ids}
        include_globs = list(opts.include_globs or [])
        exclude_globs = list(opts.exclude_globs or [])
        languages = list(opts.languages or [])

        columns = (
            tuple(opts.select_columns)
            if opts.select_columns
            else (
                "id",
                "uri",
                "start_line",
                "end_line",
                "lang",
                "content",
            )
        )
        select_clause = ", ".join(columns)

        sql_lines: list[str] = [f"SELECT {select_clause}", "FROM chunks AS c"]
        join_lines: list[str] = []
        where_clauses: list[str] = []
        order_clause: str | None = None

        if opts.preserve_order:
            join_lines.extend(
                [
                    "JOIN UNNEST($ids) WITH ORDINALITY AS ids(id, position)",
                    "  ON c.id = ids.id",
                ]
            )
            order_clause = "ORDER BY ids.position"
        else:
            where_clauses.append("c.id = ANY($ids)")

        where_clauses.extend(
            self._build_where_clauses(
                params=params,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                languages=languages,
            )
        )

        if join_lines:
            sql_lines.extend(join_lines)

        if where_clauses:
            sql_lines.append("WHERE " + where_clauses[0])
            sql_lines.extend(f"  AND {clause}" for clause in where_clauses[1:])

        if order_clause:
            sql_lines.append(order_clause)

        sql = "\n".join(sql_lines)
        return sql, params

    def _build_where_clauses(
        self,
        *,
        params: dict[str, list[int] | list[str] | str],
        include_globs: Sequence[str],
        exclude_globs: Sequence[str],
        languages: Sequence[str],
    ) -> list[str]:
        """Build WHERE clauses and populate params based on filters.

        Returns
        -------
        list[str]
            SQL fragments that should be combined with ``AND`` in the final query.
        """
        clauses: list[str] = []

        if include_globs:
            include_clauses: list[str] = []
            for index, pattern in enumerate(include_globs):
                key = f"include_{index}"
                params[key] = self._glob_to_like(pattern)
                include_clauses.append(f"c.uri LIKE ${key} ESCAPE '\\'")
            clauses.append(f"({' OR '.join(include_clauses)})")

        if exclude_globs:
            for index, pattern in enumerate(exclude_globs):
                key = f"exclude_{index}"
                params[key] = self._glob_to_like(pattern)
                clauses.append(f"c.uri NOT LIKE ${key} ESCAPE '\\'")

        if languages:
            params["languages"] = [str(language) for language in languages]
            clauses.append("c.lang = ANY($languages)")

        return clauses

    @classmethod
    def _glob_to_like(cls, pattern: str) -> str:
        normalized = pattern.replace("\\", "/")
        starts_with_recursive = normalized.startswith("**/")
        recursive_remainder = normalized[len("**/") :] if starts_with_recursive else ""

        escaped = cls._escape_like_wildcards(normalized)
        escaped = escaped.replace("**", "%")
        escaped = escaped.replace("*", "%")
        escaped = escaped.replace("?", "_")

        if (
            starts_with_recursive
            and recursive_remainder.startswith("*")
            and escaped.startswith("%/")
        ):
            escaped = escaped.replace("/%", "%", 1)
            escaped = "%" + escaped.lstrip("%")

        return escaped

    @staticmethod
    def _escape_like_wildcards(pattern: str) -> str:
        return pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
