# ruff: noqa: D100,D103,S101

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from codeintel_rev.io.faiss_build import (
    IndexBuildConfig,
    build_primary_index,
    create_secondary_index,
    save_index,
)
from codeintel_rev.io.faiss_build import (
    add_vectors as builder_add_vectors,
)
from codeintel_rev.io.faiss_runtime import search_dual
from codeintel_rev.io.faiss_store import export_idmap_parquet, get_idmap_array

EXPECTED_IDMAP_ROWS = 64


@pytest.fixture
def random_vectors() -> np.ndarray:
    rng = np.random.default_rng(1234)
    return rng.standard_normal((7000, 8), dtype=np.float32)


def test_builder_adaptive_selection(tmp_path: Path, random_vectors: np.ndarray) -> None:
    cfg = IndexBuildConfig(vec_dim=random_vectors.shape[1])
    index, label = build_primary_index(random_vectors[:2000], cfg=cfg)
    assert label.lower().startswith("flat")
    builder_add_vectors(index, random_vectors[:2000], np.arange(2000, dtype=np.int64))
    save_path = tmp_path / "flat.index"
    save_index(index, save_path)
    assert save_path.exists()


def test_runtime_merge_with_secondary(random_vectors: np.ndarray) -> None:
    cfg = IndexBuildConfig(vec_dim=random_vectors.shape[1])
    primary, _ = build_primary_index(random_vectors[:6000], cfg=cfg)
    builder_add_vectors(primary, random_vectors[:6000], np.arange(6000, dtype=np.int64))
    secondary = create_secondary_index(cfg.vec_dim)
    builder_add_vectors(
        secondary,
        random_vectors[6000:6500],
        np.arange(6000, 6500, dtype=np.int64),
    )
    queries = random_vectors[6500:6510]
    distances, ids = search_dual(
        primary=primary,
        secondary=secondary,
        query=queries,
        k=10,
        nprobe=32,
        refine_k_factor=1.0,
        catalog=None,
    )
    assert distances.shape == (queries.shape[0], 10)
    assert ids.shape == (queries.shape[0], 10)


def test_store_exports_idmap(tmp_path: Path, random_vectors: np.ndarray) -> None:
    pytest.importorskip("pyarrow")
    cfg = IndexBuildConfig(vec_dim=random_vectors.shape[1])
    index, _ = build_primary_index(random_vectors[:EXPECTED_IDMAP_ROWS], cfg=cfg)
    builder_add_vectors(
        index,
        random_vectors[:EXPECTED_IDMAP_ROWS],
        np.arange(EXPECTED_IDMAP_ROWS, dtype=np.int64),
    )
    out_path = tmp_path / "idmap.parquet"
    row_count = export_idmap_parquet(index, out_path)
    assert row_count == EXPECTED_IDMAP_ROWS
    assert out_path.exists()
    idmap = get_idmap_array(index)
    assert idmap.shape[0] == EXPECTED_IDMAP_ROWS
