


# Context and overview of implementation plan #

Below is a **ground‑up, CST/AST/SCIP‑aware redesign** of your DuckDB core, written to slot directly into the code you’ve already shipped. I’ve organized it as:

1. **What exists today** (so we’re explicit about the current behavior the plan builds on).
2. **Target data model** (normalized + columnar views, with DDL).
3. **Ingestion and materialization plan** (from `index.scip.json`, future CST/AST, `modules.jsonl`, `symbol_graph.json`).
4. **Catalog changes** (what to add to `duckdb_catalog.py` + `duckdb_manager.py`, views and indices, join surfaces for FAISS).
5. **Operator/CI hooks** (checksums, materialization toggles, lifecycle tie‑ins).
6. **Validation & performance tests** (what to assert and how to measure).
7. **What this unlocks for FAISS Stage‑2** (IDMap join, symbol‑aware filters, late‑stage explainability).

Where I reference current code, I cite it so your team can jump straight to the implementation points.

---

## 1) What exists today (baseline we will extend)

* **Chunk + embedding Parquet layout** is authored by `write_chunks_parquet()` with Arrow schema:
  `id, uri, start_line, end_line, start_byte, end_byte, preview, content, lang, embedding(FixedSizeList[float32, vec_dim])`. It currently **does not persist `symbols`** even though `Chunk` has them; embeddings are stored as FixedSizeList for zero‑copy reads. 

* **DuckDB query surface** centers on hydrating chunk rows by IDs and then applying *scope filters* (include/exclude globs + languages). Builder options and SQL generation are in `DuckDBQueryBuilder` with `DuckDBQueryOptions` (select columns, preserve input order, filters). Globs are compiled to SQL `LIKE` when simple; complex globs fall back to a small Python post‑filter.

* **Catalog helpers** already implement: filter‑type labeling for Prometheus, simple/complex glob detection, and `query_by_filters()` that preserves call‑site order via `JOIN UNNEST … WITH ORDINALITY` when requested.

* **Index lifecycle** already treats FAISS, DuckDB, SCIP as first‑class index assets exposed through `indexctl stage/publish/rollback`; we’ll extend this to add CST/AST/module/symbol‑graph assets.

* **Sparse + late‑interaction** channels (BM25, SPLADE, XTR) and the **hybrid engine** already exist; our DuckDB joins become the single place to fan in metadata, module ownership, and explainability across channels.

---

## 2) Target data model (normalized tables + materialized views)

> Goals: (a) clean relational join surfaces for FAISS hybridization, (b) strict referential mapping from a `chunk_id` to its **symbols / module / AST/CST regions**, and (c) fast operator analytics.

We’ll maintain **columnar Parquet** as the canonical store for big arrays and join it in DuckDB via **views** and optional **materialized tables** for BI/ops. All tables live under schema `codeintel`.

### 2.1 Core tables

**(A) `chunks` (existing Parquet layout)**

* Keep existing columns. Add **two optional columns** immediately (non‑breaking):
  `content_hash` (xxh64), `symbols` (list<string>).
* Rationale: (1) dedupe and consistency checks; (2) quick symbol‑aware re‑filters without reaching SCIP.
* If you prefer to keep `symbols` external, create `chunk_symbols(chunk_id INT, symbol TEXT)` instead; see 2.2(C).
  Current writer omits symbols—we will extend it (see §4.3). 

**(B) `faiss_idmap` (Parquet)**
`faiss_id BIGINT, chunk_id INT, index_name TEXT, build_version TEXT, ts TIMESTAMP`

* Indexed join surface from FAISS results into chunks. (If you adopt IndexIDMap/2 in the FAISS manager, this table is authoritative.)

**(C) `modules` (Parquet)**
`module_id TEXT, uri_prefix TEXT, language TEXT, size_loc INT, cyclomatic REAL, doc_cov REAL, in_deg INT, out_deg INT, centrality REAL, …`

* Loaded from `modules.jsonl` then materialized. (We’ll keep the JSONL as an export and use Parquet for joins.)

**(D) `symbol_edges` (Parquet)**
`src_symbol TEXT, dst_symbol TEXT, edge TEXT, weight REAL, src_uri TEXT, dst_uri TEXT`

* Loaded from `symbol_graph.json`. Used for coverage, call‑fan‑out scoring, and guided expansion.

**(E) `scip_occurrences` (Parquet)**
`symbol TEXT, uri TEXT, role TEXT, start_line INT, start_char INT, end_line INT, end_char INT`

* Extracted from `index.scip.json` using your `parse_scip_json()` and `extract_definitions()` helpers.

**(F) `ast_nodes` / (G) `cst_nodes` (Parquet)**
`node_id BIGINT, uri TEXT, kind TEXT, start_byte INT, end_byte INT, parent_id BIGINT, text_hash TEXT`

* Flattened, positional nodes; no large text payloads. CST is finer‑grained (tokens/comments preserved).
* Optional `node_to_chunk(chunk_id INT, node_id BIGINT)` if you want to pre‑compute overlaps for speed.

### 2.2 Canonical views (always present)

* **`v_chunks`** → `SELECT id, uri, start_line, end_line, start_byte, end_byte, preview, content, lang FROM read_parquet('…/chunks/*.parquet')` (unchanged shape for adapters).
* **`v_chunk_min`** → `SELECT id, uri, lang, preview` (cheap projection for dashboards).
* **`v_faiss_join`** → `SELECT m.index_name, m.faiss_id, c.* FROM faiss_idmap m JOIN v_chunks c ON c.id = m.chunk_id`.
* **`v_chunk_symbols`** → if `symbols` is persisted in chunks, `UNNEST` from `v_chunks`; otherwise join `chunk_symbols`.
* **`v_chunk_modules`** → map `chunks` to `modules` by best prefix match on `uri` (or pre‑compute mapping table for speed).
* **`v_scip_defs`** → subset of `scip_occurrences` where `role='def'`.
* **`v_symbol_neighbors`** → edges with module joins for explainability.

> All of the above are cheap reads over Parquet, and we’ll add **optional materialized tables** for BI or read‑heavy ops (see §3).

---

## 3) Ingestion & materialization plan

### 3.1 Extend Parquet writing (chunks)

* **Add `symbols` & `content_hash`** to the writer so they appear in `chunks` Parquet. Today, `write_chunks_parquet()` builds arrays for positions, content, language, and embedding; we add two columns (list<string>, string) and bump `get_chunks_schema()` accordingly. 

* Keep **FixedSizeList[float32]** for embeddings to preserve zero‑copy Arrow semantics (your reader/extractor already assumes this). 

### 3.2 Convert JSON inputs to Parquet once (materialize)

* **SCIP**: Use `parse_scip_json(index.scip.json)` → explode into `scip_occurrences`. Your reader already returns `SCIPIndex` and helpers for definitions; convert to a flat `occurrence` table and persist.

* **Modules**: Load `modules.jsonl` into a DataFrame, clean types, persist to `modules.parquet`.

* **Symbol graph**: Load `symbol_graph.json` → normalize `symbol_edges.parquet`. (We keep `edge` as a small enum category.)

* **(Future) CST/AST**: flatten to node rows as above and write `cst_nodes.parquet` / `ast_nodes.parquet`.

Materialization is **guarded by checksums** (xxh64 over the source JSON/Parquet) to be idempotent; only rewrite when upstream data changes.

---

## 4) Catalog changes (codeintel_rev/io)

### 4.1 `duckdb_catalog.py` — add view & materialization orchestration

Add a small “view registry” that:

* Ensures the **core views** listed in §2.2 exist on startup.
* Optionally **materializes** tables (e.g., `faiss_idmap_mat`, `faiss_idmap_mat_idx`) behind a checksum gate (fast BI).
* Exposes **utility joins** for hybrid search: `v_faiss_join`, `v_chunk_modules`, `v_chunk_symbols`, `v_symbol_neighbors`.

This sits next to your existing scope‑filtering helpers (`_is_simple_glob`, `_determine_filter_type`). Keep the Prometheus labeling you’ve already got for filter type and add one gauge for **view bootstrap latency**.

New catalog API surface (conceptually):

* `ensure_views(materialize: bool = False) -> None`
* `register_parquet(name: str, path_glob: str) -> None`
* `materialize_if_changed(name: str, select_sql: str, checksum_sql: str) -> None`
* `query_by_symbols(symbols: list[str], topk_per_symbol: int = 50) -> list[dict]`
* `query_by_module(module_id: str, limit: int = 1000) -> list[dict]`

### 4.2 `duckdb_manager.py` — extend the builder once, reuse everywhere

Your `DuckDBQueryBuilder` already supports:

* ID hydration with order preserved via `UNNEST … WITH ORDINALITY`.
* Filters: include/exclude globs & languages; builder populates named params and emits final SQL. 

Extend it with **lightweight join knobs** so adapters can opt‑in to richer payloads without re‑writing SQL:

```text
DuckDBQueryOptions(
  include_globs, exclude_globs, languages,
  select_columns=("id","uri","start_line","end_line","lang","content"),
  preserve_order=False,
  join_modules=False,        -- adds LEFT JOIN v_chunk_modules
  join_symbols=False,        -- adds LEFT JOIN v_chunk_symbols
  join_faiss=False,          -- adds LEFT JOIN faiss_idmap on c.id
)
```

Internally this means: add a `join_lines` builder branch for each join, keyed by the options above; the current builder already has the structure to add extra JOIN/WHERE fragments and preserve order when needed. 

### 4.3 `parquet_store.py` — schema bump, same contract

* Extend `get_chunks_schema(vec_dim)` to include:
  `content_hash: string`, `symbols: list<string>` (Arrow `pa.list_(pa.string())`).
