"""Typed DuckDB helper utilities for parameterized queries and logging."""

# [nav:section public-api]

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

import duckdb

from kgfoundry_common.errors import RegistryError
from kgfoundry_common.logging import get_logger, with_fields
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.observability import MetricsProvider, observe_duration

if TYPE_CHECKING:
    from collections.abc import Iterable

    from duckdb import DuckDBPyConnection

Params = Sequence[object] | Mapping[str, object] | None

# [nav:anchor DEFAULT_TIMEOUT_S]
DEFAULT_TIMEOUT_S: Final[float] = 5.0
# [nav:anchor DEFAULT_SLOW_QUERY_THRESHOLD_S]
DEFAULT_SLOW_QUERY_THRESHOLD_S: Final[float] = 0.5
DEFAULT_THREADS: Final[int] = 4
MAX_SQL_PREVIEW_CHARS: Final[int] = 160


@dataclass(slots=True, frozen=True)
# [nav:anchor DuckDBQueryOptions]
class DuckDBQueryOptions:
    """Configuration for DuckDB query execution helpers."""

    timeout_s: float = DEFAULT_TIMEOUT_S
    slow_query_threshold_s: float = DEFAULT_SLOW_QUERY_THRESHOLD_S
    operation: str = "duckdb.execute"
    require_parameterized: bool | None = None


__all__ = [
    "DEFAULT_SLOW_QUERY_THRESHOLD_S",
    "DEFAULT_TIMEOUT_S",
    "DuckDBQueryOptions",
    "connect",
    "execute",
    "fetch_all",
    "fetch_one",
    "validate_identifier",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))

logger = get_logger(__name__)
metrics = MetricsProvider.default()


# [nav:anchor connect]
def connect(
    db_path: Path | str,
    *,
    read_only: bool = False,
    pragmas: Mapping[str, object] | None = None,
) -> DuckDBPyConnection:
    """Create a DuckDB connection with standard pragmas applied.

    Parameters
    ----------
    db_path : Path | str
        Path to DuckDB database file.
    read_only : bool, optional
        Whether to open in read-only mode. Defaults to False.
    pragmas : Mapping[str, object] | None, optional
        Additional pragma settings.

    Returns
    -------
    DuckDBPyConnection
        Configured DuckDB connection.
    """
    database_path = Path(db_path)
    if not read_only:
        database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(database_path), read_only=read_only)
    effective_pragmas: dict[str, object] = {"threads": DEFAULT_THREADS}
    if pragmas:
        effective_pragmas.update({key.lower(): value for key, value in pragmas.items()})
    for pragma_key, value in effective_pragmas.items():
        if isinstance(value, bool):
            literal = "true" if value else "false"
        elif isinstance(value, (int, float)):
            literal = str(value)
        else:
            literal = f"'{value}'"
        conn.execute(f"PRAGMA {pragma_key}={literal}")
    return conn


def _format_sql(sql: str) -> str:
    """Format SQL query for logging preview.

    Compacts whitespace and truncates long SQL queries to MAX_SQL_PREVIEW_CHARS
    for safe logging. Used internally to prevent logging sensitive data or
    overwhelming logs with very long queries.

    Parameters
    ----------
    sql : str
        SQL query string to format.

    Returns
    -------
    str
        Compacted SQL string, truncated with ellipsis if longer than
        MAX_SQL_PREVIEW_CHARS.
    """
    compact = " ".join(sql.split())
    if len(compact) <= MAX_SQL_PREVIEW_CHARS:
        return compact
    return f"{compact[:MAX_SQL_PREVIEW_CHARS]}…"


def _truncate_value(value: object) -> object:
    """Truncate string values for logging preview.

    Truncates string values longer than MAX_SQL_PREVIEW_CHARS to prevent
    logging sensitive data or overwhelming logs. Other types are returned
    unchanged.

    Parameters
    ----------
    value : object
        Value to truncate (if string).

    Returns
    -------
    object
        Truncated string with ellipsis if longer than MAX_SQL_PREVIEW_CHARS,
        or original value if not a string.
    """
    if isinstance(value, str) and len(value) > MAX_SQL_PREVIEW_CHARS:
        return value[:MAX_SQL_PREVIEW_CHARS] + "…"
    return value


