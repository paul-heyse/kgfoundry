"""Tests for networking mounts: readiness checks, capability refresh, and MCP sub-application mounting."""

from __future__ import annotations

import asyncio
from http import HTTPStatus

import httpx
import pytest
from codeintel_rev.app import main as app_main
from codeintel_rev.app.capabilities import Capabilities
from fastapi import FastAPI
from starlette.routing import Mount

from tests._helpers import assertions


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
            assertions.expect_equal(response.status_code, HTTPStatus.OK)
            payload = response.json()
            assertions.expect_true(payload["ready"], reason="readyz should report ready")
            assertions.expect_in("faiss", payload["checks"])
            assertions.expect_true(
                payload["checks"]["faiss"]["healthy"], reason="faiss check should be healthy"
            )
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
            assertions.expect_equal(baseline.status_code, HTTPStatus.OK)
            body = baseline.json()
            assertions.expect_true(
                body["faiss_index_present"], reason="baseline should show faiss index present"
            )
            stamp = body["stamp"]

            refreshed = await client.get("/capz", params={"refresh": "true"})
            assertions.expect_equal(refreshed.status_code, HTTPStatus.OK)
            refreshed_body = refreshed.json()
            assertions.expect_false(
                refreshed_body["faiss_index_present"],
                reason="refreshed should show faiss index absent",
            )
            assertions.expect_equal(refreshed_body["versions_available"], 2)
            assertions.expect_true(
                refreshed_body["stamp"] != stamp, reason="stamp should change after refresh"
            )
    finally:
        await transport.aclose()


@pytest.mark.asyncio
async def test_main_mounts_mcp_sub_application(monkeypatch: pytest.MonkeyPatch) -> None:
    """The production app mounts the MCP ASGI sub-application under /mcp."""

    class _ReadyProbe:
        @staticmethod
        async def refresh() -> dict[str, object]:
            """Stub refresh method.

            Returns
            -------
            dict[str, object]
                Empty dict.
            """
            return {}

    async def _fake_initialize(
        app: FastAPI, *, runtime_observer: object | None = None
    ) -> tuple[object, object]:
        _ = runtime_observer
        context = object()
        readiness = _ReadyProbe()
        app.state.context = context
        app.state.readiness = readiness
        await asyncio.sleep(0)
        return context, readiness

    async def _fake_shutdown(_context: object | None, _readiness: object | None) -> None:
        await asyncio.sleep(0)

    def _fake_caps(_cls: type[Capabilities], _context: object) -> Capabilities:
        return Capabilities(faiss_index=True)

    def _fake_build_http_app(_caps: Capabilities) -> FastAPI:
        sub = FastAPI()

        @sub.get("/health")
        async def _health() -> dict[str, str]:
            return {"status": "ok"}

        return sub

    monkeypatch.setattr(app_main, "_initialize_context", _fake_initialize)
    monkeypatch.setattr(app_main, "_shutdown_context", _fake_shutdown)
    monkeypatch.setattr(Capabilities, "from_context", classmethod(_fake_caps))
    monkeypatch.setattr(app_main, "build_http_app", _fake_build_http_app)

    async with app_main.app.router.lifespan_context(app_main.app):
        mounts = [route for route in app_main.app.router.routes if isinstance(route, Mount)]
        assertions.expect_true(
            any(mount.path == "/mcp" for mount in mounts),
            reason="should mount MCP sub-application under /mcp",
        )
