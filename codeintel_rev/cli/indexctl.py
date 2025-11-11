"""Typer CLI for managing index lifecycle operations."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import click
import typer

from codeintel_rev.indexing.index_lifecycle import IndexAssets, IndexLifecycleManager
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)
app = typer.Typer(help="Manage versioned FAISS/DuckDB/SCIP assets.", no_args_is_help=True)

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
