#!/usr/bin/env bash
set -euo pipefail

CURL_BIN=${CURL_BIN:-curl}
TARGET=${1:-https://localhost}
READY_PATH=${READY_PATH:-/mcp/readyz}
STREAM_PATH=${STREAM_PATH:-/sse}
STREAM_TIMEOUT=${SMOKE_STREAM_TIMEOUT:-15}
CURL_FLAGS=()

if [[ "${SMOKE_INSECURE:-0}" == "1" ]]; then
  CURL_FLAGS+=(-k)
fi

if ! "${CURL_BIN}" --http3-only -V >/dev/null 2>&1; then
  echo "curl binary (${CURL_BIN}) is missing HTTP/3 support (needs nghttp3/quiche build)" >&2
  exit 2
fi

echo "==> curl --http3 -I ${TARGET}${READY_PATH}" >&2
"${CURL_BIN}" "${CURL_FLAGS[@]}" --http3 -I "${TARGET}${READY_PATH}"

echo "==> curl --http3-only -I ${TARGET}${READY_PATH}" >&2
"${CURL_BIN}" "${CURL_FLAGS[@]}" --http3-only -I "${TARGET}${READY_PATH}"

echo "==> curl --http3 -N ${TARGET}${STREAM_PATH} (timeout ${STREAM_TIMEOUT}s)" >&2
"${CURL_BIN}" "${CURL_FLAGS[@]}" --http3 -N --max-time "${STREAM_TIMEOUT}" "${TARGET}${STREAM_PATH}"
