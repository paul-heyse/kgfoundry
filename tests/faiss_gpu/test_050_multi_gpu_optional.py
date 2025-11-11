from typing import Any, cast

import faiss
import numpy as np
import pytest

FAISS = cast("Any", faiss)


def test_multi_gpu_all_gpus(train_db, query_db, k):
    ng = FAISS.get_num_gpus()
    if ng < 2:
        pytest.skip("Only 1 GPU available")

    d = train_db.shape[1]
    cpu = FAISS.IndexFlatL2(d)
    cpu.add(train_db)
    D_cpu, I_cpu = cpu.search(query_db, k)

    # Build across all GPUs
    gpu = FAISS.index_cpu_to_all_gpus(cpu)
    Dg, Ig = gpu.search(query_db, k)

    # Exact Flat should match across all GPUs as well
    np.testing.assert_allclose(Dg, D_cpu, rtol=1e-6, atol=1e-6)
    assert np.array_equal(Ig, I_cpu)
