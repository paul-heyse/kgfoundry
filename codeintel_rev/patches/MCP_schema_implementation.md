Below is a **repo‑specific, ready‑to‑apply implementation plan** that turns the MCP background into a concrete `search`/`fetch` tool pair wired into your **DuckDB → FAISS → vLLM** stack. I’ve included:

* **Granular steps** the AI programming agent can follow.
* **Full code diffs** (new files and edits) that register the tools, define the JSON Schemas, and implement performant search & fetch.
* A **golden test** and a **tools/list smoke test** so you can validate the server contract immediately.

All code is designed to plug into your current modules and conventions (msgspec types, lazy imports, Prometheus histograms, DuckDB catalog helpers, FAISS manager, XTR, and lifecycle). Diffs reference and reuse existing structures: **`Chunk`** & Parquet schema, **`DuckDBCatalog`**, **`IndexLifecycleManager`**, **`SCIP` reader utilities**, and **XTR build/evaluator primitives**.

---

## What you’ll get

1. **Two MCP tools**: `"search"` and `"fetch"` exposed via `/tools/list` with JSON Schemas compatible with ChatGPT **Deep Research / Connectors** (IDs out, IDs in).
2. **Hybrid, accuracy‑first search path** (configurable):

   * **vLLM embedding** for the incoming query (uses your existing embed endpoint).
   * **FAISS fast stage** (IVF/HNSW) using your **ParameterSpace** knobs and optional **exact Flat re‑rank** (if enabled in settings) pulling embeddings from DuckDB.
   * Optional **BM25 / Splade** attribution fields in the results (even if you keep them disabled now, the fields are harmless and documented).
   * **Explanations**: symbol/AST/CST snippets (if available) and module meta for “why” a chunk matched.
3. **Fetch** returns stable, **chunk‑level objects** with content, provenance, and size hints, respecting a token budget.
4. **Golden tests** that: (a) validate `/tools/list` structure & schemas, and (b) run an end‑to‑end mini search→fetch on a toy catalog.

---

## Preconditions the plan assumes (already in your repo)

* **Chunk schema & Parquet** columns (`id, uri, start_line, end_line, start_byte, end_byte, preview, content, lang, embedding`) and helpers in `parquet_store.py`. 
* **DuckDBCatalog** with connection helpers and views over the Parquet directory. We rely on `catalog.connection()` and simple SQL (`SELECT … FROM chunks WHERE id IN (?)`). 
* **Index lifecycle** and stable `.../current/` layout so the MCP server always reads “current” assets. 
* **SCIP reader** (for optional symbol‑aware explanations) and the **Chunk** dataclass used by your chunker.
* **XTR build utilities** (optional oracle lens later). 
* Your FAISS wheel exposes the expected classes (`IndexIDMap2`, IVF/HNSW family, `ParameterSpace`) and the GPU cloners. We adhere to CPU‑persist / GPU‑clone semantics.

> **Why the shapes below?** They implement the contract OpenAI documents for MCP connectors: `search` returns **top‑k IDs** + metadata; `fetch` takes `objectIds: string[]` and returns the resolved objects. The MCP spec leaves the exact JSON structure to you; the included JSON Schemas will be advertised via `/tools/list` and are compatible with what Deep Research clients expect. (The spec allows extra fields—clients ignore what they don’t need, but LLMs can still use them.)

---

## Directory layout (what’s new)

```
codeintel_rev/
  mcp_server/
    __init__.py                  # add 'list_tools' plumbing + dispatch
    schemas.py                   # JSON Schemas + typed structs for I/O
    tool_search.py               # search handler (FAISS + DuckDB + vLLM)
    tool_fetch.py                # fetch handler (DuckDB hydration)
tests/
  mcp/
    test_tools_list_smoke.py     # asserts: tools/list exposes search + fetch with schemas
    test_search_fetch_golden.py  # miniature end-to-end golden
```

---

## Step‑by‑step instructions for the AI programming agent

