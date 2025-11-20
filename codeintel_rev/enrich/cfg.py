# SPDX-License-Identifier: MIT
"""CFG and DFG scaffolding for Python functions."""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from codeintel_rev.enrich.function_index import FunctionInfo, collect_function_info
from codeintel_rev.enrich.graph.io import (
    write_cfg_blocks,
    write_cfg_edges,
    write_dfg_edges,
)
from codeintel_rev.ids.goid import GOID, EntityDescriptor, RepoSnapshot, compute_goid


class CFGBlockRow(TypedDict):
    """Serialized CFG block row."""

    function_goid_h128: int
    block_idx: int
    kind: str
    start_line: int | None
    end_line: int | None
    stmts_json: list[dict[str, object]]
    in_degree: int
    out_degree: int


class CFGEdgeRow(TypedDict):
    """Serialized CFG edge row."""

    function_goid_h128: int
    src_block_idx: int
    dst_block_idx: int
    edge_type: str
    cond_json: dict[str, object] | None


class DFGEdgeRow(TypedDict):
    """Serialized DFG edge row."""

    function_goid_h128: int
    src_block_idx: int
    dst_block_idx: int
    src_symbol: str
    dst_symbol: str
    via_phi: bool
    use_kind: str


@dataclass(slots=True)
class GraphFlowArtifacts:
    """Combined CFG/DFG tables."""

    goids: list[GOID]
    blocks: list[CFGBlockRow]
    cfg_edges: list[CFGEdgeRow]
    dfg_edges: list[DFGEdgeRow]


@dataclass(slots=True)
class _Block:
    idx: int
    kind: str
    start_line: int | None
    end_line: int | None
    stmts: list[dict[str, object]]
    in_degree: int = 0
    out_degree: int = 0


class CFGBuilder:
    """Construct simple CFG/DFG scaffolding for Python code."""

    def __init__(self, *, repo_root: Path, repo: str, commit: str) -> None:
        self.repo_root = repo_root
        self.repo = repo
        self.commit = commit

    def build(self, files: Sequence[Path]) -> GraphFlowArtifacts:
        """Return CFG/DFG tables.

        Parameters
        ----------
        files : Sequence[Path]
            Sequence of Python source file paths to analyze for control flow
            and data flow graph construction.

        Returns
        -------
        GraphFlowArtifacts
            Container holding GOIDs, CFG blocks, CFG edges, and DFG edges
            extracted from the provided files.
        """
        functions = collect_function_info(self.repo_root, files, repo=self.repo, commit=self.commit)
        snapshot = RepoSnapshot(repo=self.repo, commit=self.commit)
        blocks: list[CFGBlockRow] = []
        cfg_edges: list[CFGEdgeRow] = []
        dfg_edges: list[DFGEdgeRow] = []
        goids: list[GOID] = []
        for info in functions:
            builder = _FunctionCFGBuilder(info=info, snapshot=snapshot)
            cfg_rows, edge_rows, dfg_rows, block_goids = builder.build()
            goids.append(info.goid)
            goids.extend(block_goids)
            blocks.extend(cfg_rows)
            cfg_edges.extend(edge_rows)
            dfg_edges.extend(dfg_rows)
        return GraphFlowArtifacts(
            goids=goids, blocks=blocks, cfg_edges=cfg_edges, dfg_edges=dfg_edges
        )

    @staticmethod
    def write_artifacts(
        artifacts: GraphFlowArtifacts,
        out_dir: Path,
    ) -> tuple[Path, Path, Path]:
        """Write CFG/DFG Parquet files.

        Parameters
        ----------
        artifacts : GraphFlowArtifacts
            Graph flow artifacts container holding blocks, CFG edges, and DFG
            edges to write.
        out_dir : Path
            Output directory where the "graphs" subdirectory will be created.

        Returns
        -------
        tuple[Path, Path, Path]
            Tuple containing paths to the written blocks file, CFG edges file,
            and DFG edges file. Files are written as Parquet if available,
            with JSONL fallback.
        """
        graphs_dir = out_dir / "graphs"
        blocks_path = write_cfg_blocks(
            artifacts.blocks,
            graphs_dir / "cfg_blocks.parquet",
            jsonl_fallback=graphs_dir / "cfg_blocks.jsonl",
        )
        edges_path = write_cfg_edges(
            artifacts.cfg_edges,
            graphs_dir / "cfg_edges.parquet",
            jsonl_fallback=graphs_dir / "cfg_edges.jsonl",
        )
        dfg_path = write_dfg_edges(
            artifacts.dfg_edges,
            graphs_dir / "dfg_edges.parquet",
            jsonl_fallback=graphs_dir / "dfg_edges.jsonl",
        )
        return blocks_path, edges_path, dfg_path


