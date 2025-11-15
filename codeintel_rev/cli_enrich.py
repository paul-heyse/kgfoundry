# SPDX-License-Identifier: MIT
"""CLI entrypoint for repo enrichment and targeted overlay generation."""

from __future__ import annotations

import ast
import json
import logging
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Annotated, Any, Protocol, cast

import typer

from codeintel_rev.config_indexer import index_config_files
from codeintel_rev.coverage_ingest import collect_coverage
from codeintel_rev.enrich.ast_indexer import (
    AstMetricsRow,
    AstNodeRow,
    collect_ast_nodes_from_tree,
    compute_ast_metrics,
    empty_metrics_row,
    stable_module_path,
    write_ast_parquet,
)
from codeintel_rev.enrich.duckdb_store import DuckConn, ingest_modules_jsonl
from codeintel_rev.enrich.errors import (
    IndexingError,
    IngestError,
    StageError,
    TaggingError,
    TypeSignalError,
)
from codeintel_rev.enrich.graph_builder import ImportGraph, build_import_graph, write_import_graph
from codeintel_rev.enrich.libcst_bridge import ModuleIndex, index_module
from codeintel_rev.enrich.models import ModuleRecord
from codeintel_rev.enrich.output_writers import (
    write_json,
    write_jsonl,
    write_markdown_module,
    write_parquet,
    write_parquet_dataset,
)
from codeintel_rev.enrich.ownership import OwnershipIndex, compute_ownership
from codeintel_rev.enrich.pathnorm import (
    detect_repo_root,
    module_name_from_path,
    stable_id_for_path,
)
from codeintel_rev.enrich.scip_reader import Document, SCIPIndex
from codeintel_rev.enrich.slices_builder import build_slice_record, write_slice
from codeintel_rev.enrich.stubs_overlay import (
    OverlayInputs,
    OverlayPolicy,
    activate_overlays,
    deactivate_all,
    generate_overlay_for_file,
)
from codeintel_rev.enrich.tagging import ModuleTraits, infer_tags, load_rules
from codeintel_rev.enrich.tree_sitter_bridge import build_outline
from codeintel_rev.enrich.validators import ModuleRecordModel
from codeintel_rev.export_resolver import build_module_name_map, resolve_exports
from codeintel_rev.risk_hotspots import compute_hotspot_score
from codeintel_rev.typedness import FileTypeSignals, collect_type_signals
from codeintel_rev.uses_builder import UseGraph, build_use_graph, write_use_graph

try:  # pragma: no cover - optional dependency
    import yaml as yaml_module
except ImportError:  # pragma: no cover - optional dependency
    yaml_module = None


def _yaml_errors() -> tuple[type[BaseException], ...]:
    """Return YAML loader exceptions supported in this environment.

    Returns
    -------
    tuple[type[BaseException], ...]
        Tuple of exception classes thrown by the configured YAML parser.
    """
    if yaml_module is not None:  # pragma: no cover - optional dependency
        return (yaml_module.YAMLError,)
    return (ValueError,)


YAML_ERRORS = _yaml_errors()


LOGGER = logging.getLogger(__name__)


def _format_stage_meta(metadata: Mapping[str, object]) -> str:
    parts = [f"{key}={metadata[key]}" for key in sorted(metadata)]
    return " ".join(parts)


@contextmanager
def _stage_span(stage: str, **start_meta: object) -> Iterator[dict[str, object]]:
    """Context manager logging structured stage timings.

    Parameters
    ----------
    stage : str
        Stage name used for logging identification. Appears in all log messages
        emitted by this context manager.
    **start_meta : object
        Additional metadata key-value pairs to include in the start event log.
        These are formatted and logged when the context manager enters.

    Yields
    ------
    dict[str, object]
        Mutable dictionary that can be populated with additional metadata prior
        to logging the ``event=finish`` line.

    Raises
    ------
    Exception
        Any exception raised within the context manager is logged and re-raised.
    """
    start = time.perf_counter()
    LOGGER.debug("stage=%s event=start %s", stage, _format_stage_meta(start_meta))
    outcome: dict[str, Any] = {}
    try:
        yield outcome
    except Exception:
        LOGGER.exception("stage=%s event=error %s", stage, _format_stage_meta(start_meta))
        raise
    finally:
        outcome.setdefault("duration_sec", round(time.perf_counter() - start, 3))
        LOGGER.info(
            "stage=%s event=finish %s",
            stage,
            _format_stage_meta({**start_meta, **outcome}),
        )


class _YamlDumpFn(Protocol):
    def __call__(self, data: Mapping[str, list[str]], *, sort_keys: bool = ...) -> str: ...


EXPORT_HUB_THRESHOLD = 10
OVERLAY_PARAM_THRESHOLD = 0.8
OVERLAY_FAN_IN_THRESHOLD = 3
OVERLAY_ERROR_THRESHOLD = 5

DEFAULT_MIN_ERRORS = 25
DEFAULT_MAX_OVERLAYS = 200
DEFAULT_INCLUDE_PUBLIC_DEFS = False
DEFAULT_INJECT_GETATTR_ANY = True
DEFAULT_DRY_RUN = False
DEFAULT_ACTIVATE = True
DEFAULT_DEACTIVATE = False
DEFAULT_USE_TYPE_ERROR_OVERLAYS = False
DEFAULT_EMIT_AST = True
DEFAULT_MAX_FILE_BYTES = 2_000_000
DEFAULT_OWNER_HISTORY_DAYS = 90
DEFAULT_COMMITS_WINDOW = 50
DEFAULT_ENABLE_OWNERS = True
DEFAULT_EMIT_SLICES_FLAG = False

_EMIT_AST_FLAG = "--emit-ast/--no-emit-ast"


@dataclass(slots=True, frozen=True)
class PipelineOptions:
    """Resolved paths and filters required for pipeline execution."""

    root: Path = Path()
    scip: Path | None = None
    out: Path = Path("codeintel_rev/io/ENRICHED")
    pyrefly_json: Path | None = None
    tags_yaml: Path | None = None
    coverage_xml: Path = Path("coverage.xml")
    only: tuple[str, ...] = ()
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES


@dataclass(slots=True, frozen=True)
class AnalyticsOptions:
    """Optional analytics toggles shared across commands."""

    owners: bool = DEFAULT_ENABLE_OWNERS
    history_window_days: int = DEFAULT_OWNER_HISTORY_DAYS
    commits_window: int = DEFAULT_COMMITS_WINDOW
    emit_slices: bool = DEFAULT_EMIT_SLICES_FLAG
    slices_filter: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class CLIContextState:
    """CLI-scoped state shared between commands."""

    pipeline: PipelineOptions = field(default_factory=PipelineOptions)
    analytics: AnalyticsOptions = field(default_factory=AnalyticsOptions)


ROOT_OPTION = typer.Option(
    Path().resolve(),
    "--root",
    help="Repo or subfolder to scan.",
    exists=True,
    file_okay=False,
    dir_okay=True,
    readable=True,
)
SCIP_OPTION = typer.Option(
    None,
    "--scip",
    help="Path to SCIP index.json",
    exists=True,
    dir_okay=False,
    readable=True,
)
OUT_OPTION = typer.Option(
    Path("codeintel_rev/io/ENRICHED"),
    "--out",
    help="Output directory for enrichment artifacts.",
    dir_okay=True,
)
PYREFLY_OPTION = typer.Option(
    None,
    "--pyrefly-json",
    help="Optional path to a Pyrefly JSON/JSONL report.",
    exists=True,
    dir_okay=False,
    readable=True,
)
TAGS_OPTION = typer.Option(
    None,
    "--tags-yaml",
    help="Optional tagging rules YAML.",
    exists=True,
    dir_okay=False,
    readable=True,
)
COVERAGE_OPTION = typer.Option(
    Path("coverage.xml"),
    "--coverage-xml",
    help="Optional path to coverage XML (Cobertura format).",
    dir_okay=False,
)
ONLY_OPTION = typer.Option(
    None,
    "--only",
    help="Glob patterns (repeatable) limiting modules relative to --root.",
)
MAX_FILE_BYTES_OPTION = typer.Option(
    DEFAULT_MAX_FILE_BYTES,
    "--max-file-bytes",
    help="Skip parsing files larger than this byte threshold.",
)
OWNERS_OPTION = typer.Option(
    DEFAULT_ENABLE_OWNERS,
    "--owners/--no-owners",
    help="Compute Git ownership analytics and enrich module rows.",
)
HISTORY_WINDOW_OPTION = typer.Option(
    DEFAULT_OWNER_HISTORY_DAYS,
    "--history-window-days",
    help="Length (in days) of the long-term churn window.",
)
COMMITS_WINDOW_OPTION = typer.Option(
    DEFAULT_COMMITS_WINDOW,
    "--commits-window",
    help="Maximum commits per file sampled when computing bus factor.",
)
EMIT_SLICES_OPTION = typer.Option(
    DEFAULT_EMIT_SLICES_FLAG,
    "--emit-slices/--no-emit-slices",
    help="Emit optional slice packs (JSON + Markdown) for selected modules.",
)
SLICES_FILTER_OPTION = typer.Option(
    None,
    "--slices-filter",
    help="Tag filters (repeatable) selecting modules when emitting slices.",
)
EMIT_AST_OPTION = typer.Option(
    DEFAULT_EMIT_AST,
    "--emit-ast/--no-emit-ast",
    help="Emit Parquet datasets with AST nodes and metrics.",
)
OVERLAYS_CONFIG_OPTION = typer.Option(
    None,
    "--overlays-config",
    help="Path to a YAML/JSON file describing overlay settings.",
)
OVERLAYS_SET_OPTION = typer.Option(
    None,
    "--set",
    "-s",
    help="Override overlay settings as KEY=VALUE entries (repeatable).",
)
DRY_RUN_OPTION = typer.Option(
    DEFAULT_DRY_RUN,
    "--dry-run",
    help="Run computations and log counts without writing artifacts.",
)


