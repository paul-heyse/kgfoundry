"""Helpers for constructing sample git repositories for CLI tests."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from tests._helpers.process import run_process


@dataclass(frozen=True)
class SampleRepo:
    """Description of a bootstrapped repository used in CLI tests."""

    root: Path
    scip_path: Path


def git_env() -> dict[str, str]:
    """Return git environment variables with deterministic identity.

    Returns
    -------
    dict[str, str]
        Environment variables used when shelling out to git.
    """
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Smoke Tester",
            "GIT_AUTHOR_EMAIL": "smoke@example.com",
            "GIT_COMMITTER_NAME": "Smoke Tester",
            "GIT_COMMITTER_EMAIL": "smoke@example.com",
        }
    )
    return env


def git_executable() -> str:
    """Best-effort discovery of the git binary.

    Returns
    -------
    str
        Resolved git executable path.
    """
    return shutil.which("git") or "git"


def init_git_repo(root: Path) -> None:
    env = git_env()
    git_bin = git_executable()
    run_process([git_bin, "init"], cwd=root, env=env)
    run_process([git_bin, "config", "user.name", "Smoke Tester"], cwd=root, env=env)
    run_process([git_bin, "config", "user.email", "smoke@example.com"], cwd=root, env=env)


def write_sample_modules(repo_root: Path) -> None:
    pkg = repo_root / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(
        '"""Pkg root for smoke tests."""\n__all__ = ["alpha"]\n', encoding="utf-8"
    )
    (pkg / "alpha.py").write_text(
        (
            '"""Alpha module."""\n'
            "__all__ = ['alpha_fn']\n"
            "from pkg import beta\n\n"
            "def alpha_fn() -> str:\n"
            "    return beta.beta_fn()\n"
        ),
        encoding="utf-8",
    )
    (pkg / "beta.py").write_text(
        ('"""Beta module."""\n\ndef beta_fn() -> str:\n    return "beta"\n'),
        encoding="utf-8",
    )
    (repo_root / "CODEOWNERS").write_text("pkg/alpha.py @alpha-owner\n", encoding="utf-8")


def seed_initial_commit(repo_root: Path) -> None:
    env = git_env()
    git_bin = git_executable()
    run_process([git_bin, "add", "."], cwd=repo_root, env=env)
    run_process([git_bin, "commit", "-m", "initial"], cwd=repo_root, env=env)


def write_scip_index(repo_root: Path) -> Path:
    """Materialize a minimal SCIP index for the ``repo_root`` modules.

    Returns
    -------
    Path
        Path to the generated ``index.scip.json`` file.
    """
    scip_data = {
        "documents": [
            {
                "relativePath": "pkg/alpha.py",
                "occurrences": [
                    {"symbol": "pkg.alpha.alpha_fn", "roles": ["definition"]},
                    {"symbol": "pkg.beta.beta_fn", "roles": ["reference"]},
                ],
                "symbols": [{"symbol": "pkg.alpha.alpha_fn", "kind": "function"}],
            },
            {
                "relativePath": "pkg/beta.py",
                "occurrences": [
                    {"symbol": "pkg.beta.beta_fn", "roles": ["definition"]},
                    {"symbol": "pkg.alpha.alpha_fn", "roles": ["reference"]},
                ],
                "symbols": [
                    {"symbol": "pkg.beta.beta_fn", "kind": "function"},
                ],
            },
        ]
    }
    scip_path = repo_root / "index.scip.json"
    scip_path.write_text(json.dumps(scip_data), encoding="utf-8")
    return scip_path


def bootstrap_sample_repo(base_dir: Path) -> SampleRepo:
    """Create a git repo with sample modules and a SCIP index.

    Returns
    -------
    SampleRepo
        Dataclass describing the repo root and SCIP index path.
    """
    root = base_dir / "repo"
    root.mkdir(parents=True, exist_ok=True)
    init_git_repo(root)
    write_sample_modules(root)
    seed_initial_commit(root)
    scip_path = write_scip_index(root)
    return SampleRepo(root=root, scip_path=scip_path)
