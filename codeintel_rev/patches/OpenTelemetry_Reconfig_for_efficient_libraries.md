# OpenTelemetry transition part 1 #

Below is a **repo‑specific, ready‑to‑apply implementation plan with concrete diffs** to take your OpenTelemetry integration to the next phase. It focuses on: (1) **one bootstrapping path** for traces/metrics, (2) **domain spans** across vLLM → retrieval → fusion → hydration → envelope, (3) **trace‑anchored run reports**, and (4) **Prometheus via the OTel Prometheus reader** (drop bespoke marshaling). The plan maps to your current file layout and hot paths in `codeintel_rev` (e.g., `app/main.py`, `observability/otel.py`, `telemetry/prom.py`, `io/vllm_client.py`, `io/hybrid_search.py`, `io/duckdb_catalog.py`, `retrieval/gating.py`, `mcp_server/adapters/*`).

> **Why these changes?**
>
> * Prometheus via OTel: same scrape format with less custom code and full OTel semantics; transport is config‑only (swap to OTLP metrics later without code). 
> * Distro/CLI & env knobs: exporter, protocol (gRPC vs HTTP), propagators, resource attributes—without in‑code wiring. You can still add your custom span processors (e.g., “flight recorder”). 
> * Domain spans + semantic attributes: gives a **narratable** trace—discrete operations, not just performance numbers—so agents can validate *what happened* at each step.
> * These diffs align with where those modules live in your tree (e.g., `telemetry/prom.py` is FastAPI‑exposed; `io/*` contains vLLM, FAISS, DuckDB; adapters under `mcp_server/adapters/*.py`). 

---

## 0) Dependencies (add once)

Create a small, additive requirements file to avoid disturbing your base env:

**`requirements-otel-phase2.txt` (new)**

```
opentelemetry-sdk>=1.26.0
opentelemetry-exporter-otlp-proto-http>=1.26.0
opentelemetry-instrumentation-fastapi>=0.47b0
opentelemetry-instrumentation-httpx>=0.47b0
opentelemetry-exporter-prometheus>=0.49b0
# (Optional resource detectors if you want infra context)
opentelemetry-resourcedetector-process>=0.3.0
opentelemetry-resourcedetector-docker>=0.3.0
```

> Exporter/CLI/env behavior and Prometheus reader semantics are covered in the OTel Python technical guide you attached. 

---

## 1) New: project‑wide semantic attributes (kept in one place)

Add a tiny shim so all spans/metrics use consistent keys; include domain‑specific attributes (FAISS, vLLM, RRF, DuckDB, MCP session):

**`codeintel_rev/observability/semantic_conventions.py` (new)**

```diff
*** /dev/null
--- a/codeintel_rev/observability/semantic_conventions.py
+++ b/codeintel_rev/observability/semantic_conventions.py
@@ -0,0 +1,120 @@
+from __future__ import annotations
+
+class Attrs:
+    # Request/session/run
+    MCP_TOOL        = "mcp.tool"            # e.g., search:semantic
+    MCP_SESSION_ID  = "mcp.session_id"
+    MCP_RUN_ID      = "mcp.run_id"
+    REQUEST_STAGE   = "request.stage"       # gather | pool | fuse | hydrate | rerank
+
+    # Query + gating
+    QUERY_TEXT      = "retrieval.query_text"
+    QUERY_LEN       = "retrieval.query_len"
+    TOP_K           = "retrieval.top_k"
+    RRF_K           = "retrieval.rrf_k"
+    CHANNEL_DEPTHS  = "retrieval.channel_depths"   # dict -> str
+    CHANNELS_USED   = "retrieval.channels_used"    # list -> str
+    FUSED_DOCS      = "retrieval.fused_docs"
+    RECENCY_BOOSTED = "retrieval.recency_boosted"  # bool
+
+    # FAISS
+    FAISS_INDEX_KIND = "faiss.index_kind"   # Flat | IVFFlat | IVF-PQ | Flat+sec
+    FAISS_METRIC     = "faiss.metric"       # L2 | IP | cosine
+    FAISS_DIM        = "faiss.dim"
+    FAISS_TOPK       = "faiss.k"
+    FAISS_NPROBE     = "faiss.nprobe"
+    FAISS_GPU        = "faiss.gpu"
+
+    # vLLM
+    VLLM_MODE       = "vllm.mode"           # http | inproc
+    VLLM_MODEL_NAME = "vllm.model_name"
+    VLLM_EMBED_DIM  = "vllm.embed_dim"
+    VLLM_BATCH      = "vllm.batch_size"
+
+    # DuckDB hydration
+    DUCKDB_ROWS      = "duckdb.rows"
+    DUCKDB_SQL_BYTES = "duckdb.sql_bytes"
+
+    # Git
+    GIT_OP         = "git.op"               # blame | history
+    GIT_PATH       = "git.path"
+    GIT_LINE_RANGE = "git.line_range"
+
+    # Errors/warnings
+    WARNINGS       = "codeintel.warnings"
+
+def to_label_str(obj: object) -> str:
+    import json
+    try:
+        return json.dumps(obj, sort_keys=True, ensure_ascii=False)
+    except Exception:
+        return str(obj)
```

---

## 2) One OTel bootstrap (traces + metrics) and FastAPI instrumentation

We extend your existing `observability/otel.py` (present in repo) to (a) initialize providers once, (b) add an OTLP exporter if present, and (c) wire the **PrometheusMetricReader** for scrape‑format metrics. 

**`codeintel_rev/observability/otel.py` (extend in place)**

