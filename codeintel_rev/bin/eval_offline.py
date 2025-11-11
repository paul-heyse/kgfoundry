#!/usr/bin/env python3
"""Command-line entry point for offline FAISS recall evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from codeintel_rev.app.config_context import ApplicationContext
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Return an argument parser for the offline evaluator CLI.

    Returns
    -------
    argparse.ArgumentParser
        Configured argument parser with --queries and --output options.
    """
    parser = argparse.ArgumentParser(description="Run offline FAISS recall evaluation.")
    parser.add_argument(
        "--queries",
        type=Path,
        default=None,
        help="Optional path to JSONL queries ({qid,text,positives}). Defaults to synthesized queries.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Directory for evaluation artifacts. Defaults to settings.eval.output_dir.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute the evaluator using CLI arguments.

    Extended Summary
    ----------------
    This CLI entry point runs offline FAISS recall evaluation. It loads queries
    (from file or synthesizes them), performs FAISS searches, computes recall
    against ground truth, and writes evaluation reports. Used for validating
    index quality and tuning search parameters.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments. If None, uses `sys.argv[1:]`. Arguments are
        parsed by `build_parser()`: --queries (query file path), --output
        (output directory).

    Returns
    -------
    int
        Exit code: 0 on success, 1 on error (e.g., evaluator disabled, missing
        context, evaluation failures).

    Notes
    -----
    This tool requires an active ApplicationContext with offline recall evaluator
    enabled. Evaluation performs searches and computes recall metrics, so runtime
    scales with query count and search latency. Time complexity: O(n_queries * search_time).
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    ctx = ApplicationContext.create()
    try:
        evaluator = ctx.get_offline_recall_evaluator()
    except RuntimeError as exc:
        LOGGER.exception("offline_eval.disabled", extra={"error": str(exc)})
        return 1
    result = evaluator.run(queries_path=args.queries, output_dir=args.output)
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
