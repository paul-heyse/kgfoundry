"""Unified observability helpers for CodeIntel MCP adapters.

The adapters previously duplicated more than sixty lines of metrics boilerplate.
This module centralises the logic, delegates to :mod:`kgfoundry_common`
observability primitives, and keeps behaviour backward compatible with existing
Prometheus dashboards.

Examples
--------
Basic usage in an adapter:

>>> from codeintel_rev.mcp_server.common.observability import observe_duration
>>> with observe_duration("search", "text_search") as observation:
...     result = perform_search()
...     observation.mark_success()

Graceful degradation when metrics are unavailable:

>>> with observe_duration("semantic_search", "codeintel_mcp") as observation:
...     try:
...         perform_semantic_search()
...         observation.mark_success()
...     except RuntimeError:
...         observation.mark_error()
...         raise
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol

from kgfoundry_common.logging import get_logger
from kgfoundry_common.observability import MetricsProvider
from kgfoundry_common.observability import (
    observe_duration as _base_observe_duration,
)

if TYPE_CHECKING:
    from kgfoundry_common.observability import DurationObservation

__all__ = ["observe_duration", "Observation"]


LOGGER = get_logger(__name__)


def _supports_histogram_labels(histogram: object) -> bool:
    """Return ``True`` when the histogram exposes label support.

    Parameters
    ----------
    histogram : object
        Prometheus histogram instance or stub implementing ``_labelnames``.

    Returns
    -------
    bool
        ``True`` when the histogram exposes at least one label, ``False`` when
        labels are missing or the attribute cannot be inspected.
    """
    labelnames = getattr(histogram, "_labelnames", None)
    if labelnames is None:
        return True
    try:
        return len(tuple(labelnames)) > 0
    except TypeError:
        return False


class _NoopObservation:
    """Fallback observation used when metrics cannot be recorded."""

    def mark_error(self) -> None:
        """Mark the observation as failed without recording metrics."""

    def mark_success(self) -> None:
        """Mark the observation as successful without recording metrics."""


class Observation(Protocol):
    """Protocol describing the helpers provided by metrics observations."""

    def mark_error(self) -> None:
        """Mark the observation as failed."""

    def mark_success(self) -> None:
        """Mark the observation as successful."""


@contextmanager
def observe_duration(
    operation: str,
    component: str,
    *,
    metrics: MetricsProvider | None = None,
) -> Iterator[Observation]:
    """Yield a metrics observation with graceful degradation.

    Parameters
    ----------
    operation : str
        Operation identifier, propagated to the ``operation`` metric label.
    component : str
        Component identifier, propagated to the ``component`` metric label.
    metrics : MetricsProvider | None, optional
        Metrics provider instance. When ``None`` (the default), the global
        :class:`~kgfoundry_common.observability.MetricsProvider` singleton is
        used.

    Yields
    ------
    Observation
        Observation object supporting ``mark_success`` and ``mark_error``.

    Notes
    -----
    - Ensures label compatibility before attempting to record metrics.
    - Catches ``ValueError`` raised by the underlying observability helper and
      falls back to a no-op observation.
    - Logging uses structured fields (``operation`` and ``component``) for
      downstream correlation.
    """
    provider = metrics or MetricsProvider.default()

    if not _supports_histogram_labels(provider.operation_duration_seconds):
        LOGGER.debug(
            "Metrics disabled for operation (histogram labels unavailable)",
            extra={"operation": operation, "component": component},
        )
        yield _NoopObservation()
        return

    try:
        with _base_observe_duration(
            provider, operation, component=component
        ) as observation:
            yield observation
            return
    except ValueError as exc:
        LOGGER.warning(
            "Metrics observation failed; using noop fallback",
            extra={"operation": operation, "component": component, "error": str(exc)},
        )
        yield _NoopObservation()
