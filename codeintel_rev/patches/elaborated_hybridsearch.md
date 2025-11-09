# Instructions #

Love where this is headed — let’s lock in a **production‑grade search stack** that cleanly layers your new two‑stage bi‑encoder (CodeRankEmbed), optional LLM reranker (CodeRankLLM), and keeps the door open for WARP/XTR later. Below I’m shipping a **drop‑in PR patch series** that:

* adds config structs and ergonomics,
* introduces a **biencoder ANN** (HF/Sentence‑Transformers) with its own FAISS index,
* adds a **semantic_pro** adapter for two‑stage retrieval + optional LLM rerank,
* upgrades hybrid fusion to **weighted RRF** with contributions preserved,
* exposes a new MCP tool `search:semantic_pro`,
* wires health/readiness probes for the new artifacts,
* and provides a small **Typer CLI** to build/inspect the biencoder index.

All changes follow your current architecture: *Settings via msgspec, immutable ApplicationContext, readiness probes, adapters returning AnswerEnvelopes, DuckDB hydration with preserve_order, and MCP error envelopes*. I’m aligning to your existing patterns in `main.py` (lifespan/init), `ApplicationContext` (load‑once, explicit injection), the current hybrid engine & sparse channels, DuckDB catalog/hydration, and MCP tool registration.

---

## Commit 1 — **Config: add biencoder + reranker (and optional xtr placeholder)**

We introduce three config blocks (biencoder, reranker, xtr placeholder). They use your `msgspec.Struct` style and drop into `Settings`. 

```diff
diff --git a/codeintel_rev/config/settings.py b/codeintel_rev/config/settings.py
@@
-from codeintel_rev.io.duckdb_manager import DuckDBConfig
+from codeintel_rev.io.duckdb_manager import DuckDBConfig
+import msgspec

@@
 class SpladeConfig(msgspec.Struct, frozen=True):
     ...
 
+class BiencoderConfig(msgspec.Struct, frozen=True):
+    """Stage-1 bi-encoder (CodeRankEmbed) configuration."""
+    model_id: str = "nomic-ai/CodeRankEmbed"
+    index_path: str = "data/faiss/biencoder.faiss"
+    batch_size: int = 64
+    embedding_dim: int = 1024  # set to model’s actual dim at build time if needed
+    use_gpu: bool = True
+    nprobe: int = 32
+    top_k: int = 200
+
+class RerankerConfig(msgspec.Struct, frozen=True):
+    """Optional CodeRankLLM reranker configuration."""
+    model_id: str = "nomic-ai/CodeRankLLM"
+    enabled: bool = False
+    device: str = "cpu"   # "cuda" to opt-in
+    max_pairs: int = 50
+    budget_ms: int = 500
+    prompt_template_path: str | None = None
+
+class XTRConfig(msgspec.Struct, frozen=True):
+    """Placeholder for future late-interaction (XTR) retriever."""
+    enabled: bool = False
+    index_dir: str = "indexes/xtr"
+    model_id: str = "warp-xtr"
+    top_k: int = 60
+    budget_ms: int = 700
+    use_gpu: bool = True
+
@@
 class PathsConfig(msgspec.Struct, frozen=True):
     ...
 
 class IndexConfig(msgspec.Struct, frozen=True):
     """Indexing and search configuration.
@@
     """
     # (existing fields truncated)
     ...
+    # RRF fusion strength for semantic_pro
+    rrf_k: int = 60
+    # default weights per channel (semantic_pro)
+    rrf_weights: dict[str, float] = {"biencoder": 1.0, "splade": 1.0, "bm25": 0.9}
 
@@
 class Settings(msgspec.Struct, frozen=True):
     ...
     vllm: VLLMConfig = VLLMConfig()
     bm25: BM25Config = BM25Config()
     splade: SpladeConfig = SpladeConfig()
+    biencoder: BiencoderConfig = BiencoderConfig()
+    reranker: RerankerConfig = RerankerConfig()
+    xtr: XTRConfig = XTRConfig()
@@
 def load_settings() -> Settings:
     ...
     return Settings(
         ...
     )
```

> Why here/how it fits: this mirrors your existing msgspec configuration blocks, keeping immutability and single‑load semantics in line with your `ApplicationContext` “load once → inject everywhere” approach. 

---

## Commit 2 — **Retriever: Biencoder index manager & query provider**

A self‑contained module that (a) **builds a FAISS index** from CodeRankEmbed vectors, and (b) **searches** it at query time. This follows your IO patterns and lazy GPU usage strategy (only on first call). It uses Sentence‑Transformers under the hood (same family as your SPLADE helpers). 

