Perfect—below are **ready‑to‑apply, repo‑specific implementation plans and diffs** for the items you selected. I’ve aligned the patches with your current code structure and naming. Where I refer to existing surfaces, I cite the files you shared so you can see exactly where the integration points live.

> **What’s included (scope recap)**
>
> 1. **Auto‑tuned operating‑point profiles** (persisted near the FAISS index).
> 2. **Exact second‑stage re‑rank** (Flat/IP or cosine) with `k_factor`.
> 3. **Structure‑aware explainability + coverage accounting** (query‑pool sink + DuckDB join).
> 4. **IndexIDMap2 everywhere + persisted id‑map sidecar**.
> 5. **Safe GPU replication** (CPU persisted, GPU cloned at runtime).
> 6. **Observability** (ANN and refine latencies + kept‑ratio).
> 7. **XTR “oracle lens” hook** for offline recall@K.

## I. Glue points we’re building on

* **DuckDB catalog**: provides a managed connection and views over the Parquet chunk store. We’ll add minimal helpers to fetch embeddings by ids and to register an `idmap` join view. 
* **Parquet store schema**: `chunks` table has `id`, `uri`, ranges, and **`embedding` as FixedSizeList(float32)**. We’ll reuse this to hydrate vectors for exact re‑rank. 
* **Lifecycle manager**: publishes a version directory with a JSON manifest; we’ll persist `tuning.json` and the `*.idmap.parquet` sidecar into the same version dir. 
* **SCIP/cAST chunker**: your chunks carry `id`, `uri`, byte/line bounds and `language`—these are what we will attribute in the “pool” explainability tables. 
* **XTR builder**: streams `(chunk_id, content)` out of DuckDB; we’ll optionally reuse that plumbing to evaluate oracle recall offline. 
* **Modules metadata (modules.jsonl)**: per‑module tags/metrics we can join for coverage heatmaps via DuckDB once the pool tables are written. 
* **Your FAISS wheel**: exposes `IndexIDMap2`, IVF/HNSW, `ParameterSpace`, `OperatingPoints`, CPU↔GPU cloners, and graph indexes (incl. CAGRA). That enables the IDMap2, tuning, and GPU replication features below.

## II. Configuration: add knobs we’ll need

**Patch A — extend `IndexConfig`** (search‑time knobs + refine + autotune flags)

```diff
diff --git a/codeintel_rev/config/settings.py b/codeintel_rev/config/settings.py
--- a/codeintel_rev/config/settings.py
+++ b/codeintel_rev/config/settings.py
@@
-from msgspec import Struct
+from msgspec import Struct
+from typing import Literal
@@
 class IndexConfig(Struct, frozen=True):
-    """Index parameters for vector and token indexes."""
-    vec_dim: int
+    """
+    Index parameters for vector and token indexes.
+    Defaults bias to accuracy-first small systems.
+    """
+    vec_dim: int
+    faiss_family: Literal["auto","flat","ivf_flat","ivf_pq","hnsw","ivf_pq_refine"] = "auto"
+    nlist: int = 4096
+    pq_m: int = 64
+    pq_nbits: int = 8
+    opq_m: int = 16
+    hnsw_M: int = 32
+    hnsw_efConstruction: int = 200
+    default_k: int = 12
+    default_nprobe: int = 64
+    hnsw_efSearch: int = 128
+    refine_k_factor: float = 2.0
+    use_gpu: bool = True
+    gpu_clone_mode: Literal["replicate","shard"] = "replicate"
+    autotune_on_start: bool = True
+    semantic_min_score: float = 0.45
```

## III. FAISSManager: IDMap2, export id‑map, exact re‑rank hooks, auto‑tune, GPU clone

> You already persist the CPU index and manage runtime loading; below, we **force an `IndexIDMap2` wrapper**, add **id‑map export**, expose **apply/save/load tuning profiles**, and **instrument search**. GPU clones are created after training or on load; only the CPU index is persisted (FAISS GPU is not serializable). 

