#!/usr/bin/env python3
"""Command-line entry point for SCIP function coverage evaluation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from functools import lru_cache
from pathlib import Path

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.config import load_app_config
from codeintel_rev.config.api import AppConfig
from codeintel_rev.config.settings import Settings
from codeintel_rev.config.shim import settings_from_app_config
from codeintel_rev.evaluation.scip_coverage import SCIPCoverageEvaluator


def build_parser() -> argparse.ArgumentParser:
    """Return an argument parser for the coverage evaluator CLI.

    Returns
    -------
    argparse.ArgumentParser
        Configured argument parser with --k, --limit, and --output options.
    """
    parser = argparse.ArgumentParser(
        description="Evaluate SCIP function coverage across FAISS retrieval."
    )
    parser.add_argument(
        "--k",
        type=int,
        default=10,
        help="Top-K to consider when checking retrieval coverage (default: 10).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional limit on symbol count.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Directory for coverage artifacts. Defaults to settings.eval.output_dir.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute the coverage evaluator with the provided CLI arguments.

    Extended Summary
    ----------------
    This CLI entry point runs SCIP function coverage evaluation across FAISS
    retrieval results. It fetches symbol definitions from the DuckDB catalog,
    performs FAISS searches for each symbol, and computes coverage metrics
    (how many symbols are retrievable at top-k). Results are written to
    output directory as JSON reports.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments. If None, uses `sys.argv[1:]`. Arguments are
        parsed by `build_parser()`: --k (top-k), --limit (symbol limit),
        --output (output directory).

    Returns
    -------
    int
        Exit code: 0 on success, non-zero on error (e.g., missing context,
        evaluation failures).

    Notes
    -----
    This tool requires an active ApplicationContext with FAISS manager and
    DuckDB catalog initialized. Coverage evaluation iterates over symbol
    definitions and performs FAISS searches, so runtime scales with symbol
    count and search latency. Time complexity: O(n_symbols * search_time).
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = _cached_settings()
    ctx = ApplicationContext.create()
    evaluator = SCIPCoverageEvaluator(
        settings=settings,
        repo_root=ctx.paths.repo_root,
        duckdb_manager=ctx.duckdb_manager,
        faiss_manager=ctx.faiss_manager,
        vllm_client=ctx.vllm_client,
    )
    summary = evaluator.run(k=args.k, limit=args.limit, output_dir=args.output)
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
@lru_cache(maxsize=1)
def _cached_app_config() -> AppConfig:
    """Load and cache AppConfig for CLI invocations.

    Returns
    -------
    AppConfig
        Cached immutable configuration derived from env/file sources.
    """
    return load_app_config(file=os.environ.get("CODEINTEL_CONFIG_FILE"))


def _cached_settings() -> Settings:
    """Return legacy Settings derived from AppConfig.

    Returns
    -------
    Settings
        Legacy msgspec settings populated from AppConfig values.
    """
    return settings_from_app_config(_cached_app_config())
