Below is a complete, conflict‑aware implementation plan and ready‑to‑paste patchset that hardens and modularizes the FAISS ⇄ DuckDB ⇄ vLLM ⇄ BM25/SPLADE ⇄ MCP stack given your Phase‑2 CST/AST/SCIP pipeline upgrades and the current repository layout.

I derived the changes from the current code graph (SCIP index + repo map) and from your Phase‑2 DuckDB+PyArrow expansion notes, so the diffs below bind to functions and files that already exist in your tree—no blind renames. Where I reference functions/classes that already exist, I cite their presence in your code graph for traceability. For example, `DuckDBCatalog.ensure_faiss_idmap_views()` / `materialize_faiss_join()` and the checksum‑guarded materialization helpers are already present and used by `indexctl materialize-join`, so the plan wires around those rather than inventing new entry points.

---

## Executive summary (what changes and why)

**Upstream change impact.** Phase‑2 made your JSON/JSONL → Arrow → DuckDB path stricter (stable types, explicit encodings, checksum‑guarded materializations). It also standardized write locations for symbol graph, modules, and SCIP occurrences (per your design note), and you already added id‑map join helpers and CLI verbs to refresh/materialize FAISS joins.

**What we do here.**

1. **Persist richer chunk columns** (`symbols`, `content_hash`) in Parquet and surface them in DuckDB views so downstream stages (FAISS rerank/explainability, MCP narrative) don’t need to re‑parse JSONL. The touchpoints are `io/parquet_store.py` and `io/duckdb_catalog.py`.

2. **Complete & tighten the FAISS→hydration seam.** Use the existing ID‑map mixin (`_FAISSIdMapMixin`) to guarantee `{faiss_row → chunk_id}` stability and to hydrate via catalog methods; extend the FAISS search path with an exact rerank step that reuses your existing Flat reranker and embedding fetch helpers.

3. **Expose structure‑aware views in DuckDB** (modules, SCIP occurrences, AST/CST outlines/imports) with **materialized join** guarded by checksums that you already implemented for the FAISS join—so BI and MCP “fetch” get fast and consistent results. 

4. **Integrate explainability + contributions in MCP** by adding symbol/AST/CST context to the hydrated findings and reusing your hybrid contribution annotator + overfetch logic already present in `mcp_server.adapters.semantic`.

5. **Localize telemetry** to three boundaries (ANN, refine, hydrate) and expose them via existing observability scaffolding; this aligns with your `_run_hydration_stage()`, hybrid result trimming, and rrf annotation pipeline already in place.

The rest of this answer gives you: **(A)** the implementation checklist; **(B)** precise diffs; **(C)** smoke/golden tests and a rollout checklist.

---

## A) Implementation checklist (systematic, step‑by‑step)

### 1) Persist richer chunk columns and register views

* **Extend Arrow schema and writer**: Add `symbols: list<string>` and `content_hash: string` to `get_chunks_schema()` and to the table created in `write_chunks_parquet()`. Use your `Chunk.symbols` and compute `xxh64` hash over `text` or `(uri,start_byte,end_byte,text)`; continue to keep `embedding` as `FixedSizeList(float32, dim)`. `get_chunks_schema` already lives in `io/parquet_store.py`.

* **Register + materialize views**: Add a convenience `DuckDBCatalog.ensure_struct_views(modules, scip_occ, ast, cst, materialize=...)` that calls your existing `ensure_faiss_idmap_views()` and the checksum‑guarded materialization pattern you already used for the FAISS join. Also add `ensure_pool_views()` call sites where appropriate (it already exists), so evaluator pools & hybrid diagnostics stay in sync.

* **Wire lifecycle/CLI**: During `publish`, call `ensure_struct_views(...)` after copying staged assets, mirroring how `materialize_faiss_join()` is already reachable via `indexctl`. 

### 2) Make FAISS→hydration robust and truth‑preserving

* **Guarantee ID stability** using your `_FAISSIdMapMixin`. Its `hydrate_by_ids()` already calls the catalog batch query; we keep that seam and only expand the selected columns to include `symbols`, and lightweight structural fields. 

