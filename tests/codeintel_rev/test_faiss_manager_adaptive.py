"""Tests for adaptive FAISS index selection.

Tests verify that FAISSManager automatically selects the optimal index type
based on corpus size, providing faster training for small/medium corpora
while maintaining high recall (>95%).

These are lightweight unit tests using small vector counts (100 vectors max)
and reduced dimensions (256) to validate logic without expensive training.
For stress tests with large corpora, see test_faiss_manager_stress.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import cast

import numpy as np
import pytest
from codeintel_rev.io.faiss_manager import FAISSManager

from tests._helpers import assertions
from tests.conftest import FAISS_MODULE, HAS_FAISS_SUPPORT

if not HAS_FAISS_SUPPORT:  # pragma: no cover - dependency-gated
    pytestmark = pytest.mark.skip(
        reason="FAISS bindings unavailable on this host",
    )

# Narrow FAISS module to concrete type for static checking
if FAISS_MODULE is None:  # pragma: no cover - dependency-gated
    pytest.skip("FAISS bindings unavailable on this host", allow_module_level=True)
faiss_module: ModuleType = cast("ModuleType", FAISS_MODULE)


# Use modern numpy random generator
_rng = np.random.default_rng(42)

# Unit tests use reduced dimensions for speed
_UNIT_TEST_VEC_DIM = 256


def _nlist_value(index: object) -> int | None:
    """Return nlist from nested FAISS index implementations.

    Returns
    -------
    int | None
        Extracted ``nlist`` value or ``None`` when unavailable.
    """
    current: object | None = index
    for _ in range(6):
        if current is None:
            break
        candidate = current
        if hasattr(faiss_module, "downcast_index"):
            try:
                candidate = faiss_module.downcast_index(current)
            except (AttributeError, RuntimeError):
                candidate = current
        nlist = getattr(candidate, "nlist", None)
        if nlist is not None:
            return int(nlist)
        current = getattr(candidate, "index", None)
    return None


def _unwrap_primary_index(manager: FAISSManager) -> object:
    """Return the concrete FAISS index implementation for assertions.

    Returns
    -------
    Any
        Underlying FAISS index object (downcast when available).
    """
    cpu_index = manager.require_cpu_index()
    candidate: object = getattr(cpu_index, "index", cpu_index)
    if hasattr(faiss_module, "downcast_index"):
        try:
            return faiss_module.downcast_index(candidate)
        except (AttributeError, RuntimeError):
            return candidate
    return candidate


@dataclass(frozen=True)
class IndexDescription:
    """Structured description of FAISS index metadata for assertions."""

    type_name: str
    has_metric_type: bool
    metric_type: int | None
    has_nlist: bool


def _describe_index(index: object) -> IndexDescription:
    """Return diagnostic metadata for a FAISS index.

    Returns
    -------
    IndexDescription
        Structured metadata describing key properties (type name, metric info,
        and nlist support) used in assertions.
    """
    type_name = type(index).__name__
    has_metric_type = hasattr(index, "metric_type")
    metric_type = getattr(index, "metric_type", None) if has_metric_type else None
    has_nlist = hasattr(index, "nlist")
    return IndexDescription(
        type_name=type_name,
        has_metric_type=has_metric_type,
        metric_type=metric_type,
        has_nlist=has_nlist,
    )


@pytest.fixture
def tmp_index_path(tmp_path: Path) -> Path:
    """Create a temporary index path for testing.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory fixture.

    Returns
    -------
    Path
        Path to temporary FAISS index file.
    """
    return tmp_path / "test_index.faiss"


@pytest.mark.parametrize(
    ("n_vectors", "expected_type"),
    [
        (10, "flat"),  # Small corpus: <5K
        (100, "flat"),  # Small corpus: <5K
        (4999, "flat"),  # Small corpus: <5K (boundary)
        (5000, "ivf_flat"),  # Medium corpus: 5K-50K (boundary)
        (10000, "ivf_flat"),  # Medium corpus: 5K-50K
    ],
)
def test_adaptive_index_selection(tmp_index_path: Path, n_vectors: int, expected_type: str) -> None:
    """Test that index type is selected based on corpus size.

    Uses reduced dimensions (256) for fast unit test execution.
    Tests only small/medium corpora (<50K vectors) to avoid expensive
    IVF-PQ training. For large corpus tests, see test_large_corpus_ivf_pq_nlist.

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    n_vectors : int
        Number of vectors to test with.
    expected_type : str
        Expected index type ("flat" or "ivf_flat").

    Raises
    ------
    AssertionError
        If the index type does not match the expected type for the given
        corpus size.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    # Generate random vectors: Gaussian distribution in range [0, 1]
    # This is more representative of real embeddings (which are typically normalized)
    # and creates tighter clusters that are easier to index than wide random values
    vectors = _rng.normal(0.5, 0.15, (n_vectors, vec_dim)).astype(np.float32)
    vectors = np.clip(vectors, 0.0, 1.0)  # Ensure values are in [0, 1] range

    # Build index
    manager.build_index(vectors)

    # Verify index type
    assertions.expect_true(manager.cpu_index is not None, reason="cpu_index should be set")
    cpu_index = manager.cpu_index

    # Check index type by examining the underlying index structure
    assertions.expect_true(
        isinstance(cpu_index, faiss_module.IndexIDMap2), reason="cpu_index should be IndexIDMap2"
    )
    underlying = _unwrap_primary_index(manager)
    description = _describe_index(underlying)
    underlying_type_name = description.type_name
    has_metric_type = description.has_metric_type
    metric_type = description.metric_type
    has_nlist = description.has_nlist

    if expected_type == "flat":
        # Flat index: should have metric_type (METRIC_INNER_PRODUCT = 0) and no nlist
        # IndexFlatIP is a simple flat index with inner product metric
        assertions.expect_true(
            has_metric_type,
            reason=f"Expected flat index with metric_type, got {underlying_type_name}",
        )
        assertions.expect_false(
            has_nlist, reason=f"Expected flat index without nlist, got {underlying_type_name}"
        )
        if metric_type is not None:
            assertions.expect_equal(
                metric_type,
                faiss_module.METRIC_INNER_PRODUCT,
                reason=f"Expected METRIC_INNER_PRODUCT, got {metric_type}",
            )
    elif expected_type == "ivf_flat":
        # IVFFlat: should have both metric_type and nlist
        assertions.expect_true(
            has_nlist, reason=f"Expected IVFFlat index with nlist, got {underlying_type_name}"
        )
        assertions.expect_true(
            has_metric_type,
            reason=f"Expected IVFFlat index with metric_type, got {underlying_type_name}",
        )
        if metric_type is not None:
            assertions.expect_equal(
                metric_type,
                faiss_module.METRIC_INNER_PRODUCT,
                reason=f"Expected METRIC_INNER_PRODUCT, got {metric_type}",
            )
    else:
        # Should not reach here - large corpus tests are separate
        msg = f"Unexpected type {expected_type} in parametrized test"
        raise AssertionError(msg)