GLOBAL_OPTIONS_HELP = """Repo enrichment utilities (scan + overlays).

Global options (pass after the command, e.g. `codeintel-enrich all --root src --scip index.scip.json`):
  --root PATH           Repo or subfolder to scan.
  --scip PATH           Path to SCIP index.json (required for most commands).
  --out PATH            Output directory for enrichment artifacts.
  --pyrefly-json PATH   Optional Pyrefly report for typedness correlation.
  --tags-yaml PATH      Optional tagging rules YAML.
  --dry-run             Compute artifacts without writing to disk.
"""

app = typer.Typer(add_completion=True, help=GLOBAL_OPTIONS_HELP)


def _ensure_state(ctx: typer.Context) -> CLIContextState:
    state = ctx.obj
    if not isinstance(state, CLIContextState):
        state = CLIContextState()
        ctx.obj = state
    return state


def _capture_shared_state(
    ctx: typer.Context,
    *,
    root: Path,
    scip: Path | None,
    out: Path,
    pyrefly_json: Path | None,
    tags_yaml: Path | None,
    coverage_xml: Path,
    only: list[str] | None,
    max_file_bytes: int,
    owners: bool,
    history_window_days: int,
    commits_window: int,
    emit_slices: bool,
    slices_filter: list[str] | None,
) -> CLIContextState:
    """Persist shared pipeline + analytics options on the Typer context.

    Parameters
    ----------
    ctx : typer.Context
        Typer context object to store the shared state. The state is attached
        to ``ctx.obj`` for retrieval by downstream commands.
    root : Path
        Repository root directory path. Resolved to an absolute path before
        storing in pipeline options.
    scip : Path | None
        Optional path to SCIP index file. Resolved to absolute path if provided.
    out : Path
        Output directory path for generated artifacts. Resolved to absolute path.
    pyrefly_json : Path | None
        Optional path to Pyrefly JSON report. Resolved to absolute path if provided.
    tags_yaml : Path | None
        Optional path to tags YAML configuration file. Resolved to absolute path
        if provided.
    coverage_xml : Path
        Path to coverage XML report file. Resolved to absolute path.
    only : list[str] | None
        Optional list of file patterns to include. Converted to tuple for pipeline
        options. If None, all files are processed.
    max_file_bytes : int
        Maximum file size in bytes. Files exceeding this limit are skipped during
        processing.
    owners : bool
        Whether to include code ownership analytics in the pipeline.
    history_window_days : int
        Number of days to look back for git history analysis.
    commits_window : int
        Number of commits to analyze for git-based metrics.
    emit_slices : bool
        Whether to emit code slice analytics in the output.
    slices_filter : list[str] | None
        Optional list of slice filter patterns. Converted to tuple for analytics
        options. If None, all slices are included.

    Returns
    -------
    CLIContextState
        New context state object containing pipeline and analytics options. The
        state is also stored in ``ctx.obj`` for subsequent command invocations.
    """
    new_pipeline = PipelineOptions(
        root=root.resolve(),
        scip=scip.resolve() if scip else None,
        out=out.resolve(),
        pyrefly_json=pyrefly_json.resolve() if pyrefly_json else None,
        tags_yaml=tags_yaml.resolve() if tags_yaml else None,
        coverage_xml=coverage_xml.resolve(),
        only=tuple(only or ()),
        max_file_bytes=max_file_bytes,
    )
    new_analytics = AnalyticsOptions(
        owners=owners,
        history_window_days=history_window_days,
        commits_window=commits_window,
        emit_slices=emit_slices,
        slices_filter=tuple(slices_filter or ()),
    )
    state = CLIContextState(pipeline=new_pipeline, analytics=new_analytics)
    ctx.obj = state
    return state


@dataclass(slots=True, frozen=True)
class OverlayCLIOptions:
    """Mutable overlay generation options parsed from CLI/config."""

    stubs_root: Path = Path("stubs")
    overlays_root: Path = Path("stubs/overlays")
    min_errors: int = DEFAULT_MIN_ERRORS
    max_overlays: int = DEFAULT_MAX_OVERLAYS
    include_public_defs: bool = DEFAULT_INCLUDE_PUBLIC_DEFS
    inject_getattr_any: bool = DEFAULT_INJECT_GETATTR_ANY
    dry_run: bool = DEFAULT_DRY_RUN
    activate: bool = DEFAULT_ACTIVATE
    deactivate_all_first: bool = DEFAULT_DEACTIVATE
    type_error_overlays: bool = DEFAULT_USE_TYPE_ERROR_OVERLAYS


@dataclass(slots=True, frozen=True)
class OverlayContext:
    """Aggregated context used during overlay generation."""

    root: Path
    package_name: str
    overlays_root: Path
    stubs_root: Path
    scip_index: SCIPIndex
    type_counts: Mapping[str, int]
    policy: OverlayPolicy
    inputs: OverlayInputs


def _load_overlay_options(config_path: Path | None, overrides: list[str]) -> OverlayCLIOptions:
    options = OverlayCLIOptions()
    if config_path is not None:
        config_data = _read_overlay_config(config_path)
        for key, value in config_data.items():
            _set_overlay_option(options, key, value)
    for override in overrides:
        if "=" not in override:
            message = "Override values must use the KEY=VALUE format."
            raise typer.BadParameter(message)
        key, value = override.split("=", 1)
        _set_overlay_option(options, key, value)
    return options


def _read_overlay_config(path: Path) -> Mapping[str, Any]:
    payload = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        if yaml_module is None:
            message = "PyYAML is required to parse YAML overlay configs."
            raise typer.BadParameter(message)
        data = yaml_module.safe_load(payload)
    else:
        data = json.loads(payload)
    if not isinstance(data, Mapping):
        message = "Overlay config must be a mapping of option names to values."
        raise typer.BadParameter(message)
    return data


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    message = f"Cannot interpret '{value}' as a boolean."
    raise typer.BadParameter(message)


def _resolve_path(path_value: Path | None) -> Path | None:
    if path_value is None:
        return None
    return path_value.expanduser().resolve()


def _parse_int_option(raw_value: object, *, option: str) -> int:
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return int(raw_value, 10)
        except ValueError as exc:  # pragma: no cover - defensive parsing
            message = f"Overlay option '{option}' must be an integer."
            raise typer.BadParameter(message) from exc
    message = f"Overlay option '{option}' must be an integer."
    raise typer.BadParameter(message)


def _parse_path_option(raw_value: object, *, option: str) -> Path:
    if isinstance(raw_value, Path):
        return raw_value
    if isinstance(raw_value, str):
        return Path(raw_value)
    message = f"Overlay option '{option}' must be a filesystem path."
    raise typer.BadParameter(message)


def _set_overlay_option(options: OverlayCLIOptions, key: str, raw_value: object) -> None:
    attr = key.strip().lower()
    if attr in {"stubs_root", "overlays_root"}:
        candidate = _parse_path_option(raw_value, option=attr)
        resolved = _resolve_path(candidate)
        if resolved is None:
            message = f"Overlay option '{attr}' must be a filesystem path."
            raise typer.BadParameter(message)
        setattr(options, attr, resolved)
    elif attr in {"min_errors", "max_overlays"}:
        setattr(options, attr, _parse_int_option(raw_value, option=attr))
    elif attr in {
        "include_public_defs",
        "inject_getattr_any",
        "dry_run",
        "activate",
        "deactivate_all_first",
        "type_error_overlays",
    }:
        setattr(options, attr, _parse_bool(raw_value))
    else:
        message = f"Unknown overlay option '{key}'."
        raise typer.BadParameter(message)


@dataclass(frozen=True)
class ScipContext:
    """Cache of SCIP lookups used during scanning."""

    index: SCIPIndex
    by_file: Mapping[str, Document]


@dataclass(frozen=True)
class ScanInputs:
    """Bundle of contextual inputs used during module row construction."""

    scip_ctx: ScipContext
    type_signals: Mapping[str, FileTypeSignals]
    coverage_map: Mapping[str, Mapping[str, float]]
    tagging_rules: Mapping[str, Any]
    repo_root: Path
    max_file_bytes: int
    package_prefix: str | None


@dataclass(slots=True, frozen=True)
class PipelineContext:
    """Aggregated context derived from CLI inputs and repo state."""

    root: Path
    repo_root: Path
    scip_index: SCIPIndex
    scip_ctx: ScipContext
    type_signals: Mapping[str, FileTypeSignals]
    coverage_map: Mapping[str, Mapping[str, float]]
    config_records: list[dict[str, Any]]
    tagging_rules: Mapping[str, Any]
    package_prefix: str | None


@dataclass(slots=True, frozen=True)
class PipelineResult:
    """Aggregate artifact bundle produced by a pipeline run."""

    root: Path
    repo_root: Path
    module_rows: list[ModuleRecord]
    symbol_edges: list[tuple[str, str]]
    import_graph: ImportGraph
    use_graph: UseGraph
    config_index: list[dict[str, Any]]
    coverage_rows: list[dict[str, Any]]
    hotspot_rows: list[dict[str, Any]]
    tag_index: dict[str, list[str]]


def _discover_py_files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    """Return ordered Python files under ``root`` honoring include patterns.

    Parameters
    ----------
    root : Path
        Root directory to search for Python files. Files are discovered recursively
        using ``rglob("*.py")``, excluding any paths containing hidden directories
        (starting with ``.``).
    patterns : tuple[str, ...]
        Glob patterns to filter files. If empty, all Python files are returned.
        Patterns are matched against paths relative to ``root`` using ``fnmatch``.

    Returns
    -------
    list[Path]
        Sorted list of files relative to ``root`` matching the configured patterns.
    """
    with _stage_span("discover", root=root, patterns=len(patterns)) as meta:
        files = sorted(_iter_files(root, patterns if patterns else None))
        meta["count"] = len(files)
    return files


def _load_scip_artifacts(path: Path) -> tuple[SCIPIndex, ScipContext]:
    """Load the SCIP index and derive lookup helpers.

    Parameters
    ----------
    path : Path
        Path to the SCIP index file to load. The file must exist and be readable.

    Returns
    -------
    tuple[SCIPIndex, ScipContext]
        Parsed SCIP index and context lookups.

    Raises
    ------
    IngestError
        Raised when the SCIP payload cannot be read or parsed.
    """
    with _stage_span("ingest", scip=path) as meta:
        try:
            index = SCIPIndex.load(path)
        except Exception as exc:  # pragma: no cover - surface via CLI
            reason = "scip-load"
            raise IngestError(reason, path=str(path), detail=str(exc)) from exc
        ctx = ScipContext(index=index, by_file=index.by_file())
        meta["documents"] = len(index.documents)
        return index, ctx


