"""Unit tests for files adapter with scope filtering using integration harness."""

from __future__ import annotations

from collections.abc import Iterator
from contextvars import Token
from pathlib import Path

import pytest
from codeintel_rev.errors import (
    FileReadError,
    InvalidLineRangeError,
    PathNotDirectoryError,
    PathNotFoundError,
)
from codeintel_rev.io.path_utils import PathOutsideRepositoryError
from codeintel_rev.mcp_server.adapters.files import list_paths, open_file
from codeintel_rev.mcp_server.schemas import ScopeIn
from codeintel_rev.runtime.request_context import session_id_var

from tests._helpers import assertions
from tests._helpers.integration import (
    IntegrationHarness,
    IntegrationHarnessOptions,
    build_integration_harness,
)
from tests._helpers.settings import build_app_config_for_repo


def _seed_files(repo_root: Path) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "main.py").write_text('def main():\n    print("hello")\n')
    (repo_root / "src" / "utils.py").write_text("def helper():\n    pass\n")
    (repo_root / "src" / "app.ts").write_text('function app() {\n    console.log("hello");\n}\n')
    (repo_root / "tests" / "test_main.py").write_text("def test_main():\n    assert True\n")
    (repo_root / "README.md").write_text("# Documentation\n")


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[IntegrationHarness]:
    """Integration harness with seeded files and scope store.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory for test artifacts.

    Yields
    ------
    IntegrationHarness
        Harness containing ApplicationContext and repo_root.
    """
    files = {
        "src/main.py": 'def main():\n    print("hello")\n',
        "src/utils.py": "def helper():\n    pass\n",
        "src/app.ts": 'function app() {\n    console.log("hello");\n}\n',
        "tests/test_main.py": "def test_main():\n    assert True\n",
        "README.md": "# Documentation\n",
    }
    base = build_integration_harness(
        tmp_path,
        options=IntegrationHarnessOptions(populate_repo=False, seed_files=files),
    )
    app_config = build_app_config_for_repo(base.repo_root)
    context = base.context.with_overrides(app_config=app_config)  # type: ignore[attr-defined]
    base.context = context  # type: ignore[assignment]
    try:
        yield base
    finally:
        base.close()


async def _set_scope(
    harness: IntegrationHarness,
    session_id: str,
    scope: ScopeIn | None,
) -> Token[str | None]:
    token = session_id_var.set(session_id)
    if scope is None:
        await harness.context.scope_store.delete(session_id)
    else:
        await harness.context.scope_store.set(session_id, scope)
    return token


@pytest.mark.asyncio
async def test_list_paths_with_scope_globs(harness: IntegrationHarness) -> None:
    """Test that list_paths applies scope glob filters."""
    token = await _set_scope(harness, "test-session-123", {"include_globs": ["**/*.py"]})
    result = await list_paths(harness.context, path=None, max_results=100)  # type: ignore[arg-type]
    session_id_var.reset(token)

    assertions.expect_in("items", result)
    items = result["items"]
    assertions.expect_true(isinstance(items, list), reason="items should be a list")
    assertions.expect_true(len(items) > 0, reason="should have items")
    paths_list = [item.get("path", "") for item in items]
    assertions.expect_true(
        all(path.endswith(".py") for path in paths_list if path),
        reason="all paths should end with .py",
    )
    assertions.expect_false(
        any(path.endswith(".ts") for path in paths_list if path),
        reason="should not include .ts files",
    )
    assertions.expect_false(
        any(path.endswith(".md") for path in paths_list if path),
        reason="should not include .md files",
    )


@pytest.mark.asyncio
async def test_list_paths_with_scope_language(harness: IntegrationHarness) -> None:
    """Test that list_paths applies scope language filters."""
    token = await _set_scope(harness, "test-session-123", {"languages": ["python"]})
    result = await list_paths(harness.context, path=None, max_results=100)  # type: ignore[arg-type]
    session_id_var.reset(token)

    assertions.expect_in("items", result)
    items = result["items"]
    assertions.expect_true(isinstance(items, list), reason="items should be a list")
    assertions.expect_true(len(items) > 0, reason="should have items")
    paths_list = [item.get("path", "") for item in items]
    assertions.expect_true(
        all(path.endswith(".py") for path in paths_list if path),
        reason="all paths should end with .py",
    )
    assertions.expect_false(
        any(path.endswith(".ts") for path in paths_list if path),
        reason="should not include .ts files",
    )


