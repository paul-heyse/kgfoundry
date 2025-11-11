from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.observability.timeline import (
    bind_timeline,
    current_timeline,
    new_timeline,
)


def _read_events(tmp_path: Path) -> list[dict]:
    files = list(tmp_path.glob("events-*.jsonl"))
    assert files, "timeline should write JSONL file"
    content = files[0].read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in content if line]


def test_timeline_event_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEINTEL_DIAG_DIR", str(tmp_path))
    timeline = new_timeline("session-test")

    timeline.event("demo", "unit", attrs={"foo": "bar"})

    events = _read_events(tmp_path)
    assert events[0]["session_id"] == "session-test"
    assert events[0]["type"] == "demo"
    assert events[0]["attrs"]["foo"] == "bar"


def test_operation_context_records_duration(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEINTEL_DIAG_DIR", str(tmp_path))
    timeline = new_timeline("session-demo")
    with bind_timeline(timeline), timeline.operation("mcp.tool.test", limit=3):
        pass

    events = _read_events(tmp_path)
    # Operation emits start + end events
    assert events[0]["type"] == "operation.start"
    end_event = events[1]
    assert end_event["type"] == "operation.end"
    duration = end_event["attrs"].get("duration_ms")
    assert duration is not None
    assert duration >= 0
    assert end_event["attrs"]["limit"] == 3


def test_long_strings_are_scrubbed(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEINTEL_DIAG_DIR", str(tmp_path))
    monkeypatch.setenv("CODEINTEL_DIAG_MAX_FIELD_LEN", "4")
    timeline = new_timeline("scrub")
    timeline.event("demo", "unit", attrs={"blob": "x" * 32})

    events = _read_events(tmp_path)
    payload = events[0]["attrs"]["blob"]
    assert payload["len"] == 32
    assert "sha256" in payload


def test_bind_timeline_context_manager():
    timeline = new_timeline("ctx")
    assert current_timeline() is None
    with bind_timeline(timeline):
        assert current_timeline() is timeline
    assert current_timeline() is None
