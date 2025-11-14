"""Compatibility layer exposing Prometheus-like helpers backed by OpenTelemetry."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import Lock

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation

__all__ = [
    "CounterLike",
    "GaugeLike",
    "HistogramLike",
    "build_counter",
    "build_gauge",
    "build_histogram",
]

_METER = metrics.get_meter("codeintel_rev.telemetry")


class CounterHandle:
    """Lightweight handle mutating a counter with pre-bound attributes."""

    __slots__ = ("_attributes", "_instrument")

    def __init__(self, instrument: object, attributes: Mapping[str, object]) -> None:
        self._instrument = instrument
        self._attributes = dict(attributes)

    def inc(self, value: float = 1.0) -> None:
        """Increment the underlying counter."""
        self._instrument.add(float(value), self._attributes)


class HistogramHandle:
    """Histogram view that records values with pre-bound attributes."""

    __slots__ = ("_attributes", "_instrument")

    def __init__(self, instrument: object, attributes: Mapping[str, object]) -> None:
        self._instrument = instrument
        self._attributes = dict(attributes)

    def observe(self, value: float) -> None:
        """Record ``value`` on the histogram."""
        self._instrument.record(float(value), self._attributes)


class CounterLike:
    """Counter facade exposing `.inc()` and `.labels().inc()`."""

    __slots__ = ("_default_handle", "_instrument", "_labelnames")

    def __init__(
        self,
        name: str,
        description: str,
        labelnames: Sequence[str] | None = None,
    ) -> None:
        self._instrument = _METER.create_counter(name=name, description=description)
        self._labelnames = tuple(labelnames or ())
        self._default_handle = CounterHandle(self._instrument, {})

    def labels(self, **attributes: object) -> CounterHandle:
        """Return a handle bound to ``attributes``.

        Returns
        -------
        CounterHandle
            Handle that records metrics with the provided attributes.

        Raises
        ------
        ValueError
            Raised when a required attribute is missing.
        """
        if not self._labelnames:
            return self._default_handle
        bound: dict[str, object] = {}
        for key in self._labelnames:
            if key not in attributes:
                msg = f"Missing attribute '{key}' for counter {self._instrument.name}"
                raise ValueError(msg)
            bound[key] = attributes[key]
        return CounterHandle(self._instrument, bound)

    def inc(self, value: float = 1.0) -> None:
        """Increment the counter without attributes."""
        self._default_handle.inc(value)


class HistogramLike:
    """Histogram facade exposing `.observe()` and `.labels().observe()`."""

    __slots__ = ("_buckets", "_default_handle", "_instrument", "_labelnames")

    def __init__(
        self,
        name: str,
        description: str,
        labelnames: Sequence[str] | None = None,
        *,
        unit: str | None = None,
        buckets: Sequence[float] | None = None,
    ) -> None:
        self._instrument = _METER.create_histogram(
            name=name,
            description=description,
            unit=unit or "",
        )
        self._buckets = tuple(buckets) if buckets else None
        self._labelnames = tuple(labelnames or ())
        self._default_handle = HistogramHandle(self._instrument, {})

    def labels(self, **attributes: object) -> HistogramHandle:
        """Return a histogram handle for ``attributes``.

        Returns
        -------
        HistogramHandle
            Handle used to record values with the provided attributes.

        Raises
        ------
        ValueError
            Raised when a required attribute is missing.
        """
        if not self._labelnames:
            return self._default_handle
        bound: dict[str, object] = {}
        for key in self._labelnames:
            if key not in attributes:
                msg = f"Missing attribute '{key}' for histogram {self._instrument.name}"
                raise ValueError(msg)
            bound[key] = attributes[key]
        return HistogramHandle(self._instrument, bound)

    def observe(self, value: float) -> None:
        """Record ``value`` against the histogram."""
        self._default_handle.observe(value)


@dataclass(slots=True)
class _GaugeEntry:
    attributes: Mapping[str, object]
    value: float = 0.0


class GaugeHandle:
    """Gauge handle supporting ``set`` semantics."""

    __slots__ = ("_key", "_owner")

    def __init__(self, owner: GaugeLike, key: tuple[tuple[str, object], ...]) -> None:
        self._owner = owner
        self._key = key

    def set(self, value: float) -> None:
        """Set the gauge to ``value``."""
        self._owner.set_value(self._key, value)


class GaugeLike:
    """Gauge facade backed by an ObservableGauge."""

    __slots__ = ("_default_key", "_entries", "_labelnames", "_lock")

    def __init__(
        self,
        name: str,
        description: str,
        labelnames: Sequence[str] | None = None,
        *,
        unit: str | None = None,
    ) -> None:
        self._labelnames = tuple(labelnames or ())
        self._lock = Lock()
        self._entries: dict[tuple[tuple[str, object], ...], _GaugeEntry] = {}
        self._default_key: tuple[tuple[str, object], ...] = ()
        _METER.create_observable_gauge(
            name=name,
            description=description,
            callbacks=[self._observe],
            unit=unit or "",
        )
        # Initialize default entry to ensure gauge exists.
        self._entries[self._default_key] = _GaugeEntry(attributes={}, value=0.0)

    def labels(self, **attributes: object) -> GaugeHandle:
        """Return a handle for ``attributes``.

        Returns
        -------
        GaugeHandle
            Handle that controls the gauge entry for the provided attributes.

        Raises
        ------
        ValueError
            Raised when a required attribute is missing.
        """
        try:
            key = self._key_from_attributes(attributes)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return GaugeHandle(self, key)

    def set(self, value: float) -> None:
        """Set the gauge without attributes."""
        self.set_value(self._default_key, value)

    def _key_from_attributes(self, attributes: Mapping[str, object]) -> tuple[tuple[str, object], ...]:
        """Return a canonical attribute key tuple.

        Returns
        -------
        tuple[tuple[str, object], ...]
            Normalized attribute tuple keyed by label name.

        Raises
        ------
        ValueError
            Raised when a required attribute is missing.
        """
        if not self._labelnames:
            return self._default_key
        key: list[tuple[str, object]] = []
        for label in self._labelnames:
            if label not in attributes:
                msg = f"Missing attribute '{label}' for gauge"
                raise ValueError(msg)
            key.append((label, attributes[label]))
        return tuple(key)

    def set_value(self, key: tuple[tuple[str, object], ...], value: float) -> None:
        """Store ``value`` for the attribute tuple."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _GaugeEntry(attributes=dict(key), value=float(value))
                self._entries[key] = entry
            else:
                entry.value = float(value)

    def _observe(self, _: CallbackOptions) -> list[Observation]:
        """Return the latest gauge observations.

        Returns
        -------
        list[Observation]
            Snapshot of the most recent gauge values.
        """
        with self._lock:
            entries = list(self._entries.values())
        return [Observation(entry.value, dict(entry.attributes)) for entry in entries]


def build_counter(
    name: str,
    description: str,
    labelnames: Sequence[str] | None = None,
) -> CounterLike:
    """Return a CounterLike backed by OpenTelemetry.

    Returns
    -------
    CounterLike
        Counter interface used across the codebase.
    """
    return CounterLike(name=name, description=description, labelnames=labelnames)


def build_histogram(
    name: str,
    description: str,
    labelnames: Sequence[str] | None = None,
    *,
    unit: str | None = None,
    buckets: Sequence[float] | None = None,
) -> HistogramLike:
    """Return a HistogramLike backed by OpenTelemetry.

    Returns
    -------
    HistogramLike
        Histogram interface used across the codebase.
    """
    return HistogramLike(
        name=name,
        description=description,
        labelnames=labelnames,
        unit=unit,
        buckets=buckets,
    )


def build_gauge(
    name: str,
    description: str,
    labelnames: Sequence[str] | None = None,
    *,
    unit: str | None = None,
) -> GaugeLike:
    """Return an ObservableGauge facade.

    Returns
    -------
    GaugeLike
        Gauge interface used across the codebase.
    """
    return GaugeLike(
        name=name,
        description=description,
        labelnames=labelnames,
        unit=unit,
    )
