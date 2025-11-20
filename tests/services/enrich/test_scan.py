# SPDX-License-Identifier: MIT
"""Tests for scan service helpers."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, DuckDBCatalogOptions
from codeintel_rev.services.enrich import scan
from codeintel_rev.services.enrich.context import PipelineOptions

from tests._helpers import assertions
from tests._helpers.repo import SampleRepo, bootstrap_sample_repo


def test_iter_python_files_skips_hidden_and_auxiliary_dirs(tmp_path: Path) -> None:
    """Verify iter_python_files excludes hidden, stubs, and overlays directories."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".venv").mkdir()
    (repo / ".venv" / "ignored.py").write_text("", encoding="utf-8")
    (repo / "stubs").mkdir()
    (repo / "stubs" / "overlay.py").write_text("", encoding="utf-8")
    (repo / "pkg").mkdir()
    target = repo / "pkg" / "app.py"
    target.write_text("print('ok')\n", encoding="utf-8")

    discovered = list(scan.iter_python_files(repo))
    assertions.expect_sequence_equal(discovered, [target.resolve()])


def test_discover_python_files_honors_patterns(tmp_path: Path) -> None:
    """Ensure discover_python_files respects include globs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pkg").mkdir()
    (repo / "pkg" / "app.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "internal.py").write_text("", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("", encoding="utf-8")

    files = scan.discover_python_files(repo, ("pkg/app.py",))
    assertions.expect_sequence_equal(files, [repo / "pkg" / "app.py"])


def _ensure_app_layout(repo: Path) -> None:
    """Create directories/files required by resolve_application_paths validation."""
    config_dir = repo / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "app.yml").write_text("{}", encoding="utf-8")
    for rel in ("logs", ".cache", ".tmp", "plugins", "data", "data/faiss", "data/vectors"):
        (repo / rel).mkdir(parents=True, exist_ok=True)


def _graph_pipeline_options(tmp_path: Path) -> tuple[SampleRepo, PipelineOptions]:
    repo_bundle = bootstrap_sample_repo(tmp_path)
    _ensure_app_layout(repo_bundle.root)
    data_dir = repo_bundle.root / "data"
    pipeline_options = PipelineOptions(
        root=repo_bundle.root,
        scip=repo_bundle.scip_path,
        out=data_dir,
        coverage_xml=repo_bundle.root / "coverage.xml",
        build_goids=True,
        build_callgraph=True,
        build_cfg=True,
        build_dfg=True,
    )
    return repo_bundle, pipeline_options


def test_run_pipeline_executes_graph_steps(tmp_path: Path) -> None:
    """Running the pipeline with graph flags should emit artifacts and ingest DuckDB."""
    repo_bundle, options = _graph_pipeline_options(tmp_path)

    result = scan.run_pipeline(pipeline=options)
    assert result.module_rows, "Pipeline should emit module rows"

    data_dir = repo_bundle.root / "data"
    assert (data_dir / "goid" / "goids.parquet").exists()
    assert (data_dir / "goid" / "goid_xwalk.parquet").exists()
    assert (data_dir / "graphs" / "call_nodes.parquet").exists()
    assert (data_dir / "graphs" / "call_edges.parquet").exists()
    assert (data_dir / "graphs" / "cfg_blocks.parquet").exists()
    assert (data_dir / "graphs" / "cfg_edges.parquet").exists()
    assert (data_dir / "graphs" / "dfg_edges.parquet").exists()

    catalog = DuckDBCatalog(
        data_dir / "catalog.duckdb",
        data_dir / "vectors",
        options=DuckDBCatalogOptions(repo_root=repo_bundle.root),
    )
    try:
        with catalog.connection() as conn:
            goids_count = conn.execute("SELECT COUNT(*) FROM goids").fetchone()[0]
            call_edges_count = conn.execute("SELECT COUNT(*) FROM call_edges").fetchone()[0]
            cfg_blocks_count = conn.execute("SELECT COUNT(*) FROM cfg_blocks").fetchone()[0]
            dfg_edges_count = conn.execute("SELECT COUNT(*) FROM dfg_edges").fetchone()[0]
        assert goids_count > 0
        assert call_edges_count > 0
        assert cfg_blocks_count > 0
        assert dfg_edges_count > 0
    finally:
        catalog.close()