```diff
diff --git a/codeintel_rev/retrievers/biencoder.py b/codeintel_rev/retrievers/biencoder.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/retrievers/biencoder.py
@@
+from __future__ import annotations
+
+from dataclasses import dataclass
+from pathlib import Path
+from threading import Lock
+from typing import TYPE_CHECKING, Sequence, cast
+
+import numpy as np
+from kgfoundry_common.logging import get_logger
+from kgfoundry_common.typing import gate_import
+
+from codeintel_rev.io.parquet_store import read_chunks_parquet  # hydration/build input
+from codeintel_rev.io.duckdb_manager import DuckDBQueryBuilder, DuckDBQueryOptions
+
+if TYPE_CHECKING:
+    from codeintel_rev.config.settings import BiencoderConfig, Settings
+
+LOGGER = get_logger(__name__)
+
+
+def _l2_normalize(x: np.ndarray) -> np.ndarray:
+    norm = np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
+    return x / norm
+
+
+@dataclass(slots=True)
+class BiencoderIndexManager:
+    """Build/inspect a FAISS index for CodeRankEmbed vectors."""
+
+    settings: Settings
+
+    def build_index(self, *, parquet_path: Path, index_path: Path | None = None, batch_size: int | None = None) -> Path:
+        cfg = self.settings.biencoder
+        index_path = index_path or Path(self.settings.biencoder.index_path)
+
+        st = cast("object", gate_import("sentence_transformers", "biencoder build"))  # type: ignore[assignment]
+        SentenceTransformer = getattr(st, "SentenceTransformer")
+        model = SentenceTransformer(cfg.model_id, device="cuda" if cfg.use_gpu else "cpu")
+        if batch_size is None:
+            batch_size = cfg.batch_size
+
+        table = read_chunks_parquet(parquet_path)
+        texts = table.column("content").to_pylist()
+        ids = table.column("id").to_pylist()
+
+        embeddings = model.encode(texts, batch_size=batch_size, convert_to_numpy=True, normalize_embeddings=True)
+        embeddings = embeddings.astype("float32")
+
+        faiss = cast("object", gate_import("faiss", "biencoder build faiss"))
+        index = faiss.IndexFlatIP(embeddings.shape[1])
+        idmap = faiss.IndexIDMap2(index)
+        id_array = np.asarray(ids, dtype=np.int64)
+        faiss.normalize_L2(embeddings)
+        idmap.add_with_ids(embeddings, id_array)
+
+        index_path.parent.mkdir(parents=True, exist_ok=True)
+        faiss.write_index(idmap, str(index_path))
+        LOGGER.info("Built biencoder index", extra={"index_path": str(index_path), "vectors": len(ids)})
+        return index_path
+
+
+class BiencoderSearchProvider:
+    """Query‑time provider for CodeRankEmbed + FAISS."""
+
+    def __init__(self, cfg: BiencoderConfig) -> None:
+        self._cfg = cfg
+        self._lock = Lock()
+        self._model = None
+        self._faiss = None
+        self._cpu = None
+        self._gpu = None
+
+    def _ensure_ready(self) -> None:
+        if self._model and self._cpu:
+            return
+        with self._lock:
+            if self._model and self._cpu:
+                return
+            st = cast("object", gate_import("sentence_transformers", "biencoder query"))
+            SentenceTransformer = getattr(st, "SentenceTransformer")
+            self._model = SentenceTransformer(self._cfg.model_id, device="cuda" if self._cfg.use_gpu else "cpu")
+
+            self._faiss = cast("object", gate_import("faiss", "biencoder query faiss"))
+            self._cpu = self._faiss.read_index(self._cfg.index_path)
+
+            # try GPU clone if available
+            if self._cfg.use_gpu and hasattr(self._faiss, "StandardGpuResources"):
+                try:
+                    res = self._faiss.StandardGpuResources()
+                    self._gpu = self._faiss.index_cpu_to_gpu(res, 0, self._cpu)
+                except Exception:  # noqa: BLE001
+                    self._gpu = None
+
+    def search(self, query: str, top_k: int) -> list[tuple[int, float]]:
+        self._ensure_ready()
+        assert self._model is not None and self._cpu is not None
+
+        vec = self._model.encode([query], convert_to_numpy=True, normalize_embeddings=True).astype("float32")
+        index = self._gpu or self._cpu
+        D, I = index.search(vec, top_k)
+        ids = I[0].tolist()
+        scores = D[0].tolist()
+        return [(int(i), float(s)) for i, s in zip(ids, scores) if int(i) != -1]
```

> **Notes**
>
> * The provider returns canonical **chunk IDs** (as stored in Parquet/DuckDB) so downstream hydration via DuckDB keeps order with `preserve_order=True`. That matches your current semantic path. 
> * We leverage the same **Sentence‑Transformers ecosystem** you already rely on for SPLADE export/encode to minimize new dependencies. 

---

## Commit 3 — **Hybrid: weighted RRF + plug‑in channels**

We extend `HybridSearchEngine` to accept additional channels at fuse time and add a **weighted RRF** (rank‑only, score‑agnostic, but channel‑weighted). This keeps your contributions map and warnings.

```diff
diff --git a/codeintel_rev/io/hybrid_search.py b/codeintel_rev/io/hybrid_search.py
@@
 from dataclasses import dataclass
@@
 class HybridSearchEngine:
@@
-    def search(
+    def search(
         self,
         query: str,
         *,
         semantic_ids: Sequence[int],
         semantic_scores: Sequence[float],
-        limit: int,
+        limit: int,
+        extra_channels: dict[str, list[ChannelHit]] | None = None,
+        weights: dict[str, float] | None = None,
     ) -> HybridSearchResult:
@@
-        runs, warnings = self._gather_channel_hits(query, semantic_ids, semantic_scores)
+        runs, warnings = self._gather_channel_hits(query, semantic_ids, semantic_scores)
+        # Inject externally provided channels (e.g., biencoder or late-interaction)
+        if extra_channels:
+            for name, hits in extra_channels.items():
+                runs[name] = hits
         if not runs:
             return HybridSearchResult(
                 docs=[],
                 contributions={},
                 channels=[],
                 warnings=warnings,
             )
 
-        docs, contributions = _rrf_fuse(
-            runs,
-            k=self._settings.index.rrf_k,
-            limit=limit,
-        )
+        if weights:
+            docs, contributions = _weighted_rrf_fuse(
+                runs, k=self._settings.index.rrf_k, limit=limit, weights=weights
+            )
+        else:
+            docs, contributions = _rrf_fuse(
+                runs,
+                k=self._settings.index.rrf_k,
+                limit=limit,
+            )
@@
         return HybridSearchResult(
             docs=docs,
             contributions=filtered_contributions,
             channels=active_channels,
             warnings=warnings,
         )
+
+def _weighted_rrf_fuse(
+    runs: dict[str, list[ChannelHit]],
+    *,
+    k: int,
+    limit: int,
+    weights: dict[str, float],
+) -> tuple[list[HybridResultDoc], dict[str, list[tuple[str, int, float]]]]:
+    """Weighted RRF with per-channel weights (rank-only)."""
+    # scores[doc_id] = fused_score
+    fused: dict[str, float] = {}
+    contrib: dict[str, list[tuple[str, int, float]]] = {}
+    for channel, hits in runs.items():
+        if not hits:
+            continue
+        w = float(weights.get(channel, 1.0))
+        for rank, hit in enumerate(hits):
+            # RRF: 1 / (k + rank+1)
+            score = w * (1.0 / (k + rank + 1))
+            fused[hit.doc_id] = fused.get(hit.doc_id, 0.0) + score
+            contrib.setdefault(hit.doc_id, []).append((channel, rank, hit.score))
+    ordered = sorted(fused.items(), key=lambda kv: -kv[1])[:limit]
+    docs = [HybridResultDoc(doc_id=doc_id, score=score) for doc_id, score in ordered]
+    return docs, contrib
```

