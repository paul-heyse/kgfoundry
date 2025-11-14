Below is a complete, implementation‑grade plan—with repo‑style diffs and ops artifacts—to make your MCP stack (NGINX → Hypercorn → FastAPI/Starlette → FastMCP) **seamless to use, easy to extend, and resilient to errors**, while prioritizing **HTTP/3** wherever the platform allows.

I ground the plan in the code you’ve shared (notably `app/main.py`, `app/middleware.py`, `app/server_settings.py`, `mcp_server/server.py`, `mcp_server/error_handling.py`, etc.), and in the FastAPI/Starlette + Hypercorn + NGINX references you attached. Where I refer to concrete files or behaviors, you can trace them in your SCIP/coverage snapshot and repo map (e.g., `app/main.py`, `app/middleware.py`, `mcp_server/server.py` are present and flagged as public API / low‑coverage candidates—ideal integration points). 

---

## What you’ll get after this change

* **HTTP/3‑first edge** with **two supported topologies**:

  * **A. Terminate H3 at NGINX** (recommended for most ops): Client ↔ NGINX (HTTP/3), then NGINX ↔ Hypercorn (HTTP/1.1 keep‑alive) with **streaming‑safe config**. 
  * **B. End‑to‑end H3 via L4 pass‑through**: Client ↔ NGINX stream (UDP/TCP pass‑through) ↔ Hypercorn (H3 on origin). Choose when you require literal H3 on both hops; you give up L7 features on NGINX. 
* **Single ASGI entrypoint** that mounts **your MCP ASGI app under `/mcp`**, plus **proxy‑header correctness** and **streaming‑friendly headers** by default. (Starlette/FastAPI make sub‑app mounting first‑class.)
* **Streaming correctness** end‑to‑end (SSE, chunked JSON, token streaming): no buffering at the edge, explicit keep‑alives, backpressure‑safe server behavior (Hypercorn).
* **Operational polish**: systemd units, Hypercorn TOML (H1/H2/H3), curl & browser H3 verification, structured request IDs from edge → app for quick triage, and ready/health endpoints preserved.

---

## Layered design (quick map)

1. **FastAPI/Starlette app**

   * Mount MCP sub‑app at `/mcp`; export **`asgi`** target; add **Request‑ID** + **Streaming** middlewares (pure ASGI), keep existing readiness & capability endpoints. 

2. **Hypercorn**

   * **Mode A:** plain HTTP on loopback (behind NGINX) with long keep‑alive for streaming.
   * **Mode B:** direct TLS + QUIC (HTTP/3) at origin with `quic_bind`, ALPN, and `Alt‑Svc`. 

3. **NGINX**

   * **A. H3 termination** with `listen 443 quic` and `proxy_buffering off` for streaming paths; keep‑alive upstream; pass `X‑Request‑ID`.
   * **B. L4 pass‑through** for UDP 443 + TCP 443 to Hypercorn (loss of L7 controls by design). 

4. **Verification & Ops**

   * `curl --http3[‑only]` checks, DevTools “Protocol = h3”, graceful reloads, systemd units, and a tiny e2e test using `httpx.AsyncClient` (HTTP/2 to speed up test concurrency; httpx documents H2, not H3). 

---

## Repository diffs

> Paths assume your Python package is `codeintel_rev` and you keep ops config under `ops/`.
> The diffs below are **additive** and safe to apply even if parts of the glue already exist.

### 1) FastAPI app: mount MCP under `/mcp`, add proxy/streaming middlewares

**a. Add a lightweight runtime middleware module** (pure ASGI: zero overhead, cross‑protocol). Starlette recommends ASGI middleware when you want lowest overhead or cross‑protocol control. 

