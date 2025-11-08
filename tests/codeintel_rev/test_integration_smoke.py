"""High-level integration checks for the MCP server adapters."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import json
import pytest

from codeintel_rev.mcp_server.adapters import files as files_adapter
from codeintel_rev.mcp_server.adapters import history as history_adapter
from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
from codeintel_rev.mcp_server.adapters import text_search as text_search_adapter
from codeintel_rev.mcp_server.schemas import ScopeIn
from codeintel_rev.mcp_server.server import asgi_app, mcp


def _expect(*, condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message)


def test_mcp_server_import() -> None:
    """Ensure the MCP server entry points are initialised."""
    _expect(condition=mcp is not None, message="Expected MCP instance to be initialised")
    _expect(condition=asgi_app is not None, message="Expected ASGI application to be initialised")


@pytest.mark.asyncio
async def test_file_operations(mock_application_context, mock_session_id) -> None:
    """Verify file listing and reading adapters respond with expected keys."""
    repo_root = mock_application_context.paths.repo_root
    (repo_root / "README.md").write_text("example content", encoding="utf-8")

    listing = await files_adapter.list_paths(mock_application_context, max_results=5)
    _expect(condition="items" in listing, message="Expected 'items' key in list_paths result")
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
async def test_text_search(
    mock_application_context, mock_session_id, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the text search adapter for basic responses."""
    repo_root = mock_application_context.paths.repo_root
    (repo_root / "module.py").write_text("def sample():\n    return 1\n", encoding="utf-8")

    def _fake_run_subprocess(cmd: list[str], *, cwd: Path | None, timeout: int) -> str:
        """Simulate ripgrep JSON output for deterministic tests."""
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
    _expect(condition="matches" in result, message="Expected 'matches' key in search results")
    _expect(
        condition=isinstance(result.get("matches"), list),
        message="Text search matches should be a list",
    )


@pytest.mark.asyncio
async def test_semantic_search_no_index(mock_application_context, mock_session_id) -> None:
    """Semantic search should gracefully handle missing FAISS index."""
    envelope = await semantic_adapter.semantic_search(
        mock_application_context,
        "integration smoke test",
        limit=5,
    )
    _expect(condition="answer" in envelope, message="Expected answer in semantic search envelope")
    findings = envelope.get("findings")
    _expect(condition=isinstance(findings, list), message="Findings should be returned as a list")
    _expect(condition="problem" in envelope, message="Expected Problem Details on failure")


@pytest.mark.asyncio
async def test_git_history(mock_application_context, mock_session_id) -> None:
    """Ensure git history adapters expose expected keys."""
    repo_root = mock_application_context.paths.repo_root
    (repo_root / "README.md").write_text("sample\ncontent\n", encoding="utf-8")
    mock_application_context.async_git_client.blame_range.return_value = [
        {"line": 1, "commit": "abc", "author": "Test", "date": "2024-01-01", "message": "Line"}
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
    _expect(condition="commits" in history, message="Expected commits in file_history result")
    _expect(
        condition=isinstance(history.get("commits"), list),
        message="Commit history should be a list",
    )


def test_parse_blame_porcelain_multiple_entries() -> None:
    """The blame parser should return an entry for each porcelain header."""
    porcelain_lines = [
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 1 1 1",
        "author Alice Example",
        "author-mail <alice@example.com>",
        "author-time 1700000000",
        "author-tz +0000",
        "summary First change",
        "filename sample.py",
        "\tprint('first line')",
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 2 2 1",
        "author Bob Example",
        "author-mail <bob@example.com>",
        "author-time 1700000060",
        "author-tz +0000",
        "summary Second change",
        "filename sample.py",
        "\tprint('second line')",
    ]

    entries = history_adapter._parse_blame_porcelain("\n".join(porcelain_lines) + "\n")  # noqa: SLF001

    expected_entry_count = 2
    _expect(
        condition=len(entries) == expected_entry_count,
        message="Expected two blame entries to be parsed",
    )
    _expect(
        condition=[entry["line"] for entry in entries] == [1, 2],
        message="Expected blame entries to retain distinct line numbers",
    )
    _expect(
        condition={entry["message"] for entry in entries} == {"First change", "Second change"},
        message="Expected commit summaries to be captured for each entry",
    )
    expected_unique_dates = 2
    _expect(
        condition=len({entry["date"] for entry in entries}) == expected_unique_dates,
        message="Expected unique ISO timestamps for each blame entry",
    )


@pytest.mark.asyncio
async def test_scope_operations(mock_application_context, mock_session_id) -> None:
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
    result = files_adapter.open_file(mock_application_context, "../etc/passwd")
    _expect(condition="error" in result, message="Expected error for escaped path")
    _expect(
        condition="escapes repository root" in result["error"],
        message="Error should mention repository escape",
    )


@pytest.mark.asyncio
async def test_path_escape_rejected_by_history_adapter(mock_application_context) -> None:
    """Git adapters should refuse to run commands on escaped paths."""
    blame = await history_adapter.blame_range(mock_application_context, "../etc/passwd", 1, 2)
    _expect(condition="error" in blame, message="Expected error for escaped path")
    _expect(
        condition="escapes repository root" in blame["error"],
        message="Error should mention repository escape",
    )