def _collect_type_signal_map(
    root: Path,
    *,
    pyrefly_json: Path | None,
) -> dict[str, FileTypeSignals]:
    """Collect Pyrefly/Pyright summaries and normalize path keys.

    Parameters
    ----------
    root : Path
        Root directory path used for normalizing file paths. Also serves as the
        base path for locating Pyright JSON reports.
    pyrefly_json : Path | None
        Optional path to a Pyrefly JSON report file. If None, only Pyright
        reports are collected.

    Returns
    -------
    dict[str, FileTypeSignals]
        Mapping of normalized repo paths to joined type signal counts.

    Raises
    ------
    TypeSignalError
        Raised when either tool report cannot be parsed.
    """
    with _stage_span("type-signals", root=root) as meta:
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


def _collect_coverage_map(root: Path, coverage_xml: Path | None) -> dict[str, Mapping[str, float]]:
    """Collect coverage metrics keyed by normalized path.

    Parameters
    ----------
    root : Path
        Root directory path used for normalizing file paths in the coverage map.
    coverage_xml : Path | None
        Optional path to a coverage XML report file. If None or the file does
        not exist, returns an empty mapping.

    Returns
    -------
    dict[str, Mapping[str, float]]
        Mapping of repo paths to coverage metrics (may be empty).
    """
    with _stage_span("coverage", source=str(coverage_xml) if coverage_xml else "none") as meta:
        raw_metrics = (
            collect_coverage(coverage_xml) if coverage_xml and coverage_xml.exists() else {}
        )
        normalized = _normalize_metric_map(raw_metrics, root)
        meta["files"] = len(normalized)
        return normalized


def _index_config_records(root: Path) -> list[dict[str, Any]]:
    """Return discovered config records under ``root``.

    Parameters
    ----------
    root : Path
        Root directory to search for configuration files. The function discovers
        config files using the indexing logic from ``index_config_files``.

    Returns
    -------
    list[dict[str, Any]]
        Config metadata rows consumed by downstream stages.
    """
    with _stage_span("config-index", root=root) as meta:
        records = index_config_files(root)
        meta["records"] = len(records)
        return records


def _load_tagging_rules(path: Path | None) -> Mapping[str, Any]:
    """Load YAML tagging rules or fall back to defaults.

    Parameters
    ----------
    path : Path | None
        Optional path to a custom YAML tagging rules file. If None, default
        rules are loaded.

    Returns
    -------
    Mapping[str, Any]
        Rule dictionary keyed by tag name.

    Raises
    ------
    TaggingError
        Raised when a custom rules file cannot be parsed.
    """
    source = str(path) if path else "defaults"
    with _stage_span("tagging-rules", source=source) as meta:
        try:
            rules = load_rules(str(path) if path else None)
        except Exception as exc:  # pragma: no cover - defensive
            reason = "load-rules"
            raise TaggingError(reason, path=source, detail=str(exc)) from exc
        meta["rules"] = len(rules)
        return rules


_EXCLUDED_SCAN_SEGMENTS = {"stubs", "overlays"}


def _should_skip_candidate(candidate: Path, root: Path) -> bool:
    if any(part.startswith(".") for part in candidate.parts):
        return True
    try:
        rel_parts = candidate.relative_to(root).parts
    except ValueError:  # pragma: no cover - defensive
        rel_parts = candidate.parts
    lowered = {part.lower() for part in rel_parts}
    return bool(lowered & _EXCLUDED_SCAN_SEGMENTS)


def _iter_files(root: Path, patterns: tuple[str, ...] | None = None) -> Iterable[Path]:
    normalized_patterns = tuple(patterns or ())
    for candidate in root.rglob("*.py"):
        if _should_skip_candidate(candidate, root):
            continue
        if normalized_patterns:
            rel = _normalized_rel_path(candidate, root)
            if not any(fnmatch(rel, pattern) for pattern in normalized_patterns):
                continue
        yield candidate


