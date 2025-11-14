"""Regression tests to prevent legacy telemetry imports."""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1] / "codeintel_rev"


def _python_files() -> list[pathlib.Path]:
    """Return all Python files in codeintel_rev, excluding observability/metrics.py.

    Returns
    -------
    list[pathlib.Path]
        Python file paths in the codeintel_rev directory.
    """
    files: list[pathlib.Path] = []
    for p in ROOT.rglob("*.py"):
        if "observability/metrics.py" in str(p):
            continue  # allowed to import prometheus_client.start_http_server
        if "__pycache__" in str(p):
            continue
        files.append(p)
    return files


def test_no_legacy_prometheus_client_imports():
    """Verify no files import prometheus_client or telemetry.prom."""
    banned = {"prometheus_client", "codeintel_rev.telemetry.prom"}
    offenders: list[tuple[pathlib.Path, str]] = []
    for py in _python_files():
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders.extend((py, n.name) for n in node.names if n.name in banned)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod in banned:
                    offenders.append((py, mod))
    assert not offenders, f"Legacy telemetry imports found: {offenders}"


def test_no_legacy_telemetry_otel_imports():
    """Verify no files import telemetry.otel (should use observability.otel)."""
    banned = {"codeintel_rev.telemetry.otel"}
    offenders = []
    for py in _python_files():
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod in banned:
                    offenders.append((py, mod))
    assert not offenders, f"Legacy telemetry.otel imports found: {offenders}"
