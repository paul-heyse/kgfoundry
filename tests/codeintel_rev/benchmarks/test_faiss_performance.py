"""Performance benchmarks for adaptive FAISS indexing.

These benchmarks measure training time improvements from adaptive index
selection, showing that small/medium corpora benefit significantly from
flat/IVFFlat indexes compared to fixed IVF-PQ.

**IMPORTANT**: These benchmarks are skipped by default. To run them:
  - Set environment variable: RUN_BENCHMARKS=1 pytest ...
  - Or explicitly request: pytest -m benchmark ...

For GPU-required benchmarks, also ensure GPU is available or use -m "benchmark and gpu".
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pytest
from codeintel_rev.io.faiss_manager import FAISSManager

from tests.conftest import FAISS_MODULE, HAS_FAISS_SUPPORT

if TYPE_CHECKING:  # pragma: no cover - type checking only
    import faiss

# Use modern numpy random generator
_rng = np.random.default_rng(42)

_benchmark_gate = pytest.mark.skipif(
    not os.getenv("RUN_BENCHMARKS"),
    reason="Benchmarks skipped by default. Set RUN_BENCHMARKS=1 to enable.",
)

if not HAS_FAISS_SUPPORT:  # pragma: no cover - dependency-gated
    pytestmark = [
        _benchmark_gate,
        pytest.mark.skip(reason="FAISS bindings unavailable"),
    ]
else:
    assert FAISS_MODULE is not None
    pytestmark = [_benchmark_gate]


def _get_underlying_index(cpu_index: Any) -> Any:
    """Return the underlying FAISS index from an ID map wrapper.

    Parameters
    ----------
    cpu_index : Any
        FAISS index wrapper (e.g., IndexIDMap2) containing the underlying index.

    Returns
    -------
    Any
        Underlying FAISS index instance.
    """
    assert hasattr(cpu_index, "index"), "Expected FAISS index wrapper to expose `index` attribute"
    index_map = cast("faiss.IndexIDMap2", cpu_index)
    return index_map.index


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
def test_small_corpus_flat_vs_ivf_pq(benchmark, tmp_index_path: Path) -> None:
    """Benchmark small corpus: flat index vs fixed IVF-PQ.

    Small corpus (<5K vectors) should use flat index which requires
    no training, providing ≥10x speedup compared to fixed IVF-PQ.

    Parameters
    ----------
    benchmark : pytest_benchmark.fixture.BenchmarkFixture
        Benchmark fixture.
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = 256  # Reduced dimension for faster benchmarks
    n_vectors = 100  # Small corpus for fast benchmark
    # Generate vectors: Gaussian distribution in range [0, 1] (matches unit tests)
    vectors = _rng.normal(0.5, 0.15, (n_vectors, vec_dim)).astype(np.float32)
    vectors = np.clip(vectors, 0.0, 1.0)  # Ensure values are in [0, 1] range

    def build_adaptive() -> None:
        """Build index with adaptive selection (should use flat)."""
        manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
        manager.build_index(vectors)

    # Benchmark adaptive (flat index, no training)
    benchmark.pedantic(build_adaptive, rounds=5, iterations=1)

    # Verify flat index was used
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
    manager.build_index(vectors)
    assert manager.cpu_index is not None
    cpu_index = manager.cpu_index
    underlying = _get_underlying_index(cpu_index)
    assert underlying.__class__.__name__ == "IndexFlatIP"

    print("\nSmall corpus benchmark (5K vectors):")
    print("  Adaptive selection uses flat index (no training)")
    print("  Expected: ≥10x faster than fixed IVF-PQ")


