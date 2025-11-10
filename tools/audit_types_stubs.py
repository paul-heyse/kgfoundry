#!/usr/bin/env python3
"""Audit types- stub packages to identify which are actually needed.

This script analyzes the codebase to determine which types- packages are:
1. Actually imported in the codebase
2. Needed for transitive dependencies without py.typed
3. Redundant (stdlib modules in Python 3.13+)
4. Safe to remove

Usage:
    python tools/audit_types_stubs.py
"""

from __future__ import annotations

import ast
import json
import logging
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from kgfoundry_common.subprocess_utils import run_subprocess
from tools._shared.logging import get_logger

REPO_ROOT = Path(__file__).parent.parent
_MAX_DISPLAY_ITEMS = 20

logger = get_logger(__name__)


def get_types_packages() -> dict[str, str]:
    """Extract all types- packages from pyproject.toml.

    Returns
    -------
    dict[str, str]
        Mapping from normalized package name to types- package name.
    """
    types_packages = {}
    pyproject = REPO_ROOT / "pyproject.toml"

    with pyproject.open(encoding="utf-8") as f:
        for line in f:
            if match := re.search(r'"types-([^"]+)"', line):
                stub_name = match.group(1)
                # Normalize: types-beautifulsoup4 -> beautifulsoup4
                base = stub_name.lower().replace("-", "_")
                types_packages[base] = f"types-{stub_name}"

    return types_packages


def get_runtime_dependencies() -> set[str]:
    """Extract runtime dependencies from pyproject.toml.

    Returns
    -------
    set[str]
        Set of normalized runtime dependency names.
    """
    deps = set()
    pyproject = REPO_ROOT / "pyproject.toml"

    with pyproject.open(encoding="utf-8") as f:
        in_deps = False
        for line in f:
            if "[project]" in line:
                in_deps = False
            if "dependencies = [" in line:
                in_deps = True
                continue
            if in_deps:
                if match := re.search(r'"([^">=@]+)', line):
                    pkg = match.group(1).lower().replace("-", "_")
                    # Skip types- packages themselves
                    if not pkg.startswith("types_"):
                        deps.add(pkg)
                if line.strip() == "]":
                    break

    return deps


def _extract_imports_from_file(py_file: Path) -> list[str]:
    """Extract import names from a single Python file.

    Parameters
    ----------
    py_file : Path
        Path to Python file to analyze.

    Returns
    -------
    list[str]
        List of import module names (first component only).
    """
    imports: list[str] = []
    try:
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    imports.append(mod.lower())
            elif isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module.split(".")[0]
                imports.append(mod.lower())
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        logger.debug("Failed to parse %s: %s", py_file, exc)
    return imports


def get_actual_imports() -> dict[str, list[str]]:
    """Scan codebase for actual imports.

    Returns
    -------
    dict[str, list[str]]
        Mapping from import name to list of files where it's imported.
    """
    imports: dict[str, list[str]] = defaultdict(list)

    scan_dirs = [
        REPO_ROOT / "src",
        REPO_ROOT / "tools",
        REPO_ROOT / "codeintel_rev",
    ]

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue

        for py_file in scan_dir.rglob("*.py"):
            if any(skip in str(py_file) for skip in [".venv", "__pycache__", ".git", "stubs"]):
                continue

            file_imports = _extract_imports_from_file(py_file)
            relative_path = str(py_file.relative_to(REPO_ROOT))
            for mod in file_imports:
                imports[mod].append(relative_path)

    return dict(imports)


def _find_python_executable() -> str:
    """Find Python executable using shutil.which.

    Returns
    -------
    str
        Path to python executable.

    Raises
    ------
    RuntimeError
        If python executable cannot be found.
    """
    python_exe = shutil.which("python3") or shutil.which("python")
    if python_exe is None:
        msg = "Could not find python3 or python executable"
        raise RuntimeError(msg)
    return python_exe