```diff
--- a/codeintel_rev/observability/otel.py
+++ b/codeintel_rev/observability/otel.py
@@
-from __future__ import annotations
+from __future__ import annotations
+import os
+from typing import Iterable
+
+from opentelemetry import trace, metrics
+from opentelemetry.sdk.resources import Resource
+from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
+from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
+from opentelemetry.sdk.metrics import MeterProvider
+from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
+from opentelemetry.exporter.prometheus import PrometheusMetricReader
+try:
+    from prometheus_client import start_http_server as _prom_start_http_server
+except Exception:
+    _prom_start_http_server = None
+try:
+    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
+    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
+except Exception:
+    OTLPSpanExporter = None
+    OTLPMetricExporter = None
+
+_INIT_DONE = False
+
+def init_otel(
+    service_name: str = "codeintel-mcp",
+    exporters: Iterable[str] = ("console", "otlp", "prom"),
+    otlp_endpoint: str | None = None,
+) -> None:
+    """Idempotent OTel init for traces + metrics."""
+    global _INIT_DONE
+    if _INIT_DONE:
+        return
+    resource = Resource.create({
+        "service.name": service_name,
+        "service.namespace": "kgfoundry",
+    })
+
+    # --- Traces
+    tp = SDKTracerProvider(resource=resource)
+    if "console" in exporters:
+        tp.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
+    if "otlp" in exporters and OTLPSpanExporter:
+        ep = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
+        tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{ep}/v1/traces")))
+    trace.set_tracer_provider(tp)
+
+    # --- Metrics (OTLP push and/or Prometheus scrape)
+    readers = []
+    if "otlp" in exporters and OTLPMetricExporter:
+        ep = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
+        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=f"{ep}/v1/metrics")))
+    if "prom" in exporters:
+        readers.append(PrometheusMetricReader(prefix="codeintel"))
+        # optional web server if you don’t have one already
+        port = int(os.getenv("PROMETHEUS_PORT", "9464"))
+        if _prom_start_http_server:
+            _prom_start_http_server(port=port, addr=os.getenv("PROMETHEUS_HOST", "0.0.0.0"))
+    if readers:
+        mp = MeterProvider(resource=resource, metric_readers=readers)
+        metrics.set_meter_provider(mp)
+
+    _INIT_DONE = True
+
+def record_span_event(name: str, **attrs: object) -> None:
+    """Lightweight helper used across retrieval code to add events."""
+    span = trace.get_current_span()
+    if span and getattr(span, "is_recording", lambda: False)():
+        span.add_event(name, attrs)
```

> Using the OTel Prometheus reader lets you drop your hand‑rolled `/metrics` byte‑response while preserving Prometheus scrape format (see attached guide). 

---

## 3) FastAPI boot: instrument app + propagate session/run → spans

`app/main.py` exists and is a natural hook to init once and stamp request metadata on the root span. 

**`codeintel_rev/app/main.py`**

```diff
--- a/codeintel_rev/app/main.py
+++ b/codeintel_rev/app/main.py
@@
 from fastapi import FastAPI
 from .middleware import set_mcp_context, disable_nginx_buffering
+from starlette.middleware.base import BaseHTTPMiddleware
+from starlette.requests import Request
+from starlette.responses import Response
+from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
+from opentelemetry import trace
+from codeintel_rev.observability.otel import init_otel
+from codeintel_rev.observability.semantic_conventions import Attrs
 
 def build_http_app(capabilities: Capabilities) -> FastAPI:
-    app = FastAPI()
+    # Initialize tracing/metrics once.
+    init_otel(service_name="codeintel-mcp")
+    app = FastAPI()
     app.add_middleware(set_mcp_context)
     app.add_middleware(disable_nginx_buffering)
+    FastAPIInstrumentor.instrument_app(app)
+
+    class _TraceHeadersMiddleware(BaseHTTPMiddleware):
+        async def dispatch(self, request: Request, call_next):
+            session_id = request.headers.get("X-Session-ID")
+            run_id = request.headers.get("X-Run-ID")
+            span = trace.get_current_span()
+            if span and span.is_recording():
+                if session_id:
+                    span.set_attribute(Attrs.MCP_SESSION_ID, session_id)
+                if run_id:
+                    span.set_attribute(Attrs.MCP_RUN_ID, run_id)
+            response: Response = await call_next(request)
+            # Return trace id for client correlation
+            ctx = trace.get_current_span().get_span_context()
+            if ctx and ctx.trace_id:
+                response.headers["X-Trace-Id"] = format(ctx.trace_id, "032x")
+            return response
+
+    app.add_middleware(_TraceHeadersMiddleware)
     # … existing router/route registration …
     return app
```

---

## 4) vLLM client: wrap `embed_batch` with a CLIENT span

`io/vllm_client.py` is where your embedding happens—ideal to record model, mode, batch size, and capture failures. 

**`codeintel_rev/io/vllm_client.py`**

```diff
--- a/codeintel_rev/io/vllm_client.py
+++ b/codeintel_rev/io/vllm_client.py
@@
 from typing import Sequence
+from opentelemetry import trace
+from opentelemetry.trace import SpanKind, Status, StatusCode
+from codeintel_rev.observability.semantic_conventions import Attrs
 
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
+            except Exception as e:
+                if span.is_recording():
+                    span.record_exception(e)
+                    span.set_status(Status(StatusCode.ERROR, str(e)))
+                raise
```

---

## 5) Hybrid retrieval: domain spans + stage events

Your retrieval is centered in `io/hybrid_search.py` (plus `retrieval/hybrid.py` / `retrieval/mcp_search.py` depending on call path). We add INTERNAL spans for `gather_channels`, `fuse` (RRF), and `hydrate` (DuckDB), plus **events** for budget decisions and warnings. 

**`codeintel_rev/io/hybrid_search.py` (illustrative additions)**

```diff
--- a/codeintel_rev/io/hybrid_search.py
+++ b/codeintel_rev/io/hybrid_search.py
@@
+from opentelemetry import trace
+from opentelemetry.trace import SpanKind, Status, StatusCode
+from codeintel_rev.observability.semantic_conventions import Attrs, to_label_str
+from codeintel_rev.observability.otel import record_span_event
@@
     def search(self, query: str, top_k: int = 20, *, channels: Sequence[str] | None = None) -> SearchResults:
-        # existing logic...
+        tracer = trace.get_tracer(__name__)
+        with tracer.start_as_current_span("retrieval.search", kind=SpanKind.INTERNAL) as root:
+            if root.is_recording():
+                root.set_attribute(Attrs.QUERY_TEXT, query)
+                root.set_attribute(Attrs.QUERY_LEN, len(query))
+                root.set_attribute(Attrs.TOP_K, int(top_k))
+                if channels:
+                    root.set_attribute(Attrs.CHANNELS_USED, to_label_str(list(channels)))
+            try:
+                # 1) Gather
+                with tracer.start_as_current_span("retrieval.gather_channels") as sp:
+                    sp.set_attribute(Attrs.REQUEST_STAGE, "gather")
+                    dense, sparse, splade = self._gather_channels(query, top_k, channels)
+                    record_span_event("channels.gathered", dense=len(dense), sparse=len(sparse), splade=len(splade))
+                # 2) Fuse
+                with tracer.start_as_current_span("retrieval.fuse") as sp:
+                    sp.set_attribute(Attrs.REQUEST_STAGE, "fuse")
+                    fused = self._fuse(dense, sparse, splade, top_k=top_k)
+                    sp.set_attribute(Attrs.FUSED_DOCS, int(len(fused)))
+                # 3) Hydrate
+                with tracer.start_as_current_span("retrieval.hydrate") as sp:
+                    sp.set_attribute(Attrs.REQUEST_STAGE, "hydrate")
+                    hydrated = self._hydrate(fused)
+                return hydrated
+            except Exception as e:
+                if root.is_recording():
+                    root.record_exception(e); root.set_status(Status(StatusCode.ERROR, str(e)))
+                raise
```