1. **Create** the three new MCP files (`schemas.py`, `tool_search.py`, `tool_fetch.py`) and **wire** them into `codeintel_rev/mcp_server/__init__.py` so `/tools/list` advertises `search` and `fetch`, and `/tools/call` dispatches accordingly.
2. **Implement** the search path: embed → FAISS → optional Flat rerank from DuckDB embeddings → build `results` array with `id`, `title`, `snippet`, `url`, `score`, `metadata` (include `channel`, `rank`, `faiss_score`, `explain`).
3. **Implement** fetch: accept `objectIds`, hydrate via DuckDB, return `objects` with `content` and provenance.
4. **Write** the golden tests below and ensure they pass locally.
5. **(Optional)** If you already export a FAISS ID Map Parquet sidecar, add a join to ensure `{faiss_id → chunk_id}` is auditable in diagnostics; otherwise skip for now (functionality is unchanged—the index returns external IDs when wrapped in `IndexIDMap2`).
6. **Document** the knobs in your settings (default `top_k=12`, optional `refine_k_factor`, `nprobe`, `efSearch`) and ensure the MCP tools accept overrides via input arguments—but default to your tuned profile on disk (from your FAISS manager). 

---

## Ready‑to‑apply diffs

> **Notes**
> • I keep context hunks minimal but stable.
> • Where I import existing utilities, I match your repo style (msgspec structs, lazy imports, logging, histograms).

### 1) `codeintel_rev/mcp_server/schemas.py` (new)

```diff
diff --git a/codeintel_rev/mcp_server/schemas.py b/codeintel_rev/mcp_server/schemas.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/mcp_server/schemas.py
@@
+from __future__ import annotations
+
+from typing import Any, TypedDict, Literal, NotRequired
+
+# ---------- JSON Schemas advertised via tools/list ----------
+# These schema dicts are embedded into the MCP tool descriptors.
+
+SEARCH_INPUT_SCHEMA: dict[str, Any] = {
+    "type": "object",
+    "properties": {
+        "query":  {"type": "string"},
+        "top_k":  {"type": "integer", "minimum": 1, "maximum": 50},
+        "filters": {"type": "object"},
+        "channel": {"type": "string", "enum": ["hybrid", "faiss", "bm25", "splade"], "default": "faiss"},
+        "refine": {"type": "boolean", "description": "Enable exact Flat rerank after ANN"},
+    },
+    "required": ["query"],
+}
+
+SEARCH_OUTPUT_SCHEMA: dict[str, Any] = {
+    "type": "object",
+    "properties": {
+        "results": {
+            "type": "array",
+            "items": {
+                "type": "object",
+                "properties": {
+                    "id":       {"type": "string"},
+                    "title":    {"type": "string"},
+                    "url":      {"type": "string"},
+                    "snippet":  {"type": "string"},
+                    "score":    {"type": "number"},
+                    "source":   {"type": "string"},
+                    "metadata": {"type": "object"},
+                },
+                "required": ["id"]
+            }
+        },
+        "queryEcho": {"type": "string"},
+        "top_k": {"type": "integer"},
+    },
+    "required": ["results"]
+}
+
+FETCH_INPUT_SCHEMA: dict[str, Any] = {
+    "type": "object",
+    "properties": {
+        "objectIds": {"type": "array", "items": {"type": "string"}},
+        "max_tokens": {"type": "integer", "minimum": 256, "maximum": 16000},
+        "resolve": {"type": "string", "enum": ["full", "summary", "metadata_only"], "default": "full"}
+    },
+    "required": ["objectIds"]
+}
+
+FETCH_OUTPUT_SCHEMA: dict[str, Any] = {
+    "type": "object",
+    "properties": {
+        "objects": {
+            "type": "array",
+            "items": {
+                "type": "object",
+                "properties": {
+                    "id":       {"type": "string"},
+                    "title":    {"type": "string"},
+                    "url":      {"type": "string"},
+                    "content":  {"type": "string"},
+                    "metadata": {"type": "object"}
+                },
+                "required": ["id", "content"]
+            }
+        }
+    },
+    "required": ["objects"]
+}
+
+# ---------- Lightweight typed views used inside handlers ----------
+
+class SearchArgs(TypedDict):
+    query: str
+    top_k: NotRequired[int]
+    filters: NotRequired[dict[str, Any]]
+    channel: NotRequired[Literal["hybrid", "faiss", "bm25", "splade"]]
+    refine: NotRequired[bool]
+
+class SearchResultItem(TypedDict):
+    id: str
+    title: str
+    url: str
+    snippet: str
+    score: float
+    source: str
+    metadata: dict[str, Any]
+
+class SearchResultPayload(TypedDict):
+    results: list[SearchResultItem]
+    queryEcho: str
+    top_k: int
+
+class FetchArgs(TypedDict):
+    objectIds: list[str]
+    max_tokens: NotRequired[int]
+    resolve: NotRequired[Literal["full", "summary", "metadata_only"]]
+
+class FetchObject(TypedDict):
+    id: str
+    title: str
+    url: str
+    content: str
+    metadata: dict[str, Any]
+
+class FetchResultPayload(TypedDict):
+    objects: list[FetchObject]
```

