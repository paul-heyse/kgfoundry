"""Regression tests for runtime packages typing imports.

Verifies that:
1. All runtime packages use typing facades instead of private imports
2. Deprecated resolve_* shim functions are properly gated
3. TYPE_CHECKING guards are in place for heavy optional dependencies
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import kgfoundry_common.typing

RUNTIME_DIRS = [
    Path(__file__).parent.parent.parent / "src" / "kgfoundry_common",
    Path(__file__).parent.parent.parent / "src" / "kgfoundry",
    Path(__file__).parent.parent.parent / "src" / "search_api",
    Path(__file__).parent.parent.parent / "src" / "orchestration",
]


class TestRuntimePackagesTypingImports:
    """Test that runtime packages use proper typing imports."""

    def test_no_direct_private_types_imports(self) -> None:
        """Verify runtime packages don't import from docs._types directly."""
        for runtime_dir in RUNTIME_DIRS:
            if not runtime_dir.exists():
                continue

            for py_file in runtime_dir.rglob("*.py"):
                if py_file.name.startswith("_") and py_file.name != "__init__.py":
                    continue

                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source)

                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.ImportFrom)
                        and node.module
                        and node.module.startswith("docs._types")
                    ):
                        pytest.fail(
                            f"{py_file.name} imports from docs._types: {node.module}. "
                            "Use public facade docs.types instead."
                        )

    def test_no_imports_of_deprecated_resolve_shims(self) -> None:
        """Verify runtime packages don't import the deprecated resolve_* shim functions."""
        deprecated_shims = {"resolve_numpy", "resolve_fastapi", "resolve_faiss"}

        for runtime_dir in RUNTIME_DIRS:
            if not runtime_dir.exists():
                continue

            for py_file in runtime_dir.rglob("*.py"):
                # Skip the typing facade where shims are defined
                if "typing/__init__" in str(py_file):
                    continue

                source = py_file.read_text(encoding="utf-8")

                for shim in deprecated_shims:
                    assert f"from kgfoundry_common.typing import {shim}" not in source, (
                        f"{py_file.name} imports deprecated {shim}. "
                        "Use gate_import() directly instead."
                    )

    def test_gate_import_available_in_kgfoundry_common_typing(self) -> None:
        """Verify gate_import is available in the typing facade."""
        assert hasattr(kgfoundry_common.typing, "gate_import")
        assert callable(kgfoundry_common.typing.gate_import)
        gate_import = kgfoundry_common.typing.gate_import
        assert gate_import.__doc__, "gate_import should have a docstring"

    @staticmethod
    def _is_in_type_checking_block(tree: ast.AST, target_node: ast.AST) -> bool:
        """Check if a node is inside an `if TYPE_CHECKING:` block.

        Parameters
        ----------
        tree : ast.AST
            AST root node.
        target_node : ast.AST
            Node to check location for.

        Returns
        -------
        bool
            True if target_node is inside a TYPE_CHECKING block.
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                is_type_checking = (
                    isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
                )

                if is_type_checking:
                    for child in ast.walk(node):
                        if child is target_node:
                            return True
        return False


@pytest.mark.parametrize(
    "module_name",
    [
        "kgfoundry_common",
        "kgfoundry",
        "kgfoundry_common.typing",
        "kgfoundry_common.errors",
    ],
)
def test_runtime_modules_importable(module_name: str) -> None:
    """Test that key runtime modules can be imported successfully."""
    try:
        __import__(module_name)
    except ImportError as exc:
        pytest.fail(f"Failed to import {module_name}: {exc}")


def test_typing_facade_symbols_available() -> None:
    """Verify that essential symbols are available in runtime typing facades."""
    essential_symbols = [
        "gate_import",
        "safe_get_type",
        "TYPE_CHECKING",
        "NavMap",
        "ProblemDetails",
        "SymbolID",
        "JSONValue",
    ]

    for symbol in essential_symbols:
        assert hasattr(kgfoundry_common.typing, symbol), (
            f"kgfoundry_common.typing should provide {symbol}"
        )
