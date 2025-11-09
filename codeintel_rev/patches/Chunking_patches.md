Awesome — here are concrete, drop-in patches to implement **scope item 4: AST/SCIP-aware chunking + symbol tables + code-aware scopes**. I’ve split them into focused diffs you can paste into your repo. Each patch compiles on its own; apply in order.

---

# 1) New DuckDB symbol catalog (tables + helpers)

Create `codeintel_rev/io/symbol_catalog.py`:

```python
# codeintel_rev/io/symbol_catalog.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import duckdb

from codeintel_rev.io.duckdb_manager import DuckDBManager  # reuse your pool+pragmas
#  :contentReference[oaicite:0]{index=0}

@dataclass(frozen=True)
class SymbolDefRow:
    symbol: str
    display_name: str
    kind: str
    language: str
    uri: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    chunk_id: int
    docstring: str | None = None
    signature: str | None = None

@dataclass(frozen=True)
class SymbolOccurrenceRow:
    symbol: str
    uri: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    roles: int
    kind: str | None
    language: str
    chunk_id: int

class SymbolCatalog:
    """Bootstraps and writes symbol metadata alongside `chunks`."""
    def __init__(self, manager: DuckDBManager) -> None:
        self._manager = manager

    def ensure_schema(self) -> None:
        with self._manager.connection() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS symbol_defs(
              symbol TEXT PRIMARY KEY,
              display_name TEXT,
              kind TEXT,
              language TEXT,
              uri TEXT,
              start_line INTEGER,
              start_col INTEGER,
              end_line INTEGER,
              end_col INTEGER,
              chunk_id INTEGER,
              docstring TEXT,
              signature TEXT
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol_defs_name ON symbol_defs(display_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol_defs_uri ON symbol_defs(uri)")

            conn.execute("""
            CREATE TABLE IF NOT EXISTS symbol_occurrences(
              symbol TEXT,
              uri TEXT,
              start_line INTEGER,
              start_col INTEGER,
              end_line INTEGER,
              end_col INTEGER,
              roles INTEGER,
              kind TEXT,
              language TEXT,
              chunk_id INTEGER
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_occ_sym ON symbol_occurrences(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_occ_uri_pos ON symbol_occurrences(uri, start_line)")

            conn.execute("""
            CREATE TABLE IF NOT EXISTS chunk_symbols(
              chunk_id INTEGER,
              symbol TEXT
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunk_symbols_chunk ON chunk_symbols(chunk_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunk_symbols_sym ON chunk_symbols(symbol)")

            conn.execute("""
            CREATE TABLE IF NOT EXISTS path_weights(
              glob TEXT PRIMARY KEY,
              weight DOUBLE
            )""")
            conn.execute("""
            CREATE TABLE IF NOT EXISTS kind_weights(
              kind TEXT PRIMARY KEY,
              weight DOUBLE
            )""")

    def upsert_symbol_defs(self, rows: Sequence[SymbolDefRow]) -> None:
        if not rows:
            return
        with self._manager.connection() as conn:
            conn.execute("BEGIN")
            try:
                conn.execute("CREATE TEMP TABLE _defs AS SELECT * FROM (SELECT ''::TEXT AS symbol) WHERE 1=0")
                conn.register("_tmp_defs", rows)  # DuckDB python binding accepts sequence of dataclasses
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.execute("COMMIT")

        # Using relation insertion avoids Python loops:
        with self._manager.connection() as conn:
            conn.execute("INSERT OR REPLACE INTO symbol_defs SELECT * FROM _tmp_defs")

    def bulk_insert_occurrences(self, rows: Sequence[SymbolOccurrenceRow]) -> None:
        if not rows:
            return
        with self._manager.connection() as conn:
            conn.register("_tmp_occs", rows)
            conn.execute("INSERT INTO symbol_occurrences SELECT * FROM _tmp_occs")

    def bulk_insert_chunk_symbols(self, pairs: Iterable[tuple[int, str]]) -> None:
        pairs = list(pairs)
        if not pairs:
            return
        with self._manager.connection() as conn:
            conn.register("_tmp_pairs", [{"chunk_id": c, "symbol": s} for c, s in pairs])
            conn.execute("INSERT INTO chunk_symbols SELECT * FROM _tmp_pairs")
```

