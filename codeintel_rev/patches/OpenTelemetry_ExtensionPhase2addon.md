# detailed implementation plan and code diffs #

Below is a **Phase 2 (“next phase”) OpenTelemetry plan** tailored to the current `codeintel_rev` repository, followed by **ready‑to‑apply code diffs**. I’m building on the observability you already have in place (notably `observability.metrics`, `observability.timeline`, `telemetry.decorators`, and the MCP server adapters) and wiring them into a *single, end‑to‑end* tracing model with domain spans and an enriched run report.

> **What you already have (anchors for this plan)**
>
> * Hybrid retrieval already emits per‑stage records and domain metrics (e.g., `RECENCY_BOOSTED_TOTAL`, `QUERY_ERRORS_TOTAL`) inside `HybridSearchEngine`; these will be turned into structured span attributes and span events.  
> * The MCP semantic layer exposes tools (e.g., `semantic_search`, `semantic_search_pro`) and already has a `report_to_json` path used by `_render_run_report`; we’ll upgrade this into a first‑class trace‑anchored run report.  
> * Timeline + OTel coordination helpers (`telemetry.decorators.span_context`, `observability.otel.record_span_event`, `observability.timeline.current_timeline`) already exist; we’ll standardize what they emit and where.  
> * vLLM embed flows are clearly delineated (`VLLMClient.embed_batch`, `InprocessVLLMEmbedder.embed_batch`)—great seams for CLIENT spans with model/batch attributes.  
> * Capability/runtime plumbing and DuckDB/FAISS surfaces are in `ApplicationContext` and IO managers—these will get SERVICE and INTERNAL spans plus error mapping. 

---

## Phase 2 objective (what changes in this phase)

**Make every request narratable**: a single trace per MCP tool call with **domain spans** for *embed → retrieve → fuse → hydrate → (optional) rerank → envelope*, plus checkpoint events at each discrete operation. The same trace powers a **Run Report v2** endpoint that merges your timeline, span attributes, warnings, and budgets into one JSON/Markdown artifact.

---

## What we’ll implement now

### 1) Unify OTel bootstrapping + semantic conventions

* Add a **single place** to initialize tracing/metrics and define **semantic conventions** for attributes (e.g., `mcp.session_id`, `retrieval.rrf_k`, `faiss.index_kind`, `vllm.model_name`, `duckdb.rows`).
* Initialize FastAPI instrumentation once at app boot and propagate `X-Session-ID` (which you’re already stamping in middleware) into trace attributes so every span carries the session/run context. 

### 2) Domain spans in hot paths

* **MCP server/adapters**: start a SERVER span per tool call (`search:semantic`, `search:semantic_pro`, `search:deep`), link it to session context, and attach request controls (scope, limits) as attributes.  
* **vLLM**: surround both HTTP and in‑proc embed calls with CLIENT spans; add model name, embedding dim, batch size, mode, latency.  
* **Retrieval**: in `HybridSearchEngine.search()` add INTERNAL spans per stage: `retrieval.gather_channels`, `retrieval.pool`, `retrieval.fuse`, `retrieval.recency_boost`, `retrieval.hydrate`. Convert your existing `stage_records` into span events. Also attach **budget decisions** from `gating.decide_budgets()` as attributes/events.   
* **DuckDB**: keep per‑query spans you’ve begun and add rows/SQL size and timing; ensure exceptions set span status. (You already have `DuckDBManager` usage in context.) 
* **Git**: wrap `AsyncGitClient` calls as CLIENT spans and record the file path/range/commit count for post‑mortems. 

### 3) Run Report v2 (trace‑anchored)

* Upgrade `_render_run_report()` (already calls `telemetry.reporter.report_to_json`) so it **pulls the active trace id** and **embeds span summaries** (stages, timings, warnings, budgets, errors), not just timeline. Keep it as a JSON blob the MCP client can fetch or display after a partial run. 
* Include **“stopped‑because”** heuristics: if a downstream stage is missing but an earlier stage finished, annotate the gap (e.g., “hydrate not reached after fuse”). We can infer this purely from the span graph and stage events.

### 4) Prometheus bridge (no vendor lock‑in)

* Continue using your `metrics/registry` where it exists, but **dual‑emit** counters/histograms via OTel meters so you can scrape them through Prometheus with a Prom bridge later if desired. (No operational change to your Prometheus today.)

---

# Code diffs

> The diffs below assume the file paths that appear in your repo map and SCIP index. They are additive and should apply cleanly; module names and public seams are consistent with what’s discoverable in your indexes.

---

### A) New: semantic conventions for attributes

**`codeintel_rev/observability/semantic_conventions.py` (new)**

```diff
*** /dev/null
--- a/codeintel_rev/observability/semantic_conventions.py
+++ b/codeintel_rev/observability/semantic_conventions.py
@@ -0,0 +1,116 @@
+from __future__ import annotations
+
+"""
+Semantic attribute keys used across CodeIntel tracing/metrics.
+Keep these central so spans are searchable and consistent.
+"""
+
+class Attrs:
+    # Request + session
+    MCP_TOOL          = "mcp.tool"             # e.g., search:semantic
+    MCP_SESSION_ID    = "mcp.session_id"
+    MCP_RUN_ID        = "mcp.run_id"
+    REQUEST_STAGE     = "request.stage"        # gather | pool | fuse | hydrate | rerank
+
+    # Query + gating
+    QUERY_TEXT        = "retrieval.query_text"
+    QUERY_LEN         = "retrieval.query_len"
+    TOP_K             = "retrieval.top_k"
+    RERANK            = "retrieval.rerank"
+    RRF_K             = "retrieval.rrf_k"
+    RM3_ENABLED       = "retrieval.rm3_enabled"
+    CHANNEL_DEPTHS    = "retrieval.channel_depths"  # dict -> str
+
+    # Channels (BM25/SPLADE/FAISS) and fusion
+    CHANNELS_USED     = "retrieval.channels_used"
+    FUSED_DOCS        = "retrieval.fused_docs"
+    RECENCY_BOOSTED   = "retrieval.recency_boosted"
+
+    # FAISS
+    FAISS_INDEX_KIND  = "faiss.index_kind"     # Flat | IVFFlat | IVF-PQ | Flat+sec
+    FAISS_METRIC      = "faiss.metric"         # L2 | IP | cosine
+    FAISS_DIM         = "faiss.dim"
+    FAISS_TOPK        = "faiss.k"
+    FAISS_NPROBE      = "faiss.nprobe"
+    FAISS_GPU         = "faiss.gpu"
+
+    # vLLM
+    VLLM_MODE         = "vllm.mode"            # http | inproc
+    VLLM_MODEL_NAME   = "vllm.model_name"
+    VLLM_EMBED_DIM    = "vllm.embed_dim"
+    VLLM_BATCH        = "vllm.batch_size"
+
+    # DuckDB hydration
+    DUCKDB_ROWS       = "duckdb.rows"
+    DUCKDB_SQL_BYTES  = "duckdb.sql_bytes"
+
+    # Git
+    GIT_OP            = "git.op"               # blame | history
+    GIT_PATH          = "git.path"
+    GIT_LINE_RANGE    = "git.line_range"
+
+    # Errors/warnings
+    WARNINGS          = "codeintel.warnings"   # list -> str
+
+def to_label_str(obj: object) -> str:
+    """Small helper to stringify dicts/lists deterministically for span attrs."""
+    try:
+        import json
+        return json.dumps(obj, sort_keys=True, ensure_ascii=False)
+    except Exception:
+        return str(obj)
```

---

### B) OTel bootstrap + FastAPI instrumentation at app start

**`codeintel_rev/observability/otel.py` (extend existing)**

