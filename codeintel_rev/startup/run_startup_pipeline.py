#!/usr/bin/env python3
"""Run the SCIP → chunk → embed → FAISS pipeline and summarize artifacts.

This script is a thin orchestrator around ``codeintel_rev.bin.index_all`` that
also reports the resulting DuckDB/FAISS state so you can confirm bootstrapping
worked. It assumes the environment variables consumed by ``load_settings()``
are already exported (e.g., ``REPO_ROOT``, ``SCIP_INDEX``, ``VLLM_URL``).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(REPO_ROOT))
if SRC_ROOT.is_dir():
    sys.path.insert(0, str(SRC_ROOT))

from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config.settings import Settings, load_settings
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog


def _run_index_pipeline(args: Sequence[str]) -> None:
    """Invoke the existing indexing pipeline module with the requested flags."""
    cmd = [sys.executable, "-m", "codeintel_rev.bin.index_all", *args]
    completed = subprocess.run(cmd, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"index_all failed with exit code {completed.returncode}")


def _summarize_artifacts(settings: Settings) -> None:
    """Print chunk counts, embedding dimensions, and FAISS file locations."""
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

    print("Artifacts summary")
    print(f"  DuckDB catalog : {duckdb_path}")
    print(f"  Chunk count    : {chunk_count}")
    print(f"  Embedding dim  : {vec_dim}")
    print(f"  Parquet dir    : {vectors_dir}")
    print(f"  FAISS index    : {faiss_index} (exists={faiss_index.exists()})")
    print(f"  FAISS ID map   : {faiss_idmap} (exists={faiss_idmap.exists()})")


def main() -> None:
    """Entry point for the startup pipeline runner."""
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
