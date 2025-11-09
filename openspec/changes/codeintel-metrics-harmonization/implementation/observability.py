"""Unified observability helper for CodeIntel MCP adapters.

This module provides a single shared implementation of metrics observation patterns
that was previously duplicated across multiple adapters. It wraps the
:mod:`kgfoundry_common.observability` infrastructure with adapter-specific defaults
and graceful degradation for disabled metrics.

Examples
--------
Basic usage in an adapter:

>>> from codeintel_rev.mcp_server.common.observability import observe_duration
>>> with observe_duration("search", "text_search") as obs:
...     # Perform operation
...     result = perform_search()
...     obs.mark_success()
...     return result

With error handling:

>>> with observe_duration("semantic_search", "codeintel_mcp") as obs:
...     try:
...         result = search_vectors()
...         obs.mark_success()
...         return result
...     except VectorSearchError as exc:
...         obs.mark_error()
...         raise

Notes
-----
This module eliminates 60+ lines of duplicated boilerplate previously present in
`text_search.py` and `semantic.py`. It provides:

- Graceful degradation when Prometheus metrics unavailable
- Integration with `kgfoundry_common.observability.MetricsProvider`
- Consistent metrics naming and labeling
- Noop fallback for disabled histogram labels
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from kgfoundry_common.logging import get_logger
from kgfoundry_common.observability import (
    MetricsProvider,
)
from kgfoundry_common.observability import (
    observe_duration as kgfoundry_observe_duration,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from kgfoundry_common.observability import DurationObservation

__all__ = ["observe_duration"]

LOGGER = get_logger(__name__)


def _supports_histogram_labels(histogram: object) -> bool:
    """Check if histogram supports labeled metrics.

    Parameters
    ----------
    histogram : object
        Histogram metric object (HistogramLike protocol).

    Returns
    -------
    bool
        True if histogram supports labels, False otherwise.

    Notes
    -----
    This function checks if the histogram has ``_labelnames`` attribute and
    whether it's non-empty. Histograms without label support will gracefully
    degrade to noop observation.
    """
    labelnames = getattr(histogram, "_labelnames", None)
    if labelnames is None:
        return True
    try:
        return len(tuple(labelnames)) > 0
    except TypeError:
        return False


class _NoopObservation:
    """Fallback observation when Prometheus metrics are unavailable.

    This class provides the same interface as
    :class:`kgfoundry_common.observability.DurationObservation` but performs
    no actual metric recording. Used for graceful degradation when metrics
    are disabled or Prometheus is not configured.
    """

    def mark_error(self) -> None:
        """No-op error marker.

        Does nothing. Satisfies DurationObservation interface for type safety.
        """

    def mark_success(self) -> None:
        """No-op success marker.

        Does nothing. Satisfies DurationObservation interface for type safety.
        """


@contextmanager
def observe_duration(
    operation: str,
    component: str,
    *,
    metrics: MetricsProvider | None = None,
) -> Iterator[DurationObservation | _NoopObservation]:
    """Yield a metrics observation with graceful degradation.

    This context manager wraps :func:`kgfoundry_common.observability.observe_duration`
    with adapter-specific defaults and graceful fallback when metrics are disabled.
    It records operation duration in the
    ``kgfoundry_operation_duration_seconds`` histogram with labels for
    component, operation, and status.

    Parameters
    ----------
    operation : str
        Operation name for metrics labeling (e.g., ``"search"``,
        ``"semantic_search"``). Appears as ``operation`` label in metrics.
    component : str
        Component name for metrics labeling (e.g., ``"text_search"``,
        ``"codeintel_mcp"``). Appears as ``component`` label in metrics.
    metrics : MetricsProvider | None, optional
        Metrics provider instance. If None, uses ``MetricsProvider.default()``.
        Defaults to None.

    Yields
    ------
    DurationObservation | _NoopObservation
        Metrics observation when Prometheus is configured, otherwise a no-op
        recorder. Call ``mark_success()`` or ``mark_error()`` on the yielded
        object to record completion status.

    Notes
    -----
    Exception Propagation:
        Any exception raised within the context manager is propagated after
        metrics are recorded (if enabled). The function itself does not raise
        exceptions, but exceptions from the wrapped operation propagate through.

    Examples
    --------
    Record successful operation:

    >>> with observe_duration("search", "text_search") as obs:
    ...     result = perform_search()
    ...     obs.mark_success()

    Record failed operation:

    >>> with observe_duration("semantic_search", "codeintel_mcp") as obs:
    ...     try:
    ...         result = search_vectors()
    ...         obs.mark_success()
    ...     except VectorSearchError:
    ...         obs.mark_error()
    ...         raise

    Notes
    -----
    Metrics Behavior:
    - When Prometheus is available, records duration in ``kgfoundry_operation_duration_seconds``
    - Histogram labels: ``component``, ``operation``, ``status`` (``"success"`` or ``"error"``)
    - When Prometheus unavailable, yields noop observation (no metrics recorded)

    Graceful Degradation:
    - If ``MetricsProvider`` histogram doesn't support labels, yields noop
    - If ``observe_duration`` raises ``ValueError``, yields noop
    - Operation continues successfully even when metrics fail

    Integration:
    - Wraps ``kgfoundry_common.observability.observe_duration``
    - Uses ``MetricsProvider.default()`` for consistent metrics registry
    - Compatible with existing kgfoundry metrics infrastructure
    """
    provider = metrics or MetricsProvider.default()

    # Check if histogram supports labels (graceful degradation)
    if not _supports_histogram_labels(provider.operation_duration_seconds):
        LOGGER.debug(
            "Metrics disabled (histogram labels not supported)",
            extra={"operation": operation, "component": component},
        )
        yield _NoopObservation()
        return

    # Attempt to use real observation with fallback to noop
    try:
        with kgfoundry_observe_duration(
            provider, operation, component=component
        ) as observation:
            yield observation
            return
    except ValueError as exc:
        LOGGER.warning(
            "Metrics observation failed, using noop fallback",
            extra={
                "operation": operation,
                "component": component,
                "error": str(exc),
            },
        )
        yield _NoopObservation()
