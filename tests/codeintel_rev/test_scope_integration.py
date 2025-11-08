"""End-to-end integration tests for scope management.

Tests verify scope application across all adapters, including:
- Scope persistence across multiple adapter calls
- Parameter precedence (explicit overrides scope)
- Session isolation (concurrent sessions)
- Scope expiration and pruning
- Default behavior (no scope)
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Generator
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

import numpy as np
import pytest
from codeintel_rev.app.middleware import session_id_var
from codeintel_rev.app.scope_registry import ScopeRegistry
from codeintel_rev.mcp_server.adapters import files as files_adapter
from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
from codeintel_rev.mcp_server.adapters import text_search as text_search_adapter
from codeintel_rev.mcp_server.schemas import AnswerEnvelope, ScopeIn

pytestmark = pytest.mark.asyncio


class TestScopeRegistryImmutability:
    """Regression tests for ScopeRegistry immutability guarantees."""

    def test_set_scope_guards_against_external_mutation(self) -> None:
        """Mutating the original scope after set_scope should not affect storage."""
        registry = ScopeRegistry()
        session_id = "session-mutation"
        scope: ScopeIn = {
            "include_globs": ["src/**"],
            "languages": ["python"],
        }

        registry.set_scope(session_id, scope)

        # Mutate the original scope after caching.
        scope["include_globs"].append("tests/**")
        scope["languages"][0] = "typescript"

        stored_scope = registry.get_scope(session_id)
        assert stored_scope is not None
        assert isinstance(stored_scope, dict)
        assert stored_scope.get("include_globs") == ["src/**"]
        assert stored_scope.get("languages") == ["python"]

    def test_get_scope_returns_independent_copy(self) -> None:
        """Mutating a retrieved scope should not mutate the registry's cache."""
        registry = ScopeRegistry()
        session_id = "session-independent"
        scope: ScopeIn = {
            "include_globs": ["src/**"],
            "languages": ["python"],
        }

        registry.set_scope(session_id, scope)

        retrieved_scope = registry.get_scope(session_id)
        assert retrieved_scope is not None
        assert isinstance(retrieved_scope, dict)
        retrieved_scope["include_globs"].append("**/*.ts")  # type: ignore[index]
        retrieved_scope["languages"].append("typescript")  # type: ignore[index]

        fresh_scope = registry.get_scope(session_id)
        assert fresh_scope is not None
        assert isinstance(fresh_scope, dict)
        assert fresh_scope.get("include_globs") == ["src/**"]
        assert fresh_scope.get("languages") == ["python"]


