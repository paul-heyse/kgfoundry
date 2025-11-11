"""Symbol MCP tool registrations (pure move from server.py)."""

from __future__ import annotations

from codeintel_rev.mcp_server.error_handling import handle_adapter_errors
from codeintel_rev.mcp_server.schemas import Location, SymbolInfo
from codeintel_rev.mcp_server.server import get_context, mcp
from codeintel_rev.mcp_server.telemetry import tool_operation_scope


@mcp.tool()
@handle_adapter_errors(
    operation="symbols:search",
    empty_result={"symbols": [], "total": 0},
)
def symbol_search(
    query: str,
    kind: str | None = None,
    language: str | None = None,
) -> dict:
    """Search for symbols (functions, classes, etc).

    Returns
    -------
    dict
        Symbol matches payload.
    """
    context = get_context()
    with tool_operation_scope(
        "symbols.search",
        has_query=bool(query),
        kind=kind,
        language=language,
    ):
        with context.open_catalog() as catalog, catalog.connection() as conn:
            sql_lines = [
                "SELECT display_name, kind, language, uri, start_line, start_col, end_line, end_col",
                "FROM symbol_defs WHERE 1=1",
            ]
            params: list[object] = []
            if query:
                trimmed = query.strip()
                sql_lines.append("AND LOWER(display_name) LIKE LOWER(?)")
                params.append(f"{trimmed}%")
            if kind:
                sql_lines.append("AND kind = ?")
                params.append(kind)
            if language:
                sql_lines.append("AND language = ?")
                params.append(language)
            sql_lines.append("ORDER BY LENGTH(display_name), kind, uri LIMIT 200")

            relation = conn.execute("\n".join(sql_lines), params)
            rows = relation.fetchall()

        items: list[SymbolInfo] = []
        for name, k, _lang, uri, sl, sc, el, ec in rows:
            items.append(
                {
                    "name": name,
                    "kind": k or "symbol",
                    "location": {
                        "uri": uri,
                        "start_line": sl,
                        "start_column": sc,
                        "end_line": el,
                        "end_column": ec,
                    },
                }
            )
        return {"symbols": items, "total": len(items)}


@mcp.tool()
@handle_adapter_errors(
    operation="symbols:definition_at",
    empty_result={"locations": []},
)
def definition_at(
    path: str,
    line: int,
    character: int,
) -> dict:
    """Find definition at position.

    Returns
    -------
    dict
        Definition locations response.
    """
    context = get_context()
    with tool_operation_scope("symbols.definition_at", path=path, line=line, character=character):
        with context.open_catalog() as catalog, catalog.connection() as conn:
            occ = conn.execute(
                """
                SELECT symbol FROM symbol_occurrences
                WHERE uri = ?
                  AND (start_line < ? OR (start_line = ? AND start_col <= ?))
                  AND (end_line   > ? OR (end_line   = ? AND end_col   >= ?))
                ORDER BY (end_line - start_line) ASC, (end_col - start_col) ASC
                LIMIT 1
                """,
                [path, line - 1, line - 1, character, line - 1, line - 1, character],
            ).fetchone()
            if not occ:
                return {"locations": []}
            sym = occ[0]
            row = conn.execute(
                """
                SELECT uri, start_line, start_col, end_line, end_col
                FROM symbol_defs WHERE symbol = ? LIMIT 1
                """,
                [sym],
            ).fetchone()
        if not row:
            return {"locations": []}
        uri, sl, sc, el, ec = row
        return {
            "locations": [
                {
                    "uri": uri,
                    "start_line": sl,
                    "start_column": sc,
                    "end_line": el,
                    "end_column": ec,
                }
            ]
        }


@mcp.tool()
@handle_adapter_errors(
    operation="symbols:references_at",
    empty_result={"locations": []},
)
def references_at(
    path: str,
    line: int,
    character: int,
) -> dict:
    """Find references at position.

    Returns
    -------
    dict
        Reference locations response.
    """
    context = get_context()
    with tool_operation_scope("symbols.references_at", path=path, line=line, character=character):
        with context.open_catalog() as catalog, catalog.connection() as conn:
            occ = conn.execute(
                """
                SELECT symbol FROM symbol_occurrences
                WHERE uri = ?
                  AND (start_line < ? OR (start_line = ? AND start_col <= ?))
                  AND (end_line   > ? OR (end_line   = ? AND end_col   >= ?))
                ORDER BY (end_line - start_line) ASC, (end_col - start_col) ASC
                LIMIT 1
                """,
                [path, line - 1, line - 1, character, line - 1, line - 1, character],
            ).fetchone()
            if not occ:
                return {"locations": []}
            sym = occ[0]
            rows = conn.execute(
                """
                SELECT uri, start_line, start_col, end_line, end_col, roles
                FROM symbol_occurrences WHERE symbol = ?
                """,
                [sym],
            ).fetchall()
        locs: list[Location] = []
        for uri, sl, sc, el, ec, roles in rows:
            if int(roles) & 1:
                continue
            locs.append(
                {
                    "uri": uri,
                    "start_line": sl,
                    "start_column": sc,
                    "end_line": el,
                    "end_column": ec,
                }
            )
        return {"locations": locs}