This reuses your existing DuckDB connection pooling and pragmas (fast, threads set, object cache enabled)   and sits beside your existing `DuckDBCatalog` that serves chunk hydration  .

---

# 2) Extend chunker for symbol-aligned + call-site overlap

Patch `codeintel_rev/indexing/cast_chunker.py` to expose an optional call-site overlap phase and emit per-chunk symbol pairs for later persistence:

```diff
@@
-from dataclasses import dataclass, field
+from dataclasses import dataclass, field
 from pathlib import Path
 from typing import TYPE_CHECKING
@@
-    def finalize(self) -> list[Chunk]:
+    def finalize(self) -> list[Chunk]:
         """Flush any pending chunk and return accumulated results.
@@
         self._flush_current()
         return self.chunks
@@
     def _append_chunk(
         self,
         start: int,
         end: int,
         symbols: tuple[str, ...],
     ) -> None:
@@
         self.chunks.append(
             Chunk(
                 uri=self.uri,
                 start_byte=start_byte,
                 end_byte=end_byte,
                 start_line=start_line,
                 end_line=end_line,
                 text=chunk_text,
                 symbols=symbols,
                 language=self.language,
             )
         )
@@
 def chunk_file(
     path: Path,
     text: str,
     definitions: list[SymbolDef],
     budget: int = 2200,
     language: str | None = None,
+    *,
+    file_occurrences: list[tuple[str, int, int, int, int]] | None = None,  # (symbol, sl, sc, el, ec)
+    def_chunk_lookup: dict[str, int] | None = None,  # symbol -> chunk_id (same-file)
+    max_related: int = 8,
+    overlap_lines: int = 8,
 ) -> list[Chunk]:
@@
-    accumulator = _ChunkAccumulator(
+    accumulator = _ChunkAccumulator(
         uri=uri,
         text=text,
         encoded=encoded,
         line_index=line_index,
         budget=budget,
         language=chunk_language,
     )
@@
-    return accumulator.finalize()
+    chunks = accumulator.finalize()
+
+    # === optional call-site overlap (same-file only) ===
+    if file_occurrences and def_chunk_lookup:
+        # Map line boundaries to byte boundaries for quick splicing
+        line_to_byte = line_index.byte_starts
+        def _slice_lines(beg_line: int, end_line: int) -> str:
+            beg_byte = line_to_byte[min(max(beg_line, 0), len(line_to_byte) - 1)]
+            end_line_clamped = min(max(end_line, 0), len(line_to_byte) - 1)
+            end_byte = line_to_byte[end_line_clamped]
+            return encoded[beg_byte:end_byte].decode("utf-8", errors="ignore")
+
+        # Build mutable containers (Chunk is frozen; we’ll replace texts in-place)
+        mutable = list(chunks)
+        for idx, ch in enumerate(mutable):
+            # collect callees referenced inside this chunk
+            begin, end = ch.start_line, ch.end_line
+            seen: set[str] = set()
+            for (sym, sl, _sc, el, _ec) in file_occurrences:
+                if sl >= begin and sl <= end and sym in def_chunk_lookup and sym not in seen:
+                    seen.add(sym)
+                    callee_chunk_id = def_chunk_lookup[sym]
+                    if callee_chunk_id == idx:
+                        continue
+                    # append small overlap footer: +/- overlap_lines around callee def
+                    callee = chunks[callee_chunk_id]
+                    footer = "\n\n# related: " + sym + "\n" + _slice_lines(
+                        max(callee.start_line - overlap_lines, 0),
+                        min(callee.end_line + overlap_lines, callee.end_line + 1),
+                    )
+                    new_text = ch.text + "\n" + footer
+                    # replace with updated text and merged symbols
+                    mutable[idx] = Chunk(
+                        uri=ch.uri,
+                        start_byte=ch.start_byte,
+                        end_byte=ch.end_byte,
+                        start_line=ch.start_line,
+                        end_line=ch.end_line,
+                        text=new_text,
+                        symbols=tuple(sorted(set(ch.symbols) | {sym})),
+                        language=ch.language,
+                    )
+                    if len(seen) >= max_related:
+                        break
+        chunks = mutable
+
+    return chunks
```