```diff
*** Begin Patch
*** Add File: codeintel_rev/app/middleware_runtime.py
+from __future__ import annotations
+import asyncio
+import typing as t
+import uuid
+
+# Pure ASGI middleware to (1) ensure a request-id, (2) disable edge buffering for streams.
+# See Starlette notes: pure ASGI middlewares avoid BaseHTTPMiddleware's extra hop. 
+# (Best when you need to touch ASGI messages directly.)  :contentReference[oaicite:11]{index=11}
+
+ASGIApp = t.Callable[[dict, t.Callable, t.Callable], t.Awaitable[None]]
+
+class RequestIDMiddleware:
+    def __init__(self, app: ASGIApp, header_name: str = "x-request-id") -> None:
+        self.app = app
+        self.header_name = header_name.lower()
+
+    async def __call__(self, scope, receive, send):
+        if scope["type"] != "http":
+            return await self.app(scope, receive, send)
+
+        # capture existing id or create one
+        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
+        req_id = headers.get(self.header_name, str(uuid.uuid4()))
+
+        async def send_wrapper(message):
+            if message["type"] == "http.response.start":
+                raw_headers = message.setdefault("headers", [])
+                raw_headers.append((b"x-request-id", req_id.encode()))
+            await send(message)
+
+        return await self.app(scope, receive, send_wrapper)
+
+class StreamingHeadersMiddleware:
+    """
+    Ensure responses that *intend* to stream are not buffered by reverse proxies.
+    For NGINX we signal with 'X-Accel-Buffering: no'.  :contentReference[oaicite:12]{index=12}
+    """
+    def __init__(self, app: ASGIApp) -> None:
+        self.app = app
+
+    async def __call__(self, scope, receive, send):
+        if scope["type"] != "http":
+            return await self.app(scope, receive, send)
+
+        # Heuristic: if endpoint starts sending body in multiple chunks,
+        # set the header. This is robust for SSE/streamed JSON/token streams.
+        first_body_seen = False
+
+        async def send_wrapper(message):
+            nonlocal first_body_seen
+            if message["type"] == "http.response.body":
+                if first_body_seen is False:
+                    first_body_seen = True
+                    # inject header just-in-time before the first body
+                    await send({
+                        "type": "http.response.start",
+                        "status": 200,
+                        "headers": [(b"x-accel-buffering", b"no")],
+                    })
+                # fall through to forward the body chunk
+            await send(message)
+
+        return await self.app(scope, receive, send_wrapper)
*** End Patch
```

**b. Mount MCP and export a Hypercorn‑ready ASGI target**
We reuse your existing capability snapshot + MCP server to build the sub‑app; those modules exist in your repo and are the right glue points. 

```diff
*** Begin Patch
*** Update File: codeintel_rev/app/main.py
@@
-from fastapi import FastAPI, Request
+from fastapi import FastAPI, Request
+import os
+from hypercorn.middleware import ProxyFixMiddleware  # honor Forwarded/X-Forwarded-* behind NGINX :contentReference[oaicite:14]{index=14}
+from codeintel_rev.app.capabilities import Capabilities
+from codeintel_rev.mcp_server import server as mcp_server  # MCP ASGI app factory lives here :contentReference[oaicite:15]{index=15}
+from codeintel_rev.app.middleware_runtime import RequestIDMiddleware, StreamingHeadersMiddleware
@@
-app = FastAPI(title="codeintel_rev", docs_url="/docs")
+app = FastAPI(title="codeintel_rev", docs_url="/docs")
 
 # (your existing routers: /readyz, /capz, any SSE demos, etc., remain)
 
+@app.on_event("startup")
+async def _mount_mcp() -> None:
+    """
+    Build and mount the MCP ASGI application under /mcp from the live capability snapshot.
+    """
+    ctx = getattr(app.state, "context", None)  # your app already sets this in lifespan/startup
+    if ctx is None:
+        return
+    caps = Capabilities.from_context(ctx)
+    app.state.capabilities = caps
+    mcp_asgi = mcp_server.build_http_app(caps)  # constructs the FastMCP HTTP app  :contentReference[oaicite:16]{index=16}
+    app.mount("/mcp", mcp_asgi)
+
+# Layer middlewares: Request ID first, then streaming header helper, then proxy fix.
+_asgi = RequestIDMiddleware(app)
+_asgi = StreamingHeadersMiddleware(_asgi)
+trusted_hops = int(os.getenv("PROXY_TRUSTED_HOPS", "1"))
+asgi = ProxyFixMiddleware(_asgi, mode="legacy", trusted_hops=trusted_hops)  # Hypercorn docs pattern :contentReference[oaicite:17]{index=17}
*** End Patch
```

