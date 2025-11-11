from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from codeintel_rev.app import capabilities as capabilities_module
from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.main import capz as capz_route
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.app._context_factory import build_application_context


def _mock_module(**attrs: object) -> Any:
    namespace = SimpleNamespace()
    for key, value in attrs.items():
        setattr(namespace, key, value)
    return namespace


def _noop(*_: object, **__: object) -> None:
    """Provide a no-op callable for lazy import stubs."""


def test_capabilities_snapshot_reports_paths(tmp_path, monkeypatch) -> None:
    ctx = build_application_context(tmp_path)
    fake_modules = {
        "faiss": _mock_module(
            StandardGpuResources=object(),
            GpuClonerOptions=object(),
            index_cpu_to_gpu=_noop,
            get_num_gpus=lambda: 2,
        ),
        "duckdb": object(),
        "httpx": None,
        "torch": object(),
    }

    def fake_import_optional(name: str) -> Any:
        return fake_modules.get(name)

    monkeypatch.setattr(capabilities_module, "_import_optional", fake_import_optional)

    snapshot = Capabilities.from_context(ctx)
    assert snapshot.faiss_index
    assert snapshot.duckdb
    assert snapshot.scip_index
    assert snapshot.vllm_client
    assert snapshot.faiss_importable is True
    assert snapshot.httpx_importable is False
    assert snapshot.faiss_gpu_available is True
    payload = snapshot.model_dump()
    assert payload["duckdb_catalog_present"] is True
    assert payload["faiss_gpu_disabled_reason"] is None
    assert payload["active_index_version"] is None
    assert payload["versions_available"] == 0


def test_capz_endpoint_refresh(tmp_path, monkeypatch) -> None:
    ctx = build_application_context(tmp_path)
    initial = Capabilities(faiss_index=True, duckdb=True, scip_index=True, vllm_client=True)
    refreshed = Capabilities(
        faiss_index=False,
        duckdb=False,
        scip_index=False,
        vllm_client=False,
        faiss_importable=False,
        duckdb_importable=False,
        torch_importable=False,
        onnxruntime_importable=False,
        lucene_importable=False,
        active_index_version="v2",
        versions_available=2,
    )

    def _fake_from_context(_cls: type[Capabilities], _context: object) -> Capabilities:
        return refreshed

    monkeypatch.setattr(
        capabilities_module.Capabilities,
        "from_context",
        classmethod(_fake_from_context),
    )

    app = FastAPI()
    app.state.context = ctx
    app.state.capabilities = initial
    app.add_api_route("/capz", capz_route)

    with TestClient(app) as client:
        resp = client.get("/capz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["faiss_index_present"] is True
        assert "active_index_version" in body
        assert "stamp" in body

        refreshed_resp = client.get("/capz", params={"refresh": "true"})
        assert refreshed_resp.status_code == 200
        body = refreshed_resp.json()
        assert body["faiss_index_present"] is False
        assert body["active_index_version"] == "v2"
        assert body["versions_available"] == 2
        assert body["hints"]["faiss"] == "faiss-cpu or faiss-gpu"
        assert body["hints"]["duckdb"] == "duckdb"