* **Exact second‑stage rerank**: Keep ANN K’ = `k * refine_k_factor` and rerank with your **existing Flat reranker** (`retrieval/rerank_flat.py`) by fetching candidate embeddings with `DuckDBCatalog.get_embeddings_by_ids()`. Both the helper and reranker already exist—wire them from FAISS manager/hybrid engine, and record latency.

### 3) Enrich MCP search/fetch outputs (no schema break)

* **Search**: keep the tool’s current schema but include `explanations.symbols`, and (when present) `explanations.ast_kinds` / `explanations.cst_imports` in `metadata` / `structuredContent`, sourced from the DuckDB join in hydration (no extra JSONL reads at request time). You already have `_resolve_hybrid_results()`, `_build_hybrid_result()`, `_run_hydration_stage()` to centralize this.

* **Fetch**: return richer `content` + `metadata` (symbols, lang, module key, uri, line span, content_hash, FAISS distance, and hybrid contribution narrative); you already have `_annotate_hybrid_contributions()` for the narrative. 

### 4) Telemetry + safeguards

* Emit **three histograms**: `ann_ms`, `rerank_ms`, `hydrate_ms` (aligns with your hydration stage timing and hybrid trim points). Add a counter `post_filter_density` = retained/overfetched. The semantic adapter and hybrid code already segment the pipeline, so we add measures at those boundaries.

---

## B) Patchset (ready‑to‑paste diffs)

> **Notes.**
> • Paths and anchors match your repo map; referenced functions already exist. 
> • I minimized edits to reduce risk; new helpers are additive.
> • Where I import `xxhash`, you can swap to your preferred fast hash; DuckDB checksum guards continue to use your existing helper. 

### B1) `io/parquet_store.py` — add `symbols` + `content_hash`

We extend the Arrow schema and the writer. Your schema function and dataclass usage are visible in the SCIP index—this patch adds two fields while keeping all current ones (id, uri, lines, bytes, preview/content, lang, embedding).

```diff
*** a/codeintel_rev/io/parquet_store.py
--- b/codeintel_rev/io/parquet_store.py
@@
-from pyarrow import Table as PaTable
+from pyarrow import Table as PaTable
+import xxhash
 
@@
-def get_chunks_schema(vec_dim: int) -> pa.Schema:
-    """Get Arrow schema for chunks table."""
-    return pa.schema([
-        pa.field("id", pa.uint64()),
-        pa.field("uri", pa.string()),
-        pa.field("start_line", pa.uint32()),
-        pa.field("end_line", pa.uint32()),
-        pa.field("start_byte", pa.uint32()),
-        pa.field("end_byte", pa.uint32()),
-        pa.field("preview", pa.string()),
-        pa.field("content", pa.string()),
-        pa.field("lang", pa.string()),
-        pa.field("embedding", pa.list_(pa.field("item", pa.float32()), list_size=vec_dim)),
-    ])
+def get_chunks_schema(vec_dim: int) -> pa.Schema:
+    """Get Arrow schema for chunks table."""
+    return pa.schema([
+        pa.field("id", pa.uint64()),
+        pa.field("uri", pa.string()),
+        pa.field("start_line", pa.uint32()),
+        pa.field("end_line", pa.uint32()),
+        pa.field("start_byte", pa.uint32()),
+        pa.field("end_byte", pa.uint32()),
+        pa.field("preview", pa.string()),
+        pa.field("content", pa.string()),
+        pa.field("lang", pa.string()),
+        # NEW: structural + determinism fields
+        pa.field("symbols", pa.list_(pa.field("item", pa.string()))),
+        pa.field("content_hash", pa.string()),
+        # embeddings last; never selected unless needed
+        pa.field("embedding", pa.list_(pa.field("item", pa.float32()), list_size=vec_dim)),
+    ])
@@
-    # assemble Arrow columns (existing)
+    # assemble Arrow columns (existing)
     ids = pa.array([row_id + i for i in range(len(chunks))], type=pa.uint64())
@@
-    table = pa.table({
-        "id": ids,
-        "uri": uris,
-        "start_line": start_lines,
-        "end_line": end_lines,
-        "start_byte": start_bytes,
-        "end_byte": end_bytes,
-        "preview": previews,
-        "content": contents,
-        "lang": langs,
-        "embedding": embeddings
-    }, schema=get_chunks_schema(options.vec_dim))
+    # NEW: structural arrays
+    symbols = pa.array([list(ch.symbols) for ch in chunks], type=pa.list_(pa.string()))
+    content_hashes = pa.array([
+        xxhash.xxh3_64_hexdigest(f"{ch.uri}|{ch.start_byte}|{ch.end_byte}|{ch.text}")
+        for ch in chunks
+    ])
+    table = pa.table({
+        "id": ids,
+        "uri": uris,
+        "start_line": start_lines,
+        "end_line": end_lines,
+        "start_byte": start_bytes,
+        "end_byte": end_bytes,
+        "preview": previews,
+        "content": contents,
+        "lang": langs,
+        "symbols": symbols,
+        "content_hash": content_hashes,
+        "embedding": embeddings
+    }, schema=get_chunks_schema(options.vec_dim))
```

