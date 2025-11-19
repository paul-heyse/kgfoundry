# SPDX-License-Identifier: MIT
"""Unit tests covering enrichment pipeline stages and helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from codeintel_rev.cli.enrich_pipeline import ScanInputs
from codeintel_rev.enrich.duckdb_store import DuckConn, ingest_modules_jsonl
from codeintel_rev.enrich.models import ModuleRecord
from codeintel_rev.enrich.output_writers import write_markdown_module
from codeintel_rev.enrich.pipeline_helpers import (
    apply_tagging,
    build_module_row,
    outline_nodes_for,
    type_error_count,
)
from codeintel_rev.enrich.scip_reader import Document, Occurrence, SCIPIndex, SymbolInfo
from codeintel_rev.enrich.validators import ModuleRecordModel
from codeintel_rev.typedness import FileTypeSignals

from tests._helpers import assertions


def test_module_record_behaves_like_mapping() -> None:
    """Verify ModuleRecord behaves like a mapping with dict-like access."""
    record = ModuleRecord(
        path="pkg/demo.py",
        repo_path="pkg/demo.py",
        module_name="pkg.demo",
        stable_id="abc123",
    )
    record["fan_in"] = 2
    record.tags = ["cli", "alpha"]
    payload = record.as_json_row()
    assertions.expect_equal(payload["fan_in"], 2)
    assertions.expect_equal(payload["path"], "pkg/demo.py")
    assertions.expect_sequence_equal(payload["tags"], ["alpha", "cli"])


def test_build_module_row_captures_docstring_and_types(
    tmp_path: Path, scan_inputs_builder: Callable[..., ScanInputs]
) -> None:
    """Verify module row building captures docstrings and type error counts."""
    repo = tmp_path / "repo"
    repo.mkdir()
    module = repo / "pkg"
    module.mkdir()
    file_path = module / "alpha.py"
    file_path.write_text('"""Alpha."""\nfrom pkg import beta\n', encoding="utf-8")
    inputs = scan_inputs_builder(
        repo_root=repo,
        type_signals={"pkg/alpha.py": FileTypeSignals(pyrefly_errors=1, pyright_errors=3)},
    )
    record, edges = build_module_row(file_path, repo, inputs)
    assertions.expect_true(isinstance(record, ModuleRecord), reason="record should be ModuleRecord")
    assertions.expect_equal(record["docstring"], "Alpha.")
    assertions.expect_equal(record["type_error_count"], 3)
    assertions.expect_sequence_equal(edges, [])
    meta = record["meta"]
    assertions.expect_true(isinstance(meta, dict), reason="meta payload should be dict")
    assertions.expect_true(meta["docs"]["module_has_doc"])
    assertions.expect_in("imports", meta)
    assertions.expect_true(meta["metrics"]["defs_total"] >= 0)


def test_outline_nodes_for_python() -> None:
    """Verify outline node extraction works for Python code."""
    pytest.importorskip("tree_sitter_python")
    code = "class Foo:\n    def bar(self):\n        return 1\n"
    nodes = outline_nodes_for("pkg/foo.py", code)
    if not nodes:
        pytest.skip("Tree-sitter outline unavailable")
    assertions.expect_true(
        any(node["kind"] == "class_definition" for node in nodes),
        reason="should have class_definition node",
    )


def test_scip_index_groupings() -> None:
    """Verify SCIP index provides file and symbol grouping methods."""
    index = SCIPIndex(
        documents=[
            Document(
                path="pkg/demo.py",
                occurrences=[Occurrence(symbol="sym::demo")],
                symbols=[SymbolInfo(symbol="sym::demo", kind="function")],
            )
        ]
    )
    assertions.expect_equal(index.by_file()["pkg/demo.py"].path, "pkg/demo.py")
    assertions.expect_sequence_equal(index.symbol_to_files()["sym::demo"], ["pkg/demo.py"])
    assertions.expect_equal(index.file_symbol_kinds()["pkg/demo.py"]["sym::demo"], "function")


def test_type_error_count_prefers_max(
    tmp_path: Path, scan_inputs_builder: Callable[..., ScanInputs]
) -> None:
    """Verify type error count prefers maximum of pyrefly and pyright errors."""
    inputs = scan_inputs_builder(
        repo_root=tmp_path,
        type_signals={"pkg/demo.py": FileTypeSignals(pyrefly_errors=1, pyright_errors=4)},
    )
    assertions.expect_equal(type_error_count("pkg/demo.py", inputs), 4)


def test_apply_tagging_assigns_cli_tag() -> None:
    """Verify tagging rules assign CLI tag based on imports."""
    record = ModuleRecord(
        path="pkg/app.py",
        repo_path="pkg/app.py",
        module_name="pkg.app",
        stable_id="id1",
    )
    record["imports"] = [
        {"module": "typer", "names": ["Typer"], "aliases": {}, "is_star": False, "level": 0}
    ]
    apply_tagging([record], {"cli": {"any_import": ["typer"], "reason": "cli detected"}})
    tags = record.get("tags")
    assertions.expect_true(isinstance(tags, list), reason="tags should be list")
    if not isinstance(tags, list):  # pragma: no cover - defensive
        pytest.fail("tags should be a list")
    assertions.expect_in("cli", tags)


def test_write_markdown_module_emits_sections(tmp_path: Path) -> None:
    """Verify markdown module writer emits all expected sections."""
    row: dict[str, Any] = {
        "path": "pkg/app.py",
        "docstring": "Demo module.",
        "imports": [
            {
                "module": "pkg.utils",
                "names": ["helper"],
                "is_star": False,
                "aliases": {},
                "level": 0,
            }
        ],
        "defs": [{"kind": "function", "name": "run", "lineno": 2}],
        "tags": ["cli"],
        "errors": [],
    }
    target = tmp_path / "module.md"
    write_markdown_module(target, row)
    content = target.read_text(encoding="utf-8")
    assertions.expect_in("pkg.utils", content)
    assertions.expect_in("run", content)
    assertions.expect_in("cli", content)


def test_module_record_validator_accepts_payload() -> None:
    """Verify ModuleRecordModel validates payloads correctly."""
    payload = {"path": "pkg/app.py", "docstring": "Doc"}
    validated = ModuleRecordModel.model_validate(payload)
    assertions.expect_equal(validated.path, "pkg/app.py")


def test_duckdb_store_ingest_roundtrip(tmp_path: Path) -> None:
    """Verify DuckDB ingestion round-trip for module records."""
    pytest.importorskip("duckdb")
    jsonl_path = tmp_path / "modules.jsonl"
    row = {"path": "pkg/app.py", "docstring": "demo"}
    jsonl_path.write_text(json.dumps(row), encoding="utf-8")
    conn = DuckConn(db_path=tmp_path / "enrich.duckdb")
    count = ingest_modules_jsonl(conn, jsonl_path)
    assertions.expect_equal(count, 1)
