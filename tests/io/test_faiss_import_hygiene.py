"""Ensure FAISS IO modules gate numpy at import time."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from types import ModuleType

import pytest

from tests._helpers import assertions


@pytest.fixture(autouse=True)
def _restore_numpy_module() -> Iterator[None]:
    """Restore the original ``numpy`` module after each test."""
    original = sys.modules.get("numpy")
    try:
        yield
    finally:
        if original is not None:
            sys.modules["numpy"] = original
        else:
            sys.modules.pop("numpy", None)


def _clear(mod: str) -> None:
    """Remove ``mod`` from :mod:`sys.modules` when present."""
    sys.modules.pop(mod, None)


def _expect_numpy_absent() -> None:
    """Assert that importing a module did not eagerly load numpy."""
    assertions.expect_true("numpy" not in sys.modules, reason="numpy should stay lazy")


def test_build_does_not_import_numpy_on_module_import() -> None:
    """Import ``faiss_build`` without eagerly materializing numpy."""
    _clear("numpy")
    _clear("codeintel_rev.io.faiss_build")
    _expect_numpy_absent()

    mod = importlib.import_module("codeintel_rev.io.faiss_build")
    assertions.expect_true(isinstance(mod, ModuleType), reason="Module import failed.")
    _expect_numpy_absent()


def test_runtime_does_not_import_numpy_on_module_import() -> None:
    """Import ``faiss_runtime`` without eagerly materializing numpy."""
    _clear("numpy")
    _clear("codeintel_rev.io.faiss_runtime")
    _expect_numpy_absent()

    mod = importlib.import_module("codeintel_rev.io.faiss_runtime")
    assertions.expect_true(isinstance(mod, ModuleType), reason="Module import failed.")
    _expect_numpy_absent()


def test_store_does_not_import_numpy_on_module_import() -> None:
    """Import ``faiss_store`` without eagerly materializing numpy."""
    _clear("numpy")
    _clear("codeintel_rev.io.faiss_store")
    _expect_numpy_absent()

    mod = importlib.import_module("codeintel_rev.io.faiss_store")
    assertions.expect_true(isinstance(mod, ModuleType), reason="Module import failed.")
    _expect_numpy_absent()


def test_manager_does_not_import_numpy_on_module_import() -> None:
    """Import ``faiss_manager`` without eagerly materializing numpy."""
    _clear("numpy")
    _clear("codeintel_rev.io.faiss_manager")
    _expect_numpy_absent()

    mod = importlib.import_module("codeintel_rev.io.faiss_manager")
    assertions.expect_true(isinstance(mod, ModuleType), reason="Module import failed.")
    _expect_numpy_absent()
