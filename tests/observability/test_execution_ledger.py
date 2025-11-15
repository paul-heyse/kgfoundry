from __future__ import annotations

import pytest
from codeintel_rev.observability import execution_ledger


def test_build_run_report_includes_stage_and_envelope() -> None:
    run_id = "ledger-test-success"
    execution_ledger.begin_run(
        tool="mcp.tool:semantic",
        session_id="s",
        run_id=run_id,
        request={"limit": 5},
    )
    with execution_ledger.step(stage="embed", op="demo.embed", component="tests"):
        pass
    execution_ledger.record(
        "demo.envelope",
        stage="envelope",
        component="tests",
        results=2,
        channels=["semantic", "bm25"],
    )
    execution_ledger.end_run(status="ok")

    payload = execution_ledger.build_run_report(run_id)

    assert payload.get("run_id") == run_id
    assert payload.get("status") == "ok"
    stages = payload.get("stages_reached") or []
    assert stages
    assert stages[-1] == "envelope"
    envelope = payload.get("envelope") or {}
    assert envelope.get("results") == 2
    markdown = execution_ledger.report_to_markdown(payload)
    assert "Run `ledger-test-success`" in markdown
    assert "demo.embed" in markdown


def test_build_run_report_raises_for_missing_run() -> None:
    with pytest.raises(KeyError) as excinfo:
        execution_ledger.build_run_report("missing")
    assert "missing" in str(excinfo.value)
