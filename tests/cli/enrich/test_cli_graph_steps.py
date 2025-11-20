# ruff: noqa: S101 - pytest-style assertions are intentional.
"""Integration tests covering GOID/callgraph/CFG CLI commands."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.cli.enrich.__main__ import app  # noqa: PLC2701
from typer.testing import CliRunner


def _prepare_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    for required in (
        "config",
        "logs",
        ".cache",
        ".tmp",
        "plugins",
        "data",
        "data/faiss",
        "data/vectors",
    ):
        (repo / required).mkdir(parents=True, exist_ok=True)
    (repo / "config" / "app.yml").write_text("", encoding="utf-8")
    package = repo / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mod.py").write_text(
        "def callee() -> int:\n"
        "    value = 1\n"
        "    return value\n\n"
        "def caller() -> int:\n"
        "    total = callee()\n"
        "    return total\n",
        encoding="utf-8",
    )
    out_dir = repo / ".out"
    out_dir.mkdir(parents=True, exist_ok=True)
    return repo, out_dir


def test_goids_callgraph_cfg_cli_commands(tmp_path: Path) -> None:
    """CLI graph commands should emit artifacts and update DuckDB when requested."""
    runner = CliRunner()
    repo, out_dir = _prepare_repo(tmp_path)

    result_goids = runner.invoke(
        app,
        ["goids", "--repo-root", str(repo), "--out-dir", str(out_dir), "--ingest"],
        catch_exceptions=False,
    )
    assert result_goids.exit_code == 0, result_goids.output
    assert (out_dir / "goid" / "goids.parquet").exists()
    assert (out_dir / "goid" / "goid_xwalk.parquet").exists()

    result_callgraph = runner.invoke(
        app,
        ["callgraph", "--repo-root", str(repo), "--out-dir", str(out_dir), "--ingest"],
        catch_exceptions=False,
    )
    assert result_callgraph.exit_code == 0, result_callgraph.output
    assert (out_dir / "graphs" / "call_nodes.parquet").exists()
    assert (out_dir / "graphs" / "call_edges.parquet").exists()

    result_cfg = runner.invoke(
        app,
        ["cfg", "--repo-root", str(repo), "--out-dir", str(out_dir), "--ingest"],
        catch_exceptions=False,
    )
    assert result_cfg.exit_code == 0, result_cfg.output
    assert (out_dir / "graphs" / "cfg_blocks.parquet").exists()
    assert (out_dir / "graphs" / "cfg_edges.parquet").exists()

    result_dfg = runner.invoke(
        app,
        ["dfg", "--repo-root", str(repo), "--out-dir", str(out_dir), "--ingest"],
        catch_exceptions=False,
    )
    assert result_dfg.exit_code == 0, result_dfg.output
    assert (out_dir / "graphs" / "dfg_edges.parquet").exists()

    catalog = repo / "data" / "catalog.duckdb"
    assert catalog.exists(), "DuckDB catalog should be created when ingesting graph data."
