# SPDX-License-Identifier: MIT
"""Analytics augmentation helpers for enrichment."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from codeintel_rev.enrich.graph_builder import (
    ImportGraph,
    build_import_graph,
)
from codeintel_rev.enrich.models import ModuleRecord
from codeintel_rev.enrich.pipeline_helpers import apply_tagging as _apply_tagging
from codeintel_rev.enrich.scip_reader import SCIPIndex
from codeintel_rev.export_resolver import build_module_name_map, resolve_exports
from codeintel_rev.risk_hotspots import compute_hotspot_score
from codeintel_rev.services.enrich.context import (
    OVERLAY_ERROR_THRESHOLD,
    OVERLAY_FAN_IN_THRESHOLD,
    OVERLAY_PARAM_THRESHOLD,
    AnalyticsArtifacts,
    ConfigReferenceState,
    LegacyPipelineContext,
    PipelineContext,
    StageMeta,
    _stage,
)
from codeintel_rev.services.enrich.models import ModuleRecord as SimpleModuleRecord
from codeintel_rev.uses_builder import UseGraph, build_use_graph


def compute_pipeline_analytics(
    ctx: LegacyPipelineContext,
    module_rows: list[ModuleRecord],
) -> AnalyticsArtifacts:
    """Compute analytics artifacts for module rows.

    Parameters
    ----------
    ctx : LegacyPipelineContext
        Pipeline context containing SCIP index, config records, tagging rules,
        and package prefix.
    module_rows : list[ModuleRecord]
        List of module records to compute analytics for. Modified in place
        with additional metadata fields.

    Returns
    -------
    AnalyticsArtifacts
        Aggregated graphs and tabular analytics including import graph, use
        graph, config index, coverage rows, hotspot rows, and tag index.
    """
    with _stage(StageMeta("analytics", {"modules": len(module_rows)})) as meta:
        import_graph, use_graph, config_index = augment_module_rows(
            module_rows,
            ctx.scip_index,
            ctx.package_prefix,
            config_records=ctx.config_records,
        )
        coverage_rows = build_coverage_rows(module_rows)
        hotspot_rows = build_hotspot_rows(module_rows)
        meta["configs"] = len(config_index)
        meta["coverage_rows"] = len(coverage_rows)
        meta["hotspots"] = len(hotspot_rows)
    infer_tags(module_rows, ctx.tagging_rules)
    tag_index = build_tag_index(module_rows)
    return AnalyticsArtifacts(
        import_graph=import_graph,
        use_graph=use_graph,
        config_index=config_index,
        coverage_rows=coverage_rows,
        hotspot_rows=hotspot_rows,
        tag_index=tag_index,
    )


def prepare_config_state(
    records: list[dict[str, Any]] | None,
) -> ConfigReferenceState:
    """Materialize config reference tracking state.

    Parameters
    ----------
    records : list[dict[str, Any]] | None, optional
        Optional list of config record dictionaries. If None, uses empty list.

    Returns
    -------
    ConfigReferenceState
        Populated record/index mapping with empty references. Records are
        grouped by directory for efficient lookup.
    """
    materialized = records or []
    return ConfigReferenceState(
        records=materialized,
        by_dir=group_configs_by_dir(materialized),
        references={record["path"]: set() for record in materialized},
    )


def augment_module_rows(
    module_rows: list[ModuleRecord],
    scip_index: SCIPIndex,
    package_prefix: str | None,
    *,
    config_records: list[dict[str, Any]] | None = None,
) -> tuple[ImportGraph, UseGraph, list[dict[str, Any]]]:
    """Attach graph/usage/export metadata and emit module artifacts.

    Parameters
    ----------
    module_rows : list[ModuleRecord]
        List of module records to augment. Modified in place with graph metrics,
        export resolution, usage counts, config references, overlay flags,
        and hotspot scores.
    scip_index : SCIPIndex
        SCIP index for building use graphs and symbol usage analysis.
    package_prefix : str | None, optional
        Optional package prefix for module name resolution and import graph
        building.
    config_records : list[dict[str, Any]] | None, optional
        Optional list of config record dictionaries for reference tracking.
        If None, uses empty list.

    Returns
    -------
    tuple[ImportGraph, UseGraph, list[dict[str, Any]]]
        Import graph, use graph, and config records with populated references.
    """
    module_name_map = build_module_name_map(module_rows, package_prefix)
    import_graph = build_import_graph(module_rows, package_prefix)
    use_graph = build_use_graph(scip_index)
    config_state = prepare_config_state(config_records)

    for row in module_rows:
        exports_resolved, reexports = resolve_exports(
            row,
            module_name_map,
            package_prefix=package_prefix,
        )
        if exports_resolved:
            row["exports_resolved"] = exports_resolved
        if reexports:
            row["reexports"] = reexports
        path = str(row.get("path"))
        row["fan_in"] = import_graph.fan_in.get(path, 0)
        row["fan_out"] = import_graph.fan_out.get(path, 0)
        row["cycle_group"] = import_graph.cycle_group.get(path, -1)
        internal_imports = sorted(import_graph.edges.get(path, set()))
        if internal_imports:
            row["imports_internal"] = internal_imports
            row["imports_intra_repo"] = internal_imports
        uses = use_graph.uses_by_file.get(path, set()) or set()
        row["used_by_files"] = len(uses)
        row["used_by_symbols"] = use_graph.symbol_usage.get(path, 0)
        refs = config_refs_for_row(path, config_state.by_dir)
        row["config_refs"] = refs
        for ref in refs:
            config_state.references.setdefault(ref, set()).add(path)
        overlay_needed = should_mark_overlay(row)
        row["overlay_needed"] = overlay_needed
        if overlay_needed:
            current_tags = row.get("tags")
            tag_list = current_tags if isinstance(current_tags, list) else []
            tag_set = {str(tag) for tag in tag_list}
            tag_set.add("overlay-needed")
            row["tags"] = sorted(tag_set)
        row["hotspot_score"] = compute_hotspot_score(row)
    for record in config_state.records:
        referenced = config_state.references.get(record["path"], set())
        record["references"] = sorted(referenced)
    return import_graph, use_graph, config_state.records


def build_tag_index(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Return tag -> path mapping.

    Parameters
    ----------
    rows : Sequence[Mapping[str, Any]]
        Sequence of module record dictionaries containing "tags" and "path"
        fields.

    Returns
    -------
    dict[str, list[str]]
        Mapping of tag to associated module paths. Rows with invalid or
        missing tags/paths are skipped.
    """
    tag_index: dict[str, list[str]] = {}
    for row in rows:
        tags = row.get("tags") or []
        path = row.get("path")
        if not isinstance(path, str) or not isinstance(tags, list):
            continue
        for tag in tags:
            if not isinstance(tag, str):
                continue
            tag_index.setdefault(tag, []).append(path)
    return tag_index


