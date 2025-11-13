Below is a deep‑dive on **Hypercorn** for an AI programming agent that needs first‑class **HTTPS streaming** and a correct **HTTP/3** setup. I’ll cover what Hypercorn is, how to install and run it, how HTTPS/TLS and QUIC are configured (step‑by‑step, with production‑grade TOML), verification checklists (curl and browser), and advanced knobs you can turn for high‑throughput streaming systems.

---

## 1) What Hypercorn is (and isn’t)

**Hypercorn** is an ASGI/WSGI server, inspired by Gunicorn, built on top of the *sans‑IO* protocol libraries `h11` (HTTP/1.1), `h2` (HTTP/2), and `wsproto` (WebSockets). It supports **HTTP/1.1, HTTP/2, WebSockets (over HTTP/1 and HTTP/2)**, ASGI 2/3, and can run with **asyncio**, **uvloop**, or **trio** worker classes. This multi‑loop design is unusual among Python servers and is helpful when you want Trio semantics or uvloop speedups. ([Hypercorn Documentation][1])

For **HTTP/3**, Hypercorn integrates with **aioquic**, a QUIC + HTTP/3 stack with its own TLS 1.3 implementation. You enable it via an optional extra and a **QUIC/UDP bind** (more below). ([GitHub][2])

---

## 2) Install matrix (pick the extras you need)

```bash
# Basic server (HTTP/1.1, HTTP/2, websockets over h1/h2)
pip install hypercorn

# For HTTP/3 (QUIC) support via aioquic
pip install "hypercorn[h3]"

# Faster event loop on CPython (not on Windows)
pip install "hypercorn[uvloop]"

# Alternate concurrency model
pip install "hypercorn[trio]"
```

Hypercorn’s README explicitly calls out the `h3` extra and how to bind QUIC once installed. ([GitHub][2])

---

## 3) How Hypercorn is launched

### CLI (most common)

```bash
hypercorn -b 0.0.0.0:443 --certfile /etc/ssl/cert.pem --keyfile /etc/ssl/key.pem module:app
```

CLI usage and argument layout are documented in the Hypercorn “Usage” and “Configuring” guides. ([Hypercorn Documentation][3])

### Programmatic API (control your own loop, graceful shutdown)

```python
import asyncio, signal
from hypercorn.config import Config
from hypercorn.asyncio import serve
from myapp import app

cfg = Config()
cfg.bind = ["0.0.0.0:443"]
cfg.certfile = "/etc/ssl/cert.pem"
cfg.keyfile = "/etc/ssl/key.pem"

shutdown_event = asyncio.Event()
async def shutdown_trigger():
    await shutdown_event.wait()

loop = asyncio.get_event_loop()
loop.add_signal_handler(signal.SIGTERM, shutdown_event.set)
asyncio.run(serve(app, cfg, shutdown_trigger=shutdown_trigger))
```

The `serve()` API, uvloop/trio variants, and graceful shutdown hook are covered in “API usage.” ([Hypercorn Documentation][4])

---

## 4) HTTPS/TLS, HTTP/2, and HTTP/3—what you need to know

### 4.1 TLS/HTTPS on TCP (HTTP/1.1 + HTTP/2)

Key options (CLI names in parentheses) include:

* `certfile` (`--certfile`), `keyfile` (`--keyfile`), `ca_certs`, `ciphers`, `verify_mode`, `ssl_handshake_timeout`.
* `alpn_protocols`: **what the server advertises** over TLS; by default `["h2", "http/1.1"]`. That’s critical to negotiate HTTP/2 with browsers. ([Hypercorn Documentation][5])

Hypercorn’s HTTP/2 discussion also explains recommended ciphers and ALPN behavior (ALPN should include `h2` if you want HTTP/2). ([Hypercorn Documentation][6])

### 4.2 QUIC/HTTP‑3 on UDP

