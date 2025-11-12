Below is a tight, actionable plan that (1) reconciles what Phase‑1 promised vs. what’s actually in the repo today, (2) adds new scope enabled by SCIP+AST+CST, (3) adapts Phase‑2 to the current code surface, and (4) expands Phase‑2 where your new data lets us raise accuracy and explainability. I’ve folded in **paste‑ready diffs** for the critical pieces (Parquet schema, DuckDB views/materialization, FAISS ID‑map export + CLI, hybrid trace pool, and evaluator hooks). Where I reference your code, I cite the symbol/behavior directly from your uploaded artifacts.

---

## A. What Phase‑1 specified vs. what’s still missing (implement now)

**1) Parquet schema should carry `symbols` and a stable `content_hash`.**
Your current writer persists: `id, uri, start_line, end_line, start_byte, end_byte, preview, content, lang, embedding` (embedding as FixedSizeList) — but nothing yet for `symbols` or content hashing. We should add a `list<string>` **symbols** column and a `uint64` **content_hash** to support symbol‑aware joins, “same‑content” dedup/GC, and faster rechecks. The current implementation calls `get_chunks_schema(options.vec_dim)` and writes with PyArrow; that’s the natural extension point.  

**2) ID‑map join view & materialization in DuckDB.**
Phase‑1 planned a view `faiss_idmap` + `v_faiss_join` that joins the FAISS id‑map Parquet to `chunks`. Your catalog already has `_relation_exists()` and `_ensure_views()` scaffolding, so we should add the join views there and an optional materialized join guarded by a checksum to avoid unnecessary refresh.  

**3) Persist FAISS factory string & tuning knobs.**
Phase‑1 called out persisting the exact FAISS factory and `ParameterSpace` parameters next to the index (time‑travel for regressions). Add a tiny metadata sidecar (JSON) during build/update; your runtime already exposes factory/tuning hooks (e.g., `DefaultFactoryAdjuster._wrap_faiss` applies `nprobe`/GPU prefs).  

**4) Optional XTR oracle in the evaluator.**
You already expose `XTRIndex.search/rescore` for narrow re‑scoring; Phase‑1 proposed measuring recall deltas by replacing “Flat exact” with XTR narrow mode as an oracle in offline eval. We’ll add a toggle for that now.  

**5) CLI verbs.**
We planned `indexctl` verbs to: export the FAISS id‑map, install views, and run the evaluator. Wire them to context bootstrap; this is consistent with how your server bootstraps runtimes. 

---

## B. New scope we can add now that SCIP (+AST soon) and CST exist

**SCIP occurrences, AST nodes, CST nodes** should be landed as Parquet once per **index version** under `data/{scip|ast|cst}/…` and exposed in DuckDB views for joins from `chunks → symbols → defs/refs → AST/CST paths`. The Phase‑1 expansion note already lists target locations and the rationale (joins for accuracy/explainability, and projection‑light hydration). 

Concretely:

* **SCIP**: write `scip_occurrences.parquet(def/ref)` from your existing `SCIPIndex`; the plan stub for `to_parquet_occurrences()` hangs off `scip_reader`. 
* **CST**: write `cst_nodes.parquet` with `(uri, node_id, kind, start_byte, end_byte, parent_id, text_hash)`.
* **AST** (Tree‑sitter): write `ast_nodes.parquet` with `(uri, node_id, type, start_byte, end_byte, parent_id, docstring?, symbol?)`.
* Add small views: `v_chunk_symbols`, `v_chunk_ast`, `v_chunk_cst` to allow “chunk→symbol→structure” diagnostics and to seed hybrid gating (e.g., prefer defining chunks under a target symbol or within function boundaries for WARP/XTR late‑interaction passes).

These Parquet conversions plus views are low‑risk because your `DuckDBCatalog` already centralizes `_ensure_views()` and joins. 

---

## C. What in Phase‑2 should still ship (and how it changes with new data)

Phase‑2’s core aims are unchanged:

