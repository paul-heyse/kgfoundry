"""Tests for LibCST bridge module analysis functionality."""

from __future__ import annotations

from codeintel_rev.enrich.libcst_bridge import (
    analyze_module_from_code,
    index_module,
)

from tests._helpers import assertions


def test_index_module_compatibility() -> None:
    """Ensure legacy ModuleIndex output remains available."""
    code = "\n".join(
        [
            '"""Mod doc."""',
            "import os as operating_system",
            "from pkg import sub as alias",
            "__all__ = ['Foo']",
            "class Foo:",
            "    pass",
            "def bar(x: int) -> int:",
            "    return x",
        ]
    )
    idx = index_module("pkg/mod.py", code)
    assertions.expect_equal(idx.docstring, "Mod doc.")
    assertions.expect_true(any(entry.names == ["os"] for entry in idx.imports))
    assertions.expect_true(any(entry.aliases.get("sub") == "alias" for entry in idx.imports))
    assertions.expect_equal(idx.exports, {"Foo"})
    assertions.expect_true(any(defn.name == "Foo" for defn in idx.defs))
    assertions.expect_equal(idx.annotation_ratio["params"], idx.annotation_ratio["returns"])


def test_module_analysis_edges_and_docs() -> None:
    """Expose basic ModuleAnalysis output for downstream tooling."""
    code = "\n".join(
        [
            '"""Alpha."""',
            "from . import util",
            "def fn(x: int) -> int:",
            '    """Fn doc."""',
            "    return x",
        ]
    )
    analysis = analyze_module_from_code("pkg/mod.py", code)
    assertions.expect_equal(analysis.module, "pkg.mod")
    assertions.expect_equal(analysis.docs.module_docstring, "Alpha.")
    assertions.expect_true(analysis.docs.module_has_doc)
    assertions.expect_true(analysis.metrics.defs_total >= 1)
    assertions.expect_true(any(edge.dst_module.endswith("util") for edge in analysis.imports))
