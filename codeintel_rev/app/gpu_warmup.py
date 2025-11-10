"""GPU warmup and initialization sequence.

Performs comprehensive GPU availability checks and warmup operations to ensure
GPU is reachable and functional before expensive operations begin.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, cast

from kgfoundry_common.logging import get_logger
from kgfoundry_common.typing import gate_import

if TYPE_CHECKING:
    import faiss as _faiss
    import torch as _torch

LOGGER = get_logger(__name__)

__all__ = ["warmup_gpu"]

# Constants for GPU warmup checks
_TOTAL_GPU_CHECKS = 4
_MIN_CHECKS_FOR_DEGRADED = 2


def _check_cuda_availability() -> tuple[bool, str]:
    """Check CUDA availability via PyTorch.

    Returns
    -------
    tuple[bool, str]
        (is_available, status_message)
    """
    try:
        torch = cast("_torch", gate_import("torch", "CUDA availability checks for warmup"))

        cuda_available = torch.cuda.is_available()
        if not cuda_available:
            LOGGER.warning("CUDA not available via PyTorch")
            return (
                False,
                "CUDA not available",
            )
        else:  # noqa: RET505  # else block required by TRY300 for explicit control flow
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
    except ImportError:
        LOGGER.warning("PyTorch not available - skipping CUDA check")
        return False, "PyTorch not installed"
    except (RuntimeError, AttributeError, OSError) as exc:
        LOGGER.warning("CUDA availability check failed: %s", exc, exc_info=True)
        return False, f"CUDA check error: {exc}"


def _check_faiss_gpu_support() -> tuple[bool, str]:
    """Check FAISS GPU support.

    Returns
    -------
    tuple[bool, str]
        (is_available, status_message)
    """
    try:
        faiss = cast("_faiss", gate_import("faiss", "FAISS GPU capability checks"))

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
        else:  # noqa: RET505  # else block required by TRY300 for explicit control flow
            LOGGER.info("FAISS GPU symbols available")
            return True, "FAISS GPU symbols available"
    except ImportError:
        LOGGER.warning("FAISS not available - skipping GPU check")
        return False, "FAISS not installed"
    except (RuntimeError, AttributeError, OSError) as exc:
        LOGGER.warning("FAISS GPU check failed: %s", exc, exc_info=True)
        return False, f"FAISS GPU check error: {exc}"


def _test_torch_gpu_operations() -> tuple[bool, str]:
    """Test basic GPU tensor operations using PyTorch.

    Returns
    -------
    tuple[bool, str]
        (test_passed, status_message)
    """
    try:
        torch = cast("_torch", gate_import("torch", "Torch GPU smoke test"))

        if not torch.cuda.is_available():
            return False, "CUDA not available for torch test"
        else:  # noqa: RET505  # else block required by TRY300 for explicit control flow
            # Create a small tensor on GPU and perform basic operations
            device = torch.device("cuda:0")
            test_tensor = torch.randn(100, 100, device=device)
            _ = torch.matmul(test_tensor, test_tensor.T)
            torch.cuda.synchronize()  # Wait for GPU operations to complete
            LOGGER.info("Torch GPU operations test passed")
            return True, "Torch GPU operations test passed"
    except ImportError:
        return False, "PyTorch not installed"
    except (RuntimeError, OSError, AttributeError) as exc:
        LOGGER.warning("Torch GPU operations test failed: %s", exc, exc_info=True)
        return False, f"Torch GPU test error: {exc}"


def _test_faiss_gpu_resources() -> tuple[bool, str]:
    """Test FAISS GPU resource initialization.

    Returns
    -------
    tuple[bool, str]
        (test_passed, status_message)
    """
    try:
        faiss = cast("_faiss", gate_import("faiss", "FAISS GPU resource smoke test"))

        # Check if FAISS GPU symbols are available first
        if not all(hasattr(faiss, attr) for attr in ("StandardGpuResources",)):
            return False, "FAISS GPU symbols not available"
        else:  # noqa: RET505  # else block required by TRY300 for explicit control flow
            # Initialize GPU resources (this is lightweight)
            _ = faiss.StandardGpuResources()
            LOGGER.info("FAISS GPU resource initialization test passed")
            return True, "FAISS GPU resource initialization test passed"
    except ImportError:
        return False, "FAISS not installed"
    except (RuntimeError, AttributeError, OSError) as exc:
        LOGGER.warning("FAISS GPU resource initialization failed: %s", exc, exc_info=True)
        return False, f"FAISS GPU init error: {exc}"


@lru_cache(maxsize=1)
@lru_cache(maxsize=1)
def warmup_gpu() -> dict[str, bool | str]:
    """Perform GPU warmup sequence to verify GPU availability and functionality.

    Results are cached after the first run; call ``warmup_gpu.cache_clear()`` in tests
    to force a re-run.

    Checks:
    1. CUDA availability via PyTorch
    2. FAISS GPU support
    3. Basic GPU tensor operations (torch)
    4. FAISS GPU resource initialization

    Returns
    -------
    dict[str, bool | str]
        Dictionary with warmup results:
        - ``cuda_available``: True if CUDA is available via PyTorch
        - ``faiss_gpu_available``: True if FAISS GPU symbols are available
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

    # Step 3: Test basic GPU tensor operations (torch)
    if cuda_available:
        torch_test_passed, _torch_msg = _test_torch_gpu_operations()
        results["torch_gpu_test"] = torch_test_passed

    # Step 4: Test FAISS GPU resource initialization
    if faiss_gpu_available:
        faiss_test_passed, _faiss_test_msg = _test_faiss_gpu_resources()
        results["faiss_gpu_test"] = faiss_test_passed

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