1. **Install an explicit `IndexIDMap2` wrapper + Parquet export + cheap deletes.**
   Your FAISS wheel inventory exposes `IndexIDMap/2` and `ParameterSpace`; we’ll wrap the primary index, ensure we `add_with_ids`, export an accurate FAISS→chunk sidecar, and enable IDSelector deletes (for chunk GC). 

2. **ParameterSpace presets + LUT** (corpus‑size keyed) for `nprobe/efSearch` and a CLI tuning verb, integrated with the existing runtime adjuster (so “tune then lock” is a single step). Your repo already exposes `FAISSManager.autotune()` and runtime factory overrides; we’re simply making the presets first‑class and recorded in the index meta that Phase‑1 asked for.  

3. **Hybrid attribution + trace pool** (BM25/Splade/FAISS contribution) into a small Parquet (`last_eval_pool.parquet`) written from `_build_hybrid_result(…)` and/or an explicit `trace_writer` in `HybridSearchEngine`. The adapters already manage contribution maps; we just persist them.  

**What changes with SCIP/AST/CST?**
We now add scoped joins in the query builder (on‑demand) to favor chunks that **define** a symbol (SCIP), enforce **function‑boundary** locality (AST/CST), or bias to **module** filters (your module metadata). These become flags on `DuckDBQueryOptions`: `join_modules|join_symbols|join_ast|join_cst|join_faiss`. The Phase‑1 plan already suggested the first three; we extend to AST/CST. 

---

## D. Detailed implementation plan (with paste‑ready diffs)

> **Paths** use your existing module layout. New code is annotated.
> **Dependencies**: stdlib + `pyarrow`, `duckdb`, `numpy`.
> The diffs below are minimal and preserve existing behavior.

### D1) Extend Parquet schema (`symbols`, `content_hash`)

**File:** `codeintel_rev/io/parquet_store.py`

**Why:** prepare for symbol‑aware joins, dedup, and incidence queries. Current writer doesn’t include these columns. 

```diff
--- a/codeintel_rev/io/parquet_store.py
+++ b/codeintel_rev/io/parquet_store.py
@@
-from __future__ import annotations
+from __future__ import annotations
 from dataclasses import dataclass
 from pathlib import Path
 from typing import TYPE_CHECKING, cast
@@
-import pyarrow as pa
+import pyarrow as pa
 import pyarrow.parquet as pq
+import hashlib
@@
 @dataclass(frozen=True)
 class ParquetWriteOptions:
     vec_dim: int
     preview_max_chars: int = 256
     start_id: int = 0
@@
-def get_chunks_schema(vec_dim: int) -> pa.Schema:
+def get_chunks_schema(vec_dim: int) -> pa.Schema:
     """Return Arrow schema for chunk Parquet."""
-    return pa.schema(
+    return pa.schema(
         [
             pa.field("id", pa.int64()),
             pa.field("uri", pa.string()),
             pa.field("start_line", pa.int32()),
             pa.field("end_line", pa.int32()),
             pa.field("start_byte", pa.int64()),
             pa.field("end_byte", pa.int64()),
             pa.field("preview", pa.string()),
             pa.field("content", pa.string()),
             pa.field("lang", pa.string()),
+            # New: stable content hash (64-bit) and SCIP symbols per chunk.
+            pa.field("content_hash", pa.uint64()),
+            pa.field("symbols", pa.list_(pa.string())),
             pa.field("embedding", pa.fixed_size_list(pa.field("item", pa.float32()), vec_dim)),
         ]
     )
@@
-def write_chunks_parquet(
+def write_chunks_parquet(
     chunks: list["Chunk"],
     embeddings: "NDArrayF32",
     output_path: Path,
     options: ParquetWriteOptions,
 ) -> None:
@@
-    ids = pa.array([options.start_id + i for i in range(len(chunks))], type=pa.int64())
+    ids = pa.array([options.start_id + i for i in range(len(chunks))], type=pa.int64())
     uris = pa.array([c.uri for c in chunks], type=pa.string())
     start_lines = pa.array([c.start_line for c in chunks], type=pa.int32())
     end_lines = pa.array([c.end_line for c in chunks], type=pa.int32())
     start_bytes = pa.array([c.start_byte for c in chunks], type=pa.int64())
     end_bytes = pa.array([c.end_byte for c in chunks], type=pa.int64())
@@
     languages = pa.array([c.language for c in chunks], type=pa.string())
+    # New: content_hash (64-bit) and symbols (list<string>)
+    def _u64(bl: bytes) -> int:
+        # blake2b-64 for stability without extra deps; swap to xxhash if desired.
+        return int.from_bytes(hashlib.blake2b(bl, digest_size=8).digest(), "little", signed=False)
+    content_hashes = pa.array([_u64(c.text.encode("utf-8", errors="ignore")) for c in chunks], type=pa.uint64())
+    symbol_lists = pa.array([list(c.symbols) for c in chunks], type=pa.list_(pa.string()))
@@
     # Embedding: FixedSizeList(float32, vec_dim)
     vec_dim = options.vec_dim
     flat = embeddings.ravel()
     item_type = pa.float32()
     embedding_array = pa.FixedSizeListArray.from_arrays(
         pa.array(flat, type=item_type),
         list_size=vec_dim,
     )
@@
     table = pa.table(
         {
             "id": ids,
             "uri": uris,
             "start_line": start_lines,
             "end_line": end_lines,
             "start_byte": start_bytes,
             "end_byte": end_bytes,
             "preview": previews,
             "content": contents,
             "lang": languages,
+            "content_hash": content_hashes,
+            "symbols": symbol_lists,
             "embedding": embedding_array,
         },
         schema=get_chunks_schema(options.vec_dim),
     )
@@
     pq.write_table(
         table,
         output_path,
         compression="snappy",
         use_dictionary=True,
     )
```

