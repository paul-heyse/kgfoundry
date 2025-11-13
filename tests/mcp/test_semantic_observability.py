from __future__ import annotations

from pathlib import Path

from codeintel_rev.observability.timeline import Timeline


def _configure_timeline() -> Timeline:
    timeline = Timeline(session_id="session-1", run_id="run-1", sampled=True)
    timeline.set_metadata(started_at=0.0)
    return timeline


def test_semantic_observability_links(monkeypatch, tmp_path):
    from codeintel_rev.mcp_server.adapters import semantic

    timeline = _configure_timeline()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(semantic, "current_trace_id", lambda: "trace-123")
    monkeypatch.setattr(semantic, "current_span_id", lambda: "span-456")
    extras = semantic.build_observability_links(timeline)
    assert extras.get("trace_id") == "trace-123"
    assert extras.get("span_id") == "span-456"
    assert extras.get("run_id") == timeline.run_id
    diag_uri = extras.get("diag_report_uri")
    assert isinstance(diag_uri, str)
    diag_path = Path(diag_uri)
    assert "session-1" in diag_path.parts


def test_semantic_pro_observability_links(monkeypatch, tmp_path):
    from codeintel_rev.mcp_server.adapters import semantic_pro

    timeline = _configure_timeline()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(semantic_pro, "current_timeline", lambda: timeline)
    monkeypatch.setattr(semantic_pro, "current_trace_id", lambda: "trace-abc")
    monkeypatch.setattr(semantic_pro, "current_span_id", lambda: "span-def")
    monkeypatch.setattr(semantic_pro, "current_run_id", lambda: "run-xyz")
    extras = semantic_pro.build_observability_links()
    assert extras.get("trace_id") == "trace-abc"
    assert extras.get("span_id") == "span-def"
    assert extras.get("run_id") == "run-1"
    diag_uri = extras.get("diag_report_uri")
    assert isinstance(diag_uri, str)
    assert "diag_report_uri" in extras
