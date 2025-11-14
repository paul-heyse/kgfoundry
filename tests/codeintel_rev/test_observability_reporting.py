from __future__ import annotations

from codeintel_rev.observability.reporting import (
    TimelineRunReport,
    render_timeline_markdown,
    timeline_mermaid,
)


def test_timeline_renderers_return_content() -> None:
    report = TimelineRunReport(
        session_id="sess",
        run_id="run",
        events=[
            {"ts": 1.0, "type": "operation.start", "name": "search", "status": "ok"},
            {"ts": 2.0, "type": "operation.end", "name": "search", "status": "ok"},
        ],
    )
    markdown = render_timeline_markdown(report)
    assert "Run Report" in markdown
    mermaid = timeline_mermaid(report)
    assert "graph TD" in mermaid
