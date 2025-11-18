# SPDX-License-Identifier: MIT
"""Scan command."""

from __future__ import annotations

import typer

from codeintel_rev.cli.enrich import app, common
from codeintel_rev.enrich.errors import StageError


@app.command("scan")
def scan(
    ctx: typer.Context,
    *,
    dry_run: bool = common.DRY_RUN_OPTION,
) -> None:
    """Run the scanner and report module counts."""
    state = common.ensure_state(ctx)
    try:
        result = common.execute_pipeline(state)
    except StageError as exc:  # pragma: no cover - defensive
        common.handle_stage_error(exc)
        return
    if common.handle_dry_run("scan", dry_run=dry_run, result=result):
        return
    typer.echo(f"[scan] Scanned {len(result.module_rows)} modules.")
