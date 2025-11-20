# API extension for GOID and call graph scaffolding #

Awesome — I’ve created the **Catalog Read APIs** you asked for and packaged them in ready‑to‑use artifacts:

**Downloads**

* **OpenAPI 3.1 spec:** [codeintel-catalog-read-apis.yaml](sandbox:/mnt/data/codeintel-catalog-read-apis.yaml)
* **FastAPI route stubs (drop‑in):** [catalog_http_stubs.py](sandbox:/mnt/data/catalog_http_stubs.py)
* **README (wire‑up notes & expected DuckDB views):** [README_catalog_apis.md](sandbox:/mnt/data/README_catalog_apis.md)

Below is a quick operator’s guide plus project‑specific alignment notes and examples.

---

## What’s included

### 1) OpenAPI 3.1 spec (REST, read‑only)

**Scope:** the three high‑impact surfaces we’ve been prioritizing:

* **GOID cross‑walks**
  `GET /v1/catalog/goids`
  Resolve **G**lobal **O**bject **ID**s from any of: `scip_symbol`, `ast_qualname`, `path+start_line+end_line`, `chunk_id`, or `symbol_id`. Returns canonical `goid` with a row per linked identifier.

* **Call graph**
  `GET /v1/graph/call`
  Expand from a `root_goid` with `direction={out|in|both}`, `depth`, and filters (`lang`, `path_prefix`, include third‑party, include unresolved). Supports **NDJSON streaming** (`Accept: application/x-ndjson`) for very large graphs.

* **CFG / DFG per function**
  `GET /v1/flow/cfg/{function_goid}`
  `GET /v1/flow/dfg/{function_goid}`
  Returns typed nodes + edges (JSON by default; GraphML string when `format=graphml`).

Design matches your app patterns (FastAPI, Problem Details, cursor pagination, strict typing) and plugs into the same HTTP app where MCP is mounted (see app entrypoint notes in the Architecture Narrative).

---

### 2) FastAPI route stubs (ready to paste)

File: `catalog_http_stubs.py` (intended path in repo: `codeintel_rev/app/routes/catalog_read.py`)

* Uses your **ApplicationContext** and **DuckDBCatalog** (per‑request connections) exactly as described in the narrative.
* Response models mirror the OpenAPI schemas.
* Each endpoint delegates to IO‑layer methods you’ll implement in `codeintel_rev/io/duckdb_catalog.py`:

  * `query_goids(...) -> GOIDQueryResult`
  * `query_callgraph(...) -> dict`
  * `get_cfg(function_goid, fmt) -> dict|None`
  * `get_dfg(function_goid, fmt) -> dict|None`

This keeps layering clean and consistent with existing adapters and IO patterns.

---

### 3) DuckDB view expectations (for quick success)

The README includes logical table/view shapes the endpoints expect to read:

* `goid_crosswalk(goid, lang, module_path, file_path, start_line, end_line, scip_symbol, ast_qualname, cst_node_id, chunk_id, symbol_id, updated_at)`
* `call_edges(caller_goid, callee_goid, file_path, start_line, end_line, resolved, kind, confidence, updated_at)`
* `cfg_blocks(function_goid, block_id, label, file_path, start_line, end_line)`
* `cfg_edges(function_goid, src, dst, label)`
* `dfg_nodes(function_goid, node_id, kind, symbol, file_path, start_line, end_line)`
* `dfg_edges(function_goid, src, dst, label)`

These views can be **materialized** or **virtual** over the enrichment artifacts you already generate (AST/CST/SCIP/symbol graph). They’re wired to DuckDB through the same `DuckDBCatalog` hook used elsewhere in the system.

---

## How to wire this into your app

1. **Place the routes**
   Create `codeintel_rev/app/routes/catalog_read.py` and paste `catalog_http_stubs.py`.

2. **Mount the router** in `codeintel_rev/app/main.py`:

```python
from codeintel_rev.app.routes import catalog_read
app.include_router(catalog_read.router)
```

(Aligns with the documented endpoint‑mount extension point in the app layer.)

3. **Fill in IO layer** in `codeintel_rev/io/duckdb_catalog.py` (four methods listed above).
   Use `DuckDBManager.get_connection()` and keep queries pure/read‑only, per your IO layer contract.

4. **Publish views** in DuckDB (materialized or not). If you want a starting point, here are minimal **view skeletons** (adapt paths/joins to your catalog):

```sql
-- GOID Cross‑walk (union over sources you already store)
CREATE OR REPLACE VIEW goid_crosswalk AS
WITH from_scip AS (
  SELECT
    /* your goid function */ scip_symbol_to_goid(scip_symbol) AS goid,
    'python' AS lang,
    module_path,
    file_path,
    start_line, end_line,
    scip_symbol,
    NULL AS ast_qualname,
    NULL AS cst_node_id,
    NULL AS chunk_id,
    symbols.id AS symbol_id,
    updated_at
  FROM symbols  -- your SCIP-derived table
),
from_ast AS (
  SELECT
    ast_qualname_to_goid(module, qualname) AS goid,
    'python' AS lang,
    module AS module_path,
    path AS file_path,
    start_line, end_line,
    NULL AS scip_symbol,
    module || ':' || qualname AS ast_qualname,
    NULL AS cst_node_id,
    NULL AS chunk_id,
    NULL AS symbol_id,
    updated_at
  FROM ast_nodes  -- your AST inventory (parquet registered in DuckDB)
),
from_chunks AS (
  SELECT
    chunk_to_goid(file_path, start_line, end_line) AS goid,
    'python' AS lang,
    NULL AS module_path,
    file_path, start_line, end_line,
    NULL AS scip_symbol,
    NULL AS ast_qualname,
    NULL AS cst_node_id,
    chunk_id,
    NULL AS symbol_id,
    updated_at
  FROM chunks
)
SELECT * FROM from_scip
UNION ALL SELECT * FROM from_ast
UNION ALL SELECT * FROM from_chunks;
```

```sql
-- Call edges (normalize whatever your enrichment produced)
CREATE OR REPLACE VIEW call_edges AS
SELECT
  caller_goid, callee_goid, file_path, start_line, end_line,
  resolved, kind, confidence, updated_at
FROM callgraph_edges_source;  -- replace with your source table
```

```sql
-- CFG / DFG views (denormalized for direct reads)
CREATE OR REPLACE VIEW cfg_blocks AS SELECT * FROM cfg_blocks_source;
CREATE OR REPLACE VIEW cfg_edges  AS SELECT * FROM cfg_edges_source;
CREATE OR REPLACE VIEW dfg_nodes  AS SELECT * FROM dfg_nodes_source;
CREATE OR REPLACE VIEW dfg_edges  AS SELECT * FROM dfg_edges_source;
```

> The names like `scip_symbol_to_goid`, `ast_qualname_to_goid`, and `chunk_to_goid` can be implemented as SQL macros or resolved in your IO layer. The key is **stable, canonical GOIDs** so that call/CFG/DFG all speak one identifier (ties back to your earlier GOID decision).

