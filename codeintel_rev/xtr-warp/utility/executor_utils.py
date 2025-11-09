"""Utility functions for executing XTR/WARP experiment configurations.

This module provides functions for loading experiment configurations, executing
them in parallel or sequential modes, spawning subprocess workers, and managing
result collection and persistence. It handles the orchestration of experiment
runs across multiple configurations.
"""

from __future__ import annotations

import copy
import io
import json
import os
import pathlib
import subprocess
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import redirect_stdout
from typing import Any

from tqdm import tqdm

BEIR_DATASETS = ["nfcorpus", "scifact", "scidocs", "fiqa", "webis-touche2020", "quora"]
LOTTE_DATASETS = [
    "lifestyle",
    "writing",
    "recreation",
    "technology",
    "science",
    "pooled",
]


def _make_config(
    collection: str,
    dataset: str,
    nbits: int,
    nprobe: int | None,
    t_prime: int | None,
    document_top_k: int | None = None,
    runtime: str | None = None,
    split: str = "test",
    bound: int | None = None,
    num_threads: int = 1,
    *,
    fused_ext: bool | None = None,
) -> dict[str, Any]:
    """Create experiment configuration dictionary.

    Parameters
    ----------
    collection : str
        Dataset collection name ("beir" or "lotte").
    dataset : str
        Specific dataset identifier.
    nbits : int
        Number of quantization bits (2 or 4).
    nprobe : int | None
        Number of probes for IVF search.
    t_prime : int | None
        T' parameter for search.
    document_top_k : int | None
        Top-k documents to retrieve (default: None).
    runtime : str | None
        Runtime backend string (default: None).
    split : str
        Data split ("dev" or "test", default: "test").
    bound : int | None
        Bound parameter (default: None).
    num_threads : int
        Number of threads for execution (default: 1).
    fused_ext : bool | None
        Whether to use fused extension (default: None, auto-set to True).

    Returns
    -------
    dict[str, Any]
        Configuration dictionary.

    Raises
    ------
    ValueError
        If collection, dataset, nbits, split, or parameter types are invalid.
    """
    if collection not in {"beir", "lotte"}:
        msg = f"collection must be 'beir' or 'lotte', got {collection!r}"
        raise ValueError(msg)
    if collection == "beir":
        if dataset not in BEIR_DATASETS:
            msg = f"dataset must be one of {BEIR_DATASETS} for beir collection, got {dataset!r}"
            raise ValueError(msg)
    elif dataset not in LOTTE_DATASETS:
        msg = f"dataset must be one of {LOTTE_DATASETS} for lotte collection, got {dataset!r}"
        raise ValueError(msg)
    if nbits not in {2, 4}:
        msg = f"nbits must be 2 or 4, got {nbits}"
        raise ValueError(msg)
    if nprobe is not None and not isinstance(nprobe, int):
        msg = f"nprobe must be None or int, got {type(nprobe).__name__}"
        raise ValueError(msg)
    if t_prime is not None and not isinstance(t_prime, int):
        msg = f"t_prime must be None or int, got {type(t_prime).__name__}"
        raise ValueError(msg)
    if document_top_k is not None and not isinstance(document_top_k, int):
        msg = f"document_top_k must be None or int, got {type(document_top_k).__name__}"
        raise ValueError(msg)
    if split not in {"dev", "test"}:
        msg = f"split must be 'dev' or 'test', got {split!r}"
        raise ValueError(msg)
    if bound is not None and not isinstance(bound, int):
        msg = f"bound must be None or int, got {type(bound).__name__}"
        raise ValueError(msg)
    if fused_ext is None:
        fused_ext = True
    config = {
        "collection": collection,
        "dataset": dataset,
        "nbits": nbits,
        "nprobe": nprobe,
        "t_prime": t_prime,
        "document_top_k": document_top_k,
        "runtime": runtime,
        "split": split,
        "bound": bound,
        "num_threads": num_threads,
    }
    if num_threads != 1:
        config["fused_ext"] = fused_ext
    return config


