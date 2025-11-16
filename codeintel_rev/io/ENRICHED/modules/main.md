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
- from **(absolute)** import traceback
- from **(absolute)** import uuid
- from **collections.abc** import AsyncIterator, Awaitable, Callable, Mapping
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
- from **codeintel_rev.app.gpu_warmup** import warmup_gpu
- from **codeintel_rev.app.middleware** import SessionScopeMiddleware
- from **codeintel_rev.app.readiness** import ReadinessProbe
- from **codeintel_rev.app.routers** import index_admin
- from **codeintel_rev.app.server_settings** import get_server_settings
- from **codeintel_rev.errors** import RuntimeUnavailableError
- from **codeintel_rev.mcp_server.server** import app_context, build_http_app
- from **codeintel_rev.runtime.cells** import RuntimeCellObserver
- from **kgfoundry_common.errors** import ConfigurationError
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 43)
- variable: `SERVER_SETTINGS` (line 44)
- function: `request_identity` (line 53)
- function: `_sse_keepalive_interval` (line 74)
- function: `_sse_keepalive_budget` (line 92)
- function: `_client_address` (line 112)
- function: `_log_request_summary` (line 134)
- function: `_stream_log_extra` (line 150)
- function: `_preload_faiss_index` (line 189)
- function: `_env_flag` (line 220)
- function: `_resolve_proxy_trusted_hops` (line 237)
- function: `_log_gpu_warmup` (line 259)
- function: `_preload_faiss_if_configured` (line 280)
- function: `_preload_xtr_if_configured` (line 290)
- function: `_preload_hybrid_if_configured` (line 304)
- function: `_initialize_context` (line 315)
- function: `_shutdown_context` (line 393)
- function: `lifespan` (line 416)
- variable: `app` (line 508)
- function: `inject_request_id` (line 536)
- function: `set_mcp_context` (line 563)
- function: `disable_nginx_buffering` (line 622)
- function: `healthz` (line 658)
- function: `readyz` (line 670)
- function: `capz` (line 705)
- function: `_stream_with_logging` (line 747)
- function: `sse_demo` (line 809)
- function: `http_exception_handler_with_request_id` (line 862)
- function: `unhandled_exception_handler` (line 894)
- variable: `proxy_wrapped` (line 935)
- variable: `asgi` (line 940)
- variable: `asgi` (line 942)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 11
- **cycle_group**: 38

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 38
- recent churn 90: 38

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

- score: 2.82

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 69
- cyclomatic: 70
- loc: 946

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
- `_log_gpu_warmup` (function): summary=yes, params=ok, examples=no — Log the GPU warmup status summary.

## Tags

fastapi, low-coverage, public-api
