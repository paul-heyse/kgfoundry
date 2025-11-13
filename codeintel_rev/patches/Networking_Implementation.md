# Core Implementation #

Absolutely—let’s lock in a **production‑grade NGINX + Hypercorn (HTTP/3/QUIC) stack** around your existing MCP server so ChatGPT (or any MCP‑capable client) can connect reliably with streaming semantics (SSE/WebSocket), zero “sticky” reconnect issues, and clean extensibility.

Below is a **two‑part deliverable**:

1. **Design & operational blueprint** (why + what to configure, with trade‑offs).
2. **Concrete code/config diffs** you can apply to your repo and host (Hypercorn TOML, NGINX configs for H3 termination and for H3 pass‑through, systemd units, and minimal app changes to expose `/mcp`).

Where I refer to your repo’s current constructs (e.g., existing endpoints, capability snapshot, MCP app factory), I cite from the SCIP index you provided so you can trace exactly where these pieces live in your tree. Your repository already exposes a FastAPI app with **`/readyz`**, **`/capz`**, and an **SSE demo** endpoint, plus structured capability detection that the MCP adapter already consumes—so we’ll *mount* the MCP ASGI app under `/mcp` instead of reinventing the server.

---

## 1) Architecture & trade‑offs (HTTP/3, NGINX, Hypercorn)

### What “HTTP/3 end‑to‑end” actually means with NGINX today

* **NGINX supports HTTP/3/QUIC for *client* connections** starting in 1.25, via `listen ... quic` and related directives like `quic_retry` and `ssl_early_data`. ([Nginx][1])
* **NGINX does not (as of 2025-11-12) proxy to upstreams over HTTP/3**. Upstream H3 proxying requests continue to track as a feature request (and HTTP/2 to upstream is also not supported in OSS NGINX). If you want literal H3 hop‑to‑hop from client → NGINX → origin, that’s not supported; you can either terminate H3 at NGINX or **use NGINX “stream” as a layer‑4 pass‑through** to keep QUIC end‑to‑end. ([GitHub][2])

Because of this, you have **two proven topologies**:

**A. “Terminate at NGINX” (recommended for operations)**
`Client (H3) → NGINX (H3 terminates) → Hypercorn (H1.1 on loopback)`

* Pros: Mature, robust ops surface (TLS, cert rotation, retries/backoff, caching knobs, access control, DDoS mitigation, rate limiting), simple logging & Prometheus scraping.
* Cons: Not end‑to‑end H3; origin leg is H1.1 (or H2 where supported—NGINX OSS proxying to upstream over H2 isn’t; keep H1.1). ([Nginx][3])

**B. “End‑to‑end H3 via L4 pass‑through (stream)”**
`Client (H3) → NGINX stream (UDP/TCP pass‑through) → Hypercorn (H3)`

* Pros: **True end‑to‑end HTTP/3/QUIC** to your Python process; minimal overhead, lowest tail latency for SSE/WebSockets.
* Cons: You lose most L7 features on NGINX (no header manipulation, caching, WAF, request buffering), and troubleshooting moves to app/server. Use only if you must have *literal* H3 on both legs. NGINX stream (TCP/UDP) pass‑through is stable and documented. ([Nginx][4])

> **Hypercorn** supports **HTTP/3/QUIC** with `quic_bind`, `alpn_protocols`, `alt_svc_headers` in TOML/config; also ships **ProxyFixMiddleware** to correctly honor `Forwarded`/`X‑Forwarded‑*` headers when running behind a proxy (e.g., topology A). ([Hypercorn][5])

### Why NGINX + Hypercorn is a great fit for your MCP repo

Your codebase already has:

* A FastAPI app with health/readiness (`/readyz`) and capability snapshot (`/capz`) endpoints, plus an **SSE streaming demo**, which tells us streaming semantics are already thought through.
* A structured **capability model** to gate MCP tools and a factory that builds the MCP **ASGI app** from capabilities. We’ll **mount** this MCP app at `/mcp`.
* Middleware that already adds “**disable nginx buffering**” headers for streaming robustness—ideal for SSE/WebSocket behind NGINX. 

Together, that enables a clean, maintainable boundary:

* **ASGI**: Starlette/FastAPI app exposes `/mcp` (ASGI sub‑app) + `/readyz`, `/capz`, metrics.
* **Hypercorn**: Single process handling H1/H2/H3 (when direct) with QUIC on the same port (TCP+UDP), terminating TLS if in pass‑through mode, or just plain TLS on loopback if NGINX terminates. ([Hypercorn][5])
* **NGINX**: H3 entry, rate‑limit & protect (topology A), or L4 pass‑through for H3 end‑to‑end (topology B). QUIC config is first‑class since 1.25, using `listen 443 quic reuseport;`, `quic_retry on;`, `ssl_early_data on;`, and `Alt‑Svc`. ([Nginx][1])

---

## 2) Implementation plan by layer

### 2.1 ASGI app (mount MCP under `/mcp`, keep streaming and capability model)

Your repo already has:

* **`codeintel_rev.app.main:app`** (FastAPI), with `/readyz`, `/capz`, `/sse`, and caching the capability snapshot.
* **`Capabilities.from_context(context)`** builds the runtime capability snapshot;
  **`build_http_app(capabilities)`** returns the MCP ASGI app.

**What we’ll add**

* Mount the MCP ASGI app at **`/mcp`** during startup (after the application context exists).
* Wrap the exported ASGI app with **Hypercorn’s `ProxyFixMiddleware`** (topology A) to honor `Forwarded` / `X‑Forwarded‑*` from NGINX and keep `request.url` / scheme correct. ([Hypercorn][6])
* (Optional) Add `TrustedHostMiddleware` with your domains to mitigate host‑header attacks. ([starlette.dev][7])

> You already set “disable buffering” headers in middleware—this is perfect for SSE through NGINX and avoids stalled streams. 

### 2.2 Hypercorn configuration (H3 with or without NGINX termination)

We’ll ship a **`hypercorn.toml`** that supports both modes:

* **Topology A (NGINX terminates H3)**: Hypercorn listens on loopback TCP (`:8080`) with TLS *optional* (usually HTTP over loopback).
* **Topology B (H3 end‑to‑end)**: Hypercorn binds **the same port for TCP and UDP** with TLS material to negotiate ALPN (`h3`, `h2`, `http/1.1`), QUIC via `quic_bind`, and optional `Alt‑Svc`. ([Hypercorn][5])

You can run Hypercorn with TOML files (`--config`) and with an **ASGI object name** (e.g., `codeintel_rev.app.main:asgi`). ([Hypercorn][5])

### 2.3 NGINX configuration (two canonical variants)

**Variant A — H3 termination at NGINX**

* `listen 443 quic reuseport;` and `listen 443 ssl http2;` (H2 fallback) on the same `server`.
* **`Alt-Svc`** header to advertise H3.
* Proxy to Hypercorn on loopback (HTTP/1.1).
* Streaming‑friendly settings: **`proxy_buffering off`**, long **`proxy_read_timeout`**, pass through upgrade headers for WebSocket.
* QUIC enhancements like `quic_retry on;` and `ssl_early_data on;` optional. ([Nginx][1])

**Variant B — L4 pass‑through (TCP+UDP) for true H3 end‑to‑end**