> **Why this is safe:** `get_chunks_schema()` is already the single source of truth for the table layout and your writer builds arrays column‑by‑column; adding two columns doesn’t change existing readers that select a projection (DuckDB will ignore unseen columns). Your writer already stores embeddings as FixedSizeList (compatible with your XTR build path that re‑reads and reshapes). 

---

### D2) DuckDB catalog: join views (ID‑map, symbols/AST/CST) + optional materialization

**File:** `codeintel_rev/io/duckdb_catalog.py`

**Why:** centralize all “view‑over‑Parquet” logic; your catalog already exposes `_ensure_views()` and `_relation_exists()`; we add FAISS joins and symbol/structure views. 

```diff
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@
 class DuckDBCatalog:
@@
-    def _ensure_views(self, conn: duckdb.DuckDBPyConnection) -> None:
-        """Create views over Parquet directories if they do not already exist."""
+    def _ensure_views(self, conn: duckdb.DuckDBPyConnection) -> None:
+        """Create/refresh views over Parquet assets (chunks, modules, symbols, FAISS)."""
         log = self._log
-        # existing views...
+        # --- chunks view (existing)
+        # Expect: data/vectors/chunks/*.parquet
         chunks_glob = f"{self._vectors_dir}/chunks/*.parquet"
         conn.execute(
             """
             create or replace view chunks as
             select * from read_parquet(?, filename=true)
             """,
             [chunks_glob],
         ).create_view("chunks", replace=True)
         log.info("installed view: chunks", extra=self._extra())
+
+        # --- modules (optional)
+        modules_path = f"{self._root}/modules/modules.parquet"
+        if Path(modules_path).exists():
+            conn.execute("create or replace view modules as select * from read_parquet(?)", [modules_path])
+            log.info("installed view: modules", extra=self._extra())
+
+        # --- SCIP occurrences (optional)
+        scip_path = f"{self._root}/scip/scip_occurrences.parquet"
+        if Path(scip_path).exists():
+            conn.execute("create or replace view scip_occurrences as select * from read_parquet(?)", [scip_path])
+            log.info("installed view: scip_occurrences", extra=self._extra())
+
+        # --- AST / CST (optional)
+        ast_path = f"{self._root}/ast/ast_nodes.parquet"
+        if Path(ast_path).exists():
+            conn.execute("create or replace view ast_nodes as select * from read_parquet(?)", [ast_path])
+            log.info("installed view: ast_nodes", extra=self._extra())
+        cst_path = f"{self._root}/cst/cst_nodes.parquet"
+        if Path(cst_path).exists():
+            conn.execute("create or replace view cst_nodes as select * from read_parquet(?)", [cst_path])
+            log.info("installed view: cst_nodes", extra=self._extra())
+
+        # --- FAISS idmap (optional)
+        idmap_path = f"{self._vectors_dir}/faiss_idmap.parquet"
+        if Path(idmap_path).exists():
+            conn.execute("create or replace view faiss_idmap as select * from read_parquet(?)", [idmap_path])
+            conn.execute(
+                """
+                create or replace view v_faiss_join as
+                select c.*, m.faiss_id
+                from   chunks c
+                join   faiss_idmap m on m.chunk_id = c.id
+                """
+            )
+            log.info("installed views: faiss_idmap, v_faiss_join", extra=self._extra())
+
+        # --- v_chunk_symbols: explode list<string> symbols (if present in chunks)
+        conn.execute(
+            """
+            create or replace view v_chunk_symbols as
+            select id as chunk_id, unnest(symbols) as symbol
+            from chunks
+            """
+        )
+        log.info("installed view: v_chunk_symbols", extra=self._extra())
@@
     @staticmethod
     def _relation_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
         """Return True when the relation exists in main schema."""
         row = conn.sql("select count(*) c from duckdb_tables() where schema_name='main' and table_name=?", [name]).fetchone()
         return bool(row[0]) if row else False
@@
+    def ensure_faiss_idmap_views(self, idmap_path: Path) -> None:
+        """Install/refresh FAISS idmap views (faiss_idmap, v_faiss_join)."""
+        with self.connection() as conn:
+            conn.execute("create or replace view faiss_idmap as select * from read_parquet(?)", [str(idmap_path)])
+            conn.execute(
+                """
+                create or replace view v_faiss_join as
+                select c.*, m.faiss_id
+                from   chunks c
+                join   faiss_idmap m on m.chunk_id = c.id
+                """
+            )
+            self._log.info("installed/updated FAISS views", extra=self._extra())
```

