"""Tests covering Tarjan strongly connected components."""

from __future__ import annotations

from codeintel_rev.enrich.graph.tarjan import tarjan_scc

from tests._helpers import assertions


def test_tarjan_scc_detects_cycles() -> None:
    """Verify strongly connected components group cyclical nodes."""
    edges = {
        "a": {"b"},
        "b": {"a", "c"},
        "c": set(),
        "d": {"e"},
        "e": {"d"},
    }
    components = tarjan_scc(edges)
    assertions.expect_equal(components["a"], components["b"])
    assertions.expect_true(components["c"] != components["a"])
    assertions.expect_equal(components["d"], components["e"])
