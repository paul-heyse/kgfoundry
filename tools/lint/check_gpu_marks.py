#!/usr/bin/env python3
"""Ensure GPU-dependent tests are properly gated."""

from __future__ import annotations

import pathlib
import re
import sys
from typing import TYPE_CHECKING

from tools import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

LOGGER = get_logger(__name__)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TESTS_ROOT = REPO_ROOT / "tests"

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

HEADER_SNIPPET = [
    "import pytest",
    "from tests.conftest import HAS_GPU_STACK",
    "pytestmark = [",
    "pytest.mark.gpu",
    "pytest.mark.skipif(",
    "not HAS_GPU_STACK",
]


def iter_test_paths(argv: list[str]) -> Iterable[pathlib.Path]:
    """Yield test file paths to inspect.

    Parameters
    ----------
    argv : list[str]
        Command-line arguments (file paths or directories).

    Yields
    ------
    pathlib.Path
        Test file paths to inspect.
    """
    if argv:
        for entry in argv:
            path = pathlib.Path(entry)
            if path.suffix == ".py" and "tests" in path.parts:
                yield path
        return
    yield from TESTS_ROOT.rglob("*.py")


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


def has_required_header(source: str) -> bool:
    """Return True when the expected pytest gating header exists.

    Parameters
    ----------
    source : str
        Source code to check for GPU header.

    Returns
    -------
    bool
        True if the source contains all required header snippets.
    """
    return all(snippet in source for snippet in HEADER_SNIPPET)


def main() -> int:
    """Validate GPU gating for relevant tests.

    Returns
    -------
    int
        Exit code (0 for success, 2 if violations found).
    """
    failures: list[pathlib.Path] = []
    root_conftest = (TESTS_ROOT / "conftest.py").resolve()
    for candidate in iter_test_paths(sys.argv[1:]):
        path = candidate.resolve()
        if path == root_conftest:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if contains_gpu_import(text) and not has_required_header(text):
            failures.append(path.relative_to(REPO_ROOT))

    if not failures:
        return 0

    LOGGER.error("GPU gating header missing in the following test files:\n")
    for path in failures:
        LOGGER.error(" - %s", path)
    LOGGER.error(
        "\nAdd the standard header to each file:\n"
        "    import pytest\n"
        "    from tests.conftest import HAS_GPU_STACK\n"
        "    pytestmark = [\n"
        "        pytest.mark.gpu,\n"
        "        pytest.mark.skipif(\n"
        "            not HAS_GPU_STACK,\n"
        "            reason=\"GPU stack (extra 'gpu') not installed/available in this environment\",\n"
        "        ),\n"
        "    ]\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
