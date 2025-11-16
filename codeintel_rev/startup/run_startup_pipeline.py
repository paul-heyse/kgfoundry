"""Run the SCIP → chunk → embed → FAISS pipeline and summarize artifacts.

This script is a thin orchestrator around ``codeintel_rev.bin.index_all`` that
also reports the resulting DuckDB/FAISS state so you can confirm bootstrapping
worked. It assumes the environment variables consumed by ``load_settings()``
are already exported (e.g., ``REPO_ROOT``, ``SCIP_INDEX``, ``VLLM_URL``).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config.settings import Settings, load_settings
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from kgfoundry_common.subprocess_utils import (
    run_subprocess,
)


def _run_index_pipeline(args: Sequence[str]) -> None:
    """Invoke the existing indexing pipeline module with the requested flags.

    Parameters
    ----------
    args : Sequence[str]
        Command-line arguments to pass to the index_all module. These arguments
        control which phases of the indexing pipeline are executed.

    Notes
    -----
    SubprocessTimeoutError and SubprocessError may be raised by run_subprocess()
    when the indexing subprocess exceeds the configured timeout or exits with
    a non-zero status. These exceptions propagate unchanged.
    """
    cmd = [sys.executable, "-m", "codeintel_rev.bin.index_all", *args]
    run_subprocess(cmd)


def _summarize_artifacts(settings: Settings) -> dict[str, object]:
    """Collect chunk counts, embedding dimensions, and FAISS file locations.

    Parameters
    ----------
    settings : Settings
        Application settings containing paths and configuration for DuckDB
        and FAISS artifacts.

    Returns
    -------
    dict[str, object]
        Summary payload describing catalog metadata and FAISS artifacts.

    Notes
    -----
    OSError and RuntimeError may be raised by DuckDBCatalog operations when
    DuckDB tables or Parquet files cannot be read or when hydration fails.
    These exceptions propagate unchanged.
    """
    paths = resolve_application_paths(settings)
    vectors_dir = paths.vectors_dir
    duckdb_path = paths.duckdb_path

    with DuckDBCatalog(
        duckdb_path,
        vectors_dir,
        repo_root=paths.repo_root,
        materialize=settings.index.duckdb_materialize,
    ) as catalog:
        chunk_count = catalog.count_chunks()
        head_ids = list(range(min(5, chunk_count)))
        vec_dim = None
        if head_ids:
            _, vectors = catalog.get_embeddings_by_ids(head_ids)
            if vectors.size:
                vec_dim = vectors.shape[1]

    faiss_index = Path(paths.faiss_index)
    faiss_idmap = Path(paths.faiss_idmap_path)

    return {
        "duckdb_catalog": duckdb_path,
        "chunk_count": chunk_count,
        "embedding_dim": vec_dim,
        "parquet_dir": vectors_dir,
        "faiss_index": {"path": faiss_index, "exists": faiss_index.exists()},
        "faiss_idmap": {"path": faiss_idmap, "exists": faiss_idmap.exists()},
    }


def main() -> None:
    """Entry point for the startup pipeline runner.

    Notes
    -----
    RuntimeError and OSError may be propagated from the indexing pipeline
    or artifact summarization if execution fails or file operations fail.
    These exceptions propagate unchanged to the caller.
    """
    parser = argparse.ArgumentParser(
        description="Run SCIP→chunk→embedding→FAISS pipeline and print a summary."
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Pass through to index_all to update an existing index incrementally.",
    )
    parser.add_argument(
        "--eval-after-index",
        action="store_true",
        help="Request offline evaluation after indexing (same flag as index_all).",
    )
    parser.add_argument(
        "--eval-queries",
        type=Path,
        default=None,
        help="Optional JSONL file with evaluation queries (forwarded to index_all).",
    )
    parser.add_argument(
        "--skip-summary",
        action="store_true",
        help="Do not emit DuckDB/FAISS summary after the pipeline completes.",
    )
    parser.add_argument(
        "--phase",
        choices=("full", "embeddings", "faiss"),
        default="full",
        help="Forwarded to index_all to run only part of the pipeline.",
    )
    cli_args = parser.parse_args()

    forwarded: list[str] = []
    if cli_args.incremental:
        forwarded.append("--incremental")
    if cli_args.eval_after_index:
        forwarded.append("--eval-after-index")
    if cli_args.eval_queries is not None:
        forwarded.extend(["--eval-queries", str(cli_args.eval_queries)])
    if cli_args.phase != "full":
        forwarded.extend(["--phase", cli_args.phase])

    settings = load_settings()
    _run_index_pipeline(forwarded)

    if not cli_args.skip_summary:
        _summarize_artifacts(settings)


if __name__ == "__main__":
    main()
