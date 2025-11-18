"""Tests for retrieval pipeline gating logic."""

from __future__ import annotations

from codeintel_rev.retrieval.pipeline.gating import StageGateConfig, decide_secondary_stage

from tests._helpers import assertions


def test_decide_secondary_stage_requires_min_candidates() -> None:
    """Test that secondary stage requires minimum candidate count."""
    decision = decide_secondary_stage(
        signals={"candidate_count": 5, "elapsed_ms": 10, "top_score": 0.9, "second_score": 0.8},
        config=StageGateConfig(min_candidates=10),
    )
    assertions.expect_false(decision.should_run)
    assertions.expect_equal(decision.reason, "insufficient_candidates")


def test_decide_secondary_stage_high_margin_skips_stage() -> None:
    """Test that high margin between top scores skips secondary stage."""
    decision = decide_secondary_stage(
        signals={"candidate_count": 20, "elapsed_ms": 10, "top_score": 1.0, "second_score": 0.1},
        config=StageGateConfig(margin_threshold=0.5),
    )
    assertions.expect_false(decision.should_run)
    assertions.expect_equal(decision.reason, "high_margin")


def test_decide_secondary_stage_runs_within_budget() -> None:
    """Test that secondary stage runs when within time budget."""
    decision = decide_secondary_stage(
        signals={"candidate_count": 20, "elapsed_ms": 10, "top_score": 0.4, "second_score": 0.3},
        config=StageGateConfig(),
    )
    assertions.expect_true(decision.should_run)
    assertions.expect_equal(decision.reason, "within_budget")
