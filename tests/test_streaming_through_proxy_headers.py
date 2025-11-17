"""Tests for streaming through proxy headers: SSE event flushing and buffering control."""

from __future__ import annotations

from http import HTTPStatus

import httpx
import pytest
from fastapi import FastAPI

from tests._helpers import assertions


@pytest.mark.asyncio
async def test_sse_stream_flushes_events(  # streaming must survive proxies
    networking_test_app: FastAPI,
) -> None:
    """Test that SSE stream flushes events and sets proxy buffering headers correctly."""
    networking_test_app.state.server_settings.sse_max_keepalives = 0
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
            assertions.expect_equal(response.status_code, HTTPStatus.OK)
            assertions.expect_equal(response.headers.get("x-accel-buffering"), "no")
            lines = response.aiter_lines()
            first_line = await anext(lines)
            second_line = await anext(lines)
            assertions.expect_equal(first_line, "event: ready")
            assertions.expect_true(
                second_line.startswith("data:"), reason="second line should start with data:"
            )
    finally:
        await transport.aclose()
