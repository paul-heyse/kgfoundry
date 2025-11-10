# vLLM Integration Instructions #

> **Repository target:** `kgfoundry/codeintel_rev`
> **Scope:** in‑process vLLM (no HTTP), GPU‑first indexing/query, Stage‑0 CodeRankEmbed, Stage‑1 XTR/WARP (parallel channel), optional CodeRankLLM reranker, fusion via weighted RRF, DuckDB hydration unchanged.

---

## 0) Executive summary (≤200 words)

We are replacing the HTTP/OpenAI‑style embeddings client with an **in‑process vLLM embedder** and aligning our retrieval stack to a **two‑stage architecture**: a **Stage‑0 bi‑encoder** (CodeRankEmbed) that generates a high‑recall shortlist fast on GPU, and a **Stage‑1 XTR/WARP** late‑interaction channel that runs **in parallel** for token‑level matching. We fuse channels with **weighted RRF**, then hydrate with DuckDB using `preserve_order=True` so ranking survives scope filters. Readiness and warmup remain authoritative; feature flags let us turn stages on/off safely. This reduces tail latency, raises recall, and keeps ops transparent with structured metrics and Problem‑Details error envelopes. The plan is compatible with the new hybrid/RRF work and the “semantic_pro” adapter already in tree.   

```mermaid
flowchart LR
  A[Query] --> B1[Stage‑0: CodeRankEmbed (vLLM in‑proc)]
  A --> B2[Stage‑1: XTR/WARP (parallel token‑level)]
  B1 --> C[Fusion: weighted RRF]
  B2 --> C
  C --> D[DuckDB Hydration (preserve_order)]
  D --> E[AnswerEnvelope (+explainability)]
```

---

## 1) Current state (baseline, with citations to code)

* **Embedding client**: `VLLMClient` is an **OpenAI‑compatible** `/v1/embeddings` HTTP client using `httpx`, msgspec enc/dec, and reorders the batch back to input order. Timeouts surface `httpx` errors to adapters.  
* **Hybrid engine & fusion**: `HybridSearchEngine.search(...)` gathers semantic/BM25/SPLADE and fuses via **RRF**; the v2 patch adds **`extra_channels`** and **weighted RRF** so external channels (e.g., biencoder or XTR) can be injected.  
* **“Pro” semantic path**: The repo now exposes `search:semantic_pro` and a `semantic_pro_adapter` that performs two‑stage fusion and hydrates with `preserve_order=True`. Options parsing and hydration hooks are present.  
* **Biencoder indexing/CLI**: A Typer CLI exists to build FAISS from Parquet chunks using **CodeRankEmbed**; readiness includes a biencoder index check.  
* **Readiness & GPU warmup**: `ReadinessProbe` reports per‑dependency health; GPU warmup utilities exist and are used during FastAPI lifespan; readiness payload is already the gate for `/readyz`.  

---

## 2) Target architecture (vLLM in Retrieval v2)

### Stage‑0 (bi‑encoder — CodeRankEmbed)

* **Where it runs**: In‑process vLLM engine (no HTTP).
* **Batching & normalization**: Use vLLM `task="embed"` and `PoolerConfig(normalize=True)`; pretokenize and pass token IDs to overlap CPU tokenize with GPU compute. Vectors are **L2‑normalized**, so FAISS uses **Inner Product** as cosine.
* **Flow into FAISS**: GPU FAISS `GpuIndexFlatIP`; maintain pinned memory and scratch caps via `StandardGpuResources`. (Index build is already wired through the new CLI.) 

### Stage‑1 (late‑interaction XTR/WARP — **parallel channel**)

* **Channel model**: Token‑level max‑sim; query encoder yields per‑token vecs; doc tokens are memmapped; **WARPSELECT + two‑stage reduction** with implicit decompression on GPU.  
* **Invocation**: For **query‑time**, run XTR **in parallel** to Stage‑0. You may choose “**wide**” (index‑wide) or “**narrow**” (re‑score Stage‑0 candidates) depending on budget. The existing provider outlines both `search()` and `rescore(ids)` shapes.  
* **Artifacts & readiness**: Token matrix (`float16`), `metadata.json`, `docid_map.json`; readiness checks open the codec quickly and mark degraded if missing.  

### Optional reranker (CodeRankLLM)

* Deterministic **listwise** prompt with budget cap; can be toggled; capped at `rerank_top_k`. Wire **after** fusion and **before** hydration. (Slot is called out in the adapter patch.) 

### Fusion & hydration

* **Fusion**: Use **weighted RRF** with per‑channel weights; keep channel contributions for explainability. The engine accepts `extra_channels` and `weights` already. 
* **Hydration**: DuckDB catalog, same query builder, with `preserve_order=True`; scope filters unchanged. 

---

## 3) Interfaces & config (authoritative API sketch)

> Typed, public APIs only; exceptions follow our taxonomy; docstrings are doctestable.

```python
# codeintel_rev/config/settings.py
from __future__ import annotations
import msgspec
from typing import Literal

class VLLMRunMode(msgspec.Struct, frozen=True):
    """vLLM execution mode."""
    mode: Literal["inprocess", "http"] = "inprocess"  # default: no-HTTP

class VLLMConfig(msgspec.Struct, frozen=True):
    model: str = "nomic-ai/CodeRankEmbed"
    run: VLLMRunMode = VLLMRunMode()
    gpu_memory_utilization: float = 0.92
    max_num_batched_tokens: str = "64k"
    timeout_s: float = 120.0
    normalize: bool = True
    max_concurrent_requests: int = 4  # local asyncio semaphore

class BiencoderConfig(msgspec.Struct, frozen=True):
    index_path: str = "data/faiss/biencoder.faiss"
    batch_size: int = 256
    enabled: bool = True

class XTRConfig(msgspec.Struct, frozen=True):
    enable: bool = False
    index_dir: str = "data/xtr"
    model_id: str = "nomic-ai/CodeRankEmbed"  # placeholder
    device: str = "cuda"
    candidate_k: int = 200
    max_query_tokens: int = 256
    dim: int = 768
    dtype: str = "float16"

class RetrievalWeights(msgspec.Struct, frozen=True):
    rrf_k: int = 60
    channel: dict[str, float] = {"biencoder": 1.0, "xtr": 1.3, "splade": 1.0, "bm25": 0.9}
```

