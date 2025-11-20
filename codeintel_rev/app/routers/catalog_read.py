# SPDX-License-Identifier: MIT
"""FastAPI routes exposing catalog read APIs (GOIDs, call graphs, CFG/DFG)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from codeintel_rev.app.config_context import CatalogContext
from codeintel_rev.io.duckdb_catalog import (
    CallGraphQuery,
    CFGBlockDict,
    CFGEdgeDict,
    DFGEdgeDict,
    DFGNodeDict,
    GOIDQuery,
    SpanDict,
)

router = APIRouter(prefix="/v1", tags=["catalog-read"])


class Problem(BaseModel):
    """Problem Details response envelope."""

    type: str | None = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


class Span(BaseModel):
    """Represents a file span."""

    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None


class GOIDRow(BaseModel):
    """GOID cross-walk row."""

    goid: str
    lang: str
    module_path: str | None = None
    file_path: str | None = None
    span: Span | None = None
    scip_symbol: str | None = None
    ast_qualname: str | None = None
    cst_node_id: str | None = None
    chunk_id: int | None = None
    symbol_id: str | None = None
    updated_at: str | None = None


class GOIDListResponse(BaseModel):
    """Paginated GOID list."""

    data: list[GOIDRow]
    meta: dict[str, Any] = Field(default_factory=dict)
    links: dict[str, Any] = Field(default_factory=dict)


class CallEdge(BaseModel):
    """Call graph edge representation."""

    caller: str
    callee: str
    callsite: Span | None = None
    resolved: bool = True
    kind: str = "direct"
    confidence: float | None = None
    updated_at: str | None = None


class CallGraphResponse(BaseModel):
    """Call graph response payload."""

    nodes: list[dict[str, Any]]
    edges: list[CallEdge]
    truncated: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)


class BasicBlock(BaseModel):
    """CFG block node."""

    id: str
    label: str
    span: Span | None = None


class CFGEdge(BaseModel):
    """CFG edge."""

    src: str
    dst: str
    label: str | None = None


class CFGResponse(BaseModel):
    """CFG response."""

    function_goid: str
    blocks: list[BasicBlock]
    edges: list[CFGEdge]


class DFGNode(BaseModel):
    """DFG node representation."""

    id: str
    kind: str
    symbol: str | None = None
    span: Span | None = None


class DFGEdge(BaseModel):
    """DFG edge."""

    src: str
    dst: str
    label: str | None = None


class DFGResponse(BaseModel):
    """DFG response payload."""

    function_goid: str
    nodes: list[DFGNode]
    edges: list[DFGEdge]


def _context_dependency(request: Request) -> CatalogContext:
    """Return ApplicationContext stored on the FastAPI app.

    Parameters
    ----------
    request : Request
        FastAPI request object containing app state.

    Returns
    -------
    ApplicationContext
        Application context instance from app state.

    Raises
    ------
    HTTPException
        If context is not available (503 status code).
    """
    context = getattr(request.app.state, "context", None)
    if context is None:
        raise HTTPException(status_code=503, detail="context-unavailable")
    return context


ContextDep = Annotated[CatalogContext, Depends(_context_dependency)]


def _offset_from_cursor(cursor: str | None) -> int:
    """Return non-negative offset parsed from ``cursor``.

    Returns
    -------
    int
        Non-negative integer offset (0 when cursor missing/invalid).
    """
    if not cursor:
        return 0
    try:
        value = int(cursor)
    except (TypeError, ValueError):
        return 0
    return max(value, 0)


def _goid_symbol_filters(
    scip_symbol: Annotated[str | None, Query(description="Exact SCIP symbol string")] = None,
    ast_qualname: Annotated[str | None, Query(description="Fully-qualified AST name")] = None,
) -> tuple[str | None, str | None]:
    return scip_symbol, ast_qualname


def _goid_path_filters(
    path: Annotated[str | None, Query(description="Repo-relative path")] = None,
    start_line: Annotated[int | None, Query(description="Start line", ge=1)] = None,
    end_line: Annotated[int | None, Query(description="End line", ge=1)] = None,
) -> tuple[str | None, int | None, int | None]:
    return path, start_line, end_line


def _goid_chunk_filters(
    chunk_id: Annotated[int | None, Query(description="Chunk identifier")] = None,
    symbol_id: Annotated[str | None, Query(description="Internal symbol id")] = None,
) -> tuple[int | None, str | None]:
    return chunk_id, symbol_id


def _goid_page_filters(
    page_limit: Annotated[int, Query(alias="page[limit]", ge=1, le=1000)] = 200,
    page_cursor: Annotated[str | None, Query(alias="page[cursor]")] = None,
    sort: Annotated[str, Query(description="Sort order", pattern="^-?updated_at$")] = "-updated_at",
) -> tuple[int, str | None, str]:
    return page_limit, page_cursor, sort


def _build_goid_query(
    symbol_filters: Annotated[tuple[str | None, str | None], Depends(_goid_symbol_filters)],
    path_filters: Annotated[tuple[str | None, int | None, int | None], Depends(_goid_path_filters)],
    chunk_filters: Annotated[tuple[int | None, str | None], Depends(_goid_chunk_filters)],
    page_filters: Annotated[tuple[int, str | None, str], Depends(_goid_page_filters)],
) -> GOIDQuery:
    scip_symbol, ast_qualname = symbol_filters
    path, start_line, end_line = path_filters
    chunk_id, symbol_id = chunk_filters
    limit, cursor, sort = page_filters
    return GOIDQuery(
        scip_symbol=scip_symbol,
        ast_qualname=ast_qualname,
        path=path,
        start_line=start_line,
        end_line=end_line,
        chunk_id=chunk_id,
        symbol_id=symbol_id,
        limit=limit,
        cursor=cursor,
        sort=sort,
    )


GOIDQueryDep = Annotated[GOIDQuery, Depends(_build_goid_query)]


def _callgraph_root_params(
    root_goid: Annotated[str, Query(description="Root GOID to expand from")],
) -> str:
    return root_goid


def _callgraph_traversal_params(
    direction: Annotated[str, Query(description="Edge direction")] = "out",
    depth: Annotated[int, Query(description="Max depth", ge=0, le=10)] = 1,
    max_nodes: Annotated[int, Query(description="Max nodes", ge=1, le=100_000)] = 10_000,
) -> tuple[str, int, int]:
    return direction, depth, max_nodes


def _callgraph_filter_params(
    *,
    lang: Annotated[str | None, Query(description="Language filter")] = None,
    include_unresolved: Annotated[bool, Query(description="Include unresolved edges")] = False,
    include_third_party: Annotated[bool, Query(description="Include third-party files")] = False,
    path_prefix: Annotated[str | None, Query(description="Restrict to path prefix")] = None,
) -> tuple[str | None, bool, bool, str | None]:
    return lang, include_unresolved, include_third_party, path_prefix


def _callgraph_format_params(
    fmt: Annotated[str, Query(alias="format", description="Response format")] = "edge_list",
) -> str:
    return fmt


def _callgraph_page_params(
    page_limit: Annotated[int, Query(alias="page[limit]", ge=1, le=1000)] = 200,
    page_cursor: Annotated[str | None, Query(alias="page[cursor]")] = None,
) -> tuple[int, str | None]:
    return page_limit, page_cursor


def _build_callgraph_query(
    root: Annotated[str, Depends(_callgraph_root_params)],
    traversal: Annotated[tuple[str, int, int], Depends(_callgraph_traversal_params)],
    filters: Annotated[
        tuple[str | None, bool, bool, str | None], Depends(_callgraph_filter_params)
    ],
    fmt: Annotated[str, Depends(_callgraph_format_params)],
    paging: Annotated[tuple[int, str | None], Depends(_callgraph_page_params)],
) -> CallGraphQuery:
    direction, depth, max_nodes = traversal
    lang, include_unresolved, include_third_party, path_prefix = filters
    limit, cursor = paging
    return CallGraphQuery(
        root_goid=root,
        direction=direction,
        depth=depth,
        max_nodes=max_nodes,
        lang=lang,
        include_unresolved=include_unresolved,
        include_third_party=include_third_party,
        path_prefix=path_prefix,
        limit=limit,
        cursor=cursor,
        fmt=fmt,
    )


CallGraphQueryDep = Annotated[CallGraphQuery, Depends(_build_callgraph_query)]


@router.get("/catalog/goids", response_model=GOIDListResponse)
def list_or_resolve_goids(
    request: Request,
    query: GOIDQueryDep,
    ctx: ContextDep,
) -> GOIDListResponse:
    """Resolve GOIDs and enumerate cross-walk rows.

    Parameters
    ----------
    request : Request
        FastAPI request object for building pagination links.
    query : GOIDQueryDep
        Combined GOID cross-walk filters and pagination parameters.
    ctx : ContextDep
        Application context dependency.

    Returns
    -------
    GOIDListResponse
        Paginated response containing matching GOID rows.

    Raises
    ------
    HTTPException
        If query parameters are invalid (400 status code).
    """
    try:
        with ctx.open_catalog() as catalog:
            goid_result = catalog.query_goids(query)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows = goid_result["rows"]
    next_cursor = goid_result["next_cursor"]
    links: dict[str, str] = {"self": str(request.url)}
    page_meta: dict[str, object] = {"limit": query.limit}
    meta: dict[str, object] = {"page": page_meta}
    if next_cursor:
        page_meta["next_cursor"] = next_cursor
        links["next"] = str(request.url.include_query_params(**{"page[cursor]": next_cursor}))
        prev_cursor = max(0, _offset_from_cursor(next_cursor) - query.limit)
        links["prev"] = str(request.url.include_query_params(**{"page[cursor]": str(prev_cursor)}))
    goid_models = [
        GOIDRow(
            goid=row["goid"],
            lang=row["lang"],
            module_path=row.get("module_path"),
            file_path=row.get("file_path"),
            span=_to_span_model(row.get("span")),
            scip_symbol=row.get("scip_symbol"),
            ast_qualname=row.get("ast_qualname"),
            cst_node_id=row.get("cst_node_id"),
            chunk_id=row.get("chunk_id"),
            symbol_id=row.get("symbol_id"),
            updated_at=row.get("updated_at"),
        )
        for row in rows
    ]
    return GOIDListResponse(data=goid_models, meta=meta, links=links)


@router.get("/graph/call", response_model=CallGraphResponse)
def query_call_graph(
    request: Request,
    query: CallGraphQueryDep,
    ctx: ContextDep,
) -> Response | CallGraphResponse:
    """Return call graph edges around a root GOID.

    Parameters
    ----------
    request : Request
        FastAPI request object for checking Accept header.
    query : CallGraphQueryDep
        Call graph traversal filters, pagination, and format hints.
    ctx : ContextDep
        Application context dependency.

    Returns
    -------
    Response
        StreamingResponse with NDJSON if Accept header requests it,
        otherwise CallGraphResponse JSON.

    Raises
    ------
    HTTPException
        If query parameters are invalid (400 status code).
    """
    accepts_ndjson = "application/x-ndjson" in (request.headers.get("accept") or "")
    if accepts_ndjson:
        try:
            stream = _callgraph_ndjson_stream(ctx=ctx, query=query)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return StreamingResponse(stream, media_type="application/x-ndjson")

    try:
        with ctx.open_catalog() as catalog:
            graph = cast("dict[str, Any]", catalog.query_callgraph(query))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    next_cursor = graph.pop("next_cursor", None)
    if next_cursor:
        graph.setdefault("meta", {}).setdefault("page", {})["next_cursor"] = next_cursor
    return CallGraphResponse(**graph)


def _callgraph_ndjson_stream(
    *,
    ctx: CatalogContext,
    query: CallGraphQuery,
) -> Iterable[bytes]:
    def iterator() -> Iterable[bytes]:
        """Yield NDJSON-encoded call graph edges via paginated catalog queries.

        Yields
        ------
        bytes
            NDJSON-encoded edge objects, one per line.

        Notes
        -----
        Iterates through paginated call graph results, fetching subsequent
        pages using the next_cursor until all edges are yielded.
        """
        with ctx.open_catalog() as catalog:
            chunk = cast("dict[str, Any]", catalog.query_callgraph(query))
            next_cursor = chunk.get("next_cursor")
            current = chunk
            while True:
                edges = cast("list[dict[str, Any]]", current["edges"])
                for edge in edges:
                    yield json.dumps(edge).encode("utf-8") + b"\n"
                if not next_cursor:
                    break
                current = cast(
                    "dict[str, Any]",
                    catalog.query_callgraph(replace(query, cursor=next_cursor)),
                )
                next_cursor = current.get("next_cursor")

    return iterator()


@router.get("/flow/cfg/{function_goid:path}", response_model=CFGResponse)
def get_cfg(
    function_goid: str,
    ctx: ContextDep,
    fmt: str = Query("json", alias="format"),
) -> Response | CFGResponse:
    """Return CFG for a function GOID.

    Parameters
    ----------
    function_goid : str
        GOID of the function to retrieve CFG for.
    ctx : ContextDep
        Application context dependency.
    fmt : str, optional
        Response format ("json", "graphml", or "cytoscape"), by default "json".

    Returns
    -------
    Response | CFGResponse
        Response with GraphML XML if fmt is "graphml", otherwise CFGResponse JSON.

    Raises
    ------
    HTTPException
        If format is unsupported (400 status code) or CFG is not found (404 status code).
    """
    if fmt not in {"json", "graphml", "cytoscape"}:
        raise HTTPException(status_code=400, detail="unsupported-format")
    with ctx.open_catalog() as catalog:
        cfg = catalog.get_cfg(function_goid=function_goid)
    if not cfg:
        raise HTTPException(status_code=404, detail="CFG not found")
    cfg_blocks = cfg["blocks"]
    cfg_edges = cfg["edges"]
    if fmt == "graphml":
        content = _graphml_from_blocks_edges(cfg_blocks, cfg_edges, function_goid)
        return Response(content=content, media_type="application/xml")
    return CFGResponse(
        function_goid=function_goid,
        blocks=[
            BasicBlock(id=block["id"], label=block["label"], span=_to_span_model(block.get("span")))
            for block in cfg_blocks
        ],
        edges=[
            CFGEdge(src=edge["src"], dst=edge["dst"], label=edge.get("label"))
            for edge in cfg_edges
        ],
    )


@router.get("/flow/dfg/{function_goid:path}", response_model=DFGResponse)
def get_dfg(
    function_goid: str,
    ctx: ContextDep,
    fmt: str = Query("json", alias="format"),
) -> Response | DFGResponse:
    """Return DFG for a function GOID.

    Parameters
    ----------
    function_goid : str
        GOID of the function to retrieve DFG for.
    ctx : ContextDep
        Application context dependency.
    fmt : str, optional
        Response format ("json", "graphml", or "cytoscape"), by default "json".

    Returns
    -------
    Response | DFGResponse
        Response with GraphML XML if fmt is "graphml", otherwise DFGResponse JSON.

    Raises
    ------
    HTTPException
        If format is unsupported (400 status code) or DFG is not found (404 status code).
    """
    if fmt not in {"json", "graphml", "cytoscape"}:
        raise HTTPException(status_code=400, detail="unsupported-format")
    with ctx.open_catalog() as catalog:
        dfg = catalog.get_dfg(function_goid=function_goid)
    if not dfg:
        raise HTTPException(status_code=404, detail="DFG not found")
    dfg_nodes = dfg["nodes"]
    dfg_edges = dfg["edges"]
    if fmt == "graphml":
        content = _graphml_from_nodes_edges(dfg_nodes, dfg_edges, function_goid)
        return Response(content=content, media_type="application/xml")
    return DFGResponse(
        function_goid=function_goid,
        nodes=[
            DFGNode(
                id=node["id"],
                kind=node["kind"],
                symbol=node.get("symbol"),
                span=_to_span_model(node.get("span")),
            )
            for node in dfg_nodes
        ],
        edges=[
            DFGEdge(src=edge["src"], dst=edge["dst"], label=edge.get("label"))
            for edge in dfg_edges
        ],
    )


def _graphml_from_blocks_edges(
    blocks: Sequence[CFGBlockDict],
    edges: Sequence[CFGEdgeDict],
    function_goid: str,
) -> str:
    """Serialize CFG blocks/edges to GraphML.

    Parameters
    ----------
    blocks : list[dict[str, Any]]
        List of CFG block dictionaries with id and label fields.
    edges : list[dict[str, Any]]
        List of CFG edge dictionaries with src, dst, and optional label fields.
    function_goid : str
        GOID of the function this CFG represents.

    Returns
    -------
    str
        GraphML XML string representation of the CFG.
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        f'<graph edgedefault="directed" id="{function_goid}">',
    ]
    lines.extend(
        (
            f'<node id="{block["id"]}"><data key="label">'
            f"{block.get('label') or block['id']}</data></node>"
        )
        for block in blocks
    )
    lines.extend(
        (
            f'<edge source="{edge["src"]}" target="{edge["dst"]}"><data key="label">'
            f"{edge.get('label') or ''}</data></edge>"
        )
        for edge in edges
    )
    lines.append("</graph></graphml>")
    return "\n".join(lines)


