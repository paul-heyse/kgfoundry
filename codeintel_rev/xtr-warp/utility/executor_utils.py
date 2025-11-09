"""Utility functions for executing XTR/WARP experiment configurations.

This module provides functions for loading experiment configurations, executing
them in parallel or sequential modes, spawning subprocess workers, and managing
result collection and persistence. It handles the orchestration of experiment
runs across multiple configurations.

Security Note:
    The subprocess module is used for executing experiment scripts. All subprocess
    calls use explicit argument lists (not shell strings) and validate script paths
    to prevent path traversal attacks. See _validate_script_path and _run_secured_subprocess
    for security measures.
"""

from __future__ import annotations

import copy
import io
import json
import os
import pathlib
import shutil
import subprocess  # noqa: S404
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import redirect_stdout
from dataclasses import dataclass
from itertools import product
from typing import TypedDict, TypeVar, cast

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


_EXPERIMENT_CONFIG_KEYS = (
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
)
_CONFIG_STRING_KEYS = frozenset({"collection", "dataset", "runtime", "split"})
_CONFIG_INT_KEYS = frozenset({"nbits", "num_threads"})
_CONFIG_NULLABLE_INT_KEYS = frozenset({"nprobe", "t_prime", "document_top_k", "bound"})
_CONFIG_BOOLEAN_KEYS = frozenset({"fused_ext"})
_MISSING = object()


def _validate_optional_int(value: int | None, name: str) -> None:
    """Validate an optional integer parameter.

    Parameters
    ----------
    value : int | None
        Value to validate.
    name : str
        Parameter name for error messages.

    Raises
    ------
    ValueError
        If value is not None or int.
    """
    if value is not None and not isinstance(value, int):
        msg = f"{name} must be None or int, got {type(value).__name__}"
        raise ValueError(msg)


_RESULT_INT_KEYS = frozenset({"index_size_bytes"})
_RESULT_NUMBER_KEYS = frozenset({"index_size_gib"})
_RESULT_OBJECT_KEYS = frozenset({"metrics", "statistics", "tracker"})
_RESULT_PROVENANCE_KEY = "provenance"


def _sanitize_config_value(key: str, value: object) -> object:
    """Return typed value for ``key``, or sentinel for invalid inputs.

    Parameters
    ----------
    key : str
        Configuration key name.
    value : object
        Raw configuration value.

    Returns
    -------
    object
        Typed value if valid, or _MISSING sentinel if invalid.
    """
    if key in _CONFIG_STRING_KEYS and isinstance(value, str):
        return value
    if key in _CONFIG_INT_KEYS and isinstance(value, int):
        return value
    if key in _CONFIG_NULLABLE_INT_KEYS and (value is None or isinstance(value, int)):
        return value
    if key in _CONFIG_BOOLEAN_KEYS and isinstance(value, bool):
        return value
    return _MISSING


def _cast_config_value(key: str, value: object) -> object:
    """Cast sanitized value to the expected type for ``key``.

    Parameters
    ----------
    key : str
        Configuration key name.
    value : object
        Sanitized value to cast.

    Returns
    -------
    object
        Cast value matching the expected type for the key.
    """
    if key in _CONFIG_STRING_KEYS:
        return cast("str", value)
    if key in _CONFIG_INT_KEYS:
        return cast("int", value)
    if key in _CONFIG_NULLABLE_INT_KEYS:
        return cast("int | None", value)
    if key in _CONFIG_BOOLEAN_KEYS:
        return cast("bool", value)
    return value


def _ensure_dict(value: object, message: str) -> dict[str, object]:
    """Ensure value is a dictionary, raising TypeError if not.

    Parameters
    ----------
    value : object
        Value to check.
    message : str
        Error message to raise if value is not a dict.

    Returns
    -------
    dict[str, object]
        Value cast to dict.

    Raises
    ------
    TypeError
        If value is not a dict.
    """
    if not isinstance(value, dict):
        raise TypeError(message)
    return value


