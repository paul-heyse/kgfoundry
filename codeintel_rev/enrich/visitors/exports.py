"""Export discovery visitor used to power module analysis."""

from __future__ import annotations

import libcst as cst
from libcst import metadata as cst_metadata
from libcst.helpers import get_full_name_for_node
from libcst.metadata import CodeRange

from codeintel_rev.enrich.types import DefinitionInfo, ExportItem


def _string_literals(expr: cst.BaseExpression) -> list[str]:
    if isinstance(expr, cst.SimpleString):
        value = expr.evaluated_value
        return [value] if isinstance(value, str) else []
    if isinstance(expr, (cst.List, cst.Tuple, cst.Set)):
        values: list[str] = []
        for element in expr.elements:
            literal = element.value if isinstance(element, cst.Element) else None
            if isinstance(literal, cst.SimpleString):
                evaluated = literal.evaluated_value
                if isinstance(evaluated, str):
                    values.append(evaluated)
        return values
    return []


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

    def visit_Assign(self, node: cst.Assign) -> None:  # noqa: N802
        """Handle assignments to capture __all__ lists."""
        self._handle_assign(node)

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:  # noqa: N802
        """Handle function definitions for export tracking."""
        self._handle_function(node)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:  # noqa: N802
        """Handle class definitions for export tracking."""
        self._handle_class(node)

    def on_leave(self, original_node: cst.CSTNode) -> None:
        """Decrease scope depth when leaving classes or functions."""
        if isinstance(original_node, (cst.FunctionDef, cst.ClassDef)):
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
            name = _assign_target_name(target.target)
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
        position = self.get_metadata(
            cst_metadata.PositionProvider,
            node,
            CodeRange((0, 0), (0, 0)),
        )
        lineno = position.start.line
        self.definitions.append(
            DefinitionInfo(
                module=self.module_name,
                name=name,
                kind=kind,
                lineno=lineno,
            )
        )
