# SPDX-License-Identifier: MIT
"""Unit tests for the GOID builder."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.enrich.goid_builder import GOIDBuilder
from codeintel_rev.services.enrich.io import collect_ast_artifacts

from tests._helpers import assertions


def _write_file(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def test_goid_builder_creates_module_and_function(tmp_path: Path) -> None:
    """GOID builder should emit module and function identifiers."""
    repo = tmp_path / "repo"
    source = repo / "pkg" / "alpha.py"
    _write_file(source, "class Demo:\n    def run(self):\n        return 1\n")
    rows, _ = collect_ast_artifacts(repo, [source])
    builder = GOIDBuilder(repo="demo", commit="deadbeef")
    artifacts = builder.build(rows)
    kinds = {goid.kind for goid in artifacts.goids}
    assertions.expect_true("module" in kinds)
    assertions.expect_true("class" in kinds)
    assertions.expect_true(
        any(x.get("ast_node_type") == "FunctionDef" for x in artifacts.crosswalks),
        reason="Function crosswalk entries were not emitted",
    )
