# SPDX-License-Identifier: MIT
"""Tests for export service helpers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from codeintel_rev.enrich.graph_builder import ImportGraph
from codeintel_rev.enrich.models import ModuleRecord
from codeintel_rev.services.enrich import exports as export_services
from codeintel_rev.services.enrich.context import PipelineResult
from codeintel_rev.uses_builder import UseGraph

from tests._helpers import assertions


def _build_result(tmp_path: Path) -> PipelineResult:
    module_path = tmp_path / "pkg" / "app.py"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text("print('ok')\n", encoding="utf-8")
    record = ModuleRecord(
        path=str(module_path),
        repo_path=str(module_path),
        module_name="pkg.app",
    )
    record.tags = ["demo"]
    record.exports = ["run"]
    return PipelineResult(
        root=tmp_path,
        repo_root=tmp_path,
        module_rows=[record],
        symbol_edges=[("sym::demo", "pkg/app.py")],
        import_graph=ImportGraph(edges={}, fan_in={}, fan_out={}, cycle_group={}),
        use_graph=UseGraph(uses_by_file={}, symbol_usage={}, edges=[]),
        config_index=[],
        coverage_rows=[],
        hotspot_rows=[],
        tag_index={"demo": ["pkg/app.py"]},
    )


def test_write_exports_outputs_creates_artifacts(tmp_path: Path) -> None:
    """Ensure write_exports_outputs generates JSONL and Markdown outputs."""
    result = _build_result(tmp_path)
    export_services.write_exports_outputs(result, tmp_path)

    modules_path = tmp_path / "modules" / "modules.jsonl"
    assertions.expect_true(modules_path.exists())
    rows = modules_path.read_text(encoding="utf-8").strip().splitlines()
    assertions.expect_true(rows, reason="modules.jsonl should contain at least one row")
    payload = json.loads(rows[0])
    assertions.expect_true(payload["path"].endswith("pkg/app.py"))

    markdown_path = tmp_path / "modules" / "app.md"
    assertions.expect_true(markdown_path.exists())
    if importlib.util.find_spec("yaml") is not None:
        assertions.expect_true((tmp_path / "tags" / "tags_index.yaml").exists())