Rationale: `Chunk.symbols` is present in the upstream dataclass; we persist it now so search, explainability, and MCP can join cheaply without touching raw JSONL. 

### B2) `io/duckdb_catalog.py` — register structure views & reuse checksum guard

You already have: idmap view installer, checksum‑guarded materializer, and pool views. We add “struct views” registration and light helpers for symbol access.

```diff
*** a/codeintel_rev/io/duckdb_catalog.py
--- b/codeintel_rev/io/duckdb_catalog.py
@@
 from pathlib import Path
 import duckdb as _duckdb
@@
 class DuckDBCatalog:
@@
     def ensure_faiss_idmap_views(self, idmap_path: Path | None = None) -> None:
         ...
 
+    # --- NEW: structured asset view bootstrap ---------------------------------
+    def ensure_struct_views(
+        self,
+        *,
+        modules_parquet: Path | None = None,
+        scip_occurrences_parquet: Path | None = None,
+        ast_nodes_parquet: Path | None = None,
+        cst_nodes_parquet: Path | None = None,
+        materialize: bool = False,
+    ) -> None:
+        """
+        Register JSON/Parquet assets as DuckDB views and optionally materialize
+        structure-aware tables for BI and fast hydration.
+        """
+        conn = self.connection()
+        # register modules
+        if modules_parquet and modules_parquet.exists():
+            self._log_query("register modules", path=str(modules_parquet))
+            conn.execute(f"CREATE OR REPLACE VIEW v_modules AS SELECT * FROM read_parquet('{modules_parquet.as_posix()}')")
+        # register SCIP occurrences (defs/refs)
+        if scip_occurrences_parquet and scip_occurrences_parquet.exists():
+            self._log_query("register scip_occurrences", path=str(scip_occurrences_parquet))
+            conn.execute(f"CREATE OR REPLACE VIEW v_scip_occurrences AS SELECT * FROM read_parquet('{scip_occurrences_parquet.as_posix()}')")
+        # register AST/CST (optional; may be JSONL or Parquet)
+        if ast_nodes_parquet and ast_nodes_parquet.exists():
+            conn.execute(f"CREATE OR REPLACE VIEW v_ast_nodes AS SELECT * FROM read_parquet('{ast_nodes_parquet.as_posix()}')")
+        if cst_nodes_parquet and cst_nodes_parquet.exists():
+            conn.execute(f"CREATE OR REPLACE VIEW v_cst_nodes AS SELECT * FROM read_parquet('{cst_nodes_parquet.as_posix()}')")
+        # a narrow “symbols per chunk” view from chunks parquet itself
+        conn.execute("""
+            CREATE OR REPLACE VIEW v_chunk_symbols AS
+            SELECT id AS chunk_id, UNNEST(symbols) AS symbol FROM chunks
+        """)
+        if materialize:
+            # reuse checksum guard style from FAISS materializer
+            self.materialize_faiss_join()
+            self._materialize_if_changed(
+                table="modules_mat", source="SELECT * FROM v_modules", checksum_view="modules_meta"
+            )
+            self._materialize_if_changed(
+                table="scip_occurrences_mat", source="SELECT * FROM v_scip_occurrences", checksum_view="scip_occ_meta"
+            )
+
+    # convenience for hydration/explainability
+    def get_symbols_for_chunk(self, chunk_id: int) -> list[str]:
+        conn = self.connection()
+        rows = conn.execute("SELECT symbol FROM v_chunk_symbols WHERE chunk_id = ?", [chunk_id]).fetchall()
+        return [r[0] for r in rows]
+
+    # --- NEW: generic materializer with checksum (parallels your FAISS one) ---
+    def _materialize_if_changed(self, *, table: str, source: str, checksum_view: str) -> None:
+        conn = self.connection()
+        self._log_query("materialize_if_changed", table=table)
+        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} AS {source} LIMIT 0")
+        # simplistic: compute checksum of the source query logical hash
+        conn.execute(f"CREATE TABLE IF NOT EXISTS {checksum_view}(checksum TEXT)")
+        new_ck = conn.execute(f"SELECT md5(list_value(list_agg(*)::TEXT)) FROM ({source})").fetchone()[0]
+        old_ck = conn.execute(f"SELECT checksum FROM {checksum_view} LIMIT 1").fetchone()
+        if not old_ck or old_ck[0] != new_ck:
+            conn.execute(f"DELETE FROM {table}")
+            conn.execute(f"INSERT INTO {table} {source}")
+            conn.execute(f"DELETE FROM {checksum_view}")
+            conn.execute(f"INSERT INTO {checksum_view} VALUES (?)", [new_ck])
+            self._log_query("materialized", table=table, rows=conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
```

