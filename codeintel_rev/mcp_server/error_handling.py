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

import inspect
import traceback
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import wraps
from http import HTTPStatus
from typing import TYPE_CHECKING, TypeVar, cast

from codeintel_rev.errors import PathNotDirectoryError, PathNotFoundError
from codeintel_rev.io.path_utils import PathOutsideRepositoryError
from codeintel_rev.observability.otel import record_span_event
from codeintel_rev.telemetry.context import current_run_id
from codeintel_rev.telemetry.steps import StepEvent, emit_step
from kgfoundry_common.errors import KgFoundryError
from kgfoundry_common.logging import get_logger, with_fields
from kgfoundry_common.problem_details import build_problem_details

if TYPE_CHECKING:
    from kgfoundry_common.problem_details import ProblemDetails

LOGGER = get_logger(__name__)
COMPONENT_NAME = "codeintel_mcp"

F = TypeVar("F", bound=Callable[..., object])

# Comprehensive list of user exceptions that can be raised by adapters
# System-level exceptions (KeyboardInterrupt, SystemExit, GeneratorExit) are excluded
# as they should propagate naturally
_USER_EXCEPTIONS = (
    # Built-in exceptions
    Exception,
    # Common built-in subclasses
    ValueError,
    TypeError,
    AttributeError,
    KeyError,
    IndexError,
    FileNotFoundError,
    PermissionError,
    OSError,
    RuntimeError,
    NotImplementedError,
    UnicodeDecodeError,
    UnicodeEncodeError,
    LookupError,
    ArithmeticError,
    ReferenceError,
    StopIteration,
    StopAsyncIteration,
    SyntaxError,
    # Custom exceptions
    KgFoundryError,
    PathOutsideRepositoryError,
    PathNotDirectoryError,
    PathNotFoundError,
)


@dataclass(frozen=True)
class ProblemMapping:
    """Mapping from exception type to RFC 9457 Problem Details metadata.

    Extended Summary
    ----------------
    This dataclass encapsulates the mapping between Python exception types and
    RFC 9457 Problem Details fields (code, title, status). It is used by the
    error handling infrastructure to convert exceptions into standardized Problem
    Details responses. The mapping is immutable and used as a lookup key in
    EXCEPTION_TO_ERROR_CODE to determine appropriate HTTP status codes and error
    codes for different exception types.

    Attributes
    ----------
    code : str
        Machine-readable error code identifier (e.g., "path-not-found",
        "invalid-parameter"). Used in Problem Details "code" field and for
        structured logging. Should be kebab-case and descriptive.
    title : str
        Human-readable error title (e.g., "Path Not Found", "Invalid Parameter").
        Used in Problem Details "title" field. Should be title-case and concise.
    status : int
        HTTP status code (e.g., 404, 400, 500). Must be a valid HTTP status code
        (100-599). Used in Problem Details "status" field and HTTP response
        status. Common values: 400 (Bad Request), 404 (Not Found), 500 (Internal
        Server Error).

    Notes
    -----
    This mapping is used by format_error_response() to convert exceptions into
    Problem Details. The code should match the problem type URI suffix (e.g.,
    "path-not-found" maps to "https://kgfoundry.dev/problems/path-not-found").
    Status codes follow RFC 7231 semantics: 4xx for client errors, 5xx for server
    errors.
    """

    code: str
    title: str
    status: int


EXCEPTION_TO_ERROR_CODE: dict[type[BaseException], ProblemMapping] = {
    PathOutsideRepositoryError: ProblemMapping(
        "path-outside-repo", "Path Outside Repository", HTTPStatus.BAD_REQUEST
    ),
    PathNotDirectoryError: ProblemMapping(
        "path-not-directory", "Path Not Directory", HTTPStatus.BAD_REQUEST
    ),
    PathNotFoundError: ProblemMapping("path-not-found", "Path Not Found", HTTPStatus.NOT_FOUND),
    FileNotFoundError: ProblemMapping("path-not-found", "Path Not Found", HTTPStatus.NOT_FOUND),
    ValueError: ProblemMapping("invalid-parameter", "Invalid Parameter", HTTPStatus.BAD_REQUEST),
    NotImplementedError: ProblemMapping(
        "not-implemented", "Not Implemented", HTTPStatus.NOT_IMPLEMENTED
    ),
}