**Patch B — `codeintel_rev/io/faiss_manager.py`**

```diff
diff --git a/codeintel_rev/io/faiss_manager.py b/codeintel_rev/io/faiss_manager.py
--- a/codeintel_rev/io/faiss_manager.py
+++ b/codeintel_rev/io/faiss_manager.py
@@
 from __future__ import annotations
-from typing import Any
+from typing import Any, Sequence, Mapping
+from pathlib import Path
+import json
+import numpy as np
 import faiss  # type: ignore
+from kgfoundry_common.prometheus import build_histogram
+try:
+    import pyarrow as pa
+    import pyarrow.parquet as pq
+except Exception:  # pragma: no cover
+    pa = None  # type: ignore
+    pq = None  # type: ignore
@@
+_ann_latency = build_histogram(
+    "faiss_ann_search_duration_seconds",
+    "FAISS ANN search duration", labelnames=("family",)
+)
+_refine_latency = build_histogram(
+    "faiss_refine_duration_seconds",
+    "Exact rerank duration", labelnames=()
+)
+_kept_ratio = build_histogram(
+    "faiss_refine_kept_ratio",
+    "Post-filter kept ratio (k/K')", labelnames=()
+)
+
 class FAISSManager:
@@
-    def build_index(self, xb: NDArrayF32, ids: NDArrayI64 | None = None, *, family: str = "auto") -> None:
+    def build_index(self, xb: NDArrayF32, ids: NDArrayI64 | None = None, *, family: str = "auto") -> None:
         """
         Build the primary CPU index from vectors.
         """
         # ... factory selection omitted for brevity ...
-        if ids is None:
-            self._primary.add(xb)
-        else:
-            self._primary.add_with_ids(xb, ids.astype(np.int64))
+        # Always wrap with IDMap2 so external ids == chunk_id
+        if not isinstance(self._primary, faiss.IndexIDMap2):
+            self._primary = faiss.IndexIDMap2(self._primary)
+        if ids is None:
+            ids = np.arange(xb.shape[0], dtype=np.int64)
+        self._primary.add_with_ids(xb.astype(np.float32, copy=False), ids.astype(np.int64))
         faiss.write_index(self._primary, str(self.index_path))
+        # Optionally prepare a GPU clone for runtime search (persist CPU only)
+        if self._settings.index.use_gpu:
+            self._clone_to_gpu_safely()
@@
     def load_cpu_index(self) -> None:
-        self._primary = faiss.read_index(str(self.index_path))
+        self._primary = faiss.read_index(str(self.index_path))
+        if not isinstance(self._primary, faiss.IndexIDMap2):
+            self._primary = faiss.IndexIDMap2(self._primary)
+        if self._settings.index.use_gpu:
+            self._clone_to_gpu_safely()
+
+    # -------------------- ID map export / hydration --------------------
+    def get_idmap_array(self) -> np.ndarray:
+        """Return the FAISS row -> external_id (chunk_id) vector."""
+        idmap = faiss.extract_index_id_map(self._primary).id_map  # vector<idx_t>
+        return faiss.vector_to_array(idmap).astype(np.int64, copy=False)
+
+    def export_idmap_parquet(self, path: Path) -> int:
+        """Persist {faiss_row -> external_id} as Parquet sidecar."""
+        if pa is None or pq is None:
+            raise RuntimeError("pyarrow missing; cannot export idmap")
+        arr = self.get_idmap_array()
+        table = pa.table({"faiss_row": np.arange(arr.size, dtype=np.int64),
+                          "external_id": arr})
+        path.parent.mkdir(parents=True, exist_ok=True)
+        pq.write_table(table, path, compression="zstd", use_dictionary=True)
+        return arr.size
+
+    # -------------------- Tuning profile I/O --------------------
+    def apply_parameters(self, params: str) -> None:
+        """Apply ParameterSpace string (e.g., 'nprobe=64,quantizer_efSearch=128')."""
+        ps = faiss.ParameterSpace()
+        ps.set_index_parameters(self._primary, params)
+        if self._gpu is not None:
+            ps.set_index_parameters(self._gpu, params)
+
+    def save_tuning_profile(self, dst: Path, *, profile: Mapping[str, Any]) -> None:
+        dst.write_text(json.dumps(profile, sort_keys=True, indent=2), encoding="utf-8")
+
+    def load_tuning_profile(self, src: Path) -> dict[str, Any] | None:
+        if not src.exists():
+            return None
+        return json.loads(src.read_text(encoding="utf-8"))
+
+    # -------------------- Search + optional refine --------------------
+    def search(self, xq: NDArrayF32, k: int, *, refine_k_factor: float | None = None) -> tuple[np.ndarray, np.ndarray]:
+        """Primary search with optional exact rerank (Flat over original vectors)."""
+        family = getattr(self._settings.index, "faiss_family", "auto")
+        with _ann_latency.labels(family).time():
+            D, I = self._runtime_index().search(xq.astype(np.float32, copy=False), k=int(k))
+        rkf = refine_k_factor or self._settings.index.refine_k_factor
+        if rkf and rkf > 1.0:
+            Kprime = max(k, int(k * rkf))
+            with _ann_latency.labels(family).time():
+                Dp, Ip = self._runtime_index().search(xq, Kprime)
+            with _refine_latency.time():
+                D, I = self._exact_rerank(xq, Ip, top_k=k)
+            _kept_ratio.labels().observe(k / float(Kprime))
+        return D, I
+
+    def _exact_rerank(self, xq: NDArrayF32, candidates: np.ndarray, *, top_k: int) -> tuple[np.ndarray, np.ndarray]:
+        """
+        Fetch candidate embeddings from DuckDB and compute exact IP/cosine to return top_k.
+        Implemented in codeintel_rev.retrieval.rerank_flat.
+        """
+        from codeintel_rev.retrieval.rerank_flat import exact_rerank
+        return exact_rerank(self._catalog, xq, candidates, top_k=top_k)
+
+    # -------------------- GPU clone helper --------------------
+    def _runtime_index(self) -> faiss.Index:
+        return self._gpu if self._gpu is not None else self._primary
+
+    def _clone_to_gpu_safely(self) -> None:
+        try:
+            res = faiss.StandardGpuResources()
+            self._gpu = faiss.index_cpu_to_gpu(res, 0, self._primary)
+        except Exception:
+            self._gpu = None  # keep CPU path available
```

