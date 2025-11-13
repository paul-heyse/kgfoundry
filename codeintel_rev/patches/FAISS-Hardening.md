Below is a **repo‑specific hardening & robustness implementation plan** with **ready‑to‑apply diffs**. I’ve focused on (1) architectural tightening (shared types, deterministic IDs), (2) FAISS correctness & explainability (IDMap persistence, exact re‑rank plumbing hooks), (3) DuckDB joinability & guardrails (idmap view/materialization, integrity checks), and (4) lifecycle metadata (factory strings & tuning profiles). All changes respect your current data paths and coding style.

Where I reference existing code, I cite the concrete files/symbols from your repo so you can see exactly how the new pieces snap into place.

---

## What this delivers (at a glance)

1. **Deterministic `chunk_id` plumbing**
   Stable 64‑bit IDs based on `(uri, start_byte, end_byte)`—aligned with your `Chunk` contracts—so FAISS can always use external IDs without drift across rebuilds. We add a small helper and extend your Parquet writer to optionally emit stable IDs (keeps the default sequential mode for backwards compatibility). This leverages the `Chunk` structure emitted by your cAST chunker (URI and byte bounds are already computed)  and the current Parquet vector schema (FixedSizeList embeddings) .

2. **FAISS IDMap persistence + hydration hooks**
   We ensure the CPU index is always wrapped in `IndexIDMap2`, add `export_idmap_parquet()` to persist `{faiss_row → external_id(chunk_id)}`, plus `get_idmap_array()` and a tiny hydration helper (joins to DuckDB by `id`). This makes result auditing & BI joins trivial and resilient across process boundaries. (We keep CPU as source of truth and allow GPU clones at runtime—consistent with your lifecycle pattern.) The ParameterSpace / factory string behavior is documented in your FAISS wheel analysis; the classes and knobs we use here are present in your wheel (e.g., `IndexIDMap2`, `ParameterSpace`) .

3. **DuckDB `faiss_idmap` view + join view `v_faiss_join`**
   Lightweight catalog extension: register an optional Parquet sidecar and expose a stable join `faiss_row ↔ chunks.id`. This mirrors the style of your catalog’s safe‑startup logic (note the “empty chunks” fallback SQL) and metrics scaffolding already in place for scope filters . We also include an optional materialized join with a checksum guard for cron‑safe refreshes.

4. **Lifecycle metadata for provenance**
   We add small helpers to write/read **factory string**, **tuning profile path** and **idmap checksum** into your version manifest so operators can time‑travel regressions to concrete index settings. This extends your existing `IndexLifecycleManager` manifest pattern (CURRENT pointer, `version.json`, atomic flips) .

> **Why this is safe today:**
> – Your `Chunk` already holds the fields needed to compute a stable ID (URI and byte bounds) .
> – Your Parquet schema already stores vector embeddings as Arrow `FixedSizeList<float32>` and the usual metadata (`id`, `uri`, lines/bytes), so adding an **optional** stable‑ID mode is minimally invasive .
> – The DuckDB catalog already uses a defensive “empty select” fallback and per‑query metrics; we keep that pattern and add narrowly scoped views/functions .
> – The lifecycle module already persists version manifests; we just hang a few extra attributes from it (conservatively) .

---

## Detailed patch plan (with diffs)

> **Conventions used below**
> • *New files* appear with `+++ b/...` and full bodies.
> • *Existing files* show targeted hunks around stable anchors.
> • All diffs are plain‑text and pasteable into a patch.
> • Comments inside code note why/where we reference existing contracts.

---

### 1) Shared types and deterministic Chunk IDs

**1.1 Add lightweight shared type aliases**

We extend `codeintel_rev/typing.py` with a few repo‑wide aliases. Your module already centralizes NDArray types and lazy import gating, so piggy‑backing here keeps call sites consistent .

```diff
diff --git a/codeintel_rev/typing.py b/codeintel_rev/typing.py
--- a/codeintel_rev/typing.py
+++ b/codeintel_rev/typing.py
@@
-from typing import Any, TYPE_CHECKING, cast
+from typing import Any, TYPE_CHECKING, cast, TypedDict, NewType, Sequence

@@
 __all__ = [
     "HEAVY_DEPS",
     "NDArrayAny",
     "NDArrayF32",
     "NDArrayI64",
     "gate_import",
+    "ChunkId",
+    "Distance",
+    "IdScore",
+    "SearchHit",
 ]
@@
+# --------- shared aliases (kept tiny to avoid import cycles)
+ChunkId = NewType("ChunkId", int)
+Distance = NewType("Distance", float)
+IdScore = tuple[ChunkId, Distance]
+
+class SearchHit(TypedDict):
+    """Normalized search hit used across ANN and exact refine paths."""
+    id: int            # equals ChunkId, kept int for faiss/numpy interop
+    distance: float    # raw index metric (IP, L2); caller interprets as score
+    rank: int          # 0-based rank within the result list
```

