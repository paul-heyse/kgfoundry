"""Decorators for consistent span/timeline instrumentation."""

from __future__ import annotations

import functools
import importlib
import inspect
import logging
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from time import perf_counter
from types import SimpleNamespace
from typing import TYPE_CHECKING, TypeVar, cast

try:  # pragma: no cover - optional dependency
    from opentelemetry import trace
    from opentelemetry.trace import Span, SpanKind, Status, StatusCode
except ImportError:  # pragma: no cover - optional dependency

    @dataclass(slots=True, frozen=True)
    class _NullSpan:
        """Minimal span stub used when OpenTelemetry is unavailable."""

        attributes: dict[str, object] = field(default_factory=dict)

        def set_attribute(self, key: object, value: object) -> None:
            """Store an attribute in the span's attribute dictionary.

            This method stores key-value pairs in the span's attributes dictionary,
            providing a minimal implementation that preserves attribute data even
            when OpenTelemetry is unavailable.

            Parameters
            ----------
            key : object
                Attribute key (converted to string). Used as the dictionary key
                for storing the attribute value.
            value : object
                Attribute value to store. Can be any object type. Stored in the
                attributes dictionary for later inspection or debugging.

            Notes
            -----
            This is a minimal stub implementation that stores attributes locally
            instead of sending them to OpenTelemetry. Real span implementations
            would send attributes to distributed tracing backends.
            """
            self.attributes[str(key)] = value

        def record_exception(self, exception: BaseException) -> None:
            """Record exception information in the span's attributes.

            This method stores the exception type name in the span's attributes
            dictionary, providing a minimal implementation for exception tracking
            when OpenTelemetry is unavailable.

            Parameters
            ----------
            exception : BaseException
                Exception instance to record. The exception's type name is stored
                in the attributes dictionary under the key "last_exception".

            Notes
            -----
            This is a minimal stub implementation that stores only the exception
            type name. Real span implementations would record full exception
            details (type, message, stack trace) for distributed tracing.
            """
            self.attributes["last_exception"] = type(exception).__name__

        def set_status(self, status: object) -> None:
            """Set the span status in the span's attributes.

            This method stores the status object in the span's attributes dictionary,
            providing a minimal implementation for status tracking when OpenTelemetry
            is unavailable.

            Parameters
            ----------
            status : object
                Status object to store. Typically a Status instance with a code
                attribute (e.g., Status(StatusCode.ERROR)). Stored in the attributes
                dictionary under the key "status".

            Notes
            -----
            This is a minimal stub implementation that stores the status locally.
            Real span implementations would set the span status in OpenTelemetry,
            marking spans as OK, ERROR, etc. for trace visualization.
            """
            self.attributes["status"] = status

    class _SpanContext:
        def __enter__(self) -> _NullSpan:
            return _NullSpan()

        def __exit__(self, *_exc: object) -> bool:
            return False

    class _NoopTracer:
        def __init__(self) -> None:
            self._spans_created = 0

        def start_as_current_span(self, *_args: object, **_kwargs: object) -> _SpanContext:
            """Create a no-op span context manager.

            This method is part of the no-op tracer implementation used when
            OpenTelemetry is unavailable. It accepts any arguments but returns
            a null span context that does nothing, allowing code to use span
            context managers without checking for tracer availability.

            Parameters
            ----------
            *_args : object
                Variable positional arguments (ignored). In real OpenTelemetry
                tracers, this would include span name and other configuration.
            **_kwargs : object
                Variable keyword arguments (ignored). In real OpenTelemetry
                tracers, this would include span kind, attributes, etc.

            Returns
            -------
            _SpanContext
                A null span context manager that does nothing. The context
                manager can be used in `with` statements but has no effect.
                The internal span counter is incremented for debugging purposes.

            Notes
            -----
            This is a stub implementation that provides API compatibility
            without requiring OpenTelemetry to be installed. Real tracer
            implementations would create and return active OpenTelemetry spans
            that record timing and attributes.
            """
            self._spans_created += 1
            return _SpanContext()

    class _SpanKindEnum:
        INTERNAL = object()
        SERVER = object()
        CLIENT = object()
        PRODUCER = object()
        CONSUMER = object()

    class _StatusCodeEnum:
        ERROR = "ERROR"

    @dataclass(slots=True, frozen=True)
    class _StatusStub:
        code: object

    trace = SimpleNamespace(get_tracer=lambda *_args, **_kwargs: _NoopTracer())  # type: ignore[assignment]
    Span = _NullSpan  # type: ignore[assignment]
    SpanKind = _SpanKindEnum  # type: ignore[assignment]
    Status = _StatusStub  # type: ignore[assignment]
    StatusCode = _StatusCodeEnum  # type: ignore[assignment]

