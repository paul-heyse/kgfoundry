# ruff: noqa: S101 - pytest-style assertions are intentional.
"""CLI test for the to-duckdb command."""

from __future__ import annotations

from pathlib import Path

import pytest
from codeintel_rev.cli.enrich.__main__ import app  # noqa: PLC2701
from typer.testing import CliRunner


def _prepare_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a repo and out dir with readiness expectations.

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
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    base = repo
    for required in ("config", "logs", ".cache", ".tmp", "plugins"):
        (base / required).mkdir(parents=True, exist_ok=True)
    (base / "config" / "app.yml").write_text("", encoding="utf-8")
    out_dir = base / ".out"
    out_dir.mkdir(parents=True, exist_ok=True)
    return base, out_dir


def test_cli_to_duckdb(tmp_path: Path) -> None:
    """to-duckdb should populate the requested DuckDB table."""
    duckdb = pytest.importorskip("duckdb")
    runner = CliRunner()
    repo, out_dir = _prepare_repo(tmp_path)
    db_path = out_dir / "enrich.duckdb"
    result = runner.invoke(
        app,
        [
            "to-duckdb",
            "--repo-root",
            str(repo),
            "--out-dir",
            str(out_dir),
            "--duckdb-path",
            str(db_path),
            "--table",
            "modules",
        ],
    )
    assert result.exit_code == 0, result.output
    conn = duckdb.connect(str(db_path))
    try:
        count = conn.execute('SELECT COUNT(*) FROM "modules"').fetchone()[0]
        assert int(count) >= 1
    finally:
        conn.close()
