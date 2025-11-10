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
>>> def my_adapter(context: ApplicationContext, ...) -> dict:
...     session_id = get_session_id()
...     scope = context.scope_registry.get_scope(session_id)
...     # ... use scope

See Also
--------
codeintel_rev.app.scope_registry : ScopeRegistry for storing session scopes
codeintel_rev.mcp_server.scope_utils : Utilities for retrieving and merging scopes
"""

from __future__ import annotations

import contextvars
import uuid
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request
    from starlette.responses import Response

LOGGER = get_logger(__name__)

# Thread-local storage for session ID
# FastMCP doesn't expose Request in tool functions, so we use ContextVar
# for thread-safe session ID access in adapters
session_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "session_id", default=None
)


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

    >>> def my_adapter(context: ApplicationContext) -> dict:
    ...     session_id = get_session_id()  # Retrieves from ContextVar
    ...     scope = context.scope_registry.get_scope(session_id)
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


class SessionScopeMiddleware(BaseHTTPMiddleware):
    """Middleware for session ID extraction and context storage.

    Processes every request to extract or generate a session ID, then stores
    it in both request.state (FastAPI convention) and a ContextVar (for
    FastMCP tool access). Session IDs enable stateful scope management across
    multiple MCP tool calls within the same session.

    Notes
    -----
    This middleware is stateless and does not maintain any instance attributes.

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

    @staticmethod
    async def dispatch(request: Request, call_next: Callable[[Request], Response]) -> Response:
        """Process request and inject session ID.

        Extracts X-Session-ID header or generates UUID, stores in request.state
        and ContextVar, then invokes next middleware/handler.

        Parameters
        ----------
        request : Request
            Starlette Request object with headers and state.
        call_next : Callable[[Request], Response]
            Next middleware or route handler in the chain.

        Returns
        -------
        Response
            Response from downstream handler (unmodified).

        Notes
        -----
        The middleware is async to support FastAPI's async route handlers.
        Even if adapters are sync functions, FastAPI wraps them in asyncio.to_thread.
        """
        session_id = SessionScopeMiddleware._fetch_or_generate_session_id(request)
        SessionScopeMiddleware._persist_session_id(request, session_id)
        return await call_next(request)

    @staticmethod
    def _fetch_or_generate_session_id(request: Request) -> str:
        """Return the session ID extracted from headers or generated.

        Returns
        -------
        str
            Session identifier used to scope queries.
        """
        session_id = request.headers.get("X-Session-ID")
        log_extra = {"path": request.url.path}
        if session_id is None:
            session_id = str(uuid.uuid4())
            LOGGER.debug(
                "Generated session ID for request",
                extra={**log_extra, "session_id": session_id},
            )
        else:
            LOGGER.debug(
                "Using client-provided session ID",
                extra={**log_extra, "session_id": session_id},
            )
        return session_id

    @staticmethod
    def _persist_session_id(request: Request, session_id: str) -> None:
        """Store the session ID on the request state and ContextVar."""
        request.state.session_id = session_id
        session_id_var.set(session_id)


__all__ = ["SessionScopeMiddleware", "get_session_id", "session_id_var"]