---

## Example calls

### GOID resolution

```bash
curl -s 'http://localhost:8080/v1/catalog/goids?ast_qualname=codeintel_rev.io.duckdb_catalog:DuckDBCatalog.query_goids'
```

### Call graph (one hop out, include unresolved dynamic calls)

```bash
curl -s 'http://localhost:8080/v1/graph/call?root_goid=py::codeintel_rev.io.duckdb_catalog.DuckDBCatalog.query_goids&direction=out&depth=1&include_unresolved=true'
```

### Stream large call graphs (NDJSON)

```bash
curl -H 'Accept: application/x-ndjson' 'http://localhost:8080/v1/graph/call?root_goid=py::pkg.module.fn&direction=both&depth=2'
```

### CFG / DFG for a function

```bash
curl -s 'http://localhost:8080/v1/flow/cfg/py::pkg.module.fn'
curl -s 'http://localhost:8080/v1/flow/dfg/py::pkg.module.fn?format=graphml'
```

---

## Alignment to the repo & architecture

* **DuckDB as the catalog:** These APIs hit DuckDB via `DuckDBCatalog`/`DuckDBManager`, consistent with how symbols/chunks are hydrated today.
* **Co-located with MCP HTTP app:** Routes mount in the same FastAPI app (`codeintel_rev.app.main`) used for MCP endpoints and readiness checks.
* **Data sources:** The cross‑walk and graphs layer over artifacts you already produce (SCIP → `symbols`, AST/CST → `ast_nodes`, symbol/dep graphs → `graphs/symbol_graph.json`).
* **Error envelopes:** Problem Details (RFC 9457) response pattern matches your existing adapters/decorators.
* **Pagination & streaming:** Cursor pagination for stable queries; NDJSON streaming for graphs to avoid memory spikes on large expansions (important for 100K+ chunk repos).

---

## Suggested next small PRs (stack-safe)

1. **IO layer queries** in `DuckDBCatalog` backing these routes:

   * `query_goids(...)` should union the cross‑walk sources and return a deterministic order (`-updated_at, goid`).
   * `query_callgraph(...)` should page edges and build the node set on demand (limit by `max_nodes` and emit `truncated=true` on caps).
   * `get_cfg(...)` / `get_dfg(...)` can be straightforward selects off the views.

2. **Mount routes** in `app/main.py` and add two or three **integration tests** that stand up an ephemeral DuckDB with tiny fixture tables (as your testing philosophy recommends – real collaborators, no monkeypatching).

3. **(Optional) ETag** for `/catalog/goids` by hashing the page (e.g., `xxhash64` of `goid` + `updated_at`) to enable conditional GETs.

If you want, I can also generate a tiny set of **DuckDB DDL/VIEW definitions** wired to your actual parquet/json inputs as a companion patch, or sketch a `duckdb_catalog.py` patch implementing the four methods above against the views.

Would you like me to produce those now?


# catalog Read APIs definitions and views with wiring #

Awesome — I’ll ship a **cohesive first cut of the “catalog read APIs”** that cleanly slots into your existing layering (Entrypoints → Services → IO) and DuckDB-centric runtime. Below are **ready‑to‑commit patches** (unified diffs) plus minimal docs and tests. I’ve grounded the integration points to what your Architecture Narrative specifies about FastAPI startup, ApplicationContext, and DuckDB usage, and I’ve kept adapters/tooling consistent with your MCP patterns. Key touchpoints are cited inline to your narrative.   

---

## What’s included (scope of this PR)

**New service + router (HTTP)**

* `codeintel_rev/services/catalog/read.py`: Service layer that executes **read‑only DuckDB queries** for versions, files, chunks, symbols, modules, and tags.
* `codeintel_rev/app/routers/catalog.py`: FastAPI router exposing typed, paginated **GET** endpoints under `/catalog/*`.
* Minimal **wiring in `app/main.py`** to instantiate and attach the reader during `lifespan()` and mount the router (as your doc recommends for new endpoints). 

**Optional MCP tools (parity with HTTP)**

* `codeintel_rev/mcp_server/adapters/catalog.py`: Lightweight MCP tools that call the same service (pattern matches your existing MCP adapters and error‑handling decorator).  

**Unit tests**

* `tests/codeintel_rev/services/catalog/test_read.py`: DuckDB in‑memory tests for the service queries and pagination.
* `tests/codeintel_rev/app/test_catalog_endpoints.py`: HTTP contract tests against a test FastAPI app.

**Docs**

* `codeintel_rev/docs/HTTP_CATALOG.md`: Endpoint reference and response schemas.

> DuckDB specific: All SQL is DuckDB‑friendly (e.g., `count_if`, `like`, `limit/offset`), connections are obtained via the **existing DuckDB manager** and used per‑request (mirrors your “per‑request connections” guideline). 

---

## Endpoints (HTTP)

* `GET /catalog/versions` — list index versions (`index_versions`). 
* `GET /catalog/files` — files derived from `chunks` (with counts) + filtering by prefix, tags (optional). 
* `GET /catalog/chunks/{chunk_id}` — chunk metadata (no content hydrate here; deep‑fetch remains in your existing flow). 
* `GET /catalog/symbols` — browse/search symbols (prefix, kind, path scoping) with pagination; joins `symbols` table. 
* `GET /catalog/symbols/{symbol}` — detail: defs + ref counts and sample locations.
* `GET /catalog/modules` — module list from `modules` table if present (ingested by your enrich pipeline). 
* `GET /catalog/tags` — tag catalog from `tags_index.yaml` (lazy‑loaded/cached).

> These APIs intentionally **do not hydrate large content** (leave that to your existing `search/fetch` two‑phase flow used by Deep Research agents). 

---

## Patches

> Apply from repo root. New files will be created as shown.

### 1) `codeintel_rev/services/catalog/read.py` (new)

