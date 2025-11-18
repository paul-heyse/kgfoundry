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


def _parquet_checksum(path: Path) -> str:
    """Compute SHA256 checksum of a Parquet file.

    Parameters
    ----------
    path : Path
        Path to the Parquet file.

    Returns
    -------
    str
        Hexadecimal SHA256 checksum string.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_ensure_chunks_creates_view(tmp_path: Path) -> None:
    """Verify that ensure_chunks creates a view when materialize is False."""
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
        assertions.expect_true(relation_exists(conn, "chunks"))
    finally:
        conn.close()


def test_ensure_faiss_idmap_view_falls_back() -> None:
    """Verify that ensure_faiss_idmap_view creates empty view when idmap_parquet is None."""
    conn = duckdb.connect(database=":memory:")
    try:
        ensure_faiss_idmap_view(conn, idmap_parquet=None)
        assertions.expect_true(relation_exists(conn, "faiss_idmap"))
    finally:
        conn.close()


def test_materialize_and_refresh(tmp_path: Path) -> None:
    """Verify materialization and refresh logic for chunks and ID map views."""
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
        assertions.expect_equal(meta.rows, 1)
        assertions.expect_true(meta.refreshed)

        second = refresh_faiss_idmap_materialized(
            conn,
            idmap_parquet=idmap_path,
            checksum=checksum,
        )
        assertions.expect_false(second.refreshed)

        rows = materialize_v_faiss_join(conn)
        assertions.expect_equal(rows, 1)
    finally:
        conn.close()


def test_query_builder_options() -> None:
    """Verify that DuckDBQueryBuilder respects DuckDBQueryOptions filters."""
    builder = DuckDBQueryBuilder()
    options = DuckDBQueryOptions(
        include_globs=["src/**"],
        languages=["python"],
        preserve_order=True,
    )
    sql, params = builder.build_filter_query(chunk_ids=[1], options=options)
    assertions.expect_in("ORDER BY ids.position", sql)
    assertions.expect_equal(params["ids"], [1])
