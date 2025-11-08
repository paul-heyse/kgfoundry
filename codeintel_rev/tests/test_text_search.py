"""Unit tests for the text search adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeintel_rev.mcp_server.adapters import text_search
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


def test_search_text_flag_prefixed_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """Queries beginning with a dash should be passed after the `--` sentinel."""
    captured_commands: list[list[str]] = []
    repo_root = Path.cwd()
    target_path = repo_root / "pyproject.toml"

    def fake_run_subprocess(
        cmd: list[str], *, timeout: int | None = None, cwd: Path | None = None
    ) -> str:
        captured_commands.append(list(cmd))
        _ = timeout, cwd
        return _build_match_line(target_path)

    monkeypatch.setattr(text_search, "run_subprocess", fake_run_subprocess)

    result = text_search.search_text(
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


def test_search_text_surfaces_ripgrep_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return-code > 1 from ripgrep should surface an error message."""

    def fake_run_subprocess(
        cmd: list[str], *, timeout: int | None = None, cwd: Path | None = None
    ) -> str:
        _ = cmd, timeout, cwd
        error_message = "rg failed"
        raise SubprocessError(error_message, returncode=RG_FAILURE_CODE, stderr=error_message)

    monkeypatch.setattr(text_search, "run_subprocess", fake_run_subprocess)

    result = text_search.search_text("pattern")

    _expect(condition=result["matches"] == [], message="Expected no matches on failure")
    _expect(condition=result["total"] == 0, message="Expected total to be zero on failure")
    _expect(
        condition=result.get("error") == "rg failed",
        message="Expected error message to surface",
    )
    _expect(condition="problem" in result, message="Expected Problem Details payload")


def test_search_text_falls_back_to_grep(monkeypatch: pytest.MonkeyPatch) -> None:
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
        repo_root = Path.cwd()
        return f"{repo_root}/README.md:1:example"

    monkeypatch.setattr(text_search, "run_subprocess", fake_run_subprocess)

    result = text_search.search_text("example", max_results=1)

    _expect(
        condition=len(captured_commands) == EXPECTED_SUBPROCESS_INVOCATIONS,
        message="Expected two subprocess invocations",
    )
    _expect(condition=captured_commands[1][0] == "grep", message="Fallback should invoke grep")
    _expect(condition=result["matches"], message="Fallback grep should produce matches")


def test_search_text_fallback_normalizes_relative_paths(
    monkeypatch: pytest.MonkeyPatch,
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

    result = text_search.search_text("example", max_results=5)

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
