"""FastAPI application with MCP server mount.

Provides health/readiness endpoints, CORS, and streaming support.
"""

from __future__ import annotations

import asyncio
import os
import signal
import threading
import traceback
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from importlib.metadata import PackageNotFoundError, version
from time import perf_counter
from types import FrameType
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from hypercorn.middleware import ProxyFixMiddleware
from hypercorn.typing import ASGIFramework
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.gpu_warmup import warmup_gpu
from codeintel_rev.app.middleware import SessionScopeMiddleware
from codeintel_rev.app.readiness import ReadinessProbe
from codeintel_rev.app.routers import index_admin
from codeintel_rev.app.server_settings import get_server_settings
from codeintel_rev.errors import RuntimeUnavailableError
from codeintel_rev.mcp_server.server import app_context, build_http_app
from codeintel_rev.observability.otel import (
    as_span,
    current_trace_id,
    init_all_telemetry,
    instrument_fastapi,
    instrument_httpx,
    set_current_span_attrs,
)
from codeintel_rev.observability.runtime_observer import TimelineRuntimeObserver
from codeintel_rev.observability.semantic_conventions import Attrs
from codeintel_rev.observability.timeline import bind_timeline, new_timeline
from codeintel_rev.runtime.cells import RuntimeCellObserver
from codeintel_rev.telemetry.context import current_run_id
from codeintel_rev.telemetry.logging import install_structured_logging
from codeintel_rev.telemetry.prom import build_metrics_router
from codeintel_rev.telemetry.reporter import (
    build_report as build_run_report,
)
from codeintel_rev.telemetry.reporter import (
    render_markdown,
    render_mermaid,
    report_to_json,
)
from kgfoundry_common.errors import ConfigurationError
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)
SERVER_SETTINGS = get_server_settings()
try:
    _DIST_VERSION = version("kgfoundry")
except PackageNotFoundError:
    _DIST_VERSION = None

install_structured_logging()

_DEFAULT_SSE_KEEPALIVE_SECONDS = 25.0


def _sse_keepalive_interval() -> float:
    """Return the configured SSE keep-alive interval (seconds).

    Returns
    -------
    float
        Keep-alive interval in seconds, clamped to a minimum of 5.0 seconds.
        Defaults to ``_DEFAULT_SSE_KEEPALIVE_SECONDS`` if environment variable
        is unset or invalid.
    """
    raw_value = os.getenv("SSE_KEEPALIVE_SECONDS", str(_DEFAULT_SSE_KEEPALIVE_SECONDS))
    try:
        interval = float(raw_value)
    except ValueError:
        return _DEFAULT_SSE_KEEPALIVE_SECONDS
    return max(5.0, interval)


def _sse_keepalive_budget() -> int | None:
    """Return optional cap on keep-alive frames for long-lived SSE streams.

    Returns
    -------
    int | None
        Maximum number of keep-alive frames to emit after the initial payload.
        ``None`` indicates infinite keep-alives (default). Intended for tests to
        keep the stream finite by setting ``SSE_MAX_KEEPALIVES``.
    """
    raw_value = os.getenv("SSE_MAX_KEEPALIVES")
    if raw_value is None:
        return None
    try:
        budget = int(raw_value)
    except ValueError:
        return None
    return None if budget < 0 else budget


def _client_address(request: Request) -> str:
    """Return a printable representation of the originating client address.

    Parameters
    ----------
    request : Request
        FastAPI request object containing client connection information.

    Returns
    -------
    str
        Client address string in "host:port" format, or "host" if port is None,
        or "unknown" if client information is unavailable.
    """
    client = request.client
    if client is None:
        return "unknown"
    host = client.host or "unknown"
    port = client.port
    return f"{host}:{port}" if port is not None else host


def _log_request_summary(request: Request, *, status_code: int, duration_ms: int) -> None:
    """Emit a structured log describing a completed HTTP request."""
    LOGGER.info(
        "http.request",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "http_version": request.scope.get("http_version", "1.1"),
            "client_addr": _client_address(request),
        },
    )


