#!/usr/bin/env bash
set -euo pipefail

EDGE_MODE=${EDGE_MODE:-nginx-terminate}
HYPERCORN_APP=${HYPERCORN_APP:-codeintel_rev.app.main:asgi}
HYPERCORN_CONFIG=${HYPERCORN_CONFIG:-ops/hypercorn.toml}
HYPERCORN_CERT_FILE=${HYPERCORN_CERT_FILE:-/etc/ssl/live/mcp.example.com/fullchain.pem}
HYPERCORN_KEY_FILE=${HYPERCORN_KEY_FILE:-/etc/ssl/live/mcp.example.com/privkey.pem}
HYPERCORN_BIND=${HYPERCORN_BIND:-0.0.0.0:8443}
HYPERCORN_QUIC_BIND=${HYPERCORN_QUIC_BIND:-0.0.0.0:8443}

BASE_CMD=(hypercorn --config "${HYPERCORN_CONFIG}")

case "${EDGE_MODE}" in
  nginx-terminate)
    echo "[run_hypercorn] EDGE_MODE=nginx-terminate -> proxy expects HTTP/1.1 on loopback" >&2
    exec "${BASE_CMD[@]}" "${HYPERCORN_APP}"
    ;;
  h3-pass-through)
    echo "[run_hypercorn] EDGE_MODE=h3-pass-through -> Hypercorn terminates QUIC" >&2
    exec "${BASE_CMD[@]}" \
      --bind "${HYPERCORN_BIND}" \
      --quic-bind "${HYPERCORN_QUIC_BIND}" \
      --certfile "${HYPERCORN_CERT_FILE}" \
      --keyfile "${HYPERCORN_KEY_FILE}" \
      "${HYPERCORN_APP}"
    ;;
  *)
    echo "Unknown EDGE_MODE '${EDGE_MODE}'. Expected nginx-terminate or h3-pass-through." >&2
    exit 1
    ;;
 esac
