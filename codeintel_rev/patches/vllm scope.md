Below is a **ready‑to‑apply implementation plan** for the vLLM embedding layer—split into P0 (robustness, correctness, observability) and P1 (throughput, ergonomics)—tightly aligned to your current repository structure and coding style. I include **narrative rationale** for each change and **unified diffs** you can paste into a PR.

Where I reference existing symbols/entry points, I cite the files surfaced by your SCIP index so you can cross‑check quickly.

---

## Why these patches fit your repo

* You already call a `VLLMClient` from the semantic adapter and from the bulk indexer (`bin.index_all._embed_chunks`) and pass in a `VLLMConfig` with `base_url`, `model`, and `batch_size`. We extend those pieces without changing their public shape.
* Your `parquet_store` builds a chunks+embeddings Parquet with a FixedSizeList[float32] embedding column; we add table‑level metadata so the embedding model/pooling/normalization are auditably persisted.
* Your MCP semantic adapter already routes embedding → FAISS → DuckDB hydration with good error semantics (`EmbeddingError`, `VectorSearchError`); we wire our client to raise the same class and add timing/health signals.
* Observability plugs into your existing timeline scopes; `/readyz` exists and can advertise vLLM health.

---

# P0 — Robust, predictable embeddings with first‑class observability

### 1) Extend `VLLMConfig` and settings loader

Add explicit timeouts, retries, normalization, pooling, HTTP/2, and an **optional in‑process fallback** (for laptops/offline). We keep your existing env names (URL, MODEL, BATCH_SIZE) and add a few more.

**Patch A — `codeintel_rev/config/settings.py`**

```diff
diff --git a/codeintel_rev/config/settings.py b/codeintel_rev/config/settings.py
@@
 class VLLMConfig(msgspec.Struct, frozen=True):
-    base_url: str = "http://127.0.0.1:8001/v1"
-    model: str = "nomic-ai/nomic-embed-code"
-    batch_size: int = 64
+    # Endpoint & model
+    base_url: str = "http://127.0.0.1:8001/v1"
+    model: str = "nomic-ai/nomic-embed-code"
+    # Throughput
+    batch_size: int = 64
+    http2: bool = True
+    # Robustness
+    timeout_s: float = 30.0
+    max_retries: int = 3
+    retry_backoff_ms: int = 250
+    # Vector post-processing
+    normalize: bool = True
+    pooling_type: str = "mean"  # "mean" | "cls" | vendor-specific
+    # Health & fallback
+    health_path: str = "/models"  # OpenAI/vLLM compatible
+    allow_inprocess_fallback: bool = False
@@
 def load_settings() -> Settings:
     """
     Load settings from environment variables with sensible defaults.
@@
-    vllm = VLLMConfig(
-        base_url=os.getenv("VLLM_URL", "http://127.0.0.1:8001/v1"),
-        model=os.getenv("VLLM_MODEL", "nomic-ai/nomic-embed-code"),
-        batch_size=int(os.getenv("VLLM_BATCH_SIZE", "64")),
-    )
+    vllm = VLLMConfig(
+        base_url=os.getenv("VLLM_URL", "http://127.0.0.1:8001/v1"),
+        model=os.getenv("VLLM_MODEL", "nomic-ai/nomic-embed-code"),
+        batch_size=int(os.getenv("VLLM_BATCH_SIZE", "64")),
+        http2=os.getenv("VLLM_HTTP2", "true").lower() in ("1", "true", "yes"),
+        timeout_s=float(os.getenv("VLLM_TIMEOUT_S", "30")),
+        max_retries=int(os.getenv("VLLM_MAX_RETRIES", "3")),
+        retry_backoff_ms=int(os.getenv("VLLM_RETRY_BACKOFF_MS", "250")),
+        normalize=os.getenv("VLLM_NORMALIZE", "true").lower() in ("1", "true", "yes"),
+        pooling_type=os.getenv("VLLM_POOLING", "mean"),
+        health_path=os.getenv("VLLM_HEALTH_PATH", "/models"),
+        allow_inprocess_fallback=os.getenv("VLLM_ALLOW_INPROCESS_FALLBACK", "false").lower() in ("1","true","yes"),
+    )
 
     return Settings(
         # ...
         vllm=vllm,
     )
```