> **Why this shape?**
> • `IndexIDMap2` guarantees that `search()` returns your **external ids** (chunk ids), which stabilizes deletions, GC and downstream joins. Your FAISS wheel exposes this class; exporting a sidecar keeps the mapping auditable. 
> • Persisting `tuning.json` next to the index lets the lifecycle loader apply the **exact** `ParameterSpace` string and factory string for time‑travel reproducibility. 

## IV. Exact second‑stage re‑rank (Flat) + pool writer

**New file C — `codeintel_rev/retrieval/rerank_flat.py`**

```diff
diff --git a/codeintel_rev/retrieval/rerank_flat.py b/codeintel_rev/retrieval/rerank_flat.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/retrieval/rerank_flat.py
@@
+from __future__ import annotations
+from typing import Sequence, Tuple
+import numpy as np
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from kgfoundry_common.prometheus import build_histogram
+
+_sim_latency = build_histogram("faiss_flat_rerank_seconds", "Exact similarity compute")
+
+def exact_rerank(
+    catalog: DuckDBCatalog,
+    xq: np.ndarray,              # (1, d) or (B, d)
+    candidate_ids: np.ndarray,   # (1, K') or (B, K')
+    *,
+    top_k: int,
+    metric: str = "ip",          # "ip" or "cos"
+) -> Tuple[np.ndarray, np.ndarray]:
+    """
+    Hydrate embeddings for candidate ids via DuckDB and compute exact sims.
+    Returns (D, I) shaped like FAISS search.
+    """
+    xq = np.ascontiguousarray(xq, dtype=np.float32)
+    if xq.ndim == 1:
+        xq = xq[None, :]
+    B, d = xq.shape
+    C = candidate_ids.shape[1]
+    with _sim_latency.time():
+        # Flatten candidates across batch and fetch unique ids once
+        flat = candidate_ids.reshape(-1)
+        uniq, inv = np.unique(flat, return_inverse=True)
+        embs = catalog.get_embeddings_by_ids(uniq)  # (U, d)
+        # Build (B, C, d) candidate matrix by indexing into uniq
+        cand = embs[inv].reshape(B, C, d)
+        q = xq[:, None, :]  # (B, 1, d)
+        if metric == "cos":
+            # normalize candidates and queries defensively
+            q = q / (np.linalg.norm(q, axis=2, keepdims=True) + 1e-9)
+            cand = cand / (np.linalg.norm(cand, axis=2, keepdims=True) + 1e-9)
+        # (B, C)
+        sims = np.einsum("bid,bid->bi", cand, np.broadcast_to(q, cand.shape), optimize=True)
+        # Top-k per row
+        topk_idx = np.argpartition(-sims, kth=min(top_k, C - 1), axis=1)[:, :top_k]
+        row = np.arange(B)[:, None]
+        topk_scores = sims[row, topk_idx]
+        # sort within top-k
+        order = np.argsort(-topk_scores, axis=1)
+        topk_idx = topk_idx[row, order]
+        topk_scores = topk_scores[row, order]
+        # Map candidate column indices back to ids
+        topk_ids = candidate_ids[row, topk_idx]
+        return topk_scores.astype(np.float32), topk_ids.astype(np.int64)
```

