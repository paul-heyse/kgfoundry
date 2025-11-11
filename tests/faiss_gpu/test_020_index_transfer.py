from typing import Any, cast

import faiss
import numpy as np
import pytest

FAISS = cast("Any", faiss)


def test_cpu_to_gpu_and_back_roundtrip(train_db, query_db, k, gpu_require):
    gpu_require(FAISS.get_num_gpus() > 0, "No GPUs visible")

    d = train_db.shape[1]
    cpu = FAISS.IndexFlatL2(d)
    cpu.add(train_db)

    res = FAISS.StandardGpuResources()
    try:
        gpu = FAISS.index_cpu_to_gpu(res, 0, cpu, None)  # build GPU clone
        Dg, Ig = gpu.search(query_db, k)
        cpu2 = FAISS.index_gpu_to_cpu(gpu)
        Dc2, Ic2 = cpu2.search(query_db, k)
    except RuntimeError as exc:  # pragma: no cover - GPU stack optional
        pytest.skip(f"GPU transfer unavailable: {exc}")

    # After roundtrip results should match CPU baseline
    Dc, Ic = cpu.search(query_db, k)
    np.testing.assert_allclose(Dg, Dc, rtol=1e-4, atol=1e-4)
    np.testing.assert_allclose(Dc2, Dc, rtol=1e-4, atol=1e-4)
    assert np.array_equal(np.sort(Ig, axis=1), np.sort(Ic, axis=1))
    assert np.array_equal(np.sort(Ic2, axis=1), np.sort(Ic, axis=1))