def _expand_configs(
    datasets: str | Sequence[str],
    nbits: int | Sequence[int],
    nprobes: int | Sequence[int | None] | None,
    t_primes: int | Sequence[int | None] | None,
    document_top_ks: int | Sequence[int | None] | None = None,
    runtimes: str | Sequence[str | None] | None = None,
    split: str = "test",
    bound: int | None = None,
    num_threads: int | Sequence[int | None] | None = None,
    *,
    fused_exts: bool | Sequence[bool | None] | None = None,
) -> list[dict[str, Any]]:
    if num_threads is None:
        num_threads = 1
    if not isinstance(nbits, list):
        nbits = [nbits]
    if not isinstance(datasets, list):
        datasets = [datasets]
    if not isinstance(nprobes, list):
        nprobes = [nprobes]
    if not isinstance(t_primes, list):
        t_primes = [t_primes]
    if not isinstance(document_top_ks, list):
        document_top_ks = [document_top_ks]
    if not isinstance(runtimes, list):
        runtimes = [runtimes]
    if not isinstance(num_threads, list):
        num_threads = [num_threads]
    if not isinstance(fused_exts, list):
        fused_exts = [fused_exts]
    configs = []
    for collection_dataset in datasets:
        collection, dataset = collection_dataset.split(".")
        for nbit in nbits:
            for nprobe in nprobes:
                for t_prime in t_primes:
                    for document_top_k in document_top_ks:
                        for runtime in runtimes:
                            for threads in num_threads:
                                configs.extend(
                                    _make_config(
                                        collection=collection,
                                        dataset=dataset,
                                        nbits=nbit,
                                        nprobe=nprobe,
                                        t_prime=t_prime,
                                        document_top_k=document_top_k,
                                        runtime=runtime,
                                        split=split,
                                        bound=bound,
                                        num_threads=threads,
                                        fused_ext=fused_ext,
                                    )
                                    for fused_ext in fused_exts
                                )
    return configs


def _get(config: dict[str, object], key: str) -> object:
    if key in config:
        return config[key]
    return None


def _expand_configs_file(configuration_file: dict[str, Any]) -> list[dict[str, Any]]:
    configs = configuration_file["configurations"]
    return _expand_configs(
        datasets=_get(configs, "datasets"),
        nbits=_get(configs, "nbits"),
        nprobes=_get(configs, "nprobe"),
        t_primes=_get(configs, "t_prime"),
        document_top_ks=_get(configs, "document_top_k"),
        runtimes=_get(configs, "runtime"),
        split=_get(configs, "datasplit"),
        bound=_get(configs, "bound"),
        num_threads=_get(configs, "num_threads"),
        fused_exts=_get(configs, "fused_ext"),
    )


def _write_results(results_file: str, data: list[dict[str, Any]]) -> None:
    """Write experiment results to a JSON file.

    Parameters
    ----------
    results_file : str
        Path to the results file to write.
    data : list[dict[str, Any]]
        List of result dictionaries to serialize to JSON.
    """
    with pathlib.Path(results_file).open("w", encoding="utf-8") as file:
        file.write(json.dumps(data, indent=3))


def load_configuration(
    filename: str, *, info: bool = False, overwrite: bool = False
) -> tuple[str, str, dict[str, Any], list[dict[str, Any]]]:
    """Load experiment configuration from a JSON file.

    Reads a configuration file, expands it into multiple configurations,
    and prepares the results file. If not in info mode, creates the results
    file and ensures it doesn't already exist (unless overwrite is True).

    Parameters
    ----------
    filename : str
        Path to the JSON configuration file.
    info : bool
        If True, skip file creation and overwrite checks (default: False).
    overwrite : bool
        If True, allow overwriting existing results files (default: False).

    Returns
    -------
    tuple[str, str, dict[str, Any], list[dict[str, Any]]]
        Tuple containing:
        - results_file: Path to the results file
        - type_: Experiment type string
        - params: Parameters dictionary
        - configs: List of expanded configuration dictionaries

    Raises
    ------
    FileExistsError
        If results file already exists and overwrite=False.
    """
    with pathlib.Path(filename).open("r", encoding="utf-8") as file:
        config_file = json.loads(file.read())
    name = config_file["name"]
    type_ = config_file["type"]
    params = _get(config_file, "parameters") or {}
    configs = _expand_configs_file(config_file)

    results_file = pathlib.Path("experiments/results") / f"{name}.json"
    if not info:
        pathlib.Path("experiments/results").mkdir(exist_ok=True, parents=True)
        if pathlib.Path(results_file).exists() and not overwrite:
            msg = f"Results file {results_file} already exists and overwrite=False"
            raise FileExistsError(msg)

        _write_results(results_file, [])
    return results_file, type_, params, configs