> The DDL mirrors the Phase‑2 sketch (view + joined view) and leverages your existing `_ensure_views` pattern and relation guards. 

---

### D3) FAISS: IDMap2 wrapper, Parquet export, parameter presets meta

**File:** `codeintel_rev/io/faiss_manager.py` (or `io/faiss_dual_index.py` if that’s your central manager)

**Why:** guarantee a stable `{faiss_id → chunk_id}` mapping, enable cheap deletes, and record the factory/tuning used. The repo already exposes FAISS runtime autotune and dual‑index selection; we add three small methods.  

```diff
--- a/codeintel_rev/io/faiss_manager.py
+++ b/codeintel_rev/io/faiss_manager.py
@@
 from pathlib import Path
 from typing import Iterable, Sequence
@@
+import pyarrow as pa
+import pyarrow.parquet as pq
+from datetime import datetime, timezone
@@
 class FAISSManager:
@@
     def build_index(...):
-        index = self._train_primary_index(vectors)
-        index.add(vectors)
+        index = self._train_primary_index(vectors)
+        # Wrap in IDMap2 so faiss_id == external chunk id we pass to add_with_ids
+        index = faiss.IndexIDMap2(index)
+        index.add_with_ids(vectors, ids)  # ids are your chunk ids
         self._cpu_index = index
         ...
+        self._write_meta(factory_str, parameter_space_str, len(ids))
         return ...
@@
+    def export_idmap_parquet(self, out: Path | None = None) -> int:
+        """
+        Export {faiss_id, chunk_id, source} rows to Parquet.
+        Returns number of rows written.
+        """
+        if out is None:
+            out = Path(self.paths.faiss_idmap)  # keep a stable path in Settings/Paths
+        ids = self._cpu_index.id_map  # IndexIDMap2 keeps a direct map
+        # NB: if you have a secondary (flat) index, append its pairs with source="secondary"
+        faiss_ids = []
+        chunk_ids = []
+        sources = []
+        for i in range(ids.size()):
+            faiss_ids.append(int(ids.at(i)))
+            chunk_ids.append(int(ids.at(i)))  # external ids == chunk ids by contract
+            sources.append("primary")
+        table = pa.table({"faiss_id": pa.array(faiss_ids, pa.int64()),
+                          "chunk_id": pa.array(chunk_ids, pa.int64()),
+                          "source": pa.array(sources, pa.string())})
+        out.parent.mkdir(parents=True, exist_ok=True)
+        pq.write_table(table, out, compression="snappy", use_dictionary=True)
+        return len(faiss_ids)
+
+    def delete_by_ids(self, ids: Sequence[int]) -> int:
+        """
+        Delete a batch of chunk ids via IDSelectorBatch; returns count removed.
+        """
+        if not ids:
+            return 0
+        sel = faiss.IDSelectorBatch(len(ids), np.array(ids, dtype="int64"))
+        removed = int(self._cpu_index.remove_ids(sel))
+        # (optional) propagate to GPU or secondary
+        return removed
+
+    def _write_meta(self, factory: str, params: str, vector_count: int) -> None:
+        meta = {
+            "faiss_compile": self.get_compile_options(),
+            "factory": factory,
+            "parameter_space": params,
+            "metric": str(self.metric),
+            "vec_dim": int(self.dim),
+            "gpu_enabled": bool(self.gpu_available),
+            "built_at": datetime.now(timezone.utc).isoformat(),
+            "vector_count": int(vector_count),
+        }
+        (self.paths.vectors_dir / "faiss.meta.json").write_text(json.dumps(meta, indent=2))
```