def _parse_config_from_raw(raw: dict[str, object]) -> ExperimentConfigDict:
    """Parse ExperimentConfigDict from raw dictionary.

    Parameters
    ----------
    raw : dict[str, object]
        Raw configuration dictionary.

    Returns
    -------
    ExperimentConfigDict
        Parsed and sanitized configuration dictionary.
    """
    config: ExperimentConfigDict = {}
    for key in _EXPERIMENT_CONFIG_KEYS:
        if key not in raw:
            continue
        sanitized = _sanitize_config_value(key, raw[key])
        if sanitized is not _MISSING:
            config[key] = _cast_config_value(key, sanitized)
    return config


def _parse_params_from_raw(raw: dict[str, object]) -> ExperimentParamsDict:
    params: ExperimentParamsDict = {}
    if "num_runs" in raw and isinstance(raw["num_runs"], int):
        params["num_runs"] = raw["num_runs"]
    return params


def _parse_subprocess_payload() -> tuple[dict[str, object], dict[str, object]]:
    """Parse raw JSON input into configuration and parameter dictionaries.

    Returns
    -------
    tuple[dict[str, object], dict[str, object]]
        Tuple of (config_raw, params_raw) dictionaries.

    Raises
    ------
    TypeError
        If input is not a valid JSON object or required keys have wrong types.
    """
    data_raw: object = json.loads(input())
    if not isinstance(data_raw, dict):
        msg = "Subprocess input must be a JSON object"
        raise TypeError(msg)
    data: dict[str, object] = data_raw
    config_raw_value = data.get("config")
    if not isinstance(config_raw_value, dict):
        msg = "Subprocess input must contain 'config' key with dict value"
        raise TypeError(msg)
    config_raw: dict[str, object] = config_raw_value
    params_raw_value = data.get("params")
    if not isinstance(params_raw_value, dict):
        msg = "Subprocess input must contain 'params' key with dict value"
        raise TypeError(msg)
    params_raw: dict[str, object] = params_raw_value
    return config_raw, params_raw


def _create_result_from_dict(result_dict: dict[str, object]) -> ExperimentResultDict:
    """Build ExperimentResultDict from raw subprocess JSON payload.

    Parameters
    ----------
    result_dict : dict[str, object]
        Raw result dictionary from subprocess output.

    Returns
    -------
    ExperimentResultDict
        Parsed result dictionary.
    """
    result: ExperimentResultDict = {}
    for key in _RESULT_INT_KEYS:
        if key in result_dict and isinstance(result_dict[key], int):
            result[key] = result_dict[key]
    for key in _RESULT_NUMBER_KEYS:
        if key in result_dict and isinstance(result_dict[key], (int, float)):
            result[key] = float(result_dict[key])
    for key in _RESULT_OBJECT_KEYS:
        if key in result_dict:
            result[key] = result_dict[key]
    if "_update" in result_dict and isinstance(result_dict["_update"], dict):
        result["_update"] = result_dict["_update"]
    if _RESULT_PROVENANCE_KEY in result_dict and isinstance(
        result_dict[_RESULT_PROVENANCE_KEY], dict
    ):
        result["provenance"] = result_dict[_RESULT_PROVENANCE_KEY]
    return result


def _to_tuple(value: Sequence[T] | T | None) -> tuple[T | None, ...]:
    """Convert value to tuple, handling None and sequences.

    Parameters
    ----------
    value : Sequence[T] | T | None
        Value to convert to tuple.

    Returns
    -------
    tuple[T | None, ...]
        Tuple containing value(s), or (None,) if value is None.
    """
    if value is None:
        return (None,)
    if isinstance(value, Sequence):
        return tuple(value)
    return (value,)


def _cast_to_int_tuple(value: object) -> tuple[int | None, ...]:
    """Cast object to tuple of int | None.

    Parameters
    ----------
    value : object
        Value to cast (int, str, Sequence, or None).

    Returns
    -------
    tuple[int | None, ...]
        Tuple of integers or None values.
    """
    if value is None:
        return (None,)
    if isinstance(value, Sequence):
        return tuple(int(v) if v is not None and isinstance(v, (int, str)) else None for v in value)
    if isinstance(value, (int, str)):
        return (int(value),)
    return (None,)


