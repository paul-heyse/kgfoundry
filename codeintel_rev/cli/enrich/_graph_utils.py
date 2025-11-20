# SPDX-License-Identifier: MIT
"""Shared helpers for graph/GOID CLI commands."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.app.readiness import raise_on_errors, validate_paths
from codeintel_rev.config.paths import ResolvedPaths, resolve_application_paths
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, DuckDBCatalogOptions
from codeintel_rev.services.enrich.context import PipelineContext
from codeintel_rev.services.enrich.graph_support import (
    DEFAULT_EXCLUDES,
    collect_python_files,
    detect_commit,
)


def resolve_paths(repo_root: Path, out_dir: Path) -> tuple[ResolvedPaths, PipelineContext]:
    """Resolve application paths and create pipeline context.

    Parameters
    ----------
    repo_root : Path
        Repository root directory path.
    out_dir : Path
        Output directory path for data artifacts.

    Returns
    -------
    tuple[ResolvedPaths, PipelineContext]
        Tuple containing resolved paths configuration and pipeline context
        initialized from those paths.

    Notes
    -----
    This function resolves application paths using environment variable overrides
    and validates them before creating the pipeline context. Used by graph/GOID
    CLI commands to set up the execution environment.
    """
    paths = resolve_application_paths({"BASE_DIR": repo_root, "DATA_DIR": out_dir})
    raise_on_errors(validate_paths(paths))
    ctx = PipelineContext.from_paths(paths)
    return paths, ctx


def open_catalog(paths: ResolvedPaths) -> DuckDBCatalog:
    """Open or create a DuckDB catalog for graph/GOID operations.

    Parameters
    ----------
    paths : ResolvedPaths
        Resolved application paths containing DuckDB database path and vectors
        directory location.

    Returns
    -------
    DuckDBCatalog
        DuckDB catalog instance connected to the database at the configured path.
        The vectors directory is created if it does not exist.

    Notes
    -----
    This function creates the vectors directory if needed and initializes a
    DuckDB catalog with repository root configuration. Used by graph/GOID
    CLI commands to access the symbol catalog and GOID registry.
    """
    paths.vectors_dir.mkdir(parents=True, exist_ok=True)
    options = DuckDBCatalogOptions(repo_root=paths.repo_root)
    return DuckDBCatalog(paths.duckdb_path, paths.vectors_dir, options=options)


__all__ = [
    "DEFAULT_EXCLUDES",
    "collect_python_files",
    "detect_commit",
    "open_catalog",
    "resolve_paths",
]
