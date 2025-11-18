"""Tests for minimal import profile with optional dependencies."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest
from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.mcp_server.server import build_http_app

from tests._helpers import assertions
from tests._helpers.imports import with_module_presence


@pytest.mark.parametrize(
    "missing_modules",
    [
        {"faiss", "duckdb", "torch", "numpy"},
    ],
)
def test_import_package_in_minimal_env(missing_modules: set[str]) -> None:
    """Simulate a minimal environment where heavy deps are unavailable."""
    modules_override = dict.fromkeys(missing_modules, None)

    cached: dict[str, ModuleType] = {
        key: module for key, module in list(sys.modules.items()) if key.startswith("codeintel_rev")
    }
    for key in list(sys.modules):
        if key.startswith("codeintel_rev"):
            sys.modules.pop(key)

    importlib.invalidate_caches()

    with with_module_presence(modules_override):
        try:
            __import__("codeintel_rev")
        finally:
            for key in list(sys.modules):
                if key.startswith("codeintel_rev"):
                    sys.modules.pop(key)
            sys.modules.update(cached)


def test_server_factory_omits_semantic_modules() -> None:
    """Ensure semantic modules aren't imported when capability is absent."""
    sys.modules.pop("codeintel_rev.mcp_server.server_semantic", None)
    sys.modules.pop("codeintel_rev.mcp_server.server_symbols", None)

    caps = Capabilities(duckdb=True, scip_index=True)
    build_http_app(caps)
    assertions.expect_false(
        "codeintel_rev.mcp_server.server_semantic" in sys.modules,
        reason="semantic modules should not be imported when capability is absent",
    )
    assertions.expect_true(
        "codeintel_rev.mcp_server.server_symbols" in sys.modules,
        reason="symbol modules should be imported when scip_index capability is present",
    )