* The reranker **pulls embeddings** from DuckDB and computes exact IP or cosine—no FAISS rebuilds needed, and it reuses your existing Parquet schema.

**New file D — `codeintel_rev/eval/pool_writer.py`** (per‑query pool + explainability)

```diff
diff --git a/codeintel_rev/eval/pool_writer.py b/codeintel_rev/eval/pool_writer.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/eval/pool_writer.py
@@
+from __future__ import annotations
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Iterable, Sequence
+import pyarrow as pa
+import pyarrow.parquet as pq
+
+SCHEMA = pa.schema([
+    pa.field("run_id", pa.string()),
+    pa.field("query_id", pa.string()),
+    pa.field("channel", pa.string()),       # "faiss", "bm25", "splade", etc.
+    pa.field("rank", pa.int32()),
+    pa.field("chunk_id", pa.int64()),
+    pa.field("score", pa.float32()),
+    pa.field("explain_symbols", pa.list_(pa.string())),
+    pa.field("explain_ast_kinds", pa.list_(pa.string())),
+    pa.field("explain_cst_hits", pa.list_(pa.string())),
+])
+
+def write_pool_parquet(dst: Path, rows: Iterable[dict]) -> int:
+    """
+    Persist a query-pool with minimal explainability fields.
+    """
+    batch = pa.Table.from_pylist(list(rows), schema=SCHEMA)
+    dst.parent.mkdir(parents=True, exist_ok=True)
+    pq.write_table(batch, dst, compression="zstd", use_dictionary=True)
+    return batch.num_rows
```

## V. DuckDB: embedding fetch + FAISS id‑map join

**Patch E — `codeintel_rev/io/duckdb_catalog.py`** (add embedding fetch; register idmap join)

