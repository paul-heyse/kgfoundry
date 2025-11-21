"""Git adapter integration contracts using in-memory async client."""

from __future__ import annotations

import pytest
from codeintel_rev.mcp_server.adapters import history as history_adapter

from tests._helpers import assertions
from tests._helpers.integration import IntegrationHarness

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_blame_range_returns_payload(integration_harness: IntegrationHarness) -> None:
    """Blame adapter returns expected keys from the async git client stub."""
    repo_root = integration_harness.repo_root
    repo_root.joinpath("README.md").write_text("sample\ncontent\n", encoding="utf-8")
    context = integration_harness.context

    blame = await history_adapter.blame_range(context, "README.md", 1, 5)
    entries = blame.get("blame", [])
    assertions.expect_true(entries)
    first = entries[0]
    for key in ("line", "commit", "author", "date", "message"):
        assertions.expect_in(key, first)


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_file_history_returns_commits(integration_harness: IntegrationHarness) -> None:
    """History adapter returns commit listing from the async git client stub."""
    repo_root = integration_harness.repo_root
    repo_root.joinpath("module.py").write_text("def fn():\n    return 1\n", encoding="utf-8")
    context = integration_harness.context

    history = await history_adapter.file_history(context, "module.py", limit=5)
    commits = history.get("commits", [])
    assertions.expect_true(commits)
    first = commits[0]
    for key in ("sha", "full_sha", "author", "email", "date", "message"):
        assertions.expect_in(key, first)
