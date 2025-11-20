# SPDX-License-Identifier: MIT
"""Smoke tests for the enrichment CLI surface."""

from __future__ import annotations

from codeintel_rev.cli import enrich_analytics, enrich_overlays, enrich_pipeline
from codeintel_rev.cli_enrich import app
from typer import Typer

from tests._helpers import assertions
from tests._helpers.cli import invoke

LEGACY_GLOBAL_FLAGS = ("--root", "--scip", "--out", "--pyrefly-json", "--tags-yaml")
THIN_CLI_COMMANDS = ("scan", "exports", "overlays", "analytics", "to-duckdb")
THIN_CLI_OPTIONS = ("--repo-root", "--out-dir")


def _assert_legacy_global_options(cli_app: Typer) -> None:
    """Assert that CLI help includes legacy global option flags.

    Parameters
    ----------
    cli_app : Typer
        CLI application to check.
    """
    result = invoke(cli_app, ["--help"], catch_exceptions=False)
    assertions.expect_equal(result.exit_code, 0, reason=result.output)
    for option in LEGACY_GLOBAL_FLAGS:
        assertions.expect_in(option, result.stdout)


def _assert_thin_cli_help(cli_app: Typer) -> None:
    """Assert that CLI help includes thin CLI command names.

    Parameters
    ----------
    cli_app : Typer
        CLI application to check.
    """
    result = invoke(cli_app, ["--help"], catch_exceptions=False)
    assertions.expect_equal(result.exit_code, 0, reason=result.output)
    for command in THIN_CLI_COMMANDS:
        assertions.expect_in(command, result.stdout)


def test_legacy_cli_help_lists_commands() -> None:
    """Legacy shim now exposes the thin enrich command group."""
    _assert_thin_cli_help(app)
    result = invoke(app, ["scan", "--help"], catch_exceptions=False)
    assertions.expect_equal(result.exit_code, 0, reason=result.output)
    for option in THIN_CLI_OPTIONS:
        assertions.expect_in(option, result.stdout)


def test_pipeline_cli_help_lists_commands() -> None:
    """Compatibility shim mirrors the thin CLI surface."""
    _assert_thin_cli_help(enrich_pipeline.app)


def test_analytics_cli_help_lists_global_options() -> None:
    """Analytics CLI still exposes the legacy global options."""
    _assert_legacy_global_options(enrich_analytics.app)


def test_overlays_cli_help_lists_global_options() -> None:
    """Overlay CLI still exposes the legacy global options."""
    _assert_legacy_global_options(enrich_overlays.app)