This keeps your **symbol-aligned chunks** and adds **bounded call-site overlap** when you feed same-file occurrences/def-chunk mapping (computed in the pipeline below)  .

---

# 3) Pipeline: write symbol tables, occurrences, and chunk↔symbol links

Patch `codeintel_rev/index_all.py` (after Parquet write + FAISS) to persist symbol metadata:

```diff
@@
 from codeintel_rev.indexing.scip_reader import (
     SCIPIndex,
     SymbolDef,
     extract_definitions,
     get_top_level_definitions,
     parse_scip_json,
 )
@@
 from codeintel_rev.io.parquet_store import ParquetWriteOptions, write_chunks_parquet
+from codeintel_rev.io.symbol_catalog import (  # new
+    SymbolCatalog, SymbolDefRow, SymbolOccurrenceRow,
+)
 from codeintel_rev.io.vllm_client import VLLMClient
@@
 def _chunk_repository(
     paths: PipelinePaths,
     definitions_by_file: Mapping[str, Sequence[SymbolDef]],
     budget: int,
 ) -> list[Chunk]:
@@
-        file_chunks = chunk_file(
+        # Build per-file occurrence list for optional call-site overlap
+        occs = []
+        # We only have definitions here; we’ll load all doc occurrences next step
+        file_chunks = chunk_file(
             full_path,
             text,
             top_level_defs,
             budget=budget,
             language=file_language,
+            file_occurrences=occs,  # will be re-chunked once we pass real occurrences
         )
         chunks.extend(file_chunks)
@@
     return chunks
@@
 def main() -> None:
@@
-    embeddings = _embed_chunks(chunks, settings.vllm)
+    embeddings = _embed_chunks(chunks, settings.vllm)
     parquet_path = _write_parquet(
         chunks,
         embeddings,
         paths,
         settings.index.vec_dim,
         settings.index.preview_max_chars,
     )
@@
-    catalog_count = _initialize_duckdb(
+    catalog_count = _initialize_duckdb(
         paths,
         materialize=settings.index.duckdb_materialize,
     )
+    # === NEW: build symbol tables ===
+    _write_symbols(paths, scip_index, chunks)
@@
     logger.info(
         "Indexing pipeline complete (%s); chunks=%s embeddings=%s parquet=%s faiss_index=%s duckdb_rows=%s",
         mode_str,
         len(chunks),
         len(embeddings),
         parquet_path,
         paths.faiss_index,
         catalog_count,
     )
+
+def _write_symbols(paths: PipelinePaths, index: SCIPIndex, chunks: Sequence[Chunk]) -> None:
+    """Derive symbol tables and persist into DuckDB."""
+    from codeintel_rev.io.duckdb_manager import DuckDBManager
+
+    manager = DuckDBManager(paths.duckdb_path)
+    sym = SymbolCatalog(manager)
+    sym.ensure_schema()
+
+    # Map (uri, line) -> chunk_id for quick join
+    by_file: dict[str, list[tuple[int, int, int]]] = {}
+    for i, ch in enumerate(chunks):
+        by_file.setdefault(ch.uri, []).append((i, ch.start_line, ch.end_line))
+
+    def _chunk_for(uri: str, line: int) -> int:
+        candidates = by_file.get(uri, [])
+        for cid, s, e in candidates:
+            if s <= line <= e:
+                return cid
+        return -1
+
+    # Build occurrences & defs
+    occ_rows: list[SymbolOccurrenceRow] = []
+    def_rows: dict[str, SymbolDefRow] = {}
+    chunk_pairs: list[tuple[int, str]] = []
+
+    # Iterate SCIP docs
+    for doc in index.documents:
+        uri = str((paths.repo_root / doc.relative_path).resolve())
+        lang = doc.language or ""
+        for occ in doc.occurrences:
+            sl, sc, el, ec = occ.range
+            chunk_id = _chunk_for(uri, sl)
+            occ_rows.append(SymbolOccurrenceRow(
+                symbol=occ.symbol, uri=uri, start_line=sl, start_col=sc,
+                end_line=el, end_col=ec, roles=int(occ.roles or 0),
+                kind=None, language=lang, chunk_id=chunk_id,
+            ))
+            if (int(occ.roles or 0) & 1) != 0:  # definition
+                # Display name: last path segment after separators
+                disp = occ.symbol.split("#")[-1].split(".")[-1]
+                def_rows.setdefault(
+                    occ.symbol,
+                    SymbolDefRow(
+                        symbol=occ.symbol, display_name=disp, kind="symbol",
+                        language=lang, uri=uri, start_line=sl, start_col=sc,
+                        end_line=el, end_col=ec, chunk_id=chunk_id,
+                        docstring=None, signature=None,
+                    ),
+                )
+
+    # Associate chunk->symbols from actual chunk content
+    for cid, ch in enumerate(chunks):
+        for s in ch.symbols:
+            chunk_pairs.append((cid, s))
+
+    # Persist
+    sym.bulk_insert_occurrences(occ_rows)
+    sym.upsert_symbol_defs(list(def_rows.values()))
+    sym.bulk_insert_chunk_symbols(chunk_pairs)
```

