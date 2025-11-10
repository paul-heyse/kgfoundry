from __future__ import annotations

import time

import pytest
from codeintel_rev.retrieval.telemetry import (
    StageTiming,
    record_stage_decision,
    track_stage,
)
from codeintel_rev.retrieval.types import StageDecision
from prometheus_client import CollectorRegistry

from kgfoundry_common.prometheus import build_counter


def test_track_stage_records_duration_and_budget_flag() -> None:
    with track_stage("stage", budget_ms=1) as timer:
        time.sleep(0.002)
    snapshot = timer.snapshot()
    assert isinstance(snapshot, StageTiming)
    assert snapshot.name == "stage"
    assert snapshot.duration_ms > 0
    assert snapshot.exceeded_budget
    payload = snapshot.as_payload()
    assert payload["name"] == "stage"


def test_record_stage_decision_emits_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = CollectorRegistry()
    counter = build_counter(
        "kgfoundry_stage_decisions_total",
        "Stage gating outcomes grouped by component, stage, and decision type.",
        ("component", "stage", "decision"),
        registry=registry,
    )
    from codeintel_rev.retrieval import telemetry as telemetry_module

    monkeypatch.setattr(
        telemetry_module,
        "_STAGE_DECISION_COUNTER",
        counter,
        raising=False,
    )

    record_stage_decision(
        "component",
        "stage",
        decision=StageDecision(should_run=False, reason="disabled"),
    )
    value = registry.get_sample_value(
        "kgfoundry_stage_decisions_total",
        {"component": "component", "stage": "stage", "decision": "skip:disabled"},
    )
    assert value == pytest.approx(1.0)
