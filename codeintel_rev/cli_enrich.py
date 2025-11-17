"""Compatibility CLI that aggregates pipeline, analytics, and overlay commands."""

from __future__ import annotations

import typer

from codeintel_rev.cli import enrich_analytics, enrich_overlays, enrich_pipeline

app = typer.Typer(
    add_completion=True,
    help=enrich_pipeline.GLOBAL_OPTIONS_HELP,
)
enrich_pipeline.attach_argv_normalizer(app, enrich_pipeline.normalize_global_cli_args)
app.callback()(enrich_pipeline.shared_options)

# Pipeline commands
app.command("all")(enrich_pipeline.run_all)
app.command("run")(enrich_pipeline.run)
app.command("scan")(enrich_pipeline.scan)
app.command("exports")(enrich_pipeline.exports)
app.command("to-duckdb")(enrich_pipeline.to_duckdb)

# Analytics commands
app.command("graph")(enrich_analytics.graph)
app.command("uses")(enrich_analytics.uses)
app.command("typedness")(enrich_analytics.typedness)
app.command("doc")(enrich_analytics.doc)
app.command("coverage")(enrich_analytics.coverage)
app.command("config")(enrich_analytics.config)
app.command("hotspots")(enrich_analytics.hotspots)

# Overlay commands
app.command("overlays")(enrich_overlays.overlays)

# Re-export pipeline helpers for compatibility with tests/importers.
ScanInputs = enrich_pipeline.ScanInputs
ScipContext = enrich_pipeline.ScipContext
_build_module_row = enrich_pipeline.build_module_row
_outline_nodes_for = enrich_pipeline.outline_nodes_for
_type_error_count = enrich_pipeline.type_error_count
_apply_tagging = enrich_pipeline.apply_tagging
normalize_global_cli_args = enrich_pipeline.normalize_global_cli_args


def main() -> None:  # pragma: no cover - entrypoint
    """Invoke the compatibility CLI app."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
