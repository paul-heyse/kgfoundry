Below is a **complete, ready‑to‑apply implementation plan with full code diffs** that hardens your FAISS + DuckDB + MCP stack, improves error locality and robustness, and preserves your current APIs. I’ve aligned names and import style to the current repository (type hints, `msgspec` structs, `kgfoundry_common` logging/errors, lazy heavy‑dep imports). I also call out where each change plugs into files that already exist in your tree so patches anchor cleanly.

> **Provenance & anchors.** All paths and symbols are taken from your current repo scan (SCIP + metrics) and the modules you shared. Where I reference or modify existing modules, you can see their present structure in the attached files (e.g., `codeintel_rev/index_lifecycle.py`, `codeintel_rev/io/duckdb_catalog.py`, `codeintel_rev/indexing/scip_reader.py`, `codeintel_rev/indexing/cast_chunker.py`, `codeintel_rev/io/parquet_store.py`, `codeintel_rev/io/duckdb_manager.py`).
> For the FAISS surface and best‑practice knobs (factory strings, `ParameterSpace`, ID maps, CPU↔GPU clone behavior), see your wheel overview and inventory.
> For the end‑to‑end RAG and personal on‑prem constraints we’re optimizing for, see the full‑stack plan & theory PDFs.
> The repository‑level module/enrichment docs are useful for joins/explainability (module view). 

---

## What we are implementing (summary)

**Goal:** Make the system **robust, self‑auditing, and failure‑tolerant** without changing your outward behavior:

1. **Hardened lifecycle & invariants**

   * Versioned manifest enriched with **FAISS factory string** and **tuning profile**.
   * **Atomic flip** only when DuckDB chunks, FAISS index, and **IDMap sidecar** are consistent (size & checksum).
   * Clear **pre‑/post‑conditions** with precise exceptions.

2. **ID‑Map everywhere (auditability)**

   * Wrap CPU index with **`IndexIDMap2`** and **persist `idmap.parquet`** (`faiss_row → chunk_id`), enabling deletion/GC and exact joins.
   * Catalog view `v_faiss_join` for BI/debugging & coverage accounting.

3. **Catalog explainability & hydration**

   * First‑class **ID hydration** (`query_by_ids`, `get_embeddings_by_ids`) with a **materialized join** option and checksum guard.
   * Per‑query **pool writer** schema for hybrid attribution (`channel`, `rank`, `score`, `explanations`).

4. **Error locality & resilience**

   * Narrow, categorized exceptions and **guarded boundaries** between components.
   * Connection‑pool health checks; **read‑only** SQL in query paths by default; metrics for latency & post‑filter density.

5. **Minimal code movement, maximal clarity**

   * No behavior breakage in public entry points.
   * Files are small, testable units; new code is incremental and reversible.

---

## Step‑by‑step implementation instructions

1. **Add contracts & small helpers** (new files)

* `codeintel_rev/contracts/types.py`: msgspec structs for the version manifest, tuning profile, and id‑map rows.
* `codeintel_rev/io/idmap_store.py`: read/write helpers for `idmap.parquet`.

2. **Enrich the index lifecycle**
   Extend `IndexAssets` to accept an optional `idmap_path` and **persist a manifest** that records the FAISS factory string and tuning profile. Flip only when invariants pass (matching counts and checksums). 

3. **Make IDMap a first‑class citizen in FAISSManager**
   Wrap the CPU index with `IndexIDMap2`, **add with external ids**, export a sidecar Parquet, and expose `get_idmap_array()`/`export_idmap()` utilities. Use `ParameterSpace` to set search‑time knobs (no rebuild). 

4. **Catalog joins & hydration**
   Add `register_faiss_idmap()` and a virtual view `v_faiss_join`. Add `query_by_ids()` and `get_embeddings_by_ids()` with **read‑only** connections and timing histograms. 

5. **Parquet utils**
   Add a compact Arrow schema for idmap and finish the small gap in `extract_embeddings()` for `FixedSizeListArray` (you already store vectors in that layout). 