if TYPE_CHECKING:
    from opentelemetry.trace import Span as SpanType
    from opentelemetry.trace import SpanKind as SpanKindType
    from opentelemetry.trace import Status as StatusType
    from opentelemetry.trace import StatusCode as StatusCodeType
else:  # pragma: no cover - annotations only
    SpanType = Span
    SpanKindType = SpanKind
    StatusType = Status
    StatusCodeType = StatusCode

from codeintel_rev.observability.timeline import current_timeline
from codeintel_rev.telemetry import steps as telemetry_steps
from codeintel_rev.telemetry.context import attach_context_attrs, set_request_stage
from codeintel_rev.telemetry.prom import record_stage_latency

LOGGER = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., object])

_SPAN_KINDS: dict[str, SpanKindType] = {
    "internal": cast("SpanKindType", SpanKind.INTERNAL),
    "server": cast("SpanKindType", SpanKind.SERVER),
    "client": cast("SpanKindType", SpanKind.CLIENT),
    "producer": cast("SpanKindType", SpanKind.PRODUCER),
    "consumer": cast("SpanKindType", SpanKind.CONSUMER),
}

TRACER = trace.get_tracer("codeintel_rev.telemetry")


def _emit_checkpoint(
    stage: str | None, *, ok: bool, reason: str | None, attrs: Mapping[str, object]
) -> None:
    """Emit a checkpoint event for telemetry reporting.

    This internal helper emits checkpoint events to the telemetry reporter
    module. Checkpoints are used to track stage-level status (success/failure)
    and reasons for state changes. The function gracefully handles cases where
    the reporter module is unavailable.

    Parameters
    ----------
    stage : str | None
        Stage identifier for the checkpoint. When None, no checkpoint is
        emitted. Used to identify which stage the checkpoint belongs to
        (e.g., "search.faiss", "search.bm25").
    ok : bool
        Boolean flag indicating checkpoint status. True indicates success,
        False indicates failure or error condition.
    reason : str | None, optional
        Optional reason string explaining the checkpoint status. Included
        in the checkpoint payload when provided. Used to provide context
        for success or failure conditions.
    attrs : Mapping[str, object]
        Additional attributes to include in the checkpoint payload. These
        attributes are merged with the checkpoint metadata and included
        in the telemetry event.

    Notes
    -----
    This function imports the reporter module dynamically to avoid circular
    dependencies. If the import fails or the reporter is unavailable, the
    function silently returns without emitting a checkpoint. This ensures
    that telemetry failures don't break application functionality.
    """
    if stage is None:
        return
    payload = dict(attrs)
    payload.setdefault("status", "ok" if ok else "error")
    if reason is not None:
        payload["reason"] = reason
    try:
        reporter = importlib.import_module("codeintel_rev.telemetry.reporter")
        reporter.emit_checkpoint(stage, ok=ok, **payload)
    except (ImportError, AttributeError, RuntimeError):  # pragma: no cover - defensive
        return


def _set_span_attributes(span: SpanType, attrs: Mapping[str, object]) -> None:
    """Set attributes on an OpenTelemetry span from a mapping.

    This helper function sets span attributes from a dictionary, converting
    values to appropriate types for OpenTelemetry. Only primitive types
    (bool, int, float, str) are set directly; None values are converted to
    the string "null"; other types are converted to strings.

    Parameters
    ----------
    span : SpanType
        OpenTelemetry span to set attributes on. The span must be active
        and writable. Can be either a real OpenTelemetry Span or a _NullSpan
        stub when OpenTelemetry is unavailable.
    attrs : Mapping[str, object]
        Dictionary of attribute key-value pairs to set on the span. Keys
        are attribute names (strings), values are converted to appropriate
        types (primitives preserved, None -> "null", others -> str).

    Notes
    -----
    OpenTelemetry spans only accept primitive types (bool, int, float, str)
    as attribute values. This function handles type conversion automatically,
    ensuring all attributes are set correctly regardless of input types.
    """
    for key, value in attrs.items():
        if isinstance(value, (bool, int, float, str)):
            span.set_attribute(key, value)
        elif value is None:
            span.set_attribute(key, "null")
        else:
            span.set_attribute(key, str(value))