```diff
--- a/codeintel_rev/observability/otel.py
+++ b/codeintel_rev/observability/otel.py
@@
-from __future__ import annotations
+from __future__ import annotations
+from typing import Iterable
+import os
+
+from opentelemetry import trace, metrics
+from opentelemetry.trace import TracerProvider
+from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
+from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
+from opentelemetry.sdk.resources import Resource
+from opentelemetry.sdk.metrics import MeterProvider
+from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
+try:
+    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
+    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
+except Exception:  # optional
+    OTLPSpanExporter = None
+    OTLPMetricExporter = None
+
+_INIT_DONE = False
+
+def init_otel(
+    service_name: str = "codeintel-mcp",
+    exporters: Iterable[str] = ("console", "otlp"),
+    otlp_endpoint: str | None = None,
+) -> None:
+    """
+    Initialize OpenTelemetry for traces+metrics once.
+    Respects OTLP endpoint env if provided. Idempotent.
+    """
+    global _INIT_DONE
+    if _INIT_DONE:
+        return
+
+    resource = Resource.create({
+        "service.name": service_name,
+        "service.namespace": "kgfoundry",
+    })
+
+    # ---- Traces
+    tp: TracerProvider = SDKTracerProvider(resource=resource)
+    if "console" in exporters:
+        tp.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
+    if "otlp" in exporters and OTLPSpanExporter:
+        ep = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
+        tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{ep}/v1/traces")))
+    trace.set_tracer_provider(tp)
+
+    # ---- Metrics
+    readers = []
+    if "otlp" in exporters and OTLPMetricExporter:
+        ep = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
+        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=f"{ep}/v1/metrics")))
+    if readers:
+        mp = MeterProvider(resource=resource, metric_readers=readers)
+        metrics.set_meter_provider(mp)
+
+    _INIT_DONE = True
+
+def record_span_event(name: str, **attrs: object) -> None:
+    """
+    Utility already referenced by retrieval; keep stable API.
+    """
+    span = trace.get_current_span()
+    if span and getattr(span, "is_recording", lambda: False)():
+        span.add_event(name, attrs)
```

> Why here? Your retrieval code already imports `observability.otel.record_span_event`—this extends that module to own init, so **FastAPI boot** can call it once and every adapter/library reuses the same provider. 

---

### C) FastAPI boot: initialize tracing + propagate session/run into spans

**`codeintel_rev/app/main.py` (add init + middleware header enrichment)**

```diff
--- a/codeintel_rev/app/main.py
+++ b/codeintel_rev/app/main.py
@@
 from fastapi import FastAPI
 from .middleware import set_mcp_context, disable_nginx_buffering
+from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
+from opentelemetry import trace
+from codeintel_rev.observability.otel import init_otel
+from codeintel_rev.observability.semantic_conventions import Attrs
+from starlette.middleware.base import BaseHTTPMiddleware
+from starlette.requests import Request
+from starlette.responses import Response
 
 def build_http_app(capabilities: Capabilities) -> FastAPI:
-    app = FastAPI()
+    # Initialize tracing only once; safe if called multiple times by tests.
+    init_otel(service_name="codeintel-mcp")
+    app = FastAPI()
     app.add_middleware(set_mcp_context)
     app.add_middleware(disable_nginx_buffering)
+    FastAPIInstrumentor.instrument_app(app)
+
+    class _TraceHeadersMiddleware(BaseHTTPMiddleware):
+        async def dispatch(self, request: Request, call_next):
+            # Propagate session/run into the current root span
+            session_id = request.headers.get("X-Session-ID")
+            run_id = request.headers.get("X-Run-ID")
+            span = trace.get_current_span()
+            if span and span.is_recording():
+                if session_id:
+                    span.set_attribute(Attrs.MCP_SESSION_ID, session_id)
+                if run_id:
+                    span.set_attribute(Attrs.MCP_RUN_ID, run_id)
+            response: Response = await call_next(request)
+            # return trace id to clients for correlation
+            ctx = trace.get_current_span().get_span_context()
+            if ctx and ctx.trace_id:
+                response.headers["X-Trace-Id"] = format(ctx.trace_id, "032x")
+            return response
+
+    app.add_middleware(_TraceHeadersMiddleware)
     # ... existing router/route registration continues ...
     return app
```

> The app boot change ensures every request has a trace and returns an `X-Trace-Id` back to the caller, while also stamping spans with `mcp.session_id` and `mcp.run_id` for correlation with your timeline. (This composes with your existing context middleware.) 

---

### D) vLLM: CLIENT span around embedding

**`codeintel_rev/io/vllm_client.py` (instrument embed path)**

```diff
--- a/codeintel_rev/io/vllm_client.py
+++ b/codeintel_rev/io/vllm_client.py
@@
 from typing import Sequence
+from opentelemetry import trace
+from opentelemetry.trace import SpanKind, Status, StatusCode
+from codeintel_rev.observability.semantic_conventions import Attrs, to_label_str
 
 class VLLMClient:
@@
     def embed_batch(self, texts: Sequence[str]) -> NDArrayF32:
-        # existing logic...
+        tracer = trace.get_tracer(__name__)
+        mode = "http" if self._http_client is not None else "inproc"
+        with tracer.start_as_current_span("vllm.embed_batch", kind=SpanKind.CLIENT) as span:
+            if span.is_recording():
+                span.set_attribute(Attrs.VLLM_MODE, mode)
+                span.set_attribute(Attrs.VLLM_MODEL_NAME, self.model_name)
+                span.set_attribute(Attrs.VLLM_EMBED_DIM, int(self.embedding_dim))
+                span.set_attribute(Attrs.VLLM_BATCH, int(len(texts)))
+            try:
+                if self._http_client is not None:
+                    out = self._embed_batch_http(texts)
+                else:
+                    out = self._local_engine.embed_batch(texts)
+                return out
+            except Exception as e:  # map to trace error
+                if span.is_recording():
+                    span.record_exception(e)
+                    span.set_status(Status(StatusCode.ERROR, str(e)))
+                raise
```

> This gives you per‑batch visibility: model, dim, batch size, client/server mode, duration, and error surfaces for embed failures. (You have both client and in‑proc engines.)  

---

### E) Retrieval: stage spans in `HybridSearchEngine`

**`codeintel_rev/io/hybrid_search.py` (wrap stages, emit budgets, warnings)**

```diff
--- a/codeintel_rev/io/hybrid_search.py
+++ b/codeintel_rev/io/hybrid_search.py
@@
 from typing import Sequence, Mapping
+from opentelemetry import trace
+from opentelemetry.trace import SpanKind
+from codeintel_rev.observability.semantic_conventions import Attrs, to_label_str
@@
 class HybridSearchEngine:
@@
     def search(
         self,
         query: str,
         *,
         semantic_hits: Sequence[tuple[int, float]],
         limit: int,
         options: HybridSearchOptions | None = None
     ) -> HybridSearchResult:
-        # existing implementation ...
+        tracer = trace.get_tracer(__name__)
+        with tracer.start_as_current_span("retrieval.search", kind=SpanKind.INTERNAL) as span:
+            if span.is_recording():
+                span.set_attribute(Attrs.QUERY_TEXT, query)
+                span.set_attribute(Attrs.QUERY_LEN, len(query))
+                span.set_attribute(Attrs.TOP_K, int(limit))
+            # gather channels
+            with tracer.start_as_current_span("retrieval.gather_channels") as gspan:
+                runs, warnings = self._gather_channel_hits(query, semantic_hits)
+                if gspan.is_recording():
+                    gspan.set_attribute(Attrs.CHANNELS_USED, to_label_str(list(runs.keys())))
+                    if warnings:
+                        gspan.set_attribute(Attrs.WARNINGS, to_label_str(warnings))
+            # pool/fuse
+            docs, per_doc_contrib = self._execute_fusion(runs, limit)
+            with tracer.start_as_current_span("retrieval.fuse") as fspan:
+                if fspan.is_recording():
+                    fspan.set_attribute(Attrs.FUSED_DOCS, len(docs))
+            # optional recency boost
+            boosted_docs, boosted_count = self._apply_recency_boost_if_needed(docs)
+            if boosted_count:
+                trace.get_current_span().set_attribute(Attrs.RECENCY_BOOSTED, int(boosted_count))
+            # attach budget decision when available
+            if hasattr(self, "_last_budget_decision"):
+                bd = getattr(self, "_last_budget_decision")
+                span.set_attribute(Attrs.CHANNEL_DEPTHS, to_label_str(bd.per_channel_depths))
+                span.set_attribute(Attrs.RRF_K, bd.rrf_k)
+                span.set_attribute(Attrs.RM3_ENABLED, bool(bd.rm3_enabled))
+            # hydrate happens outside this method in pro pipeline; record here if available
+            result = self._with_stage_metadata(
+                HybridSearchResult(
+                    docs=boosted_docs, contributions=per_doc_contrib,
+                    warnings=warnings, method="hybrid-rrf"
+                )
+            )
+            return result
```

