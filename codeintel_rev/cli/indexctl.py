"""Typer CLI for managing index lifecycle operations."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

import click
import numpy as np
import typer

from codeintel_rev.config.settings import Settings, load_settings
from codeintel_rev.eval.hybrid_evaluator import EvalConfig, HybridPoolEvaluator
from codeintel_rev.indexing.index_lifecycle import IndexAssets, IndexLifecycleManager
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.xtr_manager import XTRIndex
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)
app = typer.Typer(help="Manage versioned FAISS/DuckDB/SCIP assets.", no_args_is_help=True)
DEFAULT_XTR_ORACLE = False


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
AssetsArg = Annotated[
    tuple[Path, Path, Path],
    typer.Argument(
        ...,
        help="Primary assets (faiss.index catalog.duckdb code.scip).",
        metavar="FAISS_INDEX DUCKDB_PATH SCIP_INDEX",
    ),
]
SidecarOption = Annotated[
    list[str],
    typer.Option(
        "--sidecar",
        help="Optional sidecar entry of the form name=/path (faiss_idmap, tuning).",
        default_factory=list,
    ),
]
SweepMode = Literal["quick", "full"]
_PRIMARY_ASSET_COUNT = 3
_TUNE_OVERRIDE_CASTERS: dict[str, Callable[[str], float | int]] = {
    "nprobe": int,
    "ef_search": int,
    "quantizer_ef_search": int,
    "k_factor": float,
}
_SWEEP_MODE_BY_NAME: dict[str, SweepMode] = {
    "quick": "quick",
    "full": "full",
}
_SWEEP_FLAG = "--sweep"
SWEEP_OPTION = typer.Option(
    _SWEEP_FLAG,
    case_sensitive=False,
    help="Autotune sweep mode (quick/full).",
)
IdMapOption = Annotated[Path, typer.Option("--idmap", help="Path to FAISS ID map Parquet.")]
DuckOption = Annotated[Path | None, typer.Option("--duckdb", help="Path to DuckDB catalog file.")]
OutOption = Annotated[Path | None, typer.Option("--out", help="Output path override.")]
ParamSpaceArg = Annotated[
    str,
    typer.Argument(help="FAISS ParameterSpace string (e.g. 'nprobe=64')."),
]
EvalTopKOption = Annotated[
    int,
    typer.Option("--k", min=1, help="Top-K for recall computation."),
]
EvalKFactorOption = Annotated[
    float,
    typer.Option("--k-factor", min=1.0, help="Candidate expansion factor for ANN search."),
]
EvalNProbeOption = Annotated[
    int | None,
    typer.Option("--nprobe", help="Override FAISS nprobe."),
]
EvalXtrOracleOption = Annotated[
    bool,
    typer.Option(
        "--xtr-oracle/--no-xtr-oracle",
        help="Also rescore each query using the XTR token index when available.",
    ),
]


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
    primaries: tuple[Path, Path, Path],
    channels: dict[str, Path],
    sidecars: dict[str, Path],
) -> IndexAssets:
    faiss_index, duckdb_path, scip_index = primaries
    return IndexAssets(
        faiss_index=faiss_index,
        duckdb_path=duckdb_path,
        scip_index=scip_index,
        bm25_dir=channels.get("bm25"),
        splade_dir=channels.get("splade"),
        xtr_dir=channels.get("xtr"),
        faiss_idmap=sidecars.get("faiss_idmap"),
        tuning_profile=sidecars.get("tuning"),
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


def _parse_sidecars(entries: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    allowed = {"faiss_idmap", "tuning"}
    for entry in entries:
        if "=" not in entry:
            LOGGER.warning("Ignoring malformed --sidecar entry", extra={"entry": entry})
            continue
        key, value = entry.split("=", maxsplit=1)
        normalized = key.strip().lower()
        if normalized not in allowed:
            LOGGER.warning(
                "Ignoring unsupported sidecar entry",
                extra={"entry": entry, "allowed": sorted(allowed)},
            )
            continue
        parsed[normalized] = Path(value).expanduser().resolve()
    return parsed


def _parse_tune_overrides(
    raw_args: Sequence[str],
) -> tuple[dict[str, float | int], SweepMode | None]:
    overrides: dict[str, float | int] = {}
    sweep_mode: SweepMode | None = None
    iterator = iter(raw_args)
    for token in iterator:
        if not token.startswith("--"):
            msg = f"Unknown argument '{token}'."
            raise typer.BadParameter(msg)
        normalized = token.lstrip("-")
        if not normalized:
            msg = "Encountered empty option name."
            raise typer.BadParameter(msg)
        canonical = normalized.replace("-", "_")
        if canonical in _TUNE_OVERRIDE_CASTERS:
            try:
                raw_value = next(iterator)
            except StopIteration as exc:
                msg = f"Missing value for --{normalized}."
                raise typer.BadParameter(msg) from exc
            caster = _TUNE_OVERRIDE_CASTERS[canonical]
            try:
                overrides[canonical] = caster(raw_value)
            except ValueError as exc:
                msg = f"Invalid value '{raw_value}' for --{normalized}."
                raise typer.BadParameter(msg) from exc
            continue
        sweep_candidate = _SWEEP_MODE_BY_NAME.get(canonical)
        if sweep_candidate is not None:
            if sweep_mode is not None and sweep_mode != sweep_candidate:
                msg = "Conflicting sweep modes provided."
                raise typer.BadParameter(msg)
            sweep_mode = sweep_candidate
            continue
        msg = f"Unknown option '--{normalized}'."
        raise typer.BadParameter(msg)
    return overrides, sweep_mode


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
    catalog = DuckDBCatalog(
        db_path=db_path,
        vectors_dir=vectors_dir,
        repo_root=Path(settings.paths.repo_root).expanduser().resolve(),
        materialize=settings.index.duckdb_materialize,
    )
    catalog.set_idmap_path(Path(settings.paths.faiss_idmap_path).expanduser().resolve())
    return catalog


def _load_xtr_index(settings: Settings) -> XTRIndex | None:
    if not settings.xtr.enable:
        return None
    root = Path(settings.paths.xtr_dir).expanduser().resolve()
    index = XTRIndex(root=root, config=settings.xtr)
    try:
        index.open()
    except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover - defensive logging
        LOGGER.warning("Failed to open XTR index", extra={"root": str(root), "error": str(exc)})
        return None
    if not index.ready:
        LOGGER.warning("XTR index not ready", extra={"root": str(root)})
        return None
    return index


def _eval_paths(settings: Settings) -> tuple[Path, Path]:
    out_dir = Path(settings.eval.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / "last_eval_pool.parquet", out_dir / "metrics.json"


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
    assets: AssetsArg,
    extras: ExtraOption,
    sidecars: SidecarOption,
) -> None:
    """Stage a new version by copying assets into the lifecycle root.

    Raises
    ------
    typer.BadParameter
        If the primary assets are not provided in the expected order.
    """
    mgr = _manager()
    channels = _parse_extras(list(extras))
    resolved_assets = tuple(path.expanduser().resolve() for path in assets)
    if len(resolved_assets) != _PRIMARY_ASSET_COUNT:  # defensive: typer should enforce length
        msg = "Provide FAISS, DuckDB, and SCIP asset paths."
        raise typer.BadParameter(msg)
    faiss_index, duckdb_path, scip_index = resolved_assets
    sidecar_paths = _parse_sidecars(list(sidecars))
    staged_assets = _build_assets(
        (faiss_index, duckdb_path, scip_index),
        channels,
        sidecar_paths,
    )
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


@app.command(
    "tune",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def tune_command(
    ctx: typer.Context,
    index: IndexOption = None,
    sweep: Annotated[
        SweepMode | None,
        SWEEP_OPTION,
    ] = None,
) -> None:
    """Apply FAISS tuning overrides or run an autotune sweep.

    Raises
    ------
    typer.BadParameter
        If conflicting sweep modes or missing overrides are supplied.
    """
    overrides, inferred_sweep = _parse_tune_overrides(list(ctx.args))
    if sweep is not None and inferred_sweep is not None and sweep != inferred_sweep:
        msg = "Conflicting sweep modes provided via flags."
        raise typer.BadParameter(msg)
    sweep_mode = sweep or inferred_sweep
    manager = _faiss_manager(index)
    if sweep_mode is not None:
        _run_autotune(manager, mode=sweep_mode)
        typer.echo(f"Saved tuning profile -> {manager.autotune_profile_path}")
        return
    if not overrides:
        msg = (
            "Provide at least one override (--nprobe, --ef-search, "
            "--quantizer-ef-search, --k-factor) or specify --sweep."
        )
        raise typer.BadParameter(msg)
    nprobe_override = overrides.get("nprobe")
    ef_override = overrides.get("ef_search")
    quantizer_override = overrides.get("quantizer_ef_search")
    k_factor_override = overrides.get("k_factor")
    tuning = manager.apply_runtime_tuning(
        nprobe=int(nprobe_override) if nprobe_override is not None else None,
        ef_search=int(ef_override) if ef_override is not None else None,
        quantizer_ef_search=int(quantizer_override) if quantizer_override is not None else None,
        k_factor=float(k_factor_override) if k_factor_override is not None else None,
    )
    audit_path = _write_tuning_audit(manager, tuning)
    typer.echo(f"Wrote runtime tuning snapshot -> {audit_path}")


@app.command("tune-params")
def tune_params_command(
    params: ParamSpaceArg,
    index: IndexOption = None,
) -> None:
    """Apply FAISS ParameterSpace string (nprobe/efSearch/quantizer/k_factor).

    Raises
    ------
    typer.BadParameter
        If the ParameterSpace string includes unsupported keys.
    """
    manager = _faiss_manager(index)
    try:
        tuning = manager.set_search_parameters(params)
    except ValueError as exc:
        msg = str(exc)
        raise typer.BadParameter(msg) from exc
    audit_path = _write_tuning_audit(manager, tuning)
    typer.echo(f"Wrote runtime tuning snapshot -> {audit_path}")


@app.command("show-profile")
def show_profile_command(index: IndexOption = None) -> None:
    """Print the active tuning profile, overrides, and saved ParameterSpace."""
    manager = _faiss_manager(index)
    typer.echo(json.dumps(manager.get_runtime_tuning(), indent=2))


def _write_tuning_audit(manager: FAISSManager, tuning: dict[str, object]) -> Path:
    audit_path = manager.index_path.with_suffix(".audit.json").expanduser().resolve()
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(tuning, indent=2) + "\n", encoding="utf-8")
    return audit_path


_AUTOTUNE_SAMPLE_LIMITS = {"quick": 64, "full": 256}
_AUTOTUNE_MIN_SAMPLES = 4


def _run_autotune(manager: FAISSManager, mode: SweepMode) -> None:
    settings = _get_settings()
    catalog = _duckdb_catalog()
    try:
        samples = catalog.sample_query_vectors(limit=_AUTOTUNE_SAMPLE_LIMITS[mode])
    finally:
        catalog.close()
    if len(samples) < _AUTOTUNE_MIN_SAMPLES:
        msg = (
            f"Need at least {_AUTOTUNE_MIN_SAMPLES} vectors in DuckDB catalog for {mode} "
            f"autotune (found {len(samples)})."
        )
        raise typer.BadParameter(msg)
    vectors = np.stack([vec for _, vec in samples], dtype=np.float32)
    queries = vectors[: min(32, vectors.shape[0])]
    sweep_values = (16, 32, 48, 64, 96, 128) if mode == "quick" else (16, 32, 64, 96, 128, 192, 256)
    sweep = tuple(f"nprobe={value}" for value in sweep_values)
    manager.autotune(
        queries,
        vectors,
        k=min(int(settings.index.default_k), queries.shape[0]),
        sweep=sweep,
    )


@app.command("eval")
def eval_command(
    k: EvalTopKOption = 10,
    k_factor: EvalKFactorOption = 2.0,
    nprobe: EvalNProbeOption = None,
    xtr_oracle: EvalXtrOracleOption = DEFAULT_XTR_ORACLE,
) -> None:
    """Run ANN vs Flat evaluation and optionally rescore with XTR."""
    settings = _get_settings()
    manager = _faiss_manager()
    catalog = _duckdb_catalog()
    xtr_index = _load_xtr_index(settings) if xtr_oracle else None
    pool_path, metrics_path = _eval_paths(settings)
    config = EvalConfig(
        k=k,
        k_factor=k_factor,
        nprobe=nprobe,
        max_queries=settings.eval.max_queries,
        use_xtr_oracle=bool(xtr_index and xtr_oracle),
        pool_path=pool_path,
        metrics_path=metrics_path,
    )
    evaluator = HybridPoolEvaluator(catalog, manager, xtr_index=xtr_index)
    report = evaluator.run(config)
    try:
        catalog.ensure_pool_views(pool_path)
    except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover - defensive logging
        LOGGER.warning(
            "Unable to expose pool coverage views",
            extra={"pool_path": str(pool_path), "error": str(exc)},
        )
    typer.echo(json.dumps(report.__dict__, indent=2))
