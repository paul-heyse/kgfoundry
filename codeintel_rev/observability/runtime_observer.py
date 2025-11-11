"""RuntimeCell observer that writes lifecycle events to the active timeline."""

from __future__ import annotations

from codeintel_rev.observability.timeline import Timeline, current_timeline
from codeintel_rev.runtime.cells import (
    RuntimeCellCloseResult,
    RuntimeCellInitResult,
    RuntimeCellObserver,
)


class TimelineRuntimeObserver(RuntimeCellObserver):
    """Emit runtime cell lifecycle events to the active or fallback timeline."""

    __slots__ = ("_fallback",)

    def __init__(self, fallback: Timeline | None = None) -> None:
        self._fallback = fallback

    def _timeline(self) -> Timeline | None:
        return current_timeline() or self._fallback

    def on_init_start(self, *, cell: str) -> None:
        """Record runtime initialization start."""
        timeline = self._timeline()
        if timeline is not None:
            timeline.event("runtime.init.start", cell)

    def on_init_end(self, event: RuntimeCellInitResult) -> None:
        """Record runtime initialization completion."""
        timeline = self._timeline()
        if timeline is not None:
            timeline.event(
                "runtime.init.end",
                event.cell,
                status=event.status,
                attrs={
                    "duration_ms": int(event.duration_ms),
                    "error": type(event.error).__name__ if event.error else None,
                },
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
