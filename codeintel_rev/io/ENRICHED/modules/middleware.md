# app/middleware.py

## Docstring

```
Session management middleware for CodeIntel MCP.

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
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import time
- from **(absolute)** import uuid
- from **datetime** import UTC, datetime
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING
- from **starlette.middleware.base** import BaseHTTPMiddleware, DispatchFunction
- from **starlette.types** import ASGIApp
- from **codeintel_rev.observability.ledger** import RunLedger, dated_run_dir
- from **codeintel_rev.observability.otel** import current_trace_id, set_current_span_attrs
- from **codeintel_rev.observability.runtime_observer** import bind_run_ledger
- from **codeintel_rev.observability.semantic_conventions** import Attrs
- from **codeintel_rev.observability.timeline** import bind_timeline, new_timeline
- from **codeintel_rev.runtime.request_context** import capability_stamp_var, session_id_var
- from **codeintel_rev.telemetry.context** import telemetry_context
- from **codeintel_rev.telemetry.reporter** import start_run
- from **kgfoundry_common.logging** import get_logger
- from **collections.abc** import Awaitable, Callable
- from **starlette.requests** import Request
- from **starlette.responses** import Response

## Definitions

- variable: `LOGGER` (line 79)
- function: `get_session_id` (line 82)
- function: `get_capability_stamp` (line 133)
- class: `SessionScopeMiddleware` (line 145)

## Graph Metrics

- **fan_in**: 6
- **fan_out**: 9
- **cycle_group**: 47

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 16
- recent churn 90: 16

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

SessionScopeMiddleware, capability_stamp_var, get_capability_stamp, get_session_id, session_id_var

## Doc Health

- **summary**: Session management middleware for CodeIntel MCP.
- has summary: yes
- param parity: yes
- examples present: yes

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

- score: 2.40

## Side Effects

- filesystem

## Complexity

- branches: 10
- cyclomatic: 11
- loc: 332

## Doc Coverage

- `get_session_id` (function): summary=yes, params=ok, examples=yes — Retrieve session ID from thread-local context.
- `get_capability_stamp` (function): summary=yes, params=ok, examples=no — Return the capability stamp associated with the current request.
- `SessionScopeMiddleware` (class): summary=yes, examples=yes — Middleware for session ID extraction and context storage.

## Tags

low-coverage, public-api
