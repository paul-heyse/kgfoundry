import importlib.util as u
from typing import Any, cast

import faiss

FAISS = cast("Any", faiss)


def test_gpu_wrapper_present_and_device_visible(gpu_require):
    # 1) GPU wrapper shared object present?
    spec = u.find_spec("faiss._swigfaiss_gpu")
    gpu_require(spec is not None, "faiss._swigfaiss_gpu not found in this build")

    # 2) At least one CUDA device visible to Faiss?
    ng = FAISS.get_num_gpus()
    gpu_require(ng > 0, f"No CUDA devices visible to Faiss (get_num_gpus={ng})")


def test_standard_gpu_resources_constructs():
    res = FAISS.StandardGpuResources()  # must not raise
    # Optional: exercise resource knobs commonly documented
    if hasattr(res, "setTempMemory"):
        res.setTempMemory(64 * 1024 * 1024)  # 64MiB scratch