def _init_proc(env_vars: dict[str, str]) -> None:
    for key, value in env_vars.items():
        os.environ[key] = value


def _prepare_result(result: dict[str, Any]) -> dict[str, Any]:
    """Prepare result dictionary by updating provenance from runtime parameters.

    Parameters
    ----------
    result : dict[str, Any]
        Result dictionary potentially containing "_update" key.

    Returns
    -------
    dict[str, Any]
        Result dictionary with provenance updated and "_update" removed.

    Raises
    ------
    ValueError
        If provenance key mismatch occurs during update.
    """
    if "_update" not in result:
        return result
    # NOTE Used to update parameters determined at runtime.
    result = copy.deepcopy(result)
    update = result["_update"]
    for key, value in update.items():
        current = result["provenance"][key]
        if current is not None and current != value:
            msg = f"Provenance key {key!r} mismatch: current={current!r}, update={value!r}"
            raise ValueError(msg)
        result["provenance"][key] = value
    del result["_update"]
    return result


def _execute_configs_parallel(
    configs: list[dict[str, Any]],
    callback: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    type_: str,
    params: dict[str, Any],
    results_file: str,
    max_workers: int,
) -> None:
    """Execute configurations in parallel using ProcessPoolExecutor.

    Parameters
    ----------
    configs : list[dict[str, Any]]
        List of configuration dictionaries to execute.
    callback : Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
        Function to execute for each configuration.
    type_ : str
        Experiment type string.
    params : dict[str, Any]
        Parameters dictionary to pass to callback.
    results_file : str
        Path to results file for writing.
    max_workers : int
        Maximum number of worker processes.
    """
    env_vars = dict(os.environ)
    progress = tqdm(total=len(configs))
    results = []
    with (
        ProcessPoolExecutor(
            max_workers=max_workers, initializer=_init_proc, initargs=(env_vars,)
        ) as executor,
        redirect_stdout(io.StringIO()) as rd_stdout,
    ):
        futures = {executor.submit(callback, config, params): config for config in configs}
        for future in as_completed(futures.keys()):
            result = future.result()
            config = futures[future]

            result["provenance"] = config
            result["provenance"]["type"] = type_
            result["provenance"]["parameters"] = params
            results.append(_prepare_result(result))
            _write_results(results_file=results_file, data=results)

            sys.stdout = sys.__stdout__
            sys.stdout = rd_stdout
            progress.update(1)
    progress.close()


def _execute_configs_sequential(
    configs: list[dict[str, Any]],
    callback: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    type_: str,
    params: dict[str, Any],
    results_file: str,
) -> None:
    """Execute configurations sequentially.

    Parameters
    ----------
    configs : list[dict[str, Any]]
        List of configuration dictionaries to execute.
    callback : Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
        Function to execute for each configuration.
    type_ : str
        Experiment type string.
    params : dict[str, Any]
        Parameters dictionary to pass to callback.
    results_file : str
        Path to results file for writing.
    """
    results = []
    for config in tqdm(configs):
        result = callback(config, params)
        result["provenance"] = config
        result["provenance"]["type"] = type_
        result["provenance"]["parameters"] = params
        results.append(_prepare_result(result))
        _write_results(results_file=results_file, data=results)


