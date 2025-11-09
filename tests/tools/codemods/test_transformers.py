"""Regression tests for LibCST codemod transformers and plugins."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import libcst as cst
from tools.codemods.blind_except_fix import BlindExceptTransformer
from tools.codemods.pathlib_fix import PathlibTransformer, ensure_pathlib_import
from tools.docstring_builder.config import BuilderConfig
from tools.docstring_builder.harvest import ParameterHarvest, SymbolHarvest
from tools.docstring_builder.parameters import ParameterKind
from tools.docstring_builder.plugins.base import PluginContext
from tools.docstring_builder.plugins.dataclass_fields import DataclassFieldDocPlugin
from tools.docstring_builder.schema import DocstringSchema, ParameterDoc
from tools.docstring_builder.semantics import SemanticResult

if TYPE_CHECKING:
    from pathlib import Path


def test_blind_except_transformer_records_changes() -> None:
    source = textwrap.dedent(
        """
        try:
            pass
        except:
            pass
        """
    )
    module = cst.parse_module(source)
    transformer = BlindExceptTransformer()
    result = module.visit(transformer)

    assert transformer.changes == ["bare except: → TODO + exception variable"]
    assert "except Exception as exc" in result.code


def test_pathlib_transformer_tracks_updates() -> None:
    source = textwrap.dedent(
        """
        import os

        def build(path):
            os.makedirs(path)
            with open(os.path.join(path, "file")) as handle:
                return os.path.exists(path)
        """
    )
    module = cst.parse_module(source)
    transformer = PathlibTransformer()
    result = module.visit(transformer)

    assert transformer.changes  # changes captured
    assert "os.makedirs" in " ".join(transformer.changes)

    if transformer.needs_pathlib_import:
        result = ensure_pathlib_import(result)
    assert "import pathlib" in result.code


def _build_dataclass_semantic_result(
    file_path: Path,
    parameters: list[tuple[str, str | None, str | None]],
) -> SemanticResult:
    symbol = SymbolHarvest(
        qname="example.Example",
        module="example",
        kind="class",
        parameters=[
            ParameterHarvest(
                name=name,
                kind=ParameterKind.POSITIONAL_OR_KEYWORD,
                annotation=annotation,
                default=default,
            )
            for name, annotation, default in parameters
        ],
        return_annotation=None,
        docstring=None,
        owned=True,
        filepath=file_path,
        lineno=1,
        end_lineno=None,
        col_offset=0,
        decorators=["dataclass"],
        is_async=False,
        is_generator=False,
    )
    schema = DocstringSchema(summary="Describe Example.")
    return SemanticResult(symbol=symbol, schema=schema)


def test_dataclass_field_plugin_caches_metadata(tmp_path: Path) -> None:
    initial_source = textwrap.dedent(
        """
        from dataclasses import dataclass

        @dataclass
        class Example:
            name: str
            count: int = 1
        """
    )
    file_path = tmp_path / "example.py"
    file_path.write_text(initial_source, encoding="utf-8")

    plugin = DataclassFieldDocPlugin()
    context = PluginContext(config=BuilderConfig(), repo_root=tmp_path, file_path=file_path)
    initial_result = _build_dataclass_semantic_result(
        file_path,
        [
            ("name", "str", None),
            ("count", "int", "1"),
        ],
    )

    plugin.on_start(context)
    updated = plugin.apply(context, initial_result)

    name_doc = next((param for param in updated.schema.parameters if param.name == "name"), None)
    assert isinstance(name_doc, ParameterDoc)
    assert "Configure the name" in name_doc.description

    updated_source = textwrap.dedent(
        """
        from dataclasses import dataclass

        @dataclass
        class Example:
            name: str
            count: int = 1
            enabled: bool = False
        """
    )
    file_path.write_text(updated_source, encoding="utf-8")
    result_with_enabled = _build_dataclass_semantic_result(
        file_path,
        [
            ("name", "str", None),
            ("count", "int", "1"),
            ("enabled", "bool", "False"),
        ],
    )

    cached = plugin.apply(context, result_with_enabled)
    assert not any(param.name == "enabled" for param in cached.schema.parameters)

    plugin.on_finish(context)
    plugin.on_start(context)
    refreshed = plugin.apply(context, result_with_enabled)
    assert any(param.name == "enabled" for param in refreshed.schema.parameters)
