#!/usr/bin/env python3
"""Remove unused types- stub packages from pyproject.toml.

This script removes types- packages that are not actually used in the codebase,
after verifying type checking still passes.

Usage:
    python tools/remove_unused_types_stubs.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from tools._shared.proc import run_tool

REPO_ROOT = Path(__file__).parent.parent


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
    # Use run_tool for safe subprocess execution with check=False
    result = run_tool(cmd, check=False, cwd=REPO_ROOT)

    if result.returncode != 0:
        stdout = getattr(result, "stdout", "")
        stderr = getattr(result, "stderr", "")
        return False, f"{tool_name} failed:\n{stdout}\n{stderr}"

    return True, f"{tool_name} passed"


def run_type_checkers() -> tuple[bool, str]:
    """Run pyright and pyrefly, return (success, output).

    Returns
    -------
    tuple[bool, str]
        Tuple of (success boolean, output message).
    """
    uv_exe = _find_uv_executable()

    # Run pyright
    success, output = _run_type_checker(
        [uv_exe, "run", "pyright", "--warnings", "--pythonversion=3.13"],
        "pyright",
    )
    if not success:
        return False, output

    # Run pyrefly
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

    Extended Summary
    ----------------
    This CLI tool automates the removal of unused type stub packages from
    pyproject.toml dependencies. It reads an audit file listing removal candidates,
    validates that type checking still passes after removal, and updates the
    project configuration accordingly. This helps maintain a lean dependency
    tree by removing stubs for packages that are no longer used.

    Returns
    -------
    int
        Exit code: 0 on success (stubs removed and type checking passes),
        non-zero on failure (audit file missing, type checking fails, or
        configuration update error).

    Raises
    ------
    RuntimeError
        When the audit file (types_stubs_deep_audit.json or
        types_stubs_removal_candidates.json) is not found in the expected
        location. This indicates the audit script must be run first.

    Notes
    -----
    Performance & Side Effects:
        Time complexity O(n) where n is the number of stub packages to remove.
        Reads audit JSON and pyproject.toml from disk; writes updated pyproject.toml.
        Runs type checkers (pyright/pyrefly) as validation, which may be slow.
        Not thread-safe (modifies project configuration file).

    See Also
    --------
    run_type_checkers : Type checking validation after removal
    """
    # Load removal candidates (try deep audit first, fallback to regular audit)
    candidates_file = REPO_ROOT / "tools" / "types_stubs_deep_audit.json"
    if not candidates_file.exists():
        candidates_file = REPO_ROOT / "tools" / "types_stubs_removal_candidates.json"
        if not candidates_file.exists():
            message = "No audit file found. Run audit script first."
            raise RuntimeError(message)

    with candidates_file.open(encoding="utf-8") as f:
        data = json.load(f)

    packages_to_remove = sorted(data.get("remove", []) + data.get("stdlib", []))

    # Step 1: Baseline type checking
    success, output = run_type_checkers()
    if not success:
        message = f"Baseline type checking failed:\n{output}"
        raise RuntimeError(message)

    # Step 2: Remove packages
    remove_packages_from_pyproject(packages_to_remove)

    # Step 3: Verify type checking still passes
    success, output = run_type_checkers()
    if not success:
        message = f"Type checking failed after removal:\n{output}"
        raise RuntimeError(message)

    return 0


if __name__ == "__main__":
    sys.exit(main())