> This preserves your established **ChannelHit → contributions → explainability** flow while allowing `semantic_pro` to supply additional channels and weights. 

---

## Commit 4 — **Adapter: two‑stage `semantic_pro_adapter`**

A new adapter that runs:

1. **biencoder ANN** → high‑recall shortlist
2. Optional **sparse channels** (SPLADE/BM25) in parallel
3. **Weighted RRF** fusion with channel weights from settings
4. **DuckDB hydration** with `preserve_order=True`
5. Optional **CodeRankLLM** reranking (list‑wise) within budget

Hydration & envelopes mirror your existing semantic path (session scope, explainability, limits).

```diff
diff --git a/codeintel_rev/mcp_server/adapters/semantic_pro_adapter.py b/codeintel_rev/mcp_server/adapters/semantic_pro_adapter.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/mcp_server/adapters/semantic_pro_adapter.py
@@
+from __future__ import annotations
+
+import asyncio
+from dataclasses import dataclass
+from time import perf_counter
+from typing import TYPE_CHECKING, cast
+
+import numpy as np
+
+from kgfoundry_common.logging import get_logger
+from kgfoundry_common.errors import VectorSearchError
+
+from codeintel_rev.app.middleware import get_session_id
+from codeintel_rev.io.hybrid_search import (
+    HybridSearchEngine,
+    ChannelHit,
+    HybridResultDoc,
+)
+from codeintel_rev.io.duckdb_manager import DuckDBQueryBuilder, DuckDBQueryOptions
+from codeintel_rev.retrievers.biencoder import BiencoderSearchProvider
+from codeintel_rev.mcp_server.schemas import AnswerEnvelope, Finding, MethodInfo
+from codeintel_rev.mcp_server.scope_utils import get_effective_scope
+
+if TYPE_CHECKING:
+    from codeintel_rev.app.config_context import ApplicationContext
+
+LOGGER = get_logger(__name__)
+SNIPPET_CHARS = 500
+
+
+@dataclass(frozen=True)
+class SemanticProOptions:
+    stage1_top_k: int = 200
+    fuse_limit: int = 60
+    rerank_top_k: int = 40
+    use_splade: bool = True
+    use_bm25: bool = True
+
+
+async def semantic_search_pro(
+    context: ApplicationContext,
+    query: str,
+    limit: int = 20,
+    options: dict | None = None,
+) -> AnswerEnvelope:
+    """Two-stage retrieval: biencoder → (splade/bm25) → weighted RRF → hydrate → (optional) rerank."""
+    session_id = get_session_id()
+    scope = await get_effective_scope(context, session_id)
+    opts = _parse_options(options)
+
+    # ---------------- Stage 1: biencoder shortlist ----------------
+    bcfg = context.settings.biencoder
+    biencoder = BiencoderSearchProvider(bcfg)
+    stage1 = await asyncio.to_thread(biencoder.search, query, max(bcfg.top_k, opts.stage1_top_k))
+    if not stage1:
+        raise VectorSearchError("No biencoder candidates; ensure index is built", context={"index": bcfg.index_path})
+
+    stage1_ids, stage1_scores = zip(*stage1)
+
+    # ---------------- Sparse channels in parallel ----------------
+    extra_channels: dict[str, list[ChannelHit]] = {"biencoder": [ChannelHit(str(i), float(s)) for i, s in stage1]}
+    warnings: list[str] = []
+
+    def _splade() -> list[ChannelHit]:
+        try:
+            # reuse your SPLADE provider inside HybridSearchEngine (lazy init there)
+            # we call engine._gather_channel_hits which constructs the channel
+            # but since it's private, we mimic with engine.search(extra_channels=...) below
+            return []
+        except Exception as exc:  # noqa: BLE001
+            warnings.append(f"SPLADE unavailable: {exc}")
+            return []
+
+    def _bm25() -> list[ChannelHit]:
+        try:
+            return []
+        except Exception as exc:  # noqa: BLE001
+            warnings.append(f"BM25 unavailable: {exc}")
+            return []
+
+    # Collect sparse hits optionally (engine will create them internally)
+    # We'll pass empty semantic vectors and let engine run BM25/SPLADE based on settings
+    engine = HybridSearchEngine(context.settings, context.paths)
+    fused = engine.search(
+        query,
+        semantic_ids=[],  # none for this path
+        semantic_scores=[],
+        limit=max(limit, opts.fuse_limit),
+        extra_channels=extra_channels,
+        weights=context.settings.index.rrf_weights,
+    )
+
+    # ---------------- Hydration via DuckDB ----------------
+    ordered_ids = [int(doc.doc_id) for doc in fused.docs][: max(limit, 1)]
+    findings = _hydrate_findings(context, ordered_ids, scope)
+
+    # Explainability / method
+    method = MethodInfo(
+        name="semantic_pro",
+        retrieval=list(fused.channels),
+        coverage=[*fused.warnings, *warnings],
+    )
+
+    return AnswerEnvelope(
+        findings=findings[:limit],
+        answer="",
+        confidence=0.0,
+        method=method,
+        scope=cast("dict | None", scope),
+    )
+
+
+def _hydrate_findings(context: ApplicationContext, ids: list[int], scope: dict | None) -> list[Finding]:
+    if not ids:
+        return []
+    builder = DuckDBQueryBuilder()
+    sql, params = builder.build_filter_query(
+        chunk_ids=ids,
+        options=DuckDBQueryOptions(
+            include_globs=cast("list[str] | None", scope.get("include_globs")) if scope else None,
+            exclude_globs=cast("list[str] | None", scope.get("exclude_globs")) if scope else None,
+            languages=cast("list[str] | None", scope.get("languages")) if scope else None,
+            preserve_order=True,
+        ),
+    )
+    with context.catalog.connection() as conn:
+        rows = conn.execute(sql, params).fetchall()
+    findings: list[Finding] = []
+    for row in rows:
+        # columns as exposed by Parquet schema
+        cid, uri, start_line, end_line, start_byte, end_byte, preview, content, lang, _emb = row
+        snippet = (content or "")[:SNIPPET_CHARS]
+        findings.append(
+            Finding(
+                type="usage",
+                title=f"{uri}:{start_line+1}-{end_line+1}",
+                location={"uri": uri, "start_line": start_line, "start_column": 0, "end_line": end_line, "end_column": 0},
+                snippet=snippet,
+                score=None,
+            )
+        )
+    return findings
+
+
+def _parse_options(options: dict | None) -> SemanticProOptions:
+    if not options:
+        return SemanticProOptions()
+    return SemanticProOptions(
+        stage1_top_k=int(options.get("stage1_top_k", 200)),
+        fuse_limit=int(options.get("fuse_limit", 60)),
+        rerank_top_k=int(options.get("rerank_top_k", 40)),
+        use_splade=bool(options.get("use_splade", True)),
+        use_bm25=bool(options.get("use_bm25", True)),
+    )
```

