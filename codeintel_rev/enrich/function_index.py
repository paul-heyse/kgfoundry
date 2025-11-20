# SPDX-License-Identifier: MIT
"""Helpers for indexing Python functions with GOID metadata."""

from __future__ import annotations

import ast
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from codeintel_rev.ids.goid import GOID, EntityDescriptor, GoidKind, RepoSnapshot, compute_goid

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class FunctionInfo:
    """Metadata describing a single Python function or method."""

    file_path: Path
    rel_path: str
    qualname: str
    goid: GOID
    kind: GoidKind
    class_stack: tuple[str, ...]
    enclosing_functions: tuple[str, ...]
    node: ast.FunctionDef | ast.AsyncFunctionDef
    is_public: bool


class _FunctionCollector(ast.NodeVisitor):
    """AST visitor that records function definitions and GOIDs."""

    def __init__(
        self,
        *,
        file_path: Path,
        rel_path: str,
        snapshot: RepoSnapshot,
    ) -> None:
        self.file_path = file_path
        self.rel_path = rel_path
        self._snapshot = snapshot
        self.functions: list[FunctionInfo] = []
        self._qual_stack: list[str] = []
        self._class_stack: list[str] = []
        self._function_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit a class definition and update the class stack.

        Parameters
        ----------
        node : ast.ClassDef
            AST class definition node. The class name is pushed onto the
            class stack for nested method qualification.

        Notes
        -----
        This method maintains the class stack to correctly qualify nested
        methods with their enclosing class names. The stack is popped after
        visiting child nodes to restore the previous context.
        """
        self._class_stack.append(node.name)
        self._qual_stack.append(node.name)
        self.generic_visit(node)
        self._qual_stack.pop()
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit a function definition and record function metadata.

        Parameters
        ----------
        node : ast.FunctionDef
            AST function definition node. Processed to extract function
            metadata and compute GOID.

        Notes
        -----
        This method delegates to _handle_function to extract function
        information including qualified name, GOID, and visibility.
        """
        self._handle_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit an async function definition and record function metadata.

        Parameters
        ----------
        node : ast.AsyncFunctionDef
            AST async function definition node. Processed to extract function
            metadata and compute GOID.

        Notes
        -----
        This method delegates to _handle_function to extract function
        information including qualified name, GOID, and visibility. Async
        functions are treated the same as regular functions for indexing
        purposes.
        """
        self._handle_function(node)

    def _handle_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qual_components = [*self._qual_stack, node.name]
        qualname = ".".join(component for component in qual_components if component)
        class_stack = tuple(self._class_stack)
        kind: GoidKind = "method" if class_stack else "function"
        start_line = getattr(node, "lineno", None)
        end_line = getattr(node, "end_lineno", start_line)
        descriptor = EntityDescriptor(
            language="python",
            kind=kind,
            rel_path=self.rel_path,
            qualname=qualname or node.name,
            start_line=start_line,
            end_line=end_line,
        )
        goid = compute_goid(self._snapshot, descriptor)
        info = FunctionInfo(
            file_path=self.file_path,
            rel_path=self.rel_path,
            qualname=qualname or node.name,
            goid=goid,
            kind=kind,
            class_stack=class_stack,
            enclosing_functions=tuple(self._function_stack),
            node=node,
            is_public=not node.name.startswith("_"),
        )
        self.functions.append(info)
        self._function_stack.append(node.name)
        self._qual_stack.append(node.name)
        self.generic_visit(node)
        self._qual_stack.pop()
        self._function_stack.pop()


def collect_function_info(
    repo_root: Path,
    files: Sequence[Path],
    *,
    repo: str,
    commit: str,
) -> list[FunctionInfo]:
    """Return function metadata for ``files`` rooted at ``repo_root``.

    Parameters
    ----------
    repo_root : Path
        Repository root directory path.
    files : Sequence[Path]
        Sequence of Python source file paths to analyze.
    repo : str
        Repository identifier for GOID generation.
    commit : str
        Commit hash or version identifier for GOID generation.

    Returns
    -------
    list[FunctionInfo]
        List of function metadata objects containing GOIDs, qualified names,
        and AST nodes for all functions and methods found in the provided files.
        Functions that cannot be read are skipped with a warning.
    """
    function_infos: list[FunctionInfo] = []
    snapshot = RepoSnapshot(repo=repo, commit=commit)
    for file_path in files:
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            LOGGER.warning("Failed to read %s: %s", file_path, exc)
            continue
        try:
            tree = ast.parse(text, filename=str(file_path), type_comments=True)
        except SyntaxError as exc:
            LOGGER.warning("Failed to parse %s: %s", file_path, exc)
            continue
        try:
            rel_path = file_path.relative_to(repo_root).as_posix()
        except ValueError:
            rel_path = file_path.as_posix()
        collector = _FunctionCollector(
            file_path=file_path,
            rel_path=rel_path,
            snapshot=snapshot,
        )
        collector.visit(tree)
        function_infos.extend(collector.functions)
    return function_infos


__all__ = ["FunctionInfo", "collect_function_info"]