* Hypercorn’s HTTP/3 support comes from **aioquic**; enable via `pip install "hypercorn[h3]"`.
* Bind QUIC with `--quic-bind` (UDP socket), typically **to the same host:port as your TLS bind** (e.g., `:443`). ([GitHub][2])
* **HTTP/3 discovery**: browsers usually learn about H3 via **Alt‑Svc** response headers and/or **HTTPS (SVCB) DNS records**. Hypercorn exposes `alt_svc_headers` so you can return, for example, `Alt-Svc: h3=":443"; ma=86400`. (The `HTTPS` DNS record is another discovery channel—useful if you manage DNS.) ([Hypercorn Documentation][5])

> Why Alt‑Svc? HTTP/3 is over UDP/QUIC, not TLS‑over‑TCP; Alt‑Svc tells a client it *may* try H3 to the advertised authority and port. MDN’s Alt‑Svc reference, RFC 7838, and Cloudflare/APNIC blogs explain the mechanisms and modern discovery with HTTPS/SVCB records. ([MDN Web Docs][7])

---

## 5) A production‑ready config for HTTPS + HTTP/3

Create **`hypercorn.toml`**:

```toml
# TCP/TLS for HTTP/1.1 and HTTP/2
bind = ["0.0.0.0:443"]

# QUIC/UDP for HTTP/3 (same port is fine: different transport)
quic_bind = ["0.0.0.0:443"]

# Certificates
certfile = "/etc/ssl/live/example.com/fullchain.pem"
keyfile  = "/etc/ssl/live/example.com/privkey.pem"

# ALPN for TLS connections (HTTP/2 + fallback to HTTP/1.1)
alpn_protocols = ["h2", "http/1.1"]

# Advertise HTTP/3 to clients that arrive over TCP/TLS
alt_svc_headers = [
  "h3=\":443\"; ma=86400"      # optionally also "h3-29=\":443\"; ma=86400" for legacy clients
]

# Security / hardening
keep_alive_timeout = 5                  # sensible default to mitigate idle connection DoS
ssl_handshake_timeout = 60              # default matches NGINX guidance
server_names = ["example.com", "www.example.com"]  # mitigate DNS rebinding
websocket_max_message_size = 16777216   # 16 MiB default
loglevel = "info"
accesslog = "-"                          # stdout
errorlog  = "-"                          # stderr

# Workers & event loop: choose one
# worker_class = "uvloop"               # pip install "hypercorn[uvloop]"
# worker_class = "asyncio"              # default
# worker_class = "trio"                 # pip install "hypercorn[trio]"
workers = 2
```

Run it:

```bash
hypercorn --config hypercorn.toml module:app
```

All of these knobs (including `quic_bind`, `certfile`, `keyfile`, `alpn_protocols`, `alt_svc_headers`, `server_names`, timeouts, workers) are first‑class Hypercorn config options. ([Hypercorn Documentation][5])

> **Firewall/load balancer note.** Ensure **UDP 443** is open end‑to‑end if you terminate QUIC at your origin. Many clouds default to TCP‑only security groups. If you already use an edge proxy (e.g., Cloudflare, Fastly, or NGINX‑QUIC), you can terminate H3 there and talk HTTP/1.1 or H2 to Hypercorn; in that case you do **not** need `--quic-bind`. (These vendors document that H3 discovery typically uses Alt‑Svc or HTTPS/SVCB DNS.) ([The Cloudflare Blog][8])

---

## 6) Verifying that HTTP/3 actually works

### From the CLI (curl)

* **Preferred**: a curl build with HTTP/3 support.

  ```bash
  curl --http3 -I https://example.com/
  # or to fail if h3 is unavailable
  curl --http3-only -I https://example.com/
  ```

  The curl project documents `--http3` semantics and fallback behavior; `--http3-only` is useful to make the check strict. ([Everything Curl][9])

* If you cannot install curl with HTTP/3, use a known build (e.g., Docker image) just for testing. ([Ask Ubuntu][10])

### In the browser

