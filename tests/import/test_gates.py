"""Tests for import gates and lazy loading behavior.

These tests verify that heavy dependencies are not eagerly imported when modules
are imported. The assertions are within subprocess script strings and execute
in a separate interpreter, so they don't need to be converted to assertion helpers.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from textwrap import dedent

from tests._helpers import run_process

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = REPO_ROOT / "src"


def _run_python(code: str) -> None:
    """Execute ``code`` in a fresh interpreter with repo src on PYTHONPATH."""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{SRC_PATH}{os.pathsep}{existing}" if existing else str(SRC_PATH)
    run_process([sys.executable, "-c", dedent(code)], env=env)


def test_faiss_manager_imports_are_lazy() -> None:
    """Importing faiss_manager must not import numpy/faiss eagerly."""
    script = """
    import sys
    sys.modules.pop("faiss", None)
    import numpy  # required at runtime
    import codeintel_rev.io.faiss_manager  # noqa: F401
    assert "faiss" not in sys.modules
"""
    _run_python(script)


def test_coderank_embedder_does_not_eager_import_sentence_transformers() -> None:
    """Ensure sentence_transformers stays lazy when module is imported."""
    script = """
import sys
sys.modules.pop("sentence_transformers", None)
import codeintel_rev.io.coderank_embedder  # noqa: F401
assert "sentence_transformers" not in sys.modules
"""
    _run_python(script)
