# SPDX-License-Identifier: MIT
"""Smoke test for a simplified document generation flow."""
# ruff: noqa: S101 - pytest-style assertions are intentional.

from __future__ import annotations

from pathlib import Path

from codeintel_rev.cli.enrich.__main__ import app  # noqa: PLC2701
from typer.testing import CliRunner

from tests.cli.enrich._graph_fixture import prepare_graph_repo


def test_exports_ast_goids_flow(tmp_path: Path) -> None:
    """Run exports -> ast -> goids to ensure core artifacts are emitted."""
    runner = CliRunner()
    repo, out_dir = prepare_graph_repo(tmp_path)

    result_exports = runner.invoke(
        app,
        ["exports", "--repo-root", str(repo), "--out-dir", str(out_dir)],
        catch_exceptions=False,
    )
    assert result_exports.exit_code == 0, result_exports.output
    assert (out_dir / "modules" / "modules.jsonl").exists()

    result_ast = runner.invoke(
        app,
        ["ast", "--repo-root", str(repo), "--out-dir", str(out_dir)],
        catch_exceptions=False,
    )
    assert result_ast.exit_code == 0, result_ast.output
    assert (out_dir / "ast" / "ast_nodes.parquet").exists()

    result_goids = runner.invoke(
        app,
        ["goids", "--repo-root", str(repo), "--out-dir", str(out_dir)],
        catch_exceptions=False,
    )
    assert result_goids.exit_code == 0, result_goids.output
    assert (out_dir / "goid" / "goids.parquet").exists()