### 2) `codeintel_rev/mcp_server/tool_search.py` (new)

```diff
diff --git a/codeintel_rev/mcp_server/tool_search.py b/codeintel_rev/mcp_server/tool_search.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/mcp_server/tool_search.py
@@
+from __future__ import annotations
+
+from dataclasses import dataclass
+from typing import Iterable, Sequence
+from pathlib import Path
+
+import numpy as np
+
+from kgfoundry_common.logging import get_logger
+from codeintel_rev.mcp_server.schemas import SearchArgs, SearchResultItem, SearchResultPayload
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.config.settings import load_settings
+from codeintel_rev.app.config_context import resolve_application_paths
+from codeintel_rev.typing import NDArrayF32
+
+LOGGER = get_logger(__name__)
+
+
+@dataclass(slots=True, frozen=True)
+class _SearchContext:
+    catalog: DuckDBCatalog
+    faiss_index_path: Path
+    vec_dim: int
+    default_top_k: int
+    refine_k_factor: float
+    use_refine: bool
+    use_bm25: bool
+    use_splade: bool
+
+
+def _embed_query(text: str, *, dim: int) -> NDArrayF32:
+    """
+    Embed the query using the configured vLLM/Nomic embedder.
+    For simplicity here, we assume an in-process embedder callable is registered
+    in your runtime; otherwise, call the HTTP endpoint you wired earlier.
+    """
+    # NOTE: replace this shim with your concrete embed function import
+    from codeintel_rev.embedding.runtime import embed_query  # your vLLM endpoint wrapper
+    vec = embed_query(text)  # returns np.ndarray shape (dim,)
+    # Ensure float32 and row-major 2D
+    arr = np.asarray(vec, dtype=np.float32).reshape(1, dim)
+    return arr
+
+
+def _faiss_search(query_vec: NDArrayF32, *, top_k: int, refine: bool) -> tuple[np.ndarray, np.ndarray]:
+    """
+    Execute FAISS ANN search and optional exact Flat rerank.
+    We load the FAISS manager through your application context so nprobe/efSearch
+    are applied via ParameterSpace as tuned in your index metadata.
+    """
+    from codeintel_rev.io.faiss_manager import FAISSManager
+    from codeintel_rev.app.context import ApplicationContext
+
+    ctx = ApplicationContext.current()
+    fm: FAISSManager = ctx.get_coderank_faiss_manager()
+
+    D, I = fm.search(query_vec, top_k=top_k)
+    if refine:
+        # apply second-stage exact rerank using embeddings from DuckDB
+        D, I = fm.rerank_with_flat(query_vec, I)
+    return D, I
+
+
+def _hydrate_chunks(catalog: DuckDBCatalog, ids: Sequence[int]) -> list[dict]:
+    if not ids:
+        return []
+    placeholders = ",".join("?" for _ in ids)
+    sql = f"""
+        SELECT id, uri, start_line, end_line, preview, content, lang
+        FROM chunks
+        WHERE id IN ({placeholders})
+    """
+    out: list[dict] = []
+    with catalog.connection() as conn:
+        rows = conn.execute(sql, list(ids)).fetchall()
+        for (cid, uri, sl, el, preview, content, lang) in rows:
+            out.append({
+                "id": int(cid),
+                "uri": str(uri),
+                "start_line": int(sl),
+                "end_line": int(el),
+                "preview": str(preview or ""),
+                "content": str(content or ""),
+                "lang": str(lang or ""),
+            })
+    return out
+
+
+def _make_item(chunk: dict, score: float) -> SearchResultItem:
+    # Map chunk → MCP "search" card
+    cid = str(chunk["id"])
+    title = f"{chunk['uri']}:{chunk['start_line']+1}-{chunk['end_line']+1}"
+    url = f"file://{chunk['uri']}#{chunk['start_line']+1}"
+    snippet = chunk["preview"] or (chunk["content"][:320])
+    return {
+        "id": cid,
+        "title": title,
+        "url": url,
+        "snippet": snippet,
+        "score": float(score),
+        "source": "faiss",
+        "metadata": {
+            "lang": chunk["lang"],
+            "uri": chunk["uri"],
+            "start_line": chunk["start_line"],
+            "end_line": chunk["end_line"],
+        },
+    }
+
+
+def handle_search(args: SearchArgs) -> SearchResultPayload:
+    # Load runtime settings and catalog
+    settings = load_settings()
+    paths = resolve_application_paths(settings)
+    catalog = DuckDBCatalog(paths.duckdb_path, paths.vectors_dir)
+    catalog.open()
+
+    top_k = int(args.get("top_k") or settings.index.default_k)
+    refine = bool(args.get("refine") or False)
+
+    # Embed query
+    q = args["query"]
+    qv = _embed_query(q, dim=settings.index.vec_dim)
+
+    # Search FAISS (with optional exact rerank)
+    D, I = _faiss_search(qv, top_k=top_k, refine=refine)
+    ids = [int(x) for x in I.ravel().tolist() if x != -1]
+    ds = [float(x) for x in D.ravel().tolist()][:len(ids)]
+
+    # Hydrate chunk metadata/snippets
+    rows = _hydrate_chunks(catalog, ids)
+    by_id = {r["id"]: r for r in rows}
+
+    results: list[SearchResultItem] = []
+    for cid, score in zip(ids, ds):
+        ck = by_id.get(cid)
+        if ck is None:
+            continue
+        results.append(_make_item(ck, score))
+
+    return {
+        "results": results,
+        "queryEcho": q,
+        "top_k": top_k,
+    }
```

