#!/usr/bin/env bash
set -euo pipefail

CURL_BIN=${CURL_BIN:-curl}
TARGET=${1:-https://localhost}
READY_PATH=${READY_PATH:-${SMOKE_READY_PATH:-/readyz}}
STREAM_PATH=${STREAM_PATH:-${SMOKE_STREAM_PATH:-/sse}}
STREAM_TIMEOUT=${STREAM_TIMEOUT:-${SMOKE_STREAM_TIMEOUT:-20}}
CURL_FLAGS=()

if [[ "${VERIFY_H3_INSECURE:-${SMOKE_INSECURE:-0}}" == "1" ]]; then
  CURL_FLAGS+=(-k)
fi

if ! command -v "${CURL_BIN}" >/dev/null 2>&1; then
  echo "${CURL_BIN} not found on PATH" >&2
  exit 1
fi

if ! "${CURL_BIN}" --http3-only -V >/dev/null 2>&1; then
  echo "${CURL_BIN}" "lacks HTTP/3 support; install nghttp3/quiche enabled build" >&2
  exit 2
fi

run_curl() {
  echo "==> ${CURL_BIN} ${CURL_FLAGS[*]} ${*}" >&2
  "${CURL_BIN}" "${CURL_FLAGS[@]}" "$@"
}

run_curl --http3-only -I "${TARGET}${READY_PATH}"
run_curl --http3 -I "${TARGET}${READY_PATH}"
run_curl --http3 -N --max-time "${STREAM_TIMEOUT}" "${TARGET}${STREAM_PATH}"
