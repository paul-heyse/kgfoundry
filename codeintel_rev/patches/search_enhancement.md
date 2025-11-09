
# INSTRUCTIONS #

Below is a **repo‑accurate patch set** that wires a **two‑stage retriever** (Stage‑A: **CodeRankEmbed** dense FAISS; Stage‑B: optional **WARP/XTR** late‑interaction) with an optional **CodeRankLLM** listwise reranker, exposed via a new MCP tool `search:semantic_pro`. I kept the patch surface tight and Pythonic, integrating with your existing `ApplicationContext`, DuckDB catalog hydration, and envelope/metrics patterns.

> Key external facts baked into design
> • **CodeRankEmbed requires a query instruction prefix** — *“Represent this query for searching relevant code: …”* — and is shipped as a `SentenceTransformer` bi‑encoder. We honor that in the embedder wrapper. ([Hugging Face][1])
> • **WARP** is a ColBERT/XTR late‑interaction engine designed for **GPU‑centric** speed/memory (reported **41×** speedup vs classical engines) and compatible with **XTR** compressed multivector indexes; this patch includes a wrapper and graceful fallback when the WARP Python package or compiled artifacts aren’t present. ([Weaviate Documentation][2])
> • **XTR** (cross‑token representation) compresses token‑level interactions to keep late‑interaction efficient; we model that channel as a parallel scorer with pluggable weights in RRF. ([arXiv][3])
> • **CodeRankLLM** is a 7B listwise reranker trained to order multiple code passages; we expose a lightweight, CPU‑default rerank step with deterministic JSON output. ([Hugging Face][4])

---

## What this patch adds

1. **Configuration** (`settings.py`, `config_context.py`)

* New `CodeRankConfig`, `WarpConfig`, `CodeRankLLMConfig`.
* New `PathsConfig` fields for a parallel **CodeRank FAISS index** and **WARP/XTR index dir**.
* Environment variables with safe defaults; CPU default for experimental pieces (you agreed).

2. **MCP surface** (`mcp_server/server.py`)

* New tool `search:semantic_pro` with knobs to toggle/fuse stages and reranking.

3. **Adapters** (new `mcp_server/adapters/semantic_pro.py`)

* Implements Stage‑A CodeRank → optional Stage‑B WARP/XTR → optional CodeRankLLM rerank.
* Carries session scope through DuckDB hydration (mirrors your existing `semantic.py`).

4. **IO helpers**

* `io/coderank_embedder.py` — thin, pooled `SentenceTransformer` wrapper honoring the **required** CodeRank query prefix. ([Hugging Face][1])
* `io/warp_engine.py` — WARP/XTR executor wrapper (imports the **xtr‑warp** engine if available; otherwise returns a soft “unavailable” limit). ([GitHub][5])
* `io/rerank_coderankllm.py` — JSON‑safe, listwise rerank using `transformers` with your agreed prompt skeleton. ([Hugging Face][4])
* `io/rrf.py` — weighted RRF util so you can bias CodeRank vs WARP at query time.

5. **Index build CLI for CodeRank** (optional but handy)

* `coderank.py` — Typer CLI to embed chunks from **DuckDB catalog → FAISS index** using CodeRankEmbed.

> **WARP/XTR indexing**: this patch **wraps** the runtime scorer and gracefully degrades when the compiled engine is absent. Building the XTR/WARP index depends on the external project; the wrapper points to its instructions. ([GitHub][5])

---

## Patches (unified diffs)

> Apply with `git apply -p0` from the repo root. Paths align with your existing module imports (`codeintel_rev/...`).

### 1) `codeintel_rev/config/settings.py` — add configs & env wiring

```diff
*** a/codeintel_rev/config/settings.py
--- b/codeintel_rev/config/settings.py
@@
 from codeintel_rev.io.duckdb_manager import DuckDBConfig
+#
+# New retrieval channels and reranker configuration
+#
+class CodeRankConfig(msgspec.Struct, frozen=True):
+    """CodeRankEmbed bi-encoder configuration."""
+    model_id: str = "nomic-ai/CodeRankEmbed"
+    # HuggingFace SentenceTransformer requires trust_remote_code for custom head
+    trust_remote_code: bool = True
+    device: str = "cpu"           # "cuda", "cpu", or "auto"
+    batch_size: int = 128
+    normalize: bool = True
+    # IMPORTANT instruction prefix required by model card:
+    # "Represent this query for searching relevant code: ..."
+    query_prefix: str = "Represent this query for searching relevant code: "  # :contentReference[oaicite:8]{index=8}
+
+class WarpConfig(msgspec.Struct, frozen=True):
+    """WARP/XTR late-interaction configuration."""
+    index_dir: str = "indexes/warp_xtr"    # directory produced by xtr-warp build
+    model_id: str = "intfloat/e5-multivector-large"  # placeholder; override for code-specific XTR if available
+    device: str = "cpu"                    # default CPU for experimental; toggle to "cuda" when ready
+    top_k: int = 200                       # candidate fanout within WARP
+    enabled: bool = False                  # off by default unless explicitly enabled
+
+class CodeRankLLMConfig(msgspec.Struct, frozen=True):
+    """Listwise reranker (CodeRankLLM 7B) configuration."""
+    model_id: str = "nomic-ai/CodeRankLLM"
+    device: str = "cpu"              # default CPU; set to "cuda" to accelerate
+    max_new_tokens: int = 256
+    temperature: float = 0.0
+    top_p: float = 1.0
+    enabled: bool = False
@@
 class PathsConfig(msgspec.Struct, frozen=True):
     """File system paths configuration.
@@
-    repo_root: str = "."
-    data_dir: str = "data"
-    vectors_dir: str = "data/vectors"
-    faiss_index: str = "data/faiss/code.ivfpq.faiss"
-    duckdb_path: str = "data/catalog.duckdb"
-    scip_index: str = "data/scip/index.json"
+    repo_root: str = "."
+    data_dir: str = "data"
+    vectors_dir: str = "data/vectors"
+    faiss_index: str = "data/faiss/code.ivfpq.faiss"
+    duckdb_path: str = "data/catalog.duckdb"
+    scip_index: str = "data/scip/index.json"
+    # New parallel channels
+    coderank_vectors_dir: str = "data/coderank_vectors"
+    coderank_faiss_index: str = "data/faiss/coderank.ivfpq.faiss"
+    warp_index_dir: str = "indexes/warp_xtr"
@@
 class Settings(msgspec.Struct, frozen=True):
@@
-    splade: SpladeConfig
+    splade: SpladeConfig
+    coderank: CodeRankConfig
+    warp: WarpConfig
+    coderank_llm: CodeRankLLMConfig
@@
 def load_settings() -> Settings:
@@
-    return Settings(
+    return Settings(
         vllm=vllm,
         paths=paths,
         index=index,
         limits=limits,
         redis=redis,
         duckdb=duckdb_config,
         bm25=BM25Config(
             corpus_json_dir=os.environ.get("BM25_JSONL_DIR", "data/jsonl"),
             index_dir=os.environ.get("BM25_INDEX_DIR", "indexes/bm25"),
             threads=int(os.environ.get("BM25_THREADS", "8")),
         ),
         splade=SpladeConfig(
             model_id=os.environ.get("SPLADE_MODEL_ID", "naver/splade-v3"),
             model_dir=os.environ.get("SPLADE_MODEL_DIR", "models/splade-v3"),
             onnx_dir=os.environ.get("SPLADE_ONNX_DIR", "models/splade-v3/onnx"),
             onnx_file=os.environ.get("SPLADE_ONNX_FILE", "model_qint8.onnx"),
             vectors_dir=os.environ.get("SPLADE_VECTORS_DIR", "data/splade_vectors"),
             index_dir=os.environ.get("SPLADE_INDEX_DIR", "indexes/splade_v3_impact"),
             provider=os.environ.get("SPLADE_PROVIDER", "CPUExecutionProvider"),
             quantization=int(os.environ.get("SPLADE_QUANTIZATION", "100")),
             max_terms=int(os.environ.get("SPLADE_MAX_TERMS", "3000")),
             max_clause_count=int(os.environ.get("SPLADE_MAX_CLAUSE", "4096")),
             batch_size=int(os.environ.get("SPLADE_BATCH_SIZE", "32")),
             threads=int(os.environ.get("SPLADE_THREADS", "8")),
         ),
+        coderank=CodeRankConfig(
+            model_id=os.environ.get("CODERANK_MODEL_ID", "nomic-ai/CodeRankEmbed"),
+            trust_remote_code=os.environ.get("CODERANK_TRUST_REMOTE_CODE", "1").lower() in {"1","true","yes"},
+            device=os.environ.get("CODERANK_DEVICE", "cpu"),
+            batch_size=int(os.environ.get("CODERANK_BATCH", "128")),
+            normalize=os.environ.get("CODERANK_NORMALIZE", "1").lower() in {"1","true","yes"},
+            query_prefix=os.environ.get(
+                "CODERANK_QUERY_PREFIX",
+                "Represent this query for searching relevant code: ",
+            ),
+        ),
+        warp=WarpConfig(
+            index_dir=os.environ.get("WARP_INDEX_DIR", "indexes/warp_xtr"),
+            model_id=os.environ.get("WARP_MODEL_ID", "intfloat/e5-multivector-large"),
+            device=os.environ.get("WARP_DEVICE", "cpu"),
+            top_k=int(os.environ.get("WARP_TOP_K", "200")),
+            enabled=os.environ.get("WARP_ENABLED", "0").lower() in {"1","true","yes"},
+        ),
+        coderank_llm=CodeRankLLMConfig(
+            model_id=os.environ.get("CODERANK_LLM_MODEL_ID", "nomic-ai/CodeRankLLM"),
+            device=os.environ.get("CODERANK_LLM_DEVICE", "cpu"),
+            max_new_tokens=int(os.environ.get("CODERANK_LLM_MAX_NEW_TOKENS", "256")),
+            temperature=float(os.environ.get("CODERANK_LLM_TEMPERATURE", "0.0")),
+            top_p=float(os.environ.get("CODERANK_LLM_TOP_P", "1.0")),
+            enabled=os.environ.get("CODERANK_LLM_ENABLED", "0").lower() in {"1","true","yes"},
+        ),
     )
@@
 __all__ = [
@@
     "SpladeConfig",
+    "CodeRankConfig",
+    "WarpConfig",
+    "CodeRankLLMConfig",
     "VLLMConfig",
     "load_settings",
 ]
```

---

### 2) `codeintel_rev/app/config_context.py` — add resolved paths

```diff
*** a/codeintel_rev/app/config_context.py
--- b/codeintel_rev/app/config_context.py
@@
 class ResolvedPaths:
@@
-    repo_root: Path
-    data_dir: Path
-    vectors_dir: Path
-    faiss_index: Path
-    duckdb_path: Path
-    scip_index: Path
+    repo_root: Path
+    data_dir: Path
+    vectors_dir: Path
+    faiss_index: Path
+    duckdb_path: Path
+    scip_index: Path
+    coderank_vectors_dir: Path
+    coderank_faiss_index: Path
+    warp_index_dir: Path
@@
     return ResolvedPaths(
         repo_root=repo_root,
         data_dir=_resolve(settings.paths.data_dir),
         vectors_dir=_resolve(settings.paths.vectors_dir),
         faiss_index=_resolve(settings.paths.faiss_index),
         duckdb_path=_resolve(settings.paths.duckdb_path),
         scip_index=_resolve(settings.paths.scip_index),
+        coderank_vectors_dir=_resolve(settings.paths.coderank_vectors_dir),
+        coderank_faiss_index=_resolve(settings.paths.coderank_faiss_index),
+        warp_index_dir=_resolve(settings.paths.warp_index_dir),
     )
```

---

### 3) `codeintel_rev/mcp_server/server.py` — add the new MCP tool

```diff
*** a/codeintel_rev/mcp_server/server.py
--- b/codeintel_rev/mcp_server/server.py
@@
-from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
+from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
+from codeintel_rev.mcp_server.adapters import semantic_pro as semantic_pro_adapter
@@
 async def semantic_search(
     query: str,
     limit: int = 20,
 ) -> AnswerEnvelope:
@@
     return await semantic_adapter.semantic_search(context, query, limit)
+
+# ==================== Semantic (Pro) ====================
+
+@mcp.tool()
+@handle_adapter_errors(
+    operation="search:semantic_pro",
+    empty_result={"findings": [], "answer": "", "confidence": 0.0},
+)
+async def semantic_search_pro(
+    query: str,
+    limit: int = 20,
+    *,
+    use_coderank: bool = True,
+    use_warp: bool = True,
+    use_reranker: bool = False,
+    stage_weights: dict[str, float] | None = None,
+    explain: bool = True,
+) -> AnswerEnvelope:
+    """Two-stage retrieval: CodeRank (dense) → optional WARP/XTR → optional CodeRankLLM.
+
+    Parameters
+    ----------
+    query : str
+        Natural-language or code query.
+    limit : int
+        Max hydrated results to return.
+    use_coderank : bool
+        Stage-A dense retrieval (CodeRankEmbed).
+    use_warp : bool
+        Stage-B late-interaction rerank with WARP/XTR (if index present).
+    use_reranker : bool
+        Final listwise reranker with CodeRankLLM (if model available).
+    stage_weights : dict[str, float] | None
+        Optional channel weights for fusion (keys: "coderank", "warp").
+    explain : bool
+        Include human-readable “why” strings describing contributions.
+    """
+    context = get_context()
+    return await semantic_pro_adapter.semantic_search_pro(
+        context,
+        query=query,
+        limit=limit,
+        use_coderank=use_coderank,
+        use_warp=use_warp,
+        use_reranker=use_reranker,
+        stage_weights=stage_weights or {},
+        explain=explain,
+    )
```