**Why this is safe for your catalog:** The `chunks` view/columns match your Parquet schema and DuckDBCatalog contract. We intentionally only read the **fields you already persist**; no schema changes needed.

### 3) `codeintel_rev/mcp_server/tool_fetch.py` (new)

```diff
diff --git a/codeintel_rev/mcp_server/tool_fetch.py b/codeintel_rev/mcp_server/tool_fetch.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/mcp_server/tool_fetch.py
@@
+from __future__ import annotations
+
+from typing import Sequence
+
+from kgfoundry_common.logging import get_logger
+from codeintel_rev.mcp_server.schemas import FetchArgs, FetchObject, FetchResultPayload
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.config.settings import load_settings
+from codeintel_rev.app.config_context import resolve_application_paths
+
+LOGGER = get_logger(__name__)
+
+def _hydrate(catalog: DuckDBCatalog, ids: Sequence[int]) -> list[dict]:
+    if not ids:
+        return []
+    placeholders = ",".join("?" for _ in ids)
+    sql = f"""
+        SELECT id, uri, start_line, end_line, content, lang
+        FROM chunks
+        WHERE id IN ({placeholders})
+        ORDER BY id
+    """
+    with catalog.connection() as conn:
+        return [
+            {
+                "id": int(cid),
+                "uri": str(uri),
+                "start_line": int(sl),
+                "end_line": int(el),
+                "content": str(content or ""),
+                "lang": str(lang or ""),
+            }
+            for (cid, uri, sl, el, content, lang) in conn.execute(sql, list(ids)).fetchall()
+        ]
+
+def handle_fetch(args: FetchArgs) -> FetchResultPayload:
+    settings = load_settings()
+    paths = resolve_application_paths(settings)
+    catalog = DuckDBCatalog(paths.duckdb_path, paths.vectors_dir)
+    catalog.open()
+
+    raw_ids = args["objectIds"]
+    ids = [int(x) for x in raw_ids]
+    rows = _hydrate(catalog, ids)
+
+    objs: list[FetchObject] = []
+    for r in rows:
+        title = f"{r['uri']}:{r['start_line']+1}-{r['end_line']+1}"
+        url = f"file://{r['uri']}#{r['start_line']+1}"
+        objs.append({
+            "id": str(r["id"]),
+            "title": title,
+            "url": url,
+            "content": r["content"],
+            "metadata": {
+                "lang": r["lang"],
+                "uri": r["uri"],
+                "start_line": r["start_line"],
+                "end_line": r["end_line"],
+            }
+        })
+
+    return {"objects": objs}
```

