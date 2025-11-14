#!/usr/bin/env bash
set -euo pipefail

EDGE_MODE=${MCP_EDGE_MODE:-${EDGE_MODE:-edge-terminate}}
HYPERCORN_APP=${HYPERCORN_APP:-codeintel_rev.app.main:asgi}
HYPERCORN_CONFIG=${HYPERCORN_CONFIG:-ops/hypercorn.toml}
HYPERCORN_CERT_FILE=${HYPERCORN_CERT_FILE:-/etc/ssl/live/mcp.example.com/fullchain.pem}
HYPERCORN_KEY_FILE=${HYPERCORN_KEY_FILE:-/etc/ssl/live/mcp.example.com/privkey.pem}
HYPERCORN_BIND=${HYPERCORN_BIND:-0.0.0.0:8443}
HYPERCORN_QUIC_BIND=${HYPERCORN_QUIC_BIND:-0.0.0.0:8443}

BASE_CMD=(hypercorn --config "${HYPERCORN_CONFIG}")

case "${EDGE_MODE}" in
  edge-terminate)
    echo "[run_hypercorn] MCP_EDGE_MODE=edge-terminate -> proxy expects HTTP/1.1 on loopback" >&2
    exec "${BASE_CMD[@]}" "${HYPERCORN_APP}"
    ;;
  e2e-h3)
    echo "[run_hypercorn] MCP_EDGE_MODE=e2e-h3 -> Hypercorn terminates QUIC" >&2
    exec "${BASE_CMD[@]}" \
      --bind "${HYPERCORN_BIND}" \
      --quic-bind "${HYPERCORN_QUIC_BIND}" \
      --certfile "${HYPERCORN_CERT_FILE}" \
      --keyfile "${HYPERCORN_KEY_FILE}" \
      "${HYPERCORN_APP}"
    ;;
  *)
    echo "Unknown MCP_EDGE_MODE '${EDGE_MODE}'. Expected edge-terminate or e2e-h3." >&2
    exit 1
    ;;
 esac