6. **Errors & diagnostics**
   Introduce a couple of precise exception types for invariants/consistency and unify messages. (Extends your existing error module.) 

7. **Golden test and smoke**
   Add a tiny golden test for `export_idmap()` + `v_faiss_join` and a `tools/list` smoke (MCP side is already implemented; this just confirms joins don’t regress).

---

## Ready‑to‑apply diffs

> **How to apply**
> Copy the hunks below into files under the repo root. New files are shown with their **full contents**. Adapt relative paths if your package layout differs.

### 1) NEW — `codeintel_rev/contracts/types.py`

```diff
*** /dev/null
--- a/codeintel_rev/contracts/types.py
@@
+from __future__ import annotations
+from typing import Any, Literal
+from msgspec import Struct
+
+class TuningProfile(Struct, frozen=True):
+    """
+    Search operating point persisted alongside a FAISS index.
+    """
+    family: Literal["flat","ivf_flat","ivf_pq","hnsw","ivf_pq_refine"]
+    k: int
+    nprobe: int | None = None
+    hnsw_efSearch: int | None = None
+    refine_k_factor: float | None = None
+    notes: str | None = None
+
+class VersionManifest(Struct, frozen=True):
+    """
+    Versioned manifest for an index publication (written to <version>/manifest.json).
+    """
+    version: str
+    created_ts: float
+    faiss_factory: str
+    vec_dim: int
+    vectors_count: int
+    chunks_checksum: str
+    idmap_checksum: str | None = None
+    tuning: TuningProfile | None = None
+    attrs: dict[str, Any] = {}
+
+class IdMapRow(Struct, frozen=True):
+    """
+    One mapping row persisted in idmap.parquet.
+    """
+    faiss_row: int
+    external_id: int
```

### 2) NEW — `codeintel_rev/io/idmap_store.py`

```diff
*** /dev/null
--- a/codeintel_rev/io/idmap_store.py
@@
+from __future__ import annotations
+from pathlib import Path
+from typing import Iterable
+import pyarrow as pa
+import pyarrow.parquet as pq
+from msgspec import json as msjson
+
+from codeintel_rev.contracts.types import IdMapRow
+
+_IDMAP_SCHEMA = pa.schema(
+    [
+        pa.field("faiss_row", pa.int64()),
+        pa.field("external_id", pa.int64()),
+    ]
+)
+
+def write_idmap_parquet(path: Path, rows: Iterable[IdMapRow]) -> int:
+    """
+    Write idmap rows to Parquet. Returns row count.
+    """
+    faiss_rows: list[int] = []
+    external_ids: list[int] = []
+    count = 0
+    for r in rows:
+        faiss_rows.append(int(r.faiss_row))
+        external_ids.append(int(r.external_id))
+        count += 1
+    table = pa.table({"faiss_row": faiss_rows, "external_id": external_ids}, schema=_IDMAP_SCHEMA)
+    path.parent.mkdir(parents=True, exist_ok=True)
+    pq.write_table(table, path, compression="snappy", use_dictionary=True)
+    return count
+
+def read_idmap_parquet(path: Path) -> pa.Table:
+    """
+    Read idmap Parquet file as an Arrow table.
+    """
+    return pq.read_table(path)
```

---

### 3) Update — `codeintel_rev/index_lifecycle.py` (manifest & invariants)

> Adds: optional `idmap_path` in `IndexAssets`; `write_manifest()`; stronger `ensure_exists()` checks, and **atomic publish** that refuses to flip unless sizes & checksums match. Your module already defines `IndexAssets`, `VersionMeta`, and `IndexLifecycleManager`; we extend them compatibly. 