* Use **`stream {}`** with one server on **UDP 443** and one on **TCP 443**, both forwarding to Hypercorn’s port.
* You keep H3 all the way to Hypercorn (no HTTP‑level knobs on NGINX). ([Nginx][4])

> If you later need SNI‑based fan‑out at L4, `ssl_preread` in the stream layer can route by SNI for TCP; UDP QUIC SNI routing is evolving, but the UDP pass‑through is stable. ([Server Fault][8])

### 2.4 Security & robustness

* **Proxy headers**: In topology A, configure NGINX to set `Forwarded` and `X‑Forwarded‑*`. Wrap the ASGI app with Hypercorn’s **`ProxyFixMiddleware(mode="legacy", trusted_hops=1)`** so URLs/scheme/client IPs in logs are correct. ([Hypercorn][6])
* **Host hardening**: Add Starlette/FastAPI **`TrustedHostMiddleware`** with your public domains. ([starlette.dev][7])
* **Rate limiting / connection caps**: Prefer NGINX at the edge for per‑IP/zone rate limiting (topology A).
* **Observability**: You already expose Prometheus metrics; keep access/error logs both on NGINX and Hypercorn. 
* **SSE/WebSocket**: NGINX: `proxy_buffering off;`, `proxy_read_timeout 3600;`, and WebSocket headers (`Upgrade`/`Connection`). Hypercorn supports WS over H1/H2; H3 direct works in topology B. ([Hypercorn][5])

---

## 3) Code & config diffs

> The diffs below assume the package root is your repo root and that the running ASGI entry remains **`codeintel_rev.app.main`**. We’ll add a Hypercorn‑wrapped **`asgi`** object and mount the MCP app at `/mcp`.

### 3.1 Mount MCP under `/mcp` and wrap with ProxyFix (FastAPI app)

```diff
--- a/codeintel_rev/app/main.py
+++ b/codeintel_rev/app/main.py
@@
-from fastapi import FastAPI, Request
+from fastapi import FastAPI, Request
+from typing import Optional
+import os
+from starlette.routing import Mount
+from hypercorn.middleware import ProxyFixMiddleware  # honors Forwarded / X-Forwarded-*
+from codeintel_rev.mcp_server.server import build_http_app
+from codeintel_rev.app.capabilities import Capabilities
@@
-# existing app = FastAPI(...) with /readyz, /capz, /sse etc.
 app = FastAPI(title="codeintel_rev", docs_url="/docs")
 
@@
-# lifespan() already initializes app.state.context and other state
+# lifespan() already initializes app.state.context and other state
 
+@app.on_event("startup")
+async def _mount_mcp() -> None:
+    """
+    Build and mount the MCP ASGI application under /mcp using the
+    current capability snapshot from the ApplicationContext.
+    """
+    ctx = getattr(app.state, "context", None)
+    if ctx is None:
+        # Fallback: allow /capz to signal not-ready instead of failing startup
+        return
+    caps = Capabilities.from_context(ctx)
+    app.state.capabilities = caps  # reused by /capz
+    mcp_asgi = build_http_app(caps)
+    # Mount once; if reloaded, FastAPI will rebuild routes anyway
+    app.mount("/mcp", mcp_asgi)
+
+# Export a Hypercorn-ready ASGI object that fixes proxy headers when behind NGINX.
+# Use this name as the application target for Hypercorn (see systemd unit below).
+trusted_hops = int(os.getenv("PROXY_TRUSTED_HOPS", "1"))
+asgi = ProxyFixMiddleware(app, mode="legacy", trusted_hops=trusted_hops)
```

Why these changes align with your code:

* **`Capabilities.from_context`** exists and is intended for snapshotting features from your `ApplicationContext`. 
* **`build_http_app(capabilities)`** constructs the FastMCP HTTP app with tools gated by available capabilities. 
* Your app already caches/report caps in **`/capz`** and implements streaming via **`/sse`**. We keep that intact. 

> If you also want to enforce host header validation, add in `main.py` (optional):
>
> ```python
> from starlette.middleware.trustedhost import TrustedHostMiddleware
> app.add_middleware(TrustedHostMiddleware, allowed_hosts=["example.com", "*.example.com", "localhost"])
> ```
>
> This is a Starlette‑level guard against host‑header attacks. ([starlette.dev][7])

---

### 3.2 Hypercorn configuration (TOML) for both topologies

Create **`ops/hypercorn.toml`**:

```toml
# --- Common ---
accesslog = "-"          # stdout
errorlog  = "-"          # stderr
keep_alive_timeout = 75  # generous for SSE/WS
graceful_timeout  = 20
include_server_header = false

# Advertise protocols; Hypercorn defaults are ['h2','http/1.1'], add 'h3' when using QUIC.
alpn_protocols = ["h2", "http/1.1", "h3"]

# If you want Alt-Svc from Hypercorn itself (topology B)
alt_svc_headers = ["h3=\":443\"; ma=86400"]

# === Topology A (NGINX terminates H3) ===
# NGINX proxies HTTP to loopback; no TLS necessary on the app hop.
bind = ["127.0.0.1:8080"]

# === Topology B (End-to-end H3 via L4 pass-through) ===
# Comment out `bind` above and use the following instead.
# TCP and QUIC share the same port; ensure certificates exist.
# bind = ["0.0.0.0:8443"]
# quic_bind = ["0.0.0.0:8443"]
# certfile = "/etc/ssl/certs/codeintel_rev.crt"
# keyfile  = "/etc/ssl/private/codeintel_rev.key"

# NOTE: Run Hypercorn against 'codeintel_rev.app.main:asgi'.
# See systemd unit below.
```

**Why this works**
Hypercorn supports TOML‑based config, `quic_bind`, `alpn_protocols`, and `alt_svc_headers`. Use `:8080` for NGINX‑terminated H3 or `:8443` with QUIC/TLS for end‑to‑end H3. ([Hypercorn][5])

---

### 3.3 NGINX configuration — **Variant A: H3 termination + proxy to loopback**

Create **`ops/nginx/h3_terminating.conf`** (adapt paths/domains):

```nginx
# /etc/nginx/conf.d/codeintel_rev.conf
server {
    listen 443 quic reuseport;      # HTTP/3 over QUIC
    listen 443 ssl http2;           # HTTP/2/TLS fallback
    server_name mcp.example.com;

    ssl_certificate     /etc/ssl/certs/mcp.example.com.crt;
    ssl_certificate_key /etc/ssl/private/mcp.example.com.key;
    # QUIC/H3 tips (see nginx.org QUIC docs):
    ssl_protocols TLSv1.3;
    quic_retry on;           # optional address validation
    ssl_early_data on;       # optional 0-RTT
    add_header Alt-Svc 'h3=":443"; ma=86400' always;

    # Common proxy headers; prefer Forwarded + X-Forwarded-* for app correctness
    set $upstream http://127.0.0.1:8080;

    location / {
        proxy_http_version 1.1; # upstream is H1.1; NGINX doesn't proxy upstream over H2/H3
        proxy_set_header Host               $host;
        proxy_set_header X-Real-IP          $remote_addr;
        proxy_set_header X-Forwarded-For    $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto  $scheme;
        proxy_set_header Forwarded          "for=$remote_addr;proto=$scheme;host=$host";

        # Streaming / SSE friendliness
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout  3600s;
        proxy_send_timeout  3600s;

        # WebSocket support
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_pass $upstream;
    }
}
```

