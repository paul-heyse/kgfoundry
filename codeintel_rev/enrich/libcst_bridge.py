# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import libcst as cst  # type: ignore[import-not-found]
from libcst import metadata as cst_metadata  # type: ignore[import-not-found]


@dataclass
class ImportEntry:
    module: str | None
    names: list[str]
    aliases: dict[str, str]
    is_star: bool
    level: int


@dataclass
class DefEntry:
    kind: str  # "class" | "function" | "variable"
    name: str
    lineno: int


@dataclass
class ModuleIndex:
    path: str
    imports: list[ImportEntry] = field(default_factory=list)
    defs: list[DefEntry] = field(default_factory=list)
    exports: set[str] = field(default_factory=set)
    docstring: str | None = None
    parse_ok: bool = True
    errors: list[str] = field(default_factory=list)


class _IndexVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (cst_metadata.PositionProvider,)

    def __init__(self) -> None:
        self.imports: list[ImportEntry] = []
        self.defs: list[DefEntry] = []
        self.exports: set[str] = set()
        self.docstring: str | None = None

    def visit_Module(self, node: cst.Module) -> bool | None:
        if node.has_trailing_newline:
            # Extract top-level module docstring
            maybe = node.body[0] if node.body else None
            if maybe and isinstance(maybe, cst.SimpleStatementLine):
                expr = maybe.body[0] if maybe.body else None
                if isinstance(expr, cst.Expr) and isinstance(expr.value, cst.SimpleString):
                    self.docstring = expr.value.evaluated_value
        return True

    def visit_Import(self, node: cst.Import) -> bool | None:
        names: list[str] = []
        aliases: dict[str, str] = {}
        for n in node.names:
            ident = n.name.value if isinstance(n.name, cst.Name) else n.name.attr.value  # type: ignore[attr-defined]
            names.append(ident)
            if n.asname:
                aliases[ident] = n.asname.name.value
        self.imports.append(
            ImportEntry(module=None, names=names, aliases=aliases, is_star=False, level=0)
        )
        return True

    def visit_ImportFrom(self, node: cst.ImportFrom) -> bool | None:
        is_star = isinstance(node.names, cst.ImportStar)
        names: list[str] = []
        aliases: dict[str, str] = {}
        if not is_star:
            for n in node.names:  # type: ignore[union-attr]
                ident = n.name.value if isinstance(n.name, cst.Name) else n.name.attr.value  # type: ignore[attr-defined]
                names.append(ident)
                if n.asname:
                    aliases[ident] = n.asname.name.value
        module = None
        level = 0
        if node.module:
            if isinstance(node.module, cst.Attribute):
                module = node.module.attr.value
            elif isinstance(node.module, cst.Name):
                module = node.module.value
            elif isinstance(node.module, cst.Attribute):
                module = node.module.value.attr.value  # type: ignore[union-attr]
        if node.relative:
            level = len(node.relative)
        self.imports.append(
            ImportEntry(module=module, names=names, aliases=aliases, is_star=is_star, level=level)
        )
        return True

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool | None:
        pos = self.get_metadata(cst_metadata.PositionProvider, node)
        self.defs.append(DefEntry(kind="function", name=node.name.value, lineno=pos.start.line))
        return True

    def visit_ClassDef(self, node: cst.ClassDef) -> bool | None:
        pos = self.get_metadata(cst_metadata.PositionProvider, node)
        self.defs.append(DefEntry(kind="class", name=node.name.value, lineno=pos.start.line))
        return True

    def visit_Assign(self, node: cst.Assign) -> bool | None:
        # `__all__ = ["a", "b"]` forms
        for t in node.targets:
            if isinstance(t.target, cst.Name) and t.target.value == "__all__":
                names: set[str] = set()
                if isinstance(node.value, (cst.List, cst.Tuple, cst.Set)):
                    for el in node.value.elements:
                        if isinstance(el.value, cst.SimpleString):
                            try:
                                names.add(el.value.evaluated_value)
                            except Exception:
                                pass
                elif isinstance(node.value, cst.SimpleString):
                    try:
                        names.add(node.value.evaluated_value)
                    except Exception:
                        pass
                self.exports.update(names)
        return True


def index_module(path: str, code: str) -> ModuleIndex:
    """
    Parse a Python module with LibCST and extract imports, defs, exports, and docstring.
    Falls back to a minimal record on parse error.
    """
    p = Path(path)
    try:
        mod = cst.parse_module(code)
        wrapper = cst_metadata.MetadataWrapper(mod)
        v = _IndexVisitor()
        wrapper.visit(v)
        return ModuleIndex(
            path=str(p),
            imports=v.imports,
            defs=v.defs,
            exports=v.exports,
            docstring=v.docstring,
            parse_ok=True,
        )
    except Exception as exc:  # pragma: no cover — resilience is the point
        return ModuleIndex(
            path=str(p),
            imports=[],
            defs=[],
            exports=set(),
            docstring=None,
            parse_ok=False,
            errors=[f"LibCST parse failed: {exc!r}"],
        )
