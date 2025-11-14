from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import cast

import httpx
import pytest
from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.main import (
    capz,
    disable_nginx_buffering,
    http_exception_handler_with_request_id,
    inject_request_id,
    readyz,
    sse_demo,
    unhandled_exception_handler,
)
from fastapi import FastAPI, HTTPException
from starlette.types import ExceptionHandler

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
    transport = httpx.ASGITransport(app=networking_test_app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            timeout=httpx.Timeout(5.0),
        ) as client:
            response = await client.get("/readyz")
            assert response.status_code == 200
            payload = response.json()
            assert payload["ready"] is True
            assert "faiss" in payload["checks"]
            assert payload["checks"]["faiss"]["healthy"] is True
    finally:
        await transport.aclose()


@pytest.mark.asyncio
async def test_capz_refreshes_capability_snapshot(
    networking_test_app: FastAPI,
) -> None:
    """Verify /capz refresh flag rehydrates the cached snapshot."""
    transport = httpx.ASGITransport(app=networking_test_app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
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
    finally:
        await transport.aclose()


@pytest.mark.asyncio
async def test_sse_stream_flushes_events(
    networking_test_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The /sse demo should stream events and keep buffering disabled."""
    monkeypatch.setenv("SSE_MAX_KEEPALIVES", "0")
    transport = httpx.ASGITransport(app=networking_test_app)
    try:
        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                timeout=httpx.Timeout(10.0),
            ) as client,
            client.stream("GET", "/sse") as response,
        ):
            assert response.status_code == 200
            assert response.headers.get("x-accel-buffering") == "no"
            lines: AsyncIterator[str] = response.aiter_lines()
            first_line = await anext(lines)
            second_line = await anext(lines)
            assert first_line == "event: ready"
            assert second_line.startswith("data:")
    finally:
        await transport.aclose()


@pytest.mark.asyncio
async def test_request_id_header_round_trip() -> None:
    """Middleware should generate request IDs and echo caller supplied ones."""
    app = FastAPI()
    app.middleware("http")(inject_request_id)

    @app.get("/ping")
    async def _ping() -> dict[str, str]:
        return {"status": "ok"}

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            timeout=httpx.Timeout(5.0),
        ) as client:
            generated = await client.get("/ping")
            generated_header = generated.headers.get("x-request-id")
            assert generated_header

            echoed = await client.get("/ping", headers={"X-Request-Id": "req-test"})
            assert echoed.headers.get("x-request-id") == "req-test"
    finally:
        await transport.aclose()


@pytest.mark.asyncio
async def test_exception_handler_includes_request_id() -> None:
    """Unhandled exceptions should be wrapped with a helpful envelope."""
    app = FastAPI()
    app.middleware("http")(inject_request_id)
    app.add_exception_handler(
        HTTPException,
        cast("ExceptionHandler", http_exception_handler_with_request_id),
    )
    app.add_exception_handler(
        Exception,
        cast("ExceptionHandler", unhandled_exception_handler),
    )

    @app.get("/boom")
    async def _boom() -> None:  # pragma: no cover - exercised in test
        message = "kapow"
        raise RuntimeError(message)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            timeout=httpx.Timeout(5.0),
        ) as client:
            response = await client.get("/boom")
            assert response.status_code == 500
            payload = response.json()
            assert payload["ok"] is False
            assert payload["error"]["type"] == "RuntimeError"
            assert payload["request_id"] == response.headers.get("x-request-id")
    finally:
        await transport.aclose()


@pytest.mark.asyncio
async def test_sse_emits_keepalive_comments(
    networking_test_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure the SSE demo keeps idle connections alive via comment frames."""
    monkeypatch.setenv("SSE_KEEPALIVE_SECONDS", "0.01")
    monkeypatch.setenv("SSE_MAX_KEEPALIVES", "2")
    transport = httpx.ASGITransport(app=networking_test_app)
    try:
        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                timeout=httpx.Timeout(10.0),
            ) as client,
            client.stream("GET", "/sse") as response,
        ):
            lines: AsyncIterator[str] = response.aiter_lines()
            keep_alive_seen = False
            for _ in range(30):
                next_line = await anext(lines)
                if next_line == ": keep-alive":
                    keep_alive_seen = True
                    break
            assert keep_alive_seen
    finally:
        await transport.aclose()
