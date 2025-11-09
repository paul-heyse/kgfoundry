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
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import redirect_stdout
from dataclasses import dataclass
from itertools import product
from typing import TypeVar, cast

if sys.version_info >= (3, 11):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict

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

T = TypeVar("T")


# TypedDict definitions for configuration and result dictionaries
class ExperimentConfigDict(TypedDict, total=False):
    """Typed dictionary for experiment configuration."""

    collection: str
    dataset: str
    nbits: int
    nprobe: int | None
    t_prime: int | None
    document_top_k: int | None
    runtime: str | None
    split: str
    bound: int | None
    num_threads: int
    fused_ext: bool


class ExperimentParamsDict(TypedDict, total=False):
    """Typed dictionary for experiment parameters."""

    num_runs: int


class ExperimentResultDict(TypedDict, total=False):
    """Typed dictionary for experiment results."""

    index_size_bytes: int
    index_size_gib: float
    metrics: object
    statistics: object
    tracker: object
    _update: dict[str, object]
    provenance: dict[str, object]


def _to_tuple(value: Sequence[T] | T | None) -> tuple[T | None, ...]:
    if value is None:
        return (None,)
    if isinstance(value, Sequence):
        return tuple(value)
    return (value,)


def _cast_to_int_tuple(value: object) -> tuple[int | None, ...]:
    """Cast object to tuple of int | None."""
    if value is None:
        return (None,)
    if isinstance(value, Sequence):
        return tuple(int(v) if v is not None and isinstance(v, (int, str)) else None for v in value)
    if isinstance(value, (int, str)):
        return (int(value),)
    return (None,)


def _cast_to_str_tuple(value: object) -> tuple[str | None, ...]:
    """Cast object to tuple of str | None."""
    if value is None:
        return (None,)
    if isinstance(value, Sequence):
        return tuple(str(v) if v is not None else None for v in value)
    if isinstance(value, str):
        return (value,)
    return (None,)


def _cast_to_bool_tuple(value: object) -> tuple[bool | None, ...]:
    """Cast object to tuple of bool | None."""
    if value is None:
        return (None,)
    if isinstance(value, Sequence):
        return tuple(bool(v) if v is not None and isinstance(v, bool) else None for v in value)
    if isinstance(value, bool):
        return (value,)
    return (None,)


def _filter_non_none(
    values: tuple[T | None, ...],
    *,
    name: str,
    expected_type: type | tuple[type, ...] | None = None,
) -> tuple[T, ...]:
    filtered = tuple(value for value in values if value is not None)
    if not filtered:
        raise ValueError(f"{name} must include at least one value")
    if expected_type is not None and not all(
        isinstance(value, expected_type) for value in filtered
    ):
        expected = (
            expected_type.__name__
            if isinstance(expected_type, type)
            else " or ".join(tp.__name__ for tp in expected_type)
        )
        raise TypeError(f"{name} entries must be {expected}")
    return filtered


@dataclass(frozen=True)
class ExperimentSpec:
    collection: str
    dataset: str
    nbits: int
    nprobe: int | None
    t_prime: int | None
    document_top_k: int | None
    runtime: str | None
    split: str
    bound: int | None
    num_threads: int | None

    def validate(self) -> ExperimentSpec:
        if self.collection not in {"beir", "lotte"}:
            raise ValueError(f"collection must be 'beir' or 'lotte', got {self.collection!r}")
        if self.collection == "beir":
            if self.dataset not in BEIR_DATASETS:
                raise ValueError("dataset for beir must be one of the BEIR datasets")
        elif self.dataset not in LOTTE_DATASETS:
            raise ValueError("dataset for lotte must be one of the LOTTE datasets")
        if self.nbits not in {2, 4}:
            raise ValueError(f"nbits must be 2 or 4, got {self.nbits}")
        if self.nprobe is not None and not isinstance(self.nprobe, int):
            raise ValueError(f"nprobe must be None or int, got {type(self.nprobe).__name__}")
        if self.t_prime is not None and not isinstance(self.t_prime, int):
            raise ValueError(f"t_prime must be None or int, got {type(self.t_prime).__name__}")
        if self.document_top_k is not None and not isinstance(self.document_top_k, int):
            raise ValueError(
                f"document_top_k must be None or int, got {type(self.document_top_k).__name__}"
            )
        if self.split not in {"dev", "test"}:
            raise ValueError(f"split must be 'dev' or 'test', got {self.split!r}")
        if self.bound is not None and not isinstance(self.bound, int):
            raise ValueError(f"bound must be None or int, got {type(self.bound).__name__}")
        return self


