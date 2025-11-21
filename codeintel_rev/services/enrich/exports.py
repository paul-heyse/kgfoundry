# SPDX-License-Identifier: MIT
"""Enrichment export orchestration."""
# ruff: noqa: PLR0913

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import libcst as cst
from pydantic import BaseModel

from codeintel_rev.enrich.ast_indexer import write_ast_parquet
from codeintel_rev.enrich.graph_builder import write_import_graph
from codeintel_rev.enrich.models import ModuleRecord
from codeintel_rev.enrich.output_writers import (
    write_json,
    write_jsonl,
    write_parquet,
    write_parquet_dataset,
    write_parquet_or_jsonl,
)
from codeintel_rev.enrich.ownership import OwnershipIndex, compute_ownership
from codeintel_rev.enrich.slices_builder import build_slice_record, write_slice
from codeintel_rev.ids.goid import RepoSnapshot
from codeintel_rev.services.enrich.analytics import prepare_config_state
from codeintel_rev.services.enrich.artifact_schemas import (
    ConfigRecordModel,
    CoverageRowModel,
    DocHealthRowModel,
    FunctionMetricRowModel,
    FunctionTypeRowModel,
    HotspotRowModel,
    TagIndexModel,
)
from codeintel_rev.services.enrich.config_values import build_config_value_rows
from codeintel_rev.services.enrich.context import (
    PipelineContext,
    PipelineResult,
    StageMeta,
    _stage,
)
from codeintel_rev.services.enrich.function_metrics import (
    FunctionMetricsRow,
    build_function_metrics,
    prepare_function_metrics_parquet,
)
from codeintel_rev.services.enrich.function_types import (
    FunctionTypesRow,
    build_function_types,
    prepare_function_types_parquet,
)
from codeintel_rev.services.enrich.graph_support import detect_commit
from codeintel_rev.services.enrich.io import (
    atomic_write_text,
    collect_ast_artifacts,
    write_ast_jsonl,
    write_markdown_modules,
    write_modules_json,
    write_symbol_graph,
    write_tabular_records,
    write_tag_index,
)
from codeintel_rev.services.enrich.io import (
    write_jsonl as simple_write_jsonl,
)
from codeintel_rev.services.enrich.models import ExportResult
from codeintel_rev.services.enrich.record_view import ModuleRecordView, as_record_view
from codeintel_rev.services.enrich.static_diagnostics import (
    STATIC_DIAGNOSTICS_SCHEMA,
    build_static_diagnostics_rows,
)
from codeintel_rev.typedness import FileTypeSignals
from codeintel_rev.uses_builder import write_use_graph

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class FunctionCachingState:
    """Caches and hashes for function analytics."""

    metrics_cache: dict[str, list[dict[str, Any]]]
    types_cache: dict[str, list[dict[str, Any]]]
    prior_hashes: dict[str, str]


