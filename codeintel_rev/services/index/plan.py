"""Declarative plan types for the index build pipeline."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from codeintel_rev.typing import FaissIndex

__all__ = [
    "BuildState",
    "IndexBuildConfig",
    "IndexPaths",
    "StepName",
    "StepRegistry",
    "StepRunner",
]

StepName = Literal[
    "scan_shards",
    "sample_training",
    "train_primary",
    "add_all_vectors",
    "persist_primary",
    "build_secondary",
    "persist_secondary",
    "export_idmap",
    "register_duckdb",
    "materialize_join",
]

StepFunc = Callable[["BuildState", "IndexPaths", "IndexBuildConfig"], None]


@dataclass(frozen=True, slots=True)
class IndexPaths:
    """Filesystem locations used by the index build.

    Attributes
    ----------
    vectors_parquet_dir : Path
        Directory containing Parquet shard files with vector embeddings.
        Must exist and contain *.parquet files.
    primary_index_path : Path
        Destination path for the primary FAISS index file. Parent directory
        will be created if needed during index building.
    idmap_parquet_path : Path
        Destination path for the Parquet sidecar file mapping FAISS row indices
        to external chunk IDs. Used for ID translation during search.
    duckdb_path : Path | None, optional
        Optional DuckDB catalog file path for index registration and view
        materialization. If None, DuckDB operations are skipped. Defaults to None.
    """

    vectors_parquet_dir: Path
    primary_index_path: Path
    idmap_parquet_path: Path
    duckdb_path: Path | None = None


@dataclass(frozen=True, slots=True)
class IndexBuildConfig:
    """Pure configuration knobs for the index pipeline.

    Attributes
    ----------
    vec_dim : int
        Embedding dimensionality for the vectors. Must match the dimension
        of vectors in the Parquet files. Must be at least 1.
    id_col : str, optional
        Column name containing chunk identifiers in Parquet files. Defaults
        to "chunk_id".
    vec_col : str, optional
        Column name containing embedding vectors in Parquet files. Defaults
        to "embedding".
    sample_size : int, optional
        Maximum number of rows to sample for index training. Defaults to 50_000.
        Larger samples improve index quality but increase training time.
    batch_rows : int, optional
        Number of rows to load per batch when adding vectors to the index.
        Defaults to 50_000. Larger batches improve throughput but require
        more memory.
    materialize : bool, optional
        Whether to materialize the FAISS join view inside DuckDB after
        registration. Defaults to True. Materialization improves query
        performance but requires additional storage and computation.
    """

    vec_dim: int
    id_col: str = "chunk_id"
    vec_col: str = "embedding"
    sample_size: int = 50_000
    batch_rows: int = 50_000
    materialize: bool = True


@dataclass(slots=True)
class BuildState:
    """Mutable state shared between plan steps.

    Attributes
    ----------
    shards : list[Path]
        List of Parquet shard file paths discovered during scanning. Populated
        by the scan_shards step and used by subsequent steps for vector loading.
    sample_rows : int
        Number of rows sampled for index training. Populated by the
        sample_training step. Defaults to 0.
    primary_index : FaissIndex | None
        Primary FAISS index instance after training and vector addition.
        Populated by train_primary and add_all_vectors steps. Defaults to None.
    secondary_index : FaissIndex | None
        Secondary FAISS index instance after building. Populated by the
        build_secondary step. Defaults to None.
    added_rows : int
        Number of rows added to the primary index. Incremented during
        add_all_vectors step. Defaults to 0.
    idmap_rows : int
        Number of rows in the ID map Parquet file. Populated by the
        export_idmap step. Defaults to 0.
    """

    shards: list[Path] = field(default_factory=list)
    sample_rows: int = 0
    primary_index: FaissIndex | None = None
    secondary_index: FaissIndex | None = None
    added_rows: int = 0
    idmap_rows: int = 0


@dataclass(frozen=True, slots=True)
class StepRegistry:
    """Immutable registry mapping step names to implementations."""

    mapping: Mapping[StepName, StepFunc]

    def resolve(self, name: StepName) -> StepFunc:
        """Return the callable registered for ``name``.

        Parameters
        ----------
        name : StepName
            Step name identifier to resolve.

        Returns
        -------
        StepFunc
            Callable step function registered for the given name.

        Raises
        ------
        KeyError
            If the step name is not registered in the mapping.
        """
        step = self.mapping.get(name)
        if step is None:
            msg = f"Unknown index build step: {name}"
            raise KeyError(msg)
        return step

    def validate_steps(self, steps: Iterable[StepName | str]) -> tuple[StepName, ...]:
        """Normalize an iterable of steps into a tuple of StepName.

        Parameters
        ----------
        steps : Iterable[StepName | str]
            Iterable of step names to validate and normalize.

        Returns
        -------
        tuple[StepName, ...]
            Tuple of validated StepName values.

        Raises
        ------
        KeyError
            If any step name is not registered in the mapping.
        """
        normalized: list[StepName] = []
        for raw in steps:
            candidate = cast("StepName", str(raw))
            if candidate not in self.mapping:
                msg = f"Unknown index build step: {raw}"
                raise KeyError(msg)
            normalized.append(candidate)
        return tuple(normalized)


class StepRunner:
    """Executor that runs registered steps in order.

    Parameters
    ----------
    registry : StepRegistry
        Registry mapping step names to their corresponding step functions.
        Each step function receives the current build state, index paths,
        and build configuration, and modifies the state in place.
    """

    def __init__(
        self,
        registry: StepRegistry,
    ) -> None:
        self.registry: StepRegistry = registry

    def run(
        self, steps: tuple[StepName, ...], *, paths: IndexPaths, cfg: IndexBuildConfig
    ) -> BuildState:
        """Execute ``steps`` sequentially using the provided paths/config.

        Parameters
        ----------
        steps : tuple[StepName, ...]
            Sequence of step names to execute in order. Each step name must
            exist in the registry. Steps are executed sequentially, with
            each step modifying the build state in place.
        paths : IndexPaths
            Filesystem paths for index artifacts, including vector Parquet
            directories, index output paths, and DuckDB catalog locations.
        cfg : IndexBuildConfig
            Configuration controlling vector dimensions, batch sizes, sampling,
            and materialization options.

        Returns
        -------
        BuildState
            Final build state populated by each executed step. Contains trained
            indexes, shard paths, row counts, and all intermediate artifacts
            produced during the build pipeline.

        Raises
        ------
        KeyError
            Propagated from :meth:`StepRegistry.resolve` when a requested step
            name is missing from the registry.
        """
        state = BuildState()
        for name in steps:
            try:
                step = self.registry.resolve(name)
            except KeyError as exc:  # pragma: no cover - defensive
                raise KeyError(str(exc)) from exc
            step(state, paths, cfg)
        return state