---

### 4) **New** `codeintel_rev/mcp_server/adapters/semantic_pro.py`

```diff
*** /dev/null
--- b/codeintel_rev/mcp_server/adapters/semantic_pro.py
@@
+"""Two-stage retrieval adapter (CodeRank → WARP/XTR) with optional listwise rerank.
+
+Design:
+  1) Dense Stage-A: CodeRankEmbed (FAISS) → candidate chunk IDs
+  2) Late-interaction Stage-B (optional): WARP/XTR rerank on same candidates
+  3) Listwise Reranker (optional): CodeRankLLM over hydrated text previews
+  4) Hydrate final top-K from DuckDB with session scope applied
+"""
+from __future__ import annotations
+
+import asyncio
+from time import perf_counter
+from typing import TYPE_CHECKING, Sequence, cast
+
+import numpy as np
+
+from codeintel_rev.app.middleware import get_session_id
+from codeintel_rev.mcp_server.common.observability import observe_duration
+from codeintel_rev.mcp_server.schemas import AnswerEnvelope, Finding, MethodInfo, ScopeIn
+from codeintel_rev.mcp_server.scope_utils import get_effective_scope
+from kgfoundry_common.errors import EmbeddingError, VectorSearchError
+from kgfoundry_common.logging import get_logger
+
+from codeintel_rev.io.faiss_manager import FAISSManager
+from codeintel_rev.io.rerank_coderankllm import CodeRankListwiseReranker
+from codeintel_rev.io.coderank_embedder import CodeRankEmbedder
+from codeintel_rev.io.warp_engine import WarpEngine, WarpUnavailable
+from codeintel_rev.io.rrf import weighted_rrf
+
+if TYPE_CHECKING:
+    from codeintel_rev.app.config_context import ApplicationContext
+
+SNIPPET_PREVIEW_CHARS = 500
+COMPONENT_NAME = "codeintel_mcp"
+LOGGER = get_logger(__name__)
+
+
+async def semantic_search_pro(  # noqa: C901, PLR0915
+    context: ApplicationContext,
+    *,
+    query: str,
+    limit: int = 20,
+    use_coderank: bool = True,
+    use_warp: bool = True,
+    use_reranker: bool = False,
+    stage_weights: dict[str, float] | None = None,
+    explain: bool = True,
+) -> AnswerEnvelope:
+    """Run two-stage retrieval with optional late-interaction and listwise reranking."""
+    session_id = get_session_id()
+    scope = await get_effective_scope(context, session_id)
+    return await asyncio.to_thread(
+        _semantic_pro_sync,
+        context,
+        query,
+        limit,
+        session_id,
+        scope,
+        use_coderank,
+        use_warp,
+        use_reranker,
+        stage_weights or {},
+        explain,
+    )
+
+
+def _semantic_pro_sync(  # noqa: C901, PLR0912, PLR0915
+    context: ApplicationContext,
+    query: str,
+    limit: int,
+    session_id: str,
+    scope: ScopeIn | None,
+    use_coderank: bool,
+    use_warp: bool,
+    use_reranker: bool,
+    stage_weights: dict[str, float],
+    explain: bool,
+) -> AnswerEnvelope:
+    start_time = perf_counter()
+    weights = {"coderank": 1.0, "warp": 1.0}
+    weights.update({k: float(v) for k, v in stage_weights.items()})
+
+    with observe_duration("semantic_search_pro", COMPONENT_NAME) as observation:
+        requested_limit = limit
+        max_results = max(1, context.settings.limits.max_results)
+        effective_limit = max(1, min(requested_limit, max_results))
+        trunc_msgs: list[str] = []
+        if requested_limit <= 0:
+            trunc_msgs.append(f"Requested limit {requested_limit} is not positive; using 1.")
+        if requested_limit > max_results:
+            trunc_msgs.append(
+                f"Requested limit {requested_limit} exceeds max_results {max_results}; truncating."
+            )
+
+        # ---------- Stage A: CodeRank FAISS ----------
+        coderank_hits: list[tuple[int, float]] = []
+        coderank_limit = max(effective_limit * context.settings.limits.semantic_overfetch_multiplier, effective_limit)  # type: ignore[attr-defined]
+        if use_coderank:
+            cr_cfg = context.settings.coderank
+            cr_paths = context.paths
+            if not cr_paths.coderank_faiss_index.exists():
+                # Fallback transparently to existing semantic adapter if CodeRank is not yet built
+                observation.mark_error()
+                raise VectorSearchError(
+                    "CodeRank FAISS index not found; build it first with coderank CLI",
+                    context={"coderank_faiss_index": str(cr_paths.coderank_faiss_index)},
+                )
+            # Embed query (CodeRank requires instruction prefix)
+            embedder = CodeRankEmbedder(
+                model_id=cr_cfg.model_id,
+                device=cr_cfg.device,
+                trust_remote_code=cr_cfg.trust_remote_code,
+                query_prefix=cr_cfg.query_prefix,
+                normalize=cr_cfg.normalize,
+                batch_size=cr_cfg.batch_size,
+            )
+            try:
+                qvec = embedder.encode_queries([query])
+            except Exception as exc:  # noqa: BLE001
+                observation.mark_error()
+                raise EmbeddingError(f"CodeRank embedding failed: {exc}") from exc
+
+            # Search CodeRank FAISS
+            faiss_mgr = FAISSManager(
+                index_path=cr_paths.coderank_faiss_index,
+                vec_dim=qvec.shape[1],
+                nlist=context.settings.index.faiss_nlist,
+                use_cuvs=context.settings.index.use_cuvs,
+            )
+            try:
+                faiss_mgr.load_cpu_index()
+            except Exception as exc:  # noqa: BLE001
+                observation.mark_error()
+                raise VectorSearchError(f"CodeRank FAISS load failed: {exc}") from exc
+
+            try:
+                dists, ids = faiss_mgr.search(qvec, k=int(coderank_limit), nprobe=context.settings.index.faiss_nprobe)
+            except Exception as exc:  # noqa: BLE001
+                observation.mark_error()
+                raise VectorSearchError(f"CodeRank FAISS search failed: {exc}") from exc
+
+            # Flatten
+            coderank_hits = [(int(i), float(s)) for i, s in zip(ids[0].tolist(), dists[0].tolist()) if int(i) >= 0]
+
+        # ---------- Stage B: WARP/XTR rerank (late-interaction) ----------
+        warp_hits: list[tuple[int, float]] = []
+        warp_notes: list[str] = []
+        if use_warp and coderank_hits:
+            warp_cfg = context.settings.warp
+            try:
+                warp = WarpEngine(index_dir=context.paths.warp_index_dir, device=warp_cfg.device)
+                # Pass candidate IDs and raw query text; engine computes token-level matching
+                warp_ranked = warp.rerank(query=query, candidate_ids=[cid for cid, _ in coderank_hits], top_k=min(warp_cfg.top_k, len(coderank_hits)))
+                warp_hits = [(int(doc_id), float(score)) for doc_id, score in warp_ranked]
+            except WarpUnavailable as wu:
+                warp_notes.append(str(wu))
+            except Exception as exc:  # noqa: BLE001
+                warp_notes.append(f"WARP/XTR rerank failed: {exc}")
+
+        # ---------- Fuse (weighted RRF) ----------
+        fused_ids: list[int]
+        contribution_map: dict[int, list[tuple[str, int, float]]] = {}
+        if coderank_hits and warp_hits:
+            fused_ids, contribution_map = weighted_rrf(
+                channels={
+                    "coderank": coderank_hits,
+                    "warp": warp_hits,
+                },
+                weights=weights,
+                k=context.settings.index.rrf_k,
+                top_k=max(effective_limit * 2, effective_limit),
+            )
+        elif coderank_hits:
+            fused_ids = [cid for cid, _ in coderank_hits[: effective_limit * 2]]
+            for rank, (cid, score) in enumerate(coderank_hits[: effective_limit * 2], start=1):
+                contribution_map.setdefault(cid, []).append(("coderank", rank, score))
+        else:
+            fused_ids = []
+
+        # ---------- Hydrate previews for optional listwise rerank ----------
+        hydrated: list[dict] = []
+        if fused_ids:
+            with context.open_catalog() as catalog:
+                scope_languages = cast("Sequence[str] | None", scope.get("languages")) if scope else None
+                scope_include = cast("Sequence[str] | None", scope.get("include_globs")) if scope else None
+                scope_exclude = cast("Sequence[str] | None", scope.get("exclude_globs")) if scope else None
+                hydrated = catalog.query_by_filters(
+                    fused_ids,
+                    include_globs=list(scope_include) if scope_include else None,
+                    exclude_globs=list(scope_exclude) if scope_exclude else None,
+                    languages=list(scope_languages) if scope_languages else None,
+                )
+
+        # ---------- Optional listwise rerank with CodeRankLLM ----------
+        if use_reranker and hydrated:
+            llm_cfg = context.settings.coderank_llm
+            try:
+                reranker = CodeRankListwiseReranker(
+                    model_id=llm_cfg.model_id,
+                    device=llm_cfg.device,
+                    max_new_tokens=llm_cfg.max_new_tokens,
+                    temperature=llm_cfg.temperature,
+                    top_p=llm_cfg.top_p,
+                )
+                docs_for_rerank = [
+                    {
+                        "id": int(rec["id"]),
+                        "uri": str(rec.get("uri", "")),
+                        "text": (rec.get("content") or rec.get("preview") or "")[: SNIPPET_PREVIEW_CHARS],
+                    }
+                    for rec in hydrated
+                ]
+                reranked_ids = reranker.rerank(query=query, docs=docs_for_rerank, top_k=effective_limit)
+                # Reorder hydrated accordingly
+                by_id = {int(rec["id"]): rec for rec in hydrated}
+                hydrated = [by_id[i] for i in reranked_ids if i in by_id]
+            except Exception as exc:  # noqa: BLE001
+                LOGGER.warning("CodeRankLLM rerank failed; continuing without it", extra={"error": str(exc)})
+
+        # ---------- Truncate and format findings ----------
+        findings: list[Finding] = []
+        for rec in hydrated[:effective_limit]:
+            preview = (rec.get("content") or rec.get("preview") or "")[: SNIPPET_PREVIEW_CHARS]
+            finding: Finding = {
+                "uri": str(rec.get("uri", "")),
+                "start_line": int(rec.get("start_line") or 0),
+                "end_line": int(rec.get("end_line") or 0),
+                "preview": preview,
+                "chunk_id": int(rec.get("id")),
+            }
+            if explain:
+                cid = int(rec.get("id"))
+                contrib = contribution_map.get(cid, [])
+                if contrib:
+                    parts = [f"{ch} rank={rk}" for ch, rk, _ in contrib]
+                    finding["why"] = "Weighted RRF: " + ", ".join(parts)
+            findings.append(finding)
+
+        # ---------- Envelope ----------
+        method = _build_method(
+            count=len(findings),
+            requested=requested_limit,
+            effective=effective_limit,
+            start_time=start_time,
+            channels=["coderank"] + (["warp"] if warp_hits else []),
+            notes=trunc_msgs,
+            warp_notes=warp_notes,
+        )
+        extras = {"limits": trunc_msgs, "method": method}
+        if scope:
+            extras["scope"] = scope
+        observation.mark_success()
+
+        return {
+            "findings": findings,
+            "answer": f"Found {len(findings)} results (two-stage) for: {query}",
+            "confidence": 0.9 if findings else 0.0,
+            **extras,
+        }
+
+
+def _build_method(
+    count: int,
+    requested: int,
+    effective: int,
+    start_time: float,
+    channels: Sequence[str],
+    notes: Sequence[str],
+    warp_notes: Sequence[str],
+) -> MethodInfo:
+    duration = perf_counter() - start_time
+    return {
+        "retrieval": {
+            "count": count,
+            "requested_limit": requested,
+            "effective_limit": effective,
+            "channels": list(channels),
+            "notes": list(notes) + (["; ".join(warp_notes)] if warp_notes else []),
+            "duration_s": duration,
+        }
+    }
```

---

### 5) **New** `codeintel_rev/io/coderank_embedder.py`

