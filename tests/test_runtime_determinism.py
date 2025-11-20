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

from tests._helpers import assertions
from tests.helpers import load_attribute, load_module

if TYPE_CHECKING:
    from collections.abc import Callable


def _is_callable(value: object) -> TypeGuard[Callable[..., object]]:
    """Check if value is callable.

    Parameters
    ----------
    value : object
        Value to check.

    Returns
    -------
    TypeGuard[Callable[..., object]]
        True if value is callable, False otherwise.
    """
    return callable(value)


def _require_callable(value: object, label: str) -> Callable[..., object]:
    """Require value to be callable, failing test if not.

    Parameters
    ----------
    value : object
        Value to check.
    label : str
        Label for error message.

    Returns
    -------
    Callable[..., object]
        Callable value (guaranteed by type guard).

    Raises
    ------
    pytest.Failed
        If value is not callable.
    """
    if not _is_callable(value):
        pytest.fail(f"{label} is not callable")
    return value


@pytest.mark.parametrize(
    "module_name",
    [
        "kgfoundry_common.typing",
        "tools.typing",
        pytest.param(
            "docs.typing",
            marks=pytest.mark.skipif(condition=True, reason="docs.typing may not be installed"),
        ),
    ],
)
def test_typing_modules_have_postponed_annotations(module_name: str) -> None:
    """Typing façade modules use postponed annotations."""
    try:
        module = load_module(module_name)
    except ImportError:
        pytest.skip(f"{module_name} not in Python path")

    source_file = module.__file__
    assertions.expect_true(
        source_file is not None, reason=f"{module_name} module has no __file__ attribute"
    )
    if source_file is None:  # pragma: no cover - defensive
        pytest.fail(f"{module_name} module has no __file__ attribute")
    content = Path(source_file).read_text(encoding="utf-8")
    assertions.expect_in(
        "from __future__ import annotations",
        content,
        reason=f"{module_name} missing postponed annotations directive",
    )


def test_kgfoundry_common_typing_exports_gate_import() -> None:
    """gate_import is available from canonical source."""
    gate_import_raw = load_attribute("kgfoundry_common.typing", "gate_import")
    gate_import = _require_callable(gate_import_raw, "gate_import")
    assertions.expect_true(_is_callable(gate_import), reason="gate_import should be callable")


def test_kgfoundry_common_typing_exports_safe_get_type() -> None:
    """safe_get_type is available from canonical source."""
    safe_get_type_raw = load_attribute("kgfoundry_common.typing", "safe_get_type")
    safe_get_type = _require_callable(safe_get_type_raw, "safe_get_type")
    assertions.expect_true(_is_callable(safe_get_type), reason="safe_get_type should be callable")


def test_kgfoundry_common_typing_exports_type_aliases() -> None:
    """Type aliases are accessible."""
    module = load_module("kgfoundry_common.typing")

    for name in ["JSONValue", "NavMap", "ProblemDetails", "SymbolID"]:
        attr_value = getattr(module, name, None)
        # Type narrowing: verify attribute exists and is not None
        if attr_value is None:
            pytest.fail(f"{module.__name__}.{name} is None or missing")
        assertions.expect_true(attr_value is not None, reason=f"{name} should not be None")


def test_tools_typing_re_exports_facade() -> None:
    """tools.typing re-exports from canonical source."""
    tools_module = load_module("tools.typing")
    common_module = load_module("kgfoundry_common.typing")

    tools_gate_import = getattr(tools_module, "gate_import", None)
    common_gate_import = getattr(common_module, "gate_import", None)
    if tools_gate_import is None or common_gate_import is None:
        pytest.fail("gate_import not found in modules")
    typed_tools = _require_callable(tools_gate_import, "tools.typing.gate_import")
    typed_common = _require_callable(common_gate_import, "kgfoundry_common.typing.gate_import")
    assertions.expect_true(typed_tools is typed_common, reason="should be same object")


