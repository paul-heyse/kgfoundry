"""Typed event helpers shared across telemetry modules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "RunCheckpoint",
    "TimelineEvent",
    "checkpoint_event",
    "coerce_event",
]


@dataclass(slots=True, frozen=True)
class RunCheckpoint:
    """Structured checkpoint emitted after significant pipeline stages."""

    stage: str
    ok: bool
    reason: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_event_attrs(self) -> dict[str, Any]:
        """Return a JSON-ready dictionary for downstream stores.

        Returns
        -------
        dict[str, Any]
            Attribute dictionary describing the checkpoint.
        """
        payload: dict[str, Any] = {"stage": self.stage, "ok": self.ok}
        if self.reason:
            payload["reason"] = self.reason
        payload.update(self.attrs)
        return payload


@dataclass(slots=True, frozen=True)
class TimelineEvent:
    """Normalized representation of a timeline entry."""

    session_id: str
    run_id: str
    ts: float
    type: str
    name: str
    status: str
    message: str | None
    attrs: dict[str, Any]


def checkpoint_event(
    stage: str, *, ok: bool, reason: str | None = None, **attrs: object
) -> RunCheckpoint:
    """Create a RunCheckpoint instance.

    Returns
    -------
    RunCheckpoint
        Structured checkpoint payload.
    """
    return RunCheckpoint(stage=stage, ok=ok, reason=reason, attrs=dict(attrs))


def coerce_event(payload: Mapping[str, Any]) -> TimelineEvent:
    """Coerce a raw timeline payload into :class:`TimelineEvent`.

    Returns
    -------
    TimelineEvent
        Normalised timeline event.
    """
    return TimelineEvent(
        session_id=str(payload.get("session_id", "")),
        run_id=str(payload.get("run_id", "")),
        ts=float(payload.get("ts", 0.0)),
        type=str(payload.get("type", "")),
        name=str(payload.get("name") or ""),
        status=str(payload.get("status") or "ok"),
        message=payload.get("message"),
        attrs=dict(payload.get("attrs") or {}),
    )
