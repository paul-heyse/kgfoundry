# ruff: noqa: D103,S101
"""Tests covering the DuckDB catalog refactor."""

from pathlib import Path

import duckdb
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, DuckDBCatalogOptions


def _write_parquet(path: Path, select_sql: str) -> None:
    conn = duckdb.connect(database=":memory:")
    try:
        conn.execute("DROP TABLE IF EXISTS tmp")
        relation = conn.sql(select_sql)
        relation.create("tmp")
        conn.execute("COPY tmp TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        conn.close()


def _write_chunk_parquet(path: Path) -> None:
    _write_parquet(
        path,
        """
        SELECT
            1::BIGINT AS id,
            'src/main.py'::VARCHAR AS uri,
            0::INTEGER AS start_line,
            1::INTEGER AS end_line,
            0::BIGINT AS start_byte,
            12::BIGINT AS end_byte,
            'preview'::VARCHAR AS preview,
            'content'::VARCHAR AS content,
            'python'::VARCHAR AS lang,
            [0.1, 0.2]::FLOAT[] AS embedding
        """,
    )


def _write_idmap_parquet(path: Path) -> None:
    _write_parquet(
        path,
        """
        SELECT
            0::BIGINT AS faiss_row,
            1::BIGINT AS external_id
        """,
    )


def _build_catalog(tmp_path: Path) -> tuple[DuckDBCatalog, Path]:
    data_root = tmp_path / "data"
    vectors_dir = data_root / "vectors"
    vectors_dir.mkdir(parents=True)
    chunk_parquet = vectors_dir / "chunks.parquet"
    _write_chunk_parquet(chunk_parquet)
    db_path = tmp_path / "catalog.duckdb"
    options = DuckDBCatalogOptions()
    catalog = DuckDBCatalog(db_path, vectors_dir, options=options)
    idmap_parquet = tmp_path / "faiss_idmap.parquet"
    _write_idmap_parquet(idmap_parquet)
    return catalog, idmap_parquet


def test_register_idmap_creates_views(tmp_path: Path) -> None:
    catalog, idmap_parquet = _build_catalog(tmp_path)
    stats = catalog.register_idmap_parquet(idmap_parquet, materialize=False)
    assert stats["rows"] == 1
    assert stats["refreshed"] is True

    with catalog.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM faiss_idmap").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM v_faiss_join").fetchone()[0] == 1


def test_register_idmap_materializes_join(tmp_path: Path) -> None:
    catalog, idmap_parquet = _build_catalog(tmp_path)
    first = catalog.register_idmap_parquet(idmap_parquet, materialize=True)
    assert first["rows"] == 1
    assert first["refreshed"] is True

    with catalog.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM faiss_join_mat").fetchone()[0] == 1

    second = catalog.register_idmap_parquet(idmap_parquet, materialize=True)
    assert second["rows"] == 1
    assert second["refreshed"] is False
