"""Persistence helpers for FAISS indexes."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import duckdb

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.runtime.imports import gate_import

if TYPE_CHECKING:
    import numpy as np  # type: ignore[reportMissingImports]
else:
    np = cast("np", LazyModule("numpy", "faiss store operations"))
from codeintel_rev.io.duckdb_catalog import IdMapMeta, refresh_faiss_idmap_materialized
from codeintel_rev.typing import FaissIndex, NDArrayF32, NDArrayI64

if TYPE_CHECKING:
    from codeintel_rev.io.duckdb_catalog import DuckDBCatalog

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


def export_idmap_parquet(
    index: FaissIndex,
    out_path: Path,
    *,
    index_name: str | None = None,
    timestamp: datetime | None = None,
) -> int:
    """Persist ``{faiss_row -> external_id}`` to Parquet for DuckDB sync.

    Parameters
    ----------
    index : object
        FAISS index to export from.
    out_path : Path
        Destination Parquet file.
    index_name : str | None, optional
        Logical name of the FAISS index that produced this mapping. Defaults to
        ``out_path.name`` when not provided.
    timestamp : datetime | None, optional
        Timestamp applied to every exported row. Defaults to ``datetime.now(UTC)``.

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
    now = timestamp or datetime.now(UTC)
    resolved_index_name = index_name or out_path.name
    index_col = pa_mod.array([resolved_index_name] * row_count, type=pa_mod.string())
    ts_type = pa_mod.timestamp("us", tz="UTC")
    ts_col = pa_mod.array([now] * row_count, type=ts_type)
    table = pa_mod.table(
        {
            "faiss_row": pa_mod.array(rows),
            "external_id": pa_mod.array(ids),
            "index_name": index_col,
            "ts": ts_col,
        }
    )
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


def write_profile(
    index: FaissIndex | None,
    path: Path,
    faiss_family: str | None,
    refine_k_factor: float,
) -> None:
    """Persist a minimal profile snapshot describing a FAISS index.

    Parameters
    ----------
    index : FaissIndex | None
        FAISS index to profile, or None.
    path : Path
        Destination path for the profile JSON.
    faiss_family : str | None
        Family name (e.g., "adaptive", "flat", "ivfpq"), or None.
    refine_k_factor : float
        Refinement k factor setting.
    """
    if index is None:
        return
    if faiss_family is None:
        return
    profile = {
        "dims": int(getattr(index, "d", 0)),
        "ntotal": int(getattr(index, "ntotal", 0)),
        "is_trained": bool(getattr(index, "is_trained", False)),
        "type_name": type(index).__name__,
        "faiss_family": faiss_family,
        "refine_k_factor": refine_k_factor,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2, sort_keys=True), encoding="utf-8")


def meta_snapshot(  # noqa: PLR0913,PLR0917
    index_path: Path,
    vec_dim: int,
    faiss_family: str | None,
    default_nprobe: int | None,
    hnsw_ef_search: int,
    refine_k_factor: float,
    meta_path: Path,
) -> dict[str, object]:
    """Return persisted metadata merged with current configuration.

    Returns
    -------
    dict[str, object]
        Dictionary containing index metadata including index_path,
        factory, dimension, and other configuration values.
    """
    snapshot: dict[str, object]
    if meta_path.exists():
        try:
            snapshot = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            snapshot = {}
    else:
        snapshot = {}
    snapshot.update(
        {
            "index_path": str(index_path),
            "vec_dim": vec_dim,
            "faiss_family": faiss_family,
            "default_parameters": {
                "nprobe": default_nprobe,
                "efSearch": hnsw_ef_search,
                "quantizer_efSearch": None,
                "k_factor": refine_k_factor,
            },
        }
    )
    return snapshot


