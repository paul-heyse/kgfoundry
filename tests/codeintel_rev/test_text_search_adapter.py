"""Unit tests for text search adapter scope handling."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from unittest.mock import Mock

import pytest
from codeintel_rev.config.paths import resolve_application_paths
from codeintel_rev.mcp_server.adapters.text_search import (
    SubprocessRunner,
    TextSearchOptions,
    search_text,
)
from codeintel_rev.mcp_server.schemas import ScopeIn

from kgfoundry_common.errors import VectorSearchError
from kgfoundry_common.subprocess_utils import SubprocessError, SubprocessTimeoutError
from tests._helpers import assertions, ml
from tests._helpers.settings import build_app_config_for_repo


class _DictScopeStore:
    """Minimal async scope store storing dictionaries in memory."""

    def __init__(self) -> None:
        self._data: dict[str, ScopeIn] = {}

    async def get(self, name: str) -> ScopeIn | None:
        return self._data.get(name)

    async def set(self, name: str, value: ScopeIn) -> bool:
        self._data[name] = value
        return True

    async def delete(self, name: str) -> int:
        return 1 if self._data.pop(name, None) is not None else 0


@pytest.fixture
def mock_context(tmp_path: Path) -> Mock:
    """Create a mock ApplicationContext for testing.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path provided by pytest fixture.

    Returns
    -------
    Mock
        Mock ApplicationContext object.
    """
    context = Mock()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # Create test files
    (repo_root / "src").mkdir()
    (repo_root / "src" / "main.py").write_text("def main()\n")
    (repo_root / "src" / "utils.py").write_text("def helper()\n")
    (repo_root / "tests").mkdir()
    (repo_root / "tests" / "test_main.py").write_text("def test_main()\n")

    app_config = build_app_config_for_repo(repo_root)
    context.app_config = app_config
    context.paths = resolve_application_paths(app_config)
    context.scope_store = _DictScopeStore()

    return context


@pytest.fixture
def text_search_session_factory(mock_context: Mock) -> Callable[[ScopeIn | None, str], ml.FakeTextSearchSession]:
    """Return a factory that seeds scopes and activates session IDs."""

    def _build(scope: ScopeIn | None, session_id: str) -> ml.FakeTextSearchSession:
        session = ml.FakeTextSearchSession(session_id=session_id)
        asyncio.run(session.set_scope(mock_context.scope_store, scope))
        return session

    return _build


def _build_match(path: Path) -> str:
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


def _run_search(
    context: Mock,
    options: TextSearchOptions,
    *,
    runner: SubprocessRunner,
) -> dict:
    """Execute :func:`search_text` synchronously for the provided options.

    Parameters
    ----------
    context : Mock
        Mock application context for search execution.
    options : TextSearchOptions
        Search configuration options (query, filters, etc.).

    runner : SubprocessRunner
        Subprocess runner used to simulate ripgrep/grep output.

    Returns
    -------
    dict
        Search result payload.
    """
    return asyncio.run(search_text(context, options.query, options=options, runner=runner))


def test_search_text_scope_include_and_exclude(
    mock_context: Mock, text_search_session_factory: Callable[[ScopeIn | None, str], ml.FakeTextSearchSession]
) -> None:
    """Scope include/exclude globs are forwarded as ripgrep ``--iglob`` options."""
    repo_root = mock_context.paths.repo_root
    scope: ScopeIn = {
        "include_globs": ["src/**/*.py"],
        "exclude_globs": ["src/**/tests/**"],
    }

    captured_commands: list[list[str]] = []

    def runner(
        cmd: list[str],
        *,
        cwd: Path | None,
        timeout: int,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Record command and return fake match for scope include/exclude test.

        Parameters
        ----------
        cmd : list[str]
            Command arguments to record.
        cwd : Path | None
            Working directory (unused).
        timeout : int
            Timeout value (unused).
        env : Mapping[str, str] | None, optional
            Environment variables (unused).

        Returns
        -------
        str
            JSON match line for src/main.py.
        """
        _ = cwd, timeout, env
        captured_commands.append(list(cmd))
        return _build_match(repo_root / "src" / "main.py")

    session = text_search_session_factory(scope, "session-123")
    with session.activate():
        options = TextSearchOptions(query="main", max_results=5)
        result = _run_search(mock_context, options, runner=runner)

        cmd = captured_commands[0]
        iglob_values = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--iglob"]
        assertions.expect_in("src/**/*.py", iglob_values)
        assertions.expect_in("!src/**/tests/**", iglob_values)
        sentinel_index = cmd.index("--")
        assertions.expect_equal(cmd[sentinel_index + 1], "main")
        assertions.expect_sequence_equal(cmd[sentinel_index + 2 :], ["."])
        assertions.expect_true(
            result["matches"][0]["path"].endswith("src/main.py"),
            reason="path should end with src/main.py",
        )


