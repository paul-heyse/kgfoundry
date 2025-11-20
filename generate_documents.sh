#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# End-to-end document generation helper.
# Runs SCIP indexing, enrichment (LibCST + AST), CST dataset build,
# then copies outputs into a top-level "Document Output" folder.
set -euo pipefail

convert_parquet_to_jsonl() {
  local src="$1"
  local dest="$2"

  if [ ! -f "$src" ]; then
    echo "⚠️  Missing source parquet $src; skipping JSON export" >&2
    return
  fi

  mkdir -p "$(dirname "$dest")"
  rm -f "$dest"

  SRC_PATH="$src" DEST_PATH="$dest" uv run python - <<'PY'
import os
import duckdb

src = os.environ["SRC_PATH"]
dest = os.environ["DEST_PATH"]

con = duckdb.connect()
con.execute(
    "COPY (SELECT * FROM read_parquet(?)) TO ? (FORMAT JSON, ARRAY false)",
    [dest, src],
)
PY
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pushd "$REPO_ROOT" >/dev/null

SCIP_DIR="codeintel_rev"
SCIP_BIN="$SCIP_DIR/index.scip"
SCIP_JSON="$SCIP_DIR/index.scip.json"
ENRICH_OUT="$SCIP_DIR/io/ENRICHED"
CST_OUT="$SCIP_DIR/io/CST"
DOC_OUT="$REPO_ROOT/Document Output"

echo "==> Ensuring required directories/config exist..."
mkdir -p "$REPO_ROOT/config" \
         "$REPO_ROOT/logs" \
         "$REPO_ROOT/.cache" \
         "$REPO_ROOT/.tmp" \
         "$REPO_ROOT/plugins" \
         "$REPO_ROOT/data" \
         "$REPO_ROOT/data/faiss" \
         "$REPO_ROOT/data/vectors"
if [ ! -f "$REPO_ROOT/config/app.yml" ]; then
  echo "{}" > "$REPO_ROOT/config/app.yml"
fi

echo "==> Generating SCIP index..."
(
  cd "$SCIP_DIR"
  scip-python index ../src --project-name kgfoundry
  scip print --json index.scip > index.scip.json
)

echo "==> Running enrichment pipeline (LibCST + AST + analytics)..."
uv run python -m codeintel_rev.cli.enrich_pipeline \
  all \
  --root codeintel_rev \
  --scip "$SCIP_JSON" \
  --out "$ENRICH_OUT" \
  --emit-ast

echo "==> Building GOID / call graph / CFG / DFG artifacts..."
uv run python -m codeintel_rev.cli.enrich goids \
  --repo-root "$REPO_ROOT" \
  --out-dir "$ENRICH_OUT" \
  --no-ingest
uv run python -m codeintel_rev.cli.enrich callgraph \
  --repo-root "$REPO_ROOT" \
  --out-dir "$ENRICH_OUT" \
  --no-ingest
uv run python -m codeintel_rev.cli.enrich cfg \
  --repo-root "$REPO_ROOT" \
  --out-dir "$ENRICH_OUT" \
  --no-ingest
uv run python -m codeintel_rev.cli.enrich dfg \
  --repo-root "$REPO_ROOT" \
  --out-dir "$ENRICH_OUT" \
  --no-ingest

echo "==> Building CST dataset..."
uv run python -m codeintel_rev.cst_build.cst_cli \
  --root codeintel_rev \
  --scip "$SCIP_JSON" \
  --modules "$ENRICH_OUT/modules/modules.jsonl" \
  --out "$CST_OUT"

echo "==> Normalizing CST dataset artifacts..."
rm -f "$CST_OUT/cst_nodes.jsonl"
gzip -dc "$CST_OUT/cst_nodes.jsonl.gz" > "$CST_OUT/cst_nodes.jsonl"

echo "==> Copying artifacts into \"$DOC_OUT\"..."
rm -rf "$DOC_OUT"
mkdir -p "$DOC_OUT"
cp -R "$ENRICH_OUT" "$DOC_OUT/enriched"
cp -R "$CST_OUT" "$DOC_OUT/cst"
mkdir -p "$DOC_OUT/scip"
cp "$SCIP_BIN" "$DOC_OUT/scip/index.scip"
cp "$SCIP_JSON" "$DOC_OUT/scip/index.scip.json"

echo "==> Promoting frequently accessed artifacts to Document Output root..."
cp "$SCIP_JSON" "$DOC_OUT/index.scip.json"
cp "$ENRICH_OUT/repo_map.json" "$DOC_OUT/repo_map.json"
cp "$ENRICH_OUT/modules/modules.jsonl" "$DOC_OUT/modules.jsonl"
cp "$ENRICH_OUT/ast/ast_nodes.jsonl" "$DOC_OUT/ast_nodes.jsonl"
cp "$CST_OUT/cst_nodes.jsonl" "$DOC_OUT/cst_nodes.jsonl"

echo "==> Exporting GOID / Call Graph / CFG / DFG datasets..."
GOID_PARQUET="$ENRICH_OUT/goid/goids.parquet"
GOID_CROSSWALK_PARQUET="$ENRICH_OUT/goid/goid_xwalk.parquet"
CALL_NODES_PARQUET="$ENRICH_OUT/graphs/call_nodes.parquet"
CALL_EDGES_PARQUET="$ENRICH_OUT/graphs/call_edges.parquet"
CFG_BLOCKS_PARQUET="$ENRICH_OUT/graphs/cfg_blocks.parquet"
CFG_EDGES_PARQUET="$ENRICH_OUT/graphs/cfg_edges.parquet"
DFG_EDGES_PARQUET="$ENRICH_OUT/graphs/dfg_edges.parquet"

cp "$GOID_PARQUET" "$DOC_OUT/goids.parquet"
cp "$GOID_CROSSWALK_PARQUET" "$DOC_OUT/goid_crosswalk.parquet"
cp "$CALL_NODES_PARQUET" "$DOC_OUT/call_graph_nodes.parquet"
cp "$CALL_EDGES_PARQUET" "$DOC_OUT/call_graph_edges.parquet"
cp "$CFG_BLOCKS_PARQUET" "$DOC_OUT/cfg_blocks.parquet"
cp "$CFG_EDGES_PARQUET" "$DOC_OUT/cfg_edges.parquet"
cp "$DFG_EDGES_PARQUET" "$DOC_OUT/dfg_edges.parquet"

convert_parquet_to_jsonl "$GOID_PARQUET" "$DOC_OUT/goids.jsonl"
convert_parquet_to_jsonl "$GOID_CROSSWALK_PARQUET" "$DOC_OUT/goid_crosswalk.jsonl"
convert_parquet_to_jsonl "$CALL_NODES_PARQUET" "$DOC_OUT/call_graph_nodes.jsonl"
convert_parquet_to_jsonl "$CALL_EDGES_PARQUET" "$DOC_OUT/call_graph_edges.jsonl"
convert_parquet_to_jsonl "$CFG_BLOCKS_PARQUET" "$DOC_OUT/cfg_blocks.jsonl"
convert_parquet_to_jsonl "$CFG_EDGES_PARQUET" "$DOC_OUT/cfg_edges.jsonl"
convert_parquet_to_jsonl "$DFG_EDGES_PARQUET" "$DOC_OUT/dfg_edges.jsonl"

echo "Document generation complete."
echo "Outputs available under: $DOC_OUT"

popd >/dev/null
