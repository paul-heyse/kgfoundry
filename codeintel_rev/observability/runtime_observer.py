"""RuntimeCell observer that writes lifecycle events to the active timeline."""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

from codeintel_rev.observability.ledger import RunLedger
from codeintel_rev.observability.timeline import Timeline, current_timeline
from codeintel_rev.runtime.cells import (
    RuntimeCellCloseResult,
    RuntimeCellInitContext,
    RuntimeCellInitResult,
    RuntimeCellObserver,
)

__all__ = [
    "TimelineRuntimeObserver",
    "bind_run_ledger",
    "current_run_ledger",
]


_run_ledger_var: contextvars.ContextVar[RunLedger | None] = contextvars.ContextVar(
    "codeintel_run_ledger",
    default=None,
)


def current_run_ledger() -> RunLedger | None:
    """Return the run ledger bound to the current context, if any.

    Returns
    -------
    RunLedger | None
        The run ledger bound to the current context variable, or None if no
        ledger is currently bound.
    """
    return _run_ledger_var.get()


@contextmanager
def bind_run_ledger(ledger: RunLedger | None) -> Iterator[None]:
    """Bind ``ledger`` to the current context for the duration of the block."""
    token = _run_ledger_var.set(ledger)
    try:
        yield
    finally:
        _run_ledger_var.reset(token)


class TimelineRuntimeObserver(RuntimeCellObserver):
    """Emit runtime cell lifecycle events to the active or fallback timeline."""

    __slots__ = ("_fallback",)

    def __init__(self, fallback: Timeline | None = None) -> None:
        self._fallback = fallback

    def _timeline(self, context: RuntimeCellInitContext | None = None) -> Timeline | None:
        if context and context.timeline is not None:
            return context.timeline
        return current_timeline() or self._fallback

    def on_init_start(
        self,
        *,
        cell: str,
        generation: int,
        context: RuntimeCellInitContext | None = None,
    ) -> None:
        """Record runtime initialization start."""
        timeline = self._timeline(context)
        if timeline is not None:
            attrs: dict[str, object] = {"generation": generation}
            if context is not None:
                if context.session_id is not None:
                    attrs["session_id"] = context.session_id
                if context.capability_stamp is not None:
                    attrs["capability_stamp"] = context.capability_stamp
            timeline.event("runtime.init.start", cell, attrs=attrs)

    def on_init_end(self, event: RuntimeCellInitResult) -> None:
        """Record runtime initialization completion."""
        timeline = self._timeline(event.context)
        if timeline is None:
            return
        attrs: dict[str, object] = {
            "duration_ms": int(event.duration_ms),
            "generation": event.generation,
        }
        context = event.context
        if context is not None:
            if context.session_id is not None:
                attrs["session_id"] = context.session_id
            if context.capability_stamp is not None:
                attrs["capability_stamp"] = context.capability_stamp
        if event.error is not None:
            attrs["error"] = type(event.error).__name__
        if event.status == "error":
            timeline.event(
                "runtime.init.err",
                event.cell,
                status="error",
                attrs=attrs,
            )
        else:
            timeline.event(
                "runtime.init.end",
                event.cell,
                attrs=attrs,
            )

    def on_close_end(self, event: RuntimeCellCloseResult) -> None:
        """Record runtime close completion."""
        timeline = self._timeline()
        if timeline is not None:
            timeline.event(
                "runtime.close.end",
                event.cell,
                status=event.status,
                attrs={
                    "duration_ms": int(event.duration_ms),
                    "had_payload": event.had_payload,
                },
            )

    def record_decision(
        self,
        name: str,
        *,
        reason: str,
        fallback: str | None = None,
        status: str = "ok",
    ) -> None:
        """Emit a decision event for runtime degradations or fallbacks."""
        timeline = self._timeline()
        if timeline is not None:
            event_fields = {"reason": reason}
            if fallback is not None:
                event_fields["fallback"] = fallback
            timeline.event("decision", name, status=status, attrs=event_fields)
