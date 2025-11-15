"""GPU warmup and initialization sequence.

Performs comprehensive GPU availability checks and warmup operations to ensure
GPU is reachable and functional before expensive operations begin.
"""

from __future__ import annotations

from functools import lru_cache
from typing import SupportsInt, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import FaissModule, NumpyModule, TorchModule, gate_import
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)

__all__ = ["warmup_gpu"]

# Constants for GPU warmup checks
_TOTAL_GPU_CHECKS = 4
_MIN_CHECKS_FOR_DEGRADED = 2

np = cast("NumpyModule", LazyModule("numpy", "FAISS manager vector operations"))


def _check_cuda_availability() -> tuple[bool, str]:
    """Check CUDA availability via PyTorch.

    Returns
    -------
    tuple[bool, str]
        (is_available, status_message)
    """
    try:
        torch = cast("TorchModule", gate_import("torch", "CUDA availability checks for warmup"))
    except ImportError:
        LOGGER.warning("PyTorch not available - skipping CUDA check")
        return False, "PyTorch not installed"
    except (RuntimeError, AttributeError, OSError) as exc:
        LOGGER.warning("CUDA availability check failed: %s", exc, exc_info=True)
        return False, f"CUDA check error: {exc}"
    else:
        cuda_available = torch.cuda.is_available()
        if not cuda_available:
            LOGGER.warning("CUDA not available via PyTorch")
            return (
                False,
                "CUDA not available",
            )
        device_count = torch.cuda.device_count()
        current_device = torch.cuda.current_device()
        device_name = torch.cuda.get_device_name(current_device)
        LOGGER.info(
            "CUDA available: %s devices, current device %s: %s",
            device_count,
            current_device,
            device_name,
        )
        return True, f"CUDA available ({device_count} devices)"


def _check_faiss_gpu_support() -> tuple[bool, str]:
    """Check FAISS GPU support.

    Returns
    -------
    tuple[bool, str]
        (is_available, status_message)
    """
    try:
        faiss = cast("FaissModule", gate_import("faiss", "FAISS GPU capability checks"))
    except ImportError:
        LOGGER.warning("FAISS not available - skipping GPU check")
        return False, "FAISS not installed"
    except (RuntimeError, AttributeError, OSError) as exc:
        LOGGER.warning("FAISS GPU check failed: %s", exc, exc_info=True)
        return False, f"FAISS GPU check error: {exc}"
    else:
        required_attrs = (
            "StandardGpuResources",
            "GpuClonerOptions",
            "index_cpu_to_gpu",
        )
        faiss_gpu_available = all(hasattr(faiss, attr) for attr in required_attrs)
        if not faiss_gpu_available:
            LOGGER.warning("FAISS GPU symbols not available")
            return (
                False,
                "FAISS GPU symbols not available",
            )
        LOGGER.info("FAISS GPU symbols available")
        return True, "FAISS GPU symbols available"


def _test_torch_gpu_operations() -> tuple[bool, str]:
    """Test basic GPU tensor operations using PyTorch.

    Returns
    -------
    tuple[bool, str]
        (test_passed, status_message)
    """
    try:
        torch = cast("TorchModule", gate_import("torch", "Torch GPU smoke test"))
    except ImportError:
        return False, "PyTorch not installed"
    except (RuntimeError, OSError, AttributeError) as exc:
        LOGGER.warning("Torch GPU operations test failed: %s", exc, exc_info=True)
        return False, f"Torch GPU test error: {exc}"
    else:
        if not torch.cuda.is_available():
            return False, "CUDA not available for torch test"
        device = torch.device("cuda:0")
        test_tensor = torch.randn(100, 100, device=device)
        _ = torch.matmul(test_tensor, test_tensor.T)
        torch.cuda.synchronize()  # Wait for GPU operations to complete
        LOGGER.info("Torch GPU operations test passed")
        return True, "Torch GPU operations test passed"


def _test_faiss_gpu_resources() -> tuple[bool, str, int | None]:
    """Test FAISS GPU resource initialization.

    Returns
    -------
    tuple[bool, str, int | None]
        Tuple of (test_passed, status_message, scratch_bytes).
    """
    try:
        faiss = cast("FaissModule", gate_import("faiss", "FAISS GPU resource smoke test"))
    except ImportError:
        return False, "FAISS not installed", None
    except (RuntimeError, AttributeError, OSError) as exc:
        LOGGER.warning("FAISS GPU resource initialization failed: %s", exc, exc_info=True)
        return False, f"FAISS GPU init error: {exc}", None
    else:
        if not all(hasattr(faiss, attr) for attr in ("StandardGpuResources",)):
            return False, "FAISS GPU symbols not available", None
        resources = faiss.StandardGpuResources()
        scratch_bytes: int | None = None
        get_temp = getattr(resources, "getTempMemory", None)
        if callable(get_temp):
            try:
                raw_value = get_temp()
                scratch_bytes = int(cast("SupportsInt", raw_value))
            except (RuntimeError, ValueError, TypeError):  # pragma: no cover - defensive
                scratch_bytes = None
        LOGGER.info("FAISS GPU resource initialization test passed")
        return True, "FAISS GPU resource initialization test passed", scratch_bytes


