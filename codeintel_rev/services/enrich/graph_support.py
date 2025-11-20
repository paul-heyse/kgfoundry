# SPDX-License-Identifier: MIT
"""Shared helpers for graph artifact builders."""

from __future__ import annotations

from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import Path

from codeintel_rev.services.enrich.context import PipelineContext
from codeintel_rev.services.enrich.python_files import iter_python_files
from kgfoundry_common.subprocess_utils import SubprocessError, run_subprocess

DEFAULT_EXCLUDES: tuple[str, ...] = ("**/.venv/**", "**/build/**", "**/dist/**")


def detect_commit(repo_root: Path) -> str:
    """Return the Git commit hash or ``"unknown"`` when unavailable.

    Parameters
    ----------
    repo_root : Path
        Repository root for executing Git commands.

    Returns
    -------
    str
        Commit hash string or ``"unknown"`` when Git invocation fails.
    """
    try:
        stdout = run_subprocess(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            timeout=10,
        )
    except (SubprocessError, OSError):
        return "unknown"
    return stdout.strip() or "unknown"


def collect_python_files(
    ctx: PipelineContext,
    include: Sequence[str] | None = None,
) -> list[Path]:
    """Collect Python files subject to the pipeline's include/exclude filters.

    Parameters
    ----------
    ctx : PipelineContext
        Pipeline context providing repo root information.
    include : Sequence[str] | None, optional
        Optional include glob patterns relative to the repo root.

    Returns
    -------
    list[Path]
        Absolute paths to Python files that should be analyzed.
    """
    include_globs = tuple(include or ())
    repo_root = ctx.paths.repo_root
    excludes = DEFAULT_EXCLUDES
    files: list[Path] = []
    for file_path in iter_python_files(repo_root, include_globs):
        rel = file_path.relative_to(repo_root).as_posix()
        if excludes and any(fnmatch(rel, pattern) for pattern in excludes):
            continue
        files.append(file_path)
    return files


__all__ = ["DEFAULT_EXCLUDES", "collect_python_files", "detect_commit"]
