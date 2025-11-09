from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import numpy as np
import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.mcp_server.adapters import semantic_pro

from kgfoundry_common.errors import VectorSearchError


class _FakeEmbedder:
    def __init__(self, **_: object) -> None:
        pass

    def encode_queries(self, queries: list[str]) -> np.ndarray:
        assert queries, "queries should not be empty"
        return np.asarray([[0.1, 0.2]], dtype=np.float32)


class _FakeFaissManager:
    def search(self, *_: object, **__: object) -> tuple[np.ndarray, np.ndarray]:
        distances = np.asarray([[0.9, 0.8]], dtype=np.float32)
        ids = np.asarray([[101, 102]], dtype=np.int64)
        return distances, ids


class _FakeCatalog:
    def __init__(self) -> None:
        self.records = [
            {
                "id": 101,
                "uri": "src/file_a.py",
                "start_line": 1,
                "end_line": 5,
                "preview": "code A",
            },
            {
                "id": 102,
                "uri": "src/file_b.py",
                "start_line": 10,
                "end_line": 20,
                "preview": "code B",
            },
        ]

    def query_by_ids(self, ids: list[int]) -> list[dict]:
        return [record for record in self.records if record["id"] in ids]

    def query_by_filters(self, ids: list[int], **_: object) -> list[dict]:
        return self.query_by_ids(ids)


class _FakeContext:
    def __init__(self, tmp_path: Path) -> None:
        coderank_index = tmp_path / "coderank.faiss"
        coderank_index.write_bytes(b"index")
        self.paths = SimpleNamespace(
            coderank_faiss_index=coderank_index,
            warp_index_dir=tmp_path / "warp",
        )
        self._catalog = _FakeCatalog()
        self.settings = SimpleNamespace(
            coderank=SimpleNamespace(
                model_id="stub",
                device="cpu",
                trust_remote_code=True,
                query_prefix="prefix: ",
                normalize=True,
                batch_size=8,
            ),
            limits=SimpleNamespace(max_results=10, semantic_overfetch_multiplier=2),
            index=SimpleNamespace(rrf_k=60, faiss_nprobe=16),
            warp=SimpleNamespace(enabled=False, device="cpu", top_k=50),
            coderank_llm=SimpleNamespace(
                enabled=False,
                model_id="stub",
                device="cpu",
                max_new_tokens=16,
                temperature=0.0,
                top_p=1.0,
            ),
        )

    def get_coderank_faiss_manager(self, vec_dim: int) -> _FakeFaissManager:
        assert vec_dim == 2
        return _FakeFaissManager()

    def open_catalog(self) -> AbstractContextManager[_FakeCatalog]:
        @contextmanager
        def _catalog_cm() -> Iterator[_FakeCatalog]:
            yield self._catalog

        return _catalog_cm()


@pytest.fixture(autouse=True)
def _stub_observer(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def _observer(*_: object, **__: object) -> Iterator[object]:
        class _Obs:
            def mark_error(self) -> None:
                self.errored = True

            def mark_success(self) -> None:
                self.succeeded = True

        obs = _Obs()
        yield obs

    async def _fake_scope(*_: object, **__: object) -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr(semantic_pro, "observe_duration", _observer)
    monkeypatch.setattr(semantic_pro, "CodeRankEmbedder", _FakeEmbedder)
    monkeypatch.setattr(semantic_pro, "get_session_id", lambda: "test-session")
    monkeypatch.setattr(semantic_pro, "get_effective_scope", _fake_scope)


def test_semantic_pro_produces_findings(tmp_path: Path) -> None:
    context = cast("ApplicationContext", _FakeContext(tmp_path))
    envelope = asyncio.run(
        semantic_pro.semantic_search_pro(
            context=context,
            query="how to open file",
            limit=2,
            options={
                "use_warp": False,
                "use_reranker": False,
                "stage_weights": {},
                "explain": True,
            },
        )
    )

    assert "findings" in envelope
    findings = envelope["findings"]
    assert findings, "expected at least one finding"
    first = findings[0]
    assert first.get("chunk_id") == 101
    assert "why" in first
    assert "method" in envelope
    method = envelope["method"]
    assert method.get("retrieval") == ["coderank"]


def test_semantic_pro_requires_coderank_enabled(tmp_path: Path) -> None:
    context = cast("ApplicationContext", _FakeContext(tmp_path))
    with pytest.raises(VectorSearchError):
        asyncio.run(
            semantic_pro.semantic_search_pro(
                context=context,
                query="noop",
                limit=1,
                options={"use_coderank": False},
            )
        )
