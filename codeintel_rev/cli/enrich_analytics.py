"""Analytics CLI for enrichment artifacts."""

from __future__ import annotations

import typer

import codeintel_rev.cli.enrich_pipeline as pipeline

app = typer.Typer(add_completion=True, help="Enrichment analytics commands.")
pipeline.attach_argv_normalizer(app, pipeline.normalize_global_cli_args)
app.callback()(pipeline.shared_options)


def graph(
    ctx: typer.Context,
    *,
    dry_run: bool = pipeline.DRY_RUN_OPTION,
) -> None:
    result, state = pipeline.execute_pipeline_or_exit(ctx)
    if pipeline.handle_dry_run("graph", dry_run=dry_run, result=result):
        return
    pipeline.write_graph_outputs(result, state.pipeline.out)
    typer.echo("[graph] Wrote symbol and import graphs.")


def uses(
    ctx: typer.Context,
    *,
    dry_run: bool = pipeline.DRY_RUN_OPTION,
) -> None:
    result, state = pipeline.execute_pipeline_or_exit(ctx)
    if pipeline.handle_dry_run("uses", dry_run=dry_run, result=result):
        return
    pipeline.write_uses_output(result, state.pipeline.out)
    typer.echo("[uses] Wrote uses graph.")


def typedness(
    ctx: typer.Context,
    *,
    dry_run: bool = pipeline.DRY_RUN_OPTION,
) -> None:
    result, state = pipeline.execute_pipeline_or_exit(ctx)
    if pipeline.handle_dry_run("typedness", dry_run=dry_run, result=result):
        return
    pipeline.write_typedness_output(result, state.pipeline.out)
    typer.echo("[typedness] Wrote typedness analytics.")


def doc(
    ctx: typer.Context,
    *,
    dry_run: bool = pipeline.DRY_RUN_OPTION,
) -> None:
    result, state = pipeline.execute_pipeline_or_exit(ctx)
    if pipeline.handle_dry_run("doc", dry_run=dry_run, result=result):
        return
    pipeline.write_doc_output(result, state.pipeline.out)
    typer.echo("[doc] Wrote doc health analytics.")


def coverage(
    ctx: typer.Context,
    *,
    dry_run: bool = pipeline.DRY_RUN_OPTION,
) -> None:
    result, state = pipeline.execute_pipeline_or_exit(ctx)
    if pipeline.handle_dry_run("coverage", dry_run=dry_run, result=result):
        return
    pipeline.write_coverage_output(result, state.pipeline.out)
    typer.echo("[coverage] Wrote coverage analytics.")


def config(
    ctx: typer.Context,
    *,
    dry_run: bool = pipeline.DRY_RUN_OPTION,
) -> None:
    result, state = pipeline.execute_pipeline_or_exit(ctx)
    if pipeline.handle_dry_run("config", dry_run=dry_run, result=result):
        return
    pipeline.write_config_output(result, state.pipeline.out)
    typer.echo("[config] Wrote config index.")


def hotspots(
    ctx: typer.Context,
    *,
    dry_run: bool = pipeline.DRY_RUN_OPTION,
) -> None:
    result, state = pipeline.execute_pipeline_or_exit(ctx)
    if pipeline.handle_dry_run("hotspots", dry_run=dry_run, result=result):
        return
    pipeline.write_hotspot_output(result, state.pipeline.out)
    typer.echo("[hotspots] Wrote hotspot analytics.")


app.command("graph")(graph)
app.command("uses")(uses)
app.command("typedness")(typedness)
app.command("doc")(doc)
app.command("coverage")(coverage)
app.command("config")(config)
app.command("hotspots")(hotspots)


def main() -> None:  # pragma: no cover - entrypoint
    app()


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["app"]
