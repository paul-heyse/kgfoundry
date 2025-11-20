# SPDX-License-Identifier: MIT
"""Reusable helpers for discovering Python files in repositories."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from codeintel_rev.enrich.pipeline_helpers import normalized_rel_path

EXCLUDED_SCAN_SEGMENTS = {"stubs", "overlays"}
DEFAULT_EXCLUDE_GLOBS: tuple[str, ...] = ("**/.venv/**", "**/build/**", "**/dist/**")


@dataclass(frozen=True, slots=True)
class PythonFileDiscovery:
    """Deterministic Python file discovery with include/exclude and size filters."""

    root: Path
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE_GLOBS
    max_file_bytes: int | None = None

    def iter_paths(self) -> Iterator[Path]:
        """Yield Python files honoring include/exclude globs and hidden/segment skips.

        Yields
        ------
        Iterator[Path]
            Python file candidates that pass skip, exclude, and include filters.
        """
        for candidate in self._iter_candidates():
            if not self.should_consider(candidate):
                continue
            yield candidate

    def discover(self) -> list[Path]:
        """Return a sorted list of Python files that pass filters.

        Returns
        -------
        list[Path]
            Sorted Python file paths relative to ``root`` that pass all filters.
        """
        return sorted(self.iter_paths())

    def should_consider(self, candidate: Path) -> bool:
        """Return True when ``candidate`` passes skip/exclude/include filters.

        Parameters
        ----------
        candidate : Path
            File path to evaluate against skip, exclude, and include rules.

        Returns
        -------
        bool
            True when the candidate should be processed; False otherwise.
        """
        return (
            not self._should_skip(candidate)
            and not self._should_exclude(candidate)
            and self._should_include(candidate)
        )

    def _iter_candidates(self) -> Iterator[Path]:
        return self.root.rglob("*.py")

    def _should_skip(self, candidate: Path) -> bool:
        if any(part.startswith(".") for part in candidate.parts):
            return True
        try:
            rel_parts = candidate.relative_to(self.root).parts
        except ValueError:  # pragma: no cover - defensive
            rel_parts = candidate.parts
        lowered = {part.lower() for part in rel_parts}
        if lowered & EXCLUDED_SCAN_SEGMENTS:
            return True
        if self.max_file_bytes is not None and candidate.is_file():
            try:
                if candidate.stat().st_size > self.max_file_bytes:
                    return True
            except OSError:  # pragma: no cover - best effort skip on stat failure
                return True
        return False

    def _should_exclude(self, candidate: Path) -> bool:
        if not self.exclude:
            return False
        try:
            rel = candidate.relative_to(self.root).as_posix()
        except ValueError:  # pragma: no cover - defensive
            rel = candidate.as_posix()
        return any(fnmatch(rel, pattern) for pattern in self.exclude)

    def _should_include(self, candidate: Path) -> bool:
        if not self.include:
            return True
        rel = normalized_rel_path(candidate, self.root)
        return any(fnmatch(rel, pattern) for pattern in self.include)


def iter_python_files(
    root: Path,
    patterns: tuple[str, ...] | None = None,
) -> Iterable[Path]:
    """Yield Python files honoring default exclusion rules and optional include globs.

    Parameters
    ----------
    root : Path
        Repository root directory to search for Python files.
    patterns : tuple[str, ...] | None, optional
        Optional tuple of glob patterns to include. If None, all Python files
        matching exclusion rules are yielded.

    Yields
    ------
    Path
        Path objects for Python files that match inclusion patterns and do not
        violate exclusion rules (e.g., files in stubs/ or overlays/ directories).
    """
    discovery = PythonFileDiscovery(
        root=root,
        include=tuple(patterns or ()),
        exclude=DEFAULT_EXCLUDE_GLOBS,
    )
    yield from discovery.iter_paths()


def should_skip_candidate(candidate: Path, root: Path) -> bool:
    """Determine whether a candidate file path should be excluded from scanning.

    Parameters
    ----------
    candidate : Path
        File path candidate to evaluate.
    root : Path
        Repository root directory for relative path computation.

    Returns
    -------
    bool
        True if the candidate should be skipped (hidden paths, excluded
        segments like stubs/overlays, excluded globs, or size limits),
        False otherwise.
    """
    discovery = PythonFileDiscovery(root=root)
    return not discovery.should_consider(candidate)


def _matches_any(candidate: Path, root: Path, patterns: tuple[str, ...]) -> bool:
    rel = normalized_rel_path(candidate, root)
    return any(fnmatch(rel, pattern) for pattern in patterns)


__all__ = [
    "DEFAULT_EXCLUDE_GLOBS",
    "EXCLUDED_SCAN_SEGMENTS",
    "PythonFileDiscovery",
    "iter_python_files",
    "should_skip_candidate",
]
