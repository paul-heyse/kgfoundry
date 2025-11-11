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

    Extended Summary
    ----------------
    This MCP tool performs symbol search by querying the DuckDB catalog for symbol
    definitions matching the query string, optional kind filter, and optional language
    filter. Results are ranked by symbol name length (shorter names first) and
    limited to 200 matches. Used for finding functions, classes, methods, and other
    code symbols by name.

    Parameters
    ----------
    query : str
        Symbol name or prefix to search for (e.g., "parse_json", "User"). The search
        is case-insensitive and matches symbols starting with the query string.
    kind : str | None, optional
        Optional symbol kind filter (e.g., "function", "class", "method"). If provided,
        only symbols of this kind are returned.
    language : str | None, optional
        Optional programming language filter (e.g., "python", "typescript"). If provided,
        only symbols from this language are returned.

    Returns
    -------
    dict
        Symbol matches payload containing:
        - symbols: list[SymbolInfo], matching symbols with name, kind, and location
        - total: int, number of symbols returned (max 200)

    Notes
    -----
    This tool requires SCIP index and DuckDB catalog to be available. Search is
    performed via SQL LIKE queries on the symbol_defs table. Results are sorted by
    name length to prioritize shorter, more specific matches. Time complexity: O(1)
    for SQL query execution.
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

    Extended Summary
    ----------------
    This MCP tool finds the definition of a symbol at a specific file position by
    querying the DuckDB catalog for symbol occurrences at that location, then
    retrieving the corresponding definition. Used for "go to definition" functionality
    in code editors and IDEs.

    Parameters
    ----------
    path : str
        File path (URI) where the symbol occurs.
    line : int
        Line number (1-indexed) where the symbol occurs.
    character : int
        Character offset (0-indexed) within the line where the symbol occurs.

    Returns
    -------
    dict
        Definition locations response containing:
        - locations: list[dict], definition locations with uri, start_line, start_column,
          end_line, end_column. Empty list if no definition found.

    Notes
    -----
    This tool requires SCIP index and DuckDB catalog to be available. It performs
    two SQL queries: first to find the symbol at the position, then to find its
    definition. Time complexity: O(1) for SQL query execution.
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

    Extended Summary
    ----------------
    This MCP tool finds all references to a symbol at a specific file position by
    querying the DuckDB catalog for symbol occurrences, then retrieving all occurrences
    of that symbol. Used for "find all references" functionality in code editors and IDEs.

    Parameters
    ----------
    path : str
        File path (URI) where the symbol occurs.
    line : int
        Line number (1-indexed) where the symbol occurs.
    character : int
        Character offset (0-indexed) within the line where the symbol occurs.

    Returns
    -------
    dict
        Reference locations response containing:
        - locations: list[dict], all reference locations with uri, start_line, start_column,
          end_line, end_column. Empty list if no references found.

    Notes
    -----
    This tool requires SCIP index and DuckDB catalog to be available. It performs
    two SQL queries: first to find the symbol at the position, then to find all
    occurrences of that symbol. Time complexity: O(n) where n is the number of
    references (SQL query execution).
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
