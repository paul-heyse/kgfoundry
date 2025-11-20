CREATE TABLE IF NOT EXISTS goids (
  goid_h128   HUGEINT PRIMARY KEY,
  urn         VARCHAR NOT NULL,
  repo        VARCHAR NOT NULL,
  commit      VARCHAR NOT NULL,
  rel_path    VARCHAR NOT NULL,
  language    VARCHAR NOT NULL,
  kind        VARCHAR NOT NULL,
  qualname    VARCHAR,
  start_line  INTEGER,
  end_line    INTEGER,
  created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goid_xwalk (
  goid_h128      HUGEINT NOT NULL REFERENCES goids(goid_h128),
  scip_symbol    VARCHAR,
  chunk_id       VARCHAR,
  chunk_row_id   BIGINT,
  cst_node_id    VARCHAR,
  ast_node_type  VARCHAR,
  git_blob_sha   VARCHAR,
  git_commit_sha VARCHAR,
  evidence_json  JSON,
  UNIQUE (goid_h128, scip_symbol, chunk_id)
);

CREATE OR REPLACE VIEW v_goid_by_symbol AS
SELECT go.*, gx.scip_symbol
FROM goids AS go
LEFT JOIN goid_xwalk AS gx USING (goid_h128)
WHERE gx.scip_symbol IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_goids_path_kind ON goids(rel_path, kind);
CREATE INDEX IF NOT EXISTS idx_goid_xwalk_symbol ON goid_xwalk(scip_symbol);

CREATE TABLE IF NOT EXISTS call_nodes (
  goid_h128   HUGEINT PRIMARY KEY,
  language    VARCHAR NOT NULL,
  kind        VARCHAR NOT NULL,
  arity       INTEGER,
  is_public   BOOLEAN,
  rel_path    VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS call_edges (
  caller_goid_h128 HUGEINT NOT NULL REFERENCES call_nodes(goid_h128),
  callee_goid_h128 HUGEINT,
  callsite_path    VARCHAR NOT NULL,
  callsite_line    INTEGER,
  callsite_col     INTEGER,
  language         VARCHAR NOT NULL,
  kind             VARCHAR NOT NULL,
  resolved_via     VARCHAR NOT NULL,
  confidence       DOUBLE NOT NULL,
  evidence_json    JSON,
  PRIMARY KEY (caller_goid_h128, callsite_path, callsite_line, callsite_col)
);

CREATE INDEX IF NOT EXISTS idx_call_edges_callee ON call_edges(callee_goid_h128);

CREATE TABLE IF NOT EXISTS cfg_blocks (
  function_goid_h128 HUGEINT NOT NULL,
  block_idx          INTEGER NOT NULL,
  kind               VARCHAR NOT NULL,
  start_line         INTEGER,
  end_line           INTEGER,
  stmts_json         JSON,
  in_degree          INTEGER,
  out_degree         INTEGER,
  PRIMARY KEY (function_goid_h128, block_idx)
);

CREATE TABLE IF NOT EXISTS cfg_edges (
  function_goid_h128 HUGEINT NOT NULL,
  src_block_idx      INTEGER NOT NULL,
  dst_block_idx      INTEGER NOT NULL,
  edge_type          VARCHAR NOT NULL,
  cond_json          JSON,
  PRIMARY KEY (function_goid_h128, src_block_idx, dst_block_idx)
);

CREATE TABLE IF NOT EXISTS dfg_edges (
  function_goid_h128 HUGEINT NOT NULL,
  src_block_idx      INTEGER NOT NULL,
  dst_block_idx      INTEGER NOT NULL,
  src_symbol         VARCHAR NOT NULL,
  dst_symbol         VARCHAR NOT NULL,
  via_phi            BOOLEAN,
  use_kind           VARCHAR NOT NULL,
  PRIMARY KEY (function_goid_h128, src_block_idx, dst_block_idx, src_symbol, dst_symbol, use_kind)
);

CREATE INDEX IF NOT EXISTS idx_cfg_blocks_function ON cfg_blocks(function_goid_h128);
CREATE INDEX IF NOT EXISTS idx_dfg_symbol ON dfg_edges(function_goid_h128, dst_symbol);

INSERT OR IGNORE INTO schema_version(version) VALUES (3);
