#!/usr/bin/env bash
set -euo pipefail

INDEXCTL_CMD=${INDEXCTL_CMD:-"uv run python -m codeintel_rev.cli.indexctl"}
QUERIES_FILE=${QUERIES_FILE:-scripts/queries.txt}

log() {
  echo "[smoke] $1"
}

log "exporting FAISS idmap"
${INDEXCTL_CMD} export-idmap "$@"

log "running indexctl health"
${INDEXCTL_CMD} health "$@"

if [[ -f "${QUERIES_FILE}" ]]; then
  log "running search dry-run using ${QUERIES_FILE}"
  ${INDEXCTL_CMD} search "${QUERIES_FILE}" --dry-run "$@"
else
  log "skipping search dry-run (queries file not found: ${QUERIES_FILE})"
fi
