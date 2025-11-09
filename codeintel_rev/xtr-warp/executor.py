"""Executor platform for XTR/WARP experiments.

This module provides the main entry point and execution callbacks for running
XTR/WARP experiments including index size calculation, latency measurement,
and metrics collection. It orchestrates parallel and sequential execution
of experiment configurations.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import psutil
from utility.executor_utils import (
    check_execution,
    execute_configs,
    load_configuration,
    spawn_and_execute,
)
from utility.index_sizes import bytes_to_gib, safe_index_size
from utility.runner_utils import make_run_config


def index_size(config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Calculate the size of an index for a given configuration.

    Computes the index size in bytes and converts it to GiB. This function
    is used to estimate storage requirements before building an index.

    Parameters
    ----------
    config : dict[str, Any]
        Experiment configuration dictionary containing index parameters.
    params : dict[str, Any]
        Additional parameters (must be empty for this operation).

    Returns
    -------
    dict[str, Any]
        Dictionary containing:
        - index_size_bytes: Size of the index in bytes
        - index_size_gib: Size of the index in GiB

    Raises
    ------
    ValueError
        If params dictionary is not empty.
    """
    if len(params) != 0:
        msg = f"params must be empty for index_size operation, got {len(params)} items"
        raise ValueError(msg)
    run_config = make_run_config(config)
    index_size_bytes = safe_index_size(run_config)
    return {
        "index_size_bytes": index_size_bytes,
        "index_size_gib": bytes_to_gib(index_size_bytes),
    }


def latency(config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Measure latency metrics across multiple runs.

    Executes the latency runner script multiple times (default: 3) and collects
    metrics and tracker data. Verifies that all runs produce consistent metrics
    and update information.

    Parameters
    ----------
    config : dict[str, Any]
        Experiment configuration dictionary.
    params : dict[str, Any]
        Parameters dictionary. May contain:
        - num_runs: Number of runs to execute (default: 3)

    Returns
    -------
    dict[str, Any]
        Dictionary containing:
        - metrics: Performance metrics from the runs
        - tracker: List of tracker data from each run
        - _update: Update information from the runs

    Raises
    ------
    ValueError
        If num_runs is <= 0.
    RuntimeError
        If runs produce inconsistent metrics or update information.
    """
    num_runs = params.get("num_runs", 3)
    if num_runs <= 0:
        msg = f"num_runs must be > 0, got {num_runs}"
        raise ValueError(msg)
    results = [
        spawn_and_execute("utility/latency_runner.py", config, params) for _ in range(num_runs)
    ]
    metrics = results[0]["metrics"]
    if not all(x["metrics"] == metrics for x in results):
        msg = "All runs must produce consistent metrics"
        raise RuntimeError(msg)
    update = results[0]["_update"]
    if not all(x["_update"] == update for x in results):
        msg = "All runs must produce consistent update information"
        raise RuntimeError(msg)
    return {
        "metrics": metrics,
        "tracker": [x["tracker"] for x in results],
        "_update": update,
    }


def metrics(config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Collect performance metrics for a single experiment run.

    Executes the latency runner script once and extracts metrics, statistics,
    and update information for analysis.

    Parameters
    ----------
    config : dict[str, Any]
        Experiment configuration dictionary.
    params : dict[str, Any]
        Parameters dictionary passed to the latency runner.

    Returns
    -------
    dict[str, Any]
        Dictionary containing:
        - metrics: Performance metrics from the run
        - statistics: Statistical summary of the run
        - _update: Update information from the run
    """
    run = spawn_and_execute("utility/latency_runner.py", config, params)
    return {
        "metrics": run["metrics"],
        "statistics": run["statistics"],
        "_update": run["_update"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="XTR/WARP Experiment [Executor/Platform]")
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("-w", "--workers", type=int)
    parser.add_argument("-i", "--info", action="store_true")
    parser.add_argument("-o", "--overwrite", action="store_true")
    args = parser.parse_args()

    MAX_WORKERS = args.workers or psutil.cpu_count(logical=False)
    OVERWRITE = args.overwrite
    results_file, type_, params, configs = load_configuration(
        args.config, info=args.info, overwrite=OVERWRITE
    )

    if args.info:
        check_execution(args.config, configs, results_file)
        sys.exit(0)

    EXEC_INFO = {
        "index_size": {"callback": index_size, "parallelizable": True},
        "latency": {"callback": latency, "parallelizable": False},
        "metrics": {"callback": metrics, "parallelizable": True},
    }
    execute_configs(
        EXEC_INFO,
        configs,
        results_file=results_file,
        type_=type_,
        params=params,
        max_workers=MAX_WORKERS,
    )
