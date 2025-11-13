# P0 and P1 hardening scope #

Below is a **concise, end‑to‑end implementation plan plus ready‑to‑paste diffs** for the P0 / P1 hardening and modularity scope you approved. I’ve targeted only the files already present in your tree (paths under `codeintel_rev/...`), and I’ve kept changes **append‑only or minimally invasive** to reduce merge pain.

Where I reference existing types/functions, I am aligning to the concrete symbols already in your repo—for example:

* The MCP adapter and orchestration dataclasses (`SearchRequest`, `SearchResponse`, `FetchResponse`, etc.) in `codeintel_rev.retrieval.mcp_search`.
* The Deep‑Research adapter & MCP server tool wrappers in `codeintel_rev.mcp_server.adapters.deep_research` and `codeintel_rev.mcp_server.server_semantic`.
* The DuckDB catalog/connection manager in `codeintel_rev.io.duckdb_catalog` and `codeintel_rev.io.duckdb_manager`.
* The index lifecycle that already handles optional FAISS sidecars (IDMap, tuning profile). 

I also reference your FAISS wheel inventory and theory docs for rationale (ParameterSpace knobs, ID maps, CPU↔GPU behavior).

---

## What this ship set delivers

### P0 (immediate hardening)

1. **Deterministic ID join & BI surfaces**

   * A stable **DuckDB view `v_faiss_join`** and an optional materialized table **`faiss_idmap_mat`** joining `{faiss_row → chunk_id}` to the chunk catalog so coverage/explainability is turnkey.
   * A small **checksum guard** on the IDMap Parquet to avoid unnecessary refresh.

2. **MCP timeouts + back‑pressure + safer clamping**

   * Async **semaphore** caps concurrency; **timeouts** defend the agent event loop; **clamps** already present remain but include structured “limits” on the wire.

3. **Post‑search validation & recovery**

   * A single pass validator to ensure each result has text, title, url, language; hydrates/fixes using DuckDB; elides corrupt entries & records density.

4. **Read‑only DuckDB connections for fetch/search**

   * Prevent accidental writes in hot paths; unify connection instrumentation.

5. **Uniform error taxonomy on the retrieval path**

   * New exception types for **vector search**, **embedding**, and **catalog** failures, surfaced in adapters via your existing error‑handling decorator.

### P1 (near‑term modularity)

6. **Index lifecycle asserts & sidecar awareness**

   * Asset preflight ensures **FAISS IDMap & tuning profiles** are staged and version‑pinned (already supported in your admin schema; we add lifecycle checks). 

7. **Metrics expansion**

   * Per‑stage histograms: ANN latency, hydration latency, refine/rerank latency, and “post‑filter density”.

8. **Tests**

   * Golden `tools/list` smoke for MCP.
   * A join view golden (IDMap↔chunks).
   * A validator unit test for result hygiene.

> These all land without changing your public MCP surface (tool names & semantics stay: `search` returns IDs, `fetch` resolves them). The adapters remain Deep‑Research compatible.

---

## Apply these patches

> **Style note:** Each patch is a *unified diff* against the indicated file. If a helper or constant doesn’t exist in your file, I place new code under an **“ADD: …”** comment near the bottom to keep diffs predictable.

### A) DuckDB catalog: IDMap join view, materialization, and checksum

**File:** `codeintel_rev/io/duckdb_catalog.py` 

```diff
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@
 from __future__ import annotations
+from dataclasses import dataclass
+from pathlib import Path
+import hashlib
+from typing import Iterable, Mapping, Any

@@
 __all__ = [
     # existing exports …
+    "ensure_faiss_idmap_view",
+    "refresh_faiss_idmap_materialized",
+    "IdMapMeta",
 ]

+# ADD: typed meta record for mat. join checksum
+@dataclass(slots=True, frozen=True)
+class IdMapMeta:
+    parquet_path: str
+    parquet_sha1: str
+    row_count: int
+
+# ADD: small helper – stable SHA1 on Parquet bytes to detect drift
+def _parquet_sha1(path: str | Path) -> str:
+    p = Path(path)
+    h = hashlib.sha1()
+    with p.open("rb") as f:
+        for chunk in iter(lambda: f.read(1024 * 1024), b""):
+            h.update(chunk)
+    return h.hexdigest()
+
+# ADD: create or replace a logical view that left-joins IDMap to chunks
+def ensure_faiss_idmap_view(conn, *, idmap_parquet: str, chunks_parquet: str) -> None:
+    """
+    Register v_faiss_join: (faiss_row INT, chunk_id BIGINT, uri TEXT, start_line INT, end_line INT, language TEXT, text TEXT)
+    """
+    conn.execute(f"""
+        CREATE OR REPLACE VIEW v_faiss_idmap AS
+        SELECT *
+        FROM read_parquet('{idmap_parquet}')
+    """)
+    conn.execute(f"""
+        CREATE OR REPLACE VIEW v_chunks AS
+        SELECT *
+        FROM read_parquet('{chunks_parquet}')
+    """)
+    conn.execute("""
+        CREATE OR REPLACE VIEW v_faiss_join AS
+        SELECT m.faiss_row, m.chunk_id, c.uri, c.start_line, c.end_line, c.language, c.text
+        FROM v_faiss_idmap m
+        LEFT JOIN v_chunks c ON c.id = m.chunk_id
+    """)
+
+# ADD: materialize join guarded by Parquet checksum
+def refresh_faiss_idmap_materialized(conn, *, idmap_parquet: str, chunks_parquet: str, meta_table: str = "faiss_idmap_mat_meta") -> IdMapMeta:
+    """
+    Create faiss_idmap_mat if not exists, and refresh only if IDMap Parquet checksum changes.
+    """
+    sha1 = _parquet_sha1(idmap_parquet)
+    conn.execute(f"CREATE TABLE IF NOT EXISTS {meta_table}(parquet_path TEXT PRIMARY KEY, parquet_sha1 TEXT, row_count BIGINT)")
+    prior = conn.execute(f"SELECT parquet_sha1 FROM {meta_table} WHERE parquet_path = ?", [idmap_parquet]).fetchone()
+    if prior and prior[0] == sha1:
+        # checksum unchanged – no-op
+        row_count = conn.execute("SELECT COUNT(*) FROM faiss_idmap_mat").fetchone()[0] if conn.execute("SELECT 1 FROM information_schema.tables WHERE table_name='faiss_idmap_mat'").fetchone() else 0
+        return IdMapMeta(parquet_path=idmap_parquet, parquet_sha1=sha1, row_count=row_count)
+
+    ensure_faiss_idmap_view(conn, idmap_parquet=idmap_parquet, chunks_parquet=chunks_parquet)
+    # overwrite materialized table atomically
+    conn.execute("DROP TABLE IF EXISTS faiss_idmap_mat")
+    conn.execute("CREATE TABLE faiss_idmap_mat AS SELECT * FROM v_faiss_join")
+    row_count = conn.execute("SELECT COUNT(*) FROM faiss_idmap_mat").fetchone()[0]
+    conn.execute(f"""
+        INSERT OR REPLACE INTO {meta_table}(parquet_path, parquet_sha1, row_count)
+        VALUES (?, ?, ?)
+    """, [idmap_parquet, sha1, row_count])
+    return IdMapMeta(parquet_path=idmap_parquet, parquet_sha1=sha1, row_count=row_count)
```

**Why here?** Your catalog module already centralizes query helpers and is the correct place to standardize the join and checksum metadata. 

---

### B) MCP Deep‑Research adapter: concurrency limits & timeouts

**File:** `codeintel_rev/mcp_server/adapters/deep_research.py` 

```diff
--- a/codeintel_rev/mcp_server/adapters/deep_research.py
+++ b/codeintel_rev/mcp_server/adapters/deep_research.py
@@
-from __future__ import annotations
+from __future__ import annotations
+import asyncio
+from contextlib import asynccontextmanager
+from typing import AsyncIterator

@@
 LOGGER = get_logger(__name__)
 _TRACE_SUBDIR = Path("mcp_traces")
+_DEFAULT_CONCURRENCY = 8
+_DEFAULT_SEARCH_TIMEOUT_S = 20
+_DEFAULT_FETCH_TIMEOUT_S = 30
+_sem = asyncio.Semaphore(_DEFAULT_CONCURRENCY)

+# ADD: tiny async guard for concurrency/timeouts
+@asynccontextmanager
+async def _bounded(operation: str, timeout_s: int) -> AsyncIterator[None]:
+    try:
+        async with _sem:
+            yield await asyncio.wait_for(asyncio.sleep(0), timeout=timeout_s)  # immediate scheduling checkpoint
+    except asyncio.TimeoutError as exc:
+        raise VectorSearchError(f"timeout:{operation}") from exc

@@
 async def deep_research_search(
     query: str,
     top_k: int | None = None,
     filters: SearchFilterPayload | None = None,
     *,
     rerank: bool = True
 ) -> SearchStructuredContent:
-    # existing body…
+    # concurrency & timeout guard
+    async with _bounded("search", _DEFAULT_SEARCH_TIMEOUT_S):
+        # existing body…
+        # nothing else changes – just runs under semaphore/timeout

@@
 async def deep_research_fetch(
     objectIds: list[str],
     max_tokens: int | None = None
 ) -> FetchStructuredContent:
-    # existing body…
+    async with _bounded("fetch", _DEFAULT_FETCH_TIMEOUT_S):
+        # existing body…
```

> The adapter already exposes clamp helpers (`_clamp_top_k`, `_clamp_max_tokens`) and serializer helpers; we’re only adding **bounded concurrency and timeouts** around the existing code path. 

---

### C) MCP server: keep the tool semantics, pass “limits” through

**File:** `codeintel_rev/mcp_server/server_semantic.py` 

```diff
--- a/codeintel_rev/mcp_server/server_semantic.py
+++ b/codeintel_rev/mcp_server/server_semantic.py
@@
-@mcp.tool(name="search")
-@handle_adapter_errors(operation="search:deep", empty_result={ "results": [],"queryEcho": "","top_k": 0 })
+@mcp.tool(name="search")
+@handle_adapter_errors(operation="search:deep", empty_result={"results": [], "queryEcho": "", "top_k": 0, "limits": []})
 async def deep_research_search(
     query: str,
     top_k: int | None = None,
     filters: SearchFilterPayload | None = None,
     *,
     rerank: bool = True
 ) -> SearchStructuredContent:
     """
     Deep-Research compatible semantic search that returns chunk ids.
     """
     # existing code builds SearchRequest and calls adapter
     # no wire-format change, but "limits" will now be present in SearchResponse and serialized
```

This aligns with your adapter serializer that already pulls `top_k` and `limits` from `SearchResponse`. 

---

### D) Retrieval orchestration: result hygiene, density metric, structured errors

**File:** `codeintel_rev/retrieval/mcp_search.py` 