*Why:* gives us precise operational levers while keeping the default “just works” experience. Your settings loader already documents `VLLM_*` envs; this extends that pattern. 

---

### 2) Harden the HTTP client and add batch embeddings, dedup, ordering, L2 normalize

Upgrade the `VLLMClient` to:

* Reuse a single `httpx.Client` (HTTP/2, pooled), retry idempotently with jitter.
* Accept `list[str]` of texts, dedupe within the batch (hash), **restore order** on return.
* L2 normalize when configured (one source of truth for normalization).
* Provide `health()` and `close()`.

**Patch B — `codeintel_rev/io/vllm_client.py`**

```diff
diff --git a/codeintel_rev/io/vllm_client.py b/codeintel_rev/io/vllm_client.py
@@
-from __future__ import annotations
+from __future__ import annotations
+
+from dataclasses import dataclass
+from typing import Iterable, Sequence
+import math
+import time
+import hashlib
+import logging
+import random
+
+import httpx
+import msgspec
+
+from codeintel_rev.config.settings import VLLMConfig
+from codeintel_rev.typing import NDArrayF32
+from codeintel_rev.io.vllm_engine import InprocessVLLMEmbedder  # fallback
+from codeintel_rev.mcp_server.common.errors import EmbeddingError  # raised by adapters  # noqa: E501
+
+LOGGER = logging.getLogger(__name__)
 
-class VLLMClient:
-    ...
+class _EmbReq(msgspec.Struct):
+    model: str
+    input: list[str]
+    encoding_format: str = "float"
+
+class _EmbData(msgspec.Struct):
+    embedding: list[float]
+    index: int
+
+class _EmbResp(msgspec.Struct):
+    data: list[_EmbData]
+    model: str
+
+@dataclass(slots=True)
+class VLLMClient:
+    config: VLLMConfig
+    _client: httpx.Client | None = None
+    _fallback: InprocessVLLMEmbedder | None = None
+
+    def _initialize_http_client(self) -> None:
+        if self._client is None:
+            self._client = httpx.Client(
+                base_url=self.config.base_url,
+                timeout=self.config.timeout_s,
+                http2=self.config.http2,
+                headers={"accept": "application/json"},
+            )
+
+    def _initialize_local_engine(self) -> None:
+        if self._fallback is None:
+            if self.config.allow_inprocess_fallback:
+                self._fallback = InprocessVLLMEmbedder(self.config)
+                LOGGER.warning("vLLM in-process fallback enabled")
+
+    # ---------- lifecycle ----------
+    def health(self) -> bool:
+        try:
+            self._initialize_http_client()
+            assert self._client is not None
+            r = self._client.get(self.config.health_path)
+            return r.status_code == 200
+        except Exception:
+            return False
+
+    def close(self) -> None:
+        if self._client is not None:
+            self._client.close()
+            self._client = None
+
+    # ---------- embeddings ----------
+    def embed_chunks(self, texts: Sequence[str], *, batch_size: int | None = None) -> NDArrayF32:
+        """
+        Embed a sequence of texts using an OpenAI/vLLM-compatible /v1/embeddings endpoint.
+        Deduplicates within the batch and restores original order on return.
+        """
+        if not texts:
+            import numpy as np
+            return np.empty((0, 0), dtype="float32")
+
+        self._initialize_http_client()
+        self._initialize_local_engine()
+        bsz = batch_size or self.config.batch_size
+
+        # Deduplicate while preserving positions
+        orig_positions: dict[str, list[int]] = {}
+        uniq: list[str] = []
+        for i, t in enumerate(texts):
+            if t not in orig_positions:
+                orig_positions[t] = [i]
+                uniq.append(t)
+            else:
+                orig_positions[t].append(i)
+
+        # Chunk into micro-batches
+        batches = [uniq[i : i + bsz] for i in range(0, len(uniq), bsz)]
+        all_vecs: list[list[float]] = []
+        for batch in batches:
+            vecs = self._embed_batch_http(batch)
+            # Fallback path (local) if remote fails, and allowed
+            if vecs is None and self._fallback is not None:
+                LOGGER.warning("Remote vLLM failed for batch; using in-process fallback")
+                vecs = self._fallback.embed_batch(batch)
+            if vecs is None:
+                raise EmbeddingError("Embedding service unavailable", context={"size": len(batch)})
+            all_vecs.extend(vecs)
+
+        # Map back to original order
+        # Build a map text->first index in uniq
+        pos_map: dict[str, int] = {t: i for i, t in enumerate(uniq)}
+        import numpy as np
+        dim = len(all_vecs[0]) if all_vecs else 0
+        out = np.empty((len(texts), dim), dtype="float32")
+        for t, positions in orig_positions.items():
+            v = all_vecs[pos_map[t]]
+            if self.config.normalize:
+                n = math.sqrt(sum(x * x for x in v)) or 1.0
+                v = [x / n for x in v]
+            for p in positions:
+                out[p] = v
+        return out
+
+    def _embed_batch_http(self, batch: list[str]) -> list[list[float]] | None:
+        """
+        Single HTTP call with simple bounded retries + jitter. Returns None on final failure.
+        """
+        self._initialize_http_client()
+        assert self._client is not None
+        payload = _EmbReq(model=self.config.model, input=batch)
+        data = msgspec.json.encode(payload)
+        url = "/embeddings"
+        attempt = 0
+        while True:
+            try:
+                resp = self._client.post(url, content=data)
+                if resp.status_code == 200:
+                    decoded = msgspec.json.decode(resp.content, type=_EmbResp)
+                    # Sort by index (OpenAI spec preserves order)
+                    decoded.data.sort(key=lambda d: d.index)
+                    return [d.embedding for d in decoded.data]
+                # Unrecoverable 4xx
+                if 400 <= resp.status_code < 500 and resp.status_code != 429:
+                    LOGGER.error("Embedding 4xx: %s %s", resp.status_code, resp.text[:256])
+                    return None
+            except Exception as e:
+                LOGGER.warning("Embedding batch failed: %s", e)
+
+            attempt += 1
+            if attempt > self.config.max_retries:
+                return None
+            # jittered backoff
+            delay = (self.config.retry_backoff_ms / 1000.0) * (2 ** (attempt - 1))
+            time.sleep(delay * (0.8 + 0.4 * random.random()))
```

