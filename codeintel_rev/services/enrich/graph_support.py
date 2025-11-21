# SPDX-License-Identifier: MIT
"""Shared helpers for graph artifact builders."""

from __future__ import annotations

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
    since: str | None = None
    changed_only: bool = False


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
    settings: FileDiscoverySettings | None = None,
) -> list[Path]:
    """Collect Python files subject to the pipeline's include/exclude filters.

    Parameters
    ----------
    ctx : PipelineContext
        Pipeline context providing repo root information.
    settings : FileDiscoverySettings | None, optional
        Include/exclude/max size filters plus optional change filtering
        (``since`` or ``changed_only``).

    Returns
    -------
    list[Path]
        Absolute paths to Python files that should be analyzed.
    """
    options = settings or FileDiscoverySettings()
    include_globs = options.include
    exclude_globs = options.exclude
    repo_root = ctx.paths.repo_root
    changed_filter: set[str] | None = None
    if options.since or options.changed_only:
        changed_filter = _changed_paths(repo_root, since=options.since)
    discovery = PythonFileDiscovery(
        root=repo_root,
        include=include_globs,
        exclude=exclude_globs,
        max_file_bytes=options.max_file_bytes,
    )
    candidates = discovery.discover()
    if not changed_filter:
        return candidates
    filtered: list[Path] = []
    for candidate in candidates:
        try:
            rel = candidate.relative_to(repo_root).as_posix()
        except ValueError:  # pragma: no cover - defensive
            rel = candidate.as_posix()
        if rel in changed_filter:
            filtered.append(candidate)
    return filtered


__all__ = ["DEFAULT_EXCLUDES", "collect_python_files", "detect_commit"]


def _changed_paths(repo_root: Path, *, since: str | None) -> set[str]:
    command = ["git", "-C", str(repo_root), "diff", "--name-only"]
    if since:
        command.append(str(since))
    try:
        stdout = run_subprocess(command, timeout=10)
    except (SubprocessError, OSError):
        return set()
    return {line.strip() for line in stdout.splitlines() if line.strip()}