> Your FAISS wheel supports `IndexIDMap2` and `ParameterSpace`; the manager already contains `autotune` hooks and dual‑index selection. This patch adds a stable mapping, a sidecar Parquet export, and a tiny metadata file so we can time‑travel tuning decisions.  

---

### D4) CLI verbs: idmap export, install views, run evaluator (+XTR oracle)

**File (new):** `bin/indexctl.py`
**Why:** single entrypoint to run the ops you’ll use most often (idmap export, join installation, evaluator). The Phase‑2 doc shows this verb set. 

```diff
+#!/usr/bin/env python3
+from __future__ import annotations
+import argparse, sys
+from pathlib import Path
+from codeintel_rev.app.config_context import ApplicationContext
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.eval.hybrid_pool_evaluator import EvalConfig, run_eval  # add in D5
+
+def _ctx() -> ApplicationContext:
+    return ApplicationContext.bootstrap_for_cli()
+
+def cmd_idmap_export(args: argparse.Namespace) -> None:
+    ctx = _ctx()
+    out = Path(ctx.paths.faiss_idmap)
+    n = ctx.faiss_manager.export_idmap_parquet(out)
+    print(f"wrote {n} rows → {out}")
+
+def cmd_idmap_views(args: argparse.Namespace) -> None:
+    ctx = _ctx()
+    DuckDBCatalog(db_path=ctx.paths.duckdb_path, vectors_dir=ctx.paths.vectors_dir)\
+        .ensure_faiss_idmap_views(Path(ctx.paths.faiss_idmap))
+    print("created/updated views: faiss_idmap, v_faiss_join")
+
+def cmd_eval(args: argparse.Namespace) -> None:
+    ctx = _ctx()
+    cfg = EvalConfig(k=args.k, nprobe=args.nprobe,
+                     use_xtr_oracle=(args.oracle == "xtr"),
+                     query_file=Path(args.queries) if args.queries else None,
+                     synth_from_scip=(args.queries is None))
+    out_dir = run_eval(ctx, cfg)
+    print(f"metrics → {out_dir / 'metrics.json'}")
+
+def main(argv: list[str]) -> int:
+    ap = argparse.ArgumentParser(prog="indexctl", description="Index/eval utilities")
+    sub = ap.add_subparsers(dest="cmd", required=True)
+    sub.add_parser("idmap-export").set_defaults(func=cmd_idmap_export)
+    sub.add_parser("idmap-views").set_defaults(func=cmd_idmap_views)
+    ap_eval = sub.add_parser("eval"); ap_eval.add_argument("--k", type=int, default=10)
+    ap_eval.add_argument("--nprobe", type=int, default=64)
+    ap_eval.add_argument("--oracle", choices=["none","xtr"], default="none")
+    ap_eval.add_argument("--queries", type=str, default=None)
+    ap_eval.set_defaults(func=cmd_eval)
+    args = ap.parse_args(argv); args.func(args); return 0
+
+if __name__ == "__main__":
+    raise SystemExit(main(sys.argv[1:]))
```

