"""Unit tests for text search adapter scope handling."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from codeintel_rev.app.config_context import ResolvedPaths
from codeintel_rev.mcp_server.adapters.text_search import search_text
from codeintel_rev.mcp_server.schemas import ScopeIn

from kgfoundry_common.errors import VectorSearchError
from kgfoundry_common.subprocess_utils import SubprocessError, SubprocessTimeoutError


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

    paths = ResolvedPaths(
        repo_root=repo_root,
        data_dir=repo_root / "data",
        vectors_dir=repo_root / "data" / "vectors",
        faiss_index=repo_root / "data" / "faiss" / "code.ivfpq.faiss",
        duckdb_path=repo_root / "data" / "catalog.duckdb",
        scip_index=repo_root / "index.scip",
    )
    context.paths = paths

    return context


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


def _run_search(  # noqa: PLR0913
    context: Mock,
    query: str,
    *,
    regex: bool = False,
    case_sensitive: bool = False,
    paths: Sequence[str] | None = None,
    include_globs: Sequence[str] | None = None,
    exclude_globs: Sequence[str] | None = None,
    max_results: int = 50,
) -> dict:
    """Execute the async search_text helper synchronously for tests.

    Parameters
    ----------
    context : Mock
        Mock ApplicationContext instance.
    query : str
        Search query string.
    regex : bool, optional
        Treat query as regular expression. Defaults to ``False``.
    case_sensitive : bool, optional
        Perform case-sensitive search. Defaults to ``False``.
    paths : Sequence[str] | None, optional
        Specific file paths to search. Defaults to ``None``.
    include_globs : Sequence[str] | None, optional
        Glob patterns to include. Defaults to ``None``.
    exclude_globs : Sequence[str] | None, optional
        Glob patterns to exclude. Defaults to ``None``.
    max_results : int, optional
        Maximum number of results. Defaults to ``50``.

    Returns
    -------
    dict
        Search results emitted by ``search_text``.
    """
    return asyncio.run(
        search_text(
            context,
            query,
            regex=regex,
            case_sensitive=case_sensitive,
            paths=paths,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            max_results=max_results,
        )
    )


def test_search_text_uses_observe_duration(mock_context: Mock) -> None:
    """Adapters record metrics using the shared observe_duration helper."""
    scope: ScopeIn = {}
    observation = Mock()
    observation.mark_success = Mock()
    observation.mark_error = Mock()
    calls: list[tuple[str, str]] = []

    @contextmanager
    def fake_observe(
        operation: str, component: str, **_kwargs: object
    ) -> Iterator[Mock]:
        calls.append((operation, component))
        yield observation

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.get_session_id",
            return_value="session-observe",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.get_effective_scope",
            return_value=scope,
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.observe_duration",
            fake_observe,
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.run_subprocess",
            return_value="",
        ),
    ):
        result = _run_search(mock_context, "needle", max_results=5)

    assert result["matches"] == []
    assert result["total"] == 0
    assert calls == [("text_search", "codeintel_mcp")]
    observation.mark_success.assert_called_once()
    observation.mark_error.assert_not_called()


def test_search_text_scope_include_and_exclude(mock_context: Mock) -> None:
    """Scope include/exclude globs are forwarded as ripgrep ``--iglob`` options."""
    repo_root = mock_context.paths.repo_root
    scope: ScopeIn = {
        "include_globs": ["src/**/*.py"],
        "exclude_globs": ["src/**/tests/**"],
    }

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.get_session_id",
            return_value="session-123",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.get_effective_scope",
            return_value=scope,
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.run_subprocess"
        ) as mock_run,
    ):
        mock_run.return_value = _build_match(repo_root / "src" / "main.py")

        result = _run_search(mock_context, "main", max_results=5)

        cmd = mock_run.call_args.args[0]
        iglob_values = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--iglob"]
        assert "src/**/*.py" in iglob_values
        assert "!src/**/tests/**" in iglob_values
        sentinel_index = cmd.index("--")
        assert cmd[sentinel_index + 1] == "main"
        assert cmd[sentinel_index + 2 :] == ["."]
        assert result["matches"][0]["path"].endswith("src/main.py")


def test_search_text_explicit_paths_override_scope(mock_context: Mock) -> None:
    """Explicit paths suppress scope include globs while keeping excludes."""
    repo_root = mock_context.paths.repo_root
    scope: ScopeIn = {
        "include_globs": ["src/**"],
        "exclude_globs": ["**/*.pyc"],
    }

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.get_session_id",
            return_value="session-456",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.get_effective_scope",
            return_value=scope,
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.run_subprocess"
        ) as mock_run,
    ):
        mock_run.return_value = _build_match(repo_root / "tests" / "test_main.py")

        result = _run_search(mock_context, "test", paths=["tests/"], max_results=5)

        cmd = mock_run.call_args.args[0]
        iglob_values = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--iglob"]
        assert "src/**" not in iglob_values
        assert "!**/*.pyc" in iglob_values
        assert cmd[-1].startswith("tests")
        assert result["matches"][0]["path"].endswith("tests/test_main.py")


def test_search_text_explicit_globs_override_scope(mock_context: Mock) -> None:
    """Explicit include/exclude globs override scope-provided filters."""
    repo_root = mock_context.paths.repo_root
    scope: ScopeIn = {
        "include_globs": ["src/**"],
        "exclude_globs": ["**/*.pyc"],
    }

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.get_session_id",
            return_value="session-789",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.get_effective_scope",
            return_value=scope,
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.run_subprocess"
        ) as mock_run,
    ):
        mock_run.return_value = _build_match(
            repo_root / "tests" / "integration" / "case.py"
        )

        result = _run_search(
            mock_context,
            "case",
            include_globs=["tests/**/*.py"],
            exclude_globs=["tests/**/fixtures/**"],
            max_results=5,
        )

        cmd = mock_run.call_args.args[0]
        iglob_values = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--iglob"]
        assert "tests/**/*.py" in iglob_values
        assert "!tests/**/fixtures/**" in iglob_values
        assert "src/**" not in iglob_values
        assert "!**/*.pyc" not in iglob_values
        assert result["matches"][0]["path"].endswith("tests/integration/case.py")


# ==================== Error Handling Tests ====================


def test_search_text_timeout_error(mock_context: Mock) -> None:
    """Test search_text raises VectorSearchError on timeout."""
    scope: ScopeIn = {}

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.get_session_id",
            return_value="session-timeout",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.get_effective_scope",
            return_value=scope,
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.run_subprocess"
        ) as mock_run,
    ):
        mock_run.side_effect = SubprocessTimeoutError(
            "Search timeout", command=["rg"], timeout_seconds=30
        )

        with pytest.raises(VectorSearchError, match="Search timeout"):
            _run_search(mock_context, "query", max_results=5)


def test_search_text_subprocess_error(mock_context: Mock) -> None:
    """Test search_text raises VectorSearchError on subprocess error."""
    scope: ScopeIn = {}

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.get_session_id",
            return_value="session-error",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.get_effective_scope",
            return_value=scope,
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.run_subprocess"
        ) as mock_run,
    ):
        mock_run.side_effect = SubprocessError(
            "Command failed", returncode=2, stderr="Error message"
        )

        with pytest.raises(VectorSearchError, match="Error message"):
            _run_search(mock_context, "query", max_results=5)


def test_search_text_value_error(mock_context: Mock) -> None:
    """Test search_text raises VectorSearchError on ValueError."""
    scope: ScopeIn = {}

    with (
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.get_session_id",
            return_value="session-value-error",
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.get_effective_scope",
            return_value=scope,
        ),
        patch(
            "codeintel_rev.mcp_server.adapters.text_search.run_subprocess"
        ) as mock_run,
    ):
        mock_run.side_effect = ValueError("Invalid query")

        with pytest.raises(VectorSearchError, match="Invalid query"):
            _run_search(mock_context, "query", max_results=5)
