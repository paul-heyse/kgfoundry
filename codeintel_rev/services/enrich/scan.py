# SPDX-License-Identifier: MIT
"""Scanning and pipeline preparation services."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator, Mapping, Sequence
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import typer

from codeintel_rev.config_indexer import index_config_files
from codeintel_rev.coverage_ingest import collect_coverage
from codeintel_rev.enrich.errors import TaggingError, TypeSignalError
from codeintel_rev.enrich.models import ModuleRecord
from codeintel_rev.enrich.pathnorm import detect_repo_root
from codeintel_rev.enrich.pipeline_helpers import build_module_row, normalized_rel_path
from codeintel_rev.enrich.scip_reader import SCIPIndex
from codeintel_rev.enrich.tagging import load_rules
from codeintel_rev.enrich.validators import ModuleRecordModel
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
from codeintel_rev.services.enrich.models import ModuleRecord as SimpleModuleRecord
from codeintel_rev.typedness import FileTypeSignals, collect_type_signals

_EXCLUDED_SCAN_SEGMENTS = {"stubs", "overlays"}


def discover_python_files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    """Return ordered Python files under ``root`` honoring include patterns.

    Parameters
    ----------
    root :
        Repository root or subfolder to scan.
    patterns :
        Glob include patterns relative to ``root``.

    Returns
    -------
    list[Path]
        Deterministically ordered list of Python files.
    """
    normalized_patterns = tuple(patterns or ())
    candidates = [
        fp
        for fp in iter_python_files(root)
        if not normalized_patterns or _matches_any(fp, root, normalized_patterns)
    ]
    return sorted(candidates)


def _matches_any(candidate: Path, root: Path, patterns: tuple[str, ...]) -> bool:
    rel = normalized_rel_path(candidate, root)
    return any(fnmatch(rel, pattern) for pattern in patterns)


def iter_python_files(root: Path, patterns: tuple[str, ...] | None = None) -> Iterable[Path]:
    """Yield Python files under ``root`` optionally filtered by patterns.

    Parameters
    ----------
    root :
        Repository root to traverse.
    patterns :
        Optional glob include filters.

    Yields
    ------
    Path
        Individual Python file paths meeting the filter criteria.
    """
    normalized_patterns = tuple(patterns or ())
    for candidate in root.rglob("*.py"):
        if should_skip_candidate(candidate, root):
            continue
        if normalized_patterns and not _matches_any(candidate, root, normalized_patterns):
            continue
        yield candidate


def should_skip_candidate(candidate: Path, root: Path) -> bool:
    """Return whether the candidate should be skipped.

    Returns
    -------
    bool
        ``True`` when hidden folders or excluded segments are detected.
    """
    if any(part.startswith(".") for part in candidate.parts):
        return True
    try:
        rel_parts = candidate.relative_to(root).parts
    except ValueError:  # pragma: no cover - defensive
        rel_parts = candidate.parts
    lowered = {part.lower() for part in rel_parts}
    return bool(lowered & _EXCLUDED_SCAN_SEGMENTS)


def load_scip_artifacts(path: Path) -> tuple[SCIPIndex, ScipContext]:
    """Load SCIP index and derive helper context.

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
            module_rows.append(row_dict)
            symbol_edges.extend(edges)
        meta["modules"] = len(module_rows)
    return module_rows, symbol_edges


def run_pipeline(*, pipeline: PipelineOptions) -> PipelineResult:
    """Execute the enrichment pipeline and return an aggregate result bundle.

    Returns
    -------
    PipelineResult
        Enrichment output artifacts and analytics.
    """
    prepared = prepare_pipeline(pipeline)
    ctx = prepared.context
    module_rows, symbol_edges = scan_modules(ctx, pipeline, prepared.files)
    analytics = compute_pipeline_analytics(ctx, module_rows)
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


def _iter_source_files(
    root: Path, include_globs: tuple[str, ...], exclude_globs: tuple[str, ...]
) -> Iterator[Path]:
    """Yield Python files honoring include/exclude globs.

    Yields
    ------
    Path
        Matched Python file path.
    """
    for file_path in root.rglob("*.py"):
        rel = file_path.relative_to(root)
        if include_globs and not any(rel.match(pattern) for pattern in include_globs):
            continue
        if exclude_globs and any(rel.match(pattern) for pattern in exclude_globs):
            continue
        yield file_path


def _py_module_name(repo_root: Path, file_path: Path) -> str:
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

    Returns
    -------
    str
        Normalized string representation.
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
    "iter_python_files",
    "load_scip_artifacts",
    "load_tagging_rules",
    "prepare_pipeline",
    "run_pipeline",
    "scan_modules",
    "should_skip_candidate",
]
