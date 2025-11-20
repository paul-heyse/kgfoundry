#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# End-to-end document generation helper.
# Runs SCIP indexing, enrichment (LibCST + AST), CST dataset build,
# then copies outputs into a top-level "Document_Output" folder.
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
try:
    con.execute("CREATE TEMP TABLE t AS SELECT * FROM read_parquet(?)", [src])
    con.execute("COPY t TO ? (FORMAT JSON, ARRAY false)", [dest])
except Exception as exc:  # pragma: no cover - best effort conversion
    import sys

    sys.stderr.write(f"⚠️  Failed to convert {src} to JSONL: {exc}\n")
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
SCIP_DIR="$REPO_ROOT"
SCIP_BIN="$SCIP_DIR/index.scip"
SCIP_JSON="$SCIP_DIR/index.scip.json"
ENRICH_OUT="$SCIP_DIR/io/ENRICHED"
CST_OUT="$SCIP_DIR/io/CST"
DOC_OUT="$REPO_ROOT/Document_Output"
MAPPINGS_DIR="$DOC_OUT/mappings"
INCLUDE_PY_GLOBS=(
  "codeintel_rev/**/*.py"
  "src/**/*.py"
  "tests/**/*.py"
  "tools/**/*.py"
)
EXCLUDE_PY_GLOBS=(
  ".venv/**"
  "io/ENRICHED/**"
  "Document_Output/**"
)

# Build include/exclude argument arrays to avoid word-splitting issues.
INCLUDE_ARGS=()
ONLY_ARGS=()
for pat in "${INCLUDE_PY_GLOBS[@]}"; do
  INCLUDE_ARGS+=(--include "$pat")
  ONLY_ARGS+=(--only "$pat")
done
EXCLUDE_ARGS=()
for pat in "${EXCLUDE_PY_GLOBS[@]}"; do
  EXCLUDE_ARGS+=(--exclude "$pat")
done

pushd "$REPO_ROOT" >/dev/null

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
mkdir -p "$ENRICH_OUT" "$CST_OUT"

echo "==> Generating SCIP index..."
(
  cd "$SCIP_DIR"
  scip-python index . --project-name kgfoundry
  scip print --json index.scip > index.scip.json
)

echo "==> Exporting modules and repo map..."
uv run python -m codeintel_rev.cli.enrich exports \
  --repo-root "$REPO_ROOT" \
  --out-dir "$ENRICH_OUT"

echo "==> Building hotspot analytics..."
uv run python -m codeintel_rev.cli.enrich_analytics \
  --root "$REPO_ROOT" \
  --scip "$SCIP_JSON" \
  --out "$ENRICH_OUT" \
  "${ONLY_ARGS[@]}" \
  hotspots

echo "==> Building AST artifacts from modules.jsonl..."
uv run python - <<PY
import json
from pathlib import Path

from codeintel_rev.enrich.ast_indexer import write_ast_parquet
from codeintel_rev.services.enrich.io import collect_ast_artifacts, write_ast_jsonl

repo_root = Path("$REPO_ROOT")
modules_path = Path("$ENRICH_OUT") / "modules" / "modules.jsonl"
if not modules_path.is_file():
    raise SystemExit(f"modules.jsonl not found at {modules_path}")

files = []
with modules_path.open(encoding="utf-8") as handle:
    for line in handle:
        if not line.strip():
            continue
        data = json.loads(line)
        rel = data.get("path")
        if not rel:
            continue
        path = (repo_root / rel).resolve()
        if ".venv" in path.parts:
            continue
        if not path.is_file():
            continue
        files.append(path)

node_rows, metric_rows = collect_ast_artifacts(repo_root, files)
ast_dir = Path("$ENRICH_OUT") / "ast"
ast_dir.mkdir(parents=True, exist_ok=True)
write_ast_jsonl(ast_dir / "ast_nodes.jsonl", node_rows)
write_ast_jsonl(ast_dir / "ast_metrics.jsonl", metric_rows)
write_ast_parquet(node_rows, metric_rows, out_dir=ast_dir)
PY

echo "==> Ensuring tags_index.yaml is present..."
python - <<PY
import json
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - fallback writer
    yaml = None

root = Path("$ENRICH_OUT")
json_path = root / "tag_index.json"
yaml_path = root / "tags" / "tags_index.yaml"
if yaml_path.is_file():
    raise SystemExit(0)
if not json_path.is_file():
    raise SystemExit(f"tag_index.json missing at {json_path}")

data = json.loads(json_path.read_text(encoding="utf-8"))
yaml_path.parent.mkdir(parents=True, exist_ok=True)
if yaml is not None:
    yaml.safe_dump(data, yaml_path.open("w", encoding="utf-8"), sort_keys=True)
