"""Helper utilities for DuckDB catalog tests."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import duckdb


def safe_sql_path(path: Path, base_path: Path) -> str:
    """Return a DuckDB-safe string literal for a parquet path within base_path.

    Parameters
    ----------
    path : Path
        Parquet path to validate.
    base_path : Path
        Base directory within which the path must reside.

    Returns
    -------
    str
        Escaped path string safe for use in SQL string literals.

    Raises
    ------
    ValueError
        If the path is outside the provided base directory.
    """
    validated = path.resolve()
    base_resolved = base_path.resolve()
    if not str(validated).startswith(str(base_resolved)):
        msg = f"Path {validated} is outside base directory {base_resolved}"
        raise ValueError(msg)
    return str(validated).replace("'", "''")


def write_chunks_parquet(path: Path) -> None:
    """Write a small chunks parquet file for catalog tests."""
    connection = duckdb.connect(database=":memory:")
    connection.execute("CREATE TABLE tmp (id INTEGER, uri VARCHAR, text VARCHAR)")
    connection.executemany(
        "INSERT INTO tmp VALUES (?, ?, ?)",
        [
            (2, "example.py", "second"),
            (1, "example.py", "first"),
            (3, "other.py", "other"),
        ],
    )
    connection.execute("COPY tmp TO ? (FORMAT PARQUET)", [str(path)])
    connection.close()


def write_idmap_parquet(path: Path) -> None:
    """Write a minimal FAISS idmap parquet file."""
    connection = duckdb.connect(database=":memory:")
    connection.execute("CREATE TABLE tmp (faiss_row BIGINT, external_id BIGINT, source TEXT)")
    connection.executemany(
        "INSERT INTO tmp VALUES (?, ?, ?)",
        [
            (0, 1, "primary"),
            (1, 2, "primary"),
        ],
    )
    connection.execute("COPY tmp TO ? (FORMAT PARQUET)", [str(path)])
    connection.close()


def write_single_row_parquet(path: Path, select_sql: str) -> None:
    """Materialize a single-row parquet file from a SELECT statement."""
    connection = duckdb.connect(database=":memory:")
    try:
        relation = connection.sql(select_sql)
        relation.create("tmp")
        connection.execute("COPY tmp TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        connection.close()


def seed_chunks_table(connection: duckdb.DuckDBPyConnection, rows: Iterable[tuple]) -> None:
    """Create a chunks table with the provided rows."""
    connection.execute(
        """
        CREATE TABLE chunks (
            id BIGINT,
            uri VARCHAR,
            start_line INTEGER,
            end_line INTEGER,
            start_byte BIGINT,
            end_byte BIGINT,
            preview VARCHAR,
            embedding FLOAT[]
        )
        """
    )
    connection.executemany(
        "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        list(rows),
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_uri ON chunks(uri)")


def default_chunk_rows() -> list[tuple]:
    """Return a standard set of chunk rows used across catalog tests."""
    return [
        (
            1,
            "src/main.py",
            1,
            10,
            0,
            100,
            "def main():",
            [0.1, 0.2],
        ),
        (
            2,
            "src/utils.py",
            5,
            15,
            50,
            150,
            "def helper():",
            [0.3, 0.4],
        ),
        (
            3,
            "tests/test_main.py",
            1,
            5,
            0,
            50,
            "def test_main():",
            [0.5, 0.6],
        ),
        (
            4,
            "tests/test_utils.py",
            1,
            5,
            0,
            50,
            "def test_helper():",
            [0.7, 0.8],
        ),
        (
            5,
            "src/app.ts",
            1,
            20,
            0,
            200,
            "function app() {",
            [0.9, 1.0],
        ),
        (
            6,
            "src/components/Button.tsx",
            1,
            30,
            0,
            300,
            "export const Button",
            [1.1, 1.2],
        ),
        (
            7,
            "docs/README.md",
            1,
            50,
            0,
            500,
            "# Documentation",
            [1.3, 1.4],
        ),
        (
            8,
            "src/nested/deep/file.py",
            1,
            5,
            0,
            50,
            "deep code",
            [1.5, 1.6],
        ),
        (
            9,
            "lib/legacy.py",
            1,
            10,
            0,
            100,
            "old code",
            [1.7, 1.8],
        ),
        (
            10,
            "src/config.json",
            1,
            5,
            0,
            50,
            '{"key": "value"}',
            [1.9, 2.0],
        ),
        (
            11,
            "main.py",
            1,
            20,
            0,
            200,
            "def entry():",
            [2.1, 2.2],
        ),
    ]


def table_exists(db_path: Path, table_name: str) -> bool:
    """Return True if a table exists in the DuckDB database.

    Parameters
    ----------
    db_path : Path
        Database path.
    table_name : str
        Table name to check.

    Returns
    -------
    bool
        True when the table exists.
    """
    connection = duckdb.connect(str(db_path))
    try:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'main'
              AND table_name = ?
            """,
            [table_name],
        ).fetchone()
        return bool(row and row[0])
    finally:
        connection.close()


def index_exists(db_path: Path, table_name: str, index_name: str) -> bool:
    """Return True if an index exists on the table in the DuckDB database.

    Parameters
    ----------
    db_path : Path
        Database path.
    table_name : str
        Table owning the index.
    index_name : str
        Index name to check.

    Returns
    -------
    bool
        True when the index exists.
    """
    connection = duckdb.connect(str(db_path))
    try:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM duckdb_indexes
            WHERE table_name = ?
              AND index_name = ?
            """,
            [table_name, index_name],
        ).fetchone()
        return bool(row and row[0])
    finally:
        connection.close()