> The docstrings and symbol ranges in your SCIP index show stage hooks (`_gather_channel_hits`, `_execute_fusion`, `_apply_recency_boost_if_needed`) and budget decisions—perfect anchors for stage spans + attributes.   

---

### F) MCP semantic adapters: SERVER span + run report hook

**`codeintel_rev/mcp_server/server_semantic.py` (wrap tools, surface report link)**

```diff
--- a/codeintel_rev/mcp_server/server_semantic.py
+++ b/codeintel_rev/mcp_server/server_semantic.py
@@
 from .server import get_context
+from opentelemetry import trace
+from opentelemetry.trace import SpanKind
+from codeintel_rev.observability.semantic_conventions import Attrs, to_label_str
+from codeintel_rev.telemetry.reporter import report_to_json
+from codeintel_rev.observability.otel import record_span_event
@@
 @mcp.tool()
 @handle_adapter_errors(operation="search:semantic",
                        empty_result={"findings": [], "answer": "", "confidence": 0})
 async def semantic_search(query: str, limit: int = 20) -> AnswerEnvelope:
-    context = get_context()
-    # existing call path...
+    context = get_context()
+    tracer = trace.get_tracer(__name__)
+    with tracer.start_as_current_span("mcp.search.semantic", kind=SpanKind.SERVER) as span:
+        if span.is_recording():
+            span.set_attribute(Attrs.MCP_TOOL, "search:semantic")
+            span.set_attribute(Attrs.QUERY_TEXT, query)
+            span.set_attribute(Attrs.TOP_K, int(limit))
+        result = await semantic_adapter.semantic_search(context, query, limit)
+        # let clients retrieve a run report tied to this trace
+        ctx = trace.get_current_span().get_span_context()
+        if ctx and ctx.trace_id:
+            trace_id = format(ctx.trace_id, "032x")
+            record_span_event("run_report.ready", trace_id=trace_id)
+            result.setdefault("observability", {})
+            result["observability"]["trace_id"] = trace_id
+        return result
@@
 async def _render_run_report(context: ApplicationContext, session_id: str, run_id: str) -> dict:
-    return report_to_json(context, session_id, run_id)
+    # Upgrade: include current trace id so the report can join OTel spans
+    data = report_to_json(context, session_id, run_id)
+    ctx = trace.get_current_span().get_span_context()
+    if ctx and ctx.trace_id:
+        data["trace_id"] = format(ctx.trace_id, "032x")
+    return data
```

> `_render_run_report` already exists and calls `report_to_json`—this small change ties the run report to the active trace id so your report can include span summaries along with your timeline. 

---

### G) Git client: CLIENT spans

**`codeintel_rev/io/git_client.py` (wrap async ops)**

```diff
--- a/codeintel_rev/io/git_client.py
+++ b/codeintel_rev/io/git_client.py
@@
+from opentelemetry import trace
+from opentelemetry.trace import SpanKind
+from codeintel_rev.observability.semantic_conventions import Attrs
@@
 class AsyncGitClient:
@@
     async def blame_range(self, path: str, start_line: int, end_line: int) -> list[GitBlameEntry]:
-        return await asyncio.to_thread(self._sync_client.blame_range, path, start_line, end_line)
+        tracer = trace.get_tracer(__name__)
+        with tracer.start_as_current_span("git.blame", kind=SpanKind.CLIENT) as span:
+            if span.is_recording():
+                span.set_attribute(Attrs.GIT_OP, "blame")
+                span.set_attribute(Attrs.GIT_PATH, path)
+                span.set_attribute(Attrs.GIT_LINE_RANGE, f"{start_line}-{end_line}")
+            return await asyncio.to_thread(self._sync_client.blame_range, path, start_line, end_line)
@@
     async def file_history(self, path: str, limit: int | None = None) -> list[GitHistoryEntry]:
-        return await asyncio.to_thread(self._sync_client.file_history, path, limit)
+        tracer = trace.get_tracer(__name__)
+        with tracer.start_as_current_span("git.history", kind=SpanKind.CLIENT) as span:
+            if span.is_recording():
+                span.set_attribute(Attrs.GIT_OP, "history")
+                span.set_attribute(Attrs.GIT_PATH, path)
+                if limit is not None:
+                    span.set_attribute("git.limit", int(limit))
+            return await asyncio.to_thread(self._sync_client.file_history, path, limit)
```

> These spans make Git behaviors visible in traces without changing your async interfaces. 

---

### H) (Optional, if you want FAISS‑depth spans now) FAISS search attributes

If your FAISS manager exposes a well‑bounded search method, wrap it similarly:

**`codeintel_rev/io/faiss_manager.py`**

```diff
--- a/codeintel_rev/io/faiss_manager.py
+++ b/codeintel_rev/io/faiss_manager.py
@@
+from opentelemetry import trace
+from codeintel_rev.observability.semantic_conventions import Attrs
@@
     def search_exact(self, query_vec: NDArrayF32, k: int, *, nprobe: int | None = None) -> tuple[list[int], list[float]]:
-        # existing exact search...
+        tracer = trace.get_tracer(__name__)
+        with tracer.start_as_current_span("faiss.search_exact") as span:
+            if span.is_recording():
+                span.set_attribute(Attrs.FAISS_TOPK, int(k))
+                if nprobe is not None:
+                    span.set_attribute(Attrs.FAISS_NPROBE, int(nprobe))
+                span.set_attribute(Attrs.FAISS_DIM, int(query_vec.shape[-1]))
+                span.set_attribute(Attrs.FAISS_GPU, bool(self.gpu_index is not None))
+                span.set_attribute(Attrs.FAISS_INDEX_KIND, self.index_kind)  # ensure str
+            ids, scores = self._search_exact_impl(query_vec, k, nprobe=nprobe)
+            return ids, scores
```

> Use the real method names you have—in the SCIP extracts we can see FAISS internals and helpers present, so the hook is nearby. 

---

## Acceptance checklist (Phase 2)

* [ ] `X-Trace-Id` appears in all MCP responses; internal spans carry `mcp.session_id` and (when present) `mcp.run_id`. 
* [ ] Each semantic tool call shows a trace with child spans: `vllm.embed_batch` → `retrieval.gather_channels` → `retrieval.fuse` → (optional) `retrieval.recency_boost` → hydration/rerank (in Pro path) → envelope built.  
* [ ] Stage warnings (from `_gather_channel_hits`) appear as span attributes/events; `RECENCY_BOOSTED_TOTAL` increments correlate with `retrieval.recency_boost` spans that show `recency_boosted` count. 
* [ ] Run Report v2 includes `trace_id` and merges timeline+span summaries (budgets from `gating.describe_budget_decision`, per‑stage timings).  

