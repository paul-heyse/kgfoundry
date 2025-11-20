# SPDX-License-Identifier: MIT
"""DuckDB catalog ingestion tests for graph tables."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.ids.goid import GOID
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, DuckDBCatalogOptions

from tests._helpers import assertions


def test_duckdb_catalog_ingests_graph_data(tmp_path: Path) -> None:
    """Verify call graph and CFG/DFG rows can be ingested and queried."""
    db_path = tmp_path / "catalog.duckdb"
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    catalog = DuckDBCatalog(
        db_path,
        vectors_dir,
        options=DuckDBCatalogOptions(repo_root=tmp_path),
    )
    nodes = [
        {
            "goid_h128": 1,
            "language": "python",
            "kind": "function",
            "arity": 1,
            "is_public": True,
            "rel_path": "pkg/demo.py",
        },
        {
            "goid_h128": 2,
            "language": "python",
            "kind": "function",
            "arity": 0,
            "is_public": True,
            "rel_path": "pkg/demo.py",
        },
    ]
    edges = [
        {
            "caller_goid_h128": 1,
            "callee_goid_h128": 2,
            "callsite_path": "pkg/demo.py",
            "callsite_line": 4,
            "callsite_col": 4,
            "language": "python",
            "kind": "direct",
            "resolved_via": "local-symbol",
            "confidence": 0.9,
            "evidence_json": {"expr": "callee()", "resolver": "local-symbol"},
        }
    ]
    cfg_blocks = [
        {
            "function_goid_h128": 1,
            "block_idx": 0,
            "kind": "entry",
            "start_line": 1,
            "end_line": 1,
            "stmts_json": [],
            "in_degree": 0,
            "out_degree": 1,
        },
        {
            "function_goid_h128": 1,
            "block_idx": 1,
            "kind": "exit",
            "start_line": 2,
            "end_line": 2,
            "stmts_json": [],
            "in_degree": 1,
            "out_degree": 0,
        },
    ]
    cfg_edges = [
        {
            "function_goid_h128": 1,
            "src_block_idx": 0,
            "dst_block_idx": 1,
            "edge_type": "fallthrough",
            "cond_json": None,
        }
    ]
    dfg_edges = [
        {
            "function_goid_h128": 1,
            "src_block_idx": 0,
            "dst_block_idx": 0,
            "src_symbol": "value",
            "dst_symbol": "value",
            "via_phi": False,
            "use_kind": "use",
        }
    ]
    catalog.upsert_call_nodes(nodes)
    catalog.upsert_call_edges(edges)
    catalog.upsert_cfg_blocks(cfg_blocks)
    catalog.upsert_cfg_edges(cfg_edges)
    catalog.upsert_dfg_edges(dfg_edges)
    callees = catalog.get_callees(1)
    assertions.expect_true(callees, reason="Missing call graph edges")
    assertions.expect_equal(callees[0]["callee_goid_h128"], 2)
    cfg_payload = catalog.cfg_for_function(1)
    assertions.expect_true(cfg_payload["blocks"], reason="CFG blocks missing")
    dfg_payload = catalog.dfg_for_function(1)
    assertions.expect_true(dfg_payload, reason="DFG edges missing")


def test_duckdb_catalog_handles_goids_and_crosswalk(tmp_path: Path) -> None:
    """GOID registry and crosswalk helpers should round-trip their data."""
    db_path = tmp_path / "catalog.duckdb"
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    catalog = DuckDBCatalog(
        db_path,
        vectors_dir,
        options=DuckDBCatalogOptions(repo_root=tmp_path),
    )
    goid = GOID(
        urn="goid:1/demo@deadbeef:/pkg/demo.py#python:function:demo.run?s=1&e=3",
        h128=42,
        repo="demo",
        commit="deadbeef",
        rel_path="pkg/demo.py",
        language="python",
        kind="function",
        qualname="demo.run",
        start_line=1,
        end_line=3,
    )
    crosswalk = {
        "goid_h128": goid.h128,
        "scip_symbol": "pkg.demo.demo.run",
        "chunk_id": "pkg/demo.py:1:3",
        "ast_node_type": "FunctionDef",
        "evidence_json": {"anchors": ["ast"], "lineno": 1},
    }
    catalog.upsert_goids([goid])
    catalog.upsert_goid_xwalk([crosswalk])
    # Duplicate ingest should not error and should still leave one row.
    catalog.upsert_goids([goid])
    catalog.upsert_goid_xwalk([crosswalk])
    symbol_rows = catalog.find_goid_by_symbol("pkg.demo.demo.run")
    assertions.expect_equal(len(symbol_rows), 1)
    span_rows = catalog.resolve_goid_by_path_span(
        "pkg/demo.py", kind="function", start_line=1, end_line=3
    )
    assertions.expect_true(span_rows, reason="GOID span lookup failed")
    crosswalk_rows = catalog.crosswalk_for_goid(goid.h128)
    assertions.expect_equal(len(crosswalk_rows), 1)
