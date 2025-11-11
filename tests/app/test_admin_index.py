from __future__ import annotations

from unittest.mock import MagicMock

from codeintel_rev.app.routers import index_admin
from codeintel_rev.runtime.factory_adjustment import DefaultFactoryAdjuster
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.app._context_factory import build_application_context


class _ScopeStoreStub:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    async def get(self, session_id: str) -> dict | None:  # pragma: no cover - exercised via router
        return self.data.get(session_id)

    async def set(self, session_id: str, scope: dict) -> None:
        self.data[session_id] = dict(scope)


def test_admin_tuning_updates_context(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CODEINTEL_ADMIN", "1")
    ctx = build_application_context(tmp_path)
    app = FastAPI()
    app.state.context = ctx
    app.include_router(index_admin.router)
    with TestClient(app) as client:
        resp = client.post(
            "/admin/index/tuning",
            json={"faiss_nprobe": 64},
        )
        assert resp.status_code == 200
        assert isinstance(ctx.factory_adjuster, DefaultFactoryAdjuster)
        assert ctx.factory_adjuster.faiss_nprobe == 64


def test_admin_faiss_runtime_status_endpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CODEINTEL_ADMIN", "1")
    ctx = build_application_context(tmp_path)
    manager = MagicMock()
    manager.get_runtime_tuning.return_value = {"active": {"nprobe": 32}}

    def _fake_get_manager(_self, _vec_dim, _manager=manager) -> MagicMock:
        return _manager

    monkeypatch.setattr(ctx.__class__, "get_coderank_faiss_manager", _fake_get_manager)
    app = FastAPI()
    app.state.context = ctx
    app.include_router(index_admin.router)
    with TestClient(app) as client:
        resp = client.get("/admin/index/tuning/faiss")
        assert resp.status_code == 200
        assert resp.json()["active"]["nprobe"] == 32


def test_admin_faiss_runtime_session_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CODEINTEL_ADMIN", "1")
    ctx = build_application_context(tmp_path)
    ctx.scope_store = _ScopeStoreStub()
    app = FastAPI()
    app.state.context = ctx
    app.include_router(index_admin.router)
    with TestClient(app) as client:
        resp = client.post(
            "/admin/index/tuning/faiss",
            json={"session_id": "abc", "nprobe": 48},
        )
        assert resp.status_code == 200
        assert resp.json()["faiss_tuning"]["nprobe"] == 48
        assert ctx.scope_store.data["abc"]["faiss_tuning"]["nprobe"] == 48


def test_admin_faiss_runtime_reset_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CODEINTEL_ADMIN", "1")
    ctx = build_application_context(tmp_path)
    stub = _ScopeStoreStub()
    stub.data["abc"] = {"faiss_tuning": {"nprobe": 64}, "languages": ["python"]}
    ctx.scope_store = stub
    app = FastAPI()
    app.state.context = ctx
    app.include_router(index_admin.router)
    with TestClient(app) as client:
        resp = client.delete("/admin/index/tuning/faiss", params={"session_id": "abc"})
        assert resp.status_code == 200
        assert "faiss_tuning" not in stub.data["abc"]