```diff
*** /dev/null
--- a/codeintel_rev/services/catalog/read.py
@@
+from __future__ import annotations
+
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Any, Iterable, Optional
+
+import duckdb
+from pydantic import BaseModel, Field
+
+# Layering: Services depend on IO managers/adapters (not entrypoints).
+# We take a DuckDB connection factory from the IO layer via ApplicationContext.
+# Ref: Architecture layering & DuckDB manager. :contentReference[oaicite:13]{index=13} :contentReference[oaicite:14]{index=14}
+
+
+class IndexVersion(BaseModel):
+    version: str
+    created_at: str
+    faiss_checksum: Optional[str] = None
+    duckdb_checksum: Optional[str] = None
+    scip_checksum: Optional[str] = None
+
+
+class FileEntry(BaseModel):
+    path: str
+    chunk_count: int
+
+
+class ChunkMeta(BaseModel):
+    chunk_id: int | str
+    file_path: str
+    start_line: int
+    end_line: int
+    embedding_dim: Optional[int] = None
+
+
+class SymbolRow(BaseModel):
+    symbol: str
+    kind: Optional[str] = None
+    file_path: Optional[str] = None
+    start_line: Optional[int] = None
+    end_line: Optional[int] = None
+    role: Optional[str] = None  # "def" | "ref" (as produced from SCIP ingest) :contentReference[oaicite:15]{index=15}
+
+
+class SymbolDetail(BaseModel):
+    symbol: str
+    defs: list[SymbolRow] = Field(default_factory=list)
+    refs_count: int = 0
+    refs_sample: list[SymbolRow] = Field(default_factory=list)
+
+
+class ModuleEntry(BaseModel):
+    path: str
+    module: Optional[str] = None
+    language: Optional[str] = None
+    loc: Optional[int] = None
+    tags: Optional[list[str]] = None
+
+
+class TagCatalog(BaseModel):
+    tags: dict[str, list[str]]  # tag -> list of module/file paths
+
+
+@dataclass(slots=True)
+class CatalogReader:
+    """Pure read-only service over the DuckDB catalog + sidecar artifacts.
+
+    - Connections are obtained per-call via the provided factory to match your pattern. :contentReference[oaicite:16]{index=16}
+    - No content hydration; this is navigation metadata only (search/fetch remains elsewhere). :contentReference[oaicite:17]{index=17}
+    """
+    get_connection: callable
+    artifacts_root: Path
+
+    # ---------- Versions ----------
+    def list_versions(self) -> list[IndexVersion]:
+        sql = """
+            select
+              version,
+              created_at,
+              faiss_checksum,
+              duckdb_checksum,
+              scip_checksum
+            from index_versions
+            order by created_at desc
+        """
+        with self.get_connection() as conn:
+            rows = conn.execute(sql).fetchall()
+        cols = ["version", "created_at", "faiss_checksum", "duckdb_checksum", "scip_checksum"]
+        return [IndexVersion(**dict(zip(cols, r))) for r in rows]
+
+    # ---------- Files ----------
+    def list_files(self, prefix: Optional[str], limit: int = 100, offset: int = 0) -> list[FileEntry]:
+        params: list[Any] = []
+        where = ""
+        if prefix:
+            where = "where file_path like ?"
+            params.append(f"{prefix}%")
+        sql = f"""
+            select file_path as path, count(*)::int as chunk_count
+            from chunks
+            {where}
+            group by path
+            order by path
+            limit ? offset ?
+        """
+        params.extend([limit, offset])
+        with self.get_connection() as conn:
+            rows = conn.execute(sql, params).fetchall()
+        return [FileEntry(path=r[0], chunk_count=r[1]) for r in rows]
+
+    # ---------- Chunks ----------
+    def get_chunk(self, chunk_id: str | int) -> Optional[ChunkMeta]:
+        sql = """
+            select chunk_id, file_path, start_line, end_line, embedding_dim
+            from chunks
+            where chunk_id = ?
+            limit 1
+        """
+        with self.get_connection() as conn:
+            row = conn.execute(sql, [chunk_id]).fetchone()
+        if not row:
+            return None
+        cols = ["chunk_id", "file_path", "start_line", "end_line", "embedding_dim"]
+        return ChunkMeta(**dict(zip(cols, row)))
+
+    # ---------- Symbols ----------
+    def list_symbols(
+        self,
+        q: Optional[str],
+        kind: Optional[str],
+        path_prefix: Optional[str],
+        limit: int = 100,
+        offset: int = 0,
+    ) -> list[SymbolRow]:
+        # We expose one row per symbol "occurrence" sample to make the list navigable.
+        # This stays read-only and keeps result sizes predictable via pagination.
+        clauses, params = [], []
+        if q:
+            clauses.append("symbol like ?")
+            params.append(f"{q}%")
+        if kind:
+            clauses.append("kind = ?")
+            params.append(kind)
+        if path_prefix:
+            clauses.append("file_path like ?")
+            params.append(f"{path_prefix}%")
+        where = f"where {' and '.join(clauses)}" if clauses else ""
+        sql = f"""
+            select symbol, kind, file_path, start_line, end_line, role
+            from symbols
+            {where}
+            order by symbol, file_path
+            limit ? offset ?
+        """
+        params.extend([limit, offset])
+        with self.get_connection() as conn:
+            rows = conn.execute(sql, params).fetchall()
+        cols = ["symbol", "kind", "file_path", "start_line", "end_line", "role"]
+        return [SymbolRow(**dict(zip(cols, r))) for r in rows]
+
+    def get_symbol_detail(self, symbol: str, refs_sample: int = 25) -> Optional[SymbolDetail]:
+        with self.get_connection() as conn:
+            defs = conn.execute("""
+                select symbol, kind, file_path, start_line, end_line, role
+                from symbols
+                where symbol = ? and role = 'def'
+                order by file_path, start_line
+            """, [symbol]).fetchall()
+            refs_cnt = conn.execute("""
+                select count(*)
+                from symbols
+                where symbol = ? and role = 'ref'
+            """, [symbol]).fetchone()[0]
+            refs = conn.execute("""
+                select symbol, kind, file_path, start_line, end_line, role
+                from symbols
+                where symbol = ? and role = 'ref'
+                order by file_path, start_line
+                limit ?
+            """, [symbol, refs_sample]).fetchall()
+        cols = ["symbol", "kind", "file_path", "start_line", "end_line", "role"]
+        if not defs and not refs:
+            return None
+        return SymbolDetail(
+            symbol=symbol,
+            defs=[SymbolRow(**dict(zip(cols, r))) for r in defs],
+            refs_count=int(refs_cnt),
+            refs_sample=[SymbolRow(**dict(zip(cols, r))) for r in refs],
+        )
+
+    # ---------- Modules (from enrichment pipeline) ----------
+    def list_modules(self, prefix: Optional[str], limit: int = 100, offset: int = 0) -> list[ModuleEntry]:
+        # modules table is created by enrich.duckdb_store.ensure_schema (if used) :contentReference[oaicite:18]{index=18}
+        clauses, params = [], []
+        if prefix:
+            clauses.append("path like ?")
+            params.append(f"{prefix}%")
+        where = f"where {' and '.join(clauses)}" if clauses else ""
+        sql = f"""
+            select path, module, language, loc, tags
+            from modules
+            {where}
+            order by module nulls last, path
+            limit ? offset ?
+        """
+        params.extend([limit, offset])
+        with self.get_connection() as conn:
+            try:
+                rows = conn.execute(sql, params).fetchall()
+            except duckdb.CatalogException:
+                # modules table not present
+                return []
+        out: list[ModuleEntry] = []
+        for r in rows:
+            tags = r[4] if isinstance(r[4], list) else None
+            out.append(ModuleEntry(path=r[0], module=r[1], language=r[2], loc=r[3], tags=tags))
+        return out
+
+    # ---------- Tags (YAML index) ----------
+    _tag_cache: Optional[TagCatalog] = None
+
+    def get_tags(self) -> TagCatalog:
+        if self._tag_cache is not None:
+            return self._tag_cache
+        idx = self.artifacts_root / "tags" / "tags_index.yaml"
+        if not idx.exists():
+            self._tag_cache = TagCatalog(tags={})
+            return self._tag_cache
+        import yaml  # lazy import; safe_load only
+        data = yaml.safe_load(idx.read_text()) or {}
+        tags = data.get("tags", data)  # tolerate either {tags:{...}} or flat mapping
+        self._tag_cache = TagCatalog(tags=tags if isinstance(tags, dict) else {})
+        return self._tag_cache
```

