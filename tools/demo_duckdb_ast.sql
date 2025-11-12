-- DuckDB demo for AST + LibCST + SCIP joins.
-- Run from repo root:
--   python tools/run_duckdb_demo.py --sql tools/demo_duckdb_ast.sql

CREATE OR REPLACE TABLE modules AS
  SELECT * FROM read_json_auto('codeintel_rev/io/ENRICHED/modules/modules.jsonl');

CREATE OR REPLACE TABLE ast_nodes AS
  SELECT * FROM read_parquet('codeintel_rev/io/ENRICHED/ast/ast_nodes.parquet');

CREATE OR REPLACE TABLE ast_metrics AS
  SELECT * FROM read_parquet('codeintel_rev/io/ENRICHED/ast/ast_metrics.parquet');

CREATE OR REPLACE TABLE scip_edges AS
  SELECT * FROM read_json_auto('codeintel_rev/io/ENRICHED/graphs/symbol_graph.json');

-- 1) Top 20 complex files (cyclomatic) with low LibCST-identified defs
SELECT m.path, a.cyclomatic, a.func_count, a.class_count
FROM ast_metrics a
JOIN modules m ON a.path = m.path
ORDER BY a.cyclomatic DESC
LIMIT 20;

-- 2) Public API candidates: defs exported via __all__ + AST nodes
WITH exports AS (
  SELECT path, UNNEST(exports) AS exported
  FROM modules
  WHERE array_length(exports) > 0
)
SELECT n.path, n.qualname, n.name, n.node_type
FROM ast_nodes n
JOIN exports e ON e.path = n.path AND (n.name = e.exported OR n.qualname LIKE e.exported || '%')
ORDER BY n.path, n.qualname;

-- 3) “Hotspots”: complexity × fan-in (approx via symbol references)
WITH uses AS (
  SELECT file AS path, COUNT(*) AS used_by_refs
  FROM scip_edges
  GROUP BY 1
)
SELECT a.path, a.cyclomatic, u.used_by_refs
FROM ast_metrics a
LEFT JOIN uses u ON a.path = u.path
ORDER BY (a.cyclomatic * COALESCE(u.used_by_refs, 1)) DESC
LIMIT 20;
