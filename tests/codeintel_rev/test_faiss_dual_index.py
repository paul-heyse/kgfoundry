"""Unit tests for FAISS dual-index manifest helpers and manager readiness."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from codeintel_rev.config.settings import IndexConfig
from codeintel_rev.io.faiss_dual_index import FAISSDualIndexManager, IndexManifest

from tests._helpers import assertions
from tests.conftest import FAISS_MODULE, HAS_FAISS_SUPPORT

if not HAS_FAISS_SUPPORT:  # pragma: no cover - gated on FAISS availability
    pytest.skip("FAISS bindings unavailable; skipping dual-index tests", allow_module_level=True)

assertions.expect_true(
    FAISS_MODULE is not None,
    reason="FAISS_MODULE should be available when HAS_FAISS_SUPPORT is True",
)
faiss_module: Any = FAISS_MODULE

_rng = np.random.default_rng(1234)

# Test constants
_MIN_SIMILARITY_SCORE = 0.9


def _sample_manifest() -> IndexManifest:
    """Return a representative manifest fixture for round-trip tests.

    Returns
    -------
    IndexManifest
        Manifest populated with deterministic metadata for assertions.
    """
    return IndexManifest(
        version="2025-11-08",
        vec_dim=16,
        index_type="Flat",
        metric="IP",
        trained_on="unit-test",
        built_at="2025-11-08T12:34:56Z",
        gpu_enabled=False,
        primary_count=8,
        secondary_count=0,
    )


def _build_flat_index(vec_dim: int, count: int) -> Any:
    """Construct an in-memory FAISS flat index populated with unit vectors.

    Parameters
    ----------
    vec_dim : int
        Dimensionality of the embedding space.
    count : int
        Number of vectors to generate for the index.

    Returns
    -------
    Any
        Flat inner-product index containing ``count`` normalized vectors.
    """
    base = faiss_module.IndexFlatIP(vec_dim)
    index = faiss_module.IndexIDMap2(base)
    vectors = _rng.standard_normal((count, vec_dim)).astype(np.float32)
    faiss_module.normalize_L2(vectors)
    ids = np.arange(count, dtype=np.int64)
    index.add_with_ids(vectors, ids)
    return index


@pytest.mark.asyncio
async def test_ensure_ready_loads_indexes_cpu_only(tmp_path: Path) -> None:
    """Primary index loads, secondary auto-creates, and manifest is attached for CPU use."""
    vec_dim = 16
    primary = _build_flat_index(vec_dim, 8)
    faiss_module.write_index(primary, str(tmp_path / "primary.faiss"))

    manifest = _sample_manifest()
    manifest.to_file(tmp_path / "primary.manifest.json")

    settings = IndexConfig(vec_dim=vec_dim, use_cuvs=False)
    manager = FAISSDualIndexManager(tmp_path, settings, vec_dim)

    ready, reason = await manager.ensure_ready()

    assertions.expect_true(ready, reason="manager should be ready")
    assertions.expect_true(manager.primary_index is not None, reason="primary index should exist")
    if manager.primary_index is not None:
        assertions.expect_equal(manager.primary_index.d, vec_dim)
    assertions.expect_true(
        manager.secondary_index is not None, reason="secondary index should exist"
    )
    if manager.secondary_index is not None:
        assertions.expect_equal(manager.secondary_index.ntotal, 0)
    assertions.expect_equal(manager.manifest, manifest)
    assertions.expect_false(manager.gpu_enabled)


@pytest.mark.asyncio
async def test_ensure_ready_missing_primary(tmp_path: Path) -> None:
    """Missing primary index returns explicit failure reason."""
    vec_dim = 32
    settings = IndexConfig(vec_dim=vec_dim, use_cuvs=False)
    manager = FAISSDualIndexManager(tmp_path, settings, vec_dim=vec_dim)

    ready, reason = await manager.ensure_ready()

    assertions.expect_false(
        ready, reason="manager should not be ready when primary index is missing"
    )
    assertions.expect_equal(reason, "Primary index not found")
    assertions.expect_equal(manager.primary_index, None)
    assertions.expect_equal(manager.secondary_index, None)


@pytest.mark.asyncio
async def test_ensure_ready_dimension_mismatch(tmp_path: Path) -> None:
    """Primary index dimension mismatch fails fast with message."""
    vec_dim = 32
    mismatched = _build_flat_index(vec_dim + 4, 4)
    faiss_module.write_index(mismatched, str(tmp_path / "primary.faiss"))

    settings = IndexConfig(vec_dim=vec_dim, use_cuvs=False)
    manager = FAISSDualIndexManager(tmp_path, settings, vec_dim=vec_dim)

    ready, reason = await manager.ensure_ready()

    assertions.expect_false(ready, reason="manager should not be ready when dimension mismatch")
    assertions.expect_in("Dimension mismatch", str(reason))


def test_manifest_round_trip(tmp_path: Path) -> None:
    """Manifest JSON round-trips and preserves optional fields."""
    path = tmp_path / "manifest.json"
    manifest = _sample_manifest()
    manifest.to_file(path)

    loaded = IndexManifest.from_file(path)

    assertions.expect_equal(loaded, manifest)


def test_manifest_optional_fields(tmp_path: Path) -> None:
    """Optional manifest fields survive serialization."""
    path = tmp_path / "manifest.json"
    manifest = IndexManifest(
        version="2025-11-08",
        vec_dim=16,
        index_type="IVFPQ",
        metric="IP",
        trained_on="unit-test",
        built_at="2025-11-08T12:34:56Z",
        gpu_enabled=True,
        primary_count=128,
        secondary_count=64,
        nlist=4096,
        pq_m=32,
        cuvs_version="1.0.0",
    )
    manifest.to_file(path)

    loaded = IndexManifest.from_file(path)

    assertions.expect_equal(loaded.index_type, "IVFPQ")
    assertions.expect_equal(loaded.nlist, 4096)
    assertions.expect_equal(loaded.pq_m, 32)
    assertions.expect_equal(loaded.cuvs_version, "1.0.0")


def test_manifest_invalid_payload(tmp_path: Path) -> None:
    """Non-object JSON payloads raise TypeError."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")

    with pytest.raises(TypeError, match="Manifest JSON must be an object"):
        IndexManifest.from_file(path)


