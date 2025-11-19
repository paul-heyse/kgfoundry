"""Business logic steps for the index build pipeline."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, DuckDBCatalogOptions
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.faiss_build import (
    IndexBuildConfig as FaissBuildConfig,
)
from codeintel_rev.io.faiss_build import (
    add_vectors as faiss_add_vectors,
)
from codeintel_rev.io.faiss_build import (
    build_primary_index,
    create_secondary_index,
)
from codeintel_rev.io.faiss_build import (
    save_index as faiss_save_index,
)
from codeintel_rev.io.faiss_store import (
    IndexArtifactPaths,
    export_idmap_parquet,
    save_secondary_index,
)
from codeintel_rev.services.index.plan import BuildState, IndexBuildConfig, IndexPaths
from codeintel_rev.typing import NDArrayF32, NDArrayI64

if TYPE_CHECKING:
    import numpy as np
else:  # pragma: no cover
    np = cast("np", LazyModule("numpy", "index build pipeline"))

_pq = LazyModule("pyarrow.parquet", "index build: parquet scanning")


def _parquet_shards(vectors_dir: Path) -> list[Path]:
    """Return all Parquet shards under ``vectors_dir``.

    Parameters
    ----------
    vectors_dir : Path
        Directory path to search recursively for Parquet files.

    Returns
    -------
    list[Path]
        Sorted list of all Parquet file paths found under ``vectors_dir``,
        including files in subdirectories.

    Raises
    ------
    FileNotFoundError
        Raised when ``vectors_dir`` does not exist.
    """
    if not vectors_dir.exists():
        msg = f"Vectors directory not found: {vectors_dir}"
        raise FileNotFoundError(msg)
    return sorted(vectors_dir.rglob("*.parquet"))


def _iter_batches(
    path: Path,
    *,
    columns: Sequence[str],
    batch_rows: int,
) -> Iterator[tuple[NDArrayI64, NDArrayF32]]:
    """Yield ``(ids, vectors)`` batches from ``path``.

    Parameters
    ----------
    path : Path
        Path to the Parquet file containing vector data.
    columns : Sequence[str]
        Column names to read from the Parquet file. First column must be
        integer IDs, second column must be vector arrays.
    batch_rows : int
        Number of rows to read per batch. Must be positive.

    Yields
    ------
    tuple[NDArrayI64, NDArrayF32]
        A tuple containing (ids, vectors) where ids is an int64 array of
        document identifiers and vectors is a float32 array of shape
        (batch_size, vector_dimension).

    Raises
    ------
    ValueError
        Raised when ``batch_rows`` is not positive.
    """
    if batch_rows <= 0:
        msg = "batch_rows must be positive"
        raise ValueError(msg)
    pq_mod = _pq.module()
    pf = pq_mod.ParquetFile(str(path))
    for record in pf.iter_batches(batch_size=batch_rows, columns=list(columns)):
        id_values = record.column(0).to_numpy(zero_copy_only=False)
        ids = cast("NDArrayI64", np.asarray(id_values, dtype="int64"))
        vec_lists = record.column(1).to_pylist()
        vectors = cast("NDArrayF32", np.asarray(vec_lists, dtype="float32"))
        yield ids, vectors


def _take_sample(
    shards: Sequence[Path],
    *,
    columns: Sequence[str],
    sample_size: int,
    vec_dim: int,
) -> NDArrayF32:
    """Collect up to ``sample_size`` vectors across ``shards`` for training.

    Parameters
    ----------
    shards : Sequence[Path]
        Parquet file paths to sample vectors from, processed in order until
        ``sample_size`` vectors are collected.
    columns : Sequence[str]
        Column names to read from each Parquet file. First column must be
        integer IDs, second column must be vector arrays.
    sample_size : int
        Maximum number of vectors to collect. If zero, returns an empty array.
    vec_dim : int
        Expected vector dimension. Used to create empty arrays when no
        vectors are found.

    Returns
    -------
    NDArrayF32
        A float32 array of shape (n_samples, vec_dim) containing up to
        ``sample_size`` vectors sampled from the shards. Returns an empty
        array of shape (0, vec_dim) if ``sample_size`` is zero or no vectors
        are found.
    """
    if sample_size <= 0:
        return cast("NDArrayF32", np.empty((0, vec_dim), dtype="float32"))
    pq_mod = _pq.module()
    remaining = sample_size
    samples: list[NDArrayF32] = []
    for shard in shards:
        if remaining <= 0:
            break
        pf = pq_mod.ParquetFile(str(shard))
        for record in pf.iter_batches(
            batch_size=min(remaining, sample_size), columns=list(columns)
        ):
            vec_lists = record.column(1).to_pylist()
            vectors = cast("NDArrayF32", np.asarray(vec_lists, dtype="float32"))
            if vectors.size == 0:
                continue
            take = min(remaining, vectors.shape[0])
            samples.append(cast("NDArrayF32", vectors[:take]))
            remaining -= take
            if remaining <= 0:
                break
    if not samples:
        return cast("NDArrayF32", np.empty((0, vec_dim), dtype="float32"))
    return cast("NDArrayF32", np.vstack(samples))


def _catalog(paths: IndexPaths, *, materialize: bool) -> DuckDBCatalog:
    """Return a DuckDB catalog bound to ``paths``.

    Parameters
    ----------
    paths : IndexPaths
        Index paths containing DuckDB catalog path and vector Parquet directory.
    materialize : bool
        Whether to materialize views immediately when creating the catalog.
        If True, views are computed and persisted; if False, views are
        registered but not computed until explicitly materialized.

    Returns
    -------
    DuckDBCatalog
        A DuckDB catalog instance configured with the specified paths and
        materialization policy, ready for ID map registration and join
        view operations.

    Raises
    ------
    ValueError
        Raised when ``paths.duckdb_path`` is ``None``.
    """
    if paths.duckdb_path is None:
        msg = "DuckDB path is required to build the catalog"
        raise ValueError(msg)
    manager = DuckDBManager(paths.duckdb_path)
    options = DuckDBCatalogOptions(materialize=materialize, manager=manager)
    return DuckDBCatalog(paths.duckdb_path, paths.vectors_parquet_dir, options=options)


def step_scan_shards(state: BuildState, paths: IndexPaths, _: IndexBuildConfig) -> None:
    """Find all Parquet shards that contain embeddings.

    Raises
    ------
    FileNotFoundError
        Raised when no Parquet shards are discovered.
    """
    shards = _parquet_shards(paths.vectors_parquet_dir)
    if not shards:
        msg = f"No Parquet shards found under {paths.vectors_parquet_dir}"
        raise FileNotFoundError(msg)
    state.shards = shards


def step_sample_training(state: BuildState, _: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Record how many samples are available for training.

    Raises
    ------
    ValueError
        Raised when zero vectors are available for training.
    """
    vecs = _take_sample(
        state.shards,
        columns=[cfg.id_col, cfg.vec_col],
        sample_size=cfg.sample_size,
        vec_dim=cfg.vec_dim,
    )
    state.sample_rows = int(vecs.shape[0])
    if state.sample_rows == 0:
        msg = "No vectors found for training"
        raise ValueError(msg)