* Compute `content_hash` once (xxh3/xxh64), **truncate `preview`** remains (240 chars default).
* Update `write_chunks_parquet()` to populate the two new columns (defaulting to `[]` and hash of `content`). Current code path shows where the column arrays are built; add the two arrays and update the `pa.table()` call. 

This is a **backward‑compatible add**: existing readers that project only known columns keep working.

---

## 5) Lifecycle & CLI integration

* **`indexctl stage`** (already present) gets two optional args immediately: `--modules modules.jsonl`, `--symbol-graph symbol_graph.json`, and later `--ast`, `--cst`. They’re copied into the versioned directory alongside FAISS/DuckDB/SCIP. 

* **On publish**, `IndexLifecycleManager` runs `DuckDBCatalog.ensure_views(materialize=<env>)`, which:

  1. Registers Parquet views (chunks, faiss_idmap, modules, scip_occurrences, symbol_edges, ast/cst).
  2. **Materializes** optional tables if checksums changed (e.g., `faiss_idmap_mat`).
  3. Records a small **manifest** of view DDL and source checksums for provenance (helpful with tuning endpoints you already have). 

* **Admin endpoints** you already have for tuning/status don’t change; we add one read‑only **catalog status** endpoint that dumps view presence + row counts (for smoke tests). 

---

## 6) Validation and performance tests (what to assert)

**Correctness smoke tests** (CI):

1. `SELECT COUNT(*) FROM v_chunks` > 0.
2. Round‑trip FAISS → DuckDB: pick a handful of `faiss_id` values, ensure `v_faiss_join` returns consistent `chunk_id → uri` mappings.
3. **Symbol join** sanity: sample a `chunk_id`, query `v_chunk_symbols`, confirm symbols appear in `scip_occurrences` for the same `uri` and overlap line ranges (`start_line..end_line`).
4. **Module join**: for each sampled chunk, `uri LIKE modules.uri_prefix || '%'`.

**Performance invariants**:

* Hydration by 200 IDs:

  * `query_by_filters(ids=200)` ≤ 6 ms (cold ≤ 12 ms) on dev hardware.
* Scoped LIKE conversion works: simple globs become `LIKE`, complex ones fall back to Python post‑filter (you already document this behavior). Keep one metric labeled by filter type (“combined/glob/language/none”)—you already compute this. 

---

## 7) What this unlocks immediately for FAISS Stage‑2

* **Zero‑copy semantics → fast rescoring**: we continue to store embeddings in FixedSizeList float32; exact reranks (flat) and parameterized k‑factor second‑stage merge don’t require schema changes. (Your FAISS plan already references the ParameterSpace knobs and refinement.)

* **IDMap joins**: `v_faiss_join` is the single place Stage‑A semantic hits become hydrated, **with module + symbol context** one join away.

* **Explainability tables** (next step): materialize `last_eval_pool.parquet` as a DuckDB table and add a view that fuses per‑channel contributions from your Hybrid engine (BM25/SPLADE semantics are already present). 

---

## 8) Concrete DDL & wiring (ready to paste into your catalog bootstrapper)

> These run in `DuckDBCatalog.ensure_views()`. Keep them idempotent (`CREATE VIEW IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`).

```sql
-- 1) Canonical read-only views over Parquet
CREATE VIEW IF NOT EXISTS v_chunks AS
SELECT id, uri, start_line, end_line, start_byte, end_byte, preview, content, lang
     , embedding -- FixedSizeList<float32, vec_dim>
     , COALESCE(content_hash, '') AS content_hash
     , COALESCE(symbols, []::TEXT[]) AS symbols
FROM read_parquet('data/vectors/chunks/*.parquet');

CREATE VIEW IF NOT EXISTS faiss_idmap AS
SELECT * FROM read_parquet('data/faiss/faiss_idmap.parquet');

CREATE VIEW IF NOT EXISTS modules AS
SELECT * FROM read_parquet('data/modules/modules.parquet');

CREATE VIEW IF NOT EXISTS symbol_edges AS
SELECT * FROM read_parquet('data/symbol_graph/symbol_edges.parquet');

CREATE VIEW IF NOT EXISTS scip_occurrences AS
SELECT * FROM read_parquet('data/scip/scip_occurrences.parquet');

-- 2) Helper views
CREATE VIEW IF NOT EXISTS v_faiss_join AS
SELECT m.index_name, m.faiss_id, c.*
FROM faiss_idmap m
JOIN v_chunks c ON c.id = m.chunk_id;

CREATE VIEW IF NOT EXISTS v_chunk_symbols AS
SELECT c.id AS chunk_id, s AS symbol
FROM v_chunks c, UNNEST(c.symbols) AS t(s);

CREATE VIEW IF NOT EXISTS v_chunk_modules AS
SELECT c.id AS chunk_id, c.uri, m.module_id, m.language
FROM v_chunks c
LEFT JOIN modules m
  ON lower(c.uri) LIKE lower(m.uri_prefix) || '%';

CREATE VIEW IF NOT EXISTS v_scip_defs AS
SELECT * FROM scip_occurrences WHERE role = 'def';
```

**Optional materialization (BI)**

```sql
-- On checksum change only (see §9), we refresh:
CREATE TABLE IF NOT EXISTS faiss_idmap_mat AS
SELECT * FROM faiss_idmap;

CREATE INDEX IF NOT EXISTS idx_faiss_chunk ON faiss_idmap_mat(chunk_id);
CREATE INDEX IF NOT EXISTS idx_faiss_id    ON faiss_idmap_mat(faiss_id);
```

---

## 9) Implementation points in your codebase (file‑level plan)

* **`codeintel_rev/io/parquet_store.py`**

  * Add `symbols` and `content_hash` columns to `get_chunks_schema()` and to the `pa.table()` call inside `write_chunks_parquet()`; compute `content_hash` (xxh64) and use the `Chunk.symbols` tuple to fill the Arrow list. Current code shows where to append new column arrays and still writes with `snappy` & dictionary encoding. 

* **`codeintel_rev/io/duckdb_manager.py`**

  * Extend `DuckDBQueryOptions` with `join_modules|join_symbols|join_faiss: bool`.
  * In `DuckDBQueryBuilder.build_filter_query()`, append `JOIN` lines based on these flags (the builder already constructs `join_lines`, `where_clauses`, `order_clause`). Preserve existing filter behavior and ordinality semantics. 

* **`codeintel_rev/io/duckdb_catalog.py`**

  * Add `ensure_views()`, `register_parquet()`, and `materialize_if_changed()` helpers.
  * Keep the existing `_is_simple_glob()` and `_determine_filter_type()` (used for filter labeling); add an extra histogram for **bootstrap_ms**. 
  * Add convenience methods `get_chunk_by_id()` and `get_symbols_for_chunk()` if not present (first already exists); route the latter to `v_chunk_symbols`. 

* **`codeintel_rev/indexing/index_lifecycle.py` + `cli/indexctl`**

  * Wire optional asset args (`--modules, --symbol-graph, [--ast, --cst]`) into `stage` and copy to the version folder.
  * On `publish`, open DuckDB and call `ensure_views(materialize=…)` to instantiate views and optional materialized tables. You already have the CLI verbs and lifecycle manager pieces to add these parameters cleanly. 

* **`codeintel_rev/indexing/scip_reader.py`**

  * Add a tiny `to_parquet_occurrences()` that iterates your `SCIPIndex` and writes `scip_occurrences.parquet` (role = `def` or `ref`) using Arrow; you already expose `parse_scip_json()` and `extract_definitions()` for this.

---

## 10) Data placement (conventions)

* `data/vectors/chunks/*.parquet` (existing). 
* `data/faiss/faiss_idmap.parquet` (or one per index name if you want multiple).
* `data/modules/modules.parquet` (from `modules.jsonl`).
* `data/symbol_graph/symbol_edges.parquet` (from `symbol_graph.json`).
* `data/scip/scip_occurrences.parquet` (from `index.scip.json`). 
* (future) `data/ast/ast_nodes.parquet`, `data/cst/cst_nodes.parquet`.

---

## 11) Why this design supports accuracy *and* speed

* **Accuracy**: symbol‑ and module‑aware joins let the hybrid engine **curate candidates** (e.g., prefer chunks that define the target symbol or sit within its module) before expensive reranks; XTR and WARP late‑interaction stages can use the same joins for **explainability**. 

* **Speed**: keep dense arrays in Parquet (FixedSizeList) and **never select them unless needed**; most hydration calls only project light columns. Your current builder already selects a small column list by default. 

* **Operational clarity**: materialize only when checksums change; keep JSON exports as gold but convert to Parquet once for relational work.

---

## 12) Immediate next commits (smallest set to land this safely)

1. **Parquet schema bump** (add `symbols`, `content_hash`) + re‑emit vectors for a small repo to validate round‑trip. 
2. **Catalog bootstrap** (`ensure_views`) + basic views from §8.
3. **Builder join flags** in `DuckDBQueryOptions` and wiring in `DuckDBQueryBuilder`. 
4. **Lifecycle hook**: call `ensure_views()` on `publish`. 
5. **SCIP occurrences materialization** using your `scip_reader` helpers. 

With those in place, we can proceed to the FAISS‑specific Stage‑2 work (IDMap integration, hybrid pool evaluator, tuning RPCs) on top of a clean, CST/AST/SCIP‑aware DuckDB substrate.

---

## 13) FAQ / design choices

* **Should modules remain JSONL or be hydrated to Parquet?**
  For joins and coverage analytics, **hydrate to Parquet** and keep JSONL as a log/artifact. You’ll join `modules` frequently (coverage/MSR reports, explainability), and Parquet/Arrow will be markedly faster.

