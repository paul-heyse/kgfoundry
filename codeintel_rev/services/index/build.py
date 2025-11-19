"""Plan runner wiring plan steps to the index build service."""

from __future__ import annotations

from collections.abc import Iterable

from codeintel_rev.services.index import steps as idx_steps
from codeintel_rev.services.index.plan import (
    BuildState,
    IndexBuildConfig,
    IndexPaths,
    StepName,
    StepRegistry,
    StepRunner,
)

DEFAULT_STEPS: tuple[StepName, ...] = (
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
)


def runner() -> StepRunner:
    """Return a step runner wired to the default step implementations.

    Returns
    -------
    StepRunner
        A step runner instance configured with all default index build step
        implementations, mapping step names to their corresponding step functions.
    """
    return StepRunner(
        StepRegistry(
            {
                "scan_shards": idx_steps.step_scan_shards,
                "sample_training": idx_steps.step_sample_training,
                "train_primary": idx_steps.step_train_primary,
                "add_all_vectors": idx_steps.step_add_all_vectors,
                "persist_primary": idx_steps.step_persist_primary,
                "build_secondary": idx_steps.step_build_secondary,
                "persist_secondary": idx_steps.step_persist_secondary,
                "export_idmap": idx_steps.step_export_idmap,
                "register_duckdb": idx_steps.step_register_duckdb,
                "materialize_join": idx_steps.step_materialize_join,
            }
        )
    )


def run_index_build(
    paths: IndexPaths,
    cfg: IndexBuildConfig,
    *,
    steps: Iterable[StepName | str] | None = None,
) -> BuildState:
    """Execute the index build plan.

    Parameters
    ----------
    paths : IndexPaths
        File system paths for index artifacts, including vector Parquet
        directories, index output paths, and DuckDB catalog locations.
    cfg : IndexBuildConfig
        Configuration controlling vector dimensions, batch sizes, sampling,
        and materialization options.
    steps : Iterable[StepName] | None, optional
        Custom sequence of step names to execute. If None, uses
        DEFAULT_STEPS. Defaults to None.

    Returns
    -------
    BuildState
        Final build state containing trained indexes, shard paths, row counts,
        and all intermediate artifacts produced during the build pipeline.
    """
    step_runner = runner()
    plan_steps: tuple[StepName, ...] = (
        DEFAULT_STEPS if steps is None else step_runner.registry.validate_steps(steps)
    )
    return step_runner.run(plan_steps, paths=paths, cfg=cfg)