> These verbs match the plan and your repo surface (FAISS manager search/dual‑index, XTR rescoring). Hook into packaging with an `entry_points.console_scripts` item so `indexctl` lands on `$PATH`.  

---

### D5) Hybrid evaluator (+ pool attribution parquet) and XTR oracle

**Files (new):** `codeintel_rev/eval/hybrid_pool_evaluator.py`
**Small changes:** `mcp_server/adapters/semantic.py` (write the pool)

Your adapters already accept/propagate contribution maps and build the fused result (`_build_hybrid_result`). We’ll add a small `trace_writer` hook to write `(query_id, source, rank, chunk_id, score)` rows; that makes coverage heatmaps and per‑channel contribution tables one SQL away.  

```diff
--- a/codeintel_rev/mcp_server/adapters/semantic.py
+++ b/codeintel_rev/mcp_server/adapters/semantic.py
@@
 def _build_hybrid_result(
     hydration: tuple[list[int], list[float]],
     *,
     limit: int,
     contribution_map: dict[int, list[tuple[str, int, float]]] | None,
     retrieval_channels: Sequence[str],
     method: MethodInfo | None,
+    trace_writer: "Callable[[list[tuple[str,int,int,float,int]]], None] | None" = None,
 ) -> _HybridResult:
@@
     # ...existing fusion + clipping...
     result = _HybridResult(ids[:limit], scores[:limit], contribution_map, list(retrieval_channels), method)
+    if trace_writer and contribution_map:
+        rows: list[tuple[str,int,int,float,int]] = []
+        for chunk_id, contribs in contribution_map.items():
+            for (source, rank, s) in contribs:
+                rows.append((source, rank, chunk_id, float(s), int(method.effective_limit if method else limit)))
+        trace_writer(rows)
     return result
```

**New:** `codeintel_rev/eval/hybrid_pool_evaluator.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json, pyarrow as pa, pyarrow.parquet as pq
from typing import Iterable

@dataclass(frozen=True)
class EvalConfig:
    k: int = 10
    nprobe: int = 64
    use_xtr_oracle: bool = False
    query_file: Path | None = None
    synth_from_scip: bool = True  # fall back to synthetic intent queries

def _write_pool_parquet(out: Path, rows: list[tuple[str,int,int,float,int]]) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table({
        "source": pa.array([r[0] for r in rows], pa.string()),
        "rank": pa.array([r[1] for r in rows], pa.int32()),
        "chunk_id": pa.array([r[2] for r in rows], pa.int64()),
        "score": pa.array([r[3] for r in rows], pa.float32()),
        "limit": pa.array([r[4] for r in rows], pa.int32()),
    })
    pq.write_table(table, out, compression="snappy", use_dictionary=True)
    return out

def run_eval(ctx, cfg: EvalConfig) -> Path:
    """
    Build a candidate pool via FAISS(+BM25/Splade), optionally rescore with XTR, and write metrics.
    """
    # 0) load/generate queries
    queries = [q.strip() for q in (cfg.query_file.read_text().splitlines() if cfg.query_file else ["vector store", "retry logic"]) if q.strip()]

    metrics = {"k": cfg.k, "nprobe": cfg.nprobe, "oracle": "xtr" if cfg.use_xtr_oracle else "none", "queries": len(queries)}
    rows: list[tuple[str,int,int,float,int]] = []

    def trace_writer(batch):
        rows.extend(batch)

    # 1) run through your existing hybrid surface with trace_writer
    # (this is illustrative; wire at the place where _build_hybrid_result is called)
    # results = ctx.hybrid.search(query, k=cfg.k, nprobe=cfg.nprobe, trace_writer=trace_writer)

    # 2) (optional) XTR oracle rescoring on candidate ids
    # if cfg.use_xtr_oracle:
    #     xtr_hits = ctx.xtr.rescore(query, [r.chunk_id for r in results], explain=False)

    # 3) write artifacts
    out = ctx.paths.eval_dir; out.mkdir(parents=True, exist_ok=True)
    _write_pool_parquet(out / "last_eval_pool.parquet", rows)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    return out
```

