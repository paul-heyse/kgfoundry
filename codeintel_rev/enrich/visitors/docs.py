"""Docstring counting visitor for module/class/function analysis."""

from __future__ import annotations

import libcst as cst
from libcst import Module

from codeintel_rev.enrich.types import DocInfo


class DocVisitor(cst.CSTVisitor):
    """Collect docstring statistics for modules, classes, and functions."""

    def __init__(self, module_name: str) -> None:
        """Initialize docstring visitor.

        Parameters
        ----------
        module_name : str
            Name of the module being analyzed.
        """
        self.module_name = module_name
        self.module_docstring: str | None = None
        self.module_has_doc = False
        self.classes_total = 0
        self.classes_with_doc = 0
        self.functions_total = 0
        self.functions_with_doc = 0

    def visit_Module(self, node: cst.Module) -> None:  # noqa: N802
        """Track module docstring metadata."""
        self._record_module_doc(node)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:  # noqa: N802
        """Track class docstring metadata."""
        self._record_class_doc(node)

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:  # noqa: N802
        """Track function docstring metadata."""
        self._record_function_doc(node)

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


def _safe_docstring(node: Module | cst.ClassDef | cst.FunctionDef) -> str | None:
    try:
        return node.get_docstring()
    except (ValueError, TypeError):  # pragma: no cover - defensive
        return None