def _run_pipeline(
    *, pipeline: PipelineOptions
) -> PipelineResult:  # lint-ignore[PLR0914]: pipeline orchestration needs structured locals
    if pipeline.scip is None:
        message = "The --scip option is required for enrichment commands."
        raise typer.BadParameter(message)
    root_resolved = pipeline.root.resolve()
    repo_root = detect_repo_root(root_resolved)
    files = _discover_py_files(root_resolved, pipeline.only or ())
    scip_index, scip_ctx = _load_scip_artifacts(pipeline.scip)
    type_signal_lookup = _collect_type_signal_map(
        root_resolved,
        pyrefly_json=pipeline.pyrefly_json,
    )
    coverage_lookup = _collect_coverage_map(root_resolved, pipeline.coverage_xml)
    config_records = _index_config_records(root_resolved)
    tagging_rules = _load_tagging_rules(pipeline.tags_yaml)
    ctx = PipelineContext(
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

    module_rows, symbol_edges = _scan_modules(ctx, pipeline, files)

    with _stage_span("analytics", modules=len(module_rows)) as meta:
        import_graph, use_graph, config_index = _augment_module_rows(
            module_rows,
            ctx.scip_index,
            ctx.package_prefix,
            config_records=ctx.config_records,
        )
        coverage_rows = _build_coverage_rows(module_rows)
        hotspot_rows = _build_hotspot_rows(module_rows)
        meta["configs"] = len(config_index)
        meta["coverage_rows"] = len(coverage_rows)
        meta["hotspots"] = len(hotspot_rows)
    _infer_tags(module_rows, ctx.tagging_rules)
    tag_index = _build_tag_index(module_rows)

    return PipelineResult(
        root=ctx.root,
        repo_root=ctx.repo_root,
        module_rows=module_rows,
        symbol_edges=symbol_edges,
        import_graph=import_graph,
        use_graph=use_graph,
        config_index=config_index,
        coverage_rows=coverage_rows,
        hotspot_rows=hotspot_rows,
        tag_index=tag_index,
    )


def _execute_pipeline(ctx: typer.Context) -> tuple[PipelineResult, CLIContextState]:
    state = _ensure_state(ctx)
    state.pipeline.out.mkdir(parents=True, exist_ok=True)
    result = _run_pipeline(pipeline=state.pipeline)
    return result, state


def _execute_pipeline_or_exit(ctx: typer.Context) -> tuple[PipelineResult, CLIContextState]:
    try:
        return _execute_pipeline(ctx)
    except StageError as exc:  # pragma: no cover - exercised in integration
        LOGGER.exception("stage_error %s", _format_stage_meta(exc.log_extra()))
        message = exc.detail or exc.reason
        typer.echo(f"[{exc.stage}] {message}", err=True)
        raise typer.Exit(1) from exc


def _handle_dry_run(
    command: str,
    *,
    dry_run: bool,
    result: PipelineResult,
) -> bool:
    """Emit deterministic dry-run summaries and signal whether callers should return.

    Parameters
    ----------
    command : str
        Command name to include in the dry-run summary output. Used for
        identifying which command is running in dry-run mode.
    dry_run : bool
        If True, emit summary and return True to signal early return. If False,
        return False to allow normal execution to continue.
    result : PipelineResult
        Pipeline result object containing module rows, symbol edges, tag index,
        and other metrics to summarize in dry-run output.

    Returns
    -------
    bool
        True if dry_run is True (indicating callers should return early),
        False otherwise (indicating normal execution should continue).
    """
    if not dry_run:
        return False
    overlay_candidates = sum(
        1 for row in result.module_rows if getattr(row, "overlay_needed", False)
    )
    typer.echo(
        f"[{command}] DRY RUN: modules={len(result.module_rows)} "
        f"edges={len(result.symbol_edges)} overlays_needed={overlay_candidates} "
        f"tags={len(result.tag_index)}"
    )
    return True


def _scan_modules(
    ctx: PipelineContext,
    pipeline: PipelineOptions,
    files: Sequence[Path],
) -> tuple[list[ModuleRecord], list[tuple[str, str]]]:
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
    with _stage_span("index", files=len(files)) as meta:
        for fp in files:
            row_dict, edges = _build_module_row(fp, ctx.root, scan_inputs)
            module_rows.append(row_dict)
            symbol_edges.extend(edges)
        meta["modules"] = len(module_rows)
    return module_rows, symbol_edges


@app.command("all")
def run_all(  # lint-ignore[PLR0913,PLR0917]: Typer CLI requires enumerating shared options
    ctx: typer.Context,
    root: Path = ROOT_OPTION,
    scip: Path | None = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
    coverage_xml: Path = COVERAGE_OPTION,
    only: list[str] | None = ONLY_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
    *,
    owners: bool = OWNERS_OPTION,
    history_window_days: int = HISTORY_WINDOW_OPTION,
    commits_window: int = COMMITS_WINDOW_OPTION,
    emit_slices: bool = EMIT_SLICES_OPTION,
    slices_filter: list[str] | None = SLICES_FILTER_OPTION,
    emit_ast: bool = EMIT_AST_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Run the full enrichment pipeline and emit all artifacts."""
    _capture_shared_state(
        ctx,
        root=root,
        scip=scip,
        out=out,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
        max_file_bytes=max_file_bytes,
        owners=owners,
        history_window_days=history_window_days,
        commits_window=commits_window,
        emit_slices=emit_slices,
        slices_filter=slices_filter,
    )
    result, state = _execute_pipeline_or_exit(ctx)
    if _handle_dry_run("all", dry_run=dry_run, result=result):
        return
    if state.analytics.owners:
        _apply_ownership(
            result,
            state.pipeline.out,
            history_window_days=state.analytics.history_window_days,
            commits_window=state.analytics.commits_window,
        )
    if state.analytics.emit_slices:
        _write_slices_output(
            result.module_rows,
            state.pipeline.out,
            slices_filter=list(state.analytics.slices_filter),
        )
    _write_exports_outputs(result, state.pipeline.out)
    _write_graph_outputs(result, state.pipeline.out)
    _write_uses_output(result, state.pipeline.out)
    _write_typedness_output(result, state.pipeline.out)
    _write_doc_output(result, state.pipeline.out)
    _write_coverage_output(result, state.pipeline.out)
    _write_config_output(result, state.pipeline.out)
    _write_hotspot_output(result, state.pipeline.out)
    _write_ast_outputs(result, state.pipeline.out, emit_ast=emit_ast)
    typer.echo(f"[all] Completed enrichment for {len(result.module_rows)} modules.")


@app.command("run")
def run(
    ctx: typer.Context,
    root: Path = ROOT_OPTION,
    scip: Path | None = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
    coverage_xml: Path = COVERAGE_OPTION,
    only: list[str] | None = ONLY_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
    *,
    owners: bool = OWNERS_OPTION,
    history_window_days: int = HISTORY_WINDOW_OPTION,
    commits_window: int = COMMITS_WINDOW_OPTION,
    emit_slices: bool = EMIT_SLICES_OPTION,
    slices_filter: list[str] | None = SLICES_FILTER_OPTION,
    emit_ast: bool = EMIT_AST_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Alias for ``all`` to match historical CLI entrypoints."""
    run_all(
        ctx,
        root=root,
        scip=scip,
        out=out,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
        max_file_bytes=max_file_bytes,
        owners=owners,
        history_window_days=history_window_days,
        commits_window=commits_window,
        emit_slices=emit_slices,
        slices_filter=slices_filter,
        emit_ast=emit_ast,
        dry_run=dry_run,
    )


@app.command("scan")
def scan(
    ctx: typer.Context,
    root: Path = ROOT_OPTION,
    scip: Path | None = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
    coverage_xml: Path = COVERAGE_OPTION,
    only: list[str] | None = ONLY_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
    *,
    owners: bool = OWNERS_OPTION,
    history_window_days: int = HISTORY_WINDOW_OPTION,
    commits_window: int = COMMITS_WINDOW_OPTION,
    emit_slices: bool = EMIT_SLICES_OPTION,
    slices_filter: list[str] | None = SLICES_FILTER_OPTION,
    emit_ast: bool = EMIT_AST_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Backward-compatible alias for ``all``."""
    typer.echo("[scan] Deprecated alias for `all`; running full pipeline.")
    run_all(
        ctx,
        root=root,
        scip=scip,
        out=out,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
        max_file_bytes=max_file_bytes,
        owners=owners,
        history_window_days=history_window_days,
        commits_window=commits_window,
        emit_slices=emit_slices,
        slices_filter=slices_filter,
        emit_ast=emit_ast,
        dry_run=dry_run,
    )


@app.command("exports")
def exports(
    ctx: typer.Context,
    root: Path = ROOT_OPTION,
    scip: Path | None = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
    coverage_xml: Path = COVERAGE_OPTION,
    only: list[str] | None = ONLY_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
    *,
    owners: bool = OWNERS_OPTION,
    history_window_days: int = HISTORY_WINDOW_OPTION,
    commits_window: int = COMMITS_WINDOW_OPTION,
    emit_slices: bool = EMIT_SLICES_OPTION,
    slices_filter: list[str] | None = SLICES_FILTER_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Emit modules.jsonl, repo map, tag index, and Markdown module sheets."""
    _capture_shared_state(
        ctx,
        root=root,
        scip=scip,
        out=out,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
        max_file_bytes=max_file_bytes,
        owners=owners,
        history_window_days=history_window_days,
        commits_window=commits_window,
        emit_slices=emit_slices,
        slices_filter=slices_filter,
    )
    result, state = _execute_pipeline_or_exit(ctx)
    if _handle_dry_run("exports", dry_run=dry_run, result=result):
        return
    if state.analytics.owners:
        _apply_ownership(
            result,
            state.pipeline.out,
            history_window_days=state.analytics.history_window_days,
            commits_window=state.analytics.commits_window,
        )
    if state.analytics.emit_slices:
        _write_slices_output(
            result.module_rows,
            state.pipeline.out,
            slices_filter=list(state.analytics.slices_filter),
        )
    _write_exports_outputs(result, state.pipeline.out)
    typer.echo(f"[exports] Wrote module artifacts for {len(result.module_rows)} modules.")


@app.command("graph")
def graph(
    ctx: typer.Context,
    root: Path = ROOT_OPTION,
    scip: Path | None = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
    coverage_xml: Path = COVERAGE_OPTION,
    only: list[str] | None = ONLY_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
    *,
    owners: bool = OWNERS_OPTION,
    history_window_days: int = HISTORY_WINDOW_OPTION,
    commits_window: int = COMMITS_WINDOW_OPTION,
    emit_slices: bool = EMIT_SLICES_OPTION,
    slices_filter: list[str] | None = SLICES_FILTER_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Emit symbol and import graph artifacts."""
    _capture_shared_state(
        ctx,
        root=root,
        scip=scip,
        out=out,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
        max_file_bytes=max_file_bytes,
        owners=owners,
        history_window_days=history_window_days,
        commits_window=commits_window,
        emit_slices=emit_slices,
        slices_filter=slices_filter,
    )
    result, state = _execute_pipeline_or_exit(ctx)
    if _handle_dry_run("graph", dry_run=dry_run, result=result):
        return
    _write_graph_outputs(result, state.pipeline.out)
    typer.echo("[graph] Wrote symbol and import graphs.")


@app.command("uses")
def uses(
    ctx: typer.Context,
    root: Path = ROOT_OPTION,
    scip: Path | None = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
    coverage_xml: Path = COVERAGE_OPTION,
    only: list[str] | None = ONLY_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
    *,
    owners: bool = OWNERS_OPTION,
    history_window_days: int = HISTORY_WINDOW_OPTION,
    commits_window: int = COMMITS_WINDOW_OPTION,
    emit_slices: bool = EMIT_SLICES_OPTION,
    slices_filter: list[str] | None = SLICES_FILTER_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Emit the definition-to-use graph derived from SCIP."""
    _capture_shared_state(
        ctx,
        root=root,
        scip=scip,
        out=out,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
        max_file_bytes=max_file_bytes,
        owners=owners,
        history_window_days=history_window_days,
        commits_window=commits_window,
        emit_slices=emit_slices,
        slices_filter=slices_filter,
    )
    result, state = _execute_pipeline_or_exit(ctx)
    if _handle_dry_run("uses", dry_run=dry_run, result=result):
        return
    _write_uses_output(result, state.pipeline.out)
    typer.echo("[uses] Wrote uses graph.")


@app.command("typedness")
def typedness(
    ctx: typer.Context,
    root: Path = ROOT_OPTION,
    scip: Path | None = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
    coverage_xml: Path = COVERAGE_OPTION,
    only: list[str] | None = ONLY_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
    *,
    owners: bool = OWNERS_OPTION,
    history_window_days: int = HISTORY_WINDOW_OPTION,
    commits_window: int = COMMITS_WINDOW_OPTION,
    emit_slices: bool = EMIT_SLICES_OPTION,
    slices_filter: list[str] | None = SLICES_FILTER_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Emit typedness analytics (errors, annotation ratios, untyped defs)."""
    _capture_shared_state(
        ctx,
        root=root,
        scip=scip,
        out=out,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
        max_file_bytes=max_file_bytes,
        owners=owners,
        history_window_days=history_window_days,
        commits_window=commits_window,
        emit_slices=emit_slices,
        slices_filter=slices_filter,
    )
    result, state = _execute_pipeline_or_exit(ctx)
    if _handle_dry_run("typedness", dry_run=dry_run, result=result):
        return
    _write_typedness_output(result, state.pipeline.out)
    typer.echo("[typedness] Wrote typedness analytics.")


@app.command("doc")
def doc(
    ctx: typer.Context,
    root: Path = ROOT_OPTION,
    scip: Path | None = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
    coverage_xml: Path = COVERAGE_OPTION,
    only: list[str] | None = ONLY_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
    *,
    owners: bool = OWNERS_OPTION,
    history_window_days: int = HISTORY_WINDOW_OPTION,
    commits_window: int = COMMITS_WINDOW_OPTION,
    emit_slices: bool = EMIT_SLICES_OPTION,
    slices_filter: list[str] | None = SLICES_FILTER_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Emit doc health analytics for module docstrings."""
    _capture_shared_state(
        ctx,
        root=root,
        scip=scip,
        out=out,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
        max_file_bytes=max_file_bytes,
        owners=owners,
        history_window_days=history_window_days,
        commits_window=commits_window,
        emit_slices=emit_slices,
        slices_filter=slices_filter,
    )
    result, state = _execute_pipeline_or_exit(ctx)
    if _handle_dry_run("doc", dry_run=dry_run, result=result):
        return
    _write_doc_output(result, state.pipeline.out)
    typer.echo("[doc] Wrote doc health analytics.")


@app.command("coverage")
def coverage(
    ctx: typer.Context,
    root: Path = ROOT_OPTION,
    scip: Path | None = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
    coverage_xml: Path = COVERAGE_OPTION,
    only: list[str] | None = ONLY_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
    *,
    owners: bool = OWNERS_OPTION,
    history_window_days: int = HISTORY_WINDOW_OPTION,
    commits_window: int = COMMITS_WINDOW_OPTION,
    emit_slices: bool = EMIT_SLICES_OPTION,
    slices_filter: list[str] | None = SLICES_FILTER_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Emit coverage analytics table."""
    _capture_shared_state(
        ctx,
        root=root,
        scip=scip,
        out=out,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
        max_file_bytes=max_file_bytes,
        owners=owners,
        history_window_days=history_window_days,
        commits_window=commits_window,
        emit_slices=emit_slices,
        slices_filter=slices_filter,
    )
    result, state = _execute_pipeline_or_exit(ctx)
    if _handle_dry_run("coverage", dry_run=dry_run, result=result):
        return
    _write_coverage_output(result, state.pipeline.out)
    typer.echo("[coverage] Wrote coverage analytics.")


@app.command("config")
def config(
    ctx: typer.Context,
    root: Path = ROOT_OPTION,
    scip: Path | None = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
    coverage_xml: Path = COVERAGE_OPTION,
    only: list[str] | None = ONLY_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
    *,
    owners: bool = OWNERS_OPTION,
    history_window_days: int = HISTORY_WINDOW_OPTION,
    commits_window: int = COMMITS_WINDOW_OPTION,
    emit_slices: bool = EMIT_SLICES_OPTION,
    slices_filter: list[str] | None = SLICES_FILTER_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Emit config index (YAML/TOML/JSON/Markdown references)."""
    _capture_shared_state(
        ctx,
        root=root,
        scip=scip,
        out=out,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
        max_file_bytes=max_file_bytes,
        owners=owners,
        history_window_days=history_window_days,
        commits_window=commits_window,
        emit_slices=emit_slices,
        slices_filter=slices_filter,
    )
    result, state = _execute_pipeline_or_exit(ctx)
    if _handle_dry_run("config", dry_run=dry_run, result=result):
        return
    _write_config_output(result, state.pipeline.out)
    typer.echo("[config] Wrote config index.")


@app.command("hotspots")
def hotspots(
    ctx: typer.Context,
    root: Path = ROOT_OPTION,
    scip: Path | None = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
    coverage_xml: Path = COVERAGE_OPTION,
    only: list[str] | None = ONLY_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
    *,
    owners: bool = OWNERS_OPTION,
    history_window_days: int = HISTORY_WINDOW_OPTION,
    commits_window: int = COMMITS_WINDOW_OPTION,
    emit_slices: bool = EMIT_SLICES_OPTION,
    slices_filter: list[str] | None = SLICES_FILTER_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Emit hotspot analytics (complexity x churn x centrality)."""
    _capture_shared_state(
        ctx,
        root=root,
        scip=scip,
        out=out,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
        max_file_bytes=max_file_bytes,
        owners=owners,
        history_window_days=history_window_days,
        commits_window=commits_window,
        emit_slices=emit_slices,
        slices_filter=slices_filter,
    )
    result, state = _execute_pipeline_or_exit(ctx)
    if _handle_dry_run("hotspots", dry_run=dry_run, result=result):
        return
    _write_hotspot_output(result, state.pipeline.out)
    typer.echo("[hotspots] Wrote hotspot analytics.")


@app.command("overlays")
def overlays(  # lint-ignore[PLR0913,PLR0917]: Typer CLI shared options
    ctx: typer.Context,
    root: Path = ROOT_OPTION,
    scip: Path | None = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
    coverage_xml: Path = COVERAGE_OPTION,
    only: list[str] | None = ONLY_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
    *,
    owners: bool = OWNERS_OPTION,
    history_window_days: int = HISTORY_WINDOW_OPTION,
    commits_window: int = COMMITS_WINDOW_OPTION,
    emit_slices: bool = EMIT_SLICES_OPTION,
    slices_filter: list[str] | None = SLICES_FILTER_OPTION,
    config_path: Path | None = OVERLAYS_CONFIG_OPTION,
    overrides: list[str] | None = OVERLAYS_SET_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Generate targeted overlays and optionally activate them into the stub path.

    This command generates type stub overlays (.pyi files) for modules with type
    errors, missing annotations, or other typing issues. Overlays are generated based
    on SCIP index data, type error reports, and configurable policies. The command
    can optionally activate overlays into the stub path for immediate use by type
    checkers, or deactivate existing overlays before generating new ones.

    Parameters
    ----------
    ctx : typer.Context
        Typer context object providing access to shared CLI state (pipeline options,
        analytics settings). The context is used to retrieve SCIP index path and
        other pipeline configuration required for overlay generation.
    root : Path
        Repository root directory path. Provided via typer.Option. Used as the
        base directory for discovering Python files and resolving relative paths.
    scip : Path | None, optional
        Optional path to SCIP index file. Provided via typer.Option. If None,
        overlay generation may be limited or disabled. Defaults to None.
    out : Path
        Output directory path for generated overlay files. Provided via typer.Option.
        Overlays are written to a subdirectory within this output directory.
    pyrefly_json : Path | None, optional
        Optional path to Pyrefly JSON report. Provided via typer.Option. Used to
        identify type errors and inform overlay generation decisions. Defaults to None.
    tags_yaml : Path | None, optional
        Optional path to tags YAML configuration file. Provided via typer.Option.
        Used for filtering and tagging modules that require overlays. Defaults to None.
    coverage_xml : Path
        Path to coverage XML report file. Provided via typer.Option. Used for
        identifying covered code paths that may need type annotations.
    only : list[str] | None, optional
        Optional list of file patterns to include. Provided via typer.Option.
        If provided, only files matching these patterns are processed. Defaults to None.
    max_file_bytes : int, optional
        Maximum file size in bytes. Provided via typer.Option. Files exceeding
        this limit are skipped during processing. Defaults to a configured maximum.
    owners : bool, optional
        Whether to include code ownership analytics. Provided via typer.Option.
        Used for identifying code owners of modules requiring overlays. Defaults to False.
    history_window_days : int, optional
        Number of days to look back for git history analysis. Provided via typer.Option.
        Used for computing code churn metrics. Defaults to a configured window.
    commits_window : int, optional
        Number of commits to analyze for git-based metrics. Provided via typer.Option.
        Used for identifying frequently changed files that may need overlays. Defaults
        to a configured window.
    emit_slices : bool, optional
        Whether to emit code slice analytics. Provided via typer.Option. Slices can
        help identify code patterns that need type annotations. Defaults to False.
    slices_filter : list[str] | None, optional
        Optional list of slice filter patterns. Provided via typer.Option. If provided,
        only slices matching these patterns are included. Defaults to None.
    config_path : Path | None, optional
        Path to a YAML/JSON configuration file describing overlay generation settings
        (e.g., min_errors, max_overlays, include_public_defs). If None, default
        settings are used. The config file can specify overlay policies, paths,
        and generation rules.
    overrides : list[str] | None, optional
        List of KEY=VALUE override strings to modify overlay settings from config
        or defaults. Each override must use the format "KEY=VALUE" (e.g., "min_errors=5").
        Overrides take precedence over config file settings. If None, no overrides
        are applied.
    dry_run : bool, optional
        If True, perform a dry run without writing overlay files. Provided via
        typer.Option. Shows what would be generated without actually creating files.
        Defaults to False.

    Raises
    ------
    typer.BadParameter
        Raised in the following cases:
        - ``--scip`` option is missing or invalid: SCIP index is required for
          overlay generation as it provides symbol definitions and type information
        - Override format is invalid: override strings must use KEY=VALUE format
        - Config file parsing fails: YAML/JSON config cannot be parsed or contains
          invalid values

    Notes
    -----
    This command performs overlay generation by analyzing SCIP index data and type
    error reports to identify modules that would benefit from type stub overlays.
    Overlays are generated based on configurable policies (e.g., minimum type errors,
    maximum overlays per run, public definitions only). The command writes overlay
    files to the configured overlays root directory and optionally activates them
    into the stub path. A manifest file tracks generated overlays for management
    and cleanup. The command respects the --deactivate-all-first option to clear
    existing overlays before generating new ones.
    """
    _capture_shared_state(
        ctx,
        root=root,
        scip=scip,
        out=out,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
        max_file_bytes=max_file_bytes,
        owners=owners,
        history_window_days=history_window_days,
        commits_window=commits_window,
        emit_slices=emit_slices,
        slices_filter=slices_filter,
    )
    state = _ensure_state(ctx)
    pipeline = state.pipeline
    if pipeline.scip is None:
        message = "The --scip option is required for overlay generation."
        raise typer.BadParameter(message)
    options = _load_overlay_options(config_path, list(overrides or ()))
    if dry_run and not options.dry_run:
        options = replace(options, dry_run=True)
    overlay_ctx = _build_overlay_context(pipeline, options)
    overlay_ctx.overlays_root.mkdir(parents=True, exist_ok=True)
    overlay_ctx.stubs_root.parent.mkdir(parents=True, exist_ok=True)

    removed = 0
    if options.deactivate_all_first:
        removed = deactivate_all(
            overlays_root=overlay_ctx.overlays_root,
            stubs_root=overlay_ctx.stubs_root,
        )

    generated: list[str] = []
    generated_set: set[str] = set()
    manifest_entries: list[str] = []
    package_overlays: set[str] = set()
    for fp in _iter_files(overlay_ctx.root):
        rel = _normalized_rel_path(fp, overlay_ctx.root)
        result = generate_overlay_for_file(
            py_file=fp,
            package_root=overlay_ctx.root,
            policy=overlay_ctx.policy,
            inputs=overlay_ctx.inputs,
        )
        if result.created and rel not in generated_set:
            generated.append(rel)
            generated_set.add(rel)
            manifest_entries.append(f"{overlay_ctx.package_name}/{rel}")
            if len(generated) >= overlay_ctx.policy.max_overlays or _ensure_package_overlays(
                rel_path=Path(rel),
                generated=generated,
                generated_set=generated_set,
                manifest_entries=manifest_entries,
                package_name=overlay_ctx.package_name,
                package_overlays=package_overlays,
                root=overlay_ctx.root,
                scip_index=overlay_ctx.scip_index,
                policy=overlay_ctx.policy,
                type_error_counts=overlay_ctx.type_counts,
            ):
                break
        if len(generated) >= overlay_ctx.policy.max_overlays:
            break

    if options.dry_run:
        typer.echo(
            f"[overlays] DRY RUN: would generate {len(generated)} overlays (removed {removed})."
        )
        return

    typer.echo(
        f"[overlays] Generated {len(generated)} overlays into {options.overlays_root} (removed {removed})."
    )
    if options.activate and generated:
        activated = activate_overlays(
            generated,
            overlays_root=overlay_ctx.overlays_root,
            stubs_root=overlay_ctx.stubs_root,
        )
        typer.echo(f"[overlays] Activated {activated} overlays into {options.stubs_root}.")

    manifest_path = overlay_ctx.overlays_root / "overlays_manifest.json"
    write_json(
        manifest_path,
        {
            "package": overlay_ctx.package_name,
            "generated": manifest_entries,
            "removed": removed,
            "activated": bool(options.activate and generated),
        },
    )
    typer.echo(f"[overlays] Manifest written to {manifest_path}")


@app.command("to-duckdb")
def to_duckdb(  # pragma: no cover - exercised in dedicated test
    modules_jsonl: Annotated[
        Path,
        typer.Option(
            "--modules-jsonl",
            help="Path to modules.jsonl produced by the enrichment CLI.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    db_path: Annotated[
        Path,
        typer.Option(
            "--db",
            help="Target DuckDB catalog for enrichment analytics.",
            dir_okay=False,
        ),
    ] = Path("build/enrich/enrich.duckdb"),
) -> None:
    """Load ``modules.jsonl`` into DuckDB (idempotent on ``path``)."""
    count = ingest_modules_jsonl(DuckConn(db_path=db_path), modules_jsonl)
    typer.echo(f"[to-duckdb] Loaded {count} rows into {db_path}")


def _load_overlay_tagged_paths(out_dir: Path, overlay_tag: str) -> frozenset[str]:
    """Return cached overlay-needed paths from the most recent tag index.

    Parameters
    ----------
    out_dir : Path
        Output directory containing the tags subdirectory. The function looks
        for ``tags/tags_index.yaml`` within this directory.
    overlay_tag : str
        Tag name to filter overlay paths. If empty, returns an empty frozenset.
        The tag is used to identify which paths require overlay generation.

    Returns
    -------
    frozenset[str]
        Set of file paths that require overlay generation, filtered by the
        specified tag. Returns an empty frozenset if the tag is empty, the
        tags file doesn't exist, or YAML parsing fails.
    """
    if not overlay_tag:
        return frozenset()
    tags_file = out_dir / "tags" / "tags_index.yaml"
    if not tags_file.exists() or yaml_module is None:
        return frozenset()
    try:
        payload = yaml_module.safe_load(tags_file.read_text(encoding="utf-8"))
    except YAML_ERRORS:  # pragma: no cover - defensive parsing
        LOGGER.debug("Failed to read tag index from %s", tags_file, exc_info=True)
        return frozenset()
    if not isinstance(payload, Mapping):
        return frozenset()
    entries = payload.get(overlay_tag, [])
    if not isinstance(entries, list):
        return frozenset()
    return frozenset(str(item) for item in entries if isinstance(item, str))


def _build_overlay_context(
    pipeline: PipelineOptions,
    options: OverlayCLIOptions,
) -> OverlayContext:
    if pipeline.scip is None:
        message = "The --scip option is required for overlay generation."
        raise typer.BadParameter(message)
    root_resolved = pipeline.root.resolve()
    package_name = root_resolved.name
    overlays_target_root = (options.overlays_root / package_name).resolve()
    stubs_target_root = (options.stubs_root / package_name).resolve()
    scip_index = SCIPIndex.load(pipeline.scip)
    type_signal_lookup = _normalize_type_signal_map(
        collect_type_signals(
            pyrefly_report=str(pipeline.pyrefly_json) if pipeline.pyrefly_json else None,
            pyright_json=str(root_resolved),
        ),
        root_resolved,
    )
    type_counts: dict[str, int] = {
        path: signals.total
        for path, signals in type_signal_lookup.items()
        if not Path(path).is_absolute()
    }
    policy = OverlayPolicy(
        overlays_root=overlays_target_root,
        include_public_defs=options.include_public_defs,
        inject_module_getattr_any=options.inject_getattr_any,
        when_type_errors=options.type_error_overlays,
        min_type_errors=options.min_errors,
        max_overlays=options.max_overlays,
        export_hub_threshold=EXPORT_HUB_THRESHOLD,
        overlay_tag="overlay-needed",
    )
    overlay_tagged_paths = _load_overlay_tagged_paths(pipeline.out, policy.overlay_tag)
    return OverlayContext(
        root=root_resolved,
        package_name=package_name,
        overlays_root=overlays_target_root,
        stubs_root=stubs_target_root,
        scip_index=scip_index,
        type_counts=type_counts,
        policy=policy,
        inputs=OverlayInputs(
            scip=scip_index,
            type_error_counts=type_counts,
            overlay_tagged_paths=overlay_tagged_paths,
        ),
    )


def _build_module_row(
    fp: Path,
    root: Path,
    inputs: ScanInputs,
) -> tuple[ModuleRecord, list[tuple[str, str]]]:
    rel = _normalized_rel_path(fp, root)
    repo_path = _normalized_rel_path(fp, inputs.repo_root)
    module_name = module_name_from_path(inputs.repo_root, fp, inputs.package_prefix)
    stable_id = stable_id_for_path(repo_path)
    scip_symbols, symbol_edges = _scip_symbols_and_edges(rel, inputs)
    type_errors = _type_error_count(rel, inputs)
    record = ModuleRecord(
        path=rel,
        repo_path=repo_path,
        module_name=module_name,
        stable_id=stable_id,
        scip_symbols=scip_symbols,
        type_errors=type_errors,
        type_error_count=type_errors,
        doc_metrics={
            "has_summary": False,
            "param_parity": True,
            "examples_present": False,
        },
        annotation_ratio={"params": 1.0, "returns": 1.0},
        side_effects={
            "filesystem": False,
            "network": False,
            "subprocess": False,
            "database": False,
        },
        complexity={"branches": 0, "cyclomatic": 1, "loc": 0},
        covered_lines_ratio=_coverage_value(rel, inputs, "covered_lines_ratio"),
        covered_defs_ratio=_coverage_value(rel, inputs, "covered_defs_ratio"),
    )

    code = _read_module_source(fp, rel, record, inputs.max_file_bytes)
    if code is None:
        return record, symbol_edges

    try:
        idx = _index_module_safe(rel, code)
    except IndexingError as exc:
        LOGGER.exception("LibCST index failed for %s", rel, extra=exc.log_extra())
        record.add_error(exc)
        return record, symbol_edges

    outline_nodes = _collect_outline_nodes(rel, code, record)
    _apply_index_results(record, idx, outline_nodes)
    record.config_refs = []
    return record, symbol_edges


def _scip_symbols_and_edges(
    rel_path: str,
    inputs: ScanInputs,
) -> tuple[list[str], list[tuple[str, str]]]:
    document = inputs.scip_ctx.by_file.get(rel_path)
    symbols = sorted(
        {symbol.symbol for symbol in (document.symbols if document else []) if symbol.symbol}
    )
    return symbols, [(symbol, rel_path) for symbol in symbols]


def _index_module_safe(rel_path: str, code: str) -> ModuleIndex:
    """Run LibCST indexing with structured error reporting.

    Parameters
    ----------
    rel_path : str
        Relative path to the module being indexed. Used for error reporting and
        context in the returned ModuleIndex.
    code : str
        Source code content of the module to parse. Must be valid Python syntax
        for LibCST to successfully parse.

    Returns
    -------
    ModuleIndex
        Parsed LibCST metadata for the module.

    Raises
    ------
    IndexingError
        Raised when LibCST fails to parse the module.
    """
    try:
        return index_module(rel_path, code)
    except Exception as exc:  # pragma: no cover - defensive
        reason = "libcst"
        raise IndexingError(reason, path=rel_path, detail=str(exc)) from exc


def _read_module_source(
    fp: Path,
    rel_path: str,
    record: ModuleRecord,
    max_file_bytes: int,
) -> str | None:
    """Return module source or record a structured error.

    Parameters
    ----------
    fp : Path
        File path to read source from. The file must exist and be readable.
    rel_path : str
        Relative path to the module, used for error reporting when read fails.
    record : ModuleRecord
        Module record to update with errors if reading fails. Errors are added
        via ``record.add_error()`` and ``parse_ok`` is set to False.
    max_file_bytes : int
        Maximum file size in bytes. Files exceeding this limit are skipped and
        an error is recorded.

    Returns
    -------
    str | None
        Source text when available, otherwise ``None`` after recording an error.
    """
    try:
        file_size = fp.stat().st_size
    except OSError as exc:
        error = IndexingError("stat", path=rel_path, detail=str(exc))
        LOGGER.warning("Failed to stat %s", rel_path, exc_info=True)
        record.add_error(error)
        return None
    if file_size > max_file_bytes:
        detail = f"{file_size}>{max_file_bytes}"
        error = IndexingError("file-too-large", path=rel_path, detail=detail)
        record.add_error(error)
        return None
    try:
        return fp.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        error = IndexingError("read", path=rel_path, detail=str(exc))
        LOGGER.warning("Failed to read %s", rel_path, exc_info=True)
        record.add_error(error)
        return None


def _collect_outline_nodes(
    rel_path: str,
    code: str,
    record: ModuleRecord,
) -> list[dict[str, Any]]:
    """Return Tree-sitter outline nodes while capturing failures.

    Parameters
    ----------
    rel_path : str
        Relative path to the module being processed. Used for error reporting
        when Tree-sitter parsing fails.
    code : str
        Source code content to parse with Tree-sitter. Must be valid Python
        syntax for successful parsing.
    record : ModuleRecord
        Module record to update with errors if Tree-sitter parsing fails. Errors
        are added via ``record.add_error()``.

    Returns
    -------
    list[dict[str, Any]]
        Outline nodes; empty list when extraction fails.
    """
    try:
        return _outline_nodes_for(rel_path, code)
    except IndexingError as exc:
        LOGGER.warning("Tree-sitter outline failed for %s", rel_path, extra=exc.log_extra())
        record.add_error(exc)
        return []


def _apply_index_results(
    record: ModuleRecord,
    idx: ModuleIndex,
    outline_nodes: list[dict[str, Any]],
) -> None:
    """Populate ``record`` with data derived from LibCST/Tree-sitter."""
    doc_metrics = dict(idx.doc_metrics)
    record.doc_metrics = doc_metrics
    has_summary = doc_metrics.get("has_summary")
    record.docstring = idx.docstring
    record.doc_summary = idx.doc_summary
    record.doc_has_summary = bool(has_summary)
    param_parity = doc_metrics.get("param_parity")
    record.doc_param_parity = bool(param_parity) if param_parity is not None else True
    record.doc_examples_present = bool(doc_metrics.get("examples_present"))
    record.imports = [
        {
            "module": entry.module,
            "names": list(entry.names),
            "aliases": dict(entry.aliases),
            "is_star": entry.is_star,
            "level": entry.level,
        }
        for entry in idx.imports
    ]
    record.defs = [{"kind": d.kind, "name": d.name, "lineno": d.lineno} for d in idx.defs]
    record.exports = sorted(idx.exports)
    record.exports_declared = sorted(idx.exports)
    record.outline_nodes = outline_nodes
    record.parse_ok = idx.parse_ok
    if idx.errors:
        record.errors.extend(idx.errors)
    record.doc_items = idx.doc_items
    record.annotation_ratio = dict(idx.annotation_ratio)
    record.untyped_defs = idx.untyped_defs
    record.side_effects = dict(idx.side_effects)
    record.raises = list(idx.raises)
    record.complexity = dict(idx.complexity)


def _outline_nodes_for(rel_path: str, code: str) -> list[dict[str, Any]]:
    """Build Tree-sitter outline nodes for ``rel_path``.

    Parameters
    ----------
    rel_path : str
        Relative path to the module being processed. Used for error reporting
        when Tree-sitter parsing fails.
    code : str
        Source code content to parse with Tree-sitter. Must be valid Python
        syntax for successful parsing.

    Returns
    -------
    list[dict[str, Any]]
        Outline node structures capturing names and byte offsets.

    Raises
    ------
    IndexingError
        Raised when Tree-sitter parsing fails.
    """
    try:
        outline = build_outline(rel_path, code.encode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        reason = "tree-sitter"
        raise IndexingError(reason, path=rel_path, detail=str(exc)) from exc
    if outline is None:
        return []
    return [
        {
            "kind": node.kind,
            "name": node.name,
            "start": node.start_byte,
            "end": node.end_byte,
        }
        for node in outline.nodes
    ]


def _type_error_count(rel_path: str, inputs: ScanInputs) -> int:
    signal = inputs.type_signals.get(rel_path)
    return signal.total if signal else 0


def _coverage_value(rel_path: str, inputs: ScanInputs, key: str) -> float:
    entry = inputs.coverage_map.get(rel_path, {})
    return float(entry.get(key, 0.0))


def _augment_module_rows(
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
        Module metadata rows (mutable mapping) to augment with graph and export information.
    scip_index : SCIPIndex
        SCIP index for building use graphs and resolving symbol references.
    package_prefix : str | None
        Optional package prefix for module name normalization.
    config_records : list[dict[str, Any]] | None, optional
        Optional configuration file records to cross-reference with modules.

    Returns
    -------
    tuple[ImportGraph, UseGraph, list[dict[str, Any]]]
        Graphs and config index records with reference metadata.
    """
    module_name_map = build_module_name_map(module_rows, package_prefix)
    import_graph = build_import_graph(module_rows, package_prefix)
    use_graph = build_use_graph(scip_index)
    config_records = config_records or []
    config_by_dir = _group_configs_by_dir(config_records)
    config_references: dict[str, set[str]] = {record["path"]: set() for record in config_records}

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
        path = str(row["path"])
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
        refs = _config_refs_for_row(path, config_by_dir)
        row["config_refs"] = refs
        for ref in refs:
            config_references.setdefault(ref, set()).add(path)
        overlay_needed = _should_mark_overlay(row)
        row["overlay_needed"] = overlay_needed
        if overlay_needed:
            current_tags = row.get("tags")
            tag_list = current_tags if isinstance(current_tags, list) else []
            tag_set = {str(tag) for tag in tag_list}
            tag_set.add("overlay-needed")
            row["tags"] = sorted(tag_set)
        row["hotspot_score"] = compute_hotspot_score(row)
    for record in config_records:
        referenced = config_references.get(record["path"], set())
        record["references"] = sorted(referenced)
    return import_graph, use_graph, config_records


def _build_tag_index(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
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


def _infer_tags(rows: list[ModuleRecord], rules: Mapping[str, Any]) -> None:
    """Apply tagging rules with logging/telemetry."""
    with _stage_span("tagging", rules=len(rules)) as meta:
        _apply_tagging(rows, rules)
        meta["tagged"] = sum(1 for row in rows if row.get("tags"))


def _apply_tagging(rows: list[ModuleRecord], rules: Mapping[str, Any]) -> None:
    """Apply tagging rules to module rows and update their tags in-place.

    Parameters
    ----------
    rows : list[ModuleRecord]
        Module metadata rows to tag. Modified in-place.
    rules : Mapping[str, Any]
        Tagging rules dictionary for inferring tags from module traits.
    """
    for row in rows:
        path = row.get("path")
        if not isinstance(path, str):
            continue
        traits = _traits_from_row(row)
        result = infer_tags(path=path, traits=traits, rules=rules)
        tag_set = set(row.get("tags") or [])
        tag_set.update(result.tags)
        row["tags"] = sorted(tag_set)


def _traits_from_row(row: Mapping[str, Any]) -> ModuleTraits:
    """Extract ModuleTraits from a module metadata row.

    Parameters
    ----------
    row : Mapping[str, Any]
        Module metadata row containing imports, exports, metrics, etc.

    Returns
    -------
    ModuleTraits
        Extracted traits object for tag inference.
    """
    imports_field = row.get("imports") or []
    imported_modules: list[str] = []
    if isinstance(imports_field, list):
        for entry in imports_field:
            if not isinstance(entry, Mapping):
                continue
            module = entry.get("module")
            if isinstance(module, str):
                imported_modules.append(module)
    exports = row.get("exports") or []
    has_all = bool(isinstance(exports, list) and exports)
    has_star = False
    if isinstance(imports_field, list):
        has_star = any(
            isinstance(entry, Mapping) and bool(entry.get("is_star")) for entry in imports_field
        )
    is_reexport_hub = has_star or (
        isinstance(exports, list) and len(exports) >= EXPORT_HUB_THRESHOLD
    )

    coverage_value = row.get("covered_lines_ratio")
    coverage_ratio = float(coverage_value) if isinstance(coverage_value, (int, float)) else 1.0

    fan_in_value = row.get("fan_in")
    fan_out_value = row.get("fan_out")
    hotspot_value = row.get("hotspot_score")

    type_error_value = row.get("type_error_count")
    if not isinstance(type_error_value, int):
        type_error_value = int(row.get("type_errors") or 0)

    doc_summary_flag = row.get("doc_has_summary")
    doc_parity_flag = row.get("doc_param_parity")

    return ModuleTraits(
        imported_modules=imported_modules,
        has_all=has_all,
        is_reexport_hub=is_reexport_hub,
        type_error_count=type_error_value,
        fan_in=int(fan_in_value) if isinstance(fan_in_value, int) else 0,
        fan_out=int(fan_out_value) if isinstance(fan_out_value, int) else 0,
        hotspot_score=float(hotspot_value) if isinstance(hotspot_value, (int, float)) else 0.0,
        covered_lines_ratio=coverage_ratio,
        doc_has_summary=bool(doc_summary_flag if doc_summary_flag is not None else True),
        doc_param_parity=bool(doc_parity_flag if doc_parity_flag is not None else True),
    )


def _build_coverage_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": row.get("path"),
            "covered_lines_ratio": float(row.get("covered_lines_ratio") or 0.0),
            "covered_defs_ratio": float(row.get("covered_defs_ratio") or 0.0),
        }
        for row in rows
    ]


def _build_hotspot_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
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


def _write_exports_outputs(result: PipelineResult, out: Path) -> None:
    with _stage_span("write-exports", modules=len(result.module_rows)) as meta:
        _write_modules_json(out, result.module_rows)
        _write_markdown_modules(out, result.module_rows)
        _write_repo_map(out, result)
        _write_tag_index(out, result.tag_index)
        meta["tag_groups"] = len(result.tag_index)


def _write_graph_outputs(result: PipelineResult, out: Path) -> None:
    with _stage_span("write-graphs", symbols=len(result.symbol_edges)) as meta:
        _write_symbol_graph(out, result.symbol_edges)
        write_import_graph(result.import_graph, out / "graphs" / "imports.parquet")
        meta["imports"] = sum(len(edges) for edges in result.import_graph.edges.values())


def _write_uses_output(result: PipelineResult, out: Path) -> None:
    with _stage_span("write-uses", files=len(result.use_graph.uses_by_file)) as meta:
        write_use_graph(result.use_graph, out / "graphs" / "uses.parquet")
        meta["edges"] = sum(len(paths) for paths in result.use_graph.uses_by_file.values())


def _apply_ownership(
    result: PipelineResult,
    out: Path,
    *,
    history_window_days: int,
    commits_window: int,
) -> OwnershipIndex:
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
    _write_ownership_output(ownership, out)
    return ownership


def _write_ownership_output(ownership: OwnershipIndex, out: Path) -> None:
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


def _write_slices_output(
    module_rows: Sequence[Mapping[str, Any]],
    out: Path,
    *,
    slices_filter: list[str] | None = None,
) -> None:
    filters = tuple(filter(None, slices_filter or []))
    slice_records: list[dict[str, Any]] = []
    index_rows: list[dict[str, Any]] = []
    for row in module_rows:
        tags = {tag for tag in row.get("tags") or [] if isinstance(tag, str)}
        if filters and not tags.intersection(filters):
            continue
        slice_record = build_slice_record(row)
        slice_dict = asdict(slice_record)
        write_slice(out, slice_record)
        slice_records.append(slice_dict)
        index_rows.append(
            {
                "slice_id": slice_record.slice_id,
                "path": slice_record.path,
                "module_name": slice_record.module_name,
            }
        )
    if not slice_records:
        return
    slices_dir = out / "slices"
    write_parquet(slices_dir / "index.parquet", index_rows)
    write_parquet_dataset(
        slices_dir / "index_dataset",
        index_rows,
        partitioning=["module_name"],
        dictionary_fields=("path", "module_name"),
    )
    write_jsonl(slices_dir / "slices.jsonl", slice_records)


def _write_typedness_output(result: PipelineResult, out: Path) -> None:
    rows = [
        {
            "path": row.get("path"),
            "type_error_count": int(row.get("type_error_count") or 0),
            "params_ratio": float((row.get("annotation_ratio") or {}).get("params", 0.0)),
            "returns_ratio": float((row.get("annotation_ratio") or {}).get("returns", 0.0)),
            "untyped_defs": int(row.get("untyped_defs") or 0),
        }
        for row in result.module_rows
    ]
    _write_tabular_records(out / "analytics" / "typedness.parquet", rows)


def _write_doc_output(result: PipelineResult, out: Path) -> None:
    rows = [
        {
            "path": row.get("path"),
            "doc_has_summary": bool(row.get("doc_has_summary")),
            "doc_param_parity": bool(row.get("doc_param_parity")),
            "doc_examples_present": bool(row.get("doc_examples_present")),
            "doc_summary": row.get("doc_summary"),
        }
        for row in result.module_rows
    ]
    _write_tabular_records(out / "docs" / "doc_health.parquet", rows)


def _write_coverage_output(result: PipelineResult, out: Path) -> None:
    _write_tabular_records(out / "coverage" / "coverage.parquet", result.coverage_rows)


def _write_config_output(result: PipelineResult, out: Path) -> None:
    write_jsonl(out / "configs" / "config_index.jsonl", result.config_index)


def _write_hotspot_output(result: PipelineResult, out: Path) -> None:
    _write_tabular_records(out / "analytics" / "hotspots.parquet", result.hotspot_rows)


def _write_ast_outputs(result: PipelineResult, out: Path, *, emit_ast: bool) -> None:
    if not emit_ast:
        return
    files: list[Path] = []
    for row in result.module_rows:
        path = row.get("path")
        if not isinstance(path, str):
            continue
        candidate = result.root / path
        if candidate.is_file():
            files.append(candidate)
    nodes, metrics = _collect_ast_artifacts(result.root, files)
    ast_dir = out / "ast"
    write_ast_parquet(nodes, metrics, out_dir=ast_dir)
    _write_ast_jsonl(ast_dir / "ast_nodes.jsonl", nodes)
    _write_ast_jsonl(ast_dir / "ast_metrics.jsonl", metrics)
    typer.echo(f"[ast] Wrote AST nodes ({len(nodes)}) and metrics ({len(metrics)}) tables + JSONL.")


def _write_modules_json(out: Path, module_rows: Sequence[ModuleRecord | dict[str, Any]]) -> None:
    records: list[dict[str, Any]] = []
    for row in module_rows:
        payload = row.as_json_row() if isinstance(row, ModuleRecord) else dict(row)
        ModuleRecordModel.model_validate(payload)
        records.append(payload)
    write_jsonl(out / "modules" / "modules.jsonl", records)


def _write_markdown_modules(
    out: Path, module_rows: Sequence[ModuleRecord | dict[str, Any]]
) -> None:
    modules_dir = out / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)
    for row in module_rows:
        record = row.as_json_row() if isinstance(row, ModuleRecord) else row
        path = record.get("path")
        if not isinstance(path, str):
            continue
        target = modules_dir / (Path(path).with_suffix(".md").name)
        write_markdown_module(target, record)


def _write_repo_map(out: Path, result: PipelineResult) -> None:
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
    LOGGER.info(
        "stage=summary modules=%d symbol_edges=%d tags=%d out=%s",
        len(result.module_rows),
        len(result.symbol_edges),
        len(tag_counts),
        out,
    )


def _write_symbol_graph(out: Path, symbol_edges: list[tuple[str, str]]) -> None:
    write_json(
        out / "graphs" / "symbol_graph.json",
        [{"symbol": symbol, "file": rel} for symbol, rel in symbol_edges],
    )


def _write_tabular_records(parquet_path: Path, rows: list[dict[str, Any]]) -> None:
    write_parquet(parquet_path, rows)
    write_jsonl(parquet_path.with_suffix(".jsonl"), rows)


def _collect_ast_artifacts(
    root: Path, files: Iterable[Path]
) -> tuple[list[AstNodeRow], list[AstMetricsRow]]:
    node_rows: list[AstNodeRow] = []
    metric_rows: list[AstMetricsRow] = []
    for fp in files:
        rel = _normalized_rel_path(fp, root)
        try:
            code = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            LOGGER.exception("Failed to read %s for AST emission", rel)
            continue
        try:
            tree = ast.parse(code, filename=rel, type_comments=True)
        except SyntaxError:
            LOGGER.exception("Failed to parse %s for AST emission", rel)
            metric_rows.append(empty_metrics_row(rel))
            continue
        node_rows.extend(collect_ast_nodes_from_tree(rel, tree))
        metric_rows.append(compute_ast_metrics(rel, tree))
    return node_rows, metric_rows


def _write_ast_jsonl(path: Path, rows: Iterable[AstNodeRow | AstMetricsRow]) -> None:
    """Persist AST artifacts to JSONL for portability."""
    write_jsonl(path, [row.as_record() for row in rows])


def _normalize_type_signal_map(
    signals: Mapping[str, FileTypeSignals],
    root: Path,
) -> dict[str, FileTypeSignals]:
    normalized: dict[str, FileTypeSignals] = {}
    root_resolved = root.resolve()
    for key, value in signals.items():
        normalized[_normalize_path_key(key)] = value
        try:
            rel = Path(key).resolve().relative_to(root_resolved)
        except (ValueError, OSError):
            continue
        normalized[_normalize_path_key(str(rel))] = value
    return normalized


def _normalize_metric_map(
    metrics: Mapping[str, Mapping[str, float]] | None,
    root: Path,
) -> dict[str, Mapping[str, float]]:
    if not metrics:
        return {}
    normalized: dict[str, Mapping[str, float]] = {}
    root_resolved = root.resolve()
    for key, value in metrics.items():
        normalized[_normalize_path_key(key)] = value
        try:
            rel = Path(key).resolve().relative_to(root_resolved)
        except (ValueError, OSError):
            continue
        normalized[_normalize_path_key(str(rel))] = value
    return normalized


def _normalize_path_key(path: str) -> str:
    return path.replace("\\", "/")


def _group_configs_by_dir(records: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for record in records:
        path = record.get("path")
        if not isinstance(path, str):
            continue
        dir_key = _dir_key_from_path(Path(path).parent)
        grouped.setdefault(dir_key, []).append(path)
    return grouped


def _config_refs_for_row(
    module_path: str,
    config_by_dir: Mapping[str, list[str]],
) -> list[str]:
    dirs = _ancestor_dirs(module_path)
    seen: set[str] = set()
    refs: list[str] = []
    for directory in dirs:
        for candidate in config_by_dir.get(directory, []):
            if candidate in seen:
                continue
            refs.append(candidate)
            seen.add(candidate)
    return refs


def _ancestor_dirs(path: str) -> list[str]:
    ancestors: list[str] = []
    current = Path(path).parent
    while True:
        key = _dir_key_from_path(current)
        if key:
            ancestors.append(key)
        if not key:
            break
        if current == current.parent:
            break
        current = current.parent
    return ancestors


def _dir_key_from_path(path: Path) -> str:
    rendered = str(path)
    if rendered in {"", "."}:
        return ""
    return rendered.replace("\\", "/")


def _should_mark_overlay(row: Mapping[str, Any]) -> bool:
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


def _ensure_package_overlays(  # lint-ignore[PLR0913]: helper wires overlay paths atomically
    *,
    rel_path: Path,
    generated: list[str],
    generated_set: set[str],
    manifest_entries: list[str],
    package_name: str,
    package_overlays: set[str],
    root: Path,
    scip_index: SCIPIndex,
    policy: OverlayPolicy,
    type_error_counts: Mapping[str, int],
) -> bool:
    """Ensure package ``__init__`` overlays exist for ancestors of ``rel_path``.

    Parameters
    ----------
    rel_path : Path
        Relative path to a Python file. Package overlays are created for
        all ancestor directories containing ``__init__.py`` files.
    generated : list[str]
        Mutable list of generated overlay paths (relative keys). New overlays
        are appended to this list.
    generated_set : set[str]
        Set of generated overlay paths for fast membership testing. Updated
        in parallel with ``generated``.
    manifest_entries : list[str]
        Mutable list of manifest entry strings. New entries are appended
        in the format ``{package_name}/{rel_key}``.
    package_name : str
        Package name prefix for manifest entries.
    package_overlays : set[str]
        Set of package overlay paths that have already been processed. Used
        to avoid duplicate work when traversing ancestor directories.
    root : Path
        Root directory of the package. Used to resolve absolute paths for
        ``__init__.py`` files.
    scip_index : SCIPIndex
        SCIP index for resolving star import re-exports in package overlays.
    policy : OverlayPolicy
        Policy controlling overlay generation (max_overlays, etc.).
    type_error_counts : Mapping[str, int]
        Mapping of module keys to type error counts. Used to determine
        eligibility for overlay generation.

    Returns
    -------
    bool
        True when the overlay budget (``policy.max_overlays``) was exhausted
        while creating package overlays. False otherwise.
    """
    current = rel_path.parent
    root_marker = Path()
    limit = policy.max_overlays
    while current != root_marker:
        init_rel = current / "__init__.py"
        rel_key = str(init_rel).replace("\\", "/")
        if rel_key in package_overlays:
            current = current.parent
            continue
        package_overlays.add(rel_key)
        init_abs = root / init_rel
        if not init_abs.exists():
            current = current.parent
            continue
        result = generate_overlay_for_file(
            py_file=init_abs,
            package_root=root,
            policy=policy,
            inputs=OverlayInputs(
                scip=scip_index,
                type_error_counts=type_error_counts,
                force=True,
            ),
        )
        if result.created:
            if rel_key not in generated_set:
                generated.append(rel_key)
                generated_set.add(rel_key)
                manifest_entries.append(f"{package_name}/{rel_key}")
            if len(generated) >= limit:
                return True
        current = current.parent
    return False


def _normalized_rel_path(path: Path, root: Path) -> str:
    return stable_module_path(root, path)


def _write_tag_index(out: Path, tag_index: Mapping[str, list[str]]) -> None:
    if yaml_module is None:
        return
    safe_dump = getattr(yaml_module, "safe_dump", None)
    if not callable(safe_dump):
        return
    dump_fn = cast("_YamlDumpFn", safe_dump)
    tags_path = out / "tags"
    tags_path.mkdir(parents=True, exist_ok=True)
    (tags_path / "tags_index.yaml").write_text(
        dump_fn(tag_index, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    app()
