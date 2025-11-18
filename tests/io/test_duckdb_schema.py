# ruff: noqa: D103,S101
"""Unit tests for the new DuckDB schema helpers."""

from pathlib import Path

import duckdb
from codeintel_rev.io.duckdb_schema import (
    VIEW_CHUNKS,
    sql_create_chunks_materialized,
    sql_create_empty_chunks_view,
    sql_relation_exists,
)


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
    conn = duckdb.connect(database=":memory:")
    try:
        conn.execute(sql_create_empty_chunks_view())
        row = conn.execute(sql_relation_exists(), [VIEW_CHUNKS]).fetchone()
        assert row is not None
        assert row[0] == 1
    finally:
        conn.close()


def test_chunks_materialized_sql_executes(tmp_path: Path) -> None:
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
        assert result is not None
        assert result[0] == 1
    finally:
        conn.close()


def test_relation_exists_with_missing_relation() -> None:
    conn = duckdb.connect(database=":memory:")
    try:
        row = conn.execute(sql_relation_exists(), ["missing"]).fetchone()
        assert row is None
    finally:
        conn.close()