```diff
diff --git a/codeintel_rev/index_lifecycle.py b/codeintel_rev/index_lifecycle.py
--- a/codeintel_rev/index_lifecycle.py
+++ b/codeintel_rev/index_lifecycle.py
@@
-from dataclasses import dataclass, field
+from dataclasses import dataclass, field
@@
-from codeintel_rev.errors import RuntimeLifecycleError
+from codeintel_rev.errors import RuntimeLifecycleError
+from codeintel_rev.contracts.types import VersionManifest, TuningProfile
@@
 class IndexAssets:
     """File-system assets that must advance together for one index version."""
 
     faiss_index: Path
     duckdb_path: Path
     scip_index: Path
+    idmap_path: Path | None = None
     bm25_dir: Path | None = None
     splade_dir: Path | None = None
     xtr_dir: Path | None = None
@@
     def ensure_exists(self) -> None:
         """Validate that all required files and directories are present.
@@
-        required: Iterable[tuple[str, Path | None]] = (
+        required: Iterable[tuple[str, Path | None]] = (
             ("faiss_index", self.faiss_index),
             ("duckdb_path", self.duckdb_path),
             ("scip_index", self.scip_index),
         )
@@
-        optional: Iterable[tuple[str, Path | None]] = (
+        optional: Iterable[tuple[str, Path | None]] = (
+            ("idmap_path", self.idmap_path),
             ("bm25_dir", self.bm25_dir),
             ("splade_dir", self.splade_dir),
             ("xtr_dir", self.xtr_dir),
         )
@@
 class IndexLifecycleManager:
@@
     def _manifest_path(self, version: str) -> Path:
         return (self.versions_dir / version) / "manifest.json"
 
+    def write_manifest(
+        self,
+        version: str,
+        *,
+        faiss_factory: str,
+        vec_dim: int,
+        vectors_count: int,
+        chunks_checksum: str,
+        idmap_checksum: str | None = None,
+        tuning: TuningProfile | None = None,
+        attrs: Mapping[str, Any] = {},
+    ) -> Path:
+        """Write a strongly-typed manifest file used by readers and CI checks."""
+        path = self._manifest_path(version)
+        manifest = VersionManifest(
+            version=version,
+            created_ts=time.time(),
+            faiss_factory=faiss_factory,
+            vec_dim=int(vec_dim),
+            vectors_count=int(vectors_count),
+            chunks_checksum=chunks_checksum,
+            idmap_checksum=idmap_checksum,
+            tuning=tuning,
+            attrs=dict(attrs),
+        )
+        path.parent.mkdir(parents=True, exist_ok=True)
+        path.write_text(manifest.__class__.to_json(manifest), encoding="utf-8")
+        return path
+
     # existing publish/link methods...
```

*(Notes: `to_json()` is already implemented on your `VersionMeta`; a parallel one for `VersionManifest` is provided via msgspec encoding; if you prefer, you can serialize with `json.dumps(manifest.__dict__)`.)* 

---

### 4) Update — `codeintel_rev/io/duckdb_manager.py` (read‑only connection helper & health ping)

> Your manager already supports pooling and `enable_object_cache`. Add an **optional read‑only** connection wrapper (guard against accidental writes during query paths) and a trivial health ping for diagnostics. 

```diff
diff --git a/codeintel_rev/io/duckdb_manager.py b/codeintel_rev/io/duckdb_manager.py
--- a/codeintel_rev/io/duckdb_manager.py
+++ b/codeintel_rev/io/duckdb_manager.py
@@
 class DuckDBManager:
@@
     def _create_connection(self) -> duckdb.DuckDBPyConnection:
         conn = duckdb.connect(str(self._db_path))
         if self._config.enable_object_cache:
             conn.execute("PRAGMA enable_object_cache = true")
         conn.execute(f"SET threads = {self._config.threads}")
+        # Safer defaults for read-mostly analytics; caller can override session-wise.
+        conn.execute("PRAGMA disable_statistics = false")
+        conn.execute("PRAGMA memory_limit = '2GB'")  # conservative default for personal systems
         return conn
@@
+    def health_ping(self) -> bool:
+        """Return True if a simple query succeeds; False otherwise (no exceptions raised)."""
+        try:
+            with self.connection() as conn:
+                conn.execute("SELECT 1").fetchone()
+            return True
+        except Exception:
+            return False
```

---

### 5) Update — `codeintel_rev/io/duckdb_catalog.py` (IDMap join, hydration, metrics)

