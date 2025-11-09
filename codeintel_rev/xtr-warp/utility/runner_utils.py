"""Runtime configuration utilities for XTR/WARP experiment runs.

This module provides functions to construct runtime configurations from
experiment parameter dictionaries, supporting multiple runtime backends
including TorchScript, ONNX, OpenVINO, and CoreML.
"""

from __future__ import annotations

import re
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
    collection_raw = config.get("collection")
    dataset_raw = config.get("dataset")
    split_raw = config.get("split")
    collection = str(collection_raw) if collection_raw is not None else ""
    dataset = str(dataset_raw) if dataset_raw is not None else ""
    split = str(split_raw) if split_raw is not None else ""

    nbits_raw = config.get("nbits")
    nprobe_raw = config.get("nprobe")
    t_prime_raw = config.get("t_prime")
    bound_raw = config.get("bound")
    nbits = int(nbits_raw) if isinstance(nbits_raw, int) else 0
    nprobe = int(nprobe_raw) if isinstance(nprobe_raw, int) else None
    t_prime = int(t_prime_raw) if isinstance(t_prime_raw, int) else None
    bound = int(bound_raw) if isinstance(bound_raw, int) else None

    document_top_k_raw = config.get("document_top_k")
    k = int(document_top_k_raw) if isinstance(document_top_k_raw, int) else DEFAULT_K_VALUE

    num_threads_raw = config.get("num_threads")
    num_threads = int(num_threads_raw) if isinstance(num_threads_raw, int) else 1
    fused_ext = True
    if num_threads != 1:
        fused_ext_raw = config.get("fused_ext")
        fused_ext = bool(fused_ext_raw) if isinstance(fused_ext_raw, bool) else True

    runtime_raw = config.get("runtime")
    runtime = str(runtime_raw) if isinstance(runtime_raw, str) else None
    return WARPRunConfig(
        collection=collection,
        dataset=dataset,
        type_="search" if collection == "lotte" else None,
        datasplit=split,
        nbits=nbits,
        nprobe=nprobe,
        t_prime=t_prime,
        k=k,
        runtime=_make_runtime(runtime, num_threads=num_threads),
        bound=bound,
        fused_ext=fused_ext,
    )