> The exact helper names may vary; the idea is to put a **span per stage** and keep your existing timeline events—agents get a precise, ordered narrative of *what* ran. (File presence for `io/hybrid_search.py` is in your repo map.) 

---

## 6) Budget/heuristics: attach to spans

Add a tiny helper in `retrieval/gating.py` to stamp the current span with the decision vector (k‑per‑channel, weights, RRF k, etc.). The file is present in your tree. 

**`codeintel_rev/retrieval/gating.py` (add helper + call from your decision point)**

```diff
--- a/codeintel_rev/retrieval/gating.py
+++ b/codeintel_rev/retrieval/gating.py
@@
+from opentelemetry import trace
+from codeintel_rev.observability.semantic_conventions import Attrs, to_label_str
@@
 def decide_budgets(...):
     # existing logic computing budgets -> cfg
+    span = trace.get_current_span()
+    if span and span.is_recording():
+        span.set_attribute(Attrs.RRF_K, int(cfg.rrf_k))
+        span.set_attribute(Attrs.CHANNEL_DEPTHS, to_label_str(cfg.channel_depths))
+        if getattr(cfg, "warnings", None):
+            span.set_attribute(Attrs.WARNINGS, to_label_str(cfg.warnings))
     return cfg
```

---

## 7) DuckDB hydration: rows + SQL size

Hydration is a great seam for INTERNAL spans; `io/duckdb_catalog.py` (or `io/duckdb_manager.py`) is in the repo and backs your hydrator. 

**`codeintel_rev/io/duckdb_catalog.py`**

```diff
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@
+from opentelemetry import trace
+from opentelemetry.trace import SpanKind
+from codeintel_rev.observability.semantic_conventions import Attrs
@@
     def hydrate(self, doc_ids: list[str]) -> list[HydratedDoc]:
-        # existing query composition & execution...
+        tracer = trace.get_tracer(__name__)
+        with tracer.start_as_current_span("duckdb.hydrate", kind=SpanKind.INTERNAL) as sp:
+            if sp.is_recording():
+                sp.set_attribute(Attrs.DUCKDB_SQL_BYTES, int(len(self._last_sql or "")))
+            rows = self._execute_hydration(doc_ids)
+            if sp.is_recording():
+                sp.set_attribute(Attrs.DUCKDB_ROWS, int(len(rows)))
+            return rows
```

---

## 8) MCP adapters: root SERVER spans per tool call

Your FastAPI MCP adapters live under `mcp_server/adapters/*.py` (e.g., `semantic.py`, `semantic_pro.py`, `files.py`, `text_search.py`, `deep_research.py`). They should open a **SERVER** span per tool, stamp `mcp.tool`, `mcp.session_id`, and forward to the engine. 

**`codeintel_rev/mcp_server/adapters/semantic.py` (pattern; replicate to other adapters)**

```diff
--- a/codeintel_rev/mcp_server/adapters/semantic.py
+++ b/codeintel_rev/mcp_server/adapters/semantic.py
@@
+from opentelemetry import trace
+from opentelemetry.trace import SpanKind, Status, StatusCode
+from codeintel_rev.observability.semantic_conventions import Attrs
@@
 async def semantic_search(req: SemanticSearchRequest, ctx: RequestCtx) -> AnswerEnvelope:
-    # existing logic...
+    tracer = trace.get_tracer(__name__)
+    with tracer.start_as_current_span("mcp.semantic_search", kind=SpanKind.SERVER) as span:
+        if span.is_recording():
+            span.set_attribute(Attrs.MCP_TOOL, "search:semantic")
+            sid = ctx.session_id if hasattr(ctx, "session_id") else None
+            if sid:
+                span.set_attribute(Attrs.MCP_SESSION_ID, sid)
+        try:
+            out = await _do_semantic_search(req, ctx)
+            return out
+        except Exception as e:
+            if span.is_recording():
+                span.record_exception(e); span.set_status(Status(StatusCode.ERROR, str(e)))
+            raise
```

> The same pattern applies to `mcp_server/adapters/semantic_pro.py`, `text_search.py`, `deep_research.py`, etc. 

---

## 9) Prometheus: replace bespoke `/metrics` with the OTel reader

Your tree contains `telemetry/prom.py`, which currently advertises a FastAPI `/metrics` route using `prometheus_client.generate_latest`/`CONTENT_TYPE_LATEST`. Replace that surface with the **OTel PrometheusMetricReader** installed in `observability/otel.init_otel()` above, and keep the route only as a compatibility stub. (The scip index shows that module and the prometheus_client integration.) 

**`codeintel_rev/telemetry/prom.py`**

```diff
--- a/codeintel_rev/telemetry/prom.py
+++ b/codeintel_rev/telemetry/prom.py
@@
-from prometheus_client import CONTENT_TYPE_LATEST, generate_latest, REGISTRY
-from fastapi import APIRouter, Response
-router = APIRouter()
-
-@router.get("/metrics")
-def metrics() -> Response:
-    # Legacy scrape endpoint
-    data = generate_latest(REGISTRY)
-    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
+from fastapi import APIRouter, Response
+router = APIRouter()
+
+@router.get("/metrics")
+def metrics() -> Response:
+    """
+    Compatibility shim: metrics are now exposed by the OpenTelemetry
+    PrometheusMetricReader on its own HTTP server. This endpoint exists
+    only to guide operators.
+    """
+    return Response(
+        content=b"# Metrics moved to OpenTelemetry Prometheus reader. "
+                b"Scrape the reader port (default :9464).",
+        media_type="text/plain",
+        status_code=410,
+    )
```

