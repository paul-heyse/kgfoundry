"""Gating façade for orchestrating late-interaction stages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from codeintel_rev.retrieval.gating import StageGateConfig as CoreStageGateConfig
from codeintel_rev.retrieval.gating import StageSignals, should_run_secondary_stage


@dataclass(slots=True, frozen=True)
class StageGateConfig:
    """Minimal configuration surface consumed by adapters."""

    min_candidates: int = 16
    margin_threshold: float = 0.2
    budget_ms: int = 750


@dataclass(slots=True, frozen=True)
class StageDecision:
    """Normalized gating decision."""

    should_run: bool
    reason: str
    notes: tuple[str, ...] = ()


def decide_secondary_stage(
    *,
    signals: Mapping[str, object],
    config: StageGateConfig,
) -> StageDecision:
    """Run the core gating logic and normalize the result for adapters.

    Parameters
    ----------
    signals : Mapping[str, object]
        Stage signals containing candidate_count, elapsed_ms, top_score,
        and second_score.
    config : StageGateConfig
        Gating configuration with thresholds and budgets.

    Returns
    -------
    StageDecision
        Decision containing should_run flag, reason, and optional notes.
    """
    core_config = CoreStageGateConfig(
        min_candidates=config.min_candidates,
        margin_threshold=config.margin_threshold,
        budget_ms=config.budget_ms,
    )
    stage_signals = StageSignals(
        candidate_count=int(signals.get("candidate_count", 0)),
        elapsed_ms=float(signals.get("elapsed_ms", 0.0)),
        best_score=_maybe_float(signals.get("top_score")),
        second_best_score=_maybe_float(signals.get("second_score")),
    )
    decision = should_run_secondary_stage(stage_signals, core_config)
    return StageDecision(
        should_run=decision.should_run,
        reason=decision.reason,
        notes=decision.notes,
    )


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["StageDecision", "StageGateConfig", "decide_secondary_stage"]
