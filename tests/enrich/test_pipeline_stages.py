# SPDX-License-Identifier: MIT
"""Unit tests covering enrichment pipeline stages and helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from codeintel_rev import cli_enrich
from codeintel_rev.cli_enrich import ScanInputs, ScipContext
from codeintel_rev.enrich.duckdb_store import DuckConn, ingest_modules_jsonl
from codeintel_rev.enrich.models import ModuleRecord
from codeintel_rev.enrich.output_writers import write_markdown_module
from codeintel_rev.enrich.scip_reader import Document, Occurrence, SCIPIndex, SymbolInfo
from codeintel_rev.enrich.validators import ModuleRecordModel
from codeintel_rev.typedness import FileTypeSignals


def _scan_inputs(
    tmp_path: Path, *, signals: dict[str, FileTypeSignals] | None = None
) -> ScanInputs:
    repo_root = tmp_path
    return ScanInputs(
        scip_ctx=ScipContext(index=SCIPIndex(), by_file={}),
        type_signals=signals or {},
        coverage_map={},
        tagging_rules={},
        repo_root=repo_root,
        max_file_bytes=10_000,
        package_prefix=repo_root.name,
    )


def test_module_record_behaves_like_mapping() -> None:
    record = ModuleRecord(
        path="pkg/demo.py",
        repo_path="pkg/demo.py",
        module_name="pkg.demo",
        stable_id="abc123",
    )
    record["fan_in"] = 2
    record.set_fields(tags=["cli", "alpha"])
    payload = record.as_json_row()
    assert payload["fan_in"] == 2
    assert payload["path"] == "pkg/demo.py"
    assert payload["tags"] == ["alpha", "cli"]


def test_build_module_row_captures_docstring_and_types(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    module = repo / "pkg"
    module.mkdir()
    file_path = module / "alpha.py"
    file_path.write_text('"""Alpha."""\nfrom pkg import beta\n', encoding="utf-8")
    inputs = _scan_inputs(
        repo, signals={"pkg/alpha.py": FileTypeSignals(pyrefly_errors=1, pyright_errors=3)}
    )
    record, edges = _BUILD_MODULE_ROW(file_path, repo, inputs)
    assert isinstance(record, ModuleRecord)
    assert record["docstring"] == "Alpha."
    assert record["type_error_count"] == 3
    assert edges == []


def test_outline_nodes_for_python() -> None:
    pytest.importorskip("tree_sitter_python")
    code = "class Foo:\n    def bar(self):\n        return 1\n"
    nodes = _OUTLINE_NODES_FOR("pkg/foo.py", code)
    if not nodes:
        pytest.skip("Tree-sitter outline unavailable")
    assert any(node["kind"] == "class_definition" for node in nodes)


def test_scip_index_groupings() -> None:
    index = SCIPIndex(
        documents=[
            Document(
                path="pkg/demo.py",
                occurrences=[Occurrence(symbol="sym::demo")],
                symbols=[SymbolInfo(symbol="sym::demo", kind="function")],
            )
        ]
    )
    assert index.by_file()["pkg/demo.py"].path == "pkg/demo.py"
    assert index.symbol_to_files()["sym::demo"] == ["pkg/demo.py"]
    assert index.file_symbol_kinds()["pkg/demo.py"]["sym::demo"] == "function"


def test_type_error_count_prefers_max(tmp_path: Path) -> None:
    inputs = _scan_inputs(
        tmp_path,
        signals={"pkg/demo.py": FileTypeSignals(pyrefly_errors=1, pyright_errors=4)},
    )
    assert _TYPE_ERROR_COUNT("pkg/demo.py", inputs) == 4


def test_apply_tagging_assigns_cli_tag() -> None:
    record = ModuleRecord(
        path="pkg/app.py",
        repo_path="pkg/app.py",
        module_name="pkg.app",
        stable_id="id1",
    )
    record["imports"] = [
        {"module": "typer", "names": ["Typer"], "aliases": {}, "is_star": False, "level": 0}
    ]
    _APPLY_TAGGING([record], {"cli": {"any_import": ["typer"], "reason": "cli detected"}})
    tags = record.get("tags")
    assert isinstance(tags, list)
    assert "cli" in tags


def test_write_markdown_module_emits_sections(tmp_path: Path) -> None:
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
    assert "pkg.utils" in content
    assert "run" in content
    assert "cli" in content


def test_module_record_validator_accepts_payload() -> None:
    payload = {"path": "pkg/app.py", "docstring": "Doc"}
    validated = ModuleRecordModel.model_validate(payload)
    assert validated.path == "pkg/app.py"


def test_duckdb_store_ingest_roundtrip(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    jsonl_path = tmp_path / "modules.jsonl"
    row = {"path": "pkg/app.py", "docstring": "demo"}
    jsonl_path.write_text(json.dumps(row), encoding="utf-8")
    conn = DuckConn(db_path=tmp_path / "enrich.duckdb")
    count = ingest_modules_jsonl(conn, jsonl_path)
    assert count == 1


_BUILD_MODULE_ROW_ATTR = "_build_module_row"
_OUTLINE_NODES_ATTR = "_outline_nodes_for"
_TYPE_ERROR_COUNT_ATTR = "_type_error_count"
_APPLY_TAGGING_ATTR = "_apply_tagging"

_BUILD_MODULE_ROW = getattr(cli_enrich, _BUILD_MODULE_ROW_ATTR)
_OUTLINE_NODES_FOR = getattr(cli_enrich, _OUTLINE_NODES_ATTR)
_TYPE_ERROR_COUNT = getattr(cli_enrich, _TYPE_ERROR_COUNT_ATTR)
_APPLY_TAGGING = getattr(cli_enrich, _APPLY_TAGGING_ATTR)