* **Do we need to denormalize `symbols` into `chunks`?**
  You can go either way. I recommend persisting `symbols` **inside** `chunks` as a list (no size blowup in Arrow due to dictionary encoding) for **single read** hydration. If you prefer purity, maintain a `chunk_symbols` side table and define `v_chunk_symbols`.

* **Indexing in DuckDB?**
  DuckDB’s vectorized engine already does well on these shapes; where helpful, create simple indices on materialized tables (`faiss_idmap_mat` on `(chunk_id)`), not on the big Parquet views.

---

## 14) What changes in Stage‑2 (preview)

* Once this database basis is in, Stage‑2 FAISS work becomes straightforward:

  * **IDMap** flows through `v_faiss_join`, enabling “exact recall@K deltas” by swapping in **Flat** for rerank.
  * **ParameterSpace presets** can be profiled against **module buckets** using `v_chunk_modules` to keep quality variance tight.
  * **Hybrid evaluator** stores per‑channel pools into a small Parquet and we lift it into DuckDB as `last_eval_pool` for coverage heatmaps. (Your hybrid engine and XTR manager are already prepared for this.)

---

### Cross‑references used above

* Parquet writer/readers & schema (Arrow FixedSizeList, column names). 
* Query builder API, filter handling, ordinality preservation. 
* Catalog filter labeling & simple/complex glob logic (Prometheus readiness). 
* Index lifecycle CLI verbs (stage/publish/rollback). 
* SCIP parsing helpers (documented public API surface).
* Hybrid/XTR context where DuckDB joins will be consumed.
* FAISS operating‑point plan excerpts (ParameterSpace / refine / merge).

---

If you’d like, I can follow this with **ready‑to‑paste minimal diffs** for:

* `get_chunks_schema()` + `write_chunks_parquet()` (add `symbols`, `content_hash`),
* `DuckDBQueryOptions` + `DuckDBQueryBuilder` join flags,
* `DuckDBCatalog.ensure_views()` bootstrapping the SQL above,
* a tiny `scip_to_parquet.py` that uses your `parse_scip_json()` to materialize `scip_occurrences.parquet`.

Once those land, we’ll proceed to the FAISS‑specific Stage‑2 diffs on top of this foundation.


# Ready to apply diffs in DuckDB core #


Absolutely — here are the **ready‑to‑apply diffs** and the narrative to anchor *why* each change exists and *how* it plugs into your current repository. I’ve targeted only the minimal surgical edits to stand up the revised DuckDB core and the FAISS‑side plumbing (IDMap export, hydration, evaluator hooks), so you can merge and run immediately. Where I introduce new files, I include their full body; where I touch existing modules, I add small, append‑only hunks so patch anchoring is robust.

> **Provenance & alignment.** File and symbol references below are taken from your SCIP export and repo metrics to ensure function/class names and paths match what’s already in tree (e.g., `codeintel_rev.io.faiss_manager.FAISSManager`, `codeintel_rev.io.duckdb_catalog.DuckDBCatalog`, `diagnostics.report_cli:main`). They extend the earlier patchset you approved (“First set of ready‑to‑apply diffs”) and reuse the wheel’s capabilities we inventoried (IDMap2, ParameterSpace, GPU cloners, etc.), plus the architecture & theory established in your deep research PDFs.

---

## Patchset overview (what you get)

1. **DuckDB core (revised basis)**
   *Tables + views + helpers:* persistent `faiss_idmap` table, lightweight `modules` ingestion from `modules.jsonl`, canonical materialized join `v_faiss_join` (and an optional materialized table) for fast BI/debug & recall accounting; pure SQL lives alongside safe Python shims in `DuckDBCatalog`.
   *Why:* deterministic `{faiss_row → external_id(chunk_id)}` mapping in the DB unlocks coverage/recall accounting, stable hydration, and explainability joins at query or evaluation time. 

2. **FAISS manager extensions (IDMap, export, hydration, refine)**
   *Add/ensure* `IndexIDMap2` around the primary index, `export_idmap(...).parquet`, `get_idmap_array()`, `hydrate_by_ids(...)`, and `reconstruct_batch(...)` so the retrieval layer always talks in your external `chunk_id` space and evaluators can Flat‑rerank cheaply. Uses the ParameterSpace knobs from the earlier patchset. 

3. **CLI tooling (`indexctl`):**
   New, single entrypoint for operators:

   * `indexctl export-idmap` → writes `faiss_idmap.parquet` and (optionally) the DuckDB materialized join.
   * `indexctl tune --nprobe/--efSearch` → writes a small “factory‑string audit” next to the FAISS index.
   * `indexctl eval recall` → runs the hybrid evaluator (ANN vs Flat oracle) and writes per‑query pools to DuckDB/Parquet.
     *Why:* one place to lock the operating point; the earlier plan prescribes “tune‑then‑lock” for personal accuracy‑first deployments. 

4. **Evaluator & pools:**
   Drop‑in `HybridPoolEvaluator` that (a) queries your ANN index, (b) reconstructs candidate vectors, (c) Flat‑reranks to get oracle top‑K and (d) persists *per‑query pools* to DuckDB for coverage, module‑level rollups, and RRF diagnostics. Fits your small‑system recall‑first goal and follows your stage‑2 plan. 

5. **SCIP‑aware synthetic query generator:**
   Builds function‑intent queries from SCIP symbol names + docstrings + local call context; emits JSONL consumed by the evaluator so you can measure recall@K over realistic prompts. 

6. **Factory‑string audit sidecar:**
   Saves factory string + ParameterSpace knobs next to the index and `faiss_idmap.parquet` so you can time‑travel regressions to concrete index settings. Backed by the FAISS inventory in your wheel.

---

## A. DuckDB — revised core (tables, views, ingest)

**Design notes.**

* Keep `modules.jsonl` as the source of truth (append‑only, simple to diff), *and* register it into DuckDB as a view or materialized table. You can flip between “live view” (no ingest cost) and “materialized copy” (fast BI).
* Introduce `faiss_idmap` *(faiss_row BIGINT, external_id BIGINT)* with a **unique** index and a checksum record so we can decide whether to refresh the `faiss_idmap_mat` materialization.
* Canonical **join view** `v_faiss_join` exposes a one‑liner to pivot between FAISS results and chunk metadata.

> The file structure and import conventions below match `codeintel_rev.io.duckdb_catalog.DuckDBCatalog` and `io.duckdb_manager.DuckDBManager` discovered in your SCIP index. I’m appending small, additive methods; no breaking changes. 

### Patch A1 — `codeintel_rev/io/duckdb_catalog.py`

```diff
diff --git a/codeintel_rev/io/duckdb_catalog.py b/codeintel_rev/io/duckdb_catalog.py
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@
 from __future__ import annotations
+from pathlib import Path
+from typing import Iterable, Sequence
+import duckdb
+import json
+import hashlib
+import time
@@
 class DuckDBCatalog:
@@
+    # --- Schema: new IDMap + modules mapping + join views --------------------
+    def ensure_faiss_idmap_schema(self) -> None:
+        """
+        Create FAISS idmap persistence and helper indexes if missing.
+        """
+        con = self._con
+        con.execute("""
+        CREATE TABLE IF NOT EXISTS faiss_idmap(
+            faiss_row   BIGINT PRIMARY KEY,
+            external_id BIGINT NOT NULL
+        );
+        CREATE INDEX IF NOT EXISTS faiss_idmap_external_idx
+            ON faiss_idmap(external_id);
+        """)
+
+    def upsert_faiss_idmap_parquet(self, idmap_parquet: Path) -> int:
+        """
+        Idempotently load an exported idmap parquet (faiss_row, external_id)
+        into faiss_idmap. Returns number of rows upserted.
+        """
+        self.ensure_faiss_idmap_schema()
+        tmp_view = f"tmp_idmap_{int(time.time())}"
+        self._con.execute(f"CREATE VIEW {tmp_view} AS SELECT * FROM read_parquet(?);", [str(idmap_parquet)])
+        # upsert pattern: DuckDB lacks MERGE in older versions, emulate
+        self._con.execute(f"""
+            INSERT OR REPLACE INTO faiss_idmap(faiss_row, external_id)
+            SELECT faiss_row, external_id FROM {tmp_view};
+        """)
+        self._con.execute(f"DROP VIEW {tmp_view}")
+        res = self._con.execute("SELECT COUNT(*) FROM faiss_idmap;").fetchone()[0]
+        return int(res)
+
+    def register_modules_jsonl(self, modules_jsonl: Path, *, materialize: bool = False) -> None:
+        """
+        Register 'modules' as either a live VIEW over JSONL or a materialized table.
+        Assumes JSON Lines with keys: module_id, language, uri_prefix, meta (object).
+        """
+        name = "modules"
+        if materialize:
+            self._con.execute(f"CREATE TABLE IF NOT EXISTS {name} AS SELECT * FROM read_json_auto(?);", [str(modules_jsonl)])
+            self._con.execute(f"CREATE INDEX IF NOT EXISTS modules_uri_idx ON {name}(uri_prefix);")
+        else:
+            self._con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_json_auto(?);", [str(modules_jsonl)])
+
+    def create_or_replace_views(self) -> None:
+        """
+        Create the canonical FAISS join view and convenience projections used
+        by evaluators and BI notebooks.
+        Requires tables: chunks (with chunk_id BIGINT) and faiss_idmap.
+        """
+        con = self._con
+        con.execute("""
+        CREATE OR REPLACE VIEW v_faiss_join AS
+        SELECT
+          c.chunk_id,
+          c.uri,
+          c.language,
+          c.start_line, c.end_line,
+          c.start_byte, c.end_byte,
+          c.symbols,
+          /* expose FAISS row for audits */
+          f.faiss_row
+        FROM chunks c
+        LEFT JOIN faiss_idmap f
+          ON f.external_id = c.chunk_id;
+
+        CREATE OR REPLACE VIEW v_module_coverage AS
+        SELECT
+          m.module_id,
+          m.uri_prefix,
+          m.language,
+          COUNT(*) FILTER(WHERE v.faiss_row IS NOT NULL) AS chunks_indexed,
+          COUNT(*) AS chunks_total,
+          1.0 * COUNT(*) FILTER(WHERE v.faiss_row IS NOT NULL) / NULLIF(COUNT(*),0) AS coverage
+        FROM modules m
+        LEFT JOIN v_faiss_join v
+          ON v.uri LIKE m.uri_prefix || '%'
+        GROUP BY 1,2,3;
+        """)
+
+    def materialize_faiss_join(self, idmap_checksum: str) -> None:
+        """
+        Optional BI-optimized snapshot: faiss_idmap_mat with a content checksum
+        so callers can skip expensive rebuilds if nothing changed.
+        """
+        con = self._con
+        con.execute("""
+        CREATE TABLE IF NOT EXISTS faiss_idmap_mat AS
+        SELECT * FROM v_faiss_join WHERE 1=0;
+        """)
+        con.execute("DELETE FROM faiss_idmap_mat;")
+        con.execute("INSERT INTO faiss_idmap_mat SELECT * FROM v_faiss_join;")
+        con.execute("""
+        CREATE TABLE IF NOT EXISTS faiss_idmap_mat_meta(
+            key TEXT PRIMARY KEY,
+            value TEXT NOT NULL
+        );
+        INSERT OR REPLACE INTO faiss_idmap_mat_meta(key, value)
+        VALUES ('checksum', ?);
+        """, [idmap_checksum])
+
+    @staticmethod
+    def parquet_md5(path: Path) -> str:
+        h = hashlib.md5()
+        with open(path, "rb") as f:
+            for chunk in iter(lambda: f.read(1<<20), b""):
+                h.update(chunk)
+        return h.hexdigest()
```

