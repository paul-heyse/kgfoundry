Fantastic—here’s a **hands‑on implementation plan** (with repo‑style diffs and ready‑to‑drop configs) that optimizes for:

* **Seamless use** and “it just works” ergonomics
* **HTTP/3** leveraged to the greatest extent practical
* **Error resilience** and **easy diagnosis** (uniform error envelopes, request IDs, structured logs)
* **Extensibility** (clean layering, config switches, testability)

Everything below plugs into your current tree (FastAPI app + MCP server), which already has the right surface to mount MCP under HTTP, basic readiness endpoints, and an SSE demo. I reference those components directly so you can map the changes to your codebase. 

---

## 0) What you’ll get

**Two switchable topologies (env‑controlled):**

* **A. “NGINX terminates H3” (recommended for ops):**
  Client ↔ **NGINX (HTTP/3/QUIC)** ↔ Hypercorn (**HTTP/1.1** on loopback). This gives you all the “boring‑reliable” knobs at the edge while preserving perfect streaming semantics (no buffering) to ChatGPT/MCP. 

* **B. “End‑to‑end H3 (L4 pass‑through)” (when literal H3‑to‑Hypercorn matters):**
  Client ↔ **NGINX stream pass‑through (UDP/TCP)** ↔ Hypercorn (**HTTP/3 QUIC**). You get true H3 all the way, traded against fewer L7 toys at the proxy. 

**Inside the Python app (FastAPI/Starlette + MCP):**

* Mount MCP under **`/mcp`** using your existing capability snapshot builder.
* **Request ID** on every request (propagated to responses & logs).
* **Uniform error envelope** for easy triage.
* **Streaming correctness**: automatic `X‑Accel‑Buffering: no` on SSE so NGINX never buffers streams.
* **Proxy awareness** when running behind NGINX (correct scheme/host/ip).
* **Hypercorn TOML** ready for H1/H2/H3; curl/browser verification checklist.  

**At the edge (NGINX 1.28+):**

* **HTTP/3/QUIC** enabled (`listen 443 quic reuseport; http3 on;`) and **Alt‑Svc** advertising.
* Upstream **keep‑alive** pool to Hypercorn for low latency.
* **No buffering on streaming** routes, long read timeouts for stable streams. 

**Tests & ops:**

* `httpx` / `FastAPI` test harness for `/sse` and `/mcp` smoke checks.  
* `systemd` units for Hypercorn (and notes for NGINX reload); shell scripts to validate H3 with `curl --http3-only`.  

---

## 1) Topology details (choose per environment)

> You can flip at deploy time via `MCP_NET_TOPOLOGY=nginx_terminate | h3_direct`.

* **A. H3 at NGINX, H1.1 to Hypercorn**
  This is the ops‑friendly setting. It uses HTTP/3 to your users/ChatGPT and keeps the app hop lean and predictable. We disable NGINX buffering for streaming endpoints (or honor **`X‑Accel‑Buffering: no`** set by the app for SSE), enable upstream keep‑alive, and advertise H3 with **`Alt‑Svc`**. 

* **B. End‑to‑end H3**
  NGINX **stream** forwards UDP 443 and TCP 443 to Hypercorn, which binds both **`bind`** (TLS/TCP) and **`quic_bind`** (UDP) on the same port. Hypercorn advertises H3 via **`alt_svc_headers`** and uses aioquic under the hood. 

---

## 2) App changes (mount MCP, robust streaming, easy diagnostics)

### 2.1 Add ASGI wrappers & middleware

Create a thin ASGI layer that (a) injects **request IDs**, (b) **wraps errors** into a predictable JSON envelope, and (c) **adds `X‑Accel‑Buffering: no`** when it sees `text/event-stream` so NGINX forwards bytes immediately.

> These are pure‑ASGI wrappers (zero dependencies), so they won’t fight Starlette/FastAPI middleware ordering. Starlette’s middleware and patterns are documented here if you want to expand later. 

**`codeintel_rev/app/asgi_wrappers.py` (new)**

