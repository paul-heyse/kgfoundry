# SPDX-License-Identifier: MIT
"""Scanning and pipeline preparation services."""

from __future__ import annotations

import ast
import logging
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import typer

from codeintel_rev.app.readiness import raise_on_errors, validate_paths
from codeintel_rev.config_indexer import index_config_files
from codeintel_rev.coverage_ingest import collect_coverage
from codeintel_rev.enrich.errors import TaggingError, TypeSignalError
from codeintel_rev.enrich.models import ModuleRecord
from codeintel_rev.enrich.pathnorm import detect_repo_root
from codeintel_rev.enrich.pipeline_helpers import build_module_row, normalized_rel_path
from codeintel_rev.enrich.scip_reader import SCIPIndex
from codeintel_rev.enrich.tagging import load_rules
from codeintel_rev.enrich.validators import ModuleRecordModel
from codeintel_rev.config.paths import ResolvedPaths, resolve_application_paths
from codeintel_rev.services.enrich.analytics import compute_pipeline_analytics
from codeintel_rev.services.enrich.context import (
    LegacyPipelineContext,
    PipelineContext,
    PipelineOptions,
    PipelineResult,
    PreparedPipeline,
    ScanInputs,
    ScipContext,
    StageMeta,
    _stage,
)
from codeintel_rev.services.enrich.graph_steps import (
    build_callgraph_artifacts,
    build_cfg_artifacts,
    build_goid_artifacts,
)
from codeintel_rev.services.enrich.models import ModuleRecord as SimpleModuleRecord
from codeintel_rev.services.enrich.python_files import (
    EXCLUDED_SCAN_SEGMENTS,
    iter_python_files,
    should_skip_candidate,
)
from codeintel_rev.typedness import FileTypeSignals, collect_type_signals

LOGGER = logging.getLogger(__name__)


def discover_python_files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    """Return ordered Python files under ``root`` honoring include patterns."""
    normalized_patterns = tuple(patterns or ())
    files = iter_python_files(root, normalized_patterns or None)
    return sorted(files)


def load_scip_artifacts(path: Path) -> tuple[SCIPIndex, ScipContext]:
    """Load SCIP index and derive helper context.

    Parameters
    ----------
    path : Path
        Path to the SCIP index file to load.

    Returns
    -------
    tuple[SCIPIndex, ScipContext]
        Materialized SCIP index and lookup context.
    """
    with _stage(StageMeta("scip", {"path": path})) as meta:
        scip_index = SCIPIndex.load(path)
        scip_ctx = ScipContext(index=scip_index, by_file=scip_index.by_file())
        meta["documents"] = len(scip_ctx.by_file)
    return scip_index, scip_ctx


def collect_type_signal_map(
    root: Path, *, pyrefly_json: Path | None
) -> Mapping[str, FileTypeSignals]:
    """Collect Pyrefly/Pyright summaries and normalize path keys.

    Parameters
    ----------
    root : Path
        Repository root directory. Used for path normalization and as the
        base path for Pyright JSON report discovery.
    pyrefly_json : Path | None, optional
        Optional path to Pyrefly JSON report file. If None, only Pyright
        reports are collected.

    Returns
    -------
    Mapping[str, FileTypeSignals]
        Normalized type signal metrics by repo-relative path.

    Raises
    ------
    TypeSignalError
        Raised when either report fails to parse.
    """
    with _stage(StageMeta("type-signals", {"root": root})) as meta:
        try:
            signals = collect_type_signals(
                pyrefly_report=str(pyrefly_json) if pyrefly_json else None,
                pyright_json=str(root),
            )
        except Exception as exc:  # pragma: no cover - defensive
            reason = "collect"
            raise TypeSignalError(reason, path=str(root), detail=str(exc)) from exc
        normalized = _normalize_type_signal_map(signals, root)
        meta["files"] = len(normalized)
        return normalized


def collect_coverage_map(
    root: Path, coverage_xml: Path | None
) -> Mapping[str, Mapping[str, float]]:
    """Collect coverage metrics keyed by normalized path.

    Parameters
    ----------
    root : Path
        Repository root directory used for path normalization.
    coverage_xml : Path | None, optional
        Optional path to coverage XML report file. If None or the file
        doesn't exist, returns an empty mapping.

    Returns
    -------
    Mapping[str, Mapping[str, float]]
        Coverage statistics keyed by repo-relative path.
    """
    source = str(coverage_xml) if coverage_xml else "none"
    with _stage(StageMeta("coverage", {"source": source})) as meta:
        raw_metrics = (
            collect_coverage(coverage_xml) if coverage_xml and coverage_xml.exists() else {}
        )
        normalized = _normalize_metric_map(raw_metrics, root)
        meta["files"] = len(normalized)
        return normalized


