"""Apply overlays via the enrich services."""

from __future__ import annotations

from pathlib import Path

import typer

from codeintel_rev.cli.enrich import app
from codeintel_rev.cli.enrich.common import prepare_cli_context
from codeintel_rev.services.enrich.exports import run_all_exports
from codeintel_rev.services.enrich.overlays import apply_overlays
from codeintel_rev.services.enrich.scan import scan_repo

REPO_ROOT_OPTION = typer.Option(".", "--repo-root", help="Repository root")
OUT_DIR_OPTION = typer.Option("./.enrich", "--out-dir", help="Output directory")
OVERLAY_OPTION = typer.Option(
    None,
    "--overlay",
    help="Overlay JSON or JSONL file; repeat to provide multiple files.",
    show_default=False,
)
WRITE_EXPORTS_OPTION = typer.Option(
    default=True,
    help="Emit exports after applying overlays",
    show_default=True,
)


@app.command("overlays")
def overlays(
    *,
    repo_root: Path = REPO_ROOT_OPTION,
    out_dir: Path = OUT_DIR_OPTION,
    overlay: list[Path] | None = OVERLAY_OPTION,
    write_exports: bool = WRITE_EXPORTS_OPTION,
) -> None:
    """Apply overlay metadata to the scanned records."""
    ctx, _paths = prepare_cli_context(repo_root, out_dir)
    overlay_paths = tuple(overlay or ())
    records = apply_overlays(ctx, scan_repo(ctx), overlay_paths)
    if write_exports:
        run_all_exports(ctx, records)
    typer.echo(f"Overlays applied to {len(records)} modules.")