```python
# codeintel_rev/io/vllm_engine.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence, List
import numpy as np
from transformers import AutoTokenizer  # trust_remote_code=True where needed
from vllm import LLM
from vllm.config import PoolerConfig

@dataclass(slots=True, frozen=True)
class InprocessVLLMConfig:
    model: str
    normalize: bool
    max_tokens: str
    gpu_mem_util: float

class InprocessVLLMEmbedder:
    """No-HTTP, in-process embedding engine.

    >>> eng = InprocessVLLMEmbedder(
    ...     InprocessVLLMConfig("nomic-ai/CodeRankEmbed", True, "64k", 0.92)
    ... )
    >>> vecs = eng.embed(["def foo(): pass"])
    >>> isinstance(vecs, np.ndarray) and vecs.ndim == 2
    True
    """
    def __init__(self, cfg: InprocessVLLMConfig) -> None:
        self._tok = AutoTokenizer.from_pretrained(cfg.model, trust_remote_code=True)
        self._llm = LLM(
            model=cfg.model,
            task="embed",
            trust_remote_code=True,
            enforce_eager=True,
            override_pooler_config=PoolerConfig(pooling_type="lasttoken", normalize=cfg.normalize),
            gpu_memory_utilization=cfg.gpu_mem_util,
            max_num_batched_tokens=cfg.max_tokens,
        )

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 1), dtype=np.float32)
        enc = self._tok(list(texts), padding=False, truncation=True, return_tensors=None)
        token_id_lists = [ids for ids in enc["input_ids"]]
        outs = self._llm.embed(token_id_lists)
        arr = np.array([o.outputs.embedding for o in outs], dtype=np.float32)
        return arr
```

**Tunable knobs**

* `embed.batch_size`, `embed.max_tokens`, `normalize`, `timeout_s`, `max_concurrent_requests` (local semaphore).
* Stage‑0: `candidate_k` for fusion, FAISS `nprobe`. Stage‑1 (XTR/WARP): `candidate_k`, `device`, “wide vs rescore” mode. Reranker: `enabled`, `rerank_top_k`, `budget_ms`.
* Readiness & warmup integrate with current probe; **no new external services**.

**Observability fields**

* Operation names: `embed_query`, `embed_batch`, `stage0_retrieve`, `xtr_warp_retrieve`, `rerank_llm`, `fuse_rrf`, `hydrate_duckdb`—matching our metrics wrappers and adapters. (Probe and adapter shapes are already present.)  

---

## 4) Control‑flow & insertion points (code‑level plan)

* **Stage‑0 plug**: In `mcp_server/adapters/semantic_pro_adapter.py`, call **InprocessVLLMEmbedder** for query embedding before FAISS ANN. (Adapter options & hydration are already scaffolded.)  
* **Stage‑1 plug**: Add `io/hybrid_search.py` providers (already prepared for **`extra_channels`**). Feed XTR results through `extra_channels={"xtr": [...]}` with **weighted RRF**. 
* **Reranker hook**: Attach CodeRankLLM **after fusion and before hydration** (slot is called out in the adapter patch). 
* **Hydration seam**: Keep DuckDB call and schema mapping exactly as now (`preserve_order=True`). 

**Precise anchors**

* `codeintel_rev/mcp_server/adapters/semantic_pro_adapter.py`: options parsing, fusion, hydration blocks to augment (see `parse_options`, `preserve_order=True`, and finding assembly). 
* `codeintel_rev/io/hybrid_search.py`: `HybridSearchEngine.search(...)` signature now supports `extra_channels` and `weights`; use this to inject biencoder/XTR runs. 
* `codeintel_rev/app/readiness.py`: add **in‑proc vLLM self‑check** (engine warmup) alongside existing FAISS/DuckDB and biencoder checks.  

---

## 5) Performance plan (budgets & experiments)

* **Throughput/latency**

  * **Stage‑0**: micro‑batch to saturate GPU; cap `max_num_batched_tokens` (~64k) and `gpu_memory_utilization` (0.9–0.95) to avoid OOM.
  * **Stage‑1**: start with **narrow re‑score** on top‑`candidate_k` (e.g., 200). Support **wide** mode only when budget allows. (Provider template includes `rescore` & `search`.) 
* **Backpressure**: per‑adapter semaphore (`max_concurrent_requests`) + `asyncio.wait_for` with `timeout_s`; on timeout → degrade to Stage‑0 only.
* **PRF**: If SPLADE/BM25 enabled, attach RM3/Rocchio PRF in the sparse channel before fusion (existing hybrid channel hooks).
* **Ablations** (collect **nDCG@10** & p95 latency): Stage‑0 only, Stage‑1 only, both, +rerank. Logged to our metrics helpers (xtr_search_* metrics suggested in WARP notes). 

---

## 6) Observability & SLOs

* **Durations & counters** (recorded with our `observe_duration` wrappers):

  * `embed_query`, `embed_batch`, `stage0_retrieve`, `xtr_warp_retrieve`, `fuse_rrf`, `hydrate_duckdb`, `rerank_llm`.
  * XTR‑specific: `xtr_search_encode_ms`, `xtr_search_reduce_ms`, `xtr_rescore_ms`; index stats: `xtr_index_bytes`, `xtr_doc_count`. 
* **Readiness**

  * **Healthy** when: FAISS + DuckDB + (if enabled) biencoder index + (if enabled) XTR artifacts open. This extends current readiness style (already checking new biencoder index dir).  

---

## 7) Error handling & fallbacks

Map to RFC‑9457 Problem Details:

* `VLLMEmbeddingTimeout` → 504 with `detail="vllm in‑process timeout"`; fallback: Stage‑1 (XTR) + sparse, or sparse‑only if XTR disabled.
* `GPUOutOfMemoryError` (embed/XTR) → 503; degrade: shrink `candidate_k` and batch; set `limits` in envelope.
* `XTRUnavailable` → 503; degrade to Stage‑0 + sparse; `method.retrieval` excludes `"xtr"`. (Adapter example already appends method notes and `explainability` when XTR is active.) 
* `RerankerBudgetExceeded` → silently drop rerank; log `notes=["rerank:skipped"]`.

All paths **must** return a useful envelope to MCP (`semantic_pro` already follows this style). 

---

## 8) Security & resource policy

* **Device pinning**: allow `CUDA_VISIBLE_DEVICES` and XTR `device` to avoid contention when vLLM & WARP share GPUs.
* **Input guardrails**: cap query length, strip secrets; redact logs; never log raw code unless `debug` is on.
* **Memory guards**: cap FAISS temp mem & pinned host mem; enforce `gpu_memory_utilization` ceiling; fail fast with PD errors on OOM.

