"""Scan command."""

from __future__ import annotations

from pathlib import Path

import typer

from codeintel_rev.app.readiness import raise_on_errors, validate_paths
from codeintel_rev.cli.enrich import app
from codeintel_rev.config.paths import ResolvedPaths, resolve_application_paths
from codeintel_rev.services.enrich.context import PipelineContext, PipelineInitOptions
from codeintel_rev.services.enrich.scan import scan_repo

REPO_ROOT_OPTION = typer.Option(".", "--repo-root", help="Repository root")
OUT_DIR_OPTION = typer.Option("./.enrich", "--out-dir", help="Output directory")
INCLUDE_OPTION = typer.Option(
    None,
    "--include",
    help="Include glob(s); repeat to supply multiple patterns.",
    show_default=False,
)
EXCLUDE_DEFAULT = ("**/.venv/**", "**/build/**", "**/dist/**")
EXCLUDE_OPTION = typer.Option(
    None,
    "--exclude",
    help="Exclude glob(s); repeat to override the default filters.",
    show_default=False,
)
INFER_TAGS_OPTION = typer.Option(
    default=True,
    help="Infer simple tags from file paths",
    show_default=True,
)


def _prepare_outputs(paths: ResolvedPaths) -> None:
    """Ensure output directories exist.

    Parameters
    ----------
    paths : ResolvedPaths
        Resolved application paths containing the data directory to create.
    """
    paths.data_dir.mkdir(parents=True, exist_ok=True)


@app.command("scan")
def scan(
    *,
    repo_root: Path = REPO_ROOT_OPTION,
    out_dir: Path = OUT_DIR_OPTION,
    include: list[str] | None = INCLUDE_OPTION,
    exclude: list[str] | None = EXCLUDE_OPTION,
    infer_tags: bool = INFER_TAGS_OPTION,
) -> None:
    """Scan the repository and report module counts."""
    paths = resolve_application_paths({"BASE_DIR": repo_root, "DATA_DIR": out_dir})
    raise_on_errors(validate_paths(paths))
    _prepare_outputs(paths)
    ctx = PipelineContext.from_paths(paths, options=PipelineInitOptions())
    include_globs = tuple(include or ())
    exclude_globs = tuple(exclude or EXCLUDE_DEFAULT)
    records = scan_repo(
        ctx,
        include=include_globs,
        exclude=exclude_globs,
        infer_tags=infer_tags,
    )
    typer.echo(f"Scanned {len(records)} modules.")
