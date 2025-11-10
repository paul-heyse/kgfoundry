#!/usr/bin/env python3
"""Deep audit of types- stub packages with transitive dependency analysis.

This script performs a comprehensive analysis:
1. Identifies modules directly imported/utilized in the codebase
2. Maps imports to their source packages
3. Gets full dependency tree from uv
4. Checks which packages ship py.typed (don't need types- stubs)
5. Determines which types- packages are actually needed

Usage:
    python tools/audit_types_stubs_deep.py
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from kgfoundry_common.subprocess_utils import run_subprocess
from tools._shared.logging import get_logger

REPO_ROOT = Path(__file__).parent.parent
_MAX_DISPLAY_ITEMS = 20
_PROGRESS_INTERVAL = 20

logger = get_logger(__name__)


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


def _check_package_has_typed_via_subprocess(package_name: str) -> bool:
    """Check if a package ships py.typed metadata via subprocess.

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
        logger.debug("Package name sanitized: %s -> %s", package_name, safe_package)
        return False

    # Package name is sanitized above; python_exe is from shutil.which
    # Use run_subprocess for safe execution with timeout
    try:
        cmd = [
            python_exe,
            "-c",
            f"import importlib.metadata; dist = importlib.metadata.distribution('{safe_package}'); files = [f.name for f in dist.files if f]; print('py.typed' in files)",
        ]
        stdout = run_subprocess(cmd, timeout=5, cwd=REPO_ROOT)
    except (OSError, RuntimeError):
        return False
    else:
        return "True" in stdout


def _get_all_installed_packages_via_subprocess() -> dict[str, str]:
    """Get all installed packages via subprocess.

    Returns
    -------
    dict[str, str]
        Mapping from normalized package name to actual package name.
    """
    packages = {}
    python_exe = _find_python_executable()
    # Use run_subprocess for safe execution
    try:
        cmd = [
            python_exe,
            "-c",
            "import importlib.metadata; import json; dists = {dist.metadata['Name'].lower().replace('-', '_'): dist.metadata['Name'] for dist in importlib.metadata.distributions() if dist.metadata.get('Name')}; print(json.dumps(dists))",
        ]
        stdout = run_subprocess(cmd, timeout=10, cwd=REPO_ROOT)
        packages = json.loads(stdout)
    except (json.JSONDecodeError, OSError, RuntimeError) as exc:
        logger.debug("Failed to get installed packages: %s", exc)
    return packages


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
                base = stub_name.lower().replace("-", "_")
                types_packages[base] = f"types-{stub_name}"

    return types_packages


def _extract_package_name(pkg_line: str) -> str | None:
    """Extract normalized package name from dependency specification.

    Parameters
    ----------
    pkg_line : str
        Package specification line (e.g., "package>=1.0.0").

    Returns
    -------
    str | None
        Normalized package name, or None if extraction fails.
    """
    pkg_match = re.match(r"([^>=@]+)", pkg_line)
    if pkg_match:
        return pkg_match.group(1).lower().replace("-", "_")
    return None


def get_runtime_dependencies() -> dict[str, str]:
    """Extract runtime dependencies with versions from pyproject.toml.

    Returns
    -------
    dict[str, str]
        Mapping from normalized package name to package specification string.
    """
    deps = {}
    pyproject = REPO_ROOT / "pyproject.toml"

    with pyproject.open(encoding="utf-8") as f:
        in_deps = False
        for line in f:
            if "[project]" in line:
                in_deps = False
            elif "dependencies = [" in line:
                in_deps = True
            elif in_deps:
                if line.strip() == "]":
                    break
                if match := re.search(r'"([^"]+)"', line):
                    pkg_line = match.group(1)
                    pkg_name = _extract_package_name(pkg_line)
                    if pkg_name and not pkg_name.startswith("types_"):
                        deps[pkg_name] = pkg_line

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
            if _should_skip_file(py_file):
                continue

            file_imports = _extract_imports_from_file(py_file)
            relative_path = str(py_file.relative_to(REPO_ROOT))
            for mod in file_imports:
                imports[mod].append(relative_path)

    return dict(imports)