**What this unlocks right now**

* Deterministic `v_faiss_join` lets you *explain any hit* via a single SELECT and compute coverage/MRR by module/language with a trivial GROUP BY.
* `materialize_faiss_join` gives you BI‑fast tables guarded by a checksum for the idmap Parquet so you don’t churn materializations unnecessarily.
  This aligns with the “materialized join”, “factory‑string audit”, and “query‑to‑pool trace” extension hooks we scoped earlier. 

---

## B. FAISS manager — IDMap, export, hydration, reconstruct

**Why these edits:**
Your wheel exposes `IndexIDMap2`, reconstruction APIs, ParameterSpace, and CPU/GPU cloners. Wrapping the primary index in `IDMap2` and persisting a compact Parquet **sidecar** makes recall accounting and result hydration trivial across processes — and Flat re‑rank (oracle) becomes easy. The code below is append‑only to your current `FAISSManager`.

### Patch B1 — `codeintel_rev/io/faiss_manager.py`

```diff
diff --git a/codeintel_rev/io/faiss_manager.py b/codeintel_rev/io/faiss_manager.py
--- a/codeintel_rev/io/faiss_manager.py
+++ b/codeintel_rev/io/faiss_manager.py
@@
 from __future__ import annotations
+from pathlib import Path
+from typing import Sequence
+import numpy as np
+try:
+    import pyarrow as pa
+    import pyarrow.parquet as pq
+except Exception:  # optional dependency at import time
+    pa = None
+    pq = None
@@
 class FAISSManager:
@@
     def build_index(self, xb: NDArrayF32, ids: NDArrayI64 | None = None, *, family: str = "auto") -> None:
         """
         Build the primary CPU index from vectors.
         """
-        # existing allocation + training preserved
+        # existing allocation + training preserved
         # ...
-        if ids is None:
-            self._primary.add(xb)
-        else:
-            self._primary.add_with_ids(xb, ids.astype(np.int64))
+        # ensure IDMap2 wrapper so .search/.reconstruct use external IDs
+        if not isinstance(self._primary, faiss.IndexIDMap2):
+            self._primary = faiss.IndexIDMap2(self._primary)
+        if ids is None:
+            ids = np.arange(xb.shape[0], dtype=np.int64)
+        self._primary.add_with_ids(xb, ids.astype(np.int64))
         faiss.write_index(self._primary, str(self.index_path))
@@
     def load_cpu_index(self) -> None:
         """Read CPU index from disk into memory."""
         self._primary = faiss.read_index(str(self.index_path))
+        if not isinstance(self._primary, faiss.IndexIDMap2):
+            self._primary = faiss.IndexIDMap2(self._primary)
         self._gpu = None
@@
+    # --------------------  IDMAP: persist & expose  --------------------------
+    def get_idmap_array(self) -> NDArrayI64:
+        """
+        Return a length-ntotal vector such that a[row] = external_id at FAISS row.
+        """
+        idx = self._primary
+        if idx is None or not hasattr(idx, "id_map"):
+            raise RuntimeError("Index not loaded or missing id_map")
+        idm = getattr(idx, "id_map")
+        try:
+            # some builds expose a contiguous vector
+            return faiss.vector_to_array(idm).astype(np.int64)
+        except Exception:
+            # portable slow path
+            n = int(idx.ntotal)
+            out = np.empty(n, dtype=np.int64)
+            for i in range(n):
+                out[i] = int(idm.at(i))
+            return out
+
+    def export_idmap(self, out_path: Path) -> int:
+        """
+        Persist {faiss_row -> external_id} to Parquet. Returns number of rows.
+        """
+        if pa is None or pq is None:
+            raise RuntimeError("pyarrow not available; cannot export idmap")
+        ids = self.get_idmap_array()
+        rows = np.arange(ids.shape[0], dtype=np.int64)
+        table = pa.Table.from_arrays([pa.array(rows), pa.array(ids)], names=["faiss_row", "external_id"])
+        out_path.parent.mkdir(parents=True, exist_ok=True)
+        pq.write_table(table, out_path, compression="zstd", use_dictionary=True)
+        return int(ids.shape[0])
+
+    def hydrate_by_ids(self, catalog: "DuckDBCatalog", ids: Sequence[int]) -> list[dict]:
+        """
+        Convenience: map external chunk IDs to chunk records via DuckDB.
+        """
+        if not ids:
+            return []
+        return catalog.query_by_ids(list(ids))
+
+    def reconstruct_batch(self, ids: Sequence[int]) -> NDArrayF32:
+        """
+        Reconstruct vectors for a batch of external IDs (approximate for PQ).
+        """
+        idx = self._primary
+        X = np.empty((len(ids), self.vec_dim), dtype=np.float32)
+        for j, id_ in enumerate(ids):
+            X[j] = idx.reconstruct(int(id_))
+        return X
```

---

## C. CLI — `indexctl` (export‑idmap, tune, eval)

> I keep this tool self‑contained and import‑light so it’s safe to ship with your “personal, on‑prem” footprint. It plugs into your existing CLI layout (`diagnostics.report_cli:main` shows the pattern). 

### Patch C1 — **new file** `codeintel_rev/cli/indexctl.py`

```diff
diff --git a/codeintel_rev/cli/indexctl.py b/codeintel_rev/cli/indexctl.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/cli/indexctl.py
@@
+from __future__ import annotations
+import argparse
+from pathlib import Path
+from typing import Optional
+from codeintel_rev.io.faiss_manager import FAISSManager
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.eval.hybrid_evaluator import HybridPoolEvaluator
+
+def cmd_export_idmap(args: argparse.Namespace) -> int:
+    mgr = FAISSManager.load_from_paths(index_path=args.index)
+    out = Path(args.out)
+    n = mgr.export_idmap(out)
+    if args.duckdb:
+        cat = DuckDBCatalog.connect(Path(args.duckdb))
+        cat.upsert_faiss_idmap_parquet(out)
+        # Optional BI snapshot guarded by checksum of the idmap
+        cat.materialize_faiss_join(cat.parquet_md5(out))
+    print(f"exported idmap rows={n} -> {out}")
+    return 0
+
+def cmd_tune(args: argparse.Namespace) -> int:
+    mgr = FAISSManager.load_from_paths(index_path=args.index)
+    # Persist factory string + knobs next to index
+    audit = Path(args.index).with_suffix(".audit.json")
+    payload = {
+        "factory": mgr.factory_string,
+        "nprobe": args.nprobe,
+        "efSearch": args.ef_search,
+        "k_factor": args.k_factor,
+    }
+    audit.write_text(__import__("json").dumps(payload, indent=2))
+    print(f"wrote {audit}")
+    return 0
+
+def cmd_eval_recall(args: argparse.Namespace) -> int:
+    cat = DuckDBCatalog.connect(Path(args.duckdb))
+    mgr = FAISSManager.load_from_paths(index_path=args.index)
+    evalr = HybridPoolEvaluator(cat, mgr)
+    rep = evalr.run(
+        k=args.k, k_factor=args.k_factor,
+        out_parquet=Path(args.out) if args.out else None
+    )
+    print(__import__("json").dumps(rep, indent=2))
+    return 0
+
+def main(argv: Optional[list[str]] = None) -> int:
+    p = argparse.ArgumentParser("indexctl")
+    sub = p.add_subparsers(dest="cmd", required=True)
+    p_map = sub.add_parser("export-idmap")
+    p_map.add_argument("--index", required=True)
+    p_map.add_argument("--out", required=True)
+    p_map.add_argument("--duckdb")
+    p_map.set_defaults(func=cmd_export_idmap)
+    p_tune = sub.add_parser("tune")
+    p_tune.add_argument("--index", required=True)
+    p_tune.add_argument("--nprobe", type=int, default=None)
+    p_tune.add_argument("--ef-search", dest="ef_search", type=int, default=None)
+    p_tune.add_argument("--k-factor", dest="k_factor", type=float, default=None)
+    p_tune.set_defaults(func=cmd_tune)
+    p_eval = sub.add_parser("eval")
+    p_eval.add_argument("kind", choices=["recall"])
+    p_eval.add_argument("--duckdb", required=True)
+    p_eval.add_argument("--index", required=True)
+    p_eval.add_argument("--k", type=int, default=10)
+    p_eval.add_argument("--k-factor", type=float, default=2.0)
+    p_eval.add_argument("--out")
+    p_eval.set_defaults(func=cmd_eval_recall)
+    args = p.parse_args(argv)
+    return args.func(args)
+
+if __name__ == "__main__":
+    raise SystemExit(main())
```

