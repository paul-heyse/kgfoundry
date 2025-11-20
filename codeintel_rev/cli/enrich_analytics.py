"""Analytics CLI for enrichment artifacts."""

from __future__ import annotations

from pathlib import Path

import typer

import codeintel_rev.cli.enrich_pipeline as pipeline
from codeintel_rev.services.enrich.coverage_pipeline import (
    run_coverage_analytics,
    run_risk_factors,
    run_test_analytics,
)

app = typer.Typer(add_completion=True, help="Enrichment analytics commands.")
pipeline.attach_argv_normalizer(app, pipeline.normalize_global_cli_args)
app.callback()(pipeline.shared_options)

COVERAGE_FILE_OPTION = typer.Option(
    Path(".coverage"),
    "--coverage-file",
    help="Path to coverage.py data file (with dynamic contexts enabled).",
    exists=True,
    dir_okay=False,
    readable=True,
)

PYTEST_REPORT_OPTION = typer.Option(
    Path(".cache/pytest-report.json"),
    "--pytest-report",
    help="Path to pytest JSON report generated via pytest-json-report.",
    exists=True,
    dir_okay=False,
    readable=True,
)


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


@app.command("coverage-detailed")
def coverage_detailed(
    ctx: typer.Context,
    *,
    coverage_file: Path = COVERAGE_FILE_OPTION,
) -> None:
    """Generate line-level and function-level coverage analytics."""
    state = pipeline.ensure_state(ctx)
    repo_root = state.pipeline.root
    enriched_dir = state.pipeline.out
    cov_path = coverage_file if coverage_file.is_absolute() else repo_root / coverage_file
    run_coverage_analytics(
        repo_root=repo_root,
        enriched_dir=enriched_dir,
        coverage_file=cov_path,
    )
    typer.echo("[coverage-detailed] Wrote coverage_lines and coverage_functions.")


@app.command("test-analytics")
def compute_test_analytics(
    ctx: typer.Context,
    *,
    coverage_file: Path = COVERAGE_FILE_OPTION,
    pytest_report: Path = PYTEST_REPORT_OPTION,
) -> None:
    """Generate test catalog and test→function coverage edges.

    Extended Summary
    ----------------
    Processes pytest JSON report and coverage data to generate test catalog
    and test-to-function coverage edges. Requires coverage_functions.jsonl
    to exist (generated by coverage-detailed command). Writes test_catalog
    and test_coverage_edges analytics files to the enriched output directory.

    Parameters
    ----------
    ctx : typer.Context
        Typer context providing access to pipeline state and configuration.
    coverage_file : Path, optional
        Path to coverage.py data file with dynamic contexts enabled.
        Defaults to ".coverage" in the current directory.
    pytest_report : Path, optional
        Path to pytest JSON report generated via pytest-json-report.
        Defaults to ".cache/pytest-report.json".

    Raises
    ------
    typer.Exit
        If coverage_functions.jsonl is missing, exits with code 1 after
        displaying an error message instructing the user to run
        coverage-detailed first.

    Notes
    -----
    Time O(n) where n is the number of test cases and coverage lines;
    memory O(n) for loading coverage data and test reports. Performs file I/O
    to read coverage files and pytest reports, and writes analytics outputs.
    Thread-safe for separate instances processing different repositories.
    """
    state = pipeline.ensure_state(ctx)
    repo_root = state.pipeline.root
    enriched_dir = state.pipeline.out
    coverage_functions = enriched_dir / "analytics" / "coverage" / "coverage_functions.jsonl"
    if not coverage_functions.exists():
        typer.echo(
            "coverage_functions.jsonl is missing. Run `coverage-detailed` first to "
            "materialize coverage analytics.",
            err=True,
        )
        raise typer.Exit(code=1)
    cov_path = coverage_file if coverage_file.is_absolute() else repo_root / coverage_file
    report_path = pytest_report if pytest_report.is_absolute() else repo_root / pytest_report
    run_test_analytics(
        repo_root=repo_root,
        enriched_dir=enriched_dir,
        coverage_file=cov_path,
        pytest_report=report_path,
    )
    typer.echo("[test-analytics] Wrote test_catalog and test_coverage_edges.")


@app.command("risk-factors")
def risk_factors(
    ctx: typer.Context,
) -> None:
    """Generate GOID risk factors joined across analytics tables."""
    state = pipeline.ensure_state(ctx)
    enriched_dir = state.pipeline.out
    run_risk_factors(enriched_dir)
    typer.echo("[risk-factors] Wrote goid_risk_factors analytics.")


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
