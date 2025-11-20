# SPDX-License-Identifier: MIT
"""CFG and DFG scaffolding for Python functions."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from codeintel_rev.enrich.function_index import FunctionInfo, collect_function_info
from codeintel_rev.enrich.graph.io import (
    write_cfg_blocks,
    write_cfg_edges,
    write_dfg_edges,
)
from codeintel_rev.ids.goid import GOID


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
        blocks: list[CFGBlockRow] = []
        cfg_edges: list[CFGEdgeRow] = []
        dfg_edges: list[DFGEdgeRow] = []
        goids: list[GOID] = []
        for info in functions:
            goids.append(info.goid)
            cfg_result = _build_cfg_rows(info)
            blocks.extend(cfg_result.blocks)
            cfg_edges.extend(cfg_result.edges)
            dfg_edges.extend(_build_dfg_rows(info, cfg_result.body_block_idx))
        return GraphFlowArtifacts(
            goids=goids,
            blocks=blocks,
            cfg_edges=cfg_edges,
            dfg_edges=dfg_edges,
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


@dataclass(slots=True)
class _CFGResult:
    blocks: list[CFGBlockRow]
    edges: list[CFGEdgeRow]
    body_block_idx: int


def _build_cfg_rows(info: FunctionInfo) -> _CFGResult:
    entry_idx = 0
    blocks: list[CFGBlockRow] = [
        CFGBlockRow(
            function_goid_h128=info.goid.h128,
            block_idx=entry_idx,
            kind="entry",
            start_line=getattr(info.node, "lineno", None),
            end_line=getattr(info.node, "lineno", None),
            stmts_json=[],
            in_degree=0,
            out_degree=0,
        )
    ]
    edges: list[CFGEdgeRow] = []
    body_block_idx: int
    statements = info.node.body
    if statements:
        body_block_idx = 1
        exit_idx = 2
        blocks.append(
            CFGBlockRow(
                function_goid_h128=info.goid.h128,
                block_idx=body_block_idx,
                kind="normal",
                start_line=getattr(statements[0], "lineno", getattr(info.node, "lineno", None)),
                end_line=getattr(
                    statements[-1], "end_lineno", getattr(info.node, "end_lineno", None)
                ),
                stmts_json=_statement_metadata(statements),
                in_degree=0,
                out_degree=0,
            )
        )
        blocks.append(
            CFGBlockRow(
                function_goid_h128=info.goid.h128,
                block_idx=exit_idx,
                kind="exit",
                start_line=getattr(info.node, "end_lineno", None),
                end_line=getattr(info.node, "end_lineno", None),
                stmts_json=[],
                in_degree=0,
                out_degree=0,
            )
        )
        edges.extend(
            [
                CFGEdgeRow(
                    function_goid_h128=info.goid.h128,
                    src_block_idx=entry_idx,
                    dst_block_idx=body_block_idx,
                    edge_type="fallthrough",
                    cond_json=None,
                ),
                CFGEdgeRow(
                    function_goid_h128=info.goid.h128,
                    src_block_idx=body_block_idx,
                    dst_block_idx=exit_idx,
                    edge_type="fallthrough",
                    cond_json=None,
                ),
            ]
        )
    else:
        body_block_idx = entry_idx
        exit_idx = 1
        blocks.append(
            CFGBlockRow(
                function_goid_h128=info.goid.h128,
                block_idx=exit_idx,
                kind="exit",
                start_line=getattr(info.node, "end_lineno", None),
                end_line=getattr(info.node, "end_lineno", None),
                stmts_json=[],
                in_degree=0,
                out_degree=0,
            )
        )
        edges.append(
            CFGEdgeRow(
                function_goid_h128=info.goid.h128,
                src_block_idx=entry_idx,
                dst_block_idx=exit_idx,
                edge_type="fallthrough",
                cond_json=None,
            )
        )
    _update_degrees(blocks, edges)
    return _CFGResult(blocks=blocks, edges=edges, body_block_idx=body_block_idx)


def _build_dfg_rows(info: FunctionInfo, body_idx: int) -> list[DFGEdgeRow]:
    definitions = _collect_definitions(info.node)
    uses = _collect_uses(info.node)
    def_edges = [
        DFGEdgeRow(
            function_goid_h128=info.goid.h128,
            src_block_idx=0,
            dst_block_idx=body_idx,
            src_symbol=name,
            dst_symbol=name,
            via_phi=False,
            use_kind="def",
        )
        for name in sorted(definitions)
    ]
    use_edges = [
        DFGEdgeRow(
            function_goid_h128=info.goid.h128,
            src_block_idx=body_idx if name in definitions else 0,
            dst_block_idx=body_idx,
            src_symbol=name,
            dst_symbol=name,
            via_phi=False,
            use_kind="use",
        )
        for name in sorted(uses)
    ]
    return [*def_edges, *use_edges]


def _statement_metadata(statements: Iterable[ast.stmt]) -> list[dict[str, object]]:
    return [
        {
            "kind": stmt.__class__.__name__,
            "lineno": getattr(stmt, "lineno", None),
            "end_lineno": getattr(stmt, "end_lineno", None),
        }
        for stmt in statements
    ]


def _update_degrees(blocks: list[CFGBlockRow], edges: Iterable[CFGEdgeRow]) -> None:
    degree_map: dict[int, dict[str, int]] = {
        block["block_idx"]: {"in": 0, "out": 0} for block in blocks
    }
    for edge in edges:
        src = edge["src_block_idx"]
        dst = edge["dst_block_idx"]
        degree_map[src]["out"] += 1
        degree_map[dst]["in"] += 1
    for block in blocks:
        block["in_degree"] = degree_map[block["block_idx"]]["in"]
        block["out_degree"] = degree_map[block["block_idx"]]["out"]


def _collect_definitions(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Assign):
            for target in child.targets:
                names.update(_names_in_target(target))
        if isinstance(child, ast.AnnAssign):
            names.update(_names_in_target(child.target))
        if isinstance(child, ast.AugAssign):
            names.update(_names_in_target(child.target))
        if isinstance(child, ast.arguments):
            for arg in child.args:
                if arg.arg != "self":
                    names.add(arg.arg)
    return names


def _names_in_target(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for element in target.elts:
            names.update(_names_in_target(element))
        return names
    return set()


def _collect_uses(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            names.add(child.id)
    return names


__all__ = [
    "CFGBlockRow",
    "CFGBuilder",
    "CFGEdgeRow",
    "DFGEdgeRow",
    "GraphFlowArtifacts",
]
