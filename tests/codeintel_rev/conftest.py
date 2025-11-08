"""Shared pytest fixtures for tests in tests/codeintel_rev."""

import sys
import types

try:
    import faiss  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - fallback to stub when FAISS import fails
    sys.modules.pop("faiss", None)
    faiss_module = sys.modules.setdefault("faiss", types.ModuleType("faiss"))

    if not hasattr(faiss_module, "read_index"):

        def _read_index(_path: str) -> types.SimpleNamespace:
            return types.SimpleNamespace(ntotal=0)

        faiss_module.read_index = _read_index  # type: ignore[attr-defined]

    if not hasattr(faiss_module, "write_index"):

        def _write_index(_index: object, _path: str) -> None:
            return None

        faiss_module.write_index = _write_index  # type: ignore[attr-defined]

    if not hasattr(faiss_module, "StandardGpuResources"):

        class _StandardGpuResources:
            def __init__(self) -> None:
                self.initialized = True

        faiss_module.StandardGpuResources = _StandardGpuResources  # type: ignore[attr-defined]

    if not hasattr(faiss_module, "GpuClonerOptions"):

        class _GpuClonerOptions:
            def __init__(self) -> None:
                self.useFloat16 = False

        faiss_module.GpuClonerOptions = _GpuClonerOptions  # type: ignore[attr-defined]

    if not hasattr(faiss_module, "index_cpu_to_gpu"):

        def _index_cpu_to_gpu(*_args: object, **_kwargs: object) -> None:
            msg = "GPU unavailable in tests"
            raise RuntimeError(msg)

        faiss_module.index_cpu_to_gpu = _index_cpu_to_gpu  # type: ignore[attr-defined]

from codeintel_rev.tests.conftest import *  # noqa: F403,E402