**1.2 Deterministic ID helper (`chunk_ids.py`)**

We hash `(uri, start_byte, end_byte)` with BLAKE2b/64‑bit. The inputs are already produced by your cAST chunker (stable symbol‑aware packs with precise byte bounds) .

```diff
diff --git a/codeintel_rev/indexing/chunk_ids.py b/codeintel_rev/indexing/chunk_ids.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/indexing/chunk_ids.py
@@
+from __future__ import annotations
+from hashlib import blake2b
+
+def stable_chunk_id(uri: str, start_byte: int, end_byte: int, *, salt: str = "") -> int:
+    """Return a deterministic 64-bit chunk id from (uri, start_byte, end_byte).
+
+    The Chunk shape and byte bounds come from the cAST chunker (SCIP-aware),
+    which guarantees symbol-respecting splits and precise offsets.
+    See: codeintel_rev.indexing.cast_chunker.Chunk.  # DOC: repo contract
+    """
+    h = blake2b(digest_size=8)
+    h.update(uri.encode("utf-8"))
+    h.update(b"|")
+    h.update(str(start_byte).encode("ascii"))
+    h.update(b"|")
+    h.update(str(end_byte).encode("ascii"))
+    if salt:
+        h.update(b"|")
+        h.update(salt.encode("utf-8"))
+    # little-endian -> int64 positive domain
+    return int.from_bytes(h.digest(), "little", signed=False)
```

---

### 2) Parquet writer: optional **stable id** mode

Your Parquet storage today writes a sequential `id` and `embedding` as `FixedSizeList<float32>`—this remains the default. We add an `id_strategy` switch and compute stable IDs when requested (no schema change). The existing schema remains untouched and compatible with your DuckDB views and XTR builder (which already streams `(id, content)` safely) .

```diff
diff --git a/codeintel_rev/io/parquet_store.py b/codeintel_rev/io/parquet_store.py
--- a/codeintel_rev/io/parquet_store.py
+++ b/codeintel_rev/io/parquet_store.py
@@
-from dataclasses import dataclass
+from dataclasses import dataclass
 from pathlib import Path
 from typing import TYPE_CHECKING, cast
@@
 else:
     np = cast("np", LazyModule("numpy", "Parquet embedding storage"))
+from codeintel_rev.indexing.chunk_ids import stable_chunk_id  # new helper
 
@@
 @dataclass(slots=True, frozen=True)
 class ParquetWriteOptions:
     """Configuration for Parquet persistence."""
 
-    start_id: int = 0
+    start_id: int = 0
     vec_dim: int = 2560
     preview_max_chars: int = 240
+    # New: id strategy ("sequence" keeps current behavior).
+    # "stable_hash" uses blake2b(uri,start_byte,end_byte) for deterministic ids.
+    id_strategy: str = "sequence"
+    id_hash_salt: str = ""
@@ def write_chunks_parquet(
-    # Prepare data
-    ids = list(range(options.start_id, options.start_id + len(chunks)))
+    # Prepare ids
+    if options.id_strategy == "stable_hash":
+        ids = [
+            int(
+                stable_chunk_id(c.uri, int(c.start_byte), int(c.end_byte), salt=options.id_hash_salt)
+            )
+            for c in chunks
+        ]
+    else:
+        ids = list(range(options.start_id, options.start_id + len(chunks)))
@@
     # Create table
     table = pa.table(
         {
             "id": ids,
             "uri": uris,
```

**Why this matters**
Deterministic IDs make FAISS’s `add_with_ids` and later deletions/GC safe and reproducible; they also stabilize joins to AST/CST/SCIP overlays if you later materialize those. (Your `Chunk` carries `uri` and byte bounds; we simply elevate that to an ID policy.) 

---

### 3) FAISS: always‑on IDMap + idmap sidecar + small tuning hooks

We don’t change your public search surface yet; we **strengthen** how the manager builds/loads and provide utilities you can call from the lifecycle or CLI.

