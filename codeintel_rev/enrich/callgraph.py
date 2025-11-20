# SPDX-License-Identifier: MIT
"""Static call graph construction for Python sources."""

from __future__ import annotations

import ast
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from codeintel_rev.enrich.function_index import FunctionInfo, collect_function_info
from codeintel_rev.enrich.graph.io import write_call_edges, write_call_nodes
from codeintel_rev.ids.goid import GOID

LOGGER = logging.getLogger(__name__)


class CallNodeRow(TypedDict):
    """Serialized representation of a call graph node."""

    goid_h128: int
    language: str
    kind: str
    arity: int
    is_public: bool
    rel_path: str


class CallEdgeRow(TypedDict, total=False):
    """Serialized representation of a call graph edge."""

    caller_goid_h128: int
    callee_goid_h128: int | None
    callsite_path: str
    callsite_line: int | None
    callsite_col: int | None
    language: str
    kind: str
    resolved_via: str
    confidence: float
    evidence_json: dict[str, object] | None


@dataclass(slots=True)
class CallGraphArtifacts:
    """Materialized call graph rows."""

    goids: list[GOID]
    nodes: list[CallNodeRow]
    edges: list[CallEdgeRow]


class CallGraphBuilder:
    """Build a static call graph for Python files."""

    def __init__(self, *, repo_root: Path, repo: str, commit: str) -> None:
        self.repo_root = repo_root
        self.repo = repo
        self.commit = commit

    def build(self, files: Sequence[Path]) -> CallGraphArtifacts:
        """Return call graph nodes/edges for ``files``.

        Parameters
        ----------
        files : Sequence[Path]
            Sequence of Python source file paths to analyze for call graph
            construction.

        Returns
        -------
        CallGraphArtifacts
            Container holding GOIDs, call node rows, and call edge rows extracted
            from the provided files. Nodes and edges are sorted for consistent
            output ordering.
        """
        functions = collect_function_info(self.repo_root, files, repo=self.repo, commit=self.commit)
        module_funcs: dict[str, dict[str, FunctionInfo]] = {}
        class_methods: dict[tuple[str, str], dict[str, FunctionInfo]] = {}
        for info in functions:
            if not info.node.name:
                continue
            if info.kind == "function" and not info.enclosing_functions:
                module_funcs.setdefault(info.rel_path, {})[info.node.name] = info
            if info.kind == "method" and info.class_stack:
                class_key = (info.rel_path, ".".join(info.class_stack))
                class_methods.setdefault(class_key, {})[info.node.name] = info

        node_map: dict[int, CallNodeRow] = {}
        edges: list[CallEdgeRow] = []

        for info in functions:
            node_map.setdefault(
                info.goid.h128,
                CallNodeRow(
                    goid_h128=info.goid.h128,
                    language="python",
                    kind="method" if info.class_stack else "function",
                    arity=len(getattr(info.node.args, "args", []) or []),
                    is_public=info.is_public,
                    rel_path=info.rel_path,
                ),
            )
            collector = _CallCollector(
                function=info,
                module_functions=module_funcs.get(info.rel_path, {}),
                class_methods=class_methods,
                edge_sink=edges,
            )
            collector.visit(info.node)

        nodes = [node_map[key] for key in sorted(node_map)]
        edges_sorted = sorted(
            edges,
            key=lambda edge: (
                edge.get("callsite_path") or "",
                edge.get("callsite_line") or -1,
                edge.get("callsite_col") or -1,
            ),
        )
        goids = [
            info.goid
            for info in sorted(functions, key=lambda entry: (entry.rel_path, entry.qualname))
        ]
        return CallGraphArtifacts(goids=goids, nodes=nodes, edges=edges_sorted)

    @staticmethod
    def write_artifacts(
        artifacts: CallGraphArtifacts,
        out_dir: Path,
    ) -> tuple[Path, Path]:
        """Write call node/edge Parquet datasets.

        Parameters
        ----------
        artifacts : CallGraphArtifacts
            Call graph artifacts container holding nodes and edges to write.
        out_dir : Path
            Output directory where the "graphs" subdirectory will be created.

        Returns
        -------
        tuple[Path, Path]
            Tuple containing paths to the written nodes file and edges file.
            Files are written as Parquet if available, with JSONL fallback.
        """
        graphs_dir = out_dir / "graphs"
        nodes_path = write_call_nodes(
            artifacts.nodes,
            graphs_dir / "call_nodes.parquet",
            jsonl_fallback=graphs_dir / "call_nodes.jsonl",
        )
        edges_path = write_call_edges(
            artifacts.edges,
            graphs_dir / "call_edges.parquet",
            jsonl_fallback=graphs_dir / "call_edges.jsonl",
        )
        return nodes_path, edges_path