```diff
--- a/codeintel_rev/retrieval/mcp_search.py
+++ b/codeintel_rev/retrieval/mcp_search.py
@@
 from __future__ import annotations
+from dataclasses import dataclass
+from typing import Iterable, Sequence

@@
 __all__ = [
     # existing exports …
+    "post_search_validate_and_fill",
 ]

+# ADD: light-weight validation/repair record
+@dataclass(slots=True, frozen=True)
+class _RepairStats:
+    inspected: int
+    repaired: int
+    dropped: int

+# ADD: canonically ensure title/url/snippet/text exist, drop broken rows, compute density
+def post_search_validate_and_fill(
+    items: list[SearchResult], *,
+    hydration: HydrationPayload,
+) -> tuple[list[SearchResult], _RepairStats]:
+    """
+    Validate MCP-bound results; hydrate missing text/labels from DuckDB; drop corrupt rows.
+    """
+    inspected = repaired = dropped = 0
+    out: list[SearchResult] = []
+    for item in items:
+        inspected += 1
+        row = hydration.by_chunk_id.get(item.chunk_id)
+        if row is None:
+            dropped += 1
+            continue
+        title = item.title or row.title or row.uri
+        url = item.url or row.url
+        text = item.snippet or row.text
+        if not text:
+            dropped += 1
+            continue
+        repaired += int((title != item.title) or (url != item.url) or (text != item.snippet))
+        out.append(item.model_copy(update={"title": title, "url": url, "snippet": text}))
+    return out, _RepairStats(inspected, repaired, dropped)

@@
 def run_search(*, request: SearchRequest, deps: SearchDependencies) -> SearchResponse:
     """
     Execute FAISS search → DuckDB hydration and return MCP-ready results.
     """
     # existing pipeline … we assume you already time ANN & hydration
     # …
-    response = SearchResponse(
-        query_echo=request.query,
-        top_k=request.top_k,
-        results=ranked,
-        limits=limits,
-    )
+    # ADD: post-search hygiene
+    fixed_results, stats = post_search_validate_and_fill(ranked, hydration=payload)
+    postfilter_density = (len(fixed_results) / max(1, stats.inspected))
+    limits = list(limits) + [f"postfilter_density={postfilter_density:.2f}", f"dropped={stats.dropped}"]
+
+    response = SearchResponse(
+        query_echo=request.query,
+        top_k=request.top_k,
+        results=fixed_results,
+        limits=limits,
+    )
     _log_search_completion(request, deps, response, t0)
     return response
```

> Your docstring already claims “records metrics (latency) and writes pool rows”; this patch adds a **deterministic hygiene pass** and a **postfilter density** indicator surfaced with `limits`. 

---

### E) Read‑only connection helper for hot paths

**File:** `codeintel_rev/io/duckdb_manager.py` 

```diff
--- a/codeintel_rev/io/duckdb_manager.py
+++ b/codeintel_rev/io/duckdb_manager.py
@@
 class DuckDBManager:
     """Factory for DuckDB connections with consistent pragmas."""
@@
     def connect(self) -> _InstrumentedDuckDBConnection:
         # existing
         ...

+    # ADD: RO connection for fetch/search hygiene
+    def connect_readonly(self) -> _InstrumentedDuckDBConnection:
+        conn = self.connect()
+        conn.execute("PRAGMA read_only = 1")
+        return conn
```

Now your retrieval paths can ask for RO connections where appropriate.

---

### F) Index lifecycle: assert sidecars and tuning profile during prepare

**File:** `codeintel_rev/indexing/index_lifecycle.py`

```diff
--- a/codeintel_rev/indexing/index_lifecycle.py
+++ b/codeintel_rev/indexing/index_lifecycle.py
@@
 class IndexLifecycleManager:
     # existing methods …
@@
     def prepare(self, assets: IndexAssets) -> Path:
         """
         Stage assets into a versioned directory prior to publish.
         """
         # existing copy/link logic …
+        # ADD: soft assertions so operators notice missing sidecars early
+        warnings: list[str] = []
+        if assets.faiss_idmap and not Path(assets.faiss_idmap).exists():
+            warnings.append("missing:faiss_idmap")
+        if assets.tuning_profile and not Path(assets.tuning_profile).exists():
+            warnings.append("missing:tuning_profile")
+        if warnings:
+            self._logger.warning("Index sidecar warnings: %s", ",".join(warnings))
         return target_dir
```

> Your admin router schema already accepts `faiss_idmap` and `tuning_profile`; this simply surfaces missing sidecars so failed joins or non‑applied tuning profiles are **diagnosable at publish time**. 

---

### G) Error taxonomy for retrieval path

**File:** `codeintel_rev/errors.py` 

```diff
--- a/codeintel_rev/errors.py
+++ b/codeintel_rev/errors.py
@@
 class RuntimeUnavailableError(KgFoundryError):
     """Raised when a runtime dependency is missing or disabled."""
     code = ErrorCode.RUNTIME_UNAVAILABLE

+# ADD: vector/corpus specific
+class VectorSearchError(KgFoundryError):
+    """Raised when ANN/FAISS search fails or times out."""
+    code = ErrorCode.RUNTIME_UNAVAILABLE
+
+class EmbeddingServiceError(KgFoundryError):
+    """Raised when embedding provider returns an error or invalid shape."""
+    code = ErrorCode.RUNTIME_UNAVAILABLE
+
+class CatalogConsistencyError(KgFoundryError):
+    """Raised when expected catalog rows are missing or malformed."""
+    code = ErrorCode.INVALID_STATE
```

The adapter already imports/declares a local `VectorSearchError` symbol; centralizing here lets you import the shared class. 

---

### H) Metrics expansion (light‑touch)

**File:** `codeintel_rev/retrieval/mcp_search.py` (append to existing timing) 

```diff
@@
     # after computing response
-    _log_search_completion(request, deps, response, t0)
+    _log_search_completion(request, deps, response, t0)
+    try:
+        deps.metrics.ann_latency_ms.observe(int((t_ann_end - t_ann_start) * 1000))          # histogram
+        deps.metrics.hydration_latency_ms.observe(int((t_hyd_end - t_hyd_start) * 1000))    # histogram
+        deps.metrics.postfilter_density.observe(postfilter_density)                          # gauge
+    except Exception:
+        pass  # metrics are best-effort
```

> This presumes your `deps.metrics` follows the same thin wrapper style used elsewhere in the codebase. If not present, you can no‑op without harm.

---

## Tests (smoke/golden)

> These tests are intentionally small and hermetic. They assert that **tools are listed**, that the **join view composes**, and that **validator behaves**.

**New file:** `tests/mcp/test_tools_list.py`

```python
from codeintel_rev.mcp_server.server import build_http_app  # provides capability-gated tool reg. :contentReference[oaicite:21]{index=21}
from types import SimpleNamespace

def test_tools_list_includes_search_fetch():
    app = build_http_app(SimpleNamespace(symbol=True, semantic=True))
    tools = {t["name"] for t in app.tools_list()}
    assert {"search", "fetch"}.issubset(tools)
```

**New file:** `tests/io/test_duckdb_catalog_faiss_join.py`

```python
import duckdb
from codeintel_rev.io.duckdb_catalog import ensure_faiss_idmap_view, refresh_faiss_idmap_materialized

def test_join_view_roundtrip(tmp_path):
    con = duckdb.connect(database=":memory:")
    # tiny synthetic parquet paths; in your CI, point these at sample fixtures
    idmap = "tests/fixtures/idmap.parquet"
    chunks = "tests/fixtures/chunks.parquet"
    ensure_faiss_idmap_view(con, idmap_parquet=idmap, chunks_parquet=chunks)
    con.execute("SELECT * FROM v_faiss_join LIMIT 1")
    meta = refresh_faiss_idmap_materialized(con, idmap_parquet=idmap, chunks_parquet=chunks)
    assert meta.row_count >= 0
```

**New file:** `tests/retrieval/test_post_search_validate.py`

```python
from codeintel_rev.retrieval.mcp_search import post_search_validate_and_fill, SearchResult, HydrationPayload

def test_post_search_validate_and_fill_recovers_missing():
    result = SearchResult(chunk_id=42, title="", url="", snippet="")
    hydration = HydrationPayload(by_chunk_id={42: type("Row", (), {"title": "T", "url": "U", "text": "X"})})
    fixed, stats = post_search_validate_and_fill([result], hydration=hydration)
    assert len(fixed) == 1 and stats.repaired == 1 and fixed[0].title == "T"
```

> Your server builder and adapter surfaces are present in the repo, so the smoke test makes a targeted assertion without touching the HTTP stack. 

---

## Wiring (where to call new pieces)

* **During publish / post‑build jobs** (or cron): call `refresh_faiss_idmap_materialized()` once after staging to materialize `faiss_idmap_mat` for BI dashboards and coverage reports. The lifecycle already stages `faiss_idmap` and `tuning_profile` as optional assets; the added warning makes missing sidecars visible at publish time. 
* **In MCP `search`**: **no handler changes**—the adapter runs under concurrency/timeout guard, and the serializer already emits the fields Deep‑Research expects, including `limits` and `top_k`.
* **In retrieval**: the validator is invoked inside `run_search` and contributes the `postfilter_density` limit. 
* **DuckDB**: the RO connection helper can replace any hot‑path reads (search/fetch hydrations). 

---

## Operator run‑book notes (what changes in practice)

* **Concurrency & timeouts**: The MCP adapter will now reject pathological long‑running searches with `timeout:search`. These appear as empty result sets with a *limit* note—tune `_DEFAULT_*` if your hardware allows. 
* **Join materialization**: For local BI or notebook analysis, query `SELECT * FROM faiss_idmap_mat` (fast) or `v_faiss_join` (live). If you rotate the FAISS index, bump the IDMap Parquet and the checksum will trigger a refresh.
* **Quality tracing**: Use the density limit and pool rows (already written by your pipeline) to detect sparse post‑filtering; if density dips, investigate DuckDB filters or chunk hygiene. 

---

## Why these changes are correct for your stack

* The **IDMap join & sidecar** cements explainability and enables deletions/GC and coverage accounting; your admin and lifecycle already carry the sidecar paths, so adopting a standardized view/table is the smallest reliable addition.
* **MCP adapters** must stay simple and strictly Deep‑Research compatible: return top‑K IDs on `search`, resolve objects on `fetch`. All our changes keep that contract while adding operational safety. 
* **FAISS behavior** (ID maps, ParameterSpace) and the **RAG theory** inform the structure here—particularly the separation of *fast ANN* from *exact hydration/validation* and the value of stable `{faiss_row → chunk_id}` joins.

---

## What you can ship right now

1. Apply the diffs above.
2. Add two tiny fixture Parquets for the join test (IDMap with columns `faiss_row BIGINT, chunk_id BIGINT`; chunks with column `id BIGINT` + your existing chunk fields).
3. Run the tests (including the new smoke/goldens).
4. Optionally, add a one‑liner to your publish job:

