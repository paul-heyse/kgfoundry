#!/usr/bin/env python3
"""FAISS diagnostics helper for CodeIntel."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from codeintel_rev.io.faiss_manager import FAISSManager, FAISSRuntimeOptions


def _build_argument_parser() -> argparse.ArgumentParser:
    """Create the CLI parser for FAISS diagnostics.

    Returns
    -------
    argparse.ArgumentParser
        Configured argument parser.
    """
    parser = argparse.ArgumentParser("faiss-diag", description="Inspect FAISS indexes quickly.")
    parser.add_argument("--index", type=Path, required=True, help="Path to the FAISS index file.")
    parser.add_argument("--dim", type=int, required=True, help="Vector dimensionality.")
    parser.add_argument("--nlist", type=int, default=4096, help="IVF nlist value.")
    parser.add_argument(
        "--family",
        type=str,
        default="auto",
        help="FAISS factory family (auto, flat, ivf_flat, ivf_pq, ivf_pq_refine, hnsw).",
    )
    parser.add_argument(
        "--tune",
        action="store_true",
        help="Run a lightweight autotune sweep with synthetic vectors.",
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        help="Attempt to clone the index to GPU and report the outcome.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=13,
        help="Random seed for synthetic autotune vectors.",
    )
    return parser


def _build_manager(args: argparse.Namespace) -> FAISSManager:
    runtime = FAISSRuntimeOptions(faiss_family=args.family)
    return FAISSManager(
        index_path=args.index,
        vec_dim=args.dim,
        nlist=args.nlist,
        use_cuvs=True,
        runtime=runtime,
    )


def _run_autotune(manager: FAISSManager, dim: int, seed: int) -> dict[str, object]:
    rng = np.random.default_rng(seed)
    xq = rng.standard_normal((64, dim), dtype=np.float32)
    xt = rng.standard_normal((512, dim), dtype=np.float32)
    return dict(manager.autotune(xq, xt, k=10))


def _emit(line: str) -> None:
    """Write a single line to stdout."""
    sys.stdout.write(f"{line}\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the FAISS diagnostics workflow.

    Returns
    -------
    int
        Exit status code.
    """
    parser = _build_argument_parser()
    args = parser.parse_args(argv)

    manager = _build_manager(args)
    manager.load_cpu_index()
    compile_opts = manager.get_compile_options()
    _emit(f"compile_options: {compile_opts}")

    if args.gpu:
        gpu_enabled = manager.clone_to_gpu()
        reason = manager.gpu_disabled_reason or "enabled"
        _emit(f"gpu_clone: {gpu_enabled} ({reason})")

    if args.tune:
        profile = _run_autotune(manager, args.dim, args.seed)
        profile["path"] = str(manager.autotune_profile_path)
        _emit(json.dumps(profile, indent=2))

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
