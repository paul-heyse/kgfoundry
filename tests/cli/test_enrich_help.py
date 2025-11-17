# SPDX-License-Identifier: MIT
"""Smoke tests for the enrichment CLI surface."""

from __future__ import annotations

from codeintel_rev.cli import enrich_analytics, enrich_overlays, enrich_pipeline
from codeintel_rev.cli_enrich import app
from typer import Typer

from tests._helpers import assertions
from tests._helpers.cli import invoke

GLOBAL_FLAGS = ("--root", "--scip", "--out", "--pyrefly-json", "--tags-yaml")


def _assert_global_options(cli_app: Typer) -> None:
    result = invoke(cli_app, ["--help"], catch_exceptions=False)
    assertions.expect_equal(result.exit_code, 0, reason=result.output)
    for option in GLOBAL_FLAGS:
        assertions.expect_in(option, result.stdout)


def test_legacy_cli_help_lists_global_options() -> None:
    """Legacy shim still prints global flags."""
    _assert_global_options(app)
    result = invoke(app, ["exports", "--help"], catch_exceptions=False)
    assertions.expect_equal(result.exit_code, 0, reason=result.output)
    assertions.expect_in("--dry-run", result.stdout)


def test_pipeline_cli_help_lists_global_options() -> None:
    """Pipeline CLI exposes global options."""
    _assert_global_options(enrich_pipeline.app)


def test_analytics_cli_help_lists_global_options() -> None:
    """Analytics CLI exposes global options."""
    _assert_global_options(enrich_analytics.app)


def test_overlays_cli_help_lists_global_options() -> None:
    """Overlay CLI exposes global options."""
    _assert_global_options(enrich_overlays.app)
