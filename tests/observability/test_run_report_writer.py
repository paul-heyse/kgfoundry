from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.observability.reporting import latest_run_report, render_run_report
from codeintel_rev.observability.timeline import Timeline, bind_timeline


def test_render_run_report_writes_artifacts(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CODEINTEL_DIAG_DIR", str(tmp_path / "diag"))
    timeline = Timeline(session_id="sess-1", run_id="run-1", sampled=True)
    timeline.set_metadata(kind="cli", started_at=0.0)
    with bind_timeline(timeline), timeline.operation("cli.test"):
        timeline.event("custom", "stage", attrs={"detail": "example"})
    out_dir = tmp_path / "runs"
    markdown_path = render_run_report(timeline, out_dir=out_dir)
    assert markdown_path.exists()
    json_path = markdown_path.with_suffix(".json")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["run"]["run_id"] == "run-1"
    assert data["summary"]["events"] == 3  # operation start/end + custom event
    latest = latest_run_report()
    assert latest is not None
    assert isinstance(latest, dict)
    markdown_value = latest.get("markdown")
    assert isinstance(markdown_value, str)
    assert Path(markdown_value) == markdown_path
