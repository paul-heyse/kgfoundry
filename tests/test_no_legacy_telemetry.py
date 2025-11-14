"""Regression test ensuring legacy telemetry shims stay removed."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = PROJECT_ROOT / "codeintel_rev"


def _python_files() -> list[Path]:
    files: list[Path] = []
    for path in CODE_ROOT.rglob("*.py"):
        # Observability metrics is the only module that may touch prometheus_client
        if path.name == "metrics.py" and "observability" in path.parts:
            continue
        files.append(path)
    return files


def test_no_legacy_prometheus_client_imports() -> None:
    """Ensure telemetry.prom and prometheus_client are no longer imported."""
    banned = {"prometheus_client", "codeintel_rev.telemetry.prom"}
    offenders: list[tuple[Path, str]] = []
    for file_path in _python_files():
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in banned:
                        offenders.append((file_path, alias.name))
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if module_name in banned:
                    offenders.append((file_path, module_name))
    assert not offenders, f"Legacy telemetry imports found: {offenders}"
