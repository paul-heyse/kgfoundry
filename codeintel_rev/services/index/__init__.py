"""Service entry points for building FAISS/DuckDB indexes."""

from __future__ import annotations

from codeintel_rev.services.index.build import run_index_build
from codeintel_rev.services.index.plan import IndexBuildConfig, IndexPaths

__all__ = ["IndexBuildConfig", "IndexPaths", "run_index_build"]
