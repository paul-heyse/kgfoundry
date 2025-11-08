Below is a concrete, repo‑specific **technical implementation plan** to get your **answer‑response** dataflows to “best‑in‑class”—with targeted fixes where I saw fragility in `codeintel_rev`. I read the zip you attached and reviewed the code under `codeintel_rev/` (notably `app/`, `io/`, `mcp_server/`, `retrieval/`, `indexing/`, `config/`, `tests/`). I’ll call out exact files and suggest precise changes. I’ll also map these to DuckDB/FAISS/vLLM behaviors (with primary‑source citations).

---

## Executive summary (what to change first)

1. **Make the answer pipeline explicit** (a single orchestrator that owns budgets, fallbacks, telemetry) instead of spreading logic across adapters and helpers.
2. **Fix cross‑process scope storage** (your session scope registry is per‑process; with `workers=2` you’ll lose scope unless you enforce stickiness or move to Redis).
3. **Harden DuckDB usage for concurrency & correctness** (move from a single shared connection on `DuckDBCatalog` to a per‑thread/per‑request connection strategy; add idempotent view/materialization bring‑up; enable object cache; parameterize queries).
4. **Finish hybrid retrieval** (your `retrieval/hybrid.py` has RRF but the adapters only use FAISS; wire in BM25/SPLADE + a cross‑encoder re‑ranker).
5. **Finalize FAISS dual‑index design** (your `FAISSManager` docstring describes a primary + secondary “incremental” index—finish GPU/CPU fallback, ID mapping persistence, compaction/merge, and partial‑rebuilds).
6. **Normalize embedding contract** end‑to‑end (one “embedding model ID → vector dim → dtype → normalization” source of truth; reject mismatches early in readiness).
7. **Stream answers with citations robustly** (bounded context windows, deterministic chunk formatting, cancellation, backpressure, progressive citations; include full tracing).
8. **Observability & SLOs** (instrument each stage; collect AnswerTrace rows as Parquet; Prometheus for latency/tokens/s, vector hits, reranker gains; readiness gates).

---

## What’s already strong (keep it)

* **Centralized startup context** in `app/config_context.py` and a **readiness probe** in `app/readiness.py`—great foundations for fail‑fast and health checks.
* **Typed settings** via `msgspec` in `config/settings.py` (fast and clear).
* **Parquet storage** with Arrow fixed‑size vectors in `io/parquet_store.py` (sound choice for interchange and DuckDB scanning).
* **Session ID middleware** in `app/middleware.py` and **scope registry** in `app/scope_registry.py` (nice ergonomics for “set once, reuse”).
* **vLLM embedding client** with persistent HTTP connection in `io/vllm_client.py`.

---

## Gaps & risks I actually saw (repo‑specific)

1. **Session scope isn’t shared across worker processes**

   * You run multiple ASGI workers (`app/hypercorn.toml` sets `workers = 2`). Your `ScopeRegistry` is an in‑memory dict guarded by an `RLock` (`app/scope_registry.py`). With multi‑process servers (Hypercorn/Gunicorn), **workers do not share memory**; a later request with the same `X‑Session-ID` can land on a different process and find **no stored scope**. Hypercorn’s `workers` option confirms multi‑process behavior; per‑process caches aren’t shared.  
     **Fix** below (“A. Scope & session”).

2. **DuckDB connection is process‑global and shared**

   * `io/duckdb_catalog.py` stores one `self.conn: duckdb.DuckDBPyConnection | None` and reuses it across calls. DuckDB’s Python client warns: **connections aren’t thread‑safe**; use separate connections (or a cursor per thread) (and prefer parameterized SQL). Enable `object_cache` for repeated scans. 
     **Fix** below (“B. DuckDB catalog”).

3. **Hybrid retrieval isn’t actually wired**

   * `retrieval/hybrid.py` contains RRF fusion (BM25/SPLADE/FAISS), but the MCP adapters in `mcp_server/adapters/semantic.py` only embed + FAISS and hydrate via DuckDB. There’s no Lucene/BM25 nor SPLADE integration yet (though paths exist in settings). This leaves **keyword‑only** queries weak and hurts coverage on noisy prompts. **Fix** below (“C. Retrieval layer”).