def check_package_has_typed(package_name: str) -> bool:
    """Check if a package ships py.typed metadata.

    Parameters
    ----------
    package_name : str
        Package name to check.

    Returns
    -------
    bool
        True if package ships py.typed, False otherwise.
    """
    python_exe = _find_python_executable()
    # Sanitize package name to prevent injection
    safe_package = re.sub(r"[^a-zA-Z0-9._-]", "", package_name)
    if safe_package != package_name:
        logger.warning("Package name sanitized: %s -> %s", package_name, safe_package)
        return False

    # Package name is sanitized above; python_exe is from shutil.which
    # Use run_subprocess for safe execution with timeout
    try:
        cmd = [
            python_exe,
            "-c",
            f"import importlib.metadata; dist = importlib.metadata.distribution('{safe_package}'); files = [f.name for f in dist.files if f]; print('py.typed' in files)",
        ]
        stdout = run_subprocess(cmd, timeout=5)
    except (OSError, RuntimeError):
        return False
    else:
        # Check if py.typed is mentioned
        return "py.typed" in stdout or "py_typed" in stdout


def normalize_package_name(name: str) -> str:
    """Normalize package name for comparison.

    Parameters
    ----------
    name : str
        Package name to normalize.

    Returns
    -------
    str
        Normalized package name.
    """
    return name.lower().replace("-", "_").replace(".", "_")


def map_import_to_stub(import_name: str, types_packages: dict[str, str]) -> str | None:
    """Map an import name to its corresponding types- stub.

    Parameters
    ----------
    import_name : str
        Import name to map.
    types_packages : dict[str, str]
        Available types- packages.

    Returns
    -------
    str | None
        Corresponding types- stub name, or None if not found.
    """
    normalized = normalize_package_name(import_name)

    # Direct match
    if normalized in types_packages:
        return types_packages[normalized]

    # Common mappings
    mappings = {
        "bs4": "beautifulsoup4",
        "yaml": "pyyaml",
        "dateutil": "python_dateutil",
        "jinja2": "jinja2",
        "click": "click",
        "networkx": "networkx",
        "redis": "redis",
        "tqdm": "tqdm",
        "ujson": "ujson",
    }

    if normalized in mappings:
        mapped = normalize_package_name(mappings[normalized])
        if mapped in types_packages:
            return types_packages[mapped]

    # Try fuzzy match
    for stub_base, stub_name in types_packages.items():
        if normalized == stub_base or normalized.replace("_", "") == stub_base.replace("_", ""):
            return stub_name

    return None


def get_stdlib_modules() -> set[str]:
    """Return stdlib modules that have built-in typing in Python 3.13+.

    Returns
    -------
    set[str]
        Set of stdlib module names.
    """
    return {
        "dataclasses",
        "contextvars",
        "typing",
        "collections",
        "typing_extensions",
        "contextlib",
        "functools",
        "itertools",
        "operator",
    }


def _categorize_stubs(
    types_packages: dict[str, str],
    used_stubs: set[str],
    stdlib_modules: set[str],
) -> tuple[set[str], set[str], set[str]]:
    """Categorize types- packages into used, stdlib, and unused.

    Parameters
    ----------
    types_packages : dict[str, str]
        All available types- packages.
    used_stubs : set[str]
        Stubs that are actually used.
    stdlib_modules : set[str]
        Stdlib module names.

    Returns
    -------
    tuple[set[str], set[str], set[str]]
        Tuple of (used_stubs, stdlib_stubs, unused_stubs).
    """
    final_used: set[str] = set()
    stdlib_stubs: set[str] = set()
    unused_stubs: set[str] = set()

    for stub_base, stub_name in types_packages.items():
        if stub_name in used_stubs:
            # Check if it's actually a stdlib module (shouldn't be in used_stubs)
            if stub_base in stdlib_modules:
                stdlib_stubs.add(stub_name)
            else:
                final_used.add(stub_name)
        elif stub_base in stdlib_modules:
            stdlib_stubs.add(stub_name)
        else:
            unused_stubs.add(stub_name)

    return final_used, stdlib_stubs, unused_stubs