*Why:* `embed_chunks()` is the single source of truth for batch ordering, retry, and normalization; the MCP adapter can continue to call `_embed_query_or_raise()` unchanged. Your adapters already expect `EmbeddingError` on failure. 

---

### 3) Persist embedding provenance in Parquet

Add table‑level metadata so you can **time‑travel issues** to concrete vectors: `{model, pooling, normalize, created_at}`. No column renames.

**Patch C — `codeintel_rev/io/parquet_store.py`**

```diff
diff --git a/codeintel_rev/io/parquet_store.py b/codeintel_rev/io/parquet_store.py
@@
-@dataclass(slots=True, frozen=True)
-class ParquetWriteOptions:
-    start_id: int
-    vec_dim: int
-    preview_max_chars: int = 480
+@dataclass(slots=True, frozen=True)
+class ParquetWriteOptions:
+    start_id: int
+    vec_dim: int
+    preview_max_chars: int = 480
+    table_meta: dict[str, str] | None = None
@@
 def write_chunks_parquet(
     output_path: Path,
     chunks: Sequence[Chunk],
     embeddings: NDArrayF32,
     options: ParquetWriteOptions,
 ) -> Path:
@@
-    table = pa.Table.from_arrays(arrays, schema=schema)
+    table = pa.Table.from_arrays(arrays, schema=schema)
+    # Attach model/pooling/normalize metadata if present
+    if options.table_meta:
+        meta_existing = table.schema.metadata or {}
+        combined = {**{k.decode(): v.decode() for k, v in meta_existing.items()}, **options.table_meta}
+        table = table.replace_schema_metadata({k.encode(): v.encode() for k, v in combined.items()})
@@
-    pq.write_table(table, output_path, compression="zstd", use_dictionary=True)
+    pq.write_table(table, output_path, compression="zstd", use_dictionary=True)
     return output_path
```

*Why:* You already construct the Arrow schema and write with `pyarrow.parquet.write_table`; this augments the table metadata without schema churn. 

---

### 4) Bulk indexer: use the client’s normalization, log vec dim, and persist metadata

