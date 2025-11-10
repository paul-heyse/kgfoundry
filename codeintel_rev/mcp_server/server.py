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
    return await history_adapter.file_history(context, path, limit)


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

    Returns
    -------
    ASGIApp
        ASGI application implementing the MCP HTTP API.
    """
    if getattr(capabilities, "has_symbols", False):
        importlib.import_module("codeintel_rev.mcp_server.server_symbols")
    if getattr(capabilities, "has_semantic", False):
        importlib.import_module("codeintel_rev.mcp_server.server_semantic")
    return mcp.http_app()


__all__ = ["app_context", "build_http_app", "get_context", "mcp"]