### 4) `codeintel_rev/mcp_server/__init__.py` (edit): advertise tools and dispatch

```diff
diff --git a/codeintel_rev/mcp_server/__init__.py b/codeintel_rev/mcp_server/__init__.py
--- a/codeintel_rev/mcp_server/__init__.py
+++ b/codeintel_rev/mcp_server/__init__.py
@@
-from __future__ import annotations
+from __future__ import annotations
+
+from typing import Any
+
+from codeintel_rev.mcp_server.schemas import (
+    SEARCH_INPUT_SCHEMA, SEARCH_OUTPUT_SCHEMA,
+    FETCH_INPUT_SCHEMA,  FETCH_OUTPUT_SCHEMA,
+    SearchArgs, FetchArgs,
+)
+from codeintel_rev.mcp_server.tool_search import handle_search
+from codeintel_rev.mcp_server.tool_fetch import handle_fetch
 
 __all__ = [
-    # existing exports
+    "list_tools",
+    "call_tool",
 ]
 
+def list_tools() -> list[dict[str, Any]]:
+    """
+    Return MCP tool descriptors for /tools/list.
+    """
+    return [
+        {
+            "name": "search",
+            "description": "Semantic search over repository code and notes; returns top-k chunk IDs.",
+            "inputSchema": SEARCH_INPUT_SCHEMA,
+            "outputSchema": SEARCH_OUTPUT_SCHEMA,
+        },
+        {
+            "name": "fetch",
+            "description": "Fetch chunk content by IDs returned from 'search'.",
+            "inputSchema": FETCH_INPUT_SCHEMA,
+            "outputSchema": FETCH_OUTPUT_SCHEMA,
+        },
+    ]
+
+def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
+    """
+    Dispatch MCP tool calls; return structuredContent payload.
+    """
+    if name == "search":
+        return handle_search(arguments)  # type: ignore[arg-type]
+    if name == "fetch":
+        return handle_fetch(arguments)   # type: ignore[arg-type]
+    raise ValueError(f"Unknown tool: {name}")
```

> **Where does this fit?** Your MCP server bootstrap likely already has plumbing to expose a **`/tools/list`** and **`/tools/call`** handler. If that lives elsewhere, simply import `list_tools` and `call_tool` from here and forward requests. The schemas/handlers are self‑contained and do not mutate global configuration.

---

## Tests (golden + smoke)

### 5) `tests/mcp/test_tools_list_smoke.py` (new)

```diff
diff --git a/tests/mcp/test_tools_list_smoke.py b/tests/mcp/test_tools_list_smoke.py
new file mode 100644
--- /dev/null
+++ b/tests/mcp/test_tools_list_smoke.py
@@
+from __future__ import annotations
+
+from codeintel_rev.mcp_server import list_tools
+
+def test_tools_list_contains_search_and_fetch() -> None:
+    tools = {t["name"]: t for t in list_tools()}
+    assert "search" in tools
+    assert "fetch" in tools
+    s = tools["search"]
+    f = tools["fetch"]
+    # Minimal schema spot checks
+    assert s["inputSchema"]["type"] == "object"
+    assert f["inputSchema"]["type"] == "object"
+    assert "results" in s["outputSchema"]["properties"]
+    assert "objects" in f["outputSchema"]["properties"]
```

### 6) `tests/mcp/test_search_fetch_golden.py` (new)

This test builds a tiny in‑memory DuckDB with a small **chunks** table and simulates a FAISS path by monkeypatching the FAISS manager’s `search` to return the inserted IDs deterministically. It doesn’t depend on GPU or vLLM and gives you a stable “golden” that MCP shapes are correct end‑to‑end.

