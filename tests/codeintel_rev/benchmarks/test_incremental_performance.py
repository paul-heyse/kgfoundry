"""Performance benchmarks for incremental FAISS indexing.

These benchmarks measure the speed improvement from incremental updates compared
to full rebuilds. Incremental updates should be orders of magnitude faster
(seconds vs hours) for adding new chunks to existing indexes.

**IMPORTANT**: These benchmarks are skipped by default. To run them:
  - Set environment variable: RUN_BENCHMARKS=1 pytest ...
  - Or explicitly request: pytest -m benchmark ...
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from codeintel_rev.io.faiss_manager import FAISSManager

from tests.conftest import HAS_FAISS_SUPPORT

# Use modern numpy random generator
_rng = np.random.default_rng(42)

# Gate benchmarks behind opt-in environment variable
_benchmark_gate = pytest.mark.skipif(
    not os.getenv("RUN_BENCHMARKS"),
    reason="Benchmarks skipped by default. Set RUN_BENCHMARKS=1 to enable.",
)

if not HAS_FAISS_SUPPORT:  # pragma: no cover - dependency-gated
    pytestmark = [_benchmark_gate, pytest.mark.skip(reason="FAISS bindings unavailable")]
else:
    pytestmark = [_benchmark_gate]


@pytest.fixture
def tmp_index_path(tmp_path: Path) -> Path:
    """Create a temporary index path for benchmarking.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory fixture.

    Returns
    -------
    Path
        Path to temporary FAISS index file.
    """
    return tmp_path / "benchmark_index.faiss"


@pytest.mark.benchmark
def test_incremental_update_speed(benchmark, tmp_index_path: Path) -> None:
    """Benchmark incremental update speed for adding new chunks.

    Measures the time to add new vectors to a secondary index vs full rebuild.
    Incremental updates should complete in seconds, while full rebuilds take
    much longer (especially for large indexes).

    Parameters
    ----------
    benchmark : pytest_benchmark.fixture.BenchmarkFixture
        Benchmark fixture.
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = 256  # Reduced dimension for faster benchmarks
    primary_size = 1000  # Existing index size
    new_size = 100  # New chunks to add

    # Build initial primary index
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
    primary_vectors = _rng.normal(0.5, 0.15, (primary_size, vec_dim)).astype(np.float32)
    primary_vectors = np.clip(primary_vectors, 0.0, 1.0)
    manager.build_index(primary_vectors)
    manager.add_vectors(primary_vectors, np.arange(primary_size, dtype=np.int64))
    manager.save_cpu_index()

    # Prepare new vectors for incremental update
    new_vectors = _rng.normal(0.5, 0.15, (new_size, vec_dim)).astype(np.float32)
    new_vectors = np.clip(new_vectors, 0.0, 1.0)
    new_ids = np.arange(primary_size, primary_size + new_size, dtype=np.int64)

    def incremental_update() -> None:
        """Add new vectors to secondary index."""
        manager2 = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
        manager2.load_cpu_index()
        manager2.update_index(new_vectors, new_ids)

    # Benchmark incremental update
    result = benchmark.pedantic(incremental_update, rounds=5, iterations=1)

    # Verify incremental update completes quickly (<60s for 100 vectors)
    avg_time = result.stats.mean
    assert avg_time < 60.0, f"Incremental update took {avg_time:.2f}s (target: <60s)"

    print(f"\nIncremental update benchmark ({new_size} vectors):")
    print(f"  Average time: {avg_time:.2f}s")
    print("  Expected: <60s (orders of magnitude faster than full rebuild)")


