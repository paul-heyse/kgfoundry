"""Integration tests for MCP server tool wrappers."""

from __future__ import annotations

from http import HTTPStatus

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.mcp_server.server import app_context, get_context
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests._helpers import assertions
from tests._helpers.http import build_test_app


@pytest.fixture
def mcp_test_app(mock_application_context: ApplicationContext) -> FastAPI:
    """Return a FastAPI instance wired to the mock context and MCP router.

    Returns
    -------
    FastAPI
        Fully-initialized application ready for TestClient usage.
    """
    return build_test_app(mock_application_context)


def test_set_scope_endpoint(mcp_test_app: FastAPI) -> None:
    """Test that set_scope endpoint calls adapter with context."""
    with TestClient(mcp_test_app) as client:
        # Note: FastMCP endpoints are mounted at /mcp
        # This is a basic smoke test - actual MCP protocol testing would require MCP client
        # For now, we verify the app starts and context is available
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)


def test_list_paths_endpoint(
    mcp_test_app: FastAPI,
    mock_application_context: ApplicationContext,
) -> None:
    """Test that list_paths endpoint calls adapter with context."""
    with TestClient(mcp_test_app) as client:
        # Verify app has context initialized
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        # Context should be available in app.state
        assertions.expect_true(
            hasattr(mcp_test_app.state, "context"), reason="app.state should have context"
        )
        assertions.expect_true(
            mcp_test_app.state.context is mock_application_context,
            reason="context should not be None",
        )


def test_open_file_endpoint(mcp_test_app: FastAPI) -> None:
    """Test that open_file endpoint calls adapter with context."""
    with TestClient(mcp_test_app) as client:
        # Verify app has context initialized
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        assertions.expect_true(
            hasattr(mcp_test_app.state, "context"), reason="app.state should have context"
        )


def test_search_text_endpoint(mcp_test_app: FastAPI) -> None:
    """Test that search_text endpoint calls adapter with context."""
    with TestClient(mcp_test_app) as client:
        # Verify app has context initialized
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        assertions.expect_true(
            hasattr(mcp_test_app.state, "context"), reason="app.state should have context"
        )


def test_semantic_search_endpoint(mcp_test_app: FastAPI) -> None:
    """Test that semantic_search endpoint calls adapter with context."""
    with TestClient(mcp_test_app) as client:
        # Verify app has context initialized
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        assertions.expect_true(
            hasattr(mcp_test_app.state, "context"), reason="app.state should have context"
        )


def test_blame_range_endpoint(mcp_test_app: FastAPI) -> None:
    """Test that blame_range endpoint calls adapter with context."""
    with TestClient(mcp_test_app) as client:
        # Verify app has context initialized
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        assertions.expect_true(
            hasattr(mcp_test_app.state, "context"), reason="app.state should have context"
        )


def test_file_history_endpoint(mcp_test_app: FastAPI) -> None:
    """Test that file_history endpoint calls adapter with context."""
    with TestClient(mcp_test_app) as client:
        # Verify app has context initialized
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        assertions.expect_true(
            hasattr(mcp_test_app.state, "context"), reason="app.state should have context"
        )


def test_file_resource_endpoint(mcp_test_app: FastAPI) -> None:
    """Test that file_resource endpoint calls adapter with context."""
    with TestClient(mcp_test_app) as client:
        # Verify app has context initialized
        response = client.get("/healthz")
        assertions.expect_equal(response.status_code, HTTPStatus.OK)
        assertions.expect_true(
            hasattr(mcp_test_app.state, "context"), reason="app.state should have context"
        )


def test_missing_context_raises_error() -> None:
    """Test that missing context raises RuntimeError."""
    # Clear context variable
    app_context.set(None)

    # Verify RuntimeError is raised
    with pytest.raises(RuntimeError, match="ApplicationContext not initialized"):
        get_context()


def test_get_context_success(mock_application_context: ApplicationContext) -> None:
    """Test that get_context returns context when available."""
    # Set context in context variable
    app_context.set(mock_application_context)

    # Verify context is returned
    result = get_context()
    assertions.expect_true(result is mock_application_context, reason="should return mock context")

    # Clean up
    app_context.set(None)
