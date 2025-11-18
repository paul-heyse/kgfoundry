# ruff: noqa: S101 - pytest-style assertions are intentional.
"""Smoke test for writing module rows to DuckDB."""

from __future__ import annotations

from pathlib import Path

import pytest
from codeintel_rev.app.readiness import raise_on_errors, validate_paths
from codeintel_rev.config.paths import resolve_application_paths
from codeintel_rev.services.enrich.context import PipelineContext
from codeintel_rev.services.enrich.scan import scan_repo
from codeintel_rev.services.enrich.to_duckdb import write_to_duckdb

# ruff: noqa: S101 - pytest-style assertions are intentional.


def _prepare_repo(tmp_path: Path) -> Path:
    """Create a repo layout suitable for readiness checks.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path provided by pytest fixture.

    Returns
    -------
    Path
        Base directory path containing the repository structure.
    """
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    for required in ("config", "logs", ".cache", ".tmp", "plugins"):
        (repo / required).mkdir(parents=True, exist_ok=True)
    (repo / "config" / "app.yml").write_text("", encoding="utf-8")
    return repo


def test_write_to_duckdb(tmp_path: Path) -> None:
    """write_to_duckdb should insert as many rows as scan_repo produces."""
    pytest.importorskip("duckdb")
    repo = _prepare_repo(tmp_path)
    out_dir = repo / ".out"
    paths = resolve_application_paths({"BASE_DIR": repo, "DATA_DIR": out_dir})
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    raise_on_errors(validate_paths(paths))
    ctx = PipelineContext.from_paths(
        paths, enable_db=True, duckdb_path=str(out_dir / "enrich.duckdb")
    )
    records = scan_repo(ctx)
    write_to_duckdb(ctx, records, table="modules", replace=True)
    assert ctx.db is not None
    cur = ctx.db.cursor()
    row = cur.execute('SELECT COUNT(*) FROM "modules"').fetchone()
    assert row is not None
    count = row[0]
    assert int(count) == len(records)