def test_manifest_missing_required_fields(tmp_path: Path) -> None:
    """Missing required keys raise ValueError with context."""
    path = tmp_path / "manifest.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="Manifest file has unexpected structure"):
        IndexManifest.from_file(path)


@pytest.mark.asyncio
async def test_search_primary_only(tmp_path: Path) -> None:
    """Search returns primary results when no secondary index exists."""
    vec_dim = 8
    primary = faiss_module.IndexIDMap2(faiss_module.IndexFlatIP(vec_dim))
    primary_vectors = np.eye(vec_dim, dtype=np.float32)
    faiss_module.normalize_L2(primary_vectors)
    primary_ids = np.arange(vec_dim, dtype=np.int64)
    primary.add_with_ids(primary_vectors, primary_ids)
    faiss_module.write_index(primary, str(tmp_path / "primary.faiss"))

    settings = IndexConfig(vec_dim=vec_dim, use_cuvs=False)
    manager = FAISSDualIndexManager(tmp_path, settings, vec_dim)
    ready, _ = await manager.ensure_ready()
    assertions.expect_true(ready, reason="manager should be ready")

    query = primary_vectors[1]
    results = manager.search(query, k=3)

    assertions.expect_true(bool(results), reason="search should return results")
    top_id, top_score = results[0]
    assertions.expect_equal(top_id, 1)
    assertions.expect_true(top_score > _MIN_SIMILARITY_SCORE, reason="top score should be high")