> The OTel reader exposes Prom scrape format (text) and auto‑labels with the OTel **Resource**; you keep the same metric names you record via the OTel Meter API. You can switch to **OTLP metrics** later by config only. 

---

## 10) Run Report v2: trace‑anchored, “where it stopped and why”

You already have `telemetry/reporter.py` and a timeline concept. We augment the report to embed the active **trace id** and summarize observed stage spans/events so partial runs show exactly where they stopped. (The modules exist under `telemetry/` and `observability/`.) 

**`codeintel_rev/telemetry/reporter.py` (add new helper; keep old APIs intact)**

```diff
--- a/codeintel_rev/telemetry/reporter.py
+++ b/codeintel_rev/telemetry/reporter.py
@@
+from __future__ import annotations
+from dataclasses import dataclass
+from typing import Any, Dict, List, Optional
+from opentelemetry import trace
+from codeintel_rev.observability.semantic_conventions import Attrs
+from codeintel_rev.observability.otel import record_span_event
+from .timeline import current_timeline  # existing helper
+
+@dataclass
+class RunReportV2:
+    trace_id: str
+    session_id: Optional[str]
+    run_id: Optional[str]
+    stages: List[Dict[str, Any]]
+    warnings: List[str]
+    stopped_after_stage: Optional[str]
+
+def build_run_report_v2() -> RunReportV2:
+    span = trace.get_current_span()
+    ctx = span.get_span_context() if span else None
+    trace_hex = format(ctx.trace_id, "032x") if (ctx and ctx.trace_id) else ""
+    sess = getattr(span, "attributes", {}).get(Attrs.MCP_SESSION_ID) if span else None
+    run  = getattr(span, "attributes", {}).get(Attrs.MCP_RUN_ID) if span else None
+
+    tl = current_timeline()
+    # Infer stage order from known event names you already emit
+    observed = [ev for ev in tl.events if ev.name.startswith("retrieval.")]
+    stages = [{"name": ev.name, "t": ev.ts, "attrs": ev.attrs} for ev in observed]
+    stopped = None
+    expected = ["retrieval.gather_channels", "retrieval.fuse", "retrieval.hydrate"]
+    for s in expected:
+        if s not in [st["name"] for st in stages]:
+            stopped = s  # first missing stage is where we stopped before
+            break
+    warns = []
+    for ev in tl.events:
+        if ev.name == "warning":
+            warns.append(str(ev.attrs.get("message", "")))
+    return RunReportV2(
+        trace_id=trace_hex, session_id=sess, run_id=run,
+        stages=stages, warnings=warns, stopped_after_stage=stopped
+    )
```

> The above uses your in‑process timeline (and does not require reading from a backend). It makes partial runs diagnosable: **which stage executed last** and **what warnings** were attached. 

---

## 11) (Optional) Standardize metric production via OTel Meters

You can straightaway start using `opentelemetry.metrics.get_meter(__name__)` and define histograms/counters where you currently use the bespoke registry. The Prometheus **reader** will surface them for scrape; later you can flip to OTLP metrics via env only. All of this is supported by the guide you attached. 

---

## 12) Rollout, config, and runbook (short)

1. **Install** `requirements-otel-phase2.txt`.
2. **Config** (env only; no code rebuild needed):

   * `OTEL_SERVICE_NAME=codeintel_rev`
   * `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318`
   * `PROMETHEUS_PORT=9464` (if you want the reader’s embedded server)
3. **Start your service normally** (you can also run under `opentelemetry-instrument ...` if you prefer CLI‑driven bootstrap; your new `init_otel()` remains compatible either way). CLI/env behavior is documented in your OTel guide. 
4. **Dashboard smoke‑tests**: confirm a single trace per MCP call and three stage spans (`gather_channels`, `fuse`, `hydrate`), plus vLLM CLIENT spans.

---

## Why this matches your codebase (evidence)

* The files we patch or read from exist in your tree: `app/main.py`, `observability/otel.py`, `telemetry/prom.py`, `telemetry/reporter.py`, `io/vllm_client.py`, `io/hybrid_search.py`, `io/duckdb_catalog.py`, `retrieval/gating.py`, `mcp_server/adapters/*.py`.
* The scip index shows `telemetry/prom.py` and the **prometheus_client** pattern you can retire in favor of the OTel Prometheus reader.
* The OTel exporter and distro details (endpoints, protocols, env toggles) are covered in your attached **OpenTelemetry Python Libraries Technical Guide**. 

---

## What you get after applying these diffs

* **Narratable traces**: every MCP tool call is a SERVER span with child INTERNAL/CLIENT spans for vLLM → gather → fuse (RRF) → hydrate (DuckDB), + timeline events.
* **Partial‑run clarity**: “Run Report v2” states *where* execution stopped and *why* (warnings/exceptions attached as span events).
* **One metrics surface**: Prometheus scrape via the OTel reader—no more manual `/metrics` plumbing—and future‑proof to OTLP by config only.
* **Minimal coupling**: you can still add your “flight recorder” span processor or switch transports with env, not code. 

If you’d like, I can also produce **follow‑up diffs** to (a) convert your in‑tree counters/histograms to OTel Meters (including **Views** to cap cardinality), and (b) enable **resource detectors** for process/container attributes—both are zero/low‑touch and make backend correlation even cleaner. 

# Opentelemetry reconfiguration part 2 #

Below is a **consolidated, low‑risk implementation plan** with **concrete diffs** that apply the recommendations we discussed. I’ve grounded the plan in the **current layout of your repo** (file paths verified via the latest `repo_map.json`) and in the **code that already exists for telemetry and adapters**. Where I assert specifics about your present code (e.g., the hand‑rolled Prometheus endpoint), I cite your SCIP index and repo map; where I justify choices about OTel packages/behavior, I cite the attached OpenTelemetry guide you provided.

---

## What this plan delivers (at a glance)

