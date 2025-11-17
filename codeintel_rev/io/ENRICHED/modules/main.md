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
- from **collections.abc** import AsyncIterator, Awaitable, Callable, Iterator
- from **contextlib** import asynccontextmanager, contextmanager, suppress
- from **dataclasses** import dataclass, replace
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
- from **codeintel_rev.app.config_context** import ApplicationContext, ApplicationContextOverrides
- from **codeintel_rev.app.faiss_health** import check_faiss_health
- from **codeintel_rev.app.middleware** import SessionScopeMiddleware
- from **codeintel_rev.app.readiness** import ReadinessProbe
- from **codeintel_rev.app.routers** import index_admin
- from **codeintel_rev.app.server_settings** import ServerSettings, get_server_settings
- from **codeintel_rev.errors** import RequestContextError, RuntimeUnavailableError
- from **codeintel_rev.mcp_server.server** import app_context, build_http_app
- from **codeintel_rev.runtime.cells** import RuntimeCellObserver

## Definitions

- variable: `SERVER_SETTINGS` (line 44)
- class: `AppLifecycleHooks` (line 52)
- function: `override_app_hooks` (line 66)
- function: `request_identity` (line 76)
- function: `_resolve_server_settings` (line 97)
- function: `_sse_keepalive_interval` (line 119)
- function: `_sse_keepalive_budget` (line 139)
- function: `_client_address` (line 161)
- function: `_log_request_summary` (line 183)
- function: `_stream_log_extra` (line 187)
- function: `_preload_faiss_index` (line 226)
- function: `_env_flag` (line 246)
- function: `_resolve_proxy_trusted_hops` (line 266)
- function: `_preload_faiss_if_configured` (line 284)
- function: `_preload_xtr_if_configured` (line 293)
- function: `_preload_hybrid_if_configured` (line 305)
- function: `_create_application_context` (line 315)
- function: `_initialize_context` (line 326)
- function: `_shutdown_context` (line 397)
- function: `lifespan` (line 417)
- variable: `app` (line 493)
- function: `inject_request_id` (line 522)
- function: `set_mcp_context` (line 549)
- function: `disable_nginx_buffering` (line 620)
- function: `healthz` (line 656)
- function: `readyz` (line 668)
- function: `capz` (line 703)
- function: `_stream_with_logging` (line 745)
- function: `sse_demo` (line 773)
- function: `http_exception_handler_with_request_id` (line 826)
- function: `unhandled_exception_handler` (line 858)
- variable: `proxy_wrapped` (line 888)
- variable: `asgi` (line 893)
- variable: `asgi` (line 895)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 11
- **cycle_group**: 40

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 43
- recent churn 90: 43

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

app, asgi

## Doc Health

- **summary**: FastAPI application with MCP server mount.
- has summary: yes
- param parity: no
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

- score: 2.82

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 69
- cyclomatic: 70
- loc: 899

## Doc Coverage

- `AppLifecycleHooks` (class): summary=yes, examples=no — Override hooks for application startup/shutdown behavior.
- `override_app_hooks` (function): summary=yes, params=mismatch, examples=no — Temporarily override application lifecycle hooks (tests only).
- `request_identity` (function): summary=yes, params=ok, examples=no — Return the session/run identifiers bound to ``request``.
- `_resolve_server_settings` (function): summary=yes, params=ok, examples=no — Return server settings, preferring request-level overrides.
- `_sse_keepalive_interval` (function): summary=yes, params=ok, examples=no — Return the configured SSE keep-alive interval (seconds).
- `_sse_keepalive_budget` (function): summary=yes, params=ok, examples=no — Return optional cap on keep-alive frames for long-lived SSE streams.
- `_client_address` (function): summary=yes, params=ok, examples=no — Return a printable representation of the originating client address.
- `_log_request_summary` (function): summary=yes, params=mismatch, examples=no — Emit a structured log describing a completed HTTP request.
- `_stream_log_extra` (function): summary=yes, params=ok, examples=no — Return structured logging metadata for streaming lifecycle events.
- `_preload_faiss_index` (function): summary=yes, params=ok, examples=no — Pre-load FAISS index during startup to avoid first-request latency.

## Tags

fastapi, low-coverage, public-api
