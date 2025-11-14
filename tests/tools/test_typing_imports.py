"""Regression tests for tooling packages typing imports.

Verifies that:
1. All tools packages can be imported cleanly without docs._types references
2. Private module imports are properly guarded behind TYPE_CHECKING
3. Typing facades are used consistently across tooling packages
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.helpers import load_module

TOOLS_DIRS = [
    Path(__file__).parent.parent.parent / "tools" / "docs",
    Path(__file__).parent.parent.parent / "tools" / "lint",
    Path(__file__).parent.parent.parent / "tools" / "navmap",
]


class TestToolsTypingImports:
    """Test that tools packages use proper typing imports."""

    def test_tools_packages_have_postponed_annotations(self) -> None:
        """Verify all tools modules have `from __future__ import annotations`."""
        for tools_dir in TOOLS_DIRS:
            if not tools_dir.exists():
                continue

            for py_file in tools_dir.rglob("*.py"):
                if py_file.name.startswith("_"):
                    continue

                source = py_file.read_text(encoding="utf-8")

                assert "from __future__ import annotations" in source, (
                    f"{py_file.name} missing `from __future__ import annotations`"
                )

    def test_no_unguarded_heavy_imports_in_tools(self) -> None:
        """Verify heavy optional dependencies are only imported in TYPE_CHECKING blocks."""
        heavy_imports = {"numpy", "fastapi", "faiss", "torch", "tensorflow", "sklearn"}

        for tools_dir in TOOLS_DIRS:
            if not tools_dir.exists():
                continue

            for py_file in tools_dir.rglob("*.py"):
                if py_file.name.startswith("_"):
                    continue

                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source)

                unguarded = [
                    (py_file.name, node.module)
                    for node in ast.walk(tree)
                    if (
                        isinstance(node, ast.ImportFrom)
                        and node.module
                        and node.module.split(".")[0] in heavy_imports
                        and not self._is_in_type_checking_block(tree, node)
                    )
                ]

                assert not unguarded, (
                    f"Found unguarded heavy imports in {py_file.name}: {unguarded}. "
                    "Use TYPE_CHECKING blocks or gate_import() helper."
                )

    def test_typing_facades_used_in_tools(self) -> None:
        """Verify tools import from public docs.types and tools.typing facades."""
        for tools_dir in TOOLS_DIRS:
            if not tools_dir.exists():
                continue

            for py_file in tools_dir.rglob("*.py"):
                if py_file.name.startswith("_"):
                    continue

                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source)

                # Collect all ImportFrom nodes with private docs._types imports
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

    def test_no_resolve_shims_in_tools(self) -> None:
        """Verify tools don't import deprecated resolve_numpy/fastapi/faiss shims."""
        deprecated_shims = {"resolve_numpy", "resolve_fastapi", "resolve_faiss"}
        error_messages = {
            "resolve_numpy": "Use tools.typing.gate_import('numpy', ...) instead.",
            "resolve_fastapi": "Use tools.typing.gate_import('fastapi', ...) instead.",
            "resolve_faiss": "Use tools.typing.gate_import('faiss', ...) instead.",
        }

        for tools_dir in TOOLS_DIRS:
            if not tools_dir.exists():
                continue

            for py_file in tools_dir.rglob("*.py"):
                # Skip typing façade module itself
                if py_file.name == "__init__.py" and "tools/typing" in str(py_file):
                    continue

                source = py_file.read_text(encoding="utf-8")

                for shim in deprecated_shims:
                    # Only flag if shim is imported/used, not just mentioned in comments
                    if f"from tools.typing import {shim}" in source:
                        pytest.fail(
                            f"{py_file.name} imports deprecated {shim}. {error_messages[shim]}"
                        )

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
                # Check if condition is NAME "TYPE_CHECKING"
                is_type_checking = (
                    isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
                )

                if is_type_checking:
                    # Check if target_node is inside this if block
                    for child in ast.walk(node):
                        if child is target_node:
                            return True
        return False


class TestToolsTypingFacade:
    """Test that tools.typing provides the expected façade."""

    def test_tools_typing_facade_is_available(self) -> None:
        """Verify tools.typing module exists and provides helpers."""
        module = load_module("tools.typing")

        expected_attrs = ["gate_import", "TYPE_CHECKING"]
        for attr in expected_attrs:
            assert hasattr(module, attr), f"tools.typing should provide {attr} helper"

    def test_tools_typing_re_exports_common_typing(self) -> None:
        """Verify tools.typing re-exports from kgfoundry_common.typing."""
        tools_typing = load_module("tools.typing")
        common_typing = load_module("kgfoundry_common.typing")

        # Verify some key symbols are exported
        for symbol in ["NavMap", "ProblemDetails"]:
            assert hasattr(tools_typing, symbol), f"tools.typing should re-export {symbol}"
            assert getattr(tools_typing, symbol) == getattr(common_typing, symbol), (
                f"tools.typing.{symbol} should be identical to kgfoundry_common.typing.{symbol}"
            )


@pytest.mark.parametrize(
    "module_name",
    [
        "tools.lint.check_typing_gates",
        "tools.lint.apply_postponed_annotations",
    ],
)
def test_tools_modules_importable(module_name: str) -> None:
    """Test that key tools modules can be imported successfully."""
    try:
        load_module(module_name)
    except ImportError as exc:
        pytest.fail(f"Failed to import {module_name}: {exc}")


def test_tools_no_private_cache_imports() -> None:
    """Verify tools don't import from private _cache module."""
    for tools_dir in TOOLS_DIRS:
        if not tools_dir.exists():
            continue

        for py_file in tools_dir.rglob("*.py"):
            source = py_file.read_text(encoding="utf-8")

            # Check for direct imports from private _cache module
            assert "from _cache import" not in source, (
                f"{py_file.name} should not import from private _cache module"
            )
            assert "from docs._cache import" not in source, (
                f"{py_file.name} should not import from docs._cache module"
            )
