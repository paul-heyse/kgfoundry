"""Tests for semantic_pro adapter behaviors."""

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
from codeintel_rev.io.duckdb_catalog import StructureAnnotations
from codeintel_rev.mcp_server.adapters import semantic_pro
from codeintel_rev.retrieval.types import HybridResultDoc, HybridSearchResult

from kgfoundry_common.errors import VectorSearchError
from tests._helpers import assertions, constants

EXPECTED_CHUNK_ID = 101


class _FakeVLLMClient:
    def __init__(self) -> None:
        self.embed_calls = 0

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        self.embed_calls += 1
        assertions.expect_true(texts, reason="semantic search must embed at least one text.")
        return np.asarray([[0.1, 0.2]], dtype=np.float32)


class _FakeFaissManager:
    def __init__(self) -> None:
        self.search_calls = 0

    def search(self, *_: object, **__: object) -> tuple[np.ndarray, np.ndarray]:
        self.search_calls += 1
        distances = np.asarray([[0.9, 0.8]], dtype=np.float32)
        ids = np.asarray([[EXPECTED_CHUNK_ID, EXPECTED_CHUNK_ID + 1]], dtype=np.int64)
        return distances, ids


class _FakeCatalog:
    def __init__(self) -> None:
        self.records = [
            {
                "id": EXPECTED_CHUNK_ID,
                "uri": "src/file_a.py",
                "start_line": 1,
                "end_line": 5,
                "preview": "code A",
            },
            {
                "id": EXPECTED_CHUNK_ID + 1,
                "uri": "src/file_b.py",
                "start_line": 10,
                "end_line": 20,
                "preview": "code B",
            },
        ]
        self.annotation_requests = 0

    def query_by_ids(self, ids: list[int]) -> list[dict]:
        return [record for record in self.records if record["id"] in ids]

    def query_by_filters(self, ids: list[int], **_: object) -> list[dict]:
        return self.query_by_ids(ids)

    def get_structure_annotations(self, ids: list[int]) -> dict[int, StructureAnnotations]:
        self.annotation_requests += 1
        annotations: dict[int, StructureAnnotations] = {}
        for chunk_id in ids:
            annotations[int(chunk_id)] = StructureAnnotations(
                uri="src/file.py",
                symbol_hits=("fake.symbol",),
                ast_node_kinds=("FunctionDef",),
                cst_matches=(),
            )
        return annotations


class _FakeHybridEngine:
    def __init__(self) -> None:
        self.search_calls = 0
        self.last_options: semantic_pro.HybridOptions | None = None

    def search(
        self,
        query: str,
        *,
        semantic_hits: list[tuple[int, float]],
        limit: int,
        options: semantic_pro.HybridOptions | None = None,
    ) -> HybridSearchResult:
        self.search_calls += 1
        self.last_options = options
        assertions.expect_true(query)
        extra_channels = options.extra_channels if options else None
        docs = [
            HybridResultDoc(doc_id=str(cid), score=float(score)) for cid, score in semantic_hits
        ]
        contributions = {
            str(cid): [("semantic", idx + 1, float(score))]
            for idx, (cid, score) in enumerate(semantic_hits)
        }
        channels = ["semantic"]
        if extra_channels and extra_channels.get("warp"):
            warp_hit = extra_channels["warp"][0]
            docs.insert(0, HybridResultDoc(doc_id=warp_hit.doc_id, score=float(warp_hit.score)))
            contributions.setdefault(warp_hit.doc_id, []).append(("warp", 1, float(warp_hit.score)))
            channels.append("warp")
        return HybridSearchResult(
            docs=docs[:limit],
            contributions=contributions,
            channels=channels,
            warnings=[],
            method={"retrieval": channels, "coverage": f"{len(docs[:limit])}/{limit} results"},
        )


class _StubXTRIndex:
    ready = True

    def __init__(self) -> None:
        self.calls = 0

    def rescore(
        self,
        query: str,
        candidate_chunk_ids: list[int],
        *,
        explain: bool = False,
        topk_explanations: int = 5,
    ) -> list[tuple[int, float, None]]:
        self.calls += 1
        assertions.expect_true(query)
        _ = explain
        _ = topk_explanations
        reordered = list(reversed(candidate_chunk_ids))
        total = len(reordered)
        return [(cid, float(total - idx), None) for idx, cid in enumerate(reordered)]