@dataclass(frozen=True)
class ExpansionArgs:
    datasets: tuple[str, ...]
    nbits: tuple[int, ...]
    nprobes: tuple[int | None, ...]
    t_primes: tuple[int | None, ...]
    document_top_ks: tuple[int | None, ...]
    runtimes: tuple[str | None, ...]
    num_threads: tuple[int | None, ...]
    fused_exts: tuple[bool | None, ...]
    split: str
    bound: int | None

    @classmethod
    def from_raw(cls, configs: Mapping[str, object]) -> ExpansionArgs:
        """Build expansion arguments from raw configuration metadata.

        Parameters
        ----------
        configs : Mapping[str, object]
            Raw configuration dictionary.

        Returns
        -------
        ExpansionArgs
            Expansion arguments with properly typed tuples.
        """
        fused_exts = configs.get("fused_ext")
        if fused_exts is None:
            fused_exts = (None,)
        datasets_raw = configs.get("datasets")
        nbits_raw = configs.get("nbits")
        # Type narrowing: convert object values to proper types
        datasets_tuple = (
            cast("tuple[str | None, ...]", _to_tuple(datasets_raw))
            if datasets_raw is not None
            else (None,)
        )
        nbits_tuple = (
            cast("tuple[int | None, ...]", _to_tuple(nbits_raw))
            if nbits_raw is not None
            else (None,)
        )
        bound_raw = configs.get("bound")
        bound_val: int | None = bound_raw if isinstance(bound_raw, int) else None
        return cls(
            datasets=_filter_non_none(datasets_tuple, name="datasets", expected_type=str),
            nbits=_filter_non_none(nbits_tuple, name="nbits", expected_type=int),
            nprobes=_cast_to_int_tuple(configs.get("nprobe")),
            t_primes=_cast_to_int_tuple(configs.get("t_prime")),
            document_top_ks=_cast_to_int_tuple(configs.get("document_top_k")),
            runtimes=_cast_to_str_tuple(configs.get("runtime")),
            num_threads=_cast_to_int_tuple(configs.get("num_threads")),
            fused_exts=_cast_to_bool_tuple(fused_exts),
            split=str(configs.get("datasplit") or "test"),
            bound=bound_val,
        )


def _make_config(spec: ExperimentSpec, *, fused_ext: bool | None = None) -> ExperimentConfigDict:
    """Create experiment configuration dictionary from validated spec.

    Parameters
    ----------
    spec : ExperimentSpec
        Validated experiment specification.
    fused_ext : bool | None
        Whether to use fused extension (default: None, auto-set to True).

    Returns
    -------
    ExperimentConfigDict
        Configuration dictionary.
    """
    spec = spec.validate()
    num_threads = spec.num_threads if spec.num_threads is not None else 1
    if fused_ext is None:
        fused_ext = True
    config: ExperimentConfigDict = {
        "collection": spec.collection,
        "dataset": spec.dataset,
        "nbits": spec.nbits,
        "nprobe": spec.nprobe,
        "t_prime": spec.t_prime,
        "document_top_k": spec.document_top_k,
        "runtime": spec.runtime,
        "split": spec.split,
        "bound": spec.bound,
        "num_threads": num_threads,
    }
    if num_threads != 1:
        config["fused_ext"] = fused_ext
    return config