def _cast_to_str_tuple(value: object) -> tuple[str | None, ...]:
    """Cast object to tuple of str | None.

    Parameters
    ----------
    value : object
        Value to cast (str, Sequence, or None).

    Returns
    -------
    tuple[str | None, ...]
        Tuple of strings or None values.
    """
    if value is None:
        return (None,)
    if isinstance(value, Sequence):
        return tuple(str(v) if v is not None else None for v in value)
    if isinstance(value, str):
        return (value,)
    return (None,)


def _cast_to_bool_tuple(value: object) -> tuple[bool | None, ...]:
    """Cast object to tuple of bool | None.

    Parameters
    ----------
    value : object
        Value to cast (bool, Sequence, or None).

    Returns
    -------
    tuple[bool | None, ...]
        Tuple of booleans or None values.
    """
    if value is None:
        return (None,)
    if isinstance(value, Sequence):
        return tuple(bool(v) if v is not None and isinstance(v, bool) else None for v in value)
    if isinstance(value, bool):
        return (value,)
    return (None,)


def _filter_non_none[T](
    values: tuple[T | None, ...],
    *,
    name: str,
    expected_type: type | tuple[type, ...] | None = None,
) -> tuple[T, ...]:
    filtered = tuple(value for value in values if value is not None)
    if not filtered:
        msg = f"{name} must include at least one value"
        raise ValueError(msg)
    if expected_type is not None and not all(
        isinstance(value, expected_type) for value in filtered
    ):
        expected = (
            expected_type.__name__
            if isinstance(expected_type, type)
            else " or ".join(tp.__name__ for tp in expected_type)
        )
        msg = f"{name} entries must be {expected}"
        raise TypeError(msg)
    return filtered


@dataclass(frozen=True)
class ExperimentSpec:
    """Experiment specification with validated parameters.

    Represents a single experiment configuration with all required parameters
    for indexing and search operations. Provides validation to ensure
    parameters are within acceptable ranges.

    Parameters
    ----------
    collection : str
        Collection name ("beir" or "lotte").
    dataset : str
        Dataset identifier within collection.
    nbits : int
        Quantization bits (2 or 4).
    nprobe : int | None
        Number of probes for IVF search (optional).
    t_prime : int | None
        T-prime parameter for WARP search (optional).
    document_top_k : int | None
        Top-k documents to retrieve (optional).
    runtime : str | None
        Runtime identifier (optional).
    split : str
        Data split ("dev" or "test").
    bound : int | None
        Bound parameter for search (optional).
    num_threads : int | None
        Number of threads for execution (optional).
    """

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

    def _validate_collection_and_dataset(self) -> None:
        """Validate collection and dataset parameters.

        Raises
        ------
        ValueError
            If collection is invalid or dataset doesn't match collection.
        """
        if self.collection not in {"beir", "lotte"}:
            msg = f"collection must be 'beir' or 'lotte', got {self.collection!r}"
            raise ValueError(msg)
        if self.collection == "beir":
            if self.dataset not in BEIR_DATASETS:
                msg = "dataset for beir must be one of the BEIR datasets"
                raise ValueError(msg)
        elif self.dataset not in LOTTE_DATASETS:
            msg = "dataset for lotte must be one of the LOTTE datasets"
            raise ValueError(msg)

    def _validate_numeric_parameters(self) -> None:
        """Validate numeric parameters (nbits, optional ints, split).

        Raises
        ------
        ValueError
            If any numeric parameter is invalid.
        """
        if self.nbits not in {2, 4}:
            msg = f"nbits must be 2 or 4, got {self.nbits}"
            raise ValueError(msg)
        if self.split not in {"dev", "test"}:
            msg = f"split must be 'dev' or 'test', got {self.split!r}"
            raise ValueError(msg)

    def validate(self) -> ExperimentSpec:
        """Validate experiment specification parameters.

        Checks that all parameters are within acceptable ranges and match
        expected values for the specified collection and dataset.

        Returns
        -------
        ExperimentSpec
            Self (for method chaining).

        Raises
        ------
        ValueError
            If any parameter is invalid or out of range.
            This exception is raised indirectly by _validate_collection_and_dataset,
            _validate_numeric_parameters, or _validate_optional_int when validation fails.
        """
        try:
            self._validate_collection_and_dataset()
            self._validate_numeric_parameters()
            _validate_optional_int(self.nprobe, "nprobe")
            _validate_optional_int(self.t_prime, "t_prime")
            _validate_optional_int(self.document_top_k, "document_top_k")
            _validate_optional_int(self.bound, "bound")
        except ValueError as exc:
            raise exc
        return self


