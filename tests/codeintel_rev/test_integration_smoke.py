"""High-level integration checks for the MCP server adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from codeintel_rev.io.path_utils import PathOutsideRepositoryError
from codeintel_rev.mcp_server.adapters import files as files_adapter
from codeintel_rev.mcp_server.adapters import history as history_adapter
from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
from codeintel_rev.mcp_server.adapters import text_search as text_search_adapter
from codeintel_rev.mcp_server.schemas import ScopeIn
from codeintel_rev.mcp_server.server import asgi_app, mcp

from kgfoundry_common.errors import VectorSearchError


def _expect(*, condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message)


def test_mcp_server_import() -> None:
    """Ensure the MCP server entry points are initialised."""
    _expect(condition=mcp is not None, message="Expected MCP instance to be initialised")
    _expect(
        condition=asgi_app is not None,
        message="Expected ASGI application to be initialised",
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_file_operations(mock_application_context) -> None:
    """Verify file listing and reading adapters respond with expected keys."""
    repo_root = mock_application_context.paths.repo_root
    (repo_root / "README.md").write_text("example content", encoding="utf-8")

    listing = await files_adapter.list_paths(mock_application_context, max_results=5)
    _expect(
        condition="items" in listing,
        message="Expected 'items' key in list_paths result",
    )
    _expect(
        condition=isinstance(listing.get("items"), list),
        message="Expected list_paths to return a list of items",
    )

    opened = files_adapter.open_file(mock_application_context, "README.md")
    has_expected_key = {"content", "error"}.intersection(opened.keys())
    _expect(
        condition=bool(has_expected_key),
        message="Expected either 'content' or 'error' key in open_file result",
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_text_search(mock_application_context, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the text search adapter for basic responses."""
    repo_root = mock_application_context.paths.repo_root
    (repo_root / "module.py").write_text("def sample():\n    return 1\n", encoding="utf-8")

    def _fake_run_subprocess(cmd: list[str], *, cwd: Path | None, timeout: int) -> str:
        """Simulate ripgrep JSON output for deterministic tests.

        Returns
        -------
        str
            Serialized JSON payload mimicking ripgrep output.
        """
        _ = (cmd, timeout)
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

    monkeypatch.setattr(text_search_adapter, "run_subprocess", _fake_run_subprocess)

    result = await text_search_adapter.search_text(mock_application_context, "def", max_results=3)
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
async def test_semantic_search_no_index(mock_application_context) -> None:
    """Semantic search should gracefully handle missing FAISS index."""
    with pytest.raises(VectorSearchError):
        await semantic_adapter.semantic_search(
            mock_application_context,
            "integration smoke test",
            limit=5,
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_git_history(mock_application_context) -> None:
    """Ensure git history adapters expose expected keys."""
    repo_root = mock_application_context.paths.repo_root
    (repo_root / "README.md").write_text("sample\ncontent\n", encoding="utf-8")
    mock_application_context.async_git_client.blame_range.return_value = [
        {
            "line": 1,
            "commit": "abc",
            "author": "Test",
            "date": "2024-01-01",
            "message": "Line",
        }
    ]
    mock_application_context.async_git_client.file_history.return_value = [
        {
            "sha": "abc",
            "full_sha": "abcdef",
            "author": "Test",
            "email": "test@example.com",
            "date": "2024-01-01T00:00:00Z",
            "message": "Initial commit",
        }
    ]

    blame = await history_adapter.blame_range(mock_application_context, "README.md", 1, 5)
    _expect(condition="blame" in blame, message="Expected blame data in blame_range result")
    _expect(
        condition=isinstance(blame.get("blame"), list),
        message="Blame data should be a list",
    )

    history = await history_adapter.file_history(mock_application_context, "README.md", limit=5)
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
async def test_scope_operations(mock_application_context) -> None:
    """Verify scope configuration round-trips through the adapter."""
    scope_request: ScopeIn = {"repos": ["test"], "languages": ["python"]}
    result = await files_adapter.set_scope(mock_application_context, scope_request)
    _expect(condition=result.get("status") == "ok", message="Scope status should be 'ok'")
    effective_scope = result.get("effective_scope")
    _expect(
        condition=isinstance(effective_scope, Mapping),
        message="Effective scope should be a mapping",
    )


def test_path_escape_rejected_by_file_adapter(mock_application_context) -> None:
    """Adapters should reject attempts to escape the repository root."""
    with pytest.raises(PathOutsideRepositoryError) as excinfo:
        files_adapter.open_file(mock_application_context, "../etc/passwd")

    _expect(
        condition="escapes repository root" in str(excinfo.value),
        message="Error should mention repository escape",
    )


@pytest.mark.asyncio
async def test_path_escape_rejected_by_history_adapter(
    mock_application_context,
) -> None:
    """Git adapters should refuse to run commands on escaped paths."""
    with pytest.raises(PathOutsideRepositoryError) as excinfo:
        await history_adapter.blame_range(mock_application_context, "../etc/passwd", 1, 2)

    _expect(
        condition="escapes repository root" in str(excinfo.value),
        message="Error should mention repository escape",
    )