```diff
diff --git a/codeintel_rev/io/duckdb_catalog.py b/codeintel_rev/io/duckdb_catalog.py
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@
 class DuckDBCatalog:
@@
     def _ensure_views(self, conn: duckdb.DuckDBPyConnection) -> None:
         """Create views over Parquet directories if they do not already exist."""
         if self._relation_exists(conn, "chunks"):
             return
@@
         # existing chunks view/materialization logic...
@@
+    # -------- new helpers --------
+    def get_embeddings_by_ids(self, ids: Sequence[int]) -> "np.ndarray":
+        """
+        Return embeddings for a set of chunk ids as (N, d) float32.
+        """
+        import numpy as np
+        id_list = list({int(i) for i in ids})
+        if not id_list:
+            return np.empty((0, 0), dtype=np.float32)
+        sql = """
+            SELECT id, embedding
+            FROM chunks
+            WHERE id IN (SELECT * FROM UNNEST(?))
+            ORDER BY id
+        """
+        with self.connection() as conn:
+            cur = conn.execute(sql, [id_list])
+            rows = cur.fetchall()
+        # rows: List[Tuple[int, List[float]]], FixedSizeList returns Python list
+        rows.sort(key=lambda r: r[0])
+        embs = np.asarray([np.asarray(v, dtype=np.float32) for _, v in rows], dtype=np.float32)
+        return embs
+
+    def ensure_idmap_view(self, idmap_parquet: Path) -> None:
+        """
+        Register v_faiss_idmap and v_faiss_join to audit {faiss_row -> chunk_id}.
+        """
+        with self.connection() as conn:
+            self._log_query("CREATE OR REPLACE VIEW v_faiss_idmap AS SELECT * FROM read_parquet(?)", [str(idmap_parquet)])
+            conn.execute("CREATE OR REPLACE VIEW v_faiss_idmap AS SELECT * FROM read_parquet(?)", [str(idmap_parquet)])
+            self._log_query(
+                "CREATE OR REPLACE VIEW v_faiss_join AS "
+                "SELECT c.*, m.faiss_row FROM chunks c LEFT JOIN v_faiss_idmap m ON c.id = m.external_id"
+            )
+            conn.execute(
+                "CREATE OR REPLACE VIEW v_faiss_join AS "
+                "SELECT c.*, m.faiss_row FROM chunks c LEFT JOIN v_faiss_idmap m ON c.id = m.external_id"
+            )
```

* Embeddings are **pulled directly from `chunks.embedding`**, which you already materialize/view in DuckDB; we keep zero‑copy semantics where possible.
* The id‑map view allows BI/coverage join queries and **per‑module coverage** (by joining `v_faiss_join` to your module metadata), supporting the explainability tables. 

## VI. Auto‑tuned operating point profiles

We sweep `nprobe` (IVF) and/or `efSearch` (HNSW), measure **oracle‑recall@k versus exact Flat**, pick the best point and persist **`tuning.json`** next to the index. (For tiny repos we can brute‑force with a temporary Flat over all vectors; for bigger ones, you can use a *sampled* Flat or your XTR oracle lens). Your FAISS wheel supports `ParameterSpace` and `OperatingPoints`. 

**New file F — `codeintel_rev/eval/autotune.py`**

