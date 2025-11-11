"""CLI utilities for building the CodeRank FAISS index."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import typer
from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config.settings import Settings, load_settings
from codeintel_rev.io.coderank_embedder import CodeRankEmbedder
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.faiss_manager import FAISSManager, FAISSRuntimeOptions

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command("build-index")
def build_index() -> None:
    """Embed all catalog chunks with CodeRank and persist a FAISS index.

    Raises
    ------
    typer.Exit
        If the DuckDB catalog does not contain any chunks.
    """
    settings: Settings = load_settings()
    paths = resolve_application_paths(settings)
    cfg = settings.coderank

    embedder = CodeRankEmbedder(settings=cfg)

    duckdb_manager = DuckDBManager(paths.duckdb_path, settings.duckdb)
    catalog = DuckDBCatalog(
        paths.duckdb_path,
        paths.vectors_dir,
        materialize=settings.index.duckdb_materialize,
        manager=duckdb_manager,
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
        faiss_family=settings.index.faiss_family,
        pq_m=settings.index.pq_m,
        pq_nbits=settings.index.pq_nbits,
        opq_m=settings.index.opq_m,
        default_nprobe=settings.index.default_nprobe,
        default_k=settings.index.default_k,
        hnsw_m=settings.index.hnsw_m,
        hnsw_ef_construction=settings.index.hnsw_ef_construction,
        hnsw_ef_search=settings.index.hnsw_ef_search,
        refine_k_factor=settings.index.refine_k_factor,
        use_gpu=settings.index.use_gpu,
        gpu_clone_mode=settings.index.gpu_clone_mode,
        autotune_on_start=settings.index.autotune_on_start,
        enable_range_search=settings.index.enable_range_search,
        semantic_min_score=settings.index.semantic_min_score,
    )
    manager = FAISSManager(
        index_path=index_path,
        vec_dim=vectors.shape[1],
        nlist=settings.index.nlist,
        use_cuvs=settings.index.use_cuvs,
        runtime=runtime_opts,
    )
    manager.build_index(vectors.copy(), family=settings.index.faiss_family)
    manager.add_vectors(vectors, np.asarray(chunk_ids, dtype=np.int64))
    manager.save_cpu_index()
    typer.echo(f"Saved CodeRank FAISS index to {index_path}")


def main() -> None:  # pragma: no cover - CLI entrypoint
    """Execute the CodeRank CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