---

### 2) `codeintel_rev/app/routers/catalog.py` (new)

```diff
*** /dev/null
--- a/codeintel_rev/app/routers/catalog.py
@@
+from __future__ import annotations
+
+from fastapi import APIRouter, Depends, HTTPException, Query
+
+from pydantic import BaseModel
+
+from codeintel_rev.services.catalog.read import CatalogReader, IndexVersion, FileEntry, ChunkMeta, SymbolRow, SymbolDetail, ModuleEntry, TagCatalog
+
+
+def build_catalog_router(reader: CatalogReader) -> APIRouter:
+    """Factory to build a router bound to a CatalogReader.
+    Mounted by app/main during lifespan after ApplicationContext is ready. :contentReference[oaicite:19]{index=19}
+    """
+    r = APIRouter(tags=["catalog"])
+
+    @r.get("/versions", response_model=list[IndexVersion])
+    def list_versions():
+        return reader.list_versions()
+
+    @r.get("/files", response_model=list[FileEntry])
+    def list_files(
+        prefix: str | None = Query(default=None, description="Path prefix filter"),
+        limit: int = Query(default=100, ge=1, le=1000),
+        offset: int = Query(default=0, ge=0),
+    ):
+        return reader.list_files(prefix, limit, offset)
+
+    @r.get("/chunks/{chunk_id}", response_model=ChunkMeta | None)
+    def get_chunk(chunk_id: str):
+        return reader.get_chunk(chunk_id)
+
+    @r.get("/symbols", response_model=list[SymbolRow])
+    def list_symbols(
+        q: str | None = Query(default=None, description="Symbol prefix"),
+        kind: str | None = Query(default=None, description="Symbol kind (function/class/variable/…)"),
+        path_prefix: str | None = Query(default=None, description="Limit to path prefix"),
+        limit: int = Query(default=100, ge=1, le=1000),
+        offset: int = Query(default=0, ge=0),
+    ):
+        return reader.list_symbols(q, kind, path_prefix, limit, offset)
+
+    @r.get("/symbols/{symbol}", response_model=SymbolDetail)
+    def get_symbol_detail(symbol: str, refs_sample: int = Query(default=25, ge=0, le=500)):
+        out = reader.get_symbol_detail(symbol, refs_sample)
+        if not out:
+            raise HTTPException(status_code=404, detail="symbol not found")
+        return out
+
+    @r.get("/modules", response_model=list[ModuleEntry])
+    def list_modules(
+        prefix: str | None = Query(default=None, description="Module path prefix"),
+        limit: int = Query(default=100, ge=1, le=1000),
+        offset: int = Query(default=0, ge=0),
+    ):
+        return reader.list_modules(prefix, limit, offset)
+
+    @r.get("/tags", response_model=TagCatalog)
+    def get_tags():
+        return reader.get_tags()
+
+    return r
```

---

### 3) `codeintel_rev/app/main.py` (patch to mount router & bind reader)

> This patch assumes your `lifespan()` already builds `ApplicationContext` and attaches it to the app (per narrative). We add a tiny bit to instantiate the `CatalogReader` and mount the router during startup.  

```diff
*** a/codeintel_rev/app/main.py
--- b/codeintel_rev/app/main.py
@@
-from fastapi import FastAPI
+from fastapi import FastAPI
+from pathlib import Path
@@
 from .config_context import ApplicationContext
+from codeintel_rev.app.routers.catalog import build_catalog_router
+from codeintel_rev.services.catalog.read import CatalogReader
@@
 app = FastAPI(title="CodeIntel MCP")
 
 async def lifespan(app: FastAPI):
-    # existing initialization...
+    # existing initialization...
     ctx = ApplicationContext.create()
     app.state.ctx = ctx
+    # Bind catalog reader (HTTP router) after ctx is ready. The artifacts root is whatever
+    # root your enrich pipeline writes to (e.g., indexes/active or build/enrich root).
+    # If you already have a canonical artifacts root in AppConfig, use that here.
+    artifacts_root = Path(getattr(ctx.config, "artifacts_root", "build/enrich"))
+    reader = CatalogReader(get_connection=ctx.duckdb_manager.get_connection, artifacts_root=artifacts_root)
+    app.include_router(build_catalog_router(reader), prefix="/catalog")
     try:
         yield
     finally:
         ctx.close_all_runtimes()
```

*Why here?* Your **Entrypoints layer** is the right place to mount HTTP routes; we still keep **DuckDB access** in the Services layer via the `CatalogReader` and obtain connections through the `DuckDBManager` from the **ApplicationContext** as your runtime pattern dictates.  

---

### 4) MCP parity (optional, but small and consistent): `codeintel_rev/mcp_server/adapters/catalog.py` (new)

```diff
*** /dev/null
--- a/codeintel_rev/mcp_server/adapters/catalog.py
@@
+from __future__ import annotations
+
+from typing import Optional
+from pydantic import BaseModel
+
+from codeintel_rev.mcp_server.error_handling import handle_adapter_errors
+from codeintel_rev.app.config_context import app_context  # contextvar accessor used in your adapters
+from codeintel_rev.services.catalog.read import CatalogReader
+from fastmcp import mcp  # same decorator family used elsewhere
+
+# Pattern: Access ApplicationContext via context var, construct the service on demand.
+# Ref: "Access ApplicationContext via app_context.get()" & error handling decorator. :contentReference[oaicite:24]{index=24} :contentReference[oaicite:25]{index=25}
+
+def _reader() -> CatalogReader:
+    ctx = app_context.get()
+    artifacts_root = getattr(ctx.config, "artifacts_root", "build/enrich")
+    return CatalogReader(get_connection=ctx.duckdb_manager.get_connection, artifacts_root=artifacts_root)
+
+
+class ListFilesRequest(BaseModel):
+    prefix: Optional[str] = None
+    limit: int = 100
+    offset: int = 0
+
+
+@mcp.tool()
+@handle_adapter_errors(empty_result=[])
+def catalog_list_versions() -> list[dict]:
+    return [v.model_dump() for v in _reader().list_versions()]
+
+
+@mcp.tool()
+@handle_adapter_errors(empty_result=[])
+def catalog_list_files(req: ListFilesRequest) -> list[dict]:
+    out = _reader().list_files(req.prefix, req.limit, req.offset)
+    return [r.model_dump() for r in out]
+
+
+class ListSymbolsRequest(BaseModel):
+    q: Optional[str] = None
+    kind: Optional[str] = None
+    path_prefix: Optional[str] = None
+    limit: int = 100
+    offset: int = 0
+
+
+@mcp.tool()
+@handle_adapter_errors(empty_result=[])
+def catalog_list_symbols(req: ListSymbolsRequest) -> list[dict]:
+    out = _reader().list_symbols(req.q, req.kind, req.path_prefix, req.limit, req.offset)
+    return [r.model_dump() for r in out]
+
+
+@mcp.tool()
+@handle_adapter_errors(empty_result={})
+def catalog_symbol_detail(symbol: str, refs_sample: int = 25) -> dict:
+    out = _reader().get_symbol_detail(symbol, refs_sample)
+    return {} if out is None else out.model_dump()
+
+
+@mcp.tool()
+@handle_adapter_errors(empty_result=[])
+def catalog_list_modules(prefix: Optional[str] = None, limit: int = 100, offset: int = 0) -> list[dict]:
+    out = _reader().list_modules(prefix, limit, offset)
+    return [m.model_dump() for m in out]
+
+
+@mcp.tool()
+@handle_adapter_errors(empty_result={"tags": {}})
+def catalog_tags() -> dict:
+    return _reader().get_tags().model_dump()
```