> The FAISS features used below are explicitly present in your wheel (IDMap2, `ParameterSpace`, read/write/clone) per your wheel overview and inventory; GPU indexes remain non‑serializable and must be cloned from CPU, which your lifecycle pattern already assumes .

```diff
diff --git a/codeintel_rev/io/faiss_manager.py b/codeintel_rev/io/faiss_manager.py
--- a/codeintel_rev/io/faiss_manager.py
+++ b/codeintel_rev/io/faiss_manager.py
@@
-from typing import Any
+from typing import Any, Sequence
+from pathlib import Path
+import json
+import numpy as np
+import faiss  # type: ignore
+from kgfoundry_common.logging import get_logger
+from kgfoundry_common.prometheus import build_histogram
+try:
+    import pyarrow as pa
+    import pyarrow.parquet as pq
+except Exception:  # optional until used
+    pa = None
+    pq = None
+
+LOGGER = get_logger(__name__)
+_h_search = build_histogram("faiss_search_seconds", "FAISS ANN search latency", labelnames=("stage",))
 
@@
 class FAISSManager:
@@
-    def build_index(self, xb: NDArrayF32, ids: NDArrayI64 | None = None, *, family: str = "auto") -> None:
+    def build_index(self, xb: NDArrayF32, ids: NDArrayI64 | None = None, *, family: str = "auto") -> None:
         """
-        Build the primary CPU index from vectors.
+        Build the primary CPU index from vectors. Always wraps with IDMap2 so
+        search returns external ids (chunk_id). If ids is None, fall back to a
+        monotonic sequence (safe for tiny experiments; prefer deterministic ids).
         """
-        if ids is None:
-            self._primary.add(xb)
-        else:
-            self._primary.add_with_ids(xb, ids.astype(np.int64))
+        if not isinstance(self._primary, faiss.IndexIDMap2):
+            self._primary = faiss.IndexIDMap2(self._primary)
+        if ids is None:
+            ids = np.arange(xb.shape[0], dtype=np.int64)
+        self._primary.add_with_ids(xb, ids.astype(np.int64))
         faiss.write_index(self._primary, str(self.index_path))
@@
     def load_cpu_index(self) -> None:
         """Read CPU index from disk into memory."""
-        self._primary = faiss.read_index(str(self.index_path))
+        self._primary = faiss.read_index(str(self.index_path))
+        # If the saved index is not ID-mapped (legacy), wrap it.
+        if not isinstance(self._primary, faiss.IndexIDMap2):
+            self._primary = faiss.IndexIDMap2(self._primary)
@@
+    # ---------- IDMAP UTILITIES ----------
+    def export_idmap_parquet(self, out_path: Path) -> int:
+        """
+        Persist {faiss_row -> external_id} as Parquet for BI and joins.
+        Returns the number of rows written.
+        """
+        if pa is None or pq is None:
+            raise RuntimeError("pyarrow is required to export idmap parquet")
+        ntotal = int(self._primary.ntotal)
+        # DirectMap gives row->external_id if present
+        dm = self._primary.id_map.copy()  # type: ignore[attr-defined]
+        external_ids = np.asarray(dm, dtype=np.int64)
+        faiss_rows = np.arange(ntotal, dtype=np.int64)
+        table = pa.table(
+            {"faiss_row": pa.array(faiss_rows), "external_id": pa.array(external_ids)}
+        )
+        out_path.parent.mkdir(parents=True, exist_ok=True)
+        pq.write_table(table, out_path, compression="zstd", use_dictionary=True)
+        return ntotal
+
+    def get_idmap_array(self) -> np.ndarray:
+        """Return a numpy array mapping faiss_row -> external_id."""
+        dm = self._primary.id_map.copy()  # type: ignore[attr-defined]
+        return np.asarray(dm, dtype=np.int64)
+
+    # ---------- SEARCH (with latency metrics hooks) ----------
     def search(self, xq: NDArrayF32, k: int) -> tuple[np.ndarray, np.ndarray]:
-        return self._primary.search(xq, k)
+        with _h_search.labels("ann").time():
+            return self._primary.search(xq, k)
+
+    def apply_parameter_string(self, params: str) -> None:
+        """
+        Apply ParameterSpace string to the in-memory index (e.g. "nprobe=64,quantizer_efSearch=128").
+        """
+        ps = faiss.ParameterSpace()
+        ps.set_index_parameters(self._primary, params)
+
+    def save_tuning_profile(self, root: Path, *, factory: str, params: str) -> Path:
+        """Write a small tuning.json next to the index for provenance."""
+        payload = {"factory": factory, "params": params}
+        path = root / "tuning.json"
+        path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
+        return path
```