def _should_skip_file(py_file: Path) -> bool:
    """Check if a file should be skipped during import scanning.

    Parameters
    ----------
    py_file : Path
        Path to Python file.

    Returns
    -------
    bool
        True if file should be skipped, False otherwise.
    """
    skip_patterns = [".venv", "__pycache__", ".git", "stubs"]
    return any(skip in str(py_file) for skip in skip_patterns)


def get_all_installed_packages() -> dict[str, str]:
    """Get all installed packages from the environment.

    Returns
    -------
    dict[str, str]
        Mapping from normalized package name to actual package name.
    """
    return _get_all_installed_packages_via_subprocess()


def _find_uv_executable() -> str:
    """Find uv executable using shutil.which.

    Returns
    -------
    str
        Path to uv executable.

    Raises
    ------
    RuntimeError
        If uv executable cannot be found.
    """
    uv_exe = shutil.which("uv")
    if uv_exe is None:
        msg = "Could not find uv executable"
        raise RuntimeError(msg)
    return uv_exe


def get_full_dependency_tree() -> set[str]:
    """Get full dependency tree using uv tree.

    Returns
    -------
    set[str]
        Set of normalized package names from the dependency tree.
    """
    all_packages = set()
    uv_exe = _find_uv_executable()

    # Use run_subprocess for safe execution
    try:
        cmd = [uv_exe, "tree"]
        stdout = run_subprocess(cmd, timeout=30, cwd=REPO_ROOT)
        for line in stdout.splitlines():
            # Parse uv tree output: "├── package-name v1.0.0" or "│   └── package-name v1.0.0"
            # Also handle "package-name==1.0.0" format
            if match := re.search(r"([a-zA-Z0-9_.-]+)\s+(?:v|==)([\d.]+)", line):
                pkg_name = match.group(1).lower().replace("-", "_").replace(".", "_")
                all_packages.add(pkg_name)
            elif match := re.search(r"([a-zA-Z0-9_-]+)==", line):
                pkg_name = match.group(1).lower().replace("-", "_")
                all_packages.add(pkg_name)
    except (OSError, RuntimeError) as exc:
        logger.debug("Failed to get dependency tree: %s", exc)
    return all_packages


def map_import_to_package(
    import_name: str, runtime_deps: dict[str, str], installed_packages: dict[str, str]
) -> str | None:
    """Map an import name to its source package.

    Parameters
    ----------
    import_name : str
        Import name to map.
    runtime_deps : dict[str, str]
        Runtime dependencies from pyproject.toml.
    installed_packages : dict[str, str]
        Installed packages from the environment.

    Returns
    -------
    str | None
        Package name if found, None otherwise.
    """
    normalized = import_name.lower().replace("-", "_")

    # Direct match in runtime deps
    if normalized in runtime_deps:
        return normalized

    # Common mappings (import name -> package name)
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
        "certifi": "certifi",
        "filelock": "filelock",
        "protobuf": "protobuf",
        "psutil": "psutil",
        "tree_sitter": "tree_sitter",
    }

    if normalized in mappings:
        mapped = mappings[normalized].replace("-", "_")
        if mapped in runtime_deps or mapped in installed_packages:
            return mapped

    # Check installed packages
    if normalized in installed_packages:
        return normalized

    return None


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
    # Normalize package name for lookup
    dist_name = package_name.replace("_", "-")
    if _check_package_has_typed_via_subprocess(dist_name):
        return True

    # Try with underscore
    if _check_package_has_typed_via_subprocess(package_name):
        return True

    # Fallback: check if package is in stdlib
    try:
        spec = importlib.util.find_spec(package_name)
    except (ImportError, ValueError) as exc:
        logger.debug("Failed to check stdlib for %s: %s", package_name, exc)
        return False
    else:
        # Likely stdlib if origin exists and is not in site-packages
        return bool(spec and spec.origin and "site-packages" not in str(spec.origin))


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


def map_package_to_types_stub(package_name: str, types_packages: dict[str, str]) -> str | None:
    """Map a package name to its corresponding types- stub.

    Parameters
    ----------
    package_name : str
        Package name to map.
    types_packages : dict[str, str]
        Available types- packages.

    Returns
    -------
    str | None
        Corresponding types- stub name, or None if not found.
    """
    normalized = normalize_package_name(package_name)

    # Direct match
    if normalized in types_packages:
        return types_packages[normalized]

    # Try variations
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
        "sys",
        "os",
        "pathlib",
        "json",
        "ast",
        "importlib",
        "types",
    }