Wire `bin.index_all._embed_chunks()` to pass through config batch size and write Parquet with the new `table_meta`. (You already call `VLLMClient.embed_chunks` and `_write_parquet` here.) 

**Patch D — `codeintel_rev/bin/index_all.py` (only the embedding & write parts)**

```diff
diff --git a/codeintel_rev/bin/index_all.py b/codeintel_rev/bin/index_all.py
@@ def _embed_chunks(chunks: Sequence[Chunk], config: VLLMConfig) -> NDArrayF32:
-    client = VLLMClient(config)
-    texts = [c.text[:EMBED_PREVIEW_CHARS] for c in chunks]
-    vecs: NDArrayF32 = client.embed_chunks(texts, batch_size=config.batch_size)
-    logger.info("embedded %d chunks at dim=%d", len(chunks), vecs.shape[1])
-    return vecs
+    client = VLLMClient(config)
+    texts = [c.text[:EMBED_PREVIEW_CHARS] for c in chunks]
+    vecs: NDArrayF32 = client.embed_chunks(texts, batch_size=config.batch_size)
+    dim = 0 if vecs.size == 0 else vecs.shape[1]
+    logger.info("embedded %d chunks | dim=%d | model=%s | normalize=%s | pooling=%s",
+                len(chunks), dim, config.model, config.normalize, config.pooling_type)
+    return vecs
@@ def _write_parquet(chunks: Sequence[Chunk], embeddings: NDArrayF32, paths: PipelinePaths, vec_dim: int, preview_max_chars: int) -> Path:
-    return write_chunks_parquet(
+    from time import time as _now
+    return write_chunks_parquet(
         output_path=paths.embeddings_parquet,
         chunks=chunks,
         embeddings=embeddings,
-        options=ParquetWriteOptions(start_id=0, vec_dim=vec_dim, preview_max_chars=preview_max_chars),
+        options=ParquetWriteOptions(
+            start_id=0,
+            vec_dim=vec_dim,
+            preview_max_chars=preview_max_chars,
+            table_meta={
+                "embedding_model": context.settings.vllm.model if hasattr(context, "settings") else "unknown",
+                "pooling_type": context.settings.vllm.pooling_type if hasattr(context, "settings") else "mean",
+                "normalize": str(context.settings.vllm.normalize if hasattr(context, "settings") else True).lower(),
+                "created_at_unix": str(int(_now())),
+            },
+        ),
     )
```

*Why:* preserves current flow while adding the audit trail. Your indexer already documents vec dim and flows naturally into FAISS index building. 

---

### 5) Readiness: include vLLM liveness in `/readyz`

Your app has an HTTP readiness path; advertise whether embeddings are reachable. 

**Patch E — `codeintel_rev/app/main.py` (or where readiness is implemented)**

```diff
diff --git a/codeintel_rev/app/main.py b/codeintel_rev/app/main.py
@@ async def readyz():
-    return {"status": "ok", "faiss": faiss_ok, "duckdb": duckdb_ok}
+    vllm_ok = context.vllm_client.health()
+    return {"status": "ok", "faiss": faiss_ok, "duckdb": duckdb_ok, "vllm": vllm_ok}
```

---

### 6) Adapters: keep `_embed_query_or_raise` unchanged but ensure URL is passed

Your adapter already forms `_embed_query_or_raise(client, query, observation, vllm_url)`. No signature change required; we only ensure the URL is taken from `settings`. 

> *No code change necessary unless you want to log the model too.*

---

# P1 — Throughput & Developer Ergonomics

### 7) Micro‑batch aggregator (optional utility)

Where you have high concurrency (CLI bulk indexing, not interactive MCP), a tiny collector keeps GPU/engine saturated and dedups transiently across coroutines.

**Patch F — `codeintel_rev/io/embedding_batcher.py` (new)**

