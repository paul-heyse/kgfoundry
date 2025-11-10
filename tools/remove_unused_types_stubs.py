#!/usr/bin/env python3
"""Remove unused types- stub packages from pyproject.toml.

This script removes types- packages that are not actually used in the codebase,
after verifying type checking still passes.

Usage:
    python tools/remove_unused_types_stubs.py
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess  # lint-ignore[S404] Required for check=False; executable validated via shutil.which
import sys
from pathlib import Path

from tools._shared.logging import get_logger

REPO_ROOT = Path(__file__).parent.parent

logger = get_logger(__name__)


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


def _run_type_checker(cmd: list[str], tool_name: str) -> tuple[bool, str]:
    """Run a type checker command and return success status and output.

    Parameters
    ----------
    cmd : list[str]
        Command to execute (executable validated via shutil.which).
    tool_name : str
        Name of the tool for error messages.

    Returns
    -------
    tuple[bool, str]
        Tuple of (success boolean, output message).
    """
    # Executable is validated via shutil.which; args are literal strings
    # subprocess.run required for check=False to capture return codes
    result = subprocess.run(  # lint-ignore[S603] Input validated; executable from shutil.which
        cmd,
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    if result.returncode != 0:
        return False, f"{tool_name} failed:\n{result.stdout}\n{result.stderr}"

    return True, f"{tool_name} passed"


def run_type_checkers() -> tuple[bool, str]:
    """Run pyright and pyrefly, return (success, output).

    Returns
    -------
    tuple[bool, str]
        Tuple of (success boolean, output message).
    """
    logger.info("Running type checkers...")
    uv_exe = _find_uv_executable()

    # Run pyright
    logger.info("  Running pyright...")
    success, output = _run_type_checker(
        [uv_exe, "run", "pyright", "--warnings", "--pythonversion=3.13"],
        "pyright",
    )
    if not success:
        return False, output

    # Run pyrefly
    logger.info("  Running pyrefly...")
    success, output = _run_type_checker([uv_exe, "run", "pyrefly", "check"], "pyrefly")
    if not success:
        return False, output

    return True, "All type checkers passed"


def remove_packages_from_pyproject(packages_to_remove: list[str]) -> None:
    """Remove specified packages from pyproject.toml.

    Parameters
    ----------
    packages_to_remove : list[str]
        List of types- package names to remove from pyproject.toml.
    """
    pyproject = REPO_ROOT / "pyproject.toml"

    with pyproject.open(encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    skip_next = False

    for i, line in enumerate(lines):
        # Check if this line contains a package to remove
        should_remove = False
        for pkg in packages_to_remove:
            # Handle versioned packages like "types-PyYAML>=6.0.12.20240917"
            pkg_base = pkg.split(">=")[0].split("==")[0]
            if f'"types-{pkg_base}"' in line or f'"{pkg}"' in line:
                should_remove = True
                break

        if should_remove:
            # Skip this line and check if next line is just a comma
            if i + 1 < len(lines) and lines[i + 1].strip() == ",":
                skip_next = True
            continue

        if skip_next:
            skip_next = False
            continue

        new_lines.append(line)

    with pyproject.open("w", encoding="utf-8") as f:
        f.writelines(new_lines)


def main() -> int:
    """Run the removal workflow for unused types- stub packages.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("=" * 70)
    logger.info("REMOVING UNUSED TYPES- STUB PACKAGES")
    logger.info("=" * 70)

    # Load removal candidates (try deep audit first, fallback to regular audit)
    candidates_file = REPO_ROOT / "tools" / "types_stubs_deep_audit.json"
    if not candidates_file.exists():
        candidates_file = REPO_ROOT / "tools" / "types_stubs_removal_candidates.json"
        if not candidates_file.exists():
            logger.error("No audit file found. Run audit script first.")
            return 1

    with candidates_file.open(encoding="utf-8") as f:
        data = json.load(f)

    packages_to_remove = sorted(data.get("remove", []) + data.get("stdlib", []))
    packages_to_keep = sorted(data.get("keep", []))

    logger.info("\nPackages to keep: %d", len(packages_to_keep))
    logger.info("Packages to remove: %d", len(packages_to_remove))

    separator = "\n" + "=" * 70

    # Step 1: Baseline type checking
    logger.info("%s", separator)
    logger.info("STEP 1: Baseline type checking (BEFORE removal)")
    logger.info("=" * 70)
    success, output = run_type_checkers()
    if not success:
        logger.error("ERROR: Baseline type checking failed!")
        logger.error("%s", output)
        return 1
    logger.info("✓ Baseline type checking passed")

    # Step 2: Remove packages
    logger.info("%s", separator)
    logger.info("STEP 2: Removing packages from pyproject.toml")
    logger.info("=" * 70)
    logger.info("Removing %d packages...", len(packages_to_remove))
    remove_packages_from_pyproject(packages_to_remove)
    logger.info("✓ Packages removed")

    # Step 3: Verify type checking still passes
    logger.info("%s", separator)
    logger.info("STEP 3: Verification type checking (AFTER removal)")
    logger.info("=" * 70)
    success, output = run_type_checkers()
    if not success:
        logger.error("ERROR: Type checking failed after removal!")
        logger.error("%s", output)
        logger.warning("\n⚠️  Packages have been removed but type checking failed.")
        logger.warning("   You may need to restore some packages.")
        return 1
    logger.info("✓ Verification type checking passed")

    logger.info("%s", separator)
    logger.info("SUCCESS: Removed unused types- packages")
    logger.info("=" * 70)
    logger.info("Removed %d packages", len(packages_to_remove))
    logger.info("Kept %d packages", len(packages_to_keep))

    return 0


if __name__ == "__main__":
    sys.exit(main())
