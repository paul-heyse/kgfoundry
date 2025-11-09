"""Centralized error handling for CodeIntel MCP server.

This module provides the unified error handling infrastructure for all MCP tools,
ensuring consistent error responses with RFC 9457 Problem Details compliance and
structured logging for observability.

Architecture
------------
The error handling follows a three-layer pattern:

1. **Adapter Layer**: Pure domain logic that raises typed exceptions
2. **Decorator Layer**: Automatic exception → envelope conversion
3. **Client Layer**: Uniform error envelope with Problem Details

All MCP tool functions are decorated with ``@handle_adapter_errors`` which
catches all exceptions, converts them to Problem Details, logs with structured
context, and returns a unified error envelope.

Examples
--------
Applying decorator to MCP tool:

>>> @mcp.tool()
>>> @handle_adapter_errors(
...     operation="files:open_file", empty_result={"path": "", "content": "", "lines": 0, "size": 0}
... )
... def open_file(path: str, start_line: int | None, end_line: int | None) -> dict:
...     context = get_context()
...     return files_adapter.open_file(context, path, start_line, end_line)

Error envelope structure:

>>> # On success:
>>> {"path": "src/main.py", "content": "...", "lines": 10, "size": 234}
>>>
>>> # On error (FileNotFoundError):
>>> {
...     "path": "",
...     "content": "",
...     "lines": 0,
...     "size": 0,
...     "error": "File not found: src/main.py",
...     "problem": {
...         "type": "https://kgfoundry.dev/problems/file-not-found",
...         "title": "File Not Found",
...         "status": 404,
...         "detail": "File not found: src/main.py",
...         "instance": "urn:codeintel:files:open_file",
...         "code": "file-not-found",
...     },
... }
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import wraps
from typing import TYPE_CHECKING, TypeVar, cast

from kgfoundry_common.errors import KgFoundryError
from kgfoundry_common.logging import get_logger, with_fields
from kgfoundry_common.problem_details import build_problem_details

if TYPE_CHECKING:
    from kgfoundry_common.problem_details import ProblemDetails

LOGGER = get_logger(__name__)
COMPONENT_NAME = "codeintel_mcp"

F = TypeVar("F", bound=Callable[..., object])


def convert_exception_to_envelope(
    exc: Exception,
    operation: str,
    empty_result: Mapping[str, object],
) -> dict:
    """Convert exception to unified error envelope with Problem Details.

    This function is the single source of truth for exception → envelope
    conversion. It handles all exception types (KgFoundryError subclasses,
    builtin exceptions, unknown exceptions) and produces a consistent error
    structure with RFC 9457 Problem Details compliance.

    The error envelope includes:
    - All fields from ``empty_result`` (tool-specific fields with empty/zero values)
    - ``error`` field with human-readable message
    - ``problem`` field with RFC 9457 Problem Details

    Parameters
    ----------
    exc : Exception
        Exception to convert. Can be any exception type - KgFoundryError
        subclasses are handled specially, builtin exceptions (FileNotFoundError,
        ValueError, etc.) are mapped to standard Problem Details, unknown
        exceptions are mapped to 500 Internal Error.
    operation : str
        Operation identifier in format "category:operation" (e.g.,
        "files:open_file", "search:text"). Used for Problem Details instance
        field and structured logging.
    empty_result : Mapping[str, object]
        Tool-specific result fields with empty/zero values. These are merged
        into the error envelope so clients always see the same field structure.
        Example: ``{"path": "", "content": "", "lines": 0, "size": 0}``

    Returns
    -------
    dict
        Error envelope with:

        - All fields from ``empty_result`` (empty/zero values)
        - ``error: str`` - Human-readable error message
        - ``problem: ProblemDetails`` - RFC 9457 Problem Details with type,
          title, status, detail, instance, code, and optional extensions

    Notes
    -----
    Exception Mapping:

    - **KgFoundryError**: Uses ``to_problem_details()`` method. HTTP status,
      error code, and context from exception fields. Logged at exception's
      log_level with structured context.
    - **FileNotFoundError**: 404 Not Found, code "file-not-found". Logged
      at WARNING level.
    - **UnicodeDecodeError**: 415 Unsupported Media Type, code
      "unsupported-encoding". Encoding and reason in extensions. Logged at
      WARNING level.
    - **ValueError**: 400 Bad Request, code "invalid-parameter". Logged at
      WARNING level.
    - **Unknown exceptions**: 500 Internal Server Error, code "internal-error".
      Exception type in extensions. Logged at EXCEPTION level (includes stack
      trace).

    Structured Logging:

    All exceptions are logged with structured context:

    - KgFoundryError: ``operation``, ``error_code``, ``component``
    - Builtin exceptions: ``operation``, ``component``, ``error``
    - Unknown exceptions: ``operation``, ``component``, ``exception_type``

    Examples
    --------
    Convert FileNotFoundError:

    >>> exc = FileNotFoundError("File not found: src/main.py")
    >>> envelope = convert_exception_to_envelope(
    ...     exc,
    ...     operation="files:open_file",
    ...     empty_result={"path": "", "content": "", "lines": 0, "size": 0},
    ... )
    >>> envelope["error"]
    'File not found: src/main.py'
    >>> envelope["problem"]["status"]
    404
    >>> envelope["problem"]["code"]
    'file-not-found'
    >>> envelope["path"]
    ''

    Convert KgFoundryError with context:

    >>> from kgfoundry_common.errors import VectorSearchError
    >>> exc = VectorSearchError("Search timeout", context={"query": "def main"})
    >>> envelope = convert_exception_to_envelope(
    ...     exc, operation="search:text", empty_result={"matches": [], "total": 0}
    ... )
    >>> envelope["problem"]["extensions"]["query"]
    'def main'
    """
    problem: ProblemDetails

    # KgFoundryError: Use built-in Problem Details conversion
    if isinstance(exc, KgFoundryError):
        problem = exc.to_problem_details(instance=operation)
        with with_fields(
            LOGGER,
            component=COMPONENT_NAME,
            operation=operation,
            error_code=exc.code.value,
        ) as adapter:
            adapter.log(exc.log_level, exc.message, extra={"context": exc.context})

    # FileNotFoundError: 404 Not Found
    elif isinstance(exc, FileNotFoundError):
        problem = build_problem_details(
            problem_type="https://kgfoundry.dev/problems/file-not-found",
            title="File Not Found",
            status=404,
            detail=str(exc),
            instance=operation,
            code="file-not-found",
        )
        LOGGER.warning(
            "File not found",
            extra={
                "component": COMPONENT_NAME,
                "operation": operation,
                "error": str(exc),
            },
        )

    # UnicodeDecodeError: 415 Unsupported Media Type (binary file)
    elif isinstance(exc, UnicodeDecodeError):
        problem = build_problem_details(
            problem_type="https://kgfoundry.dev/problems/unsupported-encoding",
            title="Unsupported Encoding",
            status=415,
            detail=f"Binary file or encoding error: {exc.reason}",
            instance=operation,
            code="unsupported-encoding",
            extensions={"encoding": exc.encoding, "reason": exc.reason},
        )
        LOGGER.warning(
            "Encoding error",
            extra={
                "component": COMPONENT_NAME,
                "operation": operation,
                "encoding": exc.encoding,
                "reason": exc.reason,
            },
        )

    # ValueError: 400 Bad Request (invalid parameters)
    elif isinstance(exc, ValueError):
        problem = build_problem_details(
            problem_type="https://kgfoundry.dev/problems/invalid-parameter",
            title="Invalid Parameter",
            status=400,
            detail=str(exc),
            instance=operation,
            code="invalid-parameter",
        )
        LOGGER.warning(
            "Invalid parameter",
            extra={
                "component": COMPONENT_NAME,
                "operation": operation,
                "error": str(exc),
            },
        )

    # Unknown exception: 500 Internal Server Error
    # This catches all unexpected exceptions (RuntimeError, AttributeError, etc.)
    else:
        problem = build_problem_details(
            problem_type="https://kgfoundry.dev/problems/internal-error",
            title="Internal Error",
            status=500,
            detail=str(exc),
            instance=operation,
            code="internal-error",
            extensions={"exception_type": type(exc).__name__},
        )
        LOGGER.error(
            "Unexpected error",
            extra={
                "component": COMPONENT_NAME,
                "operation": operation,
                "exception_type": type(exc).__name__,
            },
        )

    # Build envelope: empty result fields + error + problem
    envelope = dict(empty_result)
    envelope["error"] = problem["detail"]
    envelope["problem"] = problem

    return envelope


def handle_adapter_errors(
    *,
    operation: str,
    empty_result: Mapping[str, object],
) -> Callable[[F], F]:
    """Convert adapter exceptions to unified error envelopes.

    This decorator is applied to all MCP tool functions to provide automatic
    error handling. It catches all exceptions raised by adapters and converts
    them to consistent error envelopes with Problem Details.

    The decorator:

    1. Catches ALL exceptions (no exception escapes)
    2. Converts exception → Problem Details → error envelope
    3. Logs with structured context (operation, error_code, etc.)
    4. Returns error envelope (does not re-raise)
    5. Preserves function signature (important for FastMCP schema generation)

    Parameters
    ----------
    operation : str
        Operation identifier in format "category:operation". Examples:

        - "files:open_file"
        - "files:list_paths"
        - "search:text"
        - "search:semantic"
        - "git:blame_range"
        - "git:file_history"

        Used for Problem Details instance field and structured logging.
    empty_result : Mapping[str, object]
        Tool-specific result fields with empty/zero values. These are merged
        into the error envelope so clients always see the same field structure
        (just with empty values on error).

    Examples
    --------
        - open_file: ``{"path": "", "content": "", "lines": 0, "size": 0}``
        - list_paths: ``{"items": [], "total": 0, "truncated": False}``
        - blame_range: ``{"blame": []}``
        - file_history: ``{"commits": []}``
        - search_text: ``{"matches": [], "total": 0, "truncated": False}``
        - semantic_search: ``{"findings": [], "answer": "", "confidence": 0.0}``

    Returns
    -------
    Callable[[F], F]
        Decorator function that wraps the adapter call in try/except and
        converts exceptions to error envelopes. Preserves the function type
        signature ``F``.

    Notes
    -----
    Decorator Order:

    The decorator MUST be applied AFTER ``@mcp.tool()`` so FastMCP sees the
    unwrapped function signature for JSON Schema generation:

    .. code-block:: python

        @mcp.tool()  # FIRST
        @handle_adapter_errors(...)  # SECOND
        def my_tool(...):
            ...

    Function Signature Preservation:

    The decorator uses ``functools.wraps`` to preserve the function's
    ``__name__``, ``__doc__``, and ``__annotations__``. This is critical for
    FastMCP's automatic JSON Schema generation.

    Async Function Compatibility:

    The decorator works with both sync and async functions. Async functions
    should use ``async def`` and the decorator will properly await the result.

    Examples
    --------
    Sync function:

    >>> @mcp.tool()
    >>> @handle_adapter_errors(
    ...     operation="files:open_file",
    ...     empty_result={"path": "", "content": "", "lines": 0, "size": 0},
    ... )
    ... def open_file(path: str, start_line: int | None, end_line: int | None) -> dict:
    ...     context = get_context()
    ...     return files_adapter.open_file(context, path, start_line, end_line)

    Async function:

    >>> @mcp.tool()
    >>> @handle_adapter_errors(operation="git:blame_range", empty_result={"blame": []})
    ... async def blame_range(path: str, start_line: int, end_line: int) -> dict:
    ...     context = get_context()
    ...     return await history_adapter.blame_range(context, path, start_line, end_line)

    Success case (no exception):

    >>> @handle_adapter_errors(operation="test", empty_result={"value": 0})
    ... def func():
    ...     return {"value": 42}
    >>> result = func()
    >>> result
    {'value': 42}

    Error case (exception raised):

    >>> @handle_adapter_errors(operation="test", empty_result={"value": 0})
    ... def func():
    ...     raise FileNotFoundError("File not found")
    >>> result = func()
    >>> result["error"]
    'File not found'
    >>> result["problem"]["status"]
    404
    >>> result["value"]
    0
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: object, **kwargs: object) -> dict:
            try:
                return func(*args, **kwargs)  # type: ignore[return-value]
            except (
                BaseException
            ) as exc:
                return convert_exception_to_envelope(exc, operation, empty_result)

        return cast("F", wrapper)

    return decorator


__all__ = [
    "convert_exception_to_envelope",
    "handle_adapter_errors",
]
