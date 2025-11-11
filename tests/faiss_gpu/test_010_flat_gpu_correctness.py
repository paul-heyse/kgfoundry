from typing import Any, cast

import faiss
import numpy as np
import pytest

FAISS = cast("Any", faiss)


@pytest.mark.parametrize(
    "index_classes",
    [
        (FAISS.IndexFlatL2, FAISS.GpuIndexFlatL2),
        (FAISS.IndexFlatIP, FAISS.GpuIndexFlatIP),
    ],
)
def test_gpu_flat_matches_cpu(train_db, query_db, k, index_classes, gpu_require):
    # Ensure GPU is usable
    gpu_require(FAISS.get_num_gpus() > 0, "No GPUs visible to Faiss")

    d = train_db.shape[1]
    cpu_cls, gpu_cls = index_classes
    # CPU exact baseline
    cpu = cpu_cls(d)
    cpu.add(train_db)
    Dc, Ic = cpu.search(query_db, k)

    # GPU exact
    res = FAISS.StandardGpuResources()
    cfg = FAISS.GpuIndexFlatConfig()
    cfg.device = 0  # first GPU
    gpu = gpu_cls(res, d, cfg)
    try:
        Dg, Ig = gpu.search(query_db, k)
    except RuntimeError as exc:  # pragma: no cover - GPU stack optional
        pytest.skip(f"GPU flat index search unavailable: {exc}")

    # Exact flat indexes should match exactly (ordering ties aside)
    np.testing.assert_allclose(Dg, Dc, rtol=1e-6, atol=1e-6)
    assert np.array_equal(Ig, Ic)
