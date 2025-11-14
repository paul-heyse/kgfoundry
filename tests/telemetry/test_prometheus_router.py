from __future__ import annotations

import sys
import types
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

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

from codeintel_rev.telemetry.prom import build_metrics_router


def test_metrics_router_returns_deprecation_message() -> None:
    """The legacy /metrics endpoint should advertise the OTel reader."""
    app = FastAPI()
    router = build_metrics_router()
    assert router is not None
    app.include_router(router)

    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 410
    assert "Prometheus reader" in response.text
