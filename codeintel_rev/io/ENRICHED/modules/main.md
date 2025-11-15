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
- from **codeintel_rev.app.routers** import diagnostics, index_admin
- from **codeintel_rev.app.server_settings** import get_server_settings
- from **codeintel_rev.errors** import RuntimeUnavailableError
- from **codeintel_rev.mcp_server.server** import app_context, build_http_app
- from **codeintel_rev.observability** import execution_ledger
- from **codeintel_rev.observability.otel** import as_span, current_trace_id, init_all_telemetry, set_current_span_attrs
- from **codeintel_rev.observability.runtime_observer** import TimelineRuntimeObserver
- from **codeintel_rev.observability.semantic_conventions** import Attrs
- from **codeintel_rev.observability.timeline** import bind_timeline, new_timeline
- from **codeintel_rev.runtime.cells** import RuntimeCellObserver
- from **codeintel_rev.telemetry.context** import current_run_id
- from **codeintel_rev.telemetry.logging** import install_structured_logging
- from **codeintel_rev.telemetry.reporter** import build_report
- from **codeintel_rev.telemetry.reporter** import build_run_report_v2, render_markdown, render_markdown_v2, render_mermaid, report_to_json
- from **kgfoundry_common.errors** import ConfigurationError
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 65)
- variable: `SERVER_SETTINGS` (line 66)
- function: `request_identity` (line 77)
- function: `_sse_keepalive_interval` (line 98)
- function: `_sse_keepalive_budget` (line 116)
- function: `_client_address` (line 136)
- function: `_log_request_summary` (line 158)
- function: `_stream_log_extra` (line 174)
- function: `_preload_faiss_index` (line 213)
- function: `_env_flag` (line 244)
- function: `_resolve_proxy_trusted_hops` (line 261)
- function: `_log_gpu_warmup` (line 283)
- function: `_preload_faiss_if_configured` (line 304)
- function: `_preload_xtr_if_configured` (line 314)
- function: `_preload_hybrid_if_configured` (line 328)
- function: `_initialize_context` (line 339)
- function: `_shutdown_context` (line 427)
- function: `lifespan` (line 450)
- variable: `app` (line 545)
- function: `_log_execution_ledger_state` (line 552)
- function: `observability_run_report` (line 602)
- function: `get_run_report` (line 639)
- function: `get_run_report_markdown` (line 681)
- function: `get_run_report_mermaid` (line 724)
- function: `get_run_report_v2` (line 756)
- function: `get_run_report_markdown_v2` (line 776)
- function: `get_run_report_mermaid_v2` (line 798)
- function: `inject_request_id` (line 820)
- function: `set_mcp_context` (line 847)
- function: `disable_nginx_buffering` (line 926)
- function: `healthz` (line 962)
- function: `readyz` (line 974)
- function: `capz` (line 1009)
- function: `_stream_with_logging` (line 1051)
- function: `sse_demo` (line 1113)
- function: `http_exception_handler_with_request_id` (line 1166)
- function: `unhandled_exception_handler` (line 1198)
- variable: `proxy_wrapped` (line 1239)
- variable: `asgi` (line 1244)
- variable: `asgi` (line 1246)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 19
- **cycle_group**: 59

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 36
- recent churn 90: 36

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

- score: 3.10

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 89
- cyclomatic: 90
- loc: 1250

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
