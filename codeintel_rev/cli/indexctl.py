"""Typer CLI for managing index lifecycle operations."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

import click
import typer

from codeintel_rev.config.settings import Settings, load_settings
from codeintel_rev.eval.hybrid_evaluator import HybridPoolEvaluator
from codeintel_rev.indexing.index_lifecycle import IndexAssets, IndexLifecycleManager
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.faiss_manager import FAISSManager
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)
app = typer.Typer(help="Manage versioned FAISS/DuckDB/SCIP assets.", no_args_is_help=True)


@lru_cache(maxsize=1)
def _get_settings() -> Settings:
    """Load settings once and reuse for subsequent commands.

    Returns
    -------
    Settings
        Cached settings object.
    """
    return load_settings()


RootOption = Annotated[Path | None, typer.Option("--root", help="Index lifecycle root directory.")]
ExtraOption = Annotated[
    list[str],
    typer.Option(
        "--extra",
        help="Optional channel entry of the form name=/path (e.g., bm25=/tmp/bm25).",
        default_factory=list,
    ),
]
VersionArg = Annotated[str, typer.Argument(help="Version identifier.")]
PathArg = Annotated[Path, typer.Argument(help="Path to an asset on disk.")]
IndexOption = Annotated[Path | None, typer.Option("--index", help="Path to FAISS index file.")]
IdMapOption = Annotated[Path, typer.Option("--idmap", help="Path to FAISS ID map Parquet.")]
DuckOption = Annotated[Path | None, typer.Option("--duckdb", help="Path to DuckDB catalog file.")]
OutOption = Annotated[Path | None, typer.Option("--out", help="Output path override.")]


@app.callback()
def global_options(ctx: click.Context, root: RootOption = None) -> None:
    """Configure shared CLI options."""
    ctx.obj = {"root": root}


def _default_root() -> Path:
    env = os.getenv("CODEINTEL_INDEXES_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path("indexes").resolve()


def _resolve_root(ctx: click.Context, explicit_root: Path | None = None) -> Path:
    root_from_ctx = ctx.obj.get("root") if ctx.obj else None
    resolved_root = explicit_root or root_from_ctx or _default_root()
    return resolved_root.resolve()


def _manager(explicit_root: Path | None = None) -> IndexLifecycleManager:
    ctx = click.get_current_context()
    return IndexLifecycleManager(_resolve_root(ctx, explicit_root))


def _build_assets(
    faiss_index: Path,
    duckdb_path: Path,
    scip_index: Path,
    channels: dict[str, Path],
) -> IndexAssets:
    return IndexAssets(
        faiss_index=faiss_index,
        duckdb_path=duckdb_path,
        scip_index=scip_index,
        bm25_dir=channels.get("bm25"),
        splade_dir=channels.get("splade"),
        xtr_dir=channels.get("xtr"),
    )


def _parse_extras(extras: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for entry in extras:
        if "=" not in entry:
            LOGGER.warning("Ignoring malformed --extra entry", extra={"entry": entry})
            continue
        key, value = entry.split("=", maxsplit=1)
        parsed[key.strip().lower()] = Path(value).expanduser().resolve()
    return parsed


def _faiss_manager(index_override: Path | None = None) -> FAISSManager:
    settings = _get_settings()
    index_path = (index_override or Path(settings.paths.faiss_index)).expanduser().resolve()
    nlist = int(settings.index.nlist or settings.index.faiss_nlist)
    manager = FAISSManager(
        index_path=index_path,
        vec_dim=settings.index.vec_dim,
        nlist=nlist,
        use_cuvs=settings.index.use_cuvs,
    )
    manager.load_cpu_index()
    return manager


def _duckdb_catalog(path_override: Path | None = None) -> DuckDBCatalog:
    settings = _get_settings()
    db_path = (path_override or Path(settings.paths.duckdb_path)).expanduser().resolve()
    vectors_dir = Path(settings.paths.vectors_dir).expanduser().resolve()
    catalog = DuckDBCatalog(db_path=db_path, vectors_dir=vectors_dir)
    catalog.set_idmap_path(Path(settings.paths.faiss_idmap_path).expanduser().resolve())
    return catalog


@app.command("status")
def status_command() -> None:
    """Print the active version and available versions."""
    mgr = _manager()
    current = mgr.current_version() or "<none>"
    typer.echo(f"current: {current}")
    for version in mgr.list_versions():
        typer.echo(f"- {version}")


@app.command("stage")
def stage_command(
    version: VersionArg,
    faiss_index: PathArg,
    duckdb_path: PathArg,
    scip_index: PathArg,
    extras: ExtraOption,
) -> None:
    """Stage a new version by copying assets into the lifecycle root."""
    mgr = _manager()
    channels = _parse_extras(list(extras))
    staged_assets = _build_assets(faiss_index, duckdb_path, scip_index, channels)
    staging = mgr.prepare(version, staged_assets)
    typer.echo(f"Staged assets at {staging}")


@app.command("publish")
def publish_command(
    version: VersionArg,
) -> None:
    """Publish a previously staged version."""
    mgr = _manager()
    final_dir = mgr.publish(version)
    typer.echo(f"Published version {version} -> {final_dir}")


@app.command("rollback")
def rollback_command(
    version: VersionArg,
) -> None:
    """Rollback to a previously published version."""
    mgr = _manager()
    mgr.rollback(version)
    typer.echo(f"Rolled back to {version}")


@app.command("ls")
def list_command() -> None:
    """List all published versions."""
    mgr = _manager()
    versions = mgr.list_versions()
    if not versions:
        typer.echo("No versions published")
        return
    for version in versions:
        typer.echo(version)


@app.command("export-idmap")
def export_idmap_command(
    index: IndexOption = None,
    out: OutOption = None,
    duckdb: DuckOption = None,
) -> None:
    """Export FAISS ID map to Parquet and optionally refresh DuckDB materialization."""
    settings = _get_settings()
    manager = _faiss_manager(index)
    destination = (out or Path(settings.paths.faiss_idmap_path)).expanduser().resolve()
    rows = manager.export_idmap(destination)
    typer.echo(f"Exported {rows} FAISS rows -> {destination}")
    if duckdb is not None:
        catalog = _duckdb_catalog(duckdb)
        stats = catalog.refresh_faiss_idmap_mat_if_changed(destination)
        catalog.ensure_faiss_idmap_views(destination)
        typer.echo(
            f"Materialized join rows={stats['rows']} "
            f"checksum={stats['checksum']} refreshed={stats['refreshed']}"
        )


@app.command("materialize-join")
def materialize_join_command(
    idmap: IdMapOption,
    duckdb: DuckOption = None,
) -> None:
    """Refresh DuckDB's materialized FAISS join if the ID map sidecar changed."""
    catalog = _duckdb_catalog(duckdb)
    stats = catalog.refresh_faiss_idmap_mat_if_changed(idmap.expanduser().resolve())
    catalog.ensure_faiss_idmap_views(idmap)
    typer.echo(f"Refreshed={stats['refreshed']} rows={stats['rows']} checksum={stats['checksum']}")


