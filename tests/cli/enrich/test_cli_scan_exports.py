# ruff: noqa: S101 - pytest-style assertions are intentional.
"""End-to-end tests for scan and exports CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.cli.enrich.__main__ import app  # noqa: PLC2701
from typer.testing import CliRunner


def _prepare_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a repo with readiness directories and an out dir.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path provided by pytest fixture.

    Returns
    -------
    tuple[Path, Path]
        Tuple containing (base directory, output directory) paths.
    """
    repo = tmp_path / "repo"
    package = repo / "pkg"
    package.mkdir(parents=True)
    (package / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    base = repo
    for required in ("config", "logs", ".cache", ".tmp", "plugins"):
        (base / required).mkdir(parents=True, exist_ok=True)
    (base / "config" / "app.yml").write_text("", encoding="utf-8")
    out_dir = base / ".out"
    out_dir.mkdir(parents=True, exist_ok=True)
    return base, out_dir


def test_cli_scan_and_exports(tmp_path: Path) -> None:
    """Test that scan and exports commands produce expected output files."""
    runner = CliRunner()
    repo, out_dir = _prepare_repo(tmp_path)
    res_scan = runner.invoke(app, ["scan", "--repo-root", str(repo), "--out-dir", str(out_dir)])
    assert res_scan.exit_code == 0, res_scan.output

    res_exports = runner.invoke(
        app, ["exports", "--repo-root", str(repo), "--out-dir", str(out_dir)]
    )
    assert res_exports.exit_code == 0, res_exports.output

    modules = out_dir / "modules.jsonl"
    rows = [
        json.loads(line)
        for line in modules.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(row["module"] == "pkg.mod" for row in rows)
    assert (out_dir / "repo_map.json").exists()
    assert (out_dir / "tag_index.json").exists()
    assert (out_dir / "sheets" / "pkg-mod.md").exists()
