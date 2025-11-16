# SPDX-License-Identifier: MIT
"""Unit tests for CLI global option normalization."""

from __future__ import annotations

from codeintel_rev import cli_enrich

from tests._helpers import assertions


def test_normalize_moves_global_options_before_command() -> None:
    """Options provided after the command are moved ahead of it."""
    argv = [
        "python",
        "all",
        "--dry-run",
        "--root",
        "/repo",
        "--scip",
        "index.scip.json",
        "--no-owners",
    ]
    result = cli_enrich.normalize_global_cli_args(argv)
    assertions.expect_equal(
        result,
        [
            "python",
            "--root",
            "/repo",
            "--scip",
            "index.scip.json",
            "--no-owners",
            "all",
            "--dry-run",
        ],
    )


def test_normalize_preserves_existing_order() -> None:
    """Options already before the command remain in place."""
    argv = [
        "python",
        "--root=/repo",
        "--scip",
        "index.scip.json",
        "--dry-run",
        "all",
    ]
    result = cli_enrich.normalize_global_cli_args(argv)
    assertions.expect_equal(result, argv)