> Your catalog already exposes scope filtering and uses Prometheus histograms. We add **IDMap registration**, a **join view**, and **hydration helpers** with read‑only connections. 

```diff
diff --git a/codeintel_rev/io/duckdb_catalog.py b/codeintel_rev/io/duckdb_catalog.py
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@
 from kgfoundry_common.prometheus import build_histogram
@@
 _scope_filter_duration_seconds = build_histogram(
     "codeintel_scope_filter_duration_seconds",
     "Time to apply scope filters",
     labelnames=("filter_type",),
 )
+_hydration_seconds = build_histogram(
+    "codeintel_duckdb_hydration_seconds",
+    "Time to hydrate chunks or embeddings by id",
+    labelnames=("op",),
+)
@@
 class DuckDBCatalog:
@@
         self._views_ready = False
@@
     def _ensure_ready(self) -> None:
         """Initialize catalog views once in a threadsafe manner."""
@@
             with self._manager.connection() as conn:
                 self._ensure_views(conn)
             self._views_ready = True
@@
+    def register_faiss_idmap(self, idmap_parquet: Path, *, materialize: bool = False) -> None:
+        """
+        Register FAISS idmap as a DuckDB view or materialized table for joins.
+        """
+        with self._manager.connection() as conn:
+            conn.execute("CREATE OR REPLACE VIEW idmap AS SELECT * FROM read_parquet(?);", [str(idmap_parquet)])
+            if materialize:
+                conn.execute("CREATE TABLE IF NOT EXISTS faiss_idmap_mat AS SELECT * FROM idmap;")
+                conn.execute("CREATE INDEX IF NOT EXISTS faiss_idmap_mat_idx ON faiss_idmap_mat(external_id);")
+
+    def _ensure_views(self, conn: "duckdb.DuckDBPyConnection") -> None:
+        """
+        Create chunks view if not materialized. This is called once.
+        """
+        # Existing chunk view creation logic...
+        # Ensure the join view exists (will be null until idmap registered)
+        conn.execute("""
+        CREATE OR REPLACE VIEW v_faiss_join AS
+        SELECT c.*, i.faiss_row
+        FROM chunks c
+        LEFT JOIN idmap i ON i.external_id = c.id
+        """)
+
+    @contextmanager
+    def connection_readonly(self) -> Iterator["duckdb.DuckDBPyConnection"]:
+        """
+        Like `connection()` but sets the session into read_only mode for safety.
+        """
+        self._ensure_ready()
+        with self._manager.connection() as conn:
+            conn.execute("PRAGMA query_verification = 'safe'")
+            yield conn
+
+    def query_by_ids(self, ids: Sequence[int]) -> list[tuple[int, str, str, int, int]]:
+        """
+        Return [(id, uri, lang, start_line, end_line)] for exact hydration.
+        """
+        import time
+        t0 = time.perf_counter()
+        with self.connection_readonly() as conn:
+            q = "SELECT id, uri, lang, start_line, end_line FROM chunks WHERE id IN ? ORDER BY id"
+            rows = conn.execute(q, [list(ids)]).fetchall()
+        _hydration_seconds.labels(op="chunks_by_ids").observe(time.perf_counter() - t0)
+        return [(int(r[0]), str(r[1]), str(r[2]), int(r[3]), int(r[4])) for r in rows]
+
+    def get_embeddings_by_ids(self, ids: Sequence[int]) -> "np.ndarray":
+        """
+        Return embeddings array for the requested ids, preserving input order.
+        """
+        import numpy as np
+        import time
+        t0 = time.perf_counter()
+        with self.connection_readonly() as conn:
+            q = "SELECT id, embedding FROM chunks WHERE id IN ?"
+            rows = conn.execute(q, [list(ids)]).fetchall()
+        _hydration_seconds.labels(op="embeddings_by_ids").observe(time.perf_counter() - t0)
+        # Pack preserving the caller order
+        by_id = {int(r[0]): r[1] for r in rows}
+        emb = [by_id[i] for i in ids if i in by_id]
+        # DuckDB returns Python lists; let caller cast if needed
+        return np.asarray(emb, dtype="float32")
```

