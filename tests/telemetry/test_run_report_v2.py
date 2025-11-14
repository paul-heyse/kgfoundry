from __future__ import annotations

import sys
import types
from contextlib import contextmanager

if "codeintel_rev.runtime.cells" not in sys.modules:
    stub = types.ModuleType("codeintel_rev.runtime.cells")

    class _StubCell: ...

    class _StubObserver: ...

    class _StubInitContext: ...

    class _StubInitResult: ...

    class _StubCloseResult: ...

    stub.RuntimeCell = _StubCell
    stub.RuntimeCellObserver = _StubObserver
    stub.NullRuntimeCellObserver = _StubObserver
    stub.RuntimeCellInitContext = _StubInitContext
    stub.RuntimeCellInitResult = _StubInitResult
    stub.RuntimeCellCloseResult = _StubCloseResult
    sys.modules["codeintel_rev.runtime.cells"] = stub

from codeintel_rev.telemetry import reporter
from codeintel_rev.telemetry.context import telemetry_context
from codeintel_rev.telemetry.steps import StepEvent, emit_step


@contextmanager
def _temporary_run_store() -> None:
    original = reporter.RUN_REPORT_STORE
    reporter.RUN_REPORT_STORE = reporter.RunReportStore(retention=10)
    try:
        yield
    finally:
        reporter.RUN_REPORT_STORE = original


def test_run_report_v2_infers_stage_progression() -> None:
    """RunReportV2 should capture stage order and stop location."""
    with _temporary_run_store():
        reporter.start_run("session", "run", tool_name="search.semantic", capability_stamp=None)
        with telemetry_context(
            session_id="session",
            run_id="run",
            capability_stamp=None,
            tool_name="search.semantic",
        ):
            emit_step(StepEvent(kind="retrieval.gather_channels", status="completed"))
            emit_step(
                StepEvent(kind="retrieval.fuse", status="failed", detail="timeout waiting for FAISS")
            )
        reporter.finalize_run("session", "run", status="error")

        report = reporter.build_run_report_v2("session", "run")
        assert report is not None
        assert [stage.name for stage in report.stages[:2]] == ["gather", "fuse"]
        assert report.stages[0].status == "completed"
        assert report.stages[1].status == "failed"
        assert report.stopped_after_stage == "gather"
        assert report.warnings == ["timeout waiting for FAISS"]