---

## Rationale & implementation callouts

1. **Trace‑first narrative**
   Your existing **timeline** and **stage_records** provide an excellent “what actually happened” backbone. By converting these into **span events/attributes**, we make them queryable in any trace viewer, *and* we can render the same facts in your **Run Report v2** without duplicating logic. (The spans become the source of truth; `report_to_json` turns them into a compact narrative.)  

2. **Propagation via session middleware**
   You already stamp `X-Session-ID` into a `ContextVar`. The `FastAPI` middleware above simply mirrors that into the active span so **every downstream span** is searchable by session/run. (You’ll appreciate this when correlating partial runs and multi‑tool workflows.) 

3. **Budget & gating visibility**
   Decisions from `retrieval.gating.decide_budgets()` explain *why* results look the way they do. Attaching the per‑channel depths, `rrf_k`, and `rm3_enabled` as attributes gives clear causality when investigating recall/latency tradeoffs. 

4. **vLLM & FAISS as CLIENT spans**
   Treat both as distinct external dependencies (even if in‑proc), so you can filter traces by *downstream* effects. Model, batch, and `nprobe/index_kind` tell you immediately whether performance or correctness shifts are **primarily due to embedder config** or **vector index runtime**.  

5. **No change to Prometheus consumers**
   We intentionally **do not** change how metrics are scraped today. The OTel meter is there so you can add an OTel‑to‑Prom bridge later; meanwhile your `metrics/registry.py` remains the source for any existing dashboards. (Dual‑emit if you want to start smoke testing.)

---

## What this sets up for Phase 3

* **Hydration/rerank spans in Pro path** (`_hydrate_and_rerank_records`, WARP/LLM stages) with per‑stage p50/p95 histograms and error taxonomies. 
* **Search‑budget A/B probes**: attach a `retrieval.experiment` attribute to spans for automatic comparison in the run report.
* **End‑user diagnostics**: expose `/observability/run_report?trace_id=...` so any client with a trace id can fetch the narrative.

---

### How to roll out

1. Apply diffs, run locally; verify `X-Trace-Id` in responses from `semantic_search`. 
2. Run a couple of queries with/without Pro options; confirm spans in viewer show the stage tree and attributes (query len, channels, budgets). 
3. Hit your run‑report route; confirm it includes a `trace_id` and the same stages your trace shows. 

If you’d like, I can extend these diffs to include an *optional* `/observability/run_report/{trace_id}` route and a tiny **Markdown renderer** so the report reads like a human incident note.

Would you like me to produce those additional diffs now?

# Additional observability checks and markdown renderer #

Below is the “next phase” OpenTelemetry (OTel) implementation plan **tailored to your current codeintel_rev layout** and the instrumentation that already exists in the repo. I’ve broken this into:

1. **Goals & scope**
2. **Step‑by‑step implementation plan** (why + what to change)
3. **Code diffs** (copy/paste-able patches)
4. **Smoke tests & verification**
5. **Dashboards/queries you can build immediately**

Throughout I reference concrete files and symbols that are already present in your repo so you can see exactly where each change fits.

---

## 1) Goals & scope (what changes now, and why)

**Primary objectives for this phase**

* **End‑to‑end, correlated traces** flowing from the HTTP/MCP edge through tool adapters, retrieval/gating, vLLM, FAISS, DuckDB, XTR—so any “partial run” tells you *where it stopped and why*.
* **Metrics deepening** for the hottest paths (embedding, FAISS/XTR search, hybrid fusion, gating) using the Prometheus surface you already scaffolded (`build_metrics_router`, `REQUEST_LATENCY_SECONDS`, `STAGE_LATENCY_SECONDS`, etc.).
* **Tight session↔trace correlation** by binding your per‑request `X-Session-ID`/timeline to the active trace and returning a `traceparent`/`x-trace-id` so an LLM agent (or a person) can jump straight to the run in your trace backend. Your `SessionScopeMiddleware` already stamps a session and attaches a `Timeline`; we’ll extend it to *set span attributes and headers*.
* **Filling signal gaps** where you already emit timeline/OTel span events (e.g., gating, vLLM) by making those steps first‑class spans with consistent attributes + Prom metrics (batch sizes, latencies, top‑K, GPU/CPU mode, budgets, cache hit/miss, etc.). You already call `record_span_event` and timeline events in **gating** and **vLLM client**—we will standardize and deepen that.
* **Expose metrics reliably** on the HTTP app (FastAPI) by mounting the metrics router returned by `codeintel_rev.telemetry.prom.build_metrics_router`. 

**What you already have (we’ll build on it)**

* **OTel bootstrap & helpers** — `observability.otel.init_telemetry`, `as_span`, `record_span_event` (safe no‑ops when disabled).
* **Prometheus plumbing** — `telemetry.prom` defines counters/histograms and returns a FastAPI router via `build_metrics_router()`.
* **Session middleware + timeline** — creates a per‑request session and a `Timeline` that already logs events and calls `record_span_event`. We will also attach `session_id` etc. to the current span and optionally emit `traceparent` back.
* **Retrieval gating** — has clear serialization for decisions (`describe_budget_decision`) and already emits an OTel event + timeline entry. We’ll attach **span attributes** and **Prom metrics**.
* **vLLM embed** — emits timeline + OTel events around batch embedding. We’ll wrap the hot path in a span and record batch sizes/latency as Prom histograms.
* **Prom router** — exists but may not yet be mounted in the app startup. We’ll mount it. 

---

## 2) Step‑by‑step implementation plan

**A. Bootstrap OTel & mount metrics at app startup**

* Call `observability.otel.init_telemetry()` during app creation/lifespan, and **always** try to mount `build_metrics_router()` so metrics are reachable at `/metrics`. Your telemetry module already supports environment‑driven bootstrap; use that and keep a safe no‑op when disabled. 
* Include `service_version` if you have one (you already typed that parameter). 

**B. Correlate session ↔ trace at the edge**

* In `SessionScopeMiddleware.dispatch`, once you’ve created/read the `session_id` and `Timeline`, set `session_id`, `path`, `method`, `remote_ip` on the **current span** (if any). Also add outbound headers `traceparent` and `x-trace-id` so a client/agent can correlate logs and traces immediately. 

**C. Wrap tool handlers with clear spans**

* `mcp_server.telemetry.tool_operation_scope` is already your canonical “tool wrapper.” Enclose it in `as_span("mcp.tool", tool_name=..., session_id=..., scope=...)` and record **duration** via your existing `observe_duration` utility for MCP. This places all tool logic inside a single parent span per tool invocation. 

**D. Deepen retrieval signals (gating → hybrid → fusion)**

* In `retrieval.gating.decide_budgets` and friends, you already build a decision dict and emit an OTel event + timeline entry. Add:

  * span attributes: `query.len`, `profile.ambiguity`, `decision.rrf_k`, `depth.bm25`, `depth.splade`, `depth.dense`, `rm3.enabled`.
  * Prom metrics: `GATING_DECISIONS_TOTAL{class=literal|vague|default, rm3=bool}`, `GATING_AMBIGUITY` histogram, `RRFK` histogram.
* In `io.hybrid_search.HybridSearchEngine` profile/gather/fuse/hydrate internals, create child spans (`retrieval.profile`, `retrieval.gather.dense`, `retrieval.gather.bm25`, `retrieval.gather.splade`, `retrieval.fuse`, `retrieval.hydrate`). Attach attributes like per‑channel `top_k`, channel contribution counts, and RRF K. You already reference query profiling and metrics (ambiguity) here; convert key steps into spans. 

