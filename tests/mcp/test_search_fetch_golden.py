"""Tests for MCP search and fetch golden paths: structured results and content hydration."""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import numpy as np
from codeintel_rev.io.duckdb_catalog import StructureAnnotations
from codeintel_rev.io.faiss_manager import SearchRuntimeOverrides
from codeintel_rev.retrieval.mcp_search import (
    FetchDependencies,
    FetchRequest,
    FetchResponse,
    SearchDependencies,
    SearchFilters,
    SearchRequest,
    SearchResponse,
    VectorRuntime,
    run_fetch,
    run_search,
)
from codeintel_rev.typing import NDArrayF32, NDArrayI64

from tests._helpers import assertions


class _StubEmbedder:
    def __init__(self, dim: int) -> None:
        self._dim = dim

    def embed_single(self, text: str) -> list[float]:
        return [float(len(text))] * self._dim


class _StubFaissRuntime(VectorRuntime):
    def get_runtime_tuning(self) -> Mapping[str, object]:
        """Stub get_runtime_tuning method.

        Returns
        -------
        Mapping[str, object]
            Empty runtime tuning dict.
        """
        return {"active": {}}


class _StubFaiss:
    vec_dim = 4
    faiss_family: str | None = "ivf_pq"
    refine_k_factor = 1.0

    def __init__(self) -> None:
        self._runtime = _StubFaissRuntime()

    @property
    def runtime(self) -> VectorRuntime:
        return self._runtime

    @staticmethod
    def search(
        query: NDArrayF32,
        k: int | None = None,
        *,
        nprobe: int | None = None,
        runtime: SearchRuntimeOverrides | None = None,
        catalog: object | None = None,
    ) -> tuple[NDArrayF32, NDArrayI64]:
        """Stub search method.

        Parameters
        ----------
        query : NDArrayF32
            Query vector.
        k : int | None, optional
            Number of results, by default None.
        nprobe : int | None, optional
            Number of probes, by default None.
        runtime : SearchRuntimeOverrides | None, optional
            Runtime overrides, by default None.
        catalog : object | None, optional
            Catalog object, by default None.

        Returns
        -------
        tuple[NDArrayF32, NDArrayI64]
            Distances and identifiers.
        """
        _ = (query, k, nprobe, runtime, catalog)
        distances: NDArrayF32 = np.array([[0.91, 0.88]], dtype=np.float32)
        identifiers: NDArrayI64 = np.array([[1, 2]], dtype=np.int64)
        return distances, identifiers


class _StubCatalog:
    def __init__(self) -> None:
        self._rows: list[dict[str, object]] = [
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

    def query_by_ids(self, ids: Sequence[int]) -> list[dict[str, object]]:
        wanted = set(ids)
        return [row for row in self._rows if row["id"] in wanted]

    def query_by_filters(
        self,
        ids: Sequence[int],
        *,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        languages: list[str] | None = None,
    ) -> list[dict[str, object]]:
        _ = (include_globs, exclude_globs, languages)
        return self.query_by_ids(ids)

    def get_structure_annotations(self, ids: Sequence[int]) -> dict[int, StructureAnnotations]:
        row_map: dict[int, dict[str, object]] = {}
        for row in self._rows:
            row_id = row.get("id")
            if isinstance(row_id, int):
                row_map[row_id] = row
        annotations: dict[int, StructureAnnotations] = {}
        for chunk_id in ids:
            row = row_map.get(int(chunk_id))
            uri = str(row.get("uri", "")) if row else ""
            annotations[int(chunk_id)] = StructureAnnotations(
                uri=uri,
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
    """Test that run_search returns structured results with metadata and explainability."""
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
    )
    request = SearchRequest(
        query="foo",
        top_k=1,
        rerank=False,
        filters=SearchFilters(symbols=("foo",)),
    )
    response: SearchResponse = run_search(request=request, deps=deps)
    assertions.expect_equal(response.top_k, 1)
    metadata: dict[str, object] = response.results[0].metadata
    assertions.expect_equal(cast("str", metadata["uri"]), "codeintel_rev/a.py")
    symbols = cast("list[str]", metadata["symbols"])
    assertions.expect_sequence_equal(symbols, ["foo"])
    explain = cast("dict[str, object]", metadata["explain"])
    hit_reason = cast("list[str]", explain["hit_reason"])
    assertions.expect_equal(hit_reason[0], "embedding:cosine")
    if importlib.util.find_spec("pyarrow") is not None:
        pool_files = list(tmp_path.glob("*.parquet"))
        assertions.expect_true(bool(pool_files), reason="pool writer should emit a parquet file")


def test_run_fetch_hydrates_content() -> None:
    """Test that run_fetch hydrates content from catalog for requested object IDs."""
    catalog = _StubCatalog()
    deps = FetchDependencies(
        catalog=catalog,
        settings=_StubSettings(),
    )
    request = FetchRequest(object_ids=(1,), max_tokens=512)
    response: FetchResponse = run_fetch(request=request, deps=deps)
    metadata: dict[str, object] = response.objects[0].metadata
    assertions.expect_equal(cast("str", metadata["uri"]), "codeintel_rev/a.py")
    assertions.expect_in("def foo", response.objects[0].content)
