# ruff: noqa: S101 - pytest-style assertions are intentional.
"""CLI tests for the overlays command."""

from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.cli.enrich.__main__ import app  # noqa: PLC2701
from typer.testing import CliRunner


def _prepare_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a repo, out dir, and sample overlay file.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path provided by pytest fixture.

    Returns
    -------
    tuple[Path, Path, Path]
        Tuple containing (base directory, output directory, overlay file) paths.
    """
    repo = tmp_path / "repo"
    (repo / "pkg" / "cli").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (repo / "pkg" / "cli" / "entry.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    base = repo
    for required in ("config", "logs", ".cache", ".tmp", "plugins"):
        (base / required).mkdir(parents=True, exist_ok=True)
    (base / "config" / "app.yml").write_text("", encoding="utf-8")
    out_dir = base / ".out"
    out_dir.mkdir(parents=True, exist_ok=True)
    overlay = tmp_path / "overlay.json"
    overlay.write_text(
        json.dumps({"pkg.mod": {"owner": "core", "priority": "P1"}}), encoding="utf-8"
    )
    return base, out_dir, overlay


def test_cli_overlays(tmp_path: Path) -> None:
    """Test that overlays command applies metadata and writes exports."""
    runner = CliRunner()
    repo, out_dir, overlay = _prepare_repo(tmp_path)
    result = runner.invoke(
        app,
        [
            "overlays",
            "--repo-root",
            str(repo),
            "--out-dir",
            str(out_dir),
            "--overlay",
            str(overlay),
        ],
    )
    assert result.exit_code == 0, result.output
    modules = out_dir / "modules.jsonl"
    rows = [
        json.loads(line)
        for line in modules.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    meta = next(row for row in rows if row["module"] == "pkg.mod")["meta"]
    assert meta.get("owner") == "core"
    assert meta.get("priority") == "P1"