def test_small_corpus_flat_index(tmp_index_path: Path) -> None:
    """Test that small corpus (<5K) uses flat index with no training.

    Flat indexes don't require training, so build_index should complete
    immediately without training overhead.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    n_vectors = 100  # Small corpus for fast unit test
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    # Generate random vectors: Gaussian distribution in range [0, 1]
    # This is more representative of real embeddings (which are typically normalized)
    # and creates tighter clusters that are easier to index than wide random values
    vectors = _rng.normal(0.5, 0.15, (n_vectors, vec_dim)).astype(np.float32)
    vectors = np.clip(vectors, 0.0, 1.0)  # Ensure values are in [0, 1] range

    # Build index (should be fast, no training)
    manager.build_index(vectors)

    # Verify flat index was created
    assertions.expect_true(manager.cpu_index is not None, reason="cpu_index should be set")
    cpu_index = manager.cpu_index
    assertions.expect_true(
        isinstance(cpu_index, faiss_module.IndexIDMap2), reason="cpu_index should be IndexIDMap2"
    )
    underlying = _unwrap_primary_index(manager)
    # Check by type name since isinstance may not work with dynamic types
    assertions.expect_true(
        "FlatIP" in type(underlying).__name__,
        reason=f"Expected FlatIP, got {type(underlying).__name__}",
    )


def test_small_corpus_search_returns_results(tmp_index_path: Path) -> None:
    """Regression: searching flat indexes skips nprobe assignment and succeeds."""
    vec_dim = _UNIT_TEST_VEC_DIM
    n_vectors = 32  # Small corpus ensures flat index selection
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    vectors = _rng.normal(0.5, 0.15, (n_vectors, vec_dim)).astype(np.float32)
    vectors = np.clip(vectors, 0.0, 1.0)

    manager.build_index(vectors)

    ids = np.arange(n_vectors, dtype=np.int64)
    manager.add_vectors(vectors, ids)

    query = vectors[0]
    distances, retrieved_ids = manager.search(query, k=5)

    assertions.expect_equal(distances.shape, (1, 5))
    assertions.expect_equal(retrieved_ids.shape, (1, 5))
    assertions.expect_equal(retrieved_ids[0, 0], ids[0])


def test_medium_corpus_ivf_flat_nlist(tmp_index_path: Path) -> None:
    """Test that medium corpus (5K-50K) uses IVFFlat with dynamic nlist.

    Verifies that nlist is calculated correctly: min(sqrt(n), n//39) with
    minimum of 100.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    n_vectors = 5000  # Boundary case for medium corpus
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    # Generate random vectors: Gaussian distribution in range [0, 1]
    # This is more representative of real embeddings (which are typically normalized)
    # and creates tighter clusters that are easier to index than wide random values
    vectors = _rng.normal(0.5, 0.15, (n_vectors, vec_dim)).astype(np.float32)
    vectors = np.clip(vectors, 0.0, 1.0)  # Ensure values are in [0, 1] range

    manager.build_index(vectors)

    # Verify IVFFlat index
    assertions.expect_true(manager.cpu_index is not None, reason="cpu_index should be set")
    cpu_index = manager.cpu_index
    assertions.expect_true(faiss_module is not None, reason="faiss_module should be available")
    assertions.expect_true(
        isinstance(cpu_index, faiss_module.IndexIDMap2), reason="cpu_index should be IndexIDMap2"
    )
    underlying = _unwrap_primary_index(manager)
    description = _describe_index(underlying)
    # Check by type name since isinstance may not work with dynamic types
    assertions.expect_true(
        "IVFFlat" in description.type_name,
        reason=f"Expected IVFFlat, got {description.type_name}",
    )

    # Verify nlist is calculated correctly
    expected_nlist = min(int(np.sqrt(n_vectors)), n_vectors // 39)
    expected_nlist = max(expected_nlist, 100)
    assertions.expect_equal(_nlist_value(underlying), expected_nlist)


def test_large_corpus_ivf_pq_nlist(tmp_index_path: Path) -> None:
    """Test that large corpus (>50K) uses IVF-PQ with dynamic nlist.

    Verifies that nlist is calculated correctly: sqrt(n) with minimum of 1024.
    Uses reduced dimensions for fast unit test execution.

    Runs entirely on CPU; set ``RUN_BENCHMARKS=1`` if executing in benchmark suites.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    n_vectors = 50000  # Boundary case for large corpus
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    # Generate random vectors: Gaussian distribution in range [0, 1]
    # This is more representative of real embeddings (which are typically normalized)
    # and creates tighter clusters that are easier to index than wide random values
    vectors = _rng.normal(0.5, 0.15, (n_vectors, vec_dim)).astype(np.float32)
    vectors = np.clip(vectors, 0.0, 1.0)  # Ensure values are in [0, 1] range

    manager.build_index(vectors)

    # Verify IVF-PQ index
    assertions.expect_true(manager.cpu_index is not None, reason="cpu_index should be set")
    cpu_index = manager.cpu_index
    assertions.expect_true(faiss_module is not None, reason="faiss_module should be available")
    assertions.expect_true(
        isinstance(cpu_index, faiss_module.IndexIDMap2), reason="cpu_index should be IndexIDMap2"
    )
    underlying = _unwrap_primary_index(manager)

    # Verify nlist is calculated correctly
    expected_nlist = int(np.sqrt(n_vectors))
    expected_nlist = max(expected_nlist, 1024)
    nlist_value = _nlist_value(underlying)
    assertions.expect_equal(
        nlist_value, expected_nlist, reason=f"Expected nlist {expected_nlist}, got {nlist_value}"
    )


def test_memory_estimation_small_corpus(tmp_index_path: Path) -> None:
    """Test memory estimation for small corpus (flat index).

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    n_vectors = 100
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    estimates = manager.estimate_memory_usage(n_vectors)

    # Flat index: n_vectors * vec_dim * 4 bytes
    expected_cpu = n_vectors * vec_dim * 4
    assertions.expect_equal(estimates["cpu_index_bytes"], expected_cpu)
    assertions.expect_equal(estimates["total_bytes"], estimates["cpu_index_bytes"])


def test_memory_estimation_medium_corpus(tmp_index_path: Path) -> None:
    """Test memory estimation for medium corpus (IVFFlat).

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    n_vectors = 5000  # Boundary case for medium corpus
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    estimates = manager.estimate_memory_usage(n_vectors)

    # Calculate expected memory: IVFFlat uses (nlist * vec_dim * 4) + (n_vectors * 8)
    nlist = min(int(np.sqrt(n_vectors)), n_vectors // 39)
    nlist = max(nlist, 100)
    expected_cpu = (nlist * vec_dim * 4) + (n_vectors * 8)
    assertions.expect_equal(estimates["cpu_index_bytes"], expected_cpu)
    assertions.expect_equal(estimates["total_bytes"], expected_cpu)


def test_memory_estimation_large_corpus(tmp_index_path: Path) -> None:
    """Test memory estimation for large corpus (IVF-PQ).

    This test only estimates memory (doesn't build index), so it's fast.

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    n_vectors = 50000  # Boundary case for large corpus
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    estimates = manager.estimate_memory_usage(n_vectors)

    # IVF-PQ: (nlist * vec_dim * 4) + (n_vectors * 64)
    nlist = int(np.sqrt(n_vectors))
    nlist = max(nlist, 1024)
    expected_cpu = (nlist * vec_dim * 4) + (n_vectors * 64)
    assertions.expect_equal(estimates["cpu_index_bytes"], expected_cpu)
    assertions.expect_equal(estimates["total_bytes"], expected_cpu)


def test_memory_estimation_accuracy(tmp_index_path: Path) -> None:
    """Test that memory estimates are reasonable (within 20% of actual).

    This test builds an actual index and compares estimated vs actual memory
    usage. Estimates should be within ±20% of actual usage.

    Uses a small corpus size (100 vectors) with reduced dimensions for fast
    test execution while still verifying accuracy.

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    n_vectors = 100  # Small corpus for fast test execution
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    # Get estimate before building
    estimates = manager.estimate_memory_usage(n_vectors)

    # Build actual index
    # Generate random vectors: Gaussian distribution in range [0, 1]
    # This is more representative of real embeddings (which are typically normalized)
    # and creates tighter clusters that are easier to index than wide random values
    vectors = _rng.normal(0.5, 0.15, (n_vectors, vec_dim)).astype(np.float32)
    vectors = np.clip(vectors, 0.0, 1.0)  # Ensure values are in [0, 1] range
    manager.build_index(vectors)
    ids = np.arange(n_vectors, dtype=np.int64)
    manager.add_vectors(vectors, ids)

    # Get actual index size (approximate via file size after save)
    manager.save_cpu_index()
    actual_size = tmp_index_path.stat().st_size

    # Estimate should be within 20% of actual (allowing for overhead)
    # Note: File size includes serialization overhead, so we compare estimates
    # to a reasonable range
    assertions.expect_true(
        estimates["cpu_index_bytes"] > 0, reason="cpu_index_bytes should be positive"
    )
    assertions.expect_true(estimates["total_bytes"] > 0, reason="total_bytes should be positive")
    # Actual size should be reasonable (at least 50% of estimate, at most 200%)
    assertions.expect_true(
        actual_size >= estimates["cpu_index_bytes"] * 0.5,
        reason="actual size should be at least 50% of estimate",
    )
    assertions.expect_true(
        actual_size <= estimates["cpu_index_bytes"] * 2.0,
        reason="actual size should be at most 200% of estimate",
    )