4. **FAISS manager is half‑finished**

   * `io/faiss_manager.py` describes a clean **primary + secondary** design, GPU cloning, and adaptive index types. But portions are incomplete (truncations aside): no clear **IndexIDMap** persistence, no versioned manifest, no **compaction** path for folding secondary into primary, and GPU detection/fallback is scattered across `app/gpu_warmup.py`. Also ensure cuVS acceleration & `StandardGpuResources` reuse are safely toggled. See the cuVS/FAISS notes. 
     **Fix** below (“D. Vector layer”).

5. **Embedding contract not fully enforced**

   * Multiple files mention a **2560‑dim** model (e.g., `io/vllm_client.py`, `parquet_store.py`, tests), but there isn’t a single enforced **source of truth**. Readiness doesn’t currently compare “Parquet schema dim vs FAISS index dim vs vLLM embedder dim” to fail fast. **Fix** below (“E. Embedding contract”).

6. **Answer orchestration is implicit**

   * The MCP tools call helpers directly (e.g., `adapters/semantic.py`), but there isn’t one “**AnswerOrchestrator**” that sets budgets, runs parallel retrievals, applies fusion/reranking, constructs prompts, streams results, handles cancellation, and records a full trace. That absence makes error handling and fallbacks scatter and makes **end‑to‑end SLOs** hard. **Fix** below (“F. Answer orchestrator”).

7. **Readiness checks can be stricter**

   * `app/readiness.py` is well‑structured; add dimension checks, index freshness and GPU state detail (including “degraded mode” with CPU FAISS) to match your production goals. **Fix** below (“G. Readiness & fallbacks”).

---

## Target architecture for “answer‑response” (RAG‑style)

```
┌────────────────────────────────────────────────────────────────────┐
│  MCP Tool: answer(query, scope?)                                   │
│  (codeintel_rev/mcp_server/server.py)                              │
└───────────────┬────────────────────────────────────────────────────┘
                │ 1) Validate + normalize request (scope merge)
                ▼
        ┌────────────────────────────────────────────────────────┐
        │ AnswerOrchestrator (new, retrieval+gen controller)     │
        │ - Budgets, timeouts, fallbacks, tracing                │
        │ - Parallel retrieval: FAISS + BM25(+SPLADE)            │
        │ - RRF fusion + duplicate collapse                      │
        │ - Optional rerank (cross-encoder / vLLM Score API)     │
        │ - Prompt build (window-aware, deterministic)           │
        │ - vLLM streaming w/ backpressure & cancellation        │
        │ - Progressive citations + partial results              │
        └───────────┬────────────────────────────────────────────┘
                    │
   ┌────────────────┴────────────────┐
   │                                 │
   ▼                                 ▼
FAISS manager                    DuckDB catalog
(io/faiss_manager.py)            (io/duckdb_catalog.py)
 - GPU clone (cuVS)              - Hydrate text/metadata
 - Secondary index for           - SQL/Arrow to retrieve
   incremental updates             chunk payloads
 - Id map persisted
```

**Generation**: stream tokens from **vLLM** OpenAI‑compatible server; use **structured outputs/tool‑calling** when needed; consider **Score API** for reranking or classification. 

**Transport/serving**: Hypercorn H2/H3 (or H2 behind NGINX QUIC), with correct ALPN/Alt‑Svc and streaming semantics (SSE or chunked). 

---

## A. Scope & session (correctness across workers)

**Problem**: `ScopeRegistry` stores per‑session scope in memory; with multiple Hypercorn workers, requests for the same `X‑Session-ID` can hit different processes that **don’t share** state. Hypercorn’s `workers` option indicates multi‑process; in‑process caches are per worker.  

**Plan**

* **Option 1 (recommended)**: Put a tiny Redis L2 for scopes keyed by `session_id`, with TTL (e.g., 1h). Keep your in‑process LRU as **L1** for speed; on miss, fetch from Redis. (Your middleware can continue to retrieve `session_id` via `ContextVar`.) Redis ensures cross‑worker coherence. (LRU/LFU eviction policies and multi‑worker reality are discussed in the caching guide.) 
* **Option 2**: Enforce **sticky sessions** at NGINX (hash on `X‑Session-ID`) so the same session reaches the same worker. Still, Redis is safer if you scale horizontally.

**Code**: wrap `ScopeRegistry` behind an interface; add `RedisScopeStore` with `get/set/delete`, TTL, and JSON serialization. The MCP adapters call a `get_effective_scope()` that consults L1→L2.

---

## B. DuckDB catalog (thread‑safety, perf, and filtering)

**Problems seen**

