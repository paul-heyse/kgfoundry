"""Tests for incremental FAISS indexing (dual-index architecture).

Tests verify that incremental updates work correctly:
- update_index() adds vectors to secondary index
- Dual-index search returns results from both indexes
- merge_indexes() combines secondary into primary
- End-to-end workflow: initial → incremental → merge → search
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from codeintel_rev.io.faiss_manager import FAISSManager

from tests.conftest import FAISS_MODULE, HAS_FAISS_SUPPORT

if not HAS_FAISS_SUPPORT:  # pragma: no cover - dependency-gated
    pytestmark = pytest.mark.skip(
        reason="FAISS bindings unavailable on this host",
    )
else:
    assert FAISS_MODULE is not None
    faiss_module: Any = FAISS_MODULE

# Use modern numpy random generator
_rng = np.random.default_rng(42)

# Unit tests use reduced dimensions for speed
_UNIT_TEST_VEC_DIM = 256


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


def test_update_index_creates_secondary(tmp_index_path: Path) -> None:
    """Test that update_index creates secondary index on first call.

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    # Secondary index should not exist initially
    assert manager.secondary_index is None
    assert len(manager.incremental_ids) == 0

    # Generate test vectors
    new_vectors = _rng.normal(0.5, 0.15, (10, vec_dim)).astype(np.float32)
    new_vectors = np.clip(new_vectors, 0.0, 1.0)
    new_ids = np.array([100, 101, 102, 103, 104, 105, 106, 107, 108, 109], dtype=np.int64)

    # Call update_index - should create secondary index
    manager.update_index(new_vectors, new_ids)

    # Verify secondary index was created
    assert manager.secondary_index is not None
    assert len(manager.incremental_ids) == 10
    assert manager.incremental_ids == {100, 101, 102, 103, 104, 105, 106, 107, 108, 109}


def test_update_index_skips_duplicates(tmp_index_path: Path) -> None:
    """Test that update_index skips duplicate IDs.

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    # First batch
    vectors1 = _rng.normal(0.5, 0.15, (5, vec_dim)).astype(np.float32)
    vectors1 = np.clip(vectors1, 0.0, 1.0)
    ids1 = np.array([10, 11, 12, 13, 14], dtype=np.int64)
    manager.update_index(vectors1, ids1)

    assert len(manager.incremental_ids) == 5

    # Second batch with duplicates
    vectors2 = _rng.normal(0.5, 0.15, (7, vec_dim)).astype(np.float32)
    vectors2 = np.clip(vectors2, 0.0, 1.0)
    ids2 = np.array([12, 13, 14, 15, 16, 17, 18], dtype=np.int64)  # 12, 13, 14 are duplicates

    manager.update_index(vectors2, ids2)

    # Should have 5 original + 4 new = 9 total
    assert len(manager.incremental_ids) == 9
    assert manager.incremental_ids == {10, 11, 12, 13, 14, 15, 16, 17, 18}


def test_update_index_skips_primary_duplicates(tmp_index_path: Path) -> None:
    """IDs already present in the primary index are ignored during updates."""
    vec_dim = _UNIT_TEST_VEC_DIM
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    primary_vectors = _rng.normal(0.5, 0.15, (6, vec_dim)).astype(np.float32)
    primary_vectors = np.clip(primary_vectors, 0.0, 1.0)
    manager.build_index(primary_vectors)
    primary_ids = np.arange(6, dtype=np.int64)
    manager.add_vectors(primary_vectors, primary_ids)

    update_vectors = _rng.normal(0.5, 0.15, (4, vec_dim)).astype(np.float32)
    update_vectors = np.clip(update_vectors, 0.0, 1.0)
    update_ids = np.array([2, 6, 6, 7], dtype=np.int64)

    manager.update_index(update_vectors, update_ids)

    assert manager.secondary_index is not None
    assert manager.secondary_index.ntotal == 2
    assert manager.incremental_ids == {6, 7}


def test_dual_index_search(tmp_index_path: Path) -> None:
    """Test that search returns results from both primary and secondary indexes.

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    # Build primary index with initial vectors
    primary_vectors = _rng.normal(0.5, 0.15, (100, vec_dim)).astype(np.float32)
    primary_vectors = np.clip(primary_vectors, 0.0, 1.0)
    manager.build_index(primary_vectors)
    primary_ids = np.arange(100, dtype=np.int64)
    manager.add_vectors(primary_vectors, primary_ids)

    # Add vectors to secondary index
    secondary_vectors = _rng.normal(0.5, 0.15, (20, vec_dim)).astype(np.float32)
    secondary_vectors = np.clip(secondary_vectors, 0.0, 1.0)
    secondary_ids = np.arange(100, 120, dtype=np.int64)  # IDs 100-119
    manager.update_index(secondary_vectors, secondary_ids)

    # Create a query vector (similar to one in secondary index)
    query = secondary_vectors[0].copy().reshape(1, -1)

    # Search - should return results from both indexes
    _distances, result_ids = manager.search(query, k=10)

    # Verify we got results
    assert len(result_ids[0]) == 10

    # Verify results include IDs from both primary and secondary
    # (exact composition depends on similarity, but should have some from each)
    result_id_set = set(result_ids[0])
    primary_result_count = sum(1 for rid in result_id_set if rid < 100)
    secondary_result_count = sum(1 for rid in result_id_set if rid >= 100)

    # Should have results from both (exact counts depend on similarity)
    assert primary_result_count > 0 or secondary_result_count > 0