class _FakeContext:
    def __init__(self, tmp_path: Path, *, xtr_ready: bool = False) -> None:
        coderank_index = tmp_path / "coderank.faiss"
        coderank_index.write_bytes(b"index")
        (tmp_path / "xtr").mkdir(exist_ok=True)
        self.vllm_client = _FakeVLLMClient()
        self.paths = SimpleNamespace(
            coderank_faiss_index=coderank_index,
            warp_index_dir=tmp_path / "warp",
            xtr_dir=tmp_path / "xtr",
        )
        self._catalog = _FakeCatalog()
        self._hybrid = _FakeHybridEngine()
        self.faiss_requests = 0
        self.settings = SimpleNamespace(
            coderank=SimpleNamespace(
                model_id="stub",
                device="cpu",
                trust_remote_code=True,
                query_prefix="prefix: ",
                normalize=True,
                batch_size=8,
                top_k=10,
                budget_ms=1000,
                min_stage2_margin=0.05,
                min_stage2_candidates=1,
            ),
            limits=SimpleNamespace(max_results=10, semantic_overfetch_multiplier=2),
            index=SimpleNamespace(
                rrf_k=60, faiss_nprobe=16, rrf_weights={"semantic": 1.0, "warp": 1.0}
            ),
            warp=SimpleNamespace(enabled=False, device="cpu", top_k=50),
            xtr=SimpleNamespace(
                enable=xtr_ready,
                candidate_k=50,
                dtype="float16",
                dim=2,
                max_query_tokens=32,
                device="cpu",
                model_id="stub",
                mode="narrow",
            ),
            rerank=SimpleNamespace(
                enabled=False,
                top_k=50,
                provider="xtr",
                explain=False,
            ),
            coderank_llm=SimpleNamespace(
                enabled=False,
                model_id="stub",
                device="cpu",
                max_new_tokens=16,
                temperature=0.0,
                top_p=1.0,
                budget_ms=500,
            ),
            vllm=SimpleNamespace(model="stub", run=SimpleNamespace(mode="inprocess")),
        )
        self._xtr_index = _StubXTRIndex() if xtr_ready else None

    def get_coderank_faiss_manager(self, vec_dim: int) -> _FakeFaissManager:
        assertions.expect_equal(vec_dim, constants.VECTOR_DIMS.pair)
        self.faiss_requests += 1
        return _FakeFaissManager()

    def open_catalog(self) -> AbstractContextManager[_FakeCatalog]:
        @contextmanager
        def _catalog_cm() -> Iterator[_FakeCatalog]:
            yield self._catalog

        return _catalog_cm()

    def get_hybrid_engine(self) -> _FakeHybridEngine:
        return self._hybrid

    def get_xtr_index(self) -> _StubXTRIndex | None:
        return self._xtr_index


@pytest.fixture(autouse=True)
def _stub_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scope(*_: object, **__: object) -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr(semantic_pro, "get_session_id", lambda: "test-session")
    monkeypatch.setattr(semantic_pro, "get_effective_scope", _fake_scope)


def test_semantic_pro_produces_findings(tmp_path: Path) -> None:
    """Semantic pro returns findings with explainability metadata."""
    context = cast("ApplicationContext", _FakeContext(tmp_path))
    envelope = asyncio.run(
        semantic_pro.semantic_search_pro(
            context=context,
            query="how to open file",
            limit=constants.BATCH_SIZES.minimal,
            options={
                "use_warp": False,
                "use_reranker": False,
                "stage_weights": {},
                "explain": True,
            },
        )
    )

    assertions.expect_in("findings", envelope)
    findings = cast("list[dict[str, object]]", envelope["findings"])
    assertions.expect_true(findings)
    explanations = cast("dict[str, object]", findings[0].get("explanations"))
    assertions.expect_sequence_equal(explanations["matched_symbols"], ["fake.symbol"])


def test_semantic_pro_rerank_skips_without_capability(tmp_path: Path) -> None:
    """Reranker metadata indicates capability is off."""
    context = cast("ApplicationContext", _FakeContext(tmp_path))
    envelope = asyncio.run(
        semantic_pro.semantic_search_pro(
            context=context,
            query="gateway",
            limit=constants.BATCH_SIZES.minimal,
            options={"rerank": {"enabled": True}},
        )
    )
    method = envelope.get("method")
    assertions.expect_true(method is not None)
    rerank = method.get("rerank") if method else None
    assertions.expect_true(rerank is not None)
    rerank_meta = cast("dict[str, object]", rerank)
    assertions.expect_false(rerank_meta["enabled"])
    assertions.expect_equal(rerank_meta["reason"], "capability_off")


def test_semantic_pro_rerank_reorders_when_ready(tmp_path: Path) -> None:
    """XTR-enabled reranker reorders findings."""
    context = cast("ApplicationContext", _FakeContext(tmp_path, xtr_ready=True))
    envelope = asyncio.run(
        semantic_pro.semantic_search_pro(
            context=context,
            query="gateway",
            limit=constants.BATCH_SIZES.minimal,
            options={
                "rerank": {"enabled": True, "top_k": constants.BATCH_SIZES.minimal},
            },
        )
    )
    method = envelope.get("method")
    assertions.expect_true(method is not None)
    rerank_meta = method.get("rerank") if method else None
    assertions.expect_true(rerank_meta is not None)
    rerank_meta_dict = cast("dict[str, object]", rerank_meta)
    assertions.expect_true(bool(rerank_meta_dict["enabled"]))
    reordered = rerank_meta_dict.get("reordered")
    assertions.expect_true(isinstance(reordered, int) and reordered >= 1)
    findings_payload = envelope.get("findings")
    assertions.expect_true(findings_payload, reason="expected at least one finding")
    first_finding = findings_payload[0]
    assertions.expect_equal(first_finding.get("chunk_id"), EXPECTED_CHUNK_ID)
    assertions.expect_in("why", first_finding)
    method_details = envelope.get("method")
    assertions.expect_true(method_details is not None)
    if method_details:
        assertions.expect_sequence_equal(method_details.get("retrieval"), ["semantic"])
        assertions.expect_true(method_details.get("stages"))


def test_semantic_pro_requires_coderank_enabled(tmp_path: Path) -> None:
    """Disabling coderank raises VectorSearchError."""
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


def test_merge_explainability_into_findings() -> None:
    """Explainability data merges into the finding payload."""
    finding: semantic_pro.Finding = {
        "chunk_id": 1,
        "type": "usage",
        "title": "main.py",
        "location": {
            "uri": "file://main.py",
            "start_line": 1,
            "start_column": 0,
            "end_line": 1,
            "end_column": 0,
        },
        "snippet": "",
        "score": 0.5,
        "why": "",
    }
    explainability = [(1, {"token_matches": [{"q_index": 0, "doc_index": 2, "similarity": 0.9}]})]
    semantic_pro.merge_explainability_into_findings([finding], explainability)
    assertions.expect_in("XTR alignments", finding["why"])