* Single shared `self.conn` (not thread‑safe) in `io/duckdb_catalog.py`.
* No object cache or remote FS extension toggles.
* Some filter logic falls back to Python `fnmatch` (OK), but we can **push more into SQL**.

**Plan**

1. **Connection strategy**

   * Replace one global connection with a **per‑thread (or per‑request) connection**. Either:

     * a `contextmanager` that opens/uses/closes a connection per call; or
     * a `threading.local()` that stores a connection bound to the thread; or
     * a small connection pool (queue of `duckdb.connect(...)`) limited to `N`.
       DuckDB’s Python docs: connections are **not thread‑safe**; create a cursor per thread or separate connections. 

2. **Config & pragmas**

   * On connection open:

     ```sql
     PRAGMA enable_object_cache;         -- repeated scans benefit
     SET threads = <n>;                  -- from config.limits
     ```

     (Object cache boosts repeated Parquet scans.) 

3. **Materialization toggle**

   * You already support `materialize=True` to create `chunks_materialized`. Keep it. Add a simple `SELECT count(*)` drift check and `CREATE INDEX` on `uri` (you have one). For Parquet‑only mode, prefer `read_parquet(glob)` view creation, which you’re using.

4. **SQL‑first filtering**

   * Continue to translate simple globs to `LIKE` for DB‑side pruning; for language filters, **inject extension lists** and push those into SQL (`WHERE LOWER(uri) LIKE ANY ($extensions)`) when small enough. Retain Python fallback for complex patterns. (You already outline this in docstrings—implement fully.)
   * Parameterize all SQL (`?`/`$1`/named) to avoid string‑format bugs. 

5. **Arrow zero‑copy when hydrating**

   * Where possible, return `Relation.arrow()` → Arrow Table → rows, instead of Python `fetchall`, for big batches. Keep this internal—adapters can convert to dicts as needed. 

**Tests**

* Extend `tests/test_duckdb_catalog.py` to hit concurrent calls (pytest `concurrency` with anyio) and assert results match with/without materialization.

---

## C. Retrieval layer (finish “hybrid”, add reranking)

**Problems seen**

* RRF is present in `retrieval/hybrid.py` but not actually used in adapters. `adapters/semantic.py` embeds then FAISS‑searches only.

**Plan**

1. **BM25**

   * Add a simple `pyserini` BM25 searcher against a Lucene index at `settings.lucene_dir`. Convert results into your `SearchHit` dataclass.

2. **SPLADE**

   * If you want learned sparse, add SPLADE (you already reserved `settings.splade_dir`). Use pyserini’s SPLADE integration or replicate indexer. Keep SPLADE optional via config.

3. **Fusion**

   * Run FAISS, BM25, and SPLADE **in parallel** with timeouts; RRF‑fuse (you have the function). Use consistent `doc_id` = chunk ID.

4. **Reranking (strongly recommended)**

   * Apply a cross‑encoder reranker (e.g., BGE reranker) or leverage **vLLM’s “Score API”** (OpenAI‑compatible `/v1/scores` / `/v1/classifications`) to re‑score top‑N fused hits (e.g., N=50 → R=10). It’s a clean way to keep model‑side logic in vLLM and maximize GPU utility you already have. 

5. **Hydration**

   * Use `DuckDBCatalog.query_by_ids(...)` with include/exclude globs and languages to post‑filter and fetch the **final** chunk payloads.

---

## D. Vector layer (FAISS: correctness, GPU, incremental, compaction)

**Problems seen**

* `FAISSManager` promises a **primary** (Flat/IVFFlat/IVF‑PQ) + **secondary** (IndexFlatIP incremental) architecture, CPU persistence with GPU clones, and adaptive index selection—but portions are unfinished (IDMap persistence, compaction/merge, polished GPU fallback).

**Plan**

1. **Primary index policies**

   * Use **IndexIDMap2** wrapping the trained index so **chunk ID ↔ vector** is explicit. Persist as `{index.faiss, ids.parquet}` or embed IDs in FAISS if using IDMap2. (FAISS idioms).
   * Select index type by corpus size (you already describe this). Train on a **sample** if huge.

2. **GPU acceleration (cuVS + FAISS GPU)**

   * On bring‑up, try GPU: create **one** `StandardGpuResources` and clone the CPU index with `index_cpu_to_gpu`. If GPU fails, set `gpu_disabled_reason` and remain **degraded‑but‑available** on CPU. cuVS/FAISS GPU accelerations are appropriate here; keep the toggle `use_cuvs` (or autodetect). 

