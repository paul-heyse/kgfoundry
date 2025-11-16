# SPDX-License-Identifier: MIT
"""Smoke test for AST collection and DuckDB joins."""

from __future__ import annotations

import ast
import json
import textwrap
from pathlib import Path

import duckdb
import pytest
from codeintel_rev.enrich.ast_indexer import (
    collect_ast_nodes_from_tree,
    compute_ast_metrics,
    write_ast_parquet,
)

from tests._helpers import assertions

# Test constants for AST metrics
_MIN_EXPECTED_FUNCTION_COUNT = 2
_MIN_EXPECTED_CYCLOMATIC_COMPLEXITY = 2


def test_ast_collection_and_duckdb_join(tmp_path: Path) -> None:
    """Test that AST collection and DuckDB join operations work correctly."""
    source = textwrap.dedent(
        '''
        """Doc."""
        import os
        from typing import Optional

        __all__ = ["f"]

        class Cls:
            def m(self, x: int) -> int:
                if x > 0:
                    return x
                return -x

        def f(y: Optional[int] = None) -> int:
            return 0 if y is None else y

        z = 1
    '''
    ).strip()
    module_path = tmp_path / "pkg" / "mod.py"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(source, encoding="utf-8")

    rel_path = "pkg/mod.py"
    tree = ast.parse(source, filename=rel_path, type_comments=True)
    node_rows = collect_ast_nodes_from_tree(rel_path, tree)
    metric_row = compute_ast_metrics(rel_path, tree)

    qualnames = {row.qualname for row in node_rows if row.qualname}
    assertions.expect_in("Cls", qualnames)
    assertions.expect_in("Cls.m", qualnames)
    assertions.expect_in("f", qualnames)

    assertions.expect_true(
        metric_row.func_count >= _MIN_EXPECTED_FUNCTION_COUNT,
        reason=f"should have at least {_MIN_EXPECTED_FUNCTION_COUNT} functions",
    )
    assertions.expect_true(metric_row.class_count >= 1, reason="should have at least 1 class")
    assertions.expect_true(
        metric_row.cyclomatic >= _MIN_EXPECTED_CYCLOMATIC_COMPLEXITY,
        reason=f"should have cyclomatic complexity >= {_MIN_EXPECTED_CYCLOMATIC_COMPLEXITY}",
    )

    ast_dir = tmp_path / "out" / "ast"
    write_ast_parquet(node_rows, [metric_row], out_dir=ast_dir)
    modules_stub = tmp_path / "modules.jsonl"
    modules_stub.write_text(
        json.dumps({"path": rel_path, "exports": ["f"]}) + "\n",
        encoding="utf-8",
    )

    con = duckdb.connect()
    try:
        modules_path = modules_stub.as_posix()
        nodes_path = (ast_dir / "ast_nodes.parquet").as_posix()
        con.execute("CREATE TABLE modules AS SELECT * FROM read_json_auto(?)", [modules_path])
        con.execute("CREATE TABLE ast_nodes AS SELECT * FROM read_parquet(?)", [nodes_path])
        result = con.execute("SELECT COUNT(*) FROM ast_nodes JOIN modules USING(path);").fetchone()
        assertions.expect_true(result is not None, reason="query should return a result")
        if result is None:  # pragma: no cover - defensive
            pytest.fail("query should return a result")
        joined = result[0]
    finally:
        con.close()

    assertions.expect_true(joined > 0, reason="should have joined rows")