Open DevTools → Network and inspect the **Protocol** column. When the Alt‑Svc dance or HTTPS DNS is in place and UDP 443 is reachable, you should see **`h3`** after the first or second request. Cloudflare and APNIC have good explainers showing the flow (QUIC often connects in parallel with TCP). ([The Cloudflare Blog][11])

---

## 7) HTTPS **streaming** with Hypercorn (how it behaves and how to code it)

### 7.1 ASGI streaming semantics (applies across H1/H2/H3)

* Your app streams by sending multiple `http.response.body` messages with `more_body=True` and ending with `more_body=False`.
* **Backpressure**: Hypercorn **pauses** sending when the client or transport asks it to (HTTP/2 flow control or QUIC flow control). In your app, `await send(message)` will **block** when the connection applies backpressure, preventing runaway buffering—a key property for long‑running streams (SSE, chunked JSON, model token streams). ([Hypercorn Documentation][12])

### 7.2 Connection lifecycle & disconnects

Hypercorn’s connection‑closure policy ensures the app gets a single `http.disconnect`, and will no‑op if your app writes after the disconnect—helpful to avoid races in streaming code. ([Hypercorn Documentation][13])

### 7.3 Example: server‑sent events (SSE) over HTTPS (works the same over H2/H3)

```python
# Starlette-style app skeleton; similar in FastAPI/Quart
from starlette.responses import StreamingResponse

async def token_stream():
    yield "event: ready\ndata: {}\n\n"
    for i in range(1000):
        yield f"data: {i}\n\n"
        await some_async_wait()

async def sse_endpoint(request):
    return StreamingResponse(token_stream(), media_type="text/event-stream")
```

SSE rides standard HTTP response streaming; Hypercorn propagates backpressure safely as described above. ([Hypercorn Documentation][12])

> **WebSockets note.** Hypercorn documents WebSockets over **HTTP/1.1 and HTTP/2**; WebSockets over HTTP/3 requires the Extended CONNECT mechanism (RFC 9220) and is not listed as supported in Hypercorn’s docs at this time. For WebSockets over H3 you’d typically terminate at an H3‑capable proxy or use WebTransport instead. ([Hypercorn Documentation][1])

---

## 8) Advanced configuration & observability

* **Logging**:

  * Route error logs and access logs independently (`errorlog`, `accesslog`), and define a custom access log format (many atoms available).
  * You can supply a full Python logging config via `--log-config`, including **JSON or TOML** (prefix the path with `json:` or `toml:`). ([Hypercorn Documentation][14])

* **StatsD / DogStatsD metrics**:
  Built‑in counters and timers for request rate, duration, and status‑code buckets. Configure `statsd_host`, `statsd_prefix`, and `dogstatsd_tags`. You can also swap the StatsD logger class in a Python config. ([Hypercorn Documentation][15])

* **Proxy and host safety**:

  * If you deploy behind a reverse proxy or LB, use **`ProxyFixMiddleware`** to honor `Forwarded` or legacy `X‑Forwarded-*` headers safely (configure mode and `trusted_hops`).
  * Set `server_names` to the exact hostnames you serve to mitigate **DNS rebinding**. ([Hypercorn Documentation][16])

* **DoS mitigations** (important for streaming):

  * `keep_alive_timeout` (defaults to 5s) limits idle TCP sockets.
  * `ssl_handshake_timeout` (default 60s) prevents handshake stalls.
  * Hypercorn will pause writers on backpressure to avoid buffering explosions when the client stops reading (e.g., video or token streams). ([Hypercorn Documentation][17])

* **Multiple apps & WSGI**:

  * Use `DispatcherMiddleware` to mount multiple ASGI apps at different prefixes.
  * Hypercorn can serve **WSGI** directly and provides `AsyncioWSGIMiddleware`/`TrioWSGIMiddleware` when mixing with ASGI. ([Hypercorn Documentation][18])