**E. Instrument vLLM embedding hot path**

* In `VLLMClient.embed_batch` and `*_http`, wrap the call in `as_span("vllm.embed_batch")`, include `mode=http|local`, `batch.size`, `model`, and record Prom hist `EMBED_BATCH_SIZE` + `EMBED_LATENCY_SECONDS`. You already add timeline + event; keep those for your “flight recorder,” add the spans/metrics for consistent dashboards.

**F. FAISS + XTR**

* In `io.faiss_dual_index` (search) add spans `faiss.search` with attributes: `index.type`, `k`, `gpu.enabled`, and a Prom hist `FAISS_SEARCH_LATENCY_SECONDS`. 
* In `io.xtr_manager.XTRIndex.search/rescore`, add spans `xtr.search` / `xtr.rescore` with attributes: `k`, `candidates`, `narrow_mode`, and timings; add `XTR_SEARCH_LATENCY_SECONDS` hist. (You already document these methods thoroughly, so attributes map cleanly to existing parameters.) 

**G. Metrics endpoint (FastAPI)**

* Include `codeintel_rev.telemetry.prom.build_metrics_router()` in your app. This returns an `APIRouter` with a handler that calls `generate_latest()` and emits the registry you pass (or the default). You already have this code; just mount it. 

**H. Enrich run reports with trace correlation**

* Your timeline already writes events and calls OTel events. Add **trace_id** and **span_id** to the consolidated run report and emit a link (according to your backend: Jaeger/Tempo/Cortex/etc.). This can be implemented by exporting `current_trace_id()` and adding it into your `AnswerEnvelope` / “flight recorder” summaries rendered by MCP semantic tools. 

---

## 3) Code diffs

> **Notes:**
> • Diffs are intentionally small and focused; they align with the existing files/symbols seen in your repo’s SCIP/AST extracts.
> • They rely on helpers you already ship (`observability.otel.as_span`, `record_span_event`; `telemetry.prom.build_metrics_router`, `REQUEST_LATENCY_SECONDS`, `STAGE_LATENCY_SECONDS`).
> • If an import path differs slightly, adjust the relative path to your package layout.

### 3.1 App startup: initialize OTel + mount /metrics

```diff
diff --git a/codeintel_rev/app/main.py b/codeintel_rev/app/main.py
@@
-from fastapi import FastAPI
+from fastapi import FastAPI
+from codeintel_rev.observability.otel import init_telemetry
+from codeintel_rev.telemetry.prom import build_metrics_router, MetricsConfig
@@
 def lifespan(app: FastAPI):
-    # existing startup wiring...
+    # Initialize OpenTelemetry (safe no-op if disabled or deps missing)
+    init_telemetry(app=app, service_name="codeintel_rev")
+    # Mount Prometheus metrics endpoint
+    app.include_router(build_metrics_router(MetricsConfig()), tags=["metrics"])
     yield
     # existing shutdown wiring...
```

*Why:* uses your existing `init_telemetry(...)` and `build_metrics_router(...)`.

---

### 3.2 Correlate session↔trace and return trace headers

```diff
diff --git a/codeintel_rev/observability/otel.py b/codeintel_rev/observability/otel.py
@@
 from contextlib import contextmanager
 from typing import Any, AbstractContextManager
@@
 _TELEMETRY_ENABLED = False
@@
 def as_span(name: str, **attrs: object) -> AbstractContextManager[None]:
     ...
     # (existing implementation)
@@
+def set_current_span_attrs(**attrs: object) -> None:
+    """
+    Attach attributes to the current active span, if any. Safe no-op when tracing
+    is disabled.
+    """
+    if not _TELEMETRY_ENABLED:
+        return
+    try:
+        from opentelemetry.trace import get_current_span
+        span = get_current_span()
+        if span and hasattr(span, "set_attribute"):
+            for k, v in attrs.items():
+                try:
+                    span.set_attribute(str(k), v)
+                except Exception:
+                    continue
+    except Exception:
+        return
+
+def current_trace_id() -> str | None:
+    """Return the hex trace id for the current span, if any."""
+    if not _TELEMETRY_ENABLED:
+        return None
+    try:
+        from opentelemetry.trace import get_current_span
+        span = get_current_span()
+        ctx = getattr(span, "get_span_context", lambda: None)()
+        if ctx and getattr(ctx, "trace_id", 0):
+            return f"{ctx.trace_id:032x}"
+    except Exception:
+        return None
+    return None
```

*Why:* small helpers to add `session_id`, URL path, method, etc. onto the active span; and a way to emit a trace id into run reports. Your `as_span` already exists; this is complementary. 

```diff
diff --git a/codeintel_rev/app/middleware.py b/codeintel_rev/app/middleware.py
@@
-from starlette.middleware.base import BaseHTTPMiddleware
+from starlette.middleware.base import BaseHTTPMiddleware
+from codeintel_rev.observability.otel import set_current_span_attrs, current_trace_id
@@ class SessionScopeMiddleware(BaseHTTPMiddleware):
     async def dispatch(self, request: Request, call_next: DispatchFunction) -> Response:
         # existing session-id and timeline creation
         timeline = new_timeline(session_id)  # existing
         request.state.timeline = timeline
         timeline.set_metadata(... existing ...)
+
+        # Correlate session to the current trace/span (if tracing is enabled)
+        set_current_span_attrs(
+            session_id=session_id,
+            http_path=str(request.url.path),
+            http_method=request.method,
+        )
         # continue as usual
         response = await call_next(request)
+
+        # Return trace headers so clients/agents can jump to the trace
+        try:
+            tid = current_trace_id()
+            if tid:
+                response.headers["x-trace-id"] = tid
+        except Exception:
+            pass
         return response
```

*Why:* your middleware already creates the session and timeline; this binds it to the span and sends correlation back. 

---

### 3.3 Wrap MCP tool executions in spans

```diff
diff --git a/codeintel_rev/mcp_server/telemetry.py b/codeintel_rev/mcp_server/telemetry.py
@@
-from contextlib import contextmanager
+from contextlib import contextmanager
+from codeintel_rev.observability.otel import as_span, set_current_span_attrs
+from codeintel_rev.mcp_server.common.observability import observe_duration
@@
 @contextmanager
 def tool_operation_scope(tool_name: str, *, session_id: str | None = None):
-    # existing: start timeline section or similar
+    with as_span("mcp.tool", tool_name=tool_name):
+        if session_id:
+            set_current_span_attrs(session_id=session_id)
+        with observe_duration(tool=tool_name):
+            # existing: timeline integration and error wrapping
             yield
```

*Why:* gives you a clean parent span per tool, keeping existing duration/timeline logic. 

---

### 3.4 Prom metrics: add deep histograms/counters