* QUIC/H3 directives (`listen ... quic reuseport`, `quic_retry`, `ssl_early_data`, `Alt‑Svc`) follow the **official NGINX QUIC docs**. ([Nginx][1])
* Upstream leg uses **HTTP/1.1** (NGINX OSS won’t proxy upstream over H2/H3). ([Nginx][3])

---

### 3.4 NGINX configuration — **Variant B: Layer‑4 pass‑through for end‑to‑end H3**

Create **`ops/nginx/h3_passthrough.conf`**:

```nginx
# /etc/nginx/nginx.conf (or conf.d/stream.conf)
stream {
    # UDP QUIC pass-through
    upstream hypercorn_quic {
        server 127.0.0.1:8443;  # Hypercorn QUIC port (same number as TCP)
    }
    server {
        listen 443 udp reuseport;
        proxy_pass hypercorn_quic;
    }

    # TCP TLS pass-through (fallback for non-H3/legacy)
    upstream hypercorn_tls {
        server 127.0.0.1:8443;
    }
    server {
        listen 443;
        proxy_pass hypercorn_tls;
    }
}
```

This keeps QUIC/TLS **end‑to‑end** with Hypercorn. You forego HTTP‑level controls at NGINX, because this is pure L4. The **`stream`**/UDP/TCP pass‑through usage is standard. ([Nginx][4])

---

### 3.5 systemd unit for stable, auto‑restarting Hypercorn

Create **`ops/systemd/hypercorn-codeintel.service`**:

```ini
[Unit]
Description=Hypercorn (codeintel_rev ASGI)
After=network.target
Wants=network-online.target

[Service]
# Use the ProxyFix-wrapped ASGI callable
Environment=PYTHONUNBUFFERED=1
Environment=PROXY_TRUSTED_HOPS=1
# Topology A: NGINX terminates H3
ExecStart=/usr/bin/env hypercorn --config ops/hypercorn.toml codeintel_rev.app.main:asgi
# If using Topology B, ensure keys exist and switch to the B section in TOML.

WorkingDirectory=/opt/codeintel_rev
Restart=always
RestartSec=2
User=www-data
Group=www-data
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

This ensures process supervision, clean restarts, and no “random drops” due to terminal closure—a point you raised earlier. Hypercorn’s **graceful timeout** and **keep‑alive** are tuned in the TOML. ([Hypercorn][5])

---

## 4) Optional but recommended hardening & operations

* **TrustedHostMiddleware** in the app to only allow known hostnames (production). ([starlette.dev][7])
* **TLS/certs**: Prefer short‑lived certs via ACME (NGINX handles rotation in topology A).
* **SSE watchdogs**: Clients should re‑connect on `204`/`499`/timeouts; NGINX timeouts are already generous.
* **Proxy headers**: With topology A, favor the standardized `Forwarded:` header in addition to `X‑Forwarded-*`; Hypercorn’s ProxyFix handles both. ([Hypercorn][6])
* **Health**: Keep using `/readyz` to gate restarts and drains; it already reports sub‑checks and a `ready` boolean. 

---

## 5) How this ties directly to your code

* Your **ASGI app** already exists (`codeintel_rev.app.main:app`), with **readiness**, **capability snapshot**, and **SSE** for streaming—these routes stay untouched and continue to work behind NGINX.
* Your **capability machinery** (`Capabilities.from_context`) is used to build the MCP HTTP app (via **`build_http_app`**) and mounted at **`/mcp`**. That means ChatGPT (or any MCP‑aware client) can hit `/mcp` uniformly regardless of fronting topology.
* Existing **“disable NGINX buffering”** middleware will continue to set `X‑Accel-Buffering: no`, ideal for SSE through NGINX. 

---

## 6) End‑to‑end validation checklist

1. **Hypercorn (Topology A)**

   ```bash
   # app on loopback
   hypercorn --config ops/hypercorn.toml codeintel_rev.app.main:asgi
   curl -sS http://127.0.0.1:8080/readyz | jq .
   ```
2. **NGINX (Topology A)**

   * Confirm `listen 443 quic reuseport;` and `Alt-Svc` are active.
   * Test with a client that can negotiate H3 (e.g., `curl --http3 -I https://mcp.example.com/readyz`).
   * Exercise SSE: `curl -N https://mcp.example.com/sse`.
3. **Hypercorn (Topology B)**

   * Switch TOML to `bind = ["0.0.0.0:8443"]` and `quic_bind = ["0.0.0.0:8443"]` with certs/keys.
   * Test direct H3: `curl --http3 -I https://your-host:8443/readyz`.
4. **NGINX stream (Topology B)**

   * Enable `ops/nginx/h3_passthrough.conf` and confirm both **TCP 443** and **UDP 443** reach Hypercorn.
   * Validate: `curl --http3 -I https://mcp.example.com/readyz`.
5. **MCP**

   * `GET https://mcp.example.com/mcp/…` (whatever the MCP discovery/HTTP endpoint shape is from FastMCP). Your MCP tools (semantic search, symbols) are capability‑gated already. 

---

## 7) Appendices (why these specific knobs)

* **NGINX QUIC/H3** directives (listen `quic`, `reuseport`, `quic_retry`, `ssl_early_data`, `Alt‑Svc`) and the note that QUIC requires TLS 1.3 come straight from the official NGINX HTTP/3 docs. ([Nginx][1])
* **Upstream HTTP/3** proxying in NGINX OSS is not supported yet; the stream module is the correct way to preserve H3 to the origin. ([GitHub][2])
* **Hypercorn** supports TOML config, QUIC via `quic_bind`, ALPN advertisement (add `h3`), and **ProxyFixMiddleware** to respect reverse‑proxy headers (pick “legacy” or “modern” mode depending on `Forwarded` vs `X‑Forwarded-*`). ([Hypercorn][5])
* **TrustedHostMiddleware** is the canonical Starlette/ FastAPI host‑header guard. ([starlette.dev][7])

---

## 8) Summary of files added/changed

```
ops/
  hypercorn.toml                       # Hypercorn config (both topologies)
  nginx/
    h3_terminating.conf                # H3 termination + proxy to :8080
    h3_passthrough.conf                # L4 pass-through TCP+UDP 443 → :8443
  systemd/
    hypercorn-codeintel.service        # Process supervision for Hypercorn

codeintel_rev/app/main.py              # Mount MCP at /mcp + ProxyFix ASGI export
```

If you want, we can also drop in a **Dockerfile + Compose** that selects topology A by default and binds `:8080`, but the above is sufficient for bare‑metal installs.

---

### What you get after applying these changes

* **Uniform client experience** for ChatGPT/MCP clients: always talk to `/mcp`—no matter which topology or transport you pick.
* **High reliability**: systemd supervision, graceful restarts, and NGINX edge resilience.
* **High performance**: HTTP/3 QUIC on the edge (or end‑to‑end), proxy buffering disabled for stream endpoints, and clean async ASGI pipeline.
* **High extensibility**: the capability‑gated MCP toolset you already built remains in control; adding new tools is a pure code concern—no infra churn. 

---