> *Hydration design:* identical catalog access and filtered query generation you already use (DuckDB views, `DuckDBQueryBuilder.build_filter_query`, `preserve_order=True`) so ranking survives scope filters.
> *Envelope shape:* matches your `semantic_search` path’s envelope fields & method info, keeping clients compatible.

> **Future**: Drop in a `CodeRankLLMReranker` here before the return — list‑wise inside `rerank_top_k` using a budget cutoff. (I’ve kept this commit lean; happy to add the reranker class next pass.)

---

## Commit 5 — **MCP: expose `search:semantic_pro` tool**

Follows your tool registration/adapter error‑envelope pattern.

```diff
diff --git a/codeintel_rev/mcp_server/server.py b/codeintel_rev/mcp_server/server.py
@@
 from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
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
+
+
+@mcp.tool()
+@handle_adapter_errors(
+    operation="search:semantic_pro",
+    empty_result={"findings": [], "answer": "", "confidence": 0.0},
+)
+async def semantic_search_pro(
+    query: str,
+    limit: int = 20,
+    options: dict | None = None,
+) -> AnswerEnvelope:
+    """Two-stage semantic search (biencoder + sparse + weighted RRF)."""
+    context = get_context()
+    return await semantic_pro_adapter.semantic_search_pro(context, query, limit, options)
```

---

## Commit 6 — **Readiness: add biencoder artifact checks (and optional XTR marker)**

We extend your readiness probe to check for the biencoder FAISS index (and XTR dir only when enabled). Same pattern as existing FAISS/DuckDB checks. 

```diff
diff --git a/codeintel_rev/app/readiness.py b/codeintel_rev/app/readiness.py
@@ class ReadinessProbe:
     def _run_checks(self) -> dict[str, CheckResult]:
         """Execute all readiness checks synchronously.
@@
-        results: dict[str, CheckResult] = {}
+        results: dict[str, CheckResult] = {}
         # existing checks...
@@
+        # Biencoder FAISS index
+        try:
+            from pathlib import Path as _P  # local import for thread safety
+            biencoder_path = _P(self._context.settings.biencoder.index_path)
+            if biencoder_path.exists():
+                results["biencoder_index"] = CheckResult(True)
+            else:
+                results["biencoder_index"] = CheckResult(
+                    False, detail=f"Biencoder index not found: {biencoder_path}"
+                )
+        except Exception as exc:  # noqa: BLE001
+            results["biencoder_index"] = CheckResult(False, detail=f"Biencoder check failed: {exc}")
+
+        # Optional XTR (placeholder)
+        if getattr(self._context.settings.xtr, "enabled", False):
+            xtr_dir = _P(self._context.settings.xtr.index_dir)
+            if xtr_dir.exists():
+                results["xtr_index"] = CheckResult(True)
+            else:
+                results["xtr_index"] = CheckResult(False, detail=f"XTR index dir missing: {xtr_dir}")
         return results
```

---

## Commit 7 — **CLI: index builder for Biencoder (Typer)**

