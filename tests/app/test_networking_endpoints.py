from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.main import capz, disable_nginx_buffering, readyz, sse_demo
from fastapi import FastAPI

from tests.app._context_factory import build_application_context


class _FakeReadinessResult:
    """Lightweight readiness result used by HTTP tests."""

    def __init__(self, *, healthy: bool = True, detail: str = "ok") -> None:
        self.healthy = healthy
        self._detail = detail

    def as_payload(self) -> dict[str, object]:
        return {"healthy": self.healthy, "detail": self._detail}


class _FakeReadinessProbe:
    """Minimal readiness probe that mimics :class:`ReadinessProbe`."""

    async def refresh(self) -> dict[str, _FakeReadinessResult]:
        await asyncio.sleep(0)
        return {"faiss": _FakeReadinessResult()}


@pytest.fixture(name="networking_test_app")
def _networking_test_app(tmp_path, monkeypatch) -> FastAPI:
    """Return a FastAPI app exposing /readyz, /capz, and /sse for tests.

    Returns
    -------
    FastAPI
        Configured application containing the target routes.
    """
    ctx = build_application_context(tmp_path)
    app = FastAPI()
    app.state.context = ctx
    app.state.readiness = _FakeReadinessProbe()

    initial_caps = Capabilities(
        faiss_index=True,
        duckdb=True,
        scip_index=True,
        vllm_client=True,
    )
    app.state.capabilities = initial_caps
    app.state.capability_stamp = initial_caps.stamp()

    refreshed_caps = Capabilities(
        faiss_index=False,
        duckdb=False,
        scip_index=False,
        vllm_client=False,
        faiss_importable=False,
        duckdb_importable=False,
        torch_importable=False,
        onnxruntime_importable=False,
        versions_available=2,
        active_index_version="v2",
    )

    def _fake_from_context(
        _cls: type[Capabilities],
        _context: object,
    ) -> Capabilities:
        return refreshed_caps

    monkeypatch.setattr(
        Capabilities,
        "from_context",
        classmethod(_fake_from_context),
    )

    app.add_api_route("/readyz", readyz)
    app.add_api_route("/capz", capz)
    app.add_api_route("/sse", sse_demo)
    app.middleware("http")(disable_nginx_buffering)
    return app


@pytest.mark.asyncio
async def test_readyz_reports_all_checks(networking_test_app: FastAPI) -> None:
    """Ensure /readyz stays green and reports sub-check payloads."""
    async with httpx.AsyncClient(
        app=networking_test_app,
        base_url="http://testserver",
        timeout=httpx.Timeout(5.0),
    ) as client:
        response = await client.get("/readyz")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ready"] is True
        assert "faiss" in payload["checks"]
        assert payload["checks"]["faiss"]["healthy"] is True


@pytest.mark.asyncio
async def test_capz_refreshes_capability_snapshot(
    networking_test_app: FastAPI,
) -> None:
    """Verify /capz refresh flag rehydrates the cached snapshot."""
    async with httpx.AsyncClient(
        app=networking_test_app,
        base_url="http://testserver",
        timeout=httpx.Timeout(5.0),
    ) as client:
        baseline = await client.get("/capz")
        assert baseline.status_code == 200
        body = baseline.json()
        assert body["faiss_index_present"] is True
        stamp = body["stamp"]

        refreshed = await client.get("/capz", params={"refresh": "true"})
        assert refreshed.status_code == 200
        refreshed_body = refreshed.json()
        assert refreshed_body["faiss_index_present"] is False
        assert refreshed_body["active_index_version"] == "v2"
        assert refreshed_body["versions_available"] == 2
        assert refreshed_body["stamp"] != stamp


@pytest.mark.asyncio
async def test_sse_stream_flushes_events(networking_test_app: FastAPI) -> None:
    """The /sse demo should stream events and keep buffering disabled."""
    async with httpx.AsyncClient(
        app=networking_test_app,
        base_url="http://testserver",
        timeout=httpx.Timeout(10.0),
    ) as client, client.stream("GET", "/sse") as response:
        assert response.status_code == 200
        assert response.headers.get("x-accel-buffering") == "no"
        lines: AsyncIterator[str] = response.aiter_lines()
        first_line = await anext(lines)
        second_line = await anext(lines)
        assert first_line == "event: ready"
        assert second_line.startswith("data:")