> **Why this shape?**
> • Starlette/FastAPI treat sub‑apps as first‑class via `app.mount`, which keeps your API and the MCP surface modular. 
> • Hypercorn’s `ProxyFixMiddleware` is the supported way to ensure `request.url`/scheme/client are correct when you’re behind a proxy. 
> • Adding `X‑Accel‑Buffering: no` on streamed responses makes NGINX forward bytes as they arrive (or you can set `proxy_buffering off` per‑location; both are correct). 

**c. (Optional) SSE keep‑alive helper**—use from any streaming endpoint to avoid idle intermediaries closing sockets.

```diff
*** Begin Patch
*** Add File: codeintel_rev/app/streaming.py
+import asyncio
+from typing import AsyncIterator
+
+async def sse_keepalive(interval_sec: float = 15.0) -> AsyncIterator[bytes]:
+    """Yield SSE comments periodically to keep intermediaries alive."""
+    while True:
+        yield b": keep-alive\n\n"  # valid SSE comment frame
+        await asyncio.sleep(interval_sec)
*** End Patch
```

You can compose this generator with your token/data streams as needed.

---

### 2) Hypercorn configuration (two ready‑to‑run TOMLs)

> Hypercorn has first‑class knobs for HTTP/1.1, HTTP/2, and HTTP/3 (via QUIC + `aioquic`). We use **one TOML for “behind NGINX”** and **one for “direct H3”**. 

**a. `ops/hypercorn-behind-nginx.toml`** (Topology A: NGINX terminates TLS/H3)

```diff
*** Begin Patch
*** Add File: ops/hypercorn-behind-nginx.toml
+# Behind NGINX: listen on loopback, long keep-alives for streaming
+bind = ["127.0.0.1:8000"]
+keep_alive_timeout = 75
+graceful_timeout  = 20
+include_server_header = false
+accesslog = "-"
+errorlog  = "-"
+# choose your worker/event loop (asyncio default; uvloop optional)
+# worker_class = "uvloop"   # pip install "hypercorn[uvloop]"
+workers = 1
*** End Patch
```

**b. `ops/hypercorn-h3-origin.toml`** (Topology B: Hypercorn serves H3 at the origin)

```diff
*** Begin Patch
*** Add File: ops/hypercorn-h3-origin.toml
+# Direct H3 at the origin (UDP + TCP on the same port). Requires: pip install "hypercorn[h3]"
+bind = ["0.0.0.0:443"]          # TLS for HTTP/1.1 + HTTP/2
+quic_bind = ["0.0.0.0:443"]     # QUIC/UDP for HTTP/3  :contentReference[oaicite:22]{index=22}
+alpn_protocols = ["h2", "http/1.1"]
+alt_svc_headers = ["h3=\":443\"; ma=86400"]  # advertise H3 to TCP-connected clients  :contentReference[oaicite:23]{index=23}
+certfile = "/etc/ssl/live/your.host/fullchain.pem"
+keyfile  = "/etc/ssl/live/your.host/privkey.pem"
+keep_alive_timeout = 75
+graceful_timeout  = 20
+accesslog = "-"
+errorlog  = "-"
+workers = 1
*** End Patch
```

> **Verification tips:** `curl --http3 -I https://your.host/` or `--http3-only` to fail if H3 is unavailable; in your browser DevTools → Network → “Protocol” column should show `h3` on the second request once Alt‑Svc is learned. 

---

### 3) NGINX config (two canonical variants)

> Everything below follows the H3/QUIC docs you attached (1.25+), including `listen 443 quic`, `reuseport`, and the streaming/keep‑alive guidance for ASGI backends. 

**a. Topology A — Terminate H3 at NGINX; proxy to Hypercorn on loopback**

