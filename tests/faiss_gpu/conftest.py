from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from _pytest.config import Config

SEED = 1234


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register command-line options for GPU test behavior.

    Parameters
    ----------
    parser : pytest.Parser
        Pytest argument parser instance.

    Notes
    -----
    Adds `--gpu-strict` flag that causes GPU requirement failures to raise
    errors instead of skipping tests. Useful for CI environments where GPU
    availability is expected.
    """
    parser.addoption(
        "--gpu-strict", action="store_true", help="Fail instead of skip if GPU module is missing."
    )


@pytest.fixture(scope="session")
def rng() -> np.random.RandomState:
    """Provide a deterministic random number generator for test reproducibility.

    Returns
    -------
    np.random.RandomState
        RandomState instance seeded with a fixed value (1234) for consistent
        test data generation across runs.

    Notes
    -----
    Session-scoped fixture ensures all tests in the suite use the same RNG
    state, enabling deterministic vector generation for FAISS index testing.
    """
    return np.random.RandomState(SEED)


@pytest.fixture(scope="session")
def dims() -> int:
    """Provide the dimensionality for test vectors.

    Returns
    -------
    int
        Vector dimension (64) used consistently across all FAISS GPU tests.

    Notes
    -----
    Fixed dimension ensures test vectors are compatible across different index
    types (Flat, IVF) and transfer operations (CPU↔GPU roundtrips).
    """
    return 64


@pytest.fixture(scope="session")
def train_db(rng: np.random.RandomState, dims: int) -> np.ndarray:
    """Generate training database vectors for FAISS index construction.

    Parameters
    ----------
    rng : np.random.RandomState
        Seeded random number generator for reproducible vector generation.
    dims : int
        Vector dimensionality (64).

    Returns
    -------
    np.ndarray
        Array of shape (5000, 64) with dtype float32. First component includes
        a small monotonic offset to ensure non-uniformity for realistic ANN
        testing.

    Notes
    -----
    Time O(n*d); memory O(n*d). Deterministic given fixed seed. Used as the
    base dataset for building FAISS indexes (Flat, IVF) and validating GPU
    correctness against CPU baselines.
    """
    xb = rng.random_sample((5000, dims)).astype("float32")
    xb[:, 0] += np.arange(xb.shape[0]) / 1000.0
    return xb


@pytest.fixture(scope="session")
def query_db(rng: np.random.RandomState, dims: int) -> np.ndarray:
    """Generate query vectors for FAISS search operations.

    Parameters
    ----------
    rng : np.random.RandomState
        Seeded random number generator for reproducible vector generation.
    dims : int
        Vector dimensionality (64).

    Returns
    -------
    np.ndarray
        Array of shape (200, 64) with dtype float32. First component includes
        a small monotonic offset matching the pattern used in training vectors.

    Notes
    -----
    Time O(n*d); memory O(n*d). Deterministic given fixed seed. Used to
    exercise search paths (exact and approximate) and validate recall/accuracy
    metrics across CPU and GPU index implementations.
    """
    nq = 200
    xq = rng.random_sample((nq, dims)).astype("float32")
    xq[:, 0] += np.arange(nq) / 1000.0
    return xq


@pytest.fixture(scope="session")
def k() -> int:
    """Provide the number of nearest neighbors to retrieve per query.

    Returns
    -------
    int
        Top-k value (10) used consistently across all search operations.

    Notes
    -----
    Fixed k ensures comparable result sets across different index types and
    enables deterministic assertion checks (distance ordering, neighbor IDs).
    """
    return 10


@pytest.fixture(scope="session")
def gpu_require(pytestconfig: Config) -> Callable[[object, str], None]:
    """Return a helper function that skips or fails tests when GPU requirements are unmet.

    Extended Summary
    ----------------
    This fixture provides a session-scoped callback that enforces GPU availability
    checks in FAISS GPU tests. It integrates with pytest's command-line options
    (`--gpu-strict`) to control failure behavior: by default, unmet requirements
    cause test skips (allowing CI to run on CPU-only hosts), but with `--gpu-strict`
    enabled, failures raise errors instead. This pattern enables graceful degradation
    while supporting strict validation in GPU-enabled environments.

    Parameters
    ----------
    pytestconfig : Config
        Pytest configuration object providing access to command-line options.
        Used to read the `gpu_strict` flag that controls skip vs. fail behavior.

    Returns
    -------
    Callable[[object, str], None]
        Callback function that accepts:
        - `condition` (object): Truthy value indicates GPU requirement is met.
          Falsy value triggers skip/fail.
        - `reason` (str): Human-readable explanation for the skip/fail action.

        Returns None; side effect is either no-op (if condition is True) or
        calls `pytest.skip()` or `pytest.fail()` based on `--gpu-strict` flag.
        These functions raise exceptions internally to signal skip/fail to pytest.

    Notes
    -----
    • Thread-safety: Safe for concurrent test execution; no shared mutable state.
    • Performance: O(1) per call; negligible overhead.
    • Design rationale: Centralizes GPU requirement logic to avoid duplication
      across test functions. The callback pattern allows tests to express requirements
      declaratively (e.g., `gpu_require(FAISS.get_num_gpus() > 0, "No GPUs visible")`).
    • Exception behavior: When `condition` is falsy, the callback calls `pytest.skip()`
      (default) or `pytest.fail()` (if `--gpu-strict` is set), which raise exceptions
      that pytest catches to mark tests as skipped or failed.

    Examples
    --------
    >>> # In a test function:
    >>> def test_gpu_index_construction(gpu_require):
    ...     gpu_require(FAISS.get_num_gpus() > 0, "No GPUs available")
    ...     # Test proceeds only if GPU is available
    ...     index = FAISS.GpuIndexFlatL2(...)
    """

    def _check(condition: object, reason: str) -> None:
        if condition:
            return
        if pytestconfig.getoption("gpu_strict", default=False):
            pytest.fail(reason)
        pytest.skip(reason)

    return _check
