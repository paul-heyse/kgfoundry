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