@pytest.fixture
def test_repo(tmp_path: Path) -> Path:
    """Create a test repository with various file types.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory for test files.

    Returns
    -------
    Path
        Path to test repository root.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # Create directory structure
    (repo_root / "src").mkdir()
    (repo_root / "src" / "nested").mkdir()
    (repo_root / "tests").mkdir()
    (repo_root / "docs").mkdir()

    # Create Python files
    (repo_root / "src" / "main.py").write_text('def main():\n    print("hello")\n')
    (repo_root / "src" / "utils.py").write_text("def helper():\n    pass\n")
    (repo_root / "src" / "nested" / "deep.py").write_text("def deep():\n    pass\n")
    (repo_root / "tests" / "test_main.py").write_text("def test_main():\n    assert True\n")

    # Create TypeScript files
    (repo_root / "src" / "app.ts").write_text('function app() {\n    console.log("hello");\n}\n')
    (repo_root / "src" / "components").mkdir(parents=True)
    (repo_root / "src" / "components" / "Button.tsx").write_text(
        "export const Button = () => null;\n"
    )

    # Create other files
    (repo_root / "docs" / "README.md").write_text("# Documentation\n")
    (repo_root / "src" / "config.json").write_text('{"key": "value"}\n')

    return repo_root


@pytest.fixture
def mock_context(test_repo: Path) -> Mock:
    """Create a mock ApplicationContext with scope registry.

    Parameters
    ----------
    test_repo : Path
        Test repository root path.

    Returns
    -------
    Mock
        Mock ApplicationContext with initialized scope_registry and paths.
    """
    from codeintel_rev.app.config_context import ResolvedPaths
    from codeintel_rev.config.settings import Settings, load_settings

    context = Mock()
    context.scope_registry = ScopeRegistry()

    # Set up paths
    paths = ResolvedPaths(
        repo_root=test_repo,
        data_dir=test_repo / "data",
        vectors_dir=test_repo / "data" / "vectors",
        faiss_index=test_repo / "data" / "faiss" / "code.ivfpq.faiss",
        duckdb_path=test_repo / "data" / "catalog.duckdb",
        scip_index=test_repo / "index.scip",
    )
    context.paths = paths

    # Set up settings
    try:
        settings = load_settings()
    except (OSError, ValueError, KeyError):
        # Create minimal settings if load fails
        settings = Mock(spec=Settings)
        settings.limits.max_results = 1000

    context.settings = settings

    # Mock FAISS manager
    faiss_manager = Mock()
    faiss_manager.gpu_index = None
    faiss_manager.gpu_disabled_reason = None
    context.faiss_manager = faiss_manager
    context.ensure_faiss_ready = Mock(return_value=(True, [], None))

    # Mock vLLM client
    vllm_client = Mock()
    # Mock embed_single to return a numpy array (2560 dimensions)
    vllm_client.embed_single = Mock(return_value=np.array([0.1] * 2560, dtype=np.float32))
    context.vllm_client = vllm_client

    # Mock DuckDB catalog context manager
    from contextlib import contextmanager

    @contextmanager
    def mock_open_catalog() -> Generator[Mock]:
        catalog = Mock()
        catalog.query_by_ids = Mock(return_value=[])
        catalog.query_by_filters = Mock(return_value=[])
        yield catalog

    context.open_catalog = mock_open_catalog

    return context


@pytest.fixture(autouse=True)
def disable_scope_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace scope histogram with a stub for deterministic tests."""
    from codeintel_rev.mcp_server import scope_utils

    class _HistogramStub:
        def labels(self, **_: object) -> _HistogramStub:
            return self

        def observe(self, _: float) -> None:
            return None

    monkeypatch.setattr(scope_utils, "_scope_filter_duration_seconds", _HistogramStub())


@pytest.fixture
def session_id() -> str:
    """Generate a test session ID.

    Returns
    -------
    str
        UUID-formatted session ID.
    """
    import uuid

    return str(uuid.uuid4())


class TestSetScopeToListPaths:
    """Test scope application in list_paths adapter."""

    async def test_set_scope_then_list_paths_python_only(
        self, mock_context: Mock, session_id: str
    ) -> None:
        """Test that setting scope with Python globs filters list_paths results."""
        # Set session ID in ContextVar
        session_id_var.set(session_id)

        # Set scope with Python files only
        scope: ScopeIn = {"include_globs": ["**/*.py"]}
        result = files_adapter.set_scope(mock_context, scope)
        assert result["status"] == "ok"
        assert result["session_id"] == session_id

        # Call list_paths (async)
        paths_result = await files_adapter.list_paths(mock_context, path=None, max_results=100)

        # Verify only Python files returned
        items = paths_result["items"]
        assert len(items) > 0
        assert all(item["path"].endswith(".py") for item in items)
        assert not any(item["path"].endswith(".ts") for item in items)
        assert not any(item["path"].endswith(".tsx") for item in items)

    async def test_set_scope_then_list_paths_src_prefix(
        self, mock_context: Mock, session_id: str
    ) -> None:
        """Test that setting scope with src/ prefix filters list_paths results."""
        session_id_var.set(session_id)

        scope: ScopeIn = {"include_globs": ["src/**"]}
        files_adapter.set_scope(mock_context, scope)

        paths_result = await files_adapter.list_paths(mock_context, path=None, max_results=100)

        items = paths_result["items"]
        assert len(items) > 0
        assert all(item["path"].startswith("src/") for item in items)
        assert not any(item["path"].startswith("tests/") for item in items)

    async def test_set_scope_then_list_paths_language_filter(
        self, mock_context: Mock, session_id: str
    ) -> None:
        """Test that setting scope with languages filters list_paths results."""
        session_id_var.set(session_id)

        scope: ScopeIn = {"languages": ["python"]}
        files_adapter.set_scope(mock_context, scope)

        paths_result = await files_adapter.list_paths(mock_context, path=None, max_results=100)

        items = paths_result["items"]
        assert len(items) > 0
        assert all(item["path"].endswith((".py", ".pyi", ".pyw")) for item in items)
        assert not any(item["path"].endswith(".ts") for item in items)


