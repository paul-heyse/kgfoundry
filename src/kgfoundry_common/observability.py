"""Prometheus metrics and OpenTelemetry tracing helpers.

Examples
--------
>>> from kgfoundry_common.logging import set_correlation_id
>>> from kgfoundry_common.observability import MetricsProvider, observe_duration
>>> set_correlation_id("req-123")
>>> provider = MetricsProvider.default()
>>> with observe_duration(provider, "search", component="search_api") as observer:
...     observer.success()
"""

# [nav:section public-api]

from __future__ import annotations

import time
import types
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, cast

from kgfoundry_common.logging import get_logger, with_fields
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.opentelemetry_types import (
    load_trace_runtime,
)
from kgfoundry_common.prometheus import (
    build_counter,
    build_histogram,
    get_default_registry,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from kgfoundry_common.opentelemetry_types import (
        StatusCodeProtocol,
        TraceRuntime,
    )
    from kgfoundry_common.prometheus import (
        CollectorRegistry,
        CounterLike,
        HistogramLike,
    )

trace_runtime: TraceRuntime = load_trace_runtime()
trace_api = trace_runtime.api
Status = trace_runtime.status_factory
StatusCode = trace_runtime.status_codes


__all__ = [
    "MetricsProvider",
    "MetricsRegistry",
    "get_metrics_registry",
    "observe_duration",
    "record_operation",
    "start_span",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


LOGGER = get_logger(__name__)
StatusLiteral = Literal["success", "error"]
_SET_FROZEN_ATTR = object.__setattr__


def _thaw(target: object, **updates: object) -> None:
    """Assign ``updates`` to ``target`` bypassing frozen dataclass guards."""
    for name, value in updates.items():
        _SET_FROZEN_ATTR(target, name, value)


@dataclass(slots=True, frozen=True)
class _ObservabilityCache:
    """Internal cache for observability singletons.

    Caches provider and registry instances to avoid repeated initialization.
    Used internally by default() and get_metrics_registry() methods.

    Attributes
    ----------
    provider : MetricsProvider | None
        Cached metrics provider instance, or None if not yet initialized.
    registry : MetricsRegistry | None
        Cached metrics registry instance, or None if not yet initialized.
    """

    provider: MetricsProvider | None = None
    registry: MetricsRegistry | None = None


_OBS_CACHE = _ObservabilityCache()


@dataclass(slots=True, frozen=True)
# [nav:anchor MetricsProvider]
class MetricsProvider:
    """Provide component-level metrics for long-running operations.

    Extended Summary
    ----------------
    This class provides Prometheus-based metrics collection for component-level
    operations, tracking execution counts and durations. It initializes counters
    and histograms with appropriate labels (component, operation, status) and
    integrates with the Prometheus registry system. The provider is designed for
    long-running services where observability is critical for performance monitoring
    and debugging. It supports both default and custom registry configurations.

    Parameters
    ----------
    registry : CollectorRegistry | None, optional
        Prometheus registry to use. If None, uses the default registry.
        Defaults to None.

    Attributes
    ----------
    runs_total : CounterLike
        Counter for total number of operations executed by a component.
        Labeled by (component, status) for filtering and aggregation.

    Notes
    -----
    The class exposes ``operation_duration_seconds`` as a property (not a class
    attribute) to provide access to the duration histogram. Private attributes
    ``_operation_duration_seconds`` and ``_registry`` are used internally for
    implementation details. Thread-safe for concurrent metric observations.
    No I/O operations; all metrics are in-memory Prometheus collectors.
    """

    runs_total: CounterLike
    _operation_duration_seconds: HistogramLike = field(init=False, repr=False)
    _registry: CollectorRegistry | None = field(default=None, repr=False)

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        resolved_registry = cast("CollectorRegistry | None", registry or get_default_registry())
        histogram = build_histogram(
            "kgfoundry_operation_duration_seconds",
            "Operation duration in seconds for each component/operation pair.",
            labelnames=("component", "operation", "status"),
            registry=resolved_registry,
        )
        _thaw(
            self,
            _registry=resolved_registry,
            runs_total=build_counter(
                "kgfoundry_runs_total",
                "Total number of operations executed by a component.",
                ("component", "status"),
                registry=resolved_registry,
            ),
            _operation_duration_seconds=histogram,
        )

    @property
    def registry(self) -> CollectorRegistry | None:
        """Return the underlying Prometheus registry (may be ``None``)."""
        return self._registry

    @classmethod
    def default(cls) -> MetricsProvider:
        """Return a cached provider instance suitable for process-wide use.

        Returns
        -------
        MetricsProvider
            Cached metrics provider instance.
        """
        if _OBS_CACHE.provider is None:
            _thaw(_OBS_CACHE, provider=MetricsProvider())
        return cast("MetricsProvider", _OBS_CACHE.provider)

    @property
    def operation_duration_seconds(self) -> HistogramLike:
        """Prometheus histogram for operation durations."""
        return self._operation_duration_seconds

    def replace_operation_duration_histogram(self, histogram: HistogramLike) -> HistogramLike:
        """Replace the duration histogram (used in tests/instrumentation swaps).

        Parameters
        ----------
        histogram : HistogramLike
            Histogram instance that should back future duration observations.

        Returns
        -------
        HistogramLike
            The histogram that is now registered with this provider.
        """
        _thaw(self, _operation_duration_seconds=histogram)
        return histogram


@dataclass(slots=True, frozen=True)
# [nav:anchor MetricsRegistry]
class MetricsRegistry:
    """Expose request-level counters and histograms for HTTP surfaces.

    Initialises a metrics registry scoped to a namespace.

    Parameters
    ----------
    namespace : str, optional
        Namespace for metrics (e.g., "kgfoundry"). Defaults to "kgfoundry".
    registry : CollectorRegistry | None, optional
        Prometheus registry to use. If None, uses the default registry.
        Defaults to None.

    Attributes
    ----------
    requests_total : CounterLike
        Counter for total number of processed operations.
    request_errors_total : CounterLike
        Counter for total number of failed operations.
    request_duration_seconds : HistogramLike
        Histogram for operation latency in seconds.
    """

    requests_total: CounterLike
    request_errors_total: CounterLike
    request_duration_seconds: HistogramLike
    _registry: CollectorRegistry | None = field(default=None, repr=False)

    def __init__(
        self,
        *,
        namespace: str = "kgfoundry",
        registry: CollectorRegistry | None = None,
    ) -> None:
        resolved_registry = cast("CollectorRegistry | None", registry or get_default_registry())
        metric_prefix = namespace.replace("-", "_")
        labels = ("operation", "status")
        _thaw(
            self,
            _registry=resolved_registry,
            requests_total=build_counter(
                f"{metric_prefix}_requests_total",
                "Total number of processed operations.",
                labelnames=labels,
                registry=resolved_registry,
            ),
            request_errors_total=build_counter(
                f"{metric_prefix}_request_errors_total",
                "Total number of failed operations.",
                labelnames=labels,
                registry=resolved_registry,
            ),
            request_duration_seconds=build_histogram(
                f"{metric_prefix}_request_duration_seconds",
                "Operation latency in seconds.",
                labelnames=("operation",),
                registry=resolved_registry,
            ),
        )

    @property
    def registry(self) -> CollectorRegistry | None:
        """Return the underlying Prometheus registry (may be ``None``)."""
        return self._registry


# [nav:anchor get_metrics_registry]
def get_metrics_registry() -> MetricsRegistry:
    """Return the process-wide metrics registry singleton.

    Returns
    -------
    MetricsRegistry
        Process-wide metrics registry instance.
    """
    if _OBS_CACHE.registry is None:
        _thaw(_OBS_CACHE, registry=MetricsRegistry())
    return cast("MetricsRegistry", _OBS_CACHE.registry)


@dataclass(slots=True, frozen=True)
class DurationObservation:
    """Capture metrics and structured status for an in-flight operation."""

    metrics: MetricsProvider
    operation: str
    component: str
    correlation_id: str | None
    status: StatusLiteral = "success"
    _start: float = field(default_factory=time.monotonic)

    def mark_success(self) -> None:
        """Mark the operation as successful."""
        _thaw(self, status="success")

    def mark_error(self) -> None:
        """Mark the operation as failed."""
        _thaw(self, status="error")

    def success(self) -> None:  # pragma: no cover - backward compatibility alias
        """Alias for :meth:`mark_success` to preserve caller compatibility."""
        self.mark_success()

    def error(self) -> None:  # pragma: no cover - backward compatibility alias
        """Alias for :meth:`mark_error` to preserve caller compatibility."""
        self.mark_error()

    def duration_seconds(self) -> float:
        """Return the elapsed duration in seconds.

        Returns
        -------
        float
            Elapsed wall-clock duration since the observation began.
        """
        return time.monotonic() - self._start


class _DurationObservationContext:
    """Context manager that finalises :class:`DurationObservation` instances.

    Parameters
    ----------
    metrics : MetricsProvider
        Metrics provider instance for recording observations.
    operation : str
        Operation name being observed.
    component : str
        Component name executing the operation.
    correlation_id : str | None
        Correlation ID for tracing across services.
    """

    def __init__(
        self,
        *,
        metrics: MetricsProvider,
        operation: str,
        component: str,
        correlation_id: str | None,
    ) -> None:
        self._observation = DurationObservation(
            metrics=metrics,
            operation=operation,
            component=component,
            correlation_id=correlation_id,
        )

    def __enter__(self) -> DurationObservation:
        """Enter the observation context and return the observation instance.

        Returns
        -------
        DurationObservation
            Observation instance for marking success/error and recording metrics.
        """
        return self._observation

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        _tb: types.TracebackType | None,
    ) -> bool:
        """Exit the observation context and finalize metrics.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            Exception type if raised, None otherwise.
        exc : BaseException | None
            Exception instance if raised, None otherwise.
        _tb : types.TracebackType | None
            Exception traceback if raised, None otherwise.

        Returns
        -------
        bool
            False to propagate exceptions (does not suppress).
        """
        if exc_type is not None:
            self._observation.mark_error()
        _finalise_observation(self._observation)
        return False


# [nav:anchor observe_duration]
def observe_duration(
    metrics: MetricsProvider,
    operation: str,
    *,
    component: str = "unknown",
    correlation_id: str | None = None,
) -> _DurationObservationContext:
    """Record metrics and structured logs for a component operation.

    Parameters
    ----------
    metrics : MetricsProvider
        Metrics provider instance.
    operation : str
        Operation name.
    component : str, optional
        Component name. Defaults to "unknown".
    correlation_id : str | None, optional
        Correlation ID for tracing.

    Returns
    -------
    _DurationObservationContext
        Context manager yielding a :class:`DurationObservation` instance.

    Notes
    -----
    Exceptions raised within the managed block propagate after the observation
    is marked as ``"error"`` and metrics/logs are recorded.
    """
    return _DurationObservationContext(
        metrics=metrics,
        operation=operation,
        component=component,
        correlation_id=correlation_id,
    )


def _finalise_observation(observation: DurationObservation) -> None:
    """Finalize observation by recording metrics and structured logs.

    Records the operation duration, increments counters, and logs structured
    log entries with correlation ID, operation name, status, and duration.

    Parameters
    ----------
    observation : DurationObservation
        Observation instance to finalize. Must have status set (success or error).

    Notes
    -----
    This function is called automatically when exiting the observation context.
    It records Prometheus metrics (counter and histogram) and emits structured
    log entries with operation metadata.
    """
    duration = observation.duration_seconds()
    observation.metrics.runs_total.labels(
        component=observation.component,
        status=observation.status,
    ).inc()
    observation.metrics.operation_duration_seconds.labels(
        component=observation.component,
        operation=observation.operation,
        status=observation.status,
    ).observe(duration)
    extra = {
        "component": observation.component,
        "duration_ms": duration * 1000,
    }
    with with_fields(
        LOGGER,
        correlation_id=observation.correlation_id,
        operation=observation.operation,
        status=observation.status,
    ) as adapter:
        adapter.info("Operation completed", extra=extra)


@contextmanager
# [nav:anchor record_operation]
def record_operation(
    metrics: MetricsRegistry | None = None,
    *,
    operation: str = "unknown",
    correlation_id: str | None = None,
) -> Iterator[None]:
    """Track request counters and latency for an externally visible operation."""
    registry = metrics or get_metrics_registry()
    status: StatusLiteral = "success"
    start = time.monotonic()
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        duration = time.monotonic() - start
        registry.requests_total.labels(operation=operation, status=status).inc()
        if status == "error":
            registry.request_errors_total.labels(operation=operation, status=status).inc()
        registry.request_duration_seconds.labels(operation=operation).observe(duration)
        extra = {"duration_ms": duration * 1000}
        with with_fields(
            LOGGER,
            correlation_id=correlation_id,
            operation=operation,
            status=status,
        ) as adapter:
            if status == "error":
                adapter.error("Operation failed", extra=extra)
            else:
                adapter.info("Operation completed", extra=extra)


@contextmanager
# [nav:anchor start_span]
def start_span(
    name: str,
    attributes: Mapping[str, str | int | float | bool] | None = None,
) -> Iterator[None]:
    """Start an OpenTelemetry span when the optional dependency is available."""
    if trace_api is None:
        yield
        return

    tracer = trace_api.get_tracer(__name__)
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        try:
            yield
        except Exception as exc:  # pragma: no cover - requires OpenTelemetry at runtime
            span.record_exception(exc)
            if Status is not None and StatusCode is not None:
                error_code: StatusCodeProtocol = StatusCode.ERROR
                span.set_status(Status(error_code))
            raise