If you’d like, I can also provide **nginx `map`/`limit_req`** snippets for abuse‑control, and a **certbot** ACME hook that reloads NGINX and sends a `SIGHUP` to Hypercorn when certs rotate (Topology B). But you can deploy with the diffs above as‑is and get fully working H3 today.

[1]: https://nginx.org/en/docs/quic.html "Support for QUIC and HTTP/3"
[2]: https://github.com/nginx/nginx/issues/496?utm_source=chatgpt.com "reverse proxy to http3/quic · Issue #496 · nginx/nginx"
[3]: https://nginx.org/en/docs/http/ngx_http_upstream_module.html?utm_source=chatgpt.com "Module ngx_http_upstream_module"
[4]: https://nginx.org/en/docs/stream/ngx_stream_proxy_module.html?utm_source=chatgpt.com "Module ngx_stream_proxy_module"
[5]: https://hypercorn.readthedocs.io/en/latest/how_to_guides/configuring.html "Configuring — Hypercorn 0.17.3 documentation"
[6]: https://hypercorn.readthedocs.io/en/latest/how_to_guides/proxy_fix.html "Fixing proxy headers — Hypercorn 0.17.3 documentation"
[7]: https://starlette.dev/middleware/?utm_source=chatgpt.com "Middleware"
[8]: https://serverfault.com/questions/820539/how-to-proxy-multiple-tcp-streams-on-one-port-with-nginx?utm_source=chatgpt.com "How to proxy multiple tcp streams on one port with nginx"



# Extended feature set #

Absolutely—here’s a tight, production‑ready “drop‑in pack” you can paste into your repo/host to cover (1) abuse‑control at the edge and in‑app, and (2) a Certbot **deploy hook** so certificates renew hands‑free and services reload cleanly. I’ve kept it HTTP/3‑friendly (NGINX QUIC + streaming‑safe proxy settings) and aligned with the Hypercorn/Starlette stack we’ve been using.

---

## 0) Assumptions (adjust names/paths as needed)

* Public hostname: `mcp.example.com`
* NGINX installed with HTTP/3 (QUIC) support; your **main `nginx.conf`** includes `include /etc/nginx/conf.d/*.conf;` inside the `http` block.
* Hypercorn serving your ASGI app on **localhost:8000**.
* Certs managed by **Certbot (webroot)** at `/var/www/certbot/` (created below).
* Separate access log for MCP so Fail2ban can watch it.
* We terminate TLS at NGINX. (If you also run Hypercorn with its own TLS/H3 for “direct mode,” the hook below restarts it to pick up renewed keys; Hypercorn’s H3/Alt‑Svc/DoS knobs referenced below for completeness. )

---

## 1) Edge abuse‑control (NGINX) — HTTP/3/H2 enabled, streaming‑safe, with basic throttling & UA gate

**File:** `/etc/nginx/conf.d/mcp.conf`

> This file is `http`‑context safe: it defines `map`/zones *and* the `server` blocks.

```nginx
# ---------- http context items (zones, maps) ----------
# Throttle per-IP to a sustainable baseline (tune to your traffic).
limit_req_zone $binary_remote_addr zone=mcp_req_zone:10m rate=10r/s;
limit_conn_zone $binary_remote_addr zone=mcp_conn_zone:10m;

# Basic UA gate. You can remove entries that you legitimately expect.
map $http_user_agent $bad_ua {
    default 0;
    "~*(curl|wget|okhttp|python-requests|aiohttp|libwww-perl|httpclient)" 1;
    "~*^$" 1;   # empty UA
}

# ---------- HTTPS (H2 + H3/QUIC) ----------
server {
    listen 443 ssl http2;
    listen 443 quic reuseport;
    server_name mcp.example.com;

    # Certbot-managed certs
    ssl_certificate     /etc/letsencrypt/live/mcp.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    # Advertise HTTP/3 to modern clients
    add_header Alt-Svc 'h3=":443"; ma=86400' always;

    # OCSP stapling (optional, speeds first handshake)
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/letsencrypt/live/mcp.example.com/chain.pem;

    # Dedicated logs for MCP; Fail2ban will tail access log
    access_log /var/log/nginx/mcp_access.log main;
    error_log  /var/log/nginx/mcp_error.log warn;

    # ACME HTTP-01 challenge passthrough
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/certbot;
        default_type "text/plain";
        auth_basic off;
        allow all;
        try_files $uri =404;
    }

    # 403 very early for empty/suspect UA (lightweight abuse gate)
    if ($bad_ua) { return 403; }

    # Main upstream to Hypercorn (streaming-safe)
    location / {
        # Edge throttles
        limit_req  zone=mcp_req_zone  burst=50 nodelay;
        limit_conn mcp_conn_zone 20;

        # Streaming- and SSE-friendly
        proxy_buffering off;
        proxy_request_buffering off;

        # Long-lived reads for token/SSE streams
        proxy_read_timeout 3600s;
        proxy_send_timeout 60s;

        # Correct proxy headers
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Request-ID $request_id;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_pass http://127.0.0.1:8000;
    }

    # Human-friendly error pages (optional)
    error_page 403 /__errors/403.html;
    error_page 429 /__errors/429.html;
    location /__errors/ { internal; root /usr/share/nginx/html; }
}

# ---------- HTTP : redirect to HTTPS, but still serve ACME ----------
server {
    listen 80;
    server_name mcp.example.com;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/certbot;
        default_type "text/plain";
        auth_basic off;
        allow all;
        try_files $uri =404;
    }

    location / { return 301 https://$host$request_uri; }
}
```

**Why these bits?**

* `limit_req` + `limit_conn` gives a fair-share baseline and blunts bursts before they hit your app.
* `proxy_buffering off` & long `proxy_read_timeout` keep model/SSE streams flowing.
* `Alt‑Svc` advertises H3; your site will often negotiate H2 first then switch to H3 on the second request. (When your app also serves H3 directly via Hypercorn, prefer a single Alt‑Svc point of truth at the edge.) 

> **Hypercorn note:** If you ever front Hypercorn directly (no NGINX), ensure `alt_svc_headers`, `keep_alive_timeout`, and `server_names` are set in `hypercorn.toml` to advertise H3, guard against idle‑socket DoS, and pin allowed Host headers. (See §4 for a reference snippet.) 

---

## 2) Abuse escalation (Fail2ban) — ban repeat offenders across TCP/UDP

### 2.1 Filter (match 401/403/429 bursts)

**File:** `/etc/fail2ban/filter.d/nginx-mcp-abuse.conf`

```ini
[Definition]
# Very simple matcher: 10+ auth/forbidden/ratelimited hits in a short window → ban.
failregex = ^<HOST> - .* "(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD) .*" (401|403|429) .*
ignoreregex =
```

### 2.2 Jail (ban both TCP+UDP on 80/443)

**File:** `/etc/fail2ban/jail.d/nginx-mcp-abuse.local`

```ini
[nginx-mcp-abuse]
enabled   = true
filter    = nginx-mcp-abuse
logpath   = /var/log/nginx/mcp_access.log
backend   = auto
# "all" catches TCP+UDP so H3/QUIC (udp/443) offenders get blocked as well.
action    = iptables-multiport[name=nginx-mcp-abuse, port="80,443", protocol=all]
maxretry  = 10          # tune
findtime  = 120         # seconds
bantime   = 3600        # seconds
```

