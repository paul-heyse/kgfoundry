# SPDX-License-Identifier: MIT
"""Exports command."""

from __future__ import annotations

import typer

from codeintel_rev.cli.enrich import app, common
from codeintel_rev.enrich.errors import StageError
from codeintel_rev.services.enrich import exports as export_services


def _run_exports_pipeline(
    ctx: typer.Context,
    *,
    emit_ast: bool,
    dry_run: bool,
    command: str,
) -> None:
    state = common.ensure_state(ctx)
    try:
        result = common.execute_pipeline(state)
    except StageError as exc:  # pragma: no cover - defensive
        common.handle_stage_error(exc)
        return
    if common.handle_dry_run(command, dry_run=dry_run, result=result):
        return
    if state.analytics.owners:
        export_services.apply_ownership(
            result,
            state.pipeline.out,
            history_window_days=state.analytics.history_window_days,
            commits_window=state.analytics.commits_window,
        )
    if state.analytics.emit_slices:
        export_services.write_slices_output(
            result.module_rows,
            state.pipeline.out,
            slices_filter=list(state.analytics.slices_filter),
        )
    export_services.write_exports_outputs(result, state.pipeline.out)
    export_services.write_ast_outputs(result, state.pipeline.out, emit_ast=emit_ast)
    typer.echo(f"[{command}] Wrote module artifacts for {len(result.module_rows)} modules.")


@app.command("exports")
def exports(
    ctx: typer.Context,
    *,
    emit_ast: bool = common.EMIT_AST_OPTION,
    dry_run: bool = common.DRY_RUN_OPTION,
) -> None:
    """Emit modules.jsonl, repo map, markdown sheets, and tag index."""
    _run_exports_pipeline(ctx, emit_ast=emit_ast, dry_run=dry_run, command="exports")


@app.command("all")
def run_all(
    ctx: typer.Context,
    *,
    emit_ast: bool = common.EMIT_AST_OPTION,
    dry_run: bool = common.DRY_RUN_OPTION,
) -> None:
    """Run the full enrichment pipeline and emit all artifacts."""
    state = common.ensure_state(ctx)
    try:
        result = common.execute_pipeline(state)
    except StageError as exc:  # pragma: no cover - defensive
        common.handle_stage_error(exc)
        return
    if common.handle_dry_run("all", dry_run=dry_run, result=result):
        return
    if state.analytics.owners:
        export_services.apply_ownership(
            result,
            state.pipeline.out,
            history_window_days=state.analytics.history_window_days,
            commits_window=state.analytics.commits_window,
        )
    if state.analytics.emit_slices:
        export_services.write_slices_output(
            result.module_rows,
            state.pipeline.out,
            slices_filter=list(state.analytics.slices_filter),
        )
    export_services.write_exports_outputs(result, state.pipeline.out)
    export_services.write_graph_outputs(result, state.pipeline.out)
    export_services.write_uses_output(result, state.pipeline.out)
    export_services.write_typedness_output(result, state.pipeline.out)
    export_services.write_doc_output(result, state.pipeline.out)
    export_services.write_coverage_output(result, state.pipeline.out)
    export_services.write_config_output(result, state.pipeline.out)
    export_services.write_hotspot_output(result, state.pipeline.out)
    export_services.write_ast_outputs(result, state.pipeline.out, emit_ast=emit_ast)
    typer.echo(f"[all] Completed enrichment for {len(result.module_rows)} modules.")


@app.command("run")
def run(
    ctx: typer.Context,
    *,
    emit_ast: bool = common.EMIT_AST_OPTION,
    dry_run: bool = common.DRY_RUN_OPTION,
) -> None:
    """Alias for ``all`` to match historical CLI entrypoints."""
    run_all(ctx, emit_ast=emit_ast, dry_run=dry_run)