def index_config_records(root: Path) -> list[dict[str, Any]]:
    """Return discovered config records under ``root``.

    Parameters
    ----------
    root : Path
        Repository root directory to scan for configuration files.

    Returns
    -------
    list[dict[str, Any]]
        Config metadata rows discovered by the indexer.
    """
    with _stage(StageMeta("config-index", {"root": root})) as meta:
        records = index_config_files(root)
        meta["records"] = len(records)
        return records


def load_tagging_rules(path: Path | None) -> Mapping[str, Any]:
    """Load YAML tagging rules or fall back to defaults.

    Parameters
    ----------
    path : Path | None, optional
        Optional path to custom YAML tagging rules file. If None, uses
        default tagging rules.

    Returns
    -------
    Mapping[str, Any]
        Parsed tagging rules keyed by tag.

    Raises
    ------
    TaggingError
        Raised when the custom rules file cannot be parsed.
    """
    source = str(path) if path else "defaults"
    with _stage(StageMeta("tagging-rules", {"source": source})) as meta:
        try:
            rules = load_rules(str(path) if path else None)
        except Exception as exc:  # pragma: no cover - defensive
            reason = "load-rules"
            raise TaggingError(reason, path=source, detail=str(exc)) from exc
        meta["rules"] = len(rules)
        return rules


def prepare_pipeline(pipeline: PipelineOptions) -> PreparedPipeline:
    """Materialize pipeline context (SCIP, type signals, tagging rules, etc.).

    Parameters
    ----------
    pipeline : PipelineOptions
        Pipeline configuration options including paths to SCIP index, type
        signal reports, coverage XML, tagging rules, and file inclusion patterns.

    Returns
    -------
    PreparedPipeline
        Fully realized pipeline context plus file list.

    Raises
    ------
    typer.BadParameter
        Raised when the required SCIP path is missing.
    """
    if pipeline.scip is None:
        message = "The --scip option is required for enrichment commands."
        raise typer.BadParameter(message)
    root_resolved = pipeline.root.resolve()
    repo_root = detect_repo_root(root_resolved)
    files = discover_python_files(root_resolved, pipeline.only or ())
    scip_index, scip_ctx = load_scip_artifacts(pipeline.scip)
    type_signal_lookup = collect_type_signal_map(
        root_resolved,
        pyrefly_json=pipeline.pyrefly_json,
    )
    coverage_lookup = collect_coverage_map(root_resolved, pipeline.coverage_xml)
    config_records = index_config_records(root_resolved)
    tagging_rules = load_tagging_rules(pipeline.tags_yaml)
    ctx = LegacyPipelineContext(
        root=root_resolved,
        repo_root=repo_root,
        scip_index=scip_index,
        scip_ctx=scip_ctx,
        type_signals=type_signal_lookup,
        coverage_map=coverage_lookup,
        config_records=config_records,
        tagging_rules=tagging_rules,
        package_prefix=root_resolved.name or None,
    )
    return PreparedPipeline(context=ctx, files=files)


def scan_modules(
    ctx: LegacyPipelineContext,
    pipeline: PipelineOptions,
    files: Sequence[Path],
) -> tuple[list[ModuleRecord], list[tuple[str, str]]]:
    """Scan python modules returning ModuleRecord rows and symbol edges.

    Parameters
    ----------
    ctx : LegacyPipelineContext
        Pipeline context containing SCIP index, type signals, coverage data,
        and tagging rules.
    pipeline : PipelineOptions
        Pipeline configuration including max file size limits and other options.
    files : Sequence[Path]
        Sequence of Python file paths to scan and process.

    Returns
    -------
    tuple[list[ModuleRecord], list[tuple[str, str]]]
        Materialized module rows and symbol edge tuples.
    """
    scan_inputs = ScanInputs(
        scip_ctx=ctx.scip_ctx,
        type_signals=ctx.type_signals,
        coverage_map=ctx.coverage_map,
        tagging_rules=ctx.tagging_rules,
        repo_root=ctx.repo_root,
        max_file_bytes=pipeline.max_file_bytes,
        package_prefix=ctx.package_prefix,
    )
    module_rows: list[ModuleRecord] = []
    symbol_edges: list[tuple[str, str]] = []
    with _stage(StageMeta("index", {"files": len(files)})) as meta:
        for fp in files:
            row_dict, edges = build_module_row(fp, ctx.root, scan_inputs)
            ModuleRecordModel.model_validate(row_dict)
            if not row_dict.get("meta"):
                LOGGER.warning(
                    "Module record missing meta payload", extra={"path": row_dict.get("path")}
                )
            module_rows.append(row_dict)
            symbol_edges.extend(edges)
        meta["modules"] = len(module_rows)
    return module_rows, symbol_edges


