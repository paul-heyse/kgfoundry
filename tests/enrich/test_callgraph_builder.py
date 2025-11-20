# SPDX-License-Identifier: MIT
"""Call graph builder tests."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.enrich.callgraph import CallGraphBuilder

from tests._helpers import assertions


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_callgraph_builder_resolves_local_calls(tmp_path: Path) -> None:
    """Ensure local function calls resolve to GOIDs."""
    repo = tmp_path / "repo"
    file_path = _write(
        repo / "pkg" / "demo.py",
        "def callee() -> int:\n    return 1\n\ndef caller() -> int:\n    return callee()\n",
    )
    builder = CallGraphBuilder(repo_root=repo, repo=str(repo), commit="deadbeef")
    artifacts = builder.build([file_path])
    assertions.expect_true(
        any(node["kind"] == "function" for node in artifacts.nodes),
        reason="Call node list is empty",
    )
    resolved = [edge for edge in artifacts.edges if edge.get("callee_goid_h128")]
    assertions.expect_true(resolved, reason="Expected resolved caller->callee edges")


def test_callgraph_builder_resolves_from_imports(tmp_path: Path) -> None:
    """Call graph should resolve functions imported from sibling modules."""
    repo = tmp_path / "repo"
    callee = _write(
        repo / "pkg" / "alpha.py",
        "def helper() -> int:\n    return 1\n",
    )
    caller = _write(
        repo / "pkg" / "beta.py",
        "from pkg.alpha import helper\n\ndef execute() -> int:\n    return helper()\n",
    )
    builder = CallGraphBuilder(repo_root=repo, repo=str(repo), commit="deadbeef")
    artifacts = builder.build([callee, caller])
    edges = [edge for edge in artifacts.edges if edge.get("callsite_path") == "pkg/beta.py"]
    assertions.expect_true(edges, reason="No call edges recorded for import scenario")
    assertions.expect_equal(edges[0].get("resolved_via"), "imported-function")
    assertions.expect_true(edges[0].get("callee_goid_h128"))


def test_callgraph_builder_resolves_module_alias_methods(tmp_path: Path) -> None:
    """Imported modules referenced via alias should resolve class methods."""
    repo = tmp_path / "repo"
    module = _write(
        repo / "pkg" / "widgets.py",
        "class Widget:\n    @staticmethod\n    def build() -> int:\n        return 1\n",
    )
    caller = _write(
        repo / "pkg" / "service.py",
        "import pkg.widgets as widgets\n\n"
        "def orchestrate() -> int:\n"
        "    return widgets.Widget.build()\n",
    )
    builder = CallGraphBuilder(repo_root=repo, repo=str(repo), commit="cafebabe")
    artifacts = builder.build([module, caller])
    edges = [edge for edge in artifacts.edges if edge.get("callsite_path") == "pkg/service.py"]
    assertions.expect_true(edges, reason="Call edges missing for module alias invocation")
    assertions.expect_equal(edges[0].get("resolved_via"), "imported-module")
    assertions.expect_true(edges[0].get("callee_goid_h128"))
