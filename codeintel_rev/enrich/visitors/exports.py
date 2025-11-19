"""Export discovery visitor used to power module analysis."""

from __future__ import annotations

import libcst as cst
from libcst import metadata as cst_metadata

from codeintel_rev.enrich.types import DefinitionInfo, ExportItem


def _string_literals(expr: cst.BaseExpression) -> list[str]:
    if isinstance(expr, cst.SimpleString):
        value = expr.evaluated_value
        return [value] if isinstance(value, str) else []
    if isinstance(expr, (cst.List, cst.Tuple, cst.Set)):
        values: list[str] = []
        for element in expr.elements:
            literal = getattr(element, "value", None)
            if isinstance(literal, cst.SimpleString):
                evaluated = literal.evaluated_value
                if isinstance(evaluated, str):
                    values.append(evaluated)
        return values
    return []


class ExportsVisitor(cst.CSTVisitor):
    """Collect exports, __all__ assignments, and definition metadata."""

    METADATA_DEPENDENCIES = (cst_metadata.PositionProvider,)

    def __init__(self, module_name: str) -> None:
        self.module_name = module_name
        self.items: list[ExportItem] = []
        self.definitions: list[DefinitionInfo] = []
        self.dunder_all: list[str] = []
        self.function_nodes: list[cst.FunctionDef] = []
        self._scope_depth = 0

    def on_visit(self, node: cst.CSTNode) -> bool:
        """Dispatch to handlers for assignments, classes, and functions.

        Parameters
        ----------
        node : cst.CSTNode
            The current CST node being visited.

        Returns
        -------
        bool
            Always returns True to continue traversal of the AST.
        """
        if isinstance(node, cst.Assign):
            self._handle_assign(node)
        elif isinstance(node, cst.FunctionDef):
            self._handle_function(node)
        elif isinstance(node, cst.ClassDef):
            self._handle_class(node)
        return True

    def on_leave(self, node: cst.CSTNode) -> None:
        """Decrease scope depth when leaving classes or functions."""
        if isinstance(node, (cst.FunctionDef, cst.ClassDef)):
            self._scope_depth = max(0, self._scope_depth - 1)

    def finalize_items(self) -> None:
        """Update export metadata based on collected ``__all__`` values."""
        allowed = set(self.dunder_all)
        if not allowed:
            return
        for index, item in enumerate(self.items):
            via_all = item.name in allowed
            if via_all != item.via_dunder_all:
                self.items[index] = ExportItem(
                    module=item.module,
                    name=item.name,
                    kind=item.kind,
                    via_dunder_all=via_all,
                )

    def _handle_assign(self, node: cst.Assign) -> None:
        if self._scope_depth > 0:
            return
        for target in node.targets:
            name = getattr(target.target, "value", None)
            if name != "__all__":
                continue
            values = _string_literals(node.value)
            self.dunder_all.extend(values)

    def _handle_function(self, node: cst.FunctionDef) -> None:
        is_top_level = self._scope_depth == 0
        if is_top_level:
            self._record_definition(node.name.value, "function", node)
            self.function_nodes.append(node)
            self.items.append(
                ExportItem(
                    module=self.module_name,
                    name=node.name.value,
                    kind="function",
                    via_dunder_all=False,
                )
            )
        self._scope_depth += 1

    def _handle_class(self, node: cst.ClassDef) -> None:
        if self._scope_depth == 0:
            self._record_definition(node.name.value, "class", node)
            self.items.append(
                ExportItem(
                    module=self.module_name,
                    name=node.name.value,
                    kind="class",
                    via_dunder_all=False,
                )
            )
        self._scope_depth += 1

    def _record_definition(
        self,
        name: str,
        kind: str,
        node: cst.CSTNode,
    ) -> None:
        position = self.get_metadata(cst_metadata.PositionProvider, node, None)
        lineno = position.start.line if position is not None else None
        self.definitions.append(
            DefinitionInfo(
                module=self.module_name,
                name=name,
                kind=kind,
                lineno=lineno,
            )
        )
