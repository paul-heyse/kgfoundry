# SPDX-License-Identifier: MIT
"""Service-level operations for GOID, call graph, CFG, and DFG artifacts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from codeintel_rev.enrich.callgraph import CallGraphBuilder
from codeintel_rev.enrich.cfg import CFGBuilder
from codeintel_rev.enrich.goid_builder import GOIDBuilder
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, DuckDBCatalogOptions
from codeintel_rev.services.enrich.context import PipelineContext, StageMeta, _stage
from codeintel_rev.services.enrich.graph_support import collect_python_files, detect_commit
from codeintel_rev.services.enrich.io import collect_ast_artifacts


@dataclass(slots=True, frozen=True)
class GOIDArtifactsResult:
    """Result bundle for GOID artifact construction."""

    goids_path: Path
    crosswalk_path: Path


@dataclass(slots=True, frozen=True)
class CallGraphArtifactsResult:
    """Result bundle for call graph artifact construction."""

    nodes_path: Path
    edges_path: Path


@dataclass(slots=True, frozen=True)
class CFGArtifactsResult:
    """Result bundle for CFG/DFG artifact construction."""

    blocks_path: Path
    edges_path: Path
    dfg_path: Path


def build_goid_artifacts(
    ctx: PipelineContext,
    *,
    out_dir: Path | None = None,
    ingest: bool = False,
    include: Sequence[str] | None = None,
) -> GOIDArtifactsResult:
    """Build GOID registry and crosswalk artifacts.

    Returns
    -------
    GOIDArtifactsResult
        Paths to the emitted GOID registry and crosswalk datasets.
    """
    target = _ensure_output_dir(out_dir or ctx.paths.data_dir)
    files = collect_python_files(ctx, include=include)
    builder = GOIDBuilder(repo=str(ctx.paths.repo_root), commit=detect_commit(ctx.paths.repo_root))
    with _stage(StageMeta("build-goids", {"files": len(files)})) as meta:
        node_rows, _ = collect_ast_artifacts(ctx.paths.repo_root, files)
        artifacts = builder.build(node_rows)
        goids_path, crosswalk_path = builder.write_artifacts(artifacts, target)
        meta["goids"] = len(artifacts.goids)
        if ingest:
            catalog = _open_catalog(ctx)
            catalog.upsert_goids(artifacts.goids)
            catalog.upsert_goid_xwalk(artifacts.crosswalks)
            meta["ingested"] = True
    return GOIDArtifactsResult(goids_path=goids_path, crosswalk_path=crosswalk_path)


def build_callgraph_artifacts(
    ctx: PipelineContext,
    *,
    out_dir: Path | None = None,
    ingest: bool = False,
    include: Sequence[str] | None = None,
) -> CallGraphArtifactsResult:
    """Build call graph nodes and edges.

    Returns
    -------
    CallGraphArtifactsResult
        Paths to node and edge Parquet files.
    """
    target = _ensure_output_dir(out_dir or ctx.paths.data_dir)
    files = collect_python_files(ctx, include=include)
    builder = CallGraphBuilder(
        repo_root=ctx.paths.repo_root,
        repo=str(ctx.paths.repo_root),
        commit=detect_commit(ctx.paths.repo_root),
    )
    with _stage(StageMeta("build-callgraph", {"files": len(files)})) as meta:
        artifacts = builder.build(files)
        nodes_path, edges_path = builder.write_artifacts(artifacts, target)
        meta["nodes"] = len(artifacts.nodes)
        meta["edges"] = len(artifacts.edges)
        if ingest:
            catalog = _open_catalog(ctx)
            catalog.upsert_goids(artifacts.goids)
            catalog.upsert_call_nodes(artifacts.nodes)
            catalog.upsert_call_edges(artifacts.edges)
            meta["ingested"] = True
    return CallGraphArtifactsResult(nodes_path=nodes_path, edges_path=edges_path)


def build_cfg_artifacts(
    ctx: PipelineContext,
    *,
    out_dir: Path | None = None,
    ingest_cfg: bool = False,
    ingest_dfg: bool = False,
    include: Sequence[str] | None = None,
) -> CFGArtifactsResult:
    """Build CFG and DFG artifacts for Python functions.

    Parameters
    ----------
    ctx : PipelineContext
        Pipeline context describing repo paths.
    out_dir : Path | None, optional
        Output directory for graph artifacts. Defaults to ctx paths data dir.
    ingest_cfg : bool, optional
        When True, upsert CFG blocks/edges and GOIDs into DuckDB.
    ingest_dfg : bool, optional
        When True, upsert DFG edges (and GOIDs if needed) into DuckDB.
    include : Sequence[str] | None, optional
        Optional tuple of include globs restricting which files are analyzed.

    Returns
    -------
    CFGArtifactsResult
        Paths to CFG block, CFG edge, and DFG edge Parquet files.
    """
    target = _ensure_output_dir(out_dir or ctx.paths.data_dir)
    files = collect_python_files(ctx, include=include)
    builder = CFGBuilder(
        repo_root=ctx.paths.repo_root,
        repo=str(ctx.paths.repo_root),
        commit=detect_commit(ctx.paths.repo_root),
    )
    with _stage(StageMeta("build-cfg", {"files": len(files)})) as meta:
        artifacts = builder.build(files)
        blocks_path, cfg_edges_path, dfg_path = builder.write_artifacts(artifacts, target)
        meta["blocks"] = len(artifacts.blocks)
        meta["cfg_edges"] = len(artifacts.cfg_edges)
        meta["dfg_edges"] = len(artifacts.dfg_edges)
        if ingest_cfg or ingest_dfg:
            catalog = _open_catalog(ctx)
            catalog.upsert_goids(artifacts.goids)
            if ingest_cfg:
                catalog.upsert_cfg_blocks(artifacts.blocks)
                catalog.upsert_cfg_edges(artifacts.cfg_edges)
            if ingest_dfg:
                catalog.upsert_dfg_edges(artifacts.dfg_edges)
            meta["ingested_cfg"] = ingest_cfg
            meta["ingested_dfg"] = ingest_dfg
    return CFGArtifactsResult(blocks_path=blocks_path, edges_path=cfg_edges_path, dfg_path=dfg_path)


def _ensure_output_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _open_catalog(ctx: PipelineContext) -> DuckDBCatalog:
    ctx.paths.vectors_dir.mkdir(parents=True, exist_ok=True)
    options = DuckDBCatalogOptions(repo_root=ctx.paths.repo_root)
    return DuckDBCatalog(ctx.paths.duckdb_path, ctx.paths.vectors_dir, options=options)


__all__ = [
    "CFGArtifactsResult",
    "CallGraphArtifactsResult",
    "GOIDArtifactsResult",
    "build_callgraph_artifacts",
    "build_cfg_artifacts",
    "build_goid_artifacts",
]