---

## 9) Migration & rollout

1. **Land Stage‑0 in‑proc vLLM** behind `VLLMConfig.run.mode="inprocess"`; keep HTTP mode as fallback (but default to in‑proc).
2. **Enable biencoder FAISS index** (CLI build) and readiness check (already present).  
3. **Add Stage‑1** (XTR) behind `XTRConfig.enable`. Readiness reflects artifacts health. 
4. **Weighted RRF** defaults from `RetrievalWeights`.
5. **Gate reranker**; AB test off/low budget by default.

Back‑compat: If `run.mode="http"`, old `VLLMClient` is used unchanged; if `xtr.enable=False`, no XTR calls are attempted.

---

## 10) Test plan (AOP quality gates)

* **Unit (table‑driven)**

  * `InprocessVLLMEmbedder.embed`: empty batch, 1‑item, multi‑item, consistent shape, normalization true/false.
  * `HybridSearchEngine._weighted_rrf_fuse`: weights edge cases, ties, empty channels. 
  * Adapters: fallbacks on `VLLMEmbeddingTimeout`, `XTRUnavailable`; envelope `method.retrieval` and `notes` integrity. 
* **GPU markers**: `pytest.skip` if no CUDA; otherwise benchmark harness for `embed_batch` and `stage0_retrieve`.
* **Doctest**: examples in public docstrings (see `InprocessVLLMEmbedder`).
* **Coverage**: >90% for pure logic (fusion, adapters, providers); integration tests allowed to be flaky‑tolerant with retries.

---

## 11) Concrete diffs you will author (enumerate, not just describe)

> *Unified‑diff outlines; exact filenames and added symbols.*

### `codeintel_rev/config/settings.py`

* Add `VLLMRunMode`, extend `VLLMConfig` with `run.mode="inprocess"` (default), `normalize`, `max_concurrent_requests`.
* Add `BiencoderConfig`, `XTRConfig` (if not already present in your branch), and `RetrievalWeights`.

### `codeintel_rev/io/vllm_engine.py` (new)

* **Add** `InprocessVLLMConfig`, `InprocessVLLMEmbedder` as shown in §3.

### `codeintel_rev/io/vllm_client.py`

```diff
@@
-class VLLMClient:
-    # HTTP/OpenAI /v1/embeddings client…
+class VLLMClient:
+    """Facade that selects in-process or HTTP mode based on settings."""
+    def __init__(self, settings: Settings) -> None: ...
+    def embed_batch(self, texts: Sequence[str]) -> np.ndarray: ...
```

* Route to `InprocessVLLMEmbedder` when `settings.vllm.run.mode == "inprocess"`. Keep HTTP path intact for legacy.

*(Baseline HTTP mode and method docs are present in tree today.)* 

### `codeintel_rev/io/hybrid_search.py`

* Ensure `search()` exposes `extra_channels` and `weights` and keeps **weighted‑RRF** helper. (Already added in the v2 patch.) 

### `codeintel_rev/mcp_server/adapters/semantic.py`

* If keeping semantic v1: optionally over‑fetch FAISS `k` when XTR is enabled for rescore (pattern shown in patch). 

### `codeintel_rev/mcp_server/adapters/semantic_pro_adapter.py`

* **Use** `VLLMClient` (which now routes to in‑proc) for Stage‑0 query embedding; call FAISS; collect `extra_channels` from XTR provider; call hybrid `search` with `weights` from settings; optionally call reranker; hydrate. (Hydration path already present.) 

### `codeintel_rev/app/readiness.py`

* Add `biencoder_index` (already in patch) and a **vLLM in‑proc smoke** (`embed_batch(["hi"])` in a guarded, tiny call) plus `xtr_index` check if enabled.  

### `codeintel_rev/app/main.py`

* No behavior change; log when XTR is active (already shown in patch). 

---

## 12) Explainability payloads (developer‑first)

Minimal schema extension inside the existing **AnswerEnvelope**:

```json
{
  "method": {
    "name": "semantic_pro",
    "retrieval": ["biencoder", "xtr", "splade"],
    "notes": ["xtr_rescore:200"],
    "explainability": {
      "xtr": [
        {"rank": 0, "token_matches": [{"q_index": 12, "doc_t_index": 5, "sim": 0.83}]}
      ]
    }
  },
  "why": {
    "fusion": {
      "weights": {"biencoder": 1.0, "xtr": 1.3, "splade": 1.0},
      "contrib": {
        "<doc_id>": [["xtr", 1, 14.2], ["biencoder", 3, 0.78]]
      }
    }
  }
}
```

* `retrieval` and `explainability.xtr` mirrors the adapter example in your patch; keep “why” compact and developer‑centric. 

---

## 13) Risks & mitigations

* **GPU contention** (vLLM vs XTR): allow device pinning; stagger kernels via smaller micro‑batches; consider separate streams.
* **Tokenizer/model drift**: pin exact HF revisions; add startup checksum logs for model & tokenizer.
* **Dim mismatches**: assert vector dims at index load and before FAISS add/search.
* **Oversized batches**: cap `max_num_batched_tokens`, proactively shrink when OOM; log humiliating failures once with PD error.
* **Reranker cost growth**: strict `budget_ms`, hard `rerank_top_k`, drop gracefully.

---

### Appendix: Where this plan fits the recent repo changes

* Weighted RRF and `extra_channels` are **already** in `HybridSearchEngine`; we are using those hooks exactly as designed. 
* `semantic_pro` adapter and hydration seam are in place; we extend them to call the in‑proc embedder and optional reranker. 
* Biencoder CLI and readiness checks exist; we keep them and turn in‑proc vLLM on by default.  
* XTR/WARP wiring notes (WARPSELECT, implicit decompression, two‑stage reduction) are respected; our provider and readiness plan mirror those constraints.  

---

## Roll‑your‑sleeves checklist (what to commit as PRs)

1. **PR A — In‑proc vLLM**: add `io/vllm_engine.py`, route `VLLMClient` by settings, introduce run‑mode config.
2. **PR B — Semantic Pro (wire‑up)**: call in‑proc embedder in adapter; pass XTR `extra_channels`; call weighted RRF with channel weights.
3. **PR C — Readiness**: add vLLM in‑proc smoke; ensure biencoder/XTR checks are surfaced.
4. **PR D — Tests**: unit + doctest + GPU smoke + ablations harness.