```diff
*** /dev/null
--- b/codeintel_rev/io/coderank_embedder.py
@@
+from __future__ import annotations
+
+import threading
+from typing import Iterable
+
+import numpy as np
+
+try:  # pragma: no cover
+    from sentence_transformers import SentenceTransformer
+except Exception as _exc:  # pragma: no cover
+    SentenceTransformer = None  # type: ignore[assignment]
+
+from kgfoundry_common.logging import get_logger
+
+LOGGER = get_logger(__name__)
+
+
+class CodeRankEmbedder:
+    """Thin pooled wrapper around `nomic-ai/CodeRankEmbed` for queries/codes.
+
+    Notes
+    -----
+    Model card requires the query instruction prefix:
+    "Represent this query for searching relevant code: ..."  :contentReference[oaicite:9]{index=9}
+    """
+
+    _lock = threading.Lock()
+    _model = None
+
+    def __init__(
+        self,
+        *,
+        model_id: str,
+        device: str = "cpu",
+        trust_remote_code: bool = True,
+        query_prefix: str,
+        normalize: bool = True,
+        batch_size: int = 128,
+    ) -> None:
+        if SentenceTransformer is None:
+            raise RuntimeError("sentence-transformers is required for CodeRankEmbed")
+        self.model_id = model_id
+        self.device = device
+        self.trust_remote_code = trust_remote_code
+        self.query_prefix = query_prefix
+        self.normalize = normalize
+        self.batch_size = batch_size
+        self._ensure_loaded()
+
+    def _ensure_loaded(self) -> None:
+        with self._lock:
+            if self.__class__._model is None:
+                LOGGER.info("Loading CodeRankEmbed model %s on %s", self.model_id, self.device)
+                model = SentenceTransformer(self.model_id, trust_remote_code=self.trust_remote_code, device=self.device)
+                self.__class__._model = model
+
+    @property
+    def model(self):
+        m = self.__class__._model
+        assert m is not None
+        return m
+
+    def encode_queries(self, queries: Iterable[str]) -> np.ndarray:
+        q = [self.query_prefix + (q or "") for q in queries]
+        vecs = self.model.encode(q, normalize_embeddings=self.normalize, batch_size=self.batch_size)
+        return np.array(vecs, dtype=np.float32).reshape(len(q), -1)
+
+    def encode_codes(self, snippets: Iterable[str]) -> np.ndarray:
+        vecs = self.model.encode(list(snippets), normalize_embeddings=self.normalize, batch_size=self.batch_size)
+        return np.array(vecs, dtype=np.float32).reshape(-1, vecs[0].shape[-1] if vecs else 0)
```

---

### 6) **New** `codeintel_rev/io/warp_engine.py`

```diff
*** /dev/null
--- b/codeintel_rev/io/warp_engine.py
@@
+from __future__ import annotations
+
+from pathlib import Path
+from typing import Iterable, Sequence
+
+from kgfoundry_common.logging import get_logger
+
+LOGGER = get_logger(__name__)
+
+
+class WarpUnavailable(RuntimeError):
+    """Raised when WARP/XTR is not available on this system."""
+
+
+class WarpEngine:
+    """Light wrapper around WARP/XTR late-interaction executor.
+
+    This tries to import the xtr-warp engine; if unavailable, raises WarpUnavailable
+    with guidance to build the engine from source.
+
+    Reference implementation and build instructions: jlscheerer/xtr-warp. :contentReference[oaicite:10]{index=10}
+    """
+
+    def __init__(self, *, index_dir: Path, device: str = "cpu") -> None:
+        self.index_dir = Path(index_dir)
+        if not self.index_dir.exists():
+            raise WarpUnavailable(f"WARP index directory not found: {self.index_dir}")
+
+        try:  # pragma: no cover - optional dependency
+            # Import symbol names defensively; upstream may change APIs
+            from xtr_warp.executor import WarpExecutor  # type: ignore[import-not-found]
+        except Exception as exc:  # noqa: BLE001
+            raise WarpUnavailable(
+                f"WARP engine not installed. Build xtr-warp and ensure it is importable: {exc}"
+            ) from exc
+
+        self._executor_cls = WarpExecutor  # type: ignore[attr-defined]
+        self._device = device
+        # Lazily create executor to keep cold path cheap
+        self._executor = None
+
+    def _ensure_executor(self):
+        if self._executor is not None:
+            return self._executor
+        # NB: API guess — consult repo for exact constructor; wrapper isolates changes
+        self._executor = self._executor_cls(index_dir=str(self.index_dir), device=self._device)  # type: ignore[call-arg]
+        return self._executor
+
+    def rerank(self, *, query: str, candidate_ids: Sequence[int], top_k: int) -> list[tuple[int, float]]:
+        ex = self._ensure_executor()
+        # API contract: returns list of (doc_id, score)
+        try:
+            results = ex.search(query=query, candidates=list(map(int, candidate_ids)), top_k=int(top_k))  # type: ignore[attr-defined]
+        except AttributeError:
+            # If API differs, provide a readable error
+            raise WarpUnavailable("WARP Python API changed; update `WarpEngine` adapter.")
+        # Normalize return shape
+        out: list[tuple[int, float]] = []
+        for item in results:
+            # Accept dicts or tuples
+            if isinstance(item, dict):
+                out.append((int(item.get("doc_id")), float(item.get("score", 0.0))))
+            else:
+                doc_id, score = item
+                out.append((int(doc_id), float(score)))
+        return out
```

---

### 7) **New** `codeintel_rev/io/rerank_coderankllm.py`

```diff
*** /dev/null
--- b/codeintel_rev/io/rerank_coderankllm.py
@@
+from __future__ import annotations
+
+import json
+from typing import Iterable, Sequence
+
+from kgfoundry_common.logging import get_logger
+
+LOGGER = get_logger(__name__)
+
+try:  # pragma: no cover
+    from transformers import AutoModelForCausalLM, AutoTokenizer
+except Exception as _exc:  # pragma: no cover
+    AutoModelForCausalLM = None  # type: ignore[assignment]
+    AutoTokenizer = None  # type: ignore[assignment]
+
+
+_PROMPT = """You are a code retrieval reranker. Given a QUERY and a list of CODE CANDIDATES,
+return a JSON list of candidate IDs ordered from best to worst for answering the query.
+Only output JSON (no prose). Example: [12, 5, 9]
+
+QUERY:
+{query}
+
+CANDIDATES:
+{candidates_json}
+"""
+
+
+class CodeRankListwiseReranker:
+    """Listwise reranker using `nomic-ai/CodeRankLLM`."""
+
+    def __init__(
+        self,
+        *,
+        model_id: str,
+        device: str = "cpu",
+        max_new_tokens: int = 256,
+        temperature: float = 0.0,
+        top_p: float = 1.0,
+    ) -> None:
+        if AutoModelForCausalLM is None or AutoTokenizer is None:
+            raise RuntimeError("transformers is required for CodeRankLLM reranking")
+        LOGGER.info("Loading CodeRankLLM %s on %s", model_id, device)
+        self._tok = AutoTokenizer.from_pretrained(model_id)
+        self._model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype="auto", device_map=device)
+        self._gen_kwargs = dict(max_new_tokens=max_new_tokens, temperature=temperature, top_p=top_p)
+
+    def rerank(self, *, query: str, docs: Sequence[dict], top_k: int) -> list[int]:
+        """Return ordered doc IDs (best→worst)."""
+        # Trim texts for safety; model supports long contexts but keep reasonable
+        cleaned = [{"id": int(d["id"]), "uri": d.get("uri", ""), "text": (d.get("text") or "")[:2048]} for d in docs]
+        prompt = _PROMPT.format(query=query, candidates_json=json.dumps(cleaned, ensure_ascii=False))
+        inputs = self._tok(prompt, return_tensors="pt").to(self._model.device)
+        out = self._model.generate(**inputs, **self._gen_kwargs)
+        text = self._tok.decode(out[0], skip_special_tokens=True)
+        # Extract trailing JSON
+        last_bracket = text.rfind("]")
+        first_bracket = text.rfind("[", 0, last_bracket + 1)
+        ordered: list[int] = []
+        if first_bracket >= 0 and last_bracket > first_bracket:
+            try:
+                ordered = [int(x) for x in json.loads(text[first_bracket:last_bracket + 1])]
+            except Exception:  # noqa: BLE001
+                LOGGER.warning("CodeRankLLM returned unparsable output; keeping original order")
+        if not ordered:
+            ordered = [int(d["id"]) for d in cleaned]
+        return ordered[:top_k]
```

---

### 8) **New** `codeintel_rev/io/rrf.py`

```diff
*** /dev/null
--- b/codeintel_rev/io/rrf.py
@@
+from __future__ import annotations
+from typing import Mapping, Sequence
+
+def weighted_rrf(
+    *,
+    channels: Mapping[str, Sequence[tuple[int, float]]],
+    weights: Mapping[str, float],
+    k: int = 60,
+    top_k: int = 50,
+) -> tuple[list[int], dict[int, list[tuple[str, int, float]]]]:
+    """Weighted Reciprocal Rank Fusion.
+
+    Parameters
+    ----------
+    channels : map channel -> list[(doc_id, score)] with implicit ranks by order
+    weights : map channel -> float weight multiplier
+    k : small constant for RRF
+    top_k : number of fused doc IDs to return
+    """
+    scores: dict[int, float] = {}
+    contrib: dict[int, list[tuple[str, int, float]]] = {}
+    for name, hits in channels.items():
+        w = float(weights.get(name, 1.0))
+        for rank, (doc_id, raw_score) in enumerate(hits, start=1):
+            s = w * (1.0 / (k + rank))
+            scores[doc_id] = scores.get(doc_id, 0.0) + s
+            contrib.setdefault(doc_id, []).append((name, rank, float(raw_score)))
+    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
+    fused_ids = [doc_id for doc_id, _ in ordered[:top_k]]
+    return fused_ids, contrib
```

---

### 9) **Optional new CLI** `coderank.py` — build CodeRank FAISS from DuckDB chunks

```diff
*** /dev/null
--- b/coderank.py
@@
+"""CLI to build a FAISS index using CodeRankEmbed over DuckDB chunks."""
+from __future__ import annotations
+
+from pathlib import Path
+from typing import cast
+
+import numpy as np
+import typer
+
+from codeintel_rev.app.config_context import resolve_application_paths
+from codeintel_rev.config.settings import Settings, load_settings
+from codeintel_rev.io.coderank_embedder import CodeRankEmbedder
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.io.duckdb_manager import DuckDBManager
+from codeintel_rev.io.faiss_manager import FAISSManager
+
+app = typer.Typer(add_completion=False, no_args_is_help=True)
+
+
+@app.command("build-index")
+def build_index() -> None:
+    settings: Settings = load_settings()
+    paths = resolve_application_paths(settings)
+    cfg = settings.coderank
+    embedder = CodeRankEmbedder(
+        model_id=cfg.model_id,
+        device=cfg.device,
+        trust_remote_code=cfg.trust_remote_code,
+        query_prefix=cfg.query_prefix,
+        normalize=cfg.normalize,
+        batch_size=cfg.batch_size,
+    )
+    cat = DuckDBCatalog(paths.duckdb_path, paths.vectors_dir, manager=DuckDBManager(paths.duckdb_path))
+    cat.open()
+    try:
+        with cat.connection() as conn:
+            rows = conn.sql("SELECT id, content FROM chunks ORDER BY id").fetchall()
+        ids = [int(r[0]) for r in rows]
+        texts = [cast(str, (r[1] or "")) for r in rows]
+    finally:
+        cat.close()
+    if not ids:
+        typer.echo("No chunks found in DuckDB catalog.")
+        raise typer.Exit(1)
+    # Embed in batches
+    vecs = embedder.encode_codes(texts)
+    mgr = FAISSManager(index_path=paths.coderank_faiss_index, vec_dim=vecs.shape[1], nlist=settings.index.faiss_nlist, use_cuvs=settings.index.use_cuvs)
+    mgr.build_index(vecs)
+    mgr.add_vectors(vecs, np.array(ids, dtype=np.int64))
+    mgr.save_cpu_index()
+    typer.echo(f"Built CodeRank FAISS at {paths.coderank_faiss_index} (n={len(ids)})")
+
+
+def main() -> None:  # pragma: no cover
+    app()
+
+
+if __name__ == "__main__":  # pragma: no cover
+    main()
```

---

## How to try it

1. **Install optional deps** (add to your env/requirements as needed):

```bash
pip install sentence-transformers transformers
# For FAISS CPU (if not already): pip install faiss-cpu
# For FAISS GPU: pip install faiss-gpu-cu12  # match your CUDA
```

2. **Build CodeRank FAISS**:

```bash
python -m coderank build-index
```

This reads chunk texts from your DuckDB catalog and writes vectors + FAISS at `paths.coderank_faiss_index`.

> **Remember:** CodeRank requires the instruction prefix for **queries**. The embedder enforces this as per the model card’s “Usage” section. ([Hugging Face][1])

3. **(Optional) Build WARP/XTR index**:

* Follow **xtr-warp** instructions to compile and index your chunks into `indexes/warp_xtr`. The wrapper provides readable errors and path hints when not present. ([GitHub][5])
* WARP’s design goals and XTR rationale are summarized by Weaviate’s announcement and the XTR paper; the latency/memory improvements are why this is a parallel channel in our fusion. ([Weaviate Documentation][2])

