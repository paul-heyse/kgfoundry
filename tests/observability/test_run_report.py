from __future__ import annotations

from pathlib import Path

from codeintel_rev.observability.run_report import build_run_report
from codeintel_rev.telemetry.reporter import RunReportStore


def test_build_run_report_infers_stop_reason(tmp_path: Path) -> None:
    run_id = "test-run"
    day_dir = tmp_path / "telemetry" / "runs" / "2024-01-01"
    day_dir.mkdir(parents=True)
    ledger = day_dir / f"{run_id}.jsonl"
    ledger.write_text(
        """
{"session_id":"s","run_id":"test-run","kind":"vllm.embed_batch","status":"completed"}
{"session_id":"s","run_id":"test-run","kind":"duckdb.query","status":"failed","detail":"OperationalError"}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = build_run_report(run_id, ledger)

    assert report.run_id == run_id
    assert report.stopped_because == "duckdb.query:OperationalError"
    assert len(report.steps) == 2


def test_store_infers_stop_reason_from_structured_events() -> None:
    store = RunReportStore(retention=10)
    store.start_run("session", "run", tool_name=None, capability_stamp=None, started_at=None)
    store.record_structured_event(
        {
            "session_id": "session",
            "run_id": "run",
            "kind": "faiss.search",
            "status": "failed",
            "detail": "Timeout",
        }
    )
    store.finalize("session", "run", status="error", stop_reason=None, finished_at=None)
    record = store.get_run("session", "run")
    assert record is not None
    assert record.stop_reason == "faiss.search:Timeout"
