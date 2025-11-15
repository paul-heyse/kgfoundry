Absolutely—here’s the end‑to‑end, **vLLM + `nomic-ai/nomic-embed-code`** specific test plan and the exact repo functions that will be exercised at each step. I’ve split this into:

1. how to run vLLM against your *locally cached* embedding model,
2. the precise function sequence (chunk → DuckDB → embed → FAISS upsert) that already exists in the repo, and
3. a concrete test sequence (commands + quick checks) to prove each stage worked.

---

## 0) Start vLLM with your local HF cache (one-time service)

You already have the model at:

```
/home/paul/.cache/huggingface/hub/models--nomic-ai--nomic-embed-code
```

The most reliable way to make vLLM reuse this cache is to point it at the **HF cache root** (not the model leaf folder). Two equivalent options:

**Option A: use `HF_HOME`**

```bash
export HF_HOME=/home/paul/.cache/huggingface

python -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 --port 8001 \
  --model nomic-ai/nomic-embed-code \
  --task embed \
  --trust-remote-code \
  --dtype auto
```

**Option B: use `--download-dir`**

```bash
python -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 --port 8001 \
  --model nomic-ai/nomic-embed-code \
  --task embed \
  --download-dir /home/paul/.cache/huggingface \
  --trust-remote-code \
  --dtype auto
```

**Smoke test (dimension should be 3584 for `nomic-embed-code`)**

```bash
curl -s http://127.0.0.1:8001/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"nomic-ai/nomic-embed-code","input":["hello world"]}' \
| jq '.data[0].embedding | length'
# expect: 3584
```

On the KG Foundry side, the embedding client uses the `base_url` and `model` you configure in settings and then posts to the OpenAI‑compatible `/v1/embeddings` endpoint; the code path is `VLLMClient._embed_batch_http()` and it assembles `EmbeddingRequest(model=..., input=...)`. You can see that in the repo’s vLLM client and settings docs, including the example shape (“e.g., 3584”). 

---

## 1) Precise function sequence used by the repo

Below is the exact order of **existing** functions that implement chunking → DuckDB registration → embedding (via vLLM) → FAISS upsert/build.

### A. Load SCIP and **chunk** the repo

1. **Parse SCIP**
   `parse_scip_json(paths.scip_index)` loads `index.scip.json` and prepares documents/symbols. 

2. **Group definitions by file**
   `_group_definitions_by_file(scip)` organizes symbol definitions so they can be chunked per file. (Called by the pipeline helper in `bin.index_all`.) 

3. **Chunk each file**
   `cast_chunker.chunk_file(path, text, defs, options)` with `ChunkOptions(budget=..., language=...)` produces `Chunk` objects (text spans with metadata). 

4. **Write chunk parquet (and register views)**
   `_write_parquet(chunks, embeddings=None, ...)` wraps `io.parquet_store.write_chunks_parquet(...)` with `ParquetWriteOptions` (id strategy, preview chars, vec_dim, etc.). 

   The DuckDB catalog then **installs/refreshes** the parquet‑backed SQL views (modules, SCIP occurrences, AST/CST, chunk symbols) using:
   `DuckDBCatalog.ensure_struct_views()` → `_install_parquet_view(...)` / `_install_chunk_symbols_view(...)` / `_materialize_if_changed(...)` / `_file_checksum(...)`.

   For quick introspection later you also have lightweight helpers such as `DuckDBCatalog.count_chunks()` and `DuckDBCatalog.get_embeddings_by_ids(...)`. 

### B. **Embed** chunk texts with **vLLM** and persist embeddings

5. **Batch embeddings via vLLM**
   `VLLMClient._embed_batch_http(...)` creates `EmbeddingRequest(model=settings.vllm.model, input=[...])` and POSTs to `/v1/embeddings`; it returns a float32 matrix (e.g., 3584‑dim) aligned to the requested inputs. 

6. **Append embeddings to parquet**
   The pipeline reuses `_write_parquet(..., embeddings=...)` so the embeddings are written to the vectors area alongside chunks; DuckDB views remain consistent. 

### C. **Upsert / Build** the FAISS index

You have two code paths already implemented:

