"""Overview of docformatter.

This module bundles docformatter logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tools import ToolExecutionError, get_logger, run_tool

LOGGER = get_logger(__name__)


def git_diff_names() -> set[str]:
    """Compute git diff names.

    Carry out the git diff names operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Returns
    -------
    set[str]
        Set of changed file names.

    Raises
    ------
    SystemExit
        If git command execution fails.

    Examples
    --------
    >>> from tools.hooks.docformatter import git_diff_names
    >>> result = git_diff_names()
    >>> result  # doctest: +ELLIPSIS
    """
    try:
        result = run_tool(["git", "diff", "--name-only"], timeout=10.0, check=True)
        return {line for line in result.stdout.splitlines() if line.strip()}
    except ToolExecutionError as exc:
        LOGGER.exception("Failed to get git diff names")
        raise SystemExit(exc.returncode if exc.returncode is not None else 1) from exc


def main() -> int:
    """Compute main.

    Carry out the main operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Returns
    -------
    int
        Description of return value.

    Examples
    --------
    >>> from tools.hooks.docformatter import main
    >>> result = main()
    >>> result  # doctest: +ELLIPSIS
    """
    try:
        repo_result = run_tool(["git", "rev-parse", "--show-toplevel"], timeout=10.0, check=True)
        repo = repo_result.stdout.strip()
    except ToolExecutionError as exc:
        LOGGER.exception("Failed to resolve git repository root")
        return exc.returncode if exc.returncode is not None else 1

    before = git_diff_names()

    cmd = [
        sys.executable,
        "-m",
        "docformatter",
        "--in-place",
        "--wrap-summaries=100",
        "--wrap-descriptions=100",
        "-r",
        "src",
    ]
    try:
        result = run_tool(cmd, timeout=20.0, cwd=Path(repo), check=False)
    except ToolExecutionError as exc:
        LOGGER.exception("docformatter execution failed")
        return exc.returncode if exc.returncode is not None else 1

    if result.returncode not in {0, 3}:
        return result.returncode

    after = git_diff_names()
    changed = sorted(after - before)
    if changed:
        LOGGER.info("docformatter updated:")
        for path in changed:
            LOGGER.info("  %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
