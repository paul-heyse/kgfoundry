"""Text search adapter using ripgrep.

Fast text search with regex support.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codeintel_rev.app.middleware import get_session_id
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
SEARCH_MAX_RESULTS = 500
MAX_PREVIEW_CHARS = 200
GREP_SPLIT_PARTS = 3
COMMAND_NOT_FOUND_RETURN_CODE = 127
COMPONENT_NAME = "codeintel_mcp"
LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class TextSearchOptions:
    """Parameters controlling ripgrep execution."""

    _ALLOWED_KEYS = frozenset(
        {
            "regex",
            "case_sensitive",
            "paths",
            "include_globs",
            "exclude_globs",
            "max_results",
        }
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
        regex_value = _bool_override(overrides, "regex") if "regex" in overrides else cls.regex
        case_sensitive_value = (
            _bool_override(overrides, "case_sensitive")
            if "case_sensitive" in overrides
            else cls.case_sensitive
        )
        max_results_value = (
            _int_override(overrides, "max_results")
            if "max_results" in overrides
            else cls.max_results
        )
        return cls(
            query=query,
            regex=regex_value,
            case_sensitive=case_sensitive_value,
            paths=_sequence_override(overrides, "paths"),
            include_globs=_sequence_override(overrides, "include_globs"),
            exclude_globs=_sequence_override(overrides, "exclude_globs"),
            max_results=max_results_value,
        )


@dataclass(slots=True)
class _ResolvedFilters:
    """Normalized scope and override filters for ripgrep."""

    paths: list[str] | None
    include_globs: Sequence[str] | None
    exclude_globs: Sequence[str] | None


def _bool_override(overrides: Mapping[str, object], key: str) -> bool:
    """Return a boolean override for the given key.

    Parameters
    ----------
    overrides : Mapping[str, object]
        Override dictionary provided by the adapter call.
    key : str
        Lookup key corresponding to a TextSearchOptions boolean field.

    Returns
    -------
    bool
        Boolean override value retrieved from the overrides mapping.

    Raises
    ------
    TypeError
        If the override is present but not a boolean.
    """
    value = overrides[key]
    if not isinstance(value, bool):
        msg = f"{key} must be a boolean"
        raise TypeError(msg)
    return value


def _sequence_override(overrides: Mapping[str, object], key: str) -> Sequence[str] | None:
    """Return a sequence override if the value is a valid sequence of strings.

    Parameters
    ----------
    overrides : Mapping[str, object]
        Override dictionary provided by the adapter call.
    key : str
        Lookup key corresponding to a sequence field in TextSearchOptions.

    Returns
    -------
    Sequence[str] | None
        Sequence override if present, otherwise ``None``.

    Raises
    ------
    TypeError
        If the override is present but not a sequence of strings.
    """
    if key not in overrides:
        return None
    value = overrides[key]
    if (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and all(isinstance(item, str) for item in value)
    ):
        return cast("Sequence[str]", value)
    msg = f"{key} must be a sequence of strings"
    raise TypeError(msg)


def _int_override(overrides: Mapping[str, object], key: str) -> int:
    """Return an integer override for the given key.

    Parameters
    ----------
    overrides : Mapping[str, object]
        Override dictionary provided by the adapter call.
    key : str
        Lookup key corresponding to the ``max_results`` parameter.

    Returns
    -------
    int
        Integer override value retrieved from the overrides mapping.

    Raises
    ------
    TypeError
        If the override is present but not an integer.
    """
    value = overrides[key]
    if not isinstance(value, int):
        msg = f"{key} must be an int"
        raise TypeError(msg)
    return value


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
    VectorSearchError
        Raised when the underlying search operation fails (timeout, subprocess error,
        or invalid query). The error includes context about the query and search tool.
    """
    session_id = get_session_id()
    scope = await get_effective_scope(context, session_id)
    if options is None:
        options = TextSearchOptions.from_overrides(query, overrides)
    elif overrides:
        msg = "Cannot pass keyword overrides when options is provided"
        raise TypeError(msg)

    LOGGER.info(
        "text_search.accepted",
        extra={
            "session_id": session_id,
            "query_preview": _preview_text(query),
            "regex": options.regex,
            "case_sensitive": options.case_sensitive,
            "max_results": options.max_results,
        },
    )

    def _run_sync() -> dict:
        return _search_text_sync(
            context=context,
            session_id=session_id or "",
            scope=scope,
            options=options,
        )

    try:
        result = await asyncio.to_thread(_run_sync)
    except VectorSearchError as exc:
        LOGGER.warning(
            "text_search.failed",
            extra={"session_id": session_id, "error": str(exc)},
        )
        raise

    LOGGER.info(
        "text_search.completed",
        extra={
            "session_id": session_id,
            "results": result.get("total", 0),
            "truncated": result.get("truncated", False),
        },
    )
    return result


