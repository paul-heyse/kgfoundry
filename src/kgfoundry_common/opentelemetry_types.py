"""Typed facades for optional OpenTelemetry integrations.

This module centralises the small portion of the OpenTelemetry surface that the
codebase relies on.  We define lightweight ``Protocol`` interfaces that mirror
the runtime behaviour we exercise and provide helpers for loading the optional
dependency safely at runtime without leaking ``Any`` into the type graph.
"""

# [nav:section public-api]

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

SpanAttributeValue = str | int | float | bool
Attributes = Mapping[str, SpanAttributeValue]


class SpanProtocol(Protocol):
    """Minimal span surface exercised by the observability helpers."""

    def set_attribute(self, key: str, value: SpanAttributeValue) -> None:
        """Attach ``value`` to ``key`` on the span."""

    def record_exception(self, exception: BaseException) -> None:
        """Record ``exception`` on the span."""

    def set_status(self, status: object) -> None:
        """Persist ``status`` on the span."""


class TracerProtocol(Protocol):
    """Tracer facade returned by ``opentelemetry.trace.get_tracer``."""

    def start_as_current_span(self, name: str) -> AbstractContextManager[SpanProtocol]:
        """Return a context manager yielding a span."""
        ...


class TraceAPIProtocol(Protocol):
    """Subset of the OpenTelemetry trace module used by the codebase."""

    def get_tracer(self, name: str) -> TracerProtocol:
        """Return a tracer for ``name``."""
        ...


class SpanProcessorProtocol(Protocol):
    """Span processor lifecycle hooks invoked by the tests."""

    def on_start(self, span: SpanProtocol, parent_context: object | None = None) -> None:
        """Observe ``span`` immediately after creation."""
        del self, span, parent_context
        raise NotImplementedError

    def on_end(self, span: SpanProtocol) -> None:
        """Observe ``span`` once it has completed."""
        ...

    def shutdown(self) -> None:
        """Release resources associated with the processor."""
        ...

    def force_flush(self, timeout_millis: int | None = None) -> bool:
        """Flush buffered spans within ``timeout_millis``."""
        del self, timeout_millis
        raise NotImplementedError


class TracerProviderProtocol(Protocol):
    """Tracer provider constructor and helpers used in fixtures.

    Parameters
    ----------
    *args : object
        Positional arguments passed to the provider constructor.
    **kwargs : object
        Keyword arguments passed to the provider constructor.
    """

    def __init__(self, *args: object, **kwargs: object) -> None: ...

    def get_tracer(
        self,
        instrumenting_module_name: str,
        instrumenting_library_version: str | None = None,
        schema_url: str | None = None,
        attributes: Attributes | None = None,
    ) -> TracerProtocol:
        """Return a tracer configured for the given instrumentation metadata."""
        del self, instrumenting_module_name, instrumenting_library_version, schema_url, attributes
        raise NotImplementedError

    def add_span_processor(self, processor: SpanProcessorProtocol) -> None:
        """Register ``processor`` for span lifecycle callbacks."""
        del self, processor
        raise NotImplementedError

    def shutdown(self) -> None:
        """Shut down the provider gracefully."""
        ...

    def force_flush(self, timeout_millis: int | None = None) -> bool:
        """Flush pending spans and return ``True`` on success."""
        del self, timeout_millis
        raise NotImplementedError


class SpanExporterProtocol(Protocol):
    """Minimal exporter interface used by the OpenTelemetry fixtures."""

    def export(self, spans: Sequence[object]) -> None:
        """Export ``spans`` to the configured backend."""
        ...


class StatusCodeProtocol(Protocol):
    """Subset of ``opentelemetry.trace.StatusCode`` used in observability."""

    ERROR: StatusCodeProtocol


class StatusFactory(Protocol):
    """Factory callable for instantiating ``Status`` instances."""

    def __call__(
        self,
        status_code: StatusCodeProtocol,
        description: str | None = None,
    ) -> object:
        """Create a status object using ``status_code`` and ``description``."""
        ...


@dataclass(slots=True, frozen=True)
class TraceRuntime:
    """Container for optional OpenTelemetry runtime handles."""

    api: TraceAPIProtocol | None
    status_factory: StatusFactory | None
    status_codes: StatusCodeProtocol | None


def _safe_getattr(module: object, name: str) -> object | None:
    """Safely get attribute from module, returning None if missing.

    Parameters
    ----------
    module : object
        Module object to query.
    name : str
        Attribute name to retrieve.

    Returns
    -------
    object | None
        Attribute value if present, None if AttributeError is raised.
    """
    try:
        return cast("object", getattr(module, name))
    except AttributeError:  # pragma: no cover - defensive
        return None


def load_trace_runtime() -> TraceRuntime:
    """Return the OpenTelemetry trace runtime handles if available.

    Returns
    -------
    TraceRuntime
        Trace runtime handles with API, status factory, and status codes.
    """
    try:
        trace_module = import_module("opentelemetry.trace")
    except ImportError:
        return TraceRuntime(api=None, status_factory=None, status_codes=None)

    api = cast("TraceAPIProtocol", trace_module)
    status_factory = _safe_getattr(trace_module, "Status")
    status_codes = _safe_getattr(trace_module, "StatusCode")
    return TraceRuntime(
        api=api,
        status_factory=cast("StatusFactory | None", status_factory),
        status_codes=cast("StatusCodeProtocol | None", status_codes),
    )


def load_tracer_provider_cls() -> Callable[[], TracerProviderProtocol] | None:
    """Return a factory for the OpenTelemetry ``TracerProvider`` if present.

    Returns
    -------
    Callable[[], TracerProviderProtocol] | None
        Factory function for creating TracerProvider instances, or None if not available.
    """
    try:
        sdk_trace_module = import_module("opentelemetry.sdk.trace")
    except ImportError:
        return None

    provider_raw = _safe_getattr(sdk_trace_module, "TracerProvider")
    if provider_raw is None or not callable(provider_raw):
        return None
    provider_factory = cast("Callable[[], object]", provider_raw)

    def factory() -> TracerProviderProtocol:
        """Create and return a TracerProvider instance.

        Returns
        -------
        TracerProviderProtocol
            TracerProvider instance conforming to protocol.
        """
        provider = provider_factory()
        return cast("TracerProviderProtocol", provider)

    return factory


def load_in_memory_span_exporter_cls() -> Callable[[], SpanExporterProtocol] | None:
    """Return a factory for the in-memory span exporter if available.

    Returns
    -------
    Callable[[], SpanExporterProtocol] | None
        Factory function for creating InMemorySpanExporter instances, or None if not available.
    """
    try:
        exporter_module = import_module("opentelemetry.sdk.trace.export.in_memory_span_exporter")
    except ImportError:
        return None

    exporter_raw = _safe_getattr(exporter_module, "InMemorySpanExporter")
    if exporter_raw is None or not callable(exporter_raw):
        return None
    exporter_factory = cast("Callable[[], object]", exporter_raw)

    def factory() -> SpanExporterProtocol:
        """Create and return an InMemorySpanExporter instance.

        Returns
        -------
        SpanExporterProtocol
            SpanExporter instance conforming to protocol.
        """
        exporter = exporter_factory()
        return cast("SpanExporterProtocol", exporter)

    return factory