@contextmanager
def _span_scope(
    name: str,
    *,
    kind: str,
    base_attrs: Mapping[str, object],
    stage: str | None,
) -> Iterator[tuple[SpanType, dict[str, object]]]:
    """Create a context manager for OpenTelemetry span and timeline step coordination.

    This internal helper creates a coordinated context for both OpenTelemetry
    span tracing and timeline step recording. It ensures that spans and steps
    are created together, attributes are synchronized, and stage context is
    properly managed.

    Parameters
    ----------
    name : str
        Name for both the OpenTelemetry span and timeline step. Used to
        identify the operation in both tracing systems.
    kind : str
        Span kind identifier (e.g., "internal", "server", "client"). Used
        to determine the OpenTelemetry SpanKind. Must be a key in
        _SPAN_KINDS mapping or defaults to INTERNAL.
    base_attrs : Mapping[str, object]
        Base attributes to attach to both the span and step. These attributes
        are enriched with context attributes (request ID, session ID, etc.)
        before being applied.
    stage : str | None, optional
        Optional stage identifier for request stage tracking. When provided,
        sets the request stage context variable for the duration of the scope.
        Used to track which stage of request processing is active.

    Yields
    ------
    tuple[SpanType, dict[str, object]]
        Tuple containing:
        - The active OpenTelemetry span (for setting attributes, recording
          exceptions, etc.). Can be either a real OpenTelemetry Span or a
          _NullSpan stub when OpenTelemetry is unavailable.
        - The enriched telemetry attributes dictionary (for use in timeline
          steps or additional span attributes)

    Notes
    -----
    This function coordinates two observability systems: OpenTelemetry spans
    (for distributed tracing) and timeline steps (for session-level event
    tracking). Both are created together and share the same attributes and
    lifecycle. The stage parameter enables request-level stage tracking for
    multi-stage operations (e.g., search stages).
    """
    telemetry_attrs = attach_context_attrs(base_attrs)
    timeline = current_timeline()
    stage_token = set_request_stage(stage) if stage else None
    step_cm = timeline.step(name, **telemetry_attrs) if timeline is not None else nullcontext()
    span_kind = _SPAN_KINDS.get(kind)
    if span_kind is None:
        span_kind = cast("SpanKindType", SpanKind.INTERNAL)
    with TRACER.start_as_current_span(name, kind=span_kind) as span:
        _set_span_attributes(span, telemetry_attrs)
        try:
            with step_cm:
                yield span, telemetry_attrs
        finally:
            if stage_token is not None:
                stage_token.var.reset(stage_token)


def _record_exception(span: SpanType, exc: BaseException) -> None:
    """Record an exception on an OpenTelemetry span and mark it as an error.

    This helper function records an exception on a span and sets the span
    status to ERROR. Used to ensure exceptions are properly captured in
    distributed traces.

    Parameters
    ----------
    span : SpanType
        OpenTelemetry span to record the exception on. The span must be
        active and writable. Can be either a real OpenTelemetry Span or a
        _NullSpan stub when OpenTelemetry is unavailable.
    exc : BaseException
        Exception instance to record. The exception's type, message, and
        stack trace are captured in the span.

    Notes
    -----
    This function both records the exception details (type, message, stack)
    and sets the span status to ERROR, ensuring that error conditions are
    clearly visible in trace visualizations. Used by error handling code
    in decorators and context managers.
    """
    span.record_exception(exc)
    status_cls = cast("type[StatusType]", Status)
    status_code = cast("StatusCodeType", StatusCode)
    try:
        span.set_status(status_cls(status_code.ERROR))
    except TypeError:  # pragma: no cover - fallback for stub implementations
        span.set_status(status_code.ERROR)