3. **Secondary incremental index**

   * On every incremental batch (e.g., new commits or file changes), compute vectors and **append to secondary IndexFlatIP (IDMap2)** in RAM or persisted on disk (separate file).
   * At search time: query **both** primary and secondary; **merge+dedupe** on chunk ID; then pass to RRF/reranker.

4. **Compaction & versioning**

   * When `secondary.size > T` or at a scheduled maintenance window, **rebuild primary** by merging and re‑training as needed; then reset secondary.
   * Write a small **manifest** next to the FAISS file (JSON): `{version, index_type, d, trained_on, nlist, pq_m, built_at, uses_gpu, cuvs_version}`—to make readiness/debugging trivial.

5. **Dimension & dtype guardrails**

   * Enforce `float32` vectors (and L2/IP consistency). Before adding or searching, assert `vectors.shape[1] == vec_dim` else raise `ConfigurationError`.

6. **API surface**

   * Provide `ensure_ready()`, `search(vec, k, nprobe, alpha_secondary)` that auto‑selects GPU or CPU. Keep `nprobe`/`k` at the orchestrator to tune speed/quality tradeoffs per request.

**Readiness**

* Move some GPU checks from `app/gpu_warmup.py` into FAISS manager’s `ensure_ready()`: if GPU down, set **degraded mode** and continue on CPU. (Your warmup code already probes CUDA/Torch/FAISS.)

---

## E. Embedding contract (one source of truth + early failure)

**Problems seen**

* Dimension (e.g., 2560) is implied in multiple places, and `parquet_store.get_chunks_schema(vec_dim)` takes a parameter, but there’s no single authority.

**Plan**

* Add `EmbeddingsConfig` in `config/settings.py` with:

  * `model_id` (e.g., `nomic-embed-code`), `vec_dim`, `normalize` (bool), `dtype = float32`.
* In **readiness**:

  * call `vLLMClient.embed_batch(["probe"])` once (or `GET /` with model metadata if available) to detect `vec_dim`.
  * open FAISS CPU index and assert `index.d == vec_dim`.
  * inspect Parquet schema to assert fixed‑size list has `vec_dim`.
  * If any mismatch → readiness `false` with a helpful `detail`.
* Normalize embeddings consistently (unit L2 norm if using IP; else keep raw for L2).

**Why vLLM now?**
The vLLM server implements **Embeddings**, **Classifications/Score**, **Structured outputs**, **Tool calling**, etc., behind an OpenAI‑compatible API—so you can keep logic simple and reuse GPU. 

---

## F. Answer orchestrator (new module)

Create `codeintel_rev/answer/orchestrator.py`:

* **Inputs**: `QueryIn(text, scope, top_k=K, time_budget_ms, rerank_top_n=R)`.

* **Flow**:

  1. Build **three retrieval tasks** in parallel (FAISS, BM25, SPLADE) with **timeouts**.
  2. RRF‑fuse → take `M` unique doc IDs.
  3. Hydrate chunk payloads via DuckDB (SQL‑side filtering first).
  4. Optional reranking via vLLM **Score API** / cross‑encoder → trim to final `N`.
  5. Prompt‑build: format chunks deterministically; obey token budget (see vLLM model’s max context); optionally apply **prefix caching** for repeated code section prompts. 
  6. Call vLLM **Chat Completions** with **streaming**; propagate cancellation if the client disconnects; update progressive **citations** (best‑effort mapping by chunk).
  7. Emit `AnswerTrace` with timings, top‑k hits, model params, token usage.

* **Budgets**:

  * Retrieval budget and generation budget are **time‑boxed** (e.g., 400ms retrieval, gen starts with what’s ready).
  * If a retriever times out, proceed with remaining signals, log the timeout.

* **Backpressure & streaming**:

  * Expose tokens via FastAPI/Starlette `StreamingResponse`; Hypercorn provides backpressure semantics across H1/H2/H3 so your async send will block under client backpressure (that’s desirable).  

**Sketch**:

```python
# codeintel_rev/answer/orchestrator.py
class AnswerOrchestrator:
    def __init__(self, ctx: ApplicationContext): ...

    async def answer(self, q: str, scope: Scope, top_k=10, rerank_top_n=50):
        # 1) Kick off retrievals in parallel with timeouts
        faiss_t = asyncio.create_task(self._faiss(q, scope))
        bm25_t  = asyncio.create_task(self._bm25(q, scope))
        splade_t= asyncio.create_task(self._splade(q, scope))
        hits = await self._fuse_with_timeouts([faiss_t, bm25_t, splade_t])

        # 2) Hydrate & rerank
        ids = [h.doc_id for h in hits[:rerank_top_n]]
        chunks = await self.catalog.query_by_ids(ids, scope.include_globs, scope.exclude_globs, scope.languages)
        ranked = await self._rerank_if_enabled(q, chunks)  # vLLM Score API

        # 3) Build prompt
        prompt = self._build_prompt(q, ranked[:top_k])

        # 4) Stream generation (vLLM chat completions)
        async for event in self._stream_llm(prompt):
            yield event  # SSE/chunk line with token + optional [source_id]
```

(Use vLLM server’s OpenAI‑compat endpoints: Chat Completions, Score API, Structured outputs/Tool calling as needed.) 

---

## G. Readiness & fallbacks (make modes explicit)

* Add **mode** to readiness: `"ready" | "degraded" | "down"`, where:

  * **ready**: FAISS GPU OK (or you decide CPU is “ready” too), DuckDB open, vLLM reachable, dims match.
  * **degraded**: FAISS GPU failed → CPU FAISS only; SPLADE index missing; or reranker disabled.
  * **down**: index missing, dims mismatch, vLLM unreachable.
* `/readyz` returns RFC‑9457‑style detail (you already note Problem Details in docs).
* In `app/main.py`, set a warm start that calls `ApplicationContext.create()`, warms GPU (`gpu_warmup()`), and **pings vLLM** once.

---

## H. Data model & persistence

### Parquet (+DuckDB view) for chunks & embeddings

Keep your Parquet fixed‑size list for embeddings (`float32`, dim = `vec_dim`). Suggested schema (you’re close already in `io/parquet_store.py`):

| column       | type                        | notes                         |
| ------------ | --------------------------- | ----------------------------- |
| `id`         | int64 (stable)              | chunk id                      |
| `uri`        | string                      | repo‑relative                 |
| `start_line` | int32                       | inclusive                     |
| `end_line`   | int32                       | inclusive                     |
| `lang`       | string                      | mapped from extension         |
| `hash`       | string                      | content hash for invalidation |
| `preview`    | string                      | short summary/snippet         |
| `embedding`  | FixedSizeList[F32, vec_dim] | normalized if IP              |

Create a DuckDB **view** `chunks` over these files (or `chunks_materialized` table w/ index on `uri` for LIKE queries). Use `read_parquet('vectors/*.parquet')` with list/glob. Enable object cache for repeated scans. 

### FAISS index manifest

Write `<index>.manifest.json` with:

```json
{
  "version": "2025-11-08",
  "vec_dim": 2560,
  "index_type": "IVFPQ",
  "nlist": 4096,
  "pq_m": 32,
  "metric": "IP",
  "trained_on": "chunks_2025-11-01",
  "gpu_enabled": true,
  "cuvs": "libcuvs-cu13",
  "secondary_size": 12345
}
```

This lets readiness verify and operators reason about performance regimes. (Plan and cuVS/FAISS GPU context.) 

### AnswerTrace (for observability)

Append one row per answer to a local Parquet “traces” dataset:

* ids: `trace_id`, `session_id`
* request: `query`, `scope`, `budgets`
* retrieval: `faiss_ms`, `bm25_ms`, `splade_ms`, `fusion_ms`, `rerank_ms`, top‑k doc IDs
* generation: `model_id`, `temp`, `max_tokens`, `tokens_in`, `tokens_out`, `ttft_ms`, `tps`
* decision: `mode`, `fallbacks_used`
* errors: (if any)
* time: start/end

Traces are invaluable for regressions and **guardrail tuning**.

---

## I. vLLM serving & generation (streaming, structured output, reranking)

* **Where to use vLLM**:

  * Embeddings (`/v1/embeddings`) already used by your client.
  * **Chat Completions** for generation with streaming.
  * **Score API** (or `/classifications`) for reranking/cross‑encoder signals.
  * **Structured outputs** and **tool calling** if your answer tool calls code search/file ops mid‑flow. 

* **Server config**:

  * Start vLLM with **prefix caching** and **chunked prefill** to handle long prompts efficiently; expose **/metrics** for Prometheus and set utilization caps. 
  * Avoid `--async-scheduling` on v0.11.0 due to known issues (until patched). 