def _module_by_path(rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Build a mapping from repo-relative paths to module names.

    Parameters
    ----------
    rows : Sequence[Mapping[str, Any]]
        Database rows with path and module_name/module fields.

    Returns
    -------
    dict[str, str]
        Mapping from file paths to module names (falls back to path if module missing).
    """
    mapping: dict[str, str] = {}
    for row in rows:
        path = row.get("path")
        module_name = row.get("module_name") or row.get("module")
        if isinstance(path, str):
            mapping[path] = module_name if isinstance(module_name, str) else path
    return mapping


def _mirror_artifact(source: Path, alias: Path) -> None:
    """Copy artifact to a legacy alias if needed."""
    if source == alias:
        return
    if not source.exists():
        return
    alias.parent.mkdir(parents=True, exist_ok=True)
    alias.write_bytes(source.read_bytes())


def _existing_paths(paths: Iterable[Path]) -> dict[str, str]:
    """Return mapping of filename to stringified paths for existing files.

    Parameters
    ----------
    paths : Iterable[Path]
        Candidate file paths to inspect.

    Returns
    -------
    dict[str, str]
        Mapping from filename to absolute path for entries that exist on disk.
    """
    return {path.name: str(path) for path in paths if path.exists()}


def _write_validated_tabular(
    parquet_path: Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    model: type[BaseModel],
) -> None:
    """Validate rows against ``model`` then write Parquet + JSONL sidecar."""
    validated = [model.model_validate(row).model_dump() for row in rows]
    write_parquet(parquet_path, validated)
    simple_write_jsonl(parquet_path.with_suffix(".jsonl"), validated)


def _file_hash(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    digest = hashlib.sha256()
    digest.update(data)
    return digest.hexdigest()


def _load_function_caches(analytics_dir: Path) -> FunctionCachingState:
    """Load cached function analytics keyed by rel_path plus prior hashes.

    Returns
    -------
    FunctionCachingState
        Loaded metrics/types caches and prior hash mapping (may be empty).
    """

    def _load_jsonl(path: Path) -> dict[str, list[dict[str, Any]]]:
        mapping: dict[str, list[dict[str, Any]]] = {}
        if not path.exists():
            return mapping
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            rel_path = payload.get("rel_path")
            if isinstance(rel_path, str):
                mapping.setdefault(rel_path, []).append(payload)
        return mapping

    metrics_cache = _load_jsonl(analytics_dir / "function_metrics.jsonl")
    types_cache = _load_jsonl(analytics_dir / "function_types.jsonl")
    hashes_path = analytics_dir / "function_hashes.json"
    try:
        prior_hashes_raw = json.loads(hashes_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        prior_hashes_raw = {}
    prior_hashes = prior_hashes_raw if isinstance(prior_hashes_raw, dict) else {}
    return FunctionCachingState(
        metrics_cache=metrics_cache,
        types_cache=types_cache,
        prior_hashes=cast("dict[str, str]", prior_hashes),
    )


def write_exports_outputs(result: PipelineResult, out: Path) -> None:
    """Write modules.jsonl, markdown sheets, repo map, and tag index.

    Parameters
    ----------
    result : PipelineResult
        Pipeline result containing module rows and tag index to export.
    out : Path
        Output directory where export files will be written.
    """
    with _stage(StageMeta("write-exports", {"modules": len(result.module_rows)})) as meta:
        write_modules_json(out, result.module_rows)
        write_markdown_modules(out, result.module_rows)
        write_repo_map(out, result)
        TagIndexModel.model_validate(result.tag_index)
        write_tag_index(out, result.tag_index)
        meta["tag_groups"] = len(result.tag_index)


def write_graph_outputs(result: PipelineResult, out: Path) -> None:
    """Write symbol/import graphs.

    Parameters
    ----------
    result : PipelineResult
        Pipeline result containing symbol edges and import graph to export.
    out : Path
        Output directory where graph files will be written.
    """
    module_lookup = _module_by_path(result.module_rows)
    with _stage(StageMeta("write-graphs", {"symbols": len(result.symbol_edges)})) as meta:
        graphs_dir = out / "graphs"
        graphs_dir.mkdir(parents=True, exist_ok=True)
        write_symbol_graph(out, result.symbol_edges)
        import_path = graphs_dir / "import_graph_edges.parquet"
        import_jsonl = graphs_dir / "import_graph_edges.jsonl"
        used_import = write_import_graph(
            result.import_graph,
            import_path,
            jsonl_fallback=import_jsonl,
            module_by_path=module_lookup,
        )
        meta["imports"] = sum(len(edges) for edges in result.import_graph.edges.values())
        legacy_import = graphs_dir / "imports.parquet"
        _mirror_artifact(used_import, legacy_import)
        _mirror_artifact(import_jsonl, graphs_dir / "imports.jsonl")


def write_uses_output(result: PipelineResult, out: Path) -> None:
    """Write uses graph parquet.

    Parameters
    ----------
    result : PipelineResult
        Pipeline result containing use graph to export.
    out : Path
        Output directory where use graph files will be written.
    """
    with _stage(StageMeta("write-uses", {"files": len(result.use_graph.uses_by_file)})) as meta:
        graphs_dir = out / "graphs"
        graphs_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = graphs_dir / "symbol_use_edges.jsonl"
        used_path = write_use_graph(
            result.use_graph,
            graphs_dir / "symbol_use_edges.parquet",
            jsonl_fallback=jsonl_path,
            module_by_path=_module_by_path(result.module_rows),
        )
        _mirror_artifact(used_path, graphs_dir / "uses.parquet")
        _mirror_artifact(jsonl_path, graphs_dir / "uses.jsonl")
        meta["edges"] = sum(len(paths) for paths in result.use_graph.uses_by_file.values())


def apply_ownership(
    result: PipelineResult,
    out: Path,
    *,
    history_window_days: int,
    commits_window: int,
) -> OwnershipIndex:
    """Compute ownership analytics and attach to module rows.

    Parameters
    ----------
    result : PipelineResult
        Pipeline result containing module rows and repository root.
    out : Path
        Output directory where ownership analytics will be written.
    history_window_days : int
        Number of days to look back for ownership history. Used to compute
        churn windows.
    commits_window : int
        Number of recent commits to analyze for ownership. Must be at least 1.

    Returns
    -------
    OwnershipIndex
        Ownership records keyed by repo path, including owner, primary authors,
        bus factor, and churn metrics.
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
    """Persist ownership analytics.

    Parameters
    ----------
    ownership : OwnershipIndex
        Ownership index containing ownership records to persist.
    out : Path
        Output directory where ownership analytics parquet file will be written.
    """
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
    """Emit tag slices when enabled.

    Parameters
    ----------
    module_rows : Sequence[Mapping[str, Any]]
        Sequence of module record dictionaries to process for slice generation.
    out : Path
        Output directory where slice files will be written.
    slices_filter : list[str] | None, optional
        Optional list of tag names to filter slices. If provided, only modules
        with at least one matching tag are included. If None, all modules are
        included. Defaults to None.
    """
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
    """Write typedness analytics datasets and static diagnostics.

    Parameters
    ----------
    result : PipelineResult
        Pipeline result containing module rows with type error and annotation data.
    out : Path
        Output directory where typedness analytics parquet file will be written.
    """
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
    write_static_diagnostics_output(result, out)


def _collect_function_rows(
    result: PipelineResult,
    *,
    include_metrics: bool,
    include_types: bool,
    caches: FunctionCachingState,
) -> tuple[list[FunctionMetricsRow], list[FunctionTypesRow]]:
    """Collect function metrics/types rows, leveraging cached data when hashes match.

    Returns
    -------
    tuple[list[FunctionMetricsRow], list[FunctionTypesRow]]
        Aggregated metric and type rows for all modules.
    """
    repo = str(result.repo_root)
    commit = detect_commit(result.repo_root)
    created_at = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    snapshot = RepoSnapshot(repo=repo, commit=commit)
    metrics_rows: list[FunctionMetricsRow] = []
    types_rows: list[FunctionTypesRow] = []
    for row in result.module_rows:
        rel_path = row.get("path")
        if not isinstance(rel_path, str):
            continue
        if not row.get("parse_ok", True):
            continue
        file_path = (result.repo_root / rel_path).resolve()
        if _reuse_cached_rows(
            rel_path=rel_path,
            file_path=file_path,
            include_metrics=include_metrics,
            include_types=include_types,
            caches=caches,
            metrics_rows=metrics_rows,
            types_rows=types_rows,
        ):
            continue
        _compute_function_rows(
            rel_path=rel_path,
            file_path=file_path,
            snapshot=snapshot,
            repo=repo,
            commit=commit,
            created_at=created_at,
            include_metrics=include_metrics,
            include_types=include_types,
            caches=caches,
            metrics_rows=metrics_rows,
            types_rows=types_rows,
        )
    return metrics_rows, types_rows


def _reuse_cached_rows(
    *,
    rel_path: str,
    file_path: Path,
    include_metrics: bool,
    include_types: bool,
    caches: FunctionCachingState,
    metrics_rows: list[FunctionMetricsRow],
    types_rows: list[FunctionTypesRow],
) -> bool:
    file_hash = _file_hash(file_path)
    cache_hash = caches.prior_hashes.get(rel_path)
    if file_hash is None or cache_hash != file_hash:
        return False
    if include_metrics:
        metrics_rows.extend(cast("list[FunctionMetricsRow]", caches.metrics_cache.get(rel_path, [])))
    if include_types:
        types_rows.extend(cast("list[FunctionTypesRow]", caches.types_cache.get(rel_path, [])))
    caches.prior_hashes[rel_path] = file_hash
    return True


def _compute_function_rows(
    *,
    rel_path: str,
    file_path: Path,
    snapshot: RepoSnapshot,
    repo: str,
    commit: str,
    created_at: str,
    include_metrics: bool,
    include_types: bool,
    caches: FunctionCachingState,
    metrics_rows: list[FunctionMetricsRow],
    types_rows: list[FunctionTypesRow],
) -> None:
    file_hash = _file_hash(file_path)
    if not file_path.is_file():
        LOGGER.warning("Module path missing for function analytics: %s", rel_path)
        return
    try:
        code = file_path.read_text(encoding="utf-8", errors="ignore")
        module = cst.parse_module(code)
    except (OSError, cst.ParserSyntaxError) as exc:  # pragma: no cover - defensive
        LOGGER.warning("Failed to parse %s for function analytics: %s", rel_path, exc)
        return
    if include_metrics:
        metrics_rows.extend(
            build_function_metrics(
                snapshot=snapshot,
                rel_path=rel_path,
                module=module,
                code=code,
                created_at=created_at,
            )
        )
    if include_types:
        types_rows.extend(
            build_function_types(
                repo=repo,
                commit=commit,
                rel_path=rel_path,
                module=module,
                created_at=created_at,
            )
        )
    if file_hash:
        caches.prior_hashes[rel_path] = file_hash


def _write_function_outputs(
    result: PipelineResult,
    out: Path,
    *,
    emit_metrics: bool,
    emit_types: bool,
) -> tuple[int, int]:
    caches = _load_function_caches(out / "analytics")
    metrics_rows, types_rows = _collect_function_rows(
        result,
        include_metrics=emit_metrics,
        include_types=emit_types,
        caches=caches,
    )
    analytics_dir = out / "analytics"
    metrics_count = 0
    types_count = 0
    if emit_metrics:
        metrics_target = analytics_dir / "function_metrics.parquet"
        metrics_table = prepare_function_metrics_parquet(metrics_rows)
        metrics_validated = [
            FunctionMetricRowModel.model_validate(entry).model_dump() for entry in metrics_table
        ]
        write_parquet(metrics_target, metrics_validated)
        simple_write_jsonl(metrics_target.with_suffix(".jsonl"), metrics_validated)
        metrics_count = len(metrics_rows)
    if emit_types:
        types_target = analytics_dir / "function_types.parquet"
        types_table = prepare_function_types_parquet(types_rows)
        types_validated = [
            FunctionTypeRowModel.model_validate(entry).model_dump() for entry in types_table
        ]
        write_parquet(types_target, types_validated)
        simple_write_jsonl(types_target.with_suffix(".jsonl"), types_validated)
        types_count = len(types_rows)
    return metrics_count, types_count


def write_function_metrics_output(result: PipelineResult, out: Path) -> None:
    """Write per-function structural metrics."""
    with _stage(StageMeta("function-metrics", {"modules": len(result.module_rows)})) as meta:
        metrics_count, _ = _write_function_outputs(
            result,
            out,
            emit_metrics=True,
            emit_types=False,
        )
        meta["functions"] = metrics_count


def write_function_types_output(result: PipelineResult, out: Path) -> None:
    """Write per-function typedness analytics."""
    with _stage(StageMeta("function-types", {"modules": len(result.module_rows)})) as meta:
        _, types_count = _write_function_outputs(
            result,
            out,
            emit_metrics=False,
            emit_types=True,
        )
        meta["functions"] = types_count


def write_doc_output(result: PipelineResult, out: Path) -> None:
    """Write documentation health analytics.

    Parameters
    ----------
    result : PipelineResult
        Pipeline result containing module rows with documentation metadata.
    out : Path
        Output directory where documentation health analytics parquet file
        will be written.
    """
    rows = (
        DocHealthRowModel.model_validate(
            {
                "path": row.get("path"),
                "docstring": row.get("docstring"),
                "doc_has_summary": row.get("doc_has_summary"),
                "doc_param_parity": row.get("doc_param_parity"),
                "doc_examples_present": row.get("doc_examples_present"),
            }
        ).model_dump()
        for row in result.module_rows
    )
    _write_validated_tabular(out / "analytics" / "doc_health.parquet", rows, model=DocHealthRowModel)


def write_coverage_output(result: PipelineResult, out: Path) -> None:
    """Persist coverage summary.

    Parameters
    ----------
    result : PipelineResult
        Pipeline result containing coverage rows to persist.
    out : Path
        Output directory where coverage analytics parquet file will be written.
    """
    _write_validated_tabular(
        out / "analytics" / "coverage.parquet",
        result.coverage_rows,
        model=CoverageRowModel,
    )


def write_static_diagnostics_output(result: PipelineResult, out: Path) -> None:
    """Persist static diagnostics summary derived from type signals."""
    signals = getattr(result, "type_signals", None)
    if not isinstance(signals, Mapping):
        LOGGER.info("No static diagnostics to write")
        return
    analytics_dir = out / "analytics"
    analytics_dir.mkdir(parents=True, exist_ok=True)
    typed_signals = cast("Mapping[str, FileTypeSignals]", signals)
    rows = build_static_diagnostics_rows(typed_signals)
    parquet_path = analytics_dir / "static_diagnostics.parquet"
    jsonl_path = parquet_path.with_suffix(".jsonl")
    write_parquet_or_jsonl(
        parquet_path,
        jsonl_path,
        rows,
        schema=STATIC_DIAGNOSTICS_SCHEMA,
    )


def write_config_output(result: PipelineResult, out: Path) -> None:
    """Persist config index with references.

    Parameters
    ----------
    result : PipelineResult
        Pipeline result containing config index to persist.
    out : Path
        Output directory where config index JSON file will be written.
    """
    analytics_dir = out / "analytics"
    analytics_dir.mkdir(parents=True, exist_ok=True)
    config_rows = [
        ConfigRecordModel.model_validate(row).model_dump() for row in result.config_index
    ]
    write_json(analytics_dir / "config_index.json", config_rows)
    if not config_rows:
        return
    state = prepare_config_state(config_rows)
    rows = build_config_value_rows(state, result.module_rows)
    analytics_path = analytics_dir / "config_values.parquet"
    write_parquet(analytics_path, rows)
    simple_write_jsonl(analytics_path.with_suffix(".jsonl"), rows)


def write_hotspot_output(result: PipelineResult, out: Path) -> None:
    """Persist hotspot analytics.

    Parameters
    ----------
    result : PipelineResult
        Pipeline result containing hotspot rows to persist.
    out : Path
        Output directory where hotspot analytics parquet file will be written.
    """
    _write_validated_tabular(
        out / "analytics" / "hotspots.parquet",
        result.hotspot_rows,
        model=HotspotRowModel,
    )


def write_ast_outputs(result: PipelineResult, out: Path, *, emit_ast: bool) -> None:
    """Write AST nodes + metrics if enabled.

    Parameters
    ----------
    result : PipelineResult
        Pipeline result containing module rows and repository root for AST
        artifact collection.
    out : Path
        Output directory where AST JSONL files will be written.
    emit_ast : bool
        Whether to emit AST artifacts. If False, function returns immediately
        without writing any files.
    """
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
    """Write repo_map.json summary.

    Parameters
    ----------
    out : Path
        Output directory where repo_map.json will be written.
    result : PipelineResult
        Pipeline result containing repository metadata, module counts, and
        tag index to summarize.
    """
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


def record_to_json(record: ModuleRecord) -> Mapping[str, Any]:
    """Convert a service-level ModuleRecord to a JSON-compatible mapping.

    Parameters
    ----------
    record : ModuleRecord
        Module record to convert to JSON-compatible format.

    Returns
    -------
    Mapping[str, Any]
        JSON-serializable representation of the record containing path, module,
        language, loc, tags, and meta fields.
    """
    path = str(record.get("path", ""))
    meta = record.get("meta") or {}
    complexity = record.get("complexity") or {}
    return {
        "path": path,
        "module": record.get("module_name") or record.get("module") or path,
        "language": meta.get("language", "python"),
        "loc": int(record.get("loc", complexity.get("loc", 0))),
        "tags": list(record.get("tags") or []),
        "meta": dict(meta),
    }


def emit_modules_jsonl(ctx: PipelineContext, records: Iterable[ModuleRecord]) -> Path:
    """Write modules.jsonl for the refactored CLI.

    Parameters
    ----------
    ctx : PipelineContext
        Pipeline context containing output directory path.
    records : Iterable[ModuleRecord]
        Iterable of module records to write to JSONL format.

    Returns
    -------
    Path
        Path to the generated modules.jsonl file.
    """
    target = ctx.paths.data_dir / "modules" / "modules.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    count = simple_write_jsonl(target, (record_to_json(r) for r in records))
    ctx.logger.info("Wrote %d module rows to %s", count, target)
    alias = ctx.paths.data_dir / "modules.jsonl"
    if not alias.exists():
        try:
            alias.link_to(target)
        except OSError:
            alias.write_bytes(target.read_bytes())
    return target


def emit_repo_map(ctx: PipelineContext, records: Iterable[ModuleRecord]) -> Path:
    """Emit a lightweight repo_map.json file.

    Parameters
    ----------
    ctx : PipelineContext
        Pipeline context containing repository paths and output directory.
    records : Iterable[ModuleRecord]
        Iterable of module records used to compute summary statistics.

    Returns
    -------
    Path
        Path to the generated repo_map.json file.
    """
    by_pkg: dict[str, list[str]] = {}
    for record in records:
        view = as_record_view(record)
        pkg = view.module.split(".")[0] if "." in view.module else view.module
        by_pkg.setdefault(pkg, []).append(view.module)
    target = ctx.paths.data_dir / "repo_map.json"
    atomic_write_text(target, json.dumps(by_pkg, indent=2))
    ctx.logger.info("Wrote repo map to %s", target)
    return target


def emit_tag_index(ctx: PipelineContext, records: Iterable[ModuleRecord]) -> Path:
    """Emit a tag->count mapping for module tags.

    Parameters
    ----------
    ctx : PipelineContext
        Pipeline context containing output directory path.
    records : Iterable[ModuleRecord]
        Iterable of module records containing tags to index.

    Returns
    -------
    Path
        Path to the generated tag index file.
    """
    tag_counts: dict[str, int] = {}
    for record in records:
        view = as_record_view(record)
        for tag in view.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    target = ctx.paths.data_dir / "tag_index.json"
    atomic_write_text(target, json.dumps(tag_counts, indent=2))
    ctx.logger.info("Wrote tag index to %s", target)
    return target


def emit_markdown_sheets(ctx: PipelineContext, records: Iterable[ModuleRecord]) -> Path:
    """Emit Markdown sheets summarizing each module.

    Parameters
    ----------
    ctx : PipelineContext
        Pipeline context containing output directory path.
    records : Iterable[ModuleRecord]
        Iterable of module records to write as Markdown files.

    Returns
    -------
    Path
        Directory containing the generated sheets.
    """
    md_dir = ctx.paths.data_dir / "sheets"
    md_dir.mkdir(parents=True, exist_ok=True)
    views: list[ModuleRecordView] = [as_record_view(record) for record in records]

    def _write_sheet(view: ModuleRecordView) -> None:
        slug = view.module.replace(".", "-")
        body = (
            f"# {view.module}\n\n"
            f"- Path: `{view.path}`\n"
            f"- LOC: {view.loc}\n"
            f"- Tags: {', '.join(view.tags) or '—'}\n"
        )
        atomic_write_text(md_dir / f"{slug}.md", body)

    max_workers = min(8, max(1, len(views)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(_write_sheet, views))
    ctx.logger.info("Wrote markdown sheets to %s", md_dir)
    return md_dir


def write_exports_manifest(
    ctx: PipelineContext,
    *,
    result: ExportResult,
    record_count: int,
) -> Path:
    """Emit a manifest describing export outputs and counts.

    Returns
    -------
    Path
        Path to the manifest JSON file.
    """
    manifest: dict[str, object] = {
        "modules_jsonl": str(result.modules_jsonl),
        "modules_alias": str((ctx.paths.data_dir / "modules.jsonl").resolve()),
        "repo_map": str(result.repo_map),
        "tag_index": str(result.tag_index),
        "markdown_dir": str(result.markdown_dir),
        "module_count": record_count,
    }
    analytics_dir = ctx.paths.data_dir / "analytics"
    graphs_dir = ctx.paths.data_dir / "graphs"
    ast_dir = ctx.paths.data_dir / "ast"
    goid_dir = ctx.paths.data_dir / "goid"
    analytics_block = _existing_paths(
        [
            analytics_dir / "coverage.parquet",
            analytics_dir / "hotspots.parquet",
            analytics_dir / "doc_health.parquet",
            analytics_dir / "function_metrics.parquet",
            analytics_dir / "function_types.parquet",
            analytics_dir / "typedness.parquet",
            analytics_dir / "static_diagnostics.parquet",
            analytics_dir / "config_index.json",
            analytics_dir / "config_values.parquet",
            analytics_dir / "ownership.parquet",
        ]
    )
    graphs_block = _existing_paths(
        [
            graphs_dir / "import_graph_edges.parquet",
            graphs_dir / "symbol_use_edges.parquet",
            graphs_dir / "call_edges.parquet",
            graphs_dir / "cfg_edges.parquet",
            graphs_dir / "dfg_edges.parquet",
        ]
    )
    goid_block = _existing_paths(
        [
            goid_dir / "goids.parquet",
            goid_dir / "goid_xwalk.parquet",
        ]
    )
    ast_block = _existing_paths(
        [
            ast_dir / "ast_nodes.jsonl",
            ast_dir / "ast_metrics.jsonl",
            ast_dir / "ast_nodes.parquet",
            ast_dir / "ast_metrics.parquet",
        ]
    )
    if analytics_block:
        manifest["analytics"] = analytics_block
    if graphs_block:
        manifest["graphs"] = graphs_block
    if goid_block:
        manifest["goid"] = goid_block
    if ast_block:
        manifest["ast"] = ast_block
    target = ctx.paths.data_dir / "exports_manifest.json"
    write_json(target, manifest)
    return target


def run_all_exports(ctx: PipelineContext, records: list[ModuleRecord]) -> ExportResult:
    """Emit all enrich artifacts for the simplified CLI.

    Parameters
    ----------
    ctx : PipelineContext
        Pipeline context containing output directory and configuration.
    records : list[ModuleRecord]
        List of module records to export in various formats.

    Returns
    -------
    ExportResult
        Dataclass pointing to the emitted artifacts including modules.jsonl,
        repo_map.json, tag_index.json, and markdown sheets directory.
    """
    modules_jsonl = emit_modules_jsonl(ctx, records)
    repo_map = emit_repo_map(ctx, records)
    tag_index = emit_tag_index(ctx, records)
    markdown_dir = emit_markdown_sheets(ctx, records)
    export_result = ExportResult(
        modules_jsonl=modules_jsonl,
        repo_map=repo_map,
        tag_index=tag_index,
        markdown_dir=markdown_dir,
    )
    write_exports_manifest(ctx, result=export_result, record_count=len(records))
    return export_result


__all__ = [
    "apply_ownership",
    "emit_markdown_sheets",
    "emit_modules_jsonl",
    "emit_repo_map",
    "emit_tag_index",
    "record_to_json",
    "run_all_exports",
    "write_ast_outputs",
    "write_config_output",
    "write_coverage_output",
    "write_doc_output",
    "write_exports_manifest",
    "write_exports_outputs",
    "write_function_metrics_output",
    "write_function_types_output",
    "write_graph_outputs",
    "write_hotspot_output",
    "write_ownership_output",
    "write_repo_map",
    "write_slices_output",
    "write_static_diagnostics_output",
    "write_typedness_output",
    "write_uses_output",
]
