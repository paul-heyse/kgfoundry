# SPDX-License-Identifier: MIT
"""Tests covering Tree-sitter outline capture."""

from __future__ import annotations

import pytest


def test_outline_query_matches_fallback(monkeypatch):
    pytest.importorskip("tree_sitter_python")
    from codeintel_rev.enrich import tree_sitter_bridge as tsb

    source = b"""
class Foo:
    def method(self) -> None:
        pass

def helper(value: int) -> int:
    return value
"""

    monkeypatch.setattr(tsb, "_USE_TS_QUERY", True)
    query_outline = tsb.build_outline("demo.py", source)
    if query_outline is None:
        pytest.skip("Tree-sitter python language unavailable")
    query_symbols = {(node.kind, node.name) for node in query_outline.nodes}
    assert query_symbols

    monkeypatch.setattr(tsb, "_USE_TS_QUERY", False)
    dfs_outline = tsb.build_outline("demo.py", source)
    if dfs_outline is None:
        pytest.skip("Tree-sitter python language unavailable")
    dfs_symbols = {(node.kind, node.name) for node in dfs_outline.nodes}
    assert dfs_symbols == query_symbols