> Registration: your `mcp_server/server.py` auto‑registers decorated tools (consistent with narrative), so **no extra wiring** is required beyond importing this module, if that’s your pattern. If you explicitly import tools there, add a one‑liner import.  

---

### 5) Tests — service & HTTP

```diff
*** /dev/null
--- a/tests/codeintel_rev/services/catalog/test_read.py
@@
+import duckdb
+from pathlib import Path
+from codeintel_rev.services.catalog.read import CatalogReader
+
+
+def _mem_conn_factory():
+    conn = duckdb.connect(":memory:")
+    # Minimal schema mirroring your catalog tables. :contentReference[oaicite:28]{index=28}
+    conn.execute("create table index_versions(version varchar, created_at varchar, faiss_checksum varchar, duckdb_checksum varchar, scip_checksum varchar)")
+    conn.execute("insert into index_versions values ('v1','2025-01-01T00:00:00Z','a','b','c')")
+    conn.execute("""
+        create table chunks(
+          chunk_id integer,
+          file_path varchar,
+          start_line integer,
+          end_line integer,
+          embedding_dim integer
+        )
+    """)
+    conn.execute("insert into chunks values (1,'a/b.py',1,40,2560),(2,'a/c.py',1,35,2560),(3,'d/e.py',1,20,2560)")
+    conn.execute("""
+        create table symbols(
+          symbol varchar,
+          kind varchar,
+          file_path varchar,
+          start_line integer,
+          end_line integer,
+          role varchar
+        )
+    """)
+    conn.execute("insert into symbols values ('pkg.mod.fn','function','a/b.py',5,10,'def'),('pkg.mod.fn','function','d/e.py',12,18,'ref')")
+    return conn
+
+
+def test_versions_and_files(tmp_path: Path):
+    def factory():
+        return _mem_conn_factory()
+    reader = CatalogReader(get_connection=factory, artifacts_root=tmp_path)
+    versions = reader.list_versions()
+    assert versions and versions[0].version == "v1"
+    files = reader.list_files(prefix="a/", limit=10, offset=0)
+    assert [f.path for f in files] == ["a/b.py", "a/c.py"]
+
+
+def test_symbols_and_detail(tmp_path: Path):
+    def factory():
+        return _mem_conn_factory()
+    reader = CatalogReader(get_connection=factory, artifacts_root=tmp_path)
+    rows = reader.list_symbols(q="pkg.", kind=None, path_prefix=None, limit=10, offset=0)
+    assert any(r.symbol == "pkg.mod.fn" for r in rows)
+    d = reader.get_symbol_detail("pkg.mod.fn")
+    assert d and d.refs_count == 1 and d.defs
```

```diff
*** /dev/null
--- a/tests/codeintel_rev/app/test_catalog_endpoints.py
@@
+from fastapi.testclient import TestClient
+from pathlib import Path
+import duckdb
+
+from codeintel_rev.app.routers.catalog import build_catalog_router
+from codeintel_rev.services.catalog.read import CatalogReader
+from fastapi import FastAPI
+
+
+def _app():
+    app = FastAPI()
+    def factory():
+        conn = duckdb.connect(":memory:")
+        conn.execute("create table index_versions(version varchar, created_at varchar, faiss_checksum varchar, duckdb_checksum varchar, scip_checksum varchar)")
+        conn.execute("insert into index_versions values ('v1','2025-01-01T00:00:00Z','a','b','c')")
+        conn.execute("create table chunks(chunk_id integer, file_path varchar, start_line integer, end_line integer, embedding_dim integer)")
+        conn.execute("insert into chunks values (1,'x/y.py',1,10,2560)")
+        conn.execute("create table symbols(symbol varchar, kind varchar, file_path varchar, start_line integer, end_line integer, role varchar)")
+        conn.execute("insert into symbols values ('s.k','function','x/y.py',2,4,'def')")
+        return conn
+    reader = CatalogReader(get_connection=factory, artifacts_root=Path(".")) 
+    app.include_router(build_catalog_router(reader), prefix="/catalog")
+    return app
+
+
+def test_versions_endpoint():
+    client = TestClient(_app())
+    r = client.get("/catalog/versions")
+    assert r.status_code == 200
+    assert r.json()[0]["version"] == "v1"
```

---

### 6) Docs — `codeintel_rev/docs/HTTP_CATALOG.md` (new)

```diff
*** /dev/null
--- a/codeintel_rev/docs/HTTP_CATALOG.md
@@
+# Catalog Read APIs
+
+Read-only HTTP endpoints for code catalog navigation (**DuckDB-backed**). Endpoints are mounted by `app/main.py` during `lifespan()` after `ApplicationContext` is initialized. :contentReference[oaicite:29]{index=29}
+
+## Endpoints
+
+- `GET /catalog/versions` → `IndexVersion[]`  
+- `GET /catalog/files?prefix=&limit=&offset=` → `FileEntry[]`  
+- `GET /catalog/chunks/{chunk_id}` → `ChunkMeta | null`  
+- `GET /catalog/symbols?q=&kind=&path_prefix=&limit=&offset=` → `SymbolRow[]`  
+- `GET /catalog/symbols/{symbol}?refs_sample=` → `SymbolDetail`  
+- `GET /catalog/modules?prefix=&limit=&offset=` → `ModuleEntry[]` (if `modules` table exists) :contentReference[oaicite:30]{index=30}  
+- `GET /catalog/tags` → `TagCatalog` (from `tags/tags_index.yaml`)
+
+> **Notes**
+> - These endpoints are intentionally metadata‑only; **content hydration** is still provided by the existing Deep Research `search`/`fetch` two‑phase flow. :contentReference[oaicite:31]{index=31}
+> - Connections are acquired per request from `DuckDBManager.get_connection()` in the ApplicationContext runtime. :contentReference[oaicite:32]{index=32}
```

---

## Why this fits your codebase

