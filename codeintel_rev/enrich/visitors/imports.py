"""Import collection visitor used during LibCST analysis."""

from __future__ import annotations

from dataclasses import dataclass

import libcst as cst
from libcst.helpers import get_full_name_for_node

from codeintel_rev.enrich.types import ImportEdge, LegacyImportRecord


@dataclass(slots=True)
class _LegacyImportMutable:
    """Mutable accumulator for legacy import records during AST traversal."""

    module: str | None
    names: list[str]
    aliases: dict[str, str]
    is_star: bool
    level: int

    def to_record(self) -> LegacyImportRecord:
        return LegacyImportRecord(
            module=self.module,
            names=tuple(self.names),
            aliases=dict(self.aliases),
            is_star=self.is_star,
            level=self.level,
        )


def _resolve_relative(module: str, level: int, target: str) -> str:
    parts = module.split(".")
    trim = min(level, len(parts))
    prefix = parts[: len(parts) - trim]
    suffix = [segment for segment in target.split(".") if segment]
    return ".".join(part for part in [*prefix, *suffix] if part)


def _full_name(expr: cst.BaseExpression | None) -> str | None:
    if expr is None:
        return None
    name = get_full_name_for_node(expr)
    return name if name is not None else getattr(expr, "value", None)


def _assign_target_name(target: cst.BaseAssignTargetExpression | None) -> str | None:
    if target is None:
        return None
    if isinstance(target, cst.Name):
        return target.value
    if isinstance(target, cst.Attribute):
        full = get_full_name_for_node(target)
        if full is not None:
            return full
    return None


class ImportsVisitor(cst.CSTVisitor):
    """Collect import edges for graph construction and legacy metadata."""

    def __init__(self, module_name: str) -> None:
        self.module_name = module_name
        self.edges: list[ImportEdge] = []
        self.legacy_imports: list[LegacyImportRecord] = []

    def visit_Import(self, node: cst.Import) -> None:  # noqa: N802
        """Handle absolute import statements."""
        self._handle_import(node)

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:  # noqa: N802
        """Handle from-import statements."""
        self._handle_import_from(node)

    def _handle_import(self, node: cst.Import) -> None:
        entry = _LegacyImportMutable(module=None, names=[], aliases={}, is_star=False, level=0)
        for alias in node.names:
            alias_node = cst.ensure_type(alias, cst.ImportAlias)
            name = _full_name(alias_node.name)
            if not name:
                continue
            entry.names.append(name)
            alias_name = _assign_target_name(alias_node.asname.name) if alias_node.asname else None
            if alias_name:
                entry.aliases[name] = alias_name
            self.edges.append(ImportEdge(self.module_name, name, alias_name, 0))
        self.legacy_imports.append(entry.to_record())

    def _handle_import_from(self, node: cst.ImportFrom) -> None:
        level = len(node.relative or ())
        base = _full_name(node.module)
        entry = _LegacyImportMutable(module=base, names=[], aliases={}, is_star=False, level=level)
        names = node.names
        if names is None:
            return
        if isinstance(names, cst.ImportStar):
            entry.is_star = True
            target = base or ""
            resolved = target if level == 0 else _resolve_relative(self.module_name, level, target)
            self.edges.append(ImportEdge(self.module_name, resolved, None, level))
            self.legacy_imports.append(entry.to_record())
            return
        for alias in names:
            alias_node = cst.ensure_type(alias, cst.ImportAlias)
            name = _full_name(alias_node.name)
            if not name:
                continue
            entry.names.append(name)
            alias_name = (
                _assign_target_name(alias_node.asname.name)
                if alias_node.asname is not None
                else None
            )
            if alias_name:
                entry.aliases[name] = alias_name
            target = ".".join(segment for segment in (base, name) if segment)
            resolved = (
                target or name if level == 0 else _resolve_relative(self.module_name, level, target)
            )
            self.edges.append(ImportEdge(self.module_name, resolved, alias_name, level))
        self.legacy_imports.append(entry.to_record())
