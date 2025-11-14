"""Lightweight search helpers used by the in-process MCP harness."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from codeintel_rev.mcp_server.types import SearchInput, SearchOutput, SearchResultItem


class CatalogProtocol(Protocol):
    """Protocol describing the catalog surface used by the lightweight MCP tools."""

    def query_by_ids(self, ids: Sequence[int]) -> list[dict[str, object]]:
        """Return hydrated chunk rows for the provided identifiers."""
        raise NotImplementedError


@dataclass(slots=True, frozen=True)
class SearchDeps:
    """Dependencies required to execute the light search helper."""

    catalog: CatalogProtocol
    faiss_search: Callable[[str, int], list[tuple[int, float]]] | None = None
    sparse_search: Callable[[str, int], list[tuple[int, float]]] | None = None


def handle_search(deps: SearchDeps, args: dict[str, object]) -> SearchOutput:
    """Execute a lightweight search suitable for MCP tests or tooling.

    This function performs a hybrid search combining dense (FAISS) and sparse
    (BM25/SPLADE) retrieval channels, then hydrates results with chunk metadata
    from the catalog. It is called by MCP tool handlers to provide search
    functionality for testing and lightweight tooling scenarios.

    Parameters
    ----------
    deps : SearchDeps
        Search dependencies including catalog, FAISS search function, and sparse
        search function. Functions may be None if corresponding channels are disabled.
    args : dict[str, object]
        Dictionary containing SearchInput fields, typically with "query" and
        "top_k" keys.

    Returns
    -------
    SearchOutput
        msgspec-structured payload describing top-k results with metadata,
        query echo, and limits information.
    """
    payload = _normalize_search_input(args)
    top_k = max(1, min(50, payload.top_k))
    query = payload.query.strip()
    if not query:
        return SearchOutput(results=[], queryEcho="", top_k=top_k, limits=[])

    dense = deps.faiss_search(query, top_k) if deps.faiss_search else []
    sparse = deps.sparse_search(query, top_k) if deps.sparse_search else []
    merged = _merge_candidates(dense, sparse, top_k)
    chunk_ids = [cid for cid, _, _ in merged]
    rows = deps.catalog.query_by_ids(chunk_ids) if chunk_ids else []
    rows_by_id: dict[int, dict[str, object]] = {}
    for row in rows:
        row_id = row.get("id")
        if isinstance(row_id, int):
            rows_by_id[row_id] = row
    results: list[SearchResultItem] = []
    limits: list[str] = []
    for chunk_id, score, channel in merged:
        row = rows_by_id.get(chunk_id)
        if row is None:
            continue
        snippet = _build_snippet(row)
        results.append(
            SearchResultItem(
                id=str(chunk_id),
                title=str(row.get("uri") or f"chunk:{chunk_id}"),
                url=_build_url(row),
                snippet=snippet,
                score=float(score),
                source=channel,
                metadata={
                    "lang": row.get("lang"),
                    "channel": channel,
                },
            )
        )
        if len(results) >= top_k:
            break
    if payload.filters:
        limits.append("filters_applied")
    return SearchOutput(
        results=results,
        queryEcho=query,
        top_k=top_k,
        limits=limits or None,
    )


def _merge_candidates(
    dense: list[tuple[int, float]] | None,
    sparse: list[tuple[int, float]] | None,
    k: int,
) -> list[tuple[int, float, str]]:
    dense = dense or []
    sparse = sparse or []
    merged: list[tuple[int, float, str]] = []
    i = j = 0
    while len(merged) < max(k * 2, k) and (i < len(dense) or j < len(sparse)):
        if i < len(dense):
            merged.append((int(dense[i][0]), float(dense[i][1]), "vector"))
            i += 1
        if len(merged) >= max(k * 2, k):
            break
        if j < len(sparse):
            merged.append((int(sparse[j][0]), float(sparse[j][1]), "sparse"))
            j += 1
    best: dict[int, tuple[float, str]] = {}
    for cid, score, channel in merged:
        existing = best.get(cid)
        if existing is None or score > existing[0]:
            best[cid] = (score, channel)
    ranked = sorted(
        ((cid, score, channel) for cid, (score, channel) in best.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked[:k]


def _build_url(row: Mapping[str, object]) -> str:
    """Build a repo:// URL from chunk metadata row.

    Parameters
    ----------
    row : Mapping[str, object]
        Chunk metadata dictionary containing uri, start_line, and end_line.

    Returns
    -------
    str
        URL in format "repo://{uri}#L{start}-L{end}" with 1-based line numbers.
    """
    start = _coerce_int(row.get("start_line"), default=0) + 1
    end = _coerce_int(row.get("end_line"), default=start) + 1
    uri = str(row.get("uri") or "")
    return f"repo://{uri}#L{start}-L{end}"


def _build_snippet(row: Mapping[str, object]) -> str:
    """Build a text snippet from chunk metadata row.

    Parameters
    ----------
    row : Mapping[str, object]
        Chunk metadata dictionary containing preview or content.

    Returns
    -------
    str
        Text snippet up to 400 characters, preferring preview over content.
    """
    preview = row.get("preview")
    if preview:
        return str(preview)[:400]
    content = str(row.get("content") or "")
    lines = content.splitlines()
    snippet = "\n".join(lines[:8])
    return snippet[:400]


def _normalize_search_input(args: Mapping[str, object]) -> SearchInput:
    """Normalize and validate search tool input arguments.

    Parameters
    ----------
    args : Mapping[str, object]
        Raw arguments dictionary containing query, top_k, and filters.

    Returns
    -------
    SearchInput
        Normalized and validated SearchInput object.

    Raises
    ------
    ValueError
        If query is missing.
    """
    query_raw = args.get("query")
    if query_raw is None:
        msg = "query is required"
        raise ValueError(msg)
    query = str(query_raw)
    top_k_raw = args.get("top_k", 12)
    top_k = max(1, min(50, _coerce_int(top_k_raw, default=12)))
    filters_raw = args.get("filters")
    filters = dict(filters_raw) if isinstance(filters_raw, Mapping) else None
    return SearchInput(query=query, top_k=top_k, filters=filters)


def _coerce_int(value: object, *, default: int = 0) -> int:
    """Coerce a value to an integer with fallback to default.

    This function attempts to convert various types (bool, int, float, str) to
    an integer, falling back to the default value if conversion fails or the
    value is None. Used by input normalization functions to safely coerce
    user-provided values.

    Parameters
    ----------
    value : object
        Value to coerce to integer.
    default : int
        Default value to return if coercion fails. Defaults to 0.

    Returns
    -------
    int
        Coerced integer value, or default if conversion fails.
    """
    if value is None:
        return default
    candidate = default
    if isinstance(value, bool):
        candidate = int(value)
    elif isinstance(value, int):
        candidate = value
    elif isinstance(value, float):
        candidate = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped:
            try:
                candidate = int(stripped, 10)
            except ValueError:
                candidate = default
    return candidate
