"""Unit tests for the new DuckDB schema helpers."""

from pathlib import Path

import duckdb
import pytest
from codeintel_rev.io.duckdb_schema import (
    VIEW_CHUNKS,
    sql_create_chunks_materialized,
    sql_create_empty_chunks_view,
    sql_relation_exists,
)

from tests._helpers import assertions


def _write_parquet(path: Path, select_sql: str) -> None:
    conn = duckdb.connect(database=":memory:")
    try:
        conn.execute("DROP TABLE IF EXISTS tmp")
        relation = conn.sql(select_sql)
        relation.create("tmp")
        conn.execute("COPY tmp TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        conn.close()


def test_empty_chunks_view_creates_relation() -> None:
    """Verify that sql_create_empty_chunks_view creates a view relation."""
    conn = duckdb.connect(database=":memory:")
    try:
        conn.execute(sql_create_empty_chunks_view())
        row = conn.execute(sql_relation_exists(), [VIEW_CHUNKS]).fetchone()
        if row is None:
            pytest.fail("Expected sql_relation_exists to return a row for chunks view")
        assertions.expect_equal(row[0], 1)
    finally:
        conn.close()


def test_chunks_materialized_sql_executes(tmp_path: Path) -> None:
    """Verify that sql_create_chunks_materialized creates materialized table from Parquet."""
    parquet = tmp_path / "chunks.parquet"
    _write_parquet(
        parquet,
        """
        SELECT
            1::BIGINT AS id,
            'file.py'::VARCHAR AS uri,
            0::INTEGER AS start_line,
            1::INTEGER AS end_line,
            0::BIGINT AS start_byte,
            10::BIGINT AS end_byte,
            'python'::VARCHAR AS lang,
            ['symbol']::VARCHAR[] AS symbols,
            [0.1, 0.2]::FLOAT[] AS embedding
        """,
    )
    conn = duckdb.connect(database=":memory:")
    try:
        conn.execute(sql_create_chunks_materialized(), [str(parquet)])
        result = conn.execute("SELECT COUNT(*) FROM chunks_materialized").fetchone()
        if result is None:
            pytest.fail("Expected chunks_materialized count query to return a row")
        assertions.expect_equal(result[0], 1)
    finally:
        conn.close()


def test_relation_exists_with_missing_relation() -> None:
    """Verify that sql_relation_exists returns None for non-existent relations."""
    conn = duckdb.connect(database=":memory:")
    try:
        row = conn.execute(sql_relation_exists(), ["missing"]).fetchone()
        assertions.expect_true(row is None)
    finally:
        conn.close()