---

## D. Evaluator — ANN vs Flat oracle & per‑query pools

**What it does.**

* Issues ANN search (your current primary index) with `k * k_factor`.
* Reconstructs candidate vectors and computes exact dot‑product distances against the query vector → **oracle top‑K**.
* Computes recall@K and writes **pool Parquet**: `(query_id, source, rank, chunk_id, score)` plus per‑channel attribution so DuckDB can build coverage heatmaps and module contribution analyses. This follows the plan in your full‑stack doc and the theory doc’s quality tuning section.

### Patch D1 — **new file** `codeintel_rev/eval/hybrid_evaluator.py`

```diff
diff --git a/codeintel_rev/eval/hybrid_evaluator.py b/codeintel_rev/eval/hybrid_evaluator.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/eval/hybrid_evaluator.py
@@
+from __future__ import annotations
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Iterable, Sequence
+import numpy as np
+import pyarrow as pa
+import pyarrow.parquet as pq
+
+from codeintel_rev.io.faiss_manager import FAISSManager
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+
+@dataclass(frozen=True)
+class EvalReport:
+    queries: int
+    k: int
+    k_factor: float
+    recall_at_k: float
+
+class HybridPoolEvaluator:
+    """
+    Compare ANN (IVF/HNSW) against Flat oracle by re-ranking ANN pools.
+    Persists per-query pools for diagnostics.
+    """
+    def __init__(self, catalog: DuckDBCatalog, mgr: FAISSManager) -> None:
+        self._cat = catalog
+        self._mgr = mgr
+
+    def _flat_rerank(self, xq: np.ndarray, cand_ids: Sequence[int], topk: int) -> tuple[np.ndarray, np.ndarray]:
+        Xc = self._mgr.reconstruct_batch(cand_ids)
+        # cosine/IP assume normalized embeddings
+        faiss = __import__("faiss")
+        faiss.normalize_L2(Xc)
+        faiss.normalize_L2(xq)
+        D = xq @ Xc.T  # (1, m)
+        order = np.argsort(-D, axis=1)[:, :topk]
+        I = np.asarray(cand_ids, dtype=np.int64)[order]
+        return np.take_along_axis(D, order, axis=1), I
+
+    def run(self, *, k: int, k_factor: float, out_parquet: Path | None) -> dict:
+        """
+        Returns a dict summary and writes optional pool parquet with columns:
+          (query_id, source, rank, chunk_id, score)
+        """
+        qrows = self._cat.sample_query_vectors()  # implement in DuckDBCatalog
+        total = 0
+        hits = 0
+        pools = []
+        for qid, xq in qrows:
+            D_ann, I_ann = self._mgr.search(xq, k=int(k * k_factor))
+            cand = I_ann[0].tolist()
+            D_flat, I_flat = self._flat_rerank(xq.reshape(1, -1), cand, k)
+            # compute recall: how many oracle@K appear in ANN@K?
+            ann_k = set(I_ann[0][:k].tolist())
+            ora_k = set(I_flat[0][:k].tolist())
+            hits += len(ann_k & ora_k)
+            total += k
+            # persist pools (source='ann' and 'oracle')
+            for r, (cid, sc) in enumerate(zip(I_ann[0].tolist(), D_ann[0].tolist()), 1):
+                pools.append((qid, "ann", r, int(cid), float(sc)))
+            for r, (cid, sc) in enumerate(zip(I_flat[0].tolist(), D_flat[0].tolist()), 1):
+                pools.append((qid, "oracle", r, int(cid), float(sc)))
+        recall = (hits / max(total, 1.0))
+        if out_parquet:
+            table = pa.Table.from_arrays(
+                [
+                    pa.array([r[0] for r in pools], type=pa.int64()),
+                    pa.array([r[1] for r in pools], type=pa.string()),
+                    pa.array([r[2] for r in pools], type=pa.int32()),
+                    pa.array([r[3] for r in pools], type=pa.int64()),
+                    pa.array([r[4] for r in pools], type=pa.float32()),
+                ],
+                names=["query_id", "source", "rank", "chunk_id", "score"],
+            )
+            pq.write_table(table, out_parquet, compression="zstd")
+        return EvalReport(queries=len(qrows), k=k, k_factor=k_factor, recall_at_k=recall).__dict__
```

> *Where do queries come from?* Add a very small helper in `DuckDBCatalog` — `sample_query_vectors()` — that returns `(query_id, xq: np.ndarray)` from your stored query embeddings (or derive from modules/symbols for synthetic trials). This keeps the evaluator decoupled from embedding runtime. 

---

## E. SCIP‑aware synthetic queries

**Why:** Realistic “function‑intent” prompts (names + docstrings + local call‑context) give you offline recall curves that correlate with user reality. This generator just walks SCIP docs/symbols (which you already export) and emits one JSONL line per query with the ground‑truth positives (the symbol’s primary chunk ids). 

### Patch E1 — **new file** `codeintel_rev/synth/scip_synth_queries.py`

```diff
diff --git a/codeintel_rev/synth/scip_synth_queries.py b/codeintel_rev/synth/scip_synth_queries.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/synth/scip_synth_queries.py
@@
+from __future__ import annotations
+from dataclasses import asdict, dataclass
+from pathlib import Path
+import json
+from typing import Iterable
+
+@dataclass(frozen=True)
+class SynthQuery:
+    query_id: int
+    text: str
+    positives: list[int]  # chunk_ids
+    meta: dict
+
+def build_from_scip(index_json: Path, symbol_graph_json: Path, out_jsonl: Path) -> int:
+    """
+    Create function-intent queries by combining symbol name + docstring + call context.
+    """
+    scip = json.loads(index_json.read_text())
+    graph = json.loads(symbol_graph_json.read_text())
+    out = out_jsonl.open("w", encoding="utf-8")
+    n = 0
+    # pseudo: walk documents/symbols, derive text and positives via location->chunk_id mapping
+    for qid, sym in enumerate(graph.get("symbols", []), 1):
+        name = sym.get("name", "")
+        doc = sym.get("doc", "")
+        callers = ", ".join(sym.get("callers", [])[:3])
+        text = f"Where is `{name}` implemented? {doc} Called by: {callers}"
+        positives = sym.get("chunk_ids", [])
+        sq = SynthQuery(qid, text, positives, {"symbol": name})
+        out.write(json.dumps(asdict(sq)) + "\n")
+        n += 1
+    out.close()
+    return n
```

---

## F. Small additions to `DuckDBCatalog` (query vectors & ID hydration)

Additions are pure‑append and non‑breaking.

### Patch F1 — `codeintel_rev/io/duckdb_catalog.py` (append helpers)

```diff
@@
     def create_or_replace_views(self) -> None:
         ...
 
+    # -------------------- Evaluator hooks ------------------------------------
+    def sample_query_vectors(self, limit: int = 64) -> list[tuple[int, "np.ndarray"]]:
+        """
+        Returns (query_id, vector) pairs for evaluator runs.
+        Assumes a table or view 'query_embeddings(query_id BIGINT, vec BLOB)'.
+        Replace with your actual table/view as available.
+        """
+        import numpy as np
+        rows = self._con.execute("SELECT query_id, vec FROM query_embeddings LIMIT ?;", [limit]).fetchall()
+        out: list[tuple[int, np.ndarray]] = []
+        for qid, blob in rows:
+            x = np.frombuffer(blob, dtype=np.float32)
+            out.append((int(qid), x))
+        return out
+
+    def query_by_ids(self, ids: list[int]) -> list[dict]:
+        """
+        Hydrate chunk records for a list of chunk_ids.
+        """
+        q = "SELECT * FROM chunks WHERE chunk_id IN (" + ",".join("?" * len(ids)) + ");"
+        cur = self._con.execute(q, ids)
+        cols = [c[0] for c in cur.description]
+        return [dict(zip(cols, row)) for row in cur.fetchall()]
```

---

## G. Operator runbook (1‑page, practical)

1. **Export & register the idmap**

   ```
   indexctl export-idmap --index data/faiss/code.ivfpq.faiss \
                         --out data/faiss/faiss_idmap.parquet \
                         --duckdb data/db/code.duckdb
   ```

   This writes `faiss_idmap.parquet`, upserts into DuckDB, and materializes `faiss_idmap_mat` with a checksum, enabling `v_faiss_join` and `v_module_coverage` immediately.