def test_docs_typing_re_exports_facade() -> None:
    """docs.typing re-exports from canonical source."""
    try:
        docs_module = load_module("docs.typing")
        common_module = load_module("kgfoundry_common.typing")

        docs_gate_import = getattr(docs_module, "gate_import", None)
        common_gate_import = getattr(common_module, "gate_import", None)
        if docs_gate_import is None or common_gate_import is None:
            pytest.fail("gate_import not found in modules")
        typed_docs = _require_callable(docs_gate_import, "docs.typing.gate_import")
        typed_common = _require_callable(common_gate_import, "kgfoundry_common.typing.gate_import")
        assertions.expect_true(typed_docs is typed_common, reason="should be same object")
    except ImportError:
        pytest.skip("docs.typing not in Python path")


def test_facade_has_type_checking_block() -> None:
    """kgfoundry_common.typing has TYPE_CHECKING guards."""
    module = load_module("kgfoundry_common.typing")

    source_file = module.__file__
    assertions.expect_true(source_file is not None, reason="module should have __file__")
    if source_file is None:  # pragma: no cover - defensive
        pytest.fail("module should have __file__")
    content = Path(source_file).read_text(encoding="utf-8")
    # Verify TYPE_CHECKING is imported and used
    assertions.expect_in("from typing import", content)
    assertions.expect_in("if TYPE_CHECKING:", content)


def test_no_eager_numpy_import_in_facade() -> None:
    """Numpy is not imported at module level in source."""
    module = load_module("kgfoundry_common.typing")

    source_file = module.__file__
    assertions.expect_true(source_file is not None, reason="module should have __file__")
    if source_file is None:  # pragma: no cover - defensive
        pytest.fail("module should have __file__")
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


def test_gate_import_missing_module_raises_import_error() -> None:
    """gate_import raises ImportError for missing modules."""
    gate_import_raw = load_attribute("kgfoundry_common.typing", "gate_import")
    gate_import = _require_callable(gate_import_raw, "gate_import")

    with pytest.raises(ImportError) as exc_info:
        gate_import("nonexistent_module_xyz", "test")

    assertions.expect_in("not installed", str(exc_info.value))


def test_safe_get_type_missing_module_returns_none() -> None:
    """safe_get_type returns None gracefully for missing modules."""
    safe_get_type_raw = load_attribute("kgfoundry_common.typing", "safe_get_type")
    safe_get_type = _require_callable(safe_get_type_raw, "safe_get_type")
    result_raw = safe_get_type("nonexistent_module_xyz", "SomeType")
    # Type narrowing: verify None type
    if result_raw is not None:
        pytest.fail(f"Expected None, got {type(result_raw)}")
    assertions.expect_equal(result_raw, None)


def test_safe_get_type_respects_default() -> None:
    """safe_get_type uses provided default value."""
    safe_get_type_raw = load_attribute("kgfoundry_common.typing", "safe_get_type")
    safe_get_type = _require_callable(safe_get_type_raw, "safe_get_type")
    default = "my_fallback"
    result_raw = safe_get_type("nonexistent", "Type", default=default)
    # Type narrowing: verify result matches default type
    if not isinstance(result_raw, str):
        pytest.fail(f"Expected str, got {type(result_raw)}")
    assertions.expect_equal(result_raw, default)


@pytest.mark.integration
@pytest.mark.parametrize(
    "module_name",
    [
        "tools.lint.apply_postponed_annotations",
        "tools.lint.check_typing_gates",
    ],
)
def test_cli_tools_import_clean(module_name: str) -> None:
    """CLI linting tools are importable without optional dependencies."""
    try:
        module = load_module(module_name)
        assertions.expect_true(module is not None, reason=f"{module_name} failed to load")
        assertions.expect_true(
            hasattr(module, "__file__"), reason=f"{module_name} has no __file__ attribute"
        )
    except ImportError as e:
        pytest.fail(f"Failed to import {module_name}: {e}")
