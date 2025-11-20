"""Tests for diagnostics router endpoints."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path

import pytest
from codeintel_rev.app.routers import diagnostics
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests._helpers import assertions
from tests._helpers.http import build_test_app, build_test_context

_DISABLED_DETAIL = "Diagnostics endpoints disabled - observability removed"


@pytest.fixture
def diagnostics_app(tmp_path: Path) -> FastAPI:
    """Return a FastAPI app with the diagnostics router mounted.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory for test artifacts.

    Returns
    -------
    FastAPI
        Application containing the diagnostics router under `/diagnostics`.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    context = build_test_context(repo_root=repo_root)
    app = build_test_app(context)
    app.include_router(diagnostics.router)
    return app


def test_run_report_endpoint_returns_disabled_payload(diagnostics_app: FastAPI) -> None:
    """`/diagnostics/run_report/{run_id}` reports the disabled status via JSON."""
    with TestClient(diagnostics_app) as client:
        response = client.get("/diagnostics/run_report/run-123")
        assertions.expect_equal(response.status_code, HTTPStatus.NOT_IMPLEMENTED)
        payload = response.json()
        assertions.expect_equal(payload["available"], expected=False)
        assertions.expect_equal(payload["detail"], _DISABLED_DETAIL)


def test_run_report_markdown_endpoint_returns_plain_text(diagnostics_app: FastAPI) -> None:
    """`/diagnostics/run_report/{run_id}.md` returns plain text explaining the removal."""
    with TestClient(diagnostics_app) as client:
        response = client.get("/diagnostics/run_report/run-123.md")
        assertions.expect_equal(response.status_code, HTTPStatus.NOT_IMPLEMENTED)
        assertions.expect_equal(response.text, f"{_DISABLED_DETAIL}\n")
        assertions.expect_equal(response.headers["content-type"], "text/plain; charset=utf-8")