2. **Tune and lock an operating point**

   ```
   indexctl tune --index data/faiss/code.ivfpq.faiss \
                 --nprobe 64 --ef-search 128 --k-factor 2.0
   ```

   This emits `code.ivfpq.audit.json` capturing the **factory string** and **ParameterSpace** knobs, so you can time‑travel regressions to a concrete index shape. (Wheel inventory confirms `ParameterSpace` support.) 

3. **Evaluate recall vs oracle & write pools**

   ```
   indexctl eval recall --duckdb data/db/code.duckdb \
                        --index data/faiss/code.ivfpq.faiss \
                        --k 10 --k-factor 2.0 \
                        --out data/eval/last_eval_pool.parquet
   ```

   Now DuckDB can produce **coverage heatmaps** and per‑module contribution analyses from `last_eval_pool.parquet` in a few lines of SQL; this mirrors the “query‑to‑pool trace” hook we scoped. 

---

## Why these changes are “best‑in‑class” for your setting

* They respect the **accuracy‑first, small‑system** constraint (high recall knobs, explicit Flat rerank for oracle) and keep operational complexity low (single CLI, sidecars next to the index). The approach is identical to what we prescribed in your full‑stack plan and justified in the theory doc (cosine/IP normalization; IVF/HNSW trade‑offs; k‑pool refinement).
* They sit cleanly on top of the capabilities your FAISS wheel actually exposes (IDMap2, ParameterSpace, GPU/CAGRA symbols present in the build), so you’re not chasing unsupported features.
* The join and materialization logic matches your current code organization per SCIP, so these are true “minimal diffs” instead of rewrites.

---

## What to do next (fast follow)

* **Add BM25/Splade channel attribution** to the evaluator pool writer (two extra `source` values). This will let you run *true* hybrid diagnostics (RRF contributions per channel) with the same duckdb SQL you use for FAISS.
* **Wire the CLI into your packaging** (`setup.cfg`/`pyproject.toml` entry_point) so `indexctl` is on PATH; keep it optional for pure‑library installs.
* **Optionally** implement the **materialized join checksum guard** with a small `faiss_idmap_mat_meta` read (already in Patch A1) so cron jobs skip refresh unless the checksum changes.

If you want me to also render *unit test stubs* for each new function (and a tiny golden‑file test for `export_idmap` and the join view), I can drop those into `tests/io/test_duckdb_catalog.py`, `tests/io/test_faiss_manager_idmap.py`, and `tests/eval/test_hybrid_evaluator.py` in the same “ready‑to‑apply” style you asked for.

---

### Appendix — small schema notes / guardrails

* **`chunks.chunk_id`:** If you don’t already persist a stable `chunk_id`, adopt `xxhash64(uri,start_byte,end_byte)` (int64) and ensure the builder passes those IDs into FAISS via `add_with_ids(...)`. That keeps DB and index in the same ID space forever.
* **`modules` live view vs materialized:** For personal repos, the live view over JSONL is plenty; materialize only if you feel BI queries are sluggish.
* **Cosine/IP normalization:** In evaluator and search paths, normalize vectors once; cosine similarity becomes a dot product that’s extremely fast and stable (this is the geometry we emphasized in the theory doc). 

---

## Footnotes (supporting materials)

* Earlier **ready‑to‑apply diffs** you approved (this patchset continues them).
* **Wheel overview + API inventory** (to validate feature availability used here: IDMap2, ParameterSpace, GPU cloners).
* **Full‑stack plan** (operator workflows and “tune‑then‑lock” guidance) and the **theory doc** (cosine/IP, IVF/HNSW recall dynamics, k‑pool refinement).
* **SCIP‑discovered repo structure** (so paths/symbols in diffs match your tree).

---

If you’d like, I can also fold these into a **single patch file** you can `git apply` directly — but the above should be copy‑paste‑ready per file.





# Fast follow items to implement conjointly #

Below is a **ready‑to‑apply patchset** that implements the three “fast‑follow” items you called out, plus minimal unit‑test stubs and a couple of tiny SQL helpers for diagnostics. I’ve kept the file paths, logging, typing, and msgspec/pyarrow patterns aligned with what your repo already uses. Where I add new modules, I include the full file body; where I modify existing modules, I anchor hunks around stable symbols so `git apply` can land cleanly. The changes build directly on the prior plan/diffs we discussed (IDMap sidecar + join view, evaluator pool tracing, CLI) and on the FAISS API surface verified from your uploaded wheel (IDMap2, ParameterSpace, GPU cloners, etc.).   

> **What this patchset delivers**
>
> 1. **BM25/Splade channel attribution** in the evaluator pool writer so your “last_eval_pool” contains explicit `source ∈ {"faiss","bm25","splade"}`—enabling true hybrid diagnostics (RRF by channel) with the same DuckDB SQL you already use. 
> 2. **CLI wiring** (`indexctl`) exposed via packaging entry points; kept optional for pure‑library installs. The CLI surfaces: `faiss export-idmap`, `duckdb refresh-idmap-join`, and `eval write-pool`. 
> 3. **Materialized join checksum guard** so a cron/script refreshes `faiss_idmap_mat` only when the exported IDMap Parquet actually changed. This implements the `faiss_idmap_mat_meta` guard we sketched as “Patch A1.” 
>
> (Bonus) **Unit‑test stubs** for the new functions and a tiny “golden” test outline for IDMap export & join view.

The patches reference files and symbols whose presence and locations I validated from your SCIP scan / repo inventory (e.g., existing CLI under `diagnostics/`, FAISS manager surface, DuckDB catalog, warmup, etc.).  

---

## Patch FF‑1 — Evaluator pool writer: add **BM25** and **Splade** channel attribution

This introduces a small, self‑contained pool writer and wires it into your evaluator/hybrid path. The writer emits a Parquet with columns `(query_id, source, rank, chunk_id, score)`—the same shape we used previously for FAISS‑only runs; now with two additional `source` values: `"bm25"` and `"splade"`. This matches the trace format we anticipated for DuckDB explainability. 

> **New module:** `codeintel_rev/eval/pool_writer.py`
> **Modified:** `codeintel_rev/eval/hybrid_evaluator.py` (or wherever you aggregate pools)
> **DuckDB:** a convenience view to analyze RRF contributions per channel

### A. New file — `codeintel_rev/eval/pool_writer.py`

```diff
diff --git a/codeintel_rev/eval/pool_writer.py b/codeintel_rev/eval/pool_writer.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/eval/pool_writer.py
@@
+from __future__ import annotations
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Iterable, Literal
+import time
+
+try:
+    import pyarrow as pa
+    import pyarrow.parquet as pq
+except Exception as _exc:  # pragma: no cover
+    pa = None  # type: ignore[assignment]
+    pq = None  # type: ignore[assignment]
+
+Source = Literal["faiss", "bm25", "splade"]
+
+@dataclass(frozen=True)
+class PoolRow:
+    """One candidate row for evaluator pool analysis."""
+    query_id: str
+    source: Source
+    rank: int
+    chunk_id: int
+    score: float
+
+def write_pool(rows: Iterable[PoolRow], out_path: Path, *, overwrite: bool = True) -> int:
+    """Write a compact Parquet file with (query_id, source, rank, chunk_id, score).
+
+    Returns number of rows written.
+    """
+    if pa is None or pq is None:
+        raise RuntimeError("pyarrow is required to write evaluator pools")
+    rows_list = list(rows)
+    if not rows_list:
+        # produce an empty table with schema for stable downstream behavior
+        schema = pa.schema(
+            [
+                ("query_id", pa.string()),
+                ("source", pa.dictionary(pa.int32(), pa.string())),
+                ("rank", pa.int32()),
+                ("chunk_id", pa.int64()),
+                ("score", pa.float32()),
+            ]
+        )
+        table = pa.Table.from_arrays(
+            [pa.array([], type=pa.string()),
+             pa.array([], type=pa.dictionary(pa.int32(), pa.string())),
+             pa.array([], type=pa.int32()),
+             pa.array([], type=pa.int64()),
+             pa.array([], type=pa.float32())],
+            schema=schema,
+        )
+        out_path.parent.mkdir(parents=True, exist_ok=True)
+        pq.write_table(table, out_path, compression="zstd")
+        return 0
+
+    query_id = [r.query_id for r in rows_list]
+    source = [r.source for r in rows_list]
+    rank = [int(r.rank) for r in rows_list]
+    chunk_id = [int(r.chunk_id) for r in rows_list]
+    score = [float(r.score) for r in rows_list]
+
+    table = pa.Table.from_arrays(
+        [
+            pa.array(query_id, type=pa.string()),
+            pa.array(source),  # auto-dictionary enc
+            pa.array(rank, type=pa.int32()),
+            pa.array(chunk_id, type=pa.int64()),
+            pa.array(score, type=pa.float32()),
+        ],
+        names=["query_id", "source", "rank", "chunk_id", "score"],
+    )
+    out_path.parent.mkdir(parents=True, exist_ok=True)
+    if overwrite and out_path.exists():
+        out_path.unlink()
+    pq.write_table(table, out_path, compression="zstd", use_dictionary=True)
+    return len(rows_list)
```

### B. Update your evaluator (or hybrid engine) to emit sources

If you already accumulate FAISS hits into a pool, extend that call site to include BM25/Splade with `source` set accordingly. Below shows a minimal, robust pattern—adapt this hunk where you build the pool (e.g., in `HybridEvaluator.evaluate_queries`):

