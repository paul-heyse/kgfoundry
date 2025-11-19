#!/usr/bin/env python3
"""Typer CLI for orchestrating the index build pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from codeintel_rev.services.index import IndexBuildConfig, IndexPaths, run_index_build

VectorsDirOption = Annotated[
    Path,
    typer.Option(
        "--vectors-parquet-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Directory containing *.parquet shards with embeddings.",
    ),
]
PrimaryIndexOption = Annotated[
    Path,
    typer.Option(
        "--primary-index-path",
        resolve_path=True,
        help="Destination path for the primary FAISS index.",
    ),
]
IdmapPathOption = Annotated[
    Path,
    typer.Option(
        "--idmap-parquet-path",
        resolve_path=True,
        help="Destination for the {faiss_row -> external_id} Parquet sidecar.",
    ),
]
DuckDBPathOption = Annotated[
    Path | None,
    typer.Option(
        "--duckdb-path",
        resolve_path=True,
        help="Optional DuckDB catalog file used for registration/materialization.",
    ),
]
VecDimOption = Annotated[
    int,
    typer.Option("--vec-dim", min=1, help="Embedding dimensionality for the shards."),
]
IdColumnOption = Annotated[
    str,
    typer.Option("--id-col", help="Chunk identifier column name."),
]
VecColumnOption = Annotated[
    str,
    typer.Option("--vec-col", help="Embedding column name."),
]
SampleSizeOption = Annotated[
    int,
    typer.Option(
        "--sample-size",
        min=1,
        help="Maximum number of rows to sample for index training.",
    ),
]
BatchRowsOption = Annotated[
    int,
    typer.Option(
        "--batch-rows",
        min=1,
        help="Rows to load per batch when adding vectors to the index.",
    ),
]
MaterializeFlag = Annotated[
    bool,
    typer.Option(
        "--materialize/--no-materialize",
        help="Materialize the FAISS join inside DuckDB after registration.",
        show_default=True,
    ),
]

app = typer.Typer(
    add_completion=False,
    help="Build FAISS indexes and DuckDB metadata from Parquet shards.",
)


@app.command("all")
def cmd_all(  # noqa: PLR0913
    *,
    vectors_parquet_dir: VectorsDirOption,
    primary_index_path: PrimaryIndexOption,
    idmap_parquet_path: IdmapPathOption,
    duckdb_path: DuckDBPathOption = None,
    vec_dim: VecDimOption,
    id_col: IdColumnOption = "chunk_id",
    vec_col: VecColumnOption = "embedding",
    sample_size: SampleSizeOption = 50_000,
    batch_rows: BatchRowsOption = 50_000,
    materialize: MaterializeFlag = True,
) -> None:
    """Run the full index build pipeline.

    Parameters
    ----------
    vectors_parquet_dir : VectorsDirOption
        Directory containing Parquet shard files with embeddings. Must exist
        and contain *.parquet files.
    primary_index_path : PrimaryIndexOption
        Destination path for the primary FAISS index file. Parent directory
        will be created if needed.
    idmap_parquet_path : IdmapPathOption
        Destination path for the Parquet sidecar file mapping FAISS row indices
        to external chunk IDs.
    duckdb_path : DuckDBPathOption, optional
        Optional DuckDB catalog file path for index registration and view
        materialization. If None, DuckDB operations are skipped.
    vec_dim : VecDimOption
        Embedding dimensionality for the vectors. Must match the dimension
        of vectors in the Parquet files. Must be at least 1.
    id_col : IdColumnOption, optional
        Column name containing chunk identifiers in Parquet files. Defaults
        to "chunk_id".
    vec_col : VecColumnOption, optional
        Column name containing embedding vectors in Parquet files. Defaults
        to "embedding".
    sample_size : SampleSizeOption, optional
        Maximum number of rows to sample for index training. Defaults to 50_000.
        Must be at least 1.
    batch_rows : BatchRowsOption, optional
        Number of rows to load per batch when adding vectors to the index.
        Defaults to 50_000. Must be at least 1.
    materialize : MaterializeFlag, optional
        Whether to materialize the FAISS join view inside DuckDB after
        registration. Defaults to True.
    """
    paths = IndexPaths(
        vectors_parquet_dir=vectors_parquet_dir,
        primary_index_path=primary_index_path,
        idmap_parquet_path=idmap_parquet_path,
        duckdb_path=duckdb_path,
    )
    cfg = IndexBuildConfig(
        vec_dim=vec_dim,
        id_col=id_col,
        vec_col=vec_col,
        sample_size=sample_size,
        batch_rows=batch_rows,
        materialize=materialize,
    )
    state = run_index_build(paths, cfg)
    summary = [
        "index-all completed",
        f"  shards: {len(state.shards)}",
        f"  added_rows: {state.added_rows}",
        f"  idmap_rows: {state.idmap_rows}",
        f"  primary_index: {primary_index_path}",
        f"  idmap: {idmap_parquet_path}",
    ]
    typer.echo("\n".join(summary))


if __name__ == "__main__":
    app()