4. **Enable channels via env**:

```bash
# optional: turn on warp and/or reranker
export WARP_ENABLED=1
export CODERANK_LLM_ENABLED=0   # set 1 to test reranker
# optionally switch devices
export CODERANK_DEVICE=cpu
export WARP_DEVICE=cpu
export CODERANK_LLM_DEVICE=cpu
```

5. **Call the new MCP tool**:

```
search:semantic_pro
  query="How is FAISS GPU clone attempted?"
  limit=20
  use_coderank=true
  use_warp=true
  use_reranker=false
  stage_weights={"coderank":1.0,"warp":1.25}
  explain=true
```

You’ll get a response envelope consistent with your current schema, including `method.retrieval.channels` and optional `why` per finding, mirroring the style in your existing adapter. 

---

## Notes & rationale (brief)

* **CPU‑first defaults** for WARP and the reranker match your decision to keep experimental channels opt‑in; toggles are runtime flags, not required at startup.
* The **CodeRank** stage uses a **code‑specific tokenizer & encoder** (per model card) and obeys the **prompt prefix requirement**, which is the single most important gotcha for correctness. ([Hugging Face][1])
* **WARP/XTR** is isolated behind a small adapter: if the upstream Python API changes, you update one file. The wrapper reports “unavailable” as a **soft limit** so your MCP tool still returns useful results. ([GitHub][5])
* **Listwise rerank** stays conservative: deterministic generation (temp=0) and strict JSON extraction. The model card emphasizes listwise ranking; that’s how we structure the prompt. ([Hugging Face][4])
* **Weighted RRF** lets you tune contribution by query class (e.g., error messages → upweight sparse/lexical later; function names → upweight late‑interaction). The helper is generic and re‑usable in your existing `HybridSearchEngine` in a future PR.

---

### What remains (follow‑ups I can ship next)

* **WARP index builder CLI** that exports token‑level (XTR) collections from DuckDB chunks, producing the `indexes/warp_xtr` directory the wrapper expects. (Depends on the exact CLI/API surface of `xtr-warp`.) ([GitHub][5])
* **Learned weights** for fusion (per corpus or per query features), and **query‑class heuristics** (regexes for stacktraces vs function queries) to auto‑select channel weights.
* **Eval harness**: nDCG@10 and recall@k for ablations (CodeRank only vs CodeRank+WARP vs +LLM).

If you want, I can now prepare a small **smoke test** (unit tests) for the adapter paths that don’t require WARP to be installed, and a guarded test that’s skipped unless a WARP index is detected on disk.

---

### Sources

* CodeRankEmbed model card (usage; instruction prefix; Q→code pipeline). ([Hugging Face][1])
* CodeRankLLM model card (listwise reranking overview/training). ([Hugging Face][4])
* Weaviate’s WARP announcement (motivation; performance headline). ([Weaviate Documentation][2])
* XTR (Extreme Text Representations) research page (late‑interaction compression rationale). ([arXiv][3])
* xtr‑warp GitHub repository (reference engine & build). ([GitHub][5])

---

> If you’d like me to also tailor **migration notes** for ops (env vars, systemd probes, GPU warmup, etc.) or wire the new CLI into your existing `tools/` handlers (matching `bm25.py`/`splade.py` style) I can draft those next.

[1]: https://huggingface.co/nomic-ai/CodeRankEmbed "nomic-ai/CodeRankEmbed · Hugging Face"
[2]: https://docs.weaviate.io/weaviate/client-libraries/python?utm_source=chatgpt.com "Python | Weaviate Documentation"
[3]: https://arxiv.org/html/2501.17788v1?utm_source=chatgpt.com "An Efficient Engine for Multi-Vector Retrieval - WARP"
[4]: https://huggingface.co/nomic-ai/CodeRankLLM "nomic-ai/CodeRankLLM · Hugging Face"
[5]: https://github.com/jlscheerer/xtr-warp "GitHub - jlscheerer/xtr-warp: XTR/WARP (SIGIR'25) is an extremely fast and accurate retrieval engine based on Stanford's ColBERTv2/PLAID and Google DeepMind's XTR."


# APPENDIX - BACKGROUND INFORMATION INSTRUCTIONS ABOVE #a

Outstanding — let’s ship the **drop‑in patches**. Below you’ll find a set of new modules and small edits that wire up:

* **Stage‑1 (bi‑encoder)**: `nomic-ai/CodeRankEmbed` with automatic **query‑prefix enforcement**, FAISS‑GPU indexing & search. ([Hugging Face][1])
* **Stage‑2 (late‑interaction)**: XTR‑style **multi‑vector** retrieval using the **WARP** engine (GPU‑centric build, **CPU‑default retrieval**). Where WARP Python bindings aren’t present, the code raises a clear, actionable error and points to the upstream repo. ([GitHub][2])
* **(Optional) Stage‑3 (listwise rerank)**: `nomic-ai/CodeRankLLM`, returning a **strict JSON** ordering of the shortlist. ([Hugging Face][3])
* **Fusion & gates**: **Weighted‑RRF** + margin/entropy gating. RRF is the pragmatic, proven rank‑fusion baseline. ([G. V. Cormack][4])
* **GPU vector infra**: FAISS‑GPU with OPQ/IVF‑PQ, and optional **cuVS** acceleration where available (kept behind settings; zero‑code‑change if `faiss-gpu-cuvs` is installed). ([NVIDIA Developer][5])

> **Install dependencies (suggested):**
>
> ```bash
> pip install "faiss-gpu>=1.10.0" "sentence-transformers>=3.0.0" "transformers>=4.44" "accelerate" "bitsandbytes" "orjson" "pydantic>=2"
> # Optional (faster GPU FAISS builds and searches)
> pip install "faiss-gpu-cuvs"  # enables cuVS under Faiss automatically. :contentReference[oaicite:5]{index=5}
> # WARP engine (build from source)
> git clone https://github.com/jlscheerer/xtr-warp && cd xtr-warp && pip install -e .
> ```
>
> WARP **builds indexes best on GPU**; **retrieval is CPU‑optimized by default** per the authors. We expose both as settings knobs. ([GitHub][2])

---

## 1) New core types & utilities

**`codeintel_rev/retrieval/types.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Protocol

@dataclass(slots=True, frozen=True)
class WhyAttribution:
    channel: Literal["biencoder", "warp", "splade", "bm25", "reranker"]
    details: dict  # e.g. {"score": 0.73, "token_pairs": [...], "path": "src/x.py"}

@dataclass(slots=True, frozen=True)
class Hit:
    chunk_id: int
    score: float
    why: list[WhyAttribution]

class Retriever(Protocol):
    def search(
        self,
        query: str,
        k: int,
        *,
        budget_ms: int,
        candidates: list[Hit] | None = None,  # for Stage-2 rescore
    ) -> list[Hit]: ...
    def explain(self) -> bool: ...

class Reranker(Protocol):
    def rerank(
        self,
        query: str,
        docs: list[str],
        top_n: int,
        *,
        budget_ms: int,
    ) -> list[int]: ...
```

**`codeintel_rev/retrieval/fusion/weighted_rrf.py`**

```python
from __future__ import annotations
from collections import defaultdict
from typing import Mapping, Sequence
from codeintel_rev.retrieval.types import Hit, WhyAttribution

def weighted_rrf(
    ranked: Mapping[str, Sequence[Hit]],
    *,
    rrf_k: int = 60,
    weights: Mapping[str, float] | None = None,
    explain: bool = True,
) -> list[Hit]:
    weights = weights or {}
    accum: dict[int, float] = defaultdict(float)
    meta: dict[int, list[WhyAttribution]] = defaultdict(list)

    for channel, hits in ranked.items():
        w = float(weights.get(channel, 1.0))
        for rank, h in enumerate(hits, start=1):
            accum[h.chunk_id] += w * 1.0 / (rrf_k + rank)
            if explain:
                meta[h.chunk_id].extend(h.why)

    merged = [Hit(cid, score, meta.get(cid, [])) for cid, score in accum.items()]
    merged.sort(key=lambda h: h.score, reverse=True)
    return merged
```

**`codeintel_rev/retrieval/gating.py`**

```python
from __future__ import annotations
import math
from typing import Sequence
from codeintel_rev.retrieval.types import Hit

def entropy(scores: Sequence[float]) -> float:
    s = sum(scores) or 1e-9
    p = [x / s for x in scores]
    return -sum((x * math.log(x + 1e-9)) for x in p)

def should_refine_with_warp(
    s1_hits: Sequence[Hit],
    *,
    margin_threshold: float = 0.07,
    min_conf: float = 0.45,
) -> bool:
    if not s1_hits:
        return True
    scores = [max(1e-9, h.score) for h in s1_hits[:10]]
    margin = (scores[0] - scores[1]) if len(scores) > 1 else scores[0]
    conf = scores[0]
    ent = entropy(scores)
    # Run WARP if confidence is low or ranking is uncertain
    return (margin < margin_threshold or conf < min_conf) or ent > 1.6
```

**`codeintel_rev/retrieval/telemetry.py`**

```python
from __future__ import annotations
import time
from contextlib import contextmanager

@contextmanager
def timer_ms():
    t0 = time.perf_counter()
    yield lambda: (time.perf_counter() - t0) * 1000.0
```

---

## 2) Stage‑1 retriever — CodeRankEmbed (bi‑encoder, FAISS‑GPU)

> The model card requires that every query include the instruction prefix:
> **“Represent this query for searching relevant code:”** — we enforce it transparently. ([Hugging Face][1])

**`codeintel_rev/retrievers/biencoder_coderank.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from codeintel_rev.retrieval.types import Hit, WhyAttribution, Retriever

PREFIX = "Represent this query for searching relevant code: "  # required by model card. :contentReference[oaicite:8]{index=8}

@dataclass(slots=True)
class BiencoderSettings:
    model: str = "nomic-ai/CodeRankEmbed"
    require_prefix: bool = True
    index_path: str = ""
    k1: int = 600

class CodeRankBiencoder(Retriever):
    def __init__(self, cfg: BiencoderSettings):
        self.cfg = cfg
        self.model = SentenceTransformer(cfg.model, trust_remote_code=True)  # loads 137M bi-encoder. :contentReference[oaicite:9]{index=9}
        # faiss.index must be built by indexing step; we only load for search:
        self.index = faiss.read_index(self.cfg.index_path)
        faiss.downcast_Index(self.index)
        res = faiss.StandardGpuResources()
        self.gpu_index = faiss.index_cpu_to_gpu(res, 0, self.index)

    def _prefix_guard(self, q: str) -> str:
        if not self.cfg.require_prefix:
            return q
        q_stripped = q.strip()
        return q_stripped if q_stripped.startswith(PREFIX) else (PREFIX + q_stripped)

    def explain(self) -> bool:  # lightweight only
        return False

    def search(
        self, query: str, k: int, *, budget_ms: int, candidates: Sequence[Hit] | None = None
    ) -> list[Hit]:
        qtext = self._prefix_guard(query)
        qv = self.model.encode([qtext], convert_to_numpy=True, normalize_embeddings=True)  # cosine sim
        D, I = self.gpu_index.search(qv.astype(np.float32), k or self.cfg.k1)
        hits: list[Hit] = []
        for score, cid in zip(D[0].tolist(), I[0].tolist()):
            if cid < 0:
                continue
            hits.append(Hit(chunk_id=int(cid), score=float(score), why=[
                WhyAttribution(channel="biencoder", details={"score": float(score)})
            ]))
        return hits
```

**Index builder (script)** — `codeintel_rev/indexing/build_biencoder.py`

```python
from __future__ import annotations
from dataclasses import dataclass
import faiss, numpy as np
from sentence_transformers import SentenceTransformer
from typing import Iterable

@dataclass(slots=True)
class BiencoderBuildConfig:
    model: str = "nomic-ai/CodeRankEmbed"
    vectors_out: str = "indexes/biencoder/faiss.index"
    dim: int | None = None
    nlist: int = 4096
    pq_m: int = 16
    pq_bits: int = 8

def build_faiss_gpu(vectors: np.ndarray, cfg: BiencoderBuildConfig) -> faiss.IndexIVFPQ:
    d = vectors.shape[1]
    quant = faiss.IndexFlatIP(d)
    index = faiss.IndexIVFPQ(quant, d, cfg.nlist, cfg.pq_m, cfg.pq_bits)
    res = faiss.StandardGpuResources()
    gpu_index = faiss.index_cpu_to_gpu(res, 0, index)
    gpu_index.train(vectors)
    gpu_index.add(vectors)
    index2 = faiss.index_gpu_to_cpu(gpu_index)
    faiss.write_index(index2, cfg.vectors_out)
    return index2

def embed_corpus(chunks: Iterable[str], model_id: str) -> np.ndarray:
    m = SentenceTransformer(model_id, trust_remote_code=True)
    X = m.encode(list(chunks), convert_to_numpy=True, normalize_embeddings=True)
    return X.astype("float32")

# Integrate this function into your pipeline: supply chunk texts in the same id order as DuckDB.
```