@pytest.mark.asyncio
async def test_list_paths_explicit_languages_override_scope(harness: IntegrationHarness) -> None:
    """Explicit languages parameter overrides scoped languages."""
    token = await _set_scope(harness, "test-session-lang-override", {"languages": ["python"]})
    result = await list_paths(  # type: ignore[arg-type]
        harness.context,
        path=None,
        max_results=100,
        languages=["typescript"],
    )
    session_id_var.reset(token)

    assertions.expect_in("items", result)
    items = result["items"]
    assertions.expect_true(isinstance(items, list), reason="items should be a list")
    assertions.expect_true(bool(items), reason="should have items")
    paths_list = [item.get("path", "") for item in items]
    assertions.expect_true(
        all(path.endswith(".ts") for path in paths_list if path),
        reason="all paths should end with .ts",
    )
    assertions.expect_in("src/app.ts", paths_list)


@pytest.mark.asyncio
async def test_list_paths_excludes_default_directories(harness: IntegrationHarness) -> None:
    """Default exclusion globs filter VCS, virtualenv, and cache paths."""
    repo_root = harness.context.paths.repo_root  # type: ignore[attr-defined]
    (repo_root / ".git").mkdir()
    (repo_root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (repo_root / ".venv").mkdir()
    (repo_root / ".venv" / "pyvenv.cfg").write_text("home=/tmp/python\n", encoding="utf-8")
    (repo_root / "node_modules").mkdir()
    (repo_root / "node_modules" / "pkg").mkdir(parents=True, exist_ok=True)
    (repo_root / "node_modules" / "pkg" / "index.js").write_text(
        "module.exports = {};\n", encoding="utf-8"
    )
    (repo_root / "src" / "__pycache__").mkdir()
    (repo_root / "src" / "__pycache__" / "module.pyc").write_bytes(b"cache")
    (repo_root / "src" / "module.pyc").write_bytes(b"compiled")

    token = await _set_scope(harness, "default-scope", None)
    response = await list_paths(harness.context)  # type: ignore[arg-type]
    session_id_var.reset(token)

    returned_paths = {item["path"] for item in response["items"]}
    assertions.expect_in("src/main.py", returned_paths)
    assertions.expect_false(".git/HEAD" in returned_paths, reason="should exclude .git files")
    assertions.expect_false(
        ".venv/pyvenv.cfg" in returned_paths, reason="should exclude .venv files"
    )
    assertions.expect_false(
        "node_modules/pkg/index.js" in returned_paths, reason="should exclude node_modules"
    )
    assertions.expect_false("src/module.pyc" in returned_paths, reason="should exclude .pyc files")
    assertions.expect_false(
        "src/__pycache__/module.pyc" in returned_paths, reason="should exclude __pycache__"
    )


def test_open_file_success(harness: IntegrationHarness) -> None:
    """Test open_file returns file content on success."""
    result = open_file(harness.context, "README.md")  # type: ignore[arg-type]
    assertions.expect_equal(result["path"], "README.md")
    assertions.expect_in("content", result)
    assertions.expect_in("# Documentation", result["content"])
    assertions.expect_true(result["lines"] > 0, reason="lines should be positive")
    assertions.expect_true(result["size"] > 0, reason="size should be positive")


def test_open_file_with_line_range(harness: IntegrationHarness) -> None:
    """Test open_file slices content by line range."""
    result = open_file(harness.context, "src/main.py", start_line=1, end_line=1)  # type: ignore[arg-type]
    assertions.expect_equal(result["path"], "src/main.py")
    assertions.expect_in("def main():", result["content"])
    assertions.expect_equal(result["lines"], 1)


def test_open_file_path_outside_repository(harness: IntegrationHarness) -> None:
    """Test open_file raises PathOutsideRepositoryError for paths outside repo."""
    with pytest.raises(PathOutsideRepositoryError, match="escapes"):
        open_file(harness.context, "../../etc/passwd")  # type: ignore[arg-type]


def test_open_file_not_found(harness: IntegrationHarness) -> None:
    """Test open_file raises PathNotFoundError for nonexistent files."""
    with pytest.raises(PathNotFoundError, match="Path not found"):
        open_file(harness.context, "nonexistent.py")  # type: ignore[arg-type]


def test_open_file_not_a_file(harness: IntegrationHarness) -> None:
    """Test open_file raises PathNotFoundError when path is a directory."""
    with pytest.raises(PathNotFoundError, match="Not a file"):
        open_file(harness.context, "src")  # type: ignore[arg-type]


def test_open_file_binary_file(harness: IntegrationHarness) -> None:
    """Test open_file raises FileReadError for binary files."""
    binary_file = harness.context.paths.repo_root / "binary.bin"  # type: ignore[attr-defined]
    binary_file.write_bytes(b"\xff\xfe\x00\x01")

    with pytest.raises(FileReadError, match="Binary file or encoding error"):
        open_file(harness.context, "binary.bin")  # type: ignore[arg-type]


def test_open_file_invalid_start_line(harness: IntegrationHarness) -> None:
    """Test open_file raises InvalidLineRangeError for invalid start_line."""
    with pytest.raises(InvalidLineRangeError, match="start_line must be a positive integer"):
        open_file(harness.context, "README.md", start_line=0)  # type: ignore[arg-type]

    with pytest.raises(InvalidLineRangeError, match="start_line must be a positive integer"):
        open_file(harness.context, "README.md", start_line=-1)  # type: ignore[arg-type]


def test_open_file_invalid_end_line(harness: IntegrationHarness) -> None:
    """Test open_file raises InvalidLineRangeError for invalid end_line."""
    with pytest.raises(InvalidLineRangeError, match="end_line must be a positive integer"):
        open_file(harness.context, "README.md", end_line=0)  # type: ignore[arg-type]

    with pytest.raises(InvalidLineRangeError, match="end_line must be a positive integer"):
        open_file(harness.context, "README.md", end_line=-1)  # type: ignore[arg-type]


def test_open_file_start_greater_than_end(harness: IntegrationHarness) -> None:
    """Test open_file raises InvalidLineRangeError when start_line > end_line."""
    with pytest.raises(
        InvalidLineRangeError, match="start_line must be less than or equal to end_line"
    ):
        open_file(harness.context, "README.md", start_line=10, end_line=5)  # type: ignore[arg-type]


def test_open_file_exception_context(harness: IntegrationHarness) -> None:
    """Test that exceptions include proper context."""
    with pytest.raises(InvalidLineRangeError) as exc_info:
        open_file(harness.context, "README.md", start_line=0, end_line=10)  # type: ignore[arg-type]

    exc = exc_info.value
    assertions.expect_equal(exc.context["path"], "README.md")
    assertions.expect_equal(exc.context["start_line"], 0)
    assertions.expect_equal(exc.context["end_line"], 10)


@pytest.mark.asyncio
async def test_list_paths_path_not_found(harness: IntegrationHarness) -> None:
    """Test list_paths raises PathNotFoundError for nonexistent paths."""
    token = await _set_scope(harness, "test-session-error", None)
    with pytest.raises(PathNotFoundError, match="Path not found"):
        await list_paths(harness.context, path="nonexistent")  # type: ignore[arg-type]
    session_id_var.reset(token)


@pytest.mark.asyncio
async def test_list_paths_path_outside_repository(harness: IntegrationHarness) -> None:
    """Test list_paths raises PathOutsideRepositoryError for paths outside repo."""
    token = await _set_scope(harness, "test-session-error", None)
    with pytest.raises(PathOutsideRepositoryError, match="escapes"):
        await list_paths(harness.context, path="../../etc")  # type: ignore[arg-type]
    session_id_var.reset(token)


@pytest.mark.asyncio
async def test_list_paths_path_is_file(harness: IntegrationHarness) -> None:
    """Test list_paths raises PathNotDirectoryError when path is a file, not directory."""
    token = await _set_scope(harness, "test-session-error", None)
    with pytest.raises(PathNotDirectoryError, match="Path is not a directory"):
        await list_paths(harness.context, path="README.md")  # type: ignore[arg-type]
    session_id_var.reset(token)
