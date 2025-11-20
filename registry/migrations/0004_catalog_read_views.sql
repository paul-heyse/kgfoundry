CREATE VIEW IF NOT EXISTS goid_crosswalk AS
SELECT
  g.urn AS goid,
  g.language AS lang,
  CASE
    WHEN g.rel_path LIKE '%.py'
      THEN REPLACE(REGEXP_REPLACE(g.rel_path, '\.py$', ''), '/', '.')
    ELSE NULL
  END AS module_path,
  g.rel_path AS file_path,
  g.start_line,
  g.end_line,
  gx.scip_symbol,
  g.qualname AS ast_qualname,
  gx.cst_node_id,
  TRY_CAST(gx.chunk_id AS BIGINT) AS chunk_id,
  NULL AS symbol_id,
  COALESCE(g.created_at, CURRENT_TIMESTAMP) AS updated_at
FROM goids AS g
LEFT JOIN goid_xwalk AS gx USING (goid_h128);

CREATE VIEW IF NOT EXISTS v_catalog_call_edges AS
SELECT
  ce.caller_goid_h128,
  ce.callee_goid_h128,
  caller.urn AS caller_goid,
  caller.rel_path AS caller_path,
  caller.language AS caller_lang,
  callee.urn AS callee_goid,
  callee.rel_path AS callee_path,
  callee.language AS callee_lang,
  ce.callsite_path,
  ce.callsite_line,
  ce.callsite_col,
  ce.callsite_path AS file_path,
  ce.callsite_line AS start_line,
  ce.callsite_line AS end_line,
  ce.language,
  ce.kind,
  ce.resolved_via,
  ce.confidence,
  ce.callee_goid_h128 IS NOT NULL AS resolved,
  CURRENT_TIMESTAMP AS updated_at
FROM call_edges AS ce
LEFT JOIN goids AS caller ON caller.goid_h128 = ce.caller_goid_h128
LEFT JOIN goids AS callee ON callee.goid_h128 = ce.callee_goid_h128;

CREATE VIEW IF NOT EXISTS v_catalog_cfg_blocks AS
SELECT
  go.urn AS function_goid,
  go.goid_h128 AS function_goid_h128,
  cb.block_idx,
  go.urn || ':block' || CAST(cb.block_idx AS VARCHAR) AS block_id,
  cb.kind || ':' || CAST(cb.block_idx AS VARCHAR) AS label,
  go.rel_path AS file_path,
  cb.start_line,
  cb.end_line,
  cb.kind,
  cb.stmts_json,
  cb.in_degree,
  cb.out_degree
FROM cfg_blocks AS cb
LEFT JOIN goids AS go ON go.goid_h128 = cb.function_goid_h128;

CREATE VIEW IF NOT EXISTS v_catalog_cfg_edges AS
SELECT
  go.urn AS function_goid,
  go.goid_h128 AS function_goid_h128,
  ce.src_block_idx,
  ce.dst_block_idx,
  go.urn || ':block' || CAST(ce.src_block_idx AS VARCHAR) AS src,
  go.urn || ':block' || CAST(ce.dst_block_idx AS VARCHAR) AS dst,
  ce.edge_type AS label,
  ce.edge_type,
  ce.cond_json
FROM cfg_edges AS ce
LEFT JOIN goids AS go ON go.goid_h128 = ce.function_goid_h128;

CREATE VIEW IF NOT EXISTS v_catalog_dfg_nodes AS
WITH function_meta AS (
  SELECT goid_h128, urn AS function_goid, rel_path AS file_path FROM goids
),
block_spans AS (
  SELECT function_goid_h128, block_idx, start_line, end_line FROM cfg_blocks
)
SELECT DISTINCT
  meta.function_goid,
  meta.goid_h128 AS function_goid_h128,
  meta.file_path,
  de.src_block_idx AS block_idx,
  block.start_line,
  block.end_line,
  de.src_symbol AS symbol,
  meta.function_goid || ':b' || CAST(de.src_block_idx AS VARCHAR) ||
    ':' || COALESCE(de.src_symbol, 'None') ||
    ':def' AS node_id,
  'def' AS kind
FROM dfg_edges AS de
JOIN function_meta AS meta ON meta.goid_h128 = de.function_goid_h128
LEFT JOIN block_spans AS block
  ON block.function_goid_h128 = de.function_goid_h128
 AND block.block_idx = de.src_block_idx
UNION
SELECT DISTINCT
  meta.function_goid,
  meta.goid_h128 AS function_goid_h128,
  meta.file_path,
  de.dst_block_idx AS block_idx,
  block.start_line,
  block.end_line,
  de.dst_symbol AS symbol,
  meta.function_goid || ':b' || CAST(de.dst_block_idx AS VARCHAR) ||
    ':' || COALESCE(de.dst_symbol, 'None') ||
    CASE WHEN de.via_phi THEN ':phi' ELSE ':use' END AS node_id,
  CASE WHEN de.via_phi THEN 'phi' ELSE 'use' END AS kind
FROM dfg_edges AS de
JOIN function_meta AS meta ON meta.goid_h128 = de.function_goid_h128
LEFT JOIN block_spans AS block
  ON block.function_goid_h128 = de.function_goid_h128
 AND block.block_idx = de.dst_block_idx;

CREATE VIEW IF NOT EXISTS v_catalog_dfg_edges AS
SELECT
  meta.function_goid,
  meta.goid_h128 AS function_goid_h128,
  meta.function_goid || ':b' || CAST(de.src_block_idx AS VARCHAR) ||
    ':' || COALESCE(de.src_symbol, 'None') ||
    ':def' AS src,
  meta.function_goid || ':b' || CAST(de.dst_block_idx AS VARCHAR) ||
    ':' || COALESCE(de.dst_symbol, 'None') ||
    CASE WHEN de.via_phi THEN ':phi' ELSE ':use' END AS dst,
  de.use_kind AS label
FROM dfg_edges AS de
JOIN (
  SELECT goid_h128, urn AS function_goid FROM goids
) AS meta ON meta.goid_h128 = de.function_goid_h128;

INSERT OR IGNORE INTO schema_version(version) VALUES (4);
