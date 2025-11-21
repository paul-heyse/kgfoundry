"""CLI command for running completeness audits."""

from __future__ import annotations

from pathlib import Path

import typer

from codeintel_rev.cli.enrich import app
from codeintel_rev.services.enrich.artifact_manifest import resolve_from_manifest
from codeintel_rev.services.enrich.completeness import run_completeness_audit

REPO_ROOT_OPTION = typer.Option(".", "--repo-root", help="Repository root")
MODULES_JSONL_OPTION = typer.Option(
    "./.enrich/modules/modules.jsonl",
    "--modules-jsonl",
    help="Path to modules.jsonl",
)
MANIFEST_OPTION = typer.Option(
    None,
    "--manifest",
    help="Optional exports manifest to resolve modules path.",
    exists=True,
    dir_okay=False,
    readable=True,
)
OUT_PATH_OPTION = typer.Option(
    "./.enrich/completeness_report.json",
    "--out",
    help="Output path for the completeness report",
)


@app.command("audit")
def audit(
    *,
    repo_root: Path = REPO_ROOT_OPTION,
    modules_jsonl: Path = MODULES_JSONL_OPTION,
    manifest: Path | None = MANIFEST_OPTION,
    out: Path = OUT_PATH_OPTION,
) -> None:
    """Run completeness validation and emit a JSON report."""
    target_modules = _resolve_modules_from_manifest(manifest, modules_jsonl)
    report_path = run_completeness_audit(repo_root, target_modules, out)
    typer.echo(f"Completeness report written to {report_path}")


def _resolve_modules_from_manifest(manifest: Path | None, fallback: Path) -> Path:
    """Return modules.jsonl path from manifest when available.

    Returns
    -------
    Path
        Resolved modules.jsonl path or the provided fallback.
    """
    resolved, _repo_map, _tag_index = resolve_from_manifest(
        manifest, fallback_modules=fallback
    )
    return resolved