else:
    lines = []
    for key in sorted(data):
        lines.append(f"{key}:")
        for val in data[key]:
            lines.append(f"  - {val}")
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

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

echo "==> Building coverage and test analytics (best-effort)..."
COVERAGE_FILE="$REPO_ROOT/.coverage"
PYTEST_REPORT="$REPO_ROOT/.cache/pytest-report.json"
# Always regenerate analytics artifacts to avoid stale JSONL formatting.
rm -rf "$ENRICH_OUT/analytics/coverage" "$ENRICH_OUT/analytics/tests" "$ENRICH_OUT/analytics/risk"
if [ -f "$COVERAGE_FILE" ]; then
uv run python -m codeintel_rev.cli.enrich_analytics \
  --root "$REPO_ROOT" \
  --out "$ENRICH_OUT" \
  coverage-detailed \
  --coverage-file "$COVERAGE_FILE"
else
  echo "⚠️  No .coverage found; skipping coverage analytics" >&2
fi

if [ -f "$COVERAGE_FILE" ] && [ -f "$PYTEST_REPORT" ]; then
  uv run python -m codeintel_rev.cli.enrich_analytics \
    --root "$REPO_ROOT" \
    --out "$ENRICH_OUT" \
    test-analytics \
    --coverage-file "$COVERAGE_FILE" \
    --pytest-report "$PYTEST_REPORT"
else
  echo "⚠️  Missing .coverage or pytest JSON report; skipping test analytics" >&2
fi

if [ -f "$ENRICH_OUT/analytics/coverage/coverage_functions.jsonl" ]; then
  uv run python -m codeintel_rev.cli.enrich_analytics \
    --root "$REPO_ROOT" \
    --out "$ENRICH_OUT" \
    risk-factors
else
  echo "⚠️  Coverage analytics missing; skipping risk factor computation" >&2
fi

echo "==> Building CST dataset..."
uv run python -m codeintel_rev.cst_build.cst_cli \
  --root "$REPO_ROOT" \
  --scip "$SCIP_JSON" \
  --modules "$ENRICH_OUT/modules/modules.jsonl" \
  "${INCLUDE_ARGS[@]}" \
  "${EXCLUDE_ARGS[@]}" \
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

echo "==> Promoting frequently accessed artifacts to Document_Output root..."
cp "$SCIP_JSON" "$DOC_OUT/index.scip.json"
cp "$ENRICH_OUT/repo_map.json" "$DOC_OUT/repo_map.json"
cp "$ENRICH_OUT/modules/modules.jsonl" "$DOC_OUT/modules.jsonl"
convert_parquet_to_jsonl "$ENRICH_OUT/ast/ast_nodes.parquet" "$DOC_OUT/ast_nodes.jsonl"
cp "$CST_OUT/cst_nodes.jsonl" "$DOC_OUT/cst_nodes.jsonl"
copy_if_exists "$ENRICH_OUT/analytics/coverage/coverage_lines.parquet" "$DOC_OUT/coverage_lines.parquet"
convert_parquet_to_jsonl "$DOC_OUT/coverage_lines.parquet" "$DOC_OUT/coverage_lines.jsonl"
copy_if_exists "$ENRICH_OUT/analytics/coverage/coverage_functions.parquet" "$DOC_OUT/coverage_functions.parquet"
convert_parquet_to_jsonl "$DOC_OUT/coverage_functions.parquet" "$DOC_OUT/coverage_functions.jsonl"
copy_if_exists "$ENRICH_OUT/analytics/tests/test_catalog.parquet" "$DOC_OUT/test_catalog.parquet"
convert_parquet_to_jsonl "$DOC_OUT/test_catalog.parquet" "$DOC_OUT/test_catalog.jsonl"
copy_if_exists "$ENRICH_OUT/analytics/tests/test_coverage_edges.parquet" "$DOC_OUT/test_coverage_edges.parquet"
convert_parquet_to_jsonl "$DOC_OUT/test_coverage_edges.parquet" "$DOC_OUT/test_coverage_edges.jsonl"
copy_if_exists "$ENRICH_OUT/analytics/risk/goid_risk_factors.parquet" "$DOC_OUT/goid_risk_factors.parquet"
convert_parquet_to_jsonl "$DOC_OUT/goid_risk_factors.parquet" "$DOC_OUT/goid_risk_factors.jsonl"

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

# Ensure new graph outputs exist; fall back to legacy names if needed.
if [ ! -f "$IMPORT_GRAPH_EDGES_PARQUET" ] && [ -f "$ENRICH_OUT/graphs/imports.parquet" ]; then
  cp "$ENRICH_OUT/graphs/imports.parquet" "$IMPORT_GRAPH_EDGES_PARQUET"
