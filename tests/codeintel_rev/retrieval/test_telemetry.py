from __future__ import annotations

import time

from codeintel_rev.retrieval.telemetry import StageTiming, track_stage


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
