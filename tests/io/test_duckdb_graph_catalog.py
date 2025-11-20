# SPDX-License-Identifier: MIT
"""DuckDB catalog ingestion tests for graph tables."""

from __future__ import annotations

from pathlib import Path

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