```diff
diff --git a/codeintel_rev/eval/autotune.py b/codeintel_rev/eval/autotune.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/eval/autotune.py
@@
+from __future__ import annotations
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Iterable
+import json
+import numpy as np
+import faiss
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.io.faiss_manager import FAISSManager
+from codeintel_rev.retrieval.rerank_flat import exact_rerank
+
+@dataclass(frozen=True)
+class TuningResult:
+    params: str
+    recall_at_k: float
+    latency_ms: float
+
+def quick_sweep(
+    manager: FAISSManager,
+    catalog: DuckDBCatalog,
+    queries: np.ndarray,    # (Q, d), normalized to metric
+    k: int,
+    *,
+    candidates_k_factor: float = 2.0,
+    nprobe_grid: tuple[int, ...] = (8, 16, 32, 64, 128),
+    ef_grid: tuple[int, ...] = (64, 96, 128, 192),
+    use_hnsw: bool | None = None,
+) -> dict:
+    """
+    Sweep search-time knobs and pick Pareto-optimal point vs Flat oracle.
+    """
+    fam = manager._settings.index.faiss_family
+    use_hnsw = (fam == "hnsw") if use_hnsw is None else use_hnsw
+    # Build a temporary Flat exact index as oracle (small corpora assumption)
+    # Alternatively, sample or use XTR oracle for larger repos.
+    with catalog.connection() as conn:
+        rows = conn.execute("SELECT id, embedding FROM chunks ORDER BY id").fetchall()
+    xb = np.asarray([np.asarray(v, dtype=np.float32) for _, v in rows], dtype=np.float32)
+    flat = faiss.IndexFlatIP(xb.shape[1])
+    flat.add(xb)
+
+    def eval_point(param_str: str) -> TuningResult:
+        ps = faiss.ParameterSpace()
+        ps.set_index_parameters(manager._runtime_index(), param_str)
+        # measure recall and latency
+        import time
+        t0 = time.perf_counter()
+        D, I = manager._runtime_index().search(queries, int(max(k, int(k * candidates_k_factor))))
+        t_ms = (time.perf_counter() - t0) * 1000.0
+        # oracle@k via Flat exact
+        Do, Io = flat.search(queries, k)
+        # recall@k
+        inter = 0
+        for i in range(queries.shape[0]):
+            inter += len(set(I[i, :k]).intersection(set(Io[i])))
+        recall = inter / float(queries.shape[0] * k)
+        return TuningResult(param_str, recall, t_ms)
+
+    grid = [f"nprobe={n}" for n in nprobe_grid] if not use_hnsw else [f"efSearch={e}" for e in ef_grid]
+    results = [eval_point(p) for p in grid]
+    # pick best recall then latency
+    results.sort(key=lambda r: (-r.recall_at_k, r.latency_ms))
+    best = results[0]
+    payload = {
+        "family": fam,
+        "picked": {"params": best.params, "recall_at_k": best.recall_at_k, "latency_ms": best.latency_ms},
+        "grid": [r.__dict__ for r in results],
+    }
+    return payload
```

* Write the chosen **profile** with `FAISSManager.save_tuning_profile(.)` and re‑apply on load with `apply_parameters(.)`. Persist the exact **factory string** and the **ParameterSpace** string to attribute future regressions. 

## VII. XTR “oracle lens” (offline)

You already have an **XTR build pipeline** that streams chunk text from DuckDB and encodes to token‑level vectors; keep using that to compute an **oracle@K** (e.g., term‑level alignment) on a dev split when desired, and report side‑by‑side with the Flat oracle results recorded by the autotuner. The hooks you need to iterate chunks are already in `xtr_build.py` (`_iter_chunk_text`), which uses the catalog we’re extending. 

## VIII. Explainability & coverage

* **Per‑query pool sink**: write `(run_id, query_id, channel, rank, chunk_id, score, explain_*)` to Parquet using `pool_writer.write_pool_parquet(.)` and then **join in DuckDB** with `v_faiss_join` and your module metadata for coverage heatmaps and “who contributed” tables.
* **ID‑map sidecar**: `FAISSManager.export_idmap_parquet(...)` writes `{faiss_row → external_id}`. Call `catalog.ensure_idmap_view(...)` at boot so the BI/SQL layer is immediately usable. 

## IX. Minimal usage wiring (lifecycle)

At the **end of a build** (or after `build_index()`), do:

```python
# Persist idmap & tuning profile
count = faiss_mgr.export_idmap_parquet(version_dir / "faiss_idmap.parquet")
faiss_mgr.save_tuning_profile(version_dir / "tuning.json", profile=autotune_payload)

# Register views at runtime
catalog.ensure_idmap_view(version_dir / "faiss_idmap.parquet")
```

This complements your existing versioned directory layout and manifest mechanics. 

## X. Optional: evaluator recording from the search path

When you issue a search (FAISS, BM25, or Splade), append pool rows:

