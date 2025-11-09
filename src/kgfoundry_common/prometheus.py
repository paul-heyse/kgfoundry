"""Typed Prometheus helpers with graceful fallbacks.

The helpers in this module consolidate optional Prometheus dependencies behind
typed constructors so call sites never need to sprinkle ``type: ignore``
pragmas. When :mod:`prometheus_client` is unavailable the helpers return
lightweight no-op implementations that honour the same interface.

Examples
--------
Create metrics when Prometheus is installed:

>>> from kgfoundry_common.prometheus import build_counter
>>> counter = build_counter("example_total", "Example operations", ["status"])
>>> counter.labels(status="success").inc()

Fallback behaviour (no Prometheus import required):

>>> from unittest.mock import patch
>>> import kgfoundry_common.prometheus as prom
>>> with patch("kgfoundry_common.prometheus._COUNTER_CONSTRUCTOR", None):
...     noop = prom.build_counter("noop_total", "Noop counter")
...     noop.inc()
...     noop.labels(status="success").inc()
"""

# [nav:section public-api]

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn, Protocol, TypedDict, cast, overload

from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.sequence_guards import first_or_error

__all__ = [
    "HAVE_PROMETHEUS",
    "CollectorRegistry",
    "CounterLike",
    "GaugeLike",
    "HistogramLike",
    "HistogramParams",
    "build_counter",
    "build_gauge",
    "build_histogram",
    "get_default_registry",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from prometheus_client import Counter as _PromCounterType
    from prometheus_client import Gauge as _PromGaugeType
    from prometheus_client import Histogram as _PromHistogramType
    from prometheus_client.registry import CollectorRegistry
else:  # pragma: no cover - runtime fallback when dependency missing

    class _PromCounterType:
        """Runtime stub matching Prometheus counter surface."""

        def labels(self, **labels: object) -> _PromCounterType:
            """Return the counter stub regardless of label input.

            Parameters
            ----------
            **labels : object
                Label values (ignored).

            Returns
            -------
            _PromCounterType
                Counter stub instance.
            """
            del labels
            return self

        def inc(self, value: float = 1.0) -> None:
            """Perform no operation when Prometheus is absent."""
            _ = self
            del value

    class _PromGaugeType:
        """Runtime stub matching Prometheus gauge surface."""

        def labels(self, **labels: object) -> _PromGaugeType:
            """Return the gauge stub regardless of label input.

            Parameters
            ----------
            **labels : object
                Label values (ignored).

            Returns
            -------
            _PromGaugeType
                Gauge stub instance.
            """
            del labels
            return self

        def set(self, value: float) -> None:
            """Perform no operation when Prometheus is absent."""
            _ = self
            del value

    class _PromHistogramType:
        """Runtime stub matching Prometheus histogram surface."""

        def labels(self, **labels: object) -> _PromHistogramType:
            """Return the histogram stub regardless of label input.

            Parameters
            ----------
            **labels : object
                Label values (ignored).

            Returns
            -------
            _PromHistogramType
                Histogram stub instance.
            """
            del labels
            return self

        def observe(self, value: float) -> None:
            """Perform no operation when Prometheus is absent."""
            _ = self
            del value

    CollectorRegistry = object


class _CounterCallKwargs(TypedDict, total=False):
    registry: CollectorRegistry
    unit: str


class _HistogramCallKwargs(TypedDict, total=False):
    registry: CollectorRegistry
    unit: str
    buckets: tuple[float, ...]


# [nav:anchor CounterLike]
class CounterLike(Protocol):
    """Protocol describing Prometheus counter behaviour relied upon."""

    def labels(self, **labels: object) -> CounterLike:
        """Return a counter labelled with the provided fields."""
        ...

    def inc(self, value: float = 1.0) -> None:
        """Increment the counter by ``value``."""
        ...


# [nav:anchor GaugeLike]
class GaugeLike(Protocol):
    """Protocol describing Prometheus gauge behaviour relied upon."""

    def labels(self, **labels: object) -> GaugeLike:
        """Return a gauge labelled with the provided fields."""
        ...

    def set(self, value: float) -> None:
        """Set the gauge to ``value``."""
        ...


# [nav:anchor HistogramLike]
class HistogramLike(Protocol):
    """Protocol describing Prometheus histogram behaviour relied upon."""

    def labels(self, **labels: object) -> HistogramLike:
        """Return a histogram labelled with the provided fields."""
        ...

    def observe(self, value: float) -> None:
        """Record an observation of ``value``."""
        ...


class _CounterConstructor(Protocol):
    def __call__(
        self,
        name: str,
        documentation: str,
        labelnames: Sequence[str] | None = ...,
        *,
        registry: CollectorRegistry | None = ...,
        unit: str | None = ...,
        **kwargs: object,
    ) -> CounterLike:
        """Construct a Counter metric.

        Parameters
        ----------
        name : str
            Metric name.
        documentation : str
            Metric documentation/help text.
        labelnames : Sequence[str] | None, optional
            Label names for the metric.
        registry : CollectorRegistry | None, optional
            Prometheus registry instance.
        unit : str | None, optional
            Unit identifier for the metric.
        **kwargs : object
            Additional keyword arguments.

        Returns
        -------
        CounterLike
            Counter metric instance.
        """
        ...


class _GaugeConstructor(Protocol):
    def __call__(
        self,
        name: str,
        documentation: str,
        labelnames: Sequence[str] | None = ...,
        *,
        registry: CollectorRegistry | None = ...,
        unit: str | None = ...,
        **kwargs: object,
    ) -> GaugeLike:
        """Construct a Gauge metric.

        Parameters
        ----------
        name : str
            Metric name.
        documentation : str
            Metric documentation/help text.
        labelnames : Sequence[str] | None, optional
            Label names for the metric.
        registry : CollectorRegistry | None, optional
            Prometheus registry instance.
        unit : str | None, optional
            Unit identifier for the metric.
        **kwargs : object
            Additional keyword arguments.

        Returns
        -------
        GaugeLike
            Gauge metric instance.
        """
        ...


class _HistogramConstructor(Protocol):
    def __call__(self, *args: object, **kwargs: object) -> HistogramLike:
        """Construct a Histogram metric.

        Parameters
        ----------
        *args : object
            Positional arguments (name, documentation, etc.).
        **kwargs : object
            Keyword arguments (labelnames, buckets, registry, etc.).

        Returns
        -------
        HistogramLike
            Histogram metric instance.
        """
        ...


@dataclass(slots=True, frozen=True)
# [nav:anchor HistogramParams]
class HistogramParams:
    """Configuration for building a histogram metric."""

    name: str
    documentation: str
    labelnames: Sequence[str] | None = None
    buckets: Sequence[float] | None = None
    registry: CollectorRegistry | None = None
    unit: str | None = None


class _NoopCounter:
    """Counter stub used when Prometheus is unavailable."""

    __slots__ = ()

    def labels(self, **labels: object) -> _NoopCounter:
        """Return the stub counter regardless of label input.

        Parameters
        ----------
        **labels : object
            Label values (ignored).

        Returns
        -------
        _NoopCounter
            Counter stub instance.
        """
        del labels
        return self

    def inc(self, value: float = 1.0) -> None:
        """Perform no operation when Prometheus is absent."""
        _ = self
        del value


class _NoopGauge:
    """Gauge stub used when Prometheus is unavailable."""

    __slots__ = ()

    def labels(self, **labels: object) -> _NoopGauge:
        """Return the stub gauge regardless of label input.

        Parameters
        ----------
        **labels : object
            Label values (ignored).

        Returns
        -------
        _NoopGauge
            Gauge stub instance.
        """
        del labels
        return self

    def set(self, value: float) -> None:
        """Perform no operation when Prometheus is absent."""
        _ = self
        del value


class _NoopHistogram:
    """Histogram stub used when Prometheus is unavailable."""

    __slots__ = ()

    def labels(self, **labels: object) -> _NoopHistogram:
        """Return the stub histogram regardless of label input.

        Parameters
        ----------
        **labels : object
            Label values (ignored).

        Returns
        -------
        _NoopHistogram
            Histogram stub instance.
        """
        del labels
        return self

    def observe(self, value: float) -> None:
        """Perform no operation when Prometheus is absent."""
        _ = self
        del value


_COUNTER_CONSTRUCTOR: _CounterConstructor | None = None
_GAUGE_CONSTRUCTOR: _GaugeConstructor | None = None
_HISTOGRAM_CONSTRUCTOR: _HistogramConstructor | None = None
_DEFAULT_REGISTRY: object | None = None
_PROMETHEUS_VERSION: str | None = None


try:  # pragma: no cover - exercised in environments with Prometheus installed
    import prometheus_client
    from prometheus_client import REGISTRY as _PROMETHEUS_REGISTRY
    from prometheus_client import Counter as _PromCounter
    from prometheus_client import Gauge as _PromGauge
    from prometheus_client import Histogram as _PromHistogram
    from prometheus_client.registry import CollectorRegistry

except ImportError:  # pragma: no cover - handled by fallback
    HAVE_PROMETHEUS = False
else:  # pragma: no cover - exercised when dependency present
    HAVE_PROMETHEUS = True
    _COUNTER_CONSTRUCTOR = cast("_CounterConstructor", _PromCounter)
    _GAUGE_CONSTRUCTOR = cast("_GaugeConstructor", _PromGauge)
    _HISTOGRAM_CONSTRUCTOR = cast("_HistogramConstructor", _PromHistogram)
    _DEFAULT_REGISTRY = _PROMETHEUS_REGISTRY
    _PROMETHEUS_VERSION = getattr(prometheus_client, "__version__", None)


def _labels_or_default(labelnames: Sequence[str] | None) -> Sequence[str]:
    return tuple(labelnames) if labelnames is not None else ()


def _existing_collector(
    name: str,
    registry: CollectorRegistry | None,
) -> object | None:
    """Return an existing metric collector when one has already been registered.

    Parameters
    ----------
    name : str
        Metric name to look up.
    registry : CollectorRegistry | None
        Registry to search in.

    Returns
    -------
    object | None
        Existing collector if found, None otherwise.
    """
    target_registry: CollectorRegistry | None
    if registry is not None:
        target_registry = registry
    else:
        target_registry = cast("CollectorRegistry | None", _DEFAULT_REGISTRY)
    if target_registry is None:
        return None
    names_to_collectors = cast(
        "dict[str, object] | None",
        getattr(target_registry, "_names_to_collectors", None),
    )
    if isinstance(names_to_collectors, dict):
        return names_to_collectors.get(name)
    return None


_MAX_HISTOGRAM_POSITIONAL_ARGS = 3
_DOCUMENTATION_POSITION = 1


def _histogram_type_error(message: str) -> NoReturn:
    raise TypeError(message)


# [nav:anchor build_counter]
def build_counter(
    name: str,
    documentation: str,
    labelnames: Sequence[str] | None = None,
    *,
    registry: CollectorRegistry | None = None,
    unit: str | None = None,
) -> CounterLike:
    """Return a counter metric or a no-op stub.

    Parameters
    ----------
    name : str
        Metric name registered with Prometheus.
    documentation : str
        Human readable description of the metric.
    labelnames : Sequence[str] | None, optional
        Label names applied to the metric (defaults to empty tuple).
    registry : CollectorRegistry | None, optional
        Prometheus registry to register against (defaults to global registry).
    unit : str | None, optional
        Unit description recorded alongside the metric.

    Returns
    -------
    CounterLike
        Counter metric instance or no-op stub.

    Raises
    ------
    ValueError
        If metric registration fails and no existing collector is found.
    """
    constructor = _COUNTER_CONSTRUCTOR
    if constructor is None:
        return _NoopCounter()
    try:
        # prom-client prior to 0.20 does not support keyword arguments for
        # :func:`Counter`. To stay compatible we continue to pass labelnames
        # positionally while treating ``registry``/``unit`` as keyword-only.
        args: tuple[str, str, Sequence[str]] = (
            name,
            documentation,
            _labels_or_default(labelnames),
        )
        kwargs: _CounterCallKwargs = {}
        if registry is not None:
            kwargs["registry"] = registry
        if unit is not None:
            kwargs["unit"] = unit
        return constructor(*args, **kwargs)
    except ValueError:  # pragma: no cover - only hit when duplicates exist
        existing = _existing_collector(name, registry)
        if existing is None:
            raise
        return cast("CounterLike", existing)


# [nav:anchor build_gauge]
def build_gauge(
    name: str,
    documentation: str,
    labelnames: Sequence[str] | None = None,
    *,
    registry: CollectorRegistry | None = None,
    unit: str | None = None,
) -> GaugeLike:
    """Return a gauge metric or a no-op stub.

    Parameters
    ----------
    name : str
        Metric name registered with Prometheus.
    documentation : str
        Human readable description of the metric.
    labelnames : Sequence[str] | None, optional
        Label names applied to the metric (defaults to empty tuple).
    registry : CollectorRegistry | None, optional
        Prometheus registry to register against (defaults to global registry).
    unit : str | None, optional
        Unit description recorded alongside the metric.

    Returns
    -------
    GaugeLike
        Gauge metric instance or no-op stub.

    Raises
    ------
    ValueError
        If metric registration fails and no existing collector is found.
    """
    constructor = _GAUGE_CONSTRUCTOR
    if constructor is None:
        return _NoopGauge()
    try:
        return constructor(
            name,
            documentation,
            _labels_or_default(labelnames),
            registry=registry,
            unit=unit,
        )
    except ValueError:  # pragma: no cover - duplicates are rare
        existing = _existing_collector(name, registry)
        if existing is None:
            raise
        return cast("GaugeLike", existing)


def _coerce_histogram_params(*args: object, **kwargs: object) -> HistogramParams:
    """Normalize legacy histogram arguments into a :class:`HistogramParams` instance.

    Parameters
    ----------
    *args : object
        Either a single HistogramParams instance or positional arguments.
    **kwargs : object
        Optional keyword arguments.

    Returns
    -------
    HistogramParams
        Normalized histogram parameters.
    """
    args_list = list(args)

    if args_list and isinstance(args_list[0], HistogramParams):
        if len(args_list) > 1 or kwargs:
            _histogram_type_error("build_histogram() received unexpected extra arguments")
        return args_list[0]

    if not args_list:
        _histogram_type_error("build_histogram() missing required argument: 'name'")

    if len(args_list) > _MAX_HISTOGRAM_POSITIONAL_ARGS:
        _histogram_type_error("build_histogram() received too many positional arguments")

    name = str(
        first_or_error(
            args_list,
            context="histogram_args_name",
            operation="build_histogram_coerce_params",
        )
    )
    if len(args_list) > _DOCUMENTATION_POSITION:
        documentation = str(args_list[_DOCUMENTATION_POSITION])
    else:
        doc = kwargs.pop("documentation", None)
        if doc is None:
            _histogram_type_error("build_histogram() missing required argument: 'documentation'")
        documentation = str(doc)

    labelnames = kwargs.pop("labelnames", None)
    buckets = kwargs.pop("buckets", None)
    registry = kwargs.pop("registry", None)
    unit = kwargs.pop("unit", None)
    if kwargs:
        unexpected = ", ".join(sorted(kwargs))
        _histogram_type_error(f"build_histogram() got unexpected keyword arguments: {unexpected}")

    return HistogramParams(
        name=name,
        documentation=documentation,
        labelnames=cast("Sequence[str] | None", labelnames),
        buckets=cast("Sequence[float] | None", buckets),
        registry=cast("CollectorRegistry | None", registry),
        unit=None if unit is None else str(unit),
    )


@overload
def build_histogram(params: HistogramParams) -> HistogramLike: ...


@overload
def build_histogram(
    name: str,
    documentation: str,
    labelnames: Sequence[str] | None = ...,
    *,
    buckets: Sequence[float] | None = ...,
    registry: CollectorRegistry | None = ...,
    unit: str | None = ...,
) -> HistogramLike: ...


# [nav:anchor build_histogram]
def build_histogram(*args: object, **kwargs: object) -> HistogramLike:
    """Return a histogram metric or a no-op stub.

    Parameters
    ----------
    *args : object
        Either a single HistogramParams instance or positional arguments (name, documentation).
    **kwargs : object
        Optional keyword arguments: labelnames, buckets, registry, unit.

    Returns
    -------
    HistogramLike
        Histogram metric instance or no-op stub.

    Raises
    ------
    ValueError
        If metric registration fails and no existing collector is found.

    Notes
    -----
    Propagates :class:`TypeError` when the provided arguments are invalid or
    missing required parameters.
    """
    constructor = _HISTOGRAM_CONSTRUCTOR
    if constructor is None:
        return _NoopHistogram()

    params = _coerce_histogram_params(*args, **kwargs)
    label_tuple = _labels_or_default(params.labelnames)
    call_kwargs: _HistogramCallKwargs = {}
    if params.registry is not None:
        call_kwargs["registry"] = params.registry
    if params.unit is not None:
        call_kwargs["unit"] = params.unit
    if params.buckets is not None:
        call_kwargs["buckets"] = tuple(float(value) for value in params.buckets)

    try:
        return constructor(
            params.name,
            params.documentation,
            label_tuple,
            **call_kwargs,
        )
    except ValueError:  # pragma: no cover - duplicates are exceptional
        existing = _existing_collector(params.name, params.registry)
        if existing is None:
            raise
        return cast("HistogramLike", existing)


# [nav:anchor get_default_registry]
def get_default_registry() -> object | None:
    """Return the global Prometheus registry when the dependency is available.

    Returns
    -------
    object | None
        Global Prometheus registry or None if not available.
    """
    return _DEFAULT_REGISTRY


def prometheus_version() -> str | None:
    """Return the detected :mod:`prometheus_client` version for diagnostics.

    Returns
    -------
    str | None
        Version string or None if prometheus_client is not installed.
    """
    return _PROMETHEUS_VERSION