Restart Fail2ban to pick it up:

```bash
sudo systemctl restart fail2ban
sudo fail2ban-client status nginx-mcp-abuse
```

---

## 3) In‑app guardrails (Starlette/FastAPI) — Trusted hosts + light per‑IP token‑bucket

Even with edge controls, keep a **cheap, in‑process backstop**. This pure‑ASGI middleware adds a small token‑bucket per client IP and returns **429** when exceeded. Add **TrustedHostMiddleware** to reject unexpected Host headers.

**File:** `app/middleware/rate_limit.py`

```python
import time
from collections import defaultdict
from typing import Callable, Optional
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import JSONResponse

class _Bucket:
    __slots__ = ("rate", "capacity", "tokens", "ts")
    def __init__(self, rate: float, capacity: int) -> None:
        self.rate = rate; self.capacity = capacity
        self.tokens = capacity; self.ts = time.monotonic()
    def allow(self, cost: int = 1) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.ts) * self.rate)
        self.ts = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False

class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, rate: float = 10.0, capacity: int = 40,
                 key: Optional[Callable[[Scope], str]] = None) -> None:
        self.app = app
        self.rate = rate; self.capacity = capacity
        self.keyf = key or (lambda s: (s.get("client") or ("0.0.0.0", 0))[0])
        self._buckets = defaultdict(lambda: _Bucket(rate, capacity))

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":  # don’t gate websockets here
            return await self.app(scope, receive, send)
        if not self._buckets[self.keyf(scope)].allow():
            return await JSONResponse({"detail": "rate_limited"}, status_code=429)(scope, receive, send)
        return await self.app(scope, receive, send)
```

**Wire‑up in your app factory:**

```python
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

app.add_middleware(TrustedHostMiddleware, allowed_hosts=["mcp.example.com"])
app.add_middleware(RateLimitMiddleware, rate=10.0, capacity=40)
```

* `TrustedHostMiddleware` rejects invalid `Host` (defends against DNS‑rebinding when your app is reachable directly). 
* In‑process rate limiting is deliberately simple; edge controls and Fail2ban do the heavy lifting. (Keep this light to avoid per‑request overhead.) 

---

## 4) (Optional) Hypercorn hardening crib (if you later serve direct TLS/H3)

**File:** `hypercorn.toml`
*(Only needed when Hypercorn terminates TLS/H3 itself.)*

```toml
bind = ["0.0.0.0:443"]
quic_bind = ["0.0.0.0:443"]          # enable H3/QUIC at origin
certfile = "/etc/ssl/live/mcp.example.com/fullchain.pem"
keyfile  = "/etc/ssl/live/mcp.example.com/privkey.pem"

alpn_protocols = ["h2", "http/1.1"]  # TLS ALPN for H2
alt_svc_headers = ["h3=\":443\"; ma=86400"]

# Abuse/DoS hygiene
server_names = ["mcp.example.com"]   # mitigates DNS-rebinding
keep_alive_timeout = 5
read_timeout = 60
h2_max_concurrent_streams = 100
websocket_max_message_size = 16777216

loglevel = "info"
accesslog = "-"
errorlog = "-"
workers = 2
```

These knobs are all first‑class Hypercorn settings (H3 via `quic_bind` + Alt‑Svc, `server_names` safety, timeouts, H2 concurrency) and map cleanly to the abuse‑control goals. 

---

## 5) Certbot ACME (webroot) + deploy hook (reload NGINX; restart Hypercorn if it terminates TLS)

### 5.1 One‑time setup

```bash
sudo mkdir -p /var/www/certbot
sudo chown -R www-data:www-data /var/www/certbot

# First cert issue (webroot):
sudo certbot certonly --webroot -w /var/www/certbot -d mcp.example.com --agree-tos -m you@example.com --no-eff-email
```

### 5.2 Deploy hook (fires after renewals)

**File:** `/etc/letsencrypt/renewal-hooks/deploy/10-reload-mcp.sh`

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

DOMAIN="mcp.example.com"
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"
NGINX="/usr/sbin/nginx"
SYSTEMCTL="/bin/systemctl"

echo "[deploy-hook] Renewed cert for ${DOMAIN} — reloading services…"

# 1) Ensure new cert/key exist
test -s "${CERT_DIR}/fullchain.pem" && test -s "${CERT_DIR}/privkey.pem"

# 2) Validate NGINX config then reload to pick up new certs
${NGINX} -t && ${NGINX} -s reload

# 3) If Hypercorn ALSO terminates TLS/H3, restart it to reload keys
if ${SYSTEMCTL} is-active --quiet hypercorn.service; then
  ${SYSTEMCTL} restart hypercorn.service
fi

# 4) (Optional) Warm OCSP stapling cache
if command -v openssl >/dev/null; then
  timeout 10 openssl s_client -servername "${DOMAIN}" -connect "${DOMAIN}:443" -status </dev/null | grep -A1 "OCSP response" || true
fi

echo "[deploy-hook] Done."
```

Make it executable:

```bash
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/10-reload-mcp.sh
```

**Why a deploy hook?** Certbot writes renewed keys atomically; services won’t pick them up until they reload. This hook validates `nginx.conf` and sends a zero‑downtime **reload**. If Hypercorn terminates TLS/H3, it’s safer to **restart** that unit to refresh the Python TLS context. (Hypercorn’s graceful‑shutdown API exists, but in systemd flows the unit restart is simplest and reliable.) 

---

## 6) Quick verification checklist

* **HTTP/3 working:**
  `curl --http3-only -I https://mcp.example.com/` should return headers with `Alt-Svc` previously advertised; your browser DevTools “Protocol” should show `h3` after an initial load. *(H3 discovery relies on Alt‑Svc; many clients connect over H2 first, then switch.)* 
* **Streaming intact:** Tail the app while streaming tokens; NGINX proxy buffering is **off**, and `proxy_read_timeout` is generous.
* **Abuse controls:**

  * Hammer from one IP → you should see **429** (NGINX) or Fail2ban ban the IP after repeated 401/403/429 in the MCP access log.
  * Try an empty user‑agent → **403**.
* **TrustedHost:** Hitting the app via raw IP (bypassing NGINX) should be rejected by `TrustedHostMiddleware`. 

---

## 7) Where this ties back to your stack

* **Hypercorn** remains your preferred ASGI server; if you decide to expose it directly with H3, the TOML snippet in §4 gives you the exact knobs (Alt‑Svc, QUIC bind, timeouts, `server_names`) for robust streaming. 
* **Starlette/FastAPI**: the `TrustedHostMiddleware` + minimalist rate‑limit middleware are zero‑dependency and align with Starlette’s recommended patterns. If you later want Redis‑backed quotas or user‑level limits, we can swap the in‑memory bucket for a pluggable backend without changing call sites. 

---

### Want me to wrap these into repo‑style diffs (paths under `infra/` and `app/` with a small README), or generate systemd unit examples (`hypercorn.service`, `fail2ban` unit checks)? I can produce those directly next.


# Production Grade Implementation #

Absolutely—let’s lock in an **NGINX ⇄ Hypercorn** deployment that’s production‑grade for a personal‑scale MCP server, with **repo‑style diffs**, **systemd units**, **abuse/rate‑control**, and a **Certbot ACME deploy hook**. I’ll wire this plan directly to the structure that’s already present in your repo so you can drop it in and go.

