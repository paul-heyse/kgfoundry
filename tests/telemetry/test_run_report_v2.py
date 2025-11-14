from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

if "codeintel_rev.runtime.cells" not in sys.modules:
    stub = types.ModuleType("codeintel_rev.runtime.cells")

    class _StubCell: ...

    class _StubObserver: ...

    class _StubInitContext: ...

    class _StubInitResult: ...

    class _StubCloseResult: ...

    stub_typed: Any = stub
    stub_typed.RuntimeCell = _StubCell
    stub_typed.RuntimeCellObserver = _StubObserver
    stub_typed.NullRuntimeCellObserver = _StubObserver
    stub_typed.RuntimeCellInitContext = _StubInitContext
    stub_typed.RuntimeCellInitResult = _StubInitResult
    stub_typed.RuntimeCellCloseResult = _StubCloseResult
    sys.modules["codeintel_rev.runtime.cells"] = stub

from codeintel_rev.observability.semantic_conventions import Attrs
from codeintel_rev.telemetry import reporter
from codeintel_rev.telemetry.context import telemetry_context
from codeintel_rev.telemetry.steps import StepEvent, emit_step


@contextmanager
def _temporary_run_store() -> Iterator[None]:
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
                StepEvent(
                    kind="retrieval.fuse", status="failed", detail="timeout waiting for FAISS"
                )
            )
        reporter.finalize_run("session", "run", status="error")

        report = reporter.build_run_report_v2("session", "run")
        assert report is not None
        assert report.tool == "search.semantic"
        assert [stage.name for stage in report.stages[:2]] == ["gather", "fuse"]
        assert report.stages[0].status == "completed"
        assert report.stages[1].status == "failed"
        assert report.stopped_after_stage == "gather"
        assert report.warnings == ["timeout waiting for FAISS"]
        assert report.events
        assert report.events[0]["kind"] == "retrieval.gather_channels"
        assert report.span_attributes[Attrs.MCP_SESSION_ID] == "session"
