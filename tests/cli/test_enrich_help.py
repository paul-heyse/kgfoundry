# SPDX-License-Identifier: MIT
"""Smoke tests for the enrichment CLI surface."""

from __future__ import annotations

from codeintel_rev.cli_enrich import app
from typer.testing import CliRunner

runner = CliRunner()


def test_cli_help_lists_global_options() -> None:
    result = runner.invoke(app, ["--help"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    for option in ("--root", "--scip", "--out", "--pyrefly-json", "--tags-yaml", "--dry-run"):
        assert option in result.stdout


def test_exports_help_mentions_dry_run() -> None:
    result = runner.invoke(app, ["exports", "--help"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "--dry-run" in result.stdout