* **Cold build (train from scratch)** – `_build_faiss_index(embeddings, paths, index_config)` chooses a FAISS family adaptively, trains, and persists:

  * Constructs `FAISSManager(index_path=paths.faiss_index, vec_dim=index_config.vec_dim, nlist=..., use_cuvs=..., runtime=...)` 
  * `FAISSManager.build_index(embeddings_subset)` builds/trains the index, then
  * `FAISSManager.add_vectors(ids, embeddings)` upserts all vectors (IDs match chunk IDs), and
  * `FAISSManager.save_cpu_index()` writes the primary `.faiss` file to disk.

* **Incremental upsert** – `_update_faiss_index_incremental(chunks, embeddings, paths, index_config)` loads the existing index and adds only **new** chunk IDs via the **secondary** (FlatIP + IDMap2) side‑index; internally this calls `FAISSManager.update_index(...)` and maintains a dual‑index search path for immediacy. 

FAISS plumbing (selected excerpts in your codebase):

* `FAISSManager.build_index()` (factory choice, adaptive family, training limit)
* `FAISSManager.add_vectors(vectors, ids)` (IDs must be `int64` and align with chunk IDs) 
* `FAISSManager.save_cpu_index()` / `load_cpu_index(export_idmap=..., profile_path=...)` / `save_secondary_index()` for persistence and export.
* Secondary index creation and duplicate filtering helpers are encapsulated (`_ensure_secondary_index`, `_build_primary_contains`, etc.). 

Finally, when you want a **DuckDB materialized join** that brings FAISS ID maps into SQL, use:

* `DuckDBCatalog.materialize_faiss_join()` and
* `refresh_faiss_idmap_materialized(idmap_parquet)` to (re)materialize the FAISS idmap parquet into the catalog.

---

## 2) Minimal, vLLM‑specific **test sequence** (commands)

### Step 1 — Environment for embeddings (make KG Foundry talk to vLLM)

The repo’s settings loader reads **environment variables**; vLLM fields include `VLLM_URL`, `VLLM_MODEL`, `VLLM_EMBED_DIM`, etc. (see `load_settings()` doc). 

```bash
# run this in the repo root (where codeintel_rev/ lives)
export EMBEDDINGS_PROVIDER=vllm
export VLLM_URL=http://127.0.0.1:8001/v1
export VLLM_MODEL=nomic-ai/nomic-embed-code
export VLLM_EMBED_DIM=3584          # matches nomic-embed-code
# (optional)
export VLLM_BATCH_SIZE=64
export VLLM_TIMEOUT_SECONDS=60
```

> Why this is sufficient: the client constructs `EmbeddingRequest(model=VLLM_MODEL, ...)` and posts to `VLLM_URL`’s `/v1/embeddings` route, returning (n, 3584) vectors when using `nomic-embed-code`. 

### Step 2 — One‑shot: run the pipeline (SCIP → chunks → embeddings → FAISS)

If your SCIP JSON is already under the default `ENRICHED/ast` folder (as you stated), the built‑in orchestrator can run E2E using repo settings/paths:

```bash
python -m codeintel_rev.bin.index_all
```

What this does internally:

* `parse_scip_json(...)` → `_group_definitions_by_file(...)` → `cast_chunker.chunk_file(...)` to create `Chunk` objects.
* `_write_parquet(..., embeddings=None)` to persist chunks & install DuckDB views.
* `VLLMClient._embed_batch_http(...)` to embed chunk texts (delegates to vLLM `/v1/embeddings`). 
* `_write_parquet(..., embeddings=...)` to persist vectors. 
* `_build_faiss_index(...)` (or `_update_faiss_index_incremental(...)` if configured) to build/upsert the FAISS index and save it.

### Step 3 — Stage‑by‑stage (if you prefer explicit checkpoints)

If you want to validate each stage individually, the repo’s Typer CLI exposes fastening points:

**(a) Build embeddings only (uses vLLM provider from env):**

```bash
python -m codeintel_rev.cli.indexctl embeddings build
```

This fetches chunk texts from DuckDB views, batches them through `VLLMClient`, then writes/updates embeddings parquet. You can also run a quick *dimension/shape* check:

```bash
python -m codeintel_rev.cli.indexctl embeddings validate
# verifies count and vec_dim (should report 3584)
```

(The embeddings CLI calls through the same client/config; see the validate/build command docs.) 

**(b) Materialize join (optional, for SQL‑side inspection/debugging):**

```bash
python -m codeintel_rev.cli.indexctl materialize-join
```

This uses the catalog helpers to ensure the FAISS ID map parquet is materialized and joined.

**(c) Build / update FAISS**

* For a **fresh build**, the easiest route remains:

  ```bash
  python -m codeintel_rev.bin.index_all
  ```

  which runs `_build_faiss_index(...)` and saves the index. 

* For **incremental upsert**, re‑run the pipeline with new chunks; it will call `_update_faiss_index_incremental(...)` which leverages `FAISSManager.update_index(...)` (secondary index append) and `save_secondary_index()` to persist. 

---

## 3) “Did it work?” — quick, scriptable checks

**A. DuckDB: chunk count sanity**

```bash
python - <<'PY'
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.config.settings import load_settings
from codeintel_rev.app.config_context import ApplicationContext

s = load_settings()
ctx = ApplicationContext.create(s)
cat = DuckDBCatalog(ctx.paths.duckdb_path)
print("chunks:", cat.count_chunks())
PY
```

(Uses the catalog’s `count_chunks()` helper.) 

**B. Embedding dimension check from DuckDB parquet**

```bash
python - <<'PY'
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.config.settings import load_settings
from codeintel_rev.app.config_context import ApplicationContext

s = load_settings()
ctx = ApplicationContext.create(s)
cat = DuckDBCatalog(ctx.paths.duckdb_path)
ids, vecs = cat.get_embeddings_by_ids([0,1,2,3,4])
print("returned:", len(ids), "vec_dim:", (vecs.shape[1] if vecs.size else None))
PY
```

(`get_embeddings_by_ids` returns `(ids, vectors)` with `dtype=float32`, so you should see `vec_dim=3584`.) 

**C. FAISS file persisted**
You should see the index file saved by `FAISSManager.save_cpu_index()` at your configured `paths.faiss_index`. 

---

## Notes on where each piece lives in your repo

* **SCIP → chunks:** `parse_scip_json(...)`, `_group_definitions_by_file(...)`, `cast_chunker.chunk_file(...)` (chunking and options)
* **Parquet + DuckDB:** `_write_parquet(...)` → `io.parquet_store.write_chunks_parquet(...)`; `DuckDBCatalog.ensure_struct_views()` and friends manage the Parquet‑backed views & materialization.
* **Embeddings (vLLM):** `VLLMClient._embed_batch_http(...)` posts `EmbeddingRequest(model=..., input=...)` to `VLLM_URL`; vectors are “e.g., 3584” dims for `nomic-embed-code`. 
* **FAISS:** `_build_faiss_index(...)` (cold build) → `FAISSManager.build_index()` → `FAISSManager.add_vectors()` → `FAISSManager.save_cpu_index()`; `_update_faiss_index_incremental(...)` for dual‑index upserts.
* **Joins/materialization:** `DuckDBCatalog.materialize_faiss_join()` / `refresh_faiss_idmap_materialized(...)`. 

---

### TL;DR

* **Start vLLM** with `--model nomic-ai/nomic-embed-code` and point to your HF cache root (`HF_HOME` or `--download-dir`).
* **Point KG Foundry at vLLM** via `EMBEDDINGS_PROVIDER=vllm`, `VLLM_URL`, `VLLM_MODEL`, `VLLM_EMBED_DIM=3584`. 
* **Run** `python -m codeintel_rev.bin.index_all` for a one‑shot SCIP→chunks→DuckDB→embeddings(vLLM)→FAISS pipeline. (All functions listed above are already in the repo and wired together.)
* **Verify** with the small checks above (DuckDB counts, embedding dims, FAISS file presence).

If you want, I can also generate a tiny “smoke.py” that runs just the embedding path end‑to‑end against vLLM and prints the first vector’s norm to confirm non‑zero signal.