* **Layering respected**: Entrypoints mount routes; Services do work; IO is accessed via the DuckDB manager provided by the ApplicationContext. 
* **Runtime integration**: Bound during **`lifespan()`**, alongside other capability mounts you already perform (health/readiness/capz/MCP).  
* **Aligns with current data**: Reads `chunks`, `symbols`, `index_versions`; tolerates absence of `modules` table; reads `tags_index.yaml` when available.   
* **MCP parity**: Optional adapter exposes identical read capabilities as tools (decorators + error handler pattern).  

---

## Follow‑ups I can add in the next PR (keeping this one small & green)

1. **Scope filters** (path/language) from `ScopeStore` automatically applied in service methods (mirrors your semantic search adapters). 
2. **Repo/version awareness** if/when multi‑repo lands (e.g., select from versioned schemas). 
3. **Owners/analytics join** to surface `ownership.parquet` for `GET /catalog/files` (owner, churn) when available. 
4. **Symbol type enumerations** from your SCIP ingest to validate `kind` consistently. 

---

If you want, I can also include a tiny **Typer CLI** wrapper (e.g., `codeintel catalog list-symbols`) that calls the same service for local inspection — but the above is already sufficient for agents and UI to explore the catalog cleanly.


# typer CLI wrapper #

Absolutely—let’s make a **Typer** CLI that’s purpose‑built for **local inspection**, while keeping your MCP integration **auto‑discovered via decorators** (i.e., no explicit registration/import line in this CLI).

Below is a drop‑in `codeintel` CLI that wraps the same “catalog” service you already expose to MCP. It:

* Adds `codeintel catalog …` subcommands for local workflows
* **Does not** import or register any MCP decorators (so your server can still auto‑discover them elsewhere)
* Uses a small, robust **import shim** to find your service (configurable), and includes a tiny **Python‑only fallback** so the CLI works out‑of‑the‑box even before your real service is wired up
* Supports **table / JSON / NDJSON** output, filtering, globs, and stable exit codes

---

## File layout

You can add these two files to your package (or keep them in a small standalone module):

```
codeintel/
  __init__.py
  cli.py            # <- Typer CLI entry
  __main__.py       # <- allows `python -m codeintel`
```

Optional packaging snippet is below.

---

## `codeintel/cli.py`

