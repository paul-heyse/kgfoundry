from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from codeintel_rev.retrieval.mcp_search import (
    FetchDependencies,
    FetchRequest,
    FetchResponse,
    SearchDependencies,
    SearchFilters,
    SearchRequest,
    SearchResponse,
    run_fetch,
    run_search,
)


class _StubEmbedder:
    def __init__(self, dim: int) -> None:
        self._dim = dim

    def embed_single(self, text: str) -> list[float]:
        return [float(len(text))] * self._dim


class _StubFaiss:
    vec_dim = 4
    faiss_family = "ivf_pq"
    refine_k_factor = 1.0

    def get_runtime_tuning(self) -> dict[str, object]:
        return {"active": {}}

    def search(
        self,
        _query: np.ndarray,
        _k: int | None = None,
        *,
        _nprobe: int | None = None,
        _runtime: object | None = None,
        _catalog: object | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        distances = np.array([[0.91, 0.88]], dtype=np.float32)
        identifiers = np.array([[1, 2]], dtype=np.int64)
        return distances, identifiers


class _StubCatalog:
    def __init__(self) -> None:
        self._rows = [
            {
                "id": 1,
                "uri": "codeintel_rev/a.py",
                "start_line": 0,
                "end_line": 4,
                "start_byte": 0,
                "end_byte": 120,
                "lang": "python",
                "preview": "def foo():\n    return 1",
                "content": "def foo():\n    return 1",
                "symbols": ["foo"],
            },
            {
                "id": 2,
                "uri": "codeintel_rev/b.py",
                "start_line": 10,
                "end_line": 14,
                "start_byte": 200,
                "end_byte": 320,
                "lang": "python",
                "preview": "def bar():\n    return 2",
                "content": "def bar():\n    return 2",
                "symbols": ["bar"],
            },
        ]

    def query_by_ids(self, ids: Sequence[int]) -> list[dict]:
        wanted = set(ids)
        return [row for row in self._rows if row["id"] in wanted]

    def query_by_filters(
        self,
        ids: Sequence[int],
        *,
        _include_globs: list[str] | None = None,
        _exclude_globs: list[str] | None = None,
        _languages: list[str] | None = None,
    ) -> list[dict]:
        return self.query_by_ids(ids)

    def get_structure_annotations(self, ids: Sequence[int]) -> dict[int, object]:
        annotations: dict[int, object] = {}
        for chunk_id in ids:
            annotations[int(chunk_id)] = SimpleNamespace(
                symbol_hits=(f"symbol:{chunk_id}",),
                ast_node_kinds=("FunctionDef",),
                cst_matches=(),
            )
        return annotations


class _StubIndexConfig:
    vec_dim = 4
    faiss_nprobe = 1


class _StubLimits:
    max_results = 50
    semantic_overfetch_multiplier = 2


class _StubSettings:
    index = _StubIndexConfig()
    limits = _StubLimits()


def test_run_search_returns_structured_results(tmp_path: Path) -> None:
    catalog = _StubCatalog()
    deps = SearchDependencies(
        faiss=_StubFaiss(),
        embedder=_StubEmbedder(dim=4),
        catalog=catalog,
        settings=_StubSettings(),
        session_id="sess",
        run_id="run",
        limits=[],
        pool_dir=tmp_path,
        timeline=None,
    )
    request = SearchRequest(
        query="foo",
        top_k=1,
        rerank=False,
        filters=SearchFilters(symbols=("foo",)),
    )
    response: SearchResponse = run_search(request=request, deps=deps)
    assert response.top_k == 1
    assert response.results[0].metadata["uri"] == "codeintel_rev/a.py"
    assert response.results[0].metadata["symbols"] == ["foo"]
    assert response.results[0].metadata["explain"]["hit_reason"][0] == "embedding:cosine"
    if importlib.util.find_spec("pyarrow") is not None:
        pool_files = list(tmp_path.glob("*.parquet"))
        assert pool_files, "pool writer should emit a parquet file"


def test_run_fetch_hydrates_content() -> None:
    catalog = _StubCatalog()
    deps = FetchDependencies(
        catalog=catalog,
        settings=_StubSettings(),
        timeline=None,
    )
    request = FetchRequest(object_ids=(1,), max_tokens=512)
    response: FetchResponse = run_fetch(request=request, deps=deps)
    assert response.objects[0].metadata["uri"] == "codeintel_rev/a.py"
    assert "def foo" in response.objects[0].content
