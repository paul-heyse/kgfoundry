# SPDX-License-Identifier: MIT
"""Integration tests for function analytics exports."""

from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.enrich.graph_builder import ImportGraph
from codeintel_rev.enrich.models import ModuleRecord
from codeintel_rev.services.enrich import exports as export_services
from codeintel_rev.services.enrich.context import PipelineResult
from codeintel_rev.uses_builder import UseGraph

from tests._helpers import assertions


def _pipeline_result(tmp_path: Path) -> PipelineResult:
    module_path = tmp_path / "pkg" / "calc.py"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(
        "def add(x: int, y: int) -> int:\n    return x + y\n",
        encoding="utf-8",
    )
    record = ModuleRecord(
        path="pkg/calc.py",
        repo_path="pkg/calc.py",
        module_name="pkg.calc",
    )
    return PipelineResult(
        root=tmp_path,
        repo_root=tmp_path,
        module_rows=[record],
        symbol_edges=[],
        import_graph=ImportGraph(edges={}, fan_in={}, fan_out={}, cycle_group={}),
        use_graph=UseGraph(uses_by_file={}, symbol_usage={}, edges=[]),
        config_index=[],
        coverage_rows=[],
        hotspot_rows=[],
        tag_index={},
        type_signals={},
    )


def test_function_exports_write_artifacts(tmp_path: Path) -> None:
    """Function analytics writers should emit JSONL and Parquet outputs."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = _pipeline_result(tmp_path)
    export_services.write_function_metrics_output(result, out_dir)
    export_services.write_function_types_output(result, out_dir)
    metrics_json = out_dir / "analytics" / "function_metrics.jsonl"
    types_json = out_dir / "analytics" / "function_types.jsonl"
    assertions.expect_true(metrics_json.exists())
    assertions.expect_true(types_json.exists())
    metrics_rows = metrics_json.read_text(encoding="utf-8").splitlines()
    types_rows = types_json.read_text(encoding="utf-8").splitlines()
    assertions.expect_true(metrics_rows)
    assertions.expect_true(types_rows)
    metrics_payload = json.loads(metrics_rows[0])
    types_payload = json.loads(types_rows[0])
    assertions.expect_equal(metrics_payload["qualname"], "add")
    assertions.expect_equal(metrics_payload["kind"], "function")
    assertions.expect_equal(types_payload["qualname"], "add")
    assertions.expect_equal(types_payload["typedness_bucket"], "typed")
