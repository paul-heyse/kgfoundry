from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from codeintel_rev.io.faiss_manager import FAISSManager

from tests._helpers import assertions
from tests.conftest import FAISS_MODULE, HAS_FAISS_SUPPORT

if not HAS_FAISS_SUPPORT:  # pragma: no cover - dependency-gated
    pytestmark = pytest.mark.skip(
        reason="FAISS bindings unavailable on this host",
    )

if FAISS_MODULE is None:  # pragma: no cover - dependency-gated
    pytest.skip("FAISS bindings unavailable on this host", allow_module_level=True)

faiss_module: Any = FAISS_MODULE


@pytest.fixture
def faiss_manager(tmp_path: Path) -> FAISSManager:
    manager = FAISSManager(index_path=tmp_path / "index.faiss")
    # Use a lightweight flat index stub for type stability
    manager.cpu_index = faiss_module.IndexFlatIP(2)
    return manager


def test_runtime_tuning_apply_and_reset(faiss_manager: FAISSManager) -> None:
    """Runtime tuning overrides surface through describe API."""
    snapshot = faiss_manager.runtime.get_runtime_tuning()
    snapshot_overrides = cast("Mapping[str, object]", snapshot["overrides"])
    assertions.expect_mapping_equal(snapshot_overrides, {})

    updated = faiss_manager.runtime.apply_runtime_tuning(
        nprobe=32,
        ef_search=64,
        k_factor=1.5,
    )
    updated_overrides = cast("Mapping[str, object]", updated["overrides"])
    updated_active = cast("Mapping[str, object]", updated["active"])
    assertions.expect_equal(updated_overrides["nprobe"], 32)
    assertions.expect_equal(updated_active["nprobe"], 32)
    assertions.expect_equal(updated_active["efSearch"], 64)
    assertions.expect_almost_equal(cast("float", updated_active["k_factor"]), 1.5)

    reset = faiss_manager.runtime.reset_runtime_tuning()
    reset_overrides = cast("Mapping[str, object]", reset["overrides"])
    assertions.expect_mapping_equal(reset_overrides, {})
