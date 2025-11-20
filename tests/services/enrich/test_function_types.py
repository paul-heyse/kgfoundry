# SPDX-License-Identifier: MIT
"""Unit tests for per-function typedness analytics."""

from __future__ import annotations

from decimal import Decimal

import libcst as cst
from codeintel_rev.services.enrich.function_types import build_function_types

from tests._helpers import assertions

EXPECTED_PARAM_COUNT = 2
EXPECTED_ANNOTATED_PARAMS = 2
EXPECTED_METHOD_PARAMS = 1


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
    assertions.expect_equal(annotated.total_params, EXPECTED_PARAM_COUNT)
    assertions.expect_equal(annotated.annotated_params, EXPECTED_ANNOTATED_PARAMS)
    assertions.expect_true(annotated.has_return_annotation)
    assertions.expect_true(annotated.fully_typed)
    assertions.expect_equal(annotated.typedness_bucket, "typed")
    partial = indexed["partial"]
    assertions.expect_equal(partial.annotated_params, 1)
    assertions.expect_false(partial.has_return_annotation)
    assertions.expect_true(partial.partial_typed)
    assertions.expect_equal(partial.typedness_bucket, "partial")
    method = indexed["Foo.method"]
    assertions.expect_equal(method.total_params, EXPECTED_METHOD_PARAMS)
    assertions.expect_equal(method.annotated_params, EXPECTED_METHOD_PARAMS)
    assertions.expect_true(method.param_types["self"] is None)
    assertions.expect_equal(method.return_type_source, "annotation")
    assertions.expect_true(isinstance(method.function_goid_h128, Decimal))