1. **Metrics consolidation to OTel**: move metric production to the OpenTelemetry Metrics API; keep your `/metrics` route but have it surface OTel metrics via the Prometheus reader (no more hand‑marshalling). Your code today exposes Prometheus by calling `prometheus_client.exposition.generate_latest` (and `CONTENT_TYPE_LATEST`) directly; we’ll replace the *production* of metrics, not the scrape path, to avoid dashboard churn.    

2. **Provider bootstrap simplified**: support running the service under `opentelemetry-instrument` (opentelemetry‑distro) while preserving your in‑process bootstrap for CLIs/tests. The distro config (exporters, propagators) remains env‑only; you can still add your flight‑recorder span processor after init.   

3. **Resource detectors**: add container/process/k8s resource detectors so spans/logs/metrics carry infra identity out‑of‑the‑box. The guide explains the practical trade‑offs and modern detector packages. 

4. **Semantic conventions**: migrate your internal shim gradually toward official `opentelemetry.semconv` keys so downstream tools can recognize attributes without translation.

5. **Views & buckets**: define views to cap cardinality and set sensible histogram buckets. Works the same whether you scrape with Prometheus or export via OTLP.

6. **Logging correlation**: enable logging auto‑instrumentation so `trace_id` / `span_id` flow into Python `logging` without code changes; keep your current OTLP logging pipeline. 

7. **Cross‑component correlation**: use **Baggage** for stable run/session IDs and **Span Links** for fan‑out stages. This complements the span context decorators you already have (`telemetry.decorators`).  

All changes below are incremental and map cleanly to the present structure (selected paths shown): `observability/otel.py`, `observability/metrics.py`, `telemetry/prom.py`, `telemetry/decorators.py`, `app/main.py`, plus a couple of high‑value call sites (`retrieval/gating.py`, `io/vllm_client.py`, `io/faiss_manager.py`). Paths confirmed in the repo map.  

---

## Step‑by‑step implementation plan

### A) Consolidate metrics onto the OTel Metrics API (keep `/metrics`)

**Why this order:** your code currently exports Prometheus by hand; moving metric *production* to OTel first lets Prom dashboards keep working while eliminating custom registries/counters in your code. The OTel Prometheus exporter registers a **PrometheusMetricReader** that makes the same scrape format available to your **existing** `/metrics` route via `generate_latest()`—but now the values come from the OTel SDK.  

**What changes:**

* Create an OTel `MeterProvider` with a `PrometheusMetricReader`. (The guide covers using the reader + HTTP server and the relevant env vars if you prefer zero-code startup.) 
* Replace direct `prometheus_client` counters/histograms in `telemetry/prom.py` with OTel instruments.
* Keep your `/metrics` FastAPI route: it will continue returning `generate_latest()`—which now reflects the OTel reader’s aggregates (so it’s transparent to Prometheus). 

### B) Distro/CLI for services; keep in‑proc bootstrap for CLIs/tests

* Run the FastAPI service under `opentelemetry-instrument` so exporters/propagators are driven by env only (e.g., `OTEL_TRACES_EXPORTER=otlp`, `OTEL_METRICS_EXPORTER=prometheus`).
* In `app/main.py`, if instrumentation already happened (global provider set), **add** your flight‑recorder span processor. If not, fall back to your existing `init_telemetry()` for local scripts. The OTel distro/CLI details and toggles are in the guide.  

### C) Resource detectors

* Add process/container/k8s detectors and merge the `Resource` on startup. The guide notes modern container detectors and trade‑offs. 

### D) SemConv clean‑up

* Introduce a thin adapter in `observability/semantic_conventions.py` that re‑exports official `opentelemetry.semconv` keys; gradually migrate your call sites away from the local `Attrs` names.

### E) Metrics Views

* Register `View`s to drop volatile attributes (e.g., raw file paths) and to select histogram buckets for your hot instruments (latency, FAISS results, vLLM batch time).

### F) Logging auto‑instrumentation

* Turn on `OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true` and keep your OTLP logs exporter unchanged. The guide covers how the logging instrumentor hooks standard logging. 

### G) Correlation glue

* Add Baggage keys such as `run.id` and `session.id` where you first accept a request, and *link* spans for parallel fan‑out stages; your decorators already provide a consistent span wrapper.  

---

## Concrete diffs

> *Notes*: (1) Diffs are unified; insertions are prefixed with `+`. (2) Some names reflect your tree as indexed (e.g., both `observability/otel.py` and `telemetry/otel.py` exist; we keep `observability/*` as the “SDK setup” layer and use `telemetry/*` for call‑site helpers/decorators). Paths verified in the repo map.  

### 1) Dependencies

**`pyproject.toml`**

```diff
 [tool.poetry.dependencies]
 python = ">=3.11,<3.13"

 # OpenTelemetry core
+opentelemetry-api = "^1.38.0"
+opentelemetry-sdk = "^1.38.0"
+opentelemetry-semantic-conventions = "^0.45b0"

 # Exporters / readers
+opentelemetry-exporter-otlp = "^1.38.0"
+opentelemetry-exporter-prometheus = "^0.45b0"

 # Auto-instrumentation (service bootstrap)
+opentelemetry-distro = "^0.45b0"
+opentelemetry-instrumentation = "^0.45b0"
+opentelemetry-instrumentation-fastapi = "^0.45b0"
+opentelemetry-instrumentation-httpx = "^0.45b0"
+opentelemetry-instrumentation-logging = "^0.45b0"

 # Resource detectors (optional but recommended)
+opentelemetry-resourcedetector-process = "^0.4.0"
+opentelemetry-resource-detector-containerid = "^0.59b0"
+opentelemetry-resourcedetector-kubernetes = "^0.4.0"
```

> If you prefer push instead of scrape, add `opentelemetry-exporter-prometheus-remote-write` but the plan below keeps Prom **scrape** for compatibility. The guide sections on distro, Prom exporter, and OTLP protocols back these choices.   

---

### 2) Metrics provider + Prometheus reader (OTel)

**`observability/metrics.py`** — own the MeterProvider (Prom reader + Views)

