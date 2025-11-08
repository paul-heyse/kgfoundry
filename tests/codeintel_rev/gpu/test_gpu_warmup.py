"""Explicit GPU warmup tests (tiny, fast, and skippable).

These tests perform minimal GPU operations to verify GPU functionality.
They are marked with @pytest.mark.gpu and will be skipped if GPU is not available.

Run with: pytest -m gpu tests/codeintel_rev/gpu/test_gpu_warmup.py
"""

from __future__ import annotations

import importlib.util

import pytest


def _skip_if_no_cuda_torch() -> None:
    """Skip test if CUDA is not available to PyTorch."""
    torch_spec = importlib.util.find_spec("torch")
    if torch_spec is None:
        pytest.skip("PyTorch not installed")
    torch = importlib.import_module("torch")

    if not torch.cuda.is_available():
        pytest.skip("CUDA not available to PyTorch")


def _skip_if_no_faiss_gpu() -> None:
    """Skip test if FAISS GPU is not available."""
    faiss_spec = importlib.util.find_spec("faiss")
    if faiss_spec is None:
        pytest.skip("FAISS not installed")
    faiss = importlib.import_module("faiss")

    if not hasattr(faiss, "StandardGpuResources"):
        pytest.skip("FAISS not built with GPU bindings")

    if hasattr(faiss, "get_num_gpus") and faiss.get_num_gpus() <= 0:
        pytest.skip("FAISS sees 0 GPUs")


@pytest.mark.gpu
def test_torch_small_matmul() -> None:
    """Test small matrix multiplication on GPU using PyTorch.

    Performs a tiny GEMM operation to verify CUDA context initialization
    and cuBLAS functionality.
    """
    _skip_if_no_cuda_torch()

    torch = importlib.import_module("torch")
    dev = torch.device("cuda:0")
    a = torch.randn(64, 64, device=dev)
    b = torch.randn(64, 64, device=dev)
    c = a @ b
    torch.cuda.synchronize()
    assert c.numel() == 64 * 64


@pytest.mark.gpu
def test_faiss_small_search_ip() -> None:
    """Test small FAISS GPU search using inner product metric.

    Creates a tiny FAISS GPU index, adds vectors, and performs a search
    to verify FAISS GPU resource initialization and search functionality.
    """
    _skip_if_no_faiss_gpu()

    faiss = importlib.import_module("faiss")
    import numpy as np

    res = faiss.StandardGpuResources()
    d = 32
    idx = faiss.GpuIndexFlatIP(res, d)
    rs = np.random.RandomState(123)
    xb = rs.randn(256, d).astype("float32")
    xq = rs.randn(3, d).astype("float32")
    # Normalize for cosine-as-IP
    xb /= np.linalg.norm(xb, axis=1, keepdims=True) + 1e-12
    xq /= np.linalg.norm(xq, axis=1, keepdims=True) + 1e-12
    idx.add(xb)
    _distances, indices = idx.search(xq, 5)
    assert indices.shape == (3, 5)
