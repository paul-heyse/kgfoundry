"""Text search adapter using ripgrep.

Fast text search with regex support.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from codeintel_rev.app.middleware import get_session_id
from codeintel_rev.mcp_server.common.observability import observe_duration
from codeintel_rev.mcp_server.schemas import Match, ScopeIn
from codeintel_rev.mcp_server.scope_utils import (
    get_effective_scope,
    merge_scope_filters,
)
from kgfoundry_common.errors import VectorSearchError
from kgfoundry_common.logging import get_logger
from kgfoundry_common.subprocess_utils import (
    SubprocessError,
    SubprocessTimeoutError,
    run_subprocess,
)

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

SEARCH_TIMEOUT_SECONDS = 30
MAX_PREVIEW_CHARS = 200
GREP_SPLIT_PARTS = 3
COMMAND_NOT_FOUND_RETURN_CODE = 127
COMPONENT_NAME = "codeintel_mcp"
LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class TextSearchOptions:
    """Parameters controlling ripgrep execution."""

    _ALLOWED_KEYS = frozenset(
        {"regex", "case_sensitive", "paths", "include_globs", "exclude_globs", "max_results"}
    )

    query: str
    regex: bool = False
    case_sensitive: bool = False
    paths: Sequence[str] | None = None
    include_globs: Sequence[str] | None = None
    exclude_globs: Sequence[str] | None = None
    max_results: int = 50

    @classmethod
    def from_overrides(cls, query: str, overrides: Mapping[str, object]) -> TextSearchOptions:
        """Build search options from keyword overrides.

        Constructs a TextSearchOptions instance from a query string and a mapping
        of keyword arguments. Validates that all override keys are allowed options.

        Parameters
        ----------
        query : str
            Search query string (regex pattern if regex=True).
        overrides : Mapping[str, object]
            Dictionary of keyword arguments corresponding to TextSearchOptions fields.
            Valid keys are: regex, case_sensitive, paths, include_globs, exclude_globs,
            max_results.

        Returns
        -------
        TextSearchOptions
            Configured search options instance with query and overrides applied.

        Raises
        ------
        TypeError
            If any keys in overrides are not recognized as valid TextSearchOptions
            fields. This prevents typos and ensures type safety.
        """
        unexpected = set(overrides) - cls._ALLOWED_KEYS
        if unexpected:
            msg = f"Unexpected search_text keyword(s): {sorted(unexpected)}"
            raise TypeError(msg)
        return cls(query=query, **{k: overrides[k] for k in overrides})


class Observation(Protocol):
    """Interface describing the observation helpers used for metrics recording."""

    def mark_success(self) -> None:
        """Mark the current operation as successful."""

    def mark_error(self) -> None:
        """Mark the current operation as failed."""


async def search_text(
    context: ApplicationContext,
    query: str,
    *,
    options: TextSearchOptions | None = None,
    **overrides: object,
) -> dict:
    """Fast text search using ripgrep (async wrapper).

    Applies session scope path filters if set via `set_scope`. Explicit parameters
    override session scope following the precedence rules documented above.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing repo root and settings.
    query : str
        Search query string (regex pattern if ``regex=True``).
    options : TextSearchOptions | None, optional
        Explicit search configuration. When ``None``, keyword overrides are permitted.
    **overrides : object
        Backward-compatible keyword overrides corresponding to
        ``TextSearchOptions`` fields (``regex``, ``case_sensitive``, ``paths``,
        ``include_globs``, ``exclude_globs``, ``max_results``).

    Returns
    -------
    dict
        Search results containing matched paths and metadata.

    Raises
    ------
    TypeError
        If both ``options`` and keyword ``overrides`` are provided simultaneously.
        Only one method of providing search options is allowed per call.
    """
    session_id = get_session_id()
    scope = await get_effective_scope(context, session_id)
    if options is None:
        options = TextSearchOptions.from_overrides(query, overrides)
    elif overrides:
        msg = "Cannot pass keyword overrides when options is provided"
        raise TypeError(msg)
    return await asyncio.to_thread(
        _search_text_sync,
        context,
        session_id,
        scope,
        options,
    )


def _search_text_sync(
    context: ApplicationContext,
    session_id: str,
    scope: ScopeIn | None,
    options: TextSearchOptions,
) -> dict:
    repo_root = context.paths.repo_root

    query = options.query
    max_results = options.max_results

    merged_filters = merge_scope_filters(
        scope,
        {
            "include_globs": (
                list(options.include_globs)
                if options.include_globs is not None
                else options.include_globs
            ),
            "exclude_globs": (
                list(options.exclude_globs)
                if options.exclude_globs is not None
                else options.exclude_globs
            ),
        },
    )

    effective_paths = list(options.paths) if options.paths else None
    # Explicit paths suppress scope-provided include globs unless explicitly overridden
    if effective_paths and options.include_globs is None:
        effective_include_globs: Sequence[str] | None = None
    else:
        effective_include_globs = merged_filters.get("include_globs")
    effective_exclude_globs = merged_filters.get("exclude_globs")

    LOGGER.debug(
        "Searching text with scope filters",
        extra={
            "session_id": session_id,
            "query": query,
            "explicit_paths": list(options.paths) if options.paths else None,
            "explicit_include_globs": (
                list(options.include_globs) if options.include_globs is not None else None
            ),
            "explicit_exclude_globs": (
                list(options.exclude_globs) if options.exclude_globs is not None else None
            ),
            "scope_include_globs": (
                cast("Sequence[str] | None", scope.get("include_globs")) if scope else None
            ),
            "scope_exclude_globs": (
                cast("Sequence[str] | None", scope.get("exclude_globs")) if scope else None
            ),
            "effective_paths": effective_paths,
            "effective_include_globs": effective_include_globs,
            "effective_exclude_globs": effective_exclude_globs,
        },
    )

    params = RipgrepCommandParams(
        query=query,
        regex=options.regex,
        case_sensitive=options.case_sensitive,
        include_globs=effective_include_globs,
        exclude_globs=effective_exclude_globs,
        paths=effective_paths,
        max_results=options.max_results,
    )

    cmd = _build_ripgrep_command(params)

    with observe_duration("text_search", COMPONENT_NAME) as observation:
        try:
            stdout = run_subprocess(cmd, cwd=repo_root, timeout=SEARCH_TIMEOUT_SECONDS)
        except SubprocessTimeoutError as exc:
            observation.mark_error()
            error_msg = "Search timeout"
            raise VectorSearchError(
                error_msg,
                context={"query": query},
            ) from exc
        except SubprocessError as exc:
            if exc.returncode == 1:
                stdout = ""
            elif exc.returncode == COMMAND_NOT_FOUND_RETURN_CODE:
                return _fallback_grep(
                    observation=observation,
                    repo_root=repo_root,
                    query=query,
                    case_sensitive=options.case_sensitive,
                    max_results=max_results,
                )
            else:
                observation.mark_error()
                error_message = (exc.stderr or "").strip() or str(exc)
                raise VectorSearchError(
                    error_message,
                    cause=exc,
                    context={"query": query, "returncode": exc.returncode},
                ) from exc
        except ValueError as exc:
            observation.mark_error()
            error_msg = str(exc)
            raise VectorSearchError(
                error_msg,
                cause=exc,
                context={"query": query},
            ) from exc

        matches, truncated = _parse_ripgrep_output(stdout, repo_root, max_results)
        observation.mark_success()
        return {
            "matches": matches,
            "total": len(matches),
            "truncated": truncated,
        }


def _fallback_grep(
    *,
    observation: Observation,
    repo_root: Path,
    query: str,
    case_sensitive: bool,
    max_results: int,
) -> dict:
    """Fallback to basic grep if ripgrep unavailable.

    Parameters
    ----------
    observation : Observation
        Metrics observation context used to record success or failure.
    repo_root : Path
        Repository root directory.
    query : str
        Search query.
    case_sensitive : bool
        Case-sensitive search.
    max_results : int
        Maximum results.

    Returns
    -------
    dict
        Search results.

    Raises
    ------
    VectorSearchError
        If fallback grep operation fails (timeout, subprocess error, etc.).
    """
    command = ["grep", "-r", "-n"]

    if not case_sensitive:
        command.append("-i")

    command.extend(["--", query, "."])

    try:
        stdout = run_subprocess(command, cwd=repo_root, timeout=SEARCH_TIMEOUT_SECONDS)
    except SubprocessTimeoutError as exc:
        observation.mark_error()
        error_msg = "Search tool unavailable"
        raise VectorSearchError(
            error_msg,
            context={"query": query, "tool": "grep"},
        ) from exc
    except SubprocessError as exc:
        if exc.returncode == 1:
            stdout = ""
        else:
            observation.mark_error()
            error_message = (exc.stderr or "").strip() or str(exc)
            raise VectorSearchError(
                error_message,
                cause=exc,
                context={"query": query, "tool": "grep", "returncode": exc.returncode},
            ) from exc
    except ValueError as exc:
        observation.mark_error()
        error_msg = str(exc)
        raise VectorSearchError(
            error_msg,
            cause=exc,
            context={"query": query, "tool": "grep"},
        ) from exc

    matches: list[Match] = []
    for line in stdout.splitlines()[:max_results]:
        parts = line.split(":", GREP_SPLIT_PARTS - 1)
        if len(parts) < GREP_SPLIT_PARTS:
            continue

        try:
            raw_path = Path(parts[0])
            if not raw_path.is_absolute():
                raw_path = (repo_root / raw_path).resolve()
            path = str(raw_path.relative_to(repo_root))
            line_number = int(parts[1])
            preview = parts[2].strip()[:200]

            match: Match = {
                "path": path,
                "line": line_number,
                "column": 0,
                "preview": preview,
            }
            matches.append(match)
        except (ValueError, IndexError):
            continue

    observation.mark_success()
    return {
        "matches": matches,
        "total": len(matches),
        "truncated": len(matches) >= max_results,
    }


@dataclass(slots=True, frozen=True)
class RipgrepCommandParams:
    """Parameter bundle for constructing ripgrep commands."""

    query: str
    regex: bool
    case_sensitive: bool
    include_globs: Sequence[str] | None
    exclude_globs: Sequence[str] | None
    paths: Sequence[str] | None
    max_results: int


def _build_ripgrep_command(params: RipgrepCommandParams) -> list[str]:
    """Assemble the ripgrep command arguments.

    Parameters
    ----------
    params : RipgrepCommandParams
        Parameter bundle describing ripgrep invocation.

    Returns
    -------
    list[str]
        Argument vector for ripgrep invocation.
    """
    command = ["rg", "--json", "--max-count", str(params.max_results)]

    if not params.case_sensitive:
        command.append("--ignore-case")

    if not params.regex:
        command.append("--fixed-strings")

    if params.include_globs:
        for pattern in params.include_globs:
            command.extend(["--iglob", pattern])

    if params.exclude_globs:
        for pattern in params.exclude_globs:
            command.extend(["--iglob", f"!{pattern}"])

    command.append("--")
    command.append(params.query)

    if params.paths:
        command.extend(str(Path(path)) for path in params.paths)
    else:
        command.append(".")

    return command


def _parse_ripgrep_output(
    stdout: str,
    repo_root: Path,
    max_results: int,
) -> tuple[list[Match], bool]:
    """Parse ripgrep JSON output into structured matches.

    Parameters
    ----------
    stdout : str
        Ripgrep JSON output.
    repo_root : Path
        Repository root directory.
    max_results : int
        Maximum number of results to parse.

    Returns
    -------
    tuple[list[Match], bool]
        Parsed match list and whether results were truncated at max_results.
    """
    matches: list[Match] = []
    truncated = False

    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            continue

        if entry.get("type") != "match":
            continue

        data = entry.get("data", {})
        path_text = data.get("path", {}).get("text")
        if not path_text:
            continue

        try:
            relative_path = str(Path(path_text).resolve().relative_to(repo_root))
        except ValueError:
            relative_path = path_text

        line_number = int(data.get("line_number", 0))
        lines = data.get("lines", {}).get("text", "")
        submatches = data.get("submatches", [])
        column = int(submatches[0].get("start", 0)) if submatches else 0

        match: Match = {
            "path": relative_path,
            "line": line_number,
            "column": column,
            "preview": lines.strip()[:MAX_PREVIEW_CHARS],
        }
        matches.append(match)

        if len(matches) >= max_results:
            truncated = True
            break

    return matches, truncated


__all__ = ["search_text"]