```diff
+from __future__ import annotations
+from typing import Iterable
+import os
+
+from opentelemetry import metrics
+from opentelemetry.sdk.metrics import MeterProvider, View
+from opentelemetry.sdk.metrics.export import Aggregation, ExplicitBucketHistogramAggregation
+from opentelemetry.sdk.resources import Resource
+try:
+    from opentelemetry.exporter.prometheus import PrometheusMetricReader
+except Exception:  # optional: keep app running if not installed
+    PrometheusMetricReader = None  # type: ignore[assignment]
+
+_METRICS_INSTALLED = False
+
+def install_metrics_provider(resource: Resource, *, prom_prefix: str | None = "codeintel") -> None:
+    """
+    Configure the global MeterProvider with a Prometheus reader and default Views.
+    Safe no-op if already installed or if exporter package is unavailable.
+    """
+    global _METRICS_INSTALLED
+    if _METRICS_INSTALLED or PrometheusMetricReader is None:
+        return
+
+    # ---- Views (cardinality + buckets)
+    views: list[View] = [
+        # Canonical request latency in ms with SLO-friendly buckets
+        View(
+            instrument_name="request_latency_ms",
+            aggregation=ExplicitBucketHistogramAggregation([1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500]),
+        ),
+        # Drop volatile labels for any instrument that might attach raw paths
+        View(
+            instrument_name="*",
+            # Example: if you decide to drop 'path_raw' wherever it appears
+            attribute_keys=["service.name","route","status","component","stage","model","index_type"],
+        ),
+    ]
+
+    reader = PrometheusMetricReader(prefix=prom_prefix)  # registers with Prom default registry
+    provider = MeterProvider(metric_readers=[reader], resource=resource, views=views)
+    metrics.set_meter_provider(provider)
+    _METRICS_INSTALLED = True
```

(Repo contains `observability/metrics.py`; this keeps setup close to your other observability code.) 

---

### 3) Telemetry bootstrap (distro‑aware) + detectors

**`observability/otel.py`** — small refactor so we can either (a) run under `opentelemetry-instrument` or (b) do in‑proc init for scripts; add detectors and keep your `record_span_event` helper.

```diff
 from __future__ import annotations
-from typing import Iterable
+from typing import Iterable, Sequence
 import os
 
 from opentelemetry import trace
 from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
 from opentelemetry.sdk.trace.export import BatchSpanProcessor
 from opentelemetry.sdk.resources import Resource
+from opentelemetry.sdk._logs import LoggerProvider
+from opentelemetry._logs import set_logger_provider
+from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
+from opentelemetry.semconv.resource import ResourceAttributes
 
 try:
     from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
-    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
+    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
 except Exception:
     OTLPSpanExporter = None
-    OTLPMetricExporter = None
+    OTLPLogExporter = None
 
 _INIT_DONE = False
 
-def init_telemetry(service_name: str, service_version: str | None = None, *, otlp_endpoint: str | None = None) -> None:
+def init_telemetry(
+    service_name: str,
+    service_version: str | None = None,
+    *,
+    otlp_endpoint: str | None = None,
+    add_flight_recorder: bool = True,
+) -> None:
     """
-    Best-effort in-process bootstrap for traces+metrics+logs.
+    Best-effort in-process bootstrap for traces+logs.
     Idempotent; safe to call when running under opentelemetry-instrument.
     """
     global _INIT_DONE
     if _INIT_DONE:
         return
 
-    resource = Resource.create({"service.name": service_name, "service.version": service_version or "0"})
+    # Merge basic service identity (env can add more via detectors)
+    resource = Resource.create({
+        ResourceAttributes.SERVICE_NAME: service_name,
+        ResourceAttributes.SERVICE_VERSION: service_version or "0",
+        "service.namespace": "kgfoundry",
+    })
 
-    # Traces
-    tp = SDKTracerProvider(resource=resource)
+    # If a provider is already present (distro), only extend it (e.g., add processors)
+    existing = trace.get_tracer_provider()
+    tp = existing if isinstance(existing, SDKTracerProvider) else SDKTracerProvider(resource=resource)
     if OTLPSpanExporter:
         ep = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
         tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{ep}/v1/traces")))
-    trace.set_tracer_provider(tp)
+    if add_flight_recorder:
+        try:
+            from .flight_recorder import FlightRecorderSpanProcessor  # keep your local option
+            tp.add_span_processor(FlightRecorderSpanProcessor())
+        except Exception:
+            pass
+    if not isinstance(existing, SDKTracerProvider):
+        trace.set_tracer_provider(tp)
 
-    # Logs (optional)
-    try:
-        from opentelemetry.sdk._logs import LoggerProvider
-        from opentelemetry._logs import set_logger_provider
-        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
-        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
-        lp = LoggerProvider(resource=resource)
-        if OTLPLogExporter:
-            ep = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
-            lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{ep}/v1/logs")))
-        set_logger_provider(lp)
-    except Exception:
-        pass
+    # Logs (keep your pipeline, benefit from logging auto-instrumentation env switch)
+    lp = LoggerProvider(resource=resource)
+    if OTLPLogExporter:
+        ep = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
+        lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{ep}/v1/logs")))
+    set_logger_provider(lp)
 
     _INIT_DONE = True
 
 def record_span_event(name: str, **attrs: object) -> None:
     span = trace.get_current_span()
     if span and getattr(span, "is_recording", lambda: False)():
         span.add_event(name, attrs)
```

This preserves your existing helper and adds a clean hook for your **flight recorder** while cooperating with `opentelemetry-instrument`. (Your repo already imports `observability.otel.record_span_event` from several call sites.) 

> **Where to install metrics provider**: call `observability.metrics.install_metrics_provider(resource)` during app startup (next diff) so `/metrics` begins exposing OTel metrics immediately. The Prom reader/HTTP behavior is as described in the guide. 

---

### 4) Keep `/metrics`, but make it surface OTel‑backed data; migrate counters to OTel instruments

**`telemetry/prom.py`** — replace direct prometheus counters/hists with OTel instruments; keep your router that calls `generate_latest()` (it will now reflect OTel values via the reader).

