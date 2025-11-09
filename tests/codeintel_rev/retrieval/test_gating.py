from __future__ import annotations

from codeintel_rev.retrieval.gating import StageGateConfig, should_run_secondary_stage
from codeintel_rev.retrieval.types import StageSignals


def test_stage_gating_blocks_on_candidate_shortfall() -> None:
    signals = StageSignals(
        candidate_count=5, elapsed_ms=10.0, best_score=0.2, second_best_score=0.18
    )
    decision = should_run_secondary_stage(
        signals,
        StageGateConfig(min_candidates=10, margin_threshold=0.05, budget_ms=120),
    )
    assert not decision.should_run
    assert decision.reason == "insufficient_candidates"


def test_stage_gating_runs_when_within_budget_and_low_margin() -> None:
    signals = StageSignals(
        candidate_count=100, elapsed_ms=80.0, best_score=0.31, second_best_score=0.30
    )
    decision = should_run_secondary_stage(
        signals,
        StageGateConfig(min_candidates=10, margin_threshold=0.05, budget_ms=120),
    )
    assert decision.should_run
    assert decision.reason == "within_budget"
