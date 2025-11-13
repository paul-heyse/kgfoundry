"""Decorators for consistent span/timeline instrumentation."""

from __future__ import annotations

import functools
import importlib
import inspect
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from time import perf_counter
from typing import TypeVar

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

from codeintel_rev.observability.timeline import current_timeline
from codeintel_rev.telemetry.context import attach_context_attrs, set_request_stage
from codeintel_rev.telemetry.prom import record_stage_latency

F = TypeVar("F", bound=Callable[..., object])

_SPAN_KINDS: dict[str, SpanKind] = {
    "internal": SpanKind.INTERNAL,
    "server": SpanKind.SERVER,
    "client": SpanKind.CLIENT,
    "producer": SpanKind.PRODUCER,
    "consumer": SpanKind.CONSUMER,
}

TRACER = trace.get_tracer("codeintel_rev.telemetry")


def _emit_checkpoint(
    stage: str | None, *, ok: bool, reason: str | None, attrs: Mapping[str, object]
) -> None:
    if stage is None:
        return
    payload = dict(attrs)
    if reason is not None:
        payload["reason"] = reason
    try:
        reporter = importlib.import_module("codeintel_rev.telemetry.reporter")
        reporter.emit_checkpoint(stage, ok=ok, **payload)
    except (ImportError, AttributeError, RuntimeError):  # pragma: no cover - defensive
        return


def _set_span_attributes(span: Span, attrs: Mapping[str, object]) -> None:
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
) -> Iterator[tuple[Span, dict[str, object]]]:
    telemetry_attrs = attach_context_attrs(base_attrs)
    timeline = current_timeline()
    stage_token = set_request_stage(stage) if stage else None
    step_cm = timeline.step(name, **telemetry_attrs) if timeline is not None else nullcontext()
    span_kind = _SPAN_KINDS.get(kind, SpanKind.INTERNAL)
    with TRACER.start_as_current_span(name, kind=span_kind) as span:
        _set_span_attributes(span, telemetry_attrs)
        try:
            with step_cm:
                yield span, telemetry_attrs
        finally:
            if stage_token is not None:
                stage_token.var.reset(stage_token)


def _record_exception(span: Span, exc: BaseException) -> None:
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR))


@contextmanager
def span_context(
    name: str,
    *,
    kind: str = "internal",
    attrs: Mapping[str, object] | None = None,
    stage: str | None = None,
    emit_checkpoint: bool = False,
) -> Iterator[tuple[Span, dict[str, object]]]:
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
    tuple[Span, dict[str, object]]
        Tuple containing:
        - Span: The active OpenTelemetry span for adding custom attributes or
          recording events
        - dict[str, object]: Merged attribute dictionary combining provided attrs
          with context attributes (request ID, stage, etc.)

    Raises
    ------
    BaseException
        Any exception raised within the context is caught, recorded on the span
        with error status, and re-raised. The context manager ensures proper
        span cleanup and error attribution even when exceptions occur.

    Notes
    -----
    This context manager integrates OpenTelemetry tracing with timeline recording
    and Prometheus metrics. It automatically records exceptions, sets span status,
    and records stage latency. The context manager is thread-safe if the underlying
    tracing infrastructure is thread-safe. Stage latency is recorded only when
    stage is provided.
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
                    return await func(*args, **kwargs)

            return async_wrapper  # type: ignore[return-value]

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

        return sync_wrapper  # type: ignore[return-value]

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


__all__ = ["span_context", "trace_span", "trace_step"]
