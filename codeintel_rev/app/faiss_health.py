"""FAISS CPU health checks used during application startup."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, cast

from codeintel_rev.typing import gate_import

__all__ = ["check_faiss_health"]


def _faiss_cpu_smoke() -> tuple[bool, str]:
    """Run a tiny IndexFlat search to ensure FAISS works on CPU.

    Returns
    -------
    tuple[bool, str]
        Tuple of (test_passed, human-readable status message).
    """
    try:
        faiss = cast("Any", gate_import("faiss", "FAISS CPU health check"))
    except ImportError:
        return False, "FAISS module not installed"
    except (RuntimeError, AttributeError, OSError) as exc:
        return False, f"FAISS import failed: {exc}"

    try:
        np_mod = cast("Any", gate_import("numpy", "FAISS health check vectors"))
    except ImportError:
        return False, "NumPy module not installed"

    try:
        dimension = 64
        index = faiss.IndexFlatIP(dimension)
        xb = np_mod.random.standard_normal((256, dimension)).astype("float32")
        xq = np_mod.random.standard_normal((4, dimension)).astype("float32")
        faiss.normalize_L2(xb)
        faiss.normalize_L2(xq)
        index.add(xb)
        distances, labels = index.search(xq, 10)
    except (RuntimeError, ValueError, AttributeError) as exc:
        return False, f"FAISS CPU smoke test failed: {exc}"

    if distances.shape != (4, 10) or labels.shape != (4, 10):
        return False, "FAISS search returned unexpected shapes"
    return True, "FAISS IndexFlat search succeeded"


@lru_cache(maxsize=1)
def check_faiss_health() -> dict[str, bool | str | float | None]:
    """Perform a FAISS CPU health check and return structured status.

    Returns
    -------
    dict[str, bool | str | float | None]
        Mapping containing FAISS availability, smoke-test result, version info,
        and overall status metadata.
    """
    status: dict[str, bool | str | float | None] = {
        "faiss_available": False,
        "faiss_cpu_smoke": False,
        "faiss_version": None,
        "overall_status": "unavailable",
        "details": "FAISS health check not started",
    }

    try:
        faiss = cast("Any", gate_import("faiss", "FAISS CPU health check"))
    except ImportError:
        status["details"] = "FAISS module not installed"
        return status
    except (RuntimeError, AttributeError, OSError) as exc:
        status["details"] = f"FAISS import failed: {exc}"
        return status

    status["faiss_version"] = getattr(faiss, "__version__", None)
    status["faiss_available"] = True

    smoke_ok, smoke_msg = _faiss_cpu_smoke()
    status["faiss_cpu_smoke"] = smoke_ok
    status["details"] = smoke_msg
    status["overall_status"] = "ready" if smoke_ok else "unavailable"
    return status