def _stream_log_extra(
    request: Request,
    *,
    stream_name: str,
    stage: str,
    chunk_bytes: int | None = None,
) -> dict[str, object]:
    """Return structured logging metadata for streaming lifecycle events.

    Parameters
    ----------
    request : Request
        FastAPI request object containing request state and URL path.
    stream_name : str
        Name identifier for the stream being logged.
    stage : str
        Lifecycle stage identifier (e.g., "open", "flush", "closed").
    chunk_bytes : int | None
        Optional byte count for the chunk being processed. Defaults to None.

    Returns
    -------
    dict[str, object]
        Dictionary containing request_id, path, stream name, stage, and optional
        chunk_bytes for structured logging.
    """
    metadata: dict[str, object] = {
        "request_id": getattr(request.state, "request_id", None),
        "path": request.url.path,
        "stream": stream_name,
        "stage": stage,
        "client_addr": _client_address(request),
        "http_version": request.scope.get("http_version", "1.1"),
    }
    if chunk_bytes is not None:
        metadata["chunk_bytes"] = chunk_bytes
    return metadata


def _preload_faiss_index(context: ApplicationContext) -> bool:
    """Pre-load FAISS index during startup to avoid first-request latency.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing FAISS manager.

    Returns
    -------
    bool
        True if index loaded successfully, False otherwise.
    """
    try:
        context.faiss_manager.load_cpu_index()
        LOGGER.info("FAISS CPU index loaded successfully")

        # Attempt GPU clone if available
        gpu_enabled = context.faiss_manager.clone_to_gpu()
        if gpu_enabled:
            LOGGER.info("FAISS GPU acceleration enabled")
        else:
            reason = context.faiss_manager.gpu_disabled_reason or "Unknown"
            LOGGER.warning("FAISS GPU acceleration unavailable: %s", reason)
    except (FileNotFoundError, RuntimeError) as exc:
        LOGGER.warning("FAISS index pre-load failed: %s", exc)
        return False
    else:
        return True