def _graphml_from_nodes_edges(
    nodes: Sequence[DFGNodeDict],
    edges: Sequence[DFGEdgeDict],
    function_goid: str,
) -> str:
    """Serialize DFG nodes/edges to GraphML.

    Parameters
    ----------
    nodes : list[dict[str, Any]]
        List of DFG node dictionaries with id, kind, and optional symbol fields.
    edges : list[dict[str, Any]]
        List of DFG edge dictionaries with src, dst, and optional label fields.
    function_goid : str
        GOID of the function this DFG represents.

    Returns
    -------
    str
        GraphML XML string representation of the DFG.
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        f'<graph edgedefault="directed" id="{function_goid}">',
    ]
    lines.extend(
        (
            f'<node id="{node["id"]}"><data key="kind">{node.get("kind", "")}</data>'
            f'<data key="label">{node.get("symbol") or node["id"]}</data></node>'
        )
        for node in nodes
    )
    lines.extend(
        (
            f'<edge source="{edge["src"]}" target="{edge["dst"]}"><data key="label">'
            f"{edge.get('label') or ''}</data></edge>"
        )
        for edge in edges
    )
    lines.append("</graph></graphml>")
    return "\n".join(lines)


def _to_span_model(span_dict: SpanDict | None) -> Span | None:
    """Convert TypedDict span rows into API models.

    Returns
    -------
    Span | None
        Pydantic span instance mirroring the raw dict, or None.
    """
    if span_dict is None:
        return None
    return Span(
        file_path=span_dict.get("file_path"),
        start_line=span_dict.get("start_line"),
        end_line=span_dict.get("end_line"),
    )


__all__ = [
    "router",
]