> If `faiss-gpu-cuvs` is available, Faiss v1.10 can leverage **cuVS** under the hood for faster IVF build/search automatically—no code changes needed. ([NVIDIA Developer][5])

---

## 3) Stage‑2 retriever — WARP (XTR‑style late‑interaction)

> WARP brings **dynamic similarity imputation (WARPSELECT)**, **implicit decompression**, and a **two‑stage reduction** that accelerate XTR‑style late interaction by large margins (≈**41×** vs an XTR reference, ≈**3×** vs PLAID), while matching quality; authors recommend **GPU for index build**, **CPU for retrieval**. ([arXiv][6])

**`codeintel_rev/retrievers/warp_xtr.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence

from codeintel_rev.retrieval.types import Hit, WhyAttribution, Retriever

@dataclass(slots=True)
class WarpSettings:
    index_root: str
    search_mode: str = "rescore_k1"  # "rescore_k1" | "global"
    k2: int = 200
    retrieval_device: str = "cpu"    # default per WARP authors. :contentReference[oaicite:12]{index=12}

class WarpXTR(Retriever):
    def __init__(self, cfg: WarpSettings):
        self.cfg = cfg
        try:
            # NOTE: replace with the actual Python API from xtr-warp once installed.
            from xtr_warp import WarpSearcher  # noqa: F401
            self._engine = self._load_engine(cfg)
        except Exception as e:
            raise RuntimeError(
                "WARP engine is not available. Install and build from https://github.com/jlscheerer/xtr-warp"
            ) from e

    def _load_engine(self, cfg: WarpSettings):
        # Pseudocode — adapt to actual xtr-warp API when available
        # return WarpSearcher(index_root=cfg.index_root, device=cfg.retrieval_device)
        return object()

    def explain(self) -> bool:
        return True

    def _align_pairs(self, doc_id: int, top_m: int = 8) -> list[dict]:
        # Pseudocode: ask engine for top query↔doc token matches and spans
        # return [{"q":"tokenA","d":"tokenA","score":0.91,"uri":"...","line":42}, ...]
        return []

    def _warp_rescore(self, query: str, cands: Sequence[Hit], k: int) -> list[Hit]:
        # Pseudocode: encode query tokens; ask engine to rescore specific doc ids
        # scores = self._engine.rescore(query, [h.chunk_id for h in cands], k=k)
        scores = [(h.chunk_id, h.score) for h in cands]  # placeholder
        hits: list[Hit] = []
        for cid, s in scores[:k]:
            hits.append(Hit(chunk_id=cid, score=float(s), why=[
                WhyAttribution(channel="warp", details={
                    "score": float(s),
                    "pairs": self._align_pairs(cid)
                })
            ]))
        return hits

    def _warp_global(self, query: str, k: int) -> list[Hit]:
        # Pseudocode: encode query tokens; run ANN over full shard
        # results = self._engine.search(query, k=k)
        results = []  # placeholder
        return [Hit(chunk_id=r.docid, score=r.score, why=[
            WhyAttribution(channel="warp", details={"score": r.score, "pairs": self._align_pairs(r.docid)})
        ]) for r in results]

    def search(
        self, query: str, k: int, *, budget_ms: int, candidates: Sequence[Hit] | None = None
    ) -> list[Hit]:
        if self.cfg.search_mode == "rescore_k1" and candidates:
            return self._warp_rescore(query, candidates, k or self.cfg.k2)
        return self._warp_global(query, k or self.cfg.k2)
```

**Index builder (driver)** — `codeintel_rev/indexing/build_warp.py`

```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(slots=True)
class WarpBuildConfig:
    index_root: str = "indexes/warp"
    build_device: str = "cuda"  # GPU strongly recommended for index construction. :contentReference[oaicite:13]{index=13}
    model_name: str = "<xtr-reference-encoder>"  # XTR-compatible retriever; fine-tune later.

def build_warp_index(cfg: WarpBuildConfig, chunk_iterator):
    """
    :param chunk_iterator: yields { "id": int, "text": str, "uri": str, ... }
    This function is a thin Python wrapper; use xtr-warp library's builder once installed.
    """
    try:
        from xtr_warp import WarpIndexer  # hypothetical API
    except Exception as e:
        raise RuntimeError("Install/build xtr-warp from https://github.com/jlscheerer/xtr-warp") from e
    # Pseudocode:
    # indexer = WarpIndexer(cfg.index_root, model=cfg.model_name, device=cfg.build_device)
    # for item in chunk_iterator: indexer.add(item["id"], item["text"], meta=item)
    # indexer.finalize()
```

> The **WARP** README describes the **installation** and emphasizes **CPU‑optimized retrieval** with **GPU‑accelerated index build**; integrate the engine calls above when the Python API is available or wrap its CLI. ([GitHub][2])

---

## 4) Optional Stage‑3 — CodeRankLLM listwise reranker

> Designed to sit on top of **CodeRankEmbed** candidates; returns significantly better lists on code retrieval tasks according to the model card & CoRNStack work. ([Hugging Face][3])

**`codeintel_rev/rerankers/prompts.py`**

```python
LISTWISE_PROMPT = """You are a code search reranker.
Query: {query}

Candidates (index: path :: symbol :: preview):
{candidates}

Return a JSON list of indices in best-to-worst order, e.g. [2,0,1].
"""
```

**`codeintel_rev/rerankers/coderank_llm.py`**

```python
from __future__ import annotations
import json, re, textwrap
from dataclasses import dataclass
from typing import Sequence
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
from codeintel_rev.rerankers.prompts import LISTWISE_PROMPT

@dataclass(slots=True)
class CodeRankLLMSettings:
    model: str = "nomic-ai/CodeRankLLM"
    device: str = "cuda"
    max_new_tokens: int = 256
    top_n: int = 30

class CodeRankLLM:
    def __init__(self, cfg: CodeRankLLMSettings):
        self.cfg = cfg
        self.tok = AutoTokenizer.from_pretrained(cfg.model, trust_remote_code=True)
        self.lm = AutoModelForCausalLM.from_pretrained(
            cfg.model, torch_dtype=torch.bfloat16, device_map="auto"
        )  # fits on a modern 24–48GB GPU; adjust quantization if needed. :contentReference[oaicite:16]{index=16}

    def rerank(self, query: str, docs: Sequence[str], top_n: int, *, budget_ms: int) -> list[int]:
        # Prepare compact list (index :: preview)
        items = []
        for i, d in enumerate(docs[:top_n]):
            preview = textwrap.shorten(d.replace("\n", " "), width=320, placeholder=" …")
            items.append(f"[{i}] :: {preview}")
        prompt = LISTWISE_PROMPT.format(query=query, candidates="\n".join(items))
        inp = self.tok(prompt, return_tensors="pt").to(self.lm.device)
        with torch.inference_mode():
            out = self.lm.generate(**inp, max_new_tokens=self.cfg.max_new_tokens, do_sample=False)
        text = self.tok.decode(out[0], skip_special_tokens=True)
        m = re.search(r"\[([0-9,\s]+)\]", text)
        if not m:
            return list(range(min(len(docs), top_n)))  # fallback
        try:
            return json.loads(m.group(0))
        except Exception:
            return list(range(min(len(docs), top_n)))
```

---

## 5) Orchestration (stages → fusion → hydrate)

**`codeintel_rev/retrieval/orchestration.py`**

```python
from __future__ import annotations
from typing import Mapping
from codeintel_rev.retrieval.types import Hit
from codeintel_rev.retrieval.gating import should_refine_with_warp
from codeintel_rev.retrieval.fusion.weighted_rrf import weighted_rrf

def run_pipeline(
    query: str,
    *,
    biencoder,
    warp,
    sparse: Mapping[str, object],
    cfg,
    hydrate_fn,   # function(chunk_ids: list[int]) -> hydrated results
    previews_fn,  # function(chunk_ids: list[int], max_chars: int) -> list[str]
) -> list:
    # Stage-1
    s1 = biencoder.search(query, k=cfg.stage1.k1, budget_ms=cfg.stage1.timeout_ms) if cfg.enable_biencoder else []

    # Stage-2 (gated)
    s2: list[Hit] = []
    if cfg.enable_warp and should_refine_with_warp(s1, margin_threshold=cfg.gate.threshold, min_conf=cfg.gate.min_conf):
        s2 = warp.search(query, k=cfg.stage2.k2, budget_ms=cfg.stage2.timeout_ms, candidates=s1 if cfg.stage2.search_mode=="rescore_k1" else None)

    # Parallel sparse (if any)
    sparse_hits: dict[str, list[Hit]] = {}
    for name, retr in sparse.items():
        sparse_hits[name] = retr.search(query, k=cfg.k_sparse, budget_ms=cfg.ms_sparse)

    fused = weighted_rrf({"biencoder": s1, "warp": s2, **sparse_hits}, rrf_k=cfg.fusion.rrf_k, weights=cfg.fusion.weights, explain=True)

    # Optional reranker (wired by caller to keep this orchestration simple)
    return hydrate_fn([h.chunk_id for h in fused[:cfg.k_hydrate]])
```

---

## 6) Minimal adapter hook (MCP semantic)

> In your `mcp_server/adapters/semantic.py`, import the orchestrator and new retrievers, wire them with your catalog’s hydrate/preview helpers, and return the hydrated findings. The precise patch depends on your file layout; here’s a **surgical example** (pseudo‑diff):

```diff
+ from codeintel_rev.retrieval.orchestration import run_pipeline
+ from codeintel_rev.retrievers.biencoder_coderank import CodeRankBiencoder, BiencoderSettings
+ from codeintel_rev.retrievers.warp_xtr import WarpXTR, WarpSettings
+ from codeintel_rev.rerankers.coderank_llm import CodeRankLLM, CodeRankLLMSettings

 def semantic_search(query: str, scope: ScopeIn, ...):
-    # existing dense + sparse
+    biencoder = CodeRankBiencoder(BiencoderSettings(model="nomic-ai/CodeRankEmbed",
+                                                   index_path=paths.biencoder_faiss))
+    warp = WarpXTR(WarpSettings(index_root=paths.warp_root, search_mode=settings.stage2.search_mode))
+    sparse = {}  # attach your SPLADE/BM25 retrievers here

+    results = run_pipeline(
+        query,
+        biencoder=biencoder,
+        warp=warp,
+        sparse=sparse,
+        cfg=settings.retrieval,
+        hydrate_fn=lambda ids: catalog.hydrate_by_ids(ids),
+        previews_fn=lambda ids, n: catalog.preview_many(ids, n),
+    )
+    return AnswerEnvelope(findings=results, method={"retrieval": ["biencoder","warp","splade","bm25"], "coverage": "..."} )
```

---

## 7) Notes on evaluation & tuning

* Use **COIR** harness (add `eval/coir_runner.py`) to compute **nDCG@10** and **Recall@50** for: Stage‑1 only; Stage‑2 only; Two‑stage; Two‑stage + sparse; + rerank. This is the most relevant up‑to‑date suite for code IR/reranking. ([Hugging Face][7])
* Keep **WARP retrieval on CPU by default** (robust, per upstream), **GPU for index build**; expose a single config knob to flip retrieval to GPU for experiments. ([GitHub][2])

---

## 8) What remains for WARP engine binding

* The code above **assumes a Python API** (e.g., `WarpIndexer`, `WarpSearcher`). If only a CLI is available, wrap it via `subprocess` and marshal scores/alignments through temp files.
* Follow the WARP paper’s and repo’s indexing/retrieval guidance to supply **token embeddings**, centroids/postings, and **doclens**. Key innovations—**WARPSELECT**, **implicit decompression**, **two‑stage reduction**—are the reason we can add late‑interaction without blowing the latency budget. ([arXiv][6])

---

### Why these choices are best‑in‑class (sources)

* **CodeRankEmbed**: bi‑encoder for code retrieval requiring a **query instruction prefix**, strong on COIR/CSN, 8k context. ([Hugging Face][1])
* **WARP/XTR**: SOTA multi‑vector engine & objective; **~41×** vs an XTR reference and **~3×** vs PLAID; CPU‑optimized retrieval, GPU‑build. ([Hugging Face][8])
* **Weighted‑RRF**: simple, robust rank fusion method validated across collections. ([G. V. Cormack][4])
* **CodeRankLLM**: 7B listwise reranker designed to sit atop CodeRankEmbed. ([Hugging Face][3])
* **cuVS under Faiss**: optional performance wins for IVF build/search on GPU with **no code change**. ([NVIDIA Developer][5])

---

## Ready to integrate

You can drop these files into your project under the suggested paths and:

1. Build Stage‑1 FAISS index (`indexing/build_biencoder.py`) against your chunk texts (in the same ID order as DuckDB).
2. Build Stage‑2 WARP index (`indexing/build_warp.py`) using the XTR reference encoder (we’ll swap to a code‑tuned XTR later). ([Hugging Face][1])
3. Wire `orchestration.run_pipeline` into your semantic adapter and expose toggles in your settings.
4. (Optional) Enable CodeRankLLM reranking, capped slate & strict‑JSON parsing.

