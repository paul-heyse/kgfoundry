# SPDX-License-Identifier: MIT
"""Typed OpenTelemetry shims with graceful fallbacks.

This module centralizes our optional OpenTelemetry imports so that other modules
can depend on a stable interface regardless of whether Otel is installed. When
the real SDK is present we simply re-export its classes. Otherwise we provide
lightweight stub implementations that satisfy the type checker and preserve the
call contracts used throughout the codebase.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Protocol, cast, runtime_checkable


@runtime_checkable
class SpanContextProtocol(Protocol):
    """Subset of :class:`opentelemetry.trace.SpanContext` that we consume."""

    @property
    def trace_id(self) -> int:  # pragma: no cover - forwarded to Otel impl
        """Return the current trace identifier."""
        ...

    @property
    def span_id(self) -> int:  # pragma: no cover - forwarded to Otel impl
        """Return the current span identifier."""
        ...


@runtime_checkable
class SpanProtocol(Protocol):
    """Methods we rely on for span manipulation."""

    def set_attribute(self, key: object, value: object) -> None:  # pragma: no cover - Otel impl
        """Attach ``value`` to ``key`` on the span."""
        ...

    def record_exception(self, exception: BaseException) -> None:  # pragma: no cover - Otel impl
        """Record ``exception`` on the span."""
        ...

    def set_status(self, status: object) -> None:  # pragma: no cover - Otel impl
        """Set the status (typically ``Status(StatusCode.ERROR)``)."""
        ...

    def add_event(  # pragma: no cover - Otel impl
        self,
        name: str,
        attributes: Mapping[str, object] | None = None,
    ) -> None:
        """Add an event to the span."""
        ...

    def is_recording(self) -> bool:  # pragma: no cover - Otel impl
        """Return True if the span is actively recording."""
        ...

    def get_span_context(self) -> SpanContextProtocol:  # pragma: no cover - Otel impl
        """Expose the backing span context."""
        ...


@runtime_checkable
class TracerProtocol(Protocol):
    """Tracer hook used by our decorators and telemetry sinks."""

    def start_as_current_span(  # pragma: no cover - Otel impl
        self,
        name: str,
        **kwargs: object,
    ) -> AbstractContextManager[SpanProtocol]:
        """Return a context manager that yields a span."""
        ...


@runtime_checkable
class TraceAPILike(Protocol):
    """Surface area from :mod:`opentelemetry.trace` that we consume."""

    def get_tracer(
        self, name: str, version: str | None = None
    ) -> TracerProtocol:  # pragma: no cover - Otel impl
        """Return a tracer for ``name``."""
        ...

    def get_current_span(self) -> SpanProtocol:  # pragma: no cover - Otel impl
        """Return the active span, if any."""
        ...

    def set_tracer_provider(self, provider: object) -> None:  # pragma: no cover - Otel impl
        """Install a global tracer provider."""
        ...


class SpanKindProtocol(Protocol):
    """Interface of ``SpanKind`` enums we depend on."""

    INTERNAL: object
    SERVER: object
    CLIENT: object
    PRODUCER: object
    CONSUMER: object


class StatusProtocol(Protocol):
    """Interface of ``Status`` values."""

    code: object


class StatusFactory(Protocol):
    """Constructor protocol for ``Status`` implementations."""

    def __call__(self, code: object) -> StatusProtocol:  # pragma: no cover - runtime impl
        ...


class StatusCodeProtocol(Protocol):
    """Interface of ``StatusCode`` enums."""

    ERROR: object
    OK: object


@dataclass(slots=True)
class _SpanContextStub:
    """Minimal span context stub used when OpenTelemetry is unavailable."""

    trace_id: int = 0
    span_id: int = 0


@dataclass(slots=True)
class _NullSpan:
    """No-op span implementation."""

    attributes: dict[str, object] = field(default_factory=dict)
    _context: _SpanContextStub = field(default_factory=_SpanContextStub)

    def set_attribute(self, key: object, value: object) -> None:
        """Store an attribute in the span's attribute dictionary.

        Parameters
        ----------
        key : object
            Attribute key to store. Converted to string for dictionary storage.
        value : object
            Attribute value to store. Stored as-is in the attributes dictionary.
        """
        self.attributes[str(key)] = value

    def record_exception(self, exception: BaseException) -> None:
        """Record an exception in the span's attributes.

        Parameters
        ----------
        exception : BaseException
            Exception to record. The exception's type name is stored in the
            "last_exception" attribute.
        """
        self.attributes["last_exception"] = type(exception).__name__

    def set_status(self, status: object) -> None:
        """Set the span status.

        Parameters
        ----------
        status : object
            Status object to store. Stored in the "status" attribute for
            debugging purposes.
        """
        self.attributes["status"] = status

    def add_event(self, name: str, attributes: Mapping[str, object] | None = None) -> None:
        """Add an event to the span's event list.

        Parameters
        ----------
        name : str
            Event name to record.
        attributes : Mapping[str, object] | None, optional
            Optional attributes dictionary to attach to the event. Defaults to None.
        """
        events = cast(
            "list[dict[str, object]]",
            self.attributes.setdefault("events", []),
        )
        payload: dict[str, object] = {
            "name": name,
            "attributes": dict(attributes or {}),
        }
        events.append(payload)

    def is_recording(self) -> bool:
        """Check if the span is actively recording.

        Returns
        -------
        bool
            True if the span's trace_id is non-zero (indicating active recording),
            False otherwise.
        """
        return self._context.trace_id != 0

    def get_span_context(self) -> _SpanContextStub:
        """Return the span's context stub.

        Returns
        -------
        _SpanContextStub
            The span context stub containing trace_id and span_id.
        """
        return self._context


@dataclass(slots=True)
class _NullSpanContextManager:
    """Context manager yielding a :class:`_NullSpan`."""

    span: _NullSpan = field(default_factory=_NullSpan)

    def __enter__(self) -> _NullSpan:
        """Enter the context manager and return the span.

        Returns
        -------
        _NullSpan
            The null span instance stored in this context manager.
        """
        return self.span

    def __exit__(self, *_exc: object) -> bool:
        """Exit the context manager.

        Parameters
        ----------
        *_exc : object
            Exception information (unused). Required by the context manager
            protocol.

        Returns
        -------
        bool
            False to allow exceptions to propagate normally.
        """
        return False


class _NoopTracer:
    """Tracer stub that returns :class:`_NullSpan` contexts."""

    def __init__(self) -> None:
        """Initialize the no-op tracer.

        Creates a tracer stub that tracks the number of span contexts created
        but does not perform actual tracing operations.
        """
        self._contexts_created = 0

    def start_as_current_span(self, *_args: object, **_kwargs: object) -> _NullSpanContextManager:
        """Start a new span context (no-op implementation).

        Parameters
        ----------
        *_args : object
            Positional arguments (ignored). Included for compatibility with
            OpenTelemetry tracer interface.
        **_kwargs : object
            Keyword arguments (ignored). Included for compatibility with
            OpenTelemetry tracer interface.

        Returns
        -------
        _NullSpanContextManager
            A context manager yielding a null span. The span does not perform
            actual tracing operations.
        """
        self._contexts_created += 1
        return _NullSpanContextManager()


class _TraceStub:
    """Module-level trace shim matching :mod:`opentelemetry.trace`."""

    def __init__(self) -> None:
        """Initialize the trace stub.

        Creates a stub implementation of the OpenTelemetry trace API that
        provides no-op implementations of all methods.
        """
        self._tracer = _NoopTracer()
        self._current_span = _NullSpan()
        self._provider: object | None = None

    def get_tracer(self, *_args: object, **_kwargs: object) -> _NoopTracer:
        """Return the no-op tracer instance.

        Parameters
        ----------
        *_args : object
            Positional arguments (ignored). Included for compatibility with
            OpenTelemetry trace API.
        **_kwargs : object
            Keyword arguments (ignored). Included for compatibility with
            OpenTelemetry trace API.

        Returns
        -------
        _NoopTracer
            The no-op tracer instance that returns null spans.
        """
        return self._tracer

    def get_current_span(self) -> _NullSpan:
        """Return the current null span.

        Returns
        -------
        _NullSpan
            A null span instance that does not perform actual tracing operations.
        """
        return self._current_span

    def set_tracer_provider(self, provider: object) -> None:
        """Store a tracer provider (no-op implementation).

        Parameters
        ----------
        provider : object
            Tracer provider to store. Stored but not used in the stub
            implementation.
        """
        self._provider = provider


class _SpanKindStub:
    """Enum-like stub mirroring :class:`opentelemetry.trace.SpanKind`."""

    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"
    PRODUCER = "producer"
    CONSUMER = "consumer"


@dataclass(slots=True, frozen=True)
class _StatusStub:
    """Fallback :class:`opentelemetry.trace.Status` replacement."""

    code: object


class _StatusCodeStub:
    """Enum-like placeholder for ``StatusCode``."""

    ERROR = "ERROR"
    OK = "OK"


try:  # pragma: no cover - optional dependency
    from importlib import import_module

    _trace_module = import_module("opentelemetry.trace")
    trace_api = cast("TraceAPILike", _trace_module)
    _span_runtime = cast("type[SpanProtocol]", _trace_module.Span)
    _span_kind_runtime = cast(
        "SpanKindProtocol",
        _trace_module.SpanKind if hasattr(_trace_module, "SpanKind") else _SpanKindStub,
    )
    _status_runtime = cast(
        "StatusFactory",
        _trace_module.Status if hasattr(_trace_module, "Status") else _StatusStub,
    )
    _status_code_runtime = cast(
        "StatusCodeProtocol",
        _trace_module.StatusCode if hasattr(_trace_module, "StatusCode") else _StatusCodeStub,
    )
except (ImportError, AttributeError):  # pragma: no cover - Otel not installed
    trace_api = _TraceStub()
    _span_runtime = _NullSpan
    _span_kind_runtime = _SpanKindStub
    _status_runtime = _StatusStub
    _status_code_runtime = _StatusCodeStub

SpanType = SpanProtocol
SpanKindType = SpanKindProtocol
StatusType = StatusProtocol
StatusCodeType = StatusCodeProtocol

Span: type[SpanProtocol] = cast("type[SpanProtocol]", _span_runtime)
SpanKind: SpanKindProtocol = cast("SpanKindProtocol", _span_kind_runtime)
Status: StatusFactory = cast("StatusFactory", _status_runtime)
StatusCode: StatusCodeProtocol = cast("StatusCodeProtocol", _status_code_runtime)


__all__ = [
    "Span",
    "SpanKind",
    "SpanKindType",
    "SpanProtocol",
    "SpanType",
    "Status",
    "StatusCode",
    "StatusCodeType",
    "StatusType",
    "TraceAPILike",
    "trace_api",
]
