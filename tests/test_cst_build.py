# SPDX-License-Identifier: MIT
"""Tests for the LibCST dataset builder pipeline."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from codeintel_rev.cst_build.cst_collect import CSTCollector
from codeintel_rev.cst_build.cst_resolve import ModuleRow, SCIPResolver, stitch_nodes
from codeintel_rev.enrich.scip_reader import Document, Occurrence


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
    assert stats.node_rows == len(nodes) > 0
    kinds = {node.kind for node in nodes}
    for required in ("Module", "ClassDef", "FunctionDef", "For", "Return"):
        assert required in kinds
    module_node = next(node for node in nodes if node.kind == "Module")
    assert module_node.doc is not None
    module_doc = module_node.doc.get("module", "")
    assert module_doc.startswith("Top-level")
    helper_node = next(
        node for node in nodes if node.kind == "FunctionDef" and node.name == "helper"
    )
    assert helper_node.doc is not None
    assert "def_" in helper_node.doc
    assert "Sum incoming" in helper_node.doc["def_"]


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
    assert any(name.endswith("Greeter.greet") for name in method_node.qnames)
    assert any(name.startswith("pkg.greeter.") for name in method_node.qnames)
    call_node = next(node for node in nodes if node.kind == "Call" and node.name == "greet")
    targets = call_node.call_target_qnames or []
    assert targets
    assert any(name.startswith("pkg.greeter.") for name in targets)


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
    assert updated.stitch is not None
    assert updated.stitch.module_id == "module::pkg.sample"
    assert updated.stitch.scip_symbol is not None
    assert updated.stitch.scip_symbol.endswith("add#")
    assert counters.module_matches >= 1
    assert counters.scip_matches >= 1


def test_node_id_determinism(tmp_path: Path) -> None:
    """Repeated runs over the same file should yield identical node ids."""
    module_path = _write_module(tmp_path, "demo.py", "def ping() -> None:\n    return None\n")
    collector = CSTCollector(tmp_path, [module_path])
    run_one, _ = collector.collect_file(module_path)
    run_two, _ = collector.collect_file(module_path)
    assert {node.node_id for node in run_one} == {node.node_id for node in run_two}


def test_schema_payload_contains_required_fields(tmp_path: Path) -> None:
    """NodeRecord.to_dict exposes required schema properties."""
    module_path = _write_module(tmp_path, "demo.py", "VALUE = 1\n")
    collector = CSTCollector(tmp_path, [module_path])
    nodes, _ = collector.collect_file(module_path)
    payload = nodes[0].to_dict()
    for key in ("path", "node_id", "kind", "span", "parents", "scope", "qnames"):
        assert key in payload
    span = payload.get("span")
    assert isinstance(span, dict)
    assert isinstance(span.get("start"), list)