class _FunctionCFGBuilder:
    """Per-function CFG/DFG construction."""

    def __init__(self, *, info: FunctionInfo, snapshot: RepoSnapshot) -> None:
        self.info = info
        self.snapshot = snapshot
        self.blocks: dict[int, _Block] = {}
        self.edges: list[CFGEdgeRow] = []
        self.block_counter = 0
        self.line_to_block: dict[int, int] = {}
        self.entry_idx = self._add_block(
            kind="entry",
            start_line=getattr(info.node, "lineno", None),
            end_line=getattr(info.node, "lineno", None),
        )
        self.exit_idx = self._add_block(
            kind="exit",
            start_line=getattr(info.node, "end_lineno", None),
            end_line=getattr(info.node, "end_lineno", None),
        )

    def build(self) -> tuple[list[CFGBlockRow], list[CFGEdgeRow], list[DFGEdgeRow], list[GOID]]:
        """Return CFG/DFG rows with block GOIDs.

        Returns
        -------
        tuple[list[CFGBlockRow], list[CFGEdgeRow], list[DFGEdgeRow], list[GOID]]
            Block rows, CFG edges, DFG edges, and block GOIDs for the function.
        """
        if self.info.node.body:
            first_stmt = self.info.node.body[0]
            body_block = self._add_block(
                kind="normal",
                start_line=getattr(first_stmt, "lineno", getattr(self.info.node, "lineno", None)),
                end_line=getattr(
                    self.info.node.body[-1],
                    "end_lineno",
                    getattr(self.info.node, "end_lineno", None),
                ),
            )
        else:
            body_block = self._add_block(
                kind="normal",
                start_line=getattr(self.info.node, "lineno", None),
                end_line=getattr(self.info.node, "end_lineno", None),
            )
        self._add_edge(self.entry_idx, body_block, "fallthrough")
        tail = self._build_sequence(self.info.node.body, body_block)
        self._add_edge(tail, self.exit_idx, "fallthrough")
        self._finalize_degrees()
        line_lookup = dict(self.line_to_block)
        dfg_edges = _DFGAnalyzer(
            info=self.info,
            line_to_block=line_lookup,
            entry_block=self.entry_idx,
            exit_block=self.exit_idx,
        ).build_edges()
        cfg_rows = [
            self._row_from_block(block)
            for block in sorted(self.blocks.values(), key=lambda b: b.idx)
        ]
        block_goids = self._block_goids()
        edges = sorted(
            self.edges,
            key=lambda edge: (
                edge["src_block_idx"],
                edge["dst_block_idx"],
                edge.get("edge_type", ""),
            ),
        )
        return cfg_rows, edges, dfg_edges, block_goids

    def _row_from_block(self, block: _Block) -> CFGBlockRow:
        return CFGBlockRow(
            function_goid_h128=self.info.goid.h128,
            block_idx=block.idx,
            kind=block.kind,
            start_line=block.start_line,
            end_line=block.end_line,
            stmts_json=block.stmts,
            in_degree=block.in_degree,
            out_degree=block.out_degree,
        )

    def _add_block(self, *, kind: str, start_line: int | None, end_line: int | None) -> int:
        idx = self.block_counter
        self.block_counter += 1
        self.blocks[idx] = _Block(
            idx=idx,
            kind=kind,
            start_line=start_line,
            end_line=end_line,
            stmts=[],
        )
        return idx

    def _ensure_block(self, block_idx: int | None, *, kind: str, start_line: int | None) -> int:
        if block_idx is not None:
            return block_idx
        return self._add_block(kind=kind, start_line=start_line, end_line=start_line)

    def _add_edge(
        self,
        src: int | None,
        dst: int | None,
        edge_type: str,
        cond_json: dict[str, object] | None = None,
    ) -> None:
        if src is None or dst is None:
            return
        self.edges.append(
            CFGEdgeRow(
                function_goid_h128=self.info.goid.h128,
                src_block_idx=src,
                dst_block_idx=dst,
                edge_type=edge_type,
                cond_json=cond_json,
            )
        )

    def _append_stmt(self, block_idx: int, node: ast.AST, *, label: str | None = None) -> None:
        block = self.blocks[block_idx]
        start_line = getattr(node, "lineno", None)
        end_line = getattr(node, "end_lineno", start_line)
        if block.start_line is None or (start_line is not None and start_line < block.start_line):
            block.start_line = start_line
        if block.end_line is None or (end_line is not None and end_line > block.end_line):
            block.end_line = end_line
        text = _safe_unparse(node)
        metadata = {
            "kind": label or node.__class__.__name__,
            "lineno": start_line,
            "end_lineno": end_line,
            "code": text,
        }
        block.stmts.append(metadata)
        if start_line is not None:
            self.line_to_block.setdefault(start_line, block_idx)

    def _build_sequence(self, statements: list[ast.stmt], current_block: int) -> int:
        block_idx = current_block
        for stmt in statements:
            handler = getattr(self, f"_handle_{stmt.__class__.__name__}", self._handle_simple)
            block_idx = handler(stmt, block_idx)
        return block_idx

    def _handle_simple(self, node: ast.stmt, block_idx: int) -> int:
        idx = self._ensure_block(block_idx, kind="normal", start_line=getattr(node, "lineno", None))
        self._append_stmt(idx, node)
        return idx

    def _handle_Return(self, node: ast.Return, block_idx: int) -> int:  # noqa: N802
        idx = self._ensure_block(block_idx, kind="normal", start_line=getattr(node, "lineno", None))
        self._append_stmt(idx, node)
        self._add_edge(idx, self.exit_idx, "return")
        # create a fresh continuation block for any statements after return
        return self._add_block(
            kind="normal",
            start_line=getattr(node, "end_lineno", None),
            end_line=getattr(node, "end_lineno", None),
        )

    def _handle_If(self, node: ast.If, block_idx: int) -> int:  # noqa: N802
        parent_block = self._ensure_block(
            block_idx, kind="normal", start_line=getattr(node, "lineno", None)
        )
        cond_block = self._add_block(
            kind="branch",
            start_line=getattr(node.test, "lineno", getattr(node, "lineno", None)),
            end_line=getattr(node.test, "end_lineno", getattr(node, "end_lineno", None)),
        )
        self._append_stmt(cond_block, node.test, label="If")
        cond_payload = {
            "expr": _safe_unparse(node.test),
            "lineno": getattr(node.test, "lineno", None),
            "end_lineno": getattr(node.test, "end_lineno", None),
        }
        self._add_edge(parent_block, cond_block, "branch", cond_json=cond_payload)
        true_start = self._add_block(
            kind="normal",
            start_line=_first_line(node.body),
            end_line=_last_line(node.body),
        )
        self._add_edge(cond_block, true_start, "true")
        true_tail = self._build_sequence(node.body or [], true_start)
        false_tail: int
        if node.orelse:
            false_start = self._add_block(
                kind="normal",
                start_line=_first_line(node.orelse),
                end_line=_last_line(node.orelse),
            )
            self._add_edge(cond_block, false_start, "false")
            false_tail = self._build_sequence(node.orelse, false_start)
        else:
            false_tail = cond_block
        join_block = self._add_block(
            kind="normal",
            start_line=getattr(node, "end_lineno", None),
            end_line=getattr(node, "end_lineno", None),
        )
        self._add_edge(true_tail, join_block, "fallthrough")
        if false_tail is cond_block:
            self._add_edge(cond_block, join_block, "false")
        else:
            self._add_edge(false_tail, join_block, "fallthrough")
        return join_block

    def _handle_For(self, node: ast.For, block_idx: int) -> int:  # noqa: N802
        return self._handle_loop(node, block_idx, loop_kind="For")

    def _handle_While(self, node: ast.While, block_idx: int) -> int:  # noqa: N802
        return self._handle_loop(node, block_idx, loop_kind="While")

    def _handle_loop(self, node: ast.AST, block_idx: int, loop_kind: str) -> int:
        parent_block = self._ensure_block(
            block_idx, kind="normal", start_line=getattr(node, "lineno", None)
        )
        loop_header = self._add_block(
            kind="loop",
            start_line=getattr(node, "lineno", None),
            end_line=getattr(node, "end_lineno", None),
        )
        self._append_stmt(loop_header, node, label=loop_kind)
        self._add_edge(parent_block, loop_header, "loop-entry")
        body_start = self._add_block(
            kind="normal",
            start_line=_first_line(getattr(node, "body", [])),
            end_line=_last_line(getattr(node, "body", [])),
        )
        cond_source = getattr(node, "test", getattr(node, "iter", node))
        cond_payload = {
            "expr": _safe_unparse(cond_source),
            "lineno": getattr(cond_source, "lineno", getattr(node, "lineno", None)),
            "end_lineno": getattr(cond_source, "end_lineno", getattr(node, "end_lineno", None)),
        }
        self._add_edge(loop_header, body_start, "true", cond_json=cond_payload)
        body_tail = self._build_sequence(getattr(node, "body", []), body_start)
        self._add_edge(body_tail, loop_header, "loop-back")
        loop_exit = self._add_block(
            kind="normal",
            start_line=getattr(node, "end_lineno", None),
            end_line=getattr(node, "end_lineno", None),
        )
        self._add_edge(loop_header, loop_exit, "false", cond_json=cond_payload)
        return loop_exit

    def _handle_With(self, node: ast.With, block_idx: int) -> int:  # noqa: N802
        idx = self._handle_simple(node, block_idx)
        return self._build_sequence(node.body, idx)

    def _handle_Try(self, node: ast.Try, block_idx: int) -> int:  # noqa: N802
        idx = self._handle_simple(node, block_idx)
        body_tail = self._build_sequence(node.body, idx)
        finally_tail = body_tail
        for handler in node.handlers:
            handler_block = self._add_block(
                kind="exception",
                start_line=getattr(handler, "lineno", None),
                end_line=getattr(handler, "end_lineno", None),
            )
            self._append_stmt(handler_block, handler, label="ExceptHandler")
            handler_tail = self._build_sequence(handler.body, handler_block)
            finally_tail = handler_tail
        if node.finalbody:
            finally_start = self._add_block(
                kind="normal",
                start_line=_first_line(node.finalbody),
                end_line=_last_line(node.finalbody),
            )
            self._add_edge(finally_tail, finally_start, "fallthrough")
            finally_tail = self._build_sequence(node.finalbody, finally_start)
        return finally_tail

    def _finalize_degrees(self) -> None:
        for block in self.blocks.values():
            block.in_degree = 0
            block.out_degree = 0
        for edge in self.edges:
            self.blocks[edge["src_block_idx"]].out_degree += 1
            self.blocks[edge["dst_block_idx"]].in_degree += 1

    def _block_goids(self) -> list[GOID]:
        goids: list[GOID] = []
        for block in self.blocks.values():
            descriptor = EntityDescriptor(
                language="python",
                kind="block",
                rel_path=self.info.rel_path,
                qualname=f"{self.info.qualname or self.info.node.name}::block{block.idx}",
                start_line=block.start_line,
                end_line=block.end_line,
            )
            goids.append(compute_goid(self.snapshot, descriptor))
        return goids


