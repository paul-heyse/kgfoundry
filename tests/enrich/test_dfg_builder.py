# SPDX-License-Identifier: MIT
"""DFG-specific regression tests."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.enrich.cfg import CFGBuilder

from tests._helpers import assertions


def _write(path: Path, content: str) -> Path:
    """Write content to file path.

    Parameters
    ----------
    path : Path
        File path to write.
    content : str
        Content to write.

    Returns
    -------
    Path
        Written file path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_dfg_marks_phi_edges_for_branch_merges(tmp_path: Path) -> None:
    """Variables defined in multiple branches should set via_phi on use edges."""
    repo = tmp_path / "repo"
    file_path = _write(
        repo / "pkg" / "flow.py",
        "def combine(flag: bool, value: int) -> int:\n"
        "    if flag:\n"
        "        target = value\n"
        "    else:\n"
        "        target = value + 1\n"
        "    return target\n",
    )
    builder = CFGBuilder(repo_root=repo, repo=str(repo), commit="phi00001")
    artifacts = builder.build([file_path])
    target_defs = [
        edge
        for edge in artifacts.dfg_edges
        if edge["dst_symbol"] == "target" and edge["use_kind"] == "def"
    ]
    assertions.expect_equal(len(target_defs), 2)
    phi_edges = [
        edge
        for edge in artifacts.dfg_edges
        if edge["dst_symbol"] == "target" and edge["use_kind"] == "use" and edge["via_phi"]
    ]
    assertions.expect_true(phi_edges, reason="Use edges should be marked via_phi for merged defs")
