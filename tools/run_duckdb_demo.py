# SPDX-License-Identifier: MIT
"""Execute the DuckDB AST demo queries and print representative results."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb


def main() -> int:
    """CLI entry point for the DuckDB AST demo.

    Returns
    -------
    int
        Process exit code (0 on success).
    """
    parser = argparse.ArgumentParser(description="Run DuckDB demo queries for AST artifacts.")
    parser.add_argument(
        "--sql",
        type=Path,
        default=Path("tools/demo_duckdb_ast.sql"),
        help="Path to the SQL script to execute.",
    )
    args = parser.parse_args()
    try:
        run_demo(args.sql)
    except ValueError as exc:
        _echo(str(exc))
        return 1
    return 0


def run_demo(sql_path: Path) -> None:
    """Execute statements from the SQL script and print query results.

    Extended Summary
    ----------------
    This function reads a SQL script file, splits it into executable statements,
    and executes each statement against a DuckDB connection. Query results are
    printed in a formatted table (up to 5 rows), while non-query statements
    (CREATE, INSERT, etc.) are executed silently. This is used for demonstrating
    DuckDB AST artifact queries in the kgfoundry documentation.

    Parameters
    ----------
    sql_path : Path
        Path to the SQL script file (typically ``tools/demo_duckdb_ast.sql``).
        Must be readable and contain valid SQL statements terminated by semicolons.

    Raises
    ------
    ValueError
        Raised when the script contains no executable SQL statements (empty file
        or only comments/whitespace).

    Notes
    -----
    Performance & Side Effects:
        Time complexity O(n*m) where n is the number of statements and m is the
        average statement size. Reads file from disk; executes SQL against DuckDB;
        writes formatted output to stdout. Not thread-safe (uses global DuckDB
        connection).

    See Also
    --------
    _split_sql_statements : SQL statement splitting logic
    _is_query : Query detection for result printing
    """
    sql_text = sql_path.read_text(encoding="utf-8")
    statements = list(_split_sql_statements(sql_text))
    if not statements:
        message = f"No executable statements found in {sql_path}"
        raise ValueError(message)
    with duckdb.connect() as con:
        for statement in statements:
            clean = statement.strip()
            _echo()
            _echo(f">> {clean.splitlines()[0][:96]}".rstrip())
            result = con.execute(clean)
            if _is_query(clean):
                _print_rows(result)


def _split_sql_statements(sql_text: str) -> list[str]:
    """Split a SQL script into executable statements.

    Parameters
    ----------
    sql_text : str
        Raw SQL script content containing one or more statements. Statements
        are terminated by semicolons. Empty lines and lines starting with ``--``
        (comments) are ignored.

    Returns
    -------
    list[str]
        Statements ready to execute with DuckDB, with trailing semicolons and
        whitespace removed. Returns empty list if sql_text contains no executable
        statements (only comments/whitespace).
    """
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).rstrip("; \n\t")
            statements.append(statement)
            buffer = []
    if buffer:
        statements.append("\n".join(buffer).rstrip("; \n\t"))
    return statements


def _is_query(statement: str) -> bool:
    """Return True when the statement produces rows.

    Parameters
    ----------
    statement : str
        SQL statement text (with leading whitespace stripped). The function
        checks if the statement starts with SELECT or WITH keywords (case-insensitive).

    Returns
    -------
    bool
        ``True`` when the SQL statement yields a result set (SELECT or WITH
        queries), ``False`` for DDL/DML statements (CREATE, INSERT, etc.).
    """
    lowered = statement.lstrip().lower()
    return lowered.startswith(("select", "with"))


def _print_rows(result: duckdb.DuckDBPyConnection) -> None:
    """Pretty-print up to five rows from the given DuckDB result."""
    rows = result.fetchall()
    columns = [desc[0] for desc in result.description]
    limit = min(len(rows), 5)
    if not rows:
        _echo("  (no rows)")
        return
    widths = [
        max(len(col), *(len(str(row[idx])) for row in rows[:limit]))
        for idx, col in enumerate(columns)
    ]
    header = " | ".join(col.ljust(widths[idx]) for idx, col in enumerate(columns))
    _echo(f"  {header}")
    _echo("  " + "-+-".join("-" * width for width in widths))
    for row in rows[:limit]:
        _echo("  " + " | ".join(str(row[idx]).ljust(widths[idx]) for idx in range(len(columns))))
    if len(rows) > limit:
        _echo(f"  ... ({len(rows) - limit} more rows)")


def _echo(message: str = "") -> None:
    """Write a single line to stdout.

    Parameters
    ----------
    message : str, optional
        Text to emit (default: empty string). A newline is appended automatically.
        Used for consistent output formatting in the demo script.

    Notes
    -----
    Performance & Side Effects:
        Time complexity O(1). Writes to stdout via sys.stdout.write. Thread-safe
        for concurrent writes (though demo script is single-threaded).
    """
    sys.stdout.write(f"{message}\n")


if __name__ == "__main__":
    raise SystemExit(main())
