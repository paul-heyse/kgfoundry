# SPDX-License-Identifier: MIT
"""Tests for the LibCST dataset builder pipeline."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import cast

import pytest
from codeintel_rev.cst_build.cst_collect import CSTCollector
from codeintel_rev.cst_build.cst_resolve import ModuleRow, SCIPResolver, stitch_nodes
from codeintel_rev.enrich.scip_reader import Document, Occurrence

from tests._helpers import assertions


def _write_module(tmp_path: Path, relative: str, content: str) -> Path:
    file_path = tmp_path / relative
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(dedent(content), encoding="utf-8")
    return file_path


@pytest.mark.smoke
def test_index_file_smoke(tmp_path: Path) -> None:
    """Collect nodes for a small file and validate doc capture + node kinds."""
    module_path = _write_module(
        tmp_path,
        "pkg/demo.py",
        """
        \"\"\"Top-level module doc.\"\"\"

        class Handler:
            \"\"\"Handles work.\"\"\"

            def run(self, value: int) -> int:
                \"\"\"Return input doubled.\"\"\"
                return value * 2


        def helper(data: list[int]) -> int:
            \"\"\"Sum incoming data.\"\"\"
            total = 0
            for item in data:
                total += item
            return total
        """,
    )
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    collector = CSTCollector(tmp_path, [module_path])
    nodes, stats = collector.collect_file(module_path)
    assertions.expect_true(
        stats.node_rows == len(nodes) > 0, reason="node_rows should match node count"
    )
    kinds = {node.kind for node in nodes}
    for required in ("Module", "ClassDef", "FunctionDef", "For", "Return"):
        assertions.expect_in(required, kinds)
    module_node = next(node for node in nodes if node.kind == "Module")
    assertions.expect_true(module_node.doc is not None, reason="module_node should have doc")
    if module_node.doc is None:  # pragma: no cover - defensive
        pytest.fail("module_node should have doc")
    module_doc = module_node.doc.get("module", "")
    assertions.expect_true(
        module_doc.startswith("Top-level"), reason="module doc should start with Top-level"
    )
    helper_node = next(
        node for node in nodes if node.kind == "FunctionDef" and node.name == "helper"
    )
    assertions.expect_true(helper_node.doc is not None, reason="helper_node should have doc")
    if helper_node.doc is None:  # pragma: no cover - defensive
        pytest.fail("helper_node should have doc")
    helper_doc = cast("dict[str, object]", helper_node.doc)
    assertions.expect_in("def_", helper_doc)
    def_section = helper_doc.get("def_")
    assertions.expect_true(isinstance(def_section, str), reason="def_ section should be string")
    if isinstance(def_section, str):
        assertions.expect_in("Sum incoming", def_section)


def test_qualified_names_and_call_targets(tmp_path: Path) -> None:
    """Ensure qnames include module context and call targets are populated."""
    module_path = _write_module(
        tmp_path,
        "pkg/greeter.py",
        """
        class Greeter:
            \"\"\"Greets people.\"\"\"

            def greet(self, name: str) -> str:
                \"\"\"Return a greeting.\"\"\"
                return f\"Hello {name}\"


        def run() -> None:
            helper = Greeter()
            helper.greet(\"world\")
        """,
    )
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    collector = CSTCollector(tmp_path, [module_path])
    nodes, _ = collector.collect_file(module_path)
    method_node = next(
        node for node in nodes if node.kind == "FunctionDef" and node.name == "greet"
    )
    assertions.expect_true(
        any(name.endswith("Greeter.greet") for name in method_node.qnames),
        reason="qnames should include Greeter.greet",
    )
    assertions.expect_true(
        any(name.startswith("pkg.greeter.") for name in method_node.qnames),
        reason="qnames should start with pkg.greeter.",
    )
    call_node = next(node for node in nodes if node.kind == "Call" and node.name == "greet")
    targets = call_node.call_target_qnames or []
    assertions.expect_true(bool(targets), reason="call targets should exist")
    assertions.expect_true(
        any(name.startswith("pkg.greeter.") for name in targets),
        reason="targets should start with pkg.greeter.",
    )


def test_stitching_links_module_and_scip(tmp_path: Path) -> None:
    """Stitch nodes to module rows and SCIP occurrences."""
    module_path = _write_module(
        tmp_path,
        "pkg/sample.py",
        """
        def add(a: int, b: int) -> int:
            return a + b
        """,
    )
    collector = CSTCollector(tmp_path, [module_path])
    nodes, _ = collector.collect_file(module_path)
    rel_path = module_path.relative_to(tmp_path).as_posix()
    module_lookup = {rel_path: ModuleRow(module_id="module::pkg.sample", raw={"path": rel_path})}
    add_node = next(node for node in nodes if node.kind == "FunctionDef" and node.name == "add")
    start_line = add_node.span.start_line - 1
    document = Document(
        path=rel_path,
        occurrences=[
            Occurrence(
                symbol="scip-python python test 0.0.0 `pkg.sample`/add#",
                range=[start_line, 0, start_line, 3],
                roles=["Definition"],
            )
        ],
    )
    resolver = SCIPResolver({rel_path: document})
    stitched, counters = stitch_nodes(nodes, module_lookup=module_lookup, scip_resolver=resolver)
    updated = next(node for node in stitched if node.kind == "FunctionDef" and node.name == "add")
    assertions.expect_true(updated.stitch is not None, reason="stitch should be set")
    if updated.stitch is None:  # pragma: no cover - defensive
        pytest.fail("stitch should be set")
    assertions.expect_equal(updated.stitch.module_id, "module::pkg.sample")
    assertions.expect_true(
        updated.stitch.scip_symbol is not None, reason="scip_symbol should be set"
    )
    scip_symbol = updated.stitch.scip_symbol
    if scip_symbol is None:  # pragma: no cover - defensive
        pytest.fail("scip_symbol should be set")
    assertions.expect_true(
        scip_symbol.endswith("add#"), reason="scip_symbol should end with add#"
    )
    assertions.expect_true(counters.module_matches >= 1, reason="should have module matches")
    assertions.expect_true(counters.scip_matches >= 1, reason="should have scip matches")


def test_node_id_determinism(tmp_path: Path) -> None:
    """Repeated runs over the same file should yield identical node ids."""
    module_path = _write_module(tmp_path, "demo.py", "def ping() -> None:\n    return None\n")
    collector = CSTCollector(tmp_path, [module_path])
    run_one, _ = collector.collect_file(module_path)
    run_two, _ = collector.collect_file(module_path)
    assertions.expect_equal({node.node_id for node in run_one}, {node.node_id for node in run_two})


def test_schema_payload_contains_required_fields(tmp_path: Path) -> None:
    """NodeRecord.to_dict exposes required schema properties."""
    module_path = _write_module(tmp_path, "demo.py", "VALUE = 1\n")
    collector = CSTCollector(tmp_path, [module_path])
    nodes, _ = collector.collect_file(module_path)
    payload = nodes[0].to_dict()
    for key in ("path", "node_id", "kind", "span", "parents", "scope", "qnames"):
        assertions.expect_in(key, payload)
    span = payload.get("span")
    assertions.expect_true(isinstance(span, dict), reason="span should be dict")
    if not isinstance(span, dict):  # pragma: no cover - defensive
        pytest.fail("span should be dict")
    assertions.expect_true(isinstance(span.get("start"), list), reason="start should be list")