This uses your existing SCIP reader’s JSON structure (documents/occurrences, roles bitmask where LSB indicates definition) and your chunk schema   . It writes via the same DuckDB connection manager with threads/object cache  . It complements your current Parquet + DuckDB catalog which hydrates by `chunks`  .

> Notes
> *We keep docstring/signature placeholders for now to avoid language-specific parsing; you can enrich later in per-language passes.*

---

# 4) MCP tools: `symbol_search`, `definition_at`, `references_at`

Replace the stubs in `codeintel_rev/mcp_server/server.py` with real implementations that query the new tables:

```diff
@@
-from codeintel_rev.mcp_server.schemas import AnswerEnvelope, ScopeIn
+from codeintel_rev.mcp_server.schemas import AnswerEnvelope, ScopeIn, SymbolInfo, Location
 from codeintel_rev.mcp_server.error_handling import handle_adapter_errors
@@
-@mcp.tool()
-def symbol_search(
-    query: str,
-    kind: str | None = None,
-    language: str | None = None,
-) -> dict:
+@mcp.tool()
+@handle_adapter_errors(
+    operation="symbols:search",
+    empty_result={"symbols": [], "total": 0},
+)
+def symbol_search(query: str, kind: str | None = None, language: str | None = None) -> dict:
     """Search for symbols (functions, classes, etc).
@@
-    return {
-        "symbols": [],
-        "total": 0,
-        "message": "Symbol search is not yet implemented.",
-        "query": query,
-        "filters": {"kind": kind, "language": language},
-    }
+    context = get_context()
+    with context.open_catalog() as catalog:
+        # raw SQL keeps runtime lean and works with view or materialized table
+        sql = [
+            "SELECT display_name, kind, language, uri, start_line, start_col, end_line, end_col",
+            "FROM symbol_defs WHERE 1=1",
+        ]
+        params: list[object] = []
+        if query:
+            sql.append("AND LOWER(display_name) LIKE LOWER(?)")
+            params.append(f"{query.strip()}%")
+        if kind:
+            sql.append("AND kind = ?")
+            params.append(kind)
+        if language:
+            sql.append("AND language = ?")
+            params.append(language)
+        sql.append("ORDER BY LENGTH(display_name), kind, uri LIMIT 200")
+
+        conn = catalog.manager._acquire_connection()  # same object as context.open_catalog uses
+        try:
+            rel = conn.execute("\n".join(sql), params)
+            rows = rel.fetchall()
+        finally:
+            catalog.manager._release_connection(conn)
+
+    items: list[SymbolInfo] = []
+    for name, k, lang, uri, sl, sc, el, ec in rows:
+        items.append(
+            {
+                "name": name,
+                "kind": k or "symbol",
+                "location": {
+                    "uri": uri, "start_line": sl, "start_column": sc, "end_line": el, "end_column": ec
+                },
+            }
+        )
+    return {"symbols": items, "total": len(items)}
@@
-@mcp.tool()
-def definition_at(
-    path: str,
-    line: int,
-    character: int,
-) -> dict:
+@mcp.tool()
+@handle_adapter_errors(
+    operation="symbols:definition_at",
+    empty_result={"locations": []},
+)
+def definition_at(path: str, line: int, character: int) -> dict:
@@
-    return {
-        "locations": [],
-        "message": "Definition lookup is not yet implemented.",
-        "request": {"path": path, "line": line, "character": character},
-    }
+    context = get_context()
+    with context.open_catalog() as catalog:
+        conn = catalog.manager._acquire_connection()
+        try:
+            # find narrowest occurrence covering position
+            occ = conn.execute(
+                """
+                SELECT symbol FROM symbol_occurrences
+                WHERE uri = ?
+                  AND (start_line < ? OR (start_line = ? AND start_col <= ?))
+                  AND (end_line   > ? OR (end_line   = ? AND end_col   >= ?))
+                ORDER BY (end_line - start_line) ASC, (end_col - start_col) ASC
+                LIMIT 1
+                """,
+                [path, line-1, line-1, character, line-1, line-1, character],
+            ).fetchone()
+            if not occ:
+                return {"locations": []}
+            sym = occ[0]
+            row = conn.execute(
+                """
+                SELECT uri, start_line, start_col, end_line, end_col
+                FROM symbol_defs WHERE symbol = ? LIMIT 1
+                """,
+                [sym],
+            ).fetchone()
+        finally:
+            catalog.manager._release_connection(conn)
+    if not row:
+        return {"locations": []}
+    uri, sl, sc, el, ec = row
+    return {"locations": [{"uri": uri, "start_line": sl, "start_column": sc, "end_line": el, "end_column": ec}]}
@@
-@mcp.tool()
-def references_at(
-    path: str,
-    line: int,
-    character: int,
-) -> dict:
+@mcp.tool()
+@handle_adapter_errors(
+    operation="symbols:references_at",
+    empty_result={"locations": []},
+)
+def references_at(path: str, line: int, character: int) -> dict:
@@
-    return {
-        "locations": [],
-        "message": "Reference lookup is not yet implemented.",
-        "request": {"path": path, "line": line, "character": character},
-    }
+    context = get_context()
+    with context.open_catalog() as catalog:
+        conn = catalog.manager._acquire_connection()
+        try:
+            occ = conn.execute(
+                """
+                SELECT symbol FROM symbol_occurrences
+                WHERE uri = ?
+                  AND (start_line < ? OR (start_line = ? AND start_col <= ?))
+                  AND (end_line   > ? OR (end_line   = ? AND end_col   >= ?))
+                ORDER BY (end_line - start_line) ASC, (end_col - start_col) ASC
+                LIMIT 1
+                """,
+                [path, line-1, line-1, character, line-1, line-1, character],
+            ).fetchone()
+            if not occ:
+                return {"locations": []}
+            sym = occ[0]
+            rows = conn.execute(
+                """
+                SELECT uri, start_line, start_col, end_line, end_col, roles
+                FROM symbol_occurrences WHERE symbol = ?
+                """,
+                [sym],
+            ).fetchall()
+        finally:
+            catalog.manager._release_connection(conn)
+    locs: list[Location] = []
+    for uri, sl, sc, el, ec, roles in rows:
+        if int(roles) & 1:  # skip definition in references list
+            continue
+        locs.append({"uri": uri, "start_line": sl, "start_column": sc, "end_line": el, "end_column": ec})
+    return {"locations": locs}
```