@dataclass(frozen=True)
class ExpansionArgs:
    """Expansion arguments for generating experiment configurations.

    Contains parameter ranges that will be expanded into a Cartesian product
    of all possible combinations for experiment execution.

    Attributes
    ----------
    datasets : tuple[str, ...]
        Dataset identifiers to test.
    nbits : tuple[int, ...]
        Quantization bit values to test.
    nprobes : tuple[int | None, ...]
        Probe count values to test.
    t_primes : tuple[int | None, ...]
        T-prime values to test.
    document_top_ks : tuple[int | None, ...]
        Top-k values to test.
    runtimes : tuple[str | None, ...]
        Runtime identifiers to test.
    num_threads : tuple[int | None, ...]
        Thread count values to test.
    fused_exts : tuple[bool | None, ...]
        Fused extension flags to test.
    split : str
        Data split to use.
    bound : int | None
        Bound parameter value.
    """

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

    Notes
    -----
    The spec parameter is validated via ``spec.validate()`` which may raise
    ValueError if parameters are invalid. See ``ExperimentSpec.validate()``
    for details on validation errors.
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

    Generates all combinations of parameters via Cartesian product and creates
    configuration dictionaries for each combination.

    Parameters
    ----------
    params : ExpansionArgs
        Expansion arguments containing parameter ranges.

    Returns
    -------
    list[ExperimentConfigDict]
        List of expanded configuration dictionaries.

    Raises
    ------
    ValueError
        If dataset identifiers are not formatted as '<collection>.<dataset>'.
    """
    configs: list[ExperimentConfigDict] = []
    try:
        for collection_dataset in params.datasets:
            if "." not in collection_dataset:
                msg = "dataset identifiers must be formatted as '<collection>.<dataset>'"
                raise ValueError(msg)
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
                configs.extend(
                    _make_config(spec, fused_ext=fused_ext) for fused_ext in params.fused_exts
                )
    except ValueError as exc:
        raise exc
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

    Raises
    ------
    TypeError
        If configuration_file does not contain 'configurations' key with dict value.
    ValueError
        If dataset identifiers are not formatted as '<collection>.<dataset>'.
        This exception is raised indirectly by _expand_configs when validation fails.
    """
    try:
        configs_raw = configuration_file.get("configurations")
        if not isinstance(configs_raw, dict):
            msg = "configuration_file must contain 'configurations' key with dict value"
            raise TypeError(msg)
        params = ExpansionArgs.from_raw(configs_raw)
        return _expand_configs(params)
    except (TypeError, ValueError) as exc:
        raise exc


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
    TypeError
        If configuration file does not contain valid JSON object or required keys have wrong types.
    FileExistsError
        If results file already exists and overwrite=False.
    """
    with pathlib.Path(filename).open("r", encoding="utf-8") as file:
        config_file_raw: object = json.loads(file.read())
    if not isinstance(config_file_raw, dict):
        msg = f"Configuration file {filename} must contain a JSON object"
        raise TypeError(msg)
    config_file: dict[str, object] = config_file_raw
    name_raw = config_file.get("name")
    if not isinstance(name_raw, str):
        msg = "Configuration file must contain 'name' key with string value"
        raise TypeError(msg)
    name = name_raw
    type_raw = config_file.get("type")
    if not isinstance(type_raw, str):
        msg = "Configuration file must contain 'type' key with string value"
        raise TypeError(msg)
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
    """Initialize subprocess with environment variables.

    Sets environment variables in the current process. Used as an initializer
    for ProcessPoolExecutor to propagate environment to worker processes.

    Parameters
    ----------
    env_vars : dict[str, str]
        Dictionary of environment variable names to values.
    """
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
    """Execute experiment configurations in parallel or sequential mode.

    Dispatches configuration execution based on the experiment type and whether
    it's marked as parallelizable. Parallelizable experiments run concurrently
    using a process pool, while non-parallelizable ones run sequentially.

    Parameters
    ----------
    configs : list[ExperimentConfigDict]
        List of configuration dictionaries to execute.
    context : ExecutionContext
        Execution context with callback, type, params, results file, and
        parallelization settings.
    """
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

    Raises
    ------
    TypeError
        If input is not a valid JSON object or required keys have wrong types.
        This exception is raised indirectly by _parse_subprocess_payload,
        _parse_config_from_raw, or _parse_params_from_raw when parsing fails.
    """
    try:
        config_raw, params_raw = _parse_subprocess_payload()
        return _parse_config_from_raw(config_raw), _parse_params_from_raw(params_raw)
    except (TypeError, ValueError) as exc:
        raise exc


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


