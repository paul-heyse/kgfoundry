"""Tests for runtime determinism without optional dependencies.

This module verifies that typing gates are correctly implemented:
1. Postponed annotations prevent eager type evaluation
2. TYPE_CHECKING blocks protect runtime from type-only imports
3. Façade modules provide safe type access without runtime overhead
4. Key CLI tools can initialize without optional deps
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, TypeGuard

import pytest

from tests.helpers import load_attribute, load_module

if TYPE_CHECKING:
    from collections.abc import Callable


def _is_callable(value: object) -> TypeGuard[Callable[..., object]]:
    return callable(value)


def _require_callable(value: object, label: str) -> Callable[..., object]:
    if not _is_callable(value):
        pytest.fail(f"{label} is not callable")
    return value


class TestPostponedAnnotations:
    """Verify postponed annotations are present in core modules."""

    @pytest.mark.parametrize(
        "module_name",
        [
            "kgfoundry_common.typing",
            "tools.typing",
            pytest.param(
                "docs.typing",
                marks=pytest.mark.skipif(
                    condition=True, reason="docs.typing may not be installed"
                ),
            ),
        ],
    )
    def test_typing_modules_have_postponed_annotations(self, module_name: str) -> None:
        """Typing façade modules use postponed annotations."""
        try:
            module = load_module(module_name)
        except ImportError:
            pytest.skip(f"{module_name} not in Python path")

        source_file = module.__file__
        assert (
            source_file is not None
        ), f"{module_name} module has no __file__ attribute"

        content = Path(source_file).read_text(encoding="utf-8")
        assert (
            "from __future__ import annotations" in content
        ), f"{module_name} missing postponed annotations directive"


class TestTypingFacadeModules:
    """Verify façade modules export expected helpers."""

    def test_kgfoundry_common_typing_exports_gate_import(self) -> None:
        """gate_import is available from canonical source."""
        gate_import_raw = load_attribute("kgfoundry_common.typing", "gate_import")
        gate_import = _require_callable(gate_import_raw, "gate_import")
        assert _is_callable(gate_import)

    def test_kgfoundry_common_typing_exports_safe_get_type(self) -> None:
        """safe_get_type is available from canonical source."""
        safe_get_type_raw = load_attribute("kgfoundry_common.typing", "safe_get_type")
        safe_get_type = _require_callable(safe_get_type_raw, "safe_get_type")
        assert _is_callable(safe_get_type)

    def test_kgfoundry_common_typing_exports_type_aliases(self) -> None:
        """Type aliases are accessible."""
        module = load_module("kgfoundry_common.typing")

        for name in ["JSONValue", "NavMap", "ProblemDetails", "SymbolID"]:
            attr_value = getattr(module, name, None)
            # Type narrowing: verify attribute exists and is not None
            if attr_value is None:
                pytest.fail(f"{module.__name__}.{name} is None or missing")
            assert attr_value is not None

    def test_tools_typing_re_exports_facade(self) -> None:
        """tools.typing re-exports from canonical source."""
        tools_module = load_module("tools.typing")
        common_module = load_module("kgfoundry_common.typing")

        tools_gate_import = getattr(tools_module, "gate_import", None)
        common_gate_import = getattr(common_module, "gate_import", None)
        if tools_gate_import is None or common_gate_import is None:
            pytest.fail("gate_import not found in modules")
        typed_tools = _require_callable(tools_gate_import, "tools.typing.gate_import")
        typed_common = _require_callable(
            common_gate_import, "kgfoundry_common.typing.gate_import"
        )
        assert typed_tools is typed_common

    def test_docs_typing_re_exports_facade(self) -> None:
        """docs.typing re-exports from canonical source."""
        try:
            docs_module = load_module("docs.typing")
            common_module = load_module("kgfoundry_common.typing")

            docs_gate_import = getattr(docs_module, "gate_import", None)
            common_gate_import = getattr(common_module, "gate_import", None)
            if docs_gate_import is None or common_gate_import is None:
                pytest.fail("gate_import not found in modules")
            typed_docs = _require_callable(docs_gate_import, "docs.typing.gate_import")
            typed_common = _require_callable(
                common_gate_import, "kgfoundry_common.typing.gate_import"
            )
            assert typed_docs is typed_common
        except ImportError:
            pytest.skip("docs.typing not in Python path")


class TestTypeOnlyImportGuarding:
    """Verify TYPE_CHECKING guards in façade modules."""

    def test_facade_has_type_checking_block(self) -> None:
        """kgfoundry_common.typing has TYPE_CHECKING guards."""
        module = load_module("kgfoundry_common.typing")

        source_file = module.__file__
        assert source_file is not None

        content = Path(source_file).read_text(encoding="utf-8")
        # Verify TYPE_CHECKING is imported and used
        assert "from typing import" in content
        assert "if TYPE_CHECKING:" in content

    def test_no_eager_numpy_import_in_facade(self) -> None:
        """Numpy is not imported at module level in source."""
        module = load_module("kgfoundry_common.typing")

        source_file = module.__file__
        assert source_file is not None

        content = Path(source_file).read_text(encoding="utf-8")
        # Verify numpy is only imported inside TYPE_CHECKING block
        lines = content.split("\n")
        for i, line in enumerate(lines):
            # Skip lines before TYPE_CHECKING block
            if "if TYPE_CHECKING:" in line:
                # After TYPE_CHECKING block, numpy imports are OK
                break
            # Before TYPE_CHECKING, numpy should not be imported
            if line.strip().startswith("import numpy"):
                pytest.fail(f"Found unguarded numpy import at line {i + 1}")
            if "from numpy import" in line or "from numpy." in line:
                pytest.fail(f"Found unguarded numpy import at line {i + 1}")


class TestRuntimeImportSafety:
    """Verify that façade modules work without optional deps."""

    def test_gate_import_missing_module_raises_import_error(self) -> None:
        """gate_import raises ImportError for missing modules."""
        gate_import_raw = load_attribute("kgfoundry_common.typing", "gate_import")
        gate_import = _require_callable(gate_import_raw, "gate_import")

        with pytest.raises(ImportError) as exc_info:
            gate_import("nonexistent_module_xyz", "test")

        assert "not installed" in str(exc_info.value)

    def test_safe_get_type_missing_module_returns_none(self) -> None:
        """safe_get_type returns None gracefully for missing modules."""
        safe_get_type_raw = load_attribute("kgfoundry_common.typing", "safe_get_type")
        safe_get_type = _require_callable(safe_get_type_raw, "safe_get_type")
        result_raw = safe_get_type("nonexistent_module_xyz", "SomeType")
        # Type narrowing: verify None type
        if result_raw is not None:
            pytest.fail(f"Expected None, got {type(result_raw)}")
        assert result_raw is None

    def test_safe_get_type_respects_default(self) -> None:
        """safe_get_type uses provided default value."""
        safe_get_type_raw = load_attribute("kgfoundry_common.typing", "safe_get_type")
        safe_get_type = _require_callable(safe_get_type_raw, "safe_get_type")
        default = "my_fallback"
        result_raw = safe_get_type("nonexistent", "Type", default=default)
        # Type narrowing: verify result matches default type
        if not isinstance(result_raw, str):
            pytest.fail(f"Expected str, got {type(result_raw)}")
        assert result_raw == default


class TestCLIEntryPointImportClean:
    """Verify CLI entry points initialize without heavy deps."""

    @pytest.mark.integration
    @pytest.mark.parametrize(
        "module_name",
        [
            "tools.lint.apply_postponed_annotations",
            "tools.lint.check_typing_gates",
        ],
    )
    def test_cli_tools_import_clean(self, module_name: str) -> None:
        """CLI linting tools are importable without optional dependencies."""
        try:
            module = load_module(module_name)
            assert module is not None, f"{module_name} failed to load"
            assert hasattr(
                module, "__file__"
            ), f"{module_name} has no __file__ attribute"
        except ImportError as e:
            pytest.fail(f"Failed to import {module_name}: {e}")
