# SPDX-License-Identifier: MIT
"""Ownership, churn, and bus-factor analytics sourced from Git history."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

try:  # pragma: no cover - optional dependency
    from git import Repo as _RuntimeGitRepo
    from git import exc as git_exc
except ImportError:  # pragma: no cover
    _RuntimeGitRepo = None
    git_exc = None

if TYPE_CHECKING:  # pragma: no cover - typing only
    from git import Repo as GitRepo
else:

    class GitRepo:  # pragma: no cover - runtime placeholder
        """Runtime placeholder for optional GitPython dependency."""


GitError = git_exc.GitError if git_exc is not None else Exception

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
    """Normalize churn time window values to valid positive integers.

    This function sanitizes churn window values by ensuring they are positive
    integers (minimum 1), removing invalid entries, and providing a default
    window of 30 days if no valid windows are provided. The normalized windows
    are sorted for consistent processing in downstream analysis.

    Parameters
    ----------
    values : Sequence[int]
        Sequence of time window values in days. Values are validated and
        sanitized to ensure they are positive integers.

    Returns
    -------
    tuple[int, ...]
        Sorted tuple of normalized window values, each guaranteed to be at
        least 1 day. Returns (30,) if no valid windows are provided.

    Notes
    -----
    Window normalization ensures consistent churn metric computation by
    validating input values and providing sensible defaults. The function
    handles edge cases like empty sequences, zero or negative values, and
    ensures all windows are positive integers suitable for time delta calculations.
    """
    sanitized = {max(1, int(value)) for value in values if int(value) > 0}
    if not sanitized:
        sanitized = {30}
    return tuple(sorted(sanitized))


def _try_open_repo(repo_root: Path) -> GitRepo | None:
    """Attempt to open a Git repository at the specified root directory.

    This function attempts to initialize a GitPython repository object for the
    given root directory. It handles cases where GitPython is not installed or
    where the directory is not a valid Git repository by returning None. Used
    to safely access Git history for ownership and churn analysis.

    Parameters
    ----------
    repo_root : Path
        Root directory path that should contain a .git directory. The path
        is converted to a string for GitPython compatibility.

    Returns
    -------
    GitRepo | None
        GitPython Repo object if the repository is successfully opened, or None
        if GitPython is unavailable, the directory is not a Git repository, or
        repository access fails.

    Notes
    -----
    This function provides graceful degradation when Git is unavailable, allowing
    the ownership computation to proceed without Git history. The function is
    designed to be safe to call even when GitPython is not installed, making it
    suitable for environments where Git analysis is optional.
    """
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
    """Compute ownership and churn statistics for files using GitPython.

    This function analyzes Git commit history to compute ownership metrics including
    primary authors, bus factor, and churn counts over specified time windows for
    each file. The function iterates through recent commits for each file, extracts
    author information, and computes aggregated statistics. Ownership is determined
    by CODEOWNERS file lookup or by identifying the most frequent committer.

    Parameters
    ----------
    repo : GitRepo
        GitPython repository object providing access to commit history. Must be
        a valid, initialized repository.
    repo_root : Path
        Root directory of the repository, used for CODEOWNERS file lookup and
        path resolution.
    rel_paths : Sequence[str]
        Sequence of repository-relative file paths to analyze. Each path is
        processed independently to compute its ownership metrics.
    commits_window : int
        Maximum number of recent commits to analyze per file. Limits history
        traversal for performance while providing sufficient data for ownership
        analysis.
    windows : tuple[int, ...]
        Time windows in days for churn metric computation. Each window specifies
        a period over which to count commits, enabling analysis of change frequency
        over different time scales.

    Returns
    -------
    dict[str, FileOwnership]
        Dictionary mapping repository-relative file paths to their FileOwnership
        records. Each record contains ownership information, primary authors,
        bus factor, and churn counts per window. Files with no commit history or
        access errors are excluded from the result.

    Notes
    -----
    This function performs the core ownership analysis by leveraging Git history.
    It handles errors gracefully by skipping files that cannot be analyzed, ensuring
    partial results are returned even if some files fail. The bus factor calculation
    measures code concentration (higher values indicate more concentrated ownership),
    while churn windows help identify frequently changing files that may need
    attention.
    """
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
    """Extract author name from a Git commit object.

    This function safely extracts the author name from a Git commit object by
    accessing the author attribute and its name property. The function handles
    cases where the commit object structure may vary or where author information
    is missing, returning None in such cases.

    Parameters
    ----------
    commit : object
        Git commit object (typically a GitPython Commit object) containing author
        information. The object should have an 'author' attribute with a 'name'
        property.

    Returns
    -------
    str | None
        Author name string if successfully extracted and non-empty, or None if
        the author information is missing, invalid, or empty. The returned name
        is stripped of leading/trailing whitespace.

    Notes
    -----
    This helper function provides safe access to commit author information,
    handling variations in GitPython object structure and missing data gracefully.
    It ensures that only valid, non-empty author names are returned for use in
    ownership analysis.
    """
    author = getattr(commit, "author", None)
    name = getattr(author, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _top_k(items: Sequence[str], k: int) -> list[str]:
    """Extract the top K most frequent items from a sequence.

    This function counts item frequencies and returns the K most common items
    in descending order of frequency. Used to identify primary authors or most
    frequent contributors for ownership analysis.

    Parameters
    ----------
    items : Sequence[str]
        Sequence of items (typically author names) to count and rank. Duplicate
        items are counted, and the most frequent items are selected.
    k : int
        Number of top items to return. The function returns at most K items,
        fewer if the sequence contains fewer than K unique items.

    Returns
    -------
    list[str]
        List of the K most frequent items, ordered by frequency (most frequent
        first). The list length is min(k, len(unique_items)).

    Notes
    -----
    This function uses Counter for efficient frequency counting and provides
    a simple interface for extracting top contributors. It's used to identify
    primary authors for files, helping understand code ownership patterns.
    """
    counter = Counter(items)
    return [name for name, _count in counter.most_common(k)]


def _bus_factor(authors: Sequence[str]) -> float:
    """Calculate bus factor metric measuring code ownership concentration.

    The bus factor measures how concentrated code ownership is by computing the
    ratio of the most frequent contributor's commits to total commits. A higher
    bus factor (closer to 1.0) indicates more concentrated ownership (higher risk
    if that person leaves), while a lower value indicates more distributed ownership
    (lower risk). The metric ranges from 0.0 (perfectly distributed) to 1.0
    (single contributor).

    Parameters
    ----------
    authors : Sequence[str]
        Sequence of author names from commit history. Each occurrence represents
        a commit by that author, enabling frequency analysis.

    Returns
    -------
    float
        Bus factor value between 0.0 and 1.0, rounded to 3 decimal places. Returns
        0.0 if the authors sequence is empty. Higher values indicate more
        concentrated ownership.

    Notes
    -----
    The bus factor is a critical metric for assessing code health and maintenance
    risk. Files with high bus factors (close to 1.0) are at risk if the primary
    contributor becomes unavailable. This metric helps teams identify files that
    may need knowledge sharing or documentation efforts to reduce single points
    of failure.
    """
    if not authors:
        return 0.0
    counter = Counter(authors)
    return round(max(counter.values()) / max(1, sum(counter.values())), 3)


def _codeowners_lookup(repo_root: Path, rel_path: str) -> str | None:
    """Look up file owner from CODEOWNERS file using pattern matching.

    This function searches for CODEOWNERS files in standard locations (.github/CODEOWNERS,
    CODEOWNERS, .gitlab/CODEOWNERS) and matches the given file path against patterns
    in the CODEOWNERS file. Returns the first matching owner for the file path.
    CODEOWNERS files use glob-like patterns to specify ownership rules, enabling
    declarative ownership assignment.

    Parameters
    ----------
    repo_root : Path
        Root directory of the repository where CODEOWNERS files are located. The
        function checks multiple standard locations relative to this root.
    rel_path : str
        Repository-relative file path to look up ownership for. The path is matched
        against patterns in the CODEOWNERS file to determine ownership.

    Returns
    -------
    str | None
        Owner name (typically GitHub username) if a matching CODEOWNERS entry is
        found, or None if no CODEOWNERS file exists, cannot be read, or no pattern
        matches the file path.

    Notes
    -----
    CODEOWNERS files provide a declarative way to assign code ownership, which is
    particularly useful for large codebases with clear module boundaries. This
    function supports the standard CODEOWNERS format used by GitHub and GitLab,
    enabling integration with platform-native ownership features. Pattern matching
    follows glob-like rules, with support for leading slashes and wildcards.
    """
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
    """Match a file path against a glob-like pattern from CODEOWNERS.

    This function performs pattern matching compatible with CODEOWNERS file format,
    which uses glob-like patterns (e.g., "*.py", "src/**", "/docs/"). The function
    handles leading slashes in patterns (which indicate root-relative matching) and
    supports both direct path matching and matching with a leading "./" prefix for
    compatibility with different path formats.

    Parameters
    ----------
    path : str
        Repository-relative file path to match against the pattern. The path should
        not include a leading slash.
    pattern : str
        Glob-like pattern from CODEOWNERS file (e.g., "*.py", "src/**", "/docs/").
        Leading slashes are stripped to enable root-relative matching, and the pattern
        is matched against both the path and "./{path}" variants.

    Returns
    -------
    bool
        True if the path matches the pattern, False otherwise. Empty patterns
        always return False.

    Notes
    -----
    This function implements CODEOWNERS pattern matching semantics, which are similar
    to shell glob patterns but with some differences. The function handles common
    edge cases like leading slashes and path format variations to ensure reliable
    ownership lookup. Pattern matching uses Python's fnmatch module, which provides
    glob-compatible matching.
    """
    normalized_pattern = pattern.strip()
    if not normalized_pattern:
        return False
    if normalized_pattern.startswith("/"):
        normalized_pattern = normalized_pattern[1:]
    return fnmatch(path, normalized_pattern) or fnmatch(path, f"./{normalized_pattern}")
