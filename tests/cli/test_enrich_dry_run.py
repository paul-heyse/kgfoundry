# SPDX-License-Identifier: MIT
"""CLI surface tests covering the `--dry-run` flag."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from codeintel_rev.cli_enrich import app
from typer.testing import CliRunner


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "DryRun Tester")
    env.setdefault("GIT_AUTHOR_EMAIL", "dryrun@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "DryRun Tester")
    env.setdefault("GIT_COMMITTER_EMAIL", "dryrun@example.com")
    return env


def _git() -> str:
    return shutil.which("git") or "git"


def _init_repo(repo_root: Path) -> None:
    env = _git_env()
    subprocess.run([_git(), "init"], cwd=repo_root, check=True, env=env)
    subprocess.run(
        [_git(), "config", "user.name", env["GIT_AUTHOR_NAME"]], cwd=repo_root, check=True, env=env
    )
    subprocess.run(
        [_git(), "config", "user.email", env["GIT_AUTHOR_EMAIL"]],
        cwd=repo_root,
        check=True,
        env=env,
    )


def _write_repo(repo_root: Path) -> None:
    pkg = repo_root / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(
        '"""Pkg root for dry-run tests."""\n__all__ = ["alpha"]\n', encoding="utf-8"
    )
    (pkg / "alpha.py").write_text(
        """
from pkg import beta

def alpha_fn() -> str:
    return beta.beta_fn()
""".strip(),
        encoding="utf-8",
    )
    (pkg / "beta.py").write_text(
        """
def beta_fn() -> str:
    return "beta"
""".strip(),
        encoding="utf-8",
    )
    env = _git_env()
    subprocess.run([_git(), "add", "."], cwd=repo_root, check=True, env=env)
    subprocess.run([_git(), "commit", "-m", "initial"], cwd=repo_root, check=True, env=env)


def _write_scip(repo_root: Path) -> Path:
    payload = {
        "documents": [
            {
                "relativePath": "pkg/alpha.py",
                "occurrences": [{"symbol": "pkg.alpha.alpha_fn", "roles": ["definition"]}],
                "symbols": [{"symbol": "pkg.alpha.alpha_fn", "kind": "function"}],
            }
        ]
    }
    scip_path = repo_root / "index.scip.json"
    scip_path.write_text(json.dumps(payload), encoding="utf-8")
    return scip_path


def test_dry_run_skips_artifact_writes(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_repo(repo_root)
    _write_repo(repo_root)
    scip_path = _write_scip(repo_root)
    out_dir = tmp_path / "out"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "all",
            "--dry-run",
            "--root",
            str(repo_root),
            "--scip",
            str(scip_path),
            "--out",
            str(out_dir),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.stdout
    assert not (out_dir / "modules").exists()