def _run_secured_subprocess(
    python_exe_path: pathlib.Path,
    script_path: pathlib.Path,
    input_data: str,
    project_root: pathlib.Path,
) -> object:
    """Execute subprocess with comprehensive security validation.

    This function encapsulates subprocess execution with all security checks
    to prevent path traversal and command injection attacks. The subprocess
    module is imported locally to avoid module-level security warnings.

    Parameters
    ----------
    python_exe_path : pathlib.Path
        Absolute path to Python executable.
    script_path : pathlib.Path
        Absolute path to script file (validated to be within project_root).
    input_data : str
        JSON string to pass as stdin to the script.
    project_root : pathlib.Path
        Project root directory for cwd and PYTHONPATH.

    Returns
    -------
    object
        CompletedProcess instance from subprocess.run().

    Notes
    -----
    Security measures implemented:
    - Script path validated to be within project directory
    - Python executable resolved to absolute path
    - Command arguments passed as list (not shell string)
    - Working directory set to project root
    - Input data is JSON-serialized config/params (not user-provided shell commands)
    """
    return subprocess.run(  # noqa: S603
        [str(python_exe_path), str(script_path)],
        check=False,
        input=input_data,
        capture_output=True,
        bufsize=1,
        text=True,
        env={**os.environ, "PYTHONPATH": str(project_root)},
        cwd=str(project_root),
    )


def _validate_script_path(script: str, project_root: pathlib.Path) -> pathlib.Path:
    """Validate and resolve script path.

    Parameters
    ----------
    script : str
        Script path to validate.
    project_root : pathlib.Path
        Project root directory.

    Returns
    -------
    pathlib.Path
        Resolved and validated script path.

    Raises
    ------
    ValueError
        If script path is invalid, outside project directory, or not a .py file.
    """
    script_path = pathlib.Path(script).resolve()

    # Ensure script path is within project root to prevent path traversal
    try:
        script_path.relative_to(project_root)
    except ValueError:
        msg = f"Script path {script!r} must be within project directory {project_root}"
        raise ValueError(msg) from None

    # Verify script exists and is a file
    if not script_path.is_file():
        msg = f"Script path {script_path} does not exist or is not a file"
        raise ValueError(msg)

    # Verify script has .py extension
    if script_path.suffix != ".py":
        msg = f"Script path {script_path} must have .py extension"
        raise ValueError(msg)

    return script_path


def _find_python_executable() -> pathlib.Path:
    """Find and resolve Python executable path.

    Returns
    -------
    pathlib.Path
        Absolute path to Python executable.

    Raises
    ------
    RuntimeError
        If Python executable is not found in PATH.
    """
    python_exe = shutil.which("python")
    if python_exe is None:
        msg = "Python executable not found in PATH"
        raise RuntimeError(msg)
    return pathlib.Path(python_exe).resolve()


def _parse_subprocess_result(result_dict: dict[str, object]) -> ExperimentResultDict:
    """Parse ExperimentResultDict from subprocess output dictionary.

    Parameters
    ----------
    result_dict : dict[str, object]
        Raw result dictionary from subprocess output.

    Returns
    -------
    ExperimentResultDict
        Parsed result dictionary.
    """
    result: ExperimentResultDict = {}
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


