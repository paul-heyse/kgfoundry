"""Session management middleware for CodeIntel MCP.

This module provides FastAPI middleware for extracting or generating session IDs
and storing them in thread-local context variables for access by MCP tool adapters.

Key Components
--------------
SessionScopeMiddleware : class
    Middleware that processes X-Session-ID header and populates ContextVar.
session_id_var : ContextVar[str | None]
    Thread-local storage for current request's session ID.
get_session_id : function
    Helper to retrieve session ID from ContextVar (raises if not set).

Design Principles
-----------------
- **Thread-Local Isolation**: ContextVar ensures session IDs don't leak across threads
- **Fail-Safe Defaults**: Auto-generates UUID if client doesn't provide session ID
- **FastMCP Compatibility**: Works around FastMCP's lack of Request injection in tools
- **Explicit Dependencies**: No global state; session ID accessed via explicit get_session_id()

Middleware Flow
---------------
1. Extract X-Session-ID header from request
2. Generate UUID if header absent
3. Store in request.state.session_id (FastAPI convention)
4. Store in session_id_var (ContextVar for thread-local access)
5. Invoke next middleware/handler
6. Return response (no header modification—FastMCP limitation)

Example Usage
-------------
Register middleware in FastAPI application:

>>> from codeintel_rev.app.middleware import SessionScopeMiddleware
>>> app.add_middleware(SessionScopeMiddleware)

Access session ID in adapter:

>>> from codeintel_rev.app.middleware import get_session_id
>>> async def my_adapter(context: ApplicationContext, ...) -> dict:
...     session_id = get_session_id()
...     scope = await context.scope_store.get(session_id)
...     # ... use scope

See Also
--------
codeintel_rev.app.scope_store : ScopeStore for storing session scopes
codeintel_rev.mcp_server.scope_utils : Utilities for retrieving and merging scopes
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, DispatchFunction
from starlette.types import ASGIApp

from codeintel_rev.runtime.request_context import capability_stamp_var, session_id_var
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

LOGGER = get_logger(__name__)


def get_session_id() -> str:
    """Retrieve session ID from thread-local context.

    This helper is called by adapters to access the session ID set by
    SessionScopeMiddleware. It should only be called within request handlers—
    calling it outside a request context raises RuntimeError.

    Returns
    -------
    str
        Session ID for the current request (UUID format).

    Raises
    ------
    RuntimeError
        If called outside request context (session ID not set by middleware).
        This indicates middleware is not registered or adapter is called
        directly without going through FastAPI request handling.

    Examples
    --------
    In an adapter function:

    >>> async def my_adapter(context: ApplicationContext) -> dict:
    ...     session_id = get_session_id()  # Retrieves from ContextVar
    ...     scope = await context.scope_store.get(session_id)
    ...     # ... process with scope

    Outside request context (error case):

    >>> get_session_id()  # doctest: +SKIP
    Traceback (most recent call last):
        ...
    RuntimeError: Session ID not initialized—ensure SessionScopeMiddleware is registered

    Notes
    -----
    ContextVar provides thread-local storage that is automatically copied to
    child tasks in asyncio, ensuring session ID propagates correctly through
    await calls and background tasks spawned from the request handler.
    """
    session_id = session_id_var.get()
    if session_id is None:
        msg = (
            "Session ID not initialized in request context. "
            "Ensure SessionScopeMiddleware is registered in FastAPI app."
        )
        raise RuntimeError(msg)
    return session_id


def get_capability_stamp() -> str | None:
    """Return the capability stamp associated with the current request.

    Returns
    -------
    str | None
        Stable capability hash when initialized, otherwise ``None`` if the
        stamp has not been stored in the current context.
    """
    return capability_stamp_var.get()


class SessionScopeMiddleware(BaseHTTPMiddleware):
    """Middleware for session ID extraction and context storage.

    Processes every request to extract or generate a session ID, then stores
    it in both request.state (FastAPI convention) and a ContextVar (for
    FastMCP tool access). Session IDs enable stateful scope management across
    multiple MCP tool calls within the same session.

    This middleware is stateless and does not maintain any instance attributes.

    Parameters
    ----------
    app : ASGIApp
        ASGI application to wrap with middleware.
    dispatch : DispatchFunction | None, optional
        Optional custom dispatch function for the middleware. If None, uses the
        default dispatch from BaseHTTPMiddleware. Defaults to None.

    Notes
    -----
    Middleware Order:
    - SessionScopeMiddleware should be registered early in the middleware stack
      (before tool handlers) to ensure session ID is available.
    - If other middleware needs session ID, register it after SessionScope.

    Session ID Generation:
    - UUIDs are generated using uuid.uuid4() (random, 122 bits of entropy).
    - Collision probability is negligible for practical session counts (<2^61).

    Why Not Response Header:
    - FastMCP doesn't provide a way to customize response headers from tool
      handlers, so we return session_id in the response body instead.
    - Future: If FastMCP adds response customization, add X-Session-ID header.

    Examples
    --------
    Register middleware in application:

    >>> from fastapi import FastAPI
    >>> from codeintel_rev.app.middleware import SessionScopeMiddleware
    >>> app = FastAPI()
    >>> app.add_middleware(SessionScopeMiddleware)

    Send request with session ID:

    >>> import httpx
    >>> headers = {"X-Session-ID": "my-custom-session-123"}
    >>> response = httpx.post("/mcp/tools/set_scope", headers=headers, ...)

    Send request without session ID (auto-generated):

    >>> response = httpx.post("/mcp/tools/set_scope", ...)
    >>> session_id = response.json()["session_id"]  # Use for subsequent requests
    """

    def __init__(self, app: ASGIApp, dispatch: DispatchFunction | None = None) -> None:
        super().__init__(app, dispatch)
        self._logger = LOGGER

    async def dispatch(  # Required instance method for BaseHTTPMiddleware
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process request and inject session ID.

        Extracts X-Session-ID header or generates UUID, stores in request.state
        and ContextVar, then invokes next middleware/handler.

        Parameters
        ----------
        request : Request
            Starlette Request object with headers and state.
        call_next : Callable[[Request], Awaitable[Response]]
            Next middleware or route handler in the chain. Must be an async
            callable that accepts a Request and returns an awaitable Response.

        Returns
        -------
        Response
            Response from downstream handler (unmodified).

        Notes
        -----
        The middleware is async to support FastAPI's async route handlers.
        Even if adapters are sync functions, FastAPI wraps them in asyncio.to_thread.
        """
        # Extract session ID from header or generate
        session_id = request.headers.get("X-Session-ID")
        if session_id is None:
            session_id = str(uuid.uuid4())
            self._logger.debug(
                "Generated session ID for request",
                extra={"session_id": session_id, "path": request.url.path},
            )
        else:
            self._logger.debug(
                "Using client-provided session ID",
                extra={"session_id": session_id, "path": request.url.path},
            )

        run_id = request.headers.get("X-Run-ID")
        if run_id is None:
            run_id = uuid.uuid4().hex
        else:
            self._logger.debug(
                "Using client-provided run ID",
                extra={"run_id": run_id, "path": request.url.path},
            )

        request.state.session_id = session_id
        request.state.run_id = run_id

        capability_stamp = getattr(request.app.state, "capability_stamp", None)

        session_token = session_id_var.set(session_id)
        capability_token = capability_stamp_var.set(capability_stamp)
        try:
            response = await call_next(request)
        finally:
            session_id_var.reset(session_token)
            capability_stamp_var.reset(capability_token)
        response.headers.setdefault("X-Run-Id", run_id)
        response.headers.setdefault("X-Session-Id", session_id)
        return response


__all__ = [
    "SessionScopeMiddleware",
    "capability_stamp_var",
    "get_capability_stamp",
    "get_session_id",
    "session_id_var",
]
