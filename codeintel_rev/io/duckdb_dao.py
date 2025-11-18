"""DAO helpers for the DuckDB catalog, executing schema SQL."""

# DuckDB refuses bind parameters inside CREATE VIEW / read_parquet statements,
# so paths are safely quoted/escaped in this module instead.

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.io.duckdb_schema import (
    TABLE_FAISS_IDMAP_MAT,
    TABLE_FAISS_JOIN_MAT,
    VIEW_CHUNKS,
    IdMapMeta,
    sql_count,
    sql_create_chunks_materialized,
    sql_create_chunks_materialized_index,
    sql_create_chunks_view_from_materialized,
    sql_create_chunks_view_from_parquet,
    sql_create_empty_chunks_materialized,
    sql_create_empty_chunks_view,
    sql_create_empty_faiss_idmap_view,
    sql_create_faiss_idmap_from_materialized,
    sql_create_faiss_idmap_view,
    sql_create_idmap_mat,
    sql_create_idmap_mat_meta,
    sql_create_v_faiss_join,
    sql_delete_idmap_mat,
    sql_delete_idmap_meta,
    sql_insert_idmap_mat,
    sql_insert_idmap_meta,
    sql_materialize_v_faiss_join,
    sql_relation_exists,
    sql_select_idmap_checksum,
)

if TYPE_CHECKING:
    import duckdb
else:
    duckdb = cast("duckdb", LazyModule("duckdb", "DuckDB DAO operations"))

_PARQUET_MAGIC = b"PAR1"


def _quote_parquet_literal(parquet_path: Path) -> str:
    """Return a safely quoted Parquet path literal for unsupported parametrization.

    Parameters
    ----------
    parquet_path : Path
        File path to quote and escape for SQL literal usage.

    Returns
    -------
    str
        Quoted literal safe for inclusion in DDL statements.
    """
    literal = str(parquet_path)
    escape_fn = cast("Callable[[str], str] | None", getattr(duckdb, "escape_string", None))
    escaped = escape_fn(literal) if callable(escape_fn) else literal.replace("'", "''")
    return f"'{escaped}'"


def _apply_parquet_path(sql: str, parquet_path: Path) -> str:
    """Inline a Parquet path literal for DDL statements that disallow parameters.

    Parameters
    ----------
    sql : str
        SQL statement template with a single '?' placeholder.
    parquet_path : Path
        File path to substitute into the SQL template.

    Returns
    -------
    str
        SQL statement with the literal substituted once.
    """
    return sql.replace("?", _quote_parquet_literal(parquet_path), 1)


def _is_valid_parquet_file(path: Path) -> bool:
    """Return True when path appears to contain a valid Parquet file.

    Parameters
    ----------
    path : Path
        File path to check for Parquet format.

    Returns
    -------
    bool
        True when both the header and footer contain the Parquet magic value.
    """
    try:
        if path.stat().st_size < len(_PARQUET_MAGIC) * 2:
            return False
        with path.open("rb") as handle:
            header = handle.read(len(_PARQUET_MAGIC))
            if header != _PARQUET_MAGIC:
                return False
            handle.seek(-len(_PARQUET_MAGIC), os.SEEK_END)
            footer = handle.read(len(_PARQUET_MAGIC))
            return footer == _PARQUET_MAGIC
    except OSError:
        return False


def relation_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    """Return True when a table or view with the given name exists.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        Active DuckDB connection to query.
    name : str
        Name of the table or view to check for existence.

    Returns
    -------
    bool
        True when the relation exists, otherwise False.
    """
    result = conn.execute(sql_relation_exists(), [name]).fetchone()
    return bool(result and result[0])


def ensure_chunks(
    conn: duckdb.DuckDBPyConnection, *, parquet_glob: str, materialize: bool, parquet_exists: bool
) -> None:
    """Ensure the chunks view or table exists in the database.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        DuckDB connection to use for executing SQL operations.
    parquet_glob : str
        Glob pattern for Parquet files containing chunk data.
    materialize : bool
        When True, create a materialized table. When False, create a view.
    parquet_exists : bool
        Whether Parquet files matching the glob pattern exist.
    """
    if materialize:
        if parquet_exists:
            conn.execute(_apply_parquet_path(sql_create_chunks_materialized(), Path(parquet_glob)))
        else:
            conn.execute(sql_create_empty_chunks_materialized())
        conn.execute(sql_create_chunks_view_from_materialized())
        conn.execute(sql_create_chunks_materialized_index())
        return

    if parquet_exists:
        conn.execute(_apply_parquet_path(sql_create_chunks_view_from_parquet(), Path(parquet_glob)))
        return

    conn.execute(sql_create_empty_chunks_view())