def _map_imports_to_packages(
    actual_imports: dict[str, list[str]],
    runtime_deps: dict[str, str],
    installed_packages: dict[str, str],
) -> tuple[dict[str, str], set[str]]:
    """Map imports to their source packages.

    Parameters
    ----------
    actual_imports : dict[str, list[str]]
        Mapping from import name to files.
    runtime_deps : dict[str, str]
        Runtime dependencies from pyproject.toml.
    installed_packages : dict[str, str]
        Installed packages from environment.

    Returns
    -------
    tuple[dict[str, str], set[str]]
        Tuple of (import_to_package mapping, directly_used_packages set).
    """
    import_to_package: dict[str, str] = {}
    directly_used_packages: set[str] = set()

    for import_name in actual_imports:
        pkg = map_import_to_package(import_name, runtime_deps, installed_packages)
        if pkg:
            import_to_package[import_name] = pkg
            directly_used_packages.add(pkg)

    return import_to_package, directly_used_packages


def _determine_all_needed_packages(
    directly_used_packages: set[str],
    dependency_tree: set[str],
    runtime_deps: dict[str, str],
    installed_packages: dict[str, str],
) -> set[str]:
    """Determine all packages needed (direct + transitive).

    Parameters
    ----------
    directly_used_packages : set[str]
        Packages directly imported.
    dependency_tree : set[str]
        Full dependency tree from uv.
    runtime_deps : dict[str, str]
        Runtime dependencies from pyproject.toml.
    installed_packages : dict[str, str]
        Installed packages from environment.

    Returns
    -------
    set[str]
        Set of all needed package names.
    """
    all_needed = set(directly_used_packages)

    # Add all packages from dependency tree that are in our runtime deps or installed
    for pkg in dependency_tree:
        if pkg in runtime_deps or pkg in installed_packages:
            all_needed.add(pkg)

    return all_needed


def _check_packages_for_typed(
    all_needed_packages: set[str],
    stdlib_modules: set[str],
) -> tuple[set[str], set[str]]:
    """Check which packages ship py.typed.

    Parameters
    ----------
    all_needed_packages : set[str]
        All packages that are needed.
    stdlib_modules : set[str]
        Stdlib module names.

    Returns
    -------
    tuple[set[str], set[str]]
        Tuple of (packages_with_typed, packages_needing_stubs).
    """
    packages_with_typed: set[str] = set()
    packages_needing_stubs: set[str] = set()

    checked = 0
    for pkg in sorted(all_needed_packages):
        if pkg in stdlib_modules:
            continue
        checked += 1
        if checked % _PROGRESS_INTERVAL == 0:
            logger.info("   Checked %d/%d packages...", checked, len(all_needed_packages))

        if check_package_has_typed(pkg):
            packages_with_typed.add(pkg)
        else:
            packages_needing_stubs.add(pkg)

    return packages_with_typed, packages_needing_stubs


def _map_packages_to_stubs(
    packages_needing_stubs: set[str],
    types_packages: dict[str, str],
) -> tuple[set[str], dict[str, str]]:
    """Map packages needing stubs to their types- stub packages.

    Parameters
    ----------
    packages_needing_stubs : set[str]
        Packages that need types- stubs.
    types_packages : dict[str, str]
        Available types- packages.

    Returns
    -------
    tuple[set[str], dict[str, str]]
        Tuple of (needed_stubs set, stub_to_package mapping).
    """
    needed_stubs: set[str] = set()
    stub_to_package: dict[str, str] = {}

    for pkg in packages_needing_stubs:
        stub = map_package_to_types_stub(pkg, types_packages)
        if stub:
            needed_stubs.add(stub)
            stub_to_package[stub] = pkg

    return needed_stubs, stub_to_package