@pytest.mark.benchmark
def test_full_rebuild_vs_incremental(benchmark, tmp_index_path: Path) -> None:
    """Compare full rebuild time vs incremental update time.

    Demonstrates that incremental updates are much faster than rebuilding
    the entire index, especially as the index grows.

    Parameters
    ----------
    benchmark : pytest_benchmark.fixture.BenchmarkFixture
        Benchmark fixture.
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = 256  # Reduced dimension for faster benchmarks
    primary_size = 5000  # Existing index size
    new_size = 500  # New chunks to add

    # Build initial primary index
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
    primary_vectors = _rng.normal(0.5, 0.15, (primary_size, vec_dim)).astype(np.float32)
    primary_vectors = np.clip(primary_vectors, 0.0, 1.0)
    manager.build_index(primary_vectors)
    manager.add_vectors(primary_vectors, np.arange(primary_size, dtype=np.int64))
    manager.save_cpu_index()

    # Prepare combined vectors for full rebuild
    new_vectors = _rng.normal(0.5, 0.15, (new_size, vec_dim)).astype(np.float32)
    new_vectors = np.clip(new_vectors, 0.0, 1.0)
    all_vectors = np.vstack([primary_vectors, new_vectors])
    all_ids = np.arange(primary_size + new_size, dtype=np.int64)

    def full_rebuild() -> None:
        """Rebuild entire index from scratch."""
        manager2 = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
        manager2.build_index(all_vectors)
        manager2.add_vectors(all_vectors, all_ids)

    def incremental_update() -> None:
        """Add new vectors incrementally."""
        manager3 = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
        manager3.load_cpu_index()
        new_ids_only = np.arange(primary_size, primary_size + new_size, dtype=np.int64)
        manager3.update_index(new_vectors, new_ids_only)

    # Benchmark both approaches
    rebuild_result = benchmark.pedantic(full_rebuild, rounds=3, iterations=1)
    incremental_result = benchmark.pedantic(incremental_update, rounds=5, iterations=1)

    rebuild_time = rebuild_result.stats.mean
    incremental_time = incremental_result.stats.mean
    speedup = rebuild_time / incremental_time if incremental_time > 0 else float("inf")

    print(f"\nFull rebuild vs incremental update ({new_size} new vectors):")
    print(f"  Full rebuild: {rebuild_time:.2f}s")
    print(f"  Incremental: {incremental_time:.2f}s")
    print(f"  Speedup: {speedup:.1f}x")

    # Incremental should be faster (at least 2x, often much more)
    assert incremental_time < rebuild_time, (
        f"Incremental update ({incremental_time:.2f}s) should be faster than "
        f"full rebuild ({rebuild_time:.2f}s)"
    )


@pytest.mark.benchmark
def test_merge_indexes_performance(benchmark, tmp_index_path: Path) -> None:
    """Benchmark merge_indexes performance.

    Measures the time to merge secondary index into primary. This operation
    is expensive (requires rebuilding primary) but should be faster than
    a full rebuild from scratch since vectors are already extracted.

    Parameters
    ----------
    benchmark : pytest_benchmark.fixture.BenchmarkFixture
        Benchmark fixture.
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = 256  # Reduced dimension for faster benchmarks
    primary_size = 1000
    secondary_size = 200

    # Build primary and secondary indexes
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
    primary_vectors = _rng.normal(0.5, 0.15, (primary_size, vec_dim)).astype(np.float32)
    primary_vectors = np.clip(primary_vectors, 0.0, 1.0)
    manager.build_index(primary_vectors)
    manager.add_vectors(primary_vectors, np.arange(primary_size, dtype=np.int64))
    manager.save_cpu_index()

    secondary_vectors = _rng.normal(0.5, 0.15, (secondary_size, vec_dim)).astype(np.float32)
    secondary_vectors = np.clip(secondary_vectors, 0.0, 1.0)
    manager.update_index(
        secondary_vectors, np.arange(primary_size, primary_size + secondary_size, dtype=np.int64)
    )

    def merge_indexes() -> None:
        """Merge secondary index into primary."""
        manager2 = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
        manager2.load_cpu_index()
        # Load secondary
        manager2.load_secondary_index()
        manager2.merge_indexes()

    # Benchmark merge
    result = benchmark.pedantic(merge_indexes, rounds=3, iterations=1)

    avg_time = result.stats.mean
    print(f"\nMerge indexes benchmark ({secondary_size} vectors):")
    print(f"  Average time: {avg_time:.2f}s")
    print("  Note: Merge is expensive but faster than full rebuild")


@pytest.mark.benchmark
def test_dual_index_search_performance(benchmark, tmp_index_path: Path) -> None:
    """Benchmark dual-index search performance.

    Measures search latency when both primary and secondary indexes exist.
    Dual-index search should have minimal overhead compared to single-index search.

    Parameters
    ----------
    benchmark : pytest_benchmark.fixture.BenchmarkFixture
        Benchmark fixture.
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = 256  # Reduced dimension for faster benchmarks
    primary_size = 2000
    secondary_size = 300

    # Build primary and secondary indexes
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
    primary_vectors = _rng.normal(0.5, 0.15, (primary_size, vec_dim)).astype(np.float32)
    primary_vectors = np.clip(primary_vectors, 0.0, 1.0)
    manager.build_index(primary_vectors)
    manager.add_vectors(primary_vectors, np.arange(primary_size, dtype=np.int64))

    secondary_vectors = _rng.normal(0.5, 0.15, (secondary_size, vec_dim)).astype(np.float32)
    secondary_vectors = np.clip(secondary_vectors, 0.0, 1.0)
    manager.update_index(
        secondary_vectors, np.arange(primary_size, primary_size + secondary_size, dtype=np.int64)
    )

    # Create query vector
    query = _rng.normal(0.5, 0.15, (1, vec_dim)).astype(np.float32)
    query = np.clip(query, 0.0, 1.0)

    def dual_index_search() -> None:
        """Search with both primary and secondary indexes."""
        _distances, _ids = manager.search(query, k=50)

    # Benchmark dual-index search
    result = benchmark.pedantic(dual_index_search, rounds=10, iterations=1)

    avg_time = result.stats.mean
    print("\nDual-index search benchmark:")
    print(f"  Average latency: {avg_time * 1000:.2f}ms")
    print("  Expected: Minimal overhead vs single-index search")
