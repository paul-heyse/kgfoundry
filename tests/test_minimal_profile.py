from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import sys
from types import ModuleType

import pytest
from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.mcp_server.server import build_http_app


@pytest.mark.parametrize(
    "missing_modules",
    [
        {"faiss", "duckdb", "torch", "numpy"},
    ],
)
def test_import_package_in_minimal_env(
    monkeypatch: pytest.MonkeyPatch, missing_modules: set[str]
) -> None:
    """Simulate a minimal environment where heavy deps are unavailable."""
    original_specs = importlib.util.find_spec

    def fake_find_spec(
        name: str, package: str | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        if name in missing_modules:
            return None
        return original_specs(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    cached: dict[str, ModuleType] = {
        key: module for key, module in list(sys.modules.items()) if key.startswith("codeintel_rev")
    }
    for key in list(sys.modules):
        if key.startswith("codeintel_rev"):
            sys.modules.pop(key)

    importlib.invalidate_caches()

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
    assert "codeintel_rev.mcp_server.server_semantic" not in sys.modules
    assert "codeintel_rev.mcp_server.server_symbols" in sys.modules
