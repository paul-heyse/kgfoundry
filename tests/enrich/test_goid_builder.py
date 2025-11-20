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


def test_goid_builder_deduplicates_and_sets_chunk_metadata(tmp_path: Path) -> None:
    """GOID builder should deduplicate nodes and emit chunk identifiers."""
    repo = tmp_path / "repo"
    source = repo / "pkg" / "alpha.py"
    _write_file(
        source,
        "class Demo:\n    def run(self) -> int:\n        value = 1\n        return value\n",
    )
    rows, _ = collect_ast_artifacts(repo, [source])
    duplicated_rows = rows + rows  # simulate duplicate AST entries
    builder = GOIDBuilder(repo="demo", commit="cafebabe")
    artifacts = builder.build(duplicated_rows)
    # Expect module + class + method GOIDs (deduplicated)
    assertions.expect_equal(len(artifacts.goids), 3)
    class_rows = [row for row in artifacts.crosswalks if row.get("ast_node_type") == "ClassDef"]
    assertions.expect_true(class_rows, reason="Missing class crosswalk rows")
    chunk_ids = {row.get("chunk_id") for row in class_rows}
    assertions.expect_true(
        any(chunk_id and chunk_id.startswith("pkg/alpha.py:") for chunk_id in chunk_ids),
        reason="Chunk identifiers not recorded in crosswalk rows",
    )
    evidence = class_rows[0].get("evidence_json") or {}
    assertions.expect_equal(evidence.get("node_type"), "ClassDef")
