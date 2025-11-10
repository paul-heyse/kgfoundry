from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from codeintel_rev.app import config_context as config_module
from codeintel_rev.errors import RuntimeUnavailableError

from tests.app._context_factory import build_application_context


def test_coderank_faiss_missing_index_raises_runtime_unavailable(tmp_path: Path) -> None:
    ctx = build_application_context(tmp_path)
    ctx.paths.coderank_faiss_index.unlink(missing_ok=True)

    with pytest.raises(RuntimeUnavailableError) as excinfo:
        ctx.get_coderank_faiss_manager(vec_dim=256)

    assert excinfo.value.context["runtime"] == "coderank-faiss"


def test_coderank_faiss_missing_dependency_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = build_application_context(tmp_path)
    original_gate = config_module.gate_import

    def fake_gate(module: str, purpose: str) -> object:
        if module == "faiss":
            error_msg = "faiss missing"
            raise ImportError(error_msg)
        return original_gate(module, purpose)

    monkeypatch.setattr(config_module, "gate_import", fake_gate)

    with pytest.raises(RuntimeUnavailableError) as excinfo:
        ctx.get_coderank_faiss_manager(vec_dim=64)

    assert "faiss" in str(excinfo.value)


def test_xtr_missing_artifacts_raise(tmp_path: Path) -> None:
    ctx = build_application_context(tmp_path, xtr_enabled=True)
    shutil.rmtree(ctx.paths.xtr_dir)

    with pytest.raises(RuntimeUnavailableError) as excinfo:
        ctx.get_xtr_index()

    assert excinfo.value.context["runtime"] == "xtr"


def test_xtr_missing_dependency_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = build_application_context(tmp_path, xtr_enabled=True)
    original_gate = config_module.gate_import

    def fake_gate(module: str, purpose: str) -> object:
        if module == "torch":
            error_msg = "torch missing"
            raise ImportError(error_msg)
        return original_gate(module, purpose)

    monkeypatch.setattr(config_module, "gate_import", fake_gate)

    with pytest.raises(RuntimeUnavailableError):
        ctx.get_xtr_index()
