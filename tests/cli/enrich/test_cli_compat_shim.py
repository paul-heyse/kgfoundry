# ruff: noqa: S101 - pytest-style assertions are intentional.
"""Compatibility tests for the legacy enrich CLI shim."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.cli.enrich.__main__ import app as new_app  # noqa: PLC2701
from codeintel_rev.cli.enrich_pipeline import app as legacy_app
from typer.testing import CliRunner


def _prepare_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a repo with readiness directories and return out dir paths.

    Returns
    -------
    tuple[Path, Path]
        Repository base directory and output directory.
    """
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    base = repo
    for required in ("config", "logs", ".cache", ".tmp", "plugins"):
        (base / required).mkdir(parents=True, exist_ok=True)
    (base / "config" / "app.yml").write_text("", encoding="utf-8")
    out_dir = base / ".out"
    out_dir.mkdir(parents=True, exist_ok=True)
    return base, out_dir


def test_legacy_help_parity() -> None:
    """Legacy shim should expose the same commands as the new CLI."""
    runner = CliRunner()
    legacy_help = runner.invoke(legacy_app, ["--help"])
    new_help = runner.invoke(new_app, ["--help"])
    assert legacy_help.exit_code == 0
    assert new_help.exit_code == 0
    for command in ("scan", "exports", "overlays", "analytics", "to-duckdb"):
        assert command in legacy_help.stdout
        assert command in new_help.stdout


def test_legacy_scan_delegates(tmp_path: Path) -> None:
    """The legacy entry point should delegate to the new implementation."""
    runner = CliRunner()
    repo, out_dir = _prepare_repo(tmp_path)
    result = runner.invoke(
        legacy_app,
        ["scan", "--repo-root", str(repo), "--out-dir", str(out_dir)],
    )
    assert result.exit_code == 0, result.output
    assert "Scanned" in result.stdout