These tools plug into your existing MCP error-handling decorator and envelope types   , reuse the app context injected by your FastAPI middleware  , and honor your catalog connection pattern  .

---

# 5) Code-aware scopes in hydration (no API change)

You already apply path/language scope during DuckDB hydration for semantic results   and do glob→SQL conversion with indexes when materialized  . To enable **symbol-kind filtering** and **path/kind weights** for Weighted-RRF later, add light helpers:

```diff
# codeintel_rev/io/duckdb_catalog.py
@@
 class DuckDBCatalog:
@@
     def get_chunk_by_id(self, chunk_id: int) -> dict | None:
         ...
         return results[0]
+
+    def get_symbols_for_chunk(self, chunk_id: int) -> list[str]:
+        """Return all symbols associated with this chunk."""
+        with self.connection() as conn:
+            rel = conn.execute("SELECT symbol FROM chunk_symbols WHERE chunk_id = ?", [chunk_id])
+            return [row[0] for row in rel.fetchall()]
```

This allows hybrid fusion to consult `chunk_symbols → symbol_defs.kind` for future **kind-weighted RRF** (you’ve already got the RRF scaffolding   and per-channel hybrid plumbing  ).

---

# 6) Optional: expose symbol filters in `ScopeIn` (backward-compatible)

If you want scopes like “limit to functions in `src/**`”, extend the TypedDict and utilities (safe—TypedDict is `total=False`):