```diff
diff --git a/codeintel_rev/io/embedding_batcher.py b/codeintel_rev/io/embedding_batcher.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/io/embedding_batcher.py
+from __future__ import annotations
+import asyncio
+from dataclasses import dataclass
+from typing import Awaitable, Callable, Iterable, Sequence
+
+from codeintel_rev.typing import NDArrayF32
+
+EmbedFn = Callable[[Sequence[str]], Awaitable[NDArrayF32]]
+
+@dataclass(slots=True)
+class MicroBatcher:
+    """Collect requests for a short window and flush as one batch."""
+    batch_size: int
+    max_wait_ms: int = 8
+
+    def __post_init__(self) -> None:
+        self._queue: asyncio.Queue[tuple[list[str], asyncio.Future[NDArrayF32]]] = asyncio.Queue()
+        self._task: asyncio.Task[None] | None = None
+
+    async def start(self, emit: Callable[[Sequence[str]], Awaitable[NDArrayF32]]) -> None:
+        assert self._task is None
+        self._task = asyncio.create_task(self._run(emit))
+
+    async def stop(self) -> None:
+        if self._task:
+            self._task.cancel()
+            with contextlib.suppress(asyncio.CancelledError):
+                await self._task
+            self._task = None
+
+    async def submit(self, texts: list[str]) -> NDArrayF32:
+        fut: asyncio.Future[NDArrayF32] = asyncio.get_running_loop().create_future()
+        await self._queue.put((texts, fut))
+        return await fut
+
+    async def _run(self, emit: Callable[[Sequence[str]], Awaitable[NDArrayF32]]) -> None:
+        import time
+        while True:
+            bucket: list[str] = []
+            futures: list[asyncio.Future[NDArrayF32]] = []
+            start = time.perf_counter()
+            # Pull at least one
+            texts, fut = await self._queue.get()
+            bucket.extend(texts)
+            futures.append(fut)
+            # Fill until size or small window elapsed
+            while len(bucket) < self.batch_size:
+                try:
+                    timeout = max(0.0, self.max_wait_ms / 1000.0 - (time.perf_counter() - start))
+                    texts2, fut2 = await asyncio.wait_for(self._queue.get(), timeout=timeout)
+                    bucket.extend(texts2)
+                    futures.append(fut2)
+                except asyncio.TimeoutError:
+                    break
+            vecs = await emit(bucket[: self.batch_size])
+            for f in futures:
+                f.set_result(vecs)
```

*Why:* optional helper for heavy ingest. The synchronous `index_all` path can continue using `client.embed_chunks()` directly for simplicity. The MCP server can avoid it (your P0 priority was correctness & transparency).

---

### 8) In‑process engine alignment

You already have `InprocessVLLMEmbedder` with `embed_batch`. Ensure it honors `pooling_type` and `normalize` in `VLLMConfig`. 

**Patch G — `codeintel_rev/io/vllm_engine.py`**

```diff
diff --git a/codeintel_rev/io/vllm_engine.py b/codeintel_rev/io/vllm_engine.py
@@ class InprocessVLLMEmbedder:
-    def embed_batch(self, texts: list[str]) -> list[list[float]]:
-        # existing inference code ...
-        vecs = self._engine.embed(texts, pooling=self.config.pooling_type)
-        if self.config.normalize:
-            # L2 normalize
-            for i, v in enumerate(vecs):
-                n = sum(x*x for x in v) ** 0.5 or 1.0
-                vecs[i] = [x/n for x in v]
-        return vecs
+    def embed_batch(self, texts: list[str]) -> list[list[float]]:
+        vecs = self._engine.embed(texts, pooling=self.config.pooling_type)  # type: ignore[attr-defined]
+        if self.config.normalize:
+            for i, v in enumerate(vecs):
+                n = sum(x * x for x in v) ** 0.5 or 1.0
+                vecs[i] = [x / n for x in v]
+        return vecs
```

---

### 9) Tests (stubs you can extend)

* `tests/io/test_vllm_client.py` — success path, 4xx path, retry path, normalization on/off.
* `tests/io/test_parquet_meta.py` — write/read and assert table metadata.
* `tests/bin/test_index_all_embed.py` — smoke test `_embed_chunks` returns aligned dims.

**Patch H — new tests (stubs)**