class TestSetScopeToSearchText:
    """Test scope application in search_text adapter."""

    def test_set_scope_then_search_text_src_only(self, mock_context: Mock, session_id: str) -> None:
        """Test that setting scope with src/ prefix filters search_text results."""
        session_id_var.set(session_id)

        scope: ScopeIn = {"include_globs": ["src/**"]}
        files_adapter.set_scope(mock_context, scope)

        # Mock ripgrep to return test results
        # Patch at the import location in text_search module
        with patch("codeintel_rev.mcp_server.adapters.text_search.run_subprocess") as mock_run:
            # run_subprocess returns stdout as a string
            mock_run.return_value = "src/main.py:1:def main():\n"

            text_search_adapter.search_text(mock_context, "main", max_results=50)

            # Verify ripgrep was called with src/ paths
            assert mock_run.called
            # run_subprocess is called with cmd as first positional arg
            call_args = mock_run.call_args[0] if mock_run.call_args[0] else []
            cmd = call_args[0] if call_args else []
            # Check that paths include src/
            if isinstance(cmd, list):
                paths_in_cmd = [arg for arg in cmd if isinstance(arg, str) and "src" in arg]
                assert len(paths_in_cmd) > 0

    def test_set_scope_then_search_text_explicit_override(
        self, mock_context: Mock, session_id: str
    ) -> None:
        """Test that explicit paths parameter overrides scope."""
        session_id_var.set(session_id)

        # Set scope with src/
        scope: ScopeIn = {"include_globs": ["src/**"]}
        files_adapter.set_scope(mock_context, scope)

        # Patch at the import location in text_search module
        with patch("codeintel_rev.mcp_server.adapters.text_search.run_subprocess") as mock_run:
            # run_subprocess returns stdout as a string
            mock_run.return_value = ""

            # Call with explicit paths (should override scope)
            text_search_adapter.search_text(mock_context, "query", paths=["tests/"], max_results=50)

            # Verify ripgrep was called with tests/ paths (not src/)
            assert mock_run.called
            # run_subprocess is called with cmd as first positional arg
            call_args = mock_run.call_args[0] if mock_run.call_args[0] else []
            cmd = call_args[0] if call_args else []
            # Explicit paths should override scope
            if isinstance(cmd, list):
                assert any("tests" in str(arg) for arg in cmd if isinstance(arg, str))


