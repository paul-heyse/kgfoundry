"""Gating façade for orchestrating late-interaction stages."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from codeintel_rev.retrieval.gating import (
    StageGateConfig as _CoreStageGateConfig,
)
from codeintel_rev.retrieval.gating import (
    should_run_secondary_stage as _core,
)
from codeintel_rev.retrieval.types import StageSignals


class StageGateCoreResult(Protocol):
    """Protocol describing the result of core stage gating logic.

    This protocol defines the interface for gating decisions returned by the
    core gating function, enabling type-safe interaction with gating results
    while maintaining compatibility across different gating implementations.
    """

    @property
    def should_run(self) -> bool:
        """Return whether the secondary stage should run."""
        ...

    @property
    def reason(self) -> object:
        """Return the reason for the gating decision."""
        ...


StageGateCore = Callable[[StageSignals, _CoreStageGateConfig], StageGateCoreResult]


_STAGE_GATE_CORE_REF: list[StageGateCore] = [_core]


@dataclass(frozen=True, slots=True)
class StageGateConfig:
    """Minimal configuration surface consumed by adapters.

    Attributes
    ----------
    time_budget_ms : int, optional
        Maximum time budget in milliseconds for stage execution. Must be
        positive. Defaults to 750.
    min_candidates : int, optional
        Minimum number of candidates required to proceed to next stage. Must be
        positive. Defaults to 16.
    high_margin_threshold : float, optional
        High margin threshold for score differences. Must be non-negative.
        Defaults to 0.25.
    """

    time_budget_ms: int = 750
    min_candidates: int = 16
    high_margin_threshold: float = 0.25


@dataclass(frozen=True, slots=True)
class StageDecision:
    """Normalized gating decision.

    Attributes
    ----------
    should_run : bool
        Whether the stage should be executed based on gating logic.
    reason : str
        Human-readable reason string explaining the decision.
    """

    should_run: bool
    reason: str


def decide_secondary_stage(
    signals: Mapping[str, object],
    config: StageGateConfig,
) -> StageDecision:
    """Run the core gating logic and normalize the result for adapters.

    Parameters
    ----------
    signals : Mapping[str, object]
        Candidate stats (counts, margins, budgets) emitted by Stage-0.
    config : StageGateConfig
        Gating configuration to evaluate the signals against.

    Returns
    -------
    StageDecision
        Normalized decision containing ``should_run`` and ``reason`` fields.
    """
    stage_signals = _normalize_signals(signals)
    core_config = _CoreStageGateConfig(
        budget_ms=config.time_budget_ms,
        min_candidates=config.min_candidates,
        margin_threshold=config.high_margin_threshold,
    )
    out = _STAGE_GATE_CORE_REF[0](stage_signals, core_config)
    return StageDecision(should_run=bool(out.should_run), reason=str(out.reason))


@contextmanager
def override_stage_gate_core(core: StageGateCore) -> Iterator[None]:
    """Temporarily override the Stage-1 gating core callable for tests."""
    previous = _STAGE_GATE_CORE_REF[0]
    _STAGE_GATE_CORE_REF[0] = core
    try:
        yield
    finally:
        _STAGE_GATE_CORE_REF[0] = previous


def _normalize_signals(signals: Mapping[str, object]) -> StageSignals:
    """Convert raw mappings into :class:`StageSignals` instances.

    Parameters
    ----------
    signals : Mapping[str, object]
        Raw signal mapping with string keys and arbitrary values.

    Returns
    -------
    StageSignals
        Normalized signals captured for downstream gating.
    """

    def _maybe_float(value: object | None) -> float | None:
        """Convert a value to float if possible, returning None otherwise.

        Parameters
        ----------
        value : object | None
            Value to convert to float. Can be None, int, float, or other types.

        Returns
        -------
        float | None
            The float representation of the value if it's numeric (int or float),
            or None if the value is None or cannot be converted to float.
        """
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return None

    raw_candidates = signals.get("candidate_count")
    candidate_count = int(raw_candidates) if isinstance(raw_candidates, (int, float)) else 0
    elapsed_ms = _maybe_float(signals.get("elapsed_ms"))
    if elapsed_ms is None:
        elapsed_ms = _maybe_float(signals.get("budget_ms")) or 0.0
    best_score = _maybe_float(signals.get("best_score", signals.get("top_score")))
    second_best = _maybe_float(signals.get("second_best_score"))
    if second_best is None and best_score is not None:
        margin = _maybe_float(signals.get("margin"))
        if margin is not None:
            second_best = best_score - margin
    return StageSignals(
        candidate_count=candidate_count,
        elapsed_ms=float(elapsed_ms),
        best_score=best_score,
        second_best_score=second_best,
    )


__all__ = [
    "StageDecision",
    "StageGateConfig",
    "decide_secondary_stage",
    "override_stage_gate_core",
]
