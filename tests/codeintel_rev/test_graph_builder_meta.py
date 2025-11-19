# SPDX-License-Identifier: MIT
"""Tests ensuring graph builder consumes meta import edges."""

from __future__ import annotations

from codeintel_rev.graph_builder import build_import_graph

from tests._helpers import assertions


def test_build_import_graph_uses_meta_import_edges() -> None:
    """Import edges stored in meta payloads should drive graph construction."""
    origin = {"path": "pkg/origin.py", "meta": {"imports": [], "legacy_imports": []}}
    consumer = {
        "path": "pkg/consumer.py",
        "meta": {
            "imports": [
                {
                    "src_module": "pkg.consumer",
                    "dst_module": "pkg.origin",
                    "alias": None,
                    "level": 0,
                }
            ]
        },
    }
    graph = build_import_graph([origin, consumer])
    assertions.expect_equal(graph.edges["pkg/consumer.py"], {"pkg/origin.py"})
    assertions.expect_equal(graph.fan_in["pkg/origin.py"], 1)
    assertions.expect_equal(graph.fan_out["pkg/consumer.py"], 1)