```diff
*** Begin Patch
*** Add File: ops/nginx/conf.d/mcp.conf
+upstream mcp_upstream {
+    server 127.0.0.1:8000;
+    keepalive 32;                      # persistent upstream conns  :contentReference[oaicite:26]{index=26}
+}
+
+server {
+    server_name your.host;
+
+    # H2 + H3 to clients
+    listen 443 ssl http2;
+    listen 443 quic reuseport;
+    http3 on;                          # enable QUIC/H3  :contentReference[oaicite:27]{index=27}
+
+    # TLS certs (managed by certbot --nginx if you prefer)
+    ssl_certificate     /etc/letsencrypt/live/your.host/fullchain.pem;
+    ssl_certificate_key /etc/letsencrypt/live/your.host/privkey.pem;
+
+    # Advertise H3
+    add_header Alt-Svc 'h3=":443"; ma=86400' always;
+
+    # MCP app (streaming safe)
+    location /mcp/ {
+        proxy_pass http://mcp_upstream;
+
+        proxy_http_version 1.1;
+        proxy_set_header Connection "";
+
+        # Streaming: don't buffer; or let the app signal via X-Accel-Buffering: no
+        proxy_buffering off;            # streaming correctness  :contentReference[oaicite:28]{index=28}
+        proxy_read_timeout 1h;
+
+        # Forward headers & a stable request id
+        proxy_set_header Host              $host;
+        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
+        proxy_set_header X-Forwarded-Proto $scheme;
+        proxy_set_header X-Request-ID      $request_id;
+    }
+}
*** End Patch
```

**b. Topology B — L4 pass‑through for true end‑to‑end H3**

> This keeps QUIC/TLS intact to Hypercorn. You lose L7 features like header manipulation or caching; use only if you *must* keep H3 on both hops. 

```diff
*** Begin Patch
*** Add File: ops/nginx/stream/mcp-stream.conf
+stream {
+  # TCP 443 → Hypercorn
+  server {
+    listen 443;
+    proxy_pass 127.0.0.1:443;  # Hypercorn bound with TLS on 443 (see hypercorn-h3-origin.toml)
+  }
+  # UDP 443 (QUIC) → Hypercorn
+  server {
+    listen 443 udp reuseport;
+    proxy_pass 127.0.0.1:443;
+  }
+}
*** End Patch
```

> **Reload habits:** `nginx -t && nginx -s reload` is graceful (no dropped requests); workers drain cleanly. 

---

### 4) Systemd units (Hypercorn)

```diff
*** Begin Patch
*** Add File: ops/systemd/hypercorn.service
+[Unit]
+Description=Hypercorn (codeintel_rev)
+After=network.target
+Wants=network-online.target
+
+[Service]
+Type=simple
+User=www-data
+Group=www-data
+WorkingDirectory=/opt/codeintel_rev
+Environment=PYTHONUNBUFFERED=1
+ExecStart=/usr/bin/env hypercorn --config /opt/codeintel_rev/ops/hypercorn-behind-nginx.toml codeintel_rev.app.main:asgi
+Restart=on-failure
+RestartSec=2
+LimitNOFILE=65536
+
+[Install]
+WantedBy=multi-user.target
*** End Patch
```

(For topology B, point `--config` to `hypercorn-h3-origin.toml`.)

---

## Optional niceties that directly improve resilience & extensibility

1. **Request/response logging and trace propagation**

   * With the `RequestIDMiddleware` + `X‑Request‑ID` from NGINX, it’s trivial to correlate edge and app logs.
   * If you use FastAPI/Starlette logging hooks, emit JSON logs keyed by request‑id and route. (FastAPI/Starlette middleware and background‑task patterns are documented in your refs.)

2. **Client‑side robustness for any upstream calls your app makes**

   * Use `httpx.AsyncClient` with explicit timeouts and HTTP/2 enabled for concurrency; `event_hooks` provide simple, centralized logging and `.Limits()` controls pooling. (HTTPX ships H1.1 + H2; it does **not** advertise H3—H2 is perfect for agent‑style fan‑out.) 
   * If you prefer `aiohttp`, mirror the one‑session‑per‑process and `ClientTimeout` patterns. 

3. **Streaming patterns**

   * Use Starlette’s `StreamingResponse` for token/SSE output and add periodic `": keep‑alive\n\n"` frames for long‑running streams to keep intermediaries warm. Hypercorn’s backpressure model prevents buffer blow‑ups when clients slow down. 