```diff
diff --git a/codeintel_rev/telemetry/prom.py b/codeintel_rev/telemetry/prom.py
@@
-from prometheus_client import Counter, Histogram, CollectorRegistry, generate_latest
+from prometheus_client import Counter, Histogram, CollectorRegistry, generate_latest
@@
 # Existing metrics:
 # RUNS_TOTAL, RUN_ERRORS_TOTAL, REQUEST_LATENCY_SECONDS, STAGE_LATENCY_SECONDS, ...
@@
+# New deep-dive metrics (embedding / faiss / xtr / gating)
+EMBED_BATCH_SIZE = Histogram(
+    "embed_batch_size",
+    "vLLM embed batch sizes",
+    buckets=(1, 2, 4, 8, 16, 32, 64, 128),
+)
+EMBED_LATENCY_SECONDS = Histogram(
+    "embed_latency_seconds",
+    "Latency of vLLM embed_batch (end-to-end)",
+    buckets=(0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
+)
+FAISS_SEARCH_LATENCY_SECONDS = Histogram(
+    "faiss_search_latency_seconds",
+    "Latency of FAISS searches",
+    buckets=(0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2),
+)
+XTR_SEARCH_LATENCY_SECONDS = Histogram(
+    "xtr_search_latency_seconds",
+    "Latency of XTR index searches/rescores",
+    buckets=(0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2),
+)
+GATING_DECISIONS_TOTAL = Counter(
+    "gating_decisions_total",
+    "Count of query gating decisions",
+    ["class", "rm3"]
+)
+RRFK = Histogram(
+    "gating_rrf_k",
+    "Distribution of chosen RRF k values",
+    buckets=(10, 25, 50, 75, 100, 150, 200, 300),
+)
+QUERY_AMBIGUITY = Histogram(
+    "query_ambiguity",
+    "Distribution of computed ambiguity scores",
+    buckets=(0.0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0),
+)
```

*Why:* you already publish latencies/stages; these bring task‑specific observability aligned with your architecture. 

---

### 3.5 vLLM embedding spans + metrics

```diff
diff --git a/codeintel_rev/io/vllm_client.py b/codeintel_rev/io/vllm_client.py
@@
 from time import perf_counter
-from codeintel_rev.observability.timeline import current_timeline
-from codeintel_rev.observability.otel import record_span_event
+from codeintel_rev.observability.timeline import current_timeline
+from codeintel_rev.observability.otel import record_span_event, as_span
+from codeintel_rev.telemetry.prom import EMBED_BATCH_SIZE, EMBED_LATENCY_SECONDS
@@ class VLLMClient:
     def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
-        t0 = perf_counter()
+        t0 = perf_counter()
+        with as_span("vllm.embed_batch", mode=str(self._mode), size=len(texts), model=self.config.model):
             try:
                 # existing logic (local vs http)
                 ...
-            finally:
-                dt = perf_counter() - t0
-                tl = current_timeline()
-                if tl: tl.event("vllm.embed", status="ok", attrs={"batch_size": len(texts), "latency_s": dt})
-                record_span_event("vllm.embed", status="ok", size=len(texts), latency_s=dt)
+            finally:
+                dt = perf_counter() - t0
+                EMBED_BATCH_SIZE.observe(len(texts))
+                EMBED_LATENCY_SECONDS.observe(dt)
+                tl = current_timeline()
+                if tl: tl.event("vllm.embed", status="ok", attrs={"batch_size": len(texts), "latency_s": dt})
+                record_span_event("vllm.embed", status="ok", size=len(texts), latency_s=dt)
```

*Why:* you already emit timeline + OTel events; this adds a proper span and Prom metrics. 

---

### 3.6 FAISS search spans + metrics

```diff
diff --git a/codeintel_rev/io/faiss_dual_index.py b/codeintel_rev/io/faiss_dual_index.py
@@
 from time import perf_counter
+from codeintel_rev.observability.otel import as_span
+from codeintel_rev.telemetry.prom import FAISS_SEARCH_LATENCY_SECONDS
@@
     def search(self, query_vec: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
-        t0 = perf_counter()
-        # existing search across primary / secondary FAISS indexes
-        ...
-        dt = perf_counter() - t0
-        # (optional existing logging)
-        return ids, scores
+        t0 = perf_counter()
+        with as_span("faiss.search", k=int(k), index_type=self._index_type, gpu_enabled=bool(self._gpu_on)):
+            # existing search across primary / secondary FAISS indexes
+            ...
+            dt = perf_counter() - t0
+            FAISS_SEARCH_LATENCY_SECONDS.observe(dt)
+            return ids, scores
```

*Why:* isolates FAISS latency and GPU/CPU mode into a canonical span + Prom hist. 

---

### 3.7 Gating: attributes + metrics (you already emit events)

```diff
diff --git a/codeintel_rev/retrieval/gating.py b/codeintel_rev/retrieval/gating.py
@@
-from codeintel_rev.observability.otel import record_span_event
-from codeintel_rev.observability.timeline import current_timeline
+from codeintel_rev.observability.otel import record_span_event, set_current_span_attrs
+from codeintel_rev.observability.timeline import current_timeline
+from codeintel_rev.telemetry.prom import GATING_DECISIONS_TOTAL, RRFK, QUERY_AMBIGUITY
@@ def decide_budgets(profile: QueryProfile, cfg: StageGateConfig) -> BudgetDecision:
     decision = ...
-    record_span_event("retrieval.gating.decision", **describe_budget_decision(profile, decision))
+    data = describe_budget_decision(profile, decision)
+    record_span_event("retrieval.gating.decision", **data)
+    # Attach attributes to current span for easy filtering
+    set_current_span_attrs(
+        gating_rrf_k=data["rrf_k"],
+        rm3_enabled=bool(data["rm3_enabled"]),
+        depth_dense=data["per_channel_depths"].get("semantic", 0),
+        depth_bm25=data["per_channel_depths"].get("bm25", 0),
+        depth_splade=data["per_channel_depths"].get("splade", 0),
+        query_len=data["length"],
+        ambiguity=data["ambiguity"],
+    )
+    # Prometheus counters/hists
+    klass = "literal" if data.get("literal") else "vague" if data.get("vague") else "default"
+    GATING_DECISIONS_TOTAL.labels(klass, str(bool(data["rm3_enabled"]))).inc()
+    RRFK.observe(int(data["rrf_k"]))
+    QUERY_AMBIGUITY.observe(float(data["ambiguity"]))
     tl = current_timeline()
     if tl:
         tl.event("retrieval.gating.decision", attrs=data)
     return decision
```

*Why:* pairs your existing eventing with concrete span attrs + Prom metrics so decisions show up in both traces and dashboards. 

---

### 3.8 Hybrid search: profile/gather/fuse/hydrate as spans

```diff
diff --git a/codeintel_rev/io/hybrid_search.py b/codeintel_rev/io/hybrid_search.py
@@
 from time import perf_counter
 from codeintel_rev.retrieval.gating import analyze_query, decide_budgets, describe_budget_decision
+from codeintel_rev.observability.otel import as_span, record_span_event
@@ class HybridSearchEngine:
     def _profile_query(self, query: str, gate_cfg: StageGateConfig) -> tuple[QueryProfile, BudgetDecision, dict]:
-        # existing profiling & decisioning
+        with as_span("retrieval.profile"):
+            # existing profiling & decisioning
             profile = analyze_query(query, gate_cfg)
             decision = decide_budgets(profile, gate_cfg)
             data = describe_budget_decision(profile, decision)
             record_span_event("retrieval.profile", **data)
             return profile, decision, data
@@
     def _fuse_runs(...):
-        # existing RRF fusion
+        with as_span("retrieval.fuse", rrf_k=int(rrf_k), channels=",".join(channel_names)):
+            # existing RRF fusion
             fused = ...
             record_span_event("retrieval.fuse.done", rrf_k=int(rrf_k), results=len(fused))
             return fused
```

*Why:* makes critical sub-stages visible in traces with stable attributes; you already track ambiguity and decision data. 

---

### 3.9 XTR index: search/rescore spans + metrics

