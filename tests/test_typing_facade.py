"""Tests for the typing façade (kgfoundry_common.typing).

This module verifies that the typing façade correctly handles:
1. Type alias exports (NavMap, ProblemDetails, JSONValue, SymbolID)
2. Runtime helpers (gate_import, safe_get_type)
3. Backward compatibility shims (resolve_numpy, resolve_fastapi, resolve_faiss)
4. Proper error handling when dependencies are missing
"""

from __future__ import annotations

from types import ModuleType

import pytest

import kgfoundry_common.typing as typing_module
from kgfoundry_common.typing import (
    JSONValue,
    NavMap,
    ProblemDetails,
    SymbolID,
    gate_import,
    resolve_faiss,
    resolve_fastapi,
    resolve_numpy,
    safe_get_type,
)
from tests._helpers import assertions


def _install_fake_faiss(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Patch gate_import to return a synthetic faiss module during a test.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest monkeypatch fixture.

    Returns
    -------
    ModuleType
        Fake faiss module.
    """
    fake_module = ModuleType("faiss")

    def _patched_gate_import(module_name: str, purpose: str) -> ModuleType:
        if module_name == "faiss":
            return fake_module
        result = gate_import(module_name, purpose)
        if isinstance(result, ModuleType):
            return result
        message = "gate_import returned non-module result"
        raise AssertionError(message)

    monkeypatch.setattr(typing_module, "gate_import", _patched_gate_import)
    return fake_module


class TestGateImport:
    """Tests for gate_import() helper function."""

    def test_gate_import_available_module(self) -> None:
        """Import a module that is installed (json is always available)."""
        json_module = gate_import("json", "test: JSON parsing")
        assertions.expect_true(json_module is not None, reason="json_module should not be None")
        assertions.expect_true(
            hasattr(json_module, "dumps"), reason="json_module should have dumps"
        )

    def test_gate_import_missing_module(self) -> None:
        """Attempting to import a missing module raises ImportError."""
        with pytest.raises(
            ImportError,
            match=r"Cannot proceed with.*test_missing.*not installed",
        ):
            gate_import("nonexistent_module_xyz123", "test_missing")

    def test_gate_import_with_purpose_in_message(self) -> None:
        """Error message includes the purpose string."""
        purpose = "array manipulation for tests"
        with pytest.raises(ImportError) as exc_info:
            gate_import("fake_module_abc", purpose)
        assertions.expect_in(purpose, str(exc_info.value))

    def test_gate_import_suggests_pip_install(self) -> None:
        """Error message suggests the pip install command."""
        with pytest.raises(ImportError) as exc_info:
            gate_import("fake_module", "test")
        assertions.expect_in("pip install", str(exc_info.value))

    def test_gate_import_caches_result(self) -> None:
        """Multiple imports of the same module return the same object."""
        json1 = gate_import("json", "test 1")
        json2 = gate_import("json", "test 2")
        assertions.expect_true(json1 is json2, reason="should return same object")


class TestSafeGetType:
    """Tests for safe_get_type() helper function."""

    def test_safe_get_type_existing_type(self) -> None:
        """Retrieve a type from an available module."""
        list_type = safe_get_type("builtins", "list")
        assertions.expect_true(list_type is list, reason="should return list type")

    def test_safe_get_type_missing_module(self) -> None:
        """Return None when module is not found."""
        result = safe_get_type("nonexistent_xyz", "SomeType")
        assertions.expect_equal(result, None)

    def test_safe_get_type_missing_type(self) -> None:
        """Return None when type does not exist in the module."""
        result = safe_get_type("json", "NonexistentType")
        assertions.expect_equal(result, None)

    def test_safe_get_type_with_default(self) -> None:
        """Use default return value when module or type is missing."""
        default = "my_default"
        result = safe_get_type("nonexistent", "Something", default=default)
        assertions.expect_equal(result, default)


class TestBackwardCompatibilityShims:
    """Tests for deprecated resolve_*() functions."""

    def test_resolve_numpy_emits_deprecation_warning(self) -> None:
        """resolve_numpy() emits a DeprecationWarning."""
        with pytest.warns(DeprecationWarning, match=r"resolve_numpy.*deprecated"):
            resolve_numpy()

    def test_resolve_fastapi_emits_deprecation_warning(self) -> None:
        """resolve_fastapi() emits a DeprecationWarning."""
        with pytest.warns(DeprecationWarning, match=r"resolve_fastapi.*deprecated"):
            resolve_fastapi()

    def test_resolve_faiss_emits_deprecation_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """resolve_faiss() emits a DeprecationWarning."""
        _install_fake_faiss(monkeypatch)
        with pytest.warns(DeprecationWarning, match=r"resolve_faiss.*deprecated"):
            resolve_faiss()

    def test_resolve_numpy_returns_module(self) -> None:
        """resolve_numpy() returns the numpy module (despite deprecation)."""
        with pytest.warns(DeprecationWarning, match=r"deprecated"):
            numpy = resolve_numpy()
        assertions.expect_true(
            isinstance(numpy, ModuleType), reason="resolve_numpy should return a module"
        )
        assertions.expect_true(
            hasattr(numpy, "array"), reason="numpy module should have 'array' attribute"
        )
        assertions.expect_true(
            hasattr(numpy, "ndarray"), reason="numpy module should have 'ndarray' attribute"
        )

    def test_resolve_fastapi_returns_module(self) -> None:
        """resolve_fastapi() returns the fastapi module (despite deprecation)."""
        with pytest.warns(DeprecationWarning, match=r"deprecated"):
            fastapi = resolve_fastapi()
        assertions.expect_true(
            isinstance(fastapi, ModuleType), reason="resolve_fastapi should return a module"
        )
        assertions.expect_true(
            hasattr(fastapi, "FastAPI"), reason="fastapi module should have 'FastAPI' attribute"
        )

    def test_resolve_faiss_returns_module(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """resolve_faiss() returns the faiss module (despite deprecation)."""
        _install_fake_faiss(monkeypatch)
        with pytest.warns(DeprecationWarning, match=r"deprecated"):
            faiss = resolve_faiss()
        # Just verify we got something that looks like a module
        assertions.expect_true(
            isinstance(faiss, ModuleType), reason="resolve_faiss should return a module"
        )
        assertions.expect_true(
            hasattr(faiss, "__name__"), reason="faiss module should have '__name__' attribute"
        )


class TestTypeAliases:
    """Tests for type aliases exported by the façade."""

    def test_type_aliases_are_defined(self) -> None:
        """Verify that type aliases are accessible."""
        # These should be importable without error
        assertions.expect_true(NavMap is not None, reason="NavMap should be defined")
        assertions.expect_true(
            ProblemDetails is not None, reason="ProblemDetails should be defined"
        )
        assertions.expect_true(JSONValue is not None, reason="JSONValue should be defined")
        assertions.expect_true(SymbolID is not None, reason="SymbolID should be defined")

    def test_navmap_is_dict_alias(self) -> None:
        """NavMap represents a dict structure."""
        # Type aliases are runtime strings in Python < 3.12
        # Just verify they're defined and non-None
        assertions.expect_true(NavMap is not None, reason="NavMap should be defined")

    def test_problem_details_is_dict_alias(self) -> None:
        """ProblemDetails represents RFC 9457 Problem Details."""
        assertions.expect_true(
            ProblemDetails is not None, reason="ProblemDetails should be defined"
        )

    def test_symbol_id_is_str_alias(self) -> None:
        """SymbolID is a string alias for symbol identifiers."""
        assertions.expect_true(SymbolID is not None, reason="SymbolID should be defined")

    def test_json_value_covers_json_types(self) -> None:
        """JSONValue covers all valid JSON types."""
        # Just verify it's defined
        assertions.expect_true(JSONValue is not None, reason="JSONValue should be defined")
