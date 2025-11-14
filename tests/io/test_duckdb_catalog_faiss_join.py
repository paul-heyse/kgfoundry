from __future__ import annotations

from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from codeintel_rev.io.duckdb_catalog import (
    IdMapMeta,
    ensure_faiss_idmap_view,
    refresh_faiss_idmap_materialized,
)


def _write_chunks(path: Path) -> None:
    table = pa.table(
        {
            "id": pa.array([1, 2], pa.int64()),
            "uri": pa.array(["repo://a.py", "repo://b.py"]),
            "start_line": pa.array([0, 10], pa.int32()),
            "end_line": pa.array([4, 14], pa.int32()),
            "language": pa.array(["python", "python"]),
            "text": pa.array(["def foo():\n    return 1", "def bar():\n    return 2"]),
        }
    )
    pq.write_table(table, path)


def _write_idmap(path: Path) -> None:
    table = pa.table(
        {
            "faiss_row": pa.array([0, 1], pa.int64()),
            "external_id": pa.array([1, 2], pa.int64()),
        }
    )
    pq.write_table(table, path)


def test_ensure_faiss_idmap_view_registers_join(tmp_path: Path) -> None:
    chunks = tmp_path / "chunks.parquet"
    idmap = tmp_path / "faiss_idmap.parquet"
    _write_chunks(chunks)
    _write_idmap(idmap)
    conn = duckdb.connect(database=":memory:")
    ensure_faiss_idmap_view(
        conn,
        idmap_parquet=str(idmap),
        chunks_parquet=str(chunks),
    )
    count = conn.execute("SELECT COUNT(*) FROM v_faiss_join").fetchone()
    assert count is not None
    assert count[0] == 2


def test_refresh_faiss_idmap_materialized_skips_when_unchanged(tmp_path: Path) -> None:
    chunks = tmp_path / "chunks.parquet"
    idmap = tmp_path / "faiss_idmap.parquet"
    _write_chunks(chunks)
    _write_idmap(idmap)
    conn = duckdb.connect(database=str(tmp_path / "catalog.duckdb"))
    first: IdMapMeta = refresh_faiss_idmap_materialized(
        conn,
        idmap_parquet=str(idmap),
        chunks_parquet=str(chunks),
    )
    assert first.refreshed is True
    assert first.row_count == 2

    second = refresh_faiss_idmap_materialized(
        conn,
        idmap_parquet=str(idmap),
        chunks_parquet=str(chunks),
    )
    assert second.refreshed is False
    assert second.row_count == first.row_count
