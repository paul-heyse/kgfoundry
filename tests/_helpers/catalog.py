# SPDX-License-Identifier: MIT
"""Test helpers for catalog graph fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from codeintel_rev.app.routers import catalog_read
from codeintel_rev.ids.goid import GOID
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, DuckDBCatalogOptions
from fastapi import FastAPI

__all__ = ["build_graph_catalog_fixture", "make_catalog_app"]


class _StaticCatalogContext:
    """Test-only context wrapper that yields a provided catalog."""

    def __init__(self, catalog: DuckDBCatalog) -> None:
        self._catalog = catalog

    def open_catalog(self) -> AbstractContextManager[DuckDBCatalog]:
        """Return a context manager that opens/closes the stored catalog.

        Returns
        -------
        AbstractContextManager[DuckDBCatalog]
            Context manager yielding the stored catalog.
        """

        def _scope() -> Iterator[DuckDBCatalog]:
            """Context manager scope that opens and closes catalog.

            Yields
            ------
            Iterator[DuckDBCatalog]
                Catalog instance.
            """
            self._catalog.open()
            try:
                yield self._catalog
            finally:
                self._catalog.close()

        return contextmanager(_scope)()


def build_graph_catalog_fixture(tmp_path: Path) -> tuple[DuckDBCatalog, dict[str, GOID]]:
    """Create a catalog seeded with GOIDs, call graph, CFG, and DFG rows.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path for creating catalog database and vectors.

    Returns
    -------
    tuple[DuckDBCatalog, dict[str, GOID]]
        Tuple of (catalog instance, mapping of test GOID names to GOID objects).
    """
    db_path = tmp_path / "catalog.duckdb"
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir(parents=True, exist_ok=True)
    catalog = DuckDBCatalog(
        db_path,
        vectors_dir,
        options=DuckDBCatalogOptions(repo_root=tmp_path),
    )
    caller = GOID(
        urn="goid:demo/pkg/demo.py#python:function:caller",
        h128=101,
        repo="demo",
        commit="deadbeef",
        rel_path="pkg/demo.py",
        language="python",
        kind="function",
        qualname="demo.caller",
        start_line=1,
        end_line=20,
    )
    callee = GOID(
        urn="goid:demo/pkg/demo.py#python:function:callee",
        h128=202,
        repo="demo",
        commit="deadbeef",
        rel_path="pkg/demo.py",
        language="python",
        kind="function",
        qualname="demo.callee",
        start_line=30,
        end_line=40,
    )
    catalog.upsert_goids([caller, callee])
    catalog.upsert_goid_xwalk(
        [
            {
                "goid_h128": caller.h128,
                "scip_symbol": "pkg.demo.caller",
                "chunk_id": "1",
                "chunk_row_id": 1,
                "cst_node_id": "cst-1",
                "ast_node_type": "FunctionDef",
                "evidence_json": {"source": "ast"},
            },
            {
                "goid_h128": callee.h128,
                "scip_symbol": "pkg.demo.callee",
                "chunk_id": "2",
                "chunk_row_id": 2,
                "cst_node_id": "cst-2",
                "ast_node_type": "FunctionDef",
                "evidence_json": {"source": "ast"},
            },
        ]
    )
    catalog.upsert_call_nodes(
        [
            {
                "goid_h128": caller.h128,
                "language": "python",
                "kind": "function",
                "arity": 1,
                "is_public": True,
                "rel_path": caller.rel_path,
            },
            {
                "goid_h128": callee.h128,
                "language": "python",
                "kind": "function",
                "arity": 0,
                "is_public": True,
                "rel_path": callee.rel_path,
            },
        ]
    )
    catalog.upsert_call_edges(
        [
            {
                "caller_goid_h128": caller.h128,
                "callee_goid_h128": callee.h128,
                "callsite_path": caller.rel_path,
                "callsite_line": 10,
                "callsite_col": 8,
                "language": "python",
                "kind": "direct",
                "resolved_via": "scip",
                "confidence": 0.95,
                "evidence_json": {"expr": "callee()", "resolver": "scip"},
            }
        ]
    )
    catalog.upsert_cfg_blocks(
        [
            {
                "function_goid_h128": caller.h128,
                "block_idx": 0,
                "kind": "entry",
                "start_line": 1,
                "end_line": 1,
                "stmts_json": [],
                "in_degree": 0,
                "out_degree": 1,
            },
            {
                "function_goid_h128": caller.h128,
                "block_idx": 1,
                "kind": "exit",
                "start_line": 20,
                "end_line": 20,
                "stmts_json": [],
                "in_degree": 1,
                "out_degree": 0,
            },
        ]
    )
    catalog.upsert_cfg_edges(
        [
            {
                "function_goid_h128": caller.h128,
                "src_block_idx": 0,
                "dst_block_idx": 1,
                "edge_type": "fallthrough",
                "cond_json": None,
            }
        ]
    )
    catalog.upsert_dfg_edges(
        [
            {
                "function_goid_h128": caller.h128,
                "src_block_idx": 0,
                "dst_block_idx": 1,
                "src_symbol": "value",
                "dst_symbol": "value",
                "via_phi": False,
                "use_kind": "use",
            }
        ]
    )
    return catalog, {"caller": caller, "callee": callee}


def make_catalog_app(catalog: DuckDBCatalog) -> FastAPI:
    """Construct a FastAPI app mounting the catalog router with static context.

    Parameters
    ----------
    catalog : DuckDBCatalog
        Catalog to expose through the router via a static context object.

    Returns
    -------
    FastAPI
        FastAPI application with catalog routes registered.
    """
    app = FastAPI()
    app.state.context = _StaticCatalogContext(catalog)
    app.include_router(catalog_read.router)
    return app
