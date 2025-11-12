"""Tests for FAISSManager export and tuning helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import numpy as np
import pyarrow.parquet as pq
import pytest
from codeintel_rev.io.faiss_manager import FAISSManager, FAISSRuntimeOptions


def test_export_idmap_round_trip(tmp_path: Path) -> None:
    """Exported ID map reflects the chunk IDs added to the index."""
    vec_dim = 16
    vectors = np.random.RandomState(0).randn(32, vec_dim).astype(np.float32)
    ids = np.arange(32, dtype=np.int64)

    manager = FAISSManager(index_path=tmp_path / "index.faiss", vec_dim=vec_dim, use_cuvs=False)
    manager.build_index(vectors)
    manager.add_vectors(vectors, ids)
    manager.save_cpu_index()

    # Reload to ensure persistence path exercises load code paths.
    manager.load_cpu_index()
    out_path = tmp_path / "faiss_idmap.parquet"
    rows = manager.export_idmap(out_path)
    assert rows == 32

    table = pq.read_table(out_path)
    assert set(table.column_names) == {"faiss_row", "external_id", "source"}
    assert table.num_rows == 32
    assert table.column("external_id").to_pylist()[:5] == [0, 1, 2, 3, 4]
    assert set(table.column("source").to_pylist()) == {"primary"}


def _meta_path(manager: FAISSManager) -> Path:
    return Path(f"{manager.index_path}.meta.json")


def test_build_index_writes_meta_snapshot(tmp_path: Path) -> None:
    """Building an index writes a metadata sidecar with defaults."""
    vec_dim = 8
    vectors = np.random.RandomState(42).randn(128, vec_dim).astype(np.float32)
    manager = FAISSManager(index_path=tmp_path / "index.faiss", vec_dim=vec_dim, use_cuvs=False)
    manager.build_index(vectors)

    meta_file = _meta_path(manager)
    assert meta_file.exists()
    payload = cast("dict[str, Any]", json.loads(meta_file.read_text()))
    assert payload["vec_dim"] == vec_dim
    assert payload["vector_count"] == len(vectors)
    assert payload["runtime_overrides"] == {}
    assert payload["default_parameters"]["nprobe"] == manager.default_nprobe


def test_set_search_parameters_updates_overrides(tmp_path: Path) -> None:
    """ParameterSpace strings update overrides and metadata."""
    vec_dim = 16
    vectors = np.random.RandomState(7).randn(6000, vec_dim).astype(np.float32)
    manager = FAISSManager(
        index_path=tmp_path / "index.faiss",
        vec_dim=vec_dim,
        runtime=FAISSRuntimeOptions(faiss_family="ivf_flat"),
        use_cuvs=False,
    )
    manager.build_index(vectors)

    tuning = manager.set_search_parameters("nprobe=12,k_factor=1.5")
    overrides = cast("Mapping[str, float]", tuning["overrides"])
    assert overrides["nprobe"] == 12
    assert overrides["k_factor"] == pytest.approx(1.5)

    meta = cast("dict[str, Any]", json.loads(_meta_path(manager).read_text()))
    runtime_overrides = cast("dict[str, Any]", meta["runtime_overrides"])
    assert runtime_overrides["nprobe"] == 12
    assert "parameter_space" in meta
    assert "nprobe=12" in meta["parameter_space"]


def test_set_search_parameters_rejects_unknown_keys(tmp_path: Path) -> None:
    vec_dim = 8
    vectors = np.random.RandomState(9).randn(64, vec_dim).astype(np.float32)
    manager = FAISSManager(index_path=tmp_path / "index.faiss", vec_dim=vec_dim, use_cuvs=False)
    manager.build_index(vectors)
    with pytest.raises(ValueError, match="Unsupported"):
        manager.set_search_parameters("bad_param=1")
