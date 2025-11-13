# SPDX-License-Identifier: MIT
"""CLI entrypoint for repo enrichment and targeted overlay generation."""

from __future__ import annotations

import ast
import json
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Annotated, Any, Protocol, cast

try:  # pragma: no cover - optional dependency
    import polars as pl
except ImportError:  # pragma: no cover - optional dependency
    pl = None

import click
import typer
from typer.models import CommandInfo

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
from codeintel_rev.enrich.graph_builder import ImportGraph, build_import_graph, write_import_graph
from codeintel_rev.enrich.libcst_bridge import index_module
from codeintel_rev.enrich.output_writers import (
    write_json,
    write_jsonl,
    write_markdown_module,
    write_parquet,
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
    OverlayPolicy,
    activate_overlays,
    deactivate_all,
    generate_overlay_for_file,
)
from codeintel_rev.enrich.tagging import ModuleTraits, infer_tags, load_rules
from codeintel_rev.enrich.tree_sitter_bridge import build_outline
from codeintel_rev.export_resolver import build_module_name_map, resolve_exports
from codeintel_rev.risk_hotspots import compute_hotspot_score
from codeintel_rev.typedness import FileTypeSignals, collect_type_signals
from codeintel_rev.uses_builder import UseGraph, build_use_graph, write_use_graph

try:  # pragma: no cover - optional dependency
    import yaml as yaml_module
except ImportError:  # pragma: no cover - optional dependency
    yaml_module = None


LOGGER = logging.getLogger(__name__)


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


@dataclass(slots=True)
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


@dataclass(slots=True)
class AnalyticsOptions:
    """Optional analytics toggles shared across commands."""

    owners: bool = DEFAULT_ENABLE_OWNERS
    history_window_days: int = DEFAULT_OWNER_HISTORY_DAYS
    commits_window: int = DEFAULT_COMMITS_WINDOW
    emit_slices: bool = DEFAULT_EMIT_SLICES_FLAG
    slices_filter: tuple[str, ...] = ()


@dataclass(slots=True)
class CLIContextState:
    """CLI-scoped state shared between commands."""

    pipeline: PipelineOptions = field(default_factory=PipelineOptions)
    analytics: AnalyticsOptions = field(default_factory=AnalyticsOptions)


def _ensure_state(ctx: typer.Context) -> CLIContextState:
    state = ctx.obj
    if not isinstance(state, CLIContextState):
        state = CLIContextState()
        ctx.obj = state
    return state


def _state_from_click(ctx: click.Context) -> CLIContextState:
    typer_ctx = typer.Context.from_click(ctx)
    return _ensure_state(typer_ctx)


def _load_overlay_options(config_path: Path | None, overrides: list[str]) -> OverlayCLIOptions:
    options = OverlayCLIOptions()
    if config_path is not None:
        config_data = _read_overlay_config(config_path)
        for key, value in config_data.items():
            _set_overlay_option(options, key, value)
    for override in overrides:
        if "=" not in override:
            raise typer.BadParameter("Override values must use the KEY=VALUE format.")
        key, value = override.split("=", 1)
        _set_overlay_option(options, key, value)
    return options


def _resolve_path(path_value: Path | None) -> Path | None:
    if path_value is None:
        return None
    return path_value.expanduser().resolve()


def _update_pipeline_path(attr: str, allow_none: bool = False):
    def _callback(ctx: click.Context, param: click.Parameter, value: Path | None) -> None:
        state = _state_from_click(ctx)
        resolved = _resolve_path(value)
        if resolved is None and not allow_none:
            return
        setattr(state.pipeline, attr, resolved)

    return _callback


def _update_pipeline_tuple(attr: str):
    def _callback(ctx: click.Context, param: click.Parameter, value: tuple[str, ...]) -> None:
        state = _state_from_click(ctx)
        setattr(state.pipeline, attr, tuple(value))

    return _callback


def _update_pipeline_int(attr: str):
    def _callback(ctx: click.Context, param: click.Parameter, value: int) -> None:
        state = _state_from_click(ctx)
        setattr(state.pipeline, attr, value)

    return _callback


def _update_analytics_bool(attr: str):
    def _callback(ctx: click.Context, param: click.Parameter, value: bool) -> None:
        state = _state_from_click(ctx)
        setattr(state.analytics, attr, value)

    return _callback


