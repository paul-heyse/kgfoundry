# ruff: noqa: D103,S101
"""Tests covering the DuckDB DAO helpers."""

import hashlib
from pathlib import Path

import duckdb
from codeintel_rev.io.duckdb_dao import (
    DuckDBQueryBuilder,
    DuckDBQueryOptions,
    ensure_chunks,
    ensure_faiss_idmap_view,
    ensure_v_faiss_join,
    materialize_v_faiss_join,
    refresh_faiss_idmap_materialized,
    relation_exists,
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


def _parquet_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_ensure_chunks_creates_view(tmp_path: Path) -> None:
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
            [0.1, 0.2]::FLOAT[] AS embedding
        """,
    )
    conn = duckdb.connect(database=":memory:")
    try:
        ensure_chunks(
            conn,
            parquet_glob=str(parquet),
            materialize=False,
            parquet_exists=True,
        )
        assert relation_exists(conn, "chunks")
    finally:
        conn.close()


def test_ensure_faiss_idmap_view_falls_back() -> None:
    conn = duckdb.connect(database=":memory:")
    try:
        ensure_faiss_idmap_view(conn, idmap_parquet=None)
        assert relation_exists(conn, "faiss_idmap")
    finally:
        conn.close()


def test_materialize_and_refresh(tmp_path: Path) -> None:
    conn = duckdb.connect(database=":memory:")
    chunk_path = tmp_path / "chunks.parquet"
    idmap_path = tmp_path / "idmap.parquet"

    _write_parquet(
        chunk_path,
        """
        SELECT
            1::BIGINT AS id,
            'file.py'::VARCHAR AS uri,
            [0.1, 0.2]::FLOAT[] AS embedding
        """,
    )
    _write_parquet(
        idmap_path,
        """
        SELECT
            1::BIGINT AS faiss_row,
            1::BIGINT AS external_id
        """,
    )

    try:
        ensure_chunks(
            conn,
            parquet_glob=str(chunk_path),
            materialize=True,
            parquet_exists=True,
        )
        ensure_faiss_idmap_view(conn, idmap_parquet=idmap_path)
        ensure_v_faiss_join(conn)
        checksum = _parquet_checksum(idmap_path)
        meta = refresh_faiss_idmap_materialized(
            conn,
            idmap_parquet=idmap_path,
            checksum=checksum,
        )
        assert meta.rows == 1
        assert meta.refreshed

        second = refresh_faiss_idmap_materialized(
            conn,
            idmap_parquet=idmap_path,
            checksum=checksum,
        )
        assert not second.refreshed

        rows = materialize_v_faiss_join(conn)
        assert rows == 1
    finally:
        conn.close()


def test_query_builder_options() -> None:
    builder = DuckDBQueryBuilder()
    options = DuckDBQueryOptions(
        include_globs=["src/**"],
        languages=["python"],
        preserve_order=True,
    )
    sql, params = builder.build_filter_query(chunk_ids=[1], options=options)
    assert "ORDER BY ids.position" in sql
    assert params["ids"] == [1]
