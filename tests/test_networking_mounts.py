"""Tests for networking mounts: readiness checks, capability refresh, and MCP sub-application mounting."""

from __future__ import annotations

from http import HTTPStatus

import httpx
import pytest
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

            faiss_index_path = networking_test_app.state.context.paths.faiss_index
            if faiss_index_path.exists():
                faiss_index_path.unlink()
            refreshed = await client.get("/capz", params={"refresh": "true"})
            assertions.expect_equal(refreshed.status_code, HTTPStatus.OK)
            refreshed_body = refreshed.json()
            assertions.expect_false(
                refreshed_body["faiss_index_present"],
                reason="refreshed should show faiss index absent",
            )
            assertions.expect_true(
                refreshed_body["stamp"] != stamp, reason="stamp should change after refresh"
            )
    finally:
        await transport.aclose()


def test_main_mounts_mcp_sub_application(networking_test_app: FastAPI) -> None:
    """The helper-provided app should mount the MCP ASGI sub-application under /mcp."""
    mounts = [route for route in networking_test_app.router.routes if isinstance(route, Mount)]
    assertions.expect_true(
        any(mount.path == "/mcp" for mount in mounts),
        reason="should mount MCP sub-application under /mcp",
    )