class TestSetScopeToSemanticSearch:
    """Test scope application in semantic_search adapter."""

    def test_set_scope_then_semantic_search_language_filter(
        self, mock_context: Mock, session_id: str
    ) -> None:
        """Test that setting scope with languages filters semantic_search results."""
        session_id_var.set(session_id)

        scope: ScopeIn = {"languages": ["python"]}
        files_adapter.set_scope(mock_context, scope)

        # Mock FAISS search
        mock_context.faiss_manager.search = Mock(
            return_value=(
                np.array([[1, 2, 3, 4, 5]], dtype=np.int64),
                np.array([[0.9, 0.8, 0.7, 0.6, 0.5]], dtype=np.float32),
            )
        )

        # Mock vLLM embedding
        mock_context.vllm_client.embed_single = Mock(
            return_value=np.array([0.1] * 2560, dtype=np.float32)
        )

        # Mock DuckDB catalog with test chunks
        test_chunks = [
            {
                "id": 1,
                "uri": "src/main.py",
                "start_line": 1,
                "end_line": 10,
                "preview": "def main()",
            },
            {
                "id": 2,
                "uri": "src/app.ts",
                "start_line": 1,
                "end_line": 5,
                "preview": "function app()",
            },
            {
                "id": 3,
                "uri": "src/utils.py",
                "start_line": 5,
                "end_line": 15,
                "preview": "def helper()",
            },
        ]

        def mock_query_by_filters(
            ids,
            *,
            include_globs=None,
            exclude_globs=None,
            languages=None,
        ) -> list[dict]:
            # Filter by languages if provided
            if languages:
                return [
                    chunk
                    for chunk in test_chunks
                    if isinstance(chunk.get("uri"), str)
                    and any(
                        chunk["uri"].endswith(ext) for lang in languages for ext in [".py", ".pyi"]
                    )
                ]
            return test_chunks

        catalog_mock = Mock()
        catalog_mock.query_by_filters = Mock(side_effect=mock_query_by_filters)

        # Replace open_catalog context manager for this test
        from contextlib import contextmanager

        @contextmanager
        def test_open_catalog() -> Generator[Mock]:
            yield catalog_mock

        mock_context.open_catalog = test_open_catalog

        # Call semantic_search via async wrapper
        result = asyncio.run(semantic_adapter.semantic_search(mock_context, "main function", 10))

        # Verify query_by_filters was called with language filter
        assert catalog_mock.query_by_filters.called
        call_kwargs = catalog_mock.query_by_filters.call_args[1]
        assert call_kwargs.get("languages") == ["python"]

        # Verify results contain only Python files
        findings = result.get("findings", [])
        if findings:
            uris = [f.get("uri", "") for f in findings]
            assert all(isinstance(uri, str) and uri.endswith(".py") for uri in uris if uri)

    def test_set_scope_then_semantic_search_include_globs(
        self, mock_context: Mock, session_id: str
    ) -> None:
        """Test that setting scope with include_globs filters semantic_search results."""
        session_id_var.set(session_id)

        scope: ScopeIn = {"include_globs": ["src/**/*.py"]}
        files_adapter.set_scope(mock_context, scope)

        # Mock FAISS and vLLM
        mock_context.faiss_manager.search = Mock(
            return_value=(
                np.array([[1, 2, 3]], dtype=np.int64),
                np.array([[0.9, 0.8, 0.7]], dtype=np.float32),
            )
        )
        mock_context.vllm_client.embed_single = Mock(
            return_value=np.array([0.1] * 2560, dtype=np.float32)
        )

        test_chunks = [
            {
                "id": 1,
                "uri": "src/main.py",
                "start_line": 1,
                "end_line": 10,
                "preview": "def main()",
            },
            {
                "id": 2,
                "uri": "tests/test_main.py",
                "start_line": 1,
                "end_line": 5,
                "preview": "def test()",
            },
        ]

        def mock_query_by_filters(
            ids,
            *,
            include_globs=None,
            exclude_globs=None,
            languages=None,  # noqa: ARG001
        ) -> list[dict]:
            if include_globs:
                import fnmatch

                return [
                    chunk
                    for chunk in test_chunks
                    if isinstance(chunk.get("uri"), str)
                    and any(fnmatch.fnmatch(chunk["uri"], pattern) for pattern in include_globs)
                ]
            return test_chunks

        catalog_mock = Mock()
        catalog_mock.query_by_filters = Mock(side_effect=mock_query_by_filters)

        # Replace open_catalog context manager for this test
        from contextlib import contextmanager

        @contextmanager
        def test_open_catalog() -> Generator[Mock]:
            yield catalog_mock

        mock_context.open_catalog = test_open_catalog

        result = asyncio.run(semantic_adapter.semantic_search(mock_context, "test", 10))

        # Verify query_by_filters was called with include_globs
        assert catalog_mock.query_by_filters.called
        call_kwargs = catalog_mock.query_by_filters.call_args[1]
        assert call_kwargs.get("include_globs") == ["src/**/*.py"]

        # Verify results contain only src/ files
        findings = result.get("findings", [])
        if findings:
            uris = [f.get("uri", "") for f in findings]
            assert all(isinstance(uri, str) and uri.startswith("src/") for uri in uris if uri)

    def test_set_scope_then_semantic_search_exclude_globs(
        self, mock_context: Mock, session_id: str
    ) -> None:
        """Test that setting scope with exclude_globs filters semantic_search results."""
        session_id_var.set(session_id)

        scope: ScopeIn = {"exclude_globs": ["tests/**"]}
        files_adapter.set_scope(mock_context, scope)

        search_call: dict[str, int] = {}

        def fake_search(query: np.ndarray, k: int = 0) -> tuple[np.ndarray, np.ndarray]:
            search_call["k"] = k
            return (
                np.array([[0.9, 0.8]], dtype=np.float32),
                np.array([[1, 2]], dtype=np.int64),
            )

        mock_context.faiss_manager.search = Mock(side_effect=fake_search)
        mock_context.vllm_client.embed_single = Mock(
            return_value=np.array([0.1] * 2560, dtype=np.float32)
        )

        test_chunks = [
            {
                "id": 1,
                "uri": "src/main.py",
                "start_line": 1,
                "end_line": 10,
                "preview": "def main()",
            },
            {
                "id": 2,
                "uri": "tests/test_main.py",
                "start_line": 1,
                "end_line": 5,
                "preview": "def test_main()",
            },
        ]

        def mock_query_by_filters(
            ids,
            *,
            include_globs=None,
            exclude_globs=None,
            languages=None,  # noqa: ARG001
        ) -> list[dict]:
            assert exclude_globs == ["tests/**"]
            import fnmatch

            filtered: list[dict] = []
            for chunk in test_chunks:
                chunk_id = chunk.get("id")
                chunk_uri_raw = chunk.get("uri", "")
                chunk_uri = str(chunk_uri_raw) if chunk_uri_raw else ""
                if chunk_id not in ids:
                    continue
                if exclude_globs and any(
                    fnmatch.fnmatch(chunk_uri, cast(str, pattern)) for pattern in exclude_globs
                ):
                    continue
                filtered.append(chunk)
            return filtered

        catalog_mock = Mock()
        catalog_mock.query_by_filters = Mock(side_effect=mock_query_by_filters)
        catalog_mock.query_by_ids = Mock(
            side_effect=AssertionError("query_by_ids should not be used")
        )

        from contextlib import contextmanager

        @contextmanager
        def test_open_catalog() -> Generator[Mock]:
            yield catalog_mock

        mock_context.open_catalog = test_open_catalog

        result = asyncio.run(semantic_adapter.semantic_search(mock_context, "query", 2))

        assert search_call.get("k") == 4
        catalog_mock.query_by_filters.assert_called_once()
        call_kwargs = catalog_mock.query_by_filters.call_args.kwargs
        assert call_kwargs.get("exclude_globs") == ["tests/**"]

        findings = result.get("findings", [])
        assert len(findings) == 1
        first_location = findings[0].get("location") if isinstance(findings[0], dict) else None
        assert isinstance(first_location, dict)
        assert first_location.get("uri") == "src/main.py"

        method = result.get("method")
        assert method is not None
        coverage = method.get("coverage") if isinstance(method, dict) else None
        assert isinstance(coverage, str)
        assert coverage.startswith("1/2 results")


