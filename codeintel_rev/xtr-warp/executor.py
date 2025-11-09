"""Executor platform for XTR/WARP experiments.

This module provides the main entry point and execution callbacks for running
XTR/WARP experiments including index size calculation, latency measurement,
and metrics collection. It orchestrates parallel and sequential execution
of experiment configurations.
"""

from __future__ import annotations

import argparse
import sys

import psutil
from utility.executor_utils import (
    ExecutionContext,
    ExperimentConfigDict,
    ExperimentParamsDict,
    ExperimentResultDict,
    check_execution,
    execute_configs,
    load_configuration,
    spawn_and_execute,
)
from utility.index_sizes import bytes_to_gib, safe_index_size
from utility.runner_utils import make_run_config


def index_size(config: ExperimentConfigDict, params: ExperimentParamsDict) -> ExperimentResultDict:
    """Calculate the size of an index for a given configuration.

    Computes the index size in bytes and converts it to GiB. This function
    is used to estimate storage requirements before building an index.

    Parameters
    ----------
    config : ExperimentConfigDict
        Experiment configuration dictionary containing index parameters.
    params : ExperimentParamsDict
        Additional parameters (must be empty for this operation).

    Returns
    -------
    ExperimentResultDict
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
    if index_size_bytes is None:
        msg = "safe_index_size returned None"
        raise RuntimeError(msg)
    return {
        "index_size_bytes": index_size_bytes,
        "index_size_gib": bytes_to_gib(index_size_bytes),
    }


def latency(config: ExperimentConfigDict, params: ExperimentParamsDict) -> ExperimentResultDict:
    """Measure latency metrics across multiple runs.

    Executes the latency runner script multiple times (default: 3) and collects
    metrics and tracker data. Verifies that all runs produce consistent metrics
    and update information.

    Parameters
    ----------
    config : ExperimentConfigDict
        Experiment configuration dictionary.
    params : ExperimentParamsDict
        Parameters dictionary. May contain:
        - num_runs: Number of runs to execute (default: 3)

    Returns
    -------
    ExperimentResultDict
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
    if num_runs is None or num_runs <= 0:
        msg = f"num_runs must be > 0, got {num_runs}"
        raise ValueError(msg)
    results = [
        spawn_and_execute("utility/latency_runner.py", config, params) for _ in range(num_runs)
    ]
    metrics_val = results[0].get("metrics")
    if metrics_val is None:
        msg = "First result missing metrics"
        raise RuntimeError(msg)
    if not all(x.get("metrics") == metrics_val for x in results):
        msg = "All runs must produce consistent metrics"
        raise RuntimeError(msg)
    update_val = results[0].get("_update")
    if update_val is None:
        msg = "First result missing _update"
        raise RuntimeError(msg)
    if not all(x.get("_update") == update_val for x in results):
        msg = "All runs must produce consistent update information"
        raise RuntimeError(msg)
    tracker_list = [x.get("tracker") for x in results]
    return {
        "metrics": metrics_val,
        "tracker": tracker_list,
        "_update": update_val,
    }


def metrics(config: ExperimentConfigDict, params: ExperimentParamsDict) -> ExperimentResultDict:
    """Collect performance metrics for a single experiment run.

    Executes the latency runner script once and extracts metrics, statistics,
    and update information for analysis.

    Parameters
    ----------
    config : ExperimentConfigDict
        Experiment configuration dictionary.
    params : ExperimentParamsDict
        Parameters dictionary passed to the latency runner.

    Returns
    -------
    ExperimentResultDict
        Dictionary containing:
        - metrics: Performance metrics from the run
        - statistics: Statistical summary of the run
        - _update: Update information from the run
    """
    run = spawn_and_execute("utility/latency_runner.py", config, params)
    return {
        "metrics": run.get("metrics"),
        "statistics": run.get("statistics"),
        "_update": run.get("_update"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="XTR/WARP Experiment [Executor/Platform]")
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("-w", "--workers", type=int)
    parser.add_argument("-i", "--info", action="store_true")
    parser.add_argument("-o", "--overwrite", action="store_true")
    args = parser.parse_args()

    MAX_WORKERS = args.workers if args.workers is not None else psutil.cpu_count(logical=False)
    if MAX_WORKERS is None:
        MAX_WORKERS = 1
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
    profile = EXEC_INFO[type_]
    context = ExecutionContext(
        callback=profile["callback"],
        type_=type_,
        params=params,
        results_file=str(results_file),
        max_workers=MAX_WORKERS,
        parallelizable=profile["parallelizable"],
    )
    execute_configs(configs, context)