* **Workers & event loops**:
  Choose `asyncio` (default), `uvloop` (faster on Linux), or `trio` (different concurrency model). Docs note uvloop does not work on Windows. ([Hypercorn Documentation][19])

---

## 9) End‑to‑end HTTP/3 setup checklist (copy/paste for your agent)

1. **Install the right bits**

   * `pip install "hypercorn[h3]"` (and optionally `hypercorn[uvloop]`). ([GitHub][2])

2. **Bind both transports**

   * TCP/TLS for H1/H2: `bind = ["0.0.0.0:443"]`
   * QUIC/UDP for H3: `quic_bind = ["0.0.0.0:443"]` (same port, different protocol). ([Hypercorn Documentation][5])

3. **Provide certificates**

   * `certfile` and `keyfile` are required for both TLS and QUIC (QUIC always uses TLS 1.3 via aioquic). ([Hypercorn Documentation][5])

4. **Advertise HTTP/3**

   * Set `alt_svc_headers = ["h3=\":443\"; ma=86400"]` to bootstrap H3. (Optionally publish an **HTTPS/SVCB DNS record** for the domain.) ([Hypercorn Documentation][5])

5. **H2 ALPN**

   * Leave `alpn_protocols = ["h2", "http/1.1"]` so TLS clients can negotiate HTTP/2 over TCP. (ALPN here does **not** announce H3; that’s on QUIC and Alt‑Svc/DNS.) ([Hypercorn Documentation][5])

6. **Open the right ports**

   * Ensure **UDP 443** reaches the origin (security groups, LB, firewall). If you terminate H3 at an edge CDN or NGINX‑QUIC, you can skip `quic_bind`. ([The Cloudflare Blog][8])

7. **Verify**

   * `curl --http3 -I https://example.com/` (or `--http3-only`). DevTools Protocol column should show `h3`. ([Everything Curl][9])

---

## 10) Troubleshooting patterns you’ll actually hit

* **Curl shows H2, not H3**

  * Missing **Alt‑Svc** or **HTTPS/SVCB** record; or UDP 443 blocked; or HTTP/3 optional extra wasn’t installed. Use `--http3-only` to force the issue during tests. ([Everything Curl][9])
* **Kubernetes liveness/readiness probes fail**

  * Probes often speak HTTP/1.1 or H2 over TCP; make sure you also have a TCP bind (`bind = ":443"` or an `insecure_bind` for plain HTTP) and point probes there. (A user issue shows a working config binding both TCP 443 and QUIC 443.) ([GitHub][20])
* **Browser keeps using H2**

  * Alt‑Svc requires at least one successful TCP request first; try a second reload, reduce `ma`, or add HTTPS/SVCB DNS so discovery happens earlier. ([MDN Web Docs][7])
* **Streaming stalls under load**

  * That’s likely client‑side backpressure or low HTTP/2 concurrency; tune `h2_max_concurrent_streams` (default 100) and ensure your application awaits writes; Hypercorn will pause writers safely. ([Hypercorn Documentation][5])

---

## 11) HTTP/2/3 features that matter for streaming

* **Multiplexing & flow control**:
  H2/H3 multiplex streams over one connection. H3 uses QUIC streams (per‑stream reliability, less HOL blocking vs TCP) and header compression (QPACK). RFC 9114 describes the mapping; the practical upshot is smoother concurrent streaming. ([RFC Editor][21])

* **Server Push**:
  In spec for H2/H3 but deprecated/disabled in Chrome and widely avoided; prefer Early Hints/preload. Don’t depend on push for perf. ([Chrome for Developers][22])

---

## 12) Minimal examples you can drop into your agent

### 12.1 Start Hypercorn with HTTP/3 support

```bash
pip install "hypercorn[h3]"  # plus your framework (Starlette/FastAPI/Quart/etc.)
hypercorn --config hypercorn.toml yourapp:app
```

([GitHub][2])

### 12.2 Development HTTPS with a self‑signed cert