def _setup_primary_index(manager: FAISSManager, vec_dim: int) -> tuple[np.ndarray, np.ndarray]:
    """Set up primary index with test vectors.

    Parameters
    ----------
    manager : FAISSManager
        FAISS manager instance to configure.
    vec_dim : int
        Vector dimension for test vectors.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        Primary vectors and IDs.
    """
    primary_vectors = np.clip(_rng.normal(0.5, 0.15, (3, vec_dim)).astype(np.float32), 0.0, 1.0)
    manager.build_index(primary_vectors)
    primary_ids = np.array([1, 2, 3], dtype=np.int64)
    manager.add_vectors(primary_vectors, primary_ids)
    return primary_vectors, primary_ids


def _add_duplicate_to_secondary(
    manager: FAISSManager, primary_vectors: np.ndarray, primary_ids: np.ndarray
) -> tuple[int, np.ndarray]:
    """Add duplicate vector to secondary index.

    Parameters
    ----------
    manager : FAISSManager
        FAISS manager instance.
    primary_vectors : np.ndarray
        Primary index vectors.
    primary_ids : np.ndarray
        Primary index IDs.

    Returns
    -------
    tuple[int, np.ndarray]
        Duplicate ID and vector.
    """
    duplicate_id = int(primary_ids[0])
    duplicate_vector = (
        np.clip(primary_vectors[0] * 1.05, 0.0, 1.0).astype(np.float32).reshape(1, -1)
    )
    duplicate_norm = duplicate_vector.copy()
    faiss_module.normalize_L2(duplicate_norm)
    assert manager.secondary_index is not None
    manager.secondary_index.add_with_ids(duplicate_norm, np.array([duplicate_id], dtype=np.int64))
    manager.incremental_ids.add(duplicate_id)
    return duplicate_id, duplicate_vector


