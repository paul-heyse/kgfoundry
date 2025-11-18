"""Codemod to move gate_import imports to codeintel_rev.runtime.imports."""

from __future__ import annotations

import libcst as cst
from libcst import MaybeSentinel, RemovalSentinel
from libcst import matchers as m
from libcst.codemod import VisitorBasedCodemodCommand
from libcst.codemod.visitors import AddImportsVisitor
from libcst.helpers import get_full_name_for_node


class ReplaceTypingGateImports(VisitorBasedCodemodCommand):
    """Rewrite ``from codeintel_rev.typing import gate_import`` imports."""

    DESCRIPTION: str = "Move gate_import imports to codeintel_rev.runtime.imports"
    _OLD_MODULE = "codeintel_rev.typing"
    _NEW_MODULE = "codeintel_rev.runtime.imports"

    @m.visit(m.Import())
    def _handle_import(self, node: cst.Import) -> None:
        """Warn when modules alias codeintel_rev.typing."""
        for alias in node.names:
            module_name = self._module_name(alias.name)
            if module_name == self._OLD_MODULE:
                alias_name = _alias_name_value(alias.asname) or module_name
                self.warn(
                    f"Attribute access imports ({alias_name}.gate_import) require manual fixes in {self.context.filename}",
                )

    @m.leave(m.ImportFrom())
    def _handle_import_from(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.ImportFrom | RemovalSentinel:
        """Rewrite gate_import imports to the runtime helper.

        Returns
        -------
        cst.BaseStatement
            Updated import statement.
        """
        del original_node
        module_name = self._module_name(updated_node.module)
        if module_name != self._OLD_MODULE:
            return updated_node
        names = updated_node.names
        if isinstance(names, cst.ImportStar):
            self.warn(
                f"Star import from {self._OLD_MODULE} requires manual cleanup in {self.context.filename}",
            )
            return updated_node
        aliases = list(names)
        kept: list[cst.ImportAlias] = []
        removed_alias = False
        for alias in aliases:
            if m.matches(alias.name, m.Name("gate_import")):
                removed_alias = True
                asname = _alias_name_value(alias.asname)
                AddImportsVisitor.add_needed_import(
                    self.context,
                    self._NEW_MODULE,
                    "gate_import",
                    asname=asname,
                )
            else:
                kept.append(alias)
        if not removed_alias:
            return updated_node
        if not kept:
            return cst.RemoveFromParent()
        cleaned = list(kept)
        cleaned[-1] = cleaned[-1].with_changes(comma=MaybeSentinel.DEFAULT)
        return updated_node.with_changes(names=tuple(cleaned))

    @staticmethod
    def _module_name(node: cst.BaseExpression | None) -> str | None:
        if node is None:
            return None
        try:
            return get_full_name_for_node(node)
        except ValueError:  # pragma: no cover - defensive
            return None


def _alias_name_value(asname: cst.AsName | MaybeSentinel | None) -> str | None:
    if isinstance(asname, cst.AsName) and isinstance(asname.name, cst.Name):
        return asname.name.value
    return None
