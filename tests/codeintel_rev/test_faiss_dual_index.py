"""Unit tests for FAISS dual-index manifest helpers and manager readiness."""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from codeintel_rev.config.settings import IndexConfig
from codeintel_rev.io.faiss_dual_index import FAISSDualIndexManager, IndexManifest

from tests.conftest import HAS_FAISS_SUPPORT, HAS_GPU_STACK

if not HAS_FAISS_SUPPORT:  # pragma: no cover - gated on FAISS availability
    pytest.skip("FAISS module unavailable; skipping FAISS dual-index tests", allow_module_level=True)

def _build_stub_faiss_module() -> object:
    """Return a lightweight FAISS stub for environments without native bindings."""

    class _StubIndex:
        def __init__(self, dim: int) -> None:
            self.d = dim
            self.ntotal = 0

        def add(self, _vectors: np.ndarray) -> None:
            self.ntotal += len(_vectors)

        def add_with_ids(self, vectors: np.ndarray, ids: np.ndarray) -> None:
            self.add(vectors)
            _ = ids

        def search(self, _query: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
            distances = np.zeros((1, k), dtype=np.float32)
            ids = -np.ones((1, k), dtype=np.int64)
            return distances, ids

    class _StubGpuResources:
        pass

    class _StubClonerOptions:
        def __init__(self) -> None:
            self.use_cuvs = False

    module = types.SimpleNamespace()
    module.IndexFlatIP = lambda dim: _StubIndex(dim)
    module.IndexIDMap2 = lambda index: index
    module.normalize_L2 = lambda _vectors: None
    module.write_index = lambda *_args, **_kwargs: None
    module.read_index = lambda path: _StubIndex(1)
    module.StandardGpuResources = _StubGpuResources
    module.GpuClonerOptions = _StubClonerOptions
    module.index_cpu_to_gpu = lambda *_args, **_kwargs: _StubIndex(1)
    return module


try:
    sys.modules.pop("faiss", None)
    faiss = importlib.import_module("faiss")  # type: ignore[import-untyped]
    _REQUIRED_ATTRS = ("IndexFlatIP", "normalize_L2", "write_index")
    if not all(hasattr(faiss, attr) for attr in _REQUIRED_ATTRS):
        raise AttributeError("FAISS build missing required symbols")
except Exception:  # pragma: no cover - fallback when FAISS import is incomplete
    faiss = _build_stub_faiss_module()
    sys.modules["faiss"] = faiss  # type: ignore[assignment]

_rng = np.random.default_rng(1234)


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


def _build_flat_index(vec_dim: int, count: int) -> faiss.Index:  # type: ignore[name-defined]
    """Construct an in-memory FAISS flat index populated with unit vectors.

    Parameters
    ----------
    vec_dim : int
        Dimensionality of the embedding space.
    count : int
        Number of vectors to generate for the index.

    Returns
    -------
    faiss.Index
        Flat inner-product index containing ``count`` normalized vectors.
    """
    index = faiss.IndexFlatIP(vec_dim)  # type: ignore[attr-defined]
    vectors = _rng.standard_normal((count, vec_dim)).astype(np.float32)
    faiss.normalize_L2(vectors)
    index.add(vectors)
    return index


@pytest.mark.asyncio
async def test_ensure_ready_loads_indexes_without_gpu(tmp_path: Path) -> None:
    """Primary index loads, secondary auto-creates, and manifest is attached."""
    vec_dim = 16
    primary = _build_flat_index(vec_dim, 8)
    faiss.write_index(primary, str(tmp_path / "primary.faiss"))

    manifest = _sample_manifest()
    manifest.to_file(tmp_path / "primary.manifest.json")

    settings = IndexConfig(vec_dim=vec_dim, use_cuvs=True)
    manager = FAISSDualIndexManager(tmp_path, settings, vec_dim)

    ready, reason = await manager.ensure_ready()

    assert ready is True
    assert manager.primary_index is not None
    assert manager.primary_index.d == vec_dim  # type: ignore[attr-defined]
    assert manager.secondary_index is not None
    assert manager.secondary_index.ntotal == 0  # type: ignore[attr-defined]
    assert manager.manifest == manifest
    assert manager.gpu_enabled is (reason is None)


@pytest.mark.asyncio
async def test_ensure_ready_missing_primary(tmp_path: Path) -> None:
    """Missing primary index returns explicit failure reason."""
    vec_dim = 32
    settings = IndexConfig(vec_dim=vec_dim, use_cuvs=False)
    manager = FAISSDualIndexManager(tmp_path, settings, vec_dim=vec_dim)

    ready, reason = await manager.ensure_ready()

    assert ready is False
    assert reason == "Primary index not found"
    assert manager.primary_index is None
    assert manager.secondary_index is None


@pytest.mark.asyncio
async def test_ensure_ready_dimension_mismatch(tmp_path: Path) -> None:
    """Primary index dimension mismatch fails fast with message."""
    vec_dim = 32
    mismatched = _build_flat_index(vec_dim + 4, 4)
    faiss.write_index(mismatched, str(tmp_path / "primary.faiss"))

    settings = IndexConfig(vec_dim=vec_dim, use_cuvs=False)
    manager = FAISSDualIndexManager(tmp_path, settings, vec_dim)

    ready, reason = await manager.ensure_ready()

    assert ready is False
    assert reason is not None
    assert "Dimension mismatch" in reason
    assert manager.primary_index is None
    assert manager.secondary_index is None


def test_manifest_roundtrip(tmp_path: Path) -> None:
    """Manifest serialization round-trips through disk."""
    manifest = _sample_manifest()
    path = tmp_path / "manifest.json"
    manifest.to_file(path)

    loaded = IndexManifest.from_file(path)
    assert loaded == manifest


def test_manifest_optional_fields(tmp_path: Path) -> None:
    """Optional fields may be omitted from JSON payload."""
    payload = {
        "version": "2025-11-08",
        "vec_dim": 2560,
        "index_type": "IVFPQ",
        "metric": "IP",
        "trained_on": "dataset-v2",
        "built_at": "2025-11-08T11:00:00Z",
        "gpu_enabled": True,
        "primary_count": 100,
        "secondary_count": 5,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = IndexManifest.from_file(path)

    assert loaded.index_type == "IVFPQ"
    assert loaded.nlist is None
    assert loaded.pq_m is None
    assert loaded.cuvs_version is None


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
    primary = faiss.IndexFlatIP(vec_dim)  # type: ignore[attr-defined]
    primary_vectors = np.eye(vec_dim, dtype=np.float32)
    faiss.normalize_L2(primary_vectors)
    primary_ids = np.arange(vec_dim, dtype=np.int64)
    primary.add_with_ids(primary_vectors, primary_ids)
    faiss.write_index(primary, str(tmp_path / "primary.faiss"))

    settings = IndexConfig(vec_dim=vec_dim, use_cuvs=False)
    manager = FAISSDualIndexManager(tmp_path, settings, vec_dim)
    ready, _ = await manager.ensure_ready()
    assert ready is True

    query = primary_vectors[1]
    results = manager.search(query, k=3)

    assert results
    top_id, top_score = results[0]
    assert top_id == 1
    assert top_score > 0.9


@pytest.mark.asyncio
async def test_search_merges_secondary(tmp_path: Path) -> None:
    """Secondary results are merged and deduplicated."""
    vec_dim = 8
    base_vectors = np.eye(vec_dim, dtype=np.float32)
    faiss.normalize_L2(base_vectors)

    primary = faiss.IndexFlatIP(vec_dim)  # type: ignore[attr-defined]
    primary.add_with_ids(base_vectors[:2], np.array([10, 11], dtype=np.int64))
    faiss.write_index(primary, str(tmp_path / "primary.faiss"))

    secondary = faiss.IndexFlatIP(vec_dim)  # type: ignore[attr-defined]
    secondary.add_with_ids(base_vectors[2:3], np.array([99], dtype=np.int64))
    faiss.write_index(secondary, str(tmp_path / "secondary.faiss"))

    settings = IndexConfig(vec_dim=vec_dim, use_cuvs=False)
    manager = FAISSDualIndexManager(tmp_path, settings, vec_dim)
    ready, _ = await manager.ensure_ready()
    assert ready is True

    query = base_vectors[2]
    results = manager.search(query, k=2)

    assert results
    assert results[0][0] == 99
    assert results[0][1] > 0.9