@app.command("tune")
def tune_command(
    index: IndexOption = None,
    nprobe: int | None = typer.Option(None, "--nprobe", help="Override FAISS nprobe."),
    ef_search: int | None = typer.Option(None, "--ef-search", help="Override HNSW efSearch."),
    quantizer_ef_search: int | None = typer.Option(
        None,
        "--quantizer-ef-search",
        help="Override quantizer efSearch when available.",
    ),
    k_factor: float | None = typer.Option(
        None,
        "--k-factor",
        help="Candidate expansion factor for runtime refine.",
    ),
    params: str | None = typer.Option(
        None,
        "--params",
        help="FAISS ParameterSpace string (e.g. 'nprobe=64,efSearch=128,k_factor=2').",
    ),
) -> None:
    """Apply runtime tuning overrides (nprobe/efSearch/k-factor) and persist audit JSON."""
    manager = _faiss_manager(index)
    if params:
        if any(v is not None for v in (nprobe, ef_search, quantizer_ef_search, k_factor)):
            raise typer.BadParameter(
                "Cannot combine --params with individual tuning flags (nprobe/ef-search/etc.)."
            )
        try:
            tuning = manager.set_search_parameters(params)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    else:
        tuning = manager.apply_runtime_tuning(
            nprobe=nprobe,
            ef_search=ef_search,
            quantizer_ef_search=quantizer_ef_search,
            k_factor=k_factor,
        )
    audit_path = manager.index_path.with_suffix(".audit.json").expanduser().resolve()
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(tuning, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"Wrote runtime tuning snapshot -> {audit_path}")


@app.command("eval-hybrid")
def eval_hybrid_command(
    *,
    k: int = typer.Option(10, "--k", min=1, help="Top-K for recall computation."),
    k_factor: float = typer.Option(
        2.0,
        "--k-factor",
        min=1.0,
        help="Candidate expansion factor for ANN search.",
    ),
    index: IndexOption = None,
    duckdb: DuckOption = None,
    out: OutOption = None,
) -> None:
    """Evaluate ANN vs Flat recall and optionally persist pooled candidates."""
    settings = _get_settings()
    output_dir = Path(settings.eval.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = (out or (output_dir / "last_eval_pool.parquet")).expanduser().resolve()

    manager = _faiss_manager(index)
    catalog = _duckdb_catalog(duckdb)
    evaluator = HybridPoolEvaluator(catalog, manager)
    report = evaluator.run(k=k, k_factor=k_factor, out_parquet=out_path)
    typer.echo(json.dumps(report, indent=2))