```python
from __future__ import annotations

import dataclasses
import importlib
import inspect
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

# ---- Typer apps -------------------------------------------------------------

app = typer.Typer(
    add_completion=True,
    no_args_is_help=True,
    help="Local code-intelligence inspection CLI (no MCP dependencies).",
)
catalog_app = typer.Typer(no_args_is_help=True, help="Inspect the code-intel catalog.")
app.add_typer(catalog_app, name="catalog")

console = Console()


# ---- Service loader (keeps MCP auto-discovery via your decorators) ----------

def _try_import(mod_attr: str) -> Any:
    """
    Import helper for strings like 'pkg.mod:attr'. Returns attribute or module.
    Raises ImportError if not found.
    """
    if ":" in mod_attr:
        mod, attr = mod_attr.split(":", 1)
        module = importlib.import_module(mod)
        return getattr(module, attr)
    return importlib.import_module(mod_attr)


def _find_service() -> Any:
    """
    Locates your catalog service without importing MCP bits.
    Priority:
      1) env var CODEINTEL_SERVICE_IMPORT="module:attr"
      2) common paths in your likely layout.
    We accept any object exposing methods like: list_symbols, list_files, search, etc.
    """
    override = os.environ.get("CODEINTEL_SERVICE_IMPORT")
    candidates = (
        [override] if override else []
    ) + [
        # a factory
        "codeintel.catalog:get_service",
        # a singleton instance
        "codeintel.catalog:service",
        # a class we can instantiate
        "codeintel.catalog:CodeIntelCatalogService",
        "codeintel.services.catalog:CodeIntelCatalogService",
    ]

    for target in candidates:
        try:
            obj = _try_import(target)
            if callable(obj) and obj.__name__.startswith("get_"):
                return obj()  # factory -> instance
            if inspect.isclass(obj):
                try:
                    return obj()  # no-arg constructor
                except TypeError:
                    # If it needs args, let it fall through to fallback.
                    pass
            # already an instance
            return obj
        except Exception:
            continue

    # As a convenience, return a minimal Python-only fallback service so the CLI
    # is still useful before the real service is wired up.
    return _NaivePythonCatalogService()


def _call_service(obj: Any, method: str, **kwargs) -> Any:
    """
    Call `obj.<method>(**kwargs)` but only pass parameters the method actually accepts.
    This lets the CLI be ahead of (or behind) your service signature without breaking.
    """
    func = getattr(obj, method)
    sig = inspect.signature(func)
    safe = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return func(**safe)


# ---- JSON helpers -----------------------------------------------------------

def _to_mapping(x: Any) -> Mapping[str, Any]:
    """
    Convert pydantic/dataclass/namedtuple objects to a dict for JSON.
    """
    # pydantic v1/v2
    for attr in ("model_dump", "dict"):
        if hasattr(x, attr) and callable(getattr(x, attr)):
            try:
                return getattr(x, attr)()  # type: ignore[misc]
            except TypeError:
                pass
    if dataclasses.is_dataclass(x):
        return dataclasses.asdict(x)
    if isinstance(x, Mapping):
        return x
    # best-effort fallback
    return {k: getattr(x, k) for k in dir(x) if not k.startswith("_") and not callable(getattr(x, k))}


def _emit_json(items: Iterable[Any], ndjson: bool) -> None:
    if ndjson:
        for it in items:
            console.out(json.dumps(_to_mapping(it), ensure_ascii=False))
    else:
        console.out(json.dumps([_to_mapping(it) for it in items], ensure_ascii=False, indent=2))


def _auto_format(default: str = "table") -> str:
    # Pick JSON automatically when output is piped.
    return "json" if not sys.stdout.isatty() else default


# ---- Table helpers ----------------------------------------------------------

def _render_symbols_table(symbols: Sequence[Mapping[str, Any]],
                          columns: Sequence[str] | None,
                          no_header: bool) -> None:
    if not symbols:
        console.print(Panel.fit(Text("No symbols found.", style="italic")))
        raise typer.Exit(code=2)

    first = symbols[0]
    cols = columns or [c for c in ("name", "kind", "language", "file", "line", "id") if c in first]

    table = Table(show_header=not no_header)
    for c in cols:
        table.add_column(c)

    for s in symbols:
        row = [str(s.get(c, "")) for c in cols]
        table.add_row(*row)

    console.print(table)


# ---- Catalog commands -------------------------------------------------------

@catalog_app.command("list-symbols")
def list_symbols(
    root: Path = typer.Option(Path("."), "--root", "-r", exists=True, file_okay=False, dir_okay=True,
                              help="Project root (scanned locally)."),
    glob: Optional[str] = typer.Option(None, "--glob", help="Limit files by glob (e.g. 'src/**/*.py')."),
    language: Optional[str] = typer.Option(None, "--lang", help="Filter by language (e.g. 'python', 'ts')."),
    kind: Optional[list[str]] = typer.Option(None, "--kind", "-k", help="Filter by symbol kind (repeatable)."),
    name: Optional[str] = typer.Option(None, "--name", help="Substring filter on symbol name (case-insensitive)."),
    name_regex: Optional[str] = typer.Option(None, "--name-regex", help="Regex on symbol name."),
    limit: int = typer.Option(0, "--limit", "-n", help="Max items to return (0 = unlimited)."),
    sort: str = typer.Option("file,line,name", "--sort", help="Comma list of keys to sort by."),
    descending: bool = typer.Option(False, "--desc", help="Sort descending."),
    output: str = typer.Option(_auto_format(), "--format", "-f",
                               help="One of: table, json, ndjson, auto",
                               case_sensitive=False),
    columns: Optional[list[str]] = typer.Option(None, "--columns", "-c",
                                                help="Which columns to show in table output (repeatable)."),
    no_header: bool = typer.Option(False, "--no-header", help="Hide table header."),
    relative: bool = typer.Option(True, "--relative/--absolute", help="Show file paths relative to --root."),
):
    """
    List symbols from the local catalog (no MCP required).
    """
    svc = _find_service()

    # Fetch
    items = _call_service(
        svc,
        "list_symbols",
        root=Path(root),
        glob=glob,
        language=language,
        kinds=kind,
        name=name,
        name_regex=name_regex,
        limit=limit,
        sort=sort,
        descending=descending,
        relative=relative,
    )

    # Normalize to plain dicts
    data = [_to_mapping(it) for it in items]

    # Sort locally too (if service didn’t)
    if sort:
        keys = [k.strip() for k in sort.split(",") if k.strip()]
        def _key(d: Mapping[str, Any]):
            return tuple(d.get(k) for k in keys)
        try:
            data.sort(key=_key, reverse=descending)
        except Exception:
            pass

    # Output
    fmt = output.lower()
    if fmt in ("json", "ndjson"):
        _emit_json(data, ndjson=(fmt == "ndjson"))
    elif fmt in ("table", "auto"):
        _render_symbols_table(data, columns, no_header)
    else:
        console.print(f"[red]Unknown format:[/red] {output}")
        raise typer.Exit(code=64)


@catalog_app.command("show-symbol")
def show_symbol(
    symbol_id: str = typer.Argument(..., help="Symbol ID as returned by list-symbols."),
    context: int = typer.Option(4, "--context", "-C", help="Context lines around the symbol when showing source."),
    show_source: bool = typer.Option(True, "--show-source/--no-source", help="Include source preview."),
    output: str = typer.Option(_auto_format("json"), "--format", "-f", help="json or table (metadata only).",
                               case_sensitive=False),
):
    """
    Show one symbol (metadata + optional source preview).
    """
    svc = _find_service()
    result = _call_service(svc, "get_symbol", symbol_id=symbol_id, context=context, show_source=show_source)

    data = _to_mapping(result)
    if output.lower() == "json":
        console.out(json.dumps(data, ensure_ascii=False, indent=2))
        return

    # Minimal table view for metadata
    meta_cols = [k for k in ("id", "name", "kind", "language", "file", "line", "span") if k in data]
    table = Table(show_header=True)
    for c in meta_cols:
        table.add_column(c)
    table.add_row(*[str(data.get(c, "")) for c in meta_cols])
    console.print(table)

    snippet = data.get("source")
    if show_source and snippet:
        console.rule(Text("source", style="bold"))
        console.print(Text(snippet))


@catalog_app.command("list-files")
def list_files(
    root: Path = typer.Option(Path("."), "--root", "-r", exists=True),
    include: Optional[list[str]] = typer.Option(None, "--include", "-I", help="Glob(s) to include (repeatable)."),
    exclude: Optional[list[str]] = typer.Option(None, "--exclude", "-E", help="Glob(s) to exclude (repeatable)."),
    hidden: bool = typer.Option(False, "--hidden", help="Include dotfiles."),
    output: str = typer.Option(_auto_format(), "--format", "-f", help="table, json, ndjson, auto"),
    relative: bool = typer.Option(True, "--relative/--absolute"),
):
    """
    List tracked/scanable files according to your catalog.
    """
    svc = _find_service()
    files = _call_service(
        svc,
        "list_files",
        root=Path(root),
        include=include,
        exclude=exclude,
        hidden=hidden,
        relative=relative,
    )

    items = [{"file": f} if isinstance(f, str) else _to_mapping(f) for f in files]
    fmt = output.lower()
    if fmt in ("json", "ndjson"):
        _emit_json(items, ndjson=(fmt == "ndjson"))
    else:
        table = Table(show_header=fmt != "ndjson")
        table.add_column("file")
        for it in items:
            table.add_row(str(it.get("file", "")))
        console.print(table)


@app.command("search")
def search(
    query: str = typer.Argument(..., help="Plain text or regex (use --regex)."),
    root: Path = typer.Option(Path("."), "--root", "-r", exists=True),
    regex: bool = typer.Option(False, "--regex", help="Interpret QUERY as a regular expression."),
    glob: Optional[list[str]] = typer.Option(None, "--glob", help="Limit search to files matching glob(s)."),
    top_k: int = typer.Option(100, "--top-k", help="Limit results."),
    context: int = typer.Option(1, "--context", "-C", help="Context lines to include."),
    output: str = typer.Option(_auto_format(), "--format", "-f", help="table, json, ndjson, auto"),
    relative: bool = typer.Option(True, "--relative/--absolute"),
):
    """
    Grep-like search via the catalog’s search facility (or a local fallback).
    """
    svc = _find_service()
    results = _call_service(
        svc,
        "search",
        root=Path(root),
        query=query,
        regex=regex,
        glob=glob,
        top_k=top_k,
        context=context,
        relative=relative,
    )

    rows = [_to_mapping(r) for r in results]
    fmt = output.lower()
    if fmt in ("json", "ndjson"):
        _emit_json(rows, ndjson=(fmt == "ndjson"))
        return

    table = Table(show_header=True)
    for c in ("file", "line", "match"):
        table.add_column(c)
    for r in rows:
        table.add_row(str(r.get("file", "")), str(r.get("line", "")), str(r.get("match", "")))
    console.print(table)


# ---- Minimal Python-only fallback service -----------------------------------
# This is intentionally simple: it only understands Python files for list/search,
# so your real service should supersede it as soon as it can be imported.

class _NaivePythonCatalogService:
    def list_files(self, root: Path, include: Optional[Sequence[str]] = None,
                   exclude: Optional[Sequence[str]] = None, hidden: bool = False,
                   relative: bool = True):
        root = Path(root)
        patterns = include or ["**/*.py"]
        matched: set[Path] = set()
        for pat in patterns:
            matched.update(root.glob(pat))
        files = sorted(p for p in matched if p.is_file())
        if exclude:
            ex_paths: set[Path] = set()
            for pat in exclude:
                ex_paths.update(root.glob(pat))
            files = [f for f in files if f not in ex_paths]
        if not hidden:
            files = [f for f in files if not any(part.startswith(".") for part in f.relative_to(root).parts)]
        if relative:
            return [str(f.relative_to(root)) for f in files]
        return [str(f) for f in files]

    def list_symbols(self, root: Path, glob: Optional[str] = None, language: Optional[str] = None,
                     kinds: Optional[Sequence[str]] = None, name: Optional[str] = None,
                     name_regex: Optional[str] = None, limit: int = 0, sort: str = "file,line,name",
                     descending: bool = False, relative: bool = True):
        import ast

        if language and language.lower() not in ("py", "python"):
            return []

        files = self.list_files(root, include=[glob] if glob else None, relative=True)
        rx = re.compile(name_regex) if name_regex else None
        out: list[dict[str, Any]] = []

        for rf in files:
            p = Path(root) / rf
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(text)
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    k = "function"
                    nm = node.name
                    ln = getattr(node, "lineno", 1)
                elif isinstance(node, ast.AsyncFunctionDef):
                    k = "function"
                    nm = node.name
                    ln = getattr(node, "lineno", 1)
                elif isinstance(node, ast.ClassDef):
                    k = "class"
                    nm = node.name
                    ln = getattr(node, "lineno", 1)
                else:
                    continue

                if kinds and k not in kinds:
                    continue
                if name and name.lower() not in nm.lower():
                    continue
                if rx and not rx.search(nm):
                    continue

                out.append({
                    "id": f"{rf}:{ln}:{nm}",
                    "name": nm,
                    "kind": k,
                    "language": "python",
                    "file": rf if relative else str(p),
                    "line": ln,
                })

        if sort:
            keys = [s.strip() for s in sort.split(",") if s.strip()]
            def _key(d: Mapping[str, Any]): return tuple(d.get(k) for k in keys)
            out.sort(key=_key, reverse=descending)

        if limit and len(out) > limit:
            out = out[:limit]
        return out

    def get_symbol(self, symbol_id: str, context: int = 4, show_source: bool = True):
        file, line, name = symbol_id.split(":", 2)
        p = Path(file)
        if not p.is_file():
            # maybe relative to cwd
            p = Path(".") / file
        meta = {"id": symbol_id, "file": str(file), "line": int(line), "name": name, "language": "python"}
        if not show_source:
            return meta
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            idx = max(0, int(line) - 1)
            lo, hi = max(0, idx - context), min(len(lines), idx + context + 1)
            snippet = "\n".join(lines[lo:hi])
            meta["source"] = snippet
        except Exception:
            pass
        return meta

    def search(self, root: Path, query: str, regex: bool = False, glob: Optional[Sequence[str]] = None,
               top_k: int = 100, context: int = 1, relative: bool = True):
        files = self.list_files(root, include=glob, relative=True)
        rx = re.compile(query) if regex else None
        results: list[dict[str, Any]] = []
        for rf in files:
            p = Path(root) / rf
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                hit = (rx.search(line) if rx else (query in line))
                if hit:
                    results.append({"file": rf if relative else str(p), "line": i, "match": line.strip()})
                    if len(results) >= top_k:
                        return results
        return results


# ---- Entrypoint -------------------------------------------------------------

def main() -> None:
    app()  # Typer CLI


if __name__ == "__main__":
    main()
```

