from __future__ import annotations

from codeintel_rev.io.duckdb_catalog import StructureAnnotations
from codeintel_rev.retrieval.mcp_search import (
    HydrationPayload,
    SearchResult,
    post_search_validate_and_fill,
)

from tests._helpers import assertions


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

    assertions.expect_equal(stats.repaired, 1)
    assertions.expect_equal(stats.dropped, 0)
    assertions.expect_true(
        fixed[0].title.endswith("lines 1-1"), reason="title should end with lines 1-1"
    )
    assertions.expect_true(
        fixed[0].url.startswith("repo://pkg/module.py"),
        reason="url should start with repo://pkg/module.py",
    )
    assertions.expect_in("def add", fixed[0].snippet)
    assertions.expect_equal(fixed[0].metadata["lang"], "python")


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

    assertions.expect_equal(fixed, [])
    assertions.expect_equal(stats.dropped, 1)
    assertions.expect_equal(stats.inspected, 1)