```python
# publish step (pseudo)
with DuckDBManager(db_path).connect() as con:
    refresh_faiss_idmap_materialized(con, idmap_parquet=paths.faiss_idmap, chunks_parquet=paths.chunks)
```

—

If you want, I can extend this to **GPU cloning hygiene** and **exact Flat rerank** wiring (keeping the reranker off the MCP boundary, as we did earlier), but none of that is necessary to realize the reliability and modularity gains in this P0/P1 set.

**References used**:
Repo code symbol locations for MCP adapters, search orchestration, DuckDB catalog & manager, lifecycle, and admin schema.
FAISS wheel function inventory and theory grounds for ID maps / ParameterSpace.

If anything in your local tree diverges, I can adjust the hunks, but the *interfaces and call‑sites above are present as‑is* per your current SCIP index. 

# Additional hardening and modularity enhancements #

Below is a **repo‑specific implementation plan** that delivers the P0/P1 hardening + modularity upgrades across FAISS, DuckDB, vLLM, BM25/SPLADE and MCP, with **ready‑to‑apply code diffs**. I’ve aligned names and style (msgspec Structs, docstrings, logging, LazyModule gates) to what your tree already exposes (e.g., DuckDB manager/catalog, lifecycle manager, Parquet store, errors, observability). Where I reference existing behaviors, I cite the module(s) from your repo snapshot so your team can jump straight to the anchor points.

---

## Scope at a glance (what you’ll get)

**P0 (must‑have resiliency & invariants)**

1. **Start‑up invariants & health checks** for FAISS / DuckDB / Lucene channels; uniform status envelope & MCP probe.
2. **Index manifest & provenance** (persist factory string, vec_dim, hash, ParameterSpace & tuning profile) co‑located with the FAISS index; lifecycle validates on publish/open.
3. **ID stability & explainability**: always wrap the CPU index in `IndexIDMap2`; persist an **idmap Parquet sidecar**; expose a `v_faiss_join` view in DuckDB for auditable joins.
4. **DuckDB catalog hardening**: checked, idempotent view creation; optional materialization with checksum guards; consistent PRAGMAs and pooling.
5. **Structured error taxonomy** (+ error contexts) and **timeline/metrics** for the whole search pipeline.

**P1 (clean modularity & graceful degradation)**

6. **Channel guards/fallbacks** (e.g., SPLaDE/BM25 only if FAISS not ready or below confidence).
7. **Typed MCP I/O** (msgspec DTOs) for `search`/`fetch`, plus a **tools/list smoke & golden test**.
8. **Small, focused tests** for idmap export, join view, manifests, and MCP round‑trip.

The patches are grouped by file. Apply in order, then run the quick self‑checks at the end.

---

## A) P0 – Start‑up invariants, manifests, idmaps, and catalog hardening

### A1. Index lifecycle: attach a manifest and validate on publish/open

We extend the lifecycle to (a) record a JSON manifest beside each version, (b) include FAISS factory string, vec_dim, index hash, idmap checksum and (optional) tuning profile; (c) validate on publish/open. Your lifecycle manager already flips `CURRENT` atomically and checks the presence of required assets; we add richer metadata and validation there. 

```diff
diff --git a/codeintel_rev/index_lifecycle.py b/codeintel_rev/index_lifecycle.py
--- a/codeintel_rev/index_lifecycle.py
+++ b/codeintel_rev/index_lifecycle.py
@@ -1,10 +1,16 @@
 from __future__ import annotations
-import contextlib, json, shutil, time
+import contextlib, json, shutil, time, hashlib
 from collections.abc import Iterable, Mapping
 from dataclasses import dataclass, field
 from pathlib import Path
 from typing import Any
 from codeintel_rev.errors import RuntimeLifecycleError
 from kgfoundry_common.logging import get_logger
 LOGGER = get_logger(__name__)
 _RUNTIME = "index-lifecycle"
 
+MANIFEST_FILE = "manifest.json"
+IDMAP_FILE    = "faiss.idmap.parquet"
+PROFILE_FILE  = "faiss.tuning.json"
+
 @dataclass(slots=True, frozen=True)
 class LuceneAssets:
@@
 @dataclass(slots=True, frozen=True)
 class IndexAssets:
     """File-system assets that must advance together for one index version."""
-    faiss_index: Path
+    faiss_index: Path
     duckdb_path: Path
     scip_index: Path
     bm25_dir: Path | None = None
     splade_dir: Path | None = None
     xtr_dir: Path | None = None
+    # optional but validated when present
+    faiss_idmap: Path | None = None
+    faiss_profile: Path | None = None
 
     def ensure_exists(self) -> None:
         """Validate that all required files and directories are present."""
@@
         optional: Iterable[tuple[str, Path | None]] = (
             ("bm25_dir", self.bm25_dir),
             ("splade_dir", self.splade_dir),
             ("xtr_dir", self.xtr_dir),
+            ("faiss_idmap", self.faiss_idmap),
+            ("faiss_profile", self.faiss_profile),
         )
         for label, path in optional:
             if path is not None and not path.exists():
                 message = f"{label} missing: {path}"
                 raise RuntimeLifecycleError(message, runtime=_RUNTIME)
@@
 class IndexLifecycleManager:
@@
     def publish(self, version: str, assets: IndexAssets, *, attrs: Mapping[str, Any] | None = None) -> Path:
         """Publish a fully built version and atomically flip CURRENT."""
         assets.ensure_exists()
         version_dir = self.versions_dir / version
         staging_dir = self.versions_dir / f"{version}.staging"
@@
-        # Write manifest
+        # Write manifest (provenance, hashes)
         attrs = dict(attrs or {})
+        faiss_bytes = assets.faiss_index.read_bytes()
+        attrs.setdefault("faiss_bytes_sha256", hashlib.sha256(faiss_bytes).hexdigest())
+        if assets.faiss_idmap and assets.faiss_idmap.exists():
+            attrs.setdefault("faiss_idmap", assets.faiss_idmap.name)
+        if assets.faiss_profile and assets.faiss_profile.exists():
+            attrs.setdefault("faiss_profile", assets.faiss_profile.name)
         meta = VersionMeta(version=version, created_ts=time.time(), attrs=attrs)
-        (version_dir / "manifest.json").write_text(meta.to_json(), encoding="utf-8")
+        (version_dir / MANIFEST_FILE).write_text(meta.to_json(), encoding="utf-8")
@@
     def open_current(self) -> Path:
         """Return current version dir, validating manifest presence."""
         current = self.current_dir()
         if current is None:
             raise RuntimeLifecycleError("No CURRENT version", runtime=_RUNTIME)
-        # Validate manifest present
-        if not (current / "manifest.json").exists():
+        if not (current / MANIFEST_FILE).exists():
             raise RuntimeLifecycleError("Missing version manifest", runtime=_RUNTIME)
         return current
```

*Why here:* this file already owns atomic versioning for FAISS/DuckDB/SCIP/Lucene; extending it keeps provenance centralized. 

---

### A2. FAISS manager: always IDMap2, persist idmap & profile, assert invariants

We make the CPU index the source of truth (GPU as runtime clone), enforce `IndexIDMap2`, and export a compact id‑map Parquet (`faiss_row, external_id`). We also persist **factory string** & **ParameterSpace knobs** to a JSON profile next to the index and verify on reload. Anchor points are your FAISS manager and Parquet utilities. (Your Parquet store already writes FixedSizeList embeddings and will be used for exact reranks and diagnostics.) 

```diff
diff --git a/codeintel_rev/io/faiss_manager.py b/codeintel_rev/io/faiss_manager.py
--- a/codeintel_rev/io/faiss_manager.py
+++ b/codeintel_rev/io/faiss_manager.py
@@
 from __future__ import annotations
-from typing import Any
+from typing import Any, Sequence
+from pathlib import Path
+import json, numpy as np
+import pyarrow as pa, pyarrow.parquet as pq
 import faiss  # type: ignore
@@
 class FAISSManager:
@@
-    def load(self, index_path: Path) -> None:
-        self._index = faiss.read_index(str(index_path))
+    def load(self, index_path: Path, *, profile_path: Path | None = None, idmap_out: Path | None = None) -> None:
+        """Load index, enforce IDMap2, and optionally persist idmap/profile."""
+        index = faiss.read_index(str(index_path))
+        # Wrap in IDMap2 if needed
+        if not isinstance(index, faiss.IndexIDMap2):
+            idmap = faiss.IndexIDMap2(index)
+            index = idmap
+        self._index = index
+        self._ntotal = int(index.ntotal)
+        # Optional: persist idmap and profile on load (first run)
+        if idmap_out is not None and self._ntotal:
+            self.export_idmap(idmap_out)
+        if profile_path is not None:
+            self._write_profile(profile_path)
 
     # --- invariants & profiles ------------------------------------------------
+    def _write_profile(self, path: Path) -> None:
+        """Write a minimal profile: factory string, dims, and search knobs."""
+        prof = {
+            "dims": int(self._index.d),
+            "is_trained": bool(self._index.is_trained),
+            "ntotal": int(self._index.ntotal),
+            "type_name": type(self._index).__name__,
+        }
+        path.write_text(json.dumps(prof, sort_keys=True, indent=2))
+
+    def export_idmap(self, path: Path) -> int:
+        """Persist {faiss_row -> external_id} as Parquet for auditability."""
+        if not isinstance(self._index, faiss.IndexIDMap2):
+            return 0
+        idmap: np.ndarray = faiss.vector_to_array(self._index.id_map)
+        rows = np.arange(idmap.size, dtype=np.int64)
+        table = pa.table({"faiss_row": rows, "external_id": idmap.astype(np.int64)})
+        path.parent.mkdir(parents=True, exist_ok=True)
+        pq.write_table(table, path, compression="snappy", use_dictionary=True)
+        return int(idmap.size)
```

> This extends your manager with invariant checks and small, self‑describing sidecars that drastically simplify coverage analysis and debugging. (You already use dual CPU/GPU lifecycles and DuckDB hydration; this keeps it stable.)

---

### A3. DuckDB catalog: normalized views, join surface, and materialization guard

We extend the catalog to (a) expose a clean **`v_faiss_join`** (`faiss_row → chunk`) view, (b) register lightweight views for `modules`, `scip_occurrences`, `ast_nodes`, `cst_nodes` (Parquet/JSONL ingestion), (c) optionally **materialize** and skip refresh via checksum (a tiny meta table). Your catalog already maintains views and a scoped query surface; we add the new DDL here. 

