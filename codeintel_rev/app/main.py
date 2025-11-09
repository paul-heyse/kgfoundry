"""FastAPI application with MCP server mount.

Provides health/readiness endpoints, CORS, and streaming support.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.gpu_warmup import warmup_gpu
from codeintel_rev.app.middleware import SessionScopeMiddleware
from codeintel_rev.app.readiness import ReadinessProbe
from codeintel_rev.mcp_server.server import app_context
from codeintel_rev.mcp_server.server import asgi_app as mcp_asgi
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
        FastAPI will fail to start, preventing broken deployment.
    Exception
        If an unexpected error occurs during application startup. The error
        is logged and re-raised to prevent FastAPI from starting in a broken state.

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

    try:
        # Phase 1: Load configuration
        context = ApplicationContext.create()
        app.state.context = context

        # Phase 2: GPU warmup sequence
        gpu_status = warmup_gpu()
        if gpu_status["overall_status"] == "ready":
            LOGGER.info("GPU warmup successful - GPU acceleration available")
        elif gpu_status["overall_status"] == "degraded":
            LOGGER.warning(
                "GPU warmup partial - some GPU features unavailable: %s",
                gpu_status["details"],
            )
        else:
            LOGGER.info("GPU warmup indicates GPU unavailable - continuing with CPU-only mode")

        # Phase 3: Initialize readiness probe
        readiness = ReadinessProbe(context)
        await readiness.initialize()
        app.state.readiness = readiness

        # Phase 4: Optional FAISS preloading (controlled by env var)
        if context.settings.index.faiss_preload:
            LOGGER.info("Pre-loading FAISS index during startup")
            preload_success = await asyncio.to_thread(_preload_faiss_index, context)
            if not preload_success:
                LOGGER.warning("FAISS index pre-load failed; will lazy-load on first search")

        LOGGER.info("Application initialization complete")

    except ConfigurationError as exc:
        # Log structured error and re-raise to prevent FastAPI from starting
        LOGGER.exception(
            "Application startup failed due to configuration error",
            extra={"error_code": exc.code.value, "context": exc.context},
        )
        raise
    except Exception as exc:
        LOGGER.exception("Unexpected error during application startup")
        raise exc  # noqa: TRY201

    try:
        yield
    finally:
        LOGGER.info("Starting application shutdown")
        # Shutdown: close VLLMClient HTTP connections to prevent resource leaks
        # The persistent HTTP client must be explicitly closed to release
        # network connections and avoid connection pool exhaustion
        context.vllm_client.close()
        LOGGER.debug("VLLMClient HTTP connections closed during shutdown")
        await context.scope_store.close()
        await readiness.shutdown()
        LOGGER.info("Application shutdown complete")


app = FastAPI(
    title="CodeIntel MCP Gateway",
    version="0.1.0",
    lifespan=lifespan,
)

# Session scope middleware (must be registered early, before other middleware)
app.add_middleware(SessionScopeMiddleware)

# CORS middleware for browser clients
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
    """
    # Set context in context variable for MCP tool handlers
    context: ApplicationContext | None = getattr(request.app.state, "context", None)
    if context is not None:
        app_context.set(context)

    return await call_next(request)


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
    return JSONResponse({"ready": overall_ready, "checks": payload})


@app.get("/sse")
async def sse_demo() -> StreamingResponse:
    """SSE streaming demo endpoint.

    Returns
    -------
    StreamingResponse
        Server-sent events stream.
    """

    async def event_generator() -> AsyncIterator[bytes]:
        yield b"event: ready\ndata: {}\n\n"
        for i in range(5):
            yield f"data: {i}\n\n".encode()
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


# Mount MCP server at /mcp
app.mount("/mcp", mcp_asgi)

__all__ = ["app"]
