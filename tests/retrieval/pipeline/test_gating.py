"""Tests for retrieval pipeline gating logic."""

from __future__ import annotations

import pytest
from codeintel_rev.retrieval.pipeline.gating import (
    StageGateConfig,
    StageSignalFactory,
    decide_secondary_stage,
)

from tests._helpers import assertions


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"candidate_count": 5, "elapsed_ms": 12, "top_score": 0.5, "second_score": 0.4},
            (5, 12.0, 0.5, 0.4),
        ),
        (
            {"candidate_count": "7", "elapsed_ms": "1.5"},
            (7, 1.5, None, None),
        ),
    ],
)
def test_stage_signal_factory_builds_structured_payload(
    payload: dict[str, object], expected: tuple[int, float, float | None, float | None]
) -> None:
    """StageSignalFactory converts loose payloads to StageSignals."""
    signals = StageSignalFactory(payload).build()
    assertions.expect_equal(signals.candidate_count, expected[0])
    assertions.expect_equal(signals.elapsed_ms, expected[1])
    assertions.expect_equal(signals.best_score, expected[2])
    assertions.expect_equal(signals.second_best_score, expected[3])


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"candidate_count": None, "elapsed_ms": 0}, "candidate_count"),
        ({"candidate_count": True, "elapsed_ms": 0}, "candidate_count"),
        (
            {"candidate_count": 1, "elapsed_ms": 0, "top_score": "nope"},
            "top_score",
        ),
    ],
)
def test_stage_signal_factory_rejects_invalid_payload(
    payload: dict[str, object], message: str
) -> None:
    """Invalid payloads raise descriptive ValueErrors."""
    with pytest.raises(ValueError, match=message):
        StageSignalFactory(payload).build()


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
