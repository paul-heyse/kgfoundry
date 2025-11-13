#!/usr/bin/env bash

set -Eeuo pipefail
trap 'log "hook failed on line ${LINENO}" >&2' ERR

NGINX_BIN=${NGINX_BIN:-/usr/sbin/nginx}
SYSTEMCTL_BIN=${SYSTEMCTL_BIN:-/bin/systemctl}
HYPERCORN_SERVICE=${HYPERCORN_SERVICE:-hypercorn-codeintel.service}
HYPERCORN_CFG=${HYPERCORN_CFG:-/opt/codeintel_rev/ops/hypercorn/hypercorn.toml}

log() {
    printf '[certbot-hook] %s\n' "$*"
}

reload_nginx() {
    if ! "${SYSTEMCTL_BIN}" is-active --quiet nginx; then
        log "nginx inactive; skipping reload"
        return
    fi
    log "reloading nginx to pick up renewed certificates"
    "${NGINX_BIN}" -t
    "${SYSTEMCTL_BIN}" reload nginx
}

reload_hypercorn_if_needed() {
    if [[ ! -f "${HYPERCORN_CFG}" ]]; then
        log "Hypercorn config (${HYPERCORN_CFG}) missing; skipping restart"
        return
    fi
    if grep -Eq '^[[:space:]]*certfile[[:space:]]*=' "${HYPERCORN_CFG}" || [[ "${FORCE_HYPERCORN_RELOAD:-0}" == "1" ]]; then
        if "${SYSTEMCTL_BIN}" status "${HYPERCORN_SERVICE}" >/dev/null 2>&1; then
            log "restarting ${HYPERCORN_SERVICE} to load renewed certificates"
            "${SYSTEMCTL_BIN}" restart "${HYPERCORN_SERVICE}"
        else
            log "${HYPERCORN_SERVICE} not installed; skipping restart"
        fi
    else
        log "Hypercorn not terminating TLS (certfile absent); no restart needed"
    fi
}

reload_nginx
reload_hypercorn_if_needed

log "hook complete"