def execute_configs(
    exec_info: dict[str, dict[str, Any]],
    configs: list[dict[str, Any]],
    results_file: str,
    type_: str,
    params: dict[str, Any],
    max_workers: int,
) -> None:
    """Execute experiment configurations in parallel or sequential mode.

    Dispatches configuration execution based on the experiment type and whether
    it's marked as parallelizable. Parallelizable experiments run concurrently
    using a process pool, while non-parallelizable ones run sequentially.

    Parameters
    ----------
    exec_info : dict[str, dict[str, Any]]
        Execution information dictionary keyed by experiment type, containing
        callback functions and parallelizability flags.
    configs : list[dict[str, Any]]
        List of configuration dictionaries to execute.
    results_file : str
        Path to the results file where outputs will be written.
    type_ : str
        Experiment type identifier (must exist in exec_info).
    params : dict[str, Any]
        Parameters dictionary passed to each configuration execution.
    max_workers : int
        Maximum number of worker processes for parallel execution.
    """
    exec_info = exec_info[type_]
    callback, parallelizable = exec_info["callback"], exec_info["parallelizable"]
    if parallelizable:
        _execute_configs_parallel(
            configs, callback, type_, params, results_file, max_workers=max_workers
        )
    else:
        _execute_configs_sequential(configs, callback, type_, params, results_file)


def read_subprocess_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    """Read configuration and parameters from stdin for subprocess execution.

    Parses JSON input from stdin containing experiment configuration and
    parameters. Used by subprocess workers to receive their execution context.

    Returns
    -------
    tuple[dict[str, Any], dict[str, Any]]
        Tuple containing (config, params) dictionaries parsed from JSON input.
    """
    data = json.loads(input())
    return data["config"], data["params"]


def publish_subprocess_results(results: dict[str, Any]) -> None:
    """Publish subprocess execution results (no-op implementation).

    Placeholder function for publishing subprocess results. Currently
    does nothing but provides an interface for future result publishing
    mechanisms.

    Parameters
    ----------
    results : dict[str, Any]
        Results dictionary from subprocess execution.
    """


def spawn_and_execute(
    script: str, config: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Spawn a subprocess to execute a Python script with configuration.

    Runs a Python script as a subprocess, passing configuration and parameters
    as JSON via stdin. Captures stdout and parses the JSON result. Verifies
    successful execution by checking for the "#> Done" marker.

    Parameters
    ----------
    script : str
        Path to the Python script to execute.
    config : dict[str, Any]
        Configuration dictionary to pass to the script.
    params : dict[str, Any]
        Parameters dictionary to pass to the script.

    Returns
    -------
    dict[str, Any]
        Result dictionary parsed from the script's JSON output.

    Raises
    ------
    RuntimeError
        If the script doesn't output "#> Done" marker.
    """
    process = subprocess.run(
        ["python", script],
        check=False,
        input=json.dumps({"config": config, "params": params}),
        stdout=subprocess.PIPE,
        bufsize=1,
        text=True,
        env={**os.environ, "PYTHONPATH": pathlib.Path.cwd()},
        cwd=pathlib.Path.cwd(),
    )
    response = process.stdout.strip().split("\n")
    if response[-1] != "#> Done" or process.returncode != 0:
        pass
    if response[-1] != "#> Done":
        msg = f"Expected process to end with '#> Done', got {response[-1]!r}"
        raise RuntimeError(msg)
    return json.loads(response[-2])


def _strip_provenance(config: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    del result["parameters"]
    del result["type"]
    if "document_top_k" not in config:
        result["document_top_k"] = None
    if "num_threads" not in config:
        result["num_threads"] = 1
    return result


def check_execution(filename: str, configs: list[dict[str, Any]], result_file: str) -> None:
    """Verify that execution results match expected configurations.

    Compares the configurations used for execution with the provenance
    information stored in results, ensuring they match. Used for validation
    and debugging of experiment runs.

    Parameters
    ----------
    filename : str
        Path to the original configuration file.
    configs : list[dict[str, Any]]
        List of configuration dictionaries that were executed.
    result_file : str
        Path to the results file containing execution outputs.
    """
    with pathlib.Path(filename).open("r", encoding="utf-8") as file:
        config_data = json.loads(file.read())
    with pathlib.Path(result_file).open("r", encoding="utf-8") as file:
        results = json.loads(file.read())
    result_configs = [
        _strip_provenance(config_data["configurations"], result["provenance"]) for result in results
    ]
    [config for config in configs if config not in result_configs]
