"""Tests for DuckDB catalog helpers."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, relation_exists


def test_relation_exists_detects_tables() -> None:
    """Tables reported by information_schema are considered relations."""
    conn = duckdb.connect(":memory:")
    try:
        conn.execute("CREATE TABLE foo(id INTEGER)")
        assert relation_exists(conn, "foo")
    finally:
        conn.close()


def test_relation_exists_detects_views() -> None:
    """Views are also treated as relations and return True."""
    conn = duckdb.connect(":memory:")
    try:
        conn.execute("CREATE TABLE foo(id INTEGER)")
        conn.execute("CREATE VIEW foo_view AS SELECT * FROM foo")
        assert relation_exists(conn, "foo_view")
    finally:
        conn.close()


def test_relation_exists_returns_false_for_missing_relation() -> None:
    """Missing relations return False."""
    conn = duckdb.connect(":memory:")
    try:
        assert not relation_exists(conn, "does_not_exist")
    finally:
        conn.close()


def _write_idmap(path: Path, size: int) -> None:
    rows = pa.array(range(size), type=pa.int64())
    externals = pa.array(range(10_000, 10_000 + size), type=pa.int64())
    sources = pa.array(["primary"] * size, type=pa.string())
    pq.write_table(
        pa.table(
            [rows, externals, sources],
            names=["faiss_row", "external_id", "source"],
        ),
        path,
    )


def test_refresh_idmap_guard(tmp_path: Path) -> None:
    """Refreshing the ID map only rewrites when the Parquet payload changes."""
    db_path = tmp_path / "catalog.duckdb"
    vector_dir = tmp_path / "vectors"
    vector_dir.mkdir()
    catalog = DuckDBCatalog(db_path=db_path, vectors_dir=vector_dir)
    idmap = tmp_path / "faiss_idmap.parquet"
    _write_idmap(idmap, 3)

    first = catalog.refresh_faiss_idmap_mat_if_changed(idmap)
    assert first["refreshed"] is True
    assert first["rows"] == 3

    second = catalog.refresh_faiss_idmap_mat_if_changed(idmap)
    assert second["refreshed"] is False
    assert second["rows"] == 3

    _write_idmap(idmap, 4)
    third = catalog.refresh_faiss_idmap_mat_if_changed(idmap)
    assert third["refreshed"] is True
    assert third["rows"] == 4