```bash
openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 3 -subj "/CN=localhost"
hypercorn -b localhost:8443 --certfile cert.pem --keyfile key.pem module:app
```

Then experiment with QUIC on another port:

```bash
hypercorn -b 0.0.0.0:8443 --quic-bind 0.0.0.0:8443 --certfile cert.pem --keyfile key.pem module:app
```

(Ensure your browser/curl points at `https://localhost:8443` and you’ve added `Alt-Svc: h3=":8443"`.) Config keys and `--quic-bind` are documented in Hypercorn’s config reference and README. ([Hypercorn Documentation][5])

---

## 13) When to terminate HTTP/3 at the edge instead

If you’re already on Cloudflare/Fastly/… and primarily need the **client‑facing** benefits of HTTP/3, you can enable H3 at the edge and keep your origin on TLS/H2. The edge advertises H3 via Alt‑Svc and/or HTTPS DNS on your behalf and speaks TCP to Hypercorn—simplifying firewalling and ops while still yielding most user‑visible gains. ([The Cloudflare Blog][8])

---

## 14) Quick reference of Hypercorn knobs you’ll likely touch

* **Transport & binds**: `bind` (TCP), `quic_bind` (UDP/QUIC), `insecure_bind` (plain HTTP) ([Hypercorn Documentation][5])
* **TLS**: `certfile`, `keyfile`, `ca_certs`, `ciphers`, `verify_mode`, `ssl_handshake_timeout` ([Hypercorn Documentation][5])
* **Protocol advert/discovery**: `alpn_protocols` (H2), `alt_svc_headers` (H3) ([Hypercorn Documentation][5])
* **Flow & timeouts**: `keep_alive_timeout`, `read_timeout`, `graceful_timeout` ([Hypercorn Documentation][5])
* **Capacity**: `workers`, `h2_max_concurrent_streams`, `websocket_max_message_size` ([Hypercorn Documentation][5])
* **Routing & safety**: `server_names`, `ProxyFixMiddleware`, `DispatcherMiddleware` ([Hypercorn Documentation][23])
* **Observability**: `accesslog`, `errorlog`, `access_log_format`, `logconfig`, `statsd_host` (+ DogStatsD tags) ([Hypercorn Documentation][14])

---

## 15) A mental model for your agent

1. **Decide topology**: direct H3 at origin (`quic_bind`) or terminate H3 at the edge (skip `quic_bind`).
2. **Lay down certs**: same cert material works for TLS and QUIC.
3. **Bind transports**: TCP 443 + UDP 443 (if origin serves H3).
4. **Advertise H3**: Alt‑Svc header, optionally HTTPS/SVCB DNS.
5. **Stream sanely**: yield chunks, let Hypercorn backpressure block your `send()` calls, and tune H2/H3 concurrency.
6. **Verify** with curl and DevTools.
7. **Harden & observe**: timeouts, `server_names`, proxy fixing, logs + StatsD.

With that, Hypercorn gives you a fully modern, production‑grade ASGI/WSGI serving stack with **streaming over HTTPS** and **HTTP/3** when you want it—without giving up the ergonomics of Python or the flexibility of asyncio/trio. ([Hypercorn Documentation][12])

---

### Sources & further reading

* Hypercorn docs (features, config, workers, logging, proxy, WSGI, dispatch) and README. ([Hypercorn Documentation][1])
* HTTP/2 discussion (ALPN/ciphers) in Hypercorn docs. ([Hypercorn Documentation][6])
* AIOQUIC (HTTP/3 + TLS 1.3 stack used by Hypercorn). ([GitHub][24])
* Alt‑Svc and HTTP/3 discovery (MDN + RFC 7838 + RFC 9114 + Cloudflare/APNIC). ([MDN Web Docs][7])
* curl and HTTP/3 verification. ([Everything Curl][9])

If you want, I can tailor a **ready‑to‑run container** (Dockerfile + `hypercorn.toml`) for your stack (FastAPI/Starlette/Quart) with H3 on origin or H3 at the edge.

