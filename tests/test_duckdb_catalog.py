"""Unit tests for :mod:`codeintel_rev.io.duckdb_catalog`."""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog


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


def test_query_by_uri_supports_unlimited_results(tmp_path) -> None:
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    parquet_path = vectors_dir / "chunks.parquet"
    _write_chunks_parquet(parquet_path)

    db_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(db_path, vectors_dir)
    catalog.conn = duckdb.connect(database=":memory:")
    # SQL injection warning suppressed: test code with controlled input from tmp_path
    # DuckDB doesn't support parameterized CREATE VIEW, so we use string formatting with sanitized input
    parquet_expr = str(parquet_path).replace("'", "''")
    catalog.conn.execute(
        f"CREATE OR REPLACE VIEW chunks AS SELECT * FROM read_parquet('{parquet_expr}')"  # noqa: S608
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
    catalog.conn = duckdb.connect(database=":memory:")
    catalog.conn.execute(
        """
        CREATE OR REPLACE VIEW chunks AS
        SELECT * FROM (
            SELECT 1::BIGINT AS id, [0.1, 0.2]::FLOAT[] AS embedding
            UNION ALL
            SELECT 2::BIGINT AS id, NULL::FLOAT[] AS embedding
        )
        """
    )

    results = catalog.get_embeddings_by_ids([1, 2])
    assert results.shape == (1, 2)
    assert np.allclose(results[0], [0.1, 0.2])


def test_query_by_filters_handles_literal_percent(tmp_path: Path) -> None:
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()

    catalog_path = tmp_path / "catalog.duckdb"
    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    catalog.conn = duckdb.connect(database=":memory:")
    catalog.conn.execute(
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
    catalog.conn = duckdb.connect(database=":memory:")
    catalog.conn.execute(
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