def _env_flag(name: str) -> bool:
    """Return ``True`` when an environment flag is explicitly enabled.

    Parameters
    ----------
    name : str
        Environment variable name to inspect.

    Returns
    -------
    bool
        ``True`` if the variable is set to a truthy value.
    """
    value = os.getenv(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _log_gpu_warmup(status: Mapping[str, object]) -> None:
    """Log the GPU warmup status summary.

    Parameters
    ----------
    status : Mapping[str, object]
        Warmup status payload emitted by :func:`warmup_gpu`.

    """
    overall = status.get("overall_status")
    if overall == "ready":
        LOGGER.info("GPU warmup successful - GPU acceleration available")
    elif overall == "degraded":
        LOGGER.warning(
            "GPU warmup partial - some GPU features unavailable: %s",
            status.get("details"),
        )
    else:
        LOGGER.info("GPU warmup indicates GPU unavailable - continuing with CPU-only mode")


async def _preload_faiss_if_configured(context: ApplicationContext) -> None:
    """Preload FAISS indexes when configured to do so."""
    if not context.settings.index.faiss_preload:
        return
    LOGGER.info("Pre-loading FAISS index during startup")
    preload_success = await asyncio.to_thread(_preload_faiss_index, context)
    if not preload_success:
        LOGGER.warning("FAISS index pre-load failed; will lazy-load on first search")


def _preload_xtr_if_configured(context: ApplicationContext) -> None:
    """Preload XTR runtime when toggle is enabled."""
    if not _env_flag("XTR_PRELOAD"):
        return
    LOGGER.info("Pre-loading XTR index during startup")
    try:
        index = context.get_xtr_index()
    except (RuntimeError, OSError, ValueError, RuntimeUnavailableError):
        LOGGER.warning("XTR preload failed; continuing lazily", exc_info=True)
        return
    if index is None or not getattr(index, "ready", False):
        LOGGER.warning("XTR preload requested but index unavailable")


def _preload_hybrid_if_configured(context: ApplicationContext) -> None:
    """Preload HybridSearchEngine when toggle is enabled."""
    if not _env_flag("HYBRID_PRELOAD"):
        return
    LOGGER.info("Pre-loading HybridSearchEngine during startup")
    try:
        context.get_hybrid_engine()
    except (RuntimeError, OSError, ValueError, RuntimeUnavailableError):
        LOGGER.warning("Hybrid preload failed; continuing lazily", exc_info=True)


async def _initialize_context(
    app: FastAPI,
    *,
    runtime_observer: RuntimeCellObserver | None = None,
) -> tuple[ApplicationContext, ReadinessProbe]:
    """Initialize application context, readiness probe, and optional runtimes.

    Extended Summary
    ----------------
    This function orchestrates the application startup sequence by creating the
    ApplicationContext, performing GPU warmup, initializing the readiness probe,
    and optionally pre-loading FAISS, XTR, and hybrid search runtimes. It stores
    the context and readiness probe in the FastAPI app.state for access by request
    handlers. This function is called once during application startup from the
    lifespan() context manager.

    Parameters
    ----------
    app : FastAPI
        FastAPI application instance. Used to store application context and
        readiness probe in app.state for access by request handlers.
    runtime_observer : RuntimeCellObserver | None, optional
        Observer attached to runtime cells for instrumentation. Defaults to a
        no-op observer when not provided.

    Returns
    -------
    tuple[ApplicationContext, ReadinessProbe]
        Pair containing the initialized context and readiness probe. The context
        contains all configuration and long-lived clients. The readiness probe
        monitors the health of dependent services and resources.

    Raises
    ------
    TypeError
        Raised when `ApplicationContext.create` does not accept the
        ``runtime_observer`` parameter (older interface).

    Notes
    -----
    Time complexity depends on runtime pre-loading configuration. GPU warmup and
    optional pre-loading operations may take several seconds. The function performs
    I/O operations (filesystem access, network requests for readiness checks) and
    may allocate GPU resources. Thread-safe if called from a single async context
    during startup. The function is not idempotent - it should only be called once
    per application lifecycle.

    This function may propagate ConfigurationError from ApplicationContext.create()
    if application configuration is invalid or required resources are missing. The
    exception propagates to lifespan(), causing FastAPI startup to fail.

    Examples
    --------
    >>> # Called from lifespan() context manager
    >>> context, readiness = await _initialize_context(app)
    >>> assert context is not None
    >>> assert readiness is not None
    """
    try:
        context = ApplicationContext.create(runtime_observer=runtime_observer)
    except TypeError as exc:
        if "runtime_observer" in str(exc):
            context = ApplicationContext.create()
        else:  # pragma: no cover - defensive
            raise
    app.state.context = context
    with as_span("readiness.gpu_warmup", component="startup"):
        warmup_status = warmup_gpu()
        status = warmup_status.get("overall_status")
        attrs: dict[str, object] = {
            Attrs.COMPONENT: "startup",
            Attrs.STAGE: "gpu_warmup",
            "readiness.status": status or "unknown",
        }
        if status == "degraded":
            attrs[Attrs.WARN_DEGRADED] = True
        set_current_span_attrs(**attrs)
    _log_gpu_warmup(warmup_status)
    readiness = ReadinessProbe(context)
    await readiness.initialize()
    app.state.readiness = readiness
    await _preload_faiss_if_configured(context)
    _preload_xtr_if_configured(context)
    _preload_hybrid_if_configured(context)
    LOGGER.info("Application initialization complete")
    return context, readiness


async def _shutdown_context(
    context: ApplicationContext | None,
    readiness: ReadinessProbe | None,
) -> None:
    """Shut down mutable runtimes and readiness probes."""
    LOGGER.info("Starting application shutdown")
    if context is not None:
        with suppress(Exception):
            context.close_all_runtimes()
        if hasattr(context, "scope_store"):
            try:
                await context.scope_store.close()
            except (RuntimeError, OSError, ValueError):
                LOGGER.warning("Scope store shutdown failed", exc_info=True)
    if readiness is not None:
        try:
            await readiness.shutdown()
        except (RuntimeError, OSError, ValueError):
            LOGGER.warning("Readiness shutdown failed", exc_info=True)
    LOGGER.info("Application shutdown complete")


@asynccontextmanager
async def lifespan(
    app: FastAPI,
) -> AsyncIterator[None]:  # Complex initialization sequence required
    """Application lifespan manager with explicit configuration initialization.

    This function runs during FastAPI startup and shutdown, managing the
    configuration lifecycle explicitly rather than relying on lazy loading.

    Parameters
    ----------
    app : FastAPI
        FastAPI application instance. Used to store application context and
        readiness probe in app.state.

    Yields
    ------
    None
        Control to the FastAPI application after successful initialization.

    Raises
    ------
    ConfigurationError
        If configuration is invalid or required resources are missing.
        FastAPI will fail to start, preventing broken deployment. The exception
        includes RFC 9457 Problem Details with context fields for debugging.

    Notes
    -----
    Startup sequence:
    1. Load configuration from environment (fail fast if invalid)
    2. Perform GPU warmup sequence (verify CUDA/torch/FAISS GPU availability)
    3. Initialize long-lived clients (vLLM, FAISS manager)
    4. Initialize scope registry for session-scoped query constraints
    5. Run readiness checks (verify indexes exist, vLLM reachable)
    6. Optionally pre-load FAISS index (controlled by FAISS_PRELOAD env var)
    7. Start background pruning task for expired sessions

    Shutdown sequence:
    1. Cancel background pruning task
    2. Clear readiness state
    3. Explicitly close any open resources
    """
    LOGGER.info("Starting application initialization")
    context: ApplicationContext | None = None
    readiness: ReadinessProbe | None = None

    startup_timeline = new_timeline("startup", force=True)
    observer = TimelineRuntimeObserver(startup_timeline)
    hup_handler_installed = False
    previous_sighup = None
    try:
        with bind_timeline(startup_timeline):
            context, readiness = await _initialize_context(app, runtime_observer=observer)
        capabilities = Capabilities.from_context(context)
        app.state.capabilities = capabilities
        app.state.capability_stamp = capabilities.stamp()
        app.mount("/mcp", build_http_app(capabilities))
        main_thread = threading.current_thread() is threading.main_thread()
        if os.name != "nt" and main_thread:
            previous_sighup = signal.getsignal(signal.SIGHUP)

            def _handle_hup(
                signum: int, frame: FrameType | None
            ) -> None:  # pragma: no cover - signal path
                _ = (signum, frame)
                LOGGER.info("SIGHUP received - reloading index-backed runtimes")
                try:
                    if context is None:
                        LOGGER.warning("SIGHUP received before context initialization")
                        return
                    context.reload_indices()
                except (RuntimeError, OSError, ValueError):
                    LOGGER.warning("signal.hup.reload_failed", exc_info=True)

            signal.signal(signal.SIGHUP, _handle_hup)
            hup_handler_installed = True
        yield
    except ConfigurationError as exc:
        LOGGER.exception(
            "Application startup failed due to configuration error",
            extra={"error_code": exc.code.value, "context": exc.context},
        )
        raise
    finally:
        if (
            hup_handler_installed
            and previous_sighup is not None
            and os.name != "nt"
            and threading.current_thread() is threading.main_thread()
        ):
            with suppress(ValueError):  # pragma: no cover - defensive
                signal.signal(signal.SIGHUP, previous_sighup)
        await _shutdown_context(context, readiness)


app = FastAPI(
    title="CodeIntel MCP Gateway",
    version="0.1.0",
    lifespan=lifespan,
)
init_all_telemetry(
    app=app,
    service_name="codeintel-mcp",
    service_version=_DIST_VERSION,
)
instrument_fastapi(app)
instrument_httpx()

# CORS middleware for browser clients (handle preflight before session scope)
app.add_middleware(
    CORSMiddleware,
    allow_origins=SERVER_SETTINGS.cors_allow_origins,
    allow_credentials=SERVER_SETTINGS.cors_allow_credentials,
    allow_methods=SERVER_SETTINGS.cors_allow_methods,
    allow_headers=SERVER_SETTINGS.cors_allow_headers,
)

# Session scope middleware (must be registered after CORS to avoid preflight conflicts)
app.add_middleware(SessionScopeMiddleware)

if SERVER_SETTINGS.enable_trusted_hosts:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=SERVER_SETTINGS.allowed_hosts,
    )