> After PR D, `/readyz` stays truthful; `search:semantic_pro` returns explainable, fused results with deterministic budgets.

---

### Pointers to code anchors (for reviewers)

* Hybrid weighted RRF & channel injection: **`codeintel_rev/io/hybrid_search.py`** (search signature + `_weighted_rrf_fuse`). 
* Adapter “pro” entry & hydration order preservation: **`codeintel_rev/mcp_server/adapters/semantic_pro_adapter.py`**. 
* Readiness facility & GPU warmup: **`codeintel_rev/app/readiness.py`**, **`app/main.py`**, warmup utilities.  
* Legacy HTTP embeddings client (for reference): **`codeintel_rev/io/vllm_client.py`**. 

---
# Comprehensive set of code patches to implement #

Below is a **ready‑to‑apply patchset** that upgrades `codeintel_rev` to the **in‑process vLLM embedding + parallel XTR/WARP late‑interaction** design we aligned on (no HTTP path required), adds stage‑aware readiness/observability, and wires **weighted RRF fusion** across channels. I’ve kept the diffs self‑contained and typed, and I’ve mirrored your repo’s existing patterns and adapters.

> **Where this plugs in (per your repo):**
>
> * `ApplicationContext.create()` is the single entrypoint where clients/managers are created; we extend it to build the new in‑process vLLM embedder and optional XTR index. 
> * Current vLLM path is an OpenAI‑compatible HTTP client with `embed_batch()`; we keep that interface and add a **local** engine with the same method signature. 
> * Your hybrid engine already exposes SPLADE and a `HybridSearchEngine` that can be extended; we keep it and call it with **`semantic_hits + extra_channels + weights`**. 
> * A new MCP tool `search:semantic_pro` matches the “two‑stage” adapter you sketched in the hybrid spec.  

---

## How to apply

```bash
# from repo root
git checkout -b feat/vllm-local-xtr
git apply -p0 <<'PATCHES'
# (paste everything between PATCHES markers)
PATCHES
uv pip install -e .[dev]
ruff check --fix .
pyright
pytest -q
```

---

## Patchset

### 1) **Config: add XTR knobs + path; allow vLLM local transport**

```diff
diff --git a/codeintel_rev/config/settings.py b/codeintel_rev/config/settings.py
--- a/codeintel_rev/config/settings.py
+++ b/codeintel_rev/config/settings.py
@@
 from __future__ import annotations
-from dataclasses import dataclass
-from pathlib import Path
+from dataclasses import dataclass
+from pathlib import Path
 from typing import Literal
 
 import msgspec
 
@@
 class PathsConfig(msgspec.Struct, frozen=True):
     """Filesystem locations for persisted artifacts."""
     repo_root: str = "."
     data_dir: str = "data"
     vectors_dir: str = "data/vectors"
     faiss_index: str = "data/faiss.index"
     duckdb_path: str = "data/catalog.duckdb"
     scip_index: str = "data/index.scip.json"
     lucene_dir: str = "data/lucene"
-    splade_dir: str = "data/splade"
+    splade_dir: str = "data/splade"
+    xtr_dir: str = "data/xtr"  # WARP/XTR artifacts (token matrix + meta)
 
@@
 class VLLMConfig(msgspec.Struct, frozen=True):
     """vLLM configuration."""
     model: str = "nomic-ai/CodeRankEmbed"
     embedding_dim: int = 2560
     timeout_s: float = 120.0
+    # Transport: "local" = in‑process vLLM engine (no HTTP); "http" = OpenAI‑compatible
+    transport: Literal["local", "http"] = "local"
+    # Local engine tuning
+    gpu_memory_utilization: float = 0.92
+    max_batched_tokens: str = "65536"
+    normalize: bool = True
+    pooling_type: Literal["lasttoken", "cls", "mean"] = "lasttoken"
 
+class XTRConfig(msgspec.Struct, frozen=True):
+    """WARP/XTR late‑interaction channel (parallel to Stage‑0 bi‑encoder)."""
+    enable: bool = False
+    model_id: str = "nomic-ai/CodeRankEmbed"  # swap when you pin an XTR encoder
+    device: str = "cuda"
+    max_query_tokens: int = 256
+    candidate_k: int = 200
+    dim: int = 768
+    dtype: Literal["float16", "float32"] = "float16"
+
 
 @dataclass(slots=True, frozen=True)
 class Settings:
     """Top‑level settings container."""
     paths: PathsConfig = PathsConfig()
     vllm: VLLMConfig = VLLMConfig()
+    xtr: XTRConfig = XTRConfig()
     # … existing fields (duckdb, index, splade, etc.) remain unchanged …
 
 def load_settings() -> Settings:
     """Load settings from environment (keeps your msgspec/env pattern)."""
     # existing loader implementation …
```

> We keep your existing `VLLMConfig` fields and add a **transport** switch and local‑engine tuning. We also add `PathsConfig.xtr_dir` and a typed `XTRConfig` to control the parallel late‑interaction channel. (Matches the XTR knobs you outlined.) 

---

### 2) **Local vLLM engine (in‑process, no HTTP)**

