from __future__ import annotations

from codeintel_rev.io.duckdb_catalog import StructureAnnotations
from codeintel_rev.retrieval.mcp_search import (
    HydrationPayload,
    SearchResult,
    post_search_validate_and_fill,
)


def _row() -> dict[str, object]:
    return {
        "uri": "pkg/module.py",
        "start_line": 0,
        "end_line": 0,
        "start_byte": 0,
        "end_byte": 12,
        "lang": "python",
        "content": "def add(a, b):\n    return a + b\n",
        "preview": "def add(a, b):\n    return a + b\n",
    }


def test_post_search_validate_and_fill_repairs_missing_fields() -> None:
    result = SearchResult(
        chunk_id=42,
        title="",
        url="",
        snippet="",
        score=0.91,
        source="faiss",
        metadata={"lang": ""},
    )
    annotations: dict[int, StructureAnnotations] = {}
    hydration = HydrationPayload(rows={42: _row()}, annotations=annotations)

    fixed, stats = post_search_validate_and_fill([result], hydration=hydration)

    assert stats.repaired == 1
    assert stats.dropped == 0
    assert fixed[0].title.endswith("lines 1-1")
    assert fixed[0].url.startswith("repo://pkg/module.py")
    assert "def add" in fixed[0].snippet
    assert fixed[0].metadata["lang"] == "python"


def test_post_search_validate_and_fill_drops_missing_rows() -> None:
    result = SearchResult(
        chunk_id=100,
        title="orphan",
        url="repo://missing.py",
        snippet="",
        score=0.1,
        source="faiss",
        metadata={},
    )
    annotations: dict[int, StructureAnnotations] = {}
    hydration = HydrationPayload(rows={}, annotations=annotations)

    fixed, stats = post_search_validate_and_fill([result], hydration=hydration)

    assert fixed == []
    assert stats.dropped == 1
    assert stats.inspected == 1