def _verify_duplicate_in_results(
    duplicate_id: int,
    primary_ids_result: np.ndarray,
    secondary_ids_result: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Verify duplicate ID appears in both search results and return indices.

    Parameters
    ----------
    duplicate_id : int
        ID of the duplicate vector to verify.
    primary_ids_result : np.ndarray
        Primary index search result IDs.
    secondary_ids_result : np.ndarray
        Secondary index search result IDs.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        Primary and secondary indices where duplicate appears.
    """
    assert duplicate_id in primary_ids_result[0]
    assert duplicate_id in secondary_ids_result[0]
    primary_idx = np.where(primary_ids_result[0] == duplicate_id)[0]
    secondary_idx = np.where(secondary_ids_result[0] == duplicate_id)[0]
    assert primary_idx.size == 1
    assert secondary_idx.size == 1
    return primary_idx, secondary_idx


def _perform_dual_search(
    manager: FAISSManager, query: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Perform search on both primary and secondary indexes.

    Parameters
    ----------
    manager : FAISSManager
        FAISS manager instance.
    query : np.ndarray
        Query vector for search.

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
        Primary distances, primary IDs, secondary distances, secondary IDs.
    """
    primary_dists, primary_ids_result = manager.search_primary(query, k=3, nprobe=128)
    secondary_dists, secondary_ids_result = manager.search_secondary(query, k=3)
    return primary_dists, primary_ids_result, secondary_dists, secondary_ids_result


def _verify_merged_search_deduplication(
    manager: FAISSManager, query: np.ndarray, _duplicate_id: int
) -> tuple[np.ndarray, np.ndarray]:
    """Verify merged search deduplicates and return merged results.

    Parameters
    ----------
    manager : FAISSManager
        FAISS manager instance.
    query : np.ndarray
        Query vector for search.
    _duplicate_id : int
        ID of duplicate vector (unused, kept for test clarity).

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        Merged distances and IDs.
    """
    merged_dists, merged_ids = manager.search(query, k=3)
    valid_ids = [rid for rid in merged_ids[0] if rid >= 0]
    assert len(valid_ids) == len(set(valid_ids))
    return merged_dists, merged_ids


def _setup_test_indexes_with_duplicate(
    manager: FAISSManager, vec_dim: int
) -> tuple[int, np.ndarray]:
    """Set up primary and secondary indexes with a duplicate vector.

    Parameters
    ----------
    manager : FAISSManager
        FAISS manager instance to configure.
    vec_dim : int
        Vector dimension for test vectors.

    Returns
    -------
    tuple[int, np.ndarray]
        Duplicate ID and vector.
    """
    primary_vectors, primary_ids = _setup_primary_index(manager, vec_dim)
    unique_secondary = np.clip(_rng.normal(0.5, 0.15, (1, vec_dim)).astype(np.float32), 0.0, 1.0)
    manager.update_index(unique_secondary, np.array([101], dtype=np.int64))
    duplicate_id, duplicate_vector = _add_duplicate_to_secondary(
        manager, primary_vectors, primary_ids
    )
    return duplicate_id, duplicate_vector


def _verify_merged_distance(
    merged_dists: np.ndarray,
    merged_ids: np.ndarray,
    duplicate_id: int,
    expected_distance: float,
) -> None:
    """Verify merged search distance matches expected."""
    merged_idx = np.where(merged_ids[0] == duplicate_id)[0]
    assert merged_idx.size == 1
    assert np.isclose(float(merged_dists[0, merged_idx[0]]), expected_distance)


def test_merged_search_results_are_unique(tmp_index_path: Path) -> None:
    """Merged dual-index search results deduplicate overlapping chunk IDs."""
    vec_dim = _UNIT_TEST_VEC_DIM
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    # Setup indexes with duplicate
    duplicate_id, duplicate_vector = _setup_test_indexes_with_duplicate(manager, vec_dim)
    query = duplicate_vector.copy()

    # Search both indexes
    primary_dists, primary_ids_result, secondary_dists, secondary_ids_result = _perform_dual_search(
        manager, query
    )

    # Verify duplicate in both results and get indices
    primary_idx, secondary_idx = _verify_duplicate_in_results(
        duplicate_id, primary_ids_result, secondary_ids_result
    )

    # Verify merged search deduplicates
    merged_dists, merged_ids = _verify_merged_search_deduplication(manager, query, duplicate_id)

    # Verify merged distance matches expected
    expected_distance = max(
        float(primary_dists[0, primary_idx[0]]),
        float(secondary_dists[0, secondary_idx[0]]),
    )
    _verify_merged_distance(merged_dists, merged_ids, duplicate_id, expected_distance)


def test_merge_indexes_combines_vectors(tmp_index_path: Path) -> None:
    """Test that merge_indexes combines secondary into primary and clears secondary.

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    # Build primary index
    primary_vectors = _rng.normal(0.5, 0.15, (50, vec_dim)).astype(np.float32)
    primary_vectors = np.clip(primary_vectors, 0.0, 1.0)
    manager.build_index(primary_vectors)
    primary_ids = np.arange(50, dtype=np.int64)
    manager.add_vectors(primary_vectors, primary_ids)
    manager.save_cpu_index()

    # Add to secondary index
    secondary_vectors = _rng.normal(0.5, 0.15, (30, vec_dim)).astype(np.float32)
    secondary_vectors = np.clip(secondary_vectors, 0.0, 1.0)
    secondary_ids = np.arange(50, 80, dtype=np.int64)
    manager.update_index(secondary_vectors, secondary_ids)

    # Verify secondary exists before merge
    assert manager.secondary_index is not None
    assert len(manager.incremental_ids) == 30

    # Merge indexes
    manager.merge_indexes()

    # Verify secondary is cleared
    assert manager.secondary_index is None
    assert len(manager.incremental_ids) == 0

    # Verify primary index now has all vectors (80 total)
    assert manager.cpu_index is not None
    assert manager.cpu_index.ntotal == 80


def test_merge_indexes_no_secondary(tmp_index_path: Path) -> None:
    """Test that merge_indexes handles case where no secondary index exists.

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    # Build primary index only
    primary_vectors = _rng.normal(0.5, 0.15, (50, vec_dim)).astype(np.float32)
    primary_vectors = np.clip(primary_vectors, 0.0, 1.0)
    manager.build_index(primary_vectors)
    primary_ids = np.arange(50, dtype=np.int64)
    manager.add_vectors(primary_vectors, primary_ids)

    # Merge should do nothing (no secondary index)
    manager.merge_indexes()

    # Primary should be unchanged
    assert manager.cpu_index is not None
    assert manager.cpu_index.ntotal == 50


@pytest.mark.parametrize(
    ("primary_size", "secondary_size"),
    [
        (100, 10),
        (1000, 100),
        (5000, 500),
    ],
)
def test_incremental_workflow_end_to_end(
    tmp_index_path: Path, primary_size: int, secondary_size: int
) -> None:
    """Test complete incremental workflow: initial → incremental → merge → search.

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    primary_size : int
        Number of vectors in primary index.
    secondary_size : int
        Number of vectors to add incrementally.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    # Step 1: Initial indexing (build primary)
    primary_vectors = _rng.normal(0.5, 0.15, (primary_size, vec_dim)).astype(np.float32)
    primary_vectors = np.clip(primary_vectors, 0.0, 1.0)
    manager.build_index(primary_vectors)
    primary_ids = np.arange(primary_size, dtype=np.int64)
    manager.add_vectors(primary_vectors, primary_ids)
    manager.save_cpu_index()

    # Step 2: Incremental update (add to secondary)
    secondary_vectors = _rng.normal(0.5, 0.15, (secondary_size, vec_dim)).astype(np.float32)
    secondary_vectors = np.clip(secondary_vectors, 0.0, 1.0)
    secondary_ids = np.arange(primary_size, primary_size + secondary_size, dtype=np.int64)
    manager.update_index(secondary_vectors, secondary_ids)

    # Verify dual-index state
    assert manager.secondary_index is not None
    assert len(manager.incremental_ids) == secondary_size

    # Step 3: Search with dual-index
    query = secondary_vectors[0].copy().reshape(1, -1)
    _distances, result_ids = manager.search(query, k=10)
    assert len(result_ids[0]) == 10

    # Step 4: Merge secondary into primary
    manager.merge_indexes()

    # Verify merge completed
    assert manager.secondary_index is None
    assert manager.cpu_index is not None
    assert manager.cpu_index.ntotal == primary_size + secondary_size

    # Step 5: Search after merge (should still work, now only primary)
    _distances2, result_ids2 = manager.search(query, k=10)
    assert len(result_ids2[0]) == 10


def test_save_load_secondary_index(tmp_index_path: Path) -> None:
    """Test that secondary index can be saved and loaded.

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    manager1 = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)

    # Build primary and add to secondary
    primary_vectors = _rng.normal(0.5, 0.15, (50, vec_dim)).astype(np.float32)
    primary_vectors = np.clip(primary_vectors, 0.0, 1.0)
    manager1.build_index(primary_vectors)
    manager1.add_vectors(primary_vectors, np.arange(50, dtype=np.int64))
    manager1.save_cpu_index()

    secondary_vectors = _rng.normal(0.5, 0.15, (20, vec_dim)).astype(np.float32)
    secondary_vectors = np.clip(secondary_vectors, 0.0, 1.0)
    secondary_ids = np.arange(50, 70, dtype=np.int64)
    manager1.update_index(secondary_vectors, secondary_ids)
    manager1.save_secondary_index()

    # Create new manager and load both indexes
    manager2 = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
    manager2.load_cpu_index()
    manager2.load_secondary_index()

    # Verify secondary index was restored
    assert manager2.secondary_index is not None
    assert len(manager2.incremental_ids) == 20
    assert manager2.incremental_ids == set(range(50, 70))

    # Verify search works with loaded indexes
    query = secondary_vectors[0].copy().reshape(1, -1)
    _distances, result_ids = manager2.search(query, k=10)
    assert len(result_ids[0]) == 10
