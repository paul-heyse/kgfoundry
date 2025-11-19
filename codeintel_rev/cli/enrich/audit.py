"""CLI command for running completeness audits."""

from __future__ import annotations

from pathlib import Path

import typer

from codeintel_rev.cli.enrich import app
from codeintel_rev.services.enrich.completeness import run_completeness_audit

REPO_ROOT_OPTION = typer.Option(".", "--repo-root", help="Repository root")
MODULES_JSONL_OPTION = typer.Option(
    "./.enrich/modules/modules.jsonl",
    "--modules-jsonl",
    help="Path to modules.jsonl",
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
    out: Path = OUT_PATH_OPTION,
) -> None:
    """Run completeness validation and emit a JSON report."""
    report_path = run_completeness_audit(repo_root, modules_jsonl, out)
    typer.echo(f"Completeness report written to {report_path}")