def _expand_configs(params: ExpansionArgs) -> list[ExperimentConfigDict]:
    """Construct experiment dictionaries for the provided parameter space.

    Parameters
    ----------
    params : ExpansionArgs
        Expansion arguments containing parameter ranges.

    Returns
    -------
    list[ExperimentConfigDict]
        List of expanded configuration dictionaries.
    """
    configs: list[ExperimentConfigDict] = []
    for collection_dataset in params.datasets:
        if "." not in collection_dataset:
            raise ValueError("dataset identifiers must be formatted as '<collection>.<dataset>'")
        collection, dataset = collection_dataset.split(".", 1)
        for (
            nbit,
            nprobe,
            t_prime,
            document_top_k,
            runtime,
            threads,
        ) in product(
            params.nbits,
            params.nprobes,
            params.t_primes,
            params.document_top_ks,
            params.runtimes,
            params.num_threads,
        ):
            spec = ExperimentSpec(
                collection=collection,
                dataset=dataset,
                nbits=nbit,
                nprobe=nprobe,
                t_prime=t_prime,
                document_top_k=document_top_k,
                runtime=runtime,
                split=params.split,
                bound=params.bound,
                num_threads=threads,
            )
            for fused_ext in params.fused_exts:
                configs.append(_make_config(spec, fused_ext=fused_ext))
    return configs


def _expand_configs_file(configuration_file: dict[str, object]) -> list[ExperimentConfigDict]:
    """Expand configurations from a configuration file dictionary.

    Parameters
    ----------
    configuration_file : dict[str, object]
        Configuration file dictionary containing "configurations" key.

    Returns
    -------
    list[ExperimentConfigDict]
        List of expanded configuration dictionaries.
    """
    configs_raw = configuration_file.get("configurations")
    if not isinstance(configs_raw, dict):
        msg = "configuration_file must contain 'configurations' key with dict value"
        raise ValueError(msg)
    params = ExpansionArgs.from_raw(configs_raw)
    return _expand_configs(params)


def _write_results(results_file: str, data: list[ExperimentResultDict]) -> None:
    """Write experiment results to a JSON file.

    Parameters
    ----------
    results_file : str
        Path to the results file to write.
    data : list[ExperimentResultDict]
        List of result dictionaries to serialize to JSON.
    """
    with pathlib.Path(results_file).open("w", encoding="utf-8") as file:
        file.write(json.dumps(data, indent=3))


@dataclass(frozen=True)
class ExecutionContext:
    """Context required for running experiment configurations."""

    callback: Callable[[ExperimentConfigDict, ExperimentParamsDict], ExperimentResultDict]
    type_: str
    params: ExperimentParamsDict
    results_file: str
    max_workers: int
    parallelizable: bool


def load_configuration(
    filename: str, *, info: bool = False, overwrite: bool = False
) -> tuple[str, str, ExperimentParamsDict, list[ExperimentConfigDict]]:
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
    tuple[str, str, ExperimentParamsDict, list[ExperimentConfigDict]]
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
        config_file_raw: object = json.loads(file.read())
    if not isinstance(config_file_raw, dict):
        msg = f"Configuration file {filename} must contain a JSON object"
        raise ValueError(msg)
    config_file: dict[str, object] = config_file_raw
    name_raw = config_file.get("name")
    if not isinstance(name_raw, str):
        msg = "Configuration file must contain 'name' key with string value"
        raise ValueError(msg)
    name = name_raw
    type_raw = config_file.get("type")
    if not isinstance(type_raw, str):
        msg = "Configuration file must contain 'type' key with string value"
        raise ValueError(msg)
    type_ = type_raw
    params_raw = config_file.get("parameters")
    if isinstance(params_raw, dict):
        params: ExperimentParamsDict = {}
        if "num_runs" in params_raw and isinstance(params_raw["num_runs"], int):
            params["num_runs"] = params_raw["num_runs"]
    else:
        params = {}
    configs = _expand_configs_file(config_file)

    results_file = pathlib.Path("experiments/results") / f"{name}.json"
    if not info:
        pathlib.Path("experiments/results").mkdir(exist_ok=True, parents=True)
        if pathlib.Path(results_file).exists() and not overwrite:
            msg = f"Results file {results_file} already exists and overwrite=False"
            raise FileExistsError(msg)

        _write_results(str(results_file), [])
    return str(results_file), type_, params, configs


