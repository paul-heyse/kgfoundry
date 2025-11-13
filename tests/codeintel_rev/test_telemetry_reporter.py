from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from codeintel_rev.app import main as app_main
from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.mcp_server.telemetry import tool_operation_scope
from codeintel_rev.telemetry import reporter as reporter_module
from codeintel_rev.telemetry.context import telemetry_context, telemetry_metadata
from codeintel_rev.telemetry.reporter import (
    RunReportStore,
    build_report,
    emit_checkpoint,
    finalize_run,
    record_timeline_payload,
    render_markdown,
    report_to_json,
    start_run,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_report_store(monkeypatch: pytest.MonkeyPatch) -> RunReportStore:
    store = RunReportStore(retention=16)
    monkeypatch.setattr(reporter_module, "RUN_REPORT_STORE", store)
    return store


@pytest.fixture(autouse=True)
def stub_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reporter_module.Capabilities,
        "from_context",
        classmethod(lambda _cls, _context: Capabilities()),
    )


def _fake_app_context() -> ApplicationContext:
    """Return a typed stub ApplicationContext for telemetry tests.

    Returns
    -------
    ApplicationContext
        Placeholder context object used to satisfy type contracts in tests.
    """
    return cast("ApplicationContext", SimpleNamespace())


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> None:
    """Skip expensive startup for the global FastAPI app."""
    yield


def _ensure_mock_tool_route(app: FastAPI) -> None:
    """Register a lightweight tool route exactly once for integration tests."""
    if getattr(app.state, "_telemetry_mock_route_registered", False):
        return

    @app.post("/test-tools/mock")
    async def run_tool() -> dict[str, object]:
        with tool_operation_scope("tools.echo", payload_chars=4) as timeline:
            timeline.event("mock.stage", "echo", attrs={"state": "running"})
            telemetry = telemetry_metadata() or {}
            return {"ok": True, "telemetry": telemetry}

    app.state._telemetry_mock_route_registered = True


def _emit_minimal_events(session_id: str, run_id: str) -> None:
    base = {"session_id": session_id, "run_id": run_id, "status": "ok"}
    record_timeline_payload(
        {
            **base,
            "ts": 1.0,
            "type": "operation.start",
            "name": "mcp.tool.semantic_search",
            "attrs": {"tool": "semantic_search"},
        }
    )
    record_timeline_payload(
        {
            **base,
            "ts": 1.2,
            "type": "step.start",
            "name": "search.embed",
            "attrs": {"mode": "http", "n_texts": 1},
        }
    )
    record_timeline_payload(
        {
            **base,
            "ts": 1.3,
            "type": "step.end",
            "name": "search.embed",
            "attrs": {"duration_ms": 5},
        }
    )
    record_timeline_payload(
        {
            **base,
            "ts": 1.4,
            "type": "decision",
            "name": "hybrid.query_profile",
            "attrs": {"channels": ["semantic"]},
        }
    )
    record_timeline_payload(
        {
            **base,
            "ts": 1.5,
            "type": "hybrid.bm25.skip",
            "name": "bm25",
            "attrs": {"reason": "capability_off"},
        }
    )
    record_timeline_payload(
        {
            **base,
            "ts": 1.9,
            "type": "operation.end",
            "name": "mcp.tool.semantic_search",
            "attrs": {"duration_ms": 42},
        }
    )
    with telemetry_context(
        session_id=session_id,
        run_id=run_id,
        capability_stamp="demo",
        tool_name="semantic_search",
    ):
        emit_checkpoint("search.embed", ok=True)


def test_build_report_from_timeline_events() -> None:
    session_id = "sess-123"
    run_id = "run-abc"
    start_run(session_id, run_id, tool_name="semantic_search", capability_stamp="demo")
    _emit_minimal_events(session_id, run_id)
    finalize_run(session_id, run_id, status="complete")

    context = _fake_app_context()
    report = build_report(context, session_id)
    assert report is not None
    assert report.session_id == session_id
    assert report.run_id == run_id
    assert report.operations
    assert report.operations[0]["name"].startswith("mcp.tool")
    assert any(step["name"] == "search.embed" for step in report.steps)
    assert report.checkpoints
    assert report.checkpoints[0]["stage"] == "search.embed"
    assert report.decisions
    assert report.decisions[0]["name"] == "hybrid.query_profile"
    assert report.warnings or report.errors

    json_payload = report_to_json(report)
    assert json_payload["session_id"] == session_id
    markdown = render_markdown(report)
    assert session_id in markdown


@pytest.mark.asyncio
async def test_report_routes_return_payload() -> None:
    session_id = "sess-route"
    run_id = "run-route"
    start_run(session_id, run_id, tool_name="semantic_search", capability_stamp="demo")
    _emit_minimal_events(session_id, run_id)
    finalize_run(session_id, run_id, status="complete")

    original_context = getattr(app_main.app.state, "context", None)
    app_main.app.state.context = _fake_app_context()
    try:
        response = await app_main.get_run_report(session_id)
        assert response["session_id"] == session_id
        assert response["run_id"] == run_id

        markdown_response = await app_main.get_run_report_markdown(session_id)
        assert session_id in bytes(markdown_response.body).decode("utf-8")
    finally:
        app_main.app.state.context = original_context


def test_tool_execution_populates_run_report_via_http() -> None:
    """Simulate an MCP tool invocation end-to-end via the main FastAPI app."""
    app = app_main.app
    _ensure_mock_tool_route(app)
    original_context = getattr(app.state, "context", None)
    original_cap_stamp = getattr(app.state, "capability_stamp", None)
    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _noop_lifespan
    app.state.context = _fake_app_context()
    app.state.capability_stamp = "test-cap"

    client = TestClient(app, base_url="http://localhost")
    session_id = "sess-http"
    try:
        response = client.post("/test-tools/mock", headers={"X-Session-ID": session_id})
        assert response.status_code == 200
        body = response.json()
        assert body["telemetry"]["session_id"] == session_id

        report_response = client.get(f"/reports/{session_id}")
        assert report_response.status_code == 200
        report_body = report_response.json()
        assert report_body["session_id"] == session_id
        assert report_body["status"] == "complete"
        assert report_body["operations"]
        assert any(step["name"].startswith("mcp.tool") for step in report_body["operations"])
    finally:
        client.close()
        app.router.lifespan_context = original_lifespan
        app.state.context = original_context
        app.state.capability_stamp = original_cap_stamp