* **Client**:

  * Keep your persistent `httpx` client; add exponential backoff on 429/5xx; surface latency/token metrics.

---

## J. Transport: streaming over HTTPS/H2/H3 (origin or edge)

* If you terminate H3 at NGINX (your `config/nginx/codeintel-mcp.conf`), keep Hypercorn on H2. If you want H3 at origin, enable `quic_bind` and **Alt‑Svc** in `app/hypercorn.toml`. Hypercorn supports ALPN for H2 and QUIC for H3, and exposes backpressure semantics that help streaming token output behave well under load. 

---

## K. Caching & stampede control

* **L1**: `functools.lru_cache` for pure, small helpers (path stats, query normalization).
* **Async**: `async_lru` for coalescing concurrent awaits (e.g., reading same chunk lines or same small metadata).
* **L3**: Redis for **multi‑worker coherence** (e.g., `scope`, hot re‑ranking evals, small result sets); set `maxmemory` with LRU/LFU.
* Make cache keys **content‑aware** (e.g., `(resolved_path, st_mtime_ns, size)` for file reads) to avoid stale reads without manual invalidation. 

---

## L. Error handling & Problem Details

* Wrap MCP tool adapters so **all** exceptions become RFC‑9457 Problem Details: `{type, title, status, detail, instance}`. Annotate with `mode=degraded` when falling back (e.g., FAISS CPU). This dovetails with your docs and makes client UX predictable.

---

## M. Testing you should add

* **Concurrency tests** for DuckDB: N parallel calls fetching overlapping ID sets while building views/materializing.
* **RRF tests** with mocked FAISS/BM25/SPLADE lists (including tie‑breakers and missing modalities).
* **FAISS dim mismatch test**: create an index with `d=1024`, but set config `vec_dim=2560` and assert readiness is **false** with a clear message.
* **Answer orchestration e2e** (fakes for retrieval & vLLM) verifying budgets, timeouts, partial results, and progressive citations.
* **Scope round‑trip** across workers/pods (if Redis): set, get, TTL expiry.

---

## Implementation roadmap (8–12 workdays, independent chunks)

1. **Answer orchestrator module** + minimal streaming endpoint (or MCP tool) using FAISS‑only, with tracing.
2. **DuckDB refactor** (connections, object cache, SQL filtering, parameterization) + tests. 
3. **FAISS manager** completion: IDMap2, GPU clone/fallback, secondary index, manifest, compaction task, readiness hooks. 
4. **Embedding contract** & readiness invariants (fail fast on dim mismatch).
5. **BM25 & SPLADE integration**; wire `retrieval/hybrid.py` into orchestrator; parallelism + RRF; doc ID unification.
6. **Reranker**: integrate vLLM Score API; add switch in config; test gains. 
7. **Scope store L2** (Redis) & stickiness guidance; migrate MCP adapters to `get_effective_scope()`. 
8. **Observability**: Prometheus counters/histograms; `/metrics` scraping; AnswerTrace Parquet dataset; a Grafana board with TTFT/tokens‑s/queue depth (mirror vLLM dashboards). 
9. **Transport polish**: H2/H3 decision finalized; if origin H3, implement `quic_bind` & Alt‑Svc or keep H3 at NGINX edge. 

---

## Concrete code changes (surgical diffs)

### 1) `io/duckdb_catalog.py`

* Replace `self.conn` with a **connection manager**:

```python
# Pseudocode
class DuckDBCatalog:
    def _connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(str(self.db_path))
        con.execute("PRAGMA enable_object_cache")
        if self.materialize: self._ensure_materialized(con)
        else: self._ensure_view(con)
        return con

    def query_by_ids(...):
        with self._connect() as con:
            # ALL SQL uses placeholders; LIKE compiled from simple globs
            return con.execute(sql, params).fetch_arrow_table()  # or .fetchall()
```

(Connections per call are cheap for local DuckDB; or keep a small pool. Concurrency rules & object cache confirmed.) 

### 2) `io/faiss_manager.py`

* Finalize:

  * `IndexIDMap2` wrapping primary/secondary.
  * `ensure_ready()` → attempt GPU clone; otherwise CPU; set `gpu_disabled_reason`.
  * Persist `secondary` to disk (`secondary.faiss`); `load_secondary_if_exists()`.
  * `search()` merges primary+secondary results with dedupe by chunk ID.
  * `compact()` merges secondary into primary on threshold; writes manifest. (cuVS/GPU notes.) 

