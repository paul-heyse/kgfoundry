"""Tests for FAISSManager export and tuning helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import duckdb
import numpy as np
import pyarrow.parquet as pq
import pytest
from codeintel_rev.io.faiss_manager import FAISSManager, FAISSRuntimeOptions

from tests._helpers import assertions


def test_export_idmap_round_trip(tmp_path: Path) -> None:
    """Exported ID map reflects the chunk IDs added to the index."""
    vec_dim = 16
    vectors = np.random.RandomState(0).randn(32, vec_dim).astype(np.float32)
    ids = np.arange(32, dtype=np.int64)

    manager = FAISSManager(index_path=tmp_path / "index.faiss", vec_dim=vec_dim)
    manager.build_index(vectors)
    manager.add_vectors(vectors, ids)
    manager.save_cpu_index()

    # Reload to ensure persistence path exercises load code paths.
    manager.load_cpu_index()
    out_path = tmp_path / "faiss_idmap.parquet"
    rows = manager.export_idmap(out_path)
    assertions.expect_equal(rows, 32)

    table = pq.read_table(out_path)
    assertions.expect_equal(
        set(table.column_names), {"faiss_row", "external_id", "index_name", "ts"}
    )
    assertions.expect_equal(table.num_rows, 32)
    assertions.expect_sequence_equal(table.column("external_id").to_pylist()[:5], [0, 1, 2, 3, 4])
    index_names = table.column("index_name").to_pylist()
    assertions.expect_true(
        all(name == "index.faiss" for name in index_names), reason="all index names should match"
    )
    timestamps = table.column("ts").to_pylist()
    if not timestamps:  # pragma: no cover - defensive
        pytest.fail("timestamp column should be populated")
    first_ts = timestamps[0]
    assertions.expect_true(isinstance(first_ts, datetime), reason="timestamp should be datetime")
    if not isinstance(first_ts, datetime):  # pragma: no cover - defensive
        pytest.fail("timestamp did not serialize as datetime")
    assertions.expect_true(first_ts.tzinfo is not None, reason="timestamp should be timezone-aware")


def test_duckdb_join_with_idmap(tmp_path: Path) -> None:
    """ID map sidecar can be joined with chunk metadata via DuckDB."""
    vec_dim = 4
    vectors = np.random.RandomState(1).randn(4, vec_dim).astype(np.float32)
    ids = np.array([10, 11, 12, 13], dtype=np.int64)
    manager = FAISSManager(index_path=tmp_path / "index.faiss", vec_dim=vec_dim)
    manager.build_index(vectors)
    manager.add_vectors(vectors, ids)
    manager.save_cpu_index()
    manager.load_cpu_index()
    idmap_path = tmp_path / "faiss_idmap.parquet"
    manager.export_idmap(idmap_path)
    conn = duckdb.connect(str(tmp_path / "cat.duckdb"))
    conn.execute(
        """
        CREATE TABLE chunks (
            id BIGINT,
            uri VARCHAR,
            start_line INTEGER,
            end_line INTEGER,
            lang VARCHAR,
            content VARCHAR,
            preview VARCHAR,
            embedding FLOAT[]
        )
        """
    )
    for chunk_id in ids.tolist():
        conn.execute(
            "INSERT INTO chunks VALUES (?, 'repo://file.py', 0, 1, 'py', 'body', 'body', [0.1])",
            [int(chunk_id)],
        )
    relation = conn.sql(
        "SELECT faiss_row, external_id FROM read_parquet(?)",
        params=[str(idmap_path)],
    )
    relation.create_view("faiss_idmap", replace=True)
    conn.execute(
        """
        CREATE OR REPLACE VIEW v_faiss_join AS
        SELECT c.id, f.faiss_row
        FROM chunks AS c
        LEFT JOIN faiss_idmap AS f
          ON f.external_id = c.id
        """
    )
    row = conn.execute("SELECT COUNT(*) FROM v_faiss_join WHERE faiss_row IS NOT NULL").fetchone()
    assertions.expect_true(row is not None, reason="query should return a result")
    if row is None:  # pragma: no cover - defensive
        pytest.fail("query should return a result")
    assertions.expect_equal(row[0], len(ids))


def test_load_cpu_index_applies_tuning_profile(tmp_path: Path) -> None:
    """Persisted tuning profile is applied when loading a CPU index."""
    vec_dim = 8
    vectors = np.random.RandomState(7).randn(64, vec_dim).astype(np.float32)
    manager = FAISSManager(index_path=tmp_path / "index.faiss", vec_dim=vec_dim)
    manager.build_index(vectors)
    manager.save_cpu_index()
    profile_payload = {
        "nprobe": 12,
        "efSearch": 64,
        "k_factor": 1.25,
        "factory": "Flat",
    }
    (tmp_path / "tuning.json").write_text(json.dumps(profile_payload), encoding="utf-8")

    reloaded = FAISSManager(index_path=tmp_path / "index.faiss", vec_dim=vec_dim)
    reloaded.load_cpu_index()

    runtime = reloaded.runtime.get_runtime_tuning()
    active = cast("Mapping[str, object]", runtime["active"])
    assertions.expect_equal(active["nprobe"], 12)
    assertions.expect_equal(active["efSearch"], 64)
    assertions.expect_almost_equal(reloaded.refine_k_factor, 1.25)


def _meta_path(manager: FAISSManager) -> Path:
    return Path(f"{manager.index_path}.meta.json")


def test_build_index_writes_meta_snapshot(tmp_path: Path) -> None:
    """Building an index writes a metadata sidecar with defaults."""
    vec_dim = 8
    vectors = np.random.RandomState(42).randn(128, vec_dim).astype(np.float32)
    manager = FAISSManager(index_path=tmp_path / "index.faiss", vec_dim=vec_dim)
    manager.build_index(vectors)

    meta_file = _meta_path(manager)
    assertions.expect_true(meta_file.exists(), reason="meta file should exist")
    payload = cast("dict[str, Any]", json.loads(meta_file.read_text()))
    assertions.expect_equal(payload["vec_dim"], vec_dim)
    assertions.expect_equal(payload["vector_count"], len(vectors))
    assertions.expect_mapping_equal(cast("dict[str, object]", payload["runtime_overrides"]), {})
    assertions.expect_equal(payload["default_parameters"]["nprobe"], manager.default_nprobe)


def test_set_search_parameters_updates_overrides(tmp_path: Path) -> None:
    """ParameterSpace strings update overrides and metadata."""
    vec_dim = 16
    vectors = np.random.RandomState(7).randn(6000, vec_dim).astype(np.float32)
    manager = FAISSManager(
        index_path=tmp_path / "index.faiss",
        vec_dim=vec_dim,
        runtime=FAISSRuntimeOptions(faiss_family="ivf_flat"),
    )
    manager.build_index(vectors)

    tuning = manager.runtime.set_search_parameters("nprobe=12,k_factor=1.5")
    overrides = cast("Mapping[str, float]", tuning["overrides"])
    assertions.expect_equal(overrides["nprobe"], 12)
    assertions.expect_almost_equal(overrides["k_factor"], 1.5)

    meta = cast("dict[str, Any]", json.loads(_meta_path(manager).read_text()))
    runtime_overrides = cast("dict[str, Any]", meta["runtime_overrides"])
    assertions.expect_equal(runtime_overrides["nprobe"], 12)
    assertions.expect_true("parameter_space" in meta, reason="meta should have parameter_space")
    assertions.expect_true(
        "nprobe=12" in cast("str", meta["parameter_space"]),
        reason="parameter_space should contain nprobe",
    )


def test_set_search_parameters_rejects_unknown_keys(tmp_path: Path) -> None:
    """Test that unknown parameter keys are rejected."""
    vec_dim = 8
    vectors = np.random.RandomState(9).randn(64, vec_dim).astype(np.float32)
    manager = FAISSManager(index_path=tmp_path / "index.faiss", vec_dim=vec_dim)
    manager.build_index(vectors)
    with pytest.raises(ValueError, match="Unsupported"):
        manager.runtime.set_search_parameters("bad_param=1")
