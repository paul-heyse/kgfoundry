# SPDX-License-Identifier: MIT
"""Hotspot scoring utilities."""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)

try:  # pragma: no cover - optional dependency
    from git import Repo as _RuntimeGitRepo
    from git.exc import GitError
except ImportError:  # pragma: no cover - GitPython not installed
    _RuntimeGitRepo = None
    GitError = Exception

if TYPE_CHECKING:  # pragma: no cover - typing only
    from git import Repo as GitRepoType
else:  # pragma: no cover - runtime placeholder
    GitRepoType = object


def compute_hotspot_score(record: dict[str, Any]) -> float:
    """Compute a heuristic hotspot score for a module record.

    Parameters
    ----------
    record : dict[str, Any]
        Module metadata dictionary containing metrics such as fan_in, fan_out,
        complexity, type_errors, untyped_defs, covered_lines_ratio, and path.

    Returns
    -------
    float
        Score in the range ``[0, 10]`` representing relative risk.
    """
    fan_in = float(record.get("fan_in") or 0)
    fan_out = float(record.get("fan_out") or 0)
    cyclomatic = float(record.get("complexity", {}).get("cyclomatic", 0))
    type_errors = float(record.get("type_errors") or 0)
    untyped = float(record.get("untyped_defs") or 0)
    coverage = float(record.get("covered_lines_ratio") or 0.0)
    churn = float(_git_churn(record["path"]) or 0)

    structural = math.log1p(fan_in + fan_out) * 0.4
    complexity = math.log1p(cyclomatic + untyped) * 0.3
    type_risk = math.log1p(type_errors + 1) * 0.2
    churn_component = math.log1p(churn + 1) * 0.3
    coverage_penalty = (1 - coverage) * 0.2
    score = structural + complexity + type_risk + churn_component + coverage_penalty
    return round(min(score, 10.0), 3)


@lru_cache(maxsize=2048)
def _git_churn(path: str) -> int:
    """Return the number of commits touching ``path``.

    This function queries Git history to count the number of commits that modified
    a specific file path. The function uses GitPython when available, or returns
    zero when Git is unavailable or the repository cannot be accessed.

    Parameters
    ----------
    path : str
        Repository-relative file path to query commit history for. The path is
        used to filter Git commits that modified this specific file. Must be a
        valid path within the repository.

    Returns
    -------
    int
        Number of commits that touched the specified path. Returns 0 when Git is
        unavailable, the repository cannot be opened, or the path has no commit
        history. Used as a churn metric for risk hotspot analysis.
    """
    repo = _open_repo()
    if repo is None:
        return 0
    target = _repo_root() / path
    if not target.exists():
        return 0
    try:
        return sum(1 for _ in repo.iter_commits(paths=str(target)))
    except (GitError, OSError, ValueError):  # pragma: no cover - git failure
        LOGGER.debug("Failed to compute churn for %s", path, exc_info=True)
        return 0


@lru_cache(maxsize=1)
def _open_repo() -> GitRepoType | None:
    """Open project Git repository for analytics.

    Returns
    -------
    GitRepoType | None
        Git repository handle or ``None`` if GitPython unavailable.
    """
    if _RuntimeGitRepo is None:
        LOGGER.debug("GitPython unavailable; churn analytics disabled.")
        return None
    try:
        return _RuntimeGitRepo(str(_repo_root()))
    except (GitError, OSError):  # pragma: no cover - repo open failure
        LOGGER.debug("Unable to open Git repository for hotspot metrics.", exc_info=True)
        return None


@lru_cache(maxsize=1)
def _repo_root() -> Path:
    """Return repository root path.

    Returns
    -------
    Path
        Absolute path to the repository root (two levels up from this file).
    """
    return Path(__file__).resolve().parents[1]