### 3) `mcp_server/adapters/semantic.py`

* Replace direct FAISS lookup with orchestrator call.
* Accept scope from `get_effective_scope(context, session_id)`—already in `scope_utils.py`—but now backed by L2 store when configured.

### 4) `retrieval/hybrid.py`

* Keep `SearchHit`/RRF; add simple adapters for BM25/SPLADE & unify doc IDs to **chunk IDs** (integers).

### 5) `app/readiness.py`

* Add checks:

  * `faiss_ready`: `index.d == config.vec_dim`, `mode`, `gpu_disabled_reason`.
  * `duckdb_ready`: can open connection, can `SELECT count(*) FROM chunks` or `0 if empty`.
  * `vllm_ready`: probe embeddings (or metadata).
* JSON shows `{"mode":"ready|degraded|down","detail":"..."}`.

### 6) `config/settings.py`

* Introduce `EmbeddingsConfig` and move `vec_dim`, `normalize` here. Use it in `parquet_store`, `faiss_manager`, and `vllm_client`.

---

## Why these choices match “best‑in‑class”

* **DuckDB** as your structured “catalog” over Parquet is the right tool; explicitly managing connections and enabling the **object cache** gives you both correctness and speed. 
* **FAISS** dual‑index with **GPU clone** + **secondary incremental** avoids costly retrains while keeping search fresh; cuVS/FAISS GPU acceleration gives strong perf, with a **CPU fallback** path to keep the system available. 
* **vLLM** provides one GPU‑efficient plane for embeddings **and** model features (streaming generation, reranking via **Score API**, structured outputs/tool calling if needed). This reduces moving parts while increasing capability. 
* **Hypercorn** H2/H3 and **Starlette** streaming semantics are a solid base for token streams with backpressure and proper cancellation.  
* **Caching** layered with an L2 (Redis) solves your cross‑worker scope coherence and opens the door to shared memoization without accidental data leakage. 

---

## “Answer‑response” E2E acceptance criteria (copy‑paste for the PR)

* [ ] **Correctness**: identical results across 1 → N workers (scope works); FAISS ID alignment stable; dims match across vLLM/FAISS/Parquet; **no** missing‑scope bugs on multi‑process server.
* [ ] **Coverage**: purely lexical queries (BM25), semantic queries (FAISS), and hybrid queries succeed; RRF + reranker measurably improves top‑5 precision on your sample corpus.
* [ ] **Latency**: retrieval sub‑400ms p95 for medium corpora; TTFT p95 < 800ms on vLLM (model dependent) with streaming tokens.
* [ ] **Degradation**: pull GPU mid‑run → service returns readiness “degraded” and stays up using CPU FAISS; reranker can be switched off cleanly.
* [ ] **Observability**: Prom metrics exported (retrieval ms, ttft, tokens/s, FAISS GPU/CPU mode, reranker gain); AnswerTrace Parquet recorded for 100% of requests.

---

### Sources I relied on for these recommendations

* **DuckDB (Python)**: connections aren’t thread‑safe, use per‑thread connection/cursor; **object_cache** for repeated scans; parameterized SQL; relations → Arrow. 
* **Hypercorn**: HTTP/2/3 config, QUIC bind & Alt‑Svc, streaming/backpressure, multi‑worker config. 
* **LRU caching/Redis**: multi‑worker coherence, async single‑flight, eviction policies. 
* **Starlette**: `StreamingResponse`, Range/file handling, middleware patterns. 
* **vLLM**: embeddings + chat completions + **Score API** + structured outputs, streaming, optimization knobs. 
* **FAISS / cuVS**: GPU acceleration, StandardGpuResources, design motifs for GPU clones and persisted CPU indices. 

---

If you’d like, I can follow up with **ready‑to‑drop code** (a small PR) that:

* Adds `answer/orchestrator.py` with parallel retrieval, RRF, optional vLLM rerank, streaming;
* Refactors `DuckDBCatalog` connection management and adds the pragmas;
* Finishes `FAISSManager` with manifest and compaction;
* Adds Redis‑backed `ScopeStore`;
* Extends readiness & adds a basic Prometheus middleware.

That would give you an immediate, measurable jump in **robustness** and **coverage** and a clean backbone to finish the remaining features you have queued.
