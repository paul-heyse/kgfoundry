"""Stage-level telemetry helpers used by multi-stage retrieval pipelines."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter


@dataclass(slots=True, frozen=True)
class StageTiming:
    """Snapshot describing how long a stage took relative to its budget."""

    name: str
    duration_ms: float
    budget_ms: int | None
    exceeded_budget: bool

    def as_payload(self) -> dict[str, float | int | bool | str | None]:
        """Return a JSON-friendly payload for inclusion in envelopes.

        Returns
        -------
        dict[str, float | int | bool | str | None]
            Mapping containing stage timing metadata.
        """
        return {
            "name": self.name,
            "duration_ms": round(self.duration_ms, 2),
            "budget_ms": self.budget_ms,
            "exceeded_budget": self.exceeded_budget,
        }


@dataclass(slots=True)
class _StageTimer:
    name: str
    budget_ms: int | None
    _started_at: float = field(default_factory=perf_counter, init=False)
    _duration_ms: float = field(default=0.0, init=False)
    _stopped: bool = field(default=False, init=False)

    def stop(self) -> None:
        if self._stopped:
            return
        self._duration_ms = (perf_counter() - self._started_at) * 1000.0
        self._stopped = True

    def snapshot(self) -> StageTiming:
        self.stop()
        exceeded = bool(self.budget_ms is not None and self._duration_ms > self.budget_ms)
        return StageTiming(
            name=self.name,
            duration_ms=self._duration_ms,
            budget_ms=self.budget_ms,
            exceeded_budget=exceeded,
        )


@contextmanager
def track_stage(
    name: str,
    *,
    budget_ms: int | None = None,
) -> Iterator[_StageTimer]:
    """Context manager yielding a timer that can be converted into StageTiming.

    Yields
    ------
    _StageTimer
        Timer instance used to capture duration metrics.
    """
    timer = _StageTimer(name=name, budget_ms=budget_ms)
    try:
        yield timer
    finally:
        timer.stop()


__all__ = ["StageTiming", "track_stage"]