def _resolve_glob_filters(
    scope: ScopeIn | None,
    options: TextSearchOptions,
) -> _ResolvedFilters:
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

    explicit_paths = list(options.paths) if options.paths else None
    if explicit_paths and options.include_globs is None:
        include_globs: Sequence[str] | None = None
    else:
        include_globs = merged_filters.get("include_globs")
    exclude_globs = merged_filters.get("exclude_globs")
    return _ResolvedFilters(explicit_paths, include_globs, exclude_globs)


def _search_text_sync(
    context: ApplicationContext,
    session_id: str,
    scope: ScopeIn | None,
    options: TextSearchOptions,
) -> dict:
    repo_root = context.paths.repo_root

    query = options.query

    filters = _resolve_glob_filters(
        scope,
        options,
    )

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
            "effective_paths": filters.paths,
            "effective_include_globs": filters.include_globs,
            "effective_exclude_globs": filters.exclude_globs,
        },
    )

    params = RipgrepCommandParams(
        query=query,
        regex=options.regex,
        case_sensitive=options.case_sensitive,
        include_globs=filters.include_globs,
        exclude_globs=filters.exclude_globs,
        paths=filters.paths,
        max_results=options.max_results,
    )

    cmd = _build_ripgrep_command(params)

    try:
        stdout = run_subprocess(cmd, cwd=repo_root, timeout=SEARCH_TIMEOUT_SECONDS)
    except SubprocessTimeoutError as exc:
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
                repo_root=repo_root,
                query=query,
                options=options,
            )
        else:
            error_message = (exc.stderr or "").strip() or str(exc)
            raise VectorSearchError(
                error_message,
                cause=exc,
                context={"query": query, "returncode": exc.returncode},
            ) from exc
    except ValueError as exc:
        error_msg = str(exc)
        raise VectorSearchError(
            error_msg,
            cause=exc,
            context={"query": query},
        ) from exc

    matches, truncated = _parse_ripgrep_output(stdout, repo_root, options.max_results)
    result = {
        "matches": matches,
        "total": len(matches),
        "truncated": truncated,
    }
    return result


def _fallback_grep(
    *,
    repo_root: Path,
    query: str,
    options: TextSearchOptions,
) -> dict:
    """Fallback to basic grep if ripgrep unavailable.

    Parameters
    ----------
    repo_root : Path
        Repository root directory.
    query : str
        Search query.
    options : TextSearchOptions
        Search configuration controlling case sensitivity and limits.

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

    if not options.case_sensitive:
        command.append("-i")

    command.extend(["--", query, "."])

    try:
        stdout = run_subprocess(command, cwd=repo_root, timeout=SEARCH_TIMEOUT_SECONDS)
    except SubprocessTimeoutError as exc:
        error_msg = "Search tool unavailable"
        raise VectorSearchError(
            error_msg,
            context={"query": query, "tool": "grep"},
        ) from exc
    except SubprocessError as exc:
        if exc.returncode == 1:
            stdout = ""
        else:
            error_message = (exc.stderr or "").strip() or str(exc)
            raise VectorSearchError(
                error_message,
                cause=exc,
                context={"query": query, "tool": "grep", "returncode": exc.returncode},
            ) from exc
    except ValueError as exc:
        error_msg = str(exc)
        raise VectorSearchError(
            error_msg,
            cause=exc,
            context={"query": query, "tool": "grep"},
        ) from exc

    matches: list[Match] = []
    max_results = options.max_results or SEARCH_MAX_RESULTS
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
    result = {
        "matches": matches,
        "total": len(matches),
        "truncated": len(matches) >= max_results,
    }
    return result


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


def _preview_text(value: str, *, limit: int = 200) -> str:
    """Return a truncated preview suitable for span attributes.

    Parameters
    ----------
    value : str
        Text string to truncate. Leading and trailing whitespace is stripped
        before truncation.
    limit : int, optional
        Maximum length of the returned string. If the text exceeds this limit,
        it is truncated and "..." is appended. Defaults to 200.

    Returns
    -------
    str
        Truncated text preview. If the original text (after stripping) is shorter
        than the limit, returns the text unchanged. Otherwise, returns the
        truncated text with "..." appended.
    """
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)] + "..."


__all__ = ["search_text"]