def spawn_and_execute(
    script: str, config: ExperimentConfigDict, params: ExperimentParamsDict
) -> ExperimentResultDict:
    """Spawn a subprocess to execute a Python script with configuration.

    Runs a Python script as a subprocess, passing configuration and parameters
    as JSON via stdin. Captures stdout and parses the JSON result. Verifies
    successful execution by checking for the "#> Done" marker.

    The script path is validated and resolved to an absolute path within the
    project directory to prevent path traversal attacks. Subprocess execution
    uses explicit argument lists (not shell strings) to prevent command injection.

    Parameters
    ----------
    script : str
        Path to the Python script to execute. Must be relative to the project root
        or an absolute path within the project directory.
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
    ValueError
        If the script path is outside the project directory or invalid.
        This exception is raised indirectly by _validate_script_path when path validation fails.
    TypeError
        If subprocess output is not a valid JSON object.
        This exception is raised indirectly by _parse_subprocess_result when JSON parsing fails.
    RuntimeError
        If the script doesn't output "#> Done" marker or execution fails.
        This exception is raised indirectly by _parse_subprocess_result when execution verification fails.
    """
    try:
        project_root = pathlib.Path.cwd().resolve()
        script_path = _validate_script_path(script, project_root)
        python_exe_path = _find_python_executable()

        process = _run_secured_subprocess(
            python_exe_path=python_exe_path,
            script_path=script_path,
            input_data=json.dumps({"config": config, "params": params}),
            project_root=project_root,
        )
        response = process.stdout.strip().split("\n")
        if response[-1] != "#> Done":
            msg = f"Expected process to end with '#> Done', got {response[-1]!r}"
            raise RuntimeError(msg)
        result_raw: object = json.loads(response[-2])
        if not isinstance(result_raw, dict):
            msg = "Subprocess output must be a JSON object"
            raise TypeError(msg)
        return _parse_subprocess_result(result_raw)
    except (ValueError, TypeError, RuntimeError) as exc:
        raise exc


def _strip_provenance_fields(provenance: dict[str, object]) -> ExperimentConfigDict:
    """Extract configuration fields from provenance dictionary.

    Parameters
    ----------
    provenance : dict[str, object]
        Provenance dictionary containing configuration fields.

    Returns
    -------
    ExperimentConfigDict
        Extracted configuration dictionary.
    """
    stripped: ExperimentConfigDict = {}
    _assign_config_fields(stripped, provenance, _CONFIG_STRING_KEYS)
    _assign_config_fields(stripped, provenance, _CONFIG_INT_KEYS)
    _assign_config_fields(stripped, provenance, _CONFIG_NULLABLE_INT_KEYS)
    _assign_config_fields(stripped, provenance, _CONFIG_BOOLEAN_KEYS)
    return stripped


def _assign_config_fields(
    stripped: ExperimentConfigDict, provenance: dict[str, object], keys: frozenset[str]
) -> None:
    """Copy sanitized values for the provided keys into ``stripped``."""
    for key in keys:
        if key not in provenance:
            continue
        sanitized = _sanitize_config_value(key, provenance[key])
        if sanitized is _MISSING:
            continue
        stripped[key] = _cast_config_value(key, sanitized)


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

    Raises
    ------
    TypeError
        If result does not contain 'provenance' key with dict value.
    """
    provenance_raw = result.get("provenance")
    if not isinstance(provenance_raw, dict):
        msg = "Result must contain 'provenance' key with dict value"
        raise TypeError(msg)
    provenance: dict[str, object] = provenance_raw
    stripped = _strip_provenance_fields(provenance)
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

    Raises
    ------
    TypeError
        If configuration or results files do not contain valid JSON or required keys have wrong types.
    ValueError
        If configurations in results do not match expected configurations.
    """
    with pathlib.Path(filename).open("r", encoding="utf-8") as file:
        config_data_raw: object = json.loads(file.read())
    if not isinstance(config_data_raw, dict):
        msg = f"Configuration file {filename} must contain a JSON object"
        raise TypeError(msg)
    config_data: dict[str, object] = config_data_raw
    with pathlib.Path(result_file).open("r", encoding="utf-8") as file:
        results_raw: object = json.loads(file.read())
    if not isinstance(results_raw, list):
        msg = f"Results file {result_file} must contain a JSON array"
        raise TypeError(msg)
    results: list[object] = results_raw
    configs_raw = config_data.get("configurations")
    if not isinstance(configs_raw, dict):
        msg = "Configuration file must contain 'configurations' key with dict value"
        raise TypeError(msg)
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
