"""Unit tests for the shared observability helper in CodeIntel MCP."""

from __future__ import annotations

from typing import NoReturn, cast

import pytest
from codeintel_rev.mcp_server.common.observability import observe_duration
from prometheus_client import CollectorRegistry

from kgfoundry_common.observability import MetricsProvider
from kgfoundry_common.prometheus import HAVE_PROMETHEUS, HistogramLike

pytestmark = pytest.mark.skipif(
    not HAVE_PROMETHEUS,
    reason="Prometheus client not installed; metrics tests bypassed.",
)


def _get_sample_value(
    registry: CollectorRegistry,
    metric: str,
    labels: dict[str, str],
) -> float | None:
    """Return the Prometheus sample value for the given metric/labels.

    Returns
    -------
    float | None
        Captured sample value when present; ``None`` when no sample matches the
        provided labels.
    """
    return registry.get_sample_value(metric, labels)


def test_observe_duration_records_success(
    prometheus_registry: CollectorRegistry,
) -> None:
    """Successful observations increment the success counters and histograms."""
    provider = MetricsProvider(registry=prometheus_registry)
    component = "codeintel_mcp"
    operation = "semantic_search"

    with observe_duration(operation, component, metrics=provider) as observation:
        observation.mark_success()

    histogram = _get_sample_value(
        prometheus_registry,
        "kgfoundry_operation_duration_seconds_count",
        {"component": component, "operation": operation, "status": "success"},
    )
    runs_total = _get_sample_value(
        prometheus_registry,
        "kgfoundry_runs_total",
        {"component": component, "status": "success"},
    )

    assert histogram == pytest.approx(1.0)
    assert runs_total == pytest.approx(1.0)


def test_observe_duration_records_error_on_exception(
    prometheus_registry: CollectorRegistry,
) -> None:
    """Exceptions propagate while recording error metrics.

    Raises
    ------
    RuntimeError
        Forwarded from the managed block under test.
    """
    provider = MetricsProvider(registry=prometheus_registry)
    component = "codeintel_mcp"
    operation = "text_search"
    failure_message = "failure during operation"

    with (
        pytest.raises(RuntimeError, match=failure_message),
        observe_duration(
            operation,
            component,
            metrics=provider,
        ),
    ):
        raise RuntimeError(failure_message)

    histogram = _get_sample_value(
        prometheus_registry,
        "kgfoundry_operation_duration_seconds_count",
        {"component": component, "operation": operation, "status": "error"},
    )
    runs_total = _get_sample_value(
        prometheus_registry,
        "kgfoundry_runs_total",
        {"component": component, "status": "error"},
    )

    assert histogram == pytest.approx(1.0)
    assert runs_total == pytest.approx(1.0)


def test_observe_duration_noop_when_histogram_labels_disabled(
    prometheus_registry: CollectorRegistry,
) -> None:
    """Observations fall back to no-op when histograms do not expose labels."""
    provider = MetricsProvider(registry=prometheus_registry)
    component = "codeintel_mcp"
    operation = "scope_scan"

    class _HistogramWithoutLabels:
        _labelnames: tuple[str, ...] = ()

        def labels(self, **_: object) -> _HistogramWithoutLabels:
            return self

        def observe(self, *_args: object, **_kwargs: object) -> None:
            pytest.fail("metrics should not be recorded when labels are missing")

    provider.replace_operation_duration_histogram(cast("HistogramLike", _HistogramWithoutLabels()))

    with observe_duration(operation, component, metrics=provider) as observation:
        # No metrics should be recorded but methods remain safe to call.
        observation.mark_success()
        observation.mark_error()

    histogram = _get_sample_value(
        prometheus_registry,
        "kgfoundry_operation_duration_seconds_count",
        {"component": component, "operation": operation, "status": "success"},
    )
    runs_total = _get_sample_value(
        prometheus_registry,
        "kgfoundry_runs_total",
        {"component": component, "status": "success"},
    )

    assert histogram is None
    assert runs_total is None


def test_observe_duration_noop_when_base_observer_raises_value_error(
    prometheus_registry: CollectorRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ValueError from base observer triggers noop fallback."""
    provider = MetricsProvider(registry=prometheus_registry)
    component = "codeintel_mcp"
    operation = "vector_query"
    error_message = "metrics disabled"

    def _raise_value_error(*_args: object, **_kwargs: object) -> NoReturn:
        raise ValueError(error_message)

    monkeypatch.setattr(
        "codeintel_rev.mcp_server.common.observability._base_observe_duration",
        _raise_value_error,
    )

    with observe_duration(operation, component, metrics=provider) as observation:
        observation.mark_success()

    histogram = _get_sample_value(
        prometheus_registry,
        "kgfoundry_operation_duration_seconds_count",
        {"component": component, "operation": operation, "status": "success"},
    )
    runs_total = _get_sample_value(
        prometheus_registry,
        "kgfoundry_runs_total",
        {"component": component, "status": "success"},
    )

    assert histogram is None
    assert runs_total is None
