from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_sse_stream_flushes_events(  # streaming must survive proxies
    networking_test_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            lines = response.aiter_lines()
            first_line = await anext(lines)
            second_line = await anext(lines)
            assert first_line == "event: ready"
            assert second_line.startswith("data:")
    finally:
        await transport.aclose()