@pytest.mark.asyncio
async def test_search_merges_secondary(tmp_path: Path) -> None:
    """Secondary results are merged and deduplicated."""
    vec_dim = 8
    base_vectors = np.eye(vec_dim, dtype=np.float32)
    faiss_module.normalize_L2(base_vectors)

    primary = faiss_module.IndexIDMap2(faiss_module.IndexFlatIP(vec_dim))
    primary.add_with_ids(base_vectors[:2], np.array([10, 11], dtype=np.int64))
    faiss_module.write_index(primary, str(tmp_path / "primary.faiss"))

    secondary = faiss_module.IndexIDMap2(faiss_module.IndexFlatIP(vec_dim))
    secondary.add_with_ids(base_vectors[2:3], np.array([99], dtype=np.int64))
    faiss_module.write_index(secondary, str(tmp_path / "secondary.faiss"))

    settings = IndexConfig(vec_dim=vec_dim, use_cuvs=False)
    manager = FAISSDualIndexManager(tmp_path, settings, vec_dim)
    ready, _ = await manager.ensure_ready()
    assertions.expect_true(ready, reason="manager should be ready")

    query = base_vectors[2]
    results = manager.search(query, k=2)

    assertions.expect_true(bool(results), reason="search should return results")
    assertions.expect_equal(results[0][0], 99)
    assertions.expect_true(results[0][1] > _MIN_SIMILARITY_SCORE, reason="top score should be high")


@pytest.mark.asyncio
async def test_add_incremental_persists_secondary(tmp_path: Path) -> None:
    """Incremental adds populate the secondary index and persist to disk."""
    vec_dim = 6
    primary = _build_flat_index(vec_dim, 6)
    faiss_module.write_index(primary, str(tmp_path / "primary.faiss"))

    settings = IndexConfig(vec_dim=vec_dim, use_cuvs=False)
    manager = FAISSDualIndexManager(tmp_path, settings, vec_dim)
    ready, _ = await manager.ensure_ready()
    assertions.expect_true(ready, reason="manager should be ready")

    rng = np.random.default_rng(42)
    new_vectors = rng.standard_normal((1, vec_dim)).astype(np.float32)
    faiss_module.normalize_L2(new_vectors)
    new_ids = np.array([9999], dtype=np.int64)

    await manager.add_incremental(new_vectors, new_ids)

    assertions.expect_true(
        manager.secondary_index is not None, reason="secondary index should exist"
    )
    if manager.secondary_index is not None:
        assertions.expect_equal(manager.secondary_index.ntotal, 1)

    persisted = faiss_module.read_index(str(tmp_path / "secondary.faiss"))
    assertions.expect_equal(persisted.ntotal, 1)

    hits = manager.search(new_vectors[0], k=1)
    assertions.expect_equal(hits[0][0], 9999)


@pytest.mark.asyncio
async def test_add_incremental_dimension_mismatch(tmp_path: Path) -> None:
    """Dimension mismatches raise ValueError to protect index integrity."""
    vec_dim = 4
    primary = _build_flat_index(vec_dim, 4)
    faiss_module.write_index(primary, str(tmp_path / "primary.faiss"))

    settings = IndexConfig(vec_dim=vec_dim, use_cuvs=False)
    manager = FAISSDualIndexManager(tmp_path, settings, vec_dim)
    ready, _ = await manager.ensure_ready()
    assertions.expect_true(ready, reason="manager should be ready")

    bad_vectors = np.ones((1, vec_dim + 1), dtype=np.float32)
    with pytest.raises(ValueError, match="Vector dimension"):
        await manager.add_incremental(bad_vectors, np.array([1], dtype=np.int64))


@pytest.mark.asyncio
async def test_needs_compaction_threshold(tmp_path: Path) -> None:
    """Compaction triggers once the secondary ratio exceeds the threshold."""
    vec_dim = 8
    primary = _build_flat_index(vec_dim, 20)
    faiss_module.write_index(primary, str(tmp_path / "primary.faiss"))

    settings = IndexConfig(vec_dim=vec_dim, use_cuvs=False, compaction_threshold=0.05)
    manager = FAISSDualIndexManager(tmp_path, settings, vec_dim)
    ready, _ = await manager.ensure_ready()
    assertions.expect_true(ready, reason="manager should be ready")

    assertions.expect_false(
        manager.needs_compaction(), reason="should not need compaction initially"
    )

    base_vec = np.eye(vec_dim, dtype=np.float32)
    faiss_module.normalize_L2(base_vec)

    await manager.add_incremental(base_vec[0:1], np.array([10_001], dtype=np.int64))
    assertions.expect_false(
        manager.needs_compaction(), reason="should not need compaction after first add"
    )

    await manager.add_incremental(base_vec[1:2], np.array([10_002], dtype=np.int64))
    assertions.expect_true(
        manager.needs_compaction(), reason="should need compaction after threshold exceeded"
    )
