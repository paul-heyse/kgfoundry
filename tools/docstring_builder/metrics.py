"""Metrics utilities for the docstring builder pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from kgfoundry_common.prometheus import CounterLike, HistogramLike
    from tools.docstring_builder.builder_types import ExitStatus


class _Histogram(Protocol):
    """Protocol for Prometheus histogram collectors."""

    def labels(
        self, **labels: str
    ) -> _Histogram:  # pragma: no cover - third-party binding
        """Return a histogram child with the provided labels."""
        ...

    def observe(self, amount: float) -> None:
        """Record a sample in the histogram."""
        del self, amount
        raise NotImplementedError


class _Counter(Protocol):
    """Protocol for Prometheus counter collectors."""

    def labels(
        self, **labels: str
    ) -> _Counter:  # pragma: no cover - third-party binding
        """Return a counter child with the provided labels."""
        ...

    def inc(self) -> None:
        """Increment the counter by one."""
        ...


@dataclass(slots=True, frozen=True)
class MetricsRecorder:
    """Record Prometheus metrics for docstring builder runs."""

    cli_duration_seconds: HistogramLike
    runs_total: CounterLike

    def observe_cli_duration(
        self, *, command: str, status: ExitStatus, duration_seconds: float
    ) -> None:
        """Record a CLI duration sample and increment run counters."""
        status_label = status.name.lower()
        self.cli_duration_seconds.labels(command=command, status=status_label).observe(
            duration_seconds
        )
        self.runs_total.labels(status=status_label).inc()
