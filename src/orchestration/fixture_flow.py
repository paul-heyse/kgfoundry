"""Overview of fixture flow.

This module bundles fixture flow logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from prefect import flow, task

from kgfoundry_common.models import Doc
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.parquet_io import ParquetChunkWriter, ParquetVectorWriter
from registry.helper import DuckDBRegistryHelper

if TYPE_CHECKING:
    from kgfoundry_common.parquet_io import ChunkRow

__all__ = [
    "fixture_pipeline",
    "t_prepare_dirs",
    "t_register_in_duckdb",
    "t_write_fixture_chunks",
    "t_write_fixture_dense",
    "t_write_fixture_splade",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor t_prepare_dirs]
def _t_prepare_dirs_impl(root: str) -> dict[str, bool]:
    """Prepare directory structure for fixture dataset.

    Creates necessary subdirectories for parquet outputs (dense, sparse,
    chunks) and catalog artifacts.

    Parameters
    ----------
    root : str
        Root directory path where fixture data will be stored.

    Returns
    -------
    dict[str, bool]
        Status dictionary with "ok" key set to True.
    """
    path = Path(root)
    (path / "parquet" / "dense").mkdir(parents=True, exist_ok=True)
    (path / "parquet" / "sparse").mkdir(parents=True, exist_ok=True)
    (path / "parquet" / "chunks").mkdir(parents=True, exist_ok=True)
    (path / "catalog").mkdir(parents=True, exist_ok=True)
    return {"ok": True}


# [nav:anchor t_prepare_dirs]
t_prepare_dirs = task(_t_prepare_dirs_impl)


# [nav:anchor t_write_fixture_chunks]
def _t_write_fixture_chunks_impl(chunks_root: str) -> tuple[str, int]:
    """Write fixture chunk data to parquet.

    Creates a fixture dataset with a single chunk entry for testing.

    Parameters
    ----------
    chunks_root : str
        Root directory for chunk parquet files.

    Returns
    -------
    tuple[str, int]
        Tuple of (dataset_root_path, row_count).
    """
    writer = ParquetChunkWriter(chunks_root, model="docling_hybrid", run_id="fixture")
    rows: list[ChunkRow] = [
        {
            "chunk_id": "urn:chunk:fixture:0-28",
            "doc_id": "urn:doc:fixture:0001",
            "section": "Intro",
            "start_char": 0,
            "end_char": 28,
            "doctags_span": {"node_id": "n1", "start": 0, "end": 28},
            "text": "Hello fixture text about LLMs",
            "tokens": 5,
            "created_at": 0,
        }
    ]
    dataset_root = writer.write(rows)
    return dataset_root, len(rows)


# [nav:anchor t_write_fixture_chunks]
t_write_fixture_chunks = task(_t_write_fixture_chunks_impl)


# [nav:anchor t_write_fixture_dense]
def _t_write_fixture_dense_impl(dense_root: str) -> tuple[str, int]:
    """Write fixture dense embedding vectors to parquet.

    Creates a fixture dataset with a single dense embedding vector
    using Qwen3-Embedding-4B model.

    Parameters
    ----------
    dense_root : str
        Root directory for dense embedding parquet files.

    Returns
    -------
    tuple[str, int]
        Tuple of (dataset_root_path, row_count).
    """
    writer = ParquetVectorWriter(dense_root)
    vector = [0.0] * 3584
    out_root = writer.write_dense(
        "Qwen3-Embedding-4B",
        "fixture",
        3584,
        [("urn:chunk:fixture:0-28", vector, 1.0)],
        shard=0,
    )
    return out_root, 1


# [nav:anchor t_write_fixture_dense]
t_write_fixture_dense = task(_t_write_fixture_dense_impl)


# [nav:anchor t_write_fixture_splade]
def _t_write_fixture_splade_impl(sparse_root: str) -> tuple[str, int]:
    """Write fixture sparse SPLADE vectors to parquet.

    Creates a fixture dataset with a single sparse embedding vector
    using SPLADE-v3-distilbert model.

    Parameters
    ----------
    sparse_root : str
        Root directory for sparse embedding parquet files.

    Returns
    -------
    tuple[str, int]
        Tuple of (dataset_root_path, row_count).
    """
    writer = ParquetVectorWriter(sparse_root)
    out_root = writer.write_splade(
        "SPLADE-v3-distilbert",
        "fixture",
        [("urn:chunk:fixture:0-28", [1, 7, 42], [0.3, 0.2, 0.1])],
        shard=0,
    )
    return out_root, 1


# [nav:anchor t_write_fixture_splade]
t_write_fixture_splade = task(_t_write_fixture_splade_impl)


# [nav:anchor t_register_in_duckdb]
def _t_register_in_duckdb_impl(
    db_path: str,
    chunks_info: tuple[str, int],
    dense_info: tuple[str, int],
    sparse_info: tuple[str, int],
) -> dict[str, list[str]]:
    """Register fixture datasets in DuckDB registry.

    Creates runs and datasets for chunks, dense, and sparse embeddings,
    then registers a fixture document.

    Parameters
    ----------
    db_path : str
        Path to DuckDB database file.
    chunks_info : tuple[str, int]
        Tuple of (chunks_dataset_path, row_count).
    dense_info : tuple[str, int]
        Tuple of (dense_dataset_path, row_count).
    sparse_info : tuple[str, int]
        Tuple of (sparse_dataset_path, row_count).

    Returns
    -------
    dict[str, list[str]]
        Dictionary with "runs" key containing list of run IDs.
    """
    registry = DuckDBRegistryHelper(db_path)
    dense_run = registry.new_run("dense_embed", "Qwen3-Embedding-4B", "main", {"dim": 3584})
    sparse_run = registry.new_run("splade_encode", "SPLADE-v3-distilbert", "main", {"topk": 256})

    ds_chunks = registry.begin_dataset("chunks", dense_run)
    registry.commit_dataset(ds_chunks, chunks_info[0], rows=chunks_info[1])

    ds_dense = registry.begin_dataset("dense", dense_run)
    registry.commit_dataset(ds_dense, dense_info[0], rows=dense_info[1])

    ds_sparse = registry.begin_dataset("sparse", sparse_run)
    registry.commit_dataset(ds_sparse, sparse_info[0], rows=sparse_info[1])

    registry.register_documents(
        [
            Doc(
                id="urn:doc:fixture:0001",
                title="Fixture Doc",
                authors=[],
                pdf_uri="/dev/null",
                source="fixture",
                openalex_id=None,
                doi=None,
                arxiv_id=None,
                pmcid=None,
                pub_date=None,
                license="CC0",
                language="en",
                content_hash="",
            )
        ]
    )
    registry.close_run(dense_run, success=True)
    registry.close_run(sparse_run, success=True)
    return {"runs": [dense_run, sparse_run]}


# [nav:anchor t_register_in_duckdb]
t_register_in_duckdb = task(_t_register_in_duckdb_impl)


# [nav:anchor fixture_pipeline]
def _fixture_pipeline_impl(
    root: str = "/data", db_path: str = "/data/catalog/catalog.duckdb"
) -> dict[str, list[str]]:
    """Execute the complete fixture pipeline flow.

    Orchestrates creation of fixture directories, writes chunk/dense/sparse
    parquet files, and registers everything in DuckDB registry.

    Parameters
    ----------
    root : str, optional
        Root directory for fixture data. Defaults to "/data".
    db_path : str, optional
        Path to DuckDB catalog database. Defaults to "/data/catalog/catalog.duckdb".

    Returns
    -------
    dict[str, list[str]]
        Dictionary with "runs" key containing list of created run IDs.
    """
    t_prepare_dirs(root)
    chunks_info = t_write_fixture_chunks(f"{root}/parquet/chunks")
    dense_info = t_write_fixture_dense(f"{root}/parquet/dense")
    sparse_info = t_write_fixture_splade(f"{root}/parquet/sparse")
    return _t_register_in_duckdb_impl(db_path, chunks_info, dense_info, sparse_info)


# [nav:anchor fixture_pipeline]
fixture_pipeline = flow(name="kgfoundry_fixture_pipeline")(_fixture_pipeline_impl)


if __name__ == "__main__":
    fixture_pipeline()
