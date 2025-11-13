# SPDX-License-Identifier: MIT
"""Hotspot scoring utilities."""

from __future__ import annotations

import math
import shutil
import subprocess  # lint-ignore[S404]: subprocess required for git metrics
from functools import lru_cache
from pathlib import Path
from typing import Any


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

    Parameters
    ----------
    path : str
        Relative file path from repository root.

    Returns
    -------
    int
        Commit count derived from ``git log`` output.
    """
    repo_root = Path(__file__).resolve().parents[1]
    git_executable = shutil.which("git") or "git"
    target = repo_root / path
    if not target.exists():
        return 0
    try:
        # lint-ignore[S603]: git log invocation for analytics
        result = subprocess.run(
            [git_executable, "log", "--pretty=oneline", "--", str(target)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=repo_root,
            check=False,
        )
    except OSError:
        return 0
    return len([line for line in result.stdout.splitlines() if line.strip()])