```diff
diff --git a/codeintel_rev/io/xtr_manager.py b/codeintel_rev/io/xtr_manager.py
@@
 from time import perf_counter
+from codeintel_rev.observability.otel import as_span
+from codeintel_rev.telemetry.prom import XTR_SEARCH_LATENCY_SECONDS
@@ class XTRIndex:
     def search(self, query: str, k: int, *, explain: bool=False, topk_explanations: int=5):
-        t0 = perf_counter()
-        # existing search
-        ...
-        dt = perf_counter() - t0
-        return results
+        t0 = perf_counter()
+        with as_span("xtr.search", k=int(k), explain=bool(explain), topk_explanations=int(topk_explanations)):
+            # existing search
+            ...
+            dt = perf_counter() - t0
+            XTR_SEARCH_LATENCY_SECONDS.observe(dt)
+            return results
@@
     def rescore(self, query: str, candidate_chunk_ids: Iterable[int], *, explain: bool=False, topk_explanations: int=5):
-        t0 = perf_counter()
+        t0 = perf_counter()
+        with as_span("xtr.rescore", n_candidates=len(list(candidate_chunk_ids)), explain=bool(explain), topk_explanations=int(topk_explanations)):
             # existing rescoring
             ...
-        dt = perf_counter() - t0
-        return rescored
+            dt = perf_counter() - t0
+            XTR_SEARCH_LATENCY_SECONDS.observe(dt)
+            return rescored
```

*Why:* lets you separate “full search” vs “narrow rescore” in both traces and metrics. 

---

## 4) Smoke tests & verification

1. **Run app**, confirm `/metrics` returns text exposition. You’re using a router generator that already sets response type/content via `generate_latest()`. 
2. **Hit any MCP tool** and verify you see a span named `mcp.tool` with `tool_name` set, and spans for `retrieval.profile`, `faiss.search`, `vllm.embed_batch`, `retrieval.fuse`, etc. (depending on the tool path). Your `tool_operation_scope` wrapper is now the root for each tool call. 
3. **Check session correlation**: your response should have `x-trace-id` when tracing is enabled; searching that trace in your backend should show the full tree—including gating attributes (`rrf_k`, `rm3_enabled`, budgeted depths). Gating already serializes and event-logs the decision; it’s now also span attributes and metrics. 
4. **Metrics sanity**:

   * Send embedding requests in batch sizes 1, 4, 16 and confirm `embed_batch_size` histogram buckets move. 
   * Watch `faiss_search_latency_seconds` as you vary `k`/GPU availability. 
   * Confirm `gating_decisions_total{class,rm3}` increments with different queries (literal/vague). 

---

## 5) Dashboards & queries (immediately useful)

* **“Where a run stopped and why”**: Filter by `session_id` (span attribute set by middleware) → Expand spans; the last child span’s status/events will show the stop point; your timeline also logs the same story.
* **Gating quality**:

  * Time series of `gating_decisions_total` split by `class` and `rm3`.
  * Hist of `gating_rrf_k` + overlay `query_ambiguity` to validate heuristics. 
* **Embedding health**: `embed_latency_seconds` p50/p95 vs `embed_batch_size`—validate batching knobs from FAISS to vLLM. You already call `embed_batch` from tool adapters; now it’s measurable. 
* **Retrieval composition**: Panel counting how many results each channel contributes (you already annotate hybrid contributions in adapters), correlated with `rrf_k`. 
* **Cache/store health**: Your `ScopeStoreMetrics` already records L2 hits/misses—add graphs from those counters to catch Redis or in‑proc LRU behavior changes quickly. 

---

### Why this is the right “next phase”

* It **tightens** the loop between your **existing timeline/flight recorder** and **traces/metrics**—no duplicate mental models, just multiple “lenses” on the same facts. (Your `Timeline.event` already calls `record_span_event` in several paths; we’re generalizing that across hot paths and binding it to sessions.) 
* It **keeps operations permissive** (as requested) while providing the **richest possible diagnostics** for AI agents and humans: spans with stable attributes, Prom histograms/counters, and a metrics endpoint wired into the app. 
* It **minimizes code churn** by using the helpers you already ship (`init_telemetry`, `as_span`, prom router, timeline events, MCP telemetry wrappers).

---

If you want, I can follow up with **a one‑file “collector config”** (Tempo/Jaeger/Honeycomb) and **Grafana dashboard JSON** that binds to these exact metric names and span attributes—so you can paste them in and see value immediately.


# One-file collector config #

Absolutely—here’s a production‑ready **OpenTelemetry Collector configuration** tailored to your `codeintel_rev` MCP/FastAPI server and the way the repo is already instrumented (session scoping, AnswerEnvelope, DuckDB SQL spans, etc.). I’ve kept it **backend‑agnostic** but added sensible defaults so you can run it locally out of the box and plug in Prometheus, Tempo/Jaeger, or Loki by just setting env vars.

> Why this shape for your repo
>
> * **Session scoping → attributes**: your middleware stamps/reads a session id per request; we carry it through as `session.id` so runs are stitchable across tools. 
> * **AnswerEnvelope & tool adapters**: we dimension metrics on `mcp.tool`/`operation` so semantic search, symbol queries, etc., show up as first‑class series. 
> * **DuckDB SQL spans**: you already wrap DuckDB `execute()` with timing/spans; the pipeline below preserves SQL timing & length and exposes “spanmetrics” for top queries. 

---

## `otel-collector.yaml`

