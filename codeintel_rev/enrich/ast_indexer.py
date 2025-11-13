# SPDX-License-Identifier: MIT
"""AST indexer producing join-ready Parquet datasets."""

from __future__ import annotations

import ast
import logging
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.parquet as pq

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class DefInfo:
    """Intermediate representation for definition nodes with qualnames."""

    node: ast.AST
    name: str | None
    qualname: str | None
    parent_qualname: str | None


@dataclass(slots=True, frozen=True)
class AstNodeRow:
    """Row emitted to ast_nodes.parquet."""

    path: str
    module: str
    qualname: str | None
    name: str | None
    node_type: str
    lineno: int | None
    col: int | None
    end_lineno: int | None
    end_col: int | None
    parent_qualname: str | None
    decorators: tuple[str, ...]
    bases: tuple[str, ...]
    docstring: str | None
    is_public: bool

    def as_record(self) -> dict[str, object]:
        """Return a JSON/Arrow friendly mapping.

        Returns
        -------
        dict[str, object]
            Mapping ready for pyarrow ingestion.
        """
        record = asdict(self)
        record["decorators"] = list(self.decorators)
        record["bases"] = list(self.bases)
        return record


@dataclass(slots=True, frozen=True)
class AstMetricsRow:
    """Row emitted to ast_metrics.parquet."""

    path: str
    module: str
    func_count: int
    class_count: int
    assign_count: int
    import_count: int
    branch_nodes: int
    cyclomatic: int
    cognitive: int
    max_nesting: int
    statements: int

    def as_record(self) -> dict[str, object]:
        """Return a JSON/Arrow friendly mapping.

        Returns
        -------
        dict[str, object]
            Mapping ready for analytics layers.
        """
        return asdict(self)


AST_NODE_SCHEMA = pa.schema(
    [
        pa.field("path", pa.string()),
        pa.field("module", pa.string()),
        pa.field("qualname", pa.string()),
        pa.field("name", pa.string()),
        pa.field("node_type", pa.string()),
        pa.field("lineno", pa.int32()),
        pa.field("col", pa.int32()),
        pa.field("end_lineno", pa.int32()),
        pa.field("end_col", pa.int32()),
        pa.field("parent_qualname", pa.string()),
        pa.field("decorators", pa.list_(pa.string())),
        pa.field("bases", pa.list_(pa.string())),
        pa.field("docstring", pa.string()),
        pa.field("is_public", pa.bool_()),
    ]
)

AST_METRIC_SCHEMA = pa.schema(
    [
        pa.field("path", pa.string()),
        pa.field("module", pa.string()),
        pa.field("func_count", pa.int32()),
        pa.field("class_count", pa.int32()),
        pa.field("assign_count", pa.int32()),
        pa.field("import_count", pa.int32()),
        pa.field("branch_nodes", pa.int32()),
        pa.field("cyclomatic", pa.int32()),
        pa.field("cognitive", pa.int32()),
        pa.field("max_nesting", pa.int32()),
        pa.field("statements", pa.int32()),
    ]
)


def stable_module_path(repo_root: Path, file_path: Path) -> str:
    """Return a repo-relative POSIX path for the given file.

    Parameters
    ----------
    repo_root :
        Root directory used for normalization.
    file_path :
        Absolute or relative file path to normalize.

    Returns
    -------
    str
        POSIX-style path relative to ``repo_root``.
    """
    repo_root_resolved = repo_root.resolve()
    file_resolved = file_path.resolve()
    try:
        rel = file_resolved.relative_to(repo_root_resolved)
    except ValueError:  # pragma: no cover - defensive fallback
        return file_resolved.as_posix()
    return rel.as_posix()


def _module_name_from_path(path: str) -> str:
    candidate = Path(path)
    if candidate.name == "__init__.py":
        parts = candidate.parent.parts
    else:
        parts = candidate.with_suffix("").parts
    if not parts:
        return ""
    return ".".join(parts).replace("\\", ".")


def _safe_unparse(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError, TypeError):  # pragma: no cover - fallback for exotic nodes
        return node.__class__.__name__


def walk_defs_with_qualname(tree: ast.AST) -> Iterator[DefInfo]:
    """Yield definition nodes with fully-qualified names.

    Parameters
    ----------
    tree :
        Parsed module ``ast.AST``.

    Yields
    ------
    DefInfo
        Metadata for each class, function, or async function encountered.
    """
    stack: list[str] = []

    def _visit(node: ast.AST) -> Iterator[DefInfo]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = getattr(child, "name", None)
                parent = ".".join(stack) if stack else None
                qual = ".".join([parent, name]) if parent and name else name
                info = DefInfo(node=child, name=name, qualname=qual, parent_qualname=parent)
                yield info
                if name:
                    stack.append(name)
                    yield from _visit(child)
                    stack.pop()
                else:
                    yield from _visit(child)
            else:
                yield from _visit(child)

    yield from _visit(tree)


