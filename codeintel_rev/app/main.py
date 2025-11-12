"""FastAPI application with MCP server mount.

Provides health/readiness endpoints, CORS, and streaming support.
"""

from __future__ import annotations

import asyncio
import os
import signal
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from time import perf_counter
from types import FrameType

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.gpu_warmup import warmup_gpu
from codeintel_rev.app.middleware import SessionScopeMiddleware
from codeintel_rev.app.readiness import ReadinessProbe
from codeintel_rev.app.routers import index_admin
from codeintel_rev.errors import RuntimeUnavailableError
from codeintel_rev.mcp_server.server import app_context, build_http_app
from codeintel_rev.observability.otel import as_span, init_telemetry
from codeintel_rev.observability.runtime_observer import TimelineRuntimeObserver
from codeintel_rev.observability.timeline import bind_timeline, new_timeline
from codeintel_rev.runtime.cells import RuntimeCellObserver
from kgfoundry_common.errors import ConfigurationError
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)


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
    _log_gpu_warmup(warmup_gpu())
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
        init_telemetry(app)
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

# CORS middleware for browser clients (handle preflight before session scope)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://chat.openai.com",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session scope middleware (must be registered after CORS to avoid preflight conflicts)
app.add_middleware(SessionScopeMiddleware)


@app.get("/metrics")
async def metrics_endpoint() -> Response:
    """Expose Prometheus metrics for scraping.

    Returns
    -------
    Response
        Text-based metrics payload encoded in Prometheus exposition format.
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


if os.getenv("CODEINTEL_ADMIN", "").strip().lower() in {"1", "true", "yes", "on"}:
    app.include_router(index_admin.router)


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
        if timeline is not None:
            timeline.event(
                "http.request",
                request.url.path,
                status="error",
                message=str(exc),
                attrs={"method": request.method},
            )
        raise
    if timeline is not None:
        duration_ms = int((perf_counter() - start) * 1000)
        timeline.event(
            "http.request",
            request.url.path,
            attrs={
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
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


@app.get("/sse")
async def sse_demo() -> StreamingResponse:
    """SSE streaming demo endpoint.

    Returns
    -------
    StreamingResponse
        Server-sent events stream.
    """

    async def event_generator() -> AsyncIterator[bytes]:
        r"""Generate Server-Sent Events (SSE) stream for demo purposes.

        This generator function produces a simple SSE stream containing a ready
        event followed by 5 data events with incremental counters. Each data
        event is sent with a 0.5 second delay to demonstrate streaming behavior.
        The stream follows the SSE format: "event: <name>\ndata: <payload>\n\n"
        for named events, or "data: <payload>\n\n" for data-only events.

        Yields
        ------
        bytes
            SSE-formatted event chunks. Each chunk is a complete SSE message
            terminated with double newlines. The first chunk is a ready event,
            followed by 5 data events containing incremental counters (0-4).

        Notes
        -----
        This is a demo endpoint for testing SSE streaming functionality. The
        generator demonstrates proper SSE formatting and async streaming behavior.
        Time complexity: O(1) per event, total duration ~2.5 seconds (5 events
        * 0.5s delay). The function performs async I/O (asyncio.sleep) and yields
        control to the event loop between events.
        """
        yield b"event: ready\ndata: {}\n\n"
        for i in range(5):
            yield f"data: {i}\n\n".encode()
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


__all__ = ["app"]