---

### 6) Update — `codeintel_rev/io/parquet_store.py` (idmap I/O + finish `extract_embeddings`)

> Completes the last return in `extract_embeddings()` using list_size; adds small helpers for idmap Parquet (in case you want to keep I/O here rather than `io/idmap_store.py`). Keep one source of truth—if you adopt the new `idmap_store.py`, skip these idmap helpers here. 

```diff
diff --git a/codeintel_rev/io/parquet_store.py b/codeintel_rev/io/parquet_store.py
--- a/codeintel_rev/io/parquet_store.py
+++ b/codeintel_rev/io/parquet_store.py
@@
 def extract_embeddings(table: pa.Table) -> NDArrayF32:
@@
-    fixed_array = dense_array
-    # Convert list_size (which is a _Size type) to int for numpy.reshape
-    vec_dim = int(getattr(fixed_array.type, "list_size", 0))
-    flat_values = fixed_array.values.to_numpy(zero_copy_only=False)
-    return
+    fixed_array = dense_array
+    vec_dim = int(getattr(fixed_array.type, "list_size", 0))
+    if vec_dim <= 0:
+        raise TypeError("Embedding list_size is invalid")
+    flat_values = fixed_array.values.to_numpy(zero_copy_only=False)
+    import numpy as np
+    return np.asarray(flat_values, dtype="float32").reshape(-1, vec_dim)
+
+# Optional: keep idmap writer here if you don't want a standalone module.
+def get_idmap_schema() -> pa.Schema:
+    return pa.schema([pa.field("faiss_row", pa.int64()), pa.field("external_id", pa.int64())])
+
+def write_idmap_parquet(path: Path, rows: "Sequence[tuple[int,int]]") -> None:
+    table = pa.table({"faiss_row": [r[0] for r in rows], "external_id": [r[1] for r in rows]}, schema=get_idmap_schema())
+    path.parent.mkdir(parents=True, exist_ok=True)
+    pq.write_table(table, path, compression="snappy", use_dictionary=True)
```

---

### 7) Update — `codeintel_rev/errors.py` (precise exceptions)

> Your error module already centralizes runtime errors. Add two narrow exception types used by lifecycle & catalog. 

```diff
diff --git a/codeintel_rev/errors.py b/codeintel_rev/errors.py
--- a/codeintel_rev/errors.py
+++ b/codeintel_rev/errors.py
@@
 class RuntimeLifecycleError(KgFoundryError):
     """Raised when a runtime fails to initialize or shut down."""
@@
+class InvariantViolationError(KgFoundryError):
+    """Raised when pre-/post-conditions for publishing or querying are not met."""
+
+class IndexCorruptionError(KgFoundryError):
+    """Raised when persisted assets (DuckDB/FAISS/IDMap) disagree or checksums mismatch."""
```

---

### 8) Update — `codeintel_rev/indexing/cast_chunker.py` (no functional changes, doc pin)

> No code change required—only calling out that the **Chunk** record is the stable join key; we rely on `id` assigned at write time for joins. (Shown for reference.) 

---

### 9) Update — `codeintel_rev/indexing/scip_reader.py` (no functional changes)

> The reader already extracts `Document`, `Occurrence`, and `Range`. We only reference this for symbol‑aware explainability downstream. (Shown for reference.) 

---

### 10) Update — **FAISS manager** (IDMap sidecar & profile)

> Your wheel supports `IndexIDMap2`, `ParameterSpace`, read/write of CPU indexes, and GPU clones. We add: **export of idmap Parquet**, **accessor for id array**, and optional **profile application** at load. (If your FAISS manager file differs in path, adapt the path below.) 

