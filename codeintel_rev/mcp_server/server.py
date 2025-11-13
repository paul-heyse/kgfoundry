"""FastMCP server with QueryScope tools.

Implements full MCP tool catalog for code intelligence.
"""

from __future__ import annotations

import contextvars
import importlib

from fastmcp import FastMCP
from starlette.types import ASGIApp

from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.mcp_server.adapters import files as files_adapter
from codeintel_rev.mcp_server.adapters import history as history_adapter
from codeintel_rev.mcp_server.adapters import text_search as text_search_adapter
from codeintel_rev.mcp_server.error_handling import handle_adapter_errors
from codeintel_rev.mcp_server.schemas import ScopeIn
from codeintel_rev.mcp_server.telemetry import tool_operation_scope
from codeintel_rev.observability.reporting import latest_run_report

# Create FastMCP instance
mcp = FastMCP("CodeIntel MCP")

# Context variable for storing ApplicationContext per request
# This is set by middleware in main.py and accessed by tool handlers
# Made public for testing purposes (tests need to mock this)
app_context: contextvars.ContextVar[ApplicationContext | None] = contextvars.ContextVar(
    "app_context", default=None
)


def get_context() -> ApplicationContext:
    """Extract ApplicationContext from context variable.

    The context is set by middleware in main.py for each request.
    This allows tool handlers to access ApplicationContext without
    requiring Request injection (which FastMCP doesn't support).

    Returns
    -------
    ApplicationContext
        Application context for the current request.

    Raises
    ------
    RuntimeError
        If context is not initialized (should never happen after startup).
    """
    context = app_context.get()
    if context is None:
        msg = "ApplicationContext not initialized in request context"
        raise RuntimeError(msg)
    return context


# ==================== Scope & Navigation ====================


@mcp.tool()
async def set_scope(scope: ScopeIn) -> dict:
    """Set query scope for subsequent operations.

    Parameters
    ----------
    scope : ScopeIn
        Scope parameters (repos, branches, paths, languages).

    Returns
    -------
    dict
        Effective scope configuration.
    """
    context = get_context()
    with tool_operation_scope("scope.set", has_scope=bool(scope)):
        return await files_adapter.set_scope(context, scope)


@mcp.tool()
@handle_adapter_errors(
    operation="files:list_paths",
    empty_result={"items": [], "total": 0, "truncated": False},
)
async def list_paths(
    path: str | None = None,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    languages: list[str] | None = None,
    max_results: int = 1000,
) -> dict:
    """List files in scope (async).

    Error handling is automatic via decorator. All exceptions are caught
    and converted to unified error envelopes with Problem Details.

    Parameters
    ----------
    path : str | None
        Starting path (defaults to repo root).
    include_globs : list[str] | None
        Glob patterns to include.
    exclude_globs : list[str] | None
        Glob patterns to exclude.
    languages : list[str] | None
        Programming languages to include.
    max_results : int
        Maximum results to return.

    Returns
    -------
    dict
        File listing with paths. On error, returns error envelope with
        empty result fields and Problem Details.
    """
    context = get_context()
    filters_present = bool(path or include_globs or exclude_globs or languages)
    with tool_operation_scope(
        "files.list_paths",
        max_results=max_results,
        has_filters=filters_present,
    ):
        return await files_adapter.list_paths(
            context,
            path=path,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            languages=languages,
            max_results=max_results,
        )


@mcp.tool()
@handle_adapter_errors(
    operation="files:open_file",
    empty_result={"path": "", "content": "", "lines": 0, "size": 0},
)
def open_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict:
    """Read file content.

    Error handling is automatic via decorator. All exceptions are caught
    and converted to unified error envelopes with Problem Details.

    Parameters
    ----------
    path : str
        File path.
    start_line : int | None
        Start line (1-indexed, inclusive).
    end_line : int | None
        End line (1-indexed, inclusive).

    Returns
    -------
    dict
        File content and metadata. On error, returns error envelope with
        empty result fields and Problem Details.
    """
    context = get_context()
    with tool_operation_scope(
        "files.open_file",
        has_range=start_line is not None or end_line is not None,
    ):
        return files_adapter.open_file(context, path, start_line, end_line)


# ==================== Search ====================


@mcp.tool()
@handle_adapter_errors(
    operation="search:text",
    empty_result={"matches": [], "total": 0, "truncated": False},
)
async def search_text(
    query: str,
    *,
    regex: bool = False,
    case_sensitive: bool = False,
    paths: list[str] | None = None,
    max_results: int = 50,
) -> dict:
    """Fast text search (ripgrep-like).

    Error handling is automatic via decorator. All exceptions are caught
    and converted to unified error envelopes with Problem Details.

    Parameters
    ----------
    query : str
        Search query.
    regex : bool
        Treat query as regex.
    case_sensitive : bool
        Case-sensitive search.
    paths : list[str] | None
        Paths to search in.
    max_results : int
        Maximum results.

    Returns
    -------
    dict
        Search matches. On error, returns error envelope with empty result
        fields and Problem Details.
    """
    context = get_context()
    with tool_operation_scope(
        "search.text",
        query_chars=len(query),
        regex=regex,
        case_sensitive=case_sensitive,
        max_results=max_results,
    ):
        return await text_search_adapter.search_text(
            context,
            query,
            regex=regex,
            case_sensitive=case_sensitive,
            paths=paths,
            max_results=max_results,
        )