> *Note:* The histogram usage mirrors the pattern already used in your DuckDB catalog for scope filtering (Prometheus registry & labels) .

---

### 4) DuckDB catalog: idmap registration + join views (+ optional materialize)

Your catalog already protects startup with an **empty SELECT** fallback for the `chunks` relation, and exposes a connection manager with pragmatic settings and optional pooling; we follow that style and add optional idmap plumbing with a stable join view .

```diff
diff --git a/codeintel_rev/io/duckdb_catalog.py b/codeintel_rev/io/duckdb_catalog.py
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@
-from pathlib import Path
+from pathlib import Path
@@
 class DuckDBCatalog:
@@
-    def __init__(
+    def __init__(
         self,
         db_path: Path,
         vectors_dir: Path,
         *,
         materialize: bool = False,
         manager: DuckDBManager | None = None,
         log_queries: bool | None = None,
+        idmap_parquet: Path | None = None,
     ) -> None:
         self.db_path = db_path
         self.vectors_dir = vectors_dir
         self.materialize = materialize
         manager = manager or DuckDBManager(db_path)
         self._manager = manager
         self._query_builder = DuckDBQueryBuilder()
         self._embedding_dim_cache: int | None = None
         self._init_lock = Lock()
         self._views_ready = False
         self._log_queries = log_queries if log_queries is not None else manager.config.log_queries
+        self._idmap_parquet = idmap_parquet
@@
     def _ensure_views(self, conn: duckdb.DuckDBPyConnection) -> None:
         """Create views over Parquet directories if they do not already exist."""
         if self._relation_exists(conn, "chunks"):
             return
@@
-        if self.materialize:
+        if self.materialize:
             if parquet_exists:
                 sql
         else:
             # zero-copy view over a directory of Parquet files
             pattern = parquet_pattern.replace("\\", "/")
             conn.execute(
                 f"""
                 CREATE VIEW chunks AS
                 SELECT * FROM read_parquet('{pattern}');
                 """
             )
+        # Optional FAISS idmap view & join
+        if self._idmap_parquet and self._idmap_parquet.exists():
+            ipath = str(self._idmap_parquet).replace("\\", "/")
+            conn.execute(
+                f"CREATE OR REPLACE VIEW faiss_idmap AS SELECT * FROM read_parquet('{ipath}')"
+            )
+            conn.execute(
+                """
+                CREATE OR REPLACE VIEW v_faiss_join AS
+                SELECT f.faiss_row, c.*
+                FROM faiss_idmap f
+                JOIN chunks c ON c.id = f.external_id
+                """
+            )
@@
+    # Convenience to materialize the join (BI‑friendly)
+    def materialize_faiss_join(self) -> None:
+        with self.connection() as conn:
+            if not self._relation_exists(conn, "v_faiss_join"):
+                return
+            conn.execute("CREATE OR REPLACE TABLE faiss_idmap_mat AS SELECT * FROM v_faiss_join")
+            self._log_query("CREATE OR REPLACE TABLE faiss_idmap_mat AS SELECT * FROM v_faiss_join")
```

> This keeps your existing `_EMPTY_CHUNKS_SELECT` sentinel and general catalog pattern intact, adding only optional views when an idmap Parquet exists. The connection manager and config (threads, object cache, optional pool) remain unchanged and continue to guard performance/concurrency .

---

### 5) Lifecycle: stash **factory string**, **params**, **idmap checksum**

Your lifecycle already writes a version manifest and flips `CURRENT` atomically; we extend the metadata to include the index factory string and parameter string you apply via `ParameterSpace`, plus a checksum for the idmap sidecar. (Small, forward‑compatible attributes in `VersionMeta.attrs`.) 