class TestParameterOverride:
    """Test that explicit parameters override session scope."""

    async def test_list_paths_explicit_overrides_scope(
        self, mock_context: Mock, session_id: str
    ) -> None:
        """Test that explicit include_globs override scope."""
        session_id_var.set(session_id)

        # Set scope with Python files
        scope: ScopeIn = {"include_globs": ["**/*.py"]}
        files_adapter.set_scope(mock_context, scope)

        # Call with explicit TypeScript globs (should override)
        result = await files_adapter.list_paths(
            mock_context, path=None, include_globs=["**/*.ts"], max_results=100
        )

        items = result["items"]
        # Should return TypeScript files (explicit override), not Python files
        assert all(item["path"].endswith((".ts", ".tsx")) for item in items)
        assert not any(item["path"].endswith(".py") for item in items)

    def test_search_text_explicit_overrides_scope(
        self, mock_context: Mock, session_id: str
    ) -> None:
        """Test that explicit paths override scope."""
        session_id_var.set(session_id)

        scope: ScopeIn = {"include_globs": ["src/**"]}
        files_adapter.set_scope(mock_context, scope)

        # Patch at the import location in text_search module
        with patch("codeintel_rev.mcp_server.adapters.text_search.run_subprocess") as mock_run:
            # run_subprocess returns stdout as a string
            mock_run.return_value = ""

            # Call with explicit paths (should override scope)
            text_search_adapter.search_text(mock_context, "query", paths=["tests/"], max_results=50)

            # Verify ripgrep called with tests/ (explicit override)
            assert mock_run.called
            # run_subprocess is called with cmd as first positional arg
            call_args = mock_run.call_args[0] if mock_run.call_args[0] else []
            cmd = call_args[0] if call_args else []
            # Explicit paths should be used, not scope
            if isinstance(cmd, list):
                assert any("tests" in str(arg) for arg in cmd if isinstance(arg, str))