```diff
diff --git a/tests/io/test_vllm_client.py b/tests/io/test_vllm_client.py
new file mode 100644
--- /dev/null
+++ b/tests/io/test_vllm_client.py
+from __future__ import annotations
+import types
+import numpy as np
+import httpx
+from codeintel_rev.io.vllm_client import VLLMClient, _EmbResp, _EmbData
+from codeintel_rev.config.settings import VLLMConfig
+
+class _MockClient(httpx.Client):
+    def __init__(self, payload: dict[str, object]):
+        super().__init__(base_url="http://test")
+        self._payload = payload
+    def post(self, url: str, content: bytes):  # type: ignore[override]
+        return httpx.Response(200, json=self._payload)
+
+def test_embed_chunks_ok(monkeypatch):
+    cfg = VLLMConfig()
+    c = VLLMClient(cfg)
+    resp = {"data": [{"embedding": [1.0, 0.0], "index": 0}], "model": cfg.model}
+    c._client = _MockClient(resp)
+    out = c.embed_chunks(["hello"])
+    assert out.shape == (1, 2)
+    assert np.isfinite(out).all()
```

```diff
diff --git a/tests/io/test_parquet_meta.py b/tests/io/test_parquet_meta.py
new file mode 100644
--- /dev/null
+++ b/tests/io/test_parquet_meta.py
+from __future__ import annotations
+from pathlib import Path
+import pyarrow.parquet as pq
+from codeintel_rev.io.parquet_store import ParquetWriteOptions, write_chunks_parquet
+from codeintel_rev.indexing.cast_chunker import Chunk
+import numpy as np
+
+def test_metadata_roundtrip(tmp_path: Path):
+    chunks = [Chunk(uri="a.py", start_byte=0, end_byte=1, start_line=0, end_line=0,
+                    text="x", symbols=(), language="python")]
+    emb = np.array([[0.0, 1.0]], dtype="float32")
+    meta = {"embedding_model": "nomic-ai/nomic-embed-code", "normalize": "true"}
+    p = tmp_path/"emb.parquet"
+    write_chunks_parquet(p, chunks, emb, ParquetWriteOptions(start_id=0, vec_dim=2, table_meta=meta))
+    schema_meta = pq.read_table(p).schema.metadata
+    assert schema_meta is not None and schema_meta.get(b"embedding_model") == b"nomic-ai/nomic-embed-code"
```

---

# Integration touch‑points (no breaking changes)

* **Semantic MCP** already calls `_embed_query_or_raise` → `VLLMClient`; no signature changes. Your adapter composes FAISS and hydration with clear error surfaces.
* **Hybrid engine / evaluators** remain unchanged. They will benefit from stable, normalized vectors and Parquet provenance. 
* **Settings**: defaults match current behavior; new envs are optional.

---

# Operational guidance

* **Readiness:** `/readyz` now includes `"vllm": true/false` so you can diagnose embedding outages quickly. 
* **Parquet provenance:** when someone changes the embedding model/pooling/normalization, the Parquet metadata documents it; FAISS rebuilds should read the same manifest and store the factory string (already part of your lifecycle narrative).
* **Fallback mode:** Set `VLLM_ALLOW_INPROCESS_FALLBACK=true` for offline laptops; batch sizes of 16–32 are typical locally.

---

# Appendix — Where this connects in your code (quick x‑refs)

* The MCP adapter already wires `VLLMClient` via application context and takes `vllm_url` from settings. This is where `_embed_query_or_raise` lives. 
* Bulk embedding is done in `bin.index_all._embed_chunks()` and `_write_parquet()`. We touched only those two spots. 
* Table/schema writes use `pyarrow.parquet.write_table` in `io/parquet_store.py`. We only add schema metadata. 
* For future late‑interaction/oracle work, your XTR utilities and CLI are already in place. 

---

## Optional (nice to have, small)

* **Expose model/provenance in the MCP response `extras`:** trivial addition to your adapter’s envelope if you want it surfaced to clients (see `AnswerEnvelope` scaffolding). 
* **CLI check:** add `indexctl readyz` to print FAISS/DuckDB/vLLM triage matrix (you already have Typer‑based CLIs elsewhere). 

---

### What I did **not** change

* FAISS building, hybrid gating, or rerank flows—your current adapters and engines retain their contracts. The goal here is to make embeddings **predictable, auditable, and resilient** while keeping your surface area stable. 

---

If you want, I can follow up with a small **OpenAPI snippet** for `/v1/embeddings` (OpenAI‑compatible) and a test harness that spins up a mock httpx server to exercise retries/jitter.
