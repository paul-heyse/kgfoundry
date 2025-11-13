from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from codeintel_rev.observability import flight_recorder


def test_build_report_uri_uses_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    started_at = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    uri = flight_recorder.build_report_uri("sess", "run-7", trace_id="trace", started_at=started_at)
    assert uri is not None
    path = Path(uri)
    assert path.parts[-4] == "runs"
    assert path.parts[-2] == "sess"
    assert path.parts[-1] == "run-7.json"


def test_build_summary_counts_warnings():
    events = [
        {"name": "retrieval.embed", "component": "retrieval", "attrs": {}},
        {
            "name": "decision.gate.budget",
            "component": "retrieval",
            "attrs": {"warn.degraded": True, "rrf_k": 60},
        },
    ]
    summary = flight_recorder.build_event_summary(events)
    assert summary["events"] == 2
    assert summary["stages"] == ["retrieval.embed", "decision.gate.budget"]
    assert summary["warnings"] == 1
    decisions = summary["decisions"]
    assert isinstance(decisions, list)
    assert decisions
    assert decisions[0].get("rrf_k") == 60