@contextmanager
def span_context(
    name: str,
    *,
    kind: str = "internal",
    attrs: Mapping[str, object] | None = None,
    stage: str | None = None,
    emit_checkpoint: bool = False,
) -> Iterator[tuple[SpanType, dict[str, object]]]:
    """Create a span/timeline scope for the wrapped block.

    This context manager creates an OpenTelemetry span and timeline step for
    instrumenting code execution. It sets up span attributes, records exceptions,
    emits checkpoints (if enabled), and records stage latency metrics. The context
    manager ensures proper span lifecycle management and error handling.

    Parameters
    ----------
    name : str
        Span name used for OpenTelemetry tracing and timeline steps. Should be
        descriptive and identify the operation being traced (e.g., "search",
        "embed_batch").
    kind : str, optional
        Span kind indicating the role of the span: "internal" (default), "server",
        "client", "producer", or "consumer". Determines how the span appears in
        distributed tracing views.
    attrs : Mapping[str, object] | None, optional
        Additional attributes to attach to the span. Attributes are merged with
        context attributes (request ID, stage, etc.) and set on the OpenTelemetry
        span. None values are converted to "null" strings.
    stage : str | None, optional
        Stage identifier for pipeline instrumentation. If provided, records stage
        latency metrics and can emit checkpoints (if emit_checkpoint is True).
        Used for tracking pipeline execution stages.
    emit_checkpoint : bool, optional
        Whether to emit checkpoint events for the stage (defaults to False).
        When True, emits success/failure checkpoints with stage metadata. Requires
        stage to be provided.

    Yields
    ------
    tuple[SpanType, dict[str, object]]
        Tuple containing:
        - SpanType: The active OpenTelemetry span for adding custom attributes or
          recording events. Can be either a real OpenTelemetry Span or a _NullSpan
          stub when OpenTelemetry is unavailable.
        - dict[str, object]: Merged attribute dictionary combining provided attrs
          with context attributes (request ID, stage, etc.)

    Notes
    -----
    This context manager integrates OpenTelemetry tracing with timeline recording
    and Prometheus metrics. It automatically records exceptions, sets span status,
    and records stage latency. The context manager is thread-safe if the underlying
    tracing infrastructure is thread-safe. Stage latency is recorded only when
    stage is provided.

    Raises
    ------
    BaseException
        Any exception raised within the context is caught, recorded on the span
        with error status, and re-raised using Python's bare ``raise`` statement.
        The context manager ensures proper span cleanup and error attribution even
        when exceptions occur. Exceptions propagate to the caller after error
        recording and checkpoint emission (if enabled). Note: Exceptions are
        re-raised (not directly raised), preserving the original exception traceback
        and propagating through this context manager.
    """
    base_attrs = dict(attrs or {})
    stage_start = perf_counter() if stage else None
    with _span_scope(name, kind=kind, base_attrs=base_attrs, stage=stage) as (
        span,
        telemetry_attrs,
    ):
        try:
            yield span, telemetry_attrs
        except BaseException as exc:
            _record_exception(span, exc)
            if emit_checkpoint:
                _emit_checkpoint(stage, ok=False, reason=str(exc), attrs=telemetry_attrs)
            raise
        else:
            if emit_checkpoint:
                _emit_checkpoint(stage, ok=True, reason=None, attrs=telemetry_attrs)
        finally:
            if stage_start is not None and stage is not None:
                record_stage_latency(stage, perf_counter() - stage_start)