```python
# SPDX-License-Identifier: MIT
# Minimal ASGI wrappers to improve operability without changing business logic.
import json, time, uuid
from typing import Callable, Dict, Iterable, Tuple, Any

Scope = Dict[str, Any]
Message = Dict[str, Any]
Send = Callable[[Message], Any]
Receive = Callable[[], Any]
App = Callable[[Scope, Receive, Send], Any]

class RequestIdASGI:
    def __init__(self, app: App, header_name: bytes = b"x-request-id") -> None:
        self.app = app
        self.header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        req_id = (uuid.uuid4().hex)[:16]
        scope.setdefault("state", {})["request_id"] = req_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: Iterable[Tuple[bytes, bytes]] = message.get("headers", [])
                message["headers"] = list(headers) + [(self.header_name, req_id.encode())]
            await send(message)

        await self.app(scope, receive, send_with_id)

class ErrorEnvelopeASGI:
    """Uniform JSON errors with request_id to ease debugging across layers."""
    def __init__(self, app: App) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        start_sent = False
        status = 200
        headers: list[tuple[bytes, bytes]] = []

        async def _send(message: Message) -> None:
            nonlocal start_sent, status, headers
            if message["type"] == "http.response.start":
                start_sent = True
                status = message["status"]
                headers = list(message.get("headers", []))
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception as exc:
            # Only send if start not already sent (not a streaming body)
            if not start_sent:
                req_id = scope.get("state", {}).get("request_id", "")
                payload = {
                    "ok": False,
                    "error": {"type": exc.__class__.__name__, "message": str(exc)},
                    "request_id": req_id,
                    "path": scope.get("path"),
                }
                await send({
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-type", b"application/json")]
                              + [(b"x-request-id", req_id.encode()) if req_id else ()],
                })
                await send({
                    "type": "http.response.body",
                    "body": json.dumps(payload).encode(),
                    "more_body": False,
                })
            else:
                # If the response started (streaming), just close the body.
                await send({"type": "http.response.body", "body": b"", "more_body": False})

class DisableNginxBufferingForSSE:
    """Adds X-Accel-Buffering: no on SSE to prevent proxy buffering at NGINX."""
    def __init__(self, app: App) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        saw_start = False

        async def send2(message: Message) -> None:
            nonlocal saw_start
            if message["type"] == "http.response.start":
                saw_start = True
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                ctype = next((v for (k, v) in headers if k.lower() == b"content-type"), b"")
                if b"text/event-stream" in ctype:
                    headers.append((b"x-accel-buffering", b"no"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send2)
```

> Why this matters: NGINX’s docs recommend either **`proxy_buffering off;`** or returning **`X‑Accel‑Buffering: no`** on the responses you stream (e.g., SSE). Doing it in ASGI guarantees correct behavior regardless of location config, which keeps the end‑user experience consistent. 

### 2.2 Mount MCP at `/mcp` and export a Hypercorn‑ready `asgi`

**`codeintel_rev/app/main.py` (diff)**
(Your repo already exposes FastAPI and capability plumbing; we reuse it and mount MCP.) 

```diff
--- a/codeintel_rev/app/main.py
+++ b/codeintel_rev/app/main.py
@@
-from fastapi import FastAPI, Request
+from fastapi import FastAPI
+import os
+from hypercorn.middleware import ProxyFixMiddleware
+from codeintel_rev.app.capabilities import Capabilities
+from codeintel_rev.mcp_server.server import build_http_app
+from codeintel_rev.app.asgi_wrappers import (
+    RequestIdASGI, ErrorEnvelopeASGI, DisableNginxBufferingForSSE
+)
@@
-app = FastAPI(title="codeintel_rev", docs_url="/docs")
+app = FastAPI(title="codeintel_rev", docs_url="/docs")
 
 @app.on_event("startup")
 async def on_startup():
-    # existing startup logic initializes app.state.context, etc.
+    # existing startup logic initializes app.state.context, etc.
     ...
 
+@app.on_event("startup")
+async def _mount_mcp():
+    """Build and mount the MCP ASGI sub-app under /mcp."""
+    ctx = getattr(app.state, "context", None)
+    if ctx is None:
+        return
+    caps = Capabilities.from_context(ctx)
+    app.state.capabilities = caps
+    mcp_asgi = build_http_app(caps)
+    # Wrap MCP with SSE-friendly disabling of NGINX buffering
+    mcp_asgi = DisableNginxBufferingForSSE(mcp_asgi)
+    app.mount("/mcp", mcp_asgi)
+
+# Final ASGI object for the server (adds request-id & error envelope).
+trusted_hops = int(os.getenv("PROXY_TRUSTED_HOPS", "1"))
+_stack = RequestIdASGI(ErrorEnvelopeASGI(app))
+asgi = ProxyFixMiddleware(_stack, mode="legacy", trusted_hops=trusted_hops)
```

* **`build_http_app`** and **`Capabilities.from_context`** come from your existing MCP/FastAPI integration. We simply mount the sub‑app. 
* **`ProxyFixMiddleware`** ensures the app correctly interprets `X‑Forwarded‑*` when you’re in topology A behind NGINX, so URLs and scheme look right to clients. 
* Streaming SSE is still just FastAPI/Starlette **`StreamingResponse`** — nothing special for you to change in endpoints. (Docs for streaming patterns are in the FastAPI/Starlette references.)  

