#!/usr/bin/env python3
"""GPU diagnostics script for PyTorch and FAISS.

Tiny GPU diagnostics for PyTorch and FAISS:
- Initializes CUDA context
- Runs a small GEMM in torch (cuBLAS path)
- Runs a tiny FAISS-GPU search (GpuIndexFlatIP)

Exits non-zero if --require-gpu is set and a GPU isn't usable.

Usage:
    python -m codeintel_rev.mcp_server.tools.gpu_doctor
    python -m codeintel_rev.mcp_server.tools.gpu_doctor --require-gpu
    python -m codeintel_rev.mcp_server.tools.gpu_doctor --torch-only
    python -m codeintel_rev.mcp_server.tools.gpu_doctor --faiss-only
"""

from __future__ import annotations

import argparse
import sys
import traceback
from typing import cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import FaissModule, NumpyModule, TorchModule, gate_import

np = cast("NumpyModule", LazyModule("numpy", "GPU diagnostics random probes"))


def check_torch(device_index: int = 0) -> tuple[bool, dict[str, object]]:
    """Check PyTorch CUDA availability and perform smoke test.

    Parameters
    ----------
    device_index : int, optional
        CUDA device index to test (default: 0).

    Returns
    -------
    tuple[bool, dict[str, object]]
        (success, info_dict) where info_dict contains diagnostic information.
    """
    info: dict[str, object] = {}
    try:
        torch = cast("TorchModule", gate_import("torch", "GPU diagnostics (torch)"))
    except ImportError as exc:
        return False, {"error": f"torch import failed: {exc}"}

    info["torch_import_ok"] = True
    info["torch_version"] = getattr(torch, "__version__", None)
    version_mod = getattr(torch, "version", None)
    info["cuda_version"] = getattr(version_mod, "cuda", None) if version_mod else None

    if not torch.cuda.is_available():
        return False, {"error": "torch.cuda.is_available() is False", **info}

    try:
        torch.cuda.init()
        ndev = torch.cuda.device_count()
        info["device_count"] = ndev
        if ndev == 0:
            return False, {"error": "No CUDA devices visible", **info}
        device_index = min(device_index, ndev - 1)
        name = torch.cuda.get_device_name(device_index)
        cap = ".".join(map(str, torch.cuda.get_device_capability(device_index)))
        props = torch.cuda.get_device_properties(device_index)
        info.update(
            {
                "device_index": device_index,
                "device_name": name,
                "compute_capability": cap,
                "total_mem_bytes": props.total_memory,
            }
        )
        # tiny GEMM to exercise cuBLAS, plus a sync
        dev = torch.device(f"cuda:{device_index}")
        a = torch.randn(256, 256, device=dev)
        b = torch.randn(256, 256, device=dev)
        c = a @ b
        _ = float(c.sum().item())
        torch.cuda.synchronize()
    except (RuntimeError, OSError) as exc:
        info["error"] = f"torch CUDA smoke failed: {exc}"
        info["traceback"] = traceback.format_exc()
        return False, info
    else:
        return True, info


def check_faiss() -> tuple[bool, dict[str, object]]:
    """Check FAISS GPU availability and perform smoke test.

    Returns
    -------
    tuple[bool, dict[str, object]]
        (success, info_dict) where info_dict contains diagnostic information.
    """
    info: dict[str, object] = {}
    try:
        faiss = cast("FaissModule", gate_import("faiss", "GPU diagnostics (faiss)"))
    except ImportError as exc:
        return False, {"error": f"faiss import failed: {exc}"}

    info["faiss_import_ok"] = True
    # version isn't a public API; capture a best-effort string
    info["faiss_has_gpu"] = hasattr(faiss, "StandardGpuResources")

    if not info["faiss_has_gpu"]:
        return False, {
            "error": "FAISS not built with GPU bindings (StandardGpuResources missing)",
            **info,
        }

    try:
        ngpu = faiss.get_num_gpus() if hasattr(faiss, "get_num_gpus") else 0
        info["faiss_visible_gpus"] = ngpu
        if ngpu <= 0:
            return False, {"error": "faiss.get_num_gpus() returned 0", **info}

        res = faiss.StandardGpuResources()
        d = 64
        idx = faiss.GpuIndexFlatIP(res, d)
        rs = np.random.RandomState(0)
        xb = rs.randn(128, d).astype("float32")
        xq = rs.randn(4, d).astype("float32")
        # normalize for cosine-as-IP; harmless for L2 (you can remove if you use L2)
        xb /= np.linalg.norm(xb, axis=1, keepdims=True) + 1e-12
        xq /= np.linalg.norm(xq, axis=1, keepdims=True) + 1e-12
        idx.add(xb)
        _distances, indices = idx.search(xq, 5)
        ok = indices.shape == (4, 5)
        info["index_ok"] = ok
    except (RuntimeError, OSError, AttributeError) as exc:
        info["error"] = f"FAISS GPU smoke failed: {exc}"
        info["traceback"] = traceback.format_exc()
        return False, info
    else:
        if ok:
            return True, info
        return False, {"error": "Unexpected search shape", **info}


def main() -> None:
    """Run GPU diagnostics and print results.

    Parses command-line arguments and runs GPU checks. Exits with non-zero
    status if --require-gpu is set and GPU is not usable.
    """
    ap = argparse.ArgumentParser(
        description="GPU diagnostics for PyTorch and FAISS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--require-gpu",
        action="store_true",
        help="Exit non-zero if GPU isn't usable",
    )
    ap.add_argument(
        "--device-index",
        type=int,
        default=0,
        help="CUDA device index to exercise (torch)",
    )
    ap.add_argument(
        "--torch-only",
        action="store_true",
        help="Only run the PyTorch checks",
    )
    ap.add_argument(
        "--faiss-only",
        action="store_true",
        help="Only run the FAISS checks",
    )
    args = ap.parse_args()

    # Print diagnostics (print is acceptable for CLI tools)

    torch_ok: bool | None = None
    faiss_ok: bool | None = None

    if not args.faiss_only:
        torch_ok, _torch_info = check_torch(args.device_index)

    if not args.torch_only:
        faiss_ok, _faiss_info = check_faiss()

    if args.require_gpu:
        failed = (torch_ok is False) or (faiss_ok is False)
        sys.exit(1 if failed else 0)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
