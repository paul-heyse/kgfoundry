# SPDX-License-Identifier: MIT
"""LibCST-powered index utilities (imports, defs, exports, docstrings)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import libcst as cst
from libcst import metadata as cst_metadata
from libcst.helpers import (
    get_full_name_for_node,
)

try:  # pragma: no cover - optional dependency
    from docstring_parser import parse as parse_docstring
except ImportError:  # pragma: no cover - optional dependency
    parse_docstring = None


@dataclass(slots=True, frozen=True)
class ImportEntry:
    """Normalized metadata for a single import statement."""

    module: str | None
    names: list[str]
    aliases: dict[str, str]
    is_star: bool
    level: int


@dataclass(slots=True, frozen=True)
class DefEntry:
    """Top-level function/class definition summary."""

    kind: str  # "class" | "function" | "variable"
    name: str
    lineno: int


@dataclass(slots=True, frozen=True)
class ModuleIndex:
    """Aggregate module metadata returned by :func:`index_module`."""

    path: str
    imports: list[ImportEntry] = field(default_factory=list)
    defs: list[DefEntry] = field(default_factory=list)
    exports: set[str] = field(default_factory=set)
    docstring: str | None = None
    doc_summary: str | None = None
    doc_metrics: dict[str, bool] = field(
        default_factory=lambda: {
            "has_summary": False,
            "param_parity": True,
            "examples_present": False,
        }
    )
    doc_items: list[dict[str, Any]] = field(default_factory=list)
    annotation_ratio: dict[str, float] = field(
        default_factory=lambda: {"params": 1.0, "returns": 1.0}
    )
    untyped_defs: int = 0
    side_effects: dict[str, bool] = field(
        default_factory=lambda: {
            "filesystem": False,
            "network": False,
            "subprocess": False,
            "database": False,
        }
    )
    raises: list[str] = field(default_factory=list)
    complexity: dict[str, int] = field(
        default_factory=lambda: {"branches": 0, "cyclomatic": 1, "loc": 0}
    )
    parse_ok: bool = True
    errors: list[str] = field(default_factory=list)


def _extract_module_docstring(node: cst.Module) -> str | None:
    """Return the module docstring if present.

    Parameters
    ----------
    node : cst.Module
        LibCST module node to extract docstring from.

    Returns
    -------
    str | None
        Module docstring text when available, or None if no docstring exists.
    """
    if not node.body:
        return None
    first_stmt = node.body[0]
    if not isinstance(first_stmt, cst.SimpleStatementLine):
        return None
    expr = first_stmt.body[0] if first_stmt.body else None
    if isinstance(expr, cst.Expr) and isinstance(expr.value, cst.SimpleString):
        with suppress(ValueError):
            evaluated = expr.value.evaluated_value
            if isinstance(evaluated, bytes):
                return evaluated.decode("utf-8", "ignore")
            if isinstance(evaluated, str):
                return evaluated
            return str(evaluated)
    return None


def _literal_string_values(node: cst.BaseExpression) -> Iterator[str]:
    """Yield literal string values from constant containers.

    Parameters
    ----------
    node : cst.BaseExpression
        LibCST expression node (list, tuple, set, or string literal) containing
        literal string values to extract.

    Yields
    ------
    str
        Literal names included in ``__all__`` definitions.
    """
    containers = (cst.List, cst.Tuple, cst.Set)
    if isinstance(node, containers):
        for raw_element in node.elements:
            element_value = getattr(raw_element, "value", None)
            if isinstance(element_value, cst.SimpleString):
                with suppress(ValueError):
                    evaluated = element_value.evaluated_value
                    if isinstance(evaluated, bytes):
                        yield evaluated.decode("utf-8", "ignore")
                    elif isinstance(evaluated, str):
                        yield evaluated
                    else:
                        yield str(evaluated)
            elif isinstance(node, cst.SimpleString):
                with suppress(ValueError):
                    evaluated = node.evaluated_value
                    if isinstance(evaluated, bytes):
                        yield evaluated.decode("utf-8", "ignore")
                    elif isinstance(evaluated, str):
                        yield evaluated
                    else:
                        yield str(evaluated)


def _extract_def_docstring(body: cst.BaseSuite) -> str | None:
    if not getattr(body, "body", None):
        return None
    first_stmt = body.body[0]
    if isinstance(first_stmt, cst.SimpleStatementLine) and first_stmt.body:
        expr = first_stmt.body[0]
        if isinstance(expr, cst.Expr) and isinstance(expr.value, cst.SimpleString):
            with suppress(ValueError):
                evaluated = expr.value.evaluated_value
                if isinstance(evaluated, bytes):
                    return evaluated.decode("utf-8", "ignore")
                if isinstance(evaluated, str):
                    return evaluated
                return str(evaluated)
    return None


def _summarize_docstring(text: str, max_length: int = 200) -> str:
    summary = text.strip().splitlines()[0].strip() if text else ""
    if parse_docstring is not None:
        with suppress(Exception):
            parsed = parse_docstring(text)
            if parsed.short_description:
                summary = parsed.short_description.strip()
    if len(summary) > max_length:
        summary = summary[: max_length - 3] + "..."
    return summary


def _analyze_docstring(
    text: str | None,
    param_names: list[str],
) -> tuple[str | None, bool, bool, bool]:
    if not text:
        return None, False, False, False
    summary = _summarize_docstring(text)
    has_summary = bool(summary)
    documented_params: set[str] = set()
    has_examples = ">>>" in text or "examples" in text.lower()
    if parse_docstring is not None:
        with suppress(Exception):
            parsed = parse_docstring(text)
            if parsed.short_description:
                summary = parsed.short_description.strip()
                has_summary = True
            documented_params = {param.arg_name for param in parsed.params if param.arg_name}
            has_examples = has_examples or bool(parsed.examples)
    filtered_params = [name for name in param_names if name not in {"self", "cls"}]
    if filtered_params:
        parity = bool(documented_params) and set(filtered_params).issubset(documented_params)
    else:
        parity = True
    return (summary or None, has_summary, parity, has_examples)


def _iter_params(params: cst.Parameters) -> Iterator[cst.Param]:
    for collection in (
        params.posonly_params,
        params.params,
        params.kwonly_params,
    ):
        for param in collection:
            if isinstance(param, cst.Param):
                yield param
    if isinstance(params.star_arg, cst.Param):
        yield params.star_arg
    if isinstance(params.star_kwarg, cst.Param):
        yield params.star_kwarg


def _exception_name(expr: cst.BaseExpression | None) -> str | None:
    """Extract exception name from LibCST expression node.

    Parameters
    ----------
    expr : cst.BaseExpression | None
        LibCST expression node representing an exception type, or None.

    Returns
    -------
    str | None
        Dot-separated exception name (e.g., "ValueError" or "kgfoundry.errors.KgFoundryError"),
        or None if the expression cannot be resolved to a name.
    """
    if expr is None:
        return None
    if isinstance(expr, cst.Name):
        return expr.value
    if isinstance(expr, cst.Attribute):
        parts = []
        current: cst.BaseExpression | None = expr
        while isinstance(current, cst.Attribute):
            parts.append(current.attr.value)
            current = current.value
        if isinstance(current, cst.Name):
            parts.append(current.value)
            return ".".join(reversed(parts))
    return None


def _infer_side_effects(imports: set[str], code: str) -> dict[str, bool]:
    lowered = code.lower()

    def has_any(prefixes: tuple[str, ...]) -> bool:
        return any(mod.startswith(prefix) for prefix in prefixes for mod in imports)

    filesystem = has_any(("os", "pathlib", "shutil", "tarfile", "zipfile")) or "open(" in lowered
    network = (
        has_any(("http", "urllib", "requests", "httpx", "aiohttp", "socket"))
        or "requests." in lowered
    )
    subprocess = has_any(("subprocess", "asyncio")) or "subprocess." in lowered
    database = has_any(("sqlite3", "duckdb", "psycopg", "sqlalchemy", "pymongo", "redis"))

    return {
        "filesystem": filesystem,
        "network": network,
        "subprocess": subprocess,
        "database": database,
    }


class _IndexVisitor(cst.CSTVisitor):
    """Collect module metadata via a single LibCST traversal."""

    METADATA_DEPENDENCIES = (cst_metadata.PositionProvider,)

    def __init__(self, code: str) -> None:
        self.imports: list[ImportEntry] = []
        self.defs: list[DefEntry] = []
        self.exports: set[str] = set()
        self.docstring: str | None = None
        self.doc_summary: str | None = None
        self.doc_metrics: dict[str, bool] = {
            "has_summary": False,
            "param_parity": True,
            "examples_present": False,
        }
        self.doc_items: list[dict[str, Any]] = []
        self.annotation_ratio: dict[str, float] = {"params": 1.0, "returns": 1.0}
        self.untyped_defs = 0
        self.side_effects = _infer_side_effects(set(), code)
        self.complexity: dict[str, int] = {
            "branches": 0,
            "cyclomatic": 1,
            "loc": max(1, code.count("\n") + 1),
        }
        self.raises: list[str] = []
        self._class_depth = 0
        self._function_depth = 0
        self._code = code
        self._branch_count = 0
        self._raise_names: set[str] = set()
        self._imported_modules: set[str] = set()
        self._annotation_counts = {
            "params_total": 0,
            "params_annotated": 0,
            "returns_total": 0,
            "returns_annotated": 0,
        }
        self._untyped_defs = 0

    def on_visit(self, node: cst.CSTNode) -> bool:  # lint-ignore[C901,PLR0912]: visitor must handle many node shapes
        branch_nodes: tuple[type[cst.CSTNode], ...] = (
            cst.If,
            cst.For,
            cst.While,
            cst.Try,
            cst.With,
            cst.IfExp,
            cst.BooleanOperation,
        )
        optional_nodes = [
            getattr(cst, "AsyncFor", None),
            getattr(cst, "AsyncWith", None),
            getattr(cst, "Match", None),
        ]
        branch_nodes += tuple(node for node in optional_nodes if isinstance(node, type))
        if isinstance(node, branch_nodes):
            self._branch_count += 1
        if isinstance(node, cst.Raise):
            name = _exception_name(getattr(node, "exc", None))
            if name:
                self._raise_names.add(name)

        is_top_level = self._class_depth == 0 and self._function_depth == 0
        if isinstance(node, cst.Module):
            self.docstring = _extract_module_docstring(node)
            if self.docstring:
                self.doc_summary = _summarize_docstring(self.docstring)
                if self.doc_summary:
                    self.doc_metrics["has_summary"] = True
        elif isinstance(node, cst.Import):
            self._handle_import(node)
        elif isinstance(node, cst.ImportFrom):
            self._handle_import_from(node)
        elif isinstance(node, cst.FunctionDef):
            if is_top_level:
                self._handle_function_def(node)
            self._function_depth += 1
        elif isinstance(node, cst.ClassDef):
            if is_top_level:
                self._handle_class_def(node)
            self._class_depth += 1
        elif isinstance(node, cst.Assign) and is_top_level:
            self._handle_assign(node)
        elif isinstance(node, cst.AnnAssign) and is_top_level:
            self._handle_ann_assign(node)
        return True

    def on_leave(self, original_node: cst.CSTNode) -> None:
        if isinstance(original_node, cst.FunctionDef):
            self._function_depth = max(0, self._function_depth - 1)
        elif isinstance(original_node, cst.ClassDef):
            self._class_depth = max(0, self._class_depth - 1)

    def finalize(self) -> None:
        params_total = self._annotation_counts["params_total"]
        params_annotated = self._annotation_counts["params_annotated"]
        returns_total = self._annotation_counts["returns_total"]
        returns_annotated = self._annotation_counts["returns_annotated"]
        self.annotation_ratio = {
            "params": (params_annotated / params_total) if params_total else 1.0,
            "returns": (returns_annotated / returns_total) if returns_total else 1.0,
        }
        self.untyped_defs = self._untyped_defs
        self.side_effects = _infer_side_effects(self._imported_modules, self._code)
        loc_value = self.complexity.get("loc", 0)
        self.complexity = {
            "branches": self._branch_count,
            "cyclomatic": self._branch_count + 1,
            "loc": loc_value,
        }
        self.raises = sorted(self._raise_names)
        if self.doc_summary:
            self.doc_metrics["has_summary"] = True

    def _handle_import(self, node: cst.Import) -> None:
        names: list[str] = []
        aliases: dict[str, str] = {}
        for alias in node.names:
            ident = alias.name
            dotted = None
            with suppress(Exception):
                dotted = get_full_name_for_node(ident)
            if isinstance(ident, cst.Name):
                value = ident.value
            elif dotted:
                value = dotted
            elif isinstance(ident, cst.Attribute):
                value = ident.attr.value
            else:
                value = ""
            names.append(value)
            if value:
                self._imported_modules.add(value)
            if isinstance(alias.asname, cst.AsName) and isinstance(alias.asname.name, cst.Name):
                aliases[value] = alias.asname.name.value
        self.imports.append(
            ImportEntry(module=None, names=names, aliases=aliases, is_star=False, level=0)
        )

    def _handle_import_from(self, node: cst.ImportFrom) -> None:  # lint-ignore[C901]: parsing import variants requires branching
        is_star = isinstance(node.names, cst.ImportStar)
        names: list[str] = []
        aliases: dict[str, str] = {}
        if not is_star:
            alias_nodes = cast("Sequence[cst.ImportAlias]", node.names)
            for ref in alias_nodes:
                ident = ref.name
                dotted = None
                with suppress(Exception):
                    dotted = get_full_name_for_node(ident)
                if isinstance(ident, cst.Name):
                    value = ident.value
                elif dotted:
                    value = dotted
                elif isinstance(ident, cst.Attribute):
                    value = ident.attr.value
                else:
                    value = ""
                names.append(value)
                if isinstance(ref.asname, cst.AsName) and isinstance(ref.asname.name, cst.Name):
                    aliases[value] = ref.asname.name.value
        module = None
        if node.module:
            with suppress(Exception):  # pragma: no cover - LibCST helper may raise
                module = get_full_name_for_node(node.module)
        level = len(node.relative or [])
        if module:
            self._imported_modules.add(module)
            for name in names:
                if name:
                    self._imported_modules.add(f"{module}.{name}")
        self.imports.append(
            ImportEntry(
                module=module,
                names=names,
                aliases=aliases,
                is_star=is_star,
                level=level,
            )
        )

    def _handle_function_def(self, node: cst.FunctionDef) -> None:
        lineno = _lineno(self, node)
        self.defs.append(DefEntry(kind="function", name=node.name.value, lineno=lineno))
        self._record_function_doc(node, lineno)

    def _record_function_doc(self, node: cst.FunctionDef, lineno: int) -> None:
        name = node.name.value
        is_public = not name.startswith("_")
        params = list(_iter_params(node.params))
        filtered_params = [
            param.name.value
            for param in params
            if isinstance(param.name, cst.Name) and param.name.value not in {"self", "cls"}
        ]
        annotated = sum(
            1
            for param in params
            if isinstance(param, cst.Param)
            and param.annotation is not None
            and isinstance(param.name, cst.Name)
            and param.name.value not in {"self", "cls"}
        )
        self._annotation_counts["params_total"] += len(filtered_params)
        self._annotation_counts["params_annotated"] += annotated
        self._annotation_counts["returns_total"] += 1
        if node.returns is not None:
            self._annotation_counts["returns_annotated"] += 1
        needs_annotation = bool(filtered_params) and annotated < len(filtered_params)
        needs_annotation = needs_annotation or node.returns is None
        if is_public and needs_annotation:
            self._untyped_defs += 1

        docstring = _extract_def_docstring(node.body)
        summary, has_summary, parity, has_examples = _analyze_docstring(docstring, filtered_params)
        if is_public and (docstring is None or not parity):
            self.doc_metrics["param_parity"] = False
        if is_public and has_summary:
            self.doc_metrics["has_summary"] = True
        if is_public and has_examples:
            self.doc_metrics["examples_present"] = True

        self.doc_items.append(
            {
                "name": name,
                "kind": "function",
                "public": is_public,
                "lineno": lineno,
                "doc_summary": summary,
                "doc_has_summary": has_summary,
                "doc_param_parity": parity if docstring else None,
                "doc_examples_present": has_examples,
            }
        )

    def _handle_class_def(self, node: cst.ClassDef) -> None:
        lineno = _lineno(self, node)
        self.defs.append(DefEntry(kind="class", name=node.name.value, lineno=lineno))
        self._record_class_doc(node, lineno)

    def _record_class_doc(self, node: cst.ClassDef, lineno: int) -> None:
        name = node.name.value
        is_public = not name.startswith("_")
        docstring = _extract_def_docstring(node.body)
        summary, has_summary, _parity, has_examples = _analyze_docstring(docstring, [])
        if is_public and has_summary:
            self.doc_metrics["has_summary"] = True
        if is_public and has_examples:
            self.doc_metrics["examples_present"] = True

        self.doc_items.append(
            {
                "name": name,
                "kind": "class",
                "public": is_public,
                "lineno": lineno,
                "doc_summary": summary,
                "doc_has_summary": has_summary,
                "doc_param_parity": None,
                "doc_examples_present": has_examples,
            }
        )

    def _handle_assign(self, node: cst.Assign) -> None:
        lineno = _lineno(self, node)
        for target in node.targets:
            if not isinstance(target.target, cst.Name):
                continue
            name = target.target.value
            if name == "__all__":
                self.exports.update(_literal_string_values(node.value))
                continue
            if name.startswith("_"):
                continue
            self.defs.append(DefEntry(kind="variable", name=name, lineno=lineno))

    def _handle_ann_assign(self, node: cst.AnnAssign) -> None:
        lineno = _lineno(self, node)
        target = node.target
        if isinstance(target, cst.Name):
            name = target.value
            if name == "__all__" or name.startswith("_"):
                return
            self.defs.append(DefEntry(kind="variable", name=name, lineno=lineno))


def index_module(path: str, code: str) -> ModuleIndex:
    """Return parsed module metadata, falling back to a stub on parse failure.

    Parameters
    ----------
    path : str
        File path of the module being indexed (used for error reporting and
        metadata). May be absolute or relative.
    code : str
        Source code content of the module to parse and index.

    Returns
    -------
    ModuleIndex
        Parsed module metadata containing imports, defs, exports, docstring,
        and parse status. On parse failure, returns a stub with parse_ok=False
        and error details.
    """
    parsed_path = Path(path)
    try:
        wrapper = cst_metadata.MetadataWrapper(cst.parse_module(code))
    except (cst.ParserSyntaxError, RecursionError, ValueError) as exc:  # pragma: no cover
        return ModuleIndex(
            path=str(parsed_path),
            parse_ok=False,
            errors=[f"LibCST parse failed: {exc!r}"],
        )
    visitor = _IndexVisitor(code)
    wrapper.visit(visitor)
    visitor.finalize()
    return ModuleIndex(
        path=str(parsed_path),
        imports=visitor.imports,
        defs=visitor.defs,
        exports=visitor.exports,
        docstring=visitor.docstring,
        doc_summary=visitor.doc_summary,
        doc_metrics=visitor.doc_metrics,
        doc_items=visitor.doc_items,
        annotation_ratio=visitor.annotation_ratio,
        untyped_defs=visitor.untyped_defs,
        side_effects=visitor.side_effects,
        raises=visitor.raises,
        complexity=visitor.complexity,
    )


def _lineno(visitor: _IndexVisitor, node: cst.CSTNode) -> int:
    """Return the starting line number for ``node`` when metadata is available.

    Parameters
    ----------
    visitor : _IndexVisitor
        LibCST visitor instance that provides metadata access via
        ``get_metadata()``.
    node : cst.CSTNode
        LibCST node to extract line number from.

    Returns
    -------
    int
        1-based line number or 0 when metadata is unavailable.
    """
    try:
        pos = visitor.get_metadata(cst_metadata.PositionProvider, node)
        return getattr(getattr(pos, "start", None), "line", 0)
    except (KeyError, AttributeError, TypeError):  # pragma: no cover
        return 0
