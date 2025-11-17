"""Tests for typing gate import helper with error message hints."""

from __future__ import annotations

import pytest
from codeintel_rev.typing import gate_import

from tests._helpers import assertions


def test_gate_import_missing_module_includes_extra_hint() -> None:
    """Verify gate_import includes pip install hint when module is missing."""

    def fake_import(_name: str) -> object:
        message = "No module named 'faiss'"
        raise ImportError(message)

    with pytest.raises(ImportError) as excinfo:
        gate_import("faiss", "testing extras hint", import_func=fake_import)

    message = str(excinfo.value)
    assertions.expect_in("pip install codeintel-rev[faiss-cpu]", message)