def trace_span(
    name: str,
    *,
    kind: str = "internal",
    attrs: Mapping[str, object] | None = None,
    stage: str | None = None,
    emit_checkpoint: bool = False,
) -> Callable[[F], F]:
    """Wrap callable execution in an OpenTelemetry span + timeline step.

    This decorator function creates a decorator that wraps callables (functions
    or coroutines) with OpenTelemetry span and timeline instrumentation. The
    decorator automatically detects async vs sync functions and creates appropriate
    wrappers. All execution within the decorated callable is traced with spans,
    timeline steps, and optional checkpoints.

    Parameters
    ----------
    name : str
        Span name used for OpenTelemetry tracing and timeline steps. Should be
        descriptive and identify the operation being traced (e.g., "search",
        "embed_batch").
    kind : str, optional
        Span kind indicating the role of the span: "internal" (default), "server",
        "client", "producer", or "consumer". Determines how the span appears in
        distributed tracing views.
    attrs : Mapping[str, object] | None, optional
        Additional attributes to attach to the span. Attributes are merged with
        context attributes and set on the OpenTelemetry span. None values are
        converted to "null" strings.
    stage : str | None, optional
        Stage identifier for pipeline instrumentation. If provided, records stage
        latency metrics and can emit checkpoints (if emit_checkpoint is True).
        Used for tracking pipeline execution stages.
    emit_checkpoint : bool, optional
        Whether to emit checkpoint events for the stage (defaults to False).
        When True, emits success/failure checkpoints with stage metadata. Requires
        stage to be provided.

    Returns
    -------
    Callable[[F], F]
        Decorator function that wraps callables with span/timeline instrumentation.
        The decorator preserves the original function's signature and metadata via
        functools.wraps(). Async functions are wrapped with async wrappers; sync
        functions are wrapped with sync wrappers.
    """
    base_attrs = dict(attrs or {})

    def decorator(func: F) -> F:
        """Wrap a callable with OpenTelemetry span and timeline instrumentation.

        This nested function creates a decorator that wraps the target callable
        (function or coroutine) with span_context() to create an OpenTelemetry
        span and timeline step. The decorator automatically detects whether the
        callable is async or sync and creates the appropriate wrapper.

        Parameters
        ----------
        func : F
            Callable to wrap (function or coroutine function). The callable is
            wrapped to execute within a span_context() scope, creating spans and
            timeline steps automatically.

        Returns
        -------
        F
            Wrapped callable that executes within span/timeline instrumentation.
            Async functions return an async wrapper; sync functions return a
            sync wrapper. The wrapper preserves the original function's signature
            and metadata via functools.wraps().

        Notes
        -----
        This decorator function is returned by trace_span() and is applied to
        the target callable. It uses inspect.iscoroutinefunction() to detect
        async functions and creates appropriate wrappers. The wrapper executes
        the original function within a span_context() scope, ensuring all
        execution is traced. Thread-safe if span_context() is thread-safe.
        """
        if inspect.iscoroutinefunction(func):
            async_func = cast("Callable[..., Awaitable[object]]", func)

            @functools.wraps(func)
            async def async_wrapper(*args: object, **kwargs: object) -> object:
                """Async wrapper that executes coroutine within span context.

                This nested async function wraps coroutine execution in a
                span_context() scope, creating OpenTelemetry spans and timeline
                steps for async operations. It awaits the original coroutine
                and returns its result.

                Parameters
                ----------
                *args : object
                    Positional arguments passed to the original coroutine.
                **kwargs : object
                    Keyword arguments passed to the original coroutine.

                Returns
                -------
                object
                    Result returned by the original coroutine. The result is
                    passed through unchanged after span/timeline instrumentation.
                """
                with span_context(
                    name,
                    kind=kind,
                    attrs=base_attrs,
                    stage=stage,
                    emit_checkpoint=emit_checkpoint,
                ):
                    return await async_func(*args, **kwargs)

            return cast("F", async_wrapper)

        @functools.wraps(func)
        def sync_wrapper(*args: object, **kwargs: object) -> object:
            """Sync wrapper that executes function within span context.

            This nested function wraps synchronous function execution in a
            span_context() scope, creating OpenTelemetry spans and timeline
            steps for sync operations. It calls the original function and
            returns its result.

            Parameters
            ----------
            *args : object
                Positional arguments passed to the original function.
            **kwargs : object
                Keyword arguments passed to the original function.

            Returns
            -------
            object
                Result returned by the original function. The result is passed
                through unchanged after span/timeline instrumentation.
            """
            with span_context(
                name,
                kind=kind,
                attrs=base_attrs,
                stage=stage,
                emit_checkpoint=emit_checkpoint,
            ):
                return func(*args, **kwargs)

        return cast("F", sync_wrapper)

    return decorator


def trace_step(
    stage: str,
    *,
    attrs: Mapping[str, object] | None = None,
    kind: str = "internal",
) -> Callable[[F], F]:
    """Specialized decorator that records checkpoints for pipeline stages.

    This decorator is a convenience wrapper around trace_span() that automatically
    enables checkpoint emission for pipeline stage instrumentation. It sets the
    stage name as both the span name and stage identifier, and enables checkpoint
    emission to track stage success/failure. This is useful for instrumenting
    pipeline stages that need checkpoint tracking.

    Parameters
    ----------
    stage : str
        Stage identifier used as both span name and stage name. Should identify
        the pipeline stage being instrumented (e.g., "index_load", "search_execute").
        Checkpoints are automatically emitted for this stage.
    attrs : Mapping[str, object] | None, optional
        Additional attributes to attach to the span. Attributes are merged with
        context attributes and the stage name. None values are converted to "null"
        strings.
    kind : str, optional
        Span kind indicating the role of the span: "internal" (default), "server",
        "client", "producer", or "consumer". Determines how the span appears in
        distributed tracing views.

    Returns
    -------
    Callable[[F], F]
        Decorator function that wraps callables with span/timeline instrumentation
        and checkpoint emission. The decorator preserves the original function's
        signature and metadata. Checkpoints are emitted automatically on success
        or failure.
    """
    step_attrs = dict(attrs or {})
    step_attrs.setdefault("stage", stage)
    return trace_span(
        stage,
        kind=kind,
        attrs=step_attrs,
        stage=stage,
        emit_checkpoint=True,
    )


