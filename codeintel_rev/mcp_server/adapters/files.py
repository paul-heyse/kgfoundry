"""File and scope management adapter.

Provides file listing, reading, and scope configuration.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, SupportsIndex, cast

from codeintel_rev.app.middleware import get_session_id
from codeintel_rev.errors import (
    FileReadError,
    InvalidLineRangeError,
    PathNotDirectoryError,
    PathNotFoundError,
)
from codeintel_rev.io.path_utils import PathOutsideRepositoryError, resolve_within_repo
from codeintel_rev.mcp_server.schemas import ScopeIn
from codeintel_rev.mcp_server.scope_utils import (
    LANGUAGE_EXTENSIONS,
    get_effective_scope,
    merge_scope_filters,
)
from codeintel_rev.observability.execution_ledger import (
    record as ledger_record,
)
from codeintel_rev.observability.execution_ledger import (
    step as ledger_step,
)
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class FileListFilters:
    """Configuration for file listing filters."""

    include_globs: list[str] | None = None
    exclude_globs: list[str] | None = None
    languages: list[str] | None = None
    max_results: int = 1000


@dataclass(frozen=True)
class DirectoryFilters:
    """Prepared filters used during directory traversal."""

    includes: list[str]
    excludes: list[str]
    language_extensions: set[str] | None
    max_results: int


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
    with ledger_step(
        stage="gather",
        op="files.set_scope",
        component="mcp.files",
        attrs={"session_id": session_id},
    ):
        await context.scope_store.set(session_id, scope)

    LOGGER.info(
        "Set scope for session",
        extra={"session_id": session_id, "scope": scope},
    )

    return {"effective_scope": scope, "session_id": session_id, "status": "ok"}


async def list_paths(context: ApplicationContext, *args: object, **kwargs: object) -> dict:
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
    *args : object
        Positional arguments (up to 5): path, include_globs, exclude_globs, languages, max_results.
        Positional arguments are supported for backward compatibility but keyword
        arguments are preferred.
    **kwargs : object
        Keyword arguments accepted:
        - path : str | None
            Starting path relative to repo root (None = root).
        - include_globs : list[str] | None
            Glob patterns to include (e.g., ["*.py"]).
            Overrides session scope if provided.
        - exclude_globs : list[str] | None
            Glob patterns to exclude (e.g., ["__pycache__", "*.pyc"]).
            Overrides session scope if provided.
        - languages : list[str] | None
            Programming languages to include (overrides session scope when provided).
        - max_results : int
            Maximum number of files to return (default: 1000).

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
    session_id = get_session_id()
    with ledger_step(
        stage="gather",
        op="files.scope",
        component="mcp.files",
        attrs={"session_id": session_id},
    ):
        scope = await get_effective_scope(context, session_id)
    path, include_globs, exclude_globs, languages, max_results = _normalize_list_paths_arguments(
        args, kwargs
    )
    filters = FileListFilters(
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        languages=languages,
        max_results=max_results,
    )
    LOGGER.debug(
        "Listing paths (async)",
        extra={"path": path, "max_results": max_results},
    )
    attrs = {
        "path": path or ".",
        "max_results": filters.max_results,
    }

    async def _run() -> dict:
        with ledger_step(
            stage="pool_search",
            op="files.list_paths",
            component="mcp.files",
            attrs=attrs,
        ):
            result = await asyncio.to_thread(
                _list_paths_sync,
                context,
                session_id,
                scope,
                path,
                filters,
            )
        return result

    result = await _run()
    ledger_record(
        "files.list_paths",
        stage="envelope",
        component="mcp.files",
        results=result.get("total", 0),
        truncated=result.get("truncated", False),
    )
    return result


def _normalize_list_paths_arguments(
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> tuple[str | None, list[str] | None, list[str] | None, list[str] | None, int]:
    positions: list[object | None] = list(args[:5])
    positions.extend([None] * (5 - len(positions)))

    path = kwargs.pop("path", positions[0])
    include_globs = kwargs.pop("include_globs", positions[1])
    exclude_globs = kwargs.pop("exclude_globs", positions[2])
    languages = kwargs.pop("languages", positions[3])
    max_value = cast(
        "SupportsIndex | str | None",
        kwargs.pop("max_results", kwargs.pop("max", positions[4])),
    )

    max_results = 1000 if max_value is None else int(max_value)

    if kwargs:
        unexpected = ", ".join(kwargs.keys())
        msg = "Unexpected keyword arguments: " + unexpected
        raise TypeError(msg)

    return (
        cast("str | None", path),
        cast("list[str] | None", include_globs),
        cast("list[str] | None", exclude_globs),
        cast("list[str] | None", languages),
        max_results,
    )


def _list_paths_sync(
    context: ApplicationContext,
    session_id: str,
    scope: ScopeIn | None,
    path: str | None = None,
    filters: FileListFilters | None = None,
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
    filters : FileListFilters | None
        Filters for includes, excludes, language restrictions, and max results.
        If None, default filters are used (no restrictions).

    Returns
    -------
    dict
        File listing with paths and metadata.

    Notes
    -----
    Exceptions raised by ``_resolve_search_root`` (PathNotFoundError,
    PathNotDirectoryError, PathOutsideRepositoryError) may propagate through
    this function.
    """
    repo_root = context.paths.repo_root
    search_root = _resolve_search_root(repo_root, path)
    filters = filters or FileListFilters()

    if filters.max_results <= 0:
        return {"items": [], "total": 0, "truncated": False}

    merged = merge_scope_filters(
        scope,
        {
            "include_globs": filters.include_globs,
            "exclude_globs": filters.exclude_globs,
            "languages": filters.languages,
        },
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

    merged_languages = merged.get("languages")
    language_extensions: set[str] | None = None
    if merged_languages:
        language_extensions = _collect_language_extensions(merged_languages)
        if not language_extensions:
            LOGGER.warning(
                "No file extensions found for requested languages",
                extra={"languages": merged_languages},
            )
            return {"items": [], "total": 0, "truncated": False}

    directory_filters = DirectoryFilters(
        includes=includes,
        excludes=excludes,
        language_extensions=language_extensions,
        max_results=filters.max_results,
    )
    items, matched_count, truncated = _collect_filtered_paths(
        search_root=search_root,
        repo_root=repo_root,
        filters=directory_filters,
    )

    LOGGER.debug(
        "Listed paths with scope filters",
        extra={
            "session_id": session_id,
            "path": path,
            "item_count": len(items),
            "matched_count": matched_count,
            "applied_scope": scope is not None,
            "languages": merged_languages,
        },
    )

    return {
        "items": items,
        "total": matched_count,
        "truncated": truncated,
    }


def _collect_filtered_paths(
    *,
    search_root: Path,
    repo_root: Path,
    filters: DirectoryFilters,
) -> tuple[list[dict[str, object]], int, bool]:
    """Walk directories and apply include/exclude filters.

    Parameters
    ----------
    search_root : Path
        Directory to start walking from.
    repo_root : Path
        Repository root directory.
    filters : DirectoryFilters
        Prepared include/exclude/language filters plus max results.

    Returns
    -------
    tuple[list[dict[str, object]], int, bool]
        Tuple containing:
        - items: List of file entries with path, size, and modified time
        - matched_count: Total number of files that matched filters
        - truncated: True if results were truncated due to max_results limit
    """
    items: list[dict[str, object]] = []
    matched_count = 0
    truncated = False

    for current_root, dirnames, filenames in os.walk(search_root):
        try:
            resolved_root = Path(current_root).resolve()
        except OSError:
            continue

        if _relative_path_str(resolved_root, repo_root) is None:
            continue

        _prune_directories(dirnames, resolved_root, repo_root, filters.excludes)

        for file_name in filenames:
            file_path = resolved_root / file_name
            entry = _create_file_entry(
                file_path=file_path,
                repo_root=repo_root,
                includes=filters.includes,
                excludes=filters.excludes,
                language_extensions=filters.language_extensions,
            )
            if entry is None:
                continue

            matched_count += 1
            if len(items) < filters.max_results:
                items.append(entry)
            if filters.max_results and len(items) >= filters.max_results:
                truncated = True
                break

        if truncated:
            break

    return items, matched_count, truncated


def _prune_directories(
    dirnames: list[str],
    resolved_root: Path,
    repo_root: Path,
    excludes: list[str],
) -> None:
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


def _create_file_entry(
    *,
    file_path: Path,
    repo_root: Path,
    includes: list[str],
    excludes: list[str],
    language_extensions: set[str] | None,
) -> dict[str, object] | None:
    """Return a file entry dict when filters accept the file.

    Checks if a file path matches the provided include/exclude patterns and
    language extensions. Returns a dictionary with file metadata if the file
    passes all filters, otherwise returns None.

    Parameters
    ----------
    file_path : Path
        Absolute path to the file being checked.
    repo_root : Path
        Root directory of the repository, used to compute relative paths.
    includes : list[str]
        List of glob patterns that the file path must match to be included.
        Empty list means no inclusion filter is applied.
    excludes : list[str]
        List of glob patterns that the file path must not match to be included.
        Empty list means no exclusion filter is applied.
    language_extensions : set[str] | None
        Set of file extensions (with leading dot) that the file must have.
        If None, no language filter is applied.

    Returns
    -------
    dict[str, object] | None
        Dictionary containing file metadata (path, relative_path, etc.) when
        filters are satisfied, otherwise ``None``.
    """
    relative_file = _relative_path_str(file_path, repo_root)
    if relative_file is None:
        return None
    if _matches_any(relative_file, excludes) or _matches_any(f"./{relative_file}", excludes):
        return None
    if not _matches_any(relative_file, includes):
        return None
    if language_extensions and not _matches_language(relative_file, language_extensions):
        return None

    stat_result = _safe_stat(file_path)
    if stat_result is None:
        return None

    return {
        "path": relative_file,
        "size": stat_result.st_size,
        "modified": stat_result.st_mtime,
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
    PathNotFoundError
        If the requested file does not exist or is not a regular file.
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

    with ledger_step(
        stage="hydrate",
        op="files.open_file",
        component="mcp.files",
        attrs={"path": path},
    ):
        # Path validation
        try:
            file_path = resolve_within_repo(repo_root, path, allow_nonexistent=False)
        except FileNotFoundError as exc:
            error_msg = f"Path not found: {path}"
            raise PathNotFoundError(error_msg, path=path, cause=exc) from exc

        if not file_path.is_file():
            error_msg = f"Not a file: {path}"
            raise PathNotFoundError(error_msg, path=path)

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

    result = {
        "path": path,
        "content": content,
        "lines": len(content.splitlines()),
        "size": len(content),
    }
    ledger_record(
        "files.open_file",
        stage="envelope",
        component="mcp.files",
        results=result["lines"],
    )
    return result


__all__ = ["list_paths", "open_file", "set_scope"]


def _resolve_search_root(repo_root: Path, requested: str | None) -> Path:
    """Resolve search root path, raising descriptive errors on failure.

    This function calls ``resolve_within_repo`` and converts generic file
    exceptions into domain-specific errors for consistent error handling.

    Parameters
    ----------
    repo_root : Path
        Repository root directory.
    requested : str | None
        Requested path (None = root).

    Returns
    -------
    Path
        Resolved search root path.

    Raises
    ------
    PathOutsideRepositoryError
        If the resolved path escapes the repository root (raised by
        ``resolve_within_repo``).
    PathNotFoundError
        If the requested path does not exist within the repository.
    PathNotDirectoryError
        If the resolved path exists but is not a directory.
    """
    if requested is None:
        return repo_root

    try:
        search_root = resolve_within_repo(repo_root, requested, allow_nonexistent=False)
    except PathOutsideRepositoryError:
        # Re-raise to make it explicit in the function body for pydoclint
        raise
    except FileNotFoundError as exc:
        error_msg = f"Path not found: {requested}"
        raise PathNotFoundError(error_msg, path=requested, cause=exc) from exc

    if not search_root.is_dir():
        error_msg = f"Path is not a directory: {requested}"
        raise PathNotDirectoryError(error_msg, path=requested)

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


def _collect_language_extensions(languages: Sequence[str]) -> set[str]:
    """Return canonical file extensions for the requested languages.

    Parameters
    ----------
    languages : Sequence[str]
        Language codes to get extensions for (e.g., ["python", "javascript"]).

    Returns
    -------
    set[str]
        Set of file extensions (with leading dots) for the requested languages.
    """
    extensions: set[str] = set()
    for language in languages:
        extensions.update(ext.lower() for ext in LANGUAGE_EXTENSIONS.get(language.lower(), []))
    return extensions


def _matches_language(path: str, extensions: set[str]) -> bool:
    """Return True when the path matches one of the requested extensions.

    Parameters
    ----------
    path : str
        File path to check.
    extensions : set[str]
        Set of file extensions (with leading dots) to match against.

    Returns
    -------
    bool
        True if the path ends with one of the extensions (case-insensitive),
        False otherwise.
    """
    normalized = path.lower()
    return any(normalized.endswith(ext) for ext in extensions)