def _categorize_all_stubs(
    types_packages: dict[str, str],
    needed_stubs: set[str],
    stdlib_modules: set[str],
) -> tuple[set[str], set[str], set[str]]:
    """Categorize all types- packages into used, stdlib, and unused.

    Parameters
    ----------
    types_packages : dict[str, str]
        All available types- packages.
    needed_stubs : set[str]
        Stubs that are needed.
    stdlib_modules : set[str]
        Stdlib module names.

    Returns
    -------
    tuple[set[str], set[str], set[str]]
        Tuple of (used_stubs, unused_stubs, stdlib_stubs).
    """
    used_stubs: set[str] = set()
    unused_stubs: set[str] = set()
    stdlib_stubs: set[str] = set()

    for stub_base, stub_name in types_packages.items():
        if stub_name in needed_stubs:
            used_stubs.add(stub_name)
        elif stub_base in stdlib_modules:
            stdlib_stubs.add(stub_name)
        else:
            unused_stubs.add(stub_name)

    return used_stubs, unused_stubs, stdlib_stubs


def _report_results(
    used_stubs: set[str],
    stdlib_stubs: set[str],
    unused_stubs: set[str],
    stub_to_package: dict[str, str],
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
    stub_to_package : dict[str, str]
        Mapping from stub to package name.
    """
    logger.info("\n8. Results:")
    logger.info("\n   Used types- packages (%d):", len(used_stubs))
    for stub in sorted(used_stubs):
        pkg = stub_to_package.get(stub, "?")
        logger.info("     ✓ %-40s (for %s)", stub, pkg)

    logger.info("\n   Stdlib modules (not needed for Python 3.13+) (%d):", len(stdlib_stubs))
    for stub in sorted(stdlib_stubs):
        logger.info("     ✗ %s", stub)

    logger.info("\n   Unused types- packages (%d):", len(unused_stubs))
    if len(unused_stubs) > 0:
        logger.info("     (Showing first %d)", _MAX_DISPLAY_ITEMS)
        for stub in sorted(unused_stubs)[:_MAX_DISPLAY_ITEMS]:
            logger.info("     ? %s", stub)
        if len(unused_stubs) > _MAX_DISPLAY_ITEMS:
            logger.info("     ... and %d more", len(unused_stubs) - _MAX_DISPLAY_ITEMS)


def _save_results(
    used_stubs: set[str],
    unused_stubs: set[str],
    stdlib_stubs: set[str],
    stub_to_package: dict[str, str],
) -> Path:
    """Save audit results to JSON file.

    Parameters
    ----------
    used_stubs : set[str]
        Types- stubs that are used.
    unused_stubs : set[str]
        Types- stubs that are unused.
    stdlib_stubs : set[str]
        Stdlib types- stubs.
    stub_to_package : dict[str, str]
        Mapping from stub to package name.

    Returns
    -------
    Path
        Path to the output file.
    """
    output_file = REPO_ROOT / "tools" / "types_stubs_deep_audit.json"
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "keep": sorted(used_stubs),
                "remove": sorted(unused_stubs),
                "stdlib": sorted(stdlib_stubs),
                "stub_to_package_mapping": stub_to_package,
            },
            f,
            indent=2,
        )
    return output_file


def _gather_initial_data() -> tuple[dict[str, str], dict[str, str], dict[str, list[str]], set[str]]:
    """Gather initial data for audit.

    Returns
    -------
    tuple[dict[str, str], dict[str, str], dict[str, list[str]], set[str]]
        Tuple of (types_packages, runtime_deps, actual_imports, stdlib_modules).
    """
    logger.info("\n1. Gathering data...")
    types_packages = get_types_packages()
    runtime_deps = get_runtime_dependencies()
    actual_imports = get_actual_imports()
    stdlib_modules = get_stdlib_modules()

    logger.info("   Found %d types- packages", len(types_packages))
    logger.info("   Found %d runtime dependencies", len(runtime_deps))
    logger.info("   Found %d unique imports", len(actual_imports))

    return types_packages, runtime_deps, actual_imports, stdlib_modules


def _gather_package_data() -> tuple[dict[str, str], set[str]]:
    """Gather installed packages and dependency tree.

    Returns
    -------
    tuple[dict[str, str], set[str]]
        Tuple of (installed_packages, dependency_tree).
    """
    logger.info("\n2. Getting installed packages and dependency tree...")
    installed_packages = get_all_installed_packages()
    dependency_tree = get_full_dependency_tree()

    logger.info("   Found %d installed packages", len(installed_packages))
    logger.info("   Found %d packages in dependency tree", len(dependency_tree))

    return installed_packages, dependency_tree


@dataclass(frozen=True)
class _AuditContext:
    """Context for audit workflow execution."""

    types_packages: dict[str, str]
    runtime_deps: dict[str, str]
    actual_imports: dict[str, list[str]]
    stdlib_modules: set[str]
    installed_packages: dict[str, str]
    dependency_tree: set[str]


def _execute_audit_workflow(
    context: _AuditContext,
) -> tuple[set[str], set[str], set[str], dict[str, str]]:
    """Execute the main audit workflow steps.

    Parameters
    ----------
    context : _AuditContext
        Audit context containing all required data.

    Returns
    -------
    tuple[set[str], set[str], set[str], dict[str, str]]
        Tuple of (used_stubs, unused_stubs, stdlib_stubs, stub_to_package).
    """
    # Step 1: Map imports to packages
    logger.info("\n3. Mapping imports to packages...")
    import_to_package, directly_used_packages = _map_imports_to_packages(
        context.actual_imports, context.runtime_deps, context.installed_packages
    )

    logger.info("   Mapped %d imports to packages", len(import_to_package))
    logger.info("   Directly used packages: %d", len(directly_used_packages))

    # Step 2: All packages we need (direct + transitive from dependency tree)
    logger.info("\n4. Determining all needed packages...")
    all_needed_packages = _determine_all_needed_packages(
        directly_used_packages,
        context.dependency_tree,
        context.runtime_deps,
        context.installed_packages,
    )

    logger.info("   Total packages needed (direct + transitive): %d", len(all_needed_packages))

    # Step 3: Check which packages ship py.typed
    logger.info("\n5. Checking which packages ship py.typed...")
    packages_with_typed, packages_needing_stubs = _check_packages_for_typed(
        all_needed_packages, context.stdlib_modules
    )

    logger.info("   Packages with py.typed: %d", len(packages_with_typed))
    logger.info("   Packages needing types- stubs: %d", len(packages_needing_stubs))

    # Step 4: Map needed packages to types- stubs
    logger.info("\n6. Mapping packages to types- stubs...")
    needed_stubs, stub_to_package = _map_packages_to_stubs(
        packages_needing_stubs, context.types_packages
    )

    # Step 5: Categorize all stubs
    logger.info("\n7. Categorizing types- packages...")
    used_stubs, unused_stubs, stdlib_stubs = _categorize_all_stubs(
        context.types_packages, needed_stubs, context.stdlib_modules
    )

    return used_stubs, unused_stubs, stdlib_stubs, stub_to_package


def main() -> int:
    """Run the deep types- stub packages audit.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("=" * 70)
    logger.info("DEEP TYPES- STUB PACKAGES AUDIT")
    logger.info("=" * 70)

    # Gather initial data
    types_packages, runtime_deps, actual_imports, stdlib_modules = _gather_initial_data()

    # Get installed packages and full dependency tree
    installed_packages, dependency_tree = _gather_package_data()

    # Execute audit workflow
    context = _AuditContext(
        types_packages=types_packages,
        runtime_deps=runtime_deps,
        actual_imports=actual_imports,
        stdlib_modules=stdlib_modules,
        installed_packages=installed_packages,
        dependency_tree=dependency_tree,
    )
    used_stubs, unused_stubs, stdlib_stubs, stub_to_package = _execute_audit_workflow(context)

    # Report
    _report_results(used_stubs, stdlib_stubs, unused_stubs, stub_to_package)

    # Save results
    output_file = _save_results(used_stubs, unused_stubs, stdlib_stubs, stub_to_package)

    logger.info("\n9. Summary:")
    logger.info("   Total types- packages: %d", len(types_packages))
    logger.info("   Keep: %d", len(used_stubs))
    logger.info("   Remove candidates: %d", len(unused_stubs) + len(stdlib_stubs))
    logger.info("\n   Results saved to: %s", output_file.relative_to(REPO_ROOT))

    return 0


if __name__ == "__main__":
    sys.exit(main())