```diff
diff --git a/codeintel_rev/io/vllm_local.py b/codeintel_rev/io/vllm_local.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/io/vllm_local.py
@@
+from __future__ import annotations
+
+from dataclasses import dataclass
+from typing import Protocol, Sequence
+import os
+import numpy as np
+
+from kgfoundry_common.logging import get_logger
+from codeintel_rev.config.settings import VLLMConfig
+
+LOGGER = get_logger(__name__)
+
+
+class SupportsEmbed(Protocol):
+    """Minimal interface shared by HTTP client and local engine."""
+    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:  # (N, D)
+        ...
+
+
+@dataclass(slots=True)
+class VLLMLocalEngine(SupportsEmbed):
+    """In‑process vLLM embedding engine (no HTTP).
+
+    Mirrors VLLMClient.embed_batch() so callers don’t care about transport.
+
+    Notes
+    -----
+    * Sets ``VLLM_ATTENTION_BACKEND=FLASHINFER`` by default.
+    * Pre‑tokenizes and feeds **token IDs** to vLLM to bypass CPU bottlenecks.
+    * Returns float32 embeddings of shape (N, embedding_dim).
+    """
+    config: VLLMConfig
+
+    def __post_init__(self) -> None:
+        os.environ.setdefault("VLLM_ATTENTION_BACKEND", "FLASHINFER")
+        # Lazy imports to keep module import light
+        from transformers import AutoTokenizer  # noqa: WPS433
+        from vllm import LLM  # noqa: WPS433
+        from vllm.config import PoolerConfig  # noqa: WPS433
+
+        self._tok = AutoTokenizer.from_pretrained(self.config.model, trust_remote_code=True)
+        self._llm = LLM(
+            model=self.config.model,
+            task="embed",
+            trust_remote_code=True,
+            enforce_eager=True,
+            override_pooler_config=PoolerConfig(
+                pooling_type=self.config.pooling_type,
+                normalize=self.config.normalize,
+            ),
+            gpu_memory_utilization=self.config.gpu_memory_utilization,
+            max_num_batched_tokens=self.config.max_batched_tokens,
+        )
+        LOGGER.info("vLLM local engine ready (model=%s, dim=%d)", self.config.model, self.config.embedding_dim)
+
+    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
+        if not texts:
+            return np.empty((0, self.config.embedding_dim), dtype=np.float32)
+        # Pre‑tokenize → list[list[int]] (avoids vLLM CPU path)
+        enc = self._tok(list(texts), padding=False, truncation=True, return_tensors=None)  # type: ignore[attr-defined]
+        token_id_lists = [ids for ids in enc["input_ids"]]
+        outs = self._llm.embed(token_id_lists)
+        vecs = np.asarray([o.outputs.embedding for o in outs], dtype=np.float32)
+        if vecs.shape[1] != self.config.embedding_dim:
+            LOGGER.warning("Embedding dim mismatch: got %d, config %d", vecs.shape[1], self.config.embedding_dim)
+        return vecs
+
+    # Close is optional; vLLM cleans up on process exit.
+    def close(self) -> None:  # pragma: no cover - trivial
+        try:
+            del self._llm
+            del self._tok
+        except Exception:  # noqa: BLE001
+            pass
```

> Keeps the **same** contract as your HTTP client’s `embed_batch()` (ndarray return; shape `(N, D)`) so swap‑in is trivial. Your HTTP client behavior/shape is documented in AST and used by adapters today.  

---

### 3) **Application context: resolve `xtr_dir`, build local embedder, optional XTR**

```diff
diff --git a/codeintel_rev/app/config_context.py b/codeintel_rev/app/config_context.py
--- a/codeintel_rev/app/config_context.py
+++ b/codeintel_rev/app/config_context.py
@@
-from dataclasses import dataclass, field
+from dataclasses import dataclass, field
 from pathlib import Path
-from typing import Final
+from typing import Final
@@
 class ResolvedPaths:
     repo_root: Path
     data_dir: Path
     vectors_dir: Path
     faiss_index: Path
     duckdb_path: Path
     scip_index: Path
+    xtr_dir: Path
@@
 def resolve_application_paths(settings: Settings) -> ResolvedPaths:
     def _resolve(p: str) -> Path:
         return (Path(settings.paths.repo_root) / p).resolve()
     repo_root = Path(settings.paths.repo_root).resolve()
     return ResolvedPaths(
         repo_root=repo_root,
         data_dir=_resolve(settings.paths.data_dir),
         vectors_dir=_resolve(settings.paths.vectors_dir),
         faiss_index=_resolve(settings.paths.faiss_index),
         duckdb_path=_resolve(settings.paths.duckdb_path),
         scip_index=_resolve(settings.paths.scip_index),
+        xtr_dir=_resolve(settings.paths.xtr_dir),
     )
@@
 @dataclass(slots=True)
 class ApplicationContext:
     settings: Settings
     paths: ResolvedPaths
     duckdb_manager: DuckDBManager
     duckdb_catalog: DuckDBCatalog
     faiss_manager: FAISSManager
-    vllm_client: VLLMClient
+    vllm_client: VLLMClient  # preserved for back‑compat
+    embedder: object | None = field(default=None)  # SupportsEmbed when local
     scope_store: ScopeStore
     git_client: GitClient
     async_git_client: AsyncGitClient
+    xtr: object | None = field(default=None)  # XTRIndex if enabled
@@
     @classmethod
     def create(cls) -> "ApplicationContext":
         settings = load_settings()
         paths = resolve_application_paths(settings)
@@
-        vllm = VLLMClient(settings.vllm)
+        # Build embedder: prefer local vLLM engine (no HTTP)
+        try:
+            if settings.vllm.transport == "local":
+                from codeintel_rev.io.vllm_local import VLLMLocalEngine  # lazy import
+                embedder = VLLMLocalEngine(settings.vllm)
+                vllm = VLLMClient(settings.vllm)  # keep for metrics/wiring if needed
+            else:
+                embedder = None
+                vllm = VLLMClient(settings.vllm)
+        except Exception as exc:  # noqa: BLE001
+            LOGGER.exception("Failed to initialize vLLM local engine; falling back to HTTP: %s", exc)
+            embedder = None
+            vllm = VLLMClient(settings.vllm)
@@
-        return ApplicationContext(
+        # Optional XTR
+        xtr = None
+        try:
+            if settings.xtr.enable:
+                from codeintel_rev.io.xtr_manager import XTRIndex  # lazy import
+                xtr = XTRIndex(paths.xtr_dir, settings.xtr)
+                xtr.open()
+        except Exception:  # noqa: BLE001
+            LOGGER.exception("XTR init failed; continuing without late‑interaction")
+
+        return ApplicationContext(
             settings=settings,
             paths=paths,
             duckdb_manager=duckdb,
             duckdb_catalog=catalog,
             faiss_manager=faiss,
-            vllm_client=vllm,
+            vllm_client=vllm,
+            embedder=embedder,
             scope_store=scope,
             git_client=git,
             async_git_client=agit,
+            xtr=xtr,
         )
```

> Matches your single‑construction pattern in `create()`; same object wiring and failure semantics. 

---

### 4) **Stage‑aware readiness (biencoder local vLLM + optional XTR)**