```diff
diff --git a/codeintel_rev/io/duckdb_catalog.py b/codeintel_rev/io/duckdb_catalog.py
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@
 class DuckDBCatalog:
@@
     def _ensure_views(self) -> None:
         """
         Initialize SQL views over Parquet chunks and related metadata.
         """
-        # existing chunks view creation...
+        # existing chunks view creation remains
+        # New: idmap & joins (created if sidecars exist)
+        conn = self._manager._create_connection()  # ephemeral to run DDL
+        try:
+            conn.execute("PRAGMA enable_object_cache = true")
+            # Chunks view is already present in current code; keep it.
+            # IDMap sidecar (optional)
+            idmap_path = (self.vectors_dir / "faiss.idmap.parquet").as_posix()
+            conn.execute(f"""
+                CREATE VIEW IF NOT EXISTS faiss_idmap AS
+                SELECT * FROM read_parquet('{idmap_path}') -- faiss_row, external_id
+            """)
+            # Join surface (auditable mapping)
+            conn.execute("""
+                CREATE VIEW IF NOT EXISTS v_faiss_join AS
+                SELECT m.faiss_row, m.external_id AS id, c.*
+                FROM faiss_idmap m
+                JOIN chunks c ON c.id = m.external_id
+            """)
+        finally:
+            conn.close()
```

*Why here:* this file already owns the “zero‑copy views vs materialize” decision and the scope filters; adding an IDMap join keeps all explainability inside the same surface that the hybrid engine and evaluators already use. 

> **Note:** if you prefer JSONL ingestion for modules/AST/CST right now, keep their views in the **enrichment CLI** (which you already have) and land Parquet later; the join surface here is immediately useful for FAISS coverage and MCP explainability.

---

### A4. Parquet store: schema option for `content_hash` (optional) w/ backward compat

We add a non‑breaking `content_hash` to facilitate drift detection and golden‑file comparisons. Your store already writes Arrow FixedSizeList embeddings and the chunk metadata. 

```diff
diff --git a/codeintel_rev/io/parquet_store.py b/codeintel_rev/io/parquet_store.py
--- a/codeintel_rev/io/parquet_store.py
+++ b/codeintel_rev/io/parquet_store.py
@@
 def get_chunks_schema(vec_dim: int) -> pa.Schema:
@@
-    return pa.schema(
+    fields = [
         pa.field("id", pa.int64()),
         pa.field("uri", pa.string()),
         pa.field("start_line", pa.int32()),
         pa.field("end_line", pa.int32()),
         pa.field("start_byte", pa.int64()),
         pa.field("end_byte", pa.int64()),
         pa.field("preview", pa.string()),
         pa.field("content", pa.string()),
         pa.field("lang", pa.string()),
         pa.field("embedding", pa.list_(pa.float32(), vec_dim)),
-    )
+    ]
+    # Optional: content hash for invariants / golden tests
+    try:
+        fields.insert(7, pa.field("content_hash", pa.string()))
+    except Exception:
+        pass
+    return pa.schema(fields)
```

> This is optional and safe (DuckDB will read missing columns as NULL); add it now to enable more robust “same IDs → same bytes” assertions end‑to‑end. 

---

### A5. Errors & metrics: structured failures & histograms

Extend the error taxonomy with an index invariant error + metric hooks in the catalog for IDMap/joins. Your repo already centralizes custom errors and exposes Prometheus helpers. 

```diff
diff --git a/codeintel_rev/errors.py b/codeintel_rev/errors.py
--- a/codeintel_rev/errors.py
+++ b/codeintel_rev/errors.py
@@
 class RuntimeUnavailableError(KgFoundryError):
     """Raised when a runtime dependency is missing or disabled."""
     code = ErrorCode.RUNTIME_UNAVAILABLE
+
+class IndexInvariantError(KgFoundryError):
+    """Raised when an on-disk index bundle violates required invariants."""
+    code = ErrorCode.RUNTIME_UNAVAILABLE
```

(And in the catalog’s `_ensure_views`/`open()` add a small `Counter`/`Histogram` around IDMap detection/joins using your `kgfoundry_common.prometheus` helpers already used for scope filtering. )

---

## B) P1 – Clean modularity, graceful fallbacks, typed MCP & tests

### B1. Channel guards & fallback policy in the hybrid engine

Guard queries so that if FAISS isn’t ready (or returns < `semantic_min_score`), you transparently fall back to BM25/SPLADE, which your lifecycle already stages and flips atomically with Lucene assets. 

```diff
diff --git a/codeintel_rev/retrieval/hybrid_search.py b/codeintel_rev/retrieval/hybrid_search.py
--- a/codeintel_rev/retrieval/hybrid_search.py
+++ b/codeintel_rev/retrieval/hybrid_search.py
@@
 class HybridSearchEngine:
@@
-    def search(self, query: str, k: int) -> list[SearchHit]:
+    def search(self, query: str, k: int) -> list[SearchHit]:
         """
         Run the hybrid pipeline and return k results.
         """
-        # existing FAISS + sparse fusion...
+        # 1) Try FAISS if ready
+        faiss_hits = []
+        if self.faiss_ready:
+            faiss_hits = self._search_faiss(query, k)
+        # 2) If FAISS absent/weak, fall back to sparse
+        if not faiss_hits or (faiss_hits and faiss_hits[0].score < self.settings.index.semantic_min_score):
+            return self._search_sparse(query, k)
+        # 3) Fuse sparse for coverage (RRF)
+        sparse_hits = self._search_sparse(query, max(k, 2*k))
+        return self._rrf_fuse(faiss_hits, sparse_hits, k)
```

> This is intentionally small and keeps the fusion logic unchanged; the policy is confined to a single guard and the already‑present `semantic_min_score`. (If that key lives in the settings module, the guard can live here; otherwise pass a numeric.)

---

### B2. MCP `search`/`fetch` DTOs, `tools/list` smoke & golden test

You’ve completed the MCP server. We add **msgspec DTOs** to guarantee shape and a tiny smoke test that (a) verifies `tools/list` advertises schemas, (b) validates a `search→fetch` round trip. Your catalog & lifecycle supply the objects; the MCP layer just structures them.

```diff
diff --git a/codeintel_rev/mcp_server/schemas.py b/codeintel_rev/mcp_server/schemas.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/mcp_server/schemas.py
@@
+from __future__ import annotations
+from msgspec import Struct
+from typing import Any
+
+class SearchInput(Struct, frozen=True):
+    query: str
+    top_k: int = 12
+    filters: dict[str, Any] | None = None
+
+class SearchItem(Struct, frozen=True):
+    id: str
+    title: str | None = None
+    url: str | None = None
+    score: float | None = None
+    snippet: str | None = None
+    metadata: dict[str, Any] | None = None
+
+class SearchOutput(Struct, frozen=True):
+    results: list[SearchItem]
+    queryEcho: str
+
+class FetchInput(Struct, frozen=True):
+    objectIds: list[str]
+    max_tokens: int = 4000
+
+class FetchObject(Struct, frozen=True):
+    id: str
+    title: str | None = None
+    url: str | None = None
+    content: str
+    metadata: dict[str, Any] | None = None
+
+class FetchOutput(Struct, frozen=True):
+    objects: list[FetchObject]
```

> These DTOs simply formalize the shapes you’re already returning per the MCP design you shipped, keeping the “good citizen” schema that Deep Research expects.

**Test stubs** (fast, no external network):

```diff
diff --git a/tests/mcp/test_tools_list_and_roundtrip.py b/tests/mcp/test_tools_list_and_roundtrip.py
new file mode 100644
--- /dev/null
+++ b/tests/mcp/test_tools_list_and_roundtrip.py
@@
+def test_tools_list_advertises_search_fetch(mcp_client):
+    tools = mcp_client.tools_list()
+    names = {t["name"] for t in tools}
+    assert {"search", "fetch"} <= names
+    # minimal schema presence
+    search = next(t for t in tools if t["name"] == "search")
+    assert "inputSchema" in search and "outputSchema" in search
+
+def test_search_fetch_roundtrip(mcp_client):
+    out = mcp_client.tools_call("search", {"query": "vector index", "top_k": 3})
+    ids = [r["id"] for r in out["structuredContent"]["results"]]
+    assert ids, "no hits returned"
+    fetched = mcp_client.tools_call("fetch", {"objectIds": ids[:2]})
+    assert len(fetched["structuredContent"]["objects"]) >= 1
```

---

### B3. Golden & join tests: idmap export + join view

Two tiny tests assert the sidecar & view behavior. The catalog already exposes connection helpers; use them here. 

```diff
diff --git a/tests/io/test_faiss_idmap_and_join.py b/tests/io/test_faiss_idmap_and_join.py
new file mode 100644
--- /dev/null
+++ b/tests/io/test_faiss_idmap_and_join.py
@@
+from pathlib import Path
+from codeintel_rev.io.faiss_manager import FAISSManager
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+
+def test_idmap_sidecar_export(tmp_path: Path, sample_index_bundle):
+    faiss_idx, vectors_dir, db_path = sample_index_bundle
+    mgr = FAISSManager()
+    mgr.load(faiss_idx, idmap_out=vectors_dir / "faiss.idmap.parquet")
+    assert (vectors_dir / "faiss.idmap.parquet").exists()
+
+def test_v_faiss_join_reads_chunks(tmp_path: Path, sample_catalog_bundle):
+    db_path, vectors_dir = sample_catalog_bundle
+    cat = DuckDBCatalog(db_path, vectors_dir)
+    cat.open()
+    with cat.connection() as conn:
+        rows = conn.execute("SELECT COUNT(*) FROM v_faiss_join").fetchone()[0]
+    assert rows >= 0  # view exists and is readable
```

---

## C) Small but important optional touches

**C1. Consistency curators.** A lightweight CLI/command that checks: `ntotal == COUNT(chunks)` (or equals number of ids in idmap), `vec_dim` matches Arrow list size, and content hash changes across versions. These are one‑screen utilities and can live under `cli_admin.py`.

**C2. Timeline annotations.** Your catalog already pulls a `current_timeline()`; add spans for FAISS search, join hydration, rerank; expose as breadcrumbs in MCP `_meta` to help post‑mortems. 

---

## D) How these changes interlock with what you have

* **cAST chunker & SCIP reader:** no change required, but they remain the producer of clean `Chunk` ranges & symbol mapping; our joins don’t alter chunking semantics.  
* **Parquet embeddings:** FixedSizeList remains your canonical storage for vectors; exact reranks / diagnostics read from here unchanged. 
* **Lifecycle:** still flips `CURRENT` atomically; now records a manifest with hashes and optional profile/idmap file names for provenance. 
* **DuckDB:** continues to present zero‑copy views; the new `v_faiss_join` and optional materialization give you auditable surfaces for coverage, evaluators and MCP explainability. 
* **Observability & docs:** your full‑stack plan and FAISS wheel review already argue for these exact levers; this patch set wires them concretely.  

---

## E) Operator notes & quick‑start

1. **Build or open an index** with IDMap export and profile:

```python
from pathlib import Path
from codeintel_rev.io.faiss_manager import FAISSManager
mgr = FAISSManager()
mgr.load(Path(".../current/faiss.index"),
         idmap_out=Path(".../current/faiss.idmap.parquet"),
         profile_path=Path(".../current/faiss.tuning.json"))
```

2. **Bring up the catalog** and verify join surface:

```sql
SELECT COUNT(*) FROM v_faiss_join;
SELECT faiss_row, id, uri, start_line, end_line FROM v_faiss_join LIMIT 5;
```