Below you’ll find:

1. **What’s already in your repo to leverage** (brief orientation, with citations).
2. **Architecture** (ports, paths, TLS termination, streaming, WebSockets, H/3).
3. **Repo‑style diffs** adding ASGI entrypoints and wiring to your existing MCP app factory.
4. **Hypercorn config** (behind NGINX).
5. **NGINX site config** (HTTP/3 + SSE/WS streaming + abuse/rate control).
6. **systemd units** (Hypercorn service + timer for auto‑reload on code changes if desired).
7. **Certbot deploy hook** (safe NGINX reload; optional Hypercorn kick).
8. **Operational notes** (health, metrics, backpressure, timeouts, alt‑svc, etc.).

---

## 1) What’s already in your repo to leverage

Your repository already contains:

* A FastAPI application with **health, capability, and SSE** endpoints (`/readyz`, `/capz`, `/sse`) and middleware that explicitly disables NGINX buffering for streaming responses. That’s perfect for ChatGPT-side streaming stability.
* A complete **MCP HTTP app factory**: `codeintel_rev.mcp_server.server.build_http_app(capabilities) -> ASGIApp`. We’ll reuse this for the `/mcp` interface, gated by runtime capability detection. 
* A capability model **`Capabilities`** with helpers like `model_dump()`/`stamp()` and context auto‑discovery via `Capabilities.from_context(ApplicationContext)`. We’ll use this to build the MCP app with the correct feature gates at boot. 
* A first‑class **startup/lifespan** for initializing your `ApplicationContext`, readiness probe, optional FAISS/XTR warmups, and telemetry. We’ll keep that intact for `/api`.

> Why this matters: it lets us mount a **single Hypercorn process** exposing both your **FastAPI app** and **MCP app** cleanly, and front it with **NGINX** that terminates TLS + HTTP/3 and handles rate limiting, buffering controls, and ACME.

---

## 2) Target architecture

```
[Client (ChatGPT MCP / Browser)]
          |
          | QUIC + TLS (HTTP/3)  + HTTP/2/1.1 fallback
          v
      [NGINX 1.28+]
          - TLS termination (Certbot-managed)
          - HTTP/3 (quic) enabled + strict security headers
          - Alt-Svc advertisement
          - ACME /.well-known served from webroot
          - SSE/WS passthrough: proxy_buffering off, upgrade headers
          - Abuse controls: limit_req, limit_conn, big headers/timeout guard
          v (loopback)
   http://127.0.0.1:8080
          |
       [Hypercorn]
          - ASGI composite:
              /api -> your FastAPI app (health, metrics, SSE demo)
              /mcp -> FastMCP http app via build_http_app(capabilities)
```

Why Hypercorn: you prefer it (and it’s fully ASGI). We’re running it **behind NGINX** to maximize stability and leverage HTTP/3 at the edge. (Hypercorn’s ASGI/server features are well‑suited for FastAPI/Starlette; see docs you attached. )

---

## 3) Repo‑style diffs — ASGI entrypoints & composition

We add a tiny **ASGI “composition” module** that mounts **your existing FastAPI app** and **the MCP app** built from runtime capabilities into one Starlette app. We also expose discrete entrypoints for each if you choose to run them separately.

> Paths assume repo root is the Python package root (as in `codeintel_rev/...`). Adjust if your layout differs.

### 3.1 `codeintel_rev/mcp_server/asgi.py` — ASGI for the MCP server

```diff
diff --git a/codeintel_rev/mcp_server/asgi.py b/codeintel_rev/mcp_server/asgi.py
new file mode 100644
index 0000000..b1c2d3e
--- /dev/null
+++ b/codeintel_rev/mcp_server/asgi.py
@@
+"""
+ASGI entrypoint for the MCP HTTP server, using capability-gated tool registration.
+"""
+from __future__ import annotations
+
+from codeintel_rev.app.config_context import ApplicationContext
+from codeintel_rev.app.capabilities import Capabilities
+from codeintel_rev.mcp_server.server import build_http_app
+
+# Build a runtime context and capability snapshot for tool gating.
+_context = ApplicationContext.create()
+_capabilities = Capabilities.from_context(_context)
+
+# The ASGI application served at /mcp (when mounted) or as a standalone app.
+app = build_http_app(_capabilities)
```

(We’re directly using your MCP factory; see `build_http_app` docs. )

### 3.2 `codeintel_rev/app/asgi.py` — ASGI for your existing FastAPI app

Your FastAPI app lives in `codeintel_rev.app.main` and exposes `/readyz`, `/capz`, `/sse`, `/metrics`, etc. We just re‑export it as a clean ASGI entrypoint:

```diff
diff --git a/codeintel_rev/app/asgi.py b/codeintel_rev/app/asgi.py
new file mode 100644
index 0000000..c1d2e3f
--- /dev/null
+++ b/codeintel_rev/app/asgi.py
@@
+"""
+ASGI entrypoint for the core FastAPI application (health, metrics, SSE, etc.).
+"""
+from __future__ import annotations
+
+from codeintel_rev.app.main import app  # FastAPI instance with lifespan & routes
+
+# Nothing else to do: app includes readiness, capabilities, SSE, metrics.
+# Notably, it sets 'X-Accel-Buffering: no' for streaming stability behind NGINX.
```

(FastAPI app & `/capz` + SSE exist here. )

### 3.3 `codeintel_rev/asgi/app.py` — Composite ASGI (mount `/api` + `/mcp`)

```diff
diff --git a/codeintel_rev/asgi/app.py b/codeintel_rev/asgi/app.py
new file mode 100644
index 0000000..d1e2f3a
--- /dev/null
+++ b/codeintel_rev/asgi/app.py
@@
+"""
+Composite ASGI app that exposes:
+  - /api -> FastAPI app (health, metrics, SSE)
+  - /mcp -> FastMCP HTTP app
+This lets a single Hypercorn worker serve both surfaces behind NGINX.
+"""
+from __future__ import annotations
+
+from starlette.applications import Starlette
+from starlette.routing import Mount
+from starlette.responses import PlainTextResponse
+
+from codeintel_rev.app.asgi import app as api_app
+from codeintel_rev.mcp_server.asgi import app as mcp_app
+
+routes = [
+    Mount("/api", app=api_app),
+    Mount("/mcp", app=mcp_app),
+]
+
+app = Starlette(routes=routes)
+
+@app.route("/")
+async def root(_):
+    # Simple landing to show available mounts
+    return PlainTextResponse("OK: /api (FastAPI), /mcp (MCP)", status_code=200)
```

> **Why mount**: gives you a single port/process, clear separation of concerns, and straightforward NGINX proxy rules. Starlette/FastAPI interop is native. (FastAPI is ASGI; Starlette is the base toolkit. )

---

## 4) Hypercorn configuration (behind NGINX)

We’ll bind Hypercorn **only on loopback** and **without TLS** (TLS ends at NGINX). We’ll enable HTTP/1.1 + h2 on the backend (NGINX upstream typically uses h1; either works). Here is a drop‑in config:

```diff
diff --git a/deploy/hypercorn/hypercorn.toml b/deploy/hypercorn/hypercorn.toml
new file mode 100644
index 0000000..aabbcc1
--- /dev/null
+++ b/deploy/hypercorn/hypercorn.toml
@@
+bind = ["127.0.0.1:8080"]
+# Use workers appropriate to your cores (for personal scale, 1-2 is fine)
+workers = 1
+worker_class = "asyncio"
+
+# Tuning for streaming/SSE/WebSocket stability
+keep_alive_timeout = 20
+graceful_timeout = 30
+max_requests = 0
+accesslog = "-"
+errorlog  = "-"
+
+# If you ever want Hypercorn to terminate TLS/H3 directly (no NGINX):
+# quic_bind = ["0.0.0.0:443"]
+# certfile  = "/etc/letsencrypt/live/your.domain/fullchain.pem"
+# keyfile   = "/etc/letsencrypt/live/your.domain/privkey.pem"
+# (But in this guide we terminate TLS/H3 at NGINX for stability.)
```

(Hypercorn is your preferred server; these settings are standard for FastAPI/Starlette. )

---

## 5) NGINX site (HTTP/3 + abuse control + SSE/WS)

Create a site config at `/etc/nginx/sites-available/mcp.conf` and symlink to `sites-enabled`. This config:

* Terminates TLS (managed by Certbot).
* Enables **HTTP/3 (QUIC)** and advertises **Alt‑Svc**.
* Proxies **`/api`** and **`/mcp`** to Hypercorn at `127.0.0.1:8080`.
* Turns **buffering off** and extends timeouts for **SSE**; properly handles **WebSockets**.
* Adds **abuse controls**: request rate, concurrent connection limits, header size check, minimal UA allow‑list example.
* Serves **ACME challenges** from a shared webroot.

```nginx
# /etc/nginx/sites-available/mcp.conf
# NGINX 1.28+ with HTTP/3 support.

# ---- Abuse control zones (simple per-IP rate & conn limits) ----
limit_req_zone $binary_remote_addr zone=mcp_perip_rps:10m rate=20r/s;
limit_conn_zone $binary_remote_addr zone=mcp_perip_conn:10m;

map $http_upgrade $connection_upgrade {
  default upgrade;
  ''      close;
}

# Optional: very strict minimal UA allowlist (comment out if not desired)
# map $http_user_agent $ua_bad {
#   default 0; ~*curl|python-requests|wget 1;
# }

server {
  listen 80;
  listen [::]:80;
  server_name your.domain.tld;

  # ACME challenge (webroot)
  location ^~ /.well-known/acme-challenge/ {
    root /var/www/certbot;
    default_type "text/plain";
    access_log off;
    log_not_found off;
  }

  # Redirect everything else to HTTPS
  location / {
    return 301 https://$host$request_uri;
  }
}

server {
  # HTTP/3 + HTTP/2/1.1
  listen 443 ssl http2 reuseport;
  listen [::]:443 ssl http2 reuseport;
  listen 443 quic reuseport;
  listen [::]:443 quic reuseport;
  server_name your.domain.tld;

  # TLS (Certbot populates these)
  ssl_certificate     /etc/letsencrypt/live/your.domain.tld/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/your.domain.tld/privkey.pem;
  ssl_protocols       TLSv1.2 TLSv1.3;
  ssl_ciphers         HIGH:!aNULL:!MD5;

  # Advertise H3 (QUIC)
  add_header Alt-Svc 'h3=":443"; ma=86400' always;

  # Security headers (safe for APIs)
  add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
  add_header X-Frame-Options "DENY" always;
  add_header X-Content-Type-Options "nosniff" always;
  add_header Referrer-Policy "no-referrer" always;
  add_header Permissions-Policy "geolocation=()" always;

  # ---- Abuse controls ----
  # if ($ua_bad) { return 403; }  # Enable if using UA filter above
  limit_req zone=mcp_perip_rps burst=20 nodelay;
  limit_conn mcp_perip_conn 20;

  # Shared backend settings
  set $backend http://127.0.0.1:8080;

  # Common proxy config - h1 upstream is fine; h2 upstream optional
  proxy_http_version 1.1;
  proxy_set_header Host              $host;
  proxy_set_header X-Real-IP         $remote_addr;
  proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;

  # --- /api (FastAPI app) ---
  location /api/ {
    # SSE-friendly: disable buffering & extend timeouts
    proxy_buffering off;
    proxy_read_timeout  3600s;
    proxy_send_timeout  3600s;

    # Large headers/body guard (tune for your needs)
    client_max_body_size 20m;
    client_body_buffer_size 1m;

    # Pass to Hypercorn
    proxy_pass $backend;
  }

  # --- /mcp (FastMCP HTTP app) ---
  location /mcp/ {
    # Support WebSockets (if any) & SSE
    proxy_buffering off;
    proxy_read_timeout  3600s;
    proxy_send_timeout  3600s;

    proxy_set_header Upgrade    $http_upgrade;
    proxy_set_header Connection $connection_upgrade;

    proxy_pass $backend;
  }

  # Prometheus metrics passthrough if you want external scraping:
  location = /api/metrics {
    proxy_buffering off;
    proxy_read_timeout 60s;
    proxy_pass $backend;
  }

  # ACME challenge (also reachable over HTTPS)
  location ^~ /.well-known/acme-challenge/ {
    root /var/www/certbot;
    default_type "text/plain";
    access_log off;
    log_not_found off;
  }

  # Optional: drop overly large request headers to prevent abuse
  large_client_header_buffers 4 8k;
}
```

> FastAPI/Starlette + SSE: You already set the `X-Accel-Buffering: no` header in app code, which complements `proxy_buffering off` in NGINX for low‑latency streams. 

---

## 6) systemd units

### 6.1 Hypercorn service

```diff
diff --git a/deploy/systemd/codeintel-mcp.service b/deploy/systemd/codeintel-mcp.service
new file mode 100644
index 0000000..e1f2a3b
--- /dev/null
+++ b/deploy/systemd/codeintel-mcp.service
@@
+[Unit]
+Description=CodeIntel MCP (Hypercorn ASGI)
+After=network.target
+Wants=network-online.target
+
+[Service]
+Type=simple
+User=codeintel
+Group=codeintel
+WorkingDirectory=/srv/codeintel
+Environment="PYTHONUNBUFFERED=1"
+EnvironmentFile=-/etc/codeintel_rev.env
+ExecStart=/usr/bin/hypercorn --config /srv/codeintel/deploy/hypercorn/hypercorn.toml codeintel_rev.asgi.app:app
+Restart=always
+RestartSec=5
+NoNewPrivileges=true
+PrivateTmp=true
+ProtectSystem=strict
+ProtectHome=true
+LockPersonality=true
+MemoryMax=1G
+TasksMax=512
+LimitNOFILE=131072
+
+[Install]
+WantedBy=multi-user.target
```

> If you prefer to run only one surface, swap `codeintel_rev.asgi.app:app` with `codeintel_rev.app.asgi:app` (API only) or `codeintel_rev.mcp_server.asgi:app` (MCP only).

### 6.2 Optional: automatic reload on package changes (dev only)

A simple watchdog service/timer pair can send `systemctl restart` on file changes. (Omitted here to keep production stable; ask if you want it.)

---

