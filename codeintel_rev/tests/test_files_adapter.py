"""Unit tests for file adapter path handling."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

if "msgspec" not in sys.modules:
    msgspec_stub = types.ModuleType("msgspec")

    class _Struct:  # pragma: no cover - helper for test environment
        def __init__(self, **kwargs: object) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

        def __init_subclass__(cls, **kwargs: object) -> None:
            super().__init_subclass__()

    msgspec_stub.Struct = _Struct
    sys.modules["msgspec"] = msgspec_stub

if "kgfoundry_common" not in sys.modules:
    kgfoundry_common_stub = types.ModuleType("kgfoundry_common")
    problem_details_stub = types.ModuleType("kgfoundry_common.problem_details")

    class ProblemDetailsDict(dict):
        """Fallback ProblemDetailsDict for tests."""

    problem_details_stub.ProblemDetailsDict = ProblemDetailsDict
    kgfoundry_common_stub.problem_details = problem_details_stub

    sys.modules["kgfoundry_common"] = kgfoundry_common_stub
    sys.modules["kgfoundry_common.problem_details"] = problem_details_stub

if "codeintel_rev.mcp_server.service_context" not in sys.modules:
    service_context_stub = types.ModuleType("codeintel_rev.mcp_server.service_context")

    def reset_service_context() -> None:  # pragma: no cover - test helper stub
        """Test stub that mimics resetting cached service context."""

    service_context_stub.reset_service_context = reset_service_context
    sys.modules["codeintel_rev.mcp_server.service_context"] = service_context_stub

from codeintel_rev.mcp_server.adapters import files as files_adapter
from codeintel_rev.mcp_server.service_context import reset_service_context


def _expect(*, condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message)


def _set_repo_root(monkeypatch: pytest.MonkeyPatch, repo_root: Path) -> None:
    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    # Ensure cached service context does not hold stale settings across tests.
    reset_service_context()


def test_open_file_rejects_paths_outside_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """open_file should reject attempts to escape the repository root."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("within repo", encoding="utf-8")

    _set_repo_root(monkeypatch, repo_root)

    result = files_adapter.open_file("../outside.txt")
    _expect(
        condition=result.get("error", "").startswith("Path"),
        message="Expected path traversal to be rejected",
    )
    reset_service_context()


def test_open_file_rejects_negative_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """open_file should error when provided negative line bounds."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "file.txt").write_text("line1\nline2\n", encoding="utf-8")

    _set_repo_root(monkeypatch, repo_root)

    result = files_adapter.open_file("file.txt", start_line=-1, end_line=2)
    _expect(
        condition="error" in result,
        message="Expected an error payload for negative bounds",
    )
    _expect(
        condition="positive integer" in result["error"],
        message="Expected positive integer error message",
    )
    _expect(
        condition="content" not in result,
        message="Expected response to omit content when failing",
    )
    reset_service_context()


def test_open_file_rejects_start_line_after_end_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """open_file should error when start_line exceeds end_line."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "file.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")

    _set_repo_root(monkeypatch, repo_root)

    result = files_adapter.open_file("file.txt", start_line=3, end_line=2)
    _expect(
        condition="error" in result,
        message="Expected an error payload when start_line > end_line",
    )
    _expect(
        condition="less than or equal" in result["error"],
        message="Expected start_line <= end_line message",
    )
    _expect(
        condition="content" not in result,
        message="Expected response to omit content when failing",
    )
    reset_service_context()


def test_list_paths_rejects_paths_outside_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_paths should reject traversal outside the repository root."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "inner").mkdir()
    (repo_root / "inner" / "file.txt").write_text("data", encoding="utf-8")

    _set_repo_root(monkeypatch, repo_root)

    response = files_adapter.list_paths(path="../inner")
    _expect(
        condition=bool(response.get("error")),
        message="Expected traversal attempt to return an error",
    )
    _expect(
        condition="escapes repository root" in response["error"],
        message="Expected repository escape message",
    )
    reset_service_context()


def test_list_paths_excludes_common_directories_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default excludes should omit VCS, virtualenv, and dependency folders."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    (repo_root / "src").mkdir()
    (repo_root / "src" / "module.py").write_text("print('ok')\n", encoding="utf-8")
    # Compiled artifacts should be ignored even outside __pycache__ directories.
    (repo_root / "src" / "module.pyc").write_bytes(b"compiled")
    (repo_root / "src" / "__pycache__").mkdir()
    (repo_root / "src" / "__pycache__" / "module.cpython-311.pyc").write_bytes(b"cache")

    (repo_root / ".git").mkdir()
    (repo_root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    (repo_root / ".venv").mkdir()
    (repo_root / ".venv" / "pyvenv.cfg").write_text("home=/tmp/python\n", encoding="utf-8")

    (repo_root / "node_modules").mkdir()
    (repo_root / "node_modules" / "pkg").mkdir()
    (repo_root / "node_modules" / "pkg" / "index.js").write_text(
        "module.exports = {};\n", encoding="utf-8"
    )

    _set_repo_root(monkeypatch, repo_root)

    response = files_adapter.list_paths()

    returned_paths = {item["path"] for item in response["items"]}
    _expect(condition="src/module.py" in returned_paths, message="Expected src/module.py")
    _expect(condition=".git/HEAD" not in returned_paths, message="Expected .git/HEAD excluded")
    _expect(condition=".venv/pyvenv.cfg" not in returned_paths, message="Expected .venv excluded")
    _expect(
        condition="node_modules/pkg/index.js" not in returned_paths,
        message="Expected node_modules excluded",
    )
    _expect(condition="src/module.pyc" not in returned_paths, message="Expected .pyc excluded")
    _expect(
        condition="src/__pycache__/module.cpython-311.pyc" not in returned_paths,
        message="Expected __pycache__ excluded",
    )

    reset_service_context()
