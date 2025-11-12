# SPDX-License-Identifier: MIT
"""CLI entrypoint for repo enrichment and targeted overlay generation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Annotated, Any

try:  # pragma: no cover - optional dependency
    import polars as pl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
    pl = None  # type: ignore[assignment]

import typer

from codeintel_rev.config_indexer import index_config_files
from codeintel_rev.coverage_ingest import collect_coverage
from codeintel_rev.enrich.libcst_bridge import index_module
from codeintel_rev.enrich.output_writers import write_json, write_jsonl, write_markdown_module
from codeintel_rev.enrich.scip_reader import Document, SCIPIndex
from codeintel_rev.enrich.stubs_overlay import (
    OverlayPolicy,
    activate_overlays,
    deactivate_all,
    generate_overlay_for_file,
)
from codeintel_rev.enrich.tagging import ModuleTraits, infer_tags, load_rules
from codeintel_rev.enrich.tree_sitter_bridge import build_outline
from codeintel_rev.export_resolver import build_module_name_map, resolve_exports
from codeintel_rev.graph_builder import ImportGraph, build_import_graph, write_import_graph
from codeintel_rev.risk_hotspots import compute_hotspot_score
from codeintel_rev.typedness import FileTypeSignals, collect_type_signals
from codeintel_rev.uses_builder import UseGraph, build_use_graph, write_use_graph

try:  # pragma: no cover - optional dependency
    import yaml as yaml_module  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
    yaml_module = None  # type: ignore[assignment]

EXPORT_HUB_THRESHOLD = 10
OVERLAY_PARAM_THRESHOLD = 0.8
OVERLAY_FAN_IN_THRESHOLD = 3
OVERLAY_ERROR_THRESHOLD = 5

ROOT = typer.Option(Path(), "--root", help="Repo or subfolder to scan.")
SCIP = typer.Option(..., "--scip", exists=True, help="Path to SCIP index.json")
OUT = typer.Option(
    Path("codeintel_rev/io/ENRICHED"),
    "--out",
    help="Output directory for enrichment artifacts.",
)
PYREFLY = typer.Option(
    None,
    "--pyrefly-json",
    help="Optional path to a Pyrefly JSON/JSONL report.",
)
TAGS = typer.Option(None, "--tags-yaml", help="Optional tagging rules YAML.")
COVERAGE_XML = typer.Option(
    Path("coverage.xml"),
    "--coverage-xml",
    help="Optional path to coverage XML (Cobertura format).",
)
OnlyPatternsOption = Annotated[
    list[str] | None,
    typer.Option(
        "--only",
        help="Glob patterns (repeatable) limiting modules relative to --root.",
    ),
]

DEFAULT_MIN_ERRORS = 25
DEFAULT_MAX_OVERLAYS = 200
DEFAULT_INCLUDE_PUBLIC_DEFS = False
DEFAULT_INJECT_GETATTR_ANY = True
DEFAULT_DRY_RUN = False
DEFAULT_ACTIVATE = True
DEFAULT_DEACTIVATE = False
DEFAULT_USE_TYPE_ERROR_OVERLAYS = False

STUBS = typer.Option(
    Path("stubs"),
    "--stubs",
    help="Pyright stubPath root (matches pyrightconfig.json).",
)
OVERLAYS_ROOT = typer.Option(
    Path("stubs/overlays"),
    "--overlays-root",
    help="Directory for generated overlays.",
)
MIN_ERRORS = typer.Option(
    DEFAULT_MIN_ERRORS,
    "--min-errors",
    help="Generate overlays when a module has at least this many type errors.",
)
MAX_OVERLAYS = typer.Option(
    DEFAULT_MAX_OVERLAYS,
    "--max-overlays",
    help="Maximum overlays to generate in one run.",
)
INCLUDE_PUBLIC_DEFS = typer.Option(
    DEFAULT_INCLUDE_PUBLIC_DEFS,
    "--include-public-defs/--no-include-public-defs",
    help="Include placeholder defs/classes in overlays.",
)
INJECT_GETATTR_ANY = typer.Option(
    DEFAULT_INJECT_GETATTR_ANY,
    "--inject-getattr-any/--no-inject-getattr-any",
    help="Inject def __getattr__(name: str) -> Any.",
)
DRY_RUN = typer.Option(
    DEFAULT_DRY_RUN,
    "--dry-run/--no-dry-run",
    help="Plan overlay actions without writing files.",
)
ACTIVATE = typer.Option(
    DEFAULT_ACTIVATE,
    "--activate/--no-activate",
    help="Activate overlays into --stubs via symlink/copy.",
)
DEACTIVATE = typer.Option(
    DEFAULT_DEACTIVATE,
    "--deactivate-all/--no-deactivate-all",
    help="Remove previously activated overlays before generating new ones.",
)
TYPE_ERROR_OVERLAYS = typer.Option(
    DEFAULT_USE_TYPE_ERROR_OVERLAYS,
    "--type-error-overlays/--no-type-error-overlays",
    help="Allow overlays for modules exceeding --min-errors type error threshold.",
)

app = typer.Typer(add_completion=False, help="Repo enrichment utilities (scan + overlays).")


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


@dataclass(slots=True, frozen=True)
class PipelineResult:
    """Aggregate artifact bundle produced by a pipeline run."""

    root: Path
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


def _run_pipeline(  # noqa: PLR0913, PLR0914
    *,
    root: Path,
    scip: Path,
    pyrefly_json: Path | None,
    tags_yaml: Path | None,
    coverage_xml: Path,
    only: list[str] | None,
) -> PipelineResult:
    root_resolved = root.resolve()
    scip_index = SCIPIndex.load(scip)
    scip_ctx = ScipContext(index=scip_index, by_file=scip_index.by_file())

    type_signal_lookup = _normalize_type_signal_map(
        collect_type_signals(
            pyrefly_report=str(pyrefly_json) if pyrefly_json else None,
            pyright_json=str(root_resolved),
        ),
        root_resolved,
    )
    coverage_lookup = _normalize_metric_map(
        collect_coverage(coverage_xml) if coverage_xml else {},
        root_resolved,
    )
    config_records = index_config_files(root_resolved)
    rules = load_rules(str(tags_yaml) if tags_yaml else None)

    scan_inputs = ScanInputs(
        scip_ctx=scip_ctx,
        type_signals=type_signal_lookup,
        coverage_map=coverage_lookup,
        tagging_rules=rules,
    )
    module_rows: list[dict[str, Any]] = []
    symbol_edges: list[tuple[str, str]] = []
    only_patterns = tuple(only or ())

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
        module_rows=module_rows,
        symbol_edges=symbol_edges,
        import_graph=import_graph,
        use_graph=use_graph,
        config_index=config_index,
        coverage_rows=coverage_rows,
        hotspot_rows=hotspot_rows,
        tag_index=tag_index,
    )


@app.command("all")
def run_all(  # noqa: PLR0913, PLR0917 - CLI surface exposes multiple knobs
    root: Path = ROOT,
    scip: Path = SCIP,
    out: Path = OUT,
    pyrefly_json: Path | None = PYREFLY,
    tags_yaml: Path | None = TAGS,
    coverage_xml: Path = COVERAGE_XML,
    only: OnlyPatternsOption = None,
) -> None:
    """Run the full enrichment pipeline and emit all artifacts."""
    out.mkdir(parents=True, exist_ok=True)
    result = _run_pipeline(
        root=root,
        scip=scip,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
    )
    _write_exports_outputs(result, out)
    _write_graph_outputs(result, out)
    _write_uses_output(result, out)
    _write_typedness_output(result, out)
    _write_doc_output(result, out)
    _write_coverage_output(result, out)
    _write_config_output(result, out)
    _write_hotspot_output(result, out)
    typer.echo(f"[all] Completed enrichment for {len(result.module_rows)} modules.")


@app.command("scan")
def scan(  # noqa: PLR0913, PLR0917
    root: Path = ROOT,
    scip: Path = SCIP,
    out: Path = OUT,
    pyrefly_json: Path | None = PYREFLY,
    tags_yaml: Path | None = TAGS,
    coverage_xml: Path = COVERAGE_XML,
    only: OnlyPatternsOption = None,
) -> None:
    """Backward-compatible alias for ``all``."""
    typer.echo("[scan] Deprecated alias for `all`; running full pipeline.")
    run_all(
        root=root,
        scip=scip,
        out=out,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
    )


@app.command("exports")
def exports(  # noqa: PLR0913, PLR0917
    root: Path = ROOT,
    scip: Path = SCIP,
    out: Path = OUT,
    pyrefly_json: Path | None = PYREFLY,
    tags_yaml: Path | None = TAGS,
    coverage_xml: Path = COVERAGE_XML,
    only: OnlyPatternsOption = None,
) -> None:
    """Emit modules.jsonl, repo map, tag index, and Markdown module sheets."""
    out.mkdir(parents=True, exist_ok=True)
    result = _run_pipeline(
        root=root,
        scip=scip,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
    )
    _write_exports_outputs(result, out)
    typer.echo(f"[exports] Wrote module artifacts for {len(result.module_rows)} modules.")


@app.command("graph")
def graph(  # noqa: PLR0913, PLR0917
    root: Path = ROOT,
    scip: Path = SCIP,
    out: Path = OUT,
    pyrefly_json: Path | None = PYREFLY,
    tags_yaml: Path | None = TAGS,
    coverage_xml: Path = COVERAGE_XML,
    only: OnlyPatternsOption = None,
) -> None:
    """Emit symbol and import graph artifacts."""
    out.mkdir(parents=True, exist_ok=True)
    result = _run_pipeline(
        root=root,
        scip=scip,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
    )
    _write_graph_outputs(result, out)
    typer.echo("[graph] Wrote symbol and import graphs.")


@app.command("uses")
def uses(  # noqa: PLR0913, PLR0917
    root: Path = ROOT,
    scip: Path = SCIP,
    out: Path = OUT,
    pyrefly_json: Path | None = PYREFLY,
    tags_yaml: Path | None = TAGS,
    coverage_xml: Path = COVERAGE_XML,
    only: OnlyPatternsOption = None,
) -> None:
    """Emit the definition-to-use graph derived from SCIP."""
    out.mkdir(parents=True, exist_ok=True)
    result = _run_pipeline(
        root=root,
        scip=scip,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
    )
    _write_uses_output(result, out)
    typer.echo("[uses] Wrote uses graph.")


@app.command("typedness")
def typedness(  # noqa: PLR0913, PLR0917
    root: Path = ROOT,
    scip: Path = SCIP,
    out: Path = OUT,
    pyrefly_json: Path | None = PYREFLY,
    tags_yaml: Path | None = TAGS,
    coverage_xml: Path = COVERAGE_XML,
    only: OnlyPatternsOption = None,
) -> None:
    """Emit typedness analytics (errors, annotation ratios, untyped defs)."""
    out.mkdir(parents=True, exist_ok=True)
    result = _run_pipeline(
        root=root,
        scip=scip,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
    )
    _write_typedness_output(result, out)
    typer.echo("[typedness] Wrote typedness analytics.")


@app.command("doc")
def doc(  # noqa: PLR0913, PLR0917
    root: Path = ROOT,
    scip: Path = SCIP,
    out: Path = OUT,
    pyrefly_json: Path | None = PYREFLY,
    tags_yaml: Path | None = TAGS,
    coverage_xml: Path = COVERAGE_XML,
    only: OnlyPatternsOption = None,
) -> None:
    """Emit doc health analytics for module docstrings."""
    out.mkdir(parents=True, exist_ok=True)
    result = _run_pipeline(
        root=root,
        scip=scip,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
    )
    _write_doc_output(result, out)
    typer.echo("[doc] Wrote doc health analytics.")


@app.command("coverage")
def coverage(  # noqa: PLR0913, PLR0917
    root: Path = ROOT,
    scip: Path = SCIP,
    out: Path = OUT,
    pyrefly_json: Path | None = PYREFLY,
    tags_yaml: Path | None = TAGS,
    coverage_xml: Path = COVERAGE_XML,
    only: OnlyPatternsOption = None,
) -> None:
    """Emit coverage analytics table."""
    out.mkdir(parents=True, exist_ok=True)
    result = _run_pipeline(
        root=root,
        scip=scip,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
    )
    _write_coverage_output(result, out)
    typer.echo("[coverage] Wrote coverage analytics.")


@app.command("config")
def config(  # noqa: PLR0913, PLR0917
    root: Path = ROOT,
    scip: Path = SCIP,
    out: Path = OUT,
    pyrefly_json: Path | None = PYREFLY,
    tags_yaml: Path | None = TAGS,
    coverage_xml: Path = COVERAGE_XML,
    only: OnlyPatternsOption = None,
) -> None:
    """Emit config index (YAML/TOML/JSON/Markdown references)."""
    out.mkdir(parents=True, exist_ok=True)
    result = _run_pipeline(
        root=root,
        scip=scip,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
    )
    _write_config_output(result, out)
    typer.echo("[config] Wrote config index.")


@app.command("hotspots")
def hotspots(  # noqa: PLR0913, PLR0917
    root: Path = ROOT,
    scip: Path = SCIP,
    out: Path = OUT,
    pyrefly_json: Path | None = PYREFLY,
    tags_yaml: Path | None = TAGS,
    coverage_xml: Path = COVERAGE_XML,
    only: OnlyPatternsOption = None,
) -> None:
    """Emit hotspot analytics (complexity x churn x centrality)."""
    out.mkdir(parents=True, exist_ok=True)
    result = _run_pipeline(
        root=root,
        scip=scip,
        pyrefly_json=pyrefly_json,
        tags_yaml=tags_yaml,
        coverage_xml=coverage_xml,
        only=only,
    )
    _write_hotspot_output(result, out)
    typer.echo("[hotspots] Wrote hotspot analytics.")


@app.command("overlays")
def overlays(  # noqa: PLR0913, PLR0914 - CLI surface intentionally exposes many knobs
    root: Path = ROOT,
    scip: Path = SCIP,
    pyrefly_json: Path | None = PYREFLY,
    *,
    stubs_root: Path = STUBS,
    overlays_root: Path = OVERLAYS_ROOT,
    min_errors: int = MIN_ERRORS,
    max_overlays: int = MAX_OVERLAYS,
    include_public_defs: bool = INCLUDE_PUBLIC_DEFS,
    inject_getattr_any: bool = INJECT_GETATTR_ANY,
    dry_run: bool = DRY_RUN,
    activate: bool = ACTIVATE,
    deactivate_all_first: bool = DEACTIVATE,
    type_error_overlays: bool = TYPE_ERROR_OVERLAYS,
) -> None:
    """Generate targeted overlays and optionally activate them into the stub path."""
    root_resolved = root.resolve()
    package_name = root_resolved.name
    overlays_target_root = (overlays_root / package_name).resolve()
    stubs_target_root = (stubs_root / package_name).resolve()
    overlays_target_root.mkdir(parents=True, exist_ok=True)
    stubs_target_root.parent.mkdir(parents=True, exist_ok=True)

    scip_index = SCIPIndex.load(scip)

    type_signal_lookup = _normalize_type_signal_map(
        collect_type_signals(
            pyrefly_report=str(pyrefly_json) if pyrefly_json else None,
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
        include_public_defs=include_public_defs,
        inject_module_getattr_any=inject_getattr_any,
        when_type_errors=type_error_overlays,
        min_type_errors=min_errors,
        max_overlays=max_overlays,
    )

    removed = 0
    if deactivate_all_first:
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

    if dry_run:
        typer.echo(
            f"[overlays] DRY RUN: would generate {len(generated)} overlays (removed {removed})."
        )
        return

    typer.echo(
        f"[overlays] Generated {len(generated)} overlays into {overlays_root} (removed {removed})."
    )
    if activate and generated:
        activated = activate_overlays(
            generated,
            overlays_root=overlays_target_root,
            stubs_root=stubs_target_root,
        )
        typer.echo(f"[overlays] Activated {activated} overlays into {stubs_root}.")

    manifest_path = overlays_target_root / "overlays_manifest.json"
    write_json(
        manifest_path,
        {
            "package": package_name,
            "generated": manifest_entries,
            "removed": removed,
            "activated": bool(activate and generated),
        },
    )
    typer.echo(f"[overlays] Manifest written to {manifest_path}")


def _build_module_row(
    fp: Path,
    root: Path,
    inputs: ScanInputs,
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    rel = _normalized_rel_path(fp, root)
    code = fp.read_text(encoding="utf-8", errors="ignore")
    idx = index_module(rel, code)

    outline = build_outline(rel, code.encode("utf-8"))
    outline_nodes = []
    if outline:
        outline_nodes.extend(
            {
                "kind": node.kind,
                "name": node.name,
                "start": node.start_byte,
                "end": node.end_byte,
            }
            for node in outline.nodes
        )

    type_signal = inputs.type_signals.get(rel)
    type_errors = type_signal.total if type_signal else 0

    coverage_entry = inputs.coverage_map.get(rel, {})

    scip_doc = inputs.scip_ctx.by_file.get(rel)
    scip_symbols = sorted(
        {symbol.symbol for symbol in (scip_doc.symbols if scip_doc else []) if symbol.symbol}
    )
    symbol_edges = [(symbol, rel) for symbol in scip_symbols]

    row = {
        "path": rel,
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
        "covered_lines_ratio": float(coverage_entry.get("covered_lines_ratio", 0.0)),
        "covered_defs_ratio": float(coverage_entry.get("covered_defs_ratio", 0.0)),
        "config_refs": [],
        "overlay_needed": False,
    }
    return row, symbol_edges


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
        pl.DataFrame(rows).write_parquet(parquet_path)  # type: ignore[attr-defined]
    write_jsonl(parquet_path.with_suffix(".jsonl"), rows)


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
    return str(path.relative_to(root)).replace("\\", "/")


def _write_tag_index(out: Path, tag_index: Mapping[str, list[str]]) -> None:
    if yaml_module is None:
        return
    tags_path = out / "tags"
    tags_path.mkdir(parents=True, exist_ok=True)
    (tags_path / "tags_index.yaml").write_text(
        yaml_module.safe_dump(tag_index, sort_keys=True),  # type: ignore[union-attr]
        encoding="utf-8",
    )


if __name__ == "__main__":
    app()