class _CallCollector(ast.NodeVisitor):
    """Collect call expressions for a single function."""

    def __init__(
        self,
        *,
        function: FunctionInfo,
        module_functions: Mapping[str, FunctionInfo],
        class_methods: Mapping[tuple[str, str], Mapping[str, FunctionInfo]],
        edge_sink: list[CallEdgeRow],
    ) -> None:
        self.function = function
        self._root = function.node
        self._module_funcs = module_functions
        self._class_methods = class_methods
        self._edges = edge_sink

    def visit_Call(self, node: ast.Call) -> None:
        """Visit a function call expression and record call graph edges.

        Parameters
        ----------
        node : ast.Call
            AST call node representing a function invocation. The callee
            expression is resolved to determine the target function.

        Notes
        -----
        This method resolves the callee function using symbol resolution
        heuristics and records a call edge in the graph. The edge includes
        callsite location, resolution strategy, and confidence score.
        """
        callee, resolved_via, call_kind = self._resolve_callee(node.func)
        evidence: dict[str, object] = {"expr": _safe_unparse(node.func), "resolver": resolved_via}
        edge: CallEdgeRow = {
            "caller_goid_h128": self.function.goid.h128,
            "callee_goid_h128": callee.goid.h128 if callee else None,
            "callsite_path": self.function.rel_path,
            "callsite_line": getattr(node, "lineno", None),
            "callsite_col": getattr(node, "col_offset", None),
            "language": "python",
            "kind": call_kind,
            "resolved_via": resolved_via,
            "confidence": _confidence_for_resolution(resolved_via),
            "evidence_json": evidence,
        }
        self._edges.append(edge)
        super().generic_visit(node)

    def generic_visit(self, node: ast.AST) -> None:
        """Visit AST nodes with selective traversal control.

        Extended Summary
        ----------------
        This method overrides the base class generic visitor to prevent traversal
        into nested function, async function, and class definitions. This ensures
        that call graph collection only processes calls within the current function
        scope and does not descend into nested scopes that would create incorrect
        call edges. The root function node itself is always visited to allow
        processing of its direct children.

        Parameters
        ----------
        node : ast.AST
            AST node being visited. If this is a nested function, async function,
            or class definition (and not the root function being analyzed), traversal
            stops to prevent incorrect call graph edges.

        Notes
        -----
        This method implements a selective traversal strategy where nested scopes
        are skipped to maintain accurate call graph boundaries. Only calls within
        the immediate function body are recorded, preventing false edges from
        nested function definitions. The root function node is always processed
        to allow its direct call expressions to be collected.
        """
        if node is not self._root and isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        ):
            return
        super().generic_visit(node)

    def _resolve_callee(
        self,
        func: ast.expr,
    ) -> tuple[FunctionInfo | None, str, str]:
        if isinstance(func, ast.Name):
            candidate = self._module_funcs.get(func.id)
            if candidate:
                return candidate, "local-symbol", "direct"
            return None, "unresolved", "direct"
        if isinstance(func, ast.Attribute):
            attr = func.attr
            owner = func.value
            if isinstance(owner, ast.Name):
                return self._resolve_attribute(owner.id, attr)
            if isinstance(owner, ast.Attribute):
                base_name = _outer_name(owner)
                if base_name:
                    return self._resolve_attribute(base_name, attr)
        return None, "unresolved", "attr"

    def _resolve_attribute(
        self,
        base_name: str,
        attr: str,
    ) -> tuple[FunctionInfo | None, str, str]:
        if base_name == "self" and self.function.class_stack:
            class_key = (self.function.rel_path, ".".join(self.function.class_stack))
            candidate = self._class_methods.get(class_key, {}).get(attr)
            if candidate:
                return candidate, "class-self", "method"
            return None, "class-self", "method"
        class_key = (self.function.rel_path, base_name)
        candidate = self._class_methods.get(class_key, {}).get(attr)
        if candidate:
            return candidate, "class-attr", "attr_call"
        return None, "unresolved", "attr_call"


def _outer_name(expr: ast.Attribute) -> str | None:
    """Return the left-most identifier for a nested attribute.

    Parameters
    ----------
    expr : ast.Attribute
        AST attribute expression to extract the base name from.

    Returns
    -------
    str | None
        Left-most identifier name if the attribute chain starts with a Name
        node, or None if the chain structure is unexpected.
    """
    current: ast.AST = expr
    while isinstance(current, ast.Attribute):
        current = current.value
    if isinstance(current, ast.Name):
        return current.id
    return None


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError, TypeError):  # pragma: no cover - ast.unparse fallback
        return node.__class__.__name__


def _confidence_for_resolution(strategy: str) -> float:
    return {
        "local-symbol": 0.95,
        "class-self": 0.9,
        "class-attr": 0.8,
    }.get(strategy, 0.25)


__all__ = ["CallEdgeRow", "CallGraphArtifacts", "CallGraphBuilder", "CallNodeRow"]
