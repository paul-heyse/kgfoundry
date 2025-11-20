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

copy_mapping_artifact() {
  local source_parquet="$1"
  local base_name="$2"

  if [ ! -f "$source_parquet" ]; then
    echo "⚠️  Missing source parquet $source_parquet; skipping copy" >&2
    return
  fi

  local parquet_dest="$MAPPINGS_DIR/${base_name}.parquet"
  local json_dest="$MAPPINGS_DIR/${base_name}.jsonl"

  cp "$source_parquet" "$parquet_dest"
  convert_parquet_to_jsonl "$parquet_dest" "$json_dest"
  cp "$json_dest" "$DOC_OUT/${base_name}.jsonl"
}

copy_if_exists() {
  local src="$1"
  local dest="$2"
  if [ -f "$src" ]; then
    cp "$src" "$dest"
  else
    echo "⚠️  Missing artifact $src; skipping copy" >&2
  fi
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pushd "$REPO_ROOT" >/dev/null

SCIP_DIR="codeintel_rev"
SCIP_BIN="$SCIP_DIR/index.scip"
SCIP_JSON="$SCIP_DIR/index.scip.json"
ENRICH_OUT="$SCIP_DIR/io/ENRICHED"
CST_OUT="$SCIP_DIR/io/CST"
DOC_OUT="$REPO_ROOT/Document Output"
MAPPINGS_DIR="$DOC_OUT/mappings"

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
mkdir -p "$MAPPINGS_DIR"
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
IMPORT_GRAPH_EDGES_PARQUET="$ENRICH_OUT/graphs/import_graph_edges.parquet"
SYMBOL_USE_EDGES_PARQUET="$ENRICH_OUT/graphs/symbol_use_edges.parquet"

copy_mapping_artifact "$GOID_PARQUET" "goids"
copy_mapping_artifact "$GOID_CROSSWALK_PARQUET" "goid_crosswalk"
copy_mapping_artifact "$CALL_NODES_PARQUET" "call_graph_nodes"
copy_mapping_artifact "$CALL_EDGES_PARQUET" "call_graph_edges"
copy_mapping_artifact "$CFG_BLOCKS_PARQUET" "cfg_blocks"
copy_mapping_artifact "$CFG_EDGES_PARQUET" "cfg_edges"
copy_mapping_artifact "$DFG_EDGES_PARQUET" "dfg_edges"
copy_mapping_artifact "$IMPORT_GRAPH_EDGES_PARQUET" "import_graph_edges"
copy_mapping_artifact "$SYMBOL_USE_EDGES_PARQUET" "symbol_use_edges"

echo "==> Promoting key analytics artifacts to Document Output root..."
copy_if_exists "$DOC_OUT/enriched/analytics/hotspots.jsonl" "$DOC_OUT/hotspots.jsonl"
copy_if_exists "$DOC_OUT/enriched/analytics/typedness.jsonl" "$DOC_OUT/typedness.jsonl"
copy_if_exists "$DOC_OUT/enriched/ast/ast_metrics.jsonl" "$DOC_OUT/ast_metrics.jsonl"
copy_if_exists "$DOC_OUT/enriched/tags/tags_index.yaml" "$DOC_OUT/tags_index.yaml"
convert_parquet_to_jsonl "$ENRICH_OUT/analytics/config_values.parquet" "$DOC_OUT/config_values.jsonl"
convert_parquet_to_jsonl "$ENRICH_OUT/analytics/static_diagnostics.parquet" "$DOC_OUT/static_diagnostics.jsonl"
convert_parquet_to_jsonl "$ENRICH_OUT/graphs/import_graph_edges.parquet" "$DOC_OUT/import_graph_edges.jsonl"
convert_parquet_to_jsonl "$ENRICH_OUT/graphs/symbol_use_edges.parquet" "$DOC_OUT/symbol_use_edges.jsonl"

echo "Document generation complete."
echo "Outputs available under: $DOC_OUT"

popd >/dev/null
