"""Regression tests for LibCST codemod transformers and plugins."""

from __future__ import annotations

import textwrap

import libcst as cst
from tools.codemods.blind_except_fix import BlindExceptTransformer
from tools.codemods.pathlib_fix import PathlibTransformer, ensure_pathlib_import


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


# Docstring builder plugin tests removed - docstring_builder module deleted