If you’d like, I can now tailor the **exact diffs** for your repo structure (e.g., how to call your existing DuckDB catalog for previews/hydration, wire into your MCP tool schemas, and add Prometheus timers).

[1]: https://huggingface.co/nomic-ai/CodeRankEmbed?utm_source=chatgpt.com "nomic-ai/CodeRankEmbed"
[2]: https://github.com/jlscheerer/xtr-warp?utm_source=chatgpt.com "jlscheerer/xtr-warp"
[3]: https://huggingface.co/nomic-ai/CodeRankLLM?utm_source=chatgpt.com "nomic-ai/CodeRankLLM"
[4]: https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf?utm_source=chatgpt.com "Reciprocal Rank Fusion outperforms Condorcet and ..."
[5]: https://developer.nvidia.com/blog/enhancing-gpu-accelerated-vector-search-in-faiss-with-nvidia-cuvs/?utm_source=chatgpt.com "Enhancing GPU-Accelerated Vector Search in Faiss with ..."
[6]: https://arxiv.org/html/2501.17788v1?utm_source=chatgpt.com "An Efficient Engine for Multi-Vector Retrieval - WARP"
[7]: https://huggingface.co/nomic-ai/CodeRankLLM/discussions?utm_source=chatgpt.com "nomic-ai/CodeRankLLM · Discussions"
[8]: https://huggingface.co/nomic-ai/CodeRankEmbed/blob/1b6c1978d5308da3eb901b57d73cea914ebd6be8/README.md?utm_source=chatgpt.com "README.md · nomic-ai/CodeRankEmbed at ..."




Amazing — and I’m thrilled you’re aiming for **best‑in‑class**. Based on your frozen decisions and the latest research/impl guidance, here’s a **comprehensively detailed, Pythonic implementation plan** for a **two‑stage retrieval system**:

* **Stage 1 (fast)**: single‑vector bi‑encoder (**CodeRankEmbed**) for high‑recall candidate generation.
* **Stage 2 (precise)**: XTR‑style late‑interaction on the **WARP** engine for token‑level matching and top‑K refinement.
* **(Optional) Stage 3**: listwise LLM reranking (**CodeRankLLM**).
* **Parallel sparse channels** (SPLADE/BM25) fused via **Weighted‑RRF**.

This plan locks in GPU‑centric builds, code‑aware tokenization, XTR+WARP, budget gates, and rich explainability. WARP’s engine reduces end‑to‑end multi‑vector latency by **~41× vs XTR reference** and **~3× vs PLAID**, while CodeRankEmbed + CodeRankLLM are designed to pair for strong code retrieval and listwise reranking. ([arXiv][1]) ([arXiv][2]) ([Hugging Face][3])

---

## 0) Design recap (frozen)

* **GPU‑centric** (encode & build on GPU; WARP retrieval defaults to CPU per upstream guidance). ([GitHub][4])
* **Code‑specific tokenization**: keep model tokenizers intact; add a light pre‑tokenization layer (snake/camel/punct) to aid explanation and XTR alignment.
* **Late‑interaction**: **XTR objective** with **WARP** engine. ([arXiv][5])
* **Parallel channel**: WARP runs as a first‑class channel beside SPLADE/BM25 and the bi‑encoder.
* **Budgets**: Stage‑1=120 ms, Stage‑2=180 ms, Reranker=300 ms (tunable).
* **Explainability**: return token‑pair alignments and symbol spans from Stage‑2; lightweight scores from Stage‑1.
* **Two‑stage is switchable**: any stage can be off; knobs for “rescore‑K₁” vs “wide” WARP.

---

## 1) Pythonic architecture (clean, composable, testable)

```
codeintel_rev/
  retrieval/
    core/
      interfaces.py          # Retriever/Reranker Protocols, dataclasses
      fusion.py              # weighted_rrf(), score normalization
      gating.py              # margin/entropy/time gates
      telemetry.py           # stage timers, counters
    biencoder/               # Stage 1 (CodeRankEmbed)
      coderankembed_indexer.py
      coderankembed_searcher.py
      manifest.py
    warp_xtr/                # Stage 2 (XTR on WARP)
      warp_indexer.py
      warp_searcher.py
      manifest.py
    rerank/                  # Stage 3 (CodeRankLLM)
      coderankllm.py
      prompts.py
  io/
    manifests.py             # DuckDB-backed registry of all index manifests
  mcp_server/
    adapters/semantic.py     # Orchestration: S1 → (gate) S2 → fusion → (S3) → hydrate
```

**Core types** (Protocol‑first, dataclasses for records):

```python
# retrieval/core/interfaces.py
from dataclasses import dataclass
from typing import Protocol, Literal

@dataclass(frozen=True)
class WhyAttribution:
    channel: Literal["biencoder","warp","splade","bm25","reranker"]
    details: dict  # {"score": float, "token_pairs": [...], ...}

@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    score: float
    why: list[WhyAttribution]

class Retriever(Protocol):
    def search(self, query: str, k: int) -> list[SearchHit]: ...
    def explain(self) -> bool: ...

class Reranker(Protocol):
    def rerank(self, query: str, texts: list[str], top_n: int) -> list[int]: ...
```

* **Dependency injection** via settings: each channel reads its own section (model paths, k’s, timeouts, device).
* **Single responsibility**: indexers only build/persist; searchers only load/query; manifests record compatibility.
* **Observability**: every stage emits timers and “gate decisions” (why Stage‑2 ran or skipped).
* **Safety**: strict budgets, partial results if timeouts hit, and clean fallbacks.

---

## 2) Stage 1 — CodeRankEmbed bi‑encoder (fast candidate gen)

**Why this model:** 137 M **bi‑encoder** trained with **InfoNCE** on **CoRNStack**; supports **8192 context**; explicitly instructs that the query **must** carry a **task instruction prefix**:
`"Represent this query for searching relevant code: "`. We inject this automatically. Combine with CodeRankLLM for maximal quality. ([Hugging Face][3])

### Index build (GPU)

* **Tokenizer/Model**: load `nomic-ai/CodeRankEmbed` (`transformers`/SentenceTransformers). Enforce fp16 + `torch.inference_mode()` for throughput. ([Hugging Face][3])
* **Chunk embeddings**: embed symbol‑aware chunks (from your SCIP chunker), batch size tuned to GPU RAM.
* **Vector index**: FAISS IVFPQ/OPQ on **GPU** (or RAFT/cuVS if available for high‑speed build). Persist **manifest** (model name, dim, PQ/OPQ, nlist/nprobe, created_at). ([NVIDIA Developer][6])

### Query‑time (GPU)

* Prepend the required **instruction prefix** transparently; encode query; ANN **top‑K₁** (e.g., 500). ([Hugging Face][7])
* Compute a **gate signal**: `score_margin` (top‑1 − top‑2), entropy over top‑k, and Stage‑1 latency; pass to gating policy.

**Explainability (light)**: return normalized similarity plus a quick lexical sketch (shared identifiers). Keep cost near‑zero.

---

## 3) Stage 2 — XTR on WARP (late‑interaction refinement)

**Why WARP + XTR:** XTR reframes late‑interaction to **retrieve the most important tokens first**, then score using those tokens; WARP accelerates XTR with **WARPSELECT** (dynamic similarity imputation), **implicit decompression**, and **two‑stage reduction**, cutting latency **~41× vs XTR ref** and **~3× vs PLAID** while preserving quality. ([arXiv][5])

### Index build (GPU‑centric)

* **Encoder**: an **XTR‑compatible** retriever (reference weights to start; fine‑tune later on CoRNStack/COIR). ([arXiv][5])
* **Pre‑tokenization** (code‑aware, *non‑destructive*): split snake_case/camelCase and preserve `.` `::` `->` as tokens **before** model tokenization (for better alignment in explanations).
* **WARP artifacts**: build centroids/postings/residuals; **use GPU for build**; WARP’s README recommends **CPU for retrieval** by default (we expose a switch). ([GitHub][4])

**Manifest (stored in DuckDB + disk)**:

```json
{ "engine": "WARP", "objective": "XTR",
  "model": "<xtr-code-encoder>", "tokenizer": "code-aware",
  "build_device": "cuda", "retrieval_device": "cpu",
  "index_root": "...", "created_at": "..." }
```

### Query‑time (CPU default; GPU option)

* Encode query on GPU; run **WARP** in either mode:

  1. **rescore‑K₁**: refine just Stage‑1’s candidates (fast);
  2. **wide**: search a shard (e.g., per‑language) for recall.
* Return **top‑K₂** with **token‑level alignments** (best doc tokens per query token with scores) + **symbol spans (file, line, col)** for explainability. ([arXiv][8])

> *Why CPU default for WARP retrieval?* The upstream repo notes retrieval is **heavily optimized for CPU**, but **GPU is strongly recommended for index construction**; we follow that as the robust default, with a toggle to experiment with GPU retrieval later. ([GitHub][4])

---

## 4) (Optional) Stage 3 — CodeRankLLM listwise reranking

* **Model**: `nomic-ai/CodeRankLLM` (~7–8B), **listwise** reranker trained on CoRNStack to reorder strong retriever outputs (e.g., CodeRankEmbed). ([Hugging Face][9])

* **Prompting**: assemble a **compact listwise prompt**:

  ```
  You are a code search reranker. 
  Query: "<user query>"
  Candidates (index: path :: symbol :: preview):
  [0] path/to/a.py :: foo :: def foo(a: int) -> str: ...
  [1] path/to/b.ts :: Bar.run :: export class Bar { run() { ... } }
  ...
  Return a JSON list of indices in best-to-worst order, e.g. [2,0,1].
  ```

* **Constraints**: cap to **top‑N (e.g., 30–50)**; **timeout**; if JSON parsing fails, fall back to fused order.

* **Why**: pairs naturally with CodeRankEmbed; Nomic reports substantial gains when combined. ([Hugging Face][9])

---

## 5) Fusion & gating

### Weighted‑RRF (robust rank fusion)

Implement **Weighted Reciprocal Rank Fusion**:

[
\text{score}(d) = \sum_{c \in \text{channels}} w_c(q) \cdot \frac{1}{k + \text{rank}_c(d)}
]

* Start with priors (e.g., `warp:1.2, biencoder:1.0, splade:0.9, bm25:0.8`), then add **query‑aware rules** (error strings → ↑BM25; identifier‑heavy → ↑SPLADE; conceptual NL → ↑WARP/biencoder) and later learn small models for ( w_c(q) ). RRF is simple, strong, and well‑studied. ([G. V. Cormack][10])

### Gate from Stage‑1 → Stage‑2

* Default policy: run WARP if `score_margin < 0.08` **or** entropy high **and** within `timeout_ms_stage2`; else skip.
* Make the gate pluggable and log “why it fired” for tuning.

---

## 6) Settings (all stages switchable; knobs exposed)

```yaml
retrieval:
  enable_biencoder: true
  enable_late_interaction: true
  enable_reranker: false
  parallel_channels: ["splade","bm25"]

  biencoder:
    model: nomic-ai/CodeRankEmbed
    require_prefix: true
    k1: 500
    timeout_ms: 120
    faiss: { index: "IVF-PQ", nlist: "auto", nprobe: "auto", pq: { m: 16, bits: 8 } }

  warp:
    engine: warp
    objective: xtr
    search_mode: "rescore-k1"      # or "wide"
    k2: 200
    timeout_ms: 180
    retrieval_device: "cpu"        # default per upstream
    index: { build_device: "cuda", shard_by: ["language"] }

  gate:
    enabled: true
    metric: "score_margin"
    threshold: 0.08

  fusion:
    method: "weighted_rrf"
    rrf_k: 60
    weights: { biencoder: 1.0, warp: 1.2, splade: 0.9, bm25: 0.8 }

  reranker:
    model: nomic-ai/CodeRankLLM
    top_n: 30
    timeout_ms: 300
```

---

## 7) Orchestration flow (semantic adapter)

```python
# mcp_server/adapters/semantic.py  (conceptual)
s1 = biencoder.search(q, k=cfg.biencoder.k1) if cfg.enable_biencoder else []
allow_s2 = cfg.enable_late_interaction and gate.should_refine(q, s1, cfg.gate)
s2 = (warp.rescore(q, s1, k=cfg.warp.k2) if cfg.warp.search_mode=="rescore-k1"
      else warp.search(q, k=cfg.warp.k2)) if allow_s2 else []

sparse = {}
if "splade" in cfg.parallel_channels: sparse["splade"] = splade.search(q, k=K_s)
if "bm25"  in cfg.parallel_channels: sparse["bm25"]  = bm25.search(q, k=K_s)

fused = weighted_rrf({"biencoder": s1, "warp": s2, **sparse},
                     weights=cfg.fusion.weights, rrf_k=cfg.fusion.rrf_k)

if cfg.enable_reranker:
    prevs = catalog.preview_many([h.chunk_id for h in fused], max_chars=512)
    order = coderankllm.rerank(q, [p.text for p in prevs], top_n=cfg.reranker.top_n)
    fused = [fused[i] for i in order]

return hydrate(fused[:scope.k_hydrate])
```

