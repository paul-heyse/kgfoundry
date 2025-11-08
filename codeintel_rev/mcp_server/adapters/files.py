"""File and scope management adapter.

Provides file listing, reading, and scope configuration.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from codeintel_rev.app.middleware import get_session_id
from codeintel_rev.errors import FileReadError, InvalidLineRangeError
from codeintel_rev.io.path_utils import resolve_within_repo
from codeintel_rev.mcp_server.schemas import ScopeIn
from codeintel_rev.mcp_server.scope_utils import (
    apply_language_filter,
    get_effective_scope,
    merge_scope_filters,
)
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

LOGGER = get_logger(__name__)


async def set_scope(context: ApplicationContext, scope: ScopeIn) -> dict:
    """Set query scope for subsequent operations.

    Stores scope in the session-scoped registry keyed by session ID. Subsequent
    queries within the same session automatically apply these constraints.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing scope registry.
    scope : ScopeIn
        Scope configuration with repos, branches, paths, languages.

    Returns
    -------
    dict
        Confirmation with effective scope and session ID.

    Examples
    --------
    >>> result = set_scope(context, {"languages": ["python"], "include_globs": ["src/**"]})
    >>> result["status"]
    'ok'
    >>> result["session_id"]  # UUID format
    'abc123...'
    >>> result["effective_scope"]["languages"]
    ['python']

    Notes
    -----
    The session ID is extracted from the request context (set by middleware).
    If no session ID is available, this function will raise RuntimeError.
    """
    session_id = get_session_id()
    await context.scope_store.set(session_id, scope)

    LOGGER.info(
        "Set scope for session",
        extra={"session_id": session_id, "scope": scope},
    )

    return {"effective_scope": scope, "session_id": session_id, "status": "ok"}


async def list_paths(
    context: ApplicationContext,
    path: str | None = None,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    max_results: int = 1000,
) -> dict:
    """List files in repository (async with threadpool offload).

    Applies session scope filters (include_globs, exclude_globs, languages) if
    set via `set_scope`. Explicit parameters override session scope.

    This function runs the blocking directory traversal in a threadpool via
    `asyncio.to_thread` to prevent blocking the event loop. This enables
    concurrent file listing operations without thread exhaustion.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing repo root and settings.
    path : str | None
        Starting path relative to repo root (None = root).
    include_globs : list[str] | None
        Glob patterns to include (e.g., ["*.py"]). Overrides session scope if provided.
    exclude_globs : list[str] | None
        Glob patterns to exclude (e.g., ["__pycache__", "*.pyc"]). Overrides session scope if provided.
    max_results : int
        Maximum number of files to return.

    Returns
    -------
    dict
        File listing with paths and metadata.

    Examples
    --------
    Basic usage:

    >>> result = list_paths(context, path="src", include_globs=["*.py"])
    >>> isinstance(result["items"], list)
    True

    With session scope:

    >>> set_scope(context, {"languages": ["python"], "include_globs": ["src/**"]})
    >>> result = list_paths(context, path=None)
    >>> # Returns only Python files in src/ directory

    Explicit parameters override scope:

    >>> set_scope(context, {"languages": ["python"]})
    >>> result = list_paths(context, include_globs=["**/*.ts"])
    >>> # Returns TypeScript files (explicit override), not Python

    Notes
    -----
    Async Pattern:
    - The blocking directory traversal runs in a threadpool via `asyncio.to_thread`.
    - This prevents blocking the event loop and enables concurrent operations.
    - The sync implementation (`_list_paths_sync`) contains the actual logic.

    Scope Integration:
    - Session scope is retrieved from registry using session ID (set by middleware).
    - Scope's `include_globs` and `exclude_globs` are merged with explicit parameters.
    - Explicit parameters take precedence over scope (explicit wins).
    - Scope's `languages` filter is applied after directory traversal (post-filtering).
    - If no scope is set, behaves as before (no filtering beyond explicit params).

    The traversal skips directories that match the default or user supplied
    exclusion globs (for example ``**/.git/**``) so that large dependency
    folders are pruned without visiting their contents.
    """
    LOGGER.debug(
        "Listing paths (async)",
        extra={"path": path, "max_results": max_results},
    )
    session_id = get_session_id()
    scope = await get_effective_scope(context, session_id)
    return await asyncio.to_thread(
        _list_paths_sync,
        context,
        session_id,
        scope,
        path,
        include_globs,
        exclude_globs,
        max_results,
    )


def _list_paths_sync(  # noqa: C901, PLR0912, PLR0913, PLR0914, PLR0917 - PathOutsideRepositoryError raised by resolve_within_repo; pre-existing complexity
    context: ApplicationContext,
    session_id: str,
    scope: ScopeIn | None,
    path: str | None = None,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    max_results: int = 1000,
) -> dict:
    """List files in repository (synchronous implementation).

    Synchronous implementation of list_paths that performs the actual directory
    traversal. This function runs in a threadpool when called from the async
    `list_paths` wrapper.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing repo root and settings.
    session_id : str
        Session identifier for logging and scope resolution.
    scope : ScopeIn | None
        Session scope containing include/exclude globs and language filters.
        Overridden by explicit ``include_globs`` and ``exclude_globs`` parameters.
    path : str | None
        Starting path relative to repo root (None = root).
    include_globs : list[str] | None
        Glob patterns to include (e.g., ["*.py"]). Overrides session scope if provided.
    exclude_globs : list[str] | None
        Glob patterns to exclude (e.g., ["__pycache__", "*.pyc"]). Overrides session scope if provided.
    max_results : int
        Maximum number of files to return.

    Returns
    -------
    dict
        File listing with paths and metadata.

    Raises
    ------
    FileNotFoundError
        If path doesn't exist or is not a directory.
    """
    repo_root = context.paths.repo_root
    search_root = _resolve_search_root(repo_root, path)
    if search_root is None:
        error_msg = "Path not found or not a directory"
        raise FileNotFoundError(error_msg)

    merged = merge_scope_filters(
        scope,
        {"include_globs": include_globs, "exclude_globs": exclude_globs},
    )

    # Default excludes
    default_excludes = [
        "**/.git",
        "**/.git/**",
        "**/.venv",
        "**/.venv/**",
        "**/__pycache__",
        "**/__pycache__/**",
        "**/node_modules",
        "**/node_modules/**",
        "**/.pytest_cache",
        "**/.pytest_cache/**",
        "**/.ruff_cache",
        "**/.ruff_cache/**",
        "**/.mypy_cache",
        "**/.mypy_cache/**",
        "**/*.pyc",
        "**/*.pyo",
    ]
    excludes = (merged.get("exclude_globs") or []) + default_excludes
    includes = merged.get("include_globs") or ["**"]

    # Walk directory
    items = []
    for current_root, dirnames, filenames in os.walk(search_root):
        try:
            resolved_root = Path(current_root).resolve()
        except OSError:
            continue

        if _relative_path_str(resolved_root, repo_root) is None:
            continue

        # Prune excluded directories so we do not descend into them.
        for dir_name in list(dirnames):
            dir_path = resolved_root / dir_name
            relative_dir = _relative_path_str(dir_path, repo_root)
            if relative_dir is None:
                dirnames.remove(dir_name)
                continue
            dir_targets = (
                relative_dir,
                f"{relative_dir}/",
                f"./{relative_dir}",
                f"./{relative_dir}/",
            )
            if any(_matches_any(target, excludes) for target in dir_targets):
                dirnames.remove(dir_name)

        for file_name in filenames:
            file_path = resolved_root / file_name
            relative_file = _relative_path_str(file_path, repo_root)
            if relative_file is None:
                continue
            if _matches_any(relative_file, excludes) or _matches_any(
                f"./{relative_file}", excludes
            ):
                continue
            if not _matches_any(relative_file, includes):
                continue

            stat_result = _safe_stat(file_path)
            if stat_result is None:
                continue

            items.append(
                {
                    "path": relative_file,
                    "size": stat_result.st_size,
                    "modified": stat_result.st_mtime,
                }
            )

            if len(items) >= max_results:
                break

    # Apply language filter if scope has languages
    if scope:
        languages = scope.get("languages")
        if languages:
            filtered_paths = apply_language_filter([item["path"] for item in items], languages)
            items = [item for item in items if item["path"] in filtered_paths]

    if len(items) >= max_results:
        return {
            "items": items[:max_results],
            "total": len(items),
            "truncated": True,
        }

    LOGGER.debug(
        "Listed paths with scope filters",
        extra={
            "session_id": session_id,
            "path": path,
            "item_count": len(items),
            "applied_scope": scope is not None,
            "languages": scope.get("languages") if scope else None,
        },
    )

    return {
        "items": items,
        "total": len(items),
        "truncated": len(items) >= max_results,
    }