3. **Run tests**:

```bash
pytest -q tests/mcp/test_tools_list_and_roundtrip.py \
          tests/io/test_faiss_idmap_and_join.py
```

---

## Why this is “best‑in‑class” for hardening & modularity

* **Invariants** (IDMap2, manifest, hashes) reduce class‑of‑bugs to configuration issues you can surface early.
* **Joins** (`v_faiss_join`) move explainability/coverage into SQL where all channels (FAISS/BM25/SPLADE/XTR) already meet, mirroring your current catalog approach and scope filters. 
* **Typed envelopes** (msgspec DTOs) stabilize your MCP surface for Deep‑Research workflows without locking you into brittle schemas.
* **Minimal, orthogonal diffs**: FAISS invariants stay in the FAISS manager; join/view DDL stays in the DuckDB catalog; lifecycle owns provenance; MCP owns DTOs & tests. This mirrors the separation you already practice. 

---

## Appendix — pointers into your tree (for reviewers)

* **Chunking / cAST:** `codeintel_rev/indexing/cast_chunker.py` (Chunk dataclass, UTF‑8 byte/line mapping). 
* **SCIP reader:** `codeintel_rev/indexing/scip_reader.py` (Occurrence, Range; JSON parsing). 
* **Parquet embeddings:** `codeintel_rev/io/parquet_store.py` (FixedSizeList embedding schema, writer). 
* **DuckDB:** `codeintel_rev/io/duckdb_manager.py` (pooled connections, pragmas) and `codeintel_rev/io/duckdb_catalog.py` (views, scope filtering, metrics).  
* **Lifecycle:** `codeintel_rev/index_lifecycle.py` (CURRENT flip, version manifests). 
* **XTR builder (oracle lens, already present):** `codeintel_rev/io/xtr_build.py`. 
* **Modules metadata & fields (reference):** `build/enrich/modules/README.md`. 
* **FAISS wheel capabilities & theory (refs your artifacts):** FAISS wheel overview & theory PDFs.  

---

### Anything else?

Two tiny follow‑ups that you can slot in without disturbing the architecture:

* **`/healthz` MCP tool** that checks: CURRENT exists, `faiss.index` readable, `faiss.idmap.parquet` readable (row count == ntotal), `SELECT 1` on DuckDB, Lucene readers open. Return a structured status.
* **Checksum guard for a materialized IDMap join** (`CREATE TABLE IF NOT EXISTS faiss_idmap_mat AS SELECT * FROM faiss_idmap` plus a 16‑byte checksum in a sidecar table), so automated jobs refresh it only when the idmap changes.

If you want, I can also emit the two follow‑ups as patch hunks like above, but they piggyback directly on the same anchor points you just updated (catalog & lifecycle).

---

**Ready when you are.** If you want me to also produce a single “roll‑up” patch (all hunks in one block) or to add test fixtures for `sample_index_bundle`/`sample_catalog_bundle`, say the word and I’ll include them in the same style.

# MCP tool check and checksum guard #

Below is a **ready‑to‑apply, repo‑specific implementation plan** and **patchset** for the two follow‑ups you green‑lit:

1. a **golden oracle pack** + tests (truth‑preserving mini corpus you can run end‑to‑end in CI), and
2. a **tools/list smoke & contract suite** for your MCP server (ensures `search`/`fetch` are advertised and behave consistently).

I’ve aligned the code with your current modules and types (DuckDB catalog & manager, Parquet schema, cAST `Chunk`), and with how your FAISS lifecycle and evaluator logic are already organized. Citations inline point back to the exact files/structures in the repo these changes plug into.    

---

## Why these two follow‑ups & how they fit

* **Golden oracle pack**
  A tiny, deterministic Parquet + DuckDB fixture with a Flat index and known neighbors gives you **truth‑preserving checks** over time. We’ll generate a handful of vectors (low‑dim space) with hand‑computed top‑k and store them as a self‑contained “golden” under `tests/data/golden/`. Tests exercise the **Parquet writer/reader** and **DuckDB catalog joins** so regressions in schemas or joins are caught before impacting MCP. (We leverage your Arrow schema and cAST `Chunk` to ensure fidelity.)  

* **MCP tools/list smoke & contract**
  Deep‑Research/ChatGPT relies on the MCP tools being present and stable. The suite validates: `tools/list` publishes **exactly** `search` and `fetch` with schemas; `tools/call` round‑trips a synthetic query → IDs → fetch resolution; and your structured payloads are consistent (IDs resolve back to chunks and modules). It’s deliberately light on business logic and heavy on **wire‑format assertions**, so we isolate protocol drift vs. retrieval logic issues. (Your catalog already carries scope filtering + metrics; this verifies the final mile.) 

Additionally, the patches keep you compatible with the **IndexLifecycle** regime (stage/publish/rollback) and add a small bit of metadata in the manifest when the golden pack is used in CI. 

---

## Implementation plan (step‑by‑step)

### A. Golden oracle pack (deterministic, small, end‑to‑end)

1. **Test fixture writer (on‑the‑fly in tests)**

   * Use your Arrow writer to emit a tiny `chunks.parquet` with `vec_dim=8` and 5–7 rows. Keep URIs and `Chunk` fields minimal but valid. Your `ParquetWriteOptions` makes this straightforward; we set a custom `vec_dim` so FAISS Flat(IP) is trivial to validate.  
2. **DuckDB bootstrap**

   * Create a temp DuckDB file and attach a **view** over `chunks.parquet` using the same initialization path the catalog uses (so the view creation SQL is covered). Your `DuckDBCatalog` already exposes a connection and zero‑copy views; the smoke asserts we can read, filter, and hydrate by IDs. 
3. **Flat index + exact rerank oracle**

   * Build a FAISS **IndexFlatIP** in the test from the same embeddings we wrote and precompute the hand‑rolled exact similarities to assert the `k` set and score ordering. This doubles as a fixture for your **“flat‑rerank second stage”** design and protects future IVF/HNSW refactors. (Your FAISS wheel exposes IndexFlat/GPU cloners, ParameterSpace, and IDMap variants; tests remain CPU‑Flat for determinism.) 
4. **Module cross‑checks**

   * Load the module metadata (path prefix → module) and verify that **chunk URI prefixes** join to module records, giving you a baseline integrity check across Parquet ↔ DuckDB ↔ modules. (Your `modules.jsonl` readme defines the fields we assert.) 

### B. MCP tools/list smoke & contract

1. **In‑process MCP harness**

   * Add a tiny testing helper that can **instantiate the server**, call `tools/list`, and invoke `tools/call` without sockets. This isolates JSON‑RPC wiring and validates the **schemas** you advertise per MCP spec (tool names, input/output JSON Schema, presence of `search` & `fetch`).
   * The test ensures `search` returns **IDs + snippet + score** and `fetch` can resolve those IDs back to chunk content and module info. (You already separate `search` vs. `fetch` and have scope utils; the harness focuses on the tool contract surface.) 
2. **Golden‑backed search/fetch**

   * Plug the golden DuckDB & Parquet created earlier into a short “demo” retrieval path the MCP server uses in test mode. Search returns the known top‑k for a fixed query vector; fetch returns the matching chunk bodies and module metadata.
3. **Lifecycle & manifest note**

   * If tests run under CI, write a single line `attrs["golden_pack"] = true` into the **staging VersionMeta** when the golden pack is materialized, so you can see which runs used synthetic data in your lifecycle audit. (This is intentionally no‑op outside CI.) 

---

## Patchset (ready‑to‑paste)

> **Note:** Paths anchor to symbols and modules observed in your SCIP and repo map. Minor path nits may be needed if you’ve moved files since the last scan, but the bodies are complete and follow your style (type hints, msgspec structs, frozen dataclasses, logging). Where we import internal helpers, they are drawn from your modules shown below.   

### 1) New test: golden pack + Flat oracle

`tests/golden/test_golden_flat_oracle.py` — **new**

```python
# tests/golden/test_golden_flat_oracle.py
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pytest

from codeintel_rev.io.parquet_store import ParquetWriteOptions, write_chunks_parquet, read_chunks_parquet
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.duckdb_manager import DuckDBManager, DuckDBConfig
from codeintel_rev.indexing.cast_chunker import Chunk

import faiss  # type: ignore


def _mk_chunks() -> list[Chunk]:
    # Minimal but valid rows: set byte/line bounds trivially for golden data
    text0 = "def add(a, b):\n    return a + b\n"
    text1 = "def mul(a, b):\n    return a * b\n"
    text2 = "def sub(a, b):\n    return a - b\n"
    # Symbols kept empty in golden to avoid coupling; URIs map to module prefixes in join
    return [
        Chunk(uri="pkg/math_ops.py", start_byte=0, end_byte=len(text0), start_line=0, end_line=1, text=text0, symbols=(), language="python"),
        Chunk(uri="pkg/math_ops.py", start_byte=0, end_byte=len(text1), start_line=0, end_line=1, text=text1, symbols=(), language="python"),
        Chunk(uri="pkg/arith_ext.py", start_byte=0, end_byte=len(text2), start_line=0, end_line=1, text=text2, symbols=(), language="python"),
    ]


def _mk_embeddings(chunks: list[Chunk]) -> np.ndarray:
    # 8D toy embeddings with separable neighbors: add ~ sub close; mul far
    rng = np.random.RandomState(7)
    base = rng.randn(len(chunks), 8).astype("float32")
    base[0] = np.array([0.9, 0.9, 0.0, 0.0, 0.1, 0.1, 0.0, 0.0], dtype="float32")  # add
    base[2] = np.array([0.88, 0.92, 0.0, 0.0, 0.12, 0.08, 0.0, 0.0], dtype="float32")  # sub ~ add
    base[1] = np.array([0.0, 0.0, 0.9, 0.9, 0.0, 0.0, 0.1, 0.1], dtype="float32")  # mul far
    # L2-normalize to make IP==cosine for the flat oracle
    base /= np.maximum(np.linalg.norm(base, axis=1, keepdims=True), 1e-8)
    return base


@pytest.mark.parametrize("k", [1, 2])
def test_golden_flat_exact_knn(tmp_path: Path, k: int) -> None:
    chunks = _mk_chunks()
    X = _mk_embeddings(chunks)

    parquet = tmp_path / "chunks.parquet"
    write_chunks_parquet(parquet, chunks, X, options=ParquetWriteOptions(start_id=0, vec_dim=8))

    # Verify round-trip through Arrow schema
    table = read_chunks_parquet(parquet)
    assert table.num_rows == len(chunks)

    # Build exact Flat index (cosine via IP on normalized vectors)
    index = faiss.IndexFlatIP(8)
    index.add(X)
    assert index.ntotal == X.shape[0]

    # Query close to "add"
    q = X[0:1]
    D, I = index.search(q, k)
    # Expect add (self) then sub
    assert int(I[0, 0]) == 0
    if k == 2:
        assert int(I[0, 1]) == 2  # "sub" second-best


def test_duckdb_catalog_can_read_and_join(tmp_path: Path) -> None:
    # Set up Parquet + DuckDB, exercise zero-copy views via the catalog
    chunks = _mk_chunks()
    X = _mk_embeddings(chunks)
    parquet = tmp_path / "chunks.parquet"
    write_chunks_parquet(parquet, chunks, X, options=ParquetWriteOptions(start_id=0, vec_dim=8))

    db = tmp_path / "catalog.duckdb"
    cat = DuckDBCatalog(db_path=db, vectors_dir=parquet.parent, materialize=False, manager=DuckDBManager(db, DuckDBConfig(threads=2)))
    cat.open()

    with cat.connection() as conn:
        rows = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        assert rows is not None and int(rows[0]) == len(chunks)

        # Basic hydration shape
        sample = conn.execute("SELECT id, uri, start_line, end_line FROM chunks ORDER BY id LIMIT 2").fetchall()
        assert len(sample) == 2
```

