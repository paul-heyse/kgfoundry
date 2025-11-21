# SPDX-License-Identifier: MIT
"""Service-level operations for GOID, call graph, CFG/DFG, and AST artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codeintel_rev.enrich.ast_indexer import AstMetricsRow, AstNodeRow, write_ast_parquet
from codeintel_rev.enrich.callgraph import CallGraphBuilder
from codeintel_rev.enrich.cfg import CFGBuilder
from codeintel_rev.enrich.goid_builder import GOIDBuilder
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, DuckDBCatalogOptions
from codeintel_rev.services.enrich.artifacts import GraphArtifactPaths
from codeintel_rev.services.enrich.context import PipelineContext, StageMeta, _stage
from codeintel_rev.services.enrich.graph_support import (
    FileDiscoverySettings,
    collect_python_files,
    detect_commit,
)
from codeintel_rev.services.enrich.io import (
    collect_ast_artifacts,
    normalized_rel_path,
    write_ast_jsonl,
)


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


@dataclass(slots=True, frozen=True)
class ASTArtifactsResult:
    """Result bundle for AST node and metrics emission."""

    nodes_path: Path
    metrics_path: Path
    parquet_dir: Path


@dataclass(slots=True, frozen=True)
class AstCache:
    """Cache containers for AST nodes/metrics keyed by path."""

    nodes: dict[str, list[AstNodeRow]]
    metrics: dict[str, AstMetricsRow]
    hashes: dict[str, str]


def build_goid_artifacts(
    ctx: PipelineContext,
    *,
    out_dir: Path | None = None,
    ingest: bool = False,
    filters: FileDiscoverySettings | None = None,
) -> GOIDArtifactsResult:
    """Build GOID registry and crosswalk artifacts.

    Returns
    -------
    GOIDArtifactsResult
        Paths to the emitted GOID registry and crosswalk datasets.
    """
    target = _ensure_output_dir(out_dir or ctx.paths.data_dir)
    settings = filters or FileDiscoverySettings()
    files = collect_python_files(ctx, settings=settings)
    ast_dir = target / "ast"
    ast_dir.mkdir(parents=True, exist_ok=True)
    node_rows, metric_rows, hashes = _collect_ast_with_cache(ctx, files, ast_dir)
    nodes_path = ast_dir / "ast_nodes.jsonl"
    metrics_path = ast_dir / "ast_metrics.jsonl"
    builder = GOIDBuilder(repo=str(ctx.paths.repo_root), commit=_ctx_commit(ctx))
    with _stage(StageMeta("build-goids", {"files": len(files)})) as meta:
        artifacts = builder.build(node_rows)
        goids_path, crosswalk_path = builder.write_artifacts(artifacts, target)
        write_ast_jsonl(nodes_path, node_rows)
        write_ast_jsonl(metrics_path, metric_rows)
        _write_ast_cache(ast_dir, hashes)
        meta["goids"] = len(artifacts.goids)
        meta["ast_nodes"] = len(node_rows)
        meta["ast_metrics"] = len(metric_rows)
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
    filters: FileDiscoverySettings | None = None,
) -> CallGraphArtifactsResult:
    """Build call graph nodes and edges.

    Returns
    -------
    CallGraphArtifactsResult
        Paths to node and edge Parquet files.
    """
    target = _ensure_output_dir(out_dir or ctx.paths.data_dir)
    settings = filters or FileDiscoverySettings()
    files = collect_python_files(ctx, settings=settings)
    commit = _ctx_commit(ctx)
    builder = CallGraphBuilder(
        repo_root=ctx.paths.repo_root,
        repo=str(ctx.paths.repo_root),
        commit=commit,
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
    filters: FileDiscoverySettings | None = None,
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
    filters : FileDiscoverySettings | None, optional
        Optional include/exclude filters applied to file discovery.

    Returns
    -------
    CFGArtifactsResult
        Paths to CFG block, CFG edge, and DFG edge Parquet files.
    """
    target = _ensure_output_dir(out_dir or ctx.paths.data_dir)
    settings = filters or FileDiscoverySettings()
    files = collect_python_files(ctx, settings=settings)
    commit = _ctx_commit(ctx)
    builder = CFGBuilder(
        repo_root=ctx.paths.repo_root,
        repo=str(ctx.paths.repo_root),
        commit=commit,
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


def _file_hash(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    digest = hashlib.sha256()
    digest.update(data)
    return digest.hexdigest()


def _load_ast_nodes(path: Path) -> dict[str, list[AstNodeRow]]:
    mapping: dict[str, list[AstNodeRow]] = {}
    if not path.exists():
        return mapping
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        rel_path = payload.get("path")
        node = _node_from_payload(payload)
        if isinstance(rel_path, str) and node is not None:
            mapping.setdefault(rel_path, []).append(node)
    return mapping


def _load_ast_metrics(path: Path) -> dict[str, AstMetricsRow]:
    mapping: dict[str, AstMetricsRow] = {}
    if not path.exists():
        return mapping
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        rel_path = payload.get("path")
        metric = _metrics_from_payload(payload)
        if isinstance(rel_path, str) and metric is not None:
            mapping[rel_path] = metric
    return mapping


def _node_from_payload(payload: dict[str, Any]) -> AstNodeRow | None:
    path = payload.get("path")
    module = payload.get("module")
    node_type = payload.get("node_type")
    if not isinstance(path, str) or not isinstance(module, str) or not isinstance(node_type, str):
        return None
    decorators = payload.get("decorators") or []
    bases = payload.get("bases") or []
    try:
        return AstNodeRow(
            path=path,
            module=module,
            qualname=payload.get("qualname"),
            name=payload.get("name"),
            node_type=node_type,
            lineno=_int_or_none(payload.get("lineno")),
            col=_int_or_none(payload.get("col")),
            end_lineno=_int_or_none(payload.get("end_lineno")),
            end_col=_int_or_none(payload.get("end_col")),
            parent_qualname=payload.get("parent_qualname"),
            decorators=tuple(map(str, decorators)),
            bases=tuple(map(str, bases)),
            docstring=payload.get("docstring"),
            is_public=bool(payload.get("is_public")),
        )
    except (TypeError, ValueError):
        return None


def _metrics_from_payload(payload: dict[str, Any]) -> AstMetricsRow | None:
    path = payload.get("path")
    module = payload.get("module")
    if not isinstance(path, str) or not isinstance(module, str):
        return None
    try:
        return AstMetricsRow(
            path=path,
            module=module,
            func_count=_int_or_zero(payload.get("func_count")),
            class_count=_int_or_zero(payload.get("class_count")),
            assign_count=_int_or_zero(payload.get("assign_count")),
            import_count=_int_or_zero(payload.get("import_count")),
            branch_nodes=_int_or_zero(payload.get("branch_nodes")),
            cyclomatic=_int_or_zero(payload.get("cyclomatic")),
            cognitive=_int_or_zero(payload.get("cognitive")),
            max_nesting=_int_or_zero(payload.get("max_nesting")),
            statements=_int_or_zero(payload.get("statements")),
        )
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: object) -> int:
    if not isinstance(value, (int, float, str)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _load_ast_hashes(hashes_path: Path) -> dict[str, str]:
    try:
        hashes_raw = json.loads(hashes_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return hashes_raw if isinstance(hashes_raw, dict) else {}


def _load_ast_cache(ast_dir: Path) -> AstCache:
    hashes = _load_ast_hashes(ast_dir / "ast_hashes.json")
    return AstCache(
        nodes=_load_ast_nodes(ast_dir / "ast_nodes.jsonl"),
        metrics=_load_ast_metrics(ast_dir / "ast_metrics.jsonl"),
        hashes=hashes,
    )


def _write_ast_cache(ast_dir: Path, hashes: dict[str, str]) -> None:
    hashes_path = ast_dir / "ast_hashes.json"
    hashes_path.parent.mkdir(parents=True, exist_ok=True)
    hashes_path.write_text(json.dumps(hashes, indent=2), encoding="utf-8")


def _collect_ast_with_cache(
    ctx: PipelineContext, files: list[Path], ast_dir: Path
) -> tuple[list[AstNodeRow], list[AstMetricsRow], dict[str, str]]:
    cache = _load_ast_cache(ast_dir)
    node_rows: list[AstNodeRow] = []
    metric_rows: list[AstMetricsRow] = []
    new_hashes: dict[str, str] = dict(cache.hashes)
    to_process: list[Path] = []
    for file_path in files:
        rel_path = normalized_rel_path(file_path, ctx.paths.repo_root)
        file_hash = _file_hash(file_path)
        if file_hash is not None and cache.hashes.get(rel_path) == file_hash:
            node_rows.extend(cache.nodes.get(rel_path, []))
            metric = cache.metrics.get(rel_path)
            if metric:
                metric_rows.append(metric)
            new_hashes[rel_path] = file_hash
            continue
        to_process.append(file_path)
    if to_process:
        fresh_nodes, fresh_metrics = collect_ast_artifacts(ctx.paths.repo_root, to_process)
        node_rows.extend(fresh_nodes)
        metric_rows.extend(fresh_metrics)
        for fp in to_process:
            rel = normalized_rel_path(fp, ctx.paths.repo_root)
            file_hash = _file_hash(fp)
            if file_hash is not None:
                new_hashes[rel] = file_hash
    return node_rows, metric_rows, new_hashes


def _open_catalog(ctx: PipelineContext) -> DuckDBCatalog:
    ctx.paths.vectors_dir.mkdir(parents=True, exist_ok=True)
    options = DuckDBCatalogOptions(repo_root=ctx.paths.repo_root)
    return DuckDBCatalog(ctx.paths.duckdb_path, ctx.paths.vectors_dir, options=options)


def _ctx_commit(ctx: PipelineContext) -> str:
    return ctx.commit or detect_commit(ctx.paths.repo_root)


def build_ast_artifacts(
    ctx: PipelineContext,
    *,
    out_dir: Path | None = None,
    filters: FileDiscoverySettings | None = None,
) -> ASTArtifactsResult:
    """Emit AST nodes/metrics parquet + JSONL pairs.

    Returns
    -------
    ASTArtifactsResult
        Paths to emitted AST node/metrics JSONL files and the Parquet directory.
    """
    target = _ensure_output_dir(out_dir or ctx.paths.data_dir)
    settings = filters or FileDiscoverySettings()
    files = collect_python_files(ctx, settings=settings)
    ast_dir = target / "ast"
    with _stage(StageMeta("build-ast", {"files": len(files)})) as meta:
        node_rows, metric_rows, hashes = _collect_ast_with_cache(ctx, files, ast_dir)
        ast_dir.mkdir(parents=True, exist_ok=True)
        nodes_path = ast_dir / "ast_nodes.jsonl"
        metrics_path = ast_dir / "ast_metrics.jsonl"
        write_ast_jsonl(nodes_path, node_rows)
        write_ast_jsonl(metrics_path, metric_rows)
        write_ast_parquet(node_rows, metric_rows, out_dir=ast_dir)
        _write_ast_cache(ast_dir, hashes)
        meta["nodes"] = len(node_rows)
        meta["metrics"] = len(metric_rows)
    return ASTArtifactsResult(
        nodes_path=nodes_path,
        metrics_path=metrics_path,
        parquet_dir=ast_dir,
    )


def build_graph_manifest(ctx: PipelineContext, base_dir: Path | None = None) -> GraphArtifactPaths:
    """Return the normalized artifact paths under ``base_dir`` (or ctx.data_dir).

    Returns
    -------
    GraphArtifactPaths
        Manifest of graph/AST artifact locations under the chosen output dir.
    """
    out_dir = base_dir or ctx.paths.data_dir
    graphs_dir = out_dir / "graphs"
    goid_dir = out_dir / "goid"
    ast_dir = out_dir / "ast"
    return GraphArtifactPaths(
        goids=goid_dir / "goids.parquet",
        goid_xwalk=goid_dir / "goid_xwalk.parquet",
        call_nodes=graphs_dir / "call_nodes.parquet",
        call_edges=graphs_dir / "call_edges.parquet",
        cfg_blocks=graphs_dir / "cfg_blocks.parquet",
        cfg_edges=graphs_dir / "cfg_edges.parquet",
        dfg_edges=graphs_dir / "dfg_edges.parquet",
        import_edges=graphs_dir / "import_graph_edges.parquet",
        symbol_use_edges=graphs_dir / "symbol_use_edges.parquet",
        ast_nodes=ast_dir / "ast_nodes.parquet",
        ast_metrics=ast_dir / "ast_metrics.parquet",
        ast_dir=ast_dir,
    )


__all__ = [
    "ASTArtifactsResult",
    "CFGArtifactsResult",
    "CallGraphArtifactsResult",
    "GOIDArtifactsResult",
    "build_ast_artifacts",
    "build_callgraph_artifacts",
    "build_cfg_artifacts",
    "build_goid_artifacts",
    "build_graph_manifest",
]