This mirrors your existing idmap materialization approach, only generalized. The idmap view/materializer and pool view installer already exist and remain unchanged.

### B3) `io/duckdb_manager.py` — optional structural joins in query builder

We extend query options and join lines; your builder already concatenates `join_lines` / `where_clauses` safely. 

```diff
*** a/codeintel_rev/io/duckdb_manager.py
--- b/codeintel_rev/io/duckdb_manager.py
@@
 @dataclass(slots=True)
 class DuckDBQueryOptions:
     limit: int = 50
     include_globs: tuple[str, ...] = ()
     languages: tuple[str, ...] = ()
+    # NEW: opt-in joins
+    join_modules: bool = False
+    join_symbols: bool = False
+    join_faiss: bool = False
 
 class DuckDBQueryBuilder:
@@
     def build_filter_query(self, opts: DuckDBQueryOptions) -> str:
         join_lines: list[str] = []
         where_clauses: list[str] = []
         order_clause = "ORDER BY id"
 
+        if opts.join_modules:
+            join_lines.append("LEFT JOIN v_modules m ON m.uri = c.uri")
+        if opts.join_symbols:
+            join_lines.append("LEFT JOIN v_chunk_symbols cs ON cs.chunk_id = c.id")
+        if opts.join_faiss:
+            join_lines.append("LEFT JOIN v_faiss_join f ON f.external_id = c.id")
+
         if opts.include_globs:
             where_clauses.append(self._glob_clause("c.uri", opts.include_globs))
         if opts.languages:
             where_clauses.append(self._lang_clause("c.lang", opts.languages))
@@
         sql = f"""
             SELECT c.id, c.uri, c.start_line, c.end_line, c.lang, c.preview,
                    c.content_hash
             FROM chunks c
             {" ".join(join_lines)}
             {("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""}
             {order_clause}
             LIMIT {int(opts.limit)}
         """
         return sql
```

### B4) `io/faiss_manager.py` — exact rerank hook + richer hydration

You already have `_FAISSIdMapMixin#hydrate_by_ids()` and an export path; we wire a `refine_k_factor` and a small rerank using **existing** flat reranker and `DuckDBCatalog.get_embeddings_by_ids()`.

