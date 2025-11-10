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

    Extended Summary
    ----------------
    This function implements adaptive gating logic for multi-stage retrieval pipelines,
    deciding whether to run expensive secondary stages (e.g., reranking, late interaction)
    based on upstream performance signals. It evaluates candidate count, elapsed time budget,
    and score margin to determine if the secondary stage would provide sufficient value.
    This prevents unnecessary computation when upstream results are already high-quality or
    when time budgets are exceeded, improving overall pipeline efficiency.

    Parameters
    ----------
    signals : StageSignals
        Performance signals from the upstream stage, including candidate count, elapsed
        time, and score distribution. Used to assess whether secondary stage is warranted.
    config : StageGateConfig
        Gating configuration specifying thresholds for candidate count, margin, and time
        budget. Defines the decision criteria for running the secondary stage.

    Returns
    -------
    StageDecision
        Decision object describing whether the stage should run and why. Contains
        should_run boolean, reason string, and optional notes explaining the decision.
        Reasons include: "no_candidates", "insufficient_candidates", "upstream_budget_exceeded",
        "high_margin", "within_budget".

    Notes
    -----
    Time complexity O(1) for decision logic. Space complexity O(1) aside from the
    StageDecision object. The function performs no I/O and has no side effects.
    Thread-safe as it operates on input data only. Decision logic prioritizes:
    1. Candidate availability (must have candidates)
    2. Time budget (must not exceed budget)
    3. Score margin (high margin suggests good results already)
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