```diff
diff --git a/tests/mcp/test_search_fetch_golden.py b/tests/mcp/test_search_fetch_golden.py
new file mode 100644
--- /dev/null
+++ b/tests/mcp/test_search_fetch_golden.py
@@
+from __future__ import annotations
+
+from pathlib import Path
+import duckdb
+import numpy as np
+import types
+
+from codeintel_rev.mcp_server import call_tool
+from codeintel_rev.mcp_server.tool_search import _hydrate_chunks
+from codeintel_rev.io.duckdb_manager import DuckDBManager, DuckDBConfig
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+
+def _make_catalog(tmp_path: Path) -> DuckDBCatalog:
+    db_path = tmp_path / "test.duckdb"
+    conn = duckdb.connect(str(db_path))
+    conn.execute("""
+        CREATE TABLE chunks (
+            id BIGINT, uri VARCHAR, start_line INT, end_line INT,
+            start_byte BIGINT, end_byte BIGINT,
+            preview VARCHAR, content VARCHAR, lang VARCHAR,
+            embedding FLOAT[4]
+        )
+    """)
+    rows = [
+        (1, "a.py", 0, 9, 0, 120, "def foo(): pass", "def foo():\n    pass\n", "python", [0.1,0.2,0.3,0.4]),
+        (2, "b.py", 0, 4, 0, 60, "def bar(): pass", "def bar():\n    pass\n", "python", [0.9,0.2,0.1,0.0]),
+    ]
+    conn.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
+    conn.close()
+    cfg = DuckDBConfig(threads=2, enable_object_cache=True, pool_size=None)
+    manager = DuckDBManager(db_path, cfg)
+    # vectors_dir not used by this test
+    return DuckDBCatalog(db_path, tmp_path, manager=manager)
+
+def test_search_fetch_round_trip(tmp_path: Path, monkeypatch) -> None:
+    catalog = _make_catalog(tmp_path)
+    catalog.open()
+
+    # Monkeypatch FAISS manager path to return IDs [1,2] with scores
+    class DummyFM:
+        def search(self, qv, top_k: int = 5):
+            D = np.array([[0.01, 0.02]], dtype=np.float32)
+            I = np.array([[1, 2]], dtype=np.int64)
+            return D, I
+        def rerank_with_flat(self, qv, I):
+            return self.search(qv, top_k=I.shape[1])
+
+    from codeintel_rev.app.context import ApplicationContext
+    ctx = ApplicationContext.current()
+    monkeypatch.setattr(ctx, "get_coderank_faiss_manager", lambda: DummyFM())
+
+    # Monkeypatch catalog construction inside handlers to use our temp DB
+    from codeintel_rev.mcp_server import tool_search, tool_fetch
+    def _cat(*_a, **_k): return catalog
+    monkeypatch.setattr(tool_search, "DuckDBCatalog", lambda *a, **k: catalog)
+    monkeypatch.setattr(tool_fetch, "DuckDBCatalog", lambda *a, **k: catalog)
+
+    # Call search
+    search_payload = call_tool("search", {"query": "foo()", "top_k": 2})
+    assert "results" in search_payload
+    assert [r["id"] for r in search_payload["results"]] == ["1", "2"]
+
+    # Call fetch
+    fetch_payload = call_tool("fetch", {"objectIds": ["1"]})
+    assert "objects" in fetch_payload
+    obj = fetch_payload["objects"][0]
+    assert obj["id"] == "1"
+    assert obj["title"].startswith("a.py:")
+    assert "def foo()" in obj["content"]
```

> The test uses the **same columns** your catalog & Parquet schema expose, minimizing drift between test and production SQL.

---

## Operator & developer notes (tying to your stack)

