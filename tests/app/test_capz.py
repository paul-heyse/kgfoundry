"""Tests for capabilities endpoint and snapshot generation."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from types import ModuleType

from codeintel_rev.app.capabilities import (
    Capabilities,
    override_capabilities,
    override_capability_imports,
)
from codeintel_rev.app.main import capz as capz_route
from fastapi.testclient import TestClient

from tests._helpers import assertions
from tests._helpers.http import build_test_app
from tests.app._context_factory import build_application_context


def _mock_module(name: str, **attrs: object) -> ModuleType:
    """Create a mock module with the given attributes.

    Returns
    -------
    ModuleType
        Module instance populated with the provided attributes.
    """
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _noop(*_: object, **__: object) -> None:
    """Provide a no-op callable for lazy import stubs."""


def test_capabilities_snapshot_reports_paths(tmp_path: Path) -> None:
    """Verify capabilities snapshot reports all expected paths and flags."""
    ctx = build_application_context(tmp_path)
    fake_modules = {
        "faiss": _mock_module("faiss", normalize_L2=_noop),
        "duckdb": _mock_module("duckdb"),
        "httpx": None,
        "torch": _mock_module("torch"),
    }

    with override_capability_imports(fake_modules):
        snapshot = Capabilities.from_context(ctx)
    assertions.expect_true(snapshot.faiss_index, reason="faiss_index should be True")
    assertions.expect_true(snapshot.duckdb, reason="duckdb should be True")
    assertions.expect_true(snapshot.scip_index, reason="scip_index should be True")
    assertions.expect_true(snapshot.vllm_client, reason="vllm_client should be True")
    assertions.expect_equal(actual=snapshot.faiss_importable, expected=True)
    assertions.expect_equal(actual=snapshot.httpx_importable, expected=False)
    payload = snapshot.model_dump()
    assertions.expect_equal(actual=payload["duckdb_catalog_present"], expected=True)
    assertions.expect_equal(payload["active_index_version"], None)
    assertions.expect_equal(payload["versions_available"], 0)


def test_capz_endpoint_refresh(tmp_path: Path) -> None:
    """Verify capz endpoint refreshes capabilities when requested."""
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

    def _fake_from_context(_context: object) -> Capabilities:
        """Return refreshed capabilities for testing.

        Parameters
        ----------
        _context : object
            Context object (ignored).

        Returns
        -------
        Capabilities
            Refreshed capabilities instance.
        """
        return refreshed

    app = build_test_app(ctx, capabilities_override=initial)
    app.add_api_route("/capz", capz_route)

    with override_capabilities(_fake_from_context), TestClient(app) as client:
        resp = client.get("/capz")
        assertions.expect_equal(resp.status_code, HTTPStatus.OK)
        body = resp.json()
        assertions.expect_equal(actual=body["faiss_index_present"], expected=True)
        assertions.expect_in("active_index_version", body)
        assertions.expect_in("stamp", body)

        refreshed_resp = client.get("/capz", params={"refresh": "true"})
        assertions.expect_equal(refreshed_resp.status_code, HTTPStatus.OK)
        body = refreshed_resp.json()
        assertions.expect_equal(body["faiss_index_present"], expected=False)
        assertions.expect_equal(body["active_index_version"], "v2")
        assertions.expect_equal(body["versions_available"], 2)
        assertions.expect_equal(body["hints"]["faiss"], "faiss-cpu")
        assertions.expect_equal(body["hints"]["duckdb"], "duckdb")
