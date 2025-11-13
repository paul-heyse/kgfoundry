"""Unit tests for :mod:`codeintel_rev.io.duckdb_catalog`."""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog


def _safe_sql_path(path: Path, base_path: Path) -> str:
    """Safely construct SQL path literal for DuckDB read_parquet().

    Validates that the path is within the base directory to prevent path traversal,
    then escapes single quotes for safe use in SQL string literals.

    Parameters
    ----------
    path : Path
        Path to validate and escape.
    base_path : Path
        Base directory that path must be within.

    Returns
    -------
    str
        Escaped path string safe for use in SQL string literal.

    Raises
    ------
    ValueError
        If path is outside base_path directory.
    """
    validated = path.resolve()
    base_resolved = base_path.resolve()
    if not str(validated).startswith(str(base_resolved)):
        msg = f"Path {validated} is outside base directory {base_resolved}"
        raise ValueError(msg)
    # Escape single quotes for SQL string literal
    return str(validated).replace("'", "''")


def _write_chunks_parquet(path: Path) -> None:
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


def _table_exists(db_path: Path, table_name: str) -> bool:
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
        count = row[0] if row else 0
        return count > 0
    finally:
        connection.close()


def _index_exists(db_path: Path, index_name: str) -> bool:
    connection = duckdb.connect(str(db_path))
    try:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM duckdb_indexes
            WHERE table_name = ?
              AND index_name = ?
            """,
            ["chunks_materialized", index_name],
        ).fetchone()
        count = row[0] if row else 0
        return count > 0
    finally:
        connection.close()


def test_query_by_uri_supports_unlimited_results(tmp_path) -> None:
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    parquet_path = vectors_dir / "chunks.parquet"
    _write_chunks_parquet(parquet_path)

    db_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(db_path, vectors_dir)
    # DuckDB's read_parquet() requires a string literal, not a parameter
    # Path is validated and escaped via helper function to prevent SQL injection
    safe_path = _safe_sql_path(parquet_path, tmp_path)
    with duckdb.connect(str(db_path)) as connection:
        connection.execute(
            f"CREATE OR REPLACE VIEW chunks AS SELECT * FROM read_parquet('{safe_path}')"
        )

    limited = catalog.query_by_uri("example.py", limit=1)
    unlimited_zero = catalog.query_by_uri("example.py", limit=0)
    unlimited_negative = catalog.query_by_uri("example.py", limit=-1)

    catalog.close()

    assert [row["id"] for row in limited] == [1]
    assert [row["id"] for row in unlimited_zero] == [1, 2]
    assert unlimited_zero == unlimited_negative


def test_get_embeddings_by_ids_skips_null_embeddings(tmp_path: Path) -> None:
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    with duckdb.connect(str(catalog_path)) as connection:
        connection.execute(
            """
            CREATE OR REPLACE VIEW chunks AS
            SELECT * FROM (
                SELECT 1::BIGINT AS id, [0.1, 0.2]::FLOAT[] AS embedding
                UNION ALL
                SELECT 2::BIGINT AS id, NULL::FLOAT[] AS embedding
            )
            """
        )

    ids, results = catalog.get_embeddings_by_ids([1, 2])
    assert ids == [1]
    assert results.shape == (1, 2)
    assert np.allclose(results[0], [0.1, 0.2])


def test_query_by_filters_handles_literal_percent(tmp_path: Path) -> None:
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    with duckdb.connect(str(catalog_path)) as connection:
        connection.execute(
            """
            CREATE OR REPLACE VIEW chunks AS
            SELECT * FROM (
                SELECT
                    1::BIGINT AS id,
                    'src/config%file.py'::VARCHAR AS uri,
                    0::INTEGER AS start_line,
                    1::INTEGER AS end_line,
                    0::BIGINT AS start_byte,
                    10::BIGINT AS end_byte,
                    'percent file'::VARCHAR AS preview,
                    [0.1, 0.2]::FLOAT[] AS embedding
            )
            """
        )

    results = catalog.query_by_filters([1], include_globs=["src/config%file.py"])
    assert len(results) == 1
    assert results[0]["uri"] == "src/config%file.py"


def test_query_by_filters_handles_literal_underscore(tmp_path: Path) -> None:
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    with duckdb.connect(str(catalog_path)) as connection:
        connection.execute(
            """
            CREATE OR REPLACE VIEW chunks AS
            SELECT * FROM (
                SELECT
                    1::BIGINT AS id,
                    'src/config_file.py'::VARCHAR AS uri,
                    0::INTEGER AS start_line,
                    1::INTEGER AS end_line,
                    0::BIGINT AS start_byte,
                    10::BIGINT AS end_byte,
                    'underscore file'::VARCHAR AS preview,
                    [0.1, 0.2]::FLOAT[] AS embedding
            )
            """
        )

    results = catalog.query_by_filters([1], include_globs=["src/config_file.py"])
    assert len(results) == 1
    assert results[0]["uri"] == "src/config_file.py"


def test_open_materialize_creates_table_and_index(tmp_path: Path) -> None:
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    parquet_path = vectors_dir / "chunks.parquet"
    _write_chunks_parquet(parquet_path)

    catalog_path = tmp_path / "catalog.duckdb"
    with DuckDBCatalog(catalog_path, vectors_dir, materialize=True) as catalog:
        assert catalog.count_chunks() == 3

    assert _table_exists(catalog_path, "chunks_materialized") is True
    assert _index_exists(catalog_path, "idx_chunks_materialized_uri") is True

    connection = duckdb.connect(str(catalog_path))
    try:
        row = connection.execute("SELECT COUNT(*) FROM chunks_materialized").fetchone()
    finally:
        connection.close()

    row_count = row[0] if row else 0
    assert row_count == 3


def test_materialize_creates_empty_table_when_parquet_missing(tmp_path: Path) -> None:
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog_path = tmp_path / "catalog.duckdb"
    with DuckDBCatalog(catalog_path, vectors_dir, materialize=True) as catalog:
        assert catalog.count_chunks() == 0

    assert _table_exists(catalog_path, "chunks_materialized") is True
    assert _index_exists(catalog_path, "idx_chunks_materialized_uri") is True