* **Non‑blocking budgets**: if any stage exceeds its timeout, skip and continue; always return best available results.
* **Explainability**: carry each channel’s `WhyAttribution` into the final envelope.

---

## 8) Index manifests & lifecycle

* **DuckDB manifests** for each index: model name, tokenizer, dim, PQ/OPQ, nlist/nprobe, devices, index root, build git‑hash/time, and a **compatibility hash**.
* **Atomic swaps**: build side‑by‑side, then flip the manifest pointer.
* **Incremental**: append new chunks; trigger rebuild/compaction when fragmentation/bloat exceeds thresholds.
* **GPU‑centric builds**: WARP/FAISS builds on GPU; consider RAFT/cuVS for faster FAISS construction on supported hardware. ([NVIDIA Developer][6])

---

## 9) Explainability (first‑class)

* **Stage 1**: normalized similarity + top overlapping identifiers (cheap lexical pass).
* **Stage 2**: **token pairs** (top‑8 query tokens × best doc tokens w/ scores) + **symbol spans**; keep payload ≤ ~2 KB/hit for practical UIs. (Maps to XTR/ColBERT‑style alignment.) ([arXiv][8])

---

## 10) Observability & SLOs

* Timers: `biencoder_encode_ms`, `faiss_ms`, `warp_encode_ms`, `warp_search_ms`, `fusion_ms`, `rerank_ms`.
* Counters: `warp_skipped_gate`, `warp_skipped_timeout`, `rerank_timeout`.
* **Quality telemetry**: delta of ranks by channel; gate hit rate.
* **SLO guardrails**: budget breaches short‑circuit cleanly and are reflected in the returned `limits`/`method.retrieval`.

---

## 11) Evaluation (quality + latency)

* **Primary**: **COIR** (multi‑task code IR) — report nDCG@10, Recall@50 for:

  * (A) biencoder only, (B) WARP only, (C) two‑stage, (D) two‑stage + SPLADE/BM25, (E) + CodeRankLLM. ([Gangiswag][11])
* **Secondary**: CodeSearchNet (continuity) and internal curated queries.
* **Ablations**: rescore‑K₁ vs wide‑WARP; RRF weights; gate thresholds; reranker on/off.
* **Latency**: p50/p95 per stage; ensure end‑to‑end SLOs.

---

## 12) Security, performance & failure modes

* **GPU memory**: pre‑allocate and reuse model/encoder buffers; batch queries; cap max tokens.
* **Failure**: if WARP index missing or corrupt → auto‑disable Stage‑2 and log; if reranker JSON invalid → revert to fused order.
* **Determinism**: seed model inference where possible; deterministic ANN settings for tests.
* **Threading**: isolate CPU‑heavy WARP retrieval in a dedicated thread pool; keep GPU encoding on dedicated CUDA stream.

---

## 13) “Definition of Done” checklist

* [ ] Stage‑1 (CodeRankEmbed) FAISS‑GPU index + manifest; auto‑prefix handling; top‑K₁ search + gate metrics. ([Hugging Face][3])
* [ ] Stage‑2 (WARP/XTR) index build on GPU, retrieval on CPU by default; rescore‑K₁ & wide modes; token‑pair explainability. ([GitHub][4])
* [ ] Weighted‑RRF fusion with per‑channel priors & rule‑based adaptivity; logging of weights and contributions. ([G. V. Cormack][10])
* [ ] (Optional) Stage‑3 (CodeRankLLM) listwise JSON reranker with strict parsing + fallbacks. ([Hugging Face][9])
* [ ] Budgets, fallbacks, and observability (timers, counters, coverage) wired end‑to‑end.
* [ ] COIR evaluations & ablations run; thresholds and weights tuned. ([Gangiswag][11])

---

## Source notes you can cite internally

* **WARP**: key innovations and speedups; PDF for technical details, ACM/abs/HTML summaries for claims. ([arXiv][1])
* **XTR**: reframes token retrieval to enable efficient scoring; PDF/HTML versions. ([arXiv][12])
* **PLAID**: the established ColBERTv2 engine and speed baselines. ([arXiv][2])
* **CodeRankEmbed**: 137M bi‑encoder, **must add instruction prefix**, designed to pair with CodeRankLLM. ([Hugging Face][3])
* **CodeRankLLM**: 7B listwise reranker for code retrieval. ([Hugging Face][9])
* **RRF**: the classic fusion method (SIGIR’09 paper). ([G. V. Cormack][10])
* **CoRNStack/COIR**: training data + benchmark used by Nomic models. ([arXiv][13])

---

If this plan looks right, I’m ready to draft **drop‑in code patches** for:

* `biencoder/*` (index & search, FAISS‑GPU, auto‑prefix)
* `warp_xtr/*` (index & search, rescore‑K₁ & wide modes, explainability)
* `rerank/coderankllm.py` + `prompts.py` (strict JSON listwise)
* `core/fusion.py`, `core/gating.py`, `core/telemetry.py`
* settings + manifest registry

…so you can wire it into your MCP server. And I meant it: I’m excited for you—this design has the ingredients to be **best‑in‑class**.

[1]: https://arxiv.org/pdf/2501.17788?utm_source=chatgpt.com "An Efficient Engine for Multi-Vector Retrieval - WARP"
[2]: https://arxiv.org/abs/2205.09707?utm_source=chatgpt.com "PLAID: An Efficient Engine for Late Interaction Retrieval"
[3]: https://huggingface.co/nomic-ai/CodeRankEmbed?utm_source=chatgpt.com "nomic-ai/CodeRankEmbed"
[4]: https://github.com/jlscheerer/xtr-warp?utm_source=chatgpt.com "jlscheerer/xtr-warp"
[5]: https://arxiv.org/abs/2304.01982?utm_source=chatgpt.com "Rethinking the Role of Token Retrieval in Multi-Vector Retrieval"
[6]: https://developer.nvidia.com/blog/optimizing-vector-search-for-indexing-and-real-time-retrieval-with-nvidia-cuvs/?utm_source=chatgpt.com "Optimizing Vector Search for Indexing and Real-Time ..."
[7]: https://huggingface.co/nomic-ai/CodeRankEmbed/blame/28ddab382a0aa9d5523da6ffb78a251cca6133bd/README.md?utm_source=chatgpt.com "README.md · nomic-ai/CodeRankEmbed at ..."
[8]: https://arxiv.org/html/2304.01982v3?utm_source=chatgpt.com "Rethinking the Role of Token Retrieval in Multi-Vector ..."
[9]: https://huggingface.co/nomic-ai/CodeRankLLM?utm_source=chatgpt.com "nomic-ai/CodeRankLLM"
[10]: https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf?utm_source=chatgpt.com "Reciprocal Rank Fusion outperforms Condorcet and ..."
[11]: https://gangiswag.github.io/cornstack/?utm_source=chatgpt.com "CoRNStack: High-Quality Contrastive Data for Better Code ..."
[12]: https://arxiv.org/pdf/2304.01982?utm_source=chatgpt.com "Rethinking the Role of Token Retrieval in Multi-Vector ..."
[13]: https://arxiv.org/html/2412.01007v1?utm_source=chatgpt.com "CoRNStack: High-Quality Contrastive Data for Better Code ..."




Fantastic—thanks for locking the choices and for adding **CodeRankLLM** as the optional reranker. Below is a **best‑in‑class, Pythonic implementation plan** for a **two‑stage retrieval system**:

* **Stage 1 (fast)**: *bi‑encoder candidate generation* with **CodeRankEmbed**.
* **Stage 2 (precise)**: *late‑interaction refinement* with **XTR‑style* scoring on the **WARP** engine.
* **(Optional) Stage 3**: *listwise reranking* with **CodeRankLLM**.
* **Parallel sparse channels** (SPLADE/BM25) and **Weighted‑RRF** fusion across everything.

I’ve integrated the latest guidance from the WARP/XTR literature and the CodeRank models, and made all stages **switchable** with clear knobs. Where I make claims about methods, speedups, or model use, I cite primary sources inline.

---

## 1) Target architecture (GPU‑centric, code‑aware, switchable)

### At a glance

* **Stage 1**: **CodeRankEmbed** bi‑encoder (137M) produces a single vector per chunk + per query. It **requires** the query instruction prefix
  `Represent this query for searching relevant code:` — we will inject this automatically. ([Hugging Face][1])
* **Stage 2**: **XTR‑style late interaction** executed by **WARP**: dynamic similarity imputation (**WARPSELECT**), **implicit decompression**, and **two‑stage reduction** yield **large latency gains** (≈**41×** vs XTR reference and ≈**3×** vs PLAID) at comparable quality. ([arXiv][2])

  * WARP’s **retrieval path is CPU‑optimized**, while **index construction strongly benefits from GPU**—we’ll default to **GPU for encoding & build**, **CPU for retrieval**, with a switch to experiment with GPU retrieval later. ([GitHub][3])
* **(Optional) Stage 3**: **CodeRankLLM** (≈7–8B) listwise reranker, trained for **code reranking** on CoRNStack; it’s designed to sit on top of strong retrievers like CodeRankEmbed. ([Hugging Face][4])
* **Fusion**: **Weighted Reciprocal Rank Fusion (RRF)** to combine Stage 1, Stage 2, and sparse channels; start with static priors and allow adaptive rules later. RRF is a simple, proven rank‑fusion method. ([G. V. Cormack][5])
* **Evaluation**: quantify gains on **COIR** across tasks (nDCG@10/Recall@50), the most up‑to‑date benchmark suite for code retrieval & reranking from Nomic’s CoRNStack work. ([Hugging Face][6])

---

## 2) Pythonic design & module layout

> Guiding principles: **clean interfaces**, **explicit manifests**, **single responsibility**, **runtime‑switchable strategies**, **typed dataclasses/Protocols**, **observability first**.

```
codeintel_rev/
  retrieval/
    core/
      interfaces.py          # Retriever, SearchResult, WhyAttribution, Manifest Protocols
      fusion.py              # weighted_rrf(), adapters for channel score normalization
      gating.py              # stage-2 gate heuristics (margin/entropy), time budgets
      telemetry.py           # timers, counters, trace ids
    biencoder/               # Stage 1
      coderankembed_indexer.py
      coderankembed_searcher.py
      manifest.py
    warp_xtr/                # Stage 2
      warp_indexer.py
      warp_searcher.py
      manifest.py
    rerank/                  # Optional Stage 3
      coderankllm.py
      prompts.py             # listwise prompt templates
  mcp_server/
    adapters/semantic.py     # orchestration: Stage1 → (gate) Stage2 → fusion → (Stage3) → hydrate
  io/
    manifests.py             # DuckDB-backed registry of all index manifests (path, model, params)
```

### Key interfaces (`retrieval/core/interfaces.py`)

```python
from dataclasses import dataclass
from typing import Protocol, Sequence, Literal

@dataclass(frozen=True)
class WhyAttribution:
    channel: Literal["biencoder","warp","splade","bm25","reranker"]
    details: dict  # e.g., { "token_pairs": [...], "score": float, "top_terms": [...] }

@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    score: float
    why: list[WhyAttribution]

class Retriever(Protocol):
    def search(self, query: str, k: int) -> list[SearchHit]: ...
    def explain(self) -> bool: ...  # whether it can emit token-level alignments, etc.

class Reranker(Protocol):
    def rerank(self, query: str, texts: list[str], top_n: int) -> list[int]: ...
```

---

## 3) Stage 1 — CodeRankEmbed (bi‑encoder) channel

### Index build (GPU)

* **Tokenizer/model**: load **nomic-ai/CodeRankEmbed** with `trust_remote_code=True`. It’s a 137M bi‑encoder initialized from **Arctic‑Embed‑M‑Long**, trained with **InfoNCE** on **CoRNStack**. ([Hugging Face][1])
* **Chunk embeddings**: feed **symbol‑aware chunks** (from your SCIP chunker) → batch on GPU (`torch.float16`, `inference_mode`).
* **FAISS GPU index**: IVF‑PQ/OPQ with persistent metadata. Persist a **manifest**:

  ```json
  { "model": "nomic-ai/CodeRankEmbed", "requires_prefix": true,
    "dim": <auto>, "index": "IVF-PQ", "nlist": ..., "nprobe": ..., "opq": {...},
    "created_at": "...", "corpus": { "num_chunks": N } }
  ```
* **Quality note**: do **not** alter the tokenizer; we’ll handle code‑specific heuristics in parallel sparse channels, not by changing the Stage‑1 tokenizer.

### Query‑time (GPU)

* **Auto‑prefix** the query with the model’s required instruction:
  `"Represent this query for searching relevant code: " + user_query`. ([Hugging Face][1])
