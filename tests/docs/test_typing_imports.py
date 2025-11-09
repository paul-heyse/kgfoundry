"""Regression tests for documentation scripts typing imports.

Verifies that:
1. All docs scripts can be imported cleanly without docs._types references
2. Private module imports are properly guarded behind TYPE_CHECKING
3. Typing facades are used consistently across docs toolchain
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from docs.scripts.testing import clear_lazy_import_caches

from tests.helpers import load_attribute, load_module

DOCS_SCRIPTS = [
    Path(__file__).parent.parent.parent / "docs" / "_scripts",
    Path(__file__).parent.parent.parent / "docs" / "scripts",
]

DOCS_TYPES = Path(__file__).parent.parent.parent / "docs" / "types"


class TestDocsScriptsTypingImports:
    """Test that docs scripts use proper typing imports."""

    def test_scripts_can_import_without_private_modules(self) -> None:
        """Verify docs scripts import cleanly without docs._types in sys.modules."""
        # Record initial state
        initial_modules = set(sys.modules.keys())
        private_modules_before = {m for m in initial_modules if "docs._types" in m}

        try:
            # Import the shared module (foundational for all scripts)
            # This import is needed to trigger the side effect of checking module imports
            __import__("docs._scripts.shared")

            # Verify no private docs._types modules were loaded
            current_modules = set(sys.modules.keys())
            private_modules_after = {m for m in current_modules if "docs._types" in m}

            # It's OK if docs._types modules are imported, but they should be via
            # the public docs.types facade only
            new_private_modules = private_modules_after - private_modules_before

            # docs.types modules are allowed (they are the public facade)
            allowed_privates = {m for m in new_private_modules if "docs.types" in m}
            unexpected_privates = new_private_modules - allowed_privates

            assert not unexpected_privates, (
                f"docs scripts loaded unexpected private modules: {unexpected_privates}. "
                "Use docs.types public facade instead."
            )
        finally:
            # Clean up for other tests
            to_remove = [m for m in sys.modules if m.startswith("docs._scripts")]
            for m in to_remove:
                del sys.modules[m]
            clear_lazy_import_caches()

    def test_docs_scripts_have_postponed_annotations(self) -> None:
        """Verify all docs scripts have `from __future__ import annotations`."""
        for scripts_dir in DOCS_SCRIPTS:
            if not scripts_dir.exists():
                continue

            for py_file in scripts_dir.glob("*.py"):
                if py_file.name.startswith("_"):
                    continue

                source = py_file.read_text(encoding="utf-8")

                assert "from __future__ import annotations" in source, (
                    f"{py_file.name} missing `from __future__ import annotations`"
                )

    def test_no_unguarded_heavy_imports_in_scripts(self) -> None:
        """Verify heavy optional dependencies are only imported in TYPE_CHECKING blocks."""
        heavy_imports = {"numpy", "fastapi", "faiss", "torch", "tensorflow", "sklearn"}

        for scripts_dir in DOCS_SCRIPTS:
            if not scripts_dir.exists():
                continue

            for py_file in scripts_dir.glob("*.py"):
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

    def test_typing_facades_used_in_docs_scripts(self) -> None:
        """Verify scripts import from public docs.types and docs.typing facades."""
        for scripts_dir in DOCS_SCRIPTS:
            if not scripts_dir.exists():
                continue

            for py_file in scripts_dir.glob("*.py"):
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


class TestDocsTypesPublicFacade:
    """Test that docs/types/*.py re-exports from public facade."""

    def test_docs_types_modules_exist(self) -> None:
        """Verify public docs/types modules exist."""
        expected_modules = ["artifacts", "griffe", "sphinx_optional"]

        for module_name in expected_modules:
            module_file = DOCS_TYPES / f"{module_name}.py"
            assert module_file.exists(), f"docs/types/{module_name}.py should exist"

    def test_docs_types_reexports_from_private_module(self) -> None:
        """Verify docs/types re-exports from docs._types private modules."""
        for py_file in DOCS_TYPES.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            source = py_file.read_text(encoding="utf-8")

            # Each public module should import from corresponding private module
            # e.g., docs/types/artifacts.py imports from docs._types.artifacts
            assert "from docs._types" in source, (
                f"{py_file.name} should re-export from private docs._types module"
            )

    def test_docs_types_has_all_declaration(self) -> None:
        """Verify all docs/types/*.py have proper __all__ declarations."""
        for py_file in DOCS_TYPES.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            source = py_file.read_text(encoding="utf-8")

            assert "__all__" in source, f"{py_file.name} should define __all__ for public API"


class TestDocstringAndMigrationGuidance:
    """Test documentation of migration paths."""

    def test_docs_types_init_has_facade_docstring(self) -> None:
        """Verify docs/types/__init__.py documents the public facade."""
        docs_types_init = DOCS_TYPES / "__init__.py"
        content = docs_types_init.read_text(encoding="utf-8")

        assert "public facade" in content.lower(), (
            "docs/types/__init__.py should document it's a public facade"
        )

    def test_docs_typing_facade_is_available(self) -> None:
        """Verify docs.typing module exists and provides helpers."""
        module = load_module("docs.typing")

        expected_attrs = ["gate_import", "TYPE_CHECKING"]
        for attr in expected_attrs:
            assert hasattr(module, attr), f"docs.typing should provide {attr} helper"

    def test_gate_import_is_documented(self) -> None:
        """Verify gate_import helper is documented."""
        gate_import = load_attribute("docs.typing", "gate_import")
        assert gate_import.__doc__, "gate_import should have a docstring"


@pytest.mark.parametrize(
    "module_name",
    [
        "docs._scripts.shared",
        "docs._scripts.build_symbol_index",
        "docs._scripts.validate_artifacts",
        "docs._scripts.symbol_delta",
        "docs._scripts.validation",
    ],
)
def test_docs_scripts_importable(module_name: str) -> None:
    """Test that key docs scripts can be imported successfully."""
    try:
        load_module(module_name)
    except ImportError as exc:
        pytest.fail(f"Failed to import {module_name}: {exc}")


def test_no_resolve_numpy_in_docs_scripts() -> None:
    """Verify docs scripts don't import deprecated resolve_numpy shim."""
    deprecated_shims = {"resolve_numpy", "resolve_fastapi", "resolve_faiss"}
    error_messages = {
        "resolve_numpy": "Use docs.typing.gate_import('numpy', ...) instead.",
        "resolve_fastapi": "Use docs.typing.gate_import('fastapi', ...) instead.",
        "resolve_faiss": "Use docs.typing.gate_import('faiss', ...) instead.",
    }

    for scripts_dir in DOCS_SCRIPTS:
        if not scripts_dir.exists():
            continue

        for py_file in scripts_dir.glob("*.py"):
            source = py_file.read_text(encoding="utf-8")

            for shim in deprecated_shims:
                assert shim not in source, (
                    f"{py_file.name} should not import deprecated {shim}. {error_messages[shim]}"
                )