def _format_params(params: Params) -> object:
    """Format query parameters for logging preview.

    Formats query parameters for safe logging by truncating string values.
    Returns a dict for named parameters or a list for positional parameters.

    Parameters
    ----------
    params : Params
        Query parameters (Sequence for positional, Mapping for named, or None).

    Returns
    -------
    object
        Formatted parameters: dict for named params, list for positional params,
        or empty dict if params is None.
    """
    if params is None:
        return {}
    if isinstance(params, Mapping):
        return {str(key): _truncate_value(value) for key, value in params.items()}
    return [_truncate_value(value) for value in params]


def _ensure_parameterized(sql: str, *, require_parameterized: bool) -> None:
    """Ensure SQL query uses parameterized placeholders.

    Validates that SQL queries use parameterized placeholders (?, :name, or $n)
    when required. Raises RegistryError if parameterization is required but
    missing, preventing SQL injection vulnerabilities.

    Parameters
    ----------
    sql : str
        SQL query string to validate.
    require_parameterized : bool
        Whether to require parameterization. If True, query must contain
        parameter placeholders (?, :name, or $n).

    Raises
    ------
    RegistryError
        If require_parameterized is True but query contains no parameter
        placeholders.
    """
    if not require_parameterized:
        return
    if "?" in sql or ":" in sql or "$" in sql:
        return
    error_message = "DuckDB query must be parameterized"
    raise RegistryError(
        error_message,
        context={"sql_preview": _format_sql(sql)},
    )


def _set_timeout(conn: DuckDBPyConnection, timeout_s: float) -> None:
    """Set statement timeout for DuckDB connection.

    Configures the statement_timeout pragma on the connection to limit query
    execution time. Timeout is set in milliseconds. If timeout_s is <= 0,
    no timeout is set.

    Parameters
    ----------
    conn : DuckDBPyConnection
        DuckDB connection to configure.
    timeout_s : float
        Timeout in seconds. Must be positive to set a timeout.
    """
    if timeout_s <= 0:
        return
    timeout_ms = int(timeout_s * 1000)
    conn.execute(f"PRAGMA statement_timeout='{timeout_ms}ms'")


def _coerce_options(
    options: DuckDBQueryOptions | None,
    *,
    operation: str,
) -> DuckDBQueryOptions:
    if options is None:
        return DuckDBQueryOptions(operation=operation)
    if options.operation == operation:
        return options
    return replace(options, operation=operation)


# [nav:anchor execute]
def execute(
    conn: DuckDBPyConnection,
    sql: str,
    params: Params = None,
    *,
    options: DuckDBQueryOptions | None = None,
) -> DuckDBPyConnection:
    """Execute a DuckDB query with parameter binding, logging, and metrics.

    Executes a SQL query with optional parameter binding, structured logging,
    performance metrics, and timeout enforcement. Validates parameterization
    when required and logs slow queries.

    Parameters
    ----------
    conn : DuckDBPyConnection
        DuckDB connection to execute query on.
    sql : str
        SQL query string. Must use parameterized placeholders (?, :name, or $n)
        if params is provided or require_parameterized is True.
    params : Params, optional
        Query parameters (Sequence for positional, Mapping for named).
        Defaults to None.
    options : DuckDBQueryOptions | None, optional
        Query execution options including timeout, logging metadata, and
        parameter enforcement. Defaults to None (uses module defaults).

    Returns
    -------
    DuckDBPyConnection
        Connection with query result relation (use .fetchall() or .fetchone()
        to retrieve rows).

    Raises
    ------
    RegistryError
        If query execution fails, parameterization is required but missing,
        or timeout is exceeded.
    RuntimeError
        Raised if query execution completes without returning a relation.
    """
    opts = _coerce_options(options, operation="duckdb.execute")
    require_flag = (
        params is not None if opts.require_parameterized is None else opts.require_parameterized
    )
    _ensure_parameterized(sql, require_parameterized=require_flag)

    sql_preview = _format_sql(sql)
    query_params = _format_params(params)

    with (
        with_fields(
            logger,
            component="registry",
            operation=opts.operation,
            sql_preview=sql_preview,
        ) as log,
        observe_duration(metrics, opts.operation, component="registry") as observer,
    ):
        start = time.perf_counter()
        try:
            _set_timeout(conn, opts.timeout_s)
            relation = conn.execute(sql) if params is None else conn.execute(sql, params)
        except duckdb.Error as exc:
            observer.error()
            log.exception(
                "DuckDB query failed",
                extra={"params": query_params},
            )
            error_message = "DuckDB query failed"
            raise RegistryError(
                error_message,
                cause=exc,
                context={"sql_preview": sql_preview, "params": query_params},
            ) from exc
        else:
            observer.success()
            duration = time.perf_counter() - start
            if duration >= opts.slow_query_threshold_s:
                log.warning(
                    "Slow DuckDB query",
                    extra={
                        "duration_ms": round(duration * 1000, 2),
                        "params": query_params,
                    },
                )
            else:
                log.debug(
                    "DuckDB query executed",
                    extra={"duration_ms": round(duration * 1000, 2)},
                )
            return relation
    message = "DuckDB query execution completed without returning a relation"
    raise RuntimeError(message)


