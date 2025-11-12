# SPDX-License-Identifier: MIT
"""LibCST-powered index utilities (imports, defs, exports, docstrings)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

import libcst as cst  # type: ignore[import-not-found]
from libcst import metadata as cst_metadata  # type: ignore[import-not-found]
from libcst.helpers import (  # type: ignore[import-not-found]
    get_full_name_for_node,
)


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


class _IndexVisitor(cst.CSTVisitor):
    """Collect module metadata via a single LibCST traversal."""

    METADATA_DEPENDENCIES = (cst_metadata.PositionProvider,)

    def __init__(self) -> None:
        self.imports: list[ImportEntry] = []
        self.defs: list[DefEntry] = []
        self.exports: set[str] = set()
        self.docstring: str | None = None
        self._class_depth = 0
        self._function_depth = 0

    def on_visit(self, node: cst.CSTNode) -> bool:
        """Capture relevant node metadata and continue traversal.

        Parameters
        ----------
        node : cst.CSTNode
            LibCST node being visited during AST traversal.

        Returns
        -------
        bool
            Always returns True to continue traversal of child nodes.
        """
        is_top_level = self._class_depth == 0 and self._function_depth == 0
        if isinstance(node, cst.Module):
            self.docstring = _extract_module_docstring(node)
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

    def _handle_import(self, node: cst.Import) -> None:
        names: list[str] = []
        aliases: dict[str, str] = {}
        for alias in node.names:
            ident = (
                alias.name.value
                if isinstance(alias.name, cst.Name)
                else alias.name.attr.value  # pragma: no cover
            )
            names.append(ident)
            if isinstance(alias.asname, cst.AsName) and isinstance(alias.asname.name, cst.Name):
                aliases[ident] = alias.asname.name.value
        self.imports.append(
            ImportEntry(module=None, names=names, aliases=aliases, is_star=False, level=0)
        )

    def _handle_import_from(self, node: cst.ImportFrom) -> None:
        is_star = isinstance(node.names, cst.ImportStar)
        names: list[str] = []
        aliases: dict[str, str] = {}
        if not is_star:
            for ref in node.names:  # type: ignore[union-attr]
                ident = (
                    ref.name.value
                    if isinstance(ref.name, cst.Name)
                    else ref.name.attr.value  # pragma: no cover
                )
                names.append(ident)
                if isinstance(ref.asname, cst.AsName) and isinstance(ref.asname.name, cst.Name):
                    aliases[ident] = ref.asname.name.value
        module = None
        if node.module:
            with suppress(Exception):  # pragma: no cover - LibCST helper may raise
                module = get_full_name_for_node(node.module)
        level = len(node.relative or [])
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
        try:
            pos = self.get_metadata(cst_metadata.PositionProvider, node)
            lineno = getattr(getattr(pos, "start", None), "line", 0)
        except (KeyError, AttributeError, TypeError):  # pragma: no cover - metadata may be missing
            lineno = 0
        self.defs.append(DefEntry(kind="function", name=node.name.value, lineno=lineno))

    def _handle_class_def(self, node: cst.ClassDef) -> None:
        try:
            pos = self.get_metadata(cst_metadata.PositionProvider, node)
            lineno = getattr(getattr(pos, "start", None), "line", 0)
        except (KeyError, AttributeError, TypeError):  # pragma: no cover - metadata may be missing
            lineno = 0
        self.defs.append(DefEntry(kind="class", name=node.name.value, lineno=lineno))

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
    visitor = _IndexVisitor()
    wrapper.visit(visitor)
    return ModuleIndex(
        path=str(parsed_path),
        imports=visitor.imports,
        defs=visitor.defs,
        exports=visitor.exports,
        docstring=visitor.docstring,
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
