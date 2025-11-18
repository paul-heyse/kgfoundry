"""Tests for retrieval pipeline gating helpers."""

from __future__ import annotations

from types import SimpleNamespace

from codeintel_rev.retrieval.pipeline import gating

from tests._helpers import assertions

_DEFAULT_TIME_BUDGET_MS = 750
_DEFAULT_MIN_CANDIDATES = 16
_DEFAULT_MARGIN = 0.25


def test_decide_secondary_stage_delegates_to_core() -> None:
    """decide_secondary_stage returns StageDecision shaped like core output."""
    captured: dict[str, object] = {}

    def _fake_core(signals: object, config: object) -> SimpleNamespace:
        captured["signals"] = signals
        captured["config"] = config
        return SimpleNamespace(should_run=True, reason="ok")

    with gating.override_stage_gate_core(_fake_core):
        decision = gating.decide_secondary_stage({"candidate_count": 5}, gating.StageGateConfig())

    assertions.expect_true(decision.should_run)
    assertions.expect_equal(decision.reason, "ok")
    assertions.expect_true("signals" in captured)
    assertions.expect_true("config" in captured)


def test_stage_gate_config_defaults() -> None:
    """StageGateConfig exposes the budget knobs expected by adapters."""
    config = gating.StageGateConfig()
    assertions.expect_equal(config.time_budget_ms, _DEFAULT_TIME_BUDGET_MS)
    assertions.expect_equal(config.min_candidates, _DEFAULT_MIN_CANDIDATES)
    assertions.expect_equal(config.high_margin_threshold, _DEFAULT_MARGIN)
