#!/usr/bin/env bash
set -euo pipefail

NGINX_BIN=${NGINX_BIN:-nginx}
SYSTEMCTL=${SYSTEMCTL:-systemctl}
NGINX_SERVICE=${NGINX_SERVICE:-nginx}

if ! command -v "${NGINX_BIN}" >/dev/null 2>&1; then
  echo "${NGINX_BIN} not found on PATH" >&2
  exit 1
fi

echo "==> syntax check" >&2
sudo "${NGINX_BIN}" -t

echo "==> reload nginx" >&2
sudo "${SYSTEMCTL}" reload "${NGINX_SERVICE}"
