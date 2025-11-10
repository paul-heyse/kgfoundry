"""Stage-level telemetry helpers used by multi-stage retrieval pipelines."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter

from kgfoundry_common.logging import get_logger
from kgfoundry_common.observability import MetricsProvider
from kgfoundry_common.prometheus import build_counter, get_default_registry

from codeintel_rev.retrieval.types import StageDecision


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


class _TimerRuntime:
    """Mutable stopwatch backing the frozen stage timer."""

    __slots__ = ("duration_ms", "started_at", "stopped")

    def __init__(self) -> None:
        self.started_at = perf_counter()
        self.duration_ms = 0.0
        self.stopped = False

    def stop(self) -> float:
        if self.stopped:
            return self.duration_ms
        self.duration_ms = (perf_counter() - self.started_at) * 1000.0
        self.stopped = True
        return self.duration_ms


@dataclass(slots=True, frozen=True)
class _StageTimer:
    name: str
    budget_ms: int | None
    _runtime: _TimerRuntime = field(default_factory=_TimerRuntime, init=False, repr=False)

    def stop(self) -> None:
        self._runtime.stop()

    def snapshot(self) -> StageTiming:
        duration = self._runtime.stop()
        exceeded = bool(self.budget_ms is not None and duration > self.budget_ms)
        return StageTiming(
            name=self.name,
            duration_ms=duration,
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


LOGGER = get_logger(__name__)
_STAGE_DECISION_COUNTER = build_counter(
    "kgfoundry_stage_decisions_total",
    "Stage gating outcomes grouped by component, stage, and decision type.",
    ("component", "stage", "decision"),
    registry=get_default_registry(),
)


def record_stage_metric(
    component: str,
    timing: StageTiming,
    *,
    metrics: MetricsProvider | None = None,
) -> None:
    """Record the provided ``timing`` in Prometheus metrics."""
    provider = metrics or MetricsProvider.default()
    try:
        provider.operation_duration_seconds.labels(
            component=component,
            operation=timing.name,
            status="degraded" if timing.exceeded_budget else "success",
        ).observe(timing.duration_ms / 1000.0)
    except ValueError as exc:  # pragma: no cover - defensive logging
        LOGGER.warning(
            "Failed to emit stage metric",
            extra={
                "component": component,
                "stage": timing.name,
                "error": str(exc),
            },
        )


def record_stage_decision(
    component: str,
    stage: str,
    *,
    decision: StageDecision,
) -> None:
    """Increment the stage decision counter for the given outcome."""
    label_value = "run" if decision.should_run else f"skip:{decision.reason}"
    _STAGE_DECISION_COUNTER.labels(
        component=component,
        stage=stage,
        decision=label_value,
    ).inc()


__all__ = [
    "StageTiming",
    "record_stage_decision",
    "record_stage_metric",
    "track_stage",
]