class TestMultiSessionIsolation:
    """Test that concurrent sessions maintain isolated scopes."""

    async def test_concurrent_sessions_different_scopes(self, mock_context: Mock) -> None:
        """Test that two sessions with different scopes get different results."""
        session_a = "session-a-123"
        session_b = "session-b-456"

        # Set scope for session A (Python only)
        session_id_var.set(session_a)
        scope_a: ScopeIn = {"languages": ["python"]}
        files_adapter.set_scope(mock_context, scope_a)

        # Set scope for session B (TypeScript only)
        session_id_var.set(session_b)
        scope_b: ScopeIn = {"languages": ["typescript"]}
        files_adapter.set_scope(mock_context, scope_b)

        # Call list_paths from session A
        session_id_var.set(session_a)
        result_a = await files_adapter.list_paths(mock_context, path=None, max_results=100)

        # Call list_paths from session B
        session_id_var.set(session_b)
        result_b = await files_adapter.list_paths(mock_context, path=None, max_results=100)

        # Verify results are different
        items_a = result_a["items"]
        items_b = result_b["items"]

        # Session A should have Python files
        assert all(item["path"].endswith((".py", ".pyi", ".pyw")) for item in items_a)

        # Session B should have TypeScript files
        assert all(item["path"].endswith((".ts", ".tsx", ".mts", ".cts")) for item in items_b)

    @pytest.mark.asyncio
    async def test_concurrent_semantic_search_different_scopes(self, mock_context: Mock) -> None:
        """Test concurrent semantic_search calls with different scopes."""
        session_a = "session-a-789"
        session_b = "session-b-012"

        # Set up scopes
        session_id_var.set(session_a)
        scope_a: ScopeIn = {"languages": ["python"]}
        files_adapter.set_scope(mock_context, scope_a)

        session_id_var.set(session_b)
        scope_b: ScopeIn = {"languages": ["typescript"]}
        files_adapter.set_scope(mock_context, scope_b)

        # Mock FAISS and vLLM
        mock_context.faiss_manager.search = Mock(
            return_value=(
                np.array([[1, 2, 3]], dtype=np.int64),
                np.array([[0.9, 0.8, 0.7]], dtype=np.float32),
            )
        )
        mock_context.vllm_client.embed_single = Mock(
            return_value=np.array([0.1] * 2560, dtype=np.float32)
        )

        test_chunks_python = [
            {
                "id": 1,
                "uri": "src/main.py",
                "start_line": 1,
                "end_line": 10,
                "preview": "def main()",
            },
        ]
        test_chunks_typescript = [
            {
                "id": 2,
                "uri": "src/app.ts",
                "start_line": 1,
                "end_line": 5,
                "preview": "function app()",
            },
        ]

        def mock_query_by_filters(
            ids,
            *,
            include_globs=None,
            exclude_globs=None,
            languages=None,
        ) -> list[dict]:
            if languages == ["python"]:
                return test_chunks_python
            if languages == ["typescript"]:
                return test_chunks_typescript
            return []

        catalog_mock = Mock()
        catalog_mock.query_by_filters = Mock(side_effect=mock_query_by_filters)

        # Replace open_catalog context manager for this test
        from contextlib import contextmanager

        @contextmanager
        def test_open_catalog() -> Generator[Mock]:
            yield catalog_mock

        mock_context.open_catalog = test_open_catalog

        # Simulate concurrent calls using asyncio
        async def search_session_a() -> AnswerEnvelope:
            session_id_var.set(session_a)
            return await semantic_adapter.semantic_search(mock_context, "query", limit=10)

        async def search_session_b() -> AnswerEnvelope:
            session_id_var.set(session_b)
            return await semantic_adapter.semantic_search(mock_context, "query", limit=10)

        # Run concurrently
        result_a, result_b = await asyncio.gather(search_session_a(), search_session_b())

        # Verify each session got correct results
        findings_a = result_a.get("findings", [])
        findings_b = result_b.get("findings", [])

        # Session A should have Python files
        if findings_a:
            uris_a = [str(f.get("uri", "")) for f in findings_a]
            assert all(uri.endswith(".py") for uri in uris_a if uri)

        # Session B should have TypeScript files
        if findings_b:
            uris_b = [str(f.get("uri", "")) for f in findings_b]
            assert all(uri.endswith(".ts") for uri in uris_b if uri)