[1]: https://hypercorn.readthedocs.io/ "Hypercorn documentation — Hypercorn 0.17.3 documentation"
[2]: https://github.com/pgjones/hypercorn "GitHub - pgjones/hypercorn: Hypercorn is an ASGI and WSGI Server based on Hyper libraries and inspired by Gunicorn."
[3]: https://hypercorn.readthedocs.io/en/latest/tutorials/usage.html "Usage — Hypercorn 0.17.3 documentation"
[4]: https://hypercorn.readthedocs.io/en/latest/how_to_guides/api_usage.html "API Usage — Hypercorn 0.17.3 documentation"
[5]: https://hypercorn.readthedocs.io/en/latest/how_to_guides/configuring.html "Configuring — Hypercorn 0.17.3 documentation"
[6]: https://hypercorn.readthedocs.io/en/latest/discussion/http2.html "HTTP/2 — Hypercorn 0.17.3 documentation"
[7]: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Alt-Svc?utm_source=chatgpt.com "Alt-Svc header - HTTP - MDN Web Docs"
[8]: https://blog.cloudflare.com/speeding-up-https-and-http-3-negotiation-with-dns/?utm_source=chatgpt.com "Speeding up HTTPS and HTTP/3 negotiation with... DNS"
[9]: https://everything.curl.dev/http/versions/http3.html?utm_source=chatgpt.com "HTTP/3 - everything curl"
[10]: https://askubuntu.com/questions/1178611/how-do-i-install-curl-with-http3-support?utm_source=chatgpt.com "How do I install curl with http3 support"
[11]: https://blog.cloudflare.com/http3-usage-one-year-on/?utm_source=chatgpt.com "Examining HTTP/3 usage one year on"
[12]: https://hypercorn.readthedocs.io/en/latest/discussion/backpressure.html "Managing backpressure — Hypercorn 0.17.3 documentation"
[13]: https://hypercorn.readthedocs.io/en/latest/discussion/closing.html "Connection closure — Hypercorn 0.17.3 documentation"
[14]: https://hypercorn.readthedocs.io/en/latest/how_to_guides/logging.html "Logging — Hypercorn 0.17.3 documentation"
[15]: https://hypercorn.readthedocs.io/en/latest/how_to_guides/statsd.html "Statsd Logging — Hypercorn 0.17.3 documentation"
[16]: https://hypercorn.readthedocs.io/en/latest/how_to_guides/proxy_fix.html "Fixing proxy headers — Hypercorn 0.17.3 documentation"
[17]: https://hypercorn.readthedocs.io/en/latest/discussion/dos_mitigations.html "Denial Of Service mitigations — Hypercorn 0.17.3 documentation"
[18]: https://hypercorn.readthedocs.io/en/latest/how_to_guides/dispatch_apps.html "Dispatch to multiple ASGI applications — Hypercorn 0.17.3 documentation"
[19]: https://hypercorn.readthedocs.io/en/latest/discussion/workers.html "Workers — Hypercorn 0.17.3 documentation"
[20]: https://github.com/pgjones/hypercorn/issues/290 "Is the Quart/Hypercorn app really running on HTTP/3? ALL methods of k8s probes fail and chrome debugger only shows HTTP/2 in the network tab. · Issue #290 · pgjones/hypercorn · GitHub"
[21]: https://www.rfc-editor.org/rfc/rfc9114.html?utm_source=chatgpt.com "RFC 9114: HTTP/3"
[22]: https://developer.chrome.com/blog/removing-push?utm_source=chatgpt.com "Remove HTTP/2 Server Push from Chrome | Blog"
[23]: https://hypercorn.readthedocs.io/en/latest/how_to_guides/server_names.html "Server names — Hypercorn 0.17.3 documentation"
[24]: https://github.com/aiortc/aioquic?utm_source=chatgpt.com "aiortc/aioquic: QUIC and HTTP/3 implementation in Python"
