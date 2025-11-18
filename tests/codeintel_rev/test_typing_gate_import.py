"""Tests for runtime gate import helper."""

from __future__ import annotations

import pytest
from codeintel_rev.runtime.imports import gate_import

from tests._helpers import assertions


def test_gate_import_missing_module_mentions_purpose() -> None:
    """gate_import should surface the module name and purpose in error messages."""
    purpose = "testing extras hint"
    with pytest.raises(ImportError) as excinfo:
        gate_import("nonexistent_fake_module", purpose)

    message = str(excinfo.value)
    assertions.expect_in("nonexistent_fake_module", message)
    assertions.expect_in(purpose, message)


def test_gate_import_round_trips_installed_module() -> None:
    """Importing a stdlib module should succeed."""
    json_module = gate_import("json", "unit test")
    assertions.expect_true(hasattr(json_module, "loads"))