# [nav:anchor fetch_all]
def fetch_all(
    conn: DuckDBPyConnection,
    sql: str,
    params: Params = None,
    *,
    options: DuckDBQueryOptions | None = None,
) -> list[tuple[object, ...]]:
    """Execute a query and return all rows as a list of tuples.

    Executes a SQL query and returns all result rows as a list of tuples.
    Uses execute() internally for logging and metrics.

    Parameters
    ----------
    conn : DuckDBPyConnection
        DuckDB connection to execute query on.
    sql : str
        SQL query string. Must use parameterized placeholders if params provided.
    params : Params, optional
        Query parameters (Sequence for positional, Mapping for named).
        Defaults to None.
    options : DuckDBQueryOptions | None, optional
        Query execution options forwarded to :func:`execute`.
        Defaults to None.

    Returns
    -------
    list[tuple[object, ...]]
        List of result rows, each row as a tuple of column values.
    """
    relation = execute(
        conn,
        sql,
        params,
        options=_coerce_options(options, operation="duckdb.fetch_all"),
    )
    raw_rows = cast("list[tuple[object, ...]]", relation.fetchall())
    typed_rows: list[tuple[object, ...]] = [tuple(row) for row in raw_rows]
    return typed_rows


# [nav:anchor fetch_one]
def fetch_one(
    conn: DuckDBPyConnection,
    sql: str,
    params: Params = None,
    *,
    options: DuckDBQueryOptions | None = None,
) -> tuple[object, ...] | None:
    """Execute a query and return the first row or None.

    Executes a SQL query and returns the first result row as a tuple, or None
    if no rows are returned. Uses execute() internally for logging and metrics.

    Parameters
    ----------
    conn : DuckDBPyConnection
        DuckDB connection to execute query on.
    sql : str
        SQL query string. Must use parameterized placeholders if params provided.
    params : Params, optional
        Query parameters (Sequence for positional, Mapping for named).
        Defaults to None.
    options : DuckDBQueryOptions | None, optional
        Query execution options forwarded to :func:`execute`.
        Defaults to None.

    Returns
    -------
    tuple[object, ...] | None
        First result row as a tuple of column values, or None if no rows.
    """
    relation = execute(
        conn,
        sql,
        params,
        options=_coerce_options(options, operation="duckdb.fetch_one"),
    )
    raw_row = cast("tuple[object, ...] | None", relation.fetchone())
    if raw_row is None:
        return None
    return tuple(raw_row)


# [nav:anchor validate_identifier]
def validate_identifier(
    identifier: str,
    allowed: Iterable[str],
    *,
    label: str = "identifier",
) -> str:
    """Validate that an identifier is within an allowed set.

    Validates that an identifier string is present in the allowed set of values.
    Used for sanitizing table names, column names, or other database identifiers
    to prevent SQL injection.

    Parameters
    ----------
    identifier : str
        Identifier string to validate.
    allowed : Iterable[str]
        Set of allowed identifier values.
    label : str, optional
        Human-readable label for error messages (e.g., "table name", "column name").
        Defaults to "identifier".

    Returns
    -------
    str
        The validated identifier (unchanged).

    Raises
    ------
    RegistryError
        If identifier is not in the allowed set. Error context includes the
        invalid identifier and sorted list of allowed values.
    """
    allowed_set = set(allowed)
    if identifier in allowed_set:
        return identifier
    error_message = f"Invalid {label}: {identifier}"
    raise RegistryError(
        error_message,
        context={label: identifier, "allowed": sorted(allowed_set)},
    )
