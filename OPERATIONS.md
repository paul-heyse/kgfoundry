# OPERATIONS — MCP Front-End Hardening

This runbook explains how to choose the deployment topology, launch the stack,
reload nginx, verify HTTP/3 + streaming, and triage the most common transport
issues. All commands assume the repo root (`/opt/app` in production) unless
stated otherwise.

## 1. Supported topologies

| `MCP_EDGE_MODE` value      | Flow                                                                    | When to use |
|----------------------------|-------------------------------------------------------------------------|-------------|
| `edge-terminate` (default) | Client ⇢ **nginx (HTTP/3/TLS)** ⇢ Hypercorn (**HTTP/1.1 on 127.0.0.1:8000**) | Stable, friendly operations surface. nginx handles Alt-Svc, buffering, ACME, observability. |
| `e2e-h3`                   | Client ⇢ **nginx stream pass-through (UDP+TCP 443)** ⇢ Hypercorn (**HTTP/3 on origin**) | Literal QUIC to Python. Requires certificates on Hypercorn and UDP 443 open end-to-end. |

Pick a mode once per environment (dev/staging/prod) and keep the following
artifacts in sync:

* `ops/hypercorn.toml` — shared Hypercorn tuning. The pass-through bind/quic
  block can stay commented; `run_hypercorn.sh` overrides binds when
  `MCP_EDGE_MODE=e2e-h3`.
* nginx configs:
  * `ops/nginx/mcp_edge_terminate.conf` (HTTP/3 terminates at nginx).
  * `ops/nginx/mcp_e2e_h3_stream.conf` (TCP/UDP stream proxy).
* systemd: `ops/systemd/hypercorn.service` exports `MCP_EDGE_MODE`, and the optional
  `ops/systemd/nginx-pass-through.target` groups nginx + Hypercorn for pass-through
  deployments.

## 2. Local developer workflow

```bash
# Start Hypercorn with the selected topology (foreground)
make dev-up MCP_EDGE_MODE=edge-terminate
make dev-up MCP_EDGE_MODE=e2e-h3 \
  HYPERCORN_CERT_FILE=~/.config/mcp/cert.pem \
  HYPERCORN_KEY_FILE=~/.config/mcp/key.pem

# Stop any foreground Hypercorn started via make dev-up
make dev-down

# Reload nginx after editing ops/nginx/*.conf
make reload-nginx

# Tail logs (systemd-managed environments)
make logs-app    # hypercorn.service
make logs-nginx  # nginx.service
```

`run-hypercorn.sh` lives under `ops/scripts/` and is reused by both Makefile
targets and the systemd unit. It inspects `MCP_EDGE_MODE` and adds QUIC binds +
certificates automatically when you opt into pass-through mode.

## 3. Production rollout

1. Install the assets:
   ```bash
   make install-systemd  # installs hypercorn.service + run_hypercorn.sh
   sudo install -m0644 ops/nginx/mcp_edge_terminate.conf /etc/nginx/conf.d/mcp.conf
   sudo install -m0644 ops/nginx/mcp_e2e_h3_stream.conf /etc/nginx/stream.d/mcp.stream.conf
   ```
2. Enable HTTP/3 at the edge (open UDP 443, ensure nginx built with QUIC).
3. Set `MCP_EDGE_MODE` in `/etc/systemd/system/hypercorn.service` (drop-in) before
   `systemctl daemon-reload && systemctl restart hypercorn`.
4. Reload nginx via `make reload-nginx` (runs syntax check first).
5. (Optional) Enable `nginx-reload.timer` for periodic reloads after templating:

   ```bash
   sudo systemctl enable --now nginx-reload.timer
   ```

## 4. Smoke tests

`ops/scripts/verify_h3.sh` hits `/readyz` and `/sse` with `curl --http3`.
`make verify-h3 SMOKE_HOST=https://mcp.example.com` wraps the script. Expect:

* `curl --http3 -I` succeeds (HTTP/3 negotiated, `Alt-Svc` advertised).
* `curl --http3-only -I` also succeeds (no HTTP/2 fallback required).
* `curl --http3 -N` against `/sse` shows incremental frames followed by `: keep-alive` comments.

If your local `curl` lacks HTTP/3 support, the smoke script exits with code 2 and
a descriptive error so you know to install a nghttp3/quiche-enabled build.

## 5. Diagnosing common edge failures

1. **UDP 443 blocked** — pass-through mode requires UDP all the way to Hypercorn.
   Run `sudo ss -ulpn | grep 8443` on the host and confirm `nginx` or Hypercorn
   is listening. Use `nmap -sU -p 443 <host>` from outside.
2. **Alt-Svc missing** — ensure nginx config contains `add_header Alt-Svc ...` and
   Hypercorn `ops/hypercorn.toml` keeps `alpn_protocols` + `alt_svc_headers` when
   terminating TLS directly.
3. **Streams buffering** — nginx configs disable buffering on `/mcp/` and `/sse`.
   The FastAPI app also sets `X-Accel-Buffering: no` for SSE and logs
   `stream.lifecycle` events. If frames stall, check nginx error logs for
   `upstream prematurely closed` and confirm Hypercorn logs show matching
   `request_id`.
4. **Request correlation** — every request receives an `X-Request-Id`. The app
   logs a JSON line with `http.request` extras and the SSE helper logs
   `stream.lifecycle` events (`open`, `flush`, `cancelled`, `closed`). Grep the
   Hypercorn journal for the request ID, then match it with nginx access logs.
5. **Hypercorn refuses to start in pass-through mode** — verify cert/key paths
   are readable by the `app` user and that `MCP_EDGE_MODE=e2e-h3` is exported
   in `/etc/systemd/system/hypercorn.service.d/override.conf` or the Makefile
   invocation. The helper script prints the selected mode before exec’ing Hypercorn.

Keep `OPERATIONS.md`, `docs/NETWORKING.md`, `ops/hypercorn.toml`, and
`ops/nginx/*` in sync when making future topology tweaks. The
`verify_h3.sh` transcript in `SMOKE.txt` should be regenerated whenever you
change edge behavior.