fi
if [ ! -f "$SYMBOL_USE_EDGES_PARQUET" ] && [ -f "$ENRICH_OUT/graphs/uses.parquet" ]; then
  cp "$ENRICH_OUT/graphs/uses.parquet" "$SYMBOL_USE_EDGES_PARQUET"
fi

# Generate missing graph/analytics artifacts via targeted CLI commands.
if [ ! -f "$IMPORT_GRAPH_EDGES_PARQUET" ] || [ ! -f "$SYMBOL_USE_EDGES_PARQUET" ]; then
  uv run python -m codeintel_rev.cli.enrich_analytics \
    --root codeintel_rev \
    --scip "$SCIP_JSON" \
    --out "$ENRICH_OUT" \
    graph
  uv run python -m codeintel_rev.cli.enrich_analytics \
    --root codeintel_rev \
    --scip "$SCIP_JSON" \
    --out "$ENRICH_OUT" \
    uses
fi

# Ensure analytics tables are present for config values and static diagnostics.
if [ ! -f "$ENRICH_OUT/analytics/config_values.parquet" ]; then
  uv run python -m codeintel_rev.cli.enrich_analytics \
    --root codeintel_rev \
    --scip "$SCIP_JSON" \
    --out "$ENRICH_OUT" \
    config
fi

if [ ! -f "$ENRICH_OUT/analytics/static_diagnostics.parquet" ]; then
  uv run python -m codeintel_rev.cli.enrich_analytics \
    --root codeintel_rev \
    --scip "$SCIP_JSON" \
    --out "$ENRICH_OUT" \
    typedness
fi

if [ ! -f "$ENRICH_OUT/analytics/function_metrics.parquet" ]; then
  uv run python -m codeintel_rev.cli.enrich_analytics \
    --root codeintel_rev \
    --scip "$SCIP_JSON" \
    --out "$ENRICH_OUT" \
    function-metrics
fi

if [ ! -f "$ENRICH_OUT/analytics/function_types.parquet" ]; then
  uv run python -m codeintel_rev.cli.enrich_analytics \
    --root codeintel_rev \
    --scip "$SCIP_JSON" \
    --out "$ENRICH_OUT" \
    function-types
fi

copy_mapping_artifact "$GOID_PARQUET" "goids"
copy_mapping_artifact "$GOID_CROSSWALK_PARQUET" "goid_crosswalk"
copy_mapping_artifact "$CALL_NODES_PARQUET" "call_graph_nodes"
copy_mapping_artifact "$CALL_EDGES_PARQUET" "call_graph_edges"
copy_mapping_artifact "$CFG_BLOCKS_PARQUET" "cfg_blocks"
copy_mapping_artifact "$CFG_EDGES_PARQUET" "cfg_edges"
copy_mapping_artifact "$DFG_EDGES_PARQUET" "dfg_edges"
copy_mapping_artifact "$IMPORT_GRAPH_EDGES_PARQUET" "import_graph_edges"
copy_mapping_artifact "$SYMBOL_USE_EDGES_PARQUET" "symbol_use_edges"

echo "==> Promoting key analytics artifacts to Document_Output root..."
copy_if_exists "$DOC_OUT/enriched/analytics/hotspots.jsonl" "$DOC_OUT/hotspots.jsonl"
copy_if_exists "$DOC_OUT/enriched/analytics/typedness.jsonl" "$DOC_OUT/typedness.jsonl"
copy_if_exists "$DOC_OUT/enriched/analytics/function_metrics.jsonl" "$DOC_OUT/function_metrics.jsonl"
copy_if_exists "$DOC_OUT/enriched/analytics/function_types.jsonl" "$DOC_OUT/function_types.jsonl"
copy_if_exists "$DOC_OUT/enriched/ast/ast_metrics.jsonl" "$DOC_OUT/ast_metrics.jsonl"
copy_if_exists "$DOC_OUT/enriched/tags/tags_index.yaml" "$DOC_OUT/tags_index.yaml"
convert_parquet_to_jsonl "$ENRICH_OUT/analytics/config_values.parquet" "$DOC_OUT/config_values.jsonl"
convert_parquet_to_jsonl "$ENRICH_OUT/analytics/static_diagnostics.parquet" "$DOC_OUT/static_diagnostics.jsonl"
convert_parquet_to_jsonl "$ENRICH_OUT/graphs/import_graph_edges.parquet" "$DOC_OUT/import_graph_edges.jsonl"
convert_parquet_to_jsonl "$ENRICH_OUT/graphs/symbol_use_edges.parquet" "$DOC_OUT/symbol_use_edges.jsonl"

echo "Document generation complete."
echo "Outputs available under: $DOC_OUT"

popd >/dev/null