@lru_cache(maxsize=1)
def warmup_gpu() -> dict[str, bool | str]:
    """Perform GPU warmup sequence to verify GPU availability and functionality.

    Results are cached after the first run; call ``warmup_gpu.cache_clear()`` in tests
    to force a re-run.

    Checks:
    1. CUDA availability via PyTorch
    2. FAISS GPU support (+ cuVS/CAGRA symbol presence)
    3. Basic GPU tensor operations (torch)
    4. FAISS GPU resource initialization

    Returns
    -------
    dict[str, bool | str]
        Dictionary with warmup results:
        - ``cuda_available``: True if CUDA is available via PyTorch
        - ``faiss_gpu_available``: True if FAISS GPU symbols are available
        - ``faiss_cuvs_available``: True if FAISS exposes cuVS/CAGRA bindings
        - ``torch_gpu_test``: True if basic torch GPU operations succeed
        - ``faiss_gpu_test``: True if FAISS GPU resource initialization succeeds
        - ``overall_status``: "ready" if all checks pass, "degraded" if some fail,
          "unavailable" if all fail
        - ``details``: Human-readable status message

    Examples
    --------
    >>> result = warmup_gpu()
    >>> if result["overall_status"] == "ready":
    ...     print("GPU is ready for use")
    ... else:
    ...     print(f"GPU status: {result['details']}")
    """
    results: dict[str, bool | str] = {
        "cuda_available": False,
        "faiss_gpu_available": False,
        "torch_gpu_test": False,
        "faiss_gpu_test": False,
        "faiss_cuvs_available": False,
        "overall_status": "unavailable",
        "details": "GPU warmup not attempted",
    }

    # Step 1: Check CUDA availability via PyTorch
    cuda_available, cuda_msg = _check_cuda_availability()
    results["cuda_available"] = cuda_available
    if not cuda_available:
        results["details"] = cuda_msg

    # Step 2: Check FAISS GPU support
    faiss_gpu_available, faiss_msg = _check_faiss_gpu_support()
    results["faiss_gpu_available"] = faiss_gpu_available
    if not faiss_gpu_available and results["details"] == "GPU warmup not attempted":
        results["details"] = faiss_msg
    try:
        faiss_mod = cast("FaissModule", gate_import("faiss", "FAISS cuVS probe"))
        results["faiss_cuvs_available"] = bool(getattr(faiss_mod, "GpuIndexCagra", None))
    except ImportError:
        results["faiss_cuvs_available"] = False

    # Step 3: Test basic GPU tensor operations (torch)
    if cuda_available:
        torch_test_passed, _torch_msg = _test_torch_gpu_operations()
        results["torch_gpu_test"] = torch_test_passed

    # Step 4: Test FAISS GPU resource initialization
    if faiss_gpu_available:
        faiss_test_passed, _faiss_test_msg, scratch_bytes = _test_faiss_gpu_resources()
        results["faiss_gpu_test"] = faiss_test_passed
        # scratch_bytes available but not recorded (observability removed)

    # Determine overall status
    # Count boolean checks only (exclude string fields)
    checks_passed = sum(
        [
            bool(results["cuda_available"]),
            bool(results["faiss_gpu_available"]),
            bool(results["torch_gpu_test"]),
            bool(results["faiss_gpu_test"]),
        ]
    )

    if checks_passed == _TOTAL_GPU_CHECKS:
        results["overall_status"] = "ready"
        results["details"] = f"GPU warmup complete - all {_TOTAL_GPU_CHECKS} checks passed"
    elif checks_passed >= _MIN_CHECKS_FOR_DEGRADED:
        results["overall_status"] = "degraded"
        results["details"] = (
            f"GPU warmup partial - {checks_passed}/{_TOTAL_GPU_CHECKS} checks passed"
        )
    else:
        results["overall_status"] = "unavailable"
        results["details"] = (
            f"GPU warmup failed - {checks_passed}/{_TOTAL_GPU_CHECKS} checks passed"
        )

    LOGGER.info("GPU warmup complete: %s", results["details"])
    return results