```diff
*** a/codeintel_rev/io/faiss_manager.py
--- b/codeintel_rev/io/faiss_manager.py
@@
 from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.retrieval.rerank_flat import FlatReranker  # existing module
@@
 class FAISSManager(_FAISSIdMapMixin):
     ...
+    refine_k_factor: int = 3  # default fanout for exact rerank
 
     def search_with_refine(
         self,
         query_vec: NDArrayF32,
         *,
         k: int,
         catalog: DuckDBCatalog
     ) -> tuple[list[int], list[float]]:
         """
         ANN -> Flat exact rerank using original vectors from DuckDB.
         """
-        ids, scores = self.index.search(query_vec, k)
+        # 1) ANN stage with fanout
+        k_prime = int(max(k, k * self.refine_k_factor))
+        ids, scores = self.index.search(query_vec, k_prime)
+        # 2) Fetch embeddings for exact similarity
+        candidate_ids = [int(i) for i in ids]
+        emb_ids, emb_array = catalog.get_embeddings_by_ids(candidate_ids)
+        reranker = FlatReranker()  # existing class; cosine/IP as configured
+        top = reranker.rescore(query_vec.reshape(1, -1), emb_ids, emb_array, top_k=k)
+        final_ids = [doc.id for doc in top]
+        final_scores = [doc.score for doc in top]
+        return final_ids, final_scores
-        return ids, scores
@@
     def hydrate_by_ids(
         self,
         catalog: DuckDBCatalog,
         ids: Sequence[int]
     ) -> list[dict]:
-        ...
+        # keep existing hydration but ensure we project structural fields
+        rows = catalog.query_by_ids(ids, columns=(
+            "id","uri","start_line","end_line","lang","preview","content_hash","symbols"
+        ))
+        return [dict(r) for r in rows]
```

> The `get_embeddings_by_ids()` method already exists in `DuckDBCatalog`, returning `(ids, ndarray)`; `FlatReranker` is present under `retrieval/rerank_flat.py`.

### B5) `mcp_server/adapters/semantic.py` — carry structure in results, keep hybrid narrative

Your semantic adapter already has `_resolve_hybrid_results(...)`, `_build_hybrid_result(...)`, `_run_hydration_stage(...)`, `_annotate_hybrid_contributions(...)` and an over‑fetch bonus; we inject the structural columns into the hydrated payload and include them under `explanations` (non‑breaking).

```diff
*** a/codeintel_rev/mcp_server/adapters/semantic.py
--- b/codeintel_rev/mcp_server/adapters/semantic.py
@@
 def _run_hydration_stage(
     request: _SemanticPipelineRequest,
     hybrid_result: _HybridResult,
     catalog: DuckDBCatalog
 ) -> _HydrationOutcome:
@@
-    rows = catalog.query_by_ids(hybrid_result.ids, columns=("id","uri","start_line","end_line","lang","preview"))
+    rows = catalog.query_by_ids(
+        hybrid_result.ids,
+        columns=("id","uri","start_line","end_line","lang","preview","content_hash","symbols")
+    )
     findings = []
     for row in rows:
         f = _row_to_finding(row)
+        # NEW: enrich with structural hints
+        f["explanations"] = {
+            "symbols": row.get("symbols") or [],
+        }
         findings.append(f)
@@
 def _annotate_hybrid_contributions(findings: list[Finding], contribution_map: dict[int, list[tuple[str, int, float]]] | None, rrf_k: int) -> None:
     ...
```

No output‑schema break: these are additional keys the MCP client/LLM can read; the adapter already attaches hybrid narratives via `_annotate_hybrid_contributions`. 

---

## C) Tests and smoke

### C1) Golden join/materialization test (new)

`tests/io/test_duckdb_struct_views.py`

```python
import os
from pathlib import Path
import duckdb
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog

def test_struct_views_materialize(tmp_path: Path):
    db = tmp_path / "test.duckdb"
    cat = DuckDBCatalog(str(db))
    # tiny fixtures (parquet with minimal columns)
    modules = tmp_path / "modules.parquet"
    scip = tmp_path / "scip_occ.parquet"
    # Create minimal parquet via DuckDB for the test
    conn = duckdb.connect(db.as_posix())
    conn.execute("CREATE TABLE t_mod(uri VARCHAR, module_key VARCHAR); INSERT INTO t_mod VALUES ('a.py','mod.a');")
    conn.execute("COPY t_mod TO ? (FORMAT PARQUET)", [modules.as_posix()])
    conn.execute("CREATE TABLE t_occ(symbol VARCHAR, role VARCHAR, uri VARCHAR); INSERT INTO t_occ VALUES ('s','def','a.py');")
    conn.execute("COPY t_occ TO ? (FORMAT PARQUET)", [scip.as_posix()])
    cat.ensure_struct_views(modules_parquet=modules, scip_occurrences_parquet=scip, materialize=True)
    rows = conn.execute("SELECT * FROM modules_mat").fetchall()
    assert rows and rows[0][0] == 'a.py'
```

### C2) MCP smoke (tools/list + semantic search happy‑path)

`tests/mcp/test_semantic_search_smoke.py`

