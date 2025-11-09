"""Adaptive gating helpers for multi-stage retrieval pipelines."""

from __future__ import annotations

from dataclasses import dataclass

from codeintel_rev.retrieval.types import StageDecision, StageSignals


@dataclass(slots=True, frozen=True)
class StageGateConfig:
    """Configuration inputs for deciding whether to invoke a follow-up stage."""

    min_candidates: int = 40
    margin_threshold: float = 0.1
    budget_ms: int = 150


def should_run_secondary_stage(
    signals: StageSignals,
    config: StageGateConfig,
) -> StageDecision:
    """Return a gating decision for a downstream stage based on upstream signals.

    Returns
    -------
    StageDecision
        Decision describing whether the stage should run and why.
    """
    notes: list[str] = []
    if signals.candidate_count <= 0:
        return StageDecision(should_run=False, reason="no_candidates")
    if signals.candidate_count < config.min_candidates:
        notes.append(f"{signals.candidate_count}/{config.min_candidates} candidates available")
        return StageDecision(should_run=False, reason="insufficient_candidates", notes=tuple(notes))

    if signals.elapsed_ms > config.budget_ms:
        notes.append(f"stage elapsed {signals.elapsed_ms:.1f}ms > budget {config.budget_ms}ms")
        return StageDecision(
            should_run=False, reason="upstream_budget_exceeded", notes=tuple(notes)
        )

    margin = signals.margin()
    if margin is not None and margin >= config.margin_threshold > 0:
        notes.append(f"margin {margin:.4f} >= threshold {config.margin_threshold:.4f}")
        return StageDecision(should_run=False, reason="high_margin", notes=tuple(notes))

    return StageDecision(should_run=True, reason="within_budget", notes=tuple(notes))


__all__ = ["StageGateConfig", "should_run_secondary_stage"]
