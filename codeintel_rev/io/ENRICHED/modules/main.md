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
- from **collections.abc** import AsyncIterator, Awaitable, Callable, Mapping
- from **contextlib** import asynccontextmanager, suppress
- from **time** import perf_counter
- from **types** import FrameType
- from **typing** import Any, cast
- from **fastapi** import FastAPI, HTTPException, Request
- from **fastapi.middleware.cors** import CORSMiddleware
- from **fastapi.responses** import JSONResponse, PlainTextResponse, StreamingResponse
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
- from **codeintel_rev.observability.otel** import as_span
- from **codeintel_rev.observability.runtime_observer** import TimelineRuntimeObserver
- from **codeintel_rev.observability.timeline** import bind_timeline, new_timeline
- from **codeintel_rev.runtime.cells** import RuntimeCellObserver
- from **codeintel_rev.telemetry.context** import current_run_id
- from **codeintel_rev.telemetry.logging** import install_structured_logging
- from **codeintel_rev.telemetry.otel** import install_otel
- from **codeintel_rev.telemetry.prom** import build_metrics_router
- from **codeintel_rev.telemetry.reporter** import build_report
- from **codeintel_rev.telemetry.reporter** import render_markdown, report_to_json
- from **kgfoundry_common.errors** import ConfigurationError
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 54)
- variable: `SERVER_SETTINGS` (line 55)
- function: `_preload_faiss_index` (line 61)
- function: `_env_flag` (line 92)
- function: `_log_gpu_warmup` (line 109)
- function: `_preload_faiss_if_configured` (line 130)
- function: `_preload_xtr_if_configured` (line 140)
- function: `_preload_hybrid_if_configured` (line 154)
- function: `_initialize_context` (line 165)
- function: `_shutdown_context` (line 242)
- function: `lifespan` (line 265)
- variable: `app` (line 360)
- variable: `metrics_router` (line 384)
- function: `get_run_report` (line 394)
- function: `get_run_report_markdown` (line 436)
- function: `set_mcp_context` (line 479)
- function: `disable_nginx_buffering` (line 551)
- function: `healthz` (line 587)
- function: `readyz` (line 599)
- function: `capz` (line 634)
- function: `sse_demo` (line 677)
- variable: `proxy_wrapped` (line 722)
- variable: `asgi` (line 727)
- variable: `asgi` (line 729)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 19
- **cycle_group**: 83

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 27
- recent churn 90: 27

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

- score: 2.94

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 52
- cyclomatic: 53
- loc: 733

## Doc Coverage

- `_preload_faiss_index` (function): summary=yes, params=ok, examples=no — Pre-load FAISS index during startup to avoid first-request latency.
- `_env_flag` (function): summary=yes, params=ok, examples=no — Return ``True`` when an environment flag is explicitly enabled.
- `_log_gpu_warmup` (function): summary=yes, params=ok, examples=no — Log the GPU warmup status summary.
- `_preload_faiss_if_configured` (function): summary=yes, params=mismatch, examples=no — Preload FAISS indexes when configured to do so.
- `_preload_xtr_if_configured` (function): summary=yes, params=mismatch, examples=no — Preload XTR runtime when toggle is enabled.
- `_preload_hybrid_if_configured` (function): summary=yes, params=mismatch, examples=no — Preload HybridSearchEngine when toggle is enabled.
- `_initialize_context` (function): summary=yes, params=ok, examples=yes — Initialize application context, readiness probe, and optional runtimes.
- `_shutdown_context` (function): summary=yes, params=mismatch, examples=no — Shut down mutable runtimes and readiness probes.
- `lifespan` (function): summary=yes, params=ok, examples=no — Application lifespan manager with explicit configuration initialization.
- `get_run_report` (function): summary=yes, params=ok, examples=no — Return JSON run report for the session/run identifier.

## Tags

fastapi, low-coverage, public-api