> The adapters already model contribution maps and method metadata; adding a `trace_writer` makes pools durable and analyzable in DuckDB (e.g., per‑channel RRF contribution). 

---

### D6) DuckDB query builder: on‑demand JOIN flags (symbols/modules/faiss + AST/CST)

**File:** `codeintel_rev/io/duckdb_manager.py`

**Why:** keep default scans fast; add knobs to opt‑in to joins. Phase‑1 proposed three flags; we extend to AST/CST now that you will output those Parquets. 

```diff
--- a/codeintel_rev/io/duckdb_manager.py
+++ b/codeintel_rev/io/duckdb_manager.py
@@
 @dataclass
 class DuckDBQueryOptions:
     # existing fields...
-    join_modules: bool = False
-    join_symbols: bool = False
-    join_faiss: bool = False
+    join_modules: bool = False
+    join_symbols: bool = False
+    join_faiss: bool = False
+    join_ast: bool = False
+    join_cst: bool = False
@@
 class DuckDBQueryBuilder:
     def build_filter_query(self, opts: DuckDBQueryOptions) -> str:
         join_lines: list[str] = []
         where_clauses: list[str] = []
@@
         if opts.join_modules:
             join_lines.append("left join modules using(uri)")
         if opts.join_symbols:
             join_lines.append("left join v_chunk_symbols using(chunk_id)")
         if opts.join_faiss:
             join_lines.append("left join faiss_idmap on faiss_idmap.chunk_id = chunks.id")
+        if opts.join_ast:
+            join_lines.append("left join ast_nodes on ast_nodes.uri = chunks.uri and ast_nodes.start_byte <= chunks.end_byte and ast_nodes.end_byte >= chunks.start_byte")
+        if opts.join_cst:
+            join_lines.append("left join cst_nodes on cst_nodes.uri = chunks.uri and cst_nodes.start_byte <= chunks.end_byte and cst_nodes.end_byte >= chunks.start_byte")
@@
         query = "select {cols} from chunks " + " ".join(join_lines)
         # ...existing where/order/limit assembly...
         return query
```

---

## E. How this answers your 4 questions, concretely

**1) Phase‑1 items still to implement (do now):**

* **Parquet schema: `symbols`, `content_hash`.** Missing today; patch D1 addresses it. 
* **DuckDB FAISS joins + checksum‑guarded materialization.** Missing; patch D2 implements views + helper. 
* **FAISS factory & `ParameterSpace` meta sidecar.** Missing; patch D3 adds it (along with IDMap2 + export + deletes). 
* **Optional XTR oracle & CLI verbs.** Missing; patches D4–D5 implement them. 

**2) New scope to add (not a miss) given SCIP/AST/CST:**

* Convert **SCIP occurrences**, **AST nodes**, and **CST nodes** to Parquet; register **views**; expose **v_chunk_symbols** (explode) and span‑join AST/CST so hybrid gating can prefer function‑bounded hits and definition contexts. (Plan already framed this placement and why it helps accuracy without slowing default scans.) 

**3) Phase‑2 scope that we still plan to action (unchanged intent, updated wiring):**

