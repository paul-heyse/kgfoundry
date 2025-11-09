"""Utilities for detecting GPU stack availability."""

# [nav:section public-api]

from __future__ import annotations

import importlib
import importlib.util
import os
from types import ModuleType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

GPU_CORE_MODULES: tuple[str, ...] = (
    "torch",
    "torchvision",
    "torchaudio",
    "vllm",
    "faiss",
    "triton",
    "cuvs",
    "cuda",
    "cupy",
)
"""Canonical module names that make up the optional GPU stack."""


def _modules_available(modules: Iterable[str]) -> bool:
    """Check if all specified modules can be imported.

    Verifies that each module in the iterable can be resolved
    by Python's import system.

    Parameters
    ----------
    modules : Iterable[str]
        Iterable of module names to check.

    Returns
    -------
    bool
        True if all modules are available, False otherwise.
    """
    return all(importlib.util.find_spec(module) is not None for module in modules)


def has_gpu_stack(*, allow_without_cuda_env: str = "ALLOW_GPU_TESTS_WITHOUT_CUDA") -> bool:
    """Check if the optional GPU stack is available and CUDA is usable.

    Verifies that all core GPU modules can be imported and that CUDA
    is available via PyTorch. Can be overridden by an environment variable
    for testing on CPU-only hosts.

    Parameters
    ----------
    allow_without_cuda_env : str, optional
        Environment variable name that, when set to "1", permits returning
        True even when CUDA is unavailable. Defaults to
        "ALLOW_GPU_TESTS_WITHOUT_CUDA".

    Returns
    -------
    bool
        True when the GPU stack is available or the override environment
        variable is set, False otherwise.
    """
    if not _modules_available(GPU_CORE_MODULES):
        return False
    if os.getenv(allow_without_cuda_env) == "1":
        return True
    try:
        torch_module = importlib.import_module("torch")
    except ImportError:  # pragma: no cover - import guard
        return False
    cuda_module: object = getattr(torch_module, "cuda", None)
    if not isinstance(cuda_module, ModuleType):
        return False
    is_available_attr: object = getattr(cuda_module, "is_available", None)
    if not callable(is_available_attr):
        return False
    is_available = cast("Callable[[], bool]", is_available_attr)
    return bool(is_available())