def collect_ast_nodes(path: str, code: str) -> list[AstNodeRow]:
    """Parse code and collect node rows for Parquet output.

    Parameters
    ----------
    path :
        Repo-relative module path (POSIX separators).
    code :
        Source code to parse.

    Returns
    -------
    list[AstNodeRow]
        Collected module/class/function rows.
    """
    try:
        tree = ast.parse(code, filename=path, type_comments=True)
    except SyntaxError:
        LOGGER.exception("Failed to parse %s for AST node collection", path)
        return []
    return collect_ast_nodes_from_tree(path, tree)


def collect_ast_nodes_from_tree(path: str, tree: ast.AST) -> list[AstNodeRow]:
    """Collect AstNodeRow entries from a pre-parsed AST module.

    Parameters
    ----------
    path :
        Repo-relative module path (POSIX separators).
    tree :
        Parsed module tree from :mod:`ast`.

    Returns
    -------
    list[AstNodeRow]
        Rows ready for serialization.
    """
    module = _module_name_from_path(path)
    module_node = cast("ast.Module", tree)
    rows: list[AstNodeRow] = []
    docstring = ast.get_docstring(module_node, clean=True)
    rows.append(
        AstNodeRow(
            path=path,
            module=module,
            qualname=module or None,
            name=module or None,
            node_type="Module",
            lineno=1,
            col=0,
            end_lineno=getattr(tree, "end_lineno", None),
            end_col=getattr(tree, "end_col_offset", None),
            parent_qualname=None,
            decorators=(),
            bases=(),
            docstring=docstring,
            is_public=True,
        )
    )
    for info in walk_defs_with_qualname(tree):
        lineno = getattr(info.node, "lineno", None)
        end_lineno = getattr(info.node, "end_lineno", None)
        col = getattr(info.node, "col_offset", None)
        end_col = getattr(info.node, "end_col_offset", None)
        node_type = info.node.__class__.__name__
        decorators: tuple[str, ...] = ()
        bases: tuple[str, ...] = ()
        node_doc = (
            ast.get_docstring(info.node, clean=True)
            if isinstance(info.node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            else None
        )
        if isinstance(info.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = tuple(
                value
                for expr in info.node.decorator_list or []
                if (value := _safe_unparse(expr)) is not None
            )
        if isinstance(info.node, ast.ClassDef):
            decorators = tuple(
                value
                for expr in info.node.decorator_list or []
                if (value := _safe_unparse(expr)) is not None
            )
            bases = tuple(
                value
                for expr in info.node.bases or []
                if (value := _safe_unparse(expr)) is not None
            )
        rows.append(
            AstNodeRow(
                path=path,
                module=module,
                qualname=info.qualname,
                name=info.name,
                node_type=node_type,
                lineno=lineno,
                col=col,
                end_lineno=end_lineno,
                end_col=end_col,
                parent_qualname=info.parent_qualname,
                decorators=decorators,
                bases=bases,
                docstring=node_doc,
                is_public=bool(info.name and not info.name.startswith("_")),
            )
        )
    return rows


def compute_ast_metrics(path: str, tree: ast.AST) -> AstMetricsRow:
    """Compute per-file metrics from a parsed AST.

    Parameters
    ----------
    path :
        Repo-relative module path (POSIX separators).
    tree :
        Parsed AST tree for the module.

    Returns
    -------
    AstMetricsRow
        Aggregate metrics row describing the module.
    """
    module = _module_name_from_path(path)
    visitor = _MetricsVisitor()
    visitor.visit(tree)
    cyclomatic = 1 + visitor.branch_nodes
    cognitive = cyclomatic + visitor.max_nesting
    return AstMetricsRow(
        path=path,
        module=module,
        func_count=visitor.func_count,
        class_count=visitor.class_count,
        assign_count=visitor.assign_count,
        import_count=visitor.import_count,
        branch_nodes=visitor.branch_nodes,
        cyclomatic=cyclomatic,
        cognitive=cognitive,
        max_nesting=visitor.max_nesting,
        statements=visitor.statements,
    )


def empty_metrics_row(path: str) -> AstMetricsRow:
    """Return a zeroed metrics row for parse failures.

    Parameters
    ----------
    path :
        Repo-relative module path (POSIX separators).

    Returns
    -------
    AstMetricsRow
        Metrics row with zeros for all counters.
    """
    module = _module_name_from_path(path)
    return AstMetricsRow(
        path=path,
        module=module,
        func_count=0,
        class_count=0,
        assign_count=0,
        import_count=0,
        branch_nodes=0,
        cyclomatic=0,
        cognitive=0,
        max_nesting=0,
        statements=0,
    )


def write_ast_parquet(
    nodes: Sequence[AstNodeRow],
    metrics: Sequence[AstMetricsRow],
    *,
    out_dir: Path,
) -> None:
    """Persist AST datasets to Parquet files expected by DuckDB."""
    out_dir.mkdir(parents=True, exist_ok=True)
    node_table = _table_from_rows(nodes, AST_NODE_SCHEMA)
    metric_table = _table_from_rows(metrics, AST_METRIC_SCHEMA)
    pq.write_table(node_table, out_dir / "ast_nodes.parquet")
    pq.write_table(metric_table, out_dir / "ast_metrics.parquet")


RowType = AstNodeRow | AstMetricsRow


def _table_from_rows(rows: Sequence[RowType], schema: pa.Schema) -> pa.Table:
    if not rows:
        empty_arrays = [pa.array([], type=field.type) for field in schema]
        return pa.Table.from_arrays(empty_arrays, schema=schema)
    as_dicts = [row.as_record() for row in rows]
    return pa.Table.from_pylist(as_dicts, schema=schema)


class _MetricsVisitor(ast.NodeVisitor):  # lint-ignore[PLR0904]: visitor needs dedicated methods
    """Collects aggregate counts for AST metrics."""

    BRANCH_NODES = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.IfExp,
        ast.Match,
    )

    def __init__(self) -> None:
        self.func_count = 0
        self.class_count = 0
        self.assign_count = 0
        self.import_count = 0
        self.branch_nodes = 0
        self.statements = 0
        self.max_nesting = 0
        self._current_nesting = 0

    def generic_visit(self, node: ast.AST) -> None:
        """Visit a generic AST node and increment statement counter if applicable.

        This method is called for nodes that don't have a specific visitor method.
        It increments the statement counter for statement nodes and then calls
        the parent class's generic_visit to continue traversal.

        Parameters
        ----------
        node : ast.AST
            Generic AST node being visited. If the node is a statement, the
            statement counter is incremented.
        """
        if isinstance(node, ast.stmt):
            self.statements += 1
        super().generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit a function definition and increment function counter.

        Parameters
        ----------
        node : ast.FunctionDef
            AST node representing a function definition (e.g., ``def func(): ...``).
        """
        self.func_count += 1
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit a class definition and increment class counter.

        Parameters
        ----------
        node : ast.ClassDef
            AST node representing a class definition (e.g., ``class MyClass: ...``).
        """
        self.class_count += 1
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Visit an assignment statement and increment assignment counter.

        Parameters
        ----------
        node : ast.Assign
            AST node representing an assignment statement (e.g., ``x = 1``, ``a, b = 1, 2``).
        """
        self.assign_count += 1
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """Visit an import statement and increment import counter.

        Parameters
        ----------
        node : ast.Import
            AST node representing an import statement (e.g., ``import os``).
        """
        self.import_count += 1
        self.generic_visit(node)

    def branch_visit(self, node: ast.AST) -> None:
        """Increment branch metrics for complex control-flow nodes."""
        self._with_branch(self.generic_visit, node)

    def _with_branch(self, visitor: Callable[[ast.AST], None], node: ast.AST) -> None:
        self.branch_nodes += 1
        self._current_nesting += 1
        self.max_nesting = max(self.max_nesting, self._current_nesting)
        visitor(node)
        self._current_nesting -= 1


for _alias, _target in (
    ("visit_AsyncFunctionDef", _MetricsVisitor.visit_FunctionDef),
    ("visit_AnnAssign", _MetricsVisitor.visit_Assign),
    ("visit_AugAssign", _MetricsVisitor.visit_Assign),
    ("visit_NamedExpr", _MetricsVisitor.visit_Assign),
    ("visit_ImportFrom", _MetricsVisitor.visit_Import),
):
    setattr(_MetricsVisitor, _alias, _target)

for _alias in (
    "visit_ListComp",
    "visit_SetComp",
    "visit_DictComp",
    "visit_GeneratorExp",
    "visit_BoolOp",
    "visit_If",
    "visit_IfExp",
    "visit_For",
    "visit_AsyncFor",
    "visit_While",
    "visit_Try",
    "visit_With",
    "visit_AsyncWith",
    "visit_Match",
):
    setattr(_MetricsVisitor, _alias, _MetricsVisitor.branch_visit)


__all__ = [
    "AST_METRIC_SCHEMA",
    "AST_NODE_SCHEMA",
    "AstMetricsRow",
    "AstNodeRow",
    "DefInfo",
    "collect_ast_nodes",
    "collect_ast_nodes_from_tree",
    "compute_ast_metrics",
    "empty_metrics_row",
    "stable_module_path",
    "walk_defs_with_qualname",
    "write_ast_parquet",
]
