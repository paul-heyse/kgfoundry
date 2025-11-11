from __future__ import annotations

from codeintel_rev.app.routers import index_admin
from codeintel_rev.runtime.factory_adjustment import DefaultFactoryAdjuster
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.app._context_factory import build_application_context


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
