# SPDX-License-Identifier: MIT
"""Unit tests for per-function metrics analytics."""

from __future__ import annotations

from decimal import Decimal

import libcst as cst
from codeintel_rev.ids.goid import RepoSnapshot
from codeintel_rev.services.enrich.function_metrics import build_function_metrics

from tests._helpers import assertions

EXPECTED_POS_PARAMS = 2
EXPECTED_KEYWORD_ONLY_PARAMS = 1
MIN_COMPLEXITY = 3
MIN_NESTING = 2


def test_function_metrics_capture_control_flow() -> None:
    """Verify metrics capture branching, yields, and raises."""
    code = """
def outer(a: int, b: int, *, flag: bool = False):
    \"\"\"Doc.\"\"\"
    if flag:
        for i in range(2):
            yield i
    else:
        return a + b
    raise ValueError("boom")


class Container:
    @staticmethod
    def run(x):
        return x * 2
"""
    module = cst.parse_module(code)
    rows = build_function_metrics(
        snapshot=RepoSnapshot(repo="repo", commit="commit"),
        rel_path="pkg/mod.py",
        module=module,
        code=code,
        created_at="2024-01-01T00:00:00Z",
    )
    indexed = {row.qualname: row for row in rows}
    outer = indexed["outer"]
    assertions.expect_equal(outer.kind, "function")
    assertions.expect_equal(outer.return_count, 1)
    assertions.expect_equal(outer.yield_count, 1)
    assertions.expect_equal(outer.raise_count, 1)
    assertions.expect_true(outer.is_generator)
    assertions.expect_equal(outer.positional_params, EXPECTED_POS_PARAMS)
    assertions.expect_equal(outer.keyword_only_params, EXPECTED_KEYWORD_ONLY_PARAMS)
    assertions.expect_true(outer.cyclomatic_complexity >= MIN_COMPLEXITY)
    assertions.expect_true(outer.max_nesting_depth >= MIN_NESTING)
    assertions.expect_true(outer.has_docstring)
    assertions.expect_true(isinstance(outer.function_goid_h128, Decimal))
    run_method = indexed["Container.run"]
    assertions.expect_equal(run_method.kind, "method")
    assertions.expect_equal(run_method.return_count, 1)
    assertions.expect_equal(run_method.keyword_only_params, 0)