def _update_analytics_int(attr: str):
    def _callback(ctx: click.Context, param: click.Parameter, value: int) -> None:
        state = _state_from_click(ctx)
        setattr(state.analytics, attr, value)

    return _callback


def _update_analytics_tuple(attr: str):
    def _callback(ctx: click.Context, param: click.Parameter, value: tuple[str, ...]) -> None:
        state = _state_from_click(ctx)
        setattr(state.analytics, attr, tuple(value))

    return _callback


def _build_common_click_options() -> list[click.Option]:
    return [
        click.Option(
            ["--root"],
            help="Repo or subfolder to scan.",
            default=Path().resolve(),
            type=click.Path(path_type=Path, exists=True, file_okay=False),
            expose_value=False,
            callback=_update_pipeline_path("root"),
        ),
        click.Option(
            ["--scip"],
            help="Path to SCIP index.json",
            required=True,
            type=click.Path(path_type=Path, exists=True, dir_okay=False),
            expose_value=False,
            callback=_update_pipeline_path("scip"),
        ),
        click.Option(
            ["--out"],
            help="Output directory for enrichment artifacts.",
            default=Path("codeintel_rev/io/ENRICHED"),
            type=click.Path(path_type=Path, file_okay=False),
            expose_value=False,
            callback=_update_pipeline_path("out"),
        ),
        click.Option(
            ["--pyrefly-json"],
            help="Optional path to a Pyrefly JSON/JSONL report.",
            default=None,
            type=click.Path(path_type=Path, exists=True, dir_okay=False),
            expose_value=False,
            callback=_update_pipeline_path("pyrefly_json", allow_none=True),
        ),
        click.Option(
            ["--tags-yaml"],
            help="Optional tagging rules YAML.",
            default=None,
            type=click.Path(path_type=Path, exists=True, dir_okay=False),
            expose_value=False,
            callback=_update_pipeline_path("tags_yaml", allow_none=True),
        ),
        click.Option(
            ["--coverage-xml"],
            help="Optional path to coverage XML (Cobertura format).",
            default=Path("coverage.xml"),
            type=click.Path(path_type=Path, dir_okay=False),
            expose_value=False,
            callback=_update_pipeline_path("coverage_xml"),
        ),
        click.Option(
            ["--only"],
            help="Glob patterns (repeatable) limiting modules relative to --root.",
            multiple=True,
            expose_value=False,
            callback=_update_pipeline_tuple("only"),
        ),
        click.Option(
            ["--max-file-bytes"],
            help="Skip parsing files larger than this byte threshold.",
            default=DEFAULT_MAX_FILE_BYTES,
            type=int,
            expose_value=False,
            callback=_update_pipeline_int("max_file_bytes"),
        ),
        click.Option(
            ["--owners/--no-owners"],
            help="Compute Git ownership analytics and enrich module rows.",
            default=DEFAULT_ENABLE_OWNERS,
            expose_value=False,
            callback=_update_analytics_bool("owners"),
        ),
        click.Option(
            ["--history-window-days"],
            help="Length (in days) of the long-term churn window (default: 90).",
            default=DEFAULT_OWNER_HISTORY_DAYS,
            type=int,
            expose_value=False,
            callback=_update_analytics_int("history_window_days"),
        ),
        click.Option(
            ["--commits-window"],
            help="Maximum commits per file sampled when computing bus factor.",
            default=DEFAULT_COMMITS_WINDOW,
            type=int,
            expose_value=False,
            callback=_update_analytics_int("commits_window"),
        ),
        click.Option(
            ["--emit-slices/--no-emit-slices"],
            help="Emit optional slice packs (JSON + Markdown) for selected modules.",
            default=DEFAULT_EMIT_SLICES_FLAG,
            expose_value=False,
            callback=_update_analytics_bool("emit_slices"),
        ),
        click.Option(
            ["--slices-filter"],
            help="Tag filters (repeatable) selecting modules when emitting slices.",
            multiple=True,
            expose_value=False,
            callback=_update_analytics_tuple("slices_filter"),
        ),
    ]


def _attach_common_options(command_info: typer.models.CommandInfo) -> None:
    click_command = command_info.command
    for option in _build_common_click_options():
        click_command.params.append(option)


def _command(*args: Any, **kwargs: Any):
    def decorator(func: Callable[..., Any]):
        command_info = app.command(*args, **kwargs)(func)
        _attach_common_options(command_info)
        return command_info

    return decorator


_EMIT_AST_FLAG = "--emit-ast/--no-emit-ast"