def infer_tags(rows: list[ModuleRecord], rules: Mapping[str, Any]) -> None:
    """Apply tagging rules with logging/telemetry.

    Parameters
    ----------
    rows : list[ModuleRecord]
        List of module records to tag. Modified in place with inferred tags.
    rules : Mapping[str, Any]
        Tagging rules dictionary mapping rule names to rule configurations.
    """
    with _stage(StageMeta("tagging", {"rules": len(rules)})) as meta:
        _apply_tagging(rows, rules)
        meta["tagged"] = sum(1 for row in rows if row.get("tags"))


def build_coverage_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Build structured coverage rows from module metadata.

    Parameters
    ----------
    rows : Sequence[Mapping[str, Any]]
        Sequence of module record dictionaries containing coverage metadata
        fields like "covered_lines_ratio" and "covered_defs_ratio".

    Returns
    -------
    list[dict[str, Any]]
        Coverage summary rows keyed by path, with default values of 0.0
        for missing coverage ratios.
    """
    return [
        {
            "path": row.get("path"),
            "covered_lines_ratio": float(row.get("covered_lines_ratio") or 0.0),
            "covered_defs_ratio": float(row.get("covered_defs_ratio") or 0.0),
        }
        for row in rows
    ]


def build_hotspot_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Build hotspot summary rows.

    Parameters
    ----------
    rows : Sequence[Mapping[str, Any]]
        Sequence of module record dictionaries containing hotspot score
        and path information.

    Returns
    -------
    list[dict[str, Any]]
        Lightweight hotspot records containing path and hotspot_score fields.
    """
    return [
        {
            "path": row.get("path"),
            "hotspot_score": float(row.get("hotspot_score") or 0.0),
            "fan_in": int(row.get("fan_in") or 0),
            "fan_out": int(row.get("fan_out") or 0),
            "type_error_count": int(row.get("type_error_count") or row.get("type_errors") or 0),
            "used_by_files": int(row.get("used_by_files") or 0),
        }
        for row in rows
    ]


def basic_stats(
    ctx: PipelineContext,
    records: list[SimpleModuleRecord],
) -> Mapping[str, Any]:
    """Return simple analytics for the refactored CLI commands.

    Parameters
    ----------
    ctx : PipelineContext
        Pipeline context containing logger for analytics logging.
    records : list[SimpleModuleRecord]
        List of module records to compute statistics for.

    Returns
    -------
    Mapping[str, Any]
        Summary containing ``files`` (file count), ``loc_total`` (total lines
        of code), and ``tags`` (tag frequency dictionary).
    """
    file_count = len(records)
    loc_total = sum(record.loc for record in records)
    tags = Counter(tag for record in records for tag in record.tags)
    ctx.logger.info(
        "Analytics summary: files=%d loc=%d distinct_tags=%d",
        file_count,
        loc_total,
        len(tags),
    )
    return {"files": file_count, "loc_total": loc_total, "tags": dict(tags)}