def test_search_text_explicit_paths_override_scope(
    mock_context: Mock, text_search_session_factory: Callable[[ScopeIn | None, str], ml.FakeTextSearchSession]
) -> None:
    """Explicit paths suppress scope include globs while keeping excludes."""
    repo_root = mock_context.paths.repo_root
    scope: ScopeIn = {
        "include_globs": ["src/**"],
        "exclude_globs": ["**/*.pyc"],
    }

    captured_commands: list[list[str]] = []

    def runner(
        cmd: list[str],
        *,
        cwd: Path | None,
        timeout: int,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Record command and return fake match for explicit paths test.

        Parameters
        ----------
        cmd : list[str]
            Command arguments to record.
        cwd : Path | None
            Working directory (unused).
        timeout : int
            Timeout value (unused).
        env : Mapping[str, str] | None, optional
            Environment variables (unused).

        Returns
        -------
        str
            JSON match line for tests/test_main.py.
        """
        _ = cwd, timeout, env
        captured_commands.append(list(cmd))
        return _build_match(repo_root / "tests" / "test_main.py")

    session = text_search_session_factory(scope, "session-456")
    with session.activate():
        options = TextSearchOptions(
            query="test",
            paths=["tests/"],
            max_results=5,
        )
        result = _run_search(mock_context, options, runner=runner)

        cmd = captured_commands[0]
        iglob_values = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--iglob"]
        assertions.expect_false(
            "src/**" in iglob_values, reason="scope include should be suppressed"
        )
        assertions.expect_in("!**/*.pyc", iglob_values)
        assertions.expect_true(
            cmd[-1].startswith("tests"), reason="last arg should start with tests"
        )
        assertions.expect_true(
            result["matches"][0]["path"].endswith("tests/test_main.py"),
            reason="path should end with tests/test_main.py",
        )


def test_search_text_explicit_globs_override_scope(
    mock_context: Mock, text_search_session_factory: Callable[[ScopeIn | None, str], ml.FakeTextSearchSession]
) -> None:
    """Explicit include/exclude globs override scope-provided filters."""
    repo_root = mock_context.paths.repo_root
    scope: ScopeIn = {
        "include_globs": ["src/**"],
        "exclude_globs": ["**/*.pyc"],
    }

    captured_commands: list[list[str]] = []

    def runner(
        cmd: list[str],
        *,
        cwd: Path | None,
        timeout: int,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Record command and return fake match for explicit globs test.

        Parameters
        ----------
        cmd : list[str]
            Command arguments to record.
        cwd : Path | None
            Working directory (unused).
        timeout : int
            Timeout value (unused).
        env : Mapping[str, str] | None, optional
            Environment variables (unused).

        Returns
        -------
        str
            JSON match line for tests/integration/case.py.
        """
        _ = cwd, timeout, env
        captured_commands.append(list(cmd))
        return _build_match(repo_root / "tests" / "integration" / "case.py")

    session = text_search_session_factory(scope, "session-789")
    with session.activate():
        options = TextSearchOptions(
            query="case",
            include_globs=["tests/**/*.py"],
            exclude_globs=["tests/**/fixtures/**"],
            max_results=5,
        )
        result = _run_search(mock_context, options, runner=runner)

        cmd = captured_commands[0]
        iglob_values = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--iglob"]
        assertions.expect_in("tests/**/*.py", iglob_values)
        assertions.expect_in("!tests/**/fixtures/**", iglob_values)
        assertions.expect_false(
            "src/**" in iglob_values, reason="scope include should be overridden"
        )
        assertions.expect_false(
            "!**/*.pyc" in iglob_values, reason="scope exclude should be overridden"
        )
        assertions.expect_true(
            result["matches"][0]["path"].endswith("tests/integration/case.py"),
            reason="path should end with tests/integration/case.py",
        )


# ==================== Error Handling Tests ====================


def test_search_text_timeout_error(
    mock_context: Mock, text_search_session_factory: Callable[[ScopeIn | None, str], ml.FakeTextSearchSession]
) -> None:
    """Test search_text raises VectorSearchError on timeout."""
    scope: ScopeIn = {}

    def runner(
        cmd: list[str],
        *,
        cwd: Path | None,
        timeout: int,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Raise SubprocessTimeoutError to test timeout handling.

        Parameters
        ----------
        cmd : list[str]
            Command arguments (unused).
        cwd : Path | None
            Working directory (unused).
        timeout : int
            Timeout value (unused).
        env : Mapping[str, str] | None, optional
            Environment variables (unused).

        Raises
        ------
        SubprocessTimeoutError
            Always raised with message "Search timeout" and 30 second timeout.
        """
        _ = cmd, cwd, timeout, env
        message = "Search timeout"
        raise SubprocessTimeoutError(message, command=["rg"], timeout_seconds=30)

    session = text_search_session_factory(scope, "session-timeout")
    with session.activate():
        options = TextSearchOptions(query="query", max_results=5)
        with pytest.raises(VectorSearchError, match="Search timeout"):
            _run_search(mock_context, options, runner=runner)


def test_search_text_subprocess_error(
    mock_context: Mock, text_search_session_factory: Callable[[ScopeIn | None, str], ml.FakeTextSearchSession]
) -> None:
    """Test search_text raises VectorSearchError on subprocess error."""
    scope: ScopeIn = {}

    def runner(
        cmd: list[str],
        *,
        cwd: Path | None,
        timeout: int,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Raise SubprocessError to test subprocess error handling.

        Parameters
        ----------
        cmd : list[str]
            Command arguments (unused).
        cwd : Path | None
            Working directory (unused).
        timeout : int
            Timeout value (unused).
        env : Mapping[str, str] | None, optional
            Environment variables (unused).

        Raises
        ------
        SubprocessError
            Always raised with returncode 2 and stderr "Error message".
        """
        _ = cmd, cwd, timeout, env
        message = "Command failed"
        raise SubprocessError(message, returncode=2, stderr="Error message")

    session = text_search_session_factory(scope, "session-error")
    with session.activate():
        options = TextSearchOptions(query="query", max_results=5)
        with pytest.raises(VectorSearchError, match="Error message"):
            _run_search(mock_context, options, runner=runner)


def test_search_text_value_error(
    mock_context: Mock, text_search_session_factory: Callable[[ScopeIn | None, str], ml.FakeTextSearchSession]
) -> None:
    """Test search_text raises VectorSearchError on ValueError."""
    scope: ScopeIn = {}

    def runner(
        cmd: list[str],
        *,
        cwd: Path | None,
        timeout: int,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Raise ValueError to test value error handling.

        Parameters
        ----------
        cmd : list[str]
            Command arguments (unused).
        cwd : Path | None
            Working directory (unused).
        timeout : int
            Timeout value (unused).
        env : Mapping[str, str] | None, optional
            Environment variables (unused).

        Raises
        ------
        ValueError
            Always raised with message "Invalid query".
        """
        _ = cmd, cwd, timeout, env
        message = "Invalid query"
        raise ValueError(message)

    session = text_search_session_factory(scope, "session-value-error")
    with session.activate():
        options = TextSearchOptions(query="query", max_results=5)
        with pytest.raises(VectorSearchError, match="Invalid query"):
            _run_search(mock_context, options, runner=runner)
