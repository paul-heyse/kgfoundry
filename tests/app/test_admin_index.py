"""Tests for admin index endpoints and runtime tuning functionality."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

from codeintel_rev.app.routers import index_admin
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.runtime.factory_adjustment import DefaultFactoryAdjuster
from fastapi.testclient import TestClient

from tests._helpers import assertions
from tests._helpers.http import build_test_app
from tests.app._context_factory import build_application_context

_REQUIRE_ADMIN_DEP = index_admin.__dict__["_require_admin"]


def test_admin_tuning_updates_context(tmp_path: Path) -> None:
    """Test that POST /admin/index/tuning updates the application context factory adjuster."""
    ctx = build_application_context(tmp_path)
    app = build_test_app(ctx)
    app.include_router(index_admin.router)
    app.dependency_overrides[_REQUIRE_ADMIN_DEP] = lambda: None
    with TestClient(app) as client:
        resp = client.post(
            "/admin/index/tuning",
            json={"faiss_nprobe": 64},
        )
        assertions.expect_equal(resp.status_code, HTTPStatus.OK)
        assertions.expect_true(
            isinstance(ctx.factory_adjuster, DefaultFactoryAdjuster),
            reason="should be DefaultFactoryAdjuster",
        )
        adjuster = cast("DefaultFactoryAdjuster", ctx.factory_adjuster)
        assertions.expect_equal(adjuster.faiss_nprobe, 64)


def test_admin_faiss_runtime_status_endpoint(tmp_path: Path) -> None:
    """Test that GET /admin/index/tuning/faiss returns current FAISS runtime tuning status."""
    ctx = build_application_context(tmp_path)
    manager = MagicMock()
    manager.runtime = MagicMock()
    manager.runtime.get_runtime_tuning.return_value = {"active": {"nprobe": 32}}
    manager.vec_dim = ctx.app_config.index.vec_dim

    ctx.seed_runtime_cells_for_tests(coderank_faiss=cast("FAISSManager", manager))
    app = build_test_app(ctx)
    app.include_router(index_admin.router)
    app.dependency_overrides[_REQUIRE_ADMIN_DEP] = lambda: None
    with TestClient(app) as client:
        resp = client.get("/admin/index/tuning/faiss")
        assertions.expect_equal(resp.status_code, HTTPStatus.OK)
        assertions.expect_equal(resp.json()["active"]["nprobe"], 32)


def test_admin_faiss_runtime_session_override(tmp_path: Path) -> None:
    """Test that POST /admin/index/tuning/faiss updates session-specific FAISS tuning."""
    ctx = build_application_context(tmp_path)
    app = build_test_app(ctx)
    app.include_router(index_admin.router)
    app.dependency_overrides[_REQUIRE_ADMIN_DEP] = lambda: None
    with TestClient(app) as client:
        resp = client.post(
            "/admin/index/tuning/faiss",
            json={"session_id": "abc", "nprobe": 48},
        )
        assertions.expect_equal(resp.status_code, HTTPStatus.OK)
        assertions.expect_equal(resp.json()["faiss_tuning"]["nprobe"], 48)
        stored = asyncio.run(ctx.scope_store.get("abc"))
        assertions.expect_equal(stored["faiss_tuning"]["nprobe"], 48)


def test_admin_faiss_runtime_reset_session(tmp_path: Path) -> None:
    """Test that DELETE /admin/index/tuning/faiss removes session-specific FAISS tuning."""
    ctx = build_application_context(tmp_path)
    asyncio.run(ctx.scope_store.set("abc", {"faiss_tuning": {"nprobe": 64}, "languages": ["python"]}))
    app = build_test_app(ctx)
    app.include_router(index_admin.router)
    app.dependency_overrides[_REQUIRE_ADMIN_DEP] = lambda: None
    with TestClient(app) as client:
        resp = client.delete("/admin/index/tuning/faiss", params={"session_id": "abc"})
        assertions.expect_equal(resp.status_code, HTTPStatus.OK)
        assertions.expect_true(asyncio.run(ctx.scope_store.get("abc")) is None)
