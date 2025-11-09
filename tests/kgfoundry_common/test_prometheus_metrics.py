"""Prometheus metrics tests for observability instrumentation.

Verify:
- Counters increment correctly
- Histograms record operation durations
- Error scenarios update error counters
- Metric labels are set correctly
- Metrics are isolated per test via fixture
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

import pytest
from prometheus_client import Counter, Histogram

if TYPE_CHECKING:
    from _pytest.logging import LogCaptureFixture
    from prometheus_client.registry import CollectorRegistry
    from prometheus_client.samples import Sample

COUNTER_CASES: Final[tuple[tuple[str, str, int], ...]] = (
    ("search", "success", 1),
    ("index", "success", 2),
    ("delete", "error", 1),
    ("search", "error", 3),
)
COUNTER_CASE_IDS: Final[tuple[str, ...]] = (
    "search_success",
    "index_multiple",
    "delete_error",
    "search_error_multi",
)

HISTOGRAM_DURATIONS: Final[tuple[float, ...]] = (0.001, 0.01, 0.1, 1.0, 10.0)
HISTOGRAM_DURATION_IDS: Final[tuple[str, ...]] = ("1ms", "10ms", "100ms", "1s", "10s")

ERROR_TYPE_CASES: Final[tuple[tuple[str, type[Exception]], ...]] = (
    ("ValueError", ValueError),
    ("TimeoutError", TimeoutError),
    ("RuntimeError", RuntimeError),
)
ERROR_TYPE_IDS: Final[tuple[str, ...]] = (
    "value_error",
    "timeout_error",
    "runtime_error",
)


def _get_first_metric_samples(registry: CollectorRegistry) -> list[Sample]:
    """Extract first metric's samples from registry.

    Parameters
    ----------
    registry : CollectorRegistry
        Prometheus registry.

    Returns
    -------
    list[Sample]
        Samples from first metric.
    """
    metric = next(iter(registry.collect()))
    samples: list[Sample] = list(metric.samples)
    return samples


class TestCounterMetrics:
    """Verify counter metrics increment correctly."""

    def test_counter_increment_success(self, prometheus_registry: CollectorRegistry) -> None:
        """Verify success counter increments on operation.

        Parameters
        ----------
        prometheus_registry : CollectorRegistry
            Isolated Prometheus registry for test.
        """
        # Create counter in test registry
        counter = Counter(
            "test_operations_total",
            "Total operations",
            ["status"],
            registry=prometheus_registry,
        )

        # Simulate success
        counter.labels(status="success").inc()
        counter.labels(status="success").inc()

        # Verify count (Prometheus creates both _total and _created metrics)
        samples = _get_first_metric_samples(prometheus_registry)
        success_total = [
            s
            for s in samples
            if s.labels.get("status") == "success" and s.name == "test_operations_total"
        ]
        assert len(success_total) == 1
        assert success_total[0].value == 2.0

    def test_counter_increment_failure(self, prometheus_registry: CollectorRegistry) -> None:
        """Verify error counter increments on failure.

        Parameters
        ----------
        prometheus_registry : CollectorRegistry
            Isolated Prometheus registry for test.
        """
        # Create counter in test registry
        counter = Counter(
            "test_operations_total",
            "Total operations",
            ["status"],
            registry=prometheus_registry,
        )

        # Simulate failures
        counter.labels(status="error").inc()
        counter.labels(status="error").inc()
        counter.labels(status="error").inc()

        # Verify count (Prometheus creates both _total and _created metrics)
        samples = _get_first_metric_samples(prometheus_registry)
        error_total = [
            s
            for s in samples
            if s.labels.get("status") == "error" and s.name == "test_operations_total"
        ]
        assert len(error_total) == 1
        assert error_total[0].value == 3.0

    @pytest.mark.parametrize(
        ("operation", "status", "expected_count"),
        COUNTER_CASES,
        ids=COUNTER_CASE_IDS,
    )
    def test_counter_by_operation_and_status(
        self,
        prometheus_registry: CollectorRegistry,
        operation: str,
        status: str,
        expected_count: int,
    ) -> None:
        """Verify counter tracks operations by type and status.

        Parameters
        ----------
        prometheus_registry : CollectorRegistry
            Isolated Prometheus registry for test.
        operation : str
            Operation type.
        status : str
            Operation status.
        expected_count : int
            Expected counter value.
        """
        counter = Counter(
            "operations_total",
            "Total operations",
            ["operation", "status"],
            registry=prometheus_registry,
        )

        # Increment counter by expected count
        for _ in range(expected_count):
            counter.labels(operation=operation, status=status).inc()

        # Verify (Prometheus creates both _total and _created metrics)
        samples = _get_first_metric_samples(prometheus_registry)
        matching = [
            s
            for s in samples
            if (
                s.labels.get("operation") == operation
                and s.labels.get("status") == status
                and s.name == "operations_total"
            )
        ]
        assert len(matching) == 1
        assert matching[0].value == float(expected_count)


class TestHistogramMetrics:
    """Verify histogram metrics record durations."""

    def test_histogram_observe_duration(self, prometheus_registry: CollectorRegistry) -> None:
        """Verify histogram observes operation durations.

        Parameters
        ----------
        prometheus_registry : CollectorRegistry
            Isolated Prometheus registry for test.
        """
        histogram = Histogram(
            "operation_duration_seconds",
            "Operation duration",
            registry=prometheus_registry,
        )

        # Observe durations
        histogram.observe(0.1)
        histogram.observe(0.2)
        histogram.observe(0.05)

        # Verify count
        samples = _get_first_metric_samples(prometheus_registry)
        count_samples = [s for s in samples if s.name.endswith("_count")]
        assert len(count_samples) >= 1
        assert count_samples[0].value == 3.0

    def test_histogram_by_operation_type(self, prometheus_registry: CollectorRegistry) -> None:
        """Verify histogram can bucket by operation type.

        Parameters
        ----------
        prometheus_registry : CollectorRegistry
            Isolated Prometheus registry for test.
        """
        histogram = Histogram(
            "operation_duration_seconds",
            "Operation duration",
            ["operation"],
            registry=prometheus_registry,
        )

        # Record durations for different operations
        histogram.labels(operation="search").observe(0.15)
        histogram.labels(operation="search").observe(0.25)
        histogram.labels(operation="index").observe(1.5)

        # Verify search count is 2
        samples = _get_first_metric_samples(prometheus_registry)
        search_counts = [
            s
            for s in samples
            if s.name.endswith("_count") and s.labels.get("operation") == "search"
        ]
        assert len(search_counts) >= 1
        assert search_counts[0].value == 2.0

    @pytest.mark.parametrize(
        "duration",
        HISTOGRAM_DURATIONS,
        ids=HISTOGRAM_DURATION_IDS,
    )
    def test_histogram_across_ranges(
        self,
        prometheus_registry: CollectorRegistry,
        duration: float,
    ) -> None:
        """Verify histogram observes durations across ranges.

        Parameters
        ----------
        prometheus_registry : CollectorRegistry
            Isolated Prometheus registry for test.
        duration : float
            Duration to observe.
        """
        histogram = Histogram(
            "request_duration_seconds",
            "Request duration",
            registry=prometheus_registry,
        )

        histogram.observe(duration)

        # Verify observation recorded
        samples = _get_first_metric_samples(prometheus_registry)
        count_samples = [s for s in samples if s.name.endswith("_count")]
        assert len(count_samples) >= 1
        assert count_samples[0].value >= 1.0


class TestMetricsOnErrorPaths:
    """Verify metrics are emitted on error scenarios."""

    @staticmethod
    def _simulate_value_error() -> None:
        """Raise ValueError for testing.

        Raises
        ------
        ValueError
            Always raised with a test message.
        """
        msg = "Test error"
        raise ValueError(msg) from None

    def test_error_counter_on_exception(
        self,
        prometheus_registry: CollectorRegistry,
        caplog: LogCaptureFixture,
    ) -> None:
        """Verify error counter increments when exception occurs.

        Parameters
        ----------
        prometheus_registry : CollectorRegistry
            Isolated Prometheus registry for test.
        caplog : LogCaptureFixture
            Log capture fixture for capturing log messages during test execution.
        """
        error_counter = Counter(
            "operations_failed_total",
            "Failed operations",
            ["error_type"],
            registry=prometheus_registry,
        )

        # Simulate error scenario
        caplog.set_level(logging.ERROR)
        try:
            self._simulate_value_error()
        except ValueError:
            error_counter.labels(error_type="ValueError").inc()
            logging.getLogger(__name__).exception("Operation failed")

        # Verify counter
        samples = _get_first_metric_samples(prometheus_registry)
        error_total = [
            s
            for s in samples
            if s.labels.get("error_type") == "ValueError" and s.name == "operations_failed_total"
        ]
        assert len(error_total) == 1
        assert error_total[0].value == 1.0

    def _simulate_error_of_type(self, error_class: type[Exception]) -> None:
        """Raise error of specified type for testing."""
        msg = "Test"
        raise error_class(msg) from None

    @pytest.mark.parametrize(
        ("error_type", "error_class"),
        ERROR_TYPE_CASES,
        ids=ERROR_TYPE_IDS,
    )
    def test_error_counter_by_type(
        self,
        prometheus_registry: CollectorRegistry,
        error_type: str,
        error_class: type[Exception],
    ) -> None:
        """Verify error counter tracks by error type.

        Parameters
        ----------
        prometheus_registry : CollectorRegistry
            Isolated Prometheus registry for test.
        error_type : str
            Error type label.
        error_class : type[Exception]
            Exception class.
        """
        counter = Counter(
            "errors_total",
            "Total errors",
            ["error_type"],
            registry=prometheus_registry,
        )

        # Simulate multiple errors of same type
        for _ in range(2):
            try:
                self._simulate_error_of_type(error_class)
            except error_class:
                counter.labels(error_type=error_type).inc()

        # Verify
        samples = _get_first_metric_samples(prometheus_registry)
        matching = [
            s
            for s in samples
            if s.labels.get("error_type") == error_type and s.name == "errors_total"
        ]
        assert len(matching) == 1
        assert matching[0].value == 2.0


class TestMetricsIntegration:
    """Verify counter and histogram work together."""

    def test_counter_and_histogram_together(
        self,
        prometheus_registry: CollectorRegistry,
    ) -> None:
        """Verify counter and histogram can coexist in same registry.

        Parameters
        ----------
        prometheus_registry : CollectorRegistry
            Isolated Prometheus registry for test.
        """
        counter = Counter(
            "operations_total",
            "Total operations",
            registry=prometheus_registry,
        )
        histogram = Histogram(
            "operation_duration_seconds",
            "Operation duration",
            registry=prometheus_registry,
        )

        # Simulate operations
        counter.inc()
        histogram.observe(0.1)
        counter.inc()
        histogram.observe(0.2)

        # Verify both metrics recorded
        metrics = list(prometheus_registry.collect())
        assert len(metrics) == 2  # Counter and Histogram are separate metrics

        # Find samples - filter by sample name, not metric name
        counter_samples = [s for m in metrics for s in m.samples if s.name == "operations_total"]
        histogram_samples = [
            s for m in metrics for s in m.samples if "operation_duration_seconds" in s.name
        ]

        assert len(counter_samples) >= 1
        assert len(histogram_samples) >= 1
        # Find the _total sample (not _created)
        counter_total = [s for s in counter_samples if s.name == "operations_total"]
        assert len(counter_total) >= 1
        assert counter_total[0].value == 2.0


__all__ = [
    "TestCounterMetrics",
    "TestHistogramMetrics",
    "TestMetricsIntegration",
    "TestMetricsOnErrorPaths",
]