@dataclass(slots=True)
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


def _read_overlay_config(path: Path) -> Mapping[str, Any]:
    payload = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        if yaml_module is None:
            raise typer.BadParameter("PyYAML is required to parse YAML overlay configs.")
        data = yaml_module.safe_load(payload)
    else:
        data = json.loads(payload)
    if not isinstance(data, Mapping):
        raise typer.BadParameter("Overlay config must be a mapping of option names to values.")
    return data


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise typer.BadParameter(f"Cannot interpret '{value}' as a boolean.")


def _set_overlay_option(options: OverlayCLIOptions, key: str, raw_value: Any) -> None:
    attr = key.strip().lower()
    if attr in {"stubs_root", "overlays_root"}:
        setattr(options, attr, _resolve_path(Path(str(raw_value))) or Path())
    elif attr in {"min_errors", "max_overlays"}:
        setattr(options, attr, int(raw_value))
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
        raise typer.BadParameter(f"Unknown overlay option '{key}'.")


app = typer.Typer(add_completion=False, help="Repo enrichment utilities (scan + overlays).")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Initialize shared CLI context."""
    _ensure_state(ctx)


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
class PipelineResult:
    """Aggregate artifact bundle produced by a pipeline run."""

    root: Path
    repo_root: Path
    module_rows: list[dict[str, Any]]
    symbol_edges: list[tuple[str, str]]
    import_graph: ImportGraph
    use_graph: UseGraph
    config_index: list[dict[str, Any]]
    coverage_rows: list[dict[str, Any]]
    hotspot_rows: list[dict[str, Any]]
    tag_index: dict[str, list[str]]


def _iter_files(root: Path, patterns: tuple[str, ...] | None = None) -> Iterable[Path]:
    normalized_patterns = tuple(patterns or ())
    for candidate in root.rglob("*.py"):
        if any(part.startswith(".") for part in candidate.parts):
            continue
        if normalized_patterns:
            rel = _normalized_rel_path(candidate, root)
            if not any(fnmatch(rel, pattern) for pattern in normalized_patterns):
                continue
        yield candidate


def _run_pipeline(*, pipeline: PipelineOptions) -> PipelineResult:
    if pipeline.scip is None:
        raise typer.BadParameter("The --scip option is required for enrichment commands.")
    root_resolved = pipeline.root.resolve()
    repo_root = detect_repo_root(root_resolved)
    scip_index = SCIPIndex.load(pipeline.scip)
    scip_ctx = ScipContext(index=scip_index, by_file=scip_index.by_file())

    type_signal_lookup = _normalize_type_signal_map(
        collect_type_signals(
            pyrefly_report=str(pipeline.pyrefly_json) if pipeline.pyrefly_json else None,
            pyright_json=str(root_resolved),
        ),
        root_resolved,
    )
    coverage_lookup = _normalize_metric_map(
        collect_coverage(pipeline.coverage_xml) if pipeline.coverage_xml else {},
        root_resolved,
    )
    config_records = index_config_files(root_resolved)
    rules = load_rules(str(pipeline.tags_yaml) if pipeline.tags_yaml else None)

    scan_inputs = ScanInputs(
        scip_ctx=scip_ctx,
        type_signals=type_signal_lookup,
        coverage_map=coverage_lookup,
        tagging_rules=rules,
        repo_root=repo_root,
        max_file_bytes=pipeline.max_file_bytes,
        package_prefix=root_resolved.name or None,
    )
    module_rows: list[dict[str, Any]] = []
    symbol_edges: list[tuple[str, str]] = []
    only_patterns = pipeline.only

    for fp in _iter_files(root_resolved, only_patterns if only_patterns else None):
        row_dict, edges = _build_module_row(
            fp,
            root_resolved,
            scan_inputs,
        )
        module_rows.append(row_dict)
        symbol_edges.extend(edges)

    package_prefix = root_resolved.name or None
    import_graph, use_graph, config_index = _augment_module_rows(
        module_rows,
        scip_index,
        package_prefix,
        config_records=config_records,
    )
    _apply_tagging(module_rows, scan_inputs.tagging_rules)
    tag_index = _build_tag_index(module_rows)
    coverage_rows = _build_coverage_rows(module_rows)
    hotspot_rows = _build_hotspot_rows(module_rows)

    return PipelineResult(
        root=root_resolved,
        repo_root=repo_root,
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


@_command("all")
def run_all(
    ctx: typer.Context,
    emit_ast: Annotated[
        bool,
        typer.Option(
            _EMIT_AST_FLAG,
            help="Emit Parquet datasets with AST nodes and metrics.",
        ),
    ] = DEFAULT_EMIT_AST,
) -> None:
    """Run the full enrichment pipeline and emit all artifacts."""
    result, state = _execute_pipeline(ctx)
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


@_command("scan")
def scan(
    ctx: typer.Context,
    emit_ast: Annotated[
        bool,
        typer.Option(
            _EMIT_AST_FLAG,
            help="Emit Parquet datasets with AST nodes and metrics.",
        ),
    ] = DEFAULT_EMIT_AST,
) -> None:
    """Backward-compatible alias for ``all``."""
    typer.echo("[scan] Deprecated alias for `all`; running full pipeline.")
    run_all(ctx, emit_ast=emit_ast)


@_command("exports")
def exports(ctx: typer.Context) -> None:
    """Emit modules.jsonl, repo map, tag index, and Markdown module sheets."""
    result, state = _execute_pipeline(ctx)
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


@_command("graph")
def graph(ctx: typer.Context) -> None:
    """Emit symbol and import graph artifacts."""
    result, state = _execute_pipeline(ctx)
    _write_graph_outputs(result, state.pipeline.out)
    typer.echo("[graph] Wrote symbol and import graphs.")


@_command("uses")
def uses(ctx: typer.Context) -> None:
    """Emit the definition-to-use graph derived from SCIP."""
    result, state = _execute_pipeline(ctx)
    _write_uses_output(result, state.pipeline.out)
    typer.echo("[uses] Wrote uses graph.")


@_command("typedness")
def typedness(ctx: typer.Context) -> None:
    """Emit typedness analytics (errors, annotation ratios, untyped defs)."""
    result, state = _execute_pipeline(ctx)
    _write_typedness_output(result, state.pipeline.out)
    typer.echo("[typedness] Wrote typedness analytics.")


@_command("doc")
def doc(ctx: typer.Context) -> None:
    """Emit doc health analytics for module docstrings."""
    result, state = _execute_pipeline(ctx)
    _write_doc_output(result, state.pipeline.out)
    typer.echo("[doc] Wrote doc health analytics.")


@_command("coverage")
def coverage(ctx: typer.Context) -> None:
    """Emit coverage analytics table."""
    result, state = _execute_pipeline(ctx)
    _write_coverage_output(result, state.pipeline.out)
    typer.echo("[coverage] Wrote coverage analytics.")


@_command("config")
def config(ctx: typer.Context) -> None:
    """Emit config index (YAML/TOML/JSON/Markdown references)."""
    result, state = _execute_pipeline(ctx)
    _write_config_output(result, state.pipeline.out)
    typer.echo("[config] Wrote config index.")


@_command("hotspots")
def hotspots(ctx: typer.Context) -> None:
    """Emit hotspot analytics (complexity x churn x centrality)."""
    result, state = _execute_pipeline(ctx)
    _write_hotspot_output(result, state.pipeline.out)
    typer.echo("[hotspots] Wrote hotspot analytics.")


@_command("overlays")
def overlays(
    ctx: typer.Context,
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--overlays-config",
            help="Path to a YAML/JSON file describing overlay settings.",
        ),
    ] = None,
    overrides: Annotated[
        list[str],
        typer.Option(
            "--set",
            "-s",
            help="Override overlay settings as KEY=VALUE entries (repeatable).",
        ),
    ] = (),
) -> None:
    """Generate targeted overlays and optionally activate them into the stub path."""
    state = _ensure_state(ctx)
    pipeline = state.pipeline
    if pipeline.scip is None:
        raise typer.BadParameter("The --scip option is required for overlay generation.")
    options = _load_overlay_options(config_path, list(overrides))
    root_resolved = pipeline.root.resolve()
    package_name = root_resolved.name
    overlays_target_root = (options.overlays_root / package_name).resolve()
    stubs_target_root = (options.stubs_root / package_name).resolve()
    overlays_target_root.mkdir(parents=True, exist_ok=True)
    stubs_target_root.parent.mkdir(parents=True, exist_ok=True)

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
    )

    removed = 0
    if options.deactivate_all_first:
        removed = deactivate_all(overlays_root=overlays_target_root, stubs_root=stubs_target_root)

    generated: list[str] = []
    generated_set: set[str] = set()
    manifest_entries: list[str] = []
    package_overlays: set[str] = set()
    for fp in _iter_files(root_resolved):
        rel = _normalized_rel_path(fp, root_resolved)
        result = generate_overlay_for_file(
            py_file=fp,
            package_root=root_resolved,
            scip=scip_index,
            policy=policy,
            type_error_counts=type_counts,
        )
        if result.created and rel not in generated_set:
            generated.append(rel)
            generated_set.add(rel)
            manifest_entries.append(f"{package_name}/{rel}")
            if len(generated) >= policy.max_overlays or _ensure_package_overlays(
                rel_path=Path(rel),
                generated=generated,
                generated_set=generated_set,
                manifest_entries=manifest_entries,
                package_name=package_name,
                package_overlays=package_overlays,
                root=root_resolved,
                scip_index=scip_index,
                policy=policy,
                type_error_counts=type_counts,
            ):
                break
        if len(generated) >= policy.max_overlays:
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
            overlays_root=overlays_target_root,
            stubs_root=stubs_target_root,
        )
        typer.echo(f"[overlays] Activated {activated} overlays into {options.stubs_root}.")

    manifest_path = overlays_target_root / "overlays_manifest.json"
    write_json(
        manifest_path,
        {
            "package": package_name,
            "generated": manifest_entries,
            "removed": removed,
            "activated": bool(options.activate and generated),
        },
    )
    typer.echo(f"[overlays] Manifest written to {manifest_path}")


def _build_module_row(
    fp: Path,
    root: Path,
    inputs: ScanInputs,
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    rel = _normalized_rel_path(fp, root)
    repo_path = _normalized_rel_path(fp, inputs.repo_root)
    stable_id = stable_id_for_path(repo_path)
    scip_symbols, symbol_edges = _scip_symbols_and_edges(rel, inputs)

    try:
        file_size = fp.stat().st_size
    except OSError:
        file_size = None

    if file_size is not None and file_size > inputs.max_file_bytes:
        row = {
            "path": rel,
            "repo_path": repo_path,
            "module_name": module_name_from_path(inputs.repo_root, fp, inputs.package_prefix),
            "stable_id": stable_id,
            "docstring": None,
            "doc_has_summary": False,
            "doc_param_parity": True,
            "doc_examples_present": False,
            "imports": [],
            "defs": [],
            "exports": [],
            "exports_declared": [],
            "outline_nodes": [],
            "scip_symbols": scip_symbols,
            "parse_ok": False,
            "errors": [
                f"file-too-large>{file_size}>{inputs.max_file_bytes}",
            ],
            "tags": [],
            "type_errors": 0,
            "type_error_count": 0,
            "doc_summary": None,
            "doc_metrics": {
                "has_summary": False,
                "param_parity": True,
                "examples_present": False,
            },
            "doc_items": [],
            "annotation_ratio": {"params": 1.0, "returns": 1.0},
            "untyped_defs": 0,
        }
        return row, symbol_edges

    code = fp.read_text(encoding="utf-8", errors="ignore")
    idx = index_module(rel, code)
    outline_nodes = _outline_nodes_for(rel, code)

    type_errors = _type_error_count(rel, inputs)

    row = {
        "path": rel,
        "repo_path": repo_path,
        "module_name": module_name_from_path(inputs.repo_root, fp, inputs.package_prefix),
        "stable_id": stable_id,
        "docstring": idx.docstring,
        "doc_has_summary": bool(idx.doc_metrics.get("has_summary")),
        "doc_param_parity": bool(idx.doc_metrics.get("param_parity")),
        "doc_examples_present": bool(idx.doc_metrics.get("examples_present")),
        "imports": [
            {
                "module": entry.module,
                "names": entry.names,
                "aliases": entry.aliases,
                "is_star": entry.is_star,
                "level": entry.level,
            }
            for entry in idx.imports
        ],
        "defs": [{"kind": d.kind, "name": d.name, "lineno": d.lineno} for d in idx.defs],
        "exports": sorted(idx.exports),
        "exports_declared": sorted(idx.exports),
        "outline_nodes": outline_nodes,
        "scip_symbols": scip_symbols,
        "parse_ok": idx.parse_ok,
        "errors": idx.errors,
        "tags": [],
        "type_errors": type_errors,
        "type_error_count": type_errors,
        "doc_summary": idx.doc_summary,
        "doc_metrics": idx.doc_metrics,
        "doc_items": idx.doc_items,
        "annotation_ratio": idx.annotation_ratio,
        "untyped_defs": idx.untyped_defs,
        "side_effects": idx.side_effects,
        "raises": idx.raises,
        "complexity": idx.complexity,
        "covered_lines_ratio": _coverage_value(rel, inputs, "covered_lines_ratio"),
        "covered_defs_ratio": _coverage_value(rel, inputs, "covered_defs_ratio"),
        "config_refs": [],
        "overlay_needed": False,
    }
    return row, symbol_edges


def _scip_symbols_and_edges(
    rel_path: str,
    inputs: ScanInputs,
) -> tuple[list[str], list[tuple[str, str]]]:
    document = inputs.scip_ctx.by_file.get(rel_path)
    symbols = sorted(
        {symbol.symbol for symbol in (document.symbols if document else []) if symbol.symbol}
    )
    return symbols, [(symbol, rel_path) for symbol in symbols]


def _outline_nodes_for(rel_path: str, code: str) -> list[dict[str, Any]]:
    outline = build_outline(rel_path, code.encode("utf-8"))
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
    module_rows: list[dict[str, Any]],
    scip_index: SCIPIndex,
    package_prefix: str | None,
    *,
    config_records: list[dict[str, Any]] | None = None,
) -> tuple[ImportGraph, UseGraph, list[dict[str, Any]]]:
    """Attach graph/usage/export metadata and emit module artifacts.

    Parameters
    ----------
    module_rows : list[dict[str, Any]]
        Module metadata rows to augment with graph and export information.
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
        path = row["path"]
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
            tags = set(row.get("tags", []))
            tags.add("overlay-needed")
            row["tags"] = sorted(tags)
        row["hotspot_score"] = compute_hotspot_score(row)
    for record in config_records:
        referenced = config_references.get(record["path"], set())
        record["references"] = sorted(referenced)
    return import_graph, use_graph, config_records