def open_file(
    context: ApplicationContext,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict:
    """Read file content with optional line slicing.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing repo root and settings.
    path : str
        File path relative to repo root.
    start_line : int | None
        Start line (1-indexed, inclusive). Must be positive when provided.
    end_line : int | None
        End line (1-indexed, inclusive). Must be positive when provided.

    Returns
    -------
    dict
        File content and metadata with keys: path, content, lines, size.

    Raises
    ------
    FileNotFoundError
        If file doesn't exist (raised by resolve_within_repo) or is not a file.
    FileReadError
        If file is binary or has encoding issues.
    InvalidLineRangeError
        If line range parameters are invalid.

    Notes
    -----
    ``start_line`` and ``end_line`` are inclusive and 1-indexed. If both bounds
    are supplied then ``start_line`` must be less than or equal to ``end_line``.
    Providing a single bound slices from the start or through the end of the
    file respectively.

    Examples
    --------
    >>> result = open_file(context, "README.md", start_line=1, end_line=10)
    >>> "content" in result
    True
    """
    repo_root = context.paths.repo_root

    # Path validation (raises PathOutsideRepositoryError or FileNotFoundError)
    file_path = resolve_within_repo(repo_root, path, allow_nonexistent=False)

    # File type check
    if not file_path.is_file():
        error_msg = f"Not a file: {path}"
        raise FileNotFoundError(error_msg)

    # Read content (raises UnicodeDecodeError → wrapped by decorator)
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        error_msg = "Binary file or encoding error"
        raise FileReadError(error_msg, path=path) from exc

    # Line validation (raise typed exceptions)
    if start_line is not None and start_line <= 0:
        error_msg = "start_line must be a positive integer"
        raise InvalidLineRangeError(
            error_msg,
            path=path,
            line_range=(start_line, end_line),
        )
    if end_line is not None and end_line <= 0:
        error_msg = "end_line must be a positive integer"
        raise InvalidLineRangeError(
            error_msg,
            path=path,
            line_range=(start_line, end_line),
        )
    if start_line is not None and end_line is not None and start_line > end_line:
        error_msg = "start_line must be less than or equal to end_line"
        raise InvalidLineRangeError(
            error_msg,
            path=path,
            line_range=(start_line, end_line),
        )

    # Line slicing logic (pure domain logic)
    if start_line is not None or end_line is not None:
        lines = content.splitlines(keepends=True)
        start_idx = (start_line - 1) if start_line is not None else 0
        end_idx = end_line if end_line is not None else len(lines)
        content = "".join(lines[start_idx:end_idx])

    # Success case
    return {
        "path": path,
        "content": content,
        "lines": len(content.splitlines()),
        "size": len(content),
    }


__all__ = ["list_paths", "open_file", "set_scope"]


def _resolve_search_root(repo_root: Path, requested: str | None) -> Path | None:
    """Resolve search root path, returning None if path doesn't exist or is not a directory.

    This function calls ``resolve_within_repo`` which may raise exceptions, but
    this function itself does not raise exceptions. It returns ``None`` when the
    resolved path is not a directory.

    Parameters
    ----------
    repo_root : Path
        Repository root directory.
    requested : str | None
        Requested path (None = root).

    Returns
    -------
    Path | None
        Resolved search root path, or None if path doesn't exist or is not a directory.
        Note: ``resolve_within_repo`` may raise ``PathOutsideRepositoryError`` or
        ``FileNotFoundError`` before this function returns, but those exceptions
        are not caught or re-raised by this function.
    """
    if requested is None:
        return repo_root

    # Raises PathOutsideRepositoryError or FileNotFoundError
    search_root = resolve_within_repo(repo_root, requested, allow_nonexistent=False)

    if not search_root.is_dir():
        return None

    return search_root


def _matches_any(target: str, patterns: Sequence[str]) -> bool:
    normalized = target.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def _relative_path_str(path: Path, repo_root: Path) -> str | None:
    try:
        resolved = path.resolve()
    except OSError:
        return None
    try:
        relative_path = resolved.relative_to(repo_root)
    except ValueError:
        return None
    return relative_path.as_posix()


def _safe_stat(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except OSError:
        return None