def _init_proc(env_vars: dict[str, str]) -> None:
    for key, value in env_vars.items():
        os.environ[key] = value


def _prepare_result(result: ExperimentResultDict) -> ExperimentResultDict:
    """Prepare result dictionary by updating provenance from runtime parameters.

    Parameters
    ----------
    result : ExperimentResultDict
        Result dictionary potentially containing "_update" key.

    Returns
    -------
    ExperimentResultDict
        Result dictionary with provenance updated and "_update" removed.

    Raises
    ------
    ValueError
        If provenance key mismatch occurs during update.
    """
    if "_update" not in result:
        return result
    # NOTE Used to update parameters determined at runtime.
    result_copy = copy.deepcopy(result)
    update_raw = result_copy.get("_update")
    if not isinstance(update_raw, dict):
        return result_copy
    update: dict[str, object] = update_raw
    provenance_raw = result_copy.get("provenance")
    if not isinstance(provenance_raw, dict):
        return result_copy
    provenance: dict[str, object] = provenance_raw
    for key, value in update.items():
        current = provenance.get(key)
        if current is not None and current != value:
            msg = f"Provenance key {key!r} mismatch: current={current!r}, update={value!r}"
            raise ValueError(msg)
        provenance[key] = value
    result_copy["provenance"] = provenance
    # Remove _update key
    result_final: ExperimentResultDict = {}
    for k, v in result_copy.items():
        if k != "_update":
            result_final[k] = v
    return result_final


def _execute_configs_parallel(
    configs: list[ExperimentConfigDict], context: ExecutionContext
) -> None:
    env_vars = dict(os.environ)
    progress = tqdm(total=len(configs))
    results = []
    type_ = context.type_
    params = context.params
    results_file = context.results_file
    with (
        ProcessPoolExecutor(
            max_workers=context.max_workers,
            initializer=_init_proc,
            initargs=(env_vars,),
        ) as executor,
        redirect_stdout(io.StringIO()) as rd_stdout,
    ):
        futures = {
            executor.submit(context.callback, config, context.params): config for config in configs
        }
        for future in as_completed(futures.keys()):
            result = future.result()
            config = futures[future]

            # Create provenance dict with type and parameters
            provenance: dict[str, object] = dict(config)
            provenance["type"] = type_
            provenance["parameters"] = params
            result["provenance"] = provenance
            results.append(_prepare_result(result))
            _write_results(results_file=results_file, data=results)

            sys.stdout = sys.__stdout__
            sys.stdout = rd_stdout
            progress.update(1)
    progress.close()


def _execute_configs_sequential(
    configs: list[ExperimentConfigDict], context: ExecutionContext
) -> None:
    """Execute configurations sequentially.

    Parameters
    ----------
    configs : list[ExperimentConfigDict]
        List of configurations to execute.
    context : ExecutionContext
        Execution context with callback and parameters.
    """
    results = []
    for config in tqdm(configs):
        result = context.callback(config, context.params)
        # Create provenance dict with type and parameters
        provenance: dict[str, object] = dict(config)
        provenance["type"] = context.type_
        provenance["parameters"] = context.params
        result["provenance"] = provenance
        results.append(_prepare_result(result))
        _write_results(results_file=context.results_file, data=results)


def execute_configs(configs: list[ExperimentConfigDict], context: ExecutionContext) -> None:
    if context.parallelizable:
        _execute_configs_parallel(configs, context)
    else:
        _execute_configs_sequential(configs, context)