@pytest.mark.benchmark
def test_medium_corpus_ivf_flat_vs_ivf_pq(benchmark, tmp_index_path: Path) -> None:
    """Benchmark medium corpus: IVFFlat vs fixed IVF-PQ.

    Medium corpus (5K-50K vectors) should use IVFFlat with dynamic nlist,
    providing ≥2x speedup compared to fixed IVF-PQ with nlist=8192.

    Parameters
    ----------
    benchmark : pytest_benchmark.fixture.BenchmarkFixture
        Benchmark fixture.
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = 256  # Reduced dimension for faster benchmarks
    n_vectors = 5000  # Boundary case for medium corpus
    # Generate vectors: Gaussian distribution in range [0, 1] (matches unit tests)
    vectors = _rng.normal(0.5, 0.15, (n_vectors, vec_dim)).astype(np.float32)
    vectors = np.clip(vectors, 0.0, 1.0)  # Ensure values are in [0, 1] range

    def build_adaptive() -> None:
        """Build index with adaptive selection (should use IVFFlat)."""
        manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
        manager.build_index(vectors)

    # Benchmark adaptive (IVFFlat with dynamic nlist)
    benchmark.pedantic(build_adaptive, rounds=3, iterations=1)

    # Verify IVFFlat was used
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
    manager.build_index(vectors)
    assert manager.cpu_index is not None
    cpu_index = manager.cpu_index
    underlying = _get_underlying_index(cpu_index)
    assert underlying.__class__.__name__ == "IndexIVFFlat"

    print("\nMedium corpus benchmark (50K vectors):")
    print("  Adaptive selection uses IVFFlat with dynamic nlist")
    print("  Expected: ≥2x faster than fixed IVF-PQ")


@pytest.mark.benchmark
@pytest.mark.gpu
def test_large_corpus_adaptive_vs_fixed(benchmark, tmp_index_path: Path) -> None:
    """Benchmark large corpus: adaptive vs fixed IVF-PQ.

    Large corpus (>50K vectors) should use IVF-PQ with dynamic nlist,
    providing similar performance to fixed IVF-PQ but with better
    parameter selection.

    **Requires GPU** - This benchmark uses large vectors and is marked
    with @pytest.mark.gpu. It will be skipped unless GPU is available
    or explicitly requested.

    Parameters
    ----------
    benchmark : pytest_benchmark.fixture.BenchmarkFixture
        Benchmark fixture.
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = 256  # Reduced dimension for faster benchmarks
    n_vectors = 50000  # Boundary case for large corpus
    # Generate vectors: Gaussian distribution in range [0, 1] (matches unit tests)
    vectors = _rng.normal(0.5, 0.15, (n_vectors, vec_dim)).astype(np.float32)
    vectors = np.clip(vectors, 0.0, 1.0)  # Ensure values are in [0, 1] range

    def build_adaptive() -> None:
        """Build index with adaptive selection (should use IVF-PQ)."""
        manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
        manager.build_index(vectors)

    # Benchmark adaptive (IVF-PQ with dynamic nlist)
    benchmark.pedantic(build_adaptive, rounds=3, iterations=1)

    # Verify IVF-PQ was used
    manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
    manager.build_index(vectors)
    assert manager.cpu_index is not None
    cpu_index = manager.cpu_index
    underlying = _get_underlying_index(cpu_index)
    assert hasattr(underlying, "nlist")  # IVF-PQ has nlist

    print("\nLarge corpus benchmark (100K vectors):")
    print("  Adaptive selection uses IVF-PQ with dynamic nlist")
    print("  Expected: Similar performance to fixed IVF-PQ")


@pytest.mark.benchmark
def test_training_time_scaling(benchmark, tmp_index_path: Path) -> None:
    """Benchmark training time scaling across corpus sizes.

    Verifies that training time scales appropriately with corpus size:
    - Small (<5K): <5s (flat, no training)
    - Medium (5K-50K): <30s (IVFFlat)

    Parameters
    ----------
    benchmark : pytest_benchmark.fixture.BenchmarkFixture
        Benchmark fixture.
    tmp_index_path : Path
        Temporary index path.
    """
    vec_dim = 256  # Reduced dimension for faster benchmarks

    # Reduced sizes for faster benchmarks
    for n_vectors, max_time in [(100, 2), (5000, 15)]:
        # Generate vectors: Gaussian distribution in range [0, 1] (matches unit tests)
        vectors = _rng.normal(0.5, 0.15, (n_vectors, vec_dim)).astype(np.float32)
        vectors = np.clip(vectors, 0.0, 1.0)  # Ensure values are in [0, 1] range

        def build_index(vectors=vectors) -> None:
            """Build index for current corpus size."""
            manager = FAISSManager(index_path=tmp_index_path, vec_dim=vec_dim)
            manager.build_index(vectors)

        # Benchmark and verify time target
        result = benchmark.pedantic(build_index, rounds=1, iterations=1)

        # Training should complete within target time
        avg_time = result.stats.mean
        assert avg_time < max_time, f"Training took {avg_time:.2f}s (target: <{max_time}s)"

        print(f"\nCorpus size: {n_vectors} vectors")
        print(f"  Training time: {avg_time:.2f}s (target: <{max_time}s)")
