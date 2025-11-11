from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.diagnostics import report_cli


def _write_events(path: Path, events: list[dict]) -> None:
    payload = "\n".join(json.dumps(event) for event in events)
    path.write_text(payload + "\n", encoding="utf-8")


def test_report_cli_renders_latest_run(tmp_path):
    events_file = tmp_path / "events.jsonl"
    output_file = tmp_path / "report.md"
    events = [
        {
            "ts": 1,
            "session_id": "s-1",
            "run_id": "run-1",
            "type": "operation.start",
            "name": "mcp.tool.semantic_search_pro",
            "status": "ok",
            "attrs": {"limit": 5},
        },
        {
            "ts": 2,
            "session_id": "s-1",
            "run_id": "run-1",
            "type": "embed.end",
            "name": "vllm",
            "status": "ok",
            "attrs": {"duration_ms": 25, "mode": "http", "n_texts": 2},
        },
        {
            "ts": 3,
            "session_id": "s-1",
            "run_id": "run-1",
            "type": "hybrid.bm25.skip",
            "name": "bm25",
            "status": "ok",
            "attrs": {"reason": "disabled"},
        },
        {
            "ts": 4,
            "session_id": "s-1",
            "run_id": "run-1",
            "type": "operation.end",
            "name": "mcp.tool.semantic_search_pro",
            "status": "ok",
            "attrs": {"duration_ms": 120},
        },
        # Later run
        {
            "ts": 10,
            "session_id": "s-1",
            "run_id": "run-2",
            "type": "operation.start",
            "name": "mcp.tool.semantic_search_pro",
            "status": "ok",
            "attrs": {"limit": 8},
        },
        {
            "ts": 11,
            "session_id": "s-1",
            "run_id": "run-2",
            "type": "faiss.search.end",
            "name": "faiss",
            "status": "ok",
            "attrs": {"duration_ms": 30, "k": 50, "nprobe": 128, "use_gpu": True},
        },
        {
            "ts": 12,
            "session_id": "s-1",
            "run_id": "run-2",
            "type": "hybrid.fuse.end",
            "name": "fusion",
            "status": "ok",
            "attrs": {"duration_ms": 15, "channels": ["semantic"], "total": 20, "returned": 5},
        },
        {
            "ts": 13,
            "session_id": "s-1",
            "run_id": "run-2",
            "type": "operation.end",
            "name": "mcp.tool.semantic_search_pro",
            "status": "ok",
            "attrs": {"duration_ms": 220},
        },
    ]
    _write_events(events_file, events)

    exit_code = report_cli.main(
        [
            "--events",
            str(events_file),
            "--session",
            "s-1",
            "--out",
            str(output_file),
        ]
    )
    assert exit_code == 0

    report = output_file.read_text(encoding="utf-8")
    assert "**Session:** `s-1`" in report
    assert "**Run:** `run-2`" in report  # latest run selected
    assert "Stage Durations" in report
    assert "hybrid.fuse" in report
    assert "Channel Skips" in report
