from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from codeintel_rev.io.faiss_manager import FAISSManager

from tests.conftest import FAISS_MODULE, HAS_FAISS_SUPPORT

if not HAS_FAISS_SUPPORT:  # pragma: no cover - dependency-gated
    pytestmark = pytest.mark.skip(
        reason="FAISS bindings unavailable on this host",
    )

if FAISS_MODULE is None:  # pragma: no cover - dependency-gated
    pytest.skip("FAISS bindings unavailable on this host", allow_module_level=True)

faiss_module: Any = FAISS_MODULE


class _SentinelGpuIndex:
    pass


@pytest.fixture
def faiss_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FAISSManager:
    manager = FAISSManager(index_path=tmp_path / "index.faiss", use_cuvs=False)
    # Use a lightweight flat index stub for type stability
    manager.cpu_index = faiss_module.IndexFlatIP(2)

    class DummyGpuClonerOptions:
        def __init__(self) -> None:
            self.useFloat16 = False
            self.use_cuvs = False

    monkeypatch.setattr(faiss_module, "GpuClonerOptions", DummyGpuClonerOptions, raising=False)
    return manager


def test_clone_to_gpu_success(monkeypatch: pytest.MonkeyPatch, faiss_manager: FAISSManager) -> None:
    """GPU cloning succeeds when FAISS GPU helpers work."""
    gpu_resources = object()
    gpu_index = _SentinelGpuIndex()

    monkeypatch.setattr(faiss_module, "StandardGpuResources", lambda: gpu_resources, raising=False)

    def fake_index_cpu_to_gpu(
        resources: object, device: int, cpu_index: object, options: object
    ) -> object:
        assert resources is gpu_resources
        assert cpu_index is faiss_manager.cpu_index
        assert device == 0
        assert isinstance(options, faiss_module.GpuClonerOptions)
        return gpu_index

    monkeypatch.setattr(faiss_module, "index_cpu_to_gpu", fake_index_cpu_to_gpu, raising=False)

    success = faiss_manager.clone_to_gpu()

    assert success is True
    assert faiss_manager.gpu_index is gpu_index
    assert faiss_manager.gpu_resources is gpu_resources
    assert faiss_manager.gpu_disabled_reason is None


def test_clone_to_gpu_falls_back(
    monkeypatch: pytest.MonkeyPatch, faiss_manager: FAISSManager
) -> None:
    """GPU cloning failure is logged and returns False without raising."""

    def failing_resources() -> None:
        msg = "CUDA unavailable"
        raise RuntimeError(msg)

    monkeypatch.setattr(faiss_module, "StandardGpuResources", failing_resources, raising=False)

    success = faiss_manager.clone_to_gpu()

    assert success is False
    assert faiss_manager.gpu_index is None
    assert faiss_manager.gpu_resources is None
    assert faiss_manager.gpu_disabled_reason is not None
    assert "CUDA unavailable" in faiss_manager.gpu_disabled_reason