def ensure_faiss_idmap_view(conn: duckdb.DuckDBPyConnection, *, idmap_parquet: Path | None) -> None:
    """Ensure the FAISS ID map view exists in the database.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        DuckDB connection to use for executing SQL operations.
    idmap_parquet : Path | None
        Optional path to FAISS ID map Parquet file. If provided and valid,
        creates view from Parquet. Otherwise, creates view from materialized
        table or empty view.
    """
    if idmap_parquet and idmap_parquet.exists() and _is_valid_parquet_file(idmap_parquet):
        conn.execute(_apply_parquet_path(sql_create_faiss_idmap_view(), idmap_parquet))
        return

    if relation_exists(conn, TABLE_FAISS_IDMAP_MAT):
        column = _choose_idmap_column(conn)
        conn.execute(sql_create_faiss_idmap_from_materialized(column))
        return

    conn.execute(sql_create_empty_faiss_idmap_view())


def _choose_idmap_column(conn: duckdb.DuckDBPyConnection) -> str | None:
    """Choose the appropriate ID column name from the ID map table.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        DuckDB connection to query for table schema.

    Returns
    -------
    str | None
        Column name to use ("chunk_id" or "external_id"). ``None`` when neither exists.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info('faiss_idmap_mat')").fetchall()}
    if "chunk_id" in columns:
        return "chunk_id"
    if "external_id" in columns:
        return "external_id"
    return None


def ensure_v_faiss_join(conn: duckdb.DuckDBPyConnection) -> None:
    """Ensure the v_faiss_join view exists in the database.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        DuckDB connection to use for executing SQL operations.
    """
    conn.execute(sql_create_v_faiss_join())


def materialize_v_faiss_join(conn: duckdb.DuckDBPyConnection) -> int:
    """Materialize the v_faiss_join view into a table.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        DuckDB connection to use for executing SQL operations.

    Returns
    -------
    int
        Number of rows in the materialized table.
    """
    conn.execute(sql_materialize_v_faiss_join())
    count = conn.execute(sql_count(TABLE_FAISS_JOIN_MAT)).fetchone()
    return int(count[0]) if count and count[0] is not None else 0


def refresh_faiss_idmap_materialized(
    conn: duckdb.DuckDBPyConnection,
    *,
    idmap_parquet: Path,
    checksum: str,
) -> IdMapMeta:
    """Refresh the materialized FAISS ID map table with checksum-based logic.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection
        DuckDB connection to use for executing SQL operations.
    idmap_parquet : Path
        Path to the FAISS ID map Parquet file.
    checksum : str
        Checksum of the ID map Parquet file for change detection.

    Returns
    -------
    IdMapMeta
        Metadata describing the materialized table including checksum, row count,
        and whether a refresh occurred.
    """
    conn.execute(sql_create_idmap_mat())
    conn.execute(sql_create_idmap_mat_meta())

    prev_row = conn.execute(sql_select_idmap_checksum()).fetchone()
    prev_checksum = prev_row[0] if prev_row else None

    refreshed = False
    if prev_checksum != checksum:
        conn.execute(sql_delete_idmap_mat())
        conn.execute(sql_insert_idmap_mat())
        refreshed = True

    row = conn.execute(sql_count(TABLE_FAISS_IDMAP_MAT)).fetchone()
    rows = int(row[0]) if row and row[0] is not None else 0
    conn.execute(sql_delete_idmap_meta())
    conn.execute(sql_insert_idmap_meta(), [str(idmap_parquet), checksum, checksum, rows])
    return IdMapMeta(
        parquet_path=str(idmap_parquet), parquet_hash=checksum, row_count=rows, refreshed=refreshed
    )


@dataclass(slots=True)
class DuckDBQueryOptions:
    """Options for building DuckDB chunk queries.

    Attributes
    ----------
    include_globs : Sequence[str] | None
        Glob patterns for URIs to include in results.
    exclude_globs : Sequence[str] | None
        Glob patterns for URIs to exclude from results.
    languages : Sequence[str] | None
        Language codes to filter by.
    select_columns : Sequence[str] | None
        Column names to select. If None, uses default columns.
    preserve_order : bool
        Whether to preserve the order of chunk IDs in results.
    join_modules : bool
        Whether to join with modules table.
    join_symbols : bool
        Whether to join with symbol catalog.
    join_faiss : bool
        Whether to join with FAISS ID map.
    join_ast : bool
        Whether to join with AST nodes.
    join_cst : bool
        Whether to join with CST nodes.
    """

    include_globs: Sequence[str] | None = None
    exclude_globs: Sequence[str] | None = None
    languages: Sequence[str] | None = None
    select_columns: Sequence[str] | None = None
    preserve_order: bool = False
    join_modules: bool = False
    join_symbols: bool = False
    join_faiss: bool = False
    join_ast: bool = False
    join_cst: bool = False


class DuckDBQueryBuilder:
    """Helper constructing parameterized queries for chunk filtering."""

    def build_filter_query(
        self,
        *,
        chunk_ids: Sequence[int],
        options: DuckDBQueryOptions | None = None,
    ) -> tuple[str, dict[str, list[int] | list[str] | str]]:
        """Build a parameterized SQL query for filtering chunks.

        Parameters
        ----------
        chunk_ids : Sequence[int]
            List of chunk IDs to filter by. Must contain at least one ID.
        options : DuckDBQueryOptions | None, optional
            Optional query options for filtering, joining, and column selection.

        Returns
        -------
        tuple[str, dict[str, list[int] | list[str] | str]]
            Tuple containing the SQL query string and parameter dictionary.

        Raises
        ------
        ValueError
            When chunk_ids is empty.
        """
        ids = list(chunk_ids)
        if not ids:
            message = "chunk_ids must contain at least one identifier"
            raise ValueError(message)

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

        sql_lines: list[str] = [f"SELECT {select_clause}", f"FROM {VIEW_CHUNKS} AS c"]
        join_lines: list[str] = []
        where_clauses: list[str] = []
        order_clause: str | None = None

        join_lines.extend(self._build_join_clauses(opts))

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

    @staticmethod
    def _build_join_clauses(opts: DuckDBQueryOptions) -> list[str]:
        """Build SQL JOIN clauses from query options.

        Parameters
        ----------
        opts : DuckDBQueryOptions
            Query options specifying which tables to join.

        Returns
        -------
        list[str]
            List of JOIN clause strings (LEFT JOIN statements).
        """
        joins: list[str] = []
        if opts.join_modules:
            joins.append("LEFT JOIN modules USING(uri)")
        if opts.join_symbols:
            joins.append("LEFT JOIN v_chunk_symbols AS sym ON sym.chunk_id = c.id")
        if opts.join_faiss:
            joins.append("LEFT JOIN faiss_idmap AS fid ON fid.external_id = c.id")
        if opts.join_ast:
            joins.append(
                "LEFT JOIN ast_nodes AS ast "
                "ON ast.uri = c.uri "
                "AND ast.start_byte <= c.end_byte "
                "AND ast.end_byte >= c.start_byte"
            )
        if opts.join_cst:
            joins.append(
                "LEFT JOIN cst_nodes AS cst "
                "ON cst.uri = c.uri "
                "AND cst.start_byte <= c.end_byte "
                "AND cst.end_byte >= c.start_byte"
            )
        return joins

    @staticmethod
    def _build_where_clauses(
        *,
        params: dict[str, list[int] | list[str] | str],
        include_globs: Sequence[str],
        exclude_globs: Sequence[str],
        languages: Sequence[str],
    ) -> list[str]:
        """Build SQL WHERE clause conditions from filter options.

        Parameters
        ----------
        params : dict[str, list[int] | list[str] | str]
            Parameter dictionary to populate with filter values.
        include_globs : Sequence[str]
            Glob patterns for URIs to include.
        exclude_globs : Sequence[str]
            Glob patterns for URIs to exclude.
        languages : Sequence[str]
            Language codes to filter by.

        Returns
        -------
        list[str]
            List of WHERE clause condition strings.
        """
        clauses: list[str] = []
        if include_globs:
            include_clauses: list[str] = []
            for index, pattern in enumerate(include_globs):
                key = f"include_{index}"
                params[key] = DuckDBQueryBuilder._glob_to_like(pattern)
                include_clauses.append(f"c.uri LIKE ${key} ESCAPE '\\'")
            clauses.append(f"({' OR '.join(include_clauses)})")

        if exclude_globs:
            for index, pattern in enumerate(exclude_globs):
                key = f"exclude_{index}"
                params[key] = DuckDBQueryBuilder._glob_to_like(pattern)
                clauses.append(f"c.uri NOT LIKE ${key} ESCAPE '\\'")

        if languages:
            params["languages"] = [str(language) for language in languages]
            clauses.append("c.lang = ANY($languages)")

        return clauses

    @classmethod
    def _glob_to_like(cls, pattern: str) -> str:
        """Convert glob pattern to SQL LIKE pattern.

        Parameters
        ----------
        pattern : str
            Glob pattern to convert (supports **, *, ? wildcards).

        Returns
        -------
        str
            SQL LIKE pattern with wildcards converted and escaped.
        """
        normalized = pattern.replace("\\", "/")
        starts_with_recursive = normalized.startswith("**/")
        escaped = cls._escape_like_wildcards(normalized)
        escaped = escaped.replace("**", "%")
        escaped = escaped.replace("*", "%")
        escaped = escaped.replace("?", "_")

        if (
            starts_with_recursive
            and normalized[len("**/") :].startswith("*")
            and escaped.startswith("%/")
        ):
            escaped = escaped.replace("/%", "%", 1)
            escaped = "%" + escaped.lstrip("%")

        return escaped

    @staticmethod
    def _escape_like_wildcards(pattern: str) -> str:
        """Escape SQL LIKE wildcard characters in a pattern.

        Parameters
        ----------
        pattern : str
            Pattern string to escape.

        Returns
        -------
        str
            Pattern with backslashes, percent signs, and underscores escaped.
        """
        return pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
