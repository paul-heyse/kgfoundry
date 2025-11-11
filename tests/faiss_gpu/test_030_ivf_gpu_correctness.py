from typing import Any, cast

import faiss
import pytest

FAISS = cast("Any", faiss)


def recall_at_k(ids_gold, ids_test):
    # Fraction of queries whose true NN (top-1) is in test top-k
    return (ids_gold[:, :1] == ids_test).any(axis=1).mean()


@pytest.mark.parametrize("ivf_params", [(128, 16), (256, 32)])
def test_ivfflat_gpu_vs_cpu_recall(train_db, query_db, k, ivf_params, gpu_require):
    gpu_require(FAISS.get_num_gpus() > 0, "No GPUs visible")

    d = train_db.shape[1]
    nlist, nprobe = ivf_params

    # Exact CPU baseline for "true" neighbors
    flat = FAISS.IndexFlatL2(d)
    flat.add(train_db)
    _, ids_true = flat.search(query_db, k)

    # IVF on CPU (for parity with GPU params)
    quant = FAISS.IndexFlatL2(d)
    ivf_cpu = FAISS.IndexIVFFlat(quant, d, nlist, FAISS.METRIC_L2)
    ivf_cpu.train(train_db)
    ivf_cpu.nprobe = nprobe
    ivf_cpu.add(train_db)

    # Move trained IVF to GPU and search
    res = FAISS.StandardGpuResources()
    try:
        ivf_gpu = FAISS.index_cpu_to_gpu(res, 0, ivf_cpu, None)
        ivf_gpu.nprobe = nprobe
        _, ids_gpu = ivf_gpu.search(query_db, k)
    except RuntimeError as exc:  # pragma: no cover - GPU stack optional
        pytest.skip(f"IVF GPU search unavailable: {exc}")

    # Ensure recall stays in a healthy range even without tuning hyper-parameters.
    r = recall_at_k(ids_true, ids_gpu)
    assert r >= 0.80, f"IVF recall too low: {r:.3f}"
