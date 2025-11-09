"""Unit tests for the text search adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from codeintel_rev.mcp_server.adapters import text_search

from kgfoundry_common.errors import VectorSearchError
from kgfoundry_common.subprocess_utils import SubprocessError

RG_FAILURE_CODE = 2
EXPECTED_SUBPROCESS_INVOCATIONS = 2


def _expect(*, condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message)


def _build_match_line(path: Path) -> str:
    return json.dumps(
        {
            "type": "match",
            "data": {
                "path": {"text": str(path)},
                "line_number": 1,
                "lines": {"text": "example"},
                "submatches": [{"start": 0, "end": 1}],
            },
        }
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_search_text_flag_prefixed_query(
    mock_application_context, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Queries beginning with a dash should be passed after the `--` sentinel."""
    captured_commands: list[list[str]] = []
    repo_root = mock_application_context.paths.repo_root
    target_path = repo_root / "pyproject.toml"

    def fake_run_subprocess(
        cmd: list[str], *, timeout: int | None = None, cwd: Path | None = None
    ) -> str:
        captured_commands.append(list(cmd))
        _ = timeout, cwd
        return _build_match_line(target_path)

    monkeypatch.setattr(text_search, "run_subprocess", fake_run_subprocess)

    result = await text_search.search_text(
        mock_application_context,
        "-def",
        regex=False,
        case_sensitive=False,
        paths=["pyproject.toml"],
        max_results=1,
    )

    _expect(condition=bool(captured_commands), message="Expected ripgrep to be invoked")
    arguments = captured_commands[0]
    sentinel_index = arguments.index("--")
    _expect(
        condition=arguments[sentinel_index + 1] == "-def",
        message="Query should appear immediately after the sentinel",
    )
    _expect(condition=result["matches"], message="Expected at least one match")
    _expect(
        condition=result["matches"][0]["path"].endswith("pyproject.toml"),
        message="Match path should end with the queried file",
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_search_text_surfaces_ripgrep_failure(
    mock_application_context, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Return-code > 1 from ripgrep should surface an error message."""

    def fake_run_subprocess(
        cmd: list[str], *, timeout: int | None = None, cwd: Path | None = None
    ) -> str:
        _ = cmd, timeout, cwd
        error_message = "rg failed"
        raise SubprocessError(error_message, returncode=RG_FAILURE_CODE, stderr=error_message)

    monkeypatch.setattr(text_search, "run_subprocess", fake_run_subprocess)

    with pytest.raises(VectorSearchError) as excinfo:
        await text_search.search_text(mock_application_context, "pattern")

    error = str(excinfo.value)
    _expect(condition="rg failed" in error, message="Expected error message to surface")


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_search_text_falls_back_to_grep(
    mock_application_context, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing ripgrep binary should trigger the grep fallback."""
    captured_commands: list[list[str]] = []

    def fake_run_subprocess(
        cmd: list[str], *, timeout: int | None = None, cwd: Path | None = None
    ) -> str:
        _ = timeout, cwd
        captured_commands.append(list(cmd))
        if cmd[0] == "rg":
            error_message = "rg missing"
            raise SubprocessError(error_message, returncode=127, stderr=error_message)
        repo_root = mock_application_context.paths.repo_root
        return f"{repo_root}/README.md:1:example"

    monkeypatch.setattr(text_search, "run_subprocess", fake_run_subprocess)

    result = await text_search.search_text(mock_application_context, "example", max_results=1)

    _expect(
        condition=len(captured_commands) == EXPECTED_SUBPROCESS_INVOCATIONS,
        message="Expected two subprocess invocations",
    )
    _expect(
        condition=captured_commands[1][0] == "grep",
        message="Fallback should invoke grep",
    )
    _expect(condition=result["matches"], message="Fallback grep should produce matches")


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_search_text_fallback_normalizes_relative_paths(
    mock_application_context, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Relative grep results should be normalized to repo-relative paths."""

    def fake_run_subprocess(
        cmd: list[str], *, timeout: int | None = None, cwd: Path | None = None
    ) -> str:
        _ = timeout, cwd
        if cmd[0] == "rg":
            error_message = "rg missing"
            raise SubprocessError(error_message, returncode=127, stderr=error_message)
        return "\n".join(
            [
                "README.md:1:example",
                "./README.md:2:example",
            ]
        )

    monkeypatch.setattr(text_search, "run_subprocess", fake_run_subprocess)

    result = await text_search.search_text(mock_application_context, "example", max_results=5)

    expected_match_count = 2
    _expect(
        condition=len(result["matches"]) == expected_match_count,
        message="Expected two normalized matches",
    )
    _expect(
        condition={match["line"] for match in result["matches"]} == {1, 2},
        message="Expected both relative paths to be preserved",
    )
    _expect(
        condition=all(match["path"] == "README.md" for match in result["matches"]),
        message="Expected normalized repo-relative paths",
    )