def write_meta_snapshot(  # noqa: PLR0913
    *,
    index_path: Path,
    vec_dim: int,
    faiss_family: str | None,
    default_nprobe: int | None,
    hnsw_ef_search: int,
    refine_k_factor: float,
    meta_path: Path,
    runtime_overrides: Mapping[str, float | int] | None = None,
    factory: str | None = None,
    vector_count: int | None = None,
    parameter_space: str | None = None,
) -> None:
    """Write the metadata snapshot to disk with updated overrides."""
    meta = meta_snapshot(
        index_path,
        vec_dim,
        faiss_family,
        default_nprobe,
        hnsw_ef_search,
        refine_k_factor,
        meta_path,
    )
    if factory is not None:
        meta["factory"] = factory
    if vector_count is not None:
        meta["vector_count"] = int(vector_count)
    if parameter_space is not None:
        meta["parameter_space"] = parameter_space
    meta["runtime_overrides"] = dict(runtime_overrides or {})
    meta["compile_options"] = get_compile_options()
    meta["updated_at"] = datetime.now(UTC).isoformat()
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def get_compile_options() -> str:
    """Return FAISS compile options string when available.

    Returns
    -------
    str
        Compile-time configuration string for FAISS, including enabled
        features and build flags. Returns an empty string if compile options
        are not available.
    """
    try:
        faiss_mod = _faiss.module()
        return str(getattr(faiss_mod, "get_compile_options", lambda: "")())
    except (AttributeError, ImportError, RuntimeError):
        return ""


def save_tuning_profile(profile: Mapping[str, Any], path: Path) -> Path:
    """Persist tuning profile to tuning.json and return its path.

    Parameters
    ----------
    profile : Mapping[str, Any]
        Autotune profile dictionary containing tuning results.
    path : Path
        Destination path for the profile.

    Returns
    -------
    Path
        File system path where the tuning profile was saved.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return path


def load_tuned_profile(path: Path) -> dict[str, Any] | None:
    """Load a persisted tuning profile from disk.

    Parameters
    ----------
    path : Path
        Path to the tuning.json profile file.

    Returns
    -------
    dict[str, Any] | None
        Loaded profile dictionary or None if file doesn't exist or is invalid.
    """
    if not path.exists():
        return None
    try:
        return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return None


def hydrate_by_ids(catalog: DuckDBCatalog, ids: Sequence[int]) -> list[dict]:
    """Hydrate chunk metadata for ``ids`` via the provided DuckDB catalog.

    Parameters
    ----------
    catalog : DuckDBCatalog
        Catalog used to hydrate chunk metadata.
    ids : Sequence[int]
        Chunk identifiers to hydrate.

    Returns
    -------
    list[dict]
        Hydrated chunk metadata entries.
    """
    if not ids:
        return []
    return catalog.query_by_ids(list(ids))


def reconstruct_batch(index: FaissIndex, vec_dim: int, ids: Sequence[int]) -> NDArrayF32:
    """Reconstruct vectors for a batch of external chunk IDs.

    Parameters
    ----------
    index : FaissIndex
        FAISS index to reconstruct from.
    vec_dim : int
        Vector dimensionality.
    ids : Sequence[int]
        Chunk identifiers to reconstruct.

    Returns
    -------
    NDArrayI64
        Array of reconstructed vectors with shape ``(len(ids), vec_dim)``.

    Raises
    ------
    RuntimeError
        If FAISS is unable to reconstruct a specific vector.
    """
    if not ids:
        return np.empty((0, vec_dim), dtype=np.float32)

    # Enable direct map for reconstruction
    try:
        if hasattr(index, "make_direct_map"):
            index.make_direct_map()
        inner = getattr(index, "index", None)
        if inner is not None and hasattr(inner, "make_direct_map"):
            inner.make_direct_map()
    except (AttributeError, RuntimeError):
        pass

    vectors = np.empty((len(ids), vec_dim), dtype=np.float32)
    for pos, chunk_id in enumerate(ids):
        try:
            reconstructed = index.reconstruct(int(chunk_id))
        except (AttributeError, RuntimeError) as exc:
            msg = f"Unable to reconstruct FAISS vector for chunk_id {chunk_id}"
            raise RuntimeError(msg) from exc
        vectors[pos] = np.asarray(reconstructed, dtype=np.float32)
    return vectors