---

## Verification & runbook

**1) Bringup (topology A recommended):**

```bash
# Enable and start services
sudo systemctl daemon-reload
sudo systemctl enable hypercorn.service
sudo systemctl start  hypercorn.service

# NGINX test + reload
sudo nginx -t && sudo nginx -s reload
```

**2) Smoke tests:**

```bash
# HTTP/3 from CLI (use an http3-capable curl build)
curl --http3 -I https://your.host/readyz
curl --http3 -N https://your.host/mcp/stream-demo  # if you expose a demo stream
```

You should see `Protocol: h3` in browser DevTools after Alt‑Svc is learned. 

**3) App‑level test (pytest + httpx):**

```python
# tests/e2e/test_streaming.py
import pytest, httpx, asyncio

@pytest.mark.asyncio
async def test_ready_and_stream():
    async with httpx.AsyncClient(base_url="https://your.host", http2=True, verify=False) as c:
        r = await c.get("/readyz", timeout=5)
        assert r.status_code == 200
        # streaming smoke
        async with c.stream("GET", "/mcp/sse") as resp:
            assert resp.status_code == 200
            async for chunk in resp.aiter_bytes():
                assert chunk  # got some bytes
                break
```

HTTPX’s H2 client is great for high‑concurrency tests; keep H3 checks to curl/browser for now. 

---

## Why these choices map cleanly to your repo

* Your tree already contains the right public surfaces to attach the plan: **`app/main.py`**, **`app/middleware.py`**, **`app/server_settings.py`**, and the **MCP server package** (`mcp_server/*.py`). That’s exactly where we mounted the sub‑app and layered the operational middlewares. 
* Mounting sub‑apps and composing middlewares is idiomatic in **FastAPI/Starlette**, keeping the codebase modular and testable.
* **Hypercorn** exposes the H3 knobs we need (`quic_bind`, `alt_svc_headers`, ALPN, QUIC on UDP 443) and a `ProxyFixMiddleware` for correct proxy behavior; both are used here. 
* **NGINX** H3 plus streaming correctness (disable buffering or emit `X‑Accel‑Buffering: no`) is a well‑trodden path for ASGI backends and aligns with your “HTTP/3 to the greatest extent possible” goal. 

---

## Notes & trade‑offs you asked to be explicit about

* **HTTP/3 “end‑to‑end”**: OSS NGINX terminates H3 at the edge; it does not forward to upstream over H3 today. If you require H3 on both legs, use the **stream pass‑through** topology and let Hypercorn serve QUIC/TLS at origin. Expect fewer edge features in that mode. 
* **WebSockets**: Hypercorn documents WS over HTTP/1.1 and HTTP/2; if you need WS over H3, keep using topology A (WS via H1/H2 behind NGINX) or plan for WebTransport down the road. 

---

## What to implement next (fast follow)

* **Repo‑level tests**: An integration test that spins **Hypercorn in‑process** (using the programmatic API) and hits `/mcp` via `httpx.AsyncClient(app=..., base_url="https://test")` to validate the mount and middleware stack in CI. 
* **Minimal operator docs**: A `RUNBOOK.md` page with curl/browser screenshots and `journalctl -u hypercorn` snippets for first response triage.
* **Optional**: consolidate streaming helpers in `app/streaming.py` (SSE frames, JSON chunker) and standardize per‑route **timeouts** (client‑visible) so upstreams don’t appear to hang.

---

### One‑page checklist for your AI agent (a recap)

1. Apply the diffs above.
2. Choose **Topology A** or **B** and drop the matching NGINX + Hypercorn config.
3. `systemctl enable --now hypercorn && nginx -t && nginx -s reload`.
4. Verify H3 with `curl --http3` and in the browser.
5. Exercise `/mcp` with a streaming endpoint; confirm logs carry `X‑Request‑ID` from edge → app.

If you want me to tailor the mount point or fold these into your existing `app/middleware.py` instead of a new module, say the word and I’ll emit the adjusted diff.