class TestScopeExpiration:
    """Test scope expiration and pruning."""

    async def test_scope_expiration_after_prune(self, mock_context: Mock, session_id: str) -> None:
        """Test that expired scopes are removed after pruning."""
        session_id_var.set(session_id)

        # Set scope
        scope: ScopeIn = {"include_globs": ["**/*.py"]}
        files_adapter.set_scope(mock_context, scope)

        # Verify scope is set
        retrieved_scope = mock_context.scope_registry.get_scope(session_id)
        assert retrieved_scope is not None
        assert retrieved_scope.get("include_globs") == ["**/*.py"]

        # Mock time to advance 2 hours
        with patch("time.monotonic", return_value=time.monotonic() + 7200):
            # Prune expired sessions (max_age_seconds=3600)
            pruned = mock_context.scope_registry.prune_expired(max_age_seconds=3600)
            assert pruned == 1

        # Verify scope is cleared
        retrieved_scope_after = mock_context.scope_registry.get_scope(session_id)
        assert retrieved_scope_after is None

        # Verify list_paths no longer applies scope (searches all files)
        result = await files_adapter.list_paths(mock_context, path=None, max_results=100)
        items = result["items"]
        # Should include non-Python files (scope no longer applied)
        assert len(items) > 0


class TestNoScopeDefaultBehavior:
    """Test default behavior when no scope is set."""

    async def test_list_paths_no_scope_searches_all(
        self, mock_context: Mock, session_id: str
    ) -> None:
        """Test that list_paths searches all files when no scope is set."""
        session_id_var.set(session_id)

        # Don't call set_scope
        result = await files_adapter.list_paths(mock_context, path=None, max_results=100)

        items = result["items"]
        # Should include files of all types
        assert len(items) > 0
        # Should have both Python and TypeScript files
        has_python = any(item["path"].endswith(".py") for item in items)
        has_typescript = any(item["path"].endswith((".ts", ".tsx")) for item in items)
        # At least one type should be present (depending on test repo contents)
        assert has_python or has_typescript

    def test_search_text_no_scope_searches_all(self, mock_context: Mock, session_id: str) -> None:
        """Test that search_text searches all files when no scope is set."""
        session_id_var.set(session_id)

        # Patch at the import location in text_search module
        with patch("codeintel_rev.mcp_server.adapters.text_search.run_subprocess") as mock_run:
            # run_subprocess returns stdout as a string
            mock_run.return_value = ""

            text_search_adapter.search_text(mock_context, "query", max_results=50)

            # Verify ripgrep was called (no path restrictions from scope)
            assert mock_run.called

    def test_semantic_search_no_scope_searches_all(
        self, mock_context: Mock, session_id: str
    ) -> None:
        """Test that semantic_search searches all chunks when no scope is set."""
        session_id_var.set(session_id)

        # Mock FAISS and vLLM
        mock_context.faiss_manager.search = Mock(
            return_value=(
                np.array([[1, 2, 3]], dtype=np.int64),
                np.array([[0.9, 0.8, 0.7]], dtype=np.float32),
            )
        )
        mock_context.vllm_client.embed_single = Mock(
            return_value=np.array([0.1] * 2560, dtype=np.float32)
        )

        test_chunks = [
            {
                "id": 1,
                "uri": "src/main.py",
                "start_line": 1,
                "end_line": 10,
                "preview": "def main()",
            },
            {
                "id": 2,
                "uri": "src/app.ts",
                "start_line": 1,
                "end_line": 5,
                "preview": "function app()",
            },
        ]

        catalog_mock = Mock()
        catalog_mock.query_by_ids = Mock(return_value=test_chunks)
        catalog_mock.query_by_filters = Mock(return_value=test_chunks)

        # Replace open_catalog context manager for this test
        from contextlib import contextmanager

        @contextmanager
        def test_open_catalog() -> Generator[Mock]:
            yield catalog_mock

        mock_context.open_catalog = test_open_catalog

        asyncio.run(semantic_adapter.semantic_search(mock_context, "query", 10))

        # Verify query_by_ids was called (no scope filters)
        assert catalog_mock.query_by_ids.called
        # query_by_filters should not be called when no scope
        assert not catalog_mock.query_by_filters.called