def format_error_response(exc: BaseException, *, instance: str) -> dict[str, object]:
    """Return Problem Details payload for the provided exception.

    Parameters
    ----------
    exc : BaseException
        Exception instance to convert into Problem Details.
    instance : str
        RFC 9457 ``instance`` URI identifying the operation that failed.

    Returns
    -------
    dict[str, object]
        Dictionary containing ``problem`` (Problem Details payload) and
        ``status`` (HTTP status code).
    """
    if isinstance(exc, KgFoundryError):
        problem = exc.to_problem_details(instance=instance)
        status = cast("int", problem.get("status", HTTPStatus.INTERNAL_SERVER_ERROR))
        return {"problem": problem, "status": status}

    if isinstance(exc, UnicodeDecodeError):
        problem = build_problem_details(
            problem_type="https://kgfoundry.dev/problems/unsupported-encoding",
            title="Unsupported Encoding",
            status=415,
            detail=f"Binary file or encoding error: {exc.reason}",
            instance=instance,
            code="unsupported-encoding",
            extensions={"encoding": exc.encoding, "reason": exc.reason},
        )
        return {"problem": problem, "status": 415}

    for exc_type, mapping in EXCEPTION_TO_ERROR_CODE.items():
        if isinstance(exc, exc_type):
            detail = str(exc)
            problem = build_problem_details(
                problem_type=f"https://kgfoundry.dev/problems/{mapping.code}",
                title=mapping.title,
                status=mapping.status,
                detail=detail,
                instance=instance,
                code=mapping.code,
            )
            return {"problem": problem, "status": mapping.status}

    problem = build_problem_details(
        problem_type="https://kgfoundry.dev/problems/internal-error",
        title="Internal Error",
        status=500,
        detail=str(exc),
        instance=instance,
        code="internal-error",
        extensions={"exception_type": type(exc).__name__},
    )
    return {"problem": problem, "status": 500}


