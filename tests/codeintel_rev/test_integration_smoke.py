"""High-level integration checks for the MCP server adapters."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.io.path_utils import PathOutsideRepositoryError
from codeintel_rev.mcp_server.adapters import files as files_adapter
from codeintel_rev.mcp_server.adapters import history as history_adapter
from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
from codeintel_rev.mcp_server.adapters import text_search as text_search_adapter
from codeintel_rev.mcp_server.schemas import ScopeIn
from codeintel_rev.mcp_server.server import build_http_app, mcp

from tests._helpers.integration import IntegrationHarness, integration_harness_fixture


def _expect(*, condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message)


def test_mcp_server_import() -> None:
    """Ensure the MCP server entry points are initialised."""
    _expect(condition=mcp is not None, message="Expected MCP instance to be initialised")
    caps = Capabilities()
    http_app = build_http_app(caps)
    _expect(condition=http_app is not None, message="Expected HTTP app factory to produce an app")


@pytest.fixture
def integration_harness(tmp_path: Path) -> Iterator[IntegrationHarness]:
    """Provide integration test harness with real DuckDB and fakes for external services.

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


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_file_operations(integration_harness: IntegrationHarness) -> None:
    """Verify file listing and reading adapters respond with expected keys."""
    context = integration_harness.context
    repo_root = context.paths.repo_root
    (repo_root / "README.md").write_text("example content", encoding="utf-8")

    listing = await files_adapter.list_paths(context, max_results=5)
    _expect(
        condition="items" in listing,
        message="Expected 'items' key in list_paths result",
    )
    _expect(
        condition=isinstance(listing.get("items"), list),
        message="Expected list_paths to return a list of items",
    )

    opened = files_adapter.open_file(context, "README.md")
    has_expected_key = {"content", "error"}.intersection(opened.keys())
    _expect(
        condition=bool(has_expected_key),
        message="Expected either 'content' or 'error' key in open_file result",
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_text_search(integration_harness: IntegrationHarness) -> None:
    """Exercise the text search adapter for basic responses."""
    context = integration_harness.context
    repo_root = context.paths.repo_root
    (repo_root / "module.py").write_text("def sample():\n    return 1\n", encoding="utf-8")

    def _fake_run_subprocess(
        cmd: list[str],
        *,
        cwd: Path | None,
        timeout: int,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Simulate ripgrep JSON output for deterministic tests.

        Parameters
        ----------
        cmd : list[str]
            Command arguments (unused in mock).
        cwd : Path | None
            Working directory for command execution.
        timeout : int
            Command timeout in seconds (unused in mock).
        env : Mapping[str, str] | None
            Environment variables provided to the subprocess helper (unused).

        Returns
        -------
        str
            Serialized JSON payload mimicking ripgrep output.
        """
        _ = (cmd, timeout, env)
        sample_path = (cwd or repo_root) / "module.py"
        payload = {
            "type": "match",
            "data": {
                "path": {"text": str(sample_path.resolve())},
                "lines": {"text": "def sample():\n"},
                "line_number": 1,
                "submatches": [{"start": 0}],
            },
        }
        return json.dumps(payload)

    result = await text_search_adapter.search_text(
        context,
        "def",
        max_results=3,
        runner=_fake_run_subprocess,
    )
    _expect(
        condition="matches" in result,
        message="Expected 'matches' key in search results",
    )
    _expect(
        condition=isinstance(result.get("matches"), list),
        message="Text search matches should be a list",
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_semantic_search_no_index(integration_harness: IntegrationHarness) -> None:
    """Semantic search should degrade gracefully when FAISS search fails."""
    context = integration_harness.context
    context.paths.faiss_index.unlink(missing_ok=True)
    result = await semantic_adapter.semantic_search(
        context,
        "integration smoke test",
        limit=5,
    )
    _expect(
        condition=not result.get("findings"),
        message="Expected search to return no hydrated findings when FAISS fails",
    )
    limits = result.get("limits", [])
    _expect(condition=isinstance(limits, list), message="Limits should be a list")


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_git_history(integration_harness: IntegrationHarness) -> None:
    """Ensure git history adapters expose expected keys."""
    context = integration_harness.context
    repo_root = context.paths.repo_root
    (repo_root / "README.md").write_text("sample\ncontent\n", encoding="utf-8")
    blame = await history_adapter.blame_range(context, "README.md", 1, 5)
    _expect(condition="blame" in blame, message="Expected blame data in blame_range result")
    _expect(
        condition=isinstance(blame.get("blame"), list),
        message="Blame data should be a list",
    )

    history = await history_adapter.file_history(context, "README.md", limit=5)
    _expect(
        condition="commits" in history,
        message="Expected commits in file_history result",
    )
    _expect(
        condition=isinstance(history.get("commits"), list),
        message="Commit history should be a list",
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_scope_operations(integration_harness: IntegrationHarness) -> None:
    """Verify scope configuration round-trips through the adapter."""
    scope_request: ScopeIn = {"repos": ["test"], "languages": ["python"]}
    context = integration_harness.context
    result = await files_adapter.set_scope(context, scope_request)
    _expect(condition=result.get("status") == "ok", message="Scope status should be 'ok'")
    effective_scope = result.get("effective_scope")
    _expect(
        condition=isinstance(effective_scope, Mapping),
        message="Effective scope should be a mapping",
    )


def test_path_escape_rejected_by_file_adapter(integration_harness: IntegrationHarness) -> None:
    """Adapters should reject attempts to escape the repository root."""
    context = integration_harness.context
    with pytest.raises(PathOutsideRepositoryError) as excinfo:
        files_adapter.open_file(context, "../etc/passwd")

    _expect(
        condition="escapes repository root" in str(excinfo.value),
        message="Error should mention repository escape",
    )


@pytest.mark.asyncio
async def test_path_escape_rejected_by_history_adapter(
    integration_harness: IntegrationHarness,
) -> None:
    """Git adapters should refuse to run commands on escaped paths."""
    with pytest.raises(PathOutsideRepositoryError) as excinfo:
        await history_adapter.blame_range(integration_harness.context, "../etc/passwd", 1, 2)

    _expect(
        condition="escapes repository root" in str(excinfo.value),
        message="Error should mention repository escape",
    )
