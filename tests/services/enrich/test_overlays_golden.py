# ruff: noqa: S101 - pytest-style assertions are intentional.
"""Golden tests for overlay merging and exports."""

from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.app.readiness import raise_on_errors, validate_paths
from codeintel_rev.config.paths import resolve_application_paths
from codeintel_rev.services.enrich.context import PipelineContext
from codeintel_rev.services.enrich.exports import run_all_exports
from codeintel_rev.services.enrich.overlays import apply_overlays
from codeintel_rev.services.enrich.scan import scan_repo

# ruff: noqa: S101 - pytest-style assertions are intentional.


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "enrich-golden"


def _prepare_repo(tmp_path: Path) -> Path:
    """Create a repo with overlay-ready modules.

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
    (repo / "pkg" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (repo / "pkg" / "cli" / "entry.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    for required in ("config", "logs", ".cache", ".tmp", "plugins"):
        (repo / required).mkdir(parents=True, exist_ok=True)
    (repo / "config" / "app.yml").write_text("", encoding="utf-8")
    return repo


def _load_modules(path: Path) -> list[dict[str, object]]:
    """Return JSONL rows as dictionaries.

    Parameters
    ----------
    path : Path
        Path to JSONL file containing module records.

    Returns
    -------
    list[dict[str, object]]
        List of module dictionaries parsed from JSONL file.
    """
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_overlays_merge_and_export(tmp_path: Path) -> None:
    """apply_overlays should merge metadata and exports should persist it."""
    repo = _prepare_repo(tmp_path)
    out_dir = repo / ".out"
    paths = resolve_application_paths({"BASE_DIR": repo, "DATA_DIR": out_dir})
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    raise_on_errors(validate_paths(paths))

    ctx = PipelineContext.from_paths(paths)
    records = apply_overlays(
        ctx,
        scan_repo(ctx),
        [FIXTURES / "overlay.json", FIXTURES / "overlay.jsonl"],
    )
    result = run_all_exports(ctx, records)

    modules = _load_modules(result.modules_jsonl)
    pkg_mod = next(row for row in modules if row["module"] == "pkg.mod")
    raw_meta = pkg_mod.get("meta")
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    assert meta.get("owner") == "platform"
    assert meta.get("component") == "search"
    assert meta.get("risk") == "low"