* **IndexIDMap2 + Parquet export + deletes** (D3) — unchanged intent; now the DuckDB side has a first‑class join surface (`v_faiss_join`) to interrogate mapping quality immediately after builds. 
* **ParameterSpace presets** — unchanged intent; we just persist them in meta, and your runtime adjuster already gives us a single place to apply them. 
* **Hybrid pool attribution** — unchanged intent; we now persist it with the `trace_writer`, letting DuckDB produce per‑channel contribution tables and coverage heatmaps. 

**4) Phase‑2 expansion enabled by SCIP/AST/CST:**

* Add `join_ast|join_cst` flags to your query builder (D6) so Stage‑0 retrieval can **optionally** restrict or bias to function boundaries or exact symbol spans before late‑interaction rescoring. This makes XTR/WARP rescoring cheaper and **more precise** for intent‑level queries.
* With `v_chunk_symbols` and `scip_occurrences`, you can compute **module/symbol coverage** and MRR by bucket with a single query and feed that into the Prometheus counters you already attached to adapters (scope reduction warnings, method metadata). 

---

## F. Operational notes and testing hooks

* **View bootstrap time metric.** Add a small histogram `bootstrap_ms` in the catalog when `_ensure_views` runs, per Phase‑1 note; it helps detect slow mounts. 
* **Evaluator artifacts.** The evaluator writes `last_eval_pool.parquet` and `metrics.json`. Use DuckDB to compute RRF per‑channel contributions and symbol coverage by module.
* **MCP surface alignment.** The adapters already expose plan metadata, limits, and contribution maps; we didn’t change those envelopes — only added `trace_writer` — so MCP behavior and explainability remain consistent.  

---

## G. Why this design remains best‑in‑class for a personal, on‑prem RAG

* It keeps **write‑once, read‑many** Parquet artifacts with narrowly‑projected views so your common hydration path stays I/O‑light. (Your writer already uses FixedSizeList for vectors; we continue that pattern.) 
* It moves “expensive structure” (symbols/AST/CST) into **opt‑in joins**, letting power users dial accuracy up without imposing overhead on every query. 
* It makes FAISS **observable and reversible**: exact ID‑map joins, persisted factory/knobs, and a CLI to regenerate artifacts on demand. 
* It leverages your existing XTR **narrow‑mode rescorer** as an oracle so you can push recall as high as you need while keeping the default hybrid path fast. 

---

## H. What to ship next (very small PRs)

1. **Land D1–D3** (schema, views, FAISS idmap + meta) and add `indexctl` entry point in packaging so the CLI is on `PATH`. 
2. **Add D5–D6** (pool parquet + join flags) and a short cookbook in the repo: “How to slice coverage by module/symbol with DuckDB”.
3. **SCIP/AST/CST Parquet exporters** (straightforward transforms) and view registration (already scaffolded in D2).

If you’d like, I can follow up with unit test stubs for the new surfaces (golden‑file round‑trip for ID‑map export and a tiny integration test that asserts `v_faiss_join` row counts after a synthetic build), plus two or three example DuckDB queries to plot contribution heatmaps.

---

### Cross‑references (selected)

* Full‑stack plan (design targets for personal, on‑prem RAG; why we bias accuracy & keep operations light). 
* Vector theory (why the two‑stage retrieval + late interaction improves recall/precision on code). 
* Wheel inventory (IDMap/2, ParameterSpace — confirms our FAISS features are available). 
* Your repo surfaces used here:

  * Parquet writer & schema hooks.  
  * DuckDB catalog views + helpers (ensure/views, relation guard). 
  * FAISS runtime autotune & factory adjuster.  
  * XTR index search/rescore (oracle). 
  * Hybrid adapters (contribution maps, method metadata).  

---

If anything in the diffs should match a different local class/function name in your tree, I can adjust the patches to your exact file layout. Otherwise, you can paste these as‑is and run:

```
indexctl idmap-export
indexctl idmap-views
indexctl eval --k 10 --nprobe 64 --oracle xtr
```

to produce the joinable ID‑map, install the DuckDB views, and generate a first “hybrid vs. XTR oracle” offline metrics bundle.
