#!/usr/bin/env python3
"""Add the standard GPU pytest header to GPU-dependent tests."""

from __future__ import annotations

import pathlib
import re

from tools import get_logger

LOGGER = get_logger(__name__)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TESTS_ROOT = REPO_ROOT / "tests"

HEADER_TEXT = """import pytest
from tests.conftest import HAS_GPU_STACK

# Mark as GPU and skip automatically when the GPU stack is not available.
pytestmark = [
    pytest.mark.gpu,
    pytest.mark.skipif(
        not HAS_GPU_STACK,
        reason="GPU stack (extra 'gpu') not installed/available in this environment",
    ),
]

"""

GPU_IMPORT_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:from\s+(?P<mod_from>[a-zA-Z0-9_\.]+)\s+import|import\s+(?P<mod_imp>[a-zA-Z0-9_\.]+))",
    re.MULTILINE,
)

GPU_MODULE_HEADS: set[str] = {
    "torch",
    "torchvision",
    "torchaudio",
    "vllm",
    "faiss",
    "triton",
    "cuvs",
    "cuda",
    "cupy",
}

GPU_MODULE_FULL: set[str] = {
    "kgfoundry.search_api.faiss_adapter",
    "kgfoundry_common.faiss",
}


def contains_gpu_import(source: str) -> bool:
    """Return True when the source imports a known GPU module.

    Parameters
    ----------
    source : str
        Source code to check for GPU imports.

    Returns
    -------
    bool
        True if the source contains imports from known GPU modules.
    """
    for match in GPU_IMPORT_RE.finditer(source):
        mod_from = match.group("mod_from")
        mod_imp = match.group("mod_imp")
        if mod_from is not None:
            module: str = mod_from
        elif mod_imp is not None:
            module = mod_imp
        else:
            module = ""
        head: str = module.split(".", 1)[0]
        if module in GPU_MODULE_FULL or head in GPU_MODULE_HEADS:
            return True
    return False


def has_header(source: str) -> bool:
    """Return True when the GPU header already exists.

    Parameters
    ----------
    source : str
        Source code to check for GPU header.

    Returns
    -------
    bool
        True if the source contains both pytest.mark.gpu and HAS_GPU_STACK.
    """
    return "pytest.mark.gpu" in source and "HAS_GPU_STACK" in source


def insert_header(source: str) -> str:
    """Insert the standard header near the top of the file.

    Parameters
    ----------
    source : str
        Source code to insert header into.

    Returns
    -------
    str
        Source code with GPU header inserted after shebang/encoding/docstring.
    """
    lines = source.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith(("#!", "# -*-", "#")):
            index += 1
            continue
        if not stripped:
            index += 1
            continue
        break
    return "".join([*lines[:index], HEADER_TEXT, *lines[index:]])


def main() -> int:
    """Apply the GPU header to any matching test files.

    Returns
    -------
    int
        Exit code (0 for success).
    """
    changed = 0
    root_conftest = (TESTS_ROOT / "conftest.py").resolve()
    for path in TESTS_ROOT.rglob("*.py"):
        resolved = path.resolve()
        if resolved == root_conftest:
            continue
        text = resolved.read_text(encoding="utf-8")
        if not contains_gpu_import(text) or has_header(text):
            continue
        updated = insert_header(text)
        if updated != text:
            resolved.write_text(updated, encoding="utf-8")
            LOGGER.info("[gpu-header] updated %s", resolved.relative_to(REPO_ROOT))
            changed += 1
    LOGGER.info("[gpu-header] completed, modified %d files.", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
