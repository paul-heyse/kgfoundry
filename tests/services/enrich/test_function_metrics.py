# SPDX-License-Identifier: MIT
"""Unit tests for per-function metrics analytics."""

from __future__ import annotations

from decimal import Decimal

import libcst as cst
from codeintel_rev.services.enrich.function_metrics import build_function_metrics


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
        repo="repo",
        commit="commit",
        rel_path="pkg/mod.py",
        module=module,
        code=code,
        created_at="2024-01-01T00:00:00Z",
    )
    indexed = {row.qualname: row for row in rows}
    outer = indexed["outer"]
    assert outer.kind == "function"
    assert outer.return_count == 1
    assert outer.yield_count == 1
    assert outer.raise_count == 1
    assert outer.is_generator is True
    assert outer.positional_params == 2
    assert outer.keyword_only_params == 1
    assert outer.cyclomatic_complexity >= 3
    assert outer.max_nesting_depth >= 2
    assert outer.has_docstring is True
    assert isinstance(outer.function_goid_h128, Decimal)
    run_method = indexed["Container.run"]
    assert run_method.kind == "method"
    assert run_method.return_count == 1
    assert run_method.keyword_only_params == 0