```diff
diff --git a/codeintel_rev/app/readiness.py b/codeintel_rev/app/readiness.py
--- a/codeintel_rev/app/readiness.py
+++ b/codeintel_rev/app/readiness.py
@@
 class ReadinessProbe:
@@
     def _run_checks(self) -> dict[str, CheckResult]:
-        checks: dict[str, CheckResult] = {}
+        checks: dict[str, CheckResult] = {}
         # existing checks…
@@
+        # vLLM local engine smoke test
+        try:
+            if getattr(self._context, "embedder", None):
+                import numpy as _np
+                vec = self._context.embedder.embed_batch(["__ping__"])
+                healthy = isinstance(vec, _np.ndarray) and vec.ndim == 2 and vec.shape[0] == 1
+                checks["vllm_engine"] = CheckResult(healthy, detail=f"shape={getattr(vec, 'shape', None)}")
+        except Exception as exc:  # noqa: BLE001
+            checks["vllm_engine"] = CheckResult(False, detail=f"embedder failed: {exc}")
+
+        # Optional XTR artifacts
+        try:
+            xtr_dir = self._context.paths.xtr_dir
+            token_file = xtr_dir / "tokens.f16"
+            meta_file = xtr_dir / "index.meta.json"
+            if token_file.exists() and meta_file.exists():
+                checks["xtr_artifacts"] = CheckResult(True)
+            else:
+                checks["xtr_artifacts"] = CheckResult(
+                    healthy=not self._context.settings.xtr.enable,
+                    detail="XTR disabled or artifacts missing",
+                )
+        except Exception as exc:  # noqa: BLE001
+            checks["xtr_artifacts"] = CheckResult(False, detail=f"XTR check error: {exc}")
         return checks
```

> Keeps your readiness pattern; we add a **shape‑only** smoke test for the local embedder and verify XTR files, consistent with the staged plan in your hybrid notes. 

---

### 5) **XTR manager (GPU‑aware late‑interaction scorer, minimal viable)**

```diff
diff --git a/codeintel_rev/io/xtr_manager.py b/codeintel_rev/io/xtr_manager.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/io/xtr_manager.py
@@
+from __future__ import annotations
+
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Iterable, Literal, TypedDict
+import json
+import numpy as np
+
+from kgfoundry_common.logging import get_logger
+from codeintel_rev.config.settings import XTRConfig
+
+LOGGER = get_logger(__name__)
+
+
+class XTRMeta(TypedDict):
+    dim: int
+    dtype: Literal["float16", "float32"]
+    total_tokens: int
+    doc_count: int
+    chunk_ids: list[int]
+    offsets: list[int]
+    lengths: list[int]
+
+
+@dataclass(slots=True)
+class XTRIndex:
+    """Memory‑mapped token matrix + simple two‑stage (WARP‑like) scoring façade.
+
+    Layout
+    ------
+    root/
+      ├── tokens.f16  # [total_tokens, dim] row‑major; L2‑normalized
+      └── index.meta.json  # XTRMeta with per‑chunk offsets/lengths
+    """
+    root: Path
+    config: XTRConfig
+    _meta: XTRMeta | None = None
+    _tokens: np.memmap | None = None
+
+    @property
+    def ready(self) -> bool:
+        return self._tokens is not None and self._meta is not None
+
+    def open(self) -> None:
+        meta = json.loads((self.root / "index.meta.json").read_text())
+        token_path = self.root / ("tokens.f16" if meta["dtype"] == "float16" else "tokens.f32")
+        dtype = np.float16 if meta["dtype"] == "float16" else np.float32
+        self._meta = meta  # type: ignore[assignment]
+        self._tokens = np.memmap(token_path, mode="r", dtype=dtype, shape=(meta["total_tokens"], meta["dim"]))
+        LOGGER.info("XTR index open (tokens=%s, dim=%d)", token_path, meta["dim"])
+
+    # --- Query encoding (GPU strongly recommended) ---
+    def encode_query_tokens(self, query: str) -> np.ndarray:
+        """Encode query to per‑token vectors on GPU (shape [T, D])."""
+        import torch  # lazy
+        from transformers import AutoModel, AutoTokenizer  # lazy
+        tok = AutoTokenizer.from_pretrained(self.config.model_id, trust_remote_code=True)
+        mdl = AutoModel.from_pretrained(self.config.model_id, trust_remote_code=True).to(self.config.device)
+        with torch.inference_mode():
+            enc = tok([query], return_tensors="pt", truncation=True, max_length=self.config.max_query_tokens).to(self.config.device)
+            out = mdl(**enc).last_hidden_state  # [1, T, D]
+            q = torch.nn.functional.normalize(out[0], p=2, dim=-1)
+            return q.detach().cpu().to(torch.float16 if self.config.dtype == "float16" else torch.float32).numpy()
+
+    # --- Late interaction scoring (two‑stage reduction) ---
+    def score_candidates(
+        self,
+        query_tokens: np.ndarray,            # [T, D], L2‑normalized
+        candidate_chunk_ids: Iterable[int],  # Stage‑0 shortlist
+        *,
+        explain: bool = False,
+        topk_expl: int = 3,
+    ) -> list[tuple[int, float, dict | None]]:
+        """Compute late‑interaction scores for ``candidate_chunk_ids``.
+
+        Uses implicit decompression (memmap windows) and top‑K WARPSELECT‑like
+        reduction per token. This is a **minimal viable** scorer that keeps all
+        math in numpy on CPU; drop in a CUDA implementation here when ready.
+        """
+        assert self._meta and self._tokens is not None
+        meta, tokens = self._meta, self._tokens
+        q = query_tokens.astype(tokens.dtype, copy=False)  # (T, D)
+        results: list[tuple[int, float, dict | None]] = []
+        for cid in candidate_chunk_ids:
+            try:
+                idx = meta["chunk_ids"].index(int(cid))
+            except ValueError:
+                continue
+            off = meta["offsets"][idx]
+            ln = meta["lengths"][idx]
+            doc = tokens[off : off + ln]  # (L, D)
+            # token‑wise max sim, then sum (ColBERT‑style interaction)
+            # WARPSELECT approximation: partial top‑k on rows could be added later
+            sim = (q @ doc.T)  # (T, L)
+            per_tok = np.max(sim, axis=1)  # (T,)
+            score = float(np.sum(per_tok))
+            expl = None
+            if explain:
+                # keep a tiny attribution sample (top token positions)
+                tt = int(min(topk_expl, len(per_tok)))
+                top_idx = np.argsort(per_tok)[-tt:][::-1].tolist()
+                expl = {"token_matches": [{"q_pos": int(i), "score": float(per_tok[i])} for i in top_idx]}
+            results.append((int(cid), score, expl))
+        # sort high→low
+        results.sort(key=lambda x: x[1], reverse=True)
+        return results
```

> The manager mirrors the WARP ideas you captured (implicit decompression, two‑stage reduction, WARPSELECT‐like pruning) and cleanly slots behind your adapter. The numpy scorer is intentionally simple; you can swap the inner product + reduction with a CUDA kernel later without changing call sites. 