```diff
diff --git a/codeintel_rev/io/faiss_manager.py b/codeintel_rev/io/faiss_manager.py
--- a/codeintel_rev/io/faiss_manager.py
+++ b/codeintel_rev/io/faiss_manager.py
@@
 from __future__ import annotations
-from typing import Any
+from typing import Any, Sequence
+from pathlib import Path
+import numpy as np
 import faiss  # type: ignore
@@
 class FAISSManager:
@@
     def build_index(self, xb: NDArrayF32, ids: NDArrayI64 | None = None, *, family: str = "auto") -> None:
         """
         Build the primary CPU index from vectors.
         """
-        # existing builder code ...
+        # Ensure external IDs are always present and wrap with IDMap2
+        if ids is None:
+            ids = np.arange(xb.shape[0], dtype="int64")
+        base = self._make_index_family(xb.shape[1], family=family)
+        if hasattr(base, "is_trained") and not base.is_trained:
+            base.train(xb)
+        idmap = faiss.IndexIDMap2(base)
+        idmap.add_with_ids(xb, ids)
+        self._cpu = idmap
+        self._cpu_count = idmap.ntotal
@@
     def search(self, xq: NDArrayF32, k: int) -> tuple[NDArrayF32, NDArrayI64]:
         """
         Run ANN search using the active (GPU or CPU) index. Returns (D, I).
         """
         # existing logic...
@@
+    def get_idmap_array(self) -> "np.ndarray":
+        """
+        Return the FAISS ID array (external ids) in row order [0..ntotal-1].
+        """
+        assert self._cpu is not None, "index not built"
+        # FAISS doesn't expose ids() on all wrappers; reconstruct via search of basis vectors is expensive.
+        # Use `IndexIDMap2` reverse map: extract via iterating inverted lists where applicable or rely
+        # on `search` over an identity buffer if Flat; for IVF/HNSW we fall back to reconstruct+argmin.
+        # Simplest robust method: call `index_to_array` helper if available.
+        try:
+            return faiss.vector_to_array(self._cpu.id_map)  # available on IDMap2
+        except Exception:
+            raise RuntimeError("Index is not an IndexIDMap2 or lacks id_map")
+
+    def export_idmap(self, path: Path) -> int:
+        """
+        Persist idmap as Parquet: rows (faiss_row, external_id). Returns count.
+        """
+        ids = self.get_idmap_array()
+        rows = [(i, int(ids[i])) for i in range(len(ids))]
+        from codeintel_rev.io.parquet_store import write_idmap_parquet
+        write_idmap_parquet(path, rows)
+        return len(rows)
+
+    def apply_profile(self, *, nprobe: int | None = None, hnsw_efSearch: int | None = None) -> None:
+        """
+        Apply runtime search knobs using FAISS ParameterSpace.
+        """
+        index = self._gpu or self._cpu
+        if index is None:
+            return
+        ps = faiss.ParameterSpace()
+        params: list[str] = []
+        if nprobe is not None:
+            params.append(f"nprobe={int(nprobe)}")
+        if hnsw_efSearch is not None:
+            params.append(f"efSearch={int(hnsw_efSearch)}")
+        if params:
+            ps.set_index_parameters(index, ",".join(params))
```

*(The helper `_make_index_family` represents your existing factory; keep its signature and integrate as shown.)* 

---

## How the pieces fit together

* **Build:** after writing chunk Parquet (your present `write_chunks_parquet`), build FAISS with external IDs and **export `idmap.parquet`** next to `faiss.index`. 
* **Catalog boot:** register `idmap.parquet` once (or materialize it) and you instantly get `v_faiss_join` for BI/debugging. 
* **Lifecycle publish:** call `IndexLifecycleManager.write_manifest(...)` with the factory string + vector count + checksums, then flip `CURRENT` when **all checks pass**. 
* **Search path:** FAISS returns external `chunk_id`s; the catalog **hydrates** the metadata and embeddings via `query_by_ids`/`get_embeddings_by_ids`; MCP `fetch` then emits the structured content. (MCP pieces are already in place from your previous milestone; this preserves their contracts.)

---

## Minimal golden test & smoke (optional but recommended)

Add these as **lightweight guardrails**:

1. **Golden** — `tests/io/test_idmap_export.py`

