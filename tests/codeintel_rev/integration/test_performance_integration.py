"""End-to-end performance integration tests.

Tests measure complete system performance across all components:
- Full indexing pipeline performance
- Search latency (p50, p95, p99)
- Concurrent search throughput
- Git operations performance

These tests verify that performance optimizations deliver measurable improvements.
"""

from __future__ import annotations

import asyncio
import statistics
from pathlib import Path

import numpy as np
import pytest
from tests.conftest import HAS_FAISS_SUPPORT

if HAS_FAISS_SUPPORT:
    from codeintel_rev.io.faiss_manager import FAISSManager
else:  # pragma: no cover - dependency-gated
    pytestmark = pytest.mark.skip(reason="FAISS bindings unavailable on this host")

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


@pytest.mark.integration
@pytest.mark.performance
def test_indexing_pipeline_performance(tmp_index_path: Path) -> None:
    """Test full indexing pipeline performance with adaptive index selection.

    Measures total time to build an index for a representative corpus size
    and verifies that adaptive indexing is used.

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    n_vectors = 5000  # Medium corpus - should use IVFFlat

    import time

    vectors = _rng.normal(0.5, 0.15, (n_vectors, vec_dim)).astype(np.float32)
    vectors = np.clip(vectors, 0.0, 1.0)

    start_time = time.time()

    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
    manager.build_index(vectors)
    ids = np.arange(n_vectors, dtype=np.int64)
    manager.add_vectors(vectors, ids)
    manager.save_cpu_index()

    elapsed = time.time() - start_time

    # Verify adaptive indexing was used (IVFFlat for medium corpus)
    assert manager.cpu_index is not None
    underlying = manager.cpu_index.index  # type: ignore[attr-defined]
    assert hasattr(underlying, "nlist"), "Expected IVFFlat index for medium corpus"

    # Indexing should complete in reasonable time (<5 minutes for 5K vectors)
    assert elapsed < 300, f"Indexing took {elapsed:.2f}s (target: <300s)"

    print(f"\nIndexing pipeline performance ({n_vectors} vectors):")
    print(f"  Total time: {elapsed:.2f}s")
    print("  Index type: IVFFlat (adaptive selection)")


@pytest.mark.integration
@pytest.mark.performance
def test_search_latency_percentiles(tmp_index_path: Path) -> None:
    """Test search latency percentiles (p50, p95, p99).

    Measures search latency across multiple queries and calculates percentiles
    to understand typical and tail latency characteristics.

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    n_vectors = 2000
    n_queries = 100

    # Build index
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
    vectors = _rng.normal(0.5, 0.15, (n_vectors, vec_dim)).astype(np.float32)
    vectors = np.clip(vectors, 0.0, 1.0)
    manager.build_index(vectors)
    manager.add_vectors(vectors, np.arange(n_vectors, dtype=np.int64))

    # Generate query vectors
    queries = _rng.normal(0.5, 0.15, (n_queries, vec_dim)).astype(np.float32)
    queries = np.clip(queries, 0.0, 1.0)

    import time

    latencies = []
    for query in queries:
        start = time.time()
        _distances, _ids = manager.search(query, k=50)
        latencies.append(time.time() - start)

    p50 = statistics.median(latencies)
    p95 = np.percentile(latencies, 95)
    p99 = np.percentile(latencies, 99)

    print(f"\nSearch latency percentiles ({n_queries} queries, {n_vectors} vectors):")
    print(f"  p50: {p50 * 1000:.2f}ms")
    print(f"  p95: {p95 * 1000:.2f}ms")
    print(f"  p99: {p99 * 1000:.2f}ms")

    # p95 should be reasonable (<100ms for 2K vectors)
    assert p95 < 0.1, f"p95 latency {p95 * 1000:.2f}ms exceeds target (100ms)"


@pytest.mark.integration
@pytest.mark.performance
@pytest.mark.asyncio
async def test_concurrent_search_throughput(tmp_index_path: Path) -> None:
    """Test concurrent search throughput.

    Measures search throughput with concurrent requests to verify that
    async operations enable high concurrency without thread exhaustion.

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    n_vectors = 1000
    n_concurrent = 50

    # Build index
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
    vectors = _rng.normal(0.5, 0.15, (n_vectors, vec_dim)).astype(np.float32)
    vectors = np.clip(vectors, 0.0, 1.0)
    manager.build_index(vectors)
    manager.add_vectors(vectors, np.arange(n_vectors, dtype=np.int64))

    # Generate query vectors
    queries = _rng.normal(0.5, 0.15, (n_concurrent, vec_dim)).astype(np.float32)
    queries = np.clip(queries, 0.0, 1.0)

    async def search_async(query: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Perform search asynchronously.

        Parameters
        ----------
        query : np.ndarray
            Query vector.

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            Search results (distances, ids).
        """
        return await asyncio.to_thread(manager.search, query, 50)

    import time

    start_time = time.time()
    tasks = [search_async(query) for query in queries]
    results = await asyncio.gather(*tasks)
    elapsed = time.time() - start_time

    throughput = n_concurrent / elapsed

    # Verify all searches completed
    assert len(results) == n_concurrent

    print(f"\nConcurrent search throughput ({n_concurrent} concurrent queries):")
    print(f"  Total time: {elapsed:.2f}s")
    print(f"  Throughput: {throughput:.1f} queries/second")

    # Throughput should be reasonable (>10 QPS for concurrent searches)
    assert throughput > 10, f"Throughput {throughput:.1f} QPS below target (10 QPS)"


@pytest.mark.integration
@pytest.mark.performance
def test_dual_index_search_overhead(tmp_index_path: Path) -> None:
    """Test dual-index search overhead compared to single-index search.

    Measures the performance overhead of searching both primary and secondary
    indexes compared to searching only the primary index.

    Parameters
    ----------
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = _UNIT_TEST_VEC_DIM
    primary_size = 1000
    secondary_size = 200

    # Build primary index
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
    primary_vectors = _rng.normal(0.5, 0.15, (primary_size, vec_dim)).astype(np.float32)
    primary_vectors = np.clip(primary_vectors, 0.0, 1.0)
    manager.build_index(primary_vectors)
    manager.add_vectors(primary_vectors, np.arange(primary_size, dtype=np.int64))

    # Create query and measure single-index search
    query = _rng.normal(0.5, 0.15, (1, vec_dim)).astype(np.float32)
    query = np.clip(query, 0.0, 1.0)

    import time

    start = time.time()
    _distances1, _ids1 = manager.search(query, k=50)
    single_time = time.time() - start

    # Add secondary index and measure dual-index search
    secondary_vectors = _rng.normal(0.5, 0.15, (secondary_size, vec_dim)).astype(np.float32)
    secondary_vectors = np.clip(secondary_vectors, 0.0, 1.0)
    manager.update_index(
        secondary_vectors, np.arange(primary_size, primary_size + secondary_size, dtype=np.int64)
    )

    start = time.time()
    _distances2, _ids2 = manager.search(query, k=50)
    dual_time = time.time() - start

    overhead_pct = ((dual_time - single_time) / single_time) * 100 if single_time > 0 else 0

    print("\nDual-index search overhead:")
    print(f"  Single-index: {single_time * 1000:.2f}ms")
    print(f"  Dual-index: {dual_time * 1000:.2f}ms")
    print(f"  Overhead: {(dual_time - single_time) * 1000:.2f}ms ({overhead_pct:.1f}%)")

    # Overhead should be minimal (<50% increase)
    assert overhead_pct < 50, f"Dual-index overhead {overhead_pct:.1f}% exceeds target (50%)"