---

## `codeintel/__main__.py`

```python
from .cli import main

if __name__ == "__main__":
    main()
```

---

## Optional `pyproject.toml` snippet (expose `codeintel` command)

```toml
[project]
name = "codeintel"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = ["typer>=0.9", "rich>=13"]

[project.scripts]
codeintel = "codeintel.cli:main"
```

> If your service lives in a different package, keep this `pyproject.toml` in that package instead and adjust the import shim (or set `CODEINTEL_SERVICE_IMPORT`, below).

---

## How the CLI finds your service (no MCP coupling)

* By default, it looks for one of:

  * `codeintel.catalog:get_service()` → service instance
  * `codeintel.catalog:service` → service singleton
  * `codeintel.catalog:CodeIntelCatalogService` (instantiated)
  * `codeintel.services.catalog:CodeIntelCatalogService` (instantiated)
* You can **override** with an env var:

  ```bash
  export CODEINTEL_SERVICE_IMPORT="yourpkg.yourmod:get_service"
  ```
* It never imports your MCP server or registration code. Your MCP layer can continue to **auto‑discover** tools via decorators elsewhere, independent of this CLI.

---

## Expected service interface (light contract)

Your existing service probably already exposes these. The CLI uses reflection to pass only parameters a method actually declares.

```python
class CatalogService:
    def list_symbols(self, *, root: Path, glob: str | None = None,
                     language: str | None = None, kinds: list[str] | None = None,
                     name: str | None = None, name_regex: str | None = None,
                     limit: int = 0, sort: str = "file,line,name",
                     descending: bool = False, relative: bool = True) -> Iterable[Any]: ...

    def get_symbol(self, *, symbol_id: str, context: int = 4,
                   show_source: bool = True) -> Any: ...

    def list_files(self, *, root: Path, include: list[str] | None = None,
                   exclude: list[str] | None = None, hidden: bool = False,
                   relative: bool = True) -> Iterable[str | Any]: ...

    def search(self, *, root: Path, query: str, regex: bool = False,
               glob: list[str] | None = None, top_k: int = 100,
               context: int = 1, relative: bool = True) -> Iterable[Any]: ...
```

> Return types can be pydantic models, dataclasses, or plain dicts—CLI normalizes them to JSON when needed.

---

## Usage examples

```bash
# List Python classes and functions everywhere under the repo
codeintel catalog list-symbols -r . --lang python --kind class --kind function

# Filter by filename glob and partial name (case-insensitive)
codeintel catalog list-symbols -r . --glob "src/**/*.py" --name Client

# Use a regex on the symbol name
codeintel catalog list-symbols -r . --name-regex "^(get|set)_"

# Show one symbol (with source preview)
codeintel catalog show-symbol "src/api/client.py:123:Client"

# Machine-readable output
codeintel catalog list-symbols -r . --format json > symbols.json
codeintel catalog list-symbols -r . --format ndjson | jq -c .

# List files the catalog would scan
codeintel catalog list-files -r . -I "src/**/*.py" -E "src/**/generated/*"

# Grep-like search (plain or regex)
codeintel search "TODO" -r . --glob "src/**/*.py" --top-k 50
codeintel search "(?i)auth(token|z)" -r . --glob "src/**/*" --regex
```

**Exit codes**

* `0` success with output
* `2` no results (e.g., `list-symbols` found nothing)
* `64` bad CLI usage / bad format

---

## Why this design

* **Local-first**: zero MCP imports; your MCP server keeps auto‑discovery via decorators unchanged.
* **Stable contract**: CLI reflects the service method signatures and passes only supported kwargs.
* **Scriptable**: JSON and NDJSON outputs for pipelines; table view for humans.
* **Pragmatic fallback**: a small Python‑only catalog kicks in until your real service import is available.

---

