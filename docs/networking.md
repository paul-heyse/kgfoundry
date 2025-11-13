# Networking Runbook

This guide explains how to run the CodeIntel MCP service with end-to-end HTTP/3
support, hardened reverse proxy settings, and automated certificate reloads.
All referenced assets live under `ops/` so they can be version-controlled and
audited alongside the application.

## Topologies at a glance

| Mode | Files | When to pick it | Notes |
| ---- | ----- | --------------- | ----- |
| **Topology A** – HTTP/3 terminates at NGINX | `ops/nginx/h3_terminating.conf`, `ops/hypercorn/hypercorn.toml` (default) | Preferred for most deployments; keeps TLS/H3 at the edge, uses HTTP/1.1 to Hypercorn | All L7 features available: rate limiting, header shaping, ACME webroot, buffering control. Hypercorn listens on `127.0.0.1:8080`. |
| **Topology B** – Layer 4 pass-through (end-to-end H3) | `ops/nginx/h3_passthrough.conf`, uncomment `bind/quic_bind/certfile` in `ops/hypercorn/hypercorn.toml` | When you need literal QUIC all the way to Python or want to skip NGINX buffering entirely | NGINX only proxies TCP/UDP. Hypercorn terminates TLS/QUIC and must reload when certificates change. |

Switching between modes is mechanical: swap the included NGINX file and flip
the bind block inside `ops/hypercorn/hypercorn.toml`.

## File layout

```
ops/
  nginx/
    h3_terminating.conf     # L7 termination, streaming-friendly proxy
    h3_passthrough.conf     # L4 pass-through for QUIC end-to-end
  hypercorn/hypercorn.toml  # Workers, Alt-Svc, QUIC/TLS toggles
  systemd/
    hypercorn-codeintel.service
    nginx.service.d/override.conf
  certbot/renewal-hook.sh   # Post-renewal hook (reload nginx + Hypercorn if needed)
```

`codeintel_rev/app/server_settings.py` centralizes proxy/trust settings. The
FastAPI app automatically reads the `.env`/env variables (`CODEINTEL_SERVER_*`)
and wraps the exported ASGI object with Hypercorn's `ProxyFixMiddleware`.

## Deploy flow

1. Copy the repository (or a release tarball) to `/opt/codeintel_rev`.
2. Install systemd units and ulimits:

   ```bash
   make install-systemd
   ```

3. Place the desired NGINX file under `/etc/nginx/conf.d/` (Topology A) or add
   `include /opt/codeintel_rev/ops/nginx/h3_passthrough.conf;` inside the
   `stream {}` block (Topology B). Run `nginx -t && sudo systemctl reload nginx`.
4. For HTTPS, issue certificates via Certbot (webroot under
   `/var/www/codeintel_rev/acme`) and symlink `ops/certbot/renewal-hook.sh` into
   `/etc/letsencrypt/renewal-hooks/deploy/`.
5. Start Hypercorn:

   ```bash
   make run-hypercorn        # local dev
   sudo systemctl start hypercorn-codeintel.service
   ```

## Verification workflow

1. **Health** – `curl https://mcp.example.com/readyz` should return JSON with
   `"ready": true`. The new `tests/app/test_networking_endpoints.py` ensures the
   route continues to respond even when proxied.
2. **Capabilities** – `curl https://mcp.example.com/capz?refresh=true` should
   return a fresh capability snapshot plus a `stamp`.
3. **Streaming** – `curl -N https://mcp.example.com/sse` produces events with
   `X-Accel-Buffering: no` thanks to middleware covered by tests.
4. **HTTP/3** – run `make verify-h3` (uses `curl --http3-only`). In browsers,
   open DevTools → Network → Protocol column; after a refresh it should read `h3`.
   Remember that Alt-Svc requires one successful TCP request before the browser
   retries with QUIC.

## Abuse-control handbook

* NGINX config contains commented `limit_req` / `limit_conn` zones. Enable them
  when the service is internet-facing and tune burst limits per environment.
* Hypercorn `keep_alive_timeout`, `ssl_handshake_timeout`, and
  `h2_max_concurrent_streams` are pinned in `ops/hypercorn/hypercorn.toml`
  to mitigate idle-socket DoS attempts.
* `codeintel_rev/app/main.py` installs `TrustedHostMiddleware` (configurable via
  `CODEINTEL_SERVER_ALLOWED_HOSTS`) and wraps the ASGI app with
  `ProxyFixMiddleware` so the request scheme/host remains accurate behind NGINX.
* The `/readyz`, `/capz`, and `/sse` regression tests use `httpx.AsyncClient`
  to ensure 200s and streaming survive future code changes.

## Server settings & environment

`codeintel_rev/app/server_settings.py` exposes typed knobs that can be set from
`.env` or the environment. Common overrides:

| Variable | Purpose |
| -------- | ------- |
| `CODEINTEL_SERVER_ALLOWED_HOSTS` | Comma-separated list of domains accepted by `TrustedHostMiddleware`. Include your public FQDN and loopback values for health checks. |
| `CODEINTEL_SERVER_CORS_ALLOW_ORIGINS` | CSV of origins permitted to call the FastAPI surface. Defaults to ChatGPT + localhost. |
| `CODEINTEL_SERVER_PROXY_MODE` | `modern` (default) prefers the `Forwarded` header, `legacy` reads `X-Forwarded-*`. |
| `CODEINTEL_SERVER_PROXY_TRUSTED_HOPS` | Number of proxy hops Hypercorn trusts when reconstructing the client IP. |

Regenerate the `.env` example whenever you add variables so runbooks stay in
sync.

## Certificate automation

* `ops/certbot/renewal-hook.sh`:
  * Always validates and reloads NGINX after renewal.
  * Restarts `hypercorn-codeintel.service` automatically when the Hypercorn
    config has an active `certfile=` entry (Topology B) or when
    `FORCE_HYPERCORN_RELOAD=1`.
* Wire it in with `sudo install -m0755 ops/certbot/renewal-hook.sh \
  /etc/letsencrypt/renewal-hooks/deploy/99-codeintel.sh`.

## Troubleshooting

| Symptom | Likely cause | Fix |
| ------- | ------------ | --- |
| `curl --http3-only` hangs | UDP/443 blocked or Alt-Svc missing | Open UDP 443 on firewalls, reload nginx, ensure `add_header Alt-Svc 'h3=":443"; ma=86400' always;` is present. |
| `/readyz` returns `503` via proxy | FastAPI app could not initialize, or Hypercorn not running | Check `journalctl -u hypercorn-codeintel`, confirm `make run-hypercorn` works, ensure `.env` settings valid. |
| Browser sticks to `h2` | First TCP request cached, Alt-Svc stale | Hard refresh (Ctrl+Shift+R), lower `ma` in Alt-Svc, or publish HTTPS/SVCB DNS records. |
| Streaming stalls mid-response | Proxy buffering accidentally enabled | Verify `proxy_buffering off` in `h3_terminating.conf` and that the app is still setting `X-Accel-Buffering: no`. |
| Certbot renewals succeed but Hypercorn still serves old certs | Hypercorn operates in Topology B but hook not installed | Install `ops/certbot/renewal-hook.sh` or set `FORCE_HYPERCORN_RELOAD=1` before running `certbot renew`. |

All commands referenced above are encapsulated in the root `Makefile` so the
full validation loop (`make format lint types test verify-h3`) can run from a
single interface.