def emit_event(
    op: str,
    *,
    component: str,
    payload_factory: Callable[
        [tuple[object, ...], dict[str, object], object | None], Mapping[str, object]
    ]
    | None = None,
) -> Callable[[F], F]:
    """Emit a :class:`StepEvent` reflecting the wrapped callable's outcome.

    Parameters
    ----------
    op : str
        Operation name to include in the step event kind (format: "{component}.{op}").
    component : str
        Component name to include in the step event kind (format: "{component}.{op}").
    payload_factory : Callable[[tuple[object, ...], dict[str, object], object | None], Mapping[str, object]] | None, optional
        Optional factory function to build custom payload from function arguments,
        keyword arguments, and return value. If None, uses default payload extraction.

    Returns
    -------
    Callable[[F], F]
        Decorator wrapping the target callable with structured step emission.
    """

    def decorator(func: F) -> F:
        """Wrap the target callable with step event emission.

        Parameters
        ----------
        func : F
            Function or coroutine function to wrap with step event emission.

        Returns
        -------
        F
            Wrapped function that emits step events on completion or failure.
        """
        if inspect.iscoroutinefunction(func):
            async_func = cast("Callable[..., Awaitable[object]]", func)

            @functools.wraps(func)
            async def async_wrapper(*args: object, **kwargs: object) -> object:
                """Async wrapper that emits step events for async functions.

                Parameters
                ----------
                *args : object
                    Positional arguments passed to the wrapped function.
                **kwargs : object
                    Keyword arguments passed to the wrapped function.

                Returns
                -------
                object
                    Return value from the wrapped async function.

                Raises
                ------
                BaseException
                    Any exception raised by the wrapped function is re-raised after
                    emitting a failed step event.
                """
                start = perf_counter()
                try:
                    result = await async_func(*args, **kwargs)
                except BaseException as exc:
                    telemetry_steps.emit_step(
                        telemetry_steps.StepEvent(
                            kind=f"{component}.{op}",
                            status="failed",
                            detail=type(exc).__name__,
                            payload=_build_step_payload(payload_factory, args, kwargs, None),
                        )
                    )
                    raise
                telemetry_steps.emit_step(
                    telemetry_steps.StepEvent(
                        kind=f"{component}.{op}",
                        status="completed",
                        payload=_with_duration(
                            _build_step_payload(payload_factory, args, kwargs, result),
                            start,
                        ),
                    )
                )
                return result

            return cast("F", async_wrapper)

        @functools.wraps(func)
        def sync_wrapper(*args: object, **kwargs: object) -> object:
            """Sync wrapper that emits step events for synchronous functions.

            Parameters
            ----------
            *args : object
                Positional arguments passed to the wrapped function.
            **kwargs : object
                Keyword arguments passed to the wrapped function.

            Returns
            -------
            object
                Return value from the wrapped function.

            Raises
            ------
            BaseException
                Any exception raised by the wrapped function is re-raised after
                emitting a failed step event.
            """
            start = perf_counter()
            try:
                result = func(*args, **kwargs)
            except BaseException as exc:
                telemetry_steps.emit_step(
                    telemetry_steps.StepEvent(
                        kind=f"{component}.{op}",
                        status="failed",
                        detail=type(exc).__name__,
                        payload=_build_step_payload(payload_factory, args, kwargs, None),
                    )
                )
                raise
            telemetry_steps.emit_step(
                telemetry_steps.StepEvent(
                    kind=f"{component}.{op}",
                    status="completed",
                    payload=_with_duration(
                        _build_step_payload(payload_factory, args, kwargs, result),
                        start,
                    ),
                )
            )
            return result

        return cast("F", sync_wrapper)

    return decorator


def _build_step_payload(
    factory: Callable[[tuple[object, ...], dict[str, object], object | None], Mapping[str, object]]
    | None,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    result: object | None,
) -> dict[str, object]:
    if factory is None:
        return {}
    try:
        return dict(factory(args, kwargs, result))
    except (RuntimeError, ValueError, TypeError):  # pragma: no cover - advisory helper
        LOGGER.debug("Step payload factory failed", exc_info=True)
        return {}


def _with_duration(payload: dict[str, object], started_at: float) -> dict[str, object]:
    payload = dict(payload)
    payload.setdefault("duration_ms", int((perf_counter() - started_at) * 1000))
    return payload


__all__ = ["emit_event", "span_context", "trace_span", "trace_step"]
