# SPDX-License-Identifier: MIT
"""Tests for graph builders and edge writers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    import pyarrow.parquet as pq
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pq = None
from codeintel_rev.enrich.graph.builders import build_import_graph
from codeintel_rev.enrich.graph.io import write_import_edges, write_use_edges
from codeintel_rev.uses_builder import UseGraph

from tests._helpers import assertions


def _materialize_rows(path: Path) -> list[dict[str, object]]:
    if path.suffix == ".parquet":
        if pq is None:  # pragma: no cover - pyarrow optional
            pytest.skip("pyarrow is required to inspect parquet outputs")
        table = pq.read_table(path)
        return table.to_pylist()
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_build_import_graph_from_meta() -> None:
    """Import graph builder should consume meta payload edges."""
    rows = [
        {
            "path": "pkg/a.py",
            "meta": {
                "imports": [
                    {"src_module": "pkg.a", "dst_module": "pkg.b", "alias": None, "level": 0},
                ]
            },
        },
        {"path": "pkg/b.py", "meta": {"imports": []}},
    ]
    graph = build_import_graph(rows)
    assertions.expect_equal(graph.edges["pkg/a.py"], {"pkg/b.py"})
    assertions.expect_equal(graph.fan_out["pkg/a.py"], 1)
    assertions.expect_equal(graph.fan_in["pkg/b.py"], 1)


def test_write_import_edges_json_fallback(tmp_path: Path) -> None:
    """Edge writer should emit a file even without pyarrow present."""
    rows = [
        {
            "path": "pkg/a.py",
            "module_name": "pkg.a",
            "meta": {
                "imports": [
                    {"src_module": "pkg.a", "dst_module": "pkg.b", "alias": None, "level": 0},
                ]
            },
        },
        {"path": "pkg/b.py", "module_name": "pkg.b", "meta": {"imports": []}},
    ]
    graph = build_import_graph(rows)
    out = tmp_path / "import_graph_edges.parquet"
    used = write_import_edges(
        graph,
        out,
        module_by_path={"pkg/a.py": "pkg.a", "pkg/b.py": "pkg.b"},
        jsonl_fallback=tmp_path / "import_graph_edges.jsonl",
    )
    assertions.expect_true(used.exists(), reason="edge file should exist")
    records = _materialize_rows(used)
    (record,) = records
    assertions.expect_equal(record["src_module"], "pkg.a")
    assertions.expect_equal(record["dst_module"], "pkg.b")
    assertions.expect_equal(record["src_fan_out"], 1)
    assertions.expect_equal(record["dst_fan_in"], 1)
    assertions.expect_true(isinstance(record["cycle_group"], int))


def test_write_use_edges_json(tmp_path: Path) -> None:
    """Use graph edge writer should create a file from edge rows."""
    graph = UseGraph(
        uses_by_file={"pkg/a.py": {"pkg/b.py"}},
        symbol_usage={"pkg/a.py": 1},
        edges=[("pkg/a.py", "pkg/b.py", "sym::id")],
    )
    out = tmp_path / "symbol_use_edges.parquet"
    used = write_use_edges(
        graph,
        out,
        module_by_path={"pkg/a.py": "pkg.alpha", "pkg/b.py": "pkg.beta"},
        jsonl_fallback=tmp_path / "symbol_use_edges.jsonl",
    )
    assertions.expect_true(used.exists(), reason="uses edge file should exist")
    records = _materialize_rows(used)
    assertions.expect_equal(
        records[0],
        {
            "symbol": "sym::id",
            "def_path": "pkg/a.py",
            "use_path": "pkg/b.py",
            "same_file": False,
            "same_module": False,
        },
    )
