# SPDX-License-Identifier: MIT
"""Per-function structural and complexity metrics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal

import libcst as cst
from libcst import MetadataWrapper
from libcst.helpers import get_docstring

from codeintel_rev.ids.goid import RepoSnapshot
from codeintel_rev.services.enrich.function_analysis import (
    BaseFunctionVisitor,
    FunctionInfo,
    FunctionNode,
    count_parameters,
)


@dataclass(slots=True, frozen=True)
class FunctionMetricsRow:
    """Serialized metrics for a single function or method."""

    function_goid_h128: Decimal
    urn: str
    repo: str
    commit: str
    rel_path: str
    language: str
    kind: str
    qualname: str
    start_line: int
    end_line: int
    loc: int
    logical_loc: int
    param_count: int
    positional_params: int
    keyword_only_params: int
    has_varargs: bool
    has_varkw: bool
    is_async: bool
    is_generator: bool
    return_count: int
    yield_count: int
    raise_count: int
    cyclomatic_complexity: int
    max_nesting_depth: int
    stmt_count: int
    decorator_count: int
    has_docstring: bool
    complexity_bucket: str
    created_at: str


@dataclass(slots=True, frozen=True)
class _BodyMetrics:
    return_count: int
    yield_count: int
    raise_count: int
    decision_points: int
    max_depth: int


class _BodyMetricsVisitor(cst.CSTVisitor):
    def __init__(self) -> None:
        self.return_count = 0
        self.yield_count = 0
        self.raise_count = 0
        self.decision_points = 0
        self._depth = 0
        self._max_depth = 0

    @property
    def max_depth(self) -> int:
        return self._max_depth

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:  # noqa: N802
        return False

    def visit_AsyncFunctionDef(self, node: cst.AsyncFunctionDef) -> bool:  # noqa: N802
        return False

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:  # noqa: N802
        return False

    def visit_Lambda(self, node: cst.Lambda) -> bool:  # noqa: N802
        return False

    def visit_Return(self, node: cst.Return) -> None:  # noqa: N802
        self.return_count += 1

    def visit_Raise(self, node: cst.Raise) -> None:  # noqa: N802
        self.raise_count += 1

    def visit_Yield(self, node: cst.Yield) -> None:  # noqa: N802
        self.yield_count += 1

    def visit_YieldFrom(self, node: cst.YieldFrom) -> None:  # noqa: N802
        self.yield_count += 1

    def visit_BooleanOperation(self, node: cst.BooleanOperation) -> None:  # noqa: N802
        self.decision_points += 1

    def visit_IfExp(self, node: cst.IfExp) -> None:  # noqa: N802
        self.decision_points += 1

    def visit_If(self, node: cst.If) -> None:  # noqa: N802
        self._enter()

    def leave_If(self, original_node: cst.If) -> None:  # noqa: N802
        self._leave()

    def visit_For(self, node: cst.For) -> None:  # noqa: N802
        self._enter()

    def leave_For(self, original_node: cst.For) -> None:  # noqa: N802
        self._leave()

    def visit_AsyncFor(self, node: cst.AsyncFor) -> None:  # noqa: N802
        self._enter()

    def leave_AsyncFor(self, original_node: cst.AsyncFor) -> None:  # noqa: N802
        self._leave()

    def visit_While(self, node: cst.While) -> None:  # noqa: N802
        self._enter()

    def leave_While(self, original_node: cst.While) -> None:  # noqa: N802
        self._leave()

    def visit_With(self, node: cst.With) -> None:  # noqa: N802
        self._enter()

    def leave_With(self, original_node: cst.With) -> None:  # noqa: N802
        self._leave()

    def visit_AsyncWith(self, node: cst.AsyncWith) -> None:  # noqa: N802
        self._enter()

    def leave_AsyncWith(self, original_node: cst.AsyncWith) -> None:  # noqa: N802
        self._leave()

    def visit_Try(self, node: cst.Try) -> None:  # noqa: N802
        self._enter()

    def leave_Try(self, original_node: cst.Try) -> None:  # noqa: N802
        self._leave()

    def _enter(self) -> None:
        self.decision_points += 1
        self._depth += 1
        self._max_depth = max(self._max_depth, self._depth)

    def _leave(self) -> None:
        self._depth = max(self._depth - 1, 0)


class FunctionMetricsVisitor(BaseFunctionVisitor):
    """Collect metrics rows for all functions in a module."""

    def __init__(
        self,
        *,
        snapshot: RepoSnapshot,
        rel_path: str,
        code_lines: Sequence[str],
        created_at: str,
    ) -> None:
        super().__init__(snapshot=snapshot, rel_path=rel_path)
        self._code_lines = code_lines
        self._created_at = created_at
        self.rows: list[FunctionMetricsRow] = []

    def process_function(self, info: FunctionInfo) -> None:
        if info.start_line <= 0 or info.end_line <= 0 or info.end_line < info.start_line:
            return
        body_metrics = _function_body_metrics(info.node)
        param_counts = count_parameters(info.node)
        loc = (info.end_line - info.start_line) + 1
        logical_loc = _logical_loc(info.start_line, info.end_line, self._code_lines)
        stmt_count = _statement_count(info.node)
        cyclomatic = 1 + body_metrics.decision_points
        self.rows.append(
            FunctionMetricsRow(
                function_goid_h128=Decimal(info.goid.h128),
                urn=info.goid.urn,
                repo=info.goid.repo,
                commit=info.goid.commit,
                rel_path=info.goid.rel_path,
                language=info.goid.language,
                kind=info.kind,
                qualname=info.qualname,
                start_line=info.start_line,
                end_line=info.end_line,
                loc=loc,
                logical_loc=logical_loc,
                param_count=param_counts.total,
                positional_params=param_counts.positional,
                keyword_only_params=param_counts.keyword_only,
                has_varargs=param_counts.has_varargs,
                has_varkw=param_counts.has_varkw,
                is_async=info.is_async,
                is_generator=body_metrics.yield_count > 0,
                return_count=body_metrics.return_count,
                yield_count=body_metrics.yield_count,
                raise_count=body_metrics.raise_count,
                cyclomatic_complexity=cyclomatic,
                max_nesting_depth=body_metrics.max_depth,
                stmt_count=stmt_count,
                decorator_count=len(info.node.decorators),
                has_docstring=bool(get_docstring(info.node)),
                complexity_bucket=_complexity_bucket(cyclomatic),
                created_at=self._created_at,
            )
        )


def _function_body_metrics(node: FunctionNode) -> _BodyMetrics:
    visitor = _BodyMetricsVisitor()
    node.body.visit(visitor)
    return _BodyMetrics(
        return_count=visitor.return_count,
        yield_count=visitor.yield_count,
        raise_count=visitor.raise_count,
        decision_points=visitor.decision_points,
        max_depth=visitor.max_depth,
    )


def _statement_count(node: FunctionNode) -> int:
    statements = list(node.body.body)
    if statements and _is_docstring_statement(statements[0]):
        statements = statements[1:]
    return len(statements)


def _is_docstring_statement(statement: cst.BaseStatement) -> bool:
    if not isinstance(statement, cst.SimpleStatementLine):
        return False
    if not statement.body:
        return False
    first = statement.body[0]
    return isinstance(first, cst.Expr) and isinstance(first.value, cst.SimpleString)


def _logical_loc(start_line: int, end_line: int, code_lines: Sequence[str]) -> int:
    begin = max(start_line - 1, 0)
    finish = min(end_line, len(code_lines))
    count = 0
    for line in code_lines[begin:finish]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        count += 1
    return count


def _complexity_bucket(cyclomatic: int) -> str:
    if cyclomatic <= 5:
        return "low"
    if cyclomatic <= 10:
        return "medium"
    return "high"


def build_function_metrics(
    *,
    repo: str,
    commit: str,
    rel_path: str,
    module: cst.Module,
    code: str,
    created_at: str | None = None,
) -> list[FunctionMetricsRow]:
    """Return per-function metrics for ``module``."""
    snapshot = RepoSnapshot(repo=repo, commit=commit)
    wrapper = MetadataWrapper(module)
    timestamp = created_at or datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    visitor = FunctionMetricsVisitor(
        snapshot=snapshot,
        rel_path=rel_path,
        code_lines=code.splitlines(),
        created_at=timestamp,
    )
    wrapper.visit(visitor)
    return visitor.rows


def prepare_function_metrics_parquet(
    rows: Sequence[FunctionMetricsRow],
) -> list[dict[str, object]]:
    """Return Parquet-friendly payloads for metrics rows."""
    return [asdict(row) for row in rows]


def prepare_function_metrics_json(
    rows: Sequence[FunctionMetricsRow],
) -> list[dict[str, object]]:
    """Return JSON-serializable payloads for metrics rows."""
    serialized: list[dict[str, object]] = []
    for row in rows:
        record = asdict(row)
        record["function_goid_h128"] = str(record["function_goid_h128"])
        serialized.append(record)
    return serialized


__all__ = [
    "FunctionMetricsRow",
    "build_function_metrics",
    "prepare_function_metrics_json",
    "prepare_function_metrics_parquet",
]