def _analyze_usage(
    actual_imports: dict[str, list[str]],
    runtime_deps: set[str],
    types_packages: dict[str, str],
    stdlib_modules: set[str],
) -> tuple[set[str], set[str], set[str]]:
    """Analyze which stubs are used based on imports and runtime dependencies.

    Parameters
    ----------
    actual_imports : dict[str, list[str]]
        Mapping from import name to files.
    runtime_deps : set[str]
        Runtime dependencies from pyproject.toml.
    types_packages : dict[str, str]
        Available types- packages.
    stdlib_modules : set[str]
        Stdlib module names.

    Returns
    -------
    tuple[set[str], set[str], set[str]]
        Tuple of (used_stubs, stdlib_stubs, unused_stubs).
    """
    used_stubs: set[str] = set()

    # Find stubs used by imports
    for import_name in actual_imports:
        stub = map_import_to_stub(import_name, types_packages)
        if stub:
            used_stubs.add(stub)

    # Check runtime dependencies
    for dep in runtime_deps:
        normalized = normalize_package_name(dep)
        if normalized in types_packages:
            stub = types_packages[normalized]
            # Check if package ships py.typed
            if not check_package_has_typed(dep):
                used_stubs.add(stub)
            # Mark stdlib modules
            if normalized in stdlib_modules:
                used_stubs.discard(stub)

    return _categorize_stubs(types_packages, used_stubs, stdlib_modules)


def _report_results(
    used_stubs: set[str],
    stdlib_stubs: set[str],
    unused_stubs: set[str],
) -> None:
    """Report audit results to logger.

    Parameters
    ----------
    used_stubs : set[str]
        Stubs that are used.
    stdlib_stubs : set[str]
        Stdlib stubs (not needed).
    unused_stubs : set[str]
        Potentially unused stubs.
    """
    logger.info("=" * 70)
    logger.info("TYPES- STUB PACKAGES AUDIT")
    logger.info("=" * 70)

    logger.info("\n3. Results:")
    logger.info("\n   Used types- packages (%d):", len(used_stubs))
    for stub in sorted(used_stubs):
        logger.info("     ✓ %s", stub)

    logger.info("\n   Stdlib modules (not needed for Python 3.13+) (%d):", len(stdlib_stubs))
    for stub in sorted(stdlib_stubs):
        logger.info("     ✗ %s", stub)

    logger.info("\n   Potentially unused (%d):", len(unused_stubs))
    if len(unused_stubs) > 0:
        logger.info("     (Showing first %d)", _MAX_DISPLAY_ITEMS)
        for stub in sorted(unused_stubs)[:_MAX_DISPLAY_ITEMS]:
            logger.info("     ? %s", stub)
        if len(unused_stubs) > _MAX_DISPLAY_ITEMS:
            logger.info("     ... and %d more", len(unused_stubs) - _MAX_DISPLAY_ITEMS)


def main() -> int:
    """Run the types- stub packages audit.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("=" * 70)
    logger.info("TYPES- STUB PACKAGES AUDIT")
    logger.info("=" * 70)

    # Gather data
    logger.info("\n1. Gathering data...")
    types_packages = get_types_packages()
    runtime_deps = get_runtime_dependencies()
    actual_imports = get_actual_imports()
    stdlib_modules = get_stdlib_modules()

    logger.info("   Found %d types- packages", len(types_packages))
    logger.info("   Found %d runtime dependencies", len(runtime_deps))
    logger.info("   Found %d unique imports", len(actual_imports))

    # Analyze usage
    logger.info("\n2. Analyzing usage...")
    used_stubs, stdlib_stubs, unused_stubs = _analyze_usage(
        actual_imports, runtime_deps, types_packages, stdlib_modules
    )

    # Report
    _report_results(used_stubs, stdlib_stubs, unused_stubs)

    # Save removal candidates
    removal_candidates = sorted(stdlib_stubs | unused_stubs)

    logger.info("\n4. Summary:")
    logger.info("   Total types- packages: %d", len(types_packages))
    logger.info("   Keep: %d", len(used_stubs))
    logger.info("   Remove candidates: %d", len(removal_candidates))

    # Save to file
    output_file = REPO_ROOT / "tools" / "types_stubs_removal_candidates.json"
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "keep": sorted(used_stubs),
                "remove": removal_candidates,
                "stdlib": sorted(stdlib_stubs),
            },
            f,
            indent=2,
        )

    logger.info("\n   Results saved to: %s", output_file.relative_to(REPO_ROOT))

    return 0


if __name__ == "__main__":
    sys.exit(main())
