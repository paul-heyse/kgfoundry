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
    """Generate symbol and import dependency graphs from enrichment pipeline results.

    This command executes the enrichment pipeline and writes graph artifacts
    representing symbol relationships and import dependencies. The graphs enable
    visualization and analysis of code structure, dependencies, and symbol
    connectivity across the codebase. Outputs are written to the configured
    pipeline output directory.

    Parameters
    ----------
    ctx : typer.Context
        Typer context containing CLI arguments and shared pipeline state.
        Used to access global options and execute the enrichment pipeline.
    dry_run : bool, optional
        If True, validate configuration and show what would be executed without
        writing artifacts. Enables safe testing of pipeline configuration.

    Notes
    -----
    The graph command is part of the enrichment analytics suite, which provides
    insights into code structure, dependencies, and quality metrics. This command
    specifically focuses on generating graph representations that can be used for
    visualization tools, dependency analysis, and understanding code relationships.
    """
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
    """Generate uses graph showing symbol usage relationships across the codebase.

    This command executes the enrichment pipeline and writes a uses graph artifact
    that maps where symbols are referenced and used throughout the codebase. The
    uses graph enables analysis of symbol dependencies, usage patterns, and impact
    analysis for refactoring or code changes. Output is written to the configured
    pipeline output directory.

    Parameters
    ----------
    ctx : typer.Context
        Typer context containing CLI arguments and shared pipeline state.
        Used to access global options and execute the enrichment pipeline.
    dry_run : bool, optional
        If True, validate configuration and show what would be executed without
        writing artifacts. Enables safe testing of pipeline configuration.

    Notes
    -----
    The uses graph complements the symbol graph by focusing specifically on usage
    relationships. This is valuable for understanding how symbols are consumed,
    identifying unused code, and performing impact analysis for changes or deletions.
    """
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
    """Generate typedness analytics measuring type annotation coverage across the codebase.

    This command executes the enrichment pipeline and writes typedness analytics
    that measure the extent of type annotations in the codebase. Typedness metrics
    help assess code quality, maintainability, and enable better IDE support and
    static analysis. Output includes per-module and aggregate type coverage statistics.

    Parameters
    ----------
    ctx : typer.Context
        Typer context containing CLI arguments and shared pipeline state.
        Used to access global options and execute the enrichment pipeline.
    dry_run : bool, optional
        If True, validate configuration and show what would be executed without
        writing artifacts. Enables safe testing of pipeline configuration.

    Notes
    -----
    Typedness analytics are essential for Python codebases using type hints, as
    they help track progress toward full type coverage and identify areas needing
    type annotations. Higher typedness improves IDE autocomplete, enables static
    type checking, and reduces runtime type-related errors.
    """
    result, state = pipeline.execute_pipeline_or_exit(ctx)
    if pipeline.handle_dry_run("typedness", dry_run=dry_run, result=result):
        return
    pipeline.write_typedness_output(result, state.pipeline.out)
    pipeline.write_static_diagnostics_output(result, state.pipeline.out)
    typer.echo("[typedness] Wrote typedness analytics.")


def function_metrics(
    ctx: typer.Context,
    *,
    dry_run: bool = pipeline.DRY_RUN_OPTION,
) -> None:
    """Generate per-function structural metrics."""
    result, state = pipeline.execute_pipeline_or_exit(ctx)
    if pipeline.handle_dry_run("function-metrics", dry_run=dry_run, result=result):
        return
    pipeline.write_function_metrics_output(result, state.pipeline.out)
    typer.echo("[function-metrics] Wrote function metrics analytics.")


def function_types(
    ctx: typer.Context,
    *,
    dry_run: bool = pipeline.DRY_RUN_OPTION,
) -> None:
    """Generate per-function typedness analytics."""
    result, state = pipeline.execute_pipeline_or_exit(ctx)
    if pipeline.handle_dry_run("function-types", dry_run=dry_run, result=result):
        return
    pipeline.write_function_types_output(result, state.pipeline.out)
    typer.echo("[function-types] Wrote function typedness analytics.")


