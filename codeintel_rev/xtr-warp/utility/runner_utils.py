"""Runtime configuration utilities for XTR/WARP experiment runs.

This module provides functions to construct runtime configurations from
experiment parameter dictionaries, supporting multiple runtime backends
including TorchScript, ONNX, OpenVINO, and CoreML.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from warp.engine.runtime.onnx_model import XTROnnxConfig
    from warp.engine.runtime.openvino_model import XTROpenVinoConfig
    from warp.engine.runtime.torchscript_model import XTRTorchScriptConfig

from utility.executor_utils import ExperimentConfigDict
from warp.engine.config import USE_CORE_ML, WARPRunConfig
from warp.engine.runtime.onnx_model import XTROnnxConfig, XTROnnxQuantization
from warp.engine.runtime.openvino_model import XTROpenVinoConfig
from warp.engine.runtime.torchscript_model import XTRTorchScriptConfig

if USE_CORE_ML:
    from warp.engine.runtime.coreml_model import XTRCoreMLConfig

DEFAULT_K_VALUE = 1000
QUANTIZATION_TYPES = "|".join(["NONE", "PREPROCESS", "DYN_QUANTIZED_QINT8", "QUANTIZED_QATTENTION"])


def _cast_str(value: object) -> str:
    """Return string representation if value is str, else empty string.

    Parameters
    ----------
    value : object
        Value to convert to string.

    Returns
    -------
    str
        String representation if value is str, otherwise empty string.
    """
    return str(value) if isinstance(value, str) else ""


def _cast_int(value: object, *, default: int | None = None) -> int | None:
    """Return ``value`` as int or the provided default.

    Parameters
    ----------
    value : object
        Value to convert to int.
    default : int | None, optional
        Default value to return if value is not an int (default: None).

    Returns
    -------
    int | None
        Integer value if value is int, otherwise default value or None.
    """
    if isinstance(value, int):
        return value
    if default is not None:
        return default
    return None


@dataclass(frozen=True)
class RuntimeArgs:
    """Sanitised experiment arguments used to build a WARPRunConfig."""

    collection: str
    dataset: str
    split: str
    nbits: int
    nprobe: int | None
    t_prime: int | None
    bound: int | None
    document_top_k: int
    num_threads: int
    runtime: str | None
    fused_ext: bool

    @classmethod
    def from_config(cls, config: ExperimentConfigDict) -> RuntimeArgs:
        """Create RuntimeArgs from experiment configuration dictionary.

        Extracts and sanitizes configuration values, applying defaults where
        necessary. Converts string and integer values with proper type handling.

        Parameters
        ----------
        config : ExperimentConfigDict
            Experiment configuration dictionary.

        Returns
        -------
        RuntimeArgs
            Sanitized runtime arguments for WARPRunConfig construction.
        """
        collection = _cast_str(config.get("collection"))
        dataset = _cast_str(config.get("dataset"))
        split = _cast_str(config.get("split"))
        nbits = _cast_int(config.get("nbits"), default=0) or 0
        nprobe = _cast_int(config.get("nprobe"))
        t_prime = _cast_int(config.get("t_prime"))
        bound = _cast_int(config.get("bound"))
        document_top_k = (
            _cast_int(config.get("document_top_k"), default=DEFAULT_K_VALUE) or DEFAULT_K_VALUE
        )
        num_threads = _cast_int(config.get("num_threads"), default=1) or 1
        runtime_value = config.get("runtime")
        runtime = runtime_value if isinstance(runtime_value, str) else None
        fused_ext_value = config.get("fused_ext")
        fused_ext = bool(fused_ext_value) if isinstance(fused_ext_value, bool) else True
        if num_threads == 1:
            fused_ext = True
        return cls(
            collection=collection,
            dataset=dataset,
            split=split,
            nbits=nbits,
            nprobe=nprobe,
            t_prime=t_prime,
            bound=bound,
            document_top_k=document_top_k,
            num_threads=num_threads,
            runtime=runtime,
            fused_ext=fused_ext,
        )


def _make_runtime(
    runtime: str | None, num_threads: int = 1
) -> XTROnnxConfig | XTROpenVinoConfig | XTRTorchScriptConfig | None:
    if runtime is None:
        return runtime

    if runtime == "TORCHSCRIPT":
        return XTRTorchScriptConfig(num_threads=num_threads)

    match = re.match(f"ONNX\\.({QUANTIZATION_TYPES})", runtime)
    if match is not None:
        quantization = XTROnnxQuantization[match[1]]
        return XTROnnxConfig(quantization=quantization, num_threads=num_threads)

    if runtime == "OPENVINO":
        return XTROpenVinoConfig(num_threads=num_threads)

    if USE_CORE_ML and runtime == "CORE_ML":
        return XTRCoreMLConfig(num_threads=num_threads)

    raise AssertionError


def make_run_config(config: ExperimentConfigDict) -> WARPRunConfig:
    """Create a WARPRunConfig from an experiment configuration dictionary.

    Extracts experiment parameters and constructs a WARPRunConfig with
    appropriate runtime backend configuration. Handles default values
    for document_top_k and fused_ext based on thread count.

    Parameters
    ----------
    config : ExperimentConfigDict
        Configuration dictionary containing:
        - collection: Dataset collection name ("beir" or "lotte")
        - dataset: Specific dataset identifier
        - split: Data split ("dev" or "test")
        - nbits: Number of quantization bits (2 or 4)
        - nprobe: Number of probes for IVF search
        - t_prime: T' parameter for search
        - bound: Bound parameter
        - document_top_k: Top-k documents to retrieve (default: 1000)
        - num_threads: Number of threads for execution
        - runtime: Runtime backend string (e.g., "TORCHSCRIPT", "ONNX.NONE")
        - fused_ext: Whether to use fused extension (auto-set for multi-thread)

    Returns
    -------
    WARPRunConfig
        Configured WARP run configuration object.
    """
    args = RuntimeArgs.from_config(config)
    return WARPRunConfig(
        collection=args.collection,
        dataset=args.dataset,
        type_="search" if args.collection == "lotte" else None,
        datasplit=args.split,
        nbits=args.nbits,
        nprobe=args.nprobe,
        t_prime=args.t_prime,
        k=args.document_top_k,
        runtime=_make_runtime(args.runtime, num_threads=args.num_threads),
        bound=args.bound,
        fused_ext=args.fused_ext,
    )