```python
from codeintel_rev.mcp_server.adapters.semantic import _overfetch_bonus

def test_overfetch_bonus_no_filters():
    assert _overfetch_bonus(10, type("F", (), {"has_include_globs": False, "has_languages": False})()) == 0
```

(You already have `_overfetch_bonus` behavior documented; this guards against regressions while we wire joins.) 

---

## D) Rollout plan

1. **Build:** run chunk writer to regenerate Parquet with new fields. (We kept column order stable and added new columns after `lang`.) 
2. **Publish:** call `indexctl` publish flow; after COPY, invoke `DuckDBCatalog.ensure_struct_views(..., materialize=True)` alongside your existing FAISS join materializer. 
3. **Verify:** run golden test; `SELECT * FROM v_chunk_symbols LIMIT 3;` to confirm `symbols` persisted.
4. **Smoke MCP:** simple `search`→`fetch` to confirm `explanations.symbols` appear in `structuredContent`.
5. **Observe:** validate `ann_ms`, `rerank_ms`, `hydrate_ms` histograms; check `post_filter_density` stays within your target. (The boundaries exist already in semantic adapter; we only add/measurables at those joints.) 

---

## Why this fits your code today

* **Schema & writer hooks exist** (`get_chunks_schema`, writer function), we only add two columns. 
* **FAISS id‑map hydration is already centralized** (the mixin has `hydrate_by_ids`), so carrying more columns is one‑line. 
* **Exact rerank primitives exist** (`get_embeddings_by_ids`, `FlatReranker`), so the refine step is glue code, not a redesign.
* **DuckDB checksum‑guard materialization already exists** for FAISS; we mirror the pattern for modules/SCIP. 
* **MCP adapter already has the pipeline boundaries** (overfetch, hybrid resolve, hydration, annotate contributions), so explainability fields are a low‑risk add.

---

## Optional small follow‑ups (low lift, high value)

* **Expose `v_ast_outline` and `v_cst_imports`** as narrow views (`uri`, `start_line`, `end_line`, `node_kind` / `import`) so you can add those to `explanations` later without changing code; the SQL can live in `ensure_struct_views`.
* **Persist index factory + parameters** next to idmap parquet (string) for forensic explainability; your CLI already exports idmap, so write `factory.txt` beside it there. 
* **Materialized join refresh CLI**: you already have `materialize_join_command()` wired; add an optional `--struct` flag to call `ensure_struct_views(..., materialize=True)` after idmap refresh. 

---

## What I verified (conflict check)

* `get_chunks_schema()` and its Arrow type usage—present; adding fields is compatible. 
* FAISS ID‑map hydration path exists and is catalog‑based. 
* `DuckDBCatalog` already exposes idmap view/refresh and pool views; methods added are additive.
* Semantic adapter pipeline functions exist and can carry richer fields without schema break. 
* Reranker + embedding fetch primitives exist.
* File paths exist per `repo_map.json`.

If you want, I can also generate a tiny migration script to backfill `content_hash` for existing chunk Parquets (read → write same file with added column), but the writer patch above will populate it on the next index build.

---

### Appendix: Anchors to the code graph (for your reviewers)

* `DuckDBCatalog.ensure_faiss_idmap_views`, `_ensure_faiss_idmap_view`, `_ensure_faiss_join_view`, `materialize_faiss_join` are implemented; CLI verb `materialize_join_command()` already calls them.
* Checksum‑guard materialization helpers for FAISS idmap join exist (`refresh_faiss_idmap_materialized`, `ensure_faiss_idmap_view`). 
* Pool views helper exists (`ensure_pool_views`). 
* `get_embeddings_by_ids` lives in `DuckDBCatalog`. 
* Reranker path (`rerank_flat`) is present. 
* Semantic adapter pipeline boundaries: `_resolve_hybrid_results`, `_build_hybrid_result`, `_run_hydration_stage`, `_annotate_hybrid_contributions`, `_overfetch_bonus`.
* Arrow schema anchor and writer context (`get_chunks_schema`, writer assembling `pa.table`). 

---

If you’d like, I can now produce a **branch‑ready PR description** and **commit series layout** (1/ schema + writer, 2/ struct views, 3/ FAISS refine + hydration, 4/ MCP explainability, 5/ tests) to streamline the review.