def run_pipeline(*, pipeline: PipelineOptions) -> PipelineResult:
    """Execute the enrichment pipeline and return an aggregate result bundle.

    Parameters
    ----------
    pipeline : PipelineOptions
        Pipeline configuration options specifying input paths, output settings,
        and processing options.

    Returns
    -------
    PipelineResult
        Enrichment output artifacts and analytics including module rows,
        symbol edges, import graphs, coverage data, and hotspot analysis.
    """
    prepared = prepare_pipeline(pipeline)
    ctx = prepared.context
    module_rows, symbol_edges = scan_modules(ctx, pipeline, prepared.files)
    analytics = compute_pipeline_analytics(ctx, module_rows)
    _run_requested_graph_steps(ctx, pipeline)
    return PipelineResult(
        root=ctx.root,
        repo_root=ctx.repo_root,
        module_rows=module_rows,
        symbol_edges=symbol_edges,
        import_graph=analytics.import_graph,
        use_graph=analytics.use_graph,
        config_index=analytics.config_index,
        coverage_rows=analytics.coverage_rows,
        hotspot_rows=analytics.hotspot_rows,
        tag_index=analytics.tag_index,
    )


def _run_requested_graph_steps(ctx: LegacyPipelineContext, pipeline: PipelineOptions) -> None:
    """Execute GOID/callgraph/CFG/DFG steps when requested via pipeline options."""
    if not (
        pipeline.build_goids or pipeline.build_callgraph or pipeline.build_cfg or pipeline.build_dfg
    ):
        return
    pipeline_ctx, resolved_paths = _build_graph_context(ctx.repo_root, pipeline.out)
    try:
        if pipeline.build_goids:
            build_goid_artifacts(pipeline_ctx, out_dir=resolved_paths.data_dir, ingest=True)
        if pipeline.build_callgraph:
            build_callgraph_artifacts(pipeline_ctx, out_dir=resolved_paths.data_dir, ingest=True)
        if pipeline.build_cfg or pipeline.build_dfg:
            build_cfg_artifacts(
                pipeline_ctx,
                out_dir=resolved_paths.data_dir,
                ingest_cfg=pipeline.build_cfg,
                ingest_dfg=pipeline.build_dfg,
            )
    finally:
        pipeline_ctx.close()


def _build_graph_context(repo_root: Path, out_dir: Path) -> tuple[PipelineContext, ResolvedPaths]:
    mapping = {"BASE_DIR": repo_root, "DATA_DIR": out_dir}
    paths = resolve_application_paths(mapping)
    raise_on_errors(validate_paths(paths))
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    ctx = PipelineContext.from_paths(paths)
    return ctx, paths


def _iter_source_files(
    root: Path, include_globs: tuple[str, ...], exclude_globs: tuple[str, ...]
) -> Iterator[Path]:
    """Yield Python files honoring include/exclude globs.

    Parameters
    ----------
    root : Path
        Repository root directory to search for Python files.
    include_globs : tuple[str, ...]
        Glob patterns for files to include. If empty, all Python files are included.
    exclude_globs : tuple[str, ...]
        Glob patterns for files to exclude. Files matching any pattern are skipped.

    Yields
    ------
    Path
        Matched Python file path that passes both include and exclude filters.
    """
    for file_path in root.rglob("*.py"):
        rel = file_path.relative_to(root)
        if include_globs and not any(rel.match(pattern) for pattern in include_globs):
            continue
        if exclude_globs and any(rel.match(pattern) for pattern in exclude_globs):
            continue
        yield file_path


def _py_module_name(repo_root: Path, file_path: Path) -> str:
    """Compute Python module name from file path.

    Parameters
    ----------
    repo_root : Path
        Repository root directory.
    file_path : Path
        Python file path.

    Returns
    -------
    str
        Dotted module name (e.g., "package.module").
    """
    try:
        rel = file_path.relative_to(repo_root)
    except ValueError:
        rel = file_path
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _loc(text: str) -> int:
    """Return the number of lines of code in ``text``.

    Parameters
    ----------
    text : str
        Source code text to count lines in.

    Returns
    -------
    int
        Number of lines in the text (excluding empty lines if splitlines
        filters them, but typically includes all lines).
    """
    return sum(1 for _ in text.splitlines())


