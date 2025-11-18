# ruff: noqa: S101 - pytest-style assertions are intentional.
"""Golden tests for basic analytics stats."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.app.readiness import raise_on_errors, validate_paths
from codeintel_rev.config.paths import resolve_application_paths
from codeintel_rev.services.enrich.analytics import basic_stats
from codeintel_rev.services.enrich.context import PipelineContext
from codeintel_rev.services.enrich.scan import scan_repo

# ruff: noqa: S101 - pytest-style assertions are intentional.


def _prepare_repo(tmp_path: Path) -> Path:
    """Create a repo with cli and test modules.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path provided by pytest fixture.

    Returns
    -------
    Path
        Repository root directory path.
    """
    repo = tmp_path / "repo"
    (repo / "pkg" / "cli").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (repo / "pkg" / "cli" / "entry.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (repo / "tests" / "test_mod.py").write_text("def test_f():\n    assert 1\n", encoding="utf-8")
    for required in ("config", "logs", ".cache", ".tmp", "plugins"):
        (repo / required).mkdir(parents=True, exist_ok=True)
    (repo / "config" / "app.yml").write_text("", encoding="utf-8")
    return repo


def test_basic_stats(tmp_path: Path) -> None:
    """basic_stats should report deterministic values for the fixture repo."""
    repo = _prepare_repo(tmp_path)
    out_dir = repo / ".out"
    paths = resolve_application_paths({"BASE_DIR": repo, "DATA_DIR": out_dir})
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    raise_on_errors(validate_paths(paths))
    ctx = PipelineContext.from_paths(paths)
    records = scan_repo(ctx)
    stats = basic_stats(ctx, records)
    expected_files = len(records)
    expected_loc = sum(record.loc for record in records)
    assert stats["files"] == expected_files
    assert stats["loc_total"] == expected_loc
    assert stats["tags"].get("cli") == 1
    assert stats["tags"].get("test") == 1
