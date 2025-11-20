# SPDX-License-Identifier: MIT
"""Reusable helpers for discovering Python files in repositories."""

from __future__ import annotations

from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path

from codeintel_rev.enrich.pipeline_helpers import normalized_rel_path

EXCLUDED_SCAN_SEGMENTS = {"stubs", "overlays"}


def iter_python_files(
    root: Path,
    patterns: tuple[str, ...] | None = None,
) -> Iterable[Path]:
    """Yield Python files honoring default exclusion rules and optional include globs."""
    normalized_patterns = tuple(patterns or ())
    for candidate in root.rglob("*.py"):
        if should_skip_candidate(candidate, root):
            continue
        if normalized_patterns and not _matches_any(candidate, root, normalized_patterns):
            continue
        yield candidate


def should_skip_candidate(candidate: Path, root: Path) -> bool:
    """Return whether the candidate should be skipped."""
    if any(part.startswith(".") for part in candidate.parts):
        return True
    try:
        rel_parts = candidate.relative_to(root).parts
    except ValueError:  # pragma: no cover - defensive
        rel_parts = candidate.parts
    lowered = {part.lower() for part in rel_parts}
    return bool(lowered & EXCLUDED_SCAN_SEGMENTS)


def _matches_any(candidate: Path, root: Path, patterns: tuple[str, ...]) -> bool:
    rel = normalized_rel_path(candidate, root)
    return any(fnmatch(rel, pattern) for pattern in patterns)


__all__ = ["EXCLUDED_SCAN_SEGMENTS", "iter_python_files", "should_skip_candidate"]
