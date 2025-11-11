#!/usr/bin/env python3
"""Command-line entry point for SCIP function coverage evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.config.settings import load_settings
from codeintel_rev.evaluation.scip_coverage import SCIPCoverageEvaluator
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)


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
    settings = load_settings()
    ctx = ApplicationContext.create()
    evaluator = SCIPCoverageEvaluator(
        settings=settings,
        paths=settings.paths,
        duckdb_manager=ctx.duckdb_manager,
        faiss_manager=ctx.faiss_manager,
        vllm_client=ctx.vllm_client,
    )
    summary = evaluator.run(k=args.k, limit=args.limit, output_dir=args.output)
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
