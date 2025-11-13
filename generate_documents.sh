#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# End-to-end document generation helper.
# Runs SCIP indexing, enrichment (LibCST + AST), CST dataset build,
# then copies outputs into a top-level "Document Output" folder.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pushd "$REPO_ROOT" >/dev/null

SCIP_DIR="codeintel_rev"
SCIP_BIN="$SCIP_DIR/index.scip"
SCIP_JSON="$SCIP_DIR/index.scip.json"
ENRICH_OUT="$SCIP_DIR/io/ENRICHED"
CST_OUT="$SCIP_DIR/io/CST"
DOC_OUT="$REPO_ROOT/Document Output"

echo "==> Generating SCIP index..."
(
  cd "$SCIP_DIR"
  scip-python index ../src --project-name kgfoundry
  scip print --json index.scip > index.scip.json
)

echo "==> Running enrichment pipeline (LibCST + AST + analytics)..."
uv run python -m codeintel_rev.cli_enrich \
  --root codeintel_rev \
  --scip "$SCIP_JSON" \
  --out "$ENRICH_OUT" \
  all \
  --emit-ast

echo "==> Building CST dataset..."
uv run python -m codeintel_rev.cst_build.cst_cli \
  --root codeintel_rev \
  --scip "$SCIP_JSON" \
  --modules "$ENRICH_OUT/modules/modules.jsonl" \
  --out "$CST_OUT"

echo "==> Copying artifacts into \"$DOC_OUT\"..."
rm -rf "$DOC_OUT"
mkdir -p "$DOC_OUT"
cp -R "$ENRICH_OUT" "$DOC_OUT/enriched"
cp -R "$CST_OUT" "$DOC_OUT/cst"
mkdir -p "$DOC_OUT/scip"
cp "$SCIP_BIN" "$DOC_OUT/scip/index.scip"
cp "$SCIP_JSON" "$DOC_OUT/scip/index.scip.json"

echo "Document generation complete."
echo "Outputs available under: $DOC_OUT"

popd >/dev/null