def _build_tag_index(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
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


def _apply_tagging(rows: list[dict[str, Any]], rules: Mapping[str, Any]) -> None:
    """Apply tagging rules to module rows and update their tags in-place.

    Parameters
    ----------
    rows : list[dict[str, Any]]
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


def _build_coverage_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": row.get("path"),
            "covered_lines_ratio": float(row.get("covered_lines_ratio") or 0.0),
            "covered_defs_ratio": float(row.get("covered_defs_ratio") or 0.0),
        }
        for row in rows
    ]


def _build_hotspot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    _write_modules_json(out, result.module_rows)
    _write_markdown_modules(out, result.module_rows)
    _write_repo_map(out, result)
    _write_tag_index(out, result.tag_index)


def _write_graph_outputs(result: PipelineResult, out: Path) -> None:
    _write_symbol_graph(out, result.symbol_edges)
    write_import_graph(result.import_graph, out / "graphs" / "imports.parquet")


def _write_uses_output(result: PipelineResult, out: Path) -> None:
    write_use_graph(result.use_graph, out / "graphs" / "uses.parquet")


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
    module_rows: list[dict[str, Any]],
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


def _write_modules_json(out: Path, module_rows: list[dict[str, Any]]) -> None:
    write_jsonl(out / "modules" / "modules.jsonl", module_rows)


def _write_markdown_modules(out: Path, module_rows: list[dict[str, Any]]) -> None:
    modules_dir = out / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)
    for row in module_rows:
        path = row.get("path")
        if not isinstance(path, str):
            continue
        target = modules_dir / (Path(path).with_suffix(".md").name)
        write_markdown_module(target, row)


def _write_repo_map(out: Path, result: PipelineResult) -> None:
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
        },
    )


def _write_symbol_graph(out: Path, symbol_edges: list[tuple[str, str]]) -> None:
    write_json(
        out / "graphs" / "symbol_graph.json",
        [{"symbol": symbol, "file": rel} for symbol, rel in symbol_edges],
    )


def _write_tabular_records(parquet_path: Path, rows: list[dict[str, Any]]) -> None:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    if pl is not None and rows:
        pl.DataFrame(rows).write_parquet(parquet_path)
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


# lint-ignore: PLR0913 helper wires overlay paths atomically
def _ensure_package_overlays(  # noqa: PLR0913
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
            scip=scip_index,
            policy=policy,
            type_error_counts=type_error_counts,
            force=True,
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