def group_configs_by_dir(records: list[dict[str, Any]]) -> dict[str, tuple[str, ...]]:
    """Group config records by containing directory.

    Parameters
    ----------
    records : list[dict[str, Any]]
        List of config record dictionaries containing "path" fields.

    Returns
    -------
    dict[str, tuple[str, ...]]
        Directory key to config path mapping. Records with invalid or missing
        paths are skipped.
    """
    grouped: dict[str, list[str]] = {}
    for record in records:
        path = record.get("path")
        if not isinstance(path, str):
            continue
        dir_key = dir_key_from_path(Path(path).parent)
        grouped.setdefault(dir_key, []).append(path)
    return {key: tuple(paths) for key, paths in grouped.items()}


def config_refs_for_row(
    module_path: str,
    config_by_dir: Mapping[str, Sequence[str]],
) -> list[str]:
    """Return config references scoped to ancestor directories.

    Parameters
    ----------
    module_path : str
        Module file path to find config references for.
    config_by_dir : Mapping[str, Sequence[str]]
        Dictionary mapping directory keys to lists of config file paths.

    Returns
    -------
    list[str]
        Config file paths referenced by the module path. Returns empty list
        if no matching configs are found.
    """
    dirs = ancestor_dirs(module_path)
    seen: set[str] = set()
    refs: list[str] = []
    for directory in dirs:
        for candidate in config_by_dir.get(directory, []):
            if candidate in seen:
                continue
            refs.append(candidate)
            seen.add(candidate)
    return refs


def ancestor_dirs(path: str) -> list[str]:
    """Return normalized ancestor directory keys for ``path``.

    Parameters
    ----------
    path : str
        File path to compute ancestor directories for.

    Returns
    -------
    list[str]
        Directory keys ordered from nearest to farthest ancestor.
    """
    ancestors: list[str] = []
    current = Path(path).parent
    while True:
        key = dir_key_from_path(current)
        if key:
            ancestors.append(key)
        if not key:
            break
        if current == current.parent:
            break
        current = current.parent
    return ancestors


def dir_key_from_path(path: Path) -> str:
    """Return normalized directory path key.

    Parameters
    ----------
    path : Path
        Directory path to normalize.

    Returns
    -------
    str
        Forward-slash-separated directory representation (may be empty).
        Normalized string suitable for use as a dictionary key.
    """
    rendered = str(path)
    if rendered in {"", "."}:
        return ""
    return rendered.replace("\\", "/")


def should_mark_overlay(row: Mapping[str, Any]) -> bool:
    """Return True if row should be marked overlay-needed.

    Parameters
    ----------
    row : Mapping[str, Any]
        Module record dictionary containing type error counts, fan-in metrics,
        and parameter counts.

    Returns
    -------
    bool
        ``True`` when overlay heuristics deem the module a candidate based on
        type error count, fan-in, or parameter thresholds (as defined by
        OVERLAY_ERROR_THRESHOLD, OVERLAY_FAN_IN_THRESHOLD, and
        OVERLAY_PARAM_THRESHOLD constants).
    """
    type_errors = int(row.get("type_errors") or row.get("type_error_count") or 0)
    if type_errors == 0:
        return False
    ratio = row.get("annotation_ratio")
    params_ratio = 1.0
    returns_ratio = 1.0
    if isinstance(ratio, Mapping):
        params_ratio = float(ratio.get("params", 1.0))
        returns_ratio = float(ratio.get("returns", 1.0))
    untyped_defs = int(row.get("untyped_defs") or 0)
    fan_in = int(row.get("fan_in") or 0)
    exports = row.get("exports") or row.get("exports_declared") or []
    reexports = row.get("reexports") or {}
    tags = row.get("tags") or []
    is_public = (
        bool(exports) or bool(reexports) or (isinstance(tags, list) and "public-api" in tags)
    )
    needs_annotations = (
        (params_ratio < OVERLAY_PARAM_THRESHOLD)
        or (returns_ratio < OVERLAY_PARAM_THRESHOLD)
        or (untyped_defs > 0)
    )
    return bool(
        is_public
        and needs_annotations
        and (fan_in >= OVERLAY_FAN_IN_THRESHOLD or type_errors >= OVERLAY_ERROR_THRESHOLD)
    )


__all__ = [
    "augment_module_rows",
    "build_coverage_rows",
    "build_hotspot_rows",
    "build_tag_index",
    "compute_pipeline_analytics",
    "config_refs_for_row",
    "dir_key_from_path",
    "group_configs_by_dir",
    "infer_tags",
    "prepare_config_state",
    "should_mark_overlay",
]
