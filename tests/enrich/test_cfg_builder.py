# SPDX-License-Identifier: MIT
"""CFG/DFG builder tests."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.enrich.cfg import CFGBuilder

from tests._helpers import assertions


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_cfg_builder_emits_blocks_and_dfg(tmp_path: Path) -> None:
    """Ensure CFG builder emits entry/body/exit blocks and DFG edges."""
    repo = tmp_path / "repo"
    file_path = _write(
        repo / "pkg" / "flow.py",
        "def target(value: int) -> int:\n    total = value + 1\n    return total\n",
    )
    builder = CFGBuilder(repo_root=repo, repo=str(repo), commit="cafebabe")
    artifacts = builder.build([file_path])
    assertions.expect_true(
        any(block["kind"] == "entry" for block in artifacts.blocks),
        reason="CFG missing entry block",
    )
    assertions.expect_true(
        any(block["kind"] == "exit" for block in artifacts.blocks),
        reason="CFG missing exit block",
    )
    assertions.expect_true(artifacts.cfg_edges, reason="Expected CFG edges")
    assertions.expect_true(
        any(edge["use_kind"] == "def" for edge in artifacts.dfg_edges),
        reason="Expected DFG definition edges",
    )