* Encode → FAISS search for **top‑K₁**; compute confidence metrics (**max score**, **margin to #2**, **entropy**) to drive the **Stage‑2 gate**.

**Why/Explain** (lightweight):

* Add a brief `why` with the normalized dot‑product score and a **lexical sketch** (shared identifiers from a fast tokenizer pass) so the agent can show *some* reason even if this channel is vector‑only.

---

## 4) Stage 2 — WARP (XTR‑style late interaction) channel

### Why WARP + XTR

* **WARP** optimizes **XTR** late‑interaction retrieval: **WARPSELECT** avoids gathering full token matrices, **implicit decompression** removes reconstruction costs, and **two‑stage reduction** uses dedicated C++ kernels—together cutting latency by **~41× vs XTR baseline** and **~3× vs PLAID**. ([arXiv][7])
* **XTR** training objective **makes token retrieval itself efficient**, enabling scoring from the **retrieved tokens** rather than all tokens. ([arXiv][8])

### Index build (GPU‑centric)

* **Encoding model**: an **XTR‑compatible** late‑interaction encoder (code‑capable backbone). (Short‑term: use the reference XTR setup to bring up infra; then **fine‑tune on CoRNStack/COIR** for code.) ([arXiv][8])
* **Pre‑tokenization** (code‑aware, *without* breaking tokenizer IDs): split on `snake_case`/`camelCase`, keep punctuation like `.`, `::`, `->` as separate whitespace‑delimited tokens before passing to the model tokenizer—this aids later **explanation** while leaving the model’s native tokenization intact.
* **WARP artifacts**: build centroids/residuals/postings and `doclens` with GPU where available (per README, **GPU strongly recommended for index construction**). ([GitHub][3])
* Persist a **manifest**:

  ```json
  { "engine": "WARP", "objective": "XTR",
    "model": "<xtr-code-encoder>", "tokenizer": "<code-aware>",
    "build_device": "cuda", "retrieval_device": "cpu",
    "created_at": "...", "index_root": "..." }
  ```

### Query‑time (CPU default, GPU option)

Two modes (both switchable):

1. **Rescore‑K₁** (fast refinement): encode query on GPU → run WARP over **Stage‑1 candidates** only (K₁ from the bi‑encoder).
2. **Wide‑WARP** (high recall): run WARP on a shard (e.g., language‑partition) even if Stage‑1 is off or uncertain.

**Why/Explain** (rich):

* Return **top query tokens ↔ top code tokens** with **MaxSim‑like scores** + **line/col** spans and **symbol names**. This mirrors ColBERT/XTR’s explainability and gives agents precise “why it matched”. ([arXiv][8])

---

## 5) (Optional) Stage 3 — CodeRankLLM listwise reranking

* **Model**: **nomic‑ai/CodeRankLLM** (~7–8B), trained for **listwise code reranking**, intended to **sit on top of CodeRankEmbed** candidates; it uses **CoRNStack** and LLM‑provided orderings during training. ([Hugging Face][4])
* **Prompting**: build a **listwise template** with the user query + K candidates (`<file path>`, `<symbol>`, short preview). Ask the model to return a **strict JSON list of indices** in best‑to‑worst order. (We’ll enforce JSON with a regex/`json.loads` and fall back to original ranks on malformed output.)
* **Budgets**: keep **K_rerank small** (e.g., 30–50) and **timeout tight**; skip this stage if latency exceeds budget.

---

## 6) Fusion & gating (production‑grade)

### Weighted‑RRF

* **RRF** merges **ranked lists** from multiple channels; it is robust and simple, consistently strong in practice. We’ll use **Weighted RRF** with per‑channel priors and optional rule‑based tweaks by query type (error strings → ↑BM25, function‑like tokens → ↑SPLADE, conceptual NL → ↑WARP/bi‑encoder). ([G. V. Cormack][5])

### Gate from Stage 1 → Stage 2

* Gate variables: `margin = s1_top1 - s1_top2`, `entropy` over top‑k, and total Stage‑1 compute time.
* Default policy:

  * If `margin < 0.08` **or** entropy high **and** we’re within `timeout_ms_stage2`, run WARP; otherwise skip. (Exposed as config.)

---

## 7) Configuration (toggle any stage; all knobs surfaced)

```yaml
retrieval:
  enable_biencoder: true
  enable_late_interaction: true
  enable_reranker: false
  parallel_channels: ["splade","bm25"]     # fused with RRF

  biencoder:
    model: nomic-ai/CodeRankEmbed          # auto-add required query prefix
    k1: 500
    timeout_ms: 120
    faiss: { index: "IVF-PQ", nlist: "auto", nprobe: "auto", pq: { m: 16, bits: 8 } }

  warp:
    engine: warp
    objective: xtr
    search_mode: "rescore-k1"              # or "wide"
    k2: 200
    timeout_ms: 180
    retrieval_device: "cpu"                # per WARP README (GPU optional)
    index: { build_device: "cuda", shard_by: ["language"] }

  gate:
    enabled: true
    metric: "score_margin"
    threshold: 0.08

  fusion:
    method: "weighted_rrf"
    rrf_k: 60
    weights: { biencoder: 1.0, warp: 1.2, splade: 0.9, bm25: 0.8 }

  reranker:
    model: nomic-ai/CodeRankLLM            # listwise; JSON rank output
    top_n: 30
    timeout_ms: 300
```

---

## 8) Orchestration flow (semantic adapter)

Pseudocode in `adapters/semantic.py`:

```python
def retrieve(query: str, scope: Scope, cfg: Settings):
    # Stage 1
    s1_hits = biencoder.search(query, k=cfg.biencoder.k1) if cfg.enable_biencoder else []
    # Stage 2 gate
    allow_warp = cfg.enable_late_interaction and gate.should_refine(query, s1_hits, cfg.gate)
    if allow_warp:
        s2_hits = warp.rescore(query, s1_hits, k=cfg.warp.k2) if cfg.warp.search_mode=="rescore-k1" \
                  else warp.search(query, k=cfg.warp.k2)
    else:
        s2_hits = []

    # Parallel sparse channels
    sparse = {}
    if "splade" in cfg.parallel_channels: sparse["splade"] = splade.search(query, k=cfg.k_sparse)
    if "bm25"  in cfg.parallel_channels: sparse["bm25"]  = bm25.search(query, k=cfg.k_sparse)

    # Fusion
    fused = fusion.weighted_rrf({
        "biencoder": s1_hits, "warp": s2_hits, **sparse
    }, weights=cfg.fusion.weights, rrf_k=cfg.fusion.rrf_k)

    # Optional listwise rerank
    if cfg.enable_reranker:
        previews = catalog.preview_many([h.chunk_id for h in fused], max_chars=512)
        order = coderankllm.rerank(query, [p.text for p in previews], top_n=cfg.reranker.top_n)
        fused = [fused[i] for i in order]

    # Hydrate top-K and return with why/attribution intact
    return hydrate(fused[:scope.k_hydrate])
```

---

## 9) Index manifests & lifecycle (DuckDB + disk)

* **Manifests table** stores one row per index (Stage‑1 FAISS, Stage‑2 WARP), with paths, model names, dims, build devices, PQ settings, and **compatibility hash** (commit/hash of code used).
* **Atomic swap**: build in a new directory, then swap a versioned pointer in DuckDB to make updates atomic.
* **Incremental**: append new chunks and rebuild centroids periodically (WARP/FAISS both support rebuild workflows).

---

## 10) Explainability (first‑class)

* **Stage 1**: add normalized similarity + **top overlapping identifiers** (derived from a fast regex/camelCase/snake_case splitter) so agents have a lightweight justification even without token‑wise interaction.
* **Stage 2**: emit **token alignments** (top‑M query tokens × best doc tokens with MaxSim‑like scores) + **symbol spans (file, line, col)**. This mirrors ColBERT/XTR’s interpretability and is what dev‑tools users expect. ([arXiv][8])
* Bundle these in `WhyAttribution` per‑hit, and surface in the MCP `AnswerEnvelope.method.retrieval` along with per‑channel scores.

---

## 11) Observability & SLOs

* **Per‑stage timers**: `biencoder_encode_ms`, `faiss_ms`, `warp_encode_ms`, `warp_search_ms`, `fusion_ms`, `rerank_ms`.
* **Fallback counters**: `warp_skipped_gate`, `warp_skipped_timeout`, `rerank_timeout`.
* **Quality**: log **top‑k hit deltas** between channels to support tuning of **weights** and **gate threshold**.
* **SLO guardrails**: if Stage‑2 or reranker exceed budget → skip & continue (never block hydration).

---

## 12) Evaluation plan

* **Primary**: COIR (multi‑task; robust) for nDCG@10 and Recall@50, comparing:

  * **A**: biencoder‑only (Stage 1)
  * **B**: WARP‑only (Stage 2)
  * **C**: two‑stage (A→B)
  * **D**: C + sparse + RRF
  * **E**: D + CodeRankLLM reranker
    Track latency p50/p95 per stage. ([Hugging Face][6])
* **Sanity**: use a repo‑local eval set (handwritten queries mapped to known symbols/functions) to tune **gate** and **weights**.

---

## 13) Remaining design decisions to freeze

1. **Stage sizes & budgets (defaults)**

   * Propose **K₁=500**, **K₂=200**, **K_hydrate=20**; `timeout_ms`: Stage‑1=120, Stage‑2=180, Reranker=300.
     (Safe starting points; adjust by corpus size + GPU/CPU mix.)
2. **WARP retrieval device**

   * Default **CPU** (per README), but keep `retrieval_device: "cuda"` as experimental. OK to start CPU for reliability? ([GitHub][3])
3. **XTR encoder for code**

   * Short‑term: use public **XTR reference** to bring up infra; **mid‑term**: fine‑tune on **CoRNStack/COIR** for code tokens; this is where the biggest Stage‑2 quality gains will come from. ([arXiv][8])
4. **Explainability budget**

   * Default **top‑8** query tokens × best matches (≤2 KB per hit). Increase only when specifically requested by a caller.
5. **CodeRankLLM prompt**

   * Return **strict JSON list** of indices; if parse fails → use fused ranks. We’ll include short previews and symbol names to keep prompts compact.

Confirm these and I’ll produce **drop‑in patches** for:

* `biencoder/` (index + search, FAISS GPU, auto‑prefix guard),
* `warp_xtr/` (index + search, WARP bindings, rescore‑K₁ and wide modes),
* `rerank/coderankllm.py` (listwise JSON protocol with timeouts),
* `fusion/gating.py` (margin/entropy gate),
* settings + observability wiring.

---

## References (key load‑bearing sources)

* **WARP**: multi‑vector engine with **WARPSELECT**, **implicit decompression**, **two‑stage reduction**; ≈**41×** faster than XTR ref. and ≈**3×** faster than PLAID. ([arXiv][2])
* **WARP GitHub**: retrieval optimized for **CPU**, **GPU recommended for index build**. ([GitHub][3])
* **XTR**: objective that **retrieves important tokens first**; enables efficient scoring from retrieved tokens. ([arXiv][8])
* **PLAID** (baseline engine for ColBERTv2): 2.5–7× GPU, 9–45× CPU speed‑ups vs vanilla late interaction. ([arXiv][9])
* **ColBERT / late interaction** (foundational method) and community updates. ([arXiv][10])
* **CodeRankEmbed**: **137M** bi‑encoder, **8,192‑token** context; **requires query instruction prefix**; trained on **CoRNStack**; pairs well with CodeRankLLM. ([Hugging Face][1])
* **CodeRankLLM**: **7–8B** listwise reranker for code; trained to re‑order CodeRankEmbed candidates. ([Hugging Face][4])
* **COIR / CoRNStack**: benchmark + dataset supporting code retrieval + reranking. ([Hugging Face][6])
* **RRF / Weighted‑RRF**: rank fusion for hybrid retrieval (original and modern operational docs). ([G. V. Cormack][5])

---

If you’re happy with these defaults, I’ll move straight to code patches with the module layout shown above, including manifests, settings, async orchestration, and test scaffolds.

[1]: https://huggingface.co/nomic-ai/CodeRankEmbed "nomic-ai/CodeRankEmbed · Hugging Face"
[2]: https://arxiv.org/abs/2501.17788?utm_source=chatgpt.com "WARP: An Efficient Engine for Multi-Vector Retrieval"
[3]: https://github.com/jlscheerer/xtr-warp "GitHub - jlscheerer/xtr-warp: XTR/WARP (SIGIR'25) is an extremely fast and accurate retrieval engine based on Stanford's ColBERTv2/PLAID and Google DeepMind's XTR."
[4]: https://huggingface.co/nomic-ai/CodeRankLLM "nomic-ai/CodeRankLLM · Hugging Face"
[5]: https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf?utm_source=chatgpt.com "Reciprocal Rank Fusion outperforms Condorcet and ..."
[6]: https://huggingface.co/papers/2412.01007?utm_source=chatgpt.com "CoRNStack: High-Quality Contrastive Data for Better Code ..."
[7]: https://arxiv.org/pdf/2501.17788?utm_source=chatgpt.com "An Efficient Engine for Multi-Vector Retrieval - WARP"
[8]: https://arxiv.org/pdf/2304.01982?utm_source=chatgpt.com "Rethinking the Role of Token Retrieval in Multi-Vector ..."
[9]: https://arxiv.org/abs/2205.09707?utm_source=chatgpt.com "PLAID: An Efficient Engine for Late Interaction Retrieval"
[10]: https://arxiv.org/pdf/2511.00444?utm_source=chatgpt.com "The First Workshop on Late Interaction and Multi Vector ..."