metrics_router = build_metrics_router()
if metrics_router is not None:
    app.include_router(metrics_router)


if os.getenv("CODEINTEL_ADMIN", "").strip().lower() in {"1", "true", "yes", "on"}:
    app.include_router(index_admin.router)


@app.get("/reports/{session_id}")
async def get_run_report(session_id: str, run_id: str | None = None) -> dict[str, Any]:
    """Return JSON run report for the session/run identifier.

    This endpoint retrieves a run report for the specified session and optional
    run identifier. The report contains telemetry data, metrics, and execution
    details for the requested run. If no run_id is provided, returns the most
    recent run for the session.

    Parameters
    ----------
    session_id : str
        Session identifier extracted from the URL path. Used to identify the
        telemetry session containing the run report.
    run_id : str | None, optional
        Optional run identifier to retrieve a specific run report. If None
        (default), returns the most recent run for the session. Used to
        retrieve historical run reports within a session.

    Returns
    -------
    dict[str, Any]
        Run report payload serialisable to JSON containing telemetry data,
        metrics, timing information, and execution details for the requested run.
        The payload structure matches the RunReport schema.

    Raises
    ------
    HTTPException
        Raised in the following cases:
        - Status 503: Application context is not initialized (missing from app.state)
        - Status 404: Run not found for the specified session_id and run_id
    """
    context = getattr(app.state, "context", None)
    if context is None:
        raise HTTPException(status_code=503, detail="Application context not initialized")
    report = build_run_report(context, session_id, run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return report_to_json(report)


@app.get("/reports/{session_id}.md", response_class=PlainTextResponse)
async def get_run_report_markdown(session_id: str, run_id: str | None = None) -> PlainTextResponse:
    """Return Markdown run report for the session/run identifier.

    This endpoint retrieves a run report for the specified session and optional
    run identifier, formatted as Markdown. The report contains telemetry data,
    metrics, and execution details rendered in human-readable Markdown format.
    If no run_id is provided, returns the most recent run for the session.

    Parameters
    ----------
    session_id : str
        Session identifier extracted from the URL path. Used to identify the
        telemetry session containing the run report.
    run_id : str | None, optional
        Optional run identifier to retrieve a specific run report. If None
        (default), returns the most recent run for the session. Used to
        retrieve historical run reports within a session.

    Returns
    -------
    PlainTextResponse
        FastAPI PlainTextResponse containing Markdown-formatted run report body.
        The response includes telemetry data, metrics, timing information, and
        execution details rendered in Markdown format suitable for display in
        documentation or web interfaces.

    Raises
    ------
    HTTPException
        Raised in the following cases:
        - Status 503: Application context is not initialized (missing from app.state)
        - Status 404: Run not found for the specified session_id and run_id
    """
    context = getattr(app.state, "context", None)
    if context is None:
        raise HTTPException(status_code=503, detail="Application context not initialized")
    report = build_run_report(context, session_id, run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return PlainTextResponse(render_markdown(report))


@app.get("/reports/{session_id}.mmd", response_class=PlainTextResponse)
async def get_run_report_mermaid(session_id: str, run_id: str | None = None) -> PlainTextResponse:
    """Return a Mermaid representation of the run.

    Parameters
    ----------
    session_id : str
        Session identifier to retrieve the run report for.
    run_id : str | None
        Optional run identifier when multiple runs share a session. If None,
        returns the latest run for the session.

    Returns
    -------
    PlainTextResponse
        Mermaid `graph TD` body describing the run.

    Raises
    ------
    HTTPException
        Raised when the application context is not initialized or the run cannot
        be found.
    """
    context = getattr(app.state, "context", None)
    if context is None:
        raise HTTPException(status_code=503, detail="Application context not initialized")
    report = build_run_report(context, session_id, run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return PlainTextResponse(render_mermaid(report))


@app.get("/runs/{session_id}/report")
async def get_run_report_v2(session_id: str, run_id: str | None = None) -> dict[str, Any]:
    """Alias for `/reports/{session_id}` retaining backwards compatibility.

    Parameters
    ----------
    session_id : str
        Session identifier to retrieve the run report for.
    run_id : str | None
        Optional run identifier when multiple runs share a session. If None,
        returns the latest run for the session.

    Returns
    -------
    dict[str, Any]
        JSON run report payload.
    """
    return await get_run_report(session_id, run_id)


@app.get("/runs/{session_id}/report.md", response_class=PlainTextResponse)
async def get_run_report_markdown_v2(
    session_id: str, run_id: str | None = None
) -> PlainTextResponse:
    """Alias for `/reports/{session_id}.md`.

    Parameters
    ----------
    session_id : str
        Session identifier to retrieve the run report for.
    run_id : str | None
        Optional run identifier when multiple runs share a session. If None,
        returns the latest run for the session.

    Returns
    -------
    PlainTextResponse
        Markdown run report body.
    """
    return await get_run_report_markdown(session_id, run_id)


@app.get("/runs/{session_id}/report.mmd", response_class=PlainTextResponse)
async def get_run_report_mermaid_v2(
    session_id: str, run_id: str | None = None
) -> PlainTextResponse:
    """Alias for `/reports/{session_id}.mmd`.

    Parameters
    ----------
    session_id : str
        Session identifier to retrieve the run report for.
    run_id : str | None
        Optional run identifier when multiple runs share a session. If None,
        returns the latest run for the session.

    Returns
    -------
    PlainTextResponse
        Mermaid graph for the run.
    """
    return await get_run_report_mermaid(session_id, run_id)


@app.middleware("http")
async def inject_request_id(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Ensure every request carries a stable request identifier.

    Parameters
    ----------
    request : Request
        Incoming HTTP request to process.
    call_next : Callable[[Request], Awaitable[Response]]
        Next middleware or route handler in the chain.

    Returns
    -------
    Response
        Response with X-Request-Id header set to the request identifier.
    """
    incoming = request.headers.get("x-request-id", "").strip()
    request_id = incoming or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers.setdefault("X-Request-Id", request_id)
    return response


@app.middleware("http")
async def set_mcp_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Set ApplicationContext in context variable for MCP tool handlers.

    This middleware sets the ApplicationContext in a context variable that
    can be accessed by FastMCP tool handlers. FastMCP doesn't support Request
    injection directly, so we use contextvars to pass the context.

    Parameters
    ----------
    request : Request
        Incoming HTTP request from FastAPI/Starlette.
    call_next : Callable[[Request], Awaitable[Response]]
        Next middleware or route handler in the chain.

    Returns
    -------
    Response
        Response from the next handler.

    Raises
    ------
    Exception
        Propagated from `call_next()` if the downstream handler raises any
        exception. Also propagates exceptions from timeline event recording.

    Notes
    -----
    This middleware extracts the ApplicationContext from `request.app.state`
    and sets it in a context variable (`app_context`) for MCP tool handlers.
    It also records timeline events for request processing. Time complexity:
    O(1) for context variable operations, plus downstream handler time.
    """
    # Set context in context variable for MCP tool handlers
    context: ApplicationContext | None = getattr(request.app.state, "context", None)
    if context is not None:
        app_context.set(context)

    timeline = getattr(request.state, "timeline", None)
    start = perf_counter()
    try:
        with as_span("http.request", path=request.url.path, method=request.method):
            response = await call_next(request)
    except Exception as exc:
        duration_ms = int((perf_counter() - start) * 1000)
        if timeline is not None:
            timeline.event(
                "http.request",
                request.url.path,
                status="error",
                message=str(exc),
                attrs={"method": request.method},
            )
        status_code = getattr(exc, "status_code", 500)
        _log_request_summary(request, status_code=status_code, duration_ms=duration_ms)
        raise
    duration_ms = int((perf_counter() - start) * 1000)
    if timeline is not None:
        timeline.event(
            "http.request",
            request.url.path,
            attrs={
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
    _log_request_summary(request, status_code=response.status_code, duration_ms=duration_ms)
    trace_id = current_trace_id()
    if trace_id:
        response.headers.setdefault("X-Trace-Id", trace_id)
    run_id = getattr(request.state, "run_id", None) or current_run_id()
    if run_id:
        response.headers.setdefault("X-Run-Id", run_id)
    return response


@app.middleware("http")
async def disable_nginx_buffering(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Disable NGINX buffering for streaming responses.

    This middleware sets the X-Accel-Buffering header to "no" on all responses,
    which instructs NGINX to disable buffering and enable streaming. This is
    critical for Server-Sent Events (SSE) and other streaming protocols where
    backpressure and real-time delivery are important.

    The middleware runs after the request handler executes, modifying the
    response headers before it's sent to the client. This ensures that NGINX
    will stream the response directly to the client rather than buffering it
    in memory, which is essential for long-running streams and prevents memory
    issues with large responses.

    Parameters
    ----------
    request : Request
        Incoming HTTP request from FastAPI/Starlette.
    call_next : Callable[[Request], Awaitable[Response]]
        Next middleware or route handler in the chain. This is an async callable
        that takes a Request and returns an awaitable Response.

    Returns
    -------
    Response
        Response object with X-Accel-Buffering header set to "no". The response
        is the same as returned by call_next, but with the streaming header added.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Accel-Buffering", "no")
    return response


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Health check endpoint (network-only).

    Returns
    -------
    JSONResponse
        Health status.
    """
    return JSONResponse({"status": "ok"})


@app.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness check endpoint.

    Verifies that dependent services are available. This endpoint always returns
    HTTP 200, but the payload indicates whether all resources are healthy. Kubernetes
    readiness probes should check the "ready" field in the response.

    Parameters
    ----------
    request : Request
        FastAPI request object.

    Returns
    -------
    JSONResponse
        Readiness status with detailed check results.
    """
    readiness: ReadinessProbe = request.app.state.readiness
    results = await readiness.refresh()
    payload = {name: result.as_payload() for name, result in results.items()}
    overall_ready = all(result.healthy for result in results.values())
    context: ApplicationContext | None = getattr(request.app.state, "context", None)
    active_version = None
    if context is not None:
        with suppress(RuntimeError):
            active_version = context.index_manager.current_version()
    response_payload = {
        "ready": overall_ready,
        "checks": payload,
        "active_index_version": active_version,
    }
    return JSONResponse(response_payload)


@app.get("/capz")
async def capz(request: Request, *, refresh: bool = False) -> JSONResponse:
    """Return a cached capability snapshot (refreshable via query flag).

    Parameters
    ----------
    request : Request
        Incoming HTTP request from FastAPI/Starlette.
    refresh : bool, optional
        If True, forces refresh of the capability snapshot. Otherwise returns
        cached snapshot if available (default: False).

    Returns
    -------
    JSONResponse
        Capability payload with keys: capability flags (faiss_index, duckdb,
        etc.), optional hints, and stamp (SHA-256 hash). Returns 503 status
        if application context is not initialized.

    Notes
    -----
    This endpoint provides capability detection for MCP tool gating and
    monitoring. The snapshot is cached in `request.app.state.capabilities`
    and refreshed on demand or when missing. Time complexity: O(1) for cached
    responses, O(module_probe_time) for refresh.
    """
    context: ApplicationContext | None = getattr(request.app.state, "context", None)
    if context is None:
        return JSONResponse(
            {"error": "application context not initialized"},
            status_code=503,
        )
    capabilities: Capabilities | None = getattr(request.app.state, "capabilities", None)
    if refresh or capabilities is None:
        capabilities = Capabilities.from_context(context)
        request.app.state.capabilities = capabilities
        request.app.state.capability_stamp = capabilities.stamp()
    payload = capabilities.model_dump()
    stamp: str = getattr(request.app.state, "capability_stamp", capabilities.stamp(payload))
    payload["stamp"] = stamp
    return JSONResponse(payload)


async def _stream_with_logging(
    source: AsyncIterator[bytes],
    *,
    request: Request,
    stream_name: str,
) -> AsyncIterator[bytes]:
    """Wrap a streaming iterator and emit lifecycle logs for observability.

    Parameters
    ----------
    source : AsyncIterator[bytes]
        Source iterator to wrap and log.
    request : Request
        FastAPI request object for logging context.
    stream_name : str
        Name identifier for the stream being logged.

    Yields
    ------
    bytes
        Chunks from the source iterator, passed through unchanged.

    Raises
    ------
    asyncio.CancelledError
        Re-raised if the source iterator is cancelled, after logging cancellation.
    """
    LOGGER.info(
        "stream.lifecycle", extra=_stream_log_extra(request, stream_name=stream_name, stage="open")
    )
    try:
        async for chunk in source:
            if isinstance(chunk, (bytes, bytearray)):
                byte_count = len(chunk)
            elif isinstance(chunk, str):
                byte_count = len(chunk.encode("utf-8"))
            else:  # pragma: no cover - defensive path
                byte_count = 0
            LOGGER.info(
                "stream.lifecycle",
                extra=_stream_log_extra(
                    request,
                    stream_name=stream_name,
                    stage="flush",
                    chunk_bytes=byte_count,
                ),
            )
            yield chunk
    except asyncio.CancelledError:
        LOGGER.info(
            "stream.lifecycle",
            extra=_stream_log_extra(request, stream_name=stream_name, stage="cancelled"),
        )
        raise
    finally:
        LOGGER.info(
            "stream.lifecycle",
            extra=_stream_log_extra(request, stream_name=stream_name, stage="closed"),
        )


@app.get("/sse")
async def sse_demo(request: Request) -> StreamingResponse:
    """SSE streaming demo endpoint with keep-alive comments.

    Parameters
    ----------
    request : Request
        FastAPI request object for logging context.

    Returns
    -------
    StreamingResponse
        SSE stream containing ready event, 5 data events, and recurring keep-alive
        comments.
    """
    keepalive_interval = _sse_keepalive_interval()
    keepalive_budget = _sse_keepalive_budget()

    async def event_generator() -> AsyncIterator[bytes]:
        r"""Generate Server-Sent Events (SSE) stream for demo purposes.

        This generator function produces a simple SSE stream containing a ready
        event followed by 5 data events with incremental counters. Each data
        event is sent with a 0.5 second delay to demonstrate streaming behavior.
        After the initial payload burst, the generator emits keep-alive comments
        every ``SSE_KEEPALIVE_SECONDS`` so intermediaries keep the connection
        open for long-lived sessions.

        Yields
        ------
        bytes
            SSE-formatted event chunks. Each chunk is a complete SSE message
            terminated with double newlines. The first chunk is a ready event,
            followed by 5 data events containing incremental counters (0-4),
            and then recurring keep-alive comments until the client disconnects.
        """
        yield b"event: ready\ndata: {}\n\n"
        for i in range(5):
            yield f"data: {i}\n\n".encode()
            await asyncio.sleep(0.5)
        heartbeat = b": keep-alive\n\n"
        keepalive_count = 0
        while keepalive_budget is None or keepalive_count < keepalive_budget:
            await asyncio.sleep(keepalive_interval)
            yield heartbeat
            keepalive_count += 1

    return StreamingResponse(
        _stream_with_logging(event_generator(), request=request, stream_name="sse-demo"),
        media_type="text/event-stream",
    )


@app.exception_handler(HTTPException)
def http_exception_handler_with_request_id(request: Request, exc: HTTPException) -> JSONResponse:
    """Return HTTPException responses with structured payloads and request IDs.

    Parameters
    ----------
    request : Request
        FastAPI request object containing request state.
    exc : HTTPException
        HTTP exception to handle and format.

    Returns
    -------
    JSONResponse
        JSON response with error payload and X-Request-Id header if available.
    """
    headers: dict[str, str] = {}
    exc_headers = exc.headers
    if exc_headers is not None:
        headers.update(exc_headers)
    request_id = getattr(request.state, "request_id", None)
    if request_id is not None:
        headers.setdefault("X-Request-Id", request_id)
    payload: dict[str, object] = {
        "ok": False,
        "error": {"type": exc.__class__.__name__, "message": exc.detail},
    }
    if request_id is not None:
        payload["request_id"] = request_id
    return JSONResponse(payload, status_code=exc.status_code, headers=headers or None)


@app.exception_handler(Exception)
def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Wrap unhandled exceptions in a debuggable envelope.

    Parameters
    ----------
    request : Request
        FastAPI request object containing request state.
    exc : Exception
        Unhandled exception to wrap and log.

    Returns
    -------
    JSONResponse
        JSON response with error payload (status 500) and X-Request-Id header
        if available.
    """
    request_id = getattr(request.state, "request_id", None)
    stacktrace = "".join(traceback.format_exception(exc.__class__, exc, exc.__traceback__))
    LOGGER.error(
        "http.unhandled_exception",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "client_addr": _client_address(request),
            "stacktrace": stacktrace,
        },
    )
    payload: dict[str, object] = {
        "ok": False,
        "error": {"type": exc.__class__.__name__, "message": str(exc)},
    }
    if request_id is not None:
        payload["request_id"] = request_id
    headers: dict[str, str] = {}
    if request_id is not None:
        headers["X-Request-Id"] = request_id
    return JSONResponse(payload, status_code=500, headers=headers or None)


if SERVER_SETTINGS.enable_proxy_fix:
    proxy_wrapped = ProxyFixMiddleware(
        cast("ASGIFramework", app),
        mode=SERVER_SETTINGS.proxy_mode,
        trusted_hops=SERVER_SETTINGS.proxy_trusted_hops,
    )
    asgi: ASGIApp = cast("ASGIApp", proxy_wrapped)
else:  # pragma: no cover - wrapper disabled via config
    asgi = cast("ASGIApp", app)


__all__ = ["app", "asgi"]
