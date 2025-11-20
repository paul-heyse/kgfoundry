# SPDX-License-Identifier: MIT
"""Tests for artifact writer manifest promotion."""
# ruff: noqa: S101 - pytest-style assertions are intentional.

from __future__ import annotations

from pathlib import Path

from codeintel_rev.cli.enrich.__main__ import app  # noqa: PLC2701
from codeintel_rev.services.enrich.artifact_writer import process_artifact_dir
from typer.testing import CliRunner

from tests.cli.enrich._graph_fixture import prepare_graph_repo


def test_process_artifact_dir_promotes_aliases_and_jsonl(tmp_path: Path) -> None:
    """process_artifact_dir should emit JSONL sidecars and aliases."""
    runner = CliRunner()
    repo, out_dir = prepare_graph_repo(tmp_path)

    # Generate minimal graph artifacts
    result_exports = runner.invoke(
        app,
        ["exports", "--repo-root", str(repo), "--out-dir", str(out_dir)],
        catch_exceptions=False,
    )
    assert result_exports.exit_code == 0, result_exports.output
    result_goids = runner.invoke(
        app,
        ["goids", "--repo-root", str(repo), "--out-dir", str(out_dir)],
        catch_exceptions=False,
    )
    assert result_goids.exit_code == 0, result_goids.output

    process_artifact_dir(out_dir)

    # GOID JSONL sidecars should exist
    assert (out_dir / "goid" / "goids.jsonl").exists()
    # Legacy alias should be promoted if not present
    imports_parquet = out_dir / "graphs" / "imports.parquet"
    if (out_dir / "graphs" / "import_graph_edges.parquet").exists():
        assert imports_parquet.exists()
