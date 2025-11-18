# ruff: noqa: S101 - pytest-style assertions are intentional.
"""Golden tests for the enrich export services."""

from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.app.readiness import raise_on_errors, validate_paths
from codeintel_rev.config.paths import ResolvedPaths, resolve_application_paths
from codeintel_rev.services.enrich.context import PipelineContext
from codeintel_rev.services.enrich.exports import run_all_exports
from codeintel_rev.services.enrich.scan import scan_repo

# ruff: noqa: S101 - pytest-style assertions are intentional.


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "enrich-golden"


def _sanitize_modules(path: Path, repo_root: Path | None = None) -> list[dict[str, object]]:
    """Normalize module rows for stable assertions.

    Parameters
    ----------
    path : Path
        Path to JSONL file containing module records.
    repo_root : Path | None
        Optional repository root used to relativize module paths.

    Returns
    -------
    list[dict[str, object]]
        List of module dictionaries with normalized metadata (mtime set to 0)
        and sorted by module name for deterministic comparison.
    """
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    for row in rows:
        path_value = Path(row["path"])
        if repo_root is not None:
            try:
                row["path"] = path_value.relative_to(repo_root).as_posix()
            except ValueError:
                row["path"] = path_value.as_posix()
        else:
            row["path"] = path_value.as_posix()
        row["meta"] = {"mtime": 0}
    rows.sort(key=lambda row: row["module"])
    return rows


def test_exports_match_golden(tmp_path: Path) -> None:
    """run_all_exports should match the golden artifacts for a tiny repo."""
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    for required in ("config", "logs", ".cache", ".tmp", "plugins"):
        (repo / required).mkdir(parents=True, exist_ok=True)
    (repo / "config" / "app.yml").write_text("", encoding="utf-8")

    paths = resolve_application_paths({"BASE_DIR": repo, "DATA_DIR": repo / ".out"})
    _ensure_readiness(paths)
    raise_on_errors(validate_paths(paths))

    ctx = PipelineContext.from_paths(paths)
    result = run_all_exports(ctx, scan_repo(ctx))

    expected_modules = _sanitize_modules(FIXTURES / "modules.jsonl")
    actual_modules = _sanitize_modules(result.modules_jsonl, repo_root=paths.repo_root)
    assert actual_modules == expected_modules

    assert json.loads(result.repo_map.read_text(encoding="utf-8")) == json.loads(
        (FIXTURES / "repo_map.json").read_text(encoding="utf-8")
    )
    assert json.loads(result.tag_index.read_text(encoding="utf-8")) == json.loads(
        (FIXTURES / "tag_index.json").read_text(encoding="utf-8")
    )
    assert (result.markdown_dir / "pkg-mod.md").read_text(encoding="utf-8") == (
        FIXTURES / "sheets" / "pkg-mod.md"
    ).read_text(encoding="utf-8")


def _ensure_readiness(paths: ResolvedPaths) -> None:
    """Create the expected config file and data directory for readiness checks."""
    paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    paths.config_file.write_text("", encoding="utf-8")
    paths.data_dir.mkdir(parents=True, exist_ok=True)