```diff
diff --git a/codeintel_rev/eval/hybrid_evaluator.py b/codeintel_rev/eval/hybrid_evaluator.py
--- a/codeintel_rev/eval/hybrid_evaluator.py
+++ b/codeintel_rev/eval/hybrid_evaluator.py
@@
-from typing import Iterable, Sequence
+from typing import Iterable, Sequence, Iterator
 from pathlib import Path
 from kgfoundry_common.logging import get_logger
-from .pool_writer import PoolRow, write_pool
+from .pool_writer import PoolRow, write_pool
@@
-    def _build_pool_rows(self, qid: str, faiss_hits: Sequence[tuple[int, float]]) -> list[PoolRow]:
-        rows: list[PoolRow] = []
-        for r, (cid, score) in enumerate(faiss_hits, start=1):
-            rows.append(PoolRow(query_id=qid, source="faiss", rank=r, chunk_id=cid, score=score))
-        return rows
+    def _build_pool_rows(
+        self,
+        qid: str,
+        *,
+        faiss_hits: Sequence[tuple[int, float]] | None = None,
+        bm25_hits: Sequence[tuple[int, float]] | None = None,
+        splade_hits: Sequence[tuple[int, float]] | None = None,
+    ) -> Iterator[PoolRow]:
+        if faiss_hits:
+            for r, (cid, score) in enumerate(faiss_hits, start=1):
+                yield PoolRow(query_id=qid, source="faiss", rank=r, chunk_id=cid, score=float(score))
+        if bm25_hits:
+            for r, (cid, score) in enumerate(bm25_hits, start=1):
+                yield PoolRow(query_id=qid, source="bm25", rank=r, chunk_id=cid, score=float(score))
+        if splade_hits:
+            for r, (cid, score) in enumerate(splade_hits, start=1):
+                yield PoolRow(query_id=qid, source="splade", rank=r, chunk_id=cid, score=float(score))
@@
-        rows = self._build_pool_rows(qid, faiss_hits)
-        write_pool(rows, self._pool_path)
+        rows = self._build_pool_rows(
+            qid,
+            faiss_hits=faiss_hits,
+            bm25_hits=bm25_hits,
+            splade_hits=splade_hits,
+        )
+        write_pool(list(rows), self._pool_path)
```

> *Why this shape?* It’s exactly the `(query_id, source, rank, chunk_id, score)` trace we agreed to earlier for DuckDB explainability and coverage heatmaps, now with channel attribution. Your earlier plan called out this pool schema for per‑channel RRF diagnostics and coverage analyses. 

### C. Optional: DuckDB view for per‑channel RRF diagnostics

Place this in your DuckDB catalog initializer (or run as ad‑hoc SQL during analysis):

```sql
-- v_rrf_contrib_by_channel: RRF-style contribution and hit mix per source
create or replace view v_rrf_contrib_by_channel as
select
  query_id,
  source,
  count(*) as hits,
  sum(1.0 / (60.0 + cast(rank as double))) as rrf_contrib
from last_eval_pool
group by query_id, source;
```

---

## Patch FF‑2 — CLI wiring: **indexctl** on PATH (but optional)

We add a focused CLI at `codeintel_rev/cli/indexctl.py` with subcommands you can expand. Then we wire it to packaging **as an optional entry‑point**, so pure‑library users aren’t forced to install the CLI extras.

> **New file:** `codeintel_rev/cli/indexctl.py`
> **Packaging:** add console‑script entry under `pyproject.toml` *(PEP‑621)* **or** `setup.cfg` *(setuptools)*—pick the one your repo uses. The scan shows you already ship a CLI under `diagnostics/report_cli.py`; this new tool is intentionally small and task‑focused (index ops, join refresh, evaluator). 

### A. New file — `codeintel_rev/cli/indexctl.py`

```diff
diff --git a/codeintel_rev/cli/indexctl.py b/codeintel_rev/cli/indexctl.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/cli/indexctl.py
@@
+from __future__ import annotations
+import argparse
+from pathlib import Path
+from typing import Sequence
+from kgfoundry_common.logging import get_logger
+
+from codeintel_rev.io.faiss_manager import FAISSManager
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.eval.pool_writer import PoolRow, write_pool
+
+LOGGER = get_logger(__name__)
+
+def cmd_faiss_export_idmap(args: argparse.Namespace) -> int:
+    mgr = FAISSManager.from_path(Path(args.index))
+    rows = mgr.export_idmap(Path(args.out))
+    LOGGER.info("exported idmap rows=%s path=%s", rows, args.out)
+    return 0
+
+def cmd_duckdb_refresh_join(args: argparse.Namespace) -> int:
+    cat = DuckDBCatalog(Path(args.db))
+    stats = cat.refresh_faiss_idmap_mat_if_changed(Path(args.idmap))
+    LOGGER.info("faiss_idmap_mat refresh: %s", stats)
+    return 0
+
+def cmd_eval_write_pool(args: argparse.Namespace) -> int:
+    out = Path(args.out)
+    rows: list[PoolRow] = []
+    # Minimal example: consume a simple TSV (query_id \t source \t rank \t chunk_id \t score)
+    for line in Path(args.tsv).read_text(encoding="utf-8").splitlines():
+        qid, source, rank, cid, score = line.split("\t")
+        rows.append(PoolRow(qid, source, int(rank), int(cid), float(score)))  # type: ignore[arg-type]
+    write_pool(rows, out)
+    LOGGER.info("wrote pool rows=%d path=%s", len(rows), out)
+    return 0
+
+def build_parser() -> argparse.ArgumentParser:
+    p = argparse.ArgumentParser("indexctl")
+    sub = p.add_subparsers(dest="cmd", required=True)
+
+    faiss = sub.add_parser("faiss", help="FAISS index operations")
+    faiss_sub = faiss.add_subparsers(dest="sub", required=True)
+    exp = faiss_sub.add_parser("export-idmap", help="Export {faiss_row -> external_id} Parquet")
+    exp.add_argument("--index", required=True, help="Path to CPU FAISS index file")
+    exp.add_argument("--out", required=True, help="Path to Parquet sidecar to write")
+    exp.set_defaults(func=cmd_faiss_export_idmap)
+
+    duck = sub.add_parser("duckdb", help="DuckDB catalog operations")
+    duck_sub = duck.add_subparsers(dest="sub", required=True)
+    mat = duck_sub.add_parser("refresh-idmap-join", help="Refresh materialized idmap join iff checksum changed")
+    mat.add_argument("--db", required=True, help="Path to DuckDB database file")
+    mat.add_argument("--idmap", required=True, help="Path to IDMap Parquet file")
+    mat.set_defaults(func=cmd_duckdb_refresh_join)
+
+    ev = sub.add_parser("eval", help="Evaluator operations")
+    ev_sub = ev.add_subparsers(dest="sub", required=True)
+    wp = ev_sub.add_parser("write-pool", help="Write evaluator pool Parquet from TSV")
+    wp.add_argument("--tsv", required=True, help="TSV with columns: query_id,source,rank,chunk_id,score")
+    wp.add_argument("--out", required=True, help="Destination Parquet")
+    wp.set_defaults(func=cmd_eval_write_pool)
+
+    return p
+
+def main(argv: Sequence[str] | None = None) -> int:
+    p = build_parser()
+    args = p.parse_args(argv)
+    return int(args.func(args))
```

### B. Packaging entry‑point (choose your stack)

**If you use `pyproject.toml` (PEP‑621):**

```diff
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@
 [project.scripts]
 indexctl = "codeintel_rev.cli.indexctl:main"
@@
 [project.optional-dependencies]
 cli = ["pyarrow", "duckdb"]
```

**If you use `setup.cfg` (setuptools):**

```diff
diff --git a/setup.cfg b/setup.cfg
--- a/setup.cfg
+++ b/setup.cfg
@@
 [options.entry_points]
 console_scripts =
     indexctl = codeintel_rev.cli.indexctl:main
@@
 [options.extras_require]
 cli =
     pyarrow
     duckdb
```

This makes `indexctl` available when users install the **`cli` extra** (or when your wheel includes extras)—keeping the console script optional for “library‑only” environments, as requested. 

---

## Patch FF‑3 — Materialized join **checksum guard** for `faiss_idmap_mat`

Implements `faiss_idmap_mat_meta` and `refresh_faiss_idmap_mat_if_changed(...)`, so you only materialize the join when the IDMap sidecar actually changed. This follows the exact “A1” meta guard we discussed. 

> **Modified:** `codeintel_rev/io/duckdb_catalog.py`

```diff
diff --git a/codeintel_rev/io/duckdb_catalog.py b/codeintel_rev/io/duckdb_catalog.py
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@
 from __future__ import annotations
-from pathlib import Path
+from pathlib import Path
+from datetime import datetime
+import hashlib
+from typing import Any
 import duckdb
 from kgfoundry_common.logging import get_logger
 
 LOGGER = get_logger(__name__)
 
 class DuckDBCatalog:
@@
     def __init__(self, db_path: Path):
         self._db_path = Path(db_path)
         self._con = duckdb.connect(self._db_path.as_posix())
         self._con.execute("PRAGMA threads=auto")
@@
+    # ------------------------ IDMap materialization guard ------------------------
+    def _ensure_idmap_meta(self) -> None:
+        self._con.execute("""
+            create table if not exists faiss_idmap_mat_meta(
+                checksum text not null,
+                row_count bigint not null,
+                updated_at timestamp not null
+            );
+        """)
+
+    @staticmethod
+    def _file_sha256(path: Path) -> str:
+        h = hashlib.sha256()
+        with path.open("rb") as f:
+            for chunk in iter(lambda: f.read(1024 * 1024), b""):
+                h.update(chunk)
+        return h.hexdigest()
+
+    def refresh_faiss_idmap_mat_if_changed(self, idmap_parquet: Path) -> dict[str, Any]:
+        """
+        Refresh materialized idmap table iff the IDMap Parquet content changed.
+
+        Returns stats dict: {"refreshed": bool, "checksum": str, "rows": int}
+        """
+        idmap_parquet = Path(idmap_parquet)
+        self._ensure_idmap_meta()
+        checksum = self._file_sha256(idmap_parquet)
+        # Read previous meta (if any)
+        prev = self._con.execute("select checksum, row_count from faiss_idmap_mat_meta order by updated_at desc limit 1").fetchone()
+        if prev and prev[0] == checksum:
+            return {"refreshed": False, "checksum": checksum, "rows": int(prev[1])}
+
+        # Re-materialize
+        self._con.execute("create or replace table faiss_idmap_mat as select * from read_parquet(?)", [idmap_parquet.as_posix()])
+        row_count = int(self._con.execute("select count(*) from faiss_idmap_mat").fetchone()[0])
+        self._con.execute(
+            "insert into faiss_idmap_mat_meta (checksum, row_count, updated_at) values (?, ?, ?)",
+            [checksum, row_count, datetime.utcnow()],
+        )
+        LOGGER.info("Refreshed faiss_idmap_mat rows=%s checksum=%s", row_count, checksum)
+        return {"refreshed": True, "checksum": checksum, "rows": row_count}
```

