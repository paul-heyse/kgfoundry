# SPDX-License-Identifier: MIT
"""End-to-end smoke test for the enrichment CLI's extended analytics."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from codeintel_rev.cli_enrich import app
from typer.testing import CliRunner


def _git_env() -> dict[str, str]:
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


def _init_repo(repo_root: Path) -> None:
    env = _git_env()
    git_bin = _git_executable()
    subprocess.run([git_bin, "init"], cwd=repo_root, check=True, env=env)
    subprocess.run(
        [git_bin, "config", "user.name", "Smoke Tester"], cwd=repo_root, check=True, env=env
    )
    subprocess.run(
        [git_bin, "config", "user.email", "smoke@example.com"],
        cwd=repo_root,
        check=True,
        env=env,
    )


def _write_repo(repo_root: Path) -> None:
    pkg = repo_root / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(
        '"""Pkg root for smoke tests."""\n__all__ = ["alpha"]\n', encoding="utf-8"
    )
    (pkg / "alpha.py").write_text(
        '''
"""Alpha module."""
__all__ = ["alpha_fn"]
from pkg import beta

def alpha_fn() -> str:
    return beta.beta_fn()
'''.strip(),
        encoding="utf-8",
    )
    (pkg / "beta.py").write_text(
        '''
"""Beta module."""

def beta_fn() -> str:
    return "beta"
'''.strip(),
        encoding="utf-8",
    )
    (repo_root / "CODEOWNERS").write_text("pkg/alpha.py @alpha-owner\n", encoding="utf-8")


def _seed_initial_commit(repo_root: Path) -> None:
    env = _git_env()
    git_bin = _git_executable()
    subprocess.run([git_bin, "add", "."], cwd=repo_root, check=True, env=env)
    subprocess.run([git_bin, "commit", "-m", "initial"], cwd=repo_root, check=True, env=env)


def _write_scip(repo_root: Path) -> Path:
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


def _git_executable() -> str:
    return shutil.which("git") or "git"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    buffer: list[str] = []
    depth = 0
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        buffer.append(line)
        depth += line.count("{") - line.count("}")
        if depth == 0 and buffer:
            records.append(json.loads("\n".join(buffer)))
            buffer.clear()
    return records


def test_cli_enrich_emits_extended_artifacts(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_repo(repo_root)
    _write_repo(repo_root)
    _seed_initial_commit(repo_root)
    scip_path = _write_scip(repo_root)
    out_dir = tmp_path / "out"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "all",
            "--root",
            str(repo_root),
            "--scip",
            str(scip_path),
            "--out",
            str(out_dir),
            "--owners",
            "--emit-slices",
            "--slices-filter",
            "public-api",
            "--max-file-bytes",
            "8192",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    module_rows = _read_jsonl(out_dir / "modules" / "modules.jsonl")
    assert module_rows
    alpha_row = next(row for row in module_rows if str(row.get("path", "")).endswith("alpha.py"))
    assert alpha_row["owner"] == "@alpha-owner"
    assert alpha_row["primary_authors"]
    assert alpha_row.get("stable_id")
    assert str(alpha_row.get("repo_path", "")).endswith("pkg/alpha.py")
    assert str(alpha_row.get("path", "")).endswith("alpha.py")
    assert "recent_churn_30" in alpha_row

    ownership_parquet = out_dir / "analytics" / "ownership.parquet"
    fallback_jsonl = ownership_parquet.with_suffix(".parquet.jsonl")
    assert ownership_parquet.exists() or fallback_jsonl.exists()

    slices_dir = out_dir / "slices"
    assert (slices_dir / "index.parquet").exists()
    slices_jsonl = slices_dir / "slices.jsonl"
    assert slices_jsonl.exists()
    slice_records = _read_jsonl(slices_jsonl)
    assert any(str(record.get("path", "")).endswith("alpha.py") for record in slice_records)

    graphs_dir = out_dir / "graphs"
    assert (graphs_dir / "imports.parquet").exists()
    assert (graphs_dir / "uses.parquet").exists()
