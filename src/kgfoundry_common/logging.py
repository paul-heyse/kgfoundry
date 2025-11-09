"""Structured logging helpers with correlation IDs and observability support.

This module provides LoggerAdapter for structured logging with mandatory
fields (correlation_id, operation, status, duration_ms) and module-level
loggers with NullHandler to prevent duplicate handlers in libraries.

Examples
--------
>>> from kgfoundry_common.logging import get_logger
>>> logger = get_logger(__name__)
>>> logger.info("Operation started", extra={"operation": "search", "status": "started"})
"""

# [nav:section public-api]

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol, Self, cast, runtime_checkable

from kgfoundry_common.navmap_loader import load_nav_metadata

# [nav:anchor FormatterType]
FormatterType: type[logging.Formatter] = logging.Formatter

if TYPE_CHECKING:
    from kgfoundry_common.types import JsonValue

__all__ = [
    "CorrelationContext",
    "FormatterType",
    "JsonFormatter",
    "LogContextExtra",
    "LoggerAdapter",
    "LoggingCache",
    "get_correlation_id",
    "get_logger",
    "get_logging_cache",
    "measure_duration",
    "set_correlation_id",
    "setup_logging",
    "with_fields",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


@runtime_checkable
# [nav:anchor LoggingCache]
class LoggingCache(Protocol):
    """Protocol for logging cache implementations.

    This protocol defines a contract for caching logging configurations,
    formatters, or other logging-related state without exposing internal
    implementation details. Implementations provide a public interface
    for retrieving cached logging resources.

    Methods
    -------
    get_formatter() -> JsonFormatter
        Get or create a cached JSON formatter instance.
    clear() -> None
        Clear all cached entries and reset state.

    Examples
    --------
    >>> from kgfoundry_common.logging import LoggingCache, get_logging_cache
    >>> cache = get_logging_cache()
    >>> # cache implements LoggingCache protocol
    >>> assert isinstance(cache, LoggingCache)
    """

    def get_formatter(self) -> JsonFormatter:
        """Get or create a cached JSON formatter instance.

        Returns
        -------
        JsonFormatter
            A JsonFormatter instance from cache or newly created.
        """
        ...

    def clear(self) -> None:
        """Clear all cached entries and reset state.

        This method clears formatter caches and any other logging-related cached state.
        """
        ...


@dataclass(frozen=True, slots=True)
# [nav:anchor LogContextExtra]
class LogContextExtra:
    """Immutable logging context with required and optional structured fields.

    This frozen dataclass ensures thread-safe, immutable logging contexts that
    can be safely shared across async tasks. Use the `with_*` methods to create
    updated copies preserving immutability guarantees.

    Attributes
    ----------
    correlation_id : str | None
        Request or correlation ID for tracing across services.
    operation : str | None
        Name of the operation being logged (e.g., "search", "index_build").
    status : str | None
        Operation status ("success", "error", "started", "in_progress").
    duration_ms : float | None
        Operation duration in milliseconds.
    service : str | None
        Name of the service producing the log.
    endpoint : str | None
        HTTP endpoint or internal method being executed.

    Examples
    --------
    >>> ctx = LogContextExtra(correlation_id="req-123", operation="search")
    >>> ctx_with_status = ctx.with_status("success")
    >>> ctx_with_status.status
    'success'
    >>> # Immutable: original is unchanged
    >>> ctx.status is None
    True
    """

    correlation_id: str | None = None
    operation: str | None = None
    status: str | None = None
    duration_ms: float | None = None
    service: str | None = None
    endpoint: str | None = None

    def with_correlation_id(self, correlation_id: str) -> Self:
        """Return copy with updated correlation_id.

        Parameters
        ----------
        correlation_id : str
            Correlation ID to set.

        Returns
        -------
        Self
            New instance with updated correlation_id.
        """
        return replace(self, correlation_id=correlation_id)

    def with_operation(self, operation: str) -> Self:
        """Return copy with updated operation.

        Parameters
        ----------
        operation : str
            Operation name to set.

        Returns
        -------
        Self
            New instance with updated operation.
        """
        return replace(self, operation=operation)

    def with_status(self, status: str) -> Self:
        """Return copy with updated status.

        Parameters
        ----------
        status : str
            Status value to set.

        Returns
        -------
        Self
            New instance with updated status.
        """
        return replace(self, status=status)

    def with_duration_ms(self, duration_ms: float) -> Self:
        """Return copy with updated duration_ms.

        Parameters
        ----------
        duration_ms : float
            Duration in milliseconds to set.

        Returns
        -------
        Self
            New instance with updated duration_ms.
        """
        return replace(self, duration_ms=duration_ms)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict, excluding None values for logging.

        Returns
        -------
        dict[str, Any]
            Dictionary with non-None fields only.
        """
        return {
            k: v
            for k, v in {
                "correlation_id": self.correlation_id,
                "operation": self.operation,
                "status": self.status,
                "duration_ms": self.duration_ms,
                "service": self.service,
                "endpoint": self.endpoint,
            }.items()
            if v is not None
        }


# Context variable for correlation ID propagation (async-safe)
_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


# [nav:anchor JsonFormatter]
class JsonFormatter(logging.Formatter):
    """JSON formatter for structured logging.

    Formats log records as JSON with timestamp, level, name, message,
    and structured fields (correlation_id, operation, status, duration_ms).
    Automatically extracts correlation_id from contextvars if not present
    in the log record. Standard ``logging.Formatter`` constructor arguments such
    as ``fmt``, ``datefmt``, ``style``, ``validate``, and ``defaults`` are
    supported via inheritance; no additional aliases are introduced by this
    subclass.

    Examples
    --------
    >>> import logging
    >>> handler = logging.StreamHandler()
    >>> handler.setFormatter(JsonFormatter())
    >>> logger = logging.getLogger("test")
    >>> logger.addHandler(handler)
    >>> logger.info("Test message", extra={"operation": "test", "status": "success"})
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.

        Converts a logging.LogRecord to a JSON string with structured fields.
        Extracts correlation_id from contextvars if not present in the record.

        Parameters
        ----------
        record : logging.LogRecord
            Log record to format. May include extra fields in record.__dict__.

        Returns
        -------
        str
            JSON-encoded log entry with timestamp, level, message, and structured
            fields. All extra fields from the record are included if they are
            JSON-serializable.
        """
        # Log data is JSON-serializable - use JsonValue instead of Any
        data: dict[str, JsonValue] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }

        # Extract structured fields from extra (fields set via LoggerAdapter or extra dict)
        structured_fields = ["correlation_id", "operation", "status", "duration_ms"]
        for field in structured_fields:
            value = getattr(record, field, None)
            if value is not None:
                data[field] = value

        # Add correlation_id from context if not in extra
        if "correlation_id" not in data:
            ctx_correlation_id = _correlation_id.get()
            if ctx_correlation_id is not None:
                data["correlation_id"] = ctx_correlation_id

        # Add any additional extra fields (from extra dict passed to log calls)
        # Standard logging attributes to exclude
        excluded = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "thread",
            "threadName",
            "exc_info",
            "exc_text",
            "stack_info",
            "getMessage",
            "ts",  # Not a standard attribute
        }
        # Include all extra fields from record attributes (excluding standard logging attributes)
        for key, value in record.__dict__.items():
            if (
                key not in excluded
                and key not in data
                and not key.startswith("_")
                and value is not None
                and isinstance(value, (str, int, float, bool, list, dict))
            ):
                data[key] = value

        return json.dumps(data, default=str)


if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType

    class _LoggerAdapterBase:  # pragma: no cover - typing helper
        """Typing helper matching logging.LoggerAdapter interface.

        Initializes logger adapter with base logger and structured fields.

        Parameters
        ----------
        logger : logging.Logger
            Base logger instance.
        extra : LogContextExtra | Mapping[str, object] | None, optional
            Structured fields to inject into log entries.

        Attributes
        ----------
        logger : logging.Logger
            Base logger instance.
        extra : LogContextExtra | Mapping[str, object] | None
            Structured fields to inject into log entries.
        """

        logger: logging.Logger
        extra: LogContextExtra | Mapping[str, object] | None

        def __init__(
            self,
            logger: logging.Logger,
            extra: LogContextExtra | Mapping[str, object] | None,
        ) -> None: ...

else:
    _LoggerAdapterBase = logging.LoggerAdapter


# [nav:anchor LoggerAdapter]
class LoggerAdapter(_LoggerAdapterBase):
    """Logger adapter that injects structured context fields.

    This adapter ensures that all log entries include correlation_id,
    operation, status, and duration_ms fields. It propagates correlation
    IDs from context variables for async-safe operation.

    Parameters
    ----------
    logger : logging.Logger
        Base logger instance to wrap.
    extra : LogContextExtra | Mapping[str, object] | None, optional
        Structured fields to inject into log entries. Can be a LogContextExtra
        frozen dataclass or dict of fields. Defaults to None.

    Attributes
    ----------
    logger : logging.Logger
        Base logger instance to wrap.

    Examples
    --------
    >>> from kgfoundry_common.logging import get_logger
    >>> logger = get_logger(__name__)
    >>> logger.info("Search started", extra={"operation": "search", "status": "started"})
    >>> # Correlation ID is automatically injected from context
    """

    logger: logging.Logger

    def process(self, msg: str, kwargs: Mapping[str, Any]) -> tuple[str, Any]:
        """Process log message and inject structured fields.

        Merges structured fields from the adapter's extra dict and contextvars
        into the log record's extra dict. Ensures operation and status fields
        are always present.

        Parameters
        ----------
        msg : str
            Log message string.
        kwargs : Mapping[str, Any]
            Keyword arguments from logging call, including 'extra' dict.

        Returns
        -------
        tuple[str, Any]
            Processed message and kwargs with injected fields. The kwargs dict
            is modified in-place to include correlation_id, operation, and status.
        """
        if not isinstance(kwargs, dict):
            return msg, kwargs

        extra = kwargs.setdefault("extra", {})

        # Handle LogContextExtra dataclass: convert to dict if needed
        if isinstance(self.extra, LogContextExtra):
            for key, value in self.extra.to_dict().items():
                if key not in extra:
                    extra[key] = value
        # Merge self.extra (fields from LoggerAdapter constructor) into extra
        # This allows with_fields to inject fields that persist across log calls
        elif isinstance(self.extra, dict):
            for key, value in self.extra.items():
                if key not in extra:
                    extra[key] = value

        # Inject correlation_id from context if not provided
        if "correlation_id" not in extra:
            ctx_correlation_id = _correlation_id.get()
            if ctx_correlation_id is not None:
                extra["correlation_id"] = ctx_correlation_id

        # Ensure operation and status are present (defaults if missing)
        self._ensure_operation_and_status(extra, kwargs.get("level", logging.INFO))

        return msg, kwargs

    @staticmethod
    def _ensure_operation_and_status(extra: dict[str, Any], level: int) -> None:
        """Ensure operation and status fields are present in extra dict.

        Parameters
        ----------
        extra : dict[str, Any]
            Extra dict to populate.
        level : int
            Log level to determine status.
        """
        if "operation" not in extra:
            extra["operation"] = "unknown"
        if "status" not in extra:
            # Infer status from log level
            if level >= logging.ERROR:
                extra["status"] = "error"
            elif level >= logging.WARNING:
                extra["status"] = "warning"
            else:
                extra["status"] = "success"

    def debug(self, msg: object, *args: object, **kwargs: object) -> None:
        """Log a debug message with structured fields."""
        kwargs_dict = cast("dict[str, Any]", kwargs)
        extra = kwargs_dict.get("extra", {})
        if not isinstance(extra, dict):
            extra = {}
        extra = cast("dict[str, Any]", extra)
        # Handle LogContextExtra dataclass: convert to dict if needed
        if isinstance(self.extra, LogContextExtra):
            for key, value in self.extra.to_dict().items():
                if key not in extra:
                    extra[key] = value
        # Merge self.extra (fields from LoggerAdapter constructor) into extra
        elif isinstance(self.extra, dict):
            for key, value in self.extra.items():
                if key not in extra:
                    extra[key] = value
        # Inject correlation_id from context if not provided
        if "correlation_id" not in extra:
            ctx_correlation_id = _correlation_id.get()
            if ctx_correlation_id is not None:
                extra["correlation_id"] = ctx_correlation_id
        self._ensure_operation_and_status(extra, logging.DEBUG)
        kwargs_dict["extra"] = extra
        self.logger.debug(msg, *args, **kwargs_dict)

    def info(self, msg: object, *args: object, **kwargs: object) -> None:
        """Log an info message with structured fields."""
        kwargs_dict = cast("dict[str, Any]", kwargs)
        extra = kwargs_dict.get("extra", {})
        if not isinstance(extra, dict):
            extra = {}
        extra = cast("dict[str, Any]", extra)
        # Handle LogContextExtra dataclass: convert to dict if needed
        if isinstance(self.extra, LogContextExtra):
            for key, value in self.extra.to_dict().items():
                if key not in extra:
                    extra[key] = value
        # Merge self.extra (fields from LoggerAdapter constructor) into extra
        elif isinstance(self.extra, dict):
            for key, value in self.extra.items():
                if key not in extra:
                    extra[key] = value
        # Inject correlation_id from context if not provided
        if "correlation_id" not in extra:
            ctx_correlation_id = _correlation_id.get()
            if ctx_correlation_id is not None:
                extra["correlation_id"] = ctx_correlation_id
        self._ensure_operation_and_status(extra, logging.INFO)
        kwargs_dict["extra"] = extra
        self.logger.info(msg, *args, **kwargs_dict)

    def warning(self, msg: object, *args: object, **kwargs: object) -> None:
        """Log a warning message with structured fields."""
        kwargs_dict = cast("dict[str, Any]", kwargs)
        extra = kwargs_dict.get("extra", {})
        if not isinstance(extra, dict):
            extra = {}
        extra = cast("dict[str, Any]", extra)
        # Handle LogContextExtra dataclass: convert to dict if needed
        if isinstance(self.extra, LogContextExtra):
            for key, value in self.extra.to_dict().items():
                if key not in extra:
                    extra[key] = value
        # Merge self.extra (fields from LoggerAdapter constructor) into extra
        elif isinstance(self.extra, dict):
            for key, value in self.extra.items():
                if key not in extra:
                    extra[key] = value
        # Inject correlation_id from context if not provided
        if "correlation_id" not in extra:
            ctx_correlation_id = _correlation_id.get()
            if ctx_correlation_id is not None:
                extra["correlation_id"] = ctx_correlation_id
        self._ensure_operation_and_status(extra, logging.WARNING)
        kwargs_dict["extra"] = extra
        self.logger.warning(msg, *args, **kwargs_dict)

    def error(self, msg: object, *args: object, **kwargs: object) -> None:
        """Log an error message with structured fields."""
        kwargs_dict = cast("dict[str, Any]", kwargs)
        extra = kwargs_dict.get("extra", {})
        if not isinstance(extra, dict):
            extra = {}
        extra = cast("dict[str, Any]", extra)
        # Handle LogContextExtra dataclass: convert to dict if needed
        if isinstance(self.extra, LogContextExtra):
            for key, value in self.extra.to_dict().items():
                if key not in extra:
                    extra[key] = value
        # Merge self.extra (fields from LoggerAdapter constructor) into extra
        elif isinstance(self.extra, dict):
            for key, value in self.extra.items():
                if key not in extra:
                    extra[key] = value
        # Inject correlation_id from context if not provided
        if "correlation_id" not in extra:
            ctx_correlation_id = _correlation_id.get()
            if ctx_correlation_id is not None:
                extra["correlation_id"] = ctx_correlation_id
        self._ensure_operation_and_status(extra, logging.ERROR)
        kwargs_dict["extra"] = extra
        self.logger.error(msg, *args, **kwargs_dict)

    def exception(
        self,
        msg: object,
        *args: object,
        exc_info: object | bool = True,
        **kwargs: object,
    ) -> None:
        """Log an error with traceback using structured fields."""
        kwargs_dict = cast("dict[str, Any]", kwargs)
        if "exc_info" not in kwargs_dict or kwargs_dict["exc_info"] is False:
            kwargs_dict["exc_info"] = exc_info
        self.error(msg, *args, **kwargs_dict)

    def critical(self, msg: object, *args: object, **kwargs: object) -> None:
        """Log a critical message with structured fields."""
        kwargs_dict = cast("dict[str, Any]", kwargs)
        extra = kwargs_dict.get("extra", {})
        if not isinstance(extra, dict):
            extra = {}
        extra = cast("dict[str, Any]", extra)
        # Handle LogContextExtra dataclass: convert to dict if needed
        if isinstance(self.extra, LogContextExtra):
            for key, value in self.extra.to_dict().items():
                if key not in extra:
                    extra[key] = value
        # Merge self.extra (fields from LoggerAdapter constructor) into extra
        elif isinstance(self.extra, dict):
            for key, value in self.extra.items():
                if key not in extra:
                    extra[key] = value
        # Inject correlation_id from context if not provided
        if "correlation_id" not in extra:
            ctx_correlation_id = _correlation_id.get()
            if ctx_correlation_id is not None:
                extra["correlation_id"] = ctx_correlation_id
        self._ensure_operation_and_status(extra, logging.CRITICAL)
        kwargs_dict["extra"] = extra
        self.logger.critical(msg, *args, **kwargs_dict)

    def log(self, level: int, msg: object, *args: object, **kwargs: object) -> None:
        """Log a message at the given level with structured fields."""
        kwargs_dict = cast("dict[str, Any]", kwargs)
        extra = kwargs_dict.get("extra", {})
        if not isinstance(extra, dict):
            extra = {}
        extra = cast("dict[str, Any]", extra)
        # Handle LogContextExtra dataclass: convert to dict if needed
        if isinstance(self.extra, LogContextExtra):
            for key, value in self.extra.to_dict().items():
                if key not in extra:
                    extra[key] = value
        # Merge self.extra (fields from LoggerAdapter constructor) into extra
        elif isinstance(self.extra, dict):
            for key, value in self.extra.items():
                if key not in extra:
                    extra[key] = value
        # Inject correlation_id from context if not provided
        if "correlation_id" not in extra:
            ctx_correlation_id = _correlation_id.get()
            if ctx_correlation_id is not None:
                extra["correlation_id"] = ctx_correlation_id
        self._ensure_operation_and_status(extra, level)
        kwargs_dict["extra"] = extra
        self.logger.log(level, msg, *args, **kwargs_dict)

    def log_success(
        self,
        message: str,
        *,
        operation: str | None = None,
        duration_ms: float | None = None,
        **fields: object,
    ) -> None:
        """Log a successful operation with structured fields.

        Parameters
        ----------
        message : str
            Success message.
        operation : str | None, optional
            Operation name. If not provided, uses current context value or "unknown".
            Defaults to ``None``.
        duration_ms : float | None, optional
            Operation duration in milliseconds. Defaults to ``None``.
        **fields : object
            Additional structured fields to include in log record.

        Examples
        --------
        >>> from kgfoundry_common.logging import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.log_success("Index built", operation="build_index", duration_ms=1234.5)
        """
        extra: dict[str, object] = {"status": "success"}
        if operation is not None:
            extra["operation"] = operation
        if duration_ms is not None:
            extra["duration_ms"] = duration_ms
        extra.update(fields)
        self.info(message, extra=extra)

    def log_failure(
        self,
        message: str,
        *,
        exception: Exception | None = None,
        operation: str | None = None,
        duration_ms: float | None = None,
        **fields: object,
    ) -> None:
        """Log a failure with structured fields and optional exception chaining.

        Parameters
        ----------
        message : str
            Failure message.
        exception : Exception | None, optional
            Exception that caused the failure (preserved in extras). Defaults to ``None``.
        operation : str | None, optional
            Operation name. Defaults to ``None``.
        duration_ms : float | None, optional
            Operation duration in milliseconds. Defaults to ``None``.
        **fields : object
            Additional structured fields.

        Examples
        --------
        >>> from kgfoundry_common.logging import get_logger
        >>> logger = get_logger(__name__)
        >>> try:
        ...     raise ValueError("Invalid data")
        ... except ValueError as e:
        ...     logger.log_failure("Failed to process", exception=e, operation="process_data")
        """
        extra: dict[str, object] = {"status": "error"}
        if operation is not None:
            extra["operation"] = operation
        if duration_ms is not None:
            extra["duration_ms"] = duration_ms
        if exception is not None:
            extra["error_type"] = exception.__class__.__name__
            extra["error_detail"] = str(exception)
        extra.update(fields)
        self.error(message, extra=extra)

    def log_io(
        self,
        message: str,
        *,
        operation: str | None = None,
        io_type: str = "unknown",
        size_bytes: int | None = None,
        duration_ms: float | None = None,
        **fields: object,
    ) -> None:
        """Log I/O operation with structured fields.

        Parameters
        ----------
        message : str
            I/O operation message.
        operation : str | None, optional
            Operation name. Defaults to ``None``.
        io_type : str, optional
            I/O type ("read", "write", "delete", "unknown"). Defaults to ``"unknown"``.
        size_bytes : int | None, optional
            Bytes transferred/processed. Defaults to ``None``.
        duration_ms : float | None, optional
            I/O duration in milliseconds. Defaults to ``None``.
        **fields : object
            Additional structured fields.

        Examples
        --------
        >>> from kgfoundry_common.logging import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.log_io(
        ...     "Downloaded file",
        ...     operation="download",
        ...     io_type="read",
        ...     size_bytes=1024,
        ...     duration_ms=500.0,
        ... )
        """
        extra: dict[str, object] = {"status": "success", "io_type": io_type}
        if operation is not None:
            extra["operation"] = operation
        if size_bytes is not None:
            extra["size_bytes"] = size_bytes
        if duration_ms is not None:
            extra["duration_ms"] = duration_ms
        extra.update(fields)
        self.info(message, extra=extra)


# [nav:anchor get_logger]
def get_logger(name: str) -> LoggerAdapter:
    """Get a logger adapter with structured logging support.

    Creates a logger adapter that automatically injects structured fields
    (correlation_id, operation, status, duration_ms) into all log entries.
    Module-level loggers use NullHandler to prevent duplicate handlers
    in libraries. Applications should configure handlers via setup_logging().

    Parameters
    ----------
    name : str
        Logger name (typically __name__ from the calling module).

    Returns
    -------
    LoggerAdapter
        Logger adapter with structured context injection. Correlation IDs
        are automatically extracted from contextvars if set.

    Examples
    --------
    >>> from kgfoundry_common.logging import get_logger
    >>> logger = get_logger(__name__)
    >>> logger.info("Operation complete", extra={"operation": "index_build", "status": "success"})
    """
    logger = logging.getLogger(name)

    # Add NullHandler if no handlers exist (prevents duplicate handlers in libraries)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    return LoggerAdapter(logger, {})


# [nav:anchor setup_logging]
def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with JSON formatter.

    Sets up structured JSON logging to stdout. Configures the root logger
    with a StreamHandler that uses JsonFormatter. Should be called once
    at application startup.

    Parameters
    ----------
    level : int, optional
        Logging level threshold. Use logging.DEBUG, logging.INFO, etc.
        Defaults to logging.INFO (20).

    Examples
    --------
    >>> from kgfoundry_common.logging import setup_logging
    >>> import logging
    >>> setup_logging(level=logging.DEBUG)
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)


# [nav:anchor set_correlation_id]
def set_correlation_id(correlation_id: str | None) -> None:
    """Set correlation ID in context for async propagation.

    Uses `contextvars.ContextVar` to ensure correlation IDs propagate correctly
    through async tasks and thread pools without cross-contamination between
    concurrent requests.

    Parameters
    ----------
    correlation_id : str | None
        Correlation ID to set (or None to clear). This ID will be automatically
        injected into all log entries via LoggerAdapter.

    Examples
    --------
    >>> from kgfoundry_common.logging import set_correlation_id, get_logger
    >>> set_correlation_id("req-123")
    >>> logger = get_logger(__name__)
    >>> logger.info("Request started")  # correlation_id="req-123" auto-injected

    Notes
    -----
    - **Async propagation**: Correlation IDs automatically propagate through
      async tasks via `contextvars.ContextVar`, ensuring each concurrent
      request maintains its own correlation ID.
    - **Thread safety**: ContextVar is thread-safe and isolates correlation
      IDs between different threads/async tasks.
    - **Cancellation**: If an async task is cancelled, the correlation ID
      context is automatically cleaned up.
    """
    _correlation_id.set(correlation_id)


# [nav:anchor get_correlation_id]
def get_correlation_id() -> str | None:
    """Get current correlation ID from context.

    Retrieves the correlation ID that was set via set_correlation_id() or
    CorrelationContext. Returns None if no correlation ID is currently set.

    Returns
    -------
    str | None
        Current correlation ID from contextvars, or None if not set.

    Examples
    --------
    >>> from kgfoundry_common.logging import set_correlation_id, get_correlation_id
    >>> set_correlation_id("req-123")
    >>> assert get_correlation_id() == "req-123"
    >>> set_correlation_id(None)
    >>> assert get_correlation_id() is None
    """
    return _correlation_id.get()


# [nav:anchor CorrelationContext]
class CorrelationContext:
    """Context manager for correlation ID propagation using contextvars.

    Manages correlation ID context using `contextvars.ContextVar`, ensuring
    IDs propagate correctly through async tasks and thread pools without
    cross-contamination between concurrent requests. Automatically restores
    the previous correlation ID when the context exits.

    Initializes correlation context with correlation ID.

    Parameters
    ----------
    correlation_id : str | None
        Correlation ID to set in context. This ID will be automatically
        injected into all log entries within the context. Set to None to
        clear the correlation ID.

    Examples
    --------
    >>> from kgfoundry_common.logging import CorrelationContext, get_logger
    >>> logger = get_logger(__name__)
    >>> with CorrelationContext(correlation_id="req-123"):
    ...     logger.info("Request started")  # correlation_id="req-123" auto-injected
    >>> # Correlation ID is automatically cleared when context exits
    """

    def __init__(self, correlation_id: str | None) -> None:
        self.correlation_id = correlation_id
        self._token: contextvars.Token[str | None] | None = None

    def __enter__(self) -> Self:
        """Enter correlation context and set correlation ID.

        Returns
        -------
        Self
            Self for use as context manager.
        """
        self._token = _correlation_id.set(self.correlation_id)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit correlation context and restore previous correlation ID.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            Exception type (if any).
        exc_val : BaseException | None
            Exception value (if any).
        exc_tb : TracebackType | None
            Exception traceback (if any).
        """
        if self._token is not None:
            _correlation_id.reset(self._token)
        del exc_type, exc_val, exc_tb


class _WithFieldsContext(AbstractContextManager[LoggerAdapter]):
    """Context manager implementation for `with_fields`.

    Initializes context manager with logger and fields.

    Parameters
    ----------
    logger : logging.Logger | LoggerAdapter
        Base logger to wrap (may already be an adapter).
    fields : Mapping[str, object]
        Structured fields to inject into log entries.
    """

    def __init__(
        self, logger: logging.Logger | LoggerAdapter, fields: Mapping[str, object]
    ) -> None:
        self._logger = logger
        self._fields = dict(fields)
        self._token: contextvars.Token[str | None] | None = None
        self._adapter: LoggerAdapter | None = None

    def __enter__(self) -> LoggerAdapter:
        """Enter context and return logger adapter with fields.

        Sets correlation_id in contextvars if provided in fields.

        Returns
        -------
        LoggerAdapter
            Logger adapter with structured fields injected.
        """
        base_logger = (
            self._logger.logger
            if isinstance(self._logger, LoggerAdapter)
            else self._logger
        )
        correlation_id = self._fields.get("correlation_id")
        if isinstance(correlation_id, str):
            self._token = _correlation_id.set(correlation_id)
        self._adapter = LoggerAdapter(base_logger, dict(self._fields))
        return self._adapter

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        """Exit context and restore correlation_id state.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            Exception type if raised, None otherwise.
        exc_value : BaseException | None
            Exception value if raised, None otherwise.
        exc_tb : TracebackType | None
            Exception traceback if raised, None otherwise.

        Returns
        -------
        bool | None
            None (does not suppress exceptions).
        """
        if self._token is not None:
            _correlation_id.reset(self._token)
        del exc_type, exc_value, exc_tb
        return None


# [nav:anchor with_fields]
def with_fields(
    logger: logging.Logger | LoggerAdapter,
    **fields: object,
) -> AbstractContextManager[LoggerAdapter]:
    """Context manager for attaching structured fields to log entries.

    Provides a context manager that:
    1. Sets correlation_id in contextvars if provided in fields
    2. Returns a LoggerAdapter with bound fields
    3. Automatically restores correlation_id when context exits

    Parameters
    ----------
    logger : logging.Logger | LoggerAdapter
        Base logger to wrap (may already be an adapter).
    **fields : object
        Structured fields to inject into all log entries (e.g., correlation_id,
        operation, status). These fields persist for all log calls within the
        context.

    Returns
    -------
    AbstractContextManager[LoggerAdapter]
        Context manager that yields a LoggerAdapter with bound fields and
        correlation_id in context. The correlation_id is automatically restored
        when the context exits.

    Examples
    --------
    >>> from kgfoundry_common.logging import get_logger, with_fields
    >>> logger = get_logger(__name__)
    >>> with with_fields(logger, correlation_id="req-123", operation="search") as ctx_logger:
    ...     ctx_logger.info("Starting search")  # Both fields auto-injected
    >>> # Fields are cleared when context exits
    """
    return _WithFieldsContext(logger, fields)


# [nav:anchor measure_duration]
def measure_duration() -> tuple[float, float]:
    """Get current monotonic time for measuring operation duration.

    Returns
    -------
    tuple[float, float]
        Tuple of (start_time, current_time) both from monotonic clock.

    Examples
    --------
    >>> start_time, _ = measure_duration()
    >>> # do work...
    >>> _, end_time = measure_duration()
    >>> duration_ms = (end_time - start_time) * 1000
    """
    current = time.monotonic()
    return current, current


class _DefaultLoggingCache:
    """Default implementation of LoggingCache protocol.

    This class provides a simple cache for logging formatters and configuration. It implements the
    LoggingCache protocol and can be retrieved via get_logging_cache().

    Initializes the logging cache with empty formatter cache.
    """

    def __init__(self) -> None:
        self._formatter_cache: JsonFormatter | None = None

    def get_formatter(self) -> JsonFormatter:
        """Get or create a cached JSON formatter instance.

        Returns
        -------
        JsonFormatter
            A JsonFormatter instance from cache or newly created.
        """
        if self._formatter_cache is None:
            self._formatter_cache = JsonFormatter()
        return self._formatter_cache

    def clear(self) -> None:
        """Clear all cached entries and reset state.

        This method clears the formatter cache and resets internal state.
        """
        self._formatter_cache = None


# Global logging cache instance
_logging_cache: _DefaultLoggingCache = _DefaultLoggingCache()


# [nav:anchor get_logging_cache]
def get_logging_cache() -> LoggingCache:
    """Get the global logging cache instance.

    Returns a LoggingCache implementation that can be used to retrieve
    cached logging formatters and configurations. The returned object
    implements the LoggingCache protocol and provides a stable interface
    for accessing logging infrastructure without exposing internal details.

    Returns
    -------
    LoggingCache
        Global logging cache instance implementing the LoggingCache protocol.

    Examples
    --------
    >>> from kgfoundry_common.logging import get_logging_cache
    >>> cache = get_logging_cache()
    >>> formatter = cache.get_formatter()
    >>> # Use formatter for logging...

    Notes
    -----
    The returned cache is a singleton instance shared across the entire
    application. Call cache.clear() to reset cached state if needed.
    """
    return _logging_cache
