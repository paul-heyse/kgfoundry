# SPDX-License-Identifier: MIT
"""Unit tests for per-function typedness analytics."""

from __future__ import annotations

from decimal import Decimal

import libcst as cst
from codeintel_rev.services.enrich.function_types import build_function_types


def test_function_types_flags_typedness_states() -> None:
    """Verify typedness buckets and counts derive from annotations."""
    code = """
def annotated(x: int, y: str) -> str:
    return y


def partial(a, b: int):
    return a + b


class Foo:
    def method(self, value: int) -> None:
        return None
"""
    module = cst.parse_module(code)
    rows = build_function_types(
        repo="repo",
        commit="commit",
        rel_path="pkg/demo.py",
        module=module,
        created_at="2024-01-01T00:00:00Z",
    )
    indexed = {row.qualname: row for row in rows}
    annotated = indexed["annotated"]
    assert annotated.total_params == 2
    assert annotated.annotated_params == 2
    assert annotated.has_return_annotation is True
    assert annotated.fully_typed is True
    assert annotated.typedness_bucket == "typed"
    partial = indexed["partial"]
    assert partial.annotated_params == 1
    assert partial.has_return_annotation is False
    assert partial.partial_typed is True
    assert partial.typedness_bucket == "partial"
    method = indexed["Foo.method"]
    assert method.total_params == 1
    assert method.annotated_params == 1
    assert method.param_types["self"] is None
    assert method.return_type_source == "annotation"
    assert isinstance(method.function_goid_h128, Decimal)