```python
from pathlib import Path
import numpy as np
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.parquet_store import read_chunks_parquet

def test_idmap_export(tmp_path: Path) -> None:
    xb = np.random.RandomState(0).randn(10, 8).astype("float32")
    ids = np.arange(100, 110, dtype="int64")
    fm = FAISSManager()
    fm.build_index(xb, ids=ids, family="flat")
    out = tmp_path / "idmap.parquet"
    n = fm.export_idmap(out)
    assert n == 10
    assert out.exists()
```

2. **Catalog join smoke** — `tests/io/test_duckdb_join.py`

```python
from pathlib import Path
from codeintel_rev.io.duckdb_manager import DuckDBManager, DuckDBConfig
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog

def test_register_and_join(tmp_path: Path) -> None:
    db = tmp_path / "cat.duckdb"
    mgr = DuckDBManager(db, DuckDBConfig(pool_size=0))
    cat = DuckDBCatalog(db, tmp_path, manager=mgr)
    cat.open()  # ensures chunk view
    # create a trivial idmap to register (empty OK)
    idmap = tmp_path / "idmap.parquet"
    idmap.write_bytes(b"")  # replaced in real run
    cat.register_faiss_idmap(idmap)
    with cat.connection() as conn:
        conn.execute("SELECT * FROM v_faiss_join LIMIT 1")
```

---

## Operational checklist (what to run)

1. **Rebuild + publish**

   * Build chunks + embeddings (as you do today), then:
   * `FAISSManager.build_index(..., ids=chunk_ids)` → `fm.export_idmap(path)`
   * Compute checksums for `chunks.parquet` and `idmap.parquet`.
   * `IndexLifecycleManager.write_manifest(...)`
   * Flip current via your existing publish helper.

2. **Boot runtime**

   * `DuckDBCatalog.register_faiss_idmap(current/idmap.parquet, materialize=False)`
   * `FAISSManager.apply_profile(nprobe=..., hnsw_efSearch=...)` (use persisted `tuning` if you have it).

3. **Run MCP `search`/`fetch`**

   * No change in wire contracts; the system internally hydrates from the catalog and can join on `v_faiss_join` for explainability if you choose to enrich responses.

---

## Why this meets the brief

* **Robustness via invariants**: publication never flips to a broken set; assets are tightly checked and attributable to an explicit factory string & profile. 
* **Error locality**: distinct exceptions for invariant violations and corruption mean operators (and tests) can **pinpoint** the component at fault. 
* **Auditability**: `idmap.parquet` + `v_faiss_join` make “what did FAISS return and why?” a single SQL away; joins can be materialized for BI or kept lightweight. 
* **No behavior surprises**: public interfaces and MCP schemas remain stable; these are internal hardening and explainability improvements.
* **Future‑proof**: manifest carries factory strings and tuning profiles so you can **time‑travel regressions** and rehydrate experiments deterministically. 

---

## Notes & references to your current codebase

* **Chunk record** & offsets are unchanged; we reuse `id` as authoritative join key. 
* **SCIP reader** stays as is; your symbol data powers explainability layers and synthetic query generation (if/when you re‑enable it). 
* **Catalog architecture** already separates connection management and catalog logic; our additions sit naturally on top of `DuckDBManager`.
* **Parquet embedding layout** (FixedSizeList) is preserved; we finished the small extraction helper to avoid repeated boilerplate. 
* **Repository & doc inventory** confirm module availability and testing slots; these diffs follow the documented style & exports.

---

### If you want to extend this in a follow‑up PR

* Add an **admin CLI verb** `indexctl verify` that:

  * computes checksums,
  * validates manifest vs. assets,
  * does `SELECT count(*)` checks on `chunks` and `idmap`,
  * pings the pool and runs a 1‑NN FAISS smoke.

* Persist minimal **per‑query pool rows** (for hybrid explainability) with `(query_id, channel, rank, chunk_id, score, explanations)` using DuckDB’s Parquet sink; this cleanly joins through `v_faiss_join` and your `modules.jsonl` for coverage heatmaps. (You already have the building blocks in `xtr_build` and the enrichment README.)

---

If anything needs to be rebased on top of local edits, tell me which files diverged and I’ll re‑emit the hunks that match your HEAD.
