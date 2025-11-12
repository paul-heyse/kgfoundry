# SPDX-License-Identifier: MIT
"""CLI entrypoint for repo enrichment and targeted overlay generation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from codeintel_rev.enrich.libcst_bridge import index_module
from codeintel_rev.enrich.output_writers import write_json, write_jsonl, write_markdown_module
from codeintel_rev.enrich.scip_reader import Document, SCIPIndex
from codeintel_rev.enrich.stitch import stitch_records
from codeintel_rev.enrich.stubs_overlay import (
    OverlayPolicy,
    activate_overlays,
    deactivate_all,
    generate_overlay_for_file,
)
from codeintel_rev.enrich.tagging import ModuleTraits, infer_tags, load_rules
from codeintel_rev.enrich.tree_sitter_bridge import build_outline
from codeintel_rev.enrich.type_integration import TypeSummary, collect_pyrefly, collect_pyright

try:  # pragma: no cover - optional dependency
    import yaml as yaml_module  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
    yaml_module = None  # type: ignore[assignment]

EXPORT_HUB_THRESHOLD = 10

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


@dataclass(slots=True, frozen=True)
class ModuleRecord:
    """Serializable row stored in modules.jsonl."""

    path: str
    docstring: str | None
    imports: list[dict[str, Any]]
    defs: list[dict[str, Any]]
    exports: list[str]
    outline_nodes: list[dict[str, Any]]
    scip_symbols: list[str]
    parse_ok: bool
    errors: list[str]
    tags: list[str]
    type_errors: int


@dataclass(frozen=True)
class ScipContext:
    """Cache of SCIP lookups used during scanning."""

    index: SCIPIndex
    by_file: Mapping[str, Document]


@dataclass(frozen=True)
class TypeSignals:
    """Pyright/Pyrefly summaries."""

    pyright: TypeSummary | None
    pyrefly: TypeSummary | None


def _iter_files(root: Path) -> Iterable[Path]:
    for candidate in root.rglob("*.py"):
        if any(part.startswith(".") for part in candidate.parts):
            continue
        yield candidate


@app.command("scan")
def scan(
    root: Path = ROOT,
    scip: Path = SCIP,
    out: Path = OUT,
    pyrefly_json: Path | None = PYREFLY,
    tags_yaml: Path | None = TAGS,
) -> None:
    """Build LibCST/SCIP/type-signal enriched artifacts."""
    out.mkdir(parents=True, exist_ok=True)
    scip_index = SCIPIndex.load(scip)
    scip_ctx = ScipContext(index=scip_index, by_file=scip_index.by_file())

    type_signals = TypeSignals(
        pyright=collect_pyright(str(root)),
        pyrefly=collect_pyrefly(str(pyrefly_json) if pyrefly_json else None),
    )
    rules = load_rules(str(tags_yaml) if tags_yaml else None)

    module_rows: list[dict[str, Any]] = []
    symbol_edges: list[tuple[str, str]] = []
    tag_index: dict[str, list[str]] = {}

    for fp in _iter_files(root):
        row_dict, edges = _build_module_row(fp, root, scip_ctx, type_signals, rules)
        module_rows.append(row_dict)
        symbol_edges.extend(edges)
        for tag in row_dict["tags"]:
            tag_index.setdefault(tag, []).append(row_dict["path"])
    module_rows = stitch_records(module_rows, scip_index, package_prefix=root.name)
    for row in module_rows:
        write_markdown_module(
            out / "modules" / (Path(row["path"]).with_suffix(".md").name),
            row,
        )

    write_jsonl(out / "modules" / "modules.jsonl", module_rows)
    write_json(
        out / "graphs" / "symbol_graph.json",
        [{"symbol": symbol, "file": rel} for symbol, rel in symbol_edges],
    )
    write_json(
        out / "repo_map.json",
        {
            "root": str(root),
            "module_count": len(module_rows),
            "symbol_edge_count": len(symbol_edges),
            "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
            "tags": tag_index,
        },
    )
    _write_tag_index(out, tag_index)
    typer.echo(f"[scan] Wrote {len(module_rows)} module rows to {out}")


@app.command("overlays")
def overlays(  # noqa: PLR0913, PLR0914, C901 - CLI surface intentionally exposes many knobs
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

    type_counts: dict[str, int] = {}
    type_signals = TypeSignals(
        pyright=collect_pyright(str(root)),
        pyrefly=collect_pyrefly(str(pyrefly_json) if pyrefly_json else None),
    )
    for summary in (type_signals.pyrefly, type_signals.pyright):
        if not summary:
            continue
        for file_path, record in summary.by_file.items():
            _register_type_count(type_counts, file_path, record.error_count, root_resolved)

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
    scip_ctx: ScipContext,
    type_signals: TypeSignals,
    rules: Mapping[str, Any],
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

    imported_modules = [entry.module for entry in idx.imports if entry.module]
    imported_modules.extend(
        name for entry in idx.imports if entry.module is None for name in entry.names
    )
    is_reexport_hub = (
        any(entry.is_star for entry in idx.imports) or len(idx.exports) >= EXPORT_HUB_THRESHOLD
    )

    type_errors = _max_type_errors(rel, type_signals)

    traits = ModuleTraits(
        imported_modules=imported_modules,
        has_all=bool(idx.exports),
        is_reexport_hub=is_reexport_hub,
        type_error_count=type_errors,
    )
    tagging = infer_tags(path=rel, traits=traits, rules=rules)

    scip_doc = scip_ctx.by_file.get(rel)
    scip_symbols = sorted(
        {symbol.symbol for symbol in (scip_doc.symbols if scip_doc else []) if symbol.symbol}
    )
    symbol_edges = [(symbol, rel) for symbol in scip_symbols]

    row = ModuleRecord(
        path=rel,
        docstring=idx.docstring,
        imports=[
            {
                "module": entry.module,
                "names": entry.names,
                "aliases": entry.aliases,
                "is_star": entry.is_star,
                "level": entry.level,
            }
            for entry in idx.imports
        ],
        defs=[{"kind": d.kind, "name": d.name, "lineno": d.lineno} for d in idx.defs],
        exports=sorted(idx.exports),
        outline_nodes=outline_nodes,
        scip_symbols=scip_symbols,
        parse_ok=idx.parse_ok,
        errors=idx.errors,
        tags=sorted(tagging.tags),
        type_errors=type_errors,
    )
    return asdict(row), symbol_edges


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


def _max_type_errors(rel: str, type_signals: TypeSignals) -> int:
    max_errors = 0
    if type_signals.pyrefly and rel in type_signals.pyrefly.by_file:
        max_errors = type_signals.pyrefly.by_file[rel].error_count
    if type_signals.pyright and rel in type_signals.pyright.by_file:
        max_errors = max(max_errors, type_signals.pyright.by_file[rel].error_count)
    return max_errors


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


def _register_type_count(
    mapping: MutableMapping[str, int],
    file_path: str,
    count: int,
    root: Path,
) -> None:
    candidates = {file_path.replace("\\", "/")}
    try:
        rel = Path(file_path).resolve().relative_to(root)
        candidates.add(str(rel).replace("\\", "/"))
    except (ValueError, FileNotFoundError):
        pass
    for key in candidates:
        mapping[key] = max(mapping.get(key, 0), count)


if __name__ == "__main__":
    app()