def scan_repo(
    ctx: PipelineContext,
    *,
    include: tuple[str, ...] = (),
    exclude: tuple[str, ...] = ("**/.venv/**", "**/build/**", "**/dist/**"),
    infer_tags: bool = True,
) -> list[SimpleModuleRecord]:
    """Scan the repository and return lightweight module records.

    Parameters
    ----------
    ctx : PipelineContext
        Pipeline context containing repository paths and logger.
    include : tuple[str, ...], optional
        Glob patterns for files to include. If empty, all Python files are
        included (subject to exclude patterns). Defaults to empty tuple.
    exclude : tuple[str, ...], optional
        Glob patterns for files to exclude. Files matching any pattern are
        skipped. Defaults to common build/dist/venv exclusion patterns.
    infer_tags : bool, optional
        Whether to automatically infer tags based on file path (e.g., "cli",
        "test"). Defaults to True.

    Returns
    -------
    list[SimpleModuleRecord]
        Sorted list of module records discovered under ``repo_root``.
    """
    ctx.logger.info("Scanning repo at %s", ctx.paths.repo_root)
    records: list[SimpleModuleRecord] = []
    for file_path in _iter_source_files(ctx.paths.repo_root, include, exclude):
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        try:
            ast.parse(text)
        except SyntaxError:
            ctx.logger.warning("Skipping parse failure: %s", file_path)
            continue
        tags: set[str] = set()
        if infer_tags:
            if "cli" in file_path.parts:
                tags.add("cli")
            if "tests" in file_path.parts:
                tags.add("test")
        records.append(
            SimpleModuleRecord(
                path=file_path.relative_to(ctx.paths.repo_root),
                module=_py_module_name(ctx.paths.repo_root, file_path),
                language="python",
                loc=_loc(text),
                tags=tuple(sorted(tags)),
                meta={"mtime": file_path.stat().st_mtime},
            )
        )
    ctx.logger.info("Scan complete: %d modules", len(records))
    return records


def _normalize_type_signal_map(
    signals: Mapping[str, FileTypeSignals],
    root: Path,
) -> dict[str, FileTypeSignals]:
    """Normalize type-signal keys relative to ``root``.

    Parameters
    ----------
    signals : Mapping[str, FileTypeSignals]
        Raw type signal mapping with potentially absolute or relative paths.
    root : Path
        Repository root directory used for path normalization.

    Returns
    -------
    dict[str, FileTypeSignals]
        Normalized mapping keyed by repo-relative path.
    """
    normalized: dict[str, FileTypeSignals] = {}
    for path, counts in signals.items():
        normalized_path = _normalize_path_key(path, root)
        normalized[normalized_path] = counts
    return normalized


def _normalize_metric_map(
    metrics: Mapping[str, Mapping[str, float]],
    root: Path,
) -> dict[str, Mapping[str, float]]:
    """Normalize coverage metric keys relative to ``root``.

    Parameters
    ----------
    metrics : Mapping[str, Mapping[str, float]]
        Raw coverage metrics mapping with potentially absolute or relative paths.
    root : Path
        Repository root directory used for path normalization.

    Returns
    -------
    dict[str, Mapping[str, float]]
        Metric mapping keyed by repo-relative path.
    """
    normalized: dict[str, Mapping[str, float]] = {}
    for path, values in metrics.items():
        normalized_path = _normalize_path_key(path, root)
        normalized[normalized_path] = dict(values)
    return normalized


def _normalize_path_key(path: str, root: Path) -> str:
    """Normalize ``path`` relative to ``root`` when possible.

    Parameters
    ----------
    path : str
        File path string to normalize. Can be absolute or relative.
    root : Path
        Repository root directory used for relative path computation.

    Returns
    -------
    str
        Normalized string representation. If path is absolute and can be
        made relative to root, returns the relative path. Otherwise returns
        the original path string.
    """
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return str(candidate.relative_to(root))
        except ValueError:
            return path
    return path


__all__ = [
    "collect_coverage_map",
    "collect_type_signal_map",
    "discover_python_files",
    "index_config_records",
    "load_scip_artifacts",
    "load_tagging_rules",
    "prepare_pipeline",
    "run_pipeline",
    "scan_modules",
]
