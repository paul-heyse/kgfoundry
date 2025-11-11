from typing import Any, cast

import faiss
import pytest

FAISS = cast(Any, faiss)

def test_ivfflat_cuvs_enabled_if_available(train_db, query_db, k, gpu_require):
    gpu_require(FAISS.get_num_gpus() > 0, "No GPUs visible")
    d = train_db.shape[1]

    # Only run if config exposes use_cuvs
    if not hasattr(FAISS, "GpuIndexIVFFlatConfig") or not hasattr(
        FAISS.GpuIndexIVFFlatConfig(), "use_cuvs"
    ):
        pytest.skip("cuVS toggle not available in this build")

    cfg = FAISS.GpuIndexIVFFlatConfig()
    cfg.device = 0
    cfg.use_cuvs = True  # prefer cuVS kernels when supported

    res = FAISS.StandardGpuResources()
    nlist = 128
    # Build/train on CPU then construct GPU IVF with config
    quant = FAISS.IndexFlatL2(d)
    cpu_ivf = FAISS.IndexIVFFlat(quant, d, nlist, FAISS.METRIC_L2)
    cpu_ivf.train(train_db)

    gpu_ivf = FAISS.GpuIndexIVFFlat(res, cpu_ivf)  # copy trained IVF onto GPU
    gpu_ivf.nprobe = 16
    distances, neighbors = gpu_ivf.search(query_db, k)
    assert distances.shape == (query_db.shape[0], k)
    assert neighbors.shape == (query_db.shape[0], k)
