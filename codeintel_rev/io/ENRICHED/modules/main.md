# app/main.py

## Docstring

```
FastAPI application with MCP server mount.

Provides health/readiness endpoints, CORS, and streaming support.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **(absolute)** import os
- from **(absolute)** import signal
- from **(absolute)** import threading
- from **(absolute)** import uuid
- from **collections.abc** import AsyncIterator, Awaitable, Callable
- from **contextlib** import asynccontextmanager, suppress
- from **importlib.metadata** import PackageNotFoundError, version
- from **time** import perf_counter
- from **types** import FrameType
- from **typing** import cast
- from **fastapi** import FastAPI, HTTPException, Request
- from **fastapi.middleware.cors** import CORSMiddleware
- from **fastapi.responses** import JSONResponse, StreamingResponse
- from **hypercorn.middleware** import ProxyFixMiddleware
- from **hypercorn.typing** import ASGIFramework
- from **starlette.middleware.trustedhost** import TrustedHostMiddleware
- from **starlette.responses** import Response
- from **starlette.types** import ASGIApp
- from **codeintel_rev.app.capabilities** import Capabilities
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.app.faiss_health** import check_faiss_health
- from **codeintel_rev.app.middleware** import SessionScopeMiddleware
- from **codeintel_rev.app.readiness** import ReadinessProbe
- from **codeintel_rev.app.routers** import index_admin
- from **codeintel_rev.app.server_settings** import get_server_settings
- from **codeintel_rev.errors** import RequestContextError, RuntimeUnavailableError
- from **codeintel_rev.mcp_server.server** import app_context, build_http_app
- from **codeintel_rev.runtime.cells** import RuntimeCellObserver

## Definitions

- variable: `SERVER_SETTINGS` (line 40)
- function: `request_identity` (line 49)
- function: `_sse_keepalive_interval` (line 70)
- function: `_sse_keepalive_budget` (line 88)
- function: `_client_address` (line 108)
- function: `_log_request_summary` (line 130)
- function: `_stream_log_extra` (line 134)
- function: `_preload_faiss_index` (line 173)
- function: `_env_flag` (line 193)
- function: `_resolve_proxy_trusted_hops` (line 210)
- function: `_preload_faiss_if_configured` (line 228)
- function: `_preload_xtr_if_configured` (line 237)
- function: `_preload_hybrid_if_configured` (line 249)
- function: `_initialize_context` (line 259)
- function: `_shutdown_context` (line 335)
- function: `lifespan` (line 352)
- variable: `app` (line 428)
- function: `inject_request_id` (line 456)
- function: `set_mcp_context` (line 483)
- function: `disable_nginx_buffering` (line 554)
- function: `healthz` (line 590)
- function: `readyz` (line 602)
- function: `capz` (line 637)
- function: `_stream_with_logging` (line 679)
- function: `sse_demo` (line 707)
- function: `http_exception_handler_with_request_id` (line 760)
- function: `unhandled_exception_handler` (line 792)
- variable: `proxy_wrapped` (line 822)
- variable: `asgi` (line 827)
- variable: `asgi` (line 829)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 11
- **cycle_group**: 38

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 41
- recent churn 90: 41

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

app, asgi

## Doc Health

- **summary**: FastAPI application with MCP server mount.
- has summary: yes
- param parity: yes
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Config References

- app/hypercorn.toml

## Hotspot

- score: 2.79

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 62
- cyclomatic: 63
- loc: 833

## Doc Coverage

- `request_identity` (function): summary=yes, params=ok, examples=no — Return the session/run identifiers bound to ``request``.
- `_sse_keepalive_interval` (function): summary=yes, params=ok, examples=no — Return the configured SSE keep-alive interval (seconds).
- `_sse_keepalive_budget` (function): summary=yes, params=ok, examples=no — Return optional cap on keep-alive frames for long-lived SSE streams.
- `_client_address` (function): summary=yes, params=ok, examples=no — Return a printable representation of the originating client address.
- `_log_request_summary` (function): summary=yes, params=mismatch, examples=no — Emit a structured log describing a completed HTTP request.
- `_stream_log_extra` (function): summary=yes, params=ok, examples=no — Return structured logging metadata for streaming lifecycle events.
- `_preload_faiss_index` (function): summary=yes, params=ok, examples=no — Pre-load FAISS index during startup to avoid first-request latency.
- `_env_flag` (function): summary=yes, params=ok, examples=no — Return ``True`` when an environment flag is explicitly enabled.
- `_resolve_proxy_trusted_hops` (function): summary=yes, params=ok, examples=no — Return ProxyFix trusted hop count with PROXY_TRUSTED_HOPS override.
- `_preload_faiss_if_configured` (function): summary=yes, params=mismatch, examples=no — Preload FAISS indexes when configured to do so.

## Tags

fastapi, low-coverage, public-api
