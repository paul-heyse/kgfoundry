# SPDX-License-Identifier: MIT
"""Integration tests for catalog read helpers (GOID/callgraph/CFG/DFG)."""

from __future__ import annotations

from pathlib import Path

import pytest
from codeintel_rev.io.duckdb_catalog import CallGraphQuery, GOIDQuery

from tests._helpers import assertions
from tests._helpers.catalog import build_graph_catalog_fixture


def test_query_goids_filters_and_pagination(tmp_path: Path) -> None:
    """GOID query helper should filter and paginate via crosswalk view."""
    catalog, goids = build_graph_catalog_fixture(tmp_path)
    query = GOIDQuery(path="pkg/demo.py", limit=1)
    result = catalog.query_goids(query)
    rows = result["rows"]
    cursor = result["next_cursor"]
    assertions.expect_true(rows, reason="Expected at least one GOID row")
    assertions.expect_equal(cursor, "1")
    row = rows[0]
    span = row.get("span")
    assertions.expect_true(span is not None, reason="GOID span expected")
    if span is None:  # pragma: no cover - guarded above
        pytest.fail("span missing")
    assertions.expect_true(row["goid"] in {goids["caller"].urn, goids["callee"].urn})
    assertions.expect_equal(span.get("file_path"), "pkg/demo.py")


def test_query_callgraph_returns_nodes_and_edges(tmp_path: Path) -> None:
    """Call graph query should surface nodes/edges via catalog views."""
    catalog, goids = build_graph_catalog_fixture(tmp_path)
    graph_query = CallGraphQuery(
        root_goid=goids["caller"].urn,
        direction="out",
        depth=1,
        max_nodes=5,
        lang="python",
        include_unresolved=False,
        include_third_party=True,
        path_prefix="pkg",
        limit=10,
    )
    graph = catalog.query_callgraph(graph_query)
    edges = graph["edges"]
    assertions.expect_true(graph["nodes"], reason="Expected nodes in call graph result")
    assertions.expect_true(edges, reason="Expected edges in call graph result")
    assertions.expect_true(any(edge["callee"] == goids["callee"].urn for edge in edges))


def test_get_cfg_and_dfg_use_catalog_views(tmp_path: Path) -> None:
    """CFG/DFG helpers should emit spans derived from catalog views.

    Notes
    -----
    This test includes type narrowing guards that raise ``pytest.fail`` if
    CFG or DFG payloads are unexpectedly None (covered by pragma: no cover).
    """
    catalog, goids = build_graph_catalog_fixture(tmp_path)
    cfg = catalog.get_cfg(goids["caller"].urn)
    assertions.expect_true(cfg is not None)
    if cfg is None:  # pragma: no cover - guarded above
        pytest.fail("cfg payload missing")
    cfg_blocks = cfg["blocks"]
    span = cfg_blocks[0].get("span")
    assertions.expect_true(span is not None)
    if span is None:  # pragma: no cover - guarded above
        pytest.fail("cfg span missing")
    assertions.expect_equal(span.get("file_path"), "pkg/demo.py")
    dfg = catalog.get_dfg(goids["caller"].urn)
    assertions.expect_true(dfg is not None)
    if dfg is None:  # pragma: no cover - guarded above
        pytest.fail("dfg payload missing")
    assertions.expect_true(dfg["nodes"], reason="DFG nodes should be populated")
    assertions.expect_true(dfg["edges"], reason="DFG edges should be populated")
