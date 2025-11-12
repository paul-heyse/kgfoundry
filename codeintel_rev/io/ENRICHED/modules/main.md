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
- from **fastapi** import FastAPI, Request
- from **fastapi.middleware.cors** import CORSMiddleware
- from **fastapi.responses** import JSONResponse, StreamingResponse
- from **prometheus_client** import CONTENT_TYPE_LATEST, generate_latest
- from **starlette.responses** import Response
- from **codeintel_rev.app.capabilities** import Capabilities
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.app.gpu_warmup** import warmup_gpu
- from **codeintel_rev.app.middleware** import SessionScopeMiddleware
- from **codeintel_rev.app.readiness** import ReadinessProbe
- from **codeintel_rev.app.routers** import index_admin
- from **codeintel_rev.errors** import RuntimeUnavailableError
- from **codeintel_rev.mcp_server.server** import app_context, build_http_app
- from **codeintel_rev.observability.otel** import as_span, init_telemetry
- from **codeintel_rev.observability.runtime_observer** import TimelineRuntimeObserver
- from **codeintel_rev.observability.timeline** import bind_timeline, new_timeline
- from **codeintel_rev.runtime.cells** import RuntimeCellObserver
- from **kgfoundry_common.errors** import ConfigurationError
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 38)
- function: `_preload_faiss_index` (line 41)
- function: `_env_flag` (line 72)
- function: `_log_gpu_warmup` (line 89)
- function: `_preload_faiss_if_configured` (line 110)
- function: `_preload_xtr_if_configured` (line 120)
- function: `_preload_hybrid_if_configured` (line 134)
- function: `_initialize_context` (line 145)
- function: `_shutdown_context` (line 222)
- function: `lifespan` (line 245)
- variable: `app` (line 341)
- function: `metrics_endpoint` (line 364)
- function: `set_mcp_context` (line 380)
- function: `disable_nginx_buffering` (line 449)
- function: `healthz` (line 485)
- function: `readyz` (line 497)
- function: `capz` (line 532)
- function: `sse_demo` (line 575)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 12
- **cycle_group**: 70

## Declared Exports (__all__)

app

## Doc Metrics

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

## Hotspot Score

- score: 2.72

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 44
- cyclomatic: 45
- loc: 620

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
- `metrics_endpoint` (function): summary=yes, params=ok, examples=no — Expose Prometheus metrics for scraping.

## Tags

fastapi, low-coverage, public-api