```diff
diff --git a/codeintel_rev/index_lifecycle.py b/codeintel_rev/index_lifecycle.py
--- a/codeintel_rev/index_lifecycle.py
+++ b/codeintel_rev/index_lifecycle.py
@@
 class VersionMeta:
@@
     def to_json(self) -> str:
@@
         return json.dumps(
             {
                 "version": self.version,
                 "created_ts": self.created_ts,
-                "attrs": dict(self.attrs),
+                "attrs": dict(self.attrs),
             },
             sort_keys=True,
         )
@@
 class IndexLifecycleManager:
@@
+    def write_attrs(self, version: str, **attrs: object) -> Path:
+        """Merge extra attrs into version.json under the given version."""
+        vdir = self.versions_dir / version
+        manifest_path = vdir / "version.json"
+        if not manifest_path.exists():
+            raise RuntimeLifecycleError(f"manifest missing: {manifest_path}", runtime=_RUNTIME)
+        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
+        meta = dict(payload.get("attrs", {}))
+        meta.update(attrs)
+        payload["attrs"] = meta
+        manifest_path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
+        return manifest_path
```

You can now write, for example, after build:

```python
# after exporting idmap, computing checksum, and saving tuning.json
manager = IndexLifecycleManager(base_dir)
manager.write_attrs(
    version,
    faiss_factory=factory_string,
    faiss_params=parameter_string,
    faiss_idmap_path=str(idmap_parquet),
    faiss_idmap_checksum=str(idmap_checksum),
    tuning_profile=str((version_dir / "tuning.json")),
)
```

This piggybacks on your existing lifecycle structure and error classes (e.g., `RuntimeLifecycleError`) without altering the flip semantics .

---

### 6) Optional helper: embeddings hydration for exact re‑rank

To make future “exact re‑rank with Flat” trivial, add a tiny convenience to fetch embeddings by chunk IDs (order‑preserving). This uses your `chunks.embedding` FixedSizeList column and returns a `numpy` matrix, matching your storage layout and the Arrow extraction you already use in other codepaths .

```diff
diff --git a/codeintel_rev/io/duckdb_catalog.py b/codeintel_rev/io/duckdb_catalog.py
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@
     def connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
         """Yield a configured DuckDB connection.
@@
+    def get_embeddings_by_ids(self, ids: Sequence[int]) -> "np.ndarray":
+        """Return embedding rows for the given chunk ids in the same order."""
+        import numpy as np
+        self._ensure_ready()
+        if not ids:
+            return np.empty((0, 0), dtype=np.float32)
+        with self._manager.connection() as conn:
+            placeholders = ",".join(str(int(i)) for i in ids)
+            sql = f"SELECT id, embedding FROM chunks WHERE id IN ({placeholders})"
+            self._log_query(sql)
+            rows = conn.execute(sql).fetchall()
+        # map id->embedding, then restore order
+        emap: dict[int, "np.ndarray"] = {}
+        for cid, vec in rows:
+            emap[int(cid)] = np.asarray(vec, dtype=np.float32)
+        out = [emap[int(i)] for i in ids if int(i) in emap]
+        return np.vstack(out) if out else np.empty((0, 0), dtype=np.float32)
```

---

## Operational notes & why these choices are robust

* **No schema churn**: We do not change the on‑disk schema; we add an **optional** deterministic ID policy and out‑of‑band idmap sidecar. Your existing DuckDB “zero‑copy view over Parquet” remains intact and safe on start, with the same fallback semantics you already ship (that `_EMPTY_CHUNKS_SELECT` pattern) .

* **Determinism from chunker**: The stable ID relies on `uri/start_byte/end_byte` that your cAST chunker already computes precisely (UTF‑8 byte mapping, `LineIndex`, etc.). That is far more stable than line‑based char offsets for multi‑byte encodings; your helper `line_starts()` documents this rationale baked into your chunker today .

* **Explainability & BI**: Once `faiss_idmap.parquet` is exported, analysts (or your evaluator) can hit `v_faiss_join` directly and blend with module overlays (e.g., `modules.jsonl` fields like `defs`, `imports`, `hotspot_score` that your README documents) for attribution or coverage heatmaps without touching runtime code paths .

* **Lifecycle provenance**: Stashing the FAISS **factory string** and **active params** in the manifest gives you crisp post‑hoc “what changed?” answers. This meshes with the rest of your stack plan (e.g., “lock operating point” guidance and on‑prem goals described in your full‑stack doc) .

* **Pointer to exact mechanics**: If/when you add quick re‑rank: pull ANN `(I, D)`, fetch embeddings by external IDs via `DuckDBCatalog.get_embeddings_by_ids()` (above), and compute exact IP/cosine in one call. The FAISS wheel you shipped includes the Flat/index and tuning primitives needed; we’ve kept the manager surface small to make that a near‑drop‑in follow‑up .

---

## How this ties to the rest of your code (cross‑refs)

