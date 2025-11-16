# SPDX-License-Identifier: MIT
"""Smoke tests for the enrichment CLI surface."""

from __future__ import annotations

from codeintel_rev.cli_enrich import app

from tests._helpers import assertions
from tests._helpers.cli import invoke


def test_cli_help_lists_global_options() -> None:
    """Global help output exposes key options."""
    result = invoke(app, ["--help"], catch_exceptions=False)
    assertions.expect_equal(result.exit_code, 0, reason=result.output)
    for option in ("--root", "--scip", "--out", "--pyrefly-json", "--tags-yaml", "--dry-run"):
        assertions.expect_in(option, result.stdout)


def test_exports_help_mentions_dry_run() -> None:
    """Exports subcommand help references --dry-run."""
    result = invoke(app, ["exports", "--help"], catch_exceptions=False)
    assertions.expect_equal(result.exit_code, 0, reason=result.output)
    assertions.expect_in("--dry-run", result.stdout)
