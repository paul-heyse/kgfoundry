from __future__ import annotations

import sys
import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

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
