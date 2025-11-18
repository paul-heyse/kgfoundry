# SPDX-License-Identifier: MIT
"""Enrichment export orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codeintel_rev.enrich.ast_indexer import write_ast_parquet
from codeintel_rev.enrich.graph_builder import write_import_graph
from codeintel_rev.enrich.output_writers import (
    write_json,
    write_jsonl,
    write_parquet,
    write_parquet_dataset,
)
from codeintel_rev.enrich.ownership import OwnershipIndex, compute_ownership
from codeintel_rev.enrich.slices_builder import build_slice_record, write_slice
from codeintel_rev.services.enrich.context import PipelineResult, StageMeta, _stage
from codeintel_rev.services.enrich.io import (
    collect_ast_artifacts,
    write_ast_jsonl,
    write_markdown_modules,
    write_modules_json,
    write_symbol_graph,
    write_tabular_records,
    write_tag_index,
)
from codeintel_rev.uses_builder import write_use_graph


def write_exports_outputs(result: PipelineResult, out: Path) -> None:
    """Write modules.jsonl, markdown sheets, repo map, and tag index."""
    with _stage(StageMeta("write-exports", {"modules": len(result.module_rows)})) as meta:
        write_modules_json(out, result.module_rows)
        write_markdown_modules(out, result.module_rows)
        write_repo_map(out, result)
        write_tag_index(out, result.tag_index)
        meta["tag_groups"] = len(result.tag_index)


def write_graph_outputs(result: PipelineResult, out: Path) -> None:
    """Write symbol/import graphs."""
    with _stage(StageMeta("write-graphs", {"symbols": len(result.symbol_edges)})) as meta:
        write_symbol_graph(out, result.symbol_edges)
        write_import_graph(result.import_graph, out / "graphs" / "imports.parquet")
        meta["imports"] = sum(len(edges) for edges in result.import_graph.edges.values())


def write_uses_output(result: PipelineResult, out: Path) -> None:
    """Write uses graph parquet."""
    with _stage(StageMeta("write-uses", {"files": len(result.use_graph.uses_by_file)})) as meta:
        write_use_graph(result.use_graph, out / "graphs" / "uses.parquet")
        meta["edges"] = sum(len(paths) for paths in result.use_graph.uses_by_file.values())


def apply_ownership(
    result: PipelineResult,
    out: Path,
    *,
    history_window_days: int,
    commits_window: int,
) -> OwnershipIndex:
    """Compute ownership analytics and attach to module rows.

    Returns
    -------
    OwnershipIndex
        Ownership records keyed by repo path.
    """
    churn_windows = (30, max(1, history_window_days))
    repo_paths = [str(row.get("repo_path") or row.get("path") or "") for row in result.module_rows]
    ownership = compute_ownership(
        result.repo_root,
        repo_paths,
        commits_window=max(1, commits_window),
        churn_windows=churn_windows,
    )
    for row in result.module_rows:
        key = str(row.get("repo_path") or row.get("path") or "")
        entry = ownership.by_file.get(key)
        if entry is None:
            continue
        row["owner"] = entry.owner
        row["primary_authors"] = list(entry.primary_authors)
        row["bus_factor"] = entry.bus_factor
        for window, churn in entry.churn_by_window.items():
            row[f"recent_churn_{window}"] = churn
    write_ownership_output(ownership, out)
    return ownership


def write_ownership_output(ownership: OwnershipIndex, out: Path) -> None:
    """Persist ownership analytics."""
    rows: list[dict[str, Any]] = []
    for path, entry in ownership.by_file.items():
        record: dict[str, Any] = {
            "path": path,
            "owner": entry.owner,
            "primary_authors": list(entry.primary_authors),
            "bus_factor": entry.bus_factor,
        }
        for window, churn in entry.churn_by_window.items():
            record[f"recent_churn_{window}"] = churn
        rows.append(record)
    write_parquet(out / "analytics" / "ownership.parquet", rows)


def write_slices_output(
    module_rows: Sequence[Mapping[str, Any]],
    out: Path,
    *,
    slices_filter: list[str] | None = None,
) -> None:
    """Emit tag slices when enabled."""
    filters = tuple(filter(None, slices_filter or []))
    slice_payloads: list[dict[str, Any]] = []
    for row in module_rows:
        tags = {tag for tag in row.get("tags") or [] if isinstance(tag, str)}
        if filters and not tags.intersection(filters):
            continue
        slice_record = build_slice_record(row)
        write_slice(out, slice_record)
        slice_payloads.append(asdict(slice_record))
    slices_dir = out / "slices"
    slices_dir.mkdir(parents=True, exist_ok=True)
    dataset_rows = [
        {
            "slice_id": record["slice_id"],
            "path": record["path"],
            "module_name": record.get("module_name") or "",
            "owner": (record.get("owners") or {}).get("owner") or "unowned",
            "tags": ",".join(record.get("tags") or []),
        }
        for record in slice_payloads
    ]
    write_parquet(slices_dir / "index.parquet", dataset_rows)
    write_parquet_dataset(
        slices_dir / "index_dataset",
        dataset_rows,
        partitioning=("owner",),
        dictionary_fields=("module_name",),
    )
    write_jsonl(slices_dir / "slices.jsonl", slice_payloads)
    write_json(out / "analytics" / "slices.json", slice_payloads)


def write_typedness_output(result: PipelineResult, out: Path) -> None:
    """Write typedness analytics datasets."""
    rows = [
        {
            "path": row.get("path"),
            "type_error_count": int(row.get("type_error_count") or 0),
            "annotation_ratio": row.get("annotation_ratio"),
            "untyped_defs": row.get("untyped_defs"),
            "overlay_needed": row.get("overlay_needed", False),
        }
        for row in result.module_rows
    ]
    write_tabular_records(out / "analytics" / "typedness.parquet", rows)


def write_doc_output(result: PipelineResult, out: Path) -> None:
    """Write documentation health analytics."""
    rows = [
        {
            "path": row.get("path"),
            "docstring": row.get("docstring"),
            "doc_has_summary": row.get("doc_has_summary"),
            "doc_param_parity": row.get("doc_param_parity"),
            "doc_examples_present": row.get("doc_examples_present"),
        }
        for row in result.module_rows
    ]
    write_tabular_records(out / "analytics" / "doc_health.parquet", rows)


def write_coverage_output(result: PipelineResult, out: Path) -> None:
    """Persist coverage summary."""
    write_tabular_records(out / "analytics" / "coverage.parquet", result.coverage_rows)


def write_config_output(result: PipelineResult, out: Path) -> None:
    """Persist config index with references."""
    write_json(out / "analytics" / "config_index.json", result.config_index)


def write_hotspot_output(result: PipelineResult, out: Path) -> None:
    """Persist hotspot analytics."""
    write_tabular_records(out / "analytics" / "hotspots.parquet", result.hotspot_rows)


def write_ast_outputs(result: PipelineResult, out: Path, *, emit_ast: bool) -> None:
    """Write AST nodes + metrics if enabled."""
    if not emit_ast:
        return
    files = [
        (result.repo_root / Path(row.get("path") or "")).resolve()
        for row in result.module_rows
        if row.get("path")
    ]
    node_rows, metric_rows = collect_ast_artifacts(result.repo_root, files)
    ast_dir = out / "ast"
    write_ast_jsonl(ast_dir / "ast_nodes.jsonl", node_rows)
    write_ast_jsonl(ast_dir / "ast_metrics.jsonl", metric_rows)
    write_ast_parquet(node_rows, metric_rows, out_dir=ast_dir)


def write_repo_map(out: Path, result: PipelineResult) -> None:
    """Write repo_map.json summary."""
    tag_counts = {tag: len(paths) for tag, paths in result.tag_index.items()}
    write_json(
        out / "repo_map.json",
        {
            "root": str(result.root),
            "repo_root": str(result.repo_root),
            "module_count": len(result.module_rows),
            "symbol_edge_count": len(result.symbol_edges),
            "coverage_records": len(result.coverage_rows),
            "config_files": len(result.config_index),
            "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
            "tags": result.tag_index,
            "tag_counts": tag_counts,
        },
    )


__all__ = [
    "apply_ownership",
    "write_ast_outputs",
    "write_config_output",
    "write_coverage_output",
    "write_doc_output",
    "write_exports_outputs",
    "write_graph_outputs",
    "write_hotspot_output",
    "write_ownership_output",
    "write_repo_map",
    "write_slices_output",
    "write_typedness_output",
    "write_uses_output",
]