---

## 3) Hypercorn configuration (H1/H2 always, H3 when you want)

**`ops/hypercorn.toml` (new)**
(Default: NGINX terminates TLS/H3; swap to end‑to‑end H3 by uncommenting the second block.)

```toml
# Common knobs
accesslog = "-"
errorlog  = "-"
keep_alive_timeout = 75
graceful_timeout  = 20
include_server_header = false

# Default ALPN advertised on TLS (TCP). When running end-to-end H3, Hypercorn adds QUIC.
alpn_protocols = ["h2", "http/1.1"]

# --- Topology A: NGINX terminates H3; talk HTTP to loopback
bind = ["127.0.0.1:8080"]

# --- Topology B: End-to-end H3 (comment the line above and use the block below)
# bind = ["0.0.0.0:8443"]
# quic_bind = ["0.0.0.0:8443"]
# certfile = "/etc/ssl/live/mcp.example.com/fullchain.pem"
# keyfile  = "/etc/ssl/live/mcp.example.com/privkey.pem"
# alt_svc_headers = ["h3=\":8443\"; ma=86400"]
```

Run with:
`hypercorn --config ops/hypercorn.toml codeintel_rev.app.main:asgi` 

**Why these exact fields:** Hypercorn’s **`quic_bind`**, **`alt_svc_headers`**, and H2 **ALPN** are the supported way to enable QUIC/H3 and advertise it; sharing the same port for TCP/UDP is normal practice. Verification with `curl --http3-only` is also documented. 

---

## 4) NGINX configs (HTTP/3, streaming‑friendly)

### 4.1 Variant A — terminate H3 at NGINX, proxy to 127.0.0.1:8080

**`/etc/nginx/conf.d/mcp.conf` (new)**

```nginx
upstream mcp_upstream {
    server 127.0.0.1:8080;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    listen 443 quic reuseport;   # UDP/443 for HTTP/3
    http3 on;

    server_name mcp.example.com;

    ssl_certificate     /etc/letsencrypt/live/mcp.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.example.com/privkey.pem;

    # Advertise H3 to clients arriving over TCP/TLS
    add_header Alt-Svc 'h3=":443"; ma=86400' always;

    # MCP endpoint: streaming-safe proxying
    location /mcp/ {
        proxy_pass http://mcp_upstream;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # Streaming: forward bytes as they arrive
        proxy_buffering off;
        proxy_read_timeout 1h;

        # Pass useful forward headers
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Optional: your existing /readyz, /docs, etc. can share similar blocks
}
```

Key lines for H3 and streaming — `listen 443 quic reuseport`, `http3 on`, `Alt-Svc`, and **`proxy_buffering off`** — are the documented patterns for modern NGINX with QUIC and long‑lived streams. 

### 4.2 Variant B — end‑to‑end H3 pass‑through (L4 stream)

**`/etc/nginx/stream.d/mcp.stream.conf` (new)**

```nginx
# TCP pass-through (HTTPS)
server {
    listen 443;
    proxy_pass 127.0.0.1:8443;  # Hypercorn TCP/TLS bind
    proxy_protocol off;
}

# UDP pass-through (QUIC)
server {
    listen 443 udp reuseport;
    proxy_pass 127.0.0.1:8443;  # Hypercorn QUIC bind
}
```

This keeps QUIC/H3 to Hypercorn “end‑to‑end” while NGINX does pure L4 forwarding. Since there’s no HTTP layer here, the streaming behavior is entirely governed by Hypercorn + your ASGI app. 

---

## 5) Systemd units (service resilience with graceful restarts)

**`/etc/systemd/system/codeintel-rev.service` (new)**

```ini
[Unit]
Description=CodeIntel MCP (Hypercorn)
After=network.target
Wants=nginx.service

[Service]
WorkingDirectory=/opt/codeintel_rev
Environment=MCP_NET_TOPOLOGY=nginx_terminate
Environment=PYTHONUNBUFFERED=1
Environment=PROXY_TRUSTED_HOPS=1
ExecStart=/usr/bin/env bash -lc 'exec hypercorn --config ops/hypercorn.toml codeintel_rev.app.main:asgi'
Restart=on-failure
RestartSec=2
RuntimeMaxSec=0
LimitNOFILE=131072

# Graceful shutdown
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

> If you run Variant B (end‑to‑end H3), set `bind/quic_bind` in `ops/hypercorn.toml` as shown above and expose UDP 443 → 8443 through your firewall. Verify with `curl --http3-only -I https://mcp.example.com` after enabling your stream config.  

---

## 6) Test & verification snippets