def convert_exception_to_envelope(
    exc: BaseException,
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
    exc : BaseException
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
    response = format_error_response(exc, instance=operation)
    problem = cast("ProblemDetails", response["problem"])
    status = cast("int", response["status"])

    if isinstance(exc, KgFoundryError):
        kg_exc = exc
        with with_fields(
            LOGGER,
            component=COMPONENT_NAME,
            operation=operation,
            error_code=kg_exc.code.value,
        ) as adapter:
            adapter.log(kg_exc.log_level, kg_exc.message, extra={"context": kg_exc.context})
    elif isinstance(exc, PathNotDirectoryError):
        LOGGER.warning(
            "Path not directory",
            extra={
                "component": COMPONENT_NAME,
                "operation": operation,
                "error": str(exc),
            },
        )
    elif isinstance(exc, (PathNotFoundError, FileNotFoundError)):
        LOGGER.warning(
            "Path not found",
            extra={
                "component": COMPONENT_NAME,
                "operation": operation,
                "error": str(exc),
            },
        )
    elif isinstance(exc, PathOutsideRepositoryError):
        LOGGER.warning(
            "Path outside repository",
            extra={
                "component": COMPONENT_NAME,
                "operation": operation,
                "error": str(exc),
            },
        )
    elif isinstance(exc, UnicodeDecodeError):
        LOGGER.warning(
            "Encoding error",
            extra={
                "component": COMPONENT_NAME,
                "operation": operation,
                "encoding": exc.encoding,
                "reason": exc.reason,
            },
        )
    elif isinstance(exc, ValueError):
        LOGGER.warning(
            "Invalid parameter",
            extra={
                "component": COMPONENT_NAME,
                "operation": operation,
                "error": str(exc),
            },
        )
    elif isinstance(exc, NotImplementedError):
        LOGGER.error(
            "Operation not implemented",
            extra={
                "component": COMPONENT_NAME,
                "operation": operation,
                "error": str(exc),
            },
        )
    elif status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        LOGGER.error(
            "Unexpected error",
            extra={
                "component": COMPONENT_NAME,
                "operation": operation,
                "exception_type": type(exc).__name__,
            },
        )

    # Build envelope: empty result fields + error + problem
    _record_exception_event(exc, operation)
    envelope = dict(empty_result)
    detail = problem.get("detail", str(exc))
    envelope["error"] = detail
    envelope["problem"] = problem

    return envelope


def _record_exception_event(exc: BaseException, operation: str) -> None:
    """Emit an OpenTelemetry exception event for adapter errors."""
    attrs = {
        "operation": operation,
        "exception.type": type(exc).__name__,
        "exception.message": str(exc),
    }
    run_id = current_run_id()
    if run_id:
        attrs["run_id"] = run_id
    stack = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if stack:
        attrs["exception.stacktrace"] = stack[-2048:]
    try:
        record_span_event("adapter.exception", **attrs)
    except (RuntimeError, ValueError):  # pragma: no cover - best-effort telemetry
        LOGGER.debug("Failed to record exception span event", exc_info=True)
    emit_step(
        StepEvent(
            kind=f"{operation}.error",
            status="failed",
            detail=type(exc).__name__,
            payload={"message": str(exc)},
        )
    )


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
        converts exceptions to error envelopes.

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
        """Inner decorator function that wraps the adapter function.

        Extended Summary
        ----------------
        This inner function is returned by handle_adapter_errors() and wraps the
        actual adapter function (func) with exception handling. It detects whether
        func is async or sync and creates the appropriate wrapper. The wrapper
        catches all user exceptions, converts them to error envelopes, and returns
        the envelope instead of re-raising. This ensures consistent error responses
        at the MCP boundary.

        Parameters
        ----------
        func : F
            The adapter function to wrap. Can be sync or async. Must return a
            dict-compatible result on success.

        Returns
        -------
        F
            Wrapped function with the same signature as func but with automatic
            exception handling. The wrapper preserves function metadata (name,
            docstring, annotations) for FastMCP schema generation.
        """
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: object, **kwargs: object) -> dict[str, object]:
                """Async wrapper that catches exceptions and converts to error envelopes.

                Extended Summary
                ----------------
                This wrapper function handles async adapter functions by awaiting
                the function call and catching all user exceptions. On success,
                returns the function result. On exception, converts the exception
                to a Problem Details error envelope and returns it. System-level
                exceptions (KeyboardInterrupt, SystemExit, GeneratorExit) are
                re-raised to allow proper shutdown.

                Parameters
                ----------
                *args : object
                    Positional arguments passed to the wrapped function.
                **kwargs : object
                    Keyword arguments passed to the wrapped function.

                Returns
                -------
                dict[str, object]
                    Function result dict on success, or error envelope dict on
                    exception. The error envelope includes empty_result fields,
                    error message, and Problem Details.

                Raises
                ------
                KeyboardInterrupt
                    Re-raised to allow proper keyboard interrupt handling.
                SystemExit
                    Re-raised to allow proper system shutdown.
                GeneratorExit
                    Re-raised to allow proper generator cleanup.

                Notes
                -----
                This wrapper ensures all async adapter exceptions are caught and
                converted to error envelopes. The function signature is preserved
                for FastMCP schema generation. Time complexity: O(1) wrapper overhead
                plus the wrapped function's complexity.
                """
                try:
                    # Type cast needed because pyrefly can't infer awaitability from inspect check
                    coro = cast("Awaitable[dict[str, object]]", func(*args, **kwargs))
                    return await coro
                except (KeyboardInterrupt, SystemExit, GeneratorExit):
                    # Re-raise system-level exceptions - these should propagate
                    raise
                except _USER_EXCEPTIONS as exc:
                    # Catch all user exceptions to ensure Problem Details are always
                    # emitted at the boundary. System-level exceptions (KeyboardInterrupt,
                    # SystemExit, GeneratorExit) are re-raised above.
                    # This is a boundary handler that MUST catch all user exceptions to
                    # guarantee consistent error responses for clients.
                    return convert_exception_to_envelope(exc, operation, empty_result)

            return cast("F", async_wrapper)

        @wraps(func)
        def sync_wrapper(*args: object, **kwargs: object) -> dict[str, object]:
            """Sync wrapper that catches exceptions and converts to error envelopes.

            Extended Summary
            ----------------
            This wrapper function handles sync adapter functions by calling the
            function and catching all user exceptions. On success, returns the
            function result. On exception, converts the exception to a Problem
            Details error envelope and returns it. System-level exceptions
            (KeyboardInterrupt, SystemExit, GeneratorExit) are re-raised to allow
            proper shutdown.

            Parameters
            ----------
            *args : object
                Positional arguments passed to the wrapped function.
            **kwargs : object
                Keyword arguments passed to the wrapped function.

            Returns
            -------
            dict[str, object]
                Function result dict on success, or error envelope dict on
                exception. The error envelope includes empty_result fields,
                error message, and Problem Details.

            Raises
            ------
            KeyboardInterrupt
                Re-raised to allow proper keyboard interrupt handling.
            SystemExit
                Re-raised to allow proper system shutdown.
            GeneratorExit
                Re-raised to allow proper generator cleanup.

            Notes
            -----
            This wrapper ensures all sync adapter exceptions are caught and
            converted to error envelopes. The function signature is preserved
            for FastMCP schema generation. Time complexity: O(1) wrapper overhead
            plus the wrapped function's complexity.
            """
            try:
                result = func(*args, **kwargs)
                return cast("dict[str, object]", result)
            except (KeyboardInterrupt, SystemExit, GeneratorExit):
                # Re-raise system-level exceptions - these should propagate
                raise
            except _USER_EXCEPTIONS as exc:
                # Catch all user exceptions to ensure Problem Details are always
                # emitted at the boundary. System-level exceptions (KeyboardInterrupt,
                # SystemExit, GeneratorExit) are re-raised above.
                # This is a boundary handler that MUST catch all user exceptions to
                # guarantee consistent error responses for clients.
                return convert_exception_to_envelope(exc, operation, empty_result)

        return cast("F", sync_wrapper)

    return decorator


__all__ = [
    "EXCEPTION_TO_ERROR_CODE",
    "convert_exception_to_envelope",
    "format_error_response",
    "handle_adapter_errors",
]