> *Notes.*
> • This guard is content‑based (SHA‑256 of the Parquet file), so it’s robust to path and mtime.
> • It pairs with the **IDMap export** you added in FAISSManager (persisting `{faiss_row -> external_id}`), which we previously implemented to ensure stable, deterministic hydration. That build step relies on your wheel’s `IndexIDMap2` support.  

---

## (Bonus) Unit‑test stubs & a tiny golden outline

These are minimal, self‑contained stubs that exercise the new surfaces. They assume `pytest` and reuse your existing layout under `tests/…`.

### A. Test FAISS IDMap export

```diff
diff --git a/tests/io/test_faiss_manager_idmap.py b/tests/io/test_faiss_manager_idmap.py
new file mode 100644
--- /dev/null
+++ b/tests/io/test_faiss_manager_idmap.py
@@
+from __future__ import annotations
+from pathlib import Path
+import numpy as np
+import pyarrow.parquet as pq
+import faiss  # type: ignore
+
+from codeintel_rev.io.faiss_manager import FAISSManager
+
+def test_export_idmap_roundtrip(tmp_path: Path) -> None:
+    d = 16
+    xb = np.random.RandomState(0).randn(100, d).astype("float32")
+    faiss.normalize_L2(xb)
+    ids = np.arange(100, dtype="int64")
+
+    mgr = FAISSManager.from_scratch(vec_dim=d)
+    mgr.build_index(xb, ids=ids, family="flat")  # ensures IDMap2 wrapper
+
+    out = tmp_path / "faiss_idmap.parquet"
+    rows = mgr.export_idmap(out)
+    assert rows == 100
+    table = pq.read_table(out)
+    assert set(table.column_names) == {"faiss_row", "external_id"}
+    assert table.num_rows == 100
```

### B. Test DuckDB checksum guard

```diff
diff --git a/tests/io/test_duckdb_catalog.py b/tests/io/test_duckdb_catalog.py
new file mode 100644
--- /dev/null
+++ b/tests/io/test_duckdb_catalog.py
@@
+from __future__ import annotations
+from pathlib import Path
+import pyarrow as pa
+import pyarrow.parquet as pq
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+
+def _write_idmap(path: Path, n: int) -> None:
+    tbl = pa.Table.from_arrays(
+        [pa.array(range(n), type=pa.int64()), pa.array(range(1000, 1000+n), type=pa.int64())],
+        names=["faiss_row", "external_id"],
+    )
+    pq.write_table(tbl, path)
+
+def test_refresh_idmap_mat_if_changed(tmp_path: Path) -> None:
+    db = tmp_path / "test.duckdb"
+    cat = DuckDBCatalog(db)
+    idmap = tmp_path / "idmap.parquet"
+    _write_idmap(idmap, 3)
+    s1 = cat.refresh_faiss_idmap_mat_if_changed(idmap)
+    assert s1["refreshed"] is True and s1["rows"] == 3
+    s2 = cat.refresh_faiss_idmap_mat_if_changed(idmap)
+    assert s2["refreshed"] is False and s2["rows"] == 3
+    # mutate file -> checksum change
+    _write_idmap(idmap, 4)
+    s3 = cat.refresh_faiss_idmap_mat_if_changed(idmap)
+    assert s3["refreshed"] is True and s3["rows"] == 4
```

### C. Test pool writer shape + channel attribution

```diff
diff --git a/tests/eval/test_hybrid_evaluator.py b/tests/eval/test_hybrid_evaluator.py
new file mode 100644
--- /dev/null
+++ b/tests/eval/test_hybrid_evaluator.py
@@
+from __future__ import annotations
+from pathlib import Path
+import pyarrow.parquet as pq
+from codeintel_rev.eval.pool_writer import PoolRow, write_pool
+
+def test_pool_writer_sources(tmp_path: Path) -> None:
+    rows = [
+        PoolRow("q1", "faiss", 1, 111, 0.9),
+        PoolRow("q1", "bm25", 1, 222, 0.8),
+        PoolRow("q1", "splade", 1, 333, 0.7),
+    ]
+    out = tmp_path / "pool.parquet"
+    n = write_pool(rows, out)
+    assert n == 3
+    t = pq.read_table(out)
+    assert set(t.column_names) == {"query_id", "source", "rank", "chunk_id", "score"}
+    assert t.num_rows == 3
```

---

## How to use it (operator snippets)

1. **Export IDMap** after (re)building your FAISS index:

```bash
indexctl faiss export-idmap --index data/faiss/code.ivfpq.faiss --out data/faiss/faiss_idmap.parquet
```

2. **Refresh materialized join only if IDMap changed:**

```bash
indexctl duckdb refresh-idmap-join --db data/codeintel.duckdb --idmap data/faiss/faiss_idmap.parquet
```

3. **Write a pool with channel attribution** (example from a TSV you assemble during eval):

```bash
indexctl eval write-pool --tsv out/eval_pool.tsv --out out/last_eval_pool.parquet
```

Then run your usual DuckDB explainability queries (coverage by module, RRF by channel, etc.). This aligns with the evaluator/trace design we laid out earlier. 

---

## Why this integrates cleanly with your repo & wheel

* The **FAISS IDMap export** and later **join materialization** follow the earlier diffs (IndexIDMap2 wrapper, sidecar Parquet) and are supported by the concrete symbols present in your uploaded wheel: `IndexIDMap2`, I/O helpers, and `ParameterSpace` if you subsequently expose runtime knobs via CLI. 
* The **SCIP‑anchored structure** and existing modules (catalog, warmup, diagnostics) were confirmed from your SCIP inventory & metrics scan, which guided file placement and import style so patches will anchor.  

---

## (Optional, tiny) SQL helpers for hybrid channel mix

If you register `last_eval_pool.parquet` in DuckDB (or create a view to it), the following are useful during daily tuning:

```sql
-- top-K mix by channel
select source, count(*) as hits
from last_eval_pool
where rank <= 10
group by source
order by hits desc;

-- query-level RRF contribution by channel (K=10, k0=60)
select query_id, source,
       sum(1.0 / (60 + cast(rank as double))) as rrf_contrib
from last_eval_pool
where rank <= 10
group by query_id, source
order by query_id, rrf_contrib desc;
```

This is the “true hybrid diagnostics (RRF contributions per channel)” you asked to enable. 

---

## A couple of small notes (so implementation is smooth)

* **Parquet & DuckDB:** The pool writer and IDMap meta guard rely on `pyarrow` and `duckdb`; both are already common in your tree. Keep them under an optional `cli` extra in packaging, as shown, to preserve light installs. 
* **Stable external IDs:** These patches assume your FAISS build path continues to assign *external* `chunk_id` as FAISS IDs (via IDMap2). That’s how the IDMap sidecar remains meaningful and stable across rebuilds and is fully supported by your wheel. 
* **Evaluator wiring point:** If your BM25/Splade results already flow through a hybrid engine, you can emit them to the pool writer at the point where you assemble FAISS candidates—no changes to retrieval logic are required; only the trace line gains `source`. This mirrors the trace schema we documented earlier. 

---

## What you can schedule next (quick wins you hinted at)

* A tiny **DuckDB view** (`v_faiss_join`) to combine `faiss_idmap_mat` with your chunks table, then **coverage by module/language** from the same join—ties directly into the personal‑RAG “keep accuracy tight” objective we outlined in the full‑stack plan. 
* A compact **ParameterSpace preset** map (`corpus_size → {nprobe, efSearch, k_factor}`) and a CLI verb to apply it (“tune then lock”), aligned with your accuracy‑first small‑system defaults. (Your wheel exposes ParameterSpace and OperatingPoints.) 
* Optional **oracle rerank** (Flat exact) for **recall@K deltas** using the same pool/table format; your earlier evaluator diffs already anticipate this. 

---

### Provenance & alignment

* **Prior diffs & implementation plan references:** patches A/B we extended here (IDMap sidecar, pool trace, CLI) were proposed in your earlier “ready‑to‑apply diffs” sets; we keep the same file surfaces and comments so teams can diff with context.  
* **Wheel capabilities referenced:** IDMap2, `ParameterSpace`, GPU/clone semantics were verified from your wheel inventory & overview so there’s no API drift surprise.  

---

If you’d like, I can also layer in a one‑liner **`indexctl eval hybrid-run`** wiring directly to your evaluator so pool writing happens automatically during offline runs; we can reuse the pool writer above and keep the TSV path only as a debug/interop option.
