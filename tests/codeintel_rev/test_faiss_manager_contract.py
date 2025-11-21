"""FAISS manager contract tests: runtime tuning, adaptive selection, incremental merge."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from types import ModuleType
from typing import cast

import numpy as np
import pytest
from codeintel_rev.io.faiss_manager import FAISSManager

from tests._helpers import assertions
from tests._helpers.faiss import HAS_FAISS, build_manager, faiss_module, random_vectors

if not HAS_FAISS:  # pragma: no cover - dependency-gated
    pytestmark = pytest.mark.skip(reason="FAISS bindings unavailable on this host")
elif faiss_module is None:  # pragma: no cover - dependency-gated
    pytest.skip("FAISS bindings unavailable on this host", allow_module_level=True)
else:
    faiss = cast("ModuleType", faiss_module)

_UNIT_TEST_VEC_DIM = 256


@pytest.fixture
def manager(tmp_path: Path) -> FAISSManager:
    """Return a FAISSManager instance for tests.

    Returns
    -------
    FAISSManager
        Manager configured with a temporary index path.
    """
    return build_manager(tmp_path / "index.faiss", vec_dim=_UNIT_TEST_VEC_DIM)


def test_runtime_tuning_apply_reset(manager: FAISSManager) -> None:
    """Runtime tuning apply/describe/reset stays consistent."""
    snapshot = manager.runtime.get_runtime_tuning()
    overrides = cast("dict[str, object]", snapshot["overrides"])
    assertions.expect_mapping_equal(overrides, {})

    updated = manager.runtime.apply_runtime_tuning(nprobe=32, ef_search=64, k_factor=1.5)
    updated_overrides = cast("dict[str, object]", updated["overrides"])
    updated_active = cast("dict[str, object]", updated["active"])
    assertions.expect_equal(updated_overrides["nprobe"], 32)
    assertions.expect_equal(updated_active["nprobe"], 32)
    assertions.expect_equal(updated_active["efSearch"], 64)
    assertions.expect_almost_equal(cast("float", updated_active["k_factor"]), 1.5)

    reset = manager.runtime.reset_runtime_tuning()
    reset_overrides = cast("dict[str, object]", reset["overrides"])
    assertions.expect_mapping_equal(reset_overrides, {})


@pytest.mark.parametrize(
    ("n_vectors", "expected_type"),
    [
        (10, "IndexFlatIP"),
        (4999, "IndexFlatIP"),
        (5000, "IndexIVFFlat"),
        (10000, "IndexIVFFlat"),
    ],
)
def test_adaptive_index_selection(manager: FAISSManager, n_vectors: int, expected_type: str) -> None:
    """Adaptive selection chooses flat vs IVFFlat based on corpus size."""
    vectors = random_vectors(n_vectors, _UNIT_TEST_VEC_DIM)
    manager.build_index(vectors)

    cpu_index = manager.require_cpu_index()
    assertions.expect_true(
        isinstance(cpu_index, faiss.IndexIDMap2), reason="cpu_index should be wrapped"
    )
    underlying = getattr(cpu_index, "index", cpu_index)
    if hasattr(faiss, "downcast_index"):
        with suppress(AttributeError, RuntimeError):
            underlying = faiss.downcast_index(underlying)
    assertions.expect_equal(type(underlying).__name__, expected_type)


def test_incremental_update_and_merge(manager: FAISSManager) -> None:
    """Incremental updates create a secondary index and merge clears it."""
    primary_vectors = random_vectors(20, _UNIT_TEST_VEC_DIM)
    primary_ids = np.arange(primary_vectors.shape[0], dtype=np.int64)
    manager.build_index(primary_vectors)
    manager.add_vectors(primary_vectors, primary_ids)
    assertions.expect_true(manager.cpu_index is not None, reason="primary index should exist")

    secondary_vectors = random_vectors(5, _UNIT_TEST_VEC_DIM)
    secondary_ids = np.arange(100, 105, dtype=np.int64)
    manager.update_index(secondary_vectors, secondary_ids)
    assertions.expect_true(manager.secondary_index is not None, reason="secondary index should exist")
    assertions.expect_equal(manager.incremental_ids, set(secondary_ids.tolist()))

    # Search should include IDs from both indexes
    query = primary_vectors[0].reshape(1, -1)
    _, ids = manager.search(query, k=10)
    returned = {int(val) for val in ids[0] if val >= 0}
    assertions.expect_true(
        any(rid in secondary_ids for rid in returned),
        reason="merged search should include secondary IDs",
    )

    manager.merge_indexes()
    assertions.expect_true(manager.secondary_index is None, reason="secondary should be merged")
    assertions.expect_equal(manager.incremental_ids, set())
