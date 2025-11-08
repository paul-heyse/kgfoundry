"""Observability instrumentation for navmap utilities.

This module provides Prometheus metrics and structured logging helpers for
navmap operations (build, check, repair, migrate). Metrics follow Prometheus
naming conventions and include operation/status tags. The metrics originate from
the typed facade documented in ``tools/_shared/observability_facade.md`` and
comply with the "Eliminate Pyrefly Suppressions" spec so they become no-ops if
``prometheus_client`` is not installed.
"""

from __future__ import annotations

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


class NavmapMetrics:
    """Metrics registry for navmap utilities following Prometheus conventions.

    Metrics follow the naming pattern: ``navmap_<operation>_total`` for
    counters and ``navmap_<operation>_duration_seconds`` for histograms.

    Attributes
    ----------
    build_runs_total : CounterLike
        Total number of navmap build operations.
    check_runs_total : CounterLike
        Total number of navmap check operations.
    repair_runs_total : CounterLike
        Total number of navmap repair operations.
    migrate_runs_total : CounterLike
        Total number of navmap migrate operations.
    build_duration_seconds : HistogramLike
        Duration of build operations in seconds.
    check_duration_seconds : HistogramLike
        Duration of check operations in seconds.
    repair_duration_seconds : HistogramLike
        Duration of repair operations in seconds.
    migrate_duration_seconds : HistogramLike
        Duration of migrate operations in seconds.

    Parameters
    ----------
    registry : CollectorRegistry | None, optional
        Prometheus registry (defaults to default registry).

    Examples
    --------
    >>> metrics = NavmapMetrics()
    >>> metrics.build_runs_total.labels(status="success").inc()
    >>> metrics.repair_duration_seconds.labels(status="success").observe(0.123)
    """

    build_runs_total: CounterLike
    check_runs_total: CounterLike
    repair_runs_total: CounterLike
    migrate_runs_total: CounterLike
    build_duration_seconds: HistogramLike
    check_duration_seconds: HistogramLike
    repair_duration_seconds: HistogramLike
    migrate_duration_seconds: HistogramLike

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        resolved = (
            registry if registry is not None else cast("CollectorRegistry", get_default_registry())
        )
        self.registry = resolved

        self.build_runs_total = build_counter(
            "navmap_build_runs_total",
            "Total number of navmap build operations",
            ["status"],
            registry=resolved,
        )

        self.check_runs_total = build_counter(
            "navmap_check_runs_total",
            "Total number of navmap check operations",
            ["status"],
            registry=resolved,
        )

        self.repair_runs_total = build_counter(
            "navmap_repair_runs_total",
            "Total number of navmap repair operations",
            ["status"],
            registry=resolved,
        )

        self.migrate_runs_total = build_counter(
            "navmap_migrate_runs_total",
            "Total number of navmap migrate operations",
            ["status"],
            registry=resolved,
        )

        self.build_duration_seconds = build_histogram(
            "navmap_build_duration_seconds",
            "Duration of navmap build operations in seconds",
            ["status"],
            registry=resolved,
        )

        self.check_duration_seconds = build_histogram(
            "navmap_check_duration_seconds",
            "Duration of navmap check operations in seconds",
            ["status"],
            registry=resolved,
        )

        self.repair_duration_seconds = build_histogram(
            "navmap_repair_duration_seconds",
            "Duration of navmap repair operations in seconds",
            ["status"],
            registry=resolved,
        )

        self.migrate_duration_seconds = build_histogram(
            "navmap_migrate_duration_seconds",
            "Duration of navmap migrate operations in seconds",
            ["status"],
            registry=resolved,
        )


@dataclass(slots=True, frozen=True)
class _NavmapMetricsCache:
    """Internal cache for navmap metrics singleton."""

    registry: NavmapMetrics | None = None


_METRICS_CACHE = _NavmapMetricsCache()


def get_metrics_registry() -> NavmapMetrics:
    """Get or create the global metrics registry.

    Returns
    -------
    NavmapMetrics
        Global metrics registry instance.

    Examples
    --------
    >>> metrics = get_metrics_registry()
    >>> metrics.build_runs_total.labels(status="success").inc()
    """
    if _METRICS_CACHE.registry is None:
        _METRICS_CACHE.registry = NavmapMetrics()
    return _METRICS_CACHE.registry


def get_correlation_id() -> str:
    """Generate a correlation ID for tracing operations across boundaries.

    Returns
    -------
    str
        Correlation ID in the format ``urn:navmap:correlation:<uuid>``.

    Examples
    --------
    >>> cid = get_correlation_id()
    >>> assert cid.startswith("urn:navmap:correlation:")
    """
    return f"urn:navmap:correlation:{uuid.uuid4().hex}"


@contextmanager
def record_operation_metrics(
    operation: str,
    status: str = "success",
    correlation_id: str | None = None,
) -> Iterator[None]:
    """Record navmap operation metrics and duration.

    This context manager tracks the execution of navmap operations (build, check,
    repair, migrate) by recording Prometheus metrics including duration histograms
    and status counters. It automatically updates the status to "error" if an
    exception occurs within the context.

    Parameters
    ----------
    operation : str
        Operation name (e.g., "build", "check", "repair", "migrate").
    status : str, optional
        Initial status label ("success" or "error"), by default "success".
        Automatically updated to "error" if an exception occurs.
    correlation_id : str | None, optional
        Correlation ID for distributed tracing across service boundaries.
        When ``None``, a new correlation ID is auto-generated.

    Yields
    ------
    None
        Context manager that yields control to the wrapped navmap operation block.

    Raises
    ------
    Exception
        Any exception raised within the context is explicitly re-raised after
        metrics are recorded, allowing normal exception handling to proceed. The
        exception is caught using ``except Exception as exc``, metrics are updated
        to reflect the error, and then the exception is explicitly re-raised.

    Examples
    --------
    >>> with record_operation_metrics("build", status="success"):
    ...     # Build operation
    ...     pass
    """
    if correlation_id is None:
        correlation_id = get_correlation_id()

    metrics = get_metrics_registry()
    log_adapter = with_fields(
        _LOGGER,
        operation=operation,
        correlation_id=correlation_id,
    )
    start_time = time.monotonic()
    final_status = status

    try:
        yield
    except Exception as exc:
        final_status = "error"
        raise exc  # noqa: TRY201
    finally:
        duration = time.monotonic() - start_time

        if operation == "build":
            metrics.build_runs_total.labels(status=final_status).inc()
            metrics.build_duration_seconds.labels(status=final_status).observe(duration)
        elif operation == "check":
            metrics.check_runs_total.labels(status=final_status).inc()
            metrics.check_duration_seconds.labels(status=final_status).observe(duration)
        elif operation == "repair":
            metrics.repair_runs_total.labels(status=final_status).inc()
            metrics.repair_duration_seconds.labels(status=final_status).observe(duration)
        elif operation == "migrate":
            metrics.migrate_runs_total.labels(status=final_status).inc()
            metrics.migrate_duration_seconds.labels(status=final_status).observe(duration)

        with_fields(
            log_adapter,
            status=final_status,
            duration_seconds=duration,
        ).info("Navmap operation completed")
