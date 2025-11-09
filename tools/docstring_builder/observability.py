"""Observability instrumentation for the docstring builder.

This module provides Prometheus metrics, structured logging helpers, and optional
OpenTelemetry tracing for the docstring builder pipeline. Metrics follow Prometheus
naming conventions and include operation/status tags. All metrics are constructed
through the typed facade described in ``tools/_shared/observability_facade.md``
so they degrade to no-op stubs when ``prometheus_client`` is unavailable (see the
"Eliminate Pyrefly Suppressions" requirement in the code-quality spec).

Examples
--------
>>> from tools.docstring_builder.observability import (
...     get_metrics_registry,
...     record_operation_metrics,
...     get_correlation_id,
... )
>>> metrics = get_metrics_registry()
>>> correlation_id = get_correlation_id()
>>> with record_operation_metrics("harvest", correlation_id):
...     # Harvest operation
...     pass
"""

from __future__ import annotations

import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from tools._shared.logging import get_logger, with_fields
from tools._shared.prometheus import (
    build_counter,
    build_histogram,
    get_default_registry,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tools._shared.prometheus import (
        CollectorRegistry,
        CounterLike,
        HistogramLike,
    )


_LOGGER = get_logger(__name__)


class DocstringBuilderMetrics:
    """Metrics registry for the docstring builder following Prometheus conventions.

    Metrics follow the naming pattern: ``docbuilder_<operation>_<unit>_total`` for
    counters and ``docbuilder_<operation>_duration_seconds`` for histograms.

    Attributes
    ----------
    runs_total : CounterLike
        Total number of docstring builder runs.
    plugin_failures_total : CounterLike
        Total number of plugin execution failures.
    harvest_duration_seconds : HistogramLike
        Duration of harvest operations in seconds.
    policy_duration_seconds : HistogramLike
        Duration of policy engine operations in seconds.
    render_duration_seconds : HistogramLike
        Duration of rendering operations in seconds.
    cli_duration_seconds : HistogramLike
        Duration of CLI operations in seconds.

    Parameters
    ----------
    registry : CollectorRegistry | None, optional
        Prometheus registry (defaults to default registry).

    Examples
    --------
    >>> metrics = DocstringBuilderMetrics()
    >>> metrics.runs_total.labels(status="success").inc()
    >>> metrics.harvest_duration_seconds.labels(status="success").observe(0.123)
    """

    runs_total: CounterLike
    plugin_failures_total: CounterLike
    harvest_duration_seconds: HistogramLike
    policy_duration_seconds: HistogramLike
    render_duration_seconds: HistogramLike
    cli_duration_seconds: HistogramLike

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        resolved_registry = (
            registry if registry is not None else cast("CollectorRegistry", get_default_registry())
        )
        self.registry = resolved_registry

        self.runs_total = build_counter(
            "docbuilder_runs_total",
            "Total number of docstring builder runs",
            ["status"],
            registry=self.registry,
        )

        self.plugin_failures_total = build_counter(
            "docbuilder_plugin_failures_total",
            "Total number of plugin execution failures",
            ["plugin_name", "error_type"],
            registry=self.registry,
        )

        self.harvest_duration_seconds = build_histogram(
            "docbuilder_harvest_duration_seconds",
            "Duration of harvest operations in seconds",
            labelnames=["status"],
            registry=self.registry,
        )

        self.policy_duration_seconds = build_histogram(
            "docbuilder_policy_duration_seconds",
            "Duration of policy engine operations in seconds",
            labelnames=["status"],
            registry=self.registry,
        )

        self.render_duration_seconds = build_histogram(
            "docbuilder_render_duration_seconds",
            "Duration of rendering operations in seconds",
            labelnames=["status"],
            registry=self.registry,
        )

        self.cli_duration_seconds = build_histogram(
            "docbuilder_cli_duration_seconds",
            "Duration of CLI operations in seconds",
            labelnames=["command", "status"],
            registry=self.registry,
        )


@dataclass(slots=True, frozen=True)
class _DocstringBuilderMetricsCache:
    """Singleton cache for docstring builder metrics."""

    registry: DocstringBuilderMetrics | None = None


_SET_CACHE_ATTR = object.__setattr__
_METRICS_CACHE = _DocstringBuilderMetricsCache()


def _set_cache_value(cache: _DocstringBuilderMetricsCache, **updates: object) -> None:
    for name, value in updates.items():
        _SET_CACHE_ATTR(cache, name, value)


def get_metrics_registry() -> DocstringBuilderMetrics:
    """Get or create the global metrics registry.

    Returns
    -------
    DocstringBuilderMetrics
        Global metrics registry instance.

    Examples
    --------
    >>> metrics = get_metrics_registry()
    >>> metrics.runs_total.labels(status="success").inc()
    """
    if _METRICS_CACHE.registry is None:
        _set_cache_value(_METRICS_CACHE, registry=DocstringBuilderMetrics())
    return cast("DocstringBuilderMetrics", _METRICS_CACHE.registry)


def get_correlation_id() -> str:
    """Generate a correlation ID for tracing operations across boundaries.

    Returns
    -------
    str
        Correlation ID in the format ``urn:docbuilder:correlation:<uuid>``.

    Examples
    --------
    >>> corr_id = get_correlation_id()
    >>> assert corr_id.startswith("urn:docbuilder:correlation:")
    """
    return f"urn:docbuilder:correlation:{uuid.uuid4().hex}"


@contextmanager
def record_operation_metrics(
    operation: str,
    correlation_id: str | None = None,
    *,
    metrics: DocstringBuilderMetrics | None = None,
    status: str = "success",
) -> Iterator[None]:
    """Context manager to record operation metrics and duration.

    Parameters
    ----------
    operation : str
        Operation name (e.g., "harvest", "policy", "render", "cli").
    correlation_id : str | None, optional
        Correlation ID for tracing (default: auto-generated).
    metrics : DocstringBuilderMetrics | None, optional
        Metrics registry (defaults to global registry).
    status : str, optional
        Initial status (default: "success"); updated to "error" on exception.

    Yields
    ------
    None
        Context manager yields control to the operation block.

    Examples
    --------
    >>> from tools.docstring_builder.observability import (
    ...     record_operation_metrics,
    ...     get_correlation_id,
    ... )
    >>> corr_id = get_correlation_id()
    >>> with record_operation_metrics("harvest", corr_id):
    ...     # Perform harvest operation
    ...     pass
    """
    if metrics is None:
        metrics = get_metrics_registry()

    if correlation_id is None:
        correlation_id = get_correlation_id()

    log_adapter = with_fields(
        _LOGGER,
        operation=operation,
        correlation_id=correlation_id,
    )

    start_time = time.monotonic()
    final_status = status

    try:
        yield
    finally:
        exc_type, _, _ = sys.exc_info()
        if exc_type is not None and issubclass(exc_type, Exception):
            final_status = "error"
        duration = time.monotonic() - start_time

        if operation == "harvest":
            metrics.harvest_duration_seconds.labels(status=final_status).observe(duration)
        elif operation == "policy":
            metrics.policy_duration_seconds.labels(status=final_status).observe(duration)
        elif operation == "render":
            metrics.render_duration_seconds.labels(status=final_status).observe(duration)
        elif operation == "cli":
            # CLI status is determined by the command, not the operation
            # This is a simplified version; CLI should pass command explicitly
            metrics.cli_duration_seconds.labels(command="unknown", status=final_status).observe(
                duration
            )

        with_fields(
            log_adapter,
            status=final_status,
            duration_seconds=duration,
        ).info("Docstring builder operation completed")


__all__ = [
    "DocstringBuilderMetrics",
    "get_correlation_id",
    "get_metrics_registry",
    "record_operation_metrics",
]
