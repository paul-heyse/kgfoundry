"""Service-level tests for the index build pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.services.index.build import run_index_build
from codeintel_rev.services.index.plan import IndexBuildConfig, IndexPaths

from tests._helpers import assertions

np = pytest.importorskip("numpy")
pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")
pytest.importorskip("faiss")


def _write_toy_parquet(
    out_dir: Path,
    *,
    rows: int,
    dim: int,
    id_col: str,
    vec_col: str,
) -> None:
    """Write a synthetic shard with deterministic embeddings."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(1234)
    vectors = rng.standard_normal((rows, dim), dtype=np.float32)
    ids = np.arange(rows, dtype=np.int64)
    uris = [f"file_{idx}.py" for idx in range(rows)]
    lines = np.arange(rows, dtype=np.int32)
    bytes_offsets = np.arange(rows, dtype=np.int64)
    previews = ["preview"] * rows
    contents = ["content"] * rows
    langs = ["python"] * rows
    hashes = np.zeros(rows, dtype=np.uint64)
    symbols = [[] for _ in range(rows)]
    columns: dict[str, Any] = {
        "id": pa.array(ids),
        "uri": pa.array(uris),
        "start_line": pa.array(lines),
        "end_line": pa.array(lines + 1),
        "start_byte": pa.array(bytes_offsets),
        "end_byte": pa.array(bytes_offsets + 10),
        "preview": pa.array(previews),
        "content": pa.array(contents),
        "lang": pa.array(langs),
        "content_hash": pa.array(hashes, type=pa.uint64()),
        "symbols": pa.array(symbols, type=pa.list_(pa.string())),
        "embedding": pa.array([vec.tolist() for vec in vectors], type=pa.list_(pa.float32())),
    }
    if id_col != "id":
        columns[id_col] = pa.array(ids)
    if vec_col != "embedding":
        columns[vec_col] = columns["embedding"]
    table = pa.table(columns)
    pq.write_table(table, (out_dir / "shard-0.parquet").as_posix())


def test_index_build_pipeline_exports_artifacts(tmp_path: Path) -> None:
    """Building an index persists both FAISS and idmap artifacts."""
    data_dir = tmp_path / "vectors"
    rows = 128
    dim = 16
    _write_toy_parquet(data_dir, rows=rows, dim=dim, id_col="chunk_id", vec_col="embedding")
    index_dir = tmp_path / "faiss"
    paths = IndexPaths(
        vectors_parquet_dir=data_dir,
        primary_index_path=index_dir / "primary.faiss",
        idmap_parquet_path=index_dir / "faiss_idmap.parquet",
        duckdb_path=None,
    )
    cfg = IndexBuildConfig(
        vec_dim=dim,
        id_col="chunk_id",
        vec_col="embedding",
        sample_size=rows // 2,
        batch_rows=rows // 4,
        materialize=False,
    )

    state = run_index_build(paths, cfg)

    assertions.expect_equal(state.added_rows, rows)
    assertions.expect_true(paths.primary_index_path.exists(), reason="Primary index missing")
    assertions.expect_true(paths.idmap_parquet_path.exists(), reason="ID map missing")
    pf = pq.ParquetFile(paths.idmap_parquet_path.as_posix())
    metadata = pf.metadata
    assertions.expect_true(metadata is not None, reason="Missing parquet metadata")
    if metadata is not None:
        assertions.expect_equal(metadata.num_rows, rows)


def test_index_build_materializes_duckdb(tmp_path: Path) -> None:
    """DuckDB registration + materialization create the expected relations."""
    pytest.importorskip("duckdb")
    data_dir = tmp_path / "vectors"
    rows = 64
    dim = 8
    _write_toy_parquet(data_dir, rows=rows, dim=dim, id_col="chunk_id", vec_col="embedding")
    index_dir = tmp_path / "faiss"
    db_path = index_dir / "catalog.duckdb"
    paths = IndexPaths(
        vectors_parquet_dir=data_dir,
        primary_index_path=index_dir / "primary.faiss",
        idmap_parquet_path=index_dir / "faiss_idmap.parquet",
        duckdb_path=db_path,
    )
    cfg = IndexBuildConfig(
        vec_dim=dim,
        id_col="chunk_id",
        vec_col="embedding",
        sample_size=rows // 2,
        batch_rows=rows // 4,
        materialize=True,
    )

    run_index_build(paths, cfg)

    catalog = DuckDBCatalog(db_path=db_path, vectors_dir=data_dir)
    with catalog.connection() as conn:
        idmap_row = conn.execute("SELECT COUNT(*) FROM faiss_idmap").fetchone()
        join_row = conn.execute("SELECT COUNT(*) FROM faiss_join_mat").fetchone()
        assertions.expect_true(idmap_row is not None, reason="faiss_idmap view missing")
        assertions.expect_true(join_row is not None, reason="faiss_join_mat view missing")
        if idmap_row is not None and join_row is not None:
            assertions.expect_equal(idmap_row[0], rows)
            assertions.expect_equal(join_row[0], rows)
