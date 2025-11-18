"""Persistence helpers for FAISS indexes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import duckdb
import numpy as np

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.io.duckdb_catalog import IdMapMeta, refresh_faiss_idmap_materialized
from codeintel_rev.typing import NDArrayI64, gate_import

if TYPE_CHECKING:  # pragma: no cover - typing only
    import faiss as _faiss_module

    FaissIndex = _faiss_module.Index
else:  # pragma: no cover - runtime fallback
    FaissIndex = Any

_faiss = LazyModule("faiss", "FAISS store helpers")
_pyarrow = LazyModule("pyarrow", "ID map export helpers")
_pyarrow_parquet = LazyModule("pyarrow.parquet", "ID map export helpers")


@dataclass(frozen=True, slots=True)
class IndexArtifactPaths:
    """Filesystem layout for FAISS index artifacts."""

    primary_index_path: Path
    secondary_suffix: str = ".secondary"

    @property
    def secondary_index_path(self) -> Path:
        """Return the sibling path for secondary index persistence."""
        base = self.primary_index_path
        return base.parent / f"{base.stem}{self.secondary_suffix}{base.suffix}"


def get_idmap_array(index: FaissIndex) -> NDArrayI64:
    """Extract the ID map array from an ID-mapped FAISS index.

    Parameters
    ----------
    index : object
        ID-mapped FAISS index.

    Returns
    -------
    NDArrayI64
        Mapping where ``array[row]`` equals the external chunk ID.

    Raises
    ------
    RuntimeError
        If the index is not wrapped with ``IndexIDMap2``.
    TypeError
        If neither ``vector_to_array`` nor ``at`` helpers are available.
    """
    gate_import("faiss", "Accessing FAISS ID maps")
    faiss_mod = _faiss.module()
    id_map_obj = getattr(index, "id_map", None)
    if id_map_obj is None:
        msg = "FAISS index must be wrapped in IndexIDMap2 to export ID maps."
        raise RuntimeError(msg)
    vector_to_array = getattr(faiss_mod, "vector_to_array", None)
    if callable(vector_to_array):
        array = np.asarray(vector_to_array(id_map_obj), dtype=np.int64)
        if array.ndim == 1:
            return array
    ntotal = int(getattr(index, "ntotal", 0))
    ids = np.empty(ntotal, dtype=np.int64)
    at_method = getattr(id_map_obj, "at", None)
    if callable(at_method):
        id_accessor = cast("Callable[[int], int]", at_method)
        for row in range(ntotal):
            ids[row] = int(id_accessor(row))
        return ids
    msg = "Unable to extract FAISS id_map array."
    raise TypeError(msg)


def export_idmap_parquet(index: FaissIndex, out_path: Path) -> int:
    """Persist ``{faiss_row -> external_id}`` to Parquet for DuckDB sync.

    Parameters
    ----------
    index : object
        FAISS index to export from.
    out_path : Path
        Destination Parquet file.

    Returns
    -------
    int
        Number of ID rows exported.
    """
    gate_import("pyarrow", "Exporting FAISS ID map to Parquet")
    pa_mod = _pyarrow.module()
    pq_mod = _pyarrow_parquet.module()
    ids = get_idmap_array(index)
    row_count = int(ids.shape[0])
    rows = np.arange(row_count, dtype=np.int64)
    table = pa_mod.table({"faiss_row": pa_mod.array(rows), "external_id": pa_mod.array(ids)})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq_mod.write_table(table, str(out_path))
    return int(table.num_rows)


def save_secondary_index(index: FaissIndex, paths: IndexArtifactPaths) -> None:
    """Persist the in-memory secondary index."""
    gate_import("faiss", "Saving FAISS secondary index")
    faiss_mod = _faiss.module()
    faiss_mod.write_index(index, str(paths.secondary_index_path))


def load_secondary_index(paths: IndexArtifactPaths) -> FaissIndex:
    """Load the persisted secondary index.

    Parameters
    ----------
    paths : IndexArtifactPaths
        Artifact path helper.

    Returns
    -------
    object
        Loaded FAISS secondary index.
    """
    gate_import("faiss", "Loading FAISS secondary index")
    faiss_mod = _faiss.module()
    return faiss_mod.read_index(str(paths.secondary_index_path))


def refresh_duckdb_materialization(
    conn: duckdb.DuckDBPyConnection, idmap_parquet: Path, chunks_parquet: Path
) -> IdMapMeta:
    """Delegate to ``refresh_faiss_idmap_materialized`` for CLI flows.

    Parameters
    ----------
    conn : object
        DuckDB connection handle.
    idmap_parquet : Path
        Path to the ID map Parquet.
    chunks_parquet : Path
        Path to the chunk metadata Parquet file.

    Returns
    -------
    dict
        Metadata describing the refresh result.
    """
    return refresh_faiss_idmap_materialized(
        conn,
        idmap_parquet=str(idmap_parquet),
        chunks_parquet=str(chunks_parquet),
    )
