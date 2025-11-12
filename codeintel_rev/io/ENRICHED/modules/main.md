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

- function: `_preload_faiss_index` (line 41)
- function: `_env_flag` (line 72)
- function: `_log_gpu_warmup` (line 89)
- function: `_preload_faiss_if_configured` (line 110)
- function: `_preload_xtr_if_configured` (line 120)
- function: `_preload_hybrid_if_configured` (line 134)
- function: `_initialize_context` (line 145)
- function: `_shutdown_context` (line 222)
- function: `lifespan` (line 245)
- function: `_handle_hup` (line 307)
- function: `metrics_endpoint` (line 361)
- function: `set_mcp_context` (line 377)
- function: `disable_nginx_buffering` (line 446)
- function: `healthz` (line 482)
- function: `readyz` (line 494)
- function: `capz` (line 529)
- function: `sse_demo` (line 572)
- function: `event_generator` (line 581)

## Tags

fastapi, overlay-needed, public-api
