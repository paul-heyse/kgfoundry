"""Exports command."""

from __future__ import annotations

from pathlib import Path

import typer

from codeintel_rev.cli.enrich import app
from codeintel_rev.cli.enrich.common import prepare_cli_context
from codeintel_rev.services.enrich.artifact_copier import copy_from_manifest
from codeintel_rev.services.enrich.artifact_writer import process_artifact_dir
from codeintel_rev.services.enrich.exports import run_all_exports
from codeintel_rev.services.enrich.scan import scan_repo

REPO_ROOT_OPTION = typer.Option(".", "--repo-root", help="Repository root")
OUT_DIR_OPTION = typer.Option("./.enrich", "--out-dir", help="Output directory")
COPY_DEST_OPTION = typer.Option(
    None,
    "--copy-to",
    help="Optional destination for promoted artifacts (uses manifest).",
    dir_okay=True,
    file_okay=False,
    writable=True,
)


@app.command("exports")
def exports(
    *,
    repo_root: Path = REPO_ROOT_OPTION,
    out_dir: Path = OUT_DIR_OPTION,
    copy_to: Path | None = COPY_DEST_OPTION,
) -> None:
    """Emit modules.jsonl, repo map, tag index, and markdown sheets."""
    ctx, _paths = prepare_cli_context(repo_root, out_dir)
    result = run_all_exports(ctx, scan_repo(ctx))
    process_artifact_dir(ctx.paths.data_dir)
    if copy_to is not None:
        copy_from_manifest(ctx.paths.data_dir / "exports_manifest.json", copy_to)
    typer.echo(
        "Wrote artifacts: "
        f"{result.modules_jsonl}, {result.repo_map}, {result.tag_index}, {result.markdown_dir}"
    )