```python
from codeintel_rev.eval.pool_writer import write_pool_parquet
rows = []
for r, (score, cid) in enumerate(zip(scores, ids)):
    rows.append({
      "run_id": run_id, "query_id": qid, "channel": "faiss",
      "rank": r+1, "chunk_id": int(cid), "score": float(score),
      "explain_symbols": list(symbols_in_snippet),  # from SCIP/cAST if present
      "explain_ast_kinds": list(ast_kinds),         # future AST/CST hooks
      "explain_cst_hits": list(cst_hits),
    })
write_pool_parquet(out_dir / "pool.parquet", rows)
```

## XI. Why these are safe changes in *your* repo

* **DuckDBCatalog** already exposes a connection manager and views; adding `get_embeddings_by_ids` and an id‑map join are **local, backward‑compatible** helpers. 
* **Parquet store** already writes embeddings as a FixedSizeList(float32), so turning those rows into NumPy arrays is straightforward and efficient. 
* **Lifecycle** already versions assets next to a manifest; we’re only adding extra files (`faiss_idmap.parquet`, `tuning.json`) to that directory. 
* **XTR** uses the same catalog to iterate chunk text and is unaffected by the changes; it just gains better evaluability. 
* **Chunk structure** (uri/byte/line/language) remains unchanged; explainability rows reference `chunk_id` and can be joined to `chunks`/`v_faiss_join` and further to module metadata. 

## XII. Operator runbook (day‑1 to day‑N)

1. **Build / publish**

   * Build FAISS (with IDMap2) → write CPU index.
   * `export_idmap_parquet` and `save_tuning_profile` into the version dir.
   * Publish version via your lifecycle manager (flip `CURRENT`). 

2. **Runtime init**

   * Catalog boots, calls `ensure_idmap_view`.
   * FAISSManager loads CPU index, clones to GPU if enabled; loads `tuning.json` and `apply_parameters`.

3. **Search**

   * FAISS ANN at K’ = `k * refine_k_factor`.
   * Exact rerank with Flat on hydrated embeddings → top‑k.
   * Record per‑query pool Parquet rows for explainability and coverage.

4. **Tuning**

   * After fresh build (or if `autotune_on_start=True`), run `quick_sweep()` on a small dev split (or your synthetic SCIP/AST queries), persist the chosen profile.

5. **Observability**

   * Dashboards: `faiss_ann_search_duration_seconds`, `faiss_refine_duration_seconds`, `faiss_refine_kept_ratio`.
   * BI SQL: `SELECT module_prefix, COUNT(*) ... FROM pool JOIN v_faiss_join ...` for coverage by module.

---

If you want me to fold these into a **single PR‑style patchset** (including small test stubs), I can produce that as well. For now, the diffs above are minimal, self‑contained, and map 1:1 to your selected goals.

**References into your codebase & artifacts**

* DuckDB catalog and query plumbing for Parquet chunks (embedding column).
* Index lifecycle directory/version manifest where we stage `tuning.json` & `faiss_idmap.parquet`. 
* cAST chunk schema used for attribution in pool rows. 
* XTR builder streaming chunk text via catalog (offline oracle lens). 
* FAISS wheel capabilities (`IndexIDMap2`, `ParameterSpace`, GPU CPU↔GPU cloners, CAGRA).

---

**What you get immediately after applying:**

* Deterministic id‑mapping for coverage & deletions, **persisted**.
* **Truth‑preserving** re‑rank with exact similarity, without re‑indexing.
* On‑disk **tuning profiles** so operating points are reproducible.
* Per‑query **explainability pools** (ready for DuckDB joins and module‑level coverage).
* **Safe GPU** runtime use with CPU‑only persistence.
* **Metrics** wired for ANN vs refine latency and kept‑ratio to monitor stability.

If you’d like, I can now add unit‑test stubs (golden file for idmap export, smoke tests for rerank, and a tiny sweep test on a toy matrix) in `tests/io` and `tests/retrieval`.