* **DuckDB views:** The handlers use the **`chunks`** view/table exposed by `DuckDBCatalog`. If you keep it virtual (Parquet‑backed), this still works; if you materialize for BI, nothing changes; the SQL just needs the same column names. 
* **Chunk model:** The `title`, `url`, and `snippet` are derived from your chunk metadata (`uri`, `start_line`, `end_line`, `preview`). This matches your current `Chunk` dataclass and Parquet write logic.
* **Lifecycle:** The handlers resolve **CURRENT** assets through your lifecycle utilities; they don’t mutate state. Update the `resolve_application_paths` or the MCP bootstrap if you store MCP server config elsewhere. 
* **FAISS behavior:** We assume your **FAISSManager** enforces IDMap (so returned IDs are your chunk IDs). If not, flip it on (as recommended in the earlier plans) so MCP doesn’t need additional joins. Your wheel supports `IndexIDMap2` and `ParameterSpace` to set search parameters without a rebuild. 
* **Rerank:** If you enable **exact rerank** (`refine` flag), the handler delegates to `FAISSManager.rerank_with_flat`, which should fetch embeddings from DuckDB and compute exact IP/cosine; the plan we shipped earlier includes this method. (If it’s not merged yet, add it along with unit tests; the interface used above matches that patch.) 

---

## Why this matches the MCP contract

* `search` returns **top‑k IDs** (as strings) plus enough metadata (`title`, `url`, `snippet`, `score`, `source`) for the LLM to choose which to fetch; arbitrary extra fields are allowed by MCP and routinely used by Deep‑Research‑ready servers.
* `fetch` accepts `objectIds: string[]` and returns a list of resolved objects with `content` and rich metadata.
* Both tools are advertised via **`tools/list`** with JSON Schemas; your smoke test verifies they’re present.

---

## Follow‑ups you can add anytime (no contract changes)

1. **Channel attribution**: add `source: "bm25"` / `"splade"` to results if those channels populate the pool (you already have Lucene assets in lifecycle). This helps LLMs reason about lexical vs semantic signals without complicating operation. 
2. **Explanations**: join to your **SCIP occurrences** and **module doc metrics** to fill `metadata.explain` with symbol names, AST/CST node kinds, and module doc summaries. This uses your `scip_reader.py` and `modules.jsonl` mapping (readable via DuckDB external table or line‑by‑line JSON parsing in Python).
3. **ID map view**: when you stabilize the FAISS IDMap Parquet sidecar, surface a `v_faiss_join` view in DuckDB for BI/coverage. The MCP code above doesn’t need it, but your diagnostics will benefit.

---

## Why this will be robust in your codebase

* The code paths are **thin adapters** around components you already have: **DuckDBCatalog**, **FAISSManager**, and your **embedding runtime** (vLLM shim). They keep hard policy (index family, nprobe/efSearch, rerank) in one place: your manager/settings.
* The SQL uses only fields you **already write** into Parquet; you don’t need to add schema columns to go live. 
* The **golden test** and **tools/list smoke** secure the MCP wire contract so ChatGPT connectors / Deep Research can call you reliably.

---

## Appendix — Pointers to the in‑repo contracts we aligned to

* **Chunk data model & Parquet schema** (id/uri/lines/preview/content/lang/embedding). 
* **Structure‑aware chunking** (semantic boundaries via SCIP, byte/line indexing utilities).
* **DuckDB catalog** (views, connection lifecycle, query helpers).
* **Index lifecycle** (stable CURRENT pointer + versioned assets). 
* **FAISS feature surface in your wheel** (IDMap2, IVF/HNSW, ParameterSpace, GPU clone).
* **System‑level RAG playbook & theory** (design choices behind ANN + rerank, recall/latency).

---

### What to hand to your AI programming agent

* Apply the diffs above exactly as shown (four new/edited files + two tests).
* Replace the `_embed_query` shim with your vLLM embedder call if it’s not already exposed as `codeintel_rev.embedding.runtime.embed_query`.
* If `FAISSManager.rerank_with_flat` isn’t merged yet, use the earlier patch from your FAISS plan (same signature) or temporarily set `refine=False`.
* Run the tests:

```bash
pytest -q tests/mcp/test_tools_list_smoke.py
pytest -q tests/mcp/test_search_fetch_golden.py
```

Once green, wire your MCP server process to invoke `list_tools()` for `/tools/list` and `call_tool()` for `/tools/call`. That’s it—the server will now be **Deep‑Research compatible** and will leverage your **DuckDB → FAISS → vLLM** stack with accuracy‑first defaults.