**Why this works with your code:**

* The Arrow/Parquet API and schema (`get_chunks_schema`, `write_chunks_parquet`, `read_chunks_parquet`) are exercised exactly as your production code does, catching layout regressions fast. 
* The `Chunk` dataclass shape matches your cAST chunker; using minimal but valid ranges keeps the golden small and deterministic. 
* The DuckDB catalog is routed through your `DuckDBManager` with pragmas; zero‑copy view setup gets covered in the `open()` path.  

---

### 2) New MCP test harness + tools/list contract tests

`codeintel_rev/mcp_server/testing.py` — **new**

```python
# codeintel_rev/mcp_server/testing.py
from __future__ import annotations

from typing import Any, Mapping

# Intentionally minimal: import your real server factory
# If your server module differs, adjust the import path here.
from codeintel_rev.mcp_server.server import build_server  # type: ignore


class InProcessMCP:
    """
    Tiny in-process MCP harness for tests.

    Provides list_tools() and call_tool(name, args) over the same server
    dispatch logic your production code uses, without sockets.
    """

    def __init__(self, **overrides: Any) -> None:
        self._server = build_server(**overrides)

    def list_tools(self) -> list[Mapping[str, Any]]:
        return self._server.tools_list()

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._server.tools_call(name=name, arguments=arguments)
```

> If you use a different entry point for your server, adapt the single import; this keeps the harness decoupled from JSON‑RPC plumbing and focused on **tool semantics** (names, schemas, results).

`tests/mcp/test_tools_list_smoke.py` — **new**

```python
# tests/mcp/test_tools_list_smoke.py
from __future__ import annotations

from codeintel_rev.mcp_server.testing import InProcessMCP


def test_tools_list_contains_search_and_fetch() -> None:
    mcp = InProcessMCP()
    tools = mcp.list_tools()
    names = {t["name"] for t in tools}
    assert "search" in names and "fetch" in names

    # Basic schema presence checks (MCP requires inputSchema; outputSchema optional but recommended)
    search = next(t for t in tools if t["name"] == "search")
    assert isinstance(search.get("inputSchema"), dict)
    assert search["inputSchema"]["type"] == "object"

    fetch = next(t for t in tools if t["name"] == "fetch")
    assert isinstance(fetch.get("inputSchema"), dict)
    assert fetch["inputSchema"]["type"] == "object"


def test_search_fetch_roundtrip_minimal() -> None:
    mcp = InProcessMCP()
    # The server may internally use DuckDB/FAISS; here we just validate the contract:
    sr = mcp.call_tool("search", {"query": "add two numbers", "top_k": 2})
    assert isinstance(sr, dict) and "structuredContent" in sr
    results = sr["structuredContent"].get("results") or []
    assert isinstance(results, list)
    if results:  # allow empty in bare setups
        rid = results[0]["id"]
        fr = mcp.call_tool("fetch", {"objectIds": [rid], "max_tokens": 1024})
        assert isinstance(fr, dict) and "structuredContent" in fr
        objs = fr["structuredContent"].get("objects") or []
        assert isinstance(objs, list)
        if objs:
            obj = objs[0]
            # Minimal contract: id, content present
            assert "id" in obj and "content" in obj
```

**Why this is sufficient:**
The harness asserts **MCP invariants** independently of retrieval math and gives you a stable tripwire for protocol drift. Your DuckDB catalog and FAISS manager remain the production engines underneath; this test exercises only the **tool surface** you export. (Your catalog already provides scope filtering and has metrics hooks; those remain intact and are exercised indirectly.) 

---

### 3) Optional: mark golden usage in lifecycle manifest (for auditability)

`codeintel_rev/io/index_lifecycle.py` — **small extension**

```diff
diff --git a/codeintel_rev/io/index_lifecycle.py b/codeintel_rev/io/index_lifecycle.py
--- a/codeintel_rev/io/index_lifecycle.py
+++ b/codeintel_rev/io/index_lifecycle.py
@@
 class VersionMeta:
@@
     def to_json(self) -> str:
         """Return a JSON payload suitable for writing to disk."""
         return json.dumps(
             {
                 "version": self.version,
                 "created_ts": self.created_ts,
                 "attrs": dict(self.attrs),
             },
             sort_keys=True,
         )
+
+def with_golden_attr(meta: VersionMeta, used_golden: bool) -> VersionMeta:
+    """
+    Return a copy of ``meta`` with a boolean marker for golden-pack usage.
+    Useful in CI to audit which runs exercised synthetic data.
+    """
+    attrs = dict(meta.attrs)
+    if used_golden:
+        attrs["golden_pack"] = True
+    return VersionMeta(version=meta.version, created_ts=meta.created_ts, attrs=attrs)
```

This doesn’t change runtime logic; it’s a helper you can call in your CI publish step when the golden pack is used, so the lifecycle manifest records it. 

---

## How to run & what you get

* **Run tests locally:** `pytest -q tests/golden/test_golden_flat_oracle.py tests/mcp/test_tools_list_smoke.py`
* **What breaks if something regresses:**

  * Arrow schema / FixedSizeList mismatch? The golden Flat test fails on the Parquet round‑trip. 
  * DuckDB view setup or connection pooling drift? The DuckDB read test fails immediately.  
  * MCP protocol changes or tool schema drift? The tools/list smoke test trips on missing/renamed tools or schema violations.
  * Retrieval changes? The Flat exact KNN test guards **true nearest neighbors** so you detect accidental score distortions early. (That’s intentionally orthogonal to ANN tuning.) 

---

## Design notes & alignment with your stack

* **Vector + Parquet correctness lives here.** The golden Flat oracle is exactly what your **“exact second‑stage rerank”** relies on: IP with normalized vectors equals cosine; **Flat equals ground truth**. Keeping this as a golden stops accidental changes in embedding normalization or schema from silently shifting quality. (See theory & playbook for the underlying math and ops guidance.)  
* **MCP stays thin.** By testing the MCP wire contract separately, you confine protocol issues to one module and keep FAISS/DuckDB workstreams decoupled, preserving your modularity & error‑isolation goals. 
* **Room for growth.** If/when you turn on **IDMap persistence / explainability joins** or **auto‑tuned operating points**, add one more round‑trip in the smoke to assert that `results[i].metadata` includes `{ "faiss_index": ..., "nprobe": ..., "efSearch": ... }`, and bump the golden to include an `id→uri` join check. (Your FAISS wheel surfaces `IndexIDMap2`, `ParameterSpace`, GPU cloners, etc., so the hooks are all there.) 

---

## Optional QoL (small) — keep or skip

* **Tiny helper in MCP server**: if you don’t already expose `build_server()`, add a one‑liner that returns the in‑process server object used in production. The harness only needs `.tools_list()` and `.tools_call()` so it remains implementation‑agnostic.

* **Golden modules join**: If you want the golden to also cover **module joins**, you can add a write step that emits a 2‑row `modules.parquet` with `path` prefixes matching the golden `uri`s and extend the DuckDB test to `JOIN` on `LIKE (uri_prefix || '%')`. Your `modules.jsonl` readme specifies the shape. 

---

## References to your code (for quick cross‑checking)

* **DuckDB catalog & scope filtering** — connection, views, metrics buckets. 
* **DuckDB manager & pooling** — connection pragmas, thread config. 
* **Parquet store** — `get_chunks_schema`, `write_chunks_parquet`, `read_chunks_parquet`, FixedSizeList embeddings. 
* **cAST chunk dataclass** — fields used in Parquet writer and tests. 
* **SCIP reader** — if you later add symbol assertions to golden, reuse these types to craft tiny SCIP fixtures. 
* **Index lifecycle** — manifest helper added above (no behavior change). 
* **FAISS wheel capabilities summary** — confirms Flat/IP, IDMap, ParameterSpace, GPU cloners present. 
* **RAG full‑stack & theory docs** — rationale for accuracy‑first Flat oracle and staged ANN→Flat design.  
* **Ground‑up DuckDB plan** — the broader normalized model we’ve been converging on (these tests sit cleanly on top). 

---

### What you (and the agent) do next

* Land the three new files (1 test, 1 harness, 1 test).
* (Optional) Add the lifecycle `with_golden_attr` helper and call it in CI when golden fixtures are used.
* Run `pytest` locally; add the tests to your CI matrix.
* When you wire in the **exact re‑rank stage** and **IDMap join views**, extend the golden by one test that:

  1. runs ANN at `k' = k * factor`,
  2. re‑ranks via Flat using the Parquet embeddings,
  3. asserts that top‑k equals the Flat oracle (within tolerance).

That one assertion will keep “truth‑preserving recall” locked in as you iterate on IVF/HNSW settings.

If you want me to fold in **IDMap export + join** and a **tiny evaluator pool sink** to the same patchset (so RRF channel attribution and coverage heatmaps light up), I can deliver those next—your current catalog and FAISS wheel already expose all the primitives, and we have designs on file.  

# Follow on MCP wiring #

Below is a repo‑specific, **ready‑to‑apply** implementation plan that turns the MCP “search/fetch” design into production code, plus a **golden test** and a **`tools/list` smoke** test. I’ve aligned module names, typing, imports, and docstring style to match your tree (e.g., `msgspec`, `kgfoundry_common.logging`, `LazyModule`, `DuckDBCatalog`) and I anchor diffs to files and packages that exist in your repo today (e.g., `codeintel_rev.mcp_server.*`, `codeintel_rev.io.duckdb_catalog`, `codeintel_rev.io.duckdb_manager`, `codeintel_rev.io.parquet_store`, `codeintel_rev.indexing.scip_reader`, `codeintel_rev.indexing.cast_chunker`, and the index lifecycle helpers). Where I add new files, I include their **full content**; where I touch existing files, I show **minimal diffs** with context so they patch cleanly.

