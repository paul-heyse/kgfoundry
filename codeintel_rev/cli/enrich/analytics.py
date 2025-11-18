# SPDX-License-Identifier: MIT
"""Analytics command."""

from __future__ import annotations

import typer

from codeintel_rev.cli.enrich import app, common
from codeintel_rev.cli.enrich.__main__ import main as enrich_main
from codeintel_rev.enrich.errors import StageError
from codeintel_rev.services.enrich import exports as export_services


@app.command("analytics")
def analytics(
    ctx: typer.Context,
    *,
    dry_run: bool = common.DRY_RUN_OPTION,
) -> None:
    """Emit enrichment analytics artifacts (graphs, typedness, coverage, etc.)."""
    state = common.ensure_state(ctx)
    try:
        result = common.execute_pipeline(state)
    except StageError as exc:  # pragma: no cover - defensive
        common.handle_stage_error(exc)
        return
    if common.handle_dry_run("analytics", dry_run=dry_run, result=result):
        return
    export_services.write_graph_outputs(result, state.pipeline.out)
    export_services.write_uses_output(result, state.pipeline.out)
    export_services.write_typedness_output(result, state.pipeline.out)
    export_services.write_doc_output(result, state.pipeline.out)
    export_services.write_coverage_output(result, state.pipeline.out)
    export_services.write_config_output(result, state.pipeline.out)
    export_services.write_hotspot_output(result, state.pipeline.out)
    typer.echo("[analytics] Wrote analytics artifacts.")


def main() -> None:  # pragma: no cover - entrypoint shim
    """Invoke the enrichment CLI (analytics shim)."""
    enrich_main()


__all__ = ["analytics", "main"]