```diff
-from prometheus_client.exposition import CONTENT_TYPE_LATEST, generate_latest
-from prometheus_client.registry import CollectorRegistry
+from prometheus_client.exposition import CONTENT_TYPE_LATEST, generate_latest
 from fastapi import APIRouter, Response
+from opentelemetry import metrics
 
-# Existing: direct prometheus-client metrics (GATING_DECISIONS_TOTAL, RRFK, QUERY_AMBIGUITY, ...)
-# We will re-express them as OTel instruments so the Prometheus reader can expose them.
+_METER = metrics.get_meter("codeintel_rev.telemetry")
+_RUNS = _METER.create_counter(
+    name="mcp_runs_total",
+    description="Count of MCP tool runs by tool and status",
+)
+_gating_rrfk = _METER.create_histogram(
+    name="retrieval_rrf_k",
+    description="RRF k chosen by the gating step",
+    unit="1",
+)
+_gating_ambiguity = _METER.create_histogram(
+    name="retrieval_query_ambiguity",
+    description="Heuristic query ambiguity",
+    unit="1",
+)
 
-def build_metrics_router(config: MetricsConfig | None = None) -> APIRouter | None:
+def build_metrics_router(config: MetricsConfig | None = None) -> APIRouter | None:
     """
-    Return a router exposing /metrics using prometheus_client.generate_latest
-    over the configured registry.
+    Return a router exposing /metrics using prometheus_client.generate_latest.
+    NOTE: With PrometheusMetricReader installed, generate_latest() will pull
+    OTel aggregates instead of app-owned registries.
     """
     try:
         router = APIRouter()
 
         @router.get("/metrics")
         def metrics_endpoint() -> Response:
-            payload: bytes = generate_latest(config.registry if config and config.registry else CollectorRegistry())
+            # PrometheusMetricReader registers with the default registry; if installed,
+            # generate_latest() will aggregate OTel metrics on-demand.
+            payload: bytes = generate_latest()
             return Response(content=payload, media_type=CONTENT_TYPE_LATEST)
         return router
     except Exception:
         return None
 
-# keep existing helpers for compatibility, but re-implement using OTel instruments
-def record_run(tool: str, status: str) -> None:
-    RUNS_TOTAL.labels(tool=tool, status=status).inc()
+def record_run(tool: str, status: str) -> None:
+    _RUNS.add(1, {"tool": tool, "status": status})
 
-def record_gating(rrf_k: int, ambiguity: float, *, literal: bool | None = None, vague: bool | None = None, rm3: bool | None = None) -> None:
-    RRFK.observe(rrf_k)
-    QUERY_AMBIGUITY.observe(ambiguity)
+def record_gating(rrf_k: int, ambiguity: float, *, literal: bool | None = None, vague: bool | None = None, rm3: bool | None = None) -> None:
+    _gating_rrfk.record(float(rrf_k))
+    _gating_ambiguity.record(float(ambiguity))
```

Your SCIP index shows the current module uses `generate_latest` and `CONTENT_TYPE_LATEST`, and defines the gating metrics there today—this diff replaces only the **production** side.   

---

### 5) Service boot: call OTel init + install metrics provider + propagate run/session IDs

**`app/main.py`** — early in `build_http_app` / startup

```diff
 from fastapi import FastAPI
 from .server_settings import ServerSettings
 from .config_context import ApplicationContext
+from opentelemetry.sdk.resources import Resource
+from codeintel_rev.observability.otel import init_telemetry
+from codeintel_rev.observability.metrics import install_metrics_provider
+from codeintel_rev.observability.timeline import Timeline
+from opentelemetry import baggage
 
 def build_http_app(settings: ServerSettings) -> FastAPI:
     app = FastAPI(...)
-    # existing: instrumentation helpers / custom bootstrap
-    # ...
+    # Initialize OpenTelemetry if not already done by opentelemetry-instrument
+    init_telemetry(service_name="codeintel_rev", service_version=settings.version)
+
+    # Ensure MeterProvider with Prometheus reader is installed
+    resource = Resource.create({"service.name": "codeintel_rev", "service.namespace": "kgfoundry"})
+    install_metrics_provider(resource)
+
+    # Middleware to propagate a stable run/session id using Baggage
+    @app.middleware("http")
+    async def _baggage_mw(request, call_next):
+        run_id = request.headers.get("X-Run-Id")
+        session_id = request.headers.get("X-Session-Id")
+        ctx = baggage.set_baggage("run.id", run_id) if run_id else baggage.get_current()
+        if session_id:
+            ctx = baggage.set_baggage("session.id", session_id, context=ctx)
+        response = await call_next(request)
+        return response
```

(Your FastAPI app is present; this adds conservative bootstrap + correlation middleware.) 

---

### 6) Gate & retrieval: attach attrs, record metrics via new helpers

**`retrieval/gating.py`** — attach attributes + use `telemetry.prom.record_gating`

```diff
 from .types import QueryProfile, BudgetDecision
 from .rm3_heuristics import StageGateConfig
 from .gating import analyze_query, decide_budgets, describe_budget_decision
-from codeintel_rev.observability.otel import record_span_event
+from codeintel_rev.observability.otel import record_span_event
+from codeintel_rev.telemetry.prom import record_gating
+from codeintel_rev.telemetry.decorators import trace_span
 
 def compute_budget(query: str, cfg: StageGateConfig) -> BudgetDecision:
-    profile = analyze_query(query, cfg)
-    decision = decide_budgets(profile, cfg)
-    record_span_event("retrieval.gating.decision", **describe_budget_decision(profile, decision))
+    with trace_span("retrieval.gating", stage="gating") as _:
+        profile = analyze_query(query, cfg)
+        decision = decide_budgets(profile, cfg)
+        data = describe_budget_decision(profile, decision)
+        record_span_event("retrieval.gating.decision", **data)
+        record_gating(int(data["rrf_k"]), float(data["ambiguity"]),
+                      literal=bool(data.get("literal")), vague=bool(data.get("vague")),
+                      rm3=bool(data.get("rm3_enabled")))
     return decision
```

You already capture rich details in `describe_budget_decision` for observability; this just wires them into spans and OTel metrics.  

---

### 7) vLLM client: standardize attributes & stage timing

**`io/vllm_client.py`** — you already use `as_span`/decorators in places; this makes the call‑site explicit with your decorator wrapper (keeps your style consistent):