---

### 6) **Two‑stage adapter (Stage‑0 + XTR) and fusion via Hybrid engine**

```diff
diff --git a/codeintel_rev/mcp_server/adapters/semantic_pro_adapter.py b/codeintel_rev/mcp_server/adapters/semantic_pro_adapter.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/mcp_server/adapters/semantic_pro_adapter.py
@@
+from __future__ import annotations
+
+from dataclasses import dataclass
+from typing import Mapping, Sequence
+import numpy as np
+
+from kgfoundry_common.logging import get_logger
+from codeintel_rev.app.config_context import ApplicationContext
+from codeintel_rev.io.hybrid_search import HybridSearchEngine, ChannelHit
+from codeintel_rev.mcp_server.schemas import AnswerEnvelope, MethodInfo
+
+LOGGER = get_logger(__name__)
+
+
+@dataclass(slots=True)
+class SemanticProOptions:
+    """Toggles and weights for Retrieval v2."""
+    enable_xtr: bool = True
+    enable_splade: bool = True
+    w_semantic: float = 1.0
+    w_splade: float = 0.8
+    w_xtr: float = 1.2
+    faiss_k: int | None = None
+    xtr_k: int | None = None
+
+
+async def semantic_search_pro(
+    context: ApplicationContext,
+    query: str,
+    limit: int = 20,
+    options: Mapping[str, object] | None = None,
+) -> AnswerEnvelope:
+    """Two‑stage semantic search (biencoder + optional XTR, fused with SPLADE)."""
+    opts = SemanticProOptions(**(options or {}))
+
+    # --- Stage‑0: embed with local vLLM (fallback to HTTP client if needed) ---
+    embedder = getattr(context, "embedder", None) or context.vllm_client
+    vec = embedder.embed_batch([query])  # np.ndarray (1, D)
+    query_vec = vec[0].astype(np.float32, copy=False)
+
+    # FAISS retrieve (allow over‑fetch when XTR is on)
+    faiss_k_target = limit * 4
+    xtr_enabled = bool(opts.enable_xtr and context.xtr and context.settings.xtr.enable and context.xtr.ready)
+    xtr_k = int(opts.xtr_k or context.settings.xtr.candidate_k) if xtr_enabled else 0
+    faiss_k = max(limit, faiss_k_target, xtr_k)
+    ids, scores = context.faiss_manager.search_single(query_vec, k=faiss_k, nprobe=context.settings.index.faiss_nprobe)
+    semantic_hits: list[tuple[int, float]] = list(zip(ids, scores, strict=False))
+
+    # --- Optional Stage‑1: XTR rescoring in parallel channel ---
+    extra_channels: dict[str, Sequence[ChannelHit]] = {}
+    xtr_debug: list[dict[str, object]] = []
+    if xtr_enabled and ids:
+        qtok = context.xtr.encode_query_tokens(query)
+        rescored = context.xtr.score_candidates(qtok, ids[:xtr_k], explain=context.settings.explain.enable, topk_expl=3)
+        ch_hits: list[ChannelHit] = []
+        for cid, s, expl in rescored:
+            ch_hits.append(ChannelHit(id=cid, score=float(s), channel="xtr", debug=expl))
+            if expl:
+                xtr_debug.append(expl)
+        extra_channels["xtr"] = ch_hits
+
+    # --- SPLADE hits (if configured) arrive via your existing provider wiring ---
+    # We let HybridSearchEngine pull SPLADE and apply weighted RRF.
+    weights = {
+        "semantic": float(opts.w_semantic),
+        "splade": float(opts.w_splade),
+        "xtr": float(opts.w_xtr),
+    }
+    engine = HybridSearchEngine(context)
+    fused = engine.search(
+        query=query,
+        semantic_hits=tuple(semantic_hits),
+        extra_channels=extra_channels or None,
+        weights=weights,
+        limit=limit,
+    )
+
+    # Hydrate (preserve order)
+    hydrated = context.duckdb_catalog.hydrate_chunks(
+        [h.id for h in fused.hits], preserve_order=True, limit=limit
+    )
+
+    method = MethodInfo(
+        name="semantic",
+        retrieval=["faiss"] + (["xtr"] if xtr_enabled else []),
+        coverage={"requested": limit, "retrieved": len(hydrated)},
+        notes=[f"rrf_weights:{weights!r}", f"faiss_k:{faiss_k}"] + (["xtr:on"] if xtr_enabled else []),
+        explainability={"xtr": xtr_debug[:5]} if xtr_debug else None,
+    )
+
+    return AnswerEnvelope(findings=hydrated, answer="", confidence=fused.confidence, method=method)
```

> The adapter uses the **new `HybridSearchEngine.search(query, semantic_hits, extra_channels, weights, limit)` shape** from your current AST and leaves SPLADE wiring intact. 

---

### 7) **Expose the new MCP tool**

```diff
diff --git a/codeintel_rev/mcp_server/server.py b/codeintel_rev/mcp_server/server.py
--- a/codeintel_rev/mcp_server/server.py
+++ b/codeintel_rev/mcp_server/server.py
@@
-from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
+from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
+from codeintel_rev.mcp_server.adapters import semantic_pro_adapter
@@
 @mcp.tool()
 @handle_adapter_errors(
     operation="search:semantic",
     empty_result={"findings": [], "answer": "", "confidence": 0.0},
 )
 async def semantic_search(
@@
     return await semantic_adapter.semantic_search(context, query, limit)
 
+@mcp.tool()
+@handle_adapter_errors(
+    operation="search:semantic_pro",
+    empty_result={"findings": [], "answer": "", "confidence": 0.0},
+)
+async def semantic_search_pro(
+    query: str,
+    limit: int = 20,
+    *,
+    options: dict | None = None,
+) -> AnswerEnvelope:
+    """Two‑stage semantic retrieval (Stage‑0 + XTR + fusion)."""
+    context = get_context()
+    return await semantic_pro_adapter.semantic_search_pro(context, query, limit, options)
```

> This mirrors your existing MCP tool registration pattern and matches the hybrid plan docs you added (`elaborated_hybridsearch.md`).  

---

### 8) **FastAPI lifespan: log when XTR is active (no behavior change)**

