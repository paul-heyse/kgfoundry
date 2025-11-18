"""Structural guard preventing gate_import imports from codeintel_rev.typing."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _imports_gate_from_typing(py_file: Path) -> bool:
    source = py_file.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "codeintel_rev.typing":
            for alias in node.names:
                if isinstance(alias, ast.alias) and alias.name == "gate_import":
                    return True
    return False


def test_no_gate_import_from_typing() -> None:
    """Ensure no modules import gate_import from codeintel_rev.typing."""
    repo_root = Path(__file__).resolve().parents[1]
    roots = [repo_root / rel for rel in ("codeintel_rev", "tests", "tools")]
    offenders = [
        str(py_file)
        for base in roots
        if base.exists()
        for py_file in base.rglob("*.py")
        if _imports_gate_from_typing(py_file)
    ]
    if offenders:
        pytest.fail(
            "gate_import must import from codeintel_rev.runtime.imports; "
            f"found legacy imports in: {sorted(offenders)}",
        )