```diff
 from time import perf_counter
-from codeintel_rev.observability.otel import as_span
+from codeintel_rev.telemetry.decorators import trace_span
 
 async def embed_batch(self, inputs: list[str]) -> list[list[float]]:
-    with as_span("vllm.embed_batch", model=self.model_name, dim=self.dim, mode=self.mode):
+    with trace_span("vllm.embed_batch", stage="embed", attrs={
+        "llm.model": self.model_name,
+        "llm.embedding_dim": int(self.dim),
+        "vllm.mode": self.mode,  # "http" | "inproc"
+        "batch.size": len(inputs),
+    }):
         # existing logic
         ...
```

(Your codebase already uses span helpers extensively for long‑lived stages and decorators; the change keeps the shape uniform and adds common attribute names.)  

---

### 8) FAISS manager: isolate search latency as a span + histogram

**`io/faiss_manager.py`**

```diff
-from codeintel_rev.observability.otel import as_span
+from codeintel_rev.telemetry.decorators import trace_span
+from opentelemetry import metrics
 
+_METER = metrics.get_meter("codeintel_rev.io.faiss")
+_faiss_latency = _METER.create_histogram("faiss_search_ms", unit="ms",
+    description="Latency of FAISS search by index type and GPU mode")
 
 def search(self, qvec, k: int):
-    with as_span("faiss.search", k=int(k), index_type=self._index_type, gpu_enabled=bool(self._gpu_on)):
+    with trace_span("faiss.search", stage="search", attrs={
+        "index.type": self._index_type,
+        "gpu.enabled": bool(self._gpu_on),
+        "k": int(k),
+    }):
         t0 = perf_counter()
         ids, scores = self._search_internal(qvec, k)
-        # (optional) existing logging/events here
+        _faiss_latency.record((perf_counter() - t0) * 1000.0, {
+            "index.type": self._index_type,
+            "gpu.enabled": bool(self._gpu_on),
+        })
         return ids, scores
```

(You already log FAISS operations and GPU/CPU modes; this adds an OTel histogram and explicit span/stage.) 

---

### 9) Keep using your decorators & timeline

Your `telemetry.decorators` include a rich span context manager/decorator that already integrates spans + timeline + optional checkpoints; we’re reusing it above. If desired, add **Span Links**/Baggage helpers here later (not shown).  

---

## How to run (service) & env

* **Service with auto‑instrumentation** (recommended):

```bash
OTEL_SERVICE_NAME=codeintel_rev \
OTEL_TRACES_EXPORTER=otlp \
OTEL_LOGS_EXPORTER=otlp \
OTEL_METRICS_EXPORTER=prometheus \
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318 \
OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true \
opentelemetry-instrument uvicorn codeintel_rev.app.main:app --host 0.0.0.0 --port 8080
```

> The attached guide explains metric/exporter options and that Prometheus scrape can be zero‑code via env; we keep a `/metrics` route that emits `generate_latest()` from the default registry where the `PrometheusMetricReader` is registered.  

* **CLIs/tests**: continue to call `init_telemetry(...)` (kept idempotent). If `opentelemetry-instrument` was used, it will be a no‑op aside from adding the flight‑recorder processor.

---

## Validation checklist (post‑merge)

1. `GET /metrics` returns Prom text **including** OTel `target_info` and your new instruments (`mcp_runs_total`, `faiss_search_ms`, …). **No** duplicate `target_info`. (If duplicate, ensure you didn’t also start a standalone `prometheus_client.start_http_server`.) 
2. A simple request generates:

   * a server span (FastAPI auto‑instr)
   * nested spans for `retrieval.gating`, `faiss.search`, `vllm.embed_batch`
   * an event `retrieval.gating.decision` with serialized decision fields.  
3. Logs in your backend show `trace_id`/`span_id` injected automatically when `OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true`. 
4. Setting `X-Run-Id` and/or `X-Session-Id` on a request makes those show up as **Baggage** (searchable in your backend).
5. Prometheus dashboards continue to function; time‑series count is stable thanks to Views.

---

## Why these diffs are safe & the evidence behind them

* **Today you hand‑expose Prometheus**: your telemetry module calls `generate_latest` and sets `CONTENT_TYPE_LATEST`, and the router exposes `/metrics`. We keep the route and change the *producer* to OTel instruments.   
* **OTel Prometheus reader**: designed to bridge the SDK with Prom scrape; it registers with the default registry and can run its own HTTP server via env, or you can serve via your existing route. 
* **Distro/CLI behavior & configuration**: `opentelemetry-instrument` + env drives exporters and instrumentations; you can still add span processors after init.  
* **OTLP (HTTP)**: stays configurable via env if gRPC isn’t feasible. 
* **Your code already centralizes span helpers** (decorators/timeline) and calls `record_span_event` in retrieval/duckdb paths; we extend rather than replace that.  

---

## Optional (next passes, no breaking change)

* **Replace local semconv shim**: re‑export official constants in `observability/semantic_conventions.py` to reduce future churn.
* **Add process/container/k8s detectors** if you run in containers/K8s. The guide describes container‑ID & k8s pod attributes. 
* **Span Links for fan‑out**: in hybrid search fusion, link child spans (BM25/SPLADE/FAISS) to the parent query span to render a proper query graph in traces. Your `telemetry.decorators` is a good place to add a helper for this. 

---

### Touchpoints confirmed in your tree

* `telemetry/prom.py` (current Prom scrape endpoint + counters).  
* `observability/otel.py`, `observability/metrics.py` exist and are the right homes for provider setup. 
* `app/main.py` is your FastAPI entry where we hook init + baggage middleware. 
* `retrieval/gating.py` has `describe_budget_decision` (we consume its fields).  
* `io/vllm_client.py` and `io/faiss_manager.py` are where we instrument embed and FAISS search. (Existing logging/probing code is present; we add span+metric.)  

---

If you’d like, I can follow up with:

* a **one‑file toggle** for enabling resource detectors based on env (so non‑container dev runs don’t error), and
* a minimal **OTel Collector** config that receives OTLP/HTTP on `4318` and scrapes your `/metrics` route (or relays to your existing Prometheus).

But the plan + diffs above are sufficient to ship this phase without breaking your dashboards, while moving your telemetry onto the **maintained** OTel surface.

**References used**

* Your repo map & SCIP index (file locations, present endpoints & helpers).      
* OpenTelemetry libraries guide (Prometheus reader, distro/CLI, logging auto‑instrumentation, OTLP protocols, resource detectors).     