## 7) Certbot ACME deploy hook

Create a **deploy hook** to safely reload NGINX after renewal. If you terminate TLS only at NGINX, Hypercorn doesn’t need reloading.

```diff
diff --git a/deploy/certbot/deploy-reload-nginx.sh b/deploy/certbot/deploy-reload-nginx.sh
new file mode 100755
index 0000000..f1a2b3c
--- /dev/null
+++ b/deploy/certbot/deploy-reload-nginx.sh
@@
+#!/usr/bin/env bash
+set -euo pipefail
+
+logger -t certbot "Deploy hook triggered: reloading nginx"
+if systemctl is-active --quiet nginx; then
+  nginx -t && systemctl reload nginx
+else
+  logger -t certbot "nginx inactive; skipping reload"
+fi
+
+# If you were terminating TLS in Hypercorn as well (not recommended here),
+# you would also restart Hypercorn:
+# systemctl restart codeintel-mcp.service
```

Install the hook in Certbot’s deploy‑hooks directory:

```
sudo install -d -o root -g root -m 0755 /etc/letsencrypt/renewal-hooks/deploy
sudo install -o root -g root -m 0755 deploy/certbot/deploy-reload-nginx.sh \
  /etc/letsencrypt/renewal-hooks/deploy/99-reload-nginx.sh
```

ACME webroot is `/var/www/certbot` as referenced in the NGINX config.

---

## 8) Abuse‑control (NGINX) — snippets you can include

If you prefer separate include files, create two re‑usable snippets and include them in the `server` block.

```diff
diff --git a/deploy/nginx/snippets/abuse_control.conf b/deploy/nginx/snippets/abuse_control.conf
new file mode 100644
index 0000000..aa11bb2
--- /dev/null
+++ b/deploy/nginx/snippets/abuse_control.conf
@@
+# Rate-limit and connection-limit (per IP)
+limit_req_zone $binary_remote_addr zone=mcp_perip_rps:10m rate=20r/s;
+limit_conn_zone $binary_remote_addr zone=mcp_perip_conn:10m;
+
+# Optional: UA filter (comment out to disable)
+# map $http_user_agent $ua_bad {
+#   default 0; ~*curl|python-requests|wget 1;
+# }
```

```diff
diff --git a/deploy/nginx/snippets/abuse_enforce.conf b/deploy/nginx/snippets/abuse_enforce.conf
new file mode 100644
index 0000000..bb22cc3
--- /dev/null
+++ b/deploy/nginx/snippets/abuse_enforce.conf
@@
+# Enforce in server {} after ssl setup
+# if ($ua_bad) { return 403; }
+limit_req zone=mcp_perip_rps burst=20 nodelay;
+limit_conn mcp_perip_conn 20;
+large_client_header_buffers 4 8k;
```

Then in your site config, add:

```
include /etc/nginx/snippets/abuse_enforce.conf;
```

(Place the `zone` declarations once globally or in `http {}` via `abuse_control.conf`.)

---

## 9) How ChatGPT gains a stable experience

* **Streaming stability (SSE/WS):** You’ve already implemented app‑side streaming and buffering controls (FastAPI/Starlette + `X-Accel-Buffering: no`), and NGINX explicitly disables proxy buffering for `/api` and `/mcp`. That combination minimizes tail latency and dropped connections. 
* **Capability gating:** MCP tools register only if the capability snapshot says the underlying indexes/clients exist—this prevents tool “holes” and gives a consistent UX as you change local resources. 
* **Health + readiness:** `/api/readyz` lets ChatGPT retry only when you’re up; `/api/capz` provides a feature fingerprint (hash via `stamp()`). 
* **Time‑outs & keep‑alives:** NGINX timeouts are long for streaming; Hypercorn keep‑alive is moderate. This reduces “random” breaks during long MCP streams.

---

## 10) Start‑to‑finish commands

```bash
# 1) Create service account & directories
sudo useradd -r -s /usr/sbin/nologin codeintel || true
sudo mkdir -p /srv/codeintel /srv/codeintel/deploy/{hypercorn,certbot}
sudo chown -R codeintel:codeintel /srv/codeintel

# 2) Copy repo to /srv/codeintel (or deploy via CI)
#    Ensure codeintel_rev is importable (venv/poetry/pip).

# 3) Hypercorn config
sudo install -o codeintel -g codeintel -m 0644 deploy/hypercorn/hypercorn.toml /srv/codeintel/deploy/hypercorn/hypercorn.toml

# 4) systemd
sudo install -o root -g root -m 0644 deploy/systemd/codeintel-mcp.service /etc/systemd/system/codeintel-mcp.service
sudo systemctl daemon-reload
sudo systemctl enable --now codeintel-mcp.service

# 5) NGINX + Certbot
sudo mkdir -p /var/www/certbot
sudo chown -R www-data:www-data /var/www/certbot
sudo ln -s /etc/nginx/sites-available/mcp.conf /etc/nginx/sites-enabled/mcp.conf
sudo nginx -t && sudo systemctl reload nginx

# Initial cert (webroot)
sudo certbot certonly --webroot -w /var/www/certbot -d your.domain.tld --agree-tos -m you@example.com --no-eff-email
# Install deploy hook
sudo install -o root -g root -m 0755 deploy/certbot/deploy-reload-nginx.sh /etc/letsencrypt/renewal-hooks/deploy/99-reload-nginx.sh

# 6) Verify
curl -I https://your.domain.tld/api/readyz
curl -I --http3 https://your.domain.tld/api/readyz   # test H3 if your curl supports it
```

---

## 11) Notes, tradeoffs, and why this design is “best of both”

* **HTTP/3 “end‑to‑edge”:** NGINX terminates QUIC/TLS at the edge. Upstream to Hypercorn is local h1/h2—this is the standard and most stable approach today.
* **All‑Python option (Hypercorn QUIC):** You can terminate H3 in Hypercorn (see commented `quic_bind`/`certfile`/`keyfile` settings), but you’d then lose NGINX’s mature rate limiting, buffering, and ACME convenience. For personal scale, the **NGINX + Hypercorn split is safer**.
* **SSE/WS correctness:** We combined **app‑level buffering disable** (already in your code) with **NGINX `proxy_buffering off`** per path. This dual approach is the reliably low‑latency recipe for long‑lived streams. Your app’s `/sse` route is already implemented using Starlette StreamingResponse. 
* **Capabilities snapshot:** We compute once at MCP app construction using your existing `ApplicationContext.create()` → `Capabilities.from_context()`. Tools register only if their pre‑reqs exist; that keeps user experience consistent even if local indexes aren’t present. 

---

## 12) Deep links to your code elements used above

* MCP app factory: **`build_http_app(capabilities)`** in `codeintel_rev.mcp_server.server`. 
* FastAPI app + `/capz` + SSE demo + readiness lifecycle and context initialization.
* Capabilities model + snapshot/stamp helpers. 
* Readiness probe and checks used by startup/health. 
* Starlette/FastAPI/Hypercorn/httpx you referenced in your attachments.

---

### If you want me to also add:

* A **Makefile** or **poetry** section (install + run targets),
* A **watchdog dev reloader** unit/timer,
* Or **mount rules** to split `/mcp` and `/api` onto different upstream worker pools,

…I can include repo‑style diffs for those too.
