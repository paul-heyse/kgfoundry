# SPDX-License-Identifier: MIT
"""Tests for graph builders and edge writers."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.enrich.graph.builders import build_import_graph
from codeintel_rev.enrich.graph.io import write_import_edges, write_use_edges
from codeintel_rev.uses_builder import UseGraph

from tests._helpers import assertions


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
        {"path": "pkg/a.py", "meta": {"imports": []}},
        {"path": "pkg/b.py", "meta": {"imports": []}},
    ]
    graph = build_import_graph(rows)
    out = tmp_path / "imports.parquet"
    used = write_import_edges(graph, out)
    assertions.expect_true(used.exists(), reason="edge file should exist")


def test_write_use_edges_json(tmp_path: Path) -> None:
    """Use graph edge writer should create a file from edge rows."""
    graph = UseGraph(
        uses_by_file={"pkg/a.py": {"pkg/b.py"}},
        symbol_usage={"pkg/a.py": 1},
        edges=[("pkg/a.py", "pkg/b.py", "sym::id")],
    )
    out = tmp_path / "uses.parquet"
    used = write_use_edges(
        ({"def_path": a, "use_path": b, "symbol": c} for a, b, c in graph.edges),
        out,
    )
    assertions.expect_true(used.exists(), reason="uses edge file should exist")
