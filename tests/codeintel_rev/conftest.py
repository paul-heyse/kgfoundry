"""Shared pytest fixtures for codeintel_rev tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("FAISS_OPT_LEVEL", "generic")

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.middleware import session_id_var

from tests._helpers.integration import IntegrationHarness, integration_harness_fixture


@pytest.fixture
def mock_session_id() -> Iterator[str]:
    """Provide a session ID bound to middleware context vars for adapter calls.

    Yields
    ------
    str
        Session ID string that is set in the middleware context variable.
        The context variable is reset after the test completes.
    """
    session_id = "test-session"
    token = session_id_var.set(session_id)
    try:
        yield session_id
    finally:
        session_id_var.reset(token)


@pytest.fixture(autouse=True)
def _auto_session_id() -> Iterator[None]:
    """Ensure a session ID is always present for tests that omit the fixture."""
    token = session_id_var.set("auto-session")
    try:
        yield
    finally:
        session_id_var.reset(token)


@pytest.fixture
def integration_harness(tmp_path: Path) -> Iterator[IntegrationHarness]:
    """Shared integration harness with real DuckDB and fakes for external services.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path provided by pytest fixture.

    Yields
    ------
    IntegrationHarness
        Integration test harness instance, automatically closed after test.
    """
    yield from integration_harness_fixture(tmp_path)


@pytest.fixture
def mock_application_context(integration_harness: IntegrationHarness) -> ApplicationContext:
    """Provide an ApplicationContext backed by the integration harness.

    Parameters
    ----------
    integration_harness : IntegrationHarness
        Integration harness fixture providing the context.

    Returns
    -------
    ApplicationContext
        Application context instance from the harness.
    """
    return integration_harness.context