def read_subprocess_inputs() -> tuple[ExperimentConfigDict, ExperimentParamsDict]:
    """Read configuration and parameters from stdin for subprocess execution.

    Parses JSON input from stdin containing experiment configuration and
    parameters. Used by subprocess workers to receive their execution context.

    Returns
    -------
    tuple[ExperimentConfigDict, ExperimentParamsDict]
        Tuple containing (config, params) dictionaries parsed from JSON input.
    """
    data_raw: object = json.loads(input())
    if not isinstance(data_raw, dict):
        msg = "Subprocess input must be a JSON object"
        raise ValueError(msg)
    data: dict[str, object] = data_raw
    config_raw = data.get("config")
    params_raw = data.get("params")
    if not isinstance(config_raw, dict):
        msg = "Subprocess input must contain 'config' key with dict value"
        raise ValueError(msg)
    if not isinstance(params_raw, dict):
        msg = "Subprocess input must contain 'params' key with dict value"
        raise ValueError(msg)
    # Type narrowing: construct ExperimentConfigDict and ExperimentParamsDict
    config: ExperimentConfigDict = {}
    for key in (
        "collection",
        "dataset",
        "nbits",
        "nprobe",
        "t_prime",
        "document_top_k",
        "runtime",
        "split",
        "bound",
        "num_threads",
        "fused_ext",
    ):
        if key in config_raw:
            value = config_raw[key]
            # Type narrowing: ensure value matches expected type for this key
            if (
                (key in ("collection", "dataset", "runtime", "split") and isinstance(value, str))
                or (
                    key
                    in (
                        "nbits",
                        "nprobe",
                        "t_prime",
                        "document_top_k",
                        "bound",
                        "num_threads",
                    )
                    and isinstance(value, int)
                )
                or (key == "fused_ext" and isinstance(value, bool))
            ):
                config[key] = value
            elif (
                key in ("nprobe", "t_prime", "document_top_k", "runtime", "bound") and value is None
            ):
                config[key] = None
    params: ExperimentParamsDict = {}
    if "num_runs" in params_raw and isinstance(params_raw["num_runs"], int):
        params["num_runs"] = params_raw["num_runs"]
    return config, params


def publish_subprocess_results(results: ExperimentResultDict) -> None:
    """Publish subprocess execution results (no-op implementation).

    Placeholder function for publishing subprocess results. Currently
    does nothing but provides an interface for future result publishing
    mechanisms.

    Parameters
    ----------
    results : ExperimentResultDict
        Results dictionary from subprocess execution.
    """