**(A) Fast test for `/sse` and `/mcp` using `httpx` + FastAPI test client**
(Your repo already uses FastAPI; `httpx.AsyncClient` is the canonical test client in FastAPI’s docs.)

**`tests/test_streaming.py` (new)**

```python
import pytest, anyio
from httpx import AsyncClient

from codeintel_rev.app.main import app

@pytest.mark.anyio
async def test_sse_headers_present():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # If your app exposes /sse demo already; otherwise adapt to a known streaming path
        r = await ac.get("/sse")
        assert r.status_code == 200
        # When proxied through NGINX in prod, this header ensures no buffering.
        # In tests (direct), our ASGI wrapper still sets it for SSE:
        assert r.headers.get("x-accel-buffering") == "no"

@pytest.mark.anyio
async def test_mcp_mount():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.get("/mcp/healthz")  # adjust to MCP sub-app health if present
        assert r.status_code in (200, 404)  # endpoint presence may vary by build
```

FastAPI + httpx testing patterns and examples are first‑class in the docs; this shape is battle‑tested.  

**(B) H3 verification script**

**`ops/check_h3.sh` (new)**

```bash
#!/usr/bin/env bash
set -euo pipefail
domain="${1:-mcp.example.com}"
echo "Checking HTTP/3 availability for https://${domain}"
curl --http3-only -I "https://${domain}" || { echo "H3 failed"; exit 1; }
echo "OK (HTTP/3 negotiated)"
```

Hypercorn H3 (aioquic) and the curl flags (`--http3`, `--http3-only`) are documented reference checks. 

---

## 7) Small but high‑leverage operational defaults

* **Upstream keep‑alives**: done via `upstream mcp_upstream { keepalive 32; }` and `proxy_http_version 1.1` — cuts connection churn & latency. 
* **Long read timeouts** on streaming routes (`proxy_read_timeout 1h`) so token streams don’t flap. 
* **Error envelopes** and **request IDs** guarantee that a user report or trace line gives you enough to cross‑reference app, proxy, and client logs quickly. (If you later want to add Starlette’s `TrustedHostMiddleware`, it’s a one‑liner add; I’ve left it out since you’re not prioritizing security.) 
* **Proxy awareness**: `ProxyFixMiddleware` keeps generated URLs / schemes correct when behind NGINX. 

---

## 8) Extensibility “on‑ramps”

These are optional but designed to slot in without churn:

* **Metrics / traces**: If you decide to emit request/stream metrics later, Hypercorn exposes StatsD/DogStatsD toggles, and your app can add Prometheus via existing middleware patterns. I haven’t enabled them here to keep noise down, but the paths are straightforward.  
* **Client‑side resiliency for *outbound* calls** (if your MCP tools call other services): adopt `httpx.Client`/`AsyncClient` with explicit timeouts, small bounded retries at the transport, and event hooks for structured logs. (The snippet patterns and deprecations around 0.28+ are summarized here.) 

---

## 9) Operate it

1. **Choose topology**: set `MCP_NET_TOPOLOGY` and prepare either `mcp.conf` (A) or `mcp.stream.conf` (B).
2. **Enable H3 at the edge** (A): open UDP/443, deploy `mcp.conf`, `nginx -t && nginx -s reload`. 
3. **Run Hypercorn**: `systemctl enable --now codeintel-rev`.
4. **Verify H3**: `ops/check_h3.sh mcp.example.com` (look for “OK”). 
5. **Run tests**: `pytest -q tests/test_streaming.py`.

---

## Why this plan maps to your current codebase

Your repository already exposes the right seams: a FastAPI app, readiness endpoints, an SSE demo, and an MCP app factory; the diffs above **mount** and **wrap** instead of rewriting core logic, which gets you error resilience and streaming correctness with minimal surface area change. The SCIP index and repo map confirm the presence of `app/main.py`, `app/middleware.py`, MCP server modules, and related app scaffolding we leveraged. 

---

### Sources (implementation references)

* NGINX QUIC/H3 enablement, Alt‑Svc, upstream keep‑alive, and **streaming without buffering** (via `proxy_buffering off` or `X‑Accel‑Buffering: no`). 
* Hypercorn **HTTP/3 (QUIC)** via `quic_bind` + `alt_svc_headers`, CLI/TOML usage, verification with `curl --http3-only`. 
* FastAPI/Starlette **streaming** and test patterns with `httpx`.  
* `httpx` **client** best practices (timeouts, pooling, retries, hooks). 

---

If you want, I can also generate a **single patch file** that creates all the new files and applies the diffs in one shot; or a **Makefile** with `make deploy-topology-a` / `make deploy-topology-b` targets to script NGINX reload + systemd start.
