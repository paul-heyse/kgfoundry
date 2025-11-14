from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.observability import runpack as runpack_module


@dataclass(slots=True, frozen=True)
class _PathsStub:
    repo_root: Path
    data_dir: Path
    vectors_dir: Path
    faiss_index: Path
    faiss_idmap_path: Path
    duckdb_path: Path
    scip_index: Path
    coderank_vectors_dir: Path
    coderank_faiss_index: Path
    warp_index_dir: Path
    xtr_dir: Path


def _make_context(tmp_path: Path) -> ApplicationContext:
    shared_path = tmp_path / "placeholder"
    shared_path.mkdir(parents=True, exist_ok=True)
    paths = _PathsStub(
        repo_root=tmp_path,
        data_dir=tmp_path / "data",
        vectors_dir=tmp_path / "vectors",
        faiss_index=tmp_path / "faiss.index",
        faiss_idmap_path=tmp_path / "faiss.idmap",
        duckdb_path=tmp_path / "catalog.duckdb",
        scip_index=tmp_path / "index.scip",
        coderank_vectors_dir=shared_path,
        coderank_faiss_index=shared_path,
        warp_index_dir=shared_path,
        xtr_dir=shared_path,
    )
    settings = SimpleNamespace(
        index=SimpleNamespace(
            vec_dim=256,
            rrf_k=60,
            enable_bm25_channel=True,
            enable_splade_channel=False,
            use_gpu=False,
            hybrid_top_k_per_channel=25,
        ),
        bm25=SimpleNamespace(enabled=True, rm3_enabled=False),
        splade=SimpleNamespace(enabled=False),
    )
    vllm_client = SimpleNamespace(
        config=SimpleNamespace(model="stub-model", base_url="http://localhost", embedding_dim=256),
        _mode="http",
    )
    faiss_manager = SimpleNamespace(
        index_path=tmp_path / "faiss.index",
        vec_dim=256,
        use_cuvs=True,
        gpu_index=None,
    )
    duckdb_manager = SimpleNamespace(_db_path=tmp_path / "catalog.duckdb")
    context = SimpleNamespace(
        paths=paths,
        settings=settings,
        vllm_client=vllm_client,
        faiss_manager=faiss_manager,
        duckdb_manager=duckdb_manager,
    )
    return cast("ApplicationContext", context)


@pytest.fixture(autouse=True)
def stub_report_builders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _DummyTimelineReport:
        def __init__(self) -> None:
            self._payload = {
                "session_id": "sess",
                "run_id": "run",
                "events": [
                    {
                        "type": "decision",
                        "name": "gate.budget",
                        "attrs": {"rrf_k": 42},
                    }
                ],
            }

        def to_dict(self) -> dict[str, Any]:
            return self._payload

    def _fake_timeline_report(**_kwargs: object) -> _DummyTimelineReport:
        return _DummyTimelineReport()

    def _fake_run_report(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(runpack_module, "build_timeline_run_report", _fake_timeline_report)
    monkeypatch.setattr(
        runpack_module,
        "latest_run_report",
        lambda: {"json": str(tmp_path / "latest.json")},
    )
    monkeypatch.setattr(runpack_module, "build_report", _fake_run_report)
    monkeypatch.setattr(runpack_module, "resolve_timeline_dir", lambda _=None: tmp_path)


def test_make_runpack_creates_zip(tmp_path: Path) -> None:
    context = _make_context(tmp_path)
    artifact = runpack_module.make_runpack(
        context=context,
        session_id="sess",
        run_id="run",
        trace_id="trace-123",
        reason="unit-test",
    )
    assert artifact.exists()
    with zipfile.ZipFile(artifact, "r") as archive:
        meta = json.loads(archive.read("meta.json"))
        assert meta["session_id"] == "sess"
        assert meta["trace_id"] == "trace-123"
        budgets = json.loads(archive.read("budgets.json"))
        assert budgets["rrf_k"] == 42
        context_blob = json.loads(archive.read("context.json"))
        assert context_blob["settings"]["index"]["vec_dim"] == 256