def step_train_primary(state: BuildState, _: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Train the adaptive FAISS primary index.

    Raises
    ------
    ValueError
        Raised when no vectors are available to train the index.
    """
    vecs = _take_sample(
        state.shards,
        columns=[cfg.id_col, cfg.vec_col],
        sample_size=cfg.sample_size,
        vec_dim=cfg.vec_dim,
    )
    if vecs.shape[0] == 0:
        msg = "Cannot train primary index without vectors"
        raise ValueError(msg)
    faiss_cfg = FaissBuildConfig(vec_dim=cfg.vec_dim)
    primary, _label = build_primary_index(vecs, cfg=faiss_cfg)
    state.primary_index = primary


def step_add_all_vectors(state: BuildState, _: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Add every vector from every shard to the trained index.

    Raises
    ------
    RuntimeError
        Raised when the primary index has not been trained yet.
    """
    if state.primary_index is None:
        msg = "Primary index must be trained before adding vectors"
        raise RuntimeError(msg)
    total = 0
    for shard in state.shards:
        for ids, vectors in _iter_batches(
            shard,
            columns=[cfg.id_col, cfg.vec_col],
            batch_rows=cfg.batch_rows,
        ):
            if vectors.size == 0:
                continue
            faiss_add_vectors(state.primary_index, vectors, ids)
            total += int(ids.shape[0])
    state.added_rows = total


def step_persist_primary(state: BuildState, paths: IndexPaths, _: IndexBuildConfig) -> None:
    """Serialize the trained primary FAISS index.

    Raises
    ------
    RuntimeError
        Raised when the primary index has not been trained yet.
    """
    if state.primary_index is None:
        msg = "Primary index is not available"
        raise RuntimeError(msg)
    paths.primary_index_path.parent.mkdir(parents=True, exist_ok=True)
    faiss_save_index(state.primary_index, paths.primary_index_path)


def step_build_secondary(state: BuildState, _: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Construct the flat secondary index for incremental adds."""
    state.secondary_index = create_secondary_index(cfg.vec_dim)


def step_persist_secondary(state: BuildState, paths: IndexPaths, _: IndexBuildConfig) -> None:
    """Persist the secondary index as ``.secondary`` artifact.

    Raises
    ------
    RuntimeError
        Raised when the secondary index has not been built.
    """
    if state.secondary_index is None:
        msg = "Secondary index has not been built"
        raise RuntimeError(msg)
    art_paths = IndexArtifactPaths(primary_index_path=paths.primary_index_path)
    save_secondary_index(state.secondary_index, art_paths)


def step_export_idmap(state: BuildState, paths: IndexPaths, _: IndexBuildConfig) -> None:
    """Export ``{faiss_row -> external_id}`` Parquet sidecar.

    Raises
    ------
    RuntimeError
        Raised when the primary index has not been trained yet.
    """
    if state.primary_index is None:
        msg = "Primary index is not available"
        raise RuntimeError(msg)
    paths.idmap_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    state.idmap_rows = export_idmap_parquet(state.primary_index, paths.idmap_parquet_path)


def step_register_duckdb(state: BuildState, paths: IndexPaths, _: IndexBuildConfig) -> None:
    """Register the ID map in DuckDB and refresh the join view."""
    del state  # unused
    if paths.duckdb_path is None:
        return
    catalog = _catalog(paths, materialize=False)
    catalog.register_idmap_parquet(paths.idmap_parquet_path, materialize=False)


def step_materialize_join(state: BuildState, paths: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Materialize ``v_faiss_join`` when requested."""
    del state  # unused
    if not cfg.materialize or paths.duckdb_path is None:
        return
    catalog = _catalog(paths, materialize=True)
    catalog.materialize_faiss_join()
