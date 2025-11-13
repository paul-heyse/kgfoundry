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

    Yields
    ------
    tuple[Span, dict[str, object]]
        The active span and merged attribute dictionary.
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

    Returns
    -------
    Callable[[F], F]
        Decorated callable.
    """
    base_attrs = dict(attrs or {})

    def decorator(func: F) -> F:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: object, **kwargs: object) -> object:
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

    Returns
    -------
    Callable[[F], F]
        Decorated callable instrumented as ``stage``.
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
