# ruff: noqa: S101 - pytest-style assertions are intentional.
"""CLI tests for the analytics command."""

from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.cli.enrich.__main__ import app  # noqa: PLC2701
from typer.testing import CliRunner


def _prepare_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal repo and readiness directories.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path provided by pytest fixture.

    Returns
    -------
    tuple[Path, Path]
        Tuple containing (repository root directory, output directory) paths.
    """
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (repo / "config").mkdir(parents=True)
    (repo / "config" / "app.yml").write_text("", encoding="utf-8")
    for required in ("logs", ".cache", ".tmp", "plugins"):
        (repo / required).mkdir(parents=True, exist_ok=True)
    out_dir = repo / ".out"
    out_dir.mkdir(parents=True, exist_ok=True)
    return repo, out_dir


def test_cli_analytics(tmp_path: Path) -> None:
    """Analytics should report summary stats for the repo."""
    runner = CliRunner()
    repo, out_dir = _prepare_repo(tmp_path)
    result = runner.invoke(
        app,
        [
            "analytics",
            "--repo-root",
            str(repo),
            "--out-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    stats = json.loads(result.stdout)
    expected_files = sum(1 for _ in repo.rglob("*.py"))
    expected_loc = sum(len(path.read_text().splitlines()) for path in repo.rglob("*.py"))
    assert stats["files"] == expected_files
    assert stats["loc_total"] == expected_loc
    assert stats["tags"] == {}