# ==================== Git History ====================


@mcp.tool()
@handle_adapter_errors(
    operation="git:blame_range",
    empty_result={"blame": []},
)
async def blame_range(
    path: str,
    start_line: int,
    end_line: int,
) -> dict:
    """Git blame for line range (async).

    Error handling is automatic via decorator. All exceptions are caught
    and converted to unified error envelopes with Problem Details.

    Parameters
    ----------
    path : str
        File path.
    start_line : int
        Start line (1-indexed).
    end_line : int
        End line (1-indexed).

    Returns
    -------
    dict
        Blame entries for each line. On error, returns error envelope with
        empty result fields and Problem Details.
    """
    context = get_context()
    with tool_operation_scope(
        "git.blame_range",
        path=path,
        start_line=start_line,
        end_line=end_line,
    ):
        return await history_adapter.blame_range(context, path, start_line, end_line)


@mcp.tool()
@handle_adapter_errors(
    operation="git:file_history",
    empty_result={"commits": []},
)
async def file_history(
    path: str,
    limit: int = 50,
) -> dict:
    """Get file commit history (async).

    Error handling is automatic via decorator. All exceptions are caught
    and converted to unified error envelopes with Problem Details.

    Parameters
    ----------
    path : str
        File path.
    limit : int
        Maximum commits.

    Returns
    -------
    dict
        Commit history. On error, returns error envelope with empty result
        fields and Problem Details.
    """
    context = get_context()
    with tool_operation_scope(
        "git.file_history",
        path=path,
        limit=limit,
    ):
        return await history_adapter.file_history(context, path, limit)


@mcp.tool(name="report:latest_run")
def report_latest_run() -> dict[str, object]:
    """Return metadata about the most recent run report artifact.

    Returns
    -------
    dict[str, object]
        Dictionary containing report metadata. When a report is available,
        includes keys: "available" (True), "run_id", "session_id", "markdown_path",
        "json_path", and "summary". When no report is available, returns
        {"available": False}.
    """
    report = latest_run_report()
    if report is None:
        return {"available": False}
    return {
        "available": True,
        "run_id": report["run_id"],
        "session_id": report["session_id"],
        "markdown_path": str(report["markdown"]),
        "json_path": str(report["json"]),
        "summary": report["summary"],
    }


# ==================== Resources ====================


@mcp.resource("file://{path}")
def file_resource(path: str) -> str:
    """Serve file content as resource.

    Parameters
    ----------
    path : str
        File path.

    Returns
    -------
    str
        File content.
    """
    context = get_context()
    file_result = files_adapter.open_file(context, path)
    if "error" in file_result:
        return f"Error reading file {path}: {file_result['error']}"
    return file_result.get("content", "")


# ==================== Prompts ====================


@mcp.prompt()
def prompt_code_review(area: str) -> str:
    """Code review prompt template.

    Parameters
    ----------
    area : str
        Code area to review.

    Returns
    -------
    str
        Prompt template.
    """
    return f"Review the code in {area}. Focus on correctness, performance, and style."


def build_http_app(capabilities: Capabilities) -> ASGIApp:
    """Return the FastMCP ASGI app with capability-gated tool registration.

    Extended Summary
    ----------------
    This function constructs the FastMCP ASGI application with capability-based
    tool registration. It conditionally imports and registers MCP tools based on
    available capabilities (symbol search, semantic search). Tools are only
    registered if their required dependencies are available, enabling graceful
    degradation when optional components are missing.

    Parameters
    ----------
    capabilities : Capabilities
        Capability snapshot indicating which features are available. Used to gate
        tool registration (e.g., symbol search requires SCIP index, semantic search
        requires FAISS index).

    Returns
    -------
    ASGIApp
        ASGI application implementing the MCP HTTP API with capability-gated tools.
        The app exposes MCP-compliant endpoints for registered tools.

    Notes
    -----
    This function performs dynamic tool registration based on capabilities. Tools
    are registered by importing their modules, which triggers FastMCP decorator
    registration. Time complexity: O(1) for app construction, O(tool_count) for
    tool registration where tool_count is the number of available tools.
    """
    if getattr(capabilities, "has_symbols", False):
        importlib.import_module("codeintel_rev.mcp_server.server_symbols")
    if getattr(capabilities, "has_semantic", False):
        importlib.import_module("codeintel_rev.mcp_server.server_semantic")
    return mcp.http_app()


__all__ = ["app_context", "build_http_app", "get_context", "mcp"]