def doc(
    ctx: typer.Context,
    *,
    dry_run: bool = pipeline.DRY_RUN_OPTION,
) -> None:
    """Generate documentation health analytics measuring docstring coverage and quality.

    This command executes the enrichment pipeline and writes documentation health
    analytics that assess docstring coverage, completeness, and quality across the
    codebase. Documentation metrics help maintain code maintainability, improve
    developer onboarding, and ensure API documentation standards. Output includes
    per-module docstring coverage and quality scores.

    Parameters
    ----------
    ctx : typer.Context
        Typer context containing CLI arguments and shared pipeline state.
        Used to access global options and execute the enrichment pipeline.
    dry_run : bool, optional
        If True, validate configuration and show what would be executed without
        writing artifacts. Enables safe testing of pipeline configuration.

    Notes
    -----
    Documentation health analytics are critical for maintaining code quality and
    developer experience. Well-documented code reduces onboarding time, enables
    better IDE tooling, and supports automated documentation generation. This
    command helps track documentation coverage and identify areas needing
    documentation improvements.
    """
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
    """Generate code coverage analytics from test execution and symbol analysis.

    This command executes the enrichment pipeline and writes code coverage analytics
    that measure how much of the codebase is exercised by tests. Coverage metrics
    help identify untested code paths, guide test writing efforts, and ensure
    comprehensive test coverage. Output includes per-module coverage percentages
    and coverage gaps.

    Parameters
    ----------
    ctx : typer.Context
        Typer context containing CLI arguments and shared pipeline state.
        Used to access global options and execute the enrichment pipeline.
    dry_run : bool, optional
        If True, validate configuration and show what would be executed without
        writing artifacts. Enables safe testing of pipeline configuration.

    Notes
    -----
    Code coverage analytics complement test execution by providing visibility into
    which parts of the codebase are tested. High coverage reduces the risk of
    regressions and helps maintain code quality. This command integrates coverage
    data with symbol analysis to provide comprehensive coverage insights.
    """
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
    """Generate configuration index mapping configuration keys to their usage locations.

    This command executes the enrichment pipeline and writes a configuration index
    that maps configuration keys (from YAML, TOML, JSON, and environment variables)
    to their usage locations in the codebase. The config index enables tracking
    configuration usage, identifying unused settings, and understanding configuration
    dependencies. Output includes a searchable index of all configuration references.

    Parameters
    ----------
    ctx : typer.Context
        Typer context containing CLI arguments and shared pipeline state.
        Used to access global options and execute the enrichment pipeline.
    dry_run : bool, optional
        If True, validate configuration and show what would be executed without
        writing artifacts. Enables safe testing of pipeline configuration.

    Notes
    -----
    Configuration indexing is valuable for understanding how application settings
    are used throughout the codebase. This helps with configuration management,
    identifying deprecated settings, and ensuring configuration changes don't
    break functionality. The index supports both static analysis and runtime
    configuration validation.
    """
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
    """Generate code hotspot analytics identifying high-complexity and high-churn areas.

    This command executes the enrichment pipeline and writes hotspot analytics that
    identify areas of the codebase with high complexity, frequent changes, or both.
    Hotspots help prioritize refactoring efforts, identify technical debt, and
    guide code review focus. Output includes hotspot scores, complexity metrics,
    and churn statistics.

    Parameters
    ----------
    ctx : typer.Context
        Typer context containing CLI arguments and shared pipeline state.
        Used to access global options and execute the enrichment pipeline.
    dry_run : bool, optional
        If True, validate configuration and show what would be executed without
        writing artifacts. Enables safe testing of pipeline configuration.

    Notes
    -----
    Code hotspots are areas that combine high complexity with frequent changes,
    indicating potential technical debt and maintenance risk. Identifying hotspots
    helps teams prioritize refactoring efforts and allocate resources effectively.
    This command combines static analysis (complexity) with version control history
    (churn) to provide comprehensive hotspot identification.
    """
    result, state = pipeline.execute_pipeline_or_exit(ctx)
    if pipeline.handle_dry_run("hotspots", dry_run=dry_run, result=result):
        return
    pipeline.write_hotspot_output(result, state.pipeline.out)
    typer.echo("[hotspots] Wrote hotspot analytics.")


app.command("graph")(graph)
app.command("uses")(uses)
app.command("typedness")(typedness)
app.command("function-metrics")(function_metrics)
app.command("function-types")(function_types)
app.command("doc")(doc)
app.command("coverage")(coverage)
app.command("config")(config)
app.command("hotspots")(hotspots)


def main() -> None:  # pragma: no cover - entrypoint
    """Entry point for the enrichment analytics CLI application.

    This function serves as the main entry point when the module is executed
    directly or invoked as a CLI command. It delegates to the Typer application
    instance to handle command parsing, execution, and error handling. The CLI
    provides access to various analytics commands for code quality and structure
    analysis.

    Notes
    -----
    This entry point is registered as a console script in the package configuration,
    allowing the CLI to be invoked via `codeintel enrich-analytics <command>` or
    directly via Python module execution. The Typer application handles all command
    routing, argument parsing, and help text generation.
    """
    app()


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["app"]