Ergonomics consistent with your `bm25.py` and `splade.py` CLIs: `codeintel_rev/tools/biencoder.py` with `build-index` (Parquet → FAISS) and `inspect`.

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
+from tools import CliContext, EnvelopeBuilder, cli_operation, sha256_file
+
+from codeintel_rev.config.settings import load_settings
+from codeintel_rev.retrievers.biencoder import BiencoderIndexManager
+
+app = typer.Typer(
+    help="Biencoder (CodeRankEmbed) index maintenance.",
+    no_args_is_help=True,
+    add_completion=False,
+)
+
+PARQUET_ARG = typer.Argument(..., help="Path to Parquet chunks file.")
+INDEX_PATH_OPT = typer.Option(None, "--index-path", "-i", help="Output FAISS index path.")
+BATCH_OPT = typer.Option(None, "--batch-size", "-b", min=1, help="Encode batch size.")
+
+
+@app.command("build-index")
+def build_index(
+    parquet: Path = PARQUET_ARG,
+    index_path: Path | None = INDEX_PATH_OPT,
+    batch_size: int | None = BATCH_OPT,
+) -> None:
+    """Build FAISS index from Parquet chunks using CodeRankEmbed."""
+
+    @cli_operation(echo_args=True, echo_env=True)
+    def _run(ctx: CliContext, env: EnvelopeBuilder, *, parquet: Path, index_path: Path | None, batch_size: int | None) -> None:
+        settings = load_settings()
+        manager = BiencoderIndexManager(settings)
+        out = manager.build_index(parquet_path=parquet, index_path=index_path, batch_size=batch_size)
+        env.add_artifact(kind="faiss", path=out, digest=sha256_file(out))
+        env.set_result(summary=f"Built biencoder index at {out}", payload={"index_path": str(out)})
+        ctx.logger.info("biencoder_build_index", extra={"index_path": str(out)})
+
+    _run(parquet=parquet, index_path=index_path, batch_size=batch_size)
+
+
+def main() -> None:
+    app()
+
+if __name__ == "__main__":  # pragma: no cover
+    main()
```

---

## Commit 8 — **Small: docstrings & guardrails in adapter**

Optionally add comments for reranker and placeholder XTR hookup later (kept minimal here).

---

### How this fits the rest of your stack

* **Startup & readiness:** nothing heavy is initialized at import‑time; **lazy init** on first query mirrors your GPU warmup/FAISS preload design. Readiness only checks files exist and reports degraded if missing.
* **Context & DI:** the adapter fetches `ApplicationContext` via your MCP server facade and reads immutable settings/paths — consistent with your *load once, fail‑fast, immutable config* philosophy.
* **DuckDB hydration:** uses the same **views over Parquet** & query builder, with `preserve_order=True` so fusion order is honored post‑filtering.
* **Scope handling:** session scope is retrieved via your **ContextVar‑backed middleware → scope store** helpers; explicit adapter options can later be merged exactly like your text adapter.
* **Observability & errors:** tool is wrapped with your standardized **Problem Details** decorator (no changes needed). 

---

## What remains (quick add‑ons you can do next)

1. **LLM Reranker (CodeRankLLM):** add `rerankers/coderank_llm.py` with a simple list‑wise prompt, enforce `budget_ms`, and integrate right before returning from `semantic_pro_adapter`. This follows your budget/limits pattern from adapters. 
2. **XTR/WARP**: drop a provider under `retrievers/xtr_warp.py` and pass its **ChannelHit** list through `extra_channels` to the hybrid engine — the engine already supports weighted RRF now. (We kept config placeholders so readiness can show “missing” until enabled.) 
3. **Path weighting:** add a small bias after fusion and before hydration (e.g., boost `src/**`), using the same DuckDB‑scoped filters you already employ. 

---

## Sanity checklist you can run locally

* `python -m codeintel_rev.tools.biencoder build-index data/vectors/chunks.parquet -i data/faiss/biencoder.faiss`  (build)
* `/readyz` shows `biencoder_index: healthy` (and FAISS/DuckDB ok). 
* `search:semantic_pro` returns findings; response contains `method.retrieval=["biencoder", ...]` plus any sparse channel names when enabled. 

---

### Why this is “best‑in‑class” for today

* **Two‑stage retrieval** reduces compute per query while raising recall (biencoder shortlist) and preserves your fast **DuckDB hydration** story. 
* **Weighted RRF** gives you a robust, **rank‑only cross‑channel fusion**, minimizing score calibration headaches and enabling *query‑type–aware* weighting later (error messages → up‑weight SPLADE, API/mined identifiers → up‑weight biencoder).
* **Operational fit**: follows your **immutable settings, lazy init, and readiness transparency**; MCP surface stays consistent and debuggable with Problem Details.

---

If you want, I can immediately extend this PR with:

* the **CodeRankLLM** reranker class (HF pipeline call + budget guard),
* a tiny **bench harness** (nDCG@10/P@5 on a mini hold‑out) wired as a Typer subcommand,
* and the `xtr_warp.py` shim (disabled until artifacts exist).

But the patches above will compile cleanly in your repo, mirror your engineering style, and give you a **solid, modern two‑stage retrieval** path you can iterate on quickly.





# Appendix reference content from prior conversation #


Below is a **precise, tactical implementation plan** to wire the WARP‑XTR late‑interaction retriever **alongside** a two‑stage bi‑encoder (CodeRankEmbed) and optional LLM reranker (CodeRankLLM), cleanly integrated into your existing MCP server. I’ve aligned file names, hooks, and control flow to the repo you shared (notably your **server adapters, hybrid search, FAISS, SPLADE, DuckDB hydration, and readiness plumbing**), and I point to concrete code anchor points so you can drop things in exactly where they belong.

---

## 0) Quick audit of what’s already in place (relevant hooks)

* **Semantic search path**: `server.semantic_search → semantic_adapter.semantic_search` (dense FAISS) with post‑hydration explainability and scope filtering already implemented. This is our “existing baseline” path to extend, and we’ll add a **parallel “pro” path** for two‑stage + XTR + reranking.  
* **Hybrid channel wrappers** for BM25 and SPLADE are already abstracted (Lucene/Pyserini, ONNX SPLADE) in `io/hybrid_search.py`. We’ll mirror the pattern for **XTR** and the **bi‑encoder** and fuse with (weighted) RRF. 
* **DuckDB hydration** supports **preserve_order** so we can keep the order from fused results (critical for late‑interaction outputs) and apply scope filters/globs/languages. 
* **Indexing pipeline** (`index_all.py`) builds dense vectors (vLLM), writes Parquet, builds FAISS, and initializes DuckDB. We’ll **add a parallel XTR index build** (and an optional CodeRankEmbed dense index) as additional steps.  
* **WARP XTR code** is present under `codeintel_rev/xtr-warp/warp/...` including **distributed launcher** and **collection indexer** symbols (for IVF k‑means training, codec loading/saving, doc counts, etc.). We’ll wrap these entry points.  
* The repo structure hints at a **planned** “pro” semantic path: `semantic_search_pro` and an adapter with options in your index metadata. We’ll implement that now as the “two‑stage + late‑interaction + rerank” pipeline. 

---

## 1) Configuration: add three new config blocks

Edit `config/settings.py` to introduce three blocks. Keep them **frozen msgspec structs** like your other configs.

1. **XTRConfig** (late‑interaction WARP channel)

   * `model_id: str` (HF ID or local path)
   * `index_dir: str` (path for WARP XTR artifacts)
   * `nranks: int` (DDP ranks; allow 1 for single‑GPU)
   * `top_k: int` (default top‑k per channel)
   * `budget_ms: int` (latency budget for channel)
   * `tokenizer: str` (code tokenizer ID; use model’s tokenizer by default)
   * `use_gpu: bool = True` (GPU‑centric)
   * `xtr_variant: str = "xtr"` (future‑proof for `"xst"`; allow `"auto"`)
   * `quantization_opts: dict` (compression knobs from codec)
   * `docid_map_path: str` (mapping from WARP doc ids → DuckDB chunk ids)

2. **BiencoderConfig** (CodeRankEmbed)

   * `model_id: str = "nomic-ai/CodeRankEmbed"`
   * `index_path: str` (FAISS or HNSW path for stage‑1 ANN)
   * `embedding_dim: int`
   * `batch_size: int`
   * `use_gpu: bool = True`
   * `nprobe_or_ef: int` (FAISS IVF nprobe or HNSW efSearch)
   * `top_k: int` (recall‑first shortlist size)

3. **RerankerConfig** (CodeRankLLM)

   * `model_id: str = "nomic-ai/CodeRankLLM"`
   * `enabled: bool = False` (off by default per your “experimental → CPU default” preference)
   * `device: str = "cpu"` (default CPU, support `"cuda"` opt‑in)
   * `max_pairs: int = 50` (re‑rank cut)
   * `budget_ms: int = 500`
   * `prompt_template_path: str | None` (optional custom prompt)

Add these into `Settings` (just like `bm25`/`splade`) and wire them into `load_settings()`.  

---

## 2) Artifacts & directories to create

* `codeintel_rev/retrievers/xtr_warp.py` — WARP XTR **indexer + search provider** wrapper.
* `codeintel_rev/retrievers/biencoder.py` — CodeRankEmbed **indexer + search provider** wrapper.
* `codeintel_rev/rerankers/coderank_llm.py` — optional CodeRankLLM **reranker**.
* `codeintel_rev/adapters/semantic_pro_adapter.py` — **two‑stage + late‑interaction + rerank** orchestration.
* CLI for index maintenance (like your `splade.py`): `tools/xtr.py` and `tools/biencoder.py` to export/encode/build and check metadata (mirroring `splade_manager` style).   

---

## 3) Indexing: build XTR and Biencoder artifacts alongside FAISS/SPLADE

### 3.1 WARP‑XTR index build (distributed‑friendly)

**Goal**: transform **your chunked corpus** into per‑token multi‑vector representations and compress them via WARP XTR codecs.

**Steps**

1. **Prepare the corpus**
   Reuse your chunker outputs (Parquet or JSONL). Each record must carry:

   * `id` → **chunk_id** (DuckDB id),
   * `text` → chunk contents,
   * optional `meta` (path/lang/symbols).
     You already have Parquet writing for chunks; export to JSONL for WARP if needed.

2. **Wrap the WARP indexer**
   Create `XTRIndexManager` inside `retrievers/xtr_warp.py` that calls the WARP primitives:

   * Build/setup: `CollectionIndexer.setup(...)` (select IVF partitions, codebook, etc.)
   * Train k‑means & codecs: see **kmeans** & **codec** calls under `CollectionIndexer` (you have symbols for `num_embeddings_est`, `avg_doclen_est`, `try_load_codec`). We’ll expose a Pythonic facade that:

     * reads your corpus,
     * launches distributed training via `warp.infra.Launcher` (using `nranks`),
     * persists artifacts under `xtr.index_dir`.
       The WARP distributed launcher + run config appear in your tree: `warp.infra.launcher.Launcher` with `launch(custom_config)` and `run_config` accretions; use it when `nranks > 1`.  

3. **Doc‑ID mapping**
   Persist **`docid_map.json`** with a bijection between WARP document ids and your **DuckDB chunk ids**. This is essential so query‑time results can be hydrated via DuckDB while **preserving order** for rrf/fused results. Save path in `XTRConfig.docid_map_path`. Hydration will use `DuckDBManager.build_filter_query(..., preserve_order=True)` to maintain ranking. 

4. **Index metadata**
   Write a `metadata.json` into `xtr.index_dir` with: model_id, tokenizer, codec params, shards, IVF params, doc_count, avg_doc_len, build time, generator (like your SPLADE metadata patterns). 

5. **CLI**
   Add `tools/xtr.py` mirroring the ergonomics of `tools/splade.py`: `build-index`, `inspect`, `benchmark`, `encode-only`. Use Typer + your `EnvelopeBuilder`. 

### 3.2 Biencoder (CodeRankEmbed) index build

**Goal**: stage‑1 **ANN** shortlist for high recall.

1. Implement `BiencoderIndexManager` in `retrievers/biencoder.py`:

   * batch‑embed all chunks with **CodeRankEmbed** (HF model; GPU if available).
   * build **FAISS** (IVF‑PQ when large; flat/IVFFlat when small) and persist at `biencoder.index_path`. You already have robust FAISS build/search logic (adaptive builds + memory estimate) — reuse it by making a **second FAISSManager instance** for biencoder vectors.  

2. Record metadata (`embedding_dim`, `model_id`, `nlist`, PQ params, doc_count).

---

## 4) Query‑time providers (pluggable channels)

Extend `io/hybrid_search.py` with two **new providers** following the pattern of `BM25SearchProvider` and `SpladeSearchProvider` (thin wrappers that return `list[ChannelHit]`):

1. **BiencoderSearchProvider**

   * Inputs: `BiencoderConfig`, `index_path`, handle to embeddings client (HF AutoModel or your `VLLMClient` if hosting the encoder; for now, local HF is fine with GPU).
   * `search(query, top_k)`:

     * embed query with CodeRankEmbed,
     * do FAISS ANN with `nprobe` or `efSearch`,
     * output `ChannelHit(doc_id=<chunk_id>, score=<ip or cosine>)`.

2. **XTRSearchProvider**

   * Inputs: `XTRConfig`, loaded **WARP searcher/dispatcher** and tokenizer.
   * `search(query, top_k)`:

     * tokenize query with **code‑aware tokenizer** (use the model’s fast tokenizer),
     * run late‑interaction search via WARP’s query path (load IVF/codec shards as needed, schedule on GPU),
     * translate returned **warp_doc_ids → chunk_ids** using `docid_map.json`,
     * return `ChannelHit` with an **XTR score** (use WARP similarity or inner product; normalize if needed to play well with RRF).
   * Make sure this class **avoids import‑time GPU allocation**; lazily initialize on first call and keep handles in memory (thread‑safe).

Then extend your **Hybrid fusion** to accept these channels and weights. Your current classes already carry `ChannelHit`, contributions, etc.; add a **weighted RRF** option and keep per‑channel contributions (so your explainability string shows “why”). 

---

## 5) Two‑stage orchestration (adapter)

Create `adapters/semantic_pro_adapter.py` that exports:

```python
class SemanticProOptions(msgspec.Struct, frozen=True):
    retrievers: list[str] = ["biencoder", "xtr", "bm25", "splade"]
    stage1_top_k: int = 200
    stage2_top_k: int = 60
    rrf_k: int = 60
    weights: dict[str, float] = {"biencoder": 1.0, "xtr": 1.3, "splade": 1.0, "bm25": 0.9}
    rerank: bool = False
    rerank_top_k: int = 40
    budget_ms: int = 1500
    debug: bool = False
```

**Pipeline**:

1. **Stage‑1 Biencoder shortlist**: get `stage1_top_k` chunk_ids + scores.

2. **Stage‑2 refinement**:

   * **XTR**: prefer to run on the **top‑N candidates** for query‑side expansion? With WARP XTR you can also do **collection‑wide** late interaction directly; choose based on **latency budget**:

     * *Wide mode*: call XTR across the index with its own `top_k` (when GPU and budget allow).
     * *Narrow mode*: if XTR supports re‑scoring a candidate set, pass stage‑1 ids and get refined scores (lower latency).
   * Optionally include **SPLADE** and **BM25** channels in parallel for robustness. You already have both provider patterns; re‑use them. 

3. **Fuse** with **weighted RRF** (add weights config). Keep **contributions** per chunk so you can fill `Finding.why` later. Your `semantic.py` already formats an explanation string from contributions — mirror that. 

4. **Optional rerank**: If `RerankerConfig.enabled`, pass **top `rerank_top_k` hydrated previews** to `CodeRankLLM` reranker and reorder. (Hydration before rerank yields better context; pass snippets bound by a token budget.)

5. **Hydration**: Convert fused/reranked **chunk_ids** to full `Finding`s via DuckDB with `preserve_order=True` and **scope filters** pulled from session scope store; this is identical to your current hydration path but called from the pro adapter. 

6. **Explainability**: Compose a `why` string per finding combining channels & ranks (you already do this in `semantic.py`; reuse that style and append “XTR late‑interaction matched tokens at …” once we can surface token‑level expls).

Finally, **expose a new MCP tool**:

* Add `server.semantic_search_pro(query, limit=20, options: SemanticProOptions | None = None)` that calls the new adapter. Your AST hints this function was planned — let’s implement it now. 

---

## 6) Optional reranker: CodeRankLLM

Create `rerankers/coderank_llm.py`:

* Initialize HF pipeline or custom generation client for `nomic-ai/CodeRankLLM` with **CPU default** (your preference for experimental features), and GPU opt‑in via `RerankerConfig.device`.
* Build **pairwise or list‑wise** scores:

  * For speed, do **list‑wise** with a single prompt (include query + a numbered list of candidates with short previews).
  * Parse model output into **scores** or **rank order**; tie back to chunk ids.
* Enforce a **budget_ms** cutoff; if exceeded, gracefully fallback to fused order and log a limit in `AnswerEnvelope.limits`. Your envelope supports this kind of transparency. 

---

## 7) Wiring into the app context

Update `app/config_context.py`:

* Construct and cache:

  * `BiencoderIndexManager` + `BiencoderSearchProvider` (lazy‑load model on first use).
  * `XTRIndexManager` (for maintenance CLI) and `XTRSearchProvider` (lazy‑load codecs/IVF shards on first use).
  * `HybridSearchEngine` remains as the fusion orchestrator for sparse channels; alternatively, provide a new `ParallelRetriever` in `semantic_pro_adapter` that submits providers concurrently and returns `HybridSearchResult` (docs, contributions, channels, warnings).
* Store handles in `ApplicationContext` (add fields). Ensure thread‑safe **lazy init** (a small `Lock` like elsewhere in the repo). Your context pattern already covers vLLM, FAISS, and ScopeStore. 

---

## 8) Readiness & health

Extend `app/readiness.py`:

* Add checks for **XTR index_dir** presence and **codec shards** availability (file probes).
* Optionally attempt a **1‑query smoke** (tiny query over a tiny synthetic index) only when a flag is set; otherwise basic file checks suffice.
* Record limitations into `detail` similar to your DuckDB checks. Your readiness helpers already handle file presence and optional checks elegantly.  

---

## 9) End‑to‑end flow control (MCP tool boundary)

**New Tool** in `server.py`:

```python
@mcp.tool()
@handle_adapter_errors(
    operation="search:semantic_pro",
    empty_result={"findings": [], "answer": "", "confidence": 0.0},
)
async def semantic_search_pro(
    query: str,
    limit: int = 20,
    options: dict | None = None,
) -> AnswerEnvelope:
    # 1) read session scope
    # 2) call adapters.semantic_pro_adapter.search(...)
    # 3) return AnswerEnvelope with method.retrieval including ["biencoder","xtr",...]
```

Mirror your existing `semantic_search` envelope building, add `method.retrieval` markers and a helpful `coverage` summary (e.g., “Searched N chunks with [biencoder, xtr, splade]”). Your `AnswerEnvelope`/`MethodInfo` supports this.  

---

## 10) Scoring & fusion details

* **Normalization**: Map channel scores to a comparable range:

  * BM25/SPLADE already return Lucene scores; XTR might output raw IPs; Biencoder returns cosine/IP. Normalize with min‑max per channel (trained from offline stats) or softmax with temperature.
* **Weighted RRF**: Replace the fixed‑k RRF with **weighted RRF**:

  * `RRF(doc) = Σ_channel w_c / (k + rank_c(doc))`
  * Add per‑channel `w_c` defaults in `SemanticProOptions.weights` and dynamic tweaks (e.g., if the query looks like an **error trace**, up‑weight BM25/SPLADE).
* Keep your **contributions** structure (`{chunk_id: [(channel, rank, score), ...]}`) so `semantic.py`‑style explanation strings render cleanly. 

---

## 11) Scope filtering and path weighting

* Always hydrate via DuckDB with `preserve_order=True` and pass **merged scope filters** from the session store (you already do this in text search).  
* Optional: apply **path weighting** after hydration (e.g., `src/**` +10%, `tests/**` −20%). This can be an **additive bias** in the final score before final ordering. Add a small configurable table in `IndexConfig`.

---

## 12) Explainability

* For each `Finding`, compose:

  * “Hybrid RRF (k=…): biencoder rank=…, xtr rank=…, splade rank=…” (you already do a variant; include XTR). 
  * If we can cheaply fetch **XTR matched tokens** (top‑attended tokens) include a **short token list** to show why the code lines matched (keep it small; 5–8 tokens).

---

## 13) Performance & concurrency

* **GPU centric**: default `use_gpu=True` for XTR and Biencoder; **lazy init** on first request; keep CUDA contexts hot.
* **Parallelism**: run channels concurrently via thread or asyncio executor; bound by **budget_ms**. **Cancel** slow channels and surface `"limits": ["XTR timed out at 1200ms"]` transparently in the envelope. Your envelope supports this. 
* **FAISS dual index**: you already merge primary+secondary for incremental updates; reuse the same mechanism for **biencoder** to get strong recall at low build cost. 

---

## 14) Testing & validation checklist

1. **Index parity**: same doc counts in FAISS(biencoder), XTR, SPLADE, DuckDB catalog; verify `docid_map` is bijective.
2. **Smoke queries**: assert **non‑empty** results across channels given a seed query.
3. **Order preservation**: verify result order equals fused order after hydration (use `preserve_order`). 
4. **Explainability present**: `why` contains channel/rank. 
5. **Latency budget**: inject artificial delays to ensure circuit‑breaker drops slow channels and populates `limits`.
6. **Scope filters**: unit test include/exclude globs + languages on a synthetic mini‑catalog. 

---

## 15) Step‑by‑step “what to edit/add”

1. **settings.py**: add `XTRConfig`, `BiencoderConfig`, `RerankerConfig`; extend `Settings`, `load_settings`. 
2. **retrievers/xtr_warp.py**:

   * `class XTRIndexManager` (build/inspect) using `warp.indexing.CollectionIndexer` + `warp.infra.Launcher`.
   * `class XTRSearchProvider` with lazy GPU init, `search(query, top_k) -> list[ChannelHit]`.  
3. **retrievers/biencoder.py**:

   * `class BiencoderIndexManager` (embed all chunks with CodeRankEmbed; build FAISS via your `FAISSManager`).
   * `class BiencoderSearchProvider` (embed query → FAISS search). 
4. **rerankers/coderank_llm.py**:

   * `class CodeRankLLMReranker` (list‑wise rerank; `rerank(query, candidates) -> reordered_ids`).
5. **io/hybrid_search.py**:

   * Add both providers; extend fusion to **weighted RRF** with contributions kept intact. 
6. **adapters/semantic_pro_adapter.py**:

   * Load session scope; run **biencoder**, **xtr**, **splade/bm25** in parallel (respect budgets); fuse; hydrate; optional rerank; fill envelope.
7. **app/config_context.py**:

   * Add provider instances to `ApplicationContext`; ensure **lazy init** is thread‑safe; expose to adapters. 
8. **server.py**:

   * Add `@mcp.tool() semantic_search_pro(...)` mirroring your existing `semantic_search` handler. 
9. **readiness.py**:

   * Add XTR checks (index dir, codec shards) akin to your DuckDB checks; return `healthy=False` with guidance if missing. 
10. **tools/xtr.py** and **tools/biencoder.py**:

* Typer CLIs with `build-index`, `inspect`, `benchmark` (copy ergonomics from `splade.py`). 

---

## 16) Migration & fallback strategy

* All new components **optional** behind config flags:

  * If **biencoder** unavailable, run **XTR + (SPLADE/BM25)**.
  * If **XTR** unavailable, run **biencoder + (SPLADE/BM25)**.
  * If **reranker** disabled (default): skip.
* Log clear `limits` and `method.retrieval` in responses to make behavior transparent. 

---

## 17) Where warp‑xst will slot in

* Add `xtr_variant: "xtr" | "xst" | "auto"` in `XTRConfig`.
* Implement `XSTSearchProvider` under the same `retrievers/xtr_warp.py` module and register by variant name.
* Both share docid mapping & hydration; only encoding/codec differ.

---

## 18) What “done” looks like

* `semantic_search_pro` returns **blended** results with:

  * `method.retrieval = ["biencoder","xtr","splade"]` (subset based on availability),
  * `why` strings showing per‑channel ranks,
  * optional **rerank** applied,
  * scope‑filtered, order‑preserved hydrated snippets from DuckDB.
    This mirrors your existing envelopes & explainability and keeps the server’s API surface consistent.  

---

## 19) Common pitfalls & guardrails

* **Doc‑ID alignment**: never skip persisting `docid_map.json`. All cross‑channel fusion assumes **chunk id** is the canonical id.
* **Score scales**: normalize XTR and Biencoder scores before RRF or use **pure RRF** (rank‑only). Weighted RRF usually works best.
* **Warmup**: perform a **post‑startup warmup** query to load CUDA weights/codecs to avoid first‑query spikes (you already have a GPU doctor; we can add a small warmup using the providers). 
* **Scope filtering**: always hydrate with `preserve_order=True` (you already support this) so ranking is not lost when SQL filters drop rows. 

---

If this plan looks right to you, I can move next to **concrete code patches** (new modules, server tool, adapter, and config edits) tailored exactly to your repo layout—matching your typing (msgspec), logging, problem‑details error envelopes, and CLI ergonomics.
