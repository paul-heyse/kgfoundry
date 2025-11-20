# SPDX-License-Identifier: MIT
"""Shared helpers for graph artifact builders."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from codeintel_rev.services.enrich.context import PipelineContext
from codeintel_rev.services.enrich.python_files import (
    DEFAULT_EXCLUDE_GLOBS,
    PythonFileDiscovery,
)
from kgfoundry_common.subprocess_utils import SubprocessError, run_subprocess

DEFAULT_EXCLUDES: tuple[str, ...] = DEFAULT_EXCLUDE_GLOBS


@dataclass(frozen=True, slots=True)
class FileDiscoverySettings:
    """Inclusion/exclusion filters shared by graph artifact builders."""

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = DEFAULT_EXCLUDES
    max_file_bytes: int | None = None


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
    exclude: Sequence[str] | None = None,
    max_file_bytes: int | None = None,
) -> list[Path]:
    """Collect Python files subject to the pipeline's include/exclude filters.

    Parameters
    ----------
    ctx : PipelineContext
        Pipeline context providing repo root information.
    include : Sequence[str] | None, optional
        Optional include glob patterns relative to the repo root.
    exclude : Sequence[str] | None, optional
        Optional exclude globs overriding the default exclusion list.
    max_file_bytes : int | None, optional
        Optional size threshold; files larger than this are skipped.

    Returns
    -------
    list[Path]
        Absolute paths to Python files that should be analyzed.
    """
    include_globs = tuple(include or ())
    exclude_globs = tuple(exclude or DEFAULT_EXCLUDES)
    repo_root = ctx.paths.repo_root
    discovery = PythonFileDiscovery(
        root=repo_root,
        include=include_globs,
        exclude=exclude_globs,
        max_file_bytes=max_file_bytes,
    )
    return discovery.discover()


__all__ = ["DEFAULT_EXCLUDES", "collect_python_files", "detect_commit"]
