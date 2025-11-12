# SPDX-License-Identifier: MIT
"""Smoke test for AST collection and DuckDB joins."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import textwrap

import duckdb
from codeintel_rev.enrich.ast_indexer import (
    collect_ast_nodes_from_tree,
    compute_ast_metrics,
    write_ast_parquet,
)


def test_ast_collection_and_duckdb_join(tmp_path: Path) -> None:
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
    assert "Cls" in qualnames
    assert "Cls.m" in qualnames
    assert "f" in qualnames

    assert metric_row.func_count >= 2
    assert metric_row.class_count >= 1
    assert metric_row.cyclomatic >= 2

    ast_dir = tmp_path / "out" / "ast"
    write_ast_parquet(node_rows, [metric_row], out_dir=ast_dir)
    modules_stub = tmp_path / "modules.jsonl"
    modules_stub.write_text(
        json.dumps({"path": rel_path, "exports": ["f"]}) + "\n",
        encoding="utf-8",
    )

    con = duckdb.connect()
    try:
        modules_path = modules_stub.as_posix().replace("'", "''")
        nodes_path = (ast_dir / "ast_nodes.parquet").as_posix().replace("'", "''")
        con.execute(f"CREATE TABLE modules AS SELECT * FROM read_json_auto('{modules_path}');")
        con.execute(f"CREATE TABLE ast_nodes AS SELECT * FROM read_parquet('{nodes_path}');")
        joined = con.execute("SELECT COUNT(*) FROM ast_nodes JOIN modules USING(path);").fetchone()[
            0
        ]
    finally:
        con.close()

    assert joined > 0