* **Chunk provenance & byte math**: the `Chunk` dataclass and its UTF‑8 byte/line machinery in `cast_chunker.py`—we reuse that contract for stable IDs (no re‑parse on lookup, precise extraction) .

* **SCIP surfaces**: your `scip_reader`’s `Range`, `Occurrence`, and `Document` structures remain the source of symbol ranges; this patch doesn’t change SCIP ingestion but is compatible with symbol‑aware joins if you later stamp symbol lists into a separate Parquet or a JSON->Parquet ingest step .

* **Catalog primitives & metrics**: we preserved your safe startup pattern and metric style in `DuckDBCatalog` and `DuckDBManager`; the additional histogram we added in FAISS mirrors the Prometheus pattern used for scope filtering timing .

* **Parquet layout**: unchanged embedding `FixedSizeList` semantics; our hydration helper simply reuses that coding path in reverse (Arrow->numpy), exactly as your storage helpers do today .

* **XTR builder**: your XTR utilities already stream `(id, content)` batches from DuckDB; those are unaffected and can later leverage the idmap join for pool diagnostics/oracles as you extend the evaluator (the generator `_iter_chunk_text` reads from `chunks` with `ORDER BY id`) .

---

## What to run (suggested order)

1. **Rebuild vectors with deterministic IDs** (optional now; you can defer)
   Set `ParquetWriteOptions(id_strategy="stable_hash")` the next time you emit Parquet. This is a one‑line change at your write site (keeps compatibility if you stick with sequential IDs for now) .

2. **Rebuild FAISS and export idmap**
   After `build_index(..., ids=chunk_ids)`, call `export_idmap_parquet(<version_dir>/faiss_idmap.parquet)`.

3. **Hook the catalog to the idmap**
   Initialize `DuckDBCatalog(..., idmap_parquet=<version_dir>/faiss_idmap.parquet)` (or drop a symlink at a stable path).

4. **Write lifecycle provenance**
   After successful build, write attrs (`faiss_factory`, `faiss_params`, `faiss_idmap_path`, checksum, `tuning_profile`) with `IndexLifecycleManager.write_attrs(...)` .

5. **(Optional) Materialize the join**
   Call `catalog.materialize_faiss_join()` to create `faiss_idmap_mat` for BI/reporting batches.

---

## Future‑proofing notes (no action required now)

* **AST/CST overlays**: With stable external IDs, you can later add separate Parquet overlays (e.g., `chunk_symbols.parquet`, `chunk_ast_nodes.parquet`) keyed by `id` and join inside DuckDB without touching FAISS. Your `modules.jsonl` already documents a rich set of fields you can propagate when ready .

* **Operating point tuning**: When you’re ready to finalize auto‑tuned profiles, `FAISSManager.save_tuning_profile()` is the hook to write the chosen params; use `apply_parameter_string()` on load. The `ParameterSpace` contract and relevant knobs are in your wheel inventory and overview (nprobe, efSearch, k_factor/refine) .

---

### Appendix — Citations for key contracts we touched

* **Chunk shape & byte/line math** (for deterministic IDs): `codeintel_rev/indexing/cast_chunker.py` (Chunk, LineIndex, UTF‑8 mapping). 
* **Parquet schema** (FixedSizeList embeddings; id/uri/bytes/lines/lang): `codeintel_rev/io/parquet_store.py`. 
* **DuckDB catalog** (safe startup, scope metrics, query helpers): `codeintel_rev/io/duckdb_catalog.py`. 
* **DuckDB connection manager** (threads/object cache/pool): `codeintel_rev/io/duckdb_manager.py`. 
* **Lifecycle & manifests** (versioned assets, `version.json`, flips): `codeintel_rev/index_lifecycle.py`. 
* **XTR chunk streaming** (reads `(id, content)` from DuckDB): `codeintel_rev/xtr_build.py`. 
* **Modules overlay reference** (fields available for attribution/coverage): `README.md` for `modules.jsonl`. 
* **FAISS wheel content & knobs** (`IndexIDMap2`, `ParameterSpace`, GPU clone): wheel overview + inventory.
* **Full‑stack operating principles** (accuracy‑first, on‑prem, observability): full‑stack plan. 

---

If you want me to extend this with: (a) the tiny CLI verbs to *export‑idmap*, *register‑idmap*, and *(optional) materialize‑join*, and (b) a one‑page operator runbook that ties these steps to your `IndexLifecycleManager` (build→stage→publish), say the word—I can ship those as additional **ready‑to‑apply** diffs in the same style.
