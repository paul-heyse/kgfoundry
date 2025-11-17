# SPDX-License-Identifier: MIT
"""Tests covering Tree-sitter outline capture."""

from __future__ import annotations

import pytest
from codeintel_rev.enrich import tree_sitter_bridge as tsb

from tests._helpers import assertions


def test_outline_query_matches_fallback() -> None:
    """Test that Tree-sitter outline query matches fallback behavior."""
    pytest.importorskip("tree_sitter_python")

    source = b"""
class Foo:
    def method(self) -> None:
        pass

def helper(value: int) -> int:
    return value
"""

    with tsb.override_outline_config(use_ts_query=True):
        query_outline = tsb.build_outline("demo.py", source)
    if query_outline is None:
        pytest.skip("Tree-sitter python language unavailable")
    query_symbols = {(node.kind, node.name) for node in query_outline.nodes}
    assertions.expect_true(bool(query_symbols), reason="query_outline should have symbols")

    with tsb.override_outline_config(use_ts_query=False):
        dfs_outline = tsb.build_outline("demo.py", source)
    if dfs_outline is None:
        pytest.skip("Tree-sitter python language unavailable")
    dfs_symbols = {(node.kind, node.name) for node in dfs_outline.nodes}
    assertions.expect_equal(dfs_symbols, query_symbols)