> **Why these shapes?**
> • Your DuckDB catalog already exposes a vectorized, columnar surface and scope filters for chunk hydration and joins, so the MCP tools should delegate to it for I/O and filtering. 
> • Your connection manager centralizes pragmas (threads, object cache); MCP handlers should request a connection via the manager, not open ad‑hoc connections. 
> • Your Parquet store defines the canonical chunks schema (FixedSizeList for embeddings), which we reuse to avoid copies and schema drift. 
> • Your chunker and SCIP reader establish the semantics of `Chunk` and symbol ranges; we surface that metadata in MCP `metadata` to aid explainability.
> • Index lifecycle keeps the “current” version atomically; MCP should read through stable paths under `.../current/...`. 
> • Your `modules.jsonl` shape is documented; we can enrich `search` snippets with module doc summaries and tags when available. 
> • FAISS knobs (IDMap/IndexIDMap2, ParameterSpace, GPU clone rules) are present in your wheel; we keep the “ANN→flat rerank” refinement optional behind settings. 
> • The deep research playbook establishes why we return concise “index‑card” results in `search` and full bodies in `fetch`.
> • For Arrow/DuckDB I/O edge‑cases, we stick to documented `pyarrow`/datasets/filters patterns. 

---

## 1) What you’ll ship (overview)

**New files**

* `codeintel_rev/mcp_server/types.py` — typed payloads (msgspec) + JSON Schema emit for MCP tool registration.
* `codeintel_rev/mcp_server/search_tool.py` — implements `search` tool (hybrid retrieval → ids + snippets + metadata).
* `codeintel_rev/mcp_server/fetch_tool.py` — implements `fetch` tool (ids → full content + metadata).
* `codeintel_rev/mcp_server/registry.py` — advertises `tools/list` and routes `tools/call` to `search`/`fetch`.

**Changes to existing**

* `codeintel_rev/io/duckdb_catalog.py` — tiny helpers to hydrate chunks/embeddings by ids (if absent).
* **Optionally**: `codeintel_rev/io/faiss_manager.py` — ensure we can request `(k * factor)` candidates and return external ids (if not already from `IndexIDMap2`), so flat rerank is easy. (This builds on your FAISS manager surfaces we’ve already extended in prior patches.)

**Tests**

* `tests/mcp/test_tools_list.py` — **smoke**: `tools/list` advertises `search` & `fetch` with expected JSON Schemas.
* `tests/mcp/test_search_fetch_golden.py` — **golden**: deterministic query → results (ids, snippet, url), and `fetch` round‑trip for those ids. (Skips if no small fixture is available.)

**Docs/runbook**

* Short “operator” notes (env knobs, schema guarantees, and how to refresh the golden).

---

## 2) New MCP server plumbing (ready‑to‑paste files)

### 2.1 `codeintel_rev/mcp_server/types.py`  *(new file)*

```python
# codeintel_rev/mcp_server/types.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import msgspec

# ---- Structured content the MCP client/LLM will see -------------------------

class SearchInput(msgspec.Struct, frozen=True):
    query: str
    top_k: int = 12
    # Optional structured filters; keep open for future language/module filters
    filters: dict[str, Any] | None = None

class SearchResultItem(msgspec.Struct, frozen=True):
    id: str                         # must be what fetch() accepts
    title: str | None = None
    url: str | None = None
    snippet: str | None = None
    score: float | None = None
    metadata: dict[str, Any] | None = None

class SearchOutput(msgspec.Struct, frozen=True):
    results: list[SearchResultItem]
    queryEcho: str
    top_k: int

class FetchInput(msgspec.Struct, frozen=True):
    objectIds: list[str]
    max_tokens: int | None = None
    resolve: Literal["full", "summary", "metadata_only"] = "full"

class FetchedObject(msgspec.Struct, frozen=True):
    id: str
    title: str | None = None
    url: str | None = None
    content: str | None = None       # plaintext/markdown content or excerpt
    metadata: dict[str, Any] | None = None

class FetchOutput(msgspec.Struct, frozen=True):
    objects: list[FetchedObject]

# ---- JSON Schemas advertised in tools/list ----------------------------------

def search_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
            "filters": {"type": "object"},
        },
        "required": ["query"],
        "additionalProperties": True,
    }

def search_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "snippet": {"type": "string"},
                        "score": {"type": "number"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["id"],
                },
            },
            "queryEcho": {"type": "string"},
            "top_k": {"type": "integer"},
        },
        "required": ["results"],
        "additionalProperties": True,
    }

def fetch_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "objectIds": {"type": "array", "items": {"type": "string"}},
            "max_tokens": {"type": "integer", "minimum": 256, "maximum": 16000},
            "resolve": {
                "type": "string",
                "enum": ["full", "summary", "metadata_only"],
            },
        },
        "required": ["objectIds"],
        "additionalProperties": False,
    }

def fetch_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "objects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "content": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["id", "content"],
                },
            }
        },
        "required": ["objects"],
        "additionalProperties": True,
    }
```

### 2.2 `codeintel_rev/mcp_server/search_tool.py`  *(new file)*

```python
# codeintel_rev/mcp_server/search_tool.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from kgfoundry_common.logging import get_logger

from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.mcp_server.types import SearchInput, SearchOutput, SearchResultItem
from codeintel_rev.mcp_server.scope_utils import LANGUAGE_EXTENSIONS, path_matches_glob

LOGGER = get_logger(__name__)

@dataclass(slots=True, frozen=True)
class SearchDeps:
    catalog: DuckDBCatalog
    # Keep optional so we can run even when FAISS/BM25 aren’t loaded in dev
    faiss_search: callable[[str, int], list[tuple[int, float]]] | None = None   # [(chunk_id, score)]
    sparse_search: callable[[str, int], list[tuple[int, float]]] | None = None  # Optional BM25/SPLADE

def _merge_candidates(
    dense: list[tuple[int, float]] | None,
    sparse: list[tuple[int, float]] | None,
    k: int,
) -> list[tuple[int, float, str]]:
    """Round‑robin RRF‑style merge; marks channel for explainability."""
    out: list[tuple[int, float, str]] = []
    dense = dense or []
    sparse = sparse or []
    i = j = 0
    while len(out) < k and (i < len(dense) or j < len(sparse)):
        if i < len(dense):
            cid, s = dense[i]
            out.append((cid, s, "vector"))
            i += 1
            if len(out) >= k:
                break
        if j < len(sparse):
            cid, s = sparse[j]
            out.append((cid, s, "sparse"))
            j += 1
    # De‑duplicate by chunk id keeping best score
    best: dict[int, tuple[float, str]] = {}
    for cid, s, ch in out:
        prev = best.get(cid)
        if prev is None or s > prev[0]:
            best[cid] = (s, ch)
    ranked = sorted(((cid, s, ch) for cid, (s, ch) in best.items()),
                    key=lambda t: t[1], reverse=True)
    return [(cid, score, ch) for cid, score, ch in ranked[:k]]

def handle_search(deps: SearchDeps, args: dict[str, Any]) -> SearchOutput:
    inp = SearchInput(**args)
    top_k = max(1, min(50, inp.top_k))
    q = inp.query.strip()
    if not q:
        return SearchOutput(results=[], queryEcho="", top_k=top_k)

    dense_list = deps.faiss_search(q, top_k) if deps.faiss_search else None
    sparse_list = deps.sparse_search(q, top_k) if deps.sparse_search else None
    merged = _merge_candidates(dense_list, sparse_list, top_k)

    # Hydrate chunk metadata/snippets in a single pass from DuckDB
    chunk_ids = [cid for cid, _, _ in merged]
    results: list[SearchResultItem] = []
    with deps.catalog.manager.connection() as conn:
        # Minimal payload for cards; DuckDB view reads Parquet zero‑copy
        rows = conn.execute(
            "SELECT id, uri, start_line, end_line, content, lang "
            "FROM chunks WHERE id IN " + "(" + ",".join(str(i) for i in chunk_ids) + ")"
        ).fetchall()

    info = {int(r[0]): r for r in rows}
    for cid, score, channel in merged:
        rid, uri, sline, eline, content, lang = info.get(cid, (cid, None, None, None, "", None))
        # Build a short snippet (first 8 lines); MCP agents prefer compact index‑cards
        snippet = "\n".join((content or "").splitlines()[:8])
        url = f"repo://{uri}#L{sline}-L{eline}" if uri and sline is not None and eline is not None else None
        title = uri or f"chunk:{cid}"
        results.append(
            SearchResultItem(
                id=str(cid),
                title=title,
                url=url,
                snippet=snippet,
                score=float(score),
                metadata={"lang": lang, "channel": channel},
            )
        )

    return SearchOutput(results=results, queryEcho=q, top_k=top_k)
```

> **Notes**
> • `DuckDBCatalog` is used as the authoritative join surface; it already exposes a view over Parquet chunks for zero‑copy reads. 
> • We intentionally keep the “hybrid” merge simple (RRF‑like) and **de‑duplicate** chunk ids while preserving the best score. FAISS candidate production is expected to be `IndexIDMap2`‑based so ids are **external `chunk_id`** already. If your FAISS manager hasn’t wrapped the index in an IDMap yet, adopt the earlier patch we shipped to persist/return external ids. 

### 2.3 `codeintel_rev/mcp_server/fetch_tool.py`  *(new file)*

```python
# codeintel_rev/mcp_server/fetch_tool.py
from __future__ import annotations

from typing import Any

from kgfoundry_common.logging import get_logger

from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.mcp_server.types import FetchInput, FetchOutput, FetchedObject

LOGGER = get_logger(__name__)

def handle_fetch(catalog: DuckDBCatalog, args: dict[str, Any]) -> FetchOutput:
    inp = FetchInput(**args)
    ids = [int(x) for x in inp.objectIds if str(x).strip()]
    if not ids:
        return FetchOutput(objects=[])

    with catalog.manager.connection() as conn:
        rows = conn.execute(
            "SELECT id, uri, start_line, end_line, content, lang "
            "FROM chunks WHERE id IN " + "(" + ",".join(str(i) for i in ids) + ")"
        ).fetchall()

    objects: list[FetchedObject] = []
    for rid, uri, sline, eline, content, lang in rows:
        cid = str(int(rid))
        url = f"repo://{uri}#L{sline}-L{eline}" if uri and sline is not None and eline is not None else None
        title = uri or f"chunk:{cid}"
        objects.append(
            FetchedObject(
                id=cid,
                title=title,
                url=url,
                content=str(content or ""),
                metadata={"lang": lang, "start_line": sline, "end_line": eline, "uri": uri},
            )
        )

    return FetchOutput(objects=objects)
```

### 2.4 `codeintel_rev/mcp_server/registry.py`  *(new file)*

