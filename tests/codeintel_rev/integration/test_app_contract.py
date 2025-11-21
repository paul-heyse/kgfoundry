"""Application surface contract: health and readiness endpoints."""

from __future__ import annotations

from http import HTTPStatus
from typing import cast

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests._helpers import assertions
from tests._helpers.integration import IntegrationHarness

pytestmark = pytest.mark.integration


def test_health_and_ready_endpoints(
    integration_app: tuple[TestClient, IntegrationHarness],
) -> None:
    """Health and readiness endpoints respond with expected payloads."""
    client, harness = integration_app
    context = harness.context

    health_response = client.get("/healthz")
    assertions.expect_equal(health_response.status_code, HTTPStatus.OK)
    assertions.expect_equal(health_response.json(), {"status": "ok"})

    ready_response = client.get("/readyz")
    assertions.expect_equal(ready_response.status_code, HTTPStatus.OK)
    ready_payload = ready_response.json()
    assertions.expect_true(ready_payload.get("ready") is True)
    checks = ready_payload.get("checks", {})
    assertions.expect_true(checks.get("repo_root", {}).get("healthy") is True)
    assertions.expect_true(checks.get("data_dir", {}).get("healthy") is True)

    app_state = cast("FastAPI", client.app)
    assertions.expect_true(hasattr(app_state.state, "context"))
    stored_context = cast("ApplicationContext", app_state.state.context)
    assertions.expect_equal(stored_context.paths.repo_root, context.paths.repo_root)
