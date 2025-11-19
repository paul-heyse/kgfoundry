"""CLI utilities for building the CodeRank FAISS index."""

from __future__ import annotations

import os
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import numpy as np
import typer
from codeintel_rev.app import readiness as fs_readiness
from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config import load_app_config
from codeintel_rev.config.api import AppConfig
from codeintel_rev.config.helpers import index_settings
from codeintel_rev.config.paths import ResolvedPaths
from codeintel_rev.config.settings import Settings
from codeintel_rev.config.shim import settings_from_app_config
from codeintel_rev.io.coderank_embedder import CodeRankEmbedder
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.faiss_manager import FAISSManager, FAISSRuntimeOptions

app = typer.Typer(no_args_is_help=True, add_completion=False)


@lru_cache(maxsize=1)
def _cached_app_config() -> AppConfig:
    return load_app_config(file=os.environ.get("CODEINTEL_CONFIG_FILE"))


@lru_cache(maxsize=1)
def _legacy_settings() -> Settings:
    return settings_from_app_config(_cached_app_config())


@lru_cache(maxsize=1)
def _cached_paths() -> ResolvedPaths:
    return resolve_application_paths(_cached_app_config())


@app.command("build-index")
def build_index() -> None:
    """Embed all catalog chunks with CodeRank and persist a FAISS index.

    Raises
    ------
    typer.Exit
        If the DuckDB catalog does not contain any chunks.
    """
    app_config = _cached_app_config()
    settings = _legacy_settings()
    paths = _cached_paths()
    index_cfg = index_settings(app_config)
    fs_readiness.raise_on_errors(fs_readiness.validate_paths(paths))
    cfg = settings.coderank

    embedder = CodeRankEmbedder(settings=cfg)

    duckdb_manager = DuckDBManager(paths.duckdb_path, settings.duckdb)
    catalog = DuckDBCatalog(
        db_path=paths.duckdb_path,
        vectors_dir=paths.vectors_dir,
        materialize=index_cfg.duckdb_materialize,
        manager=duckdb_manager,
        repo_root=paths.repo_root,
    )
    catalog.open()
    try:
        with catalog.connection() as conn:
            rows = conn.sql(
                """
                SELECT id, COALESCE(content, preview, '') AS payload
                FROM chunks
                ORDER BY id
                """
            ).fetchall()
    finally:
        catalog.close()

    if not rows:
        typer.echo("No chunks available in DuckDB catalog; aborting.", err=True)
        raise typer.Exit(code=1)

    chunk_ids = [int(row[0]) for row in rows]
    snippets: Sequence[str] = [str(row[1] or "") for row in rows]
    typer.echo(f"Embedding {len(chunk_ids)} chunks with CodeRank...")
    vectors = embedder.encode_codes(snippets)

    index_path = Path(paths.coderank_faiss_index)
    runtime_opts = FAISSRuntimeOptions(
        faiss_family=index_cfg.faiss_family,
        pq_m=index_cfg.pq_m,
        pq_nbits=index_cfg.pq_nbits,
        opq_m=index_cfg.opq_m,
        default_nprobe=index_cfg.default_nprobe,
        default_k=index_cfg.default_k,
        hnsw_m=index_cfg.hnsw_m,
        hnsw_ef_construction=index_cfg.hnsw_ef_construction,
        hnsw_ef_search=index_cfg.hnsw_ef_search,
        refine_k_factor=index_cfg.refine_k_factor,
        autotune_on_start=index_cfg.autotune_on_start,
        enable_range_search=index_cfg.enable_range_search,
        semantic_min_score=index_cfg.semantic_min_score,
    )
    nlist_value = index_cfg.nlist or index_cfg.faiss_nlist
    manager = FAISSManager(
        index_path=index_path,
        vec_dim=vectors.shape[1],
        nlist=int(nlist_value),
        runtime=runtime_opts,
    )
    manager.build_index(vectors.copy(), family=index_cfg.faiss_family)
    manager.add_vectors(vectors, np.asarray(chunk_ids, dtype=np.int64))
    manager.save_cpu_index()
    typer.echo(f"Saved CodeRank FAISS index to {index_path}")


def main() -> None:  # pragma: no cover - CLI entrypoint
    """Execute the CodeRank CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
