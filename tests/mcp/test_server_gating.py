from __future__ import annotations

import sys

from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.mcp_server.server import build_http_app


def test_semantic_module_not_imported_without_capability() -> None:
    sys.modules.pop("codeintel_rev.mcp_server.server_semantic", None)
    caps = Capabilities(faiss_index=False, duckdb=False, scip_index=False, vllm_client=False)
    build_http_app(caps)
    assert "codeintel_rev.mcp_server.server_semantic" not in sys.modules


def test_semantic_module_imported_with_capability() -> None:
    sys.modules.pop("codeintel_rev.mcp_server.server_semantic", None)
    caps = Capabilities(faiss_index=True, duckdb=True, scip_index=True, vllm_client=True)
    build_http_app(caps)
    assert "codeintel_rev.mcp_server.server_semantic" in sys.modules


def test_symbol_module_not_imported_without_capability() -> None:
    sys.modules.pop("codeintel_rev.mcp_server.server_symbols", None)
    caps = Capabilities(faiss_index=True, duckdb=False, scip_index=False, vllm_client=True)
    build_http_app(caps)
    assert "codeintel_rev.mcp_server.server_symbols" not in sys.modules


def test_symbol_module_imported_with_capability() -> None:
    sys.modules.pop("codeintel_rev.mcp_server.server_symbols", None)
    caps = Capabilities(faiss_index=True, duckdb=True, scip_index=True, vllm_client=True)
    build_http_app(caps)
    assert "codeintel_rev.mcp_server.server_symbols" in sys.modules