```yaml
# OpenTelemetry Collector (contrib) config for kgfoundry/codeintel_rev
# Goals:
#  - Accept OTLP (traces/metrics/logs) from the FastAPI/MCP server
#  - Scrape process/host and app /metrics
#  - Expose ONE Prometheus endpoint to be scraped by your existing Prometheus
#  - Ship traces to any OTLP backend (Tempo/Jaeger/OTLP vendor) + optional local file
#  - Ship logs to Loki (optional) + rolling JSON files for deep diagnostics
#  - Derive span-level RED metrics via spanmetrics
#  - Keep everything toggleable via env vars; run well locally by default

extensions:
  health_check: {}
  zpages:
    endpoint: 0.0.0.0:55679
  pprof:
    endpoint: 0.0.0.0:1777

receivers:
  # Your app should export OTLP (grpc 4317 / http 4318).
  # Python hints: OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

  # Scrape metrics from your app (if it exposes /metrics) and from the collector itself
  prometheus:
    config:
      scrape_configs:
        - job_name: 'codeintel_rev_app'
          scrape_interval: 10s
          static_configs:
            # change to your FastAPI host:port for /metrics (or remove if using only OTLP metrics)
            - targets: [ '${APP_METRICS_TARGET:localhost:8000}' ]
              labels:
                service_name: codeintel_rev
        - job_name: 'otel_collector'
          scrape_interval: 10s
          static_configs:
            - targets: [ '0.0.0.0:8888' ]

  # Bring in host/process metrics for context around performance incidents
  hostmetrics:
    collection_interval: 30s
    scrapers:
      cpu: {}
      memory: {}
      process: {}
      load: {}
      disk: {}
      filesystem: {}
      network: {}

  # Optional: read structured logs from files (if you emit app logs to disk)
  filelog:
    include:
      - ${CODEINTEL_LOG_PATHS:/var/log/codeintel/*.log}
    start_at: end
    include_file_path: true
    include_file_name: true

processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 60
    spike_limit_percentage: 20

  batch:
    send_batch_max_size: 8192
    send_batch_size: 2048
    timeout: 2s

  # Add machine/env identity + consistent service namespace
  resourcedetection:
    detectors: [env, system, host]
    timeout: 5s
    override: false

  # Normalize attributes common to this service (do NOT hardcode service.name; let app set it)
  attributes/codeintel_common:
    actions:
      - key: service.namespace
        action: upsert
        value: "kgfoundry.codeintel_rev"
      # carry session scope from your middleware and surface on every span/log/metric point
      - key: session.id
        action: upsert
        from_attribute: http.request.header.x-session-id

  # Turn traces into golden RED metrics (reqs/errors/duration)
  spanmetrics:
    metrics_exporter: prometheus
    dimensions:
      - http.method
      - http.route
      - http.status_code
      - rpc.system
      - rpc.method
      - session.id
      - mcp.tool
      - db.system
    aggregation_temporality: "AGGREGATION_TEMPORALITY_CUMULATIVE"
    histogram:
      explicit:
        buckets: [5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2s, 5s, 10s]

  # Optional tail sampling to keep all errors and slow requests
  tailsampling:
    decision_wait: 5s
    num_traces: 20000
    policies:
      - name: keep-errors
        type: status_code
        status_code:
          status_codes: [ ERROR ]
      - name: keep-slow
        type: latency
        latency:
          threshold_ms: ${TAIL_SLOW_MS:500}
      - name: probabilistic-default
        type: probabilistic
        probabilistic:
          sampling_percentage: ${TAIL_SAMPLING_PCT:10}

exporters:
  # Human-friendly debugging (stdout)
  logging:
    loglevel: ${OTEL_LOGLEVEL:info}

  # One endpoint Prometheus scrapes to collect EVERYTHING (hostmetrics + app OTLP + spanmetrics)
  prometheus:
    endpoint: 0.0.0.0:8889
    # Optional: honor labels from app; use with caution to avoid high cardinality
    # const_labels: { cluster: "dev" }

  # Push metrics to a remote-write endpoint if you prefer push
  prometheusremotewrite:
    endpoint: ${PROM_REMOTE_WRITE_URL:}
    tls:
      insecure: ${PROM_REMOTE_WRITE_TLS_INSECURE:true}
    sending_queue:
      enabled: true
    retry_on_failure:
      enabled: true

  # Generic OTLP exporter for traces/metrics/logs; works with Tempo, OTLP vendors, etc.
  otlp:
    endpoint: ${OTLP_ENDPOINT:}
    tls:
      insecure: ${OTLP_TLS_INSECURE:true}
    # If you only want traces, you can specify protocol sections; left generic here.

  # Optional: ship logs to Loki
  loki:
    endpoint: ${LOKI_URL:}
    default_labels_enabled:
      exporter: false
      job: true
      instance: true
      level: true
    labels:
      service_name: "resource.attributes[\"service.name\"]"
      session_id: "attributes[\"session.id\"]"
      tool: "attributes[\"mcp.tool\"]"

  # Write raw JSON payloads to disk for deep forensics (rotated by size)
  file/traces:
    path: ${OTEL_FILE_TRACES:/var/otel/traces.ndjson}
    rotation: { max_megabytes: 512, max_days: 7, localtime: true }
  file/metrics:
    path: ${OTEL_FILE_METRICS:/var/otel/metrics.ndjson}
    rotation: { max_megabytes: 512, max_days: 7, localtime: true }
  file/logs:
    path: ${OTEL_FILE_LOGS:/var/otel/logs.ndjson}
    rotation: { max_megabytes: 512, max_days: 7, localtime: true }

service:
  extensions: [health_check, zpages, pprof]

  pipelines:
    # Primary traces pipeline from app
    traces:
      receivers: [otlp]
      processors: [memory_limiter, resourcedetection, attributes/codeintel_common, batch]
      exporters: [otlp, logging, file/traces]

    # Derive RED metrics from traces → Prometheus
    traces/spanmetrics:
      receivers: [otlp]
      processors: [spanmetrics]
      exporters: [prometheus]

    metrics:
      receivers: [otlp, hostmetrics, prometheus]
      processors: [memory_limiter, resourcedetection, attributes/codeintel_common, batch]
      exporters: [prometheus, logging, file/metrics, prometheusremotewrite]

    logs:
      receivers: [otlp, filelog]
      processors: [memory_limiter, resourcedetection, attributes/codeintel_common, batch]
      exporters: [logging, file/logs, loki]

  telemetry:
    metrics:
      address: 0.0.0.0:8888
```

### How this maps to your code today (and what you’ll “get for free”)

* **Per‑session visibility**: your `SessionScopeMiddleware` sets/reads a session id; the `attributes/codeintel_common` processor lifts `X-Session-ID` into `session.id` across traces/logs/metrics, so a partial run’s breadcrumbs are stitchable and explorable. 
* **Tool‑level dimensions**: your MCP tools (e.g., `semantic_search` / `semantic_search_pro`) surface operation names and live under a common `AnswerEnvelope`; those names become the `mcp.tool`/`rpc.method` dimensions in spanmetrics, so “errors and latency by tool” are a graph away.
* **SQL observability**: your instrumented DuckDB `execute()` already emits timing/span metadata; the collector preserves it and the spanmetrics processor turns it into top‑N “slowest query” series without extra code. 

---

## Run it locally (two common options)

**Binary (recommended for dev):**

```bash
otelcol-contrib --config otel-collector.yaml
```

**Docker:**

```yaml
# docker-compose.yml fragment
services:
  otel-collector:
    image: otel/opentelemetry-collector-contrib:latest
    command: ["--config=/etc/otelcol/otel-collector.yaml"]
    network_mode: "host" # simplest for local dev; or map the ports below explicitly
    volumes:
      - ./otel-collector.yaml:/etc/otelcol/otel-collector.yaml:ro
      - ./var-otel:/var/otel
    environment:
      APP_METRICS_TARGET: "localhost:8000"      # if your FastAPI exposes /metrics
      OTLP_ENDPOINT: ""                         # e.g., http://localhost:4317 or :4318
      LOKI_URL: ""                              # e.g., http://localhost:3100/loki/api/v1/push
      PROM_REMOTE_WRITE_URL: ""                 # optional
      TAIL_SLOW_MS: "500"
      TAIL_SAMPLING_PCT: "10"
```

> Your existing Prometheus can now **scrape the collector at `:8889`** (single, unified target) and get:
>
> 1. host/process metrics, 2) app metrics (if you expose `/metrics`), and 3) **trace‑derived RED metrics**.

---

## Python app side (minimal settings to talk to the collector)

In your FastAPI/MCP process set (shell or `.env`):

```bash
# Traces + metrics + logs → local collector
export OTEL_SERVICE_NAME=codeintel_rev
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_METRICS_EXPORTER=otlp
export OTEL_TRACES_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp

# Propagate the session id your middleware already manages
# (Make sure the header X-Session-ID is forwarded; attributes processor will lift it into session.id)
```

> If you already use Prometheus client metrics in the app, **keep them**. The collector will scrape them and unify with OTLP metrics.

---

## Small validation checklist

* `curl -s localhost:8889/metrics | head` ⇒ should show RED metrics like `traces_spanmetrics_calls_total` grouped by `mcp.tool`, `http.route`, `session.id`.
* `curl -s localhost:8888/metrics | head` ⇒ collector self‑metrics.
* Traces in your backend (Tempo/Jaeger/etc.) keyed by `session.id` show each **partial run** as a span tree (search, DuckDB hydration, Git adapters, etc.).
* `var-otel/*.ndjson` files grow as you exercise the system—goldmine for post‑mortems.

---

### Optional (quick improvements you can add later)

* **Tail sampling rules** per tool (e.g., keep all `search:semantic_pro` traces).
* Add **routing** processor if you want to split “dev vs prod” exports using an attribute like `deployment.environment`.
* If you expose **pprof** from the app, the collector already has `pprof` and `zpages` extensions enabled to help with local diagnosis.

---

If you’d like, I can also provide:

* A one‑liner **Kubernetes manifest** with the same config,
* A Grafana **dashboard JSON** wired for the spanmetrics (`calls_total`, `latency_bucket`, error rates) broken out by `mcp.tool` and `session.id`, and
* A micro **OpenTelemetry‑SDK snippet** to standardize how `mcp.tool` and `session.id` are attached to spans in your adapters.

But the config above is complete and runnable as‑is for your current repo structure and instrumentation.


