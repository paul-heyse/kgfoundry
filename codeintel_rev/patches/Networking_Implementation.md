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
