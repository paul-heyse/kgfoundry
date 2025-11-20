# SPDX-License-Identifier: MIT
"""Integration test covering the AST CLI command."""
# ruff: noqa: S101 - pytest-style assertions are intentional.

from __future__ import annotations

from pathlib import Path

from codeintel_rev.cli.enrich.__main__ import app  # noqa: PLC2701
from typer.testing import CliRunner

from tests.cli.enrich._graph_fixture import prepare_graph_repo


def test_ast_cli_command(tmp_path: Path) -> None:
    """CLI ast command should emit AST node/metric artifacts."""
    runner = CliRunner()
    repo, out_dir = prepare_graph_repo(tmp_path)

    result_ast = runner.invoke(
        app,
        ["ast", "--repo-root", str(repo), "--out-dir", str(out_dir)],
        catch_exceptions=False,
    )
    assert result_ast.exit_code == 0, result_ast.output
    assert (out_dir / "ast" / "ast_nodes.parquet").exists()
    assert (out_dir / "ast" / "ast_metrics.parquet").exists()
