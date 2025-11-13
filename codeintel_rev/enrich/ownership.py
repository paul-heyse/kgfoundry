# SPDX-License-Identifier: MIT
"""Ownership, churn, and bus-factor analytics sourced from Git history."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kgfoundry_common.logging import get_logger

try:  # pragma: no cover - optional dependency
    from git import Repo as _RuntimeGitRepo
    from git import exc as git_exc
except ImportError:  # pragma: no cover
    _RuntimeGitRepo = None
    git_exc = None

if TYPE_CHECKING:  # pragma: no cover - typing only
    from git import Repo as GitRepo
else:
    GitRepo = Any  # type: ignore[assignment]

GitError = git_exc.GitError if git_exc is not None else Exception
LOGGER = get_logger(__name__)

__all__ = ["FileOwnership", "OwnershipIndex", "compute_ownership"]


@dataclass(slots=True, frozen=True)
class FileOwnership:
    """Aggregated ownership metadata for a single file."""

    path: str
    owner: str | None = None
    primary_authors: tuple[str, ...] = field(default_factory=tuple)
    bus_factor: float = 0.0
    churn_by_window: dict[int, int] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class OwnershipIndex:
    """Collection of :class:`FileOwnership` entries keyed by relative path."""

    by_file: dict[str, FileOwnership] = field(default_factory=dict)
    churn_windows: tuple[int, ...] = field(default_factory=lambda: (30, 90))


def compute_ownership(
    repo_root: Path,
    rel_paths: Sequence[str],
    *,
    commits_window: int = 50,
    churn_windows: Sequence[int] = (30, 90),
) -> OwnershipIndex:
    """Return ownership metrics for ``rel_paths`` relative to ``repo_root``.

    This function computes code ownership and churn metrics for a set of files
    by analyzing Git commit history. The function extracts commit statistics,
    author information, and churn metrics over specified time windows. Metrics
    are computed using GitPython when available, or returns an empty index if
    Git is unavailable.

    Parameters
    ----------
    repo_root : Path
        Root directory of the Git repository. Used to locate the .git directory
        and initialize GitPython repository access. The path is resolved to an
        absolute path before processing.
    rel_paths : Sequence[str]
        Sequence of repository-relative file paths to compute ownership for.
        Paths are normalized, deduplicated, and sorted before processing. Empty
        sequences return an OwnershipIndex with empty by_file mapping.
    commits_window : int, optional
        Number of recent commits to analyze for ownership metrics (default: 50).
        Used to limit Git history traversal for performance. Larger windows
        provide more comprehensive ownership data but take longer to compute.
    churn_windows : Sequence[int], optional
        Time windows in days for churn metric computation (default: (30, 90)).
        Each window specifies a period over which to compute churn statistics.
        Windows are normalized and sorted before use.

    Returns
    -------
    OwnershipIndex
        Aggregated ownership/churn signals keyed by repo-relative path. The index
        contains ownership records for each file with commit counts, author
        information, and churn metrics. Returns an empty index (with churn_windows
        set) when Git is unavailable, paths are empty, or repository access fails.
    """
    unique_paths = sorted({path for path in rel_paths if path})
    windows = _normalize_windows(churn_windows)
    if not unique_paths:
        return OwnershipIndex(churn_windows=windows)
    repo = _try_open_repo(repo_root)
    if repo is None:
        LOGGER.debug("GitPython unavailable; ownership analytics disabled.")
        return OwnershipIndex(churn_windows=windows)
    records = _stats_via_gitpython(
        repo=repo,
        repo_root=repo_root,
        rel_paths=unique_paths,
        commits_window=commits_window,
        windows=windows,
    )
    return OwnershipIndex(by_file=records, churn_windows=windows)


def _normalize_windows(values: Sequence[int]) -> tuple[int, ...]:
    sanitized = {max(1, int(value)) for value in values if int(value) > 0}
    if not sanitized:
        sanitized = {30}
    return tuple(sorted(sanitized))


def _try_open_repo(repo_root: Path) -> GitRepo | None:
    if _RuntimeGitRepo is None:  # pragma: no cover - GitPython not installed
        return None
    try:
        return _RuntimeGitRepo(str(repo_root))
    except GitError:  # pragma: no cover - repo open failures
        return None


def _stats_via_gitpython(
    *,
    repo: GitRepo,
    repo_root: Path,
    rel_paths: Sequence[str],
    commits_window: int,
    windows: tuple[int, ...],
) -> dict[str, FileOwnership]:
    commit_limit = max(1, commits_window)
    now = datetime.now(tz=UTC)
    cutoffs = {window: now - timedelta(days=window) for window in windows}
    rows: dict[str, FileOwnership] = {}
    for rel in rel_paths:
        try:
            commits = list(repo.iter_commits(paths=rel, max_count=commit_limit))
        except (GitError, ValueError):  # pragma: no cover - rare git failure
            commits = []
        authors: list[str] = []
        for commit in commits:
            author_name = _author_name(commit)
            if author_name:
                authors.append(author_name)
        churn_counts: dict[int, int] = dict.fromkeys(windows, 0)
        for commit in commits:
            committed = datetime.fromtimestamp(commit.committed_date, tz=UTC)
            for window, cutoff in cutoffs.items():
                if committed >= cutoff:
                    churn_counts[window] += 1
        owner = _codeowners_lookup(repo_root, rel) or (authors[0] if authors else None)
        rows[rel] = FileOwnership(
            path=rel,
            owner=owner,
            primary_authors=tuple(_top_k(authors, k=3)),
            bus_factor=_bus_factor(authors),
            churn_by_window=churn_counts,
        )
    return rows


def _author_name(commit: object) -> str | None:
    author = getattr(commit, "author", None)
    name = getattr(author, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _top_k(items: Sequence[str], k: int) -> list[str]:
    counter = Counter(items)
    return [name for name, _count in counter.most_common(k)]


def _bus_factor(authors: Sequence[str]) -> float:
    if not authors:
        return 0.0
    counter = Counter(authors)
    return round(max(counter.values()) / max(1, sum(counter.values())), 3)


def _codeowners_lookup(repo_root: Path, rel_path: str) -> str | None:
    for candidate in (".github/CODEOWNERS", "CODEOWNERS", ".gitlab/CODEOWNERS"):
        path = repo_root / candidate
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover - limited readability
            continue
        for raw_line in content.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            pattern, *owners = parts
            if owners and _glob_like_match(rel_path, pattern):
                return owners[0]
    return None


def _glob_like_match(path: str, pattern: str) -> bool:
    normalized_pattern = pattern.strip()
    if not normalized_pattern:
        return False
    if normalized_pattern.startswith("/"):
        normalized_pattern = normalized_pattern[1:]
    return fnmatch(path, normalized_pattern) or fnmatch(path, f"./{normalized_pattern}")
