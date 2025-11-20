"""Factory functions for creating test ApplicationContext instances.

This module provides utilities for constructing ApplicationContext instances
configured for testing, supporting both real repository data and synthetic
test fixtures based on environment configuration.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.config.paths import ResolvedPaths, resolve_application_paths

from tests._helpers.integration import build_integration_harness
from tests._helpers.settings import build_app_config_from_paths

_REAL_DATA_ENV = os.getenv("KGFOUNDRY_TEST_USE_REAL_DATA")
if _REAL_DATA_ENV is None:
    _USE_REAL_DATA = False
else:
    _USE_REAL_DATA = _REAL_DATA_ENV.strip().lower() not in {"0", "false", "no"}
_REPO_ROOT_OVERRIDE = os.getenv("KGFOUNDRY_TEST_REPO_ROOT")


def _real_paths(repo_root: Path) -> ResolvedPaths:
    """Resolve application paths using real repository data artifacts.

    Parameters
    ----------
    repo_root : Path
        Repository root directory containing real data artifacts (FAISS indexes,
        DuckDB catalogs, SCIP indexes, etc.).

    Returns
    -------
    ResolvedPaths
        Resolved paths pointing to real data artifacts in the repository.

    Raises
    ------
    FileNotFoundError
        If required data artifacts are missing from the repository. The error
        message lists all missing paths and suggests running the indexing
        pipeline or disabling real-data mode.
    """
    data_dir = repo_root / "data"
    vectors_dir = data_dir / "vectors"
    faiss_dir = data_dir / "faiss"
    faiss_index = faiss_dir / "code.ivfpq.faiss"
    faiss_idmap = faiss_dir / "faiss_idmap.parquet"
    duckdb_path = data_dir / "catalog.duckdb"
    scip_index = repo_root / "codeintel_rev" / "index.scip.json"

    missing = [
        path
        for path in (
            data_dir,
            vectors_dir,
            faiss_dir,
            faiss_index,
            faiss_idmap,
            duckdb_path,
            scip_index,
        )
        if not path.exists()
    ]
    if missing:
        parts: list[str] = []
        for path in missing:
            try:
                parts.append(str(path.relative_to(repo_root)))
            except ValueError:
                parts.append(str(path))
        formatted = ", ".join(parts)
        message = (
            "Real-data fixtures enabled but missing required artifacts: "
            f"{formatted}. Run the indexing pipeline or set "
            "KGFOUNDRY_TEST_USE_REAL_DATA=0 to fall back to synthetic fixtures."
        )
        raise FileNotFoundError(message)

    overrides = {
        "BASE_DIR": repo_root,
        "SCIP_INDEX": scip_index,
    }
    return resolve_application_paths(overrides)


def _synthetic_paths(tmp_path: Path) -> ResolvedPaths:
    """Create synthetic test paths and directory structure.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path where synthetic repository structure should
        be created.

    Returns
    -------
    ResolvedPaths
        Resolved paths pointing to synthetic test fixtures including empty
        FAISS index files, DuckDB catalog, SCIP index, and configuration
        directories.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    data_dir = repo_root / "data"
    subdirs = {
        "vectors": data_dir / "vectors",
        "faiss": data_dir / "faiss",
        "coderank_vectors": data_dir / "coderank_vectors",
        "lucene": data_dir / "lucene",
        "splade": data_dir / "splade",
        "xtr": data_dir / "xtr",
    }
    warp_dir = repo_root / "indexes" / "warp_xtr"

    for directory in (data_dir, *subdirs.values(), warp_dir):
        directory.mkdir(parents=True, exist_ok=True)

    files = {
        "faiss_index": subdirs["faiss"] / "code.ivfpq.faiss",
        "faiss_idmap": subdirs["faiss"] / "faiss_idmap.parquet",
        "coderank_index": subdirs["faiss"] / "coderank.ivfpq.faiss",
        "duckdb_path": data_dir / "catalog.duckdb",
        "scip_index": repo_root / "index.scip",
    }
    for path in files.values():
        path.touch()

    config_dir = repo_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "app.yml"
    config_file.write_text("test: true")

    for directory in (
        repo_root / "logs",
        repo_root / ".cache",
        repo_root / ".tmp",
        repo_root / "plugins",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    overrides = {
        "BASE_DIR": repo_root,
        "SCIP_INDEX": files["scip_index"],
    }
    return resolve_application_paths(overrides)


def _prepare_paths(tmp_path: Path) -> ResolvedPaths:
    """Return ResolvedPaths backed by either real repo data or synthetic fixtures.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory used when creating synthetic fixtures.

    Returns
    -------
    ResolvedPaths
        Paths pointing to either the real repository layout or synthetic test data.

    """
    if _USE_REAL_DATA:
        repo_root = (
            Path(_REPO_ROOT_OVERRIDE).expanduser().resolve()
            if _REPO_ROOT_OVERRIDE
            else Path(__file__).resolve().parents[2]
        )
        return _real_paths(repo_root)
    return _synthetic_paths(tmp_path)


def build_application_context(
    tmp_path: Path,
    *,
    xtr_enabled: bool = False,
    enable_bm25: bool = False,
    enable_splade: bool = False,
    seed_coderank_runtime: bool = False,
) -> ApplicationContext:
    """Create a lightweight ApplicationContext for unit tests.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path for creating test repository structure.
    xtr_enabled : bool, optional
        Whether to enable XTR (extraction) features, by default False.
    enable_bm25 : bool, optional
        Whether to enable BM25 search channel, by default False.
    enable_splade : bool, optional
        Whether to enable SPLADE search channel, by default False.
    seed_coderank_runtime : bool, optional
        Whether to pre-seed the CodeRank FAISS runtime cell. Defaults to False
        to allow tests to exercise missing/index gating paths.

    Returns
    -------
    ApplicationContext
        Configured application context with mocked dependencies for testing.
    """
    paths = _prepare_paths(tmp_path)
    app_config = build_app_config_from_paths(paths)
    bm25_index_dir = paths.lucene_dir / "bm25"
    bm25_corpus_dir = paths.data_dir / "bm25_json"
    splade_vectors_dir = paths.data_dir / "splade_vectors"
    splade_index_dir = paths.splade_dir / "impact"
    splade_model_dir = paths.repo_root / "models" / "splade"
    splade_onnx_dir = splade_model_dir / "onnx"
    for directory in (
        bm25_index_dir,
        bm25_corpus_dir,
        splade_vectors_dir,
        splade_index_dir,
        splade_model_dir,
        splade_onnx_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    bm25_cfg = replace(
        app_config.bm25,
        enabled=enable_bm25,
        index_dir=bm25_index_dir,
        corpus_json_dir=bm25_corpus_dir,
    )
    splade_cfg = replace(
        app_config.splade,
        enabled=enable_splade,
        vectors_dir=splade_vectors_dir,
        index_dir=splade_index_dir,
        model_dir=splade_model_dir,
        onnx_dir=splade_onnx_dir,
    )
    xtr_cfg = replace(app_config.xtr, enable=xtr_enabled)
    app_config = replace(app_config, bm25=bm25_cfg, splade=splade_cfg, xtr=xtr_cfg)
    harness = build_integration_harness(tmp_path, populate_repo=False)
    base_context = harness.context
    ctx = base_context.with_overrides(app_config=app_config)
    if seed_coderank_runtime:
        ctx.seed_runtime_cells_for_tests(coderank_faiss=ctx.faiss_manager)
    return ctx