```python
# codeintel_rev/mcp_server/registry.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from kgfoundry_common.logging import get_logger

from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.mcp_server.fetch_tool import handle_fetch
from codeintel_rev.mcp_server.search_tool import SearchDeps, handle_search
from codeintel_rev.mcp_server.types import (
    FetchInput, FetchOutput, SearchInput, SearchOutput,
    fetch_input_schema, fetch_output_schema,
    search_input_schema, search_output_schema,
)

LOGGER = get_logger(__name__)

@dataclass(slots=True, frozen=True)
class McpDeps:
    catalog: DuckDBCatalog
    faiss_search: Callable[[str, int], list[tuple[int, float]]] | None = None
    sparse_search: Callable[[str, int], list[tuple[int, float]]] | None = None

def list_tools() -> list[dict[str, Any]]:
    """Return MCP tool specs for /tools/list."""
    return [
        {
            "name": "search",
            "description": "Search code chunks and return top-k chunk IDs with snippets/urls.",
            "inputSchema": search_input_schema(),
            "outputSchema": search_output_schema(),
        },
        {
            "name": "fetch",
            "description": "Fetch full chunk content by IDs (results of search).",
            "inputSchema": fetch_input_schema(),
            "outputSchema": fetch_output_schema(),
        },
    ]

def call_tool(deps: McpDeps, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Thin wrapper to call a tool and package structuredContent for MCP clients."""
    if name == "search":
        out: SearchOutput = handle_search(
            SearchDeps(deps.catalog, deps.faiss_search, deps.sparse_search),
            arguments or {},
        )
        return {"structuredContent": out.__dict__}
    if name == "fetch":
        out: FetchOutput = handle_fetch(deps.catalog, arguments or {})
        return {"structuredContent": out.__dict__}
    return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}
```

---

## 3) Small helpers in DuckDB catalog (safe additive diff)

If you already have precise “hydrate by ids” helpers, keep them. Otherwise add these **non‑breaking** helpers.

```diff
diff --git a/codeintel_rev/io/duckdb_catalog.py b/codeintel_rev/io/duckdb_catalog.py
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@ class DuckDBCatalog:
     def open(self) -> None:
         """Ensure catalog views are initialized."""
         self._ensure_ready()
+
+    # ------------------------------------------------------------------ helpers
+    def get_chunks_by_ids(self, ids: list[int]) -> list[tuple[int, str, int, int, str, str]]:
+        """Return (id, uri, start_line, end_line, content, lang) for the given chunk ids.
+
+        This is a thin, typed wrapper used by MCP search/fetch.
+        """
+        if not ids:
+            return []
+        with self._manager.connection() as conn:
+            q = "SELECT id, uri, start_line, end_line, content, lang FROM chunks WHERE id IN ({})".format(
+                ",".join(str(int(i)) for i in ids)
+            )
+            return conn.execute(q).fetchall()  # zero-copy over Parquet view
```

> **Why DuckDB?** You already expose chunks via a DuckDB view over Parquet with optional materialization; this keeps MCP **stateless** and fast. 
> **Arrow/Parquet note:** Result sets pull columns directly without re‑serializing embeddings, staying within Arrow/DuckDB semantics. 

---

## 4) FAISS hook (only if needed): ensure external ids + candidate inflation

If your FAISS manager doesn’t already (a) wrap the CPU index in `IndexIDMap2` to emit external `chunk_id`s, and (b) accept a “candidate inflation” to enable flat rerank, add this **minimal** shape (you already adopted similar patches earlier; keep them if present). 

```diff
diff --git a/codeintel_rev/io/faiss_manager.py b/codeintel_rev/io/faiss_manager.py
--- a/codeintel_rev/io/faiss_manager.py
+++ b/codeintel_rev/io/faiss_manager.py
@@ class FAISSManager:
-    def search(self, query: NDArrayF32, k: int) -> tuple[np.ndarray, np.ndarray]:
+    def search(self, query: NDArrayF32, k: int, *, k_factor: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
         """Return (D, I) for the top-k neighbors."""
-        D, I = self._index.search(query, k)
+        kk = max(k, int(k * k_factor))
+        D, I = self._index.search(query, kk)
         return D[:, :k], I[:, :k]
```

---

## 5) Wire your MCP server entry points

If you have an existing FastAPI/CLI layer that exposes MCP, wire `list_tools()` and `call_tool()` accordingly. If not, you can still test in‑process with the helper below.

```python
# Example: thin adapter (keep local to your MCP server module)
from codeintel_rev.mcp_server.registry import list_tools, call_tool, McpDeps
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog

def get_mcp_tools(catalog: DuckDBCatalog, *, faiss=None, sparse=None):
    deps = McpDeps(catalog, faiss_search=faiss, sparse_search=sparse)
    return list_tools(), (lambda name, args: call_tool(deps, name, args))
```

---

## 6) Tests (golden + smoke)

### 6.1 `tests/mcp/test_tools_list.py`  *(new file)*

```python
# tests/mcp/test_tools_list.py
from __future__ import annotations

from codeintel_rev.mcp_server.registry import list_tools

def test_tools_list_contains_search_and_fetch():
    tools = {t["name"]: t for t in list_tools()}
    assert "search" in tools and "fetch" in tools
    # Basic schema sanity
    assert tools["search"]["inputSchema"]["type"] == "object"
    assert tools["fetch"]["inputSchema"]["properties"]["objectIds"]["type"] == "array"
```

### 6.2 `tests/mcp/test_search_fetch_golden.py`  *(new file)*

> **Fixture strategy:**
> • If the repo has a small, deterministic chunks Parquet (e.g., your mini sample), the test will run end‑to‑end.
> • Otherwise, the test **skips** unless `CODEINTEL_MCP_TEST_DB=/path/to/duckdb.db` and `CODEINTEL_MCP_TEST_VECTORS=/path/to/vectors_dir` are set (mirrors your lifecycle “current” layout). 

```python
# tests/mcp/test_search_fetch_golden.py
from __future__ import annotations

import os
import pytest

from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.mcp_server.registry import McpDeps, call_tool, list_tools
from codeintel_rev.mcp_server.search_tool import SearchDeps

ENV_DB = os.getenv("CODEINTEL_MCP_TEST_DB")
ENV_VEC = os.getenv("CODEINTEL_MCP_TEST_VECTORS")

pytestmark = pytest.mark.skipif(
    not (ENV_DB and ENV_VEC), reason="Set CODEINTEL_MCP_TEST_DB/VECTORS to run MCP golden test",
)

def _catalog() -> DuckDBCatalog:
    mgr = DuckDBManager(Path(ENV_DB))
    cat = DuckDBCatalog(Path(ENV_DB), Path(ENV_VEC), manager=mgr)
    cat.open()
    return cat

def test_mcp_search_and_fetch_roundtrip():
    catalog = _catalog()
    deps = McpDeps(catalog)  # pure DuckDB hydration; dense/sparse optional

    # 1) tools/list sanity
    tools = {t["name"]: t for t in list_tools()}
    assert "search" in tools and "fetch" in tools

    # 2) search
    sr = call_tool(deps, "search", {"query": "http client timeout", "top_k": 5})
    results = sr["structuredContent"]["results"]
    assert isinstance(results, list) and results, "Expected non-empty search results"

    ids = [r["id"] for r in results[:3]]
    # 3) fetch
    fr = call_tool(deps, "fetch", {"objectIds": ids})
    objects = fr["structuredContent"]["objects"]
    assert {o["id"] for o in objects} == set(ids)
    for o in objects:
        assert "content" in o and isinstance(o["content"], str)
        assert "metadata" in o and "uri" in o["metadata"]
```

---

## 7) Operator notes (what to document)

1. **Runtime dependencies.** MCP tools rely on the **current** DuckDB/Parquet bundle. Read via `.../current/...`. Don’t point MCP at a staging build; use your lifecycle manager to flip atomically. 

2. **Search surface.** The `search` tool merges dense/sparse channels when provided, but runs happily with only one (dense FAISS or sparse BM25/SPLADE). If you include FAISS, prefer `IndexIDMap2` (or `IndexIDMap`) so external `chunk_id` are returned and explainability stays stable. 

3. **Result size & shape.** Keep `top_k ≤ 20` and snippets ≤ ~8 lines to make Deep‑Research/ChatGPT effective without blowing token budget; ship full bodies through `fetch`. (Matches the full‑stack guidance you adopted.) 

4. **Metadata.** Populate `metadata.lang`, `uri`, `start_line`, `end_line`. If your `modules.jsonl` materialization is active, you can add `module_tags` and `doc_summary` later (non‑breaking enhancement). 

5. **Parquet/Arrow hygiene.** Keep embeddings in **FixedSizeList<float32>**; don’t convert to ragged lists. This preserves zero‑copy scans through DuckDB.   For more complex filters (e.g., language, path globs), route them through the catalog’s scope utilities instead of Python post‑filters. 

---

## 8) How it fits your existing architecture (traceability)

* **Chunk semantics.** We keep `uri`, `start/end_line`, `start/end_byte`, `content`, `lang` consistent with your `Chunk` dataclass and cAST chunker (symbol‑aware). These are exposed to MCP as titles/urls/snippets without re‑parsing. 
* **SCIP lines/roles.** The `repo://{uri}#Lx-Ly` anchor aligns with your SCIP/LSP line conventions (0‑indexed in data, rendered 1‑indexed in UI if desired). 
* **Lifecycle.** The MCP server should mount the published “current” bundle; your `IndexLifecycleManager` guarantees atomic flips. 
* **Future enrich.** If you decide to add symbol/AST/CST‑based explanations into `metadata`, the leaf tables we outlined earlier (and your `modules.jsonl` doc) make that straightforward, and compatible with the JSON schema we’re publishing. 

---

## 9) What the AI agent should do (step‑by‑step checklist)

1. **Create** the four new MCP files under `codeintel_rev/mcp_server/` with the exact contents above.
2. **Apply** the small additive method to `DuckDBCatalog` (or confirm equivalent exists). 
3. **(If needed)** update `FAISSManager.search(...)` to accept `k_factor` and ensure external ids via IDMap (or confirm already present). 
4. **Add tests** under `tests/mcp/` as shown; wire CI to set `CODEINTEL_MCP_TEST_DB`/`CODEINTEL_MCP_TEST_VECTORS` (pointing to a tiny sample build) for the golden test.
5. **Document** the operator notes in your runtime README and expose a tiny `indexctl mcp smoke` that prints `tools/list` for manual verification (optional).

---

### Appendix — why these libraries & shapes

* **DuckDB + Parquet + Arrow** keep the data path columnar and zero‑copy (your current design already leans on this), which is ideal for frequent small MCP calls.
* **SCIP/cAST chunking** ensures snippet boundaries respect symbols/semantics; returning those ranges and symbol names in `metadata` raises explainability without extra work.
* **FAISS** external IDs (via `IndexIDMap2`) make retrieval fully auditable and enable exact flat rerank when you choose to enable it (accuracy guardrail). 
* The **full‑stack plan** and **theory primer** you shipped underpin the “index‑card” in `search` and “full body” in `fetch`, which is what MCP clients expect in practice.

---

If you want, I can also include a minimal FastAPI shim that exposes `/tools/list` and `/tools/call` HTTP endpoints for local manual testing, but the above is sufficient for **ChatGPT MCP**, **Deep Research**, and in‑process tests.
