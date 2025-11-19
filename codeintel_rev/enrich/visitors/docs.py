"""Docstring counting visitor for module/class/function analysis."""

from __future__ import annotations

import libcst as cst

from codeintel_rev.enrich.types import DocInfo


class DocVisitor(cst.CSTVisitor):
    """Collect docstring statistics for modules, classes, and functions."""

    def __init__(self, module_name: str) -> None:
        self.module_name = module_name
        self.module_docstring: str | None = None
        self.module_has_doc = False
        self.classes_total = 0
        self.classes_with_doc = 0
        self.functions_total = 0
        self.functions_with_doc = 0

    def on_visit(self, node: cst.CSTNode) -> bool:
        """Inspect nodes and update docstring statistics.

        Parameters
        ----------
        node : cst.CSTNode
            The current CST node being visited.

        Returns
        -------
        bool
            Always returns True to continue traversal of the AST.
        """
        if isinstance(node, cst.Module):
            self._record_module_doc(node)
        elif isinstance(node, cst.ClassDef):
            self._record_class_doc(node)
        elif isinstance(node, cst.FunctionDef):
            self._record_function_doc(node)
        return True

    def build_info(self) -> DocInfo:
        """Return the aggregated docstring snapshot.

        Returns
        -------
        DocInfo
            A dataclass containing the module name, module docstring, and counts
            of documented/total classes and functions.
        """
        return DocInfo(
            module=self.module_name,
            module_docstring=self.module_docstring,
            module_has_doc=self.module_has_doc,
            classes_with_doc=self.classes_with_doc,
            classes_total=self.classes_total,
            functions_with_doc=self.functions_with_doc,
            functions_total=self.functions_total,
        )

    def _record_module_doc(self, node: cst.Module) -> None:
        doc = _safe_docstring(node)
        self.module_docstring = doc
        self.module_has_doc = bool(doc)

    def _record_class_doc(self, node: cst.ClassDef) -> None:
        self.classes_total += 1
        self.classes_with_doc += int(bool(_safe_docstring(node)))

    def _record_function_doc(self, node: cst.FunctionDef) -> None:
        self.functions_total += 1
        self.functions_with_doc += int(bool(_safe_docstring(node)))


def _safe_docstring(node: cst.CSTNode) -> str | None:
    try:
        return node.get_docstring()
    except (ValueError, TypeError):  # pragma: no cover - defensive
        return None