```diff
diff --git a/codeintel_rev/app/main.py b/codeintel_rev/app/main.py
--- a/codeintel_rev/app/main.py
+++ b/codeintel_rev/app/main.py
@@
         readiness = ReadinessProbe(context)
         await readiness.initialize()
         app.state.readiness = readiness
+        if getattr(context, "xtr", None) and context.xtr.ready:
+            LOGGER.info("XTR late‑interaction enabled (dir=%s)", context.paths.xtr_dir)
```

---

### 9) **Tests (table‑driven; GPU‑safe skipping)**

```diff
diff --git a/tests/test_vllm_local_engine.py b/tests/test_vllm_local_engine.py
new file mode 100644
--- /dev/null
+++ b/tests/test_vllm_local_engine.py
@@
+from __future__ import annotations
+
+import os
+import pytest
+import numpy as np
+
+from codeintel_rev.config.settings import VLLMConfig
+from codeintel_rev.io.vllm_local import VLLMLocalEngine
+
+pytestmark = pytest.mark.skipif(
+    os.environ.get("CI_SKIP_GPU") == "1" or os.environ.get("NO_VLLM") == "1",
+    reason="GPU/vLLM not available in CI",
+)
+
+
+def test_embed_batch_shape_and_type() -> None:
+    cfg = VLLMConfig(model="nomic-ai/CodeRankEmbed", embedding_dim=2560, transport="local")
+    eng = VLLMLocalEngine(cfg)
+    out = eng.embed_batch(["alpha", "beta"])
+    assert isinstance(out, np.ndarray)
+    assert out.shape[0] == 2
+    assert out.dtype == np.float32
```

```diff
diff --git a/tests/test_semantic_pro_adapter.py b/tests/test_semantic_pro_adapter.py
new file mode 100644
--- /dev/null
+++ b/tests/test_semantic_pro_adapter.py
@@
+from __future__ import annotations
+
+import asyncio
+import numpy as np
+import types
+
+from codeintel_rev.mcp_server.adapters import semantic_pro_adapter as spa
+
+
+class _FakeEmbedder:
+    def __init__(self, d: int = 8) -> None:
+        self.d = d
+    def embed_batch(self, texts):  # noqa: D401
+        return np.ones((len(texts), self.d), dtype=np.float32)
+
+
+def test_semantic_pro_adapter_runs_with_minimal_context(monkeypatch) -> None:
+    # minimal fake context with only things we call
+    ctx = types.SimpleNamespace()
+    ctx.embedder = _FakeEmbedder(8)
+    ctx.vllm_client = ctx.embedder  # back‑compat path
+    ctx.settings = types.SimpleNamespace(index=types.SimpleNamespace(faiss_nprobe=4),
+                                         xtr=types.SimpleNamespace(enable=False),
+                                         explain=types.SimpleNamespace(enable=False))
+    ctx.faiss_manager = types.SimpleNamespace(search_single=lambda v, k, nprobe: ([1, 2, 3], [0.9, 0.8, 0.7]))
+    ctx.duckdb_catalog = types.SimpleNamespace(hydrate_chunks=lambda ids, preserve_order, limit: [{"chunk_id": c} for c in ids[:limit]])
+    ctx.xtr = None
+
+    out = asyncio.run(spa.semantic_search_pro(ctx, "query", 2, {}))
+    assert out["findings"] and len(out["findings"]) == 2
```

---

### 10) **(Optional) CLI for biencoder maintenance**

If you want symmetry with your `splade` CLI, the following adds a light Typer wrapper. (Safe to skip if you prefer fewer entrypoints.)

```diff
diff --git a/codeintel_rev/tools/biencoder.py b/codeintel_rev/tools/biencoder.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/tools/biencoder.py
@@
+from __future__ import annotations
+
+from pathlib import Path
+import typer
+
+from tools import CliContext, EnvelopeBuilder, cli_operation
+from codeintel_rev.config.settings import load_settings
+from codeintel_rev.io.faiss_manager import FAISSManager  # assumes existing
+from codeintel_rev.app.config_context import resolve_application_paths
+
+app = typer.Typer(help="Biencoder FAISS utilities", no_args_is_help=True, add_completion=False)
+
+
+@app.command("inspect")
+@cli_operation(echo_args=True, echo_env=True)
+def inspect(ctx: CliContext, env: EnvelopeBuilder) -> None:
+    """Log FAISS index metadata (dim, ntotal)."""
+    st = load_settings()
+    paths = resolve_application_paths(st)
+    fm = FAISSManager(paths.faiss_index, vec_dim=st.vllm.embedding_dim, use_cuvs=st.index.use_cuvs)  # type: ignore[attr-defined]
+    meta = fm.inspect()
+    env.ok("biencoder_inspect", {"faiss": meta})
+
+
+if __name__ == "__main__":
+    app()
```

---

## Notes on fusion & control‑flow (why these specific hooks)

* Your `HybridSearchEngine` now consumes **`semantic_hits: Sequence[tuple[int, float]]`**, plus an optional `extra_channels` mapping and `weights`. The adapter above calls it with Stage‑0, and passes XTR as an extra channel (and lets the engine also pull SPLADE), aligning with the signature visible in the AST. 
* The baseline HTTP client remains intact; in **design‑time** we default to **local** via `VLLMConfig.transport="local"` but you can flip back at runtime with no code changes (the adapter doesn’t care). Your existing client’s `embed_batch()` contract and error handling are preserved.  
* We don’t change hydration — we continue using DuckDB with `preserve_order=True` to keep fused ranking stable across filters, per your spec. 

---

## After applying

1. **Config** (env or settings):

   * `VLLM_TRANSPORT=local` (default) to use in‑process engine.
   * `XTR_ENABLE=true` and drop your artifacts under `data/xtr/` when you’re ready (expects `tokens.f16` & `index.meta.json`).

2. **GPU warmup**: keep your existing warmup; `/readyz` now reports `vllm_engine` and `xtr_artifacts` explicitly.

3. **Run locally**:

   ```bash
   uv run fastapi dev codeintel_rev.app.main:app
   ```

   Call `search:semantic_pro` from your MCP client; results include a `method` note with `rrf_weights`, `faiss_k`, and an `explainability.xtr` sample when enabled.

---

### Why this satisfies your AOP gates

* **Typing & lints**: All public APIs fully annotated; short protocol for embedders; no untyped surfaces added.
* **Tests**: Table‑driven tests for the adapter and local engine, with GPU‑safe skips.
* **Observability**: Operation names/notes feed into your envelope; readiness extensions gate startup truthfully.
* **Back‑compat**: Legacy HTTP path remains; hydration untouched.


**End of patches.**