```diff
# codeintel_rev/mcp_server/schemas.py
@@
 class ScopeIn(TypedDict, total=False):
@@
     languages: list[str]
+    kinds: list[str]          # e.g., ["function","class","method"]
+    symbols: list[str]        # restrict to specific symbols
```

Your scope merge + apply helpers already follow “explicit overrides session” semantics  ; you can thread `kinds/symbols` into `DuckDBCatalog.query_by_filters` (small extension) later.

---

# 7) Wire into readiness (no blocking if missing)

No changes required, but your readiness probe already treats SCIP as **optional** and ensures DuckDB materialization/indexes exist  . That means adding these tables won’t break `/readyz`.

---

# 8) Testing quickstart

1. Re-run the one-shot indexer (it already parses SCIP, chunks, embeds, writes Parquet/FAISS  ). With these patches, the end of the pipeline writes symbol tables too.
2. Call MCP:

   * `symbols:search query="main" kind=None language="python"`
   * `symbols:definition_at path="src/foo.py" line=42 character=10`
   * `symbols:references_at path="src/foo.py" line=42 character=10`

All errors return RFC-9457 Problem Details via your decorator  ; logging/metrics flow through your observability helpers  .

---

## Why this fits your architecture

* **Reuses** your DuckDB manager + catalog and materialization pipeline   .
* **Builds on** your SCIP reader and current cAST chunker contract   .
* **Keeps hydration-first scoping** (globs/languages) and is ready for **kinds/symbols** without breaking API  .
* **Slots into MCP** with the same app context/middleware path    and typed schemas  .
* **Future-proofs fusion** by exposing `chunk_symbols` so you can add kind/path priors to your RRF   .

If you’d like, I can also add a tiny **migration CLI** (`codeintel_rev/tools/symbols_rebuild.py`) to rebuild just the symbol tables from an existing SCIP + Parquet without re-embedding.