class _DFGAnalyzer(ast.NodeVisitor):
    """Collect def-use edges for a function."""

    def __init__(
        self,
        *,
        info: FunctionInfo,
        line_to_block: Mapping[int, int],
        entry_block: int,
        exit_block: int,
    ) -> None:
        self.info = info
        self.line_to_block = line_to_block
        self.entry_block = entry_block
        self.exit_block = exit_block
        self.root = info.node
        self.def_blocks: dict[str, set[int]] = {}
        self.edges: set[tuple[int, int, str, bool, str]] = set()

    def build_edges(self) -> list[DFGEdgeRow]:
        """Build data flow graph edges for the function.

        Returns
        -------
        list[DFGEdgeRow]
            Sorted list of data flow edges representing def-use relationships
            between blocks in the function.
        """
        for arg in _argument_names(self.info.node.args):
            self._record_def(arg, self.entry_block)
        self.visit(self.info.node)
        return [
            DFGEdgeRow(
                function_goid_h128=self.info.goid.h128,
                src_block_idx=src,
                dst_block_idx=dst,
                src_symbol=symbol,
                dst_symbol=symbol,
                via_phi=via_phi,
                use_kind=kind,
            )
            for (src, dst, symbol, via_phi, kind) in sorted(
                self.edges, key=lambda item: (item[2], item[0], item[1], item[4])
            )
        ]

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit function definition node.

        Parameters
        ----------
        node : ast.FunctionDef
            AST function definition node to process.
        """
        self._visit_function_node(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit async function definition node.

        Parameters
        ----------
        node : ast.AsyncFunctionDef
            AST async function definition node to process.
        """
        self._visit_function_node(node)

    def _visit_function_node(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if node is self.root:
            for decorator in getattr(node, "decorator_list", []):
                self.visit(decorator)
            for stmt in node.body:
                self.visit(stmt)
            return
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit class definition node.

        Parameters
        ----------
        node : ast.ClassDef
            AST class definition node to process.
        """
        self._block_for(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Visit name node and record def or use.

        Parameters
        ----------
        node : ast.Name
            AST name node. If context is Load, records a use; if Store, records a def.
        """
        if isinstance(node.ctx, ast.Load):
            self._record_use(node.id, node)
        elif isinstance(node.ctx, ast.Store):
            self._record_def(node.id, self._block_for(node))

    def visit_Assign(self, node: ast.Assign) -> None:
        """Visit assignment node and record definitions.

        Parameters
        ----------
        node : ast.Assign
            AST assignment node. Records defs for all target names, then visits value.
        """
        for target in node.targets:
            for name in _names_in_target(target):
                self._record_def(name, self._block_for(node))
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Visit annotated assignment node and record definitions.

        Parameters
        ----------
        node : ast.AnnAssign
            AST annotated assignment node. Records defs for target names, then visits value if present.
        """
        for name in _names_in_target(node.target):
            self._record_def(name, self._block_for(node))
        if node.value:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """Visit augmented assignment node and record use and def.

        Parameters
        ----------
        node : ast.AugAssign
            AST augmented assignment node. Records both use and def for target names, then visits value.
        """
        for name in _names_in_target(node.target):
            self._record_use(name, node)
            self._record_def(name, self._block_for(node))
        self.visit(node.value)

    def visit_For(self, node: ast.For) -> None:
        """Visit for loop node.

        Parameters
        ----------
        node : ast.For
            AST for loop node to process.
        """
        self._visit_for_node(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        """Visit async for loop node.

        Parameters
        ----------
        node : ast.AsyncFor
            AST async for loop node to process.
        """
        self._visit_for_node(node)

    def _visit_for_node(self, node: ast.For | ast.AsyncFor) -> None:
        for name in _names_in_target(node.target):
            self._record_def(name, self._block_for(node))
        self.visit(node.iter)
        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_With(self, node: ast.With) -> None:
        """Visit with statement node.

        Parameters
        ----------
        node : ast.With
            AST with statement node. Records defs for optional variable names,
            visits context expressions, then visits body statements.
        """
        for item in node.items:
            if item.optional_vars:
                for name in _names_in_target(item.optional_vars):
                    self._record_def(name, self._block_for(item))
            self.visit(item.context_expr)
        for stmt in node.body:
            self.visit(stmt)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        """Visit comprehension node.

        Parameters
        ----------
        node : ast.comprehension
            AST comprehension node. Records defs for target names, visits iterable,
            then visits any if clauses.
        """
        for name in _names_in_target(node.target):
            self._record_def(name, self._block_for(node))
        self.visit(node.iter)
        for if_clause in node.ifs:
            self.visit(if_clause)

    def _record_def(self, name: str, block_idx: int) -> None:
        if not name:
            return
        entry = self.def_blocks.setdefault(name, set())
        entry.add(block_idx)
        self.edges.add((block_idx, block_idx, name, False, "def"))

    def _record_use(self, name: str, node: ast.AST) -> None:
        if not name:
            return
        sources = self.def_blocks.get(name) or {self.entry_block}
        dst_block = self._block_for(node)
        via_phi = len(sources) > 1
        for src in sources:
            self.edges.add((src, dst_block, name, via_phi, "use"))

    def _block_for(self, node: ast.AST) -> int:
        line = getattr(node, "lineno", None)
        if line is None:
            return self.entry_block
        return self.line_to_block.get(line, self.entry_block)


def _argument_names(args: ast.arguments) -> list[str]:
    names: list[str] = []
    for collection in (
        args.posonlyargs,
        args.args,
        args.kwonlyargs,
    ):
        names.extend(arg.arg for arg in collection)
    if args.vararg:
        names.append(args.vararg.arg)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return names


def _names_in_target(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for element in node.elts:
            names.update(_names_in_target(element))
        return names
    return set()


def _first_line(statements: list[ast.stmt]) -> int | None:
    if not statements:
        return None
    return getattr(statements[0], "lineno", None)


def _last_line(statements: list[ast.stmt]) -> int | None:
    if not statements:
        return None
    return getattr(statements[-1], "end_lineno", getattr(statements[-1], "lineno", None))


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError, TypeError):  # pragma: no cover - ast.unparse fallback
        return node.__class__.__name__


__all__ = [
    "CFGBlockRow",
    "CFGBuilder",
    "CFGEdgeRow",
    "DFGEdgeRow",
    "GraphFlowArtifacts",
]
