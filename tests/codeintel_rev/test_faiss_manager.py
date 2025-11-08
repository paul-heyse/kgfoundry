from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from codeintel_rev.io.faiss_manager import FAISSManager

from tests.conftest import HAS_FAISS_SUPPORT

if not HAS_FAISS_SUPPORT:  # pragma: no cover - dependency-gated
    pytestmark = pytest.mark.skip(
        reason="FAISS bindings unavailable on this host",
    )
else:
    import faiss


class _SentinelGpuIndex:
    pass


@pytest.fixture
def faiss_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FAISSManager:
    manager = FAISSManager(index_path=tmp_path / "index.faiss", use_cuvs=False)
    # CPU index presence is validated by identity only in tests
    manager.cpu_index = cast("faiss.Index", object())

    class DummyGpuClonerOptions:
        def __init__(self) -> None:
            self.useFloat16 = False
            self.use_cuvs = False

    monkeypatch.setattr(
        faiss,
        "GpuClonerOptions",
        DummyGpuClonerOptions,
        raising=False,
    )
    return manager


def test_clone_to_gpu_success(monkeypatch: pytest.MonkeyPatch, faiss_manager: FAISSManager) -> None:
    """GPU cloning succeeds when FAISS GPU helpers work."""
    gpu_resources = object()
    gpu_index = _SentinelGpuIndex()

    monkeypatch.setattr(faiss, "StandardGpuResources", lambda: gpu_resources, raising=False)

    def fake_index_cpu_to_gpu(
        resources: object, device: int, cpu_index: object, options: faiss.GpuClonerOptions
    ) -> object:
        assert resources is gpu_resources
        assert cpu_index is faiss_manager.cpu_index
        assert device == 0
        assert isinstance(options, faiss.GpuClonerOptions)
        return gpu_index

    monkeypatch.setattr(faiss, "index_cpu_to_gpu", fake_index_cpu_to_gpu, raising=False)

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

    monkeypatch.setattr(faiss, "StandardGpuResources", failing_resources, raising=False)

    success = faiss_manager.clone_to_gpu()

    assert success is False
    assert faiss_manager.gpu_index is None
    assert faiss_manager.gpu_resources is None
    assert faiss_manager.gpu_disabled_reason is not None
    assert "CUDA unavailable" in faiss_manager.gpu_disabled_reason
