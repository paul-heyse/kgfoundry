"""Tests for MCP server module gating based on capabilities."""

from __future__ import annotations

import sys

from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.mcp_server.server import build_http_app

from tests._helpers import assertions


def test_semantic_module_not_imported_without_capability() -> None:
    """Verify semantic module is not imported when capabilities are missing."""
    sys.modules.pop("codeintel_rev.mcp_server.server_semantic", None)
    caps = Capabilities(faiss_index=False, duckdb=False, scip_index=False, vllm_client=False)
    build_http_app(caps)
    assertions.expect_false(
        "codeintel_rev.mcp_server.server_semantic" in sys.modules,
        reason="semantic module should not be imported without capabilities",
    )


def test_semantic_module_imported_with_capability() -> None:
    """Verify semantic module is imported when all capabilities are present."""
    sys.modules.pop("codeintel_rev.mcp_server.server_semantic", None)
    caps = Capabilities(faiss_index=True, duckdb=True, scip_index=True, vllm_client=True)
    build_http_app(caps)
    assertions.expect_in("codeintel_rev.mcp_server.server_semantic", sys.modules)


def test_symbol_module_not_imported_without_capability() -> None:
    """Verify symbol module is not imported without scip_index capability."""
    sys.modules.pop("codeintel_rev.mcp_server.server_symbols", None)
    caps = Capabilities(faiss_index=True, duckdb=False, scip_index=False, vllm_client=True)
    build_http_app(caps)
    assertions.expect_false(
        "codeintel_rev.mcp_server.server_symbols" in sys.modules,
        reason="symbols module should not be imported without scip_index",
    )


def test_symbol_module_imported_with_capability() -> None:
    """Verify symbol module is imported when scip_index capability is present."""
    sys.modules.pop("codeintel_rev.mcp_server.server_symbols", None)
    caps = Capabilities(faiss_index=True, duckdb=True, scip_index=True, vllm_client=True)
    build_http_app(caps)
    assertions.expect_in("codeintel_rev.mcp_server.server_symbols", sys.modules)