def spawn_and_execute(
    script: str, config: ExperimentConfigDict, params: ExperimentParamsDict
) -> ExperimentResultDict:
    """Spawn a subprocess to execute a Python script with configuration.

    Runs a Python script as a subprocess, passing configuration and parameters
    as JSON via stdin. Captures stdout and parses the JSON result. Verifies
    successful execution by checking for the "#> Done" marker.

    Parameters
    ----------
    script : str
        Path to the Python script to execute.
    config : ExperimentConfigDict
        Configuration dictionary to pass to the script.
    params : ExperimentParamsDict
        Parameters dictionary to pass to the script.

    Returns
    -------
    ExperimentResultDict
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
        env={**os.environ, "PYTHONPATH": str(pathlib.Path.cwd())},
        cwd=pathlib.Path.cwd(),
    )
    response = process.stdout.strip().split("\n")
    if response[-1] != "#> Done" or process.returncode != 0:
        pass
    if response[-1] != "#> Done":
        msg = f"Expected process to end with '#> Done', got {response[-1]!r}"
        raise RuntimeError(msg)
    result_raw: object = json.loads(response[-2])
    if not isinstance(result_raw, dict):
        msg = "Subprocess output must be a JSON object"
        raise RuntimeError(msg)
    # Type narrowing: construct ExperimentResultDict
    result: ExperimentResultDict = {}
    result_dict: dict[str, object] = result_raw
    if "index_size_bytes" in result_dict and isinstance(result_dict["index_size_bytes"], int):
        result["index_size_bytes"] = result_dict["index_size_bytes"]
    if "index_size_gib" in result_dict and isinstance(result_dict["index_size_gib"], (int, float)):
        result["index_size_gib"] = float(result_dict["index_size_gib"])
    if "metrics" in result_dict:
        result["metrics"] = result_dict["metrics"]
    if "statistics" in result_dict:
        result["statistics"] = result_dict["statistics"]
    if "tracker" in result_dict:
        result["tracker"] = result_dict["tracker"]
    if "_update" in result_dict and isinstance(result_dict["_update"], dict):
        result["_update"] = result_dict["_update"]
    if "provenance" in result_dict and isinstance(result_dict["provenance"], dict):
        result["provenance"] = result_dict["provenance"]
    return result


def _strip_provenance(
    config: dict[str, object], result: ExperimentResultDict
) -> ExperimentConfigDict:
    """Strip provenance fields from result to match config format.

    Parameters
    ----------
    config : dict[str, object]
        Original configuration dictionary.
    result : ExperimentResultDict
        Result dictionary with provenance.

    Returns
    -------
    ExperimentConfigDict
        Stripped configuration dictionary.
    """
    provenance_raw = result.get("provenance")
    if not isinstance(provenance_raw, dict):
        msg = "Result must contain 'provenance' key with dict value"
        raise ValueError(msg)
    provenance: dict[str, object] = provenance_raw
    stripped: ExperimentConfigDict = {}
    for key in (
        "collection",
        "dataset",
        "nbits",
        "nprobe",
        "t_prime",
        "document_top_k",
        "runtime",
        "split",
        "bound",
        "num_threads",
        "fused_ext",
    ):
        if key in provenance and key not in ("parameters", "type"):
            value = provenance[key]
            # Type narrowing: ensure value matches expected type for this key
            if (
                (key in ("collection", "dataset", "runtime", "split") and isinstance(value, str))
                or (
                    key
                    in (
                        "nbits",
                        "nprobe",
                        "t_prime",
                        "document_top_k",
                        "bound",
                        "num_threads",
                    )
                    and isinstance(value, int)
                )
                or (key == "fused_ext" and isinstance(value, bool))
            ):
                stripped[key] = value
            elif (
                key in ("nprobe", "t_prime", "document_top_k", "runtime", "bound") and value is None
            ):
                stripped[key] = None
    if "document_top_k" not in config:
        stripped["document_top_k"] = None
    if "num_threads" not in config:
        stripped["num_threads"] = 1
    return stripped


def check_execution(filename: str, configs: list[ExperimentConfigDict], result_file: str) -> None:
    """Verify that execution results match expected configurations.

    Compares the configurations used for execution with the provenance
    information stored in results, ensuring they match. Used for validation
    and debugging of experiment runs.

    Parameters
    ----------
    filename : str
        Path to the original configuration file.
    configs : list[ExperimentConfigDict]
        List of configuration dictionaries that were executed.
    result_file : str
        Path to the results file containing execution outputs.
    """
    with pathlib.Path(filename).open("r", encoding="utf-8") as file:
        config_data_raw: object = json.loads(file.read())
    if not isinstance(config_data_raw, dict):
        msg = f"Configuration file {filename} must contain a JSON object"
        raise ValueError(msg)
    config_data: dict[str, object] = config_data_raw
    with pathlib.Path(result_file).open("r", encoding="utf-8") as file:
        results_raw: object = json.loads(file.read())
    if not isinstance(results_raw, list):
        msg = f"Results file {result_file} must contain a JSON array"
        raise ValueError(msg)
    results: list[object] = results_raw
    configs_raw = config_data.get("configurations")
    if not isinstance(configs_raw, dict):
        msg = "Configuration file must contain 'configurations' key with dict value"
        raise ValueError(msg)
    result_configs: list[ExperimentConfigDict] = []
    for result_item in results:
        if not isinstance(result_item, dict):
            continue
        result_dict: dict[str, object] = result_item
        provenance_raw = result_dict.get("provenance")
        if not isinstance(provenance_raw, dict):
            continue
        # Create a minimal ExperimentResultDict with provenance
        result_with_provenance: ExperimentResultDict = {"provenance": provenance_raw}
        result_configs.append(_strip_provenance(configs_raw, result_with_provenance))
    # Check that all configs are in result_configs
    missing_configs = [config for config in configs if config not in result_configs]
    if missing_configs:
        msg = f"Missing configurations in results: {missing_configs}"
        raise ValueError(msg)
