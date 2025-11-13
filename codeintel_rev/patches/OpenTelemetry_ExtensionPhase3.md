Below is **Phase 3** for your OpenTelemetry build‑out—focused on “**everything that happened**” (not just how fast), end‑to‑end **run correlation**, and a **durable operation ledger** that a programming LLM can mine to validate hypotheses about system behavior.

This plan is grounded in the current `codeintel_rev` layout (e.g., `app/main.py`, `observability/otel.py`, `telemetry/*`, `mcp_server/adapters/*`, `io/*`), as reflected in your latest repo map and SCIP index.

---

## Phase 3 — Objectives (what changes now)

1. **Operation Ledger (truth log).** Every discrete step (e.g., “import module”, “embed batch”, “gather SPLADE hits”, “fuse”, “hydrate”, “git.blame”) is recorded as a **first‑class “step event”** with `status ∈ {completed, skipped, failed, timed_out}`, **no inference**. These are written to:

   * a) OTel **span events** (narratable traces), and
   * b) a **JSONL run ledger** on disk (durable, simple to diff/inspect, easy for an LLM to read).

2. **Run correlation & partial‑run postmortems.** A consistent **`run_id`** is created at request entry (or propagated if provided), tied to **trace context** and returned in headers. A **Run Report v2.1** endpoint merges the ledger + spans to answer: *what ran, what didn’t, and why it stopped where it did*.

3. **OTel Logs bridge.** Your existing Python logging is bridged into **OTel Logs** with trace/span correlation so ops messages are visible alongside traces **and** captured in the run ledger.

4. **Domain‑specific diagnostics.** New “step kinds” for CodeIntel: FAISS/duckdb/bm25/splade/git/vLLM/rerank. Each step carries **well‑named attributes** so agents and humans can filter/aggregate.

> Nothing here gates the service (you asked for no CI hooks). It is pure diagnostics and narration.

---

## Patch index (TL;DR)

New modules:

* `observability/logs.py` – OTel logs bootstrap + logging bridge.
* `observability/ledger.py` – JSONL run ledger writer.
* `telemetry/steps.py` – step event schema + convenience emitters.
* `observability/run_report.py` – assemble Run Report v2.1 from spans + ledger.

Targeted edits:

* `observability/otel.py` – extend init to include logs; keep Phase 2 traces/metrics init. 
* `app/main.py` – generate/propagate `X-Run-ID`, return `X-Trace-Id` (Phase 2), attach both to root spans. 
* `mcp_server/adapters/semantic.py` (+ `semantic_pro.py`) – wrap tool calls with SERVER spans, emit step events, open/close run ledger, attach report link in AnswerEnvelope. 
* `io/vllm_client.py` – already CLIENT span (Phase 2); now emit step events (`embed_batch`) into ledger. 
* `io/hybrid_search.py` – already stage INTERNAL spans (Phase 2); now emit structured step events per channel & fusion/recency/hydration. 
* `io/duckdb_catalog.py`, `io/faiss_manager.py`, `io/bm25_manager.py`, `io/splade_manager.py`, `io/git_client.py` – add concise step emitters at key seams. 
* `mcp_server/error_handling.py` – capture domain errors to span status + step events with “stopped‑because” hints. 
* `app/routers/index_admin.py` – add `GET /observability/run/{run_id}/report` to fetch Run Report v2.1 (JSON/Markdown). 

---

## Code diffs (ready to apply)

> Notes:
>
> * Diffs assume the Phase 2 tracer bootstrap is present in `observability/otel.py` and the FastAPI app is built in `app/main.py`. Both files exist in your repo. 
> * Paths we patch exist (or are adjacent to files that exist) in your repo map (`mcp_server/adapters/semantic.py`, `io/*`, etc.). 
> * Where a function name differs slightly in your tree, the narrative callouts below indicate the seam to place the code (e.g., within the semantic adapter handler that builds the `AnswerEnvelope`). Your SCIP index confirms these modules are present. 

---

### 1) **New** — OTel logs bootstrap & logging bridge

**`codeintel_rev/observability/logs.py` (new)**

```diff
*** /dev/null
--- a/codeintel_rev/observability/logs.py
+++ b/codeintel_rev/observability/logs.py
@@ -0,0 +1,138 @@
+from __future__ import annotations
+import logging
+import os
+from typing import Iterable
+
+from opentelemetry._logs import set_logger_provider
+from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
+from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
+from opentelemetry.sdk.resources import Resource
+from opentelemetry.instrumentation.logging import LoggingInstrumentor
+
+try:
+    from opentelemetry.exporter.otlp.proto.http.log_exporter import OTLPLogExporter
+except Exception:  # optional dependency
+    OTLPLogExporter = None  # type: ignore
+
+_INIT_DONE = False
+
+def init_otel_logging(
+    service_name: str = "codeintel-mcp",
+    exporters: Iterable[str] = ("otlp",),
+    otlp_endpoint: str | None = None,
+    level: int = logging.INFO,
+) -> None:
+    """
+    Initialize OpenTelemetry Logs and bridge Python logging.
+    - Injects trace_id/span_id into logs automatically
+    - Exports to OTLP if available, falls back to in-process only
+    - Adds a root LoggingHandler so existing logging.* calls are captured
+    """
+    global _INIT_DONE
+    if _INIT_DONE:
+        return
+
+    resource = Resource.create({
+        "service.name": service_name,
+        "service.namespace": "kgfoundry",
+    })
+    provider = LoggerProvider(resource=resource)
+    set_logger_provider(provider)
+
+    if "otlp" in exporters and OTLPLogExporter:
+        ep = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
+        provider.add_log_record_processor(
+            BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{ep}/v1/logs"))
+        )
+
+    # Bridge stdlib logging → OTel
+    handler = LoggingHandler(level=level, logger_provider=provider)
+    root = logging.getLogger()
+    root.setLevel(min(root.level or level, level))
+    root.addHandler(handler)
+
+    # Ensure trace/span correlation fields are added to log records
+    LoggingInstrumentor().instrument(set_logging_format=True)
+    _INIT_DONE = True
```

---

### 2) **New** — Semantic conventions (step‑oriented) and helpers

If you already created `observability/semantic_conventions.py` in Phase 2, keep it and add **step constants** (we reuse it below). Otherwise, create it now.

**`codeintel_rev/observability/semantic_conventions.py` (append)**

```diff
--- a/codeintel_rev/observability/semantic_conventions.py
+++ b/codeintel_rev/observability/semantic_conventions.py
@@
 class Attrs:
+    # Step events
+    STEP_KIND        = "codeintel.step.kind"       # e.g., "faiss.search", "duckdb.query"
+    STEP_STATUS      = "codeintel.step.status"     # completed | skipped | failed | timed_out
+    STEP_DETAIL      = "codeintel.step.detail"     # free-form message
+    STEP_PAYLOAD     = "codeintel.step.payload"    # JSON string of structured attrs
+    RUN_LEDGER_PATH  = "codeintel.run.ledger_path" # JSONL ledger absolute path
+    RUN_ID           = "codeintel.run.id"
+    TRACE_ID         = "codeintel.trace.id"
```

---

### 3) **New** — Step schema + emitters (span‑event + ledger + stdlog)

**`codeintel_rev/telemetry/steps.py` (new)**

```diff
*** /dev/null
--- a/codeintel_rev/telemetry/steps.py
+++ b/codeintel_rev/telemetry/steps.py
@@ -0,0 +1,198 @@
+from __future__ import annotations
+import json
+import logging
+from dataclasses import dataclass, asdict
+from datetime import datetime, timezone
+from typing import Mapping, MutableMapping, Any
+from opentelemetry import trace
+from codeintel_rev.observability.semantic_conventions import Attrs, to_label_str
+from codeintel_rev.observability.ledger import RunLedger
+
+LOGGER = logging.getLogger(__name__)
+
+StepStatus = str  # "completed" | "skipped" | "failed" | "timed_out"
+
+@dataclass(slots=True, frozen=True)
+class StepEvent:
+    kind: str               # e.g., "faiss.search", "duckdb.query", "vllm.embed_batch"
+    status: StepStatus
+    detail: str | None = None
+    payload: Mapping[str, Any] | None = None
+
+def _now_iso() -> str:
+    return datetime.now(timezone.utc).isoformat()
+
+def emit_step(
+    run_ledger: RunLedger | None,
+    step: StepEvent,
+) -> None:
+    """
+    Emit a step to (1) the current span as an event, (2) the JSONL run ledger, (3) std logging.
+    Designed to be cheap; payload should already be small/normalized.
+    """
+    span = trace.get_current_span()
+    attrs: MutableMapping[str, Any] = {
+        Attrs.STEP_KIND: step.kind,
+        Attrs.STEP_STATUS: step.status,
+    }
+    if step.detail:
+        attrs[Attrs.STEP_DETAIL] = step.detail
+    if step.payload:
+        attrs[Attrs.STEP_PAYLOAD] = to_label_str(step.payload)
+
+    # (1) span event
+    if span and span.is_recording():
+        span.add_event("codeintel.step", attrs=attrs)
+
+    # (2) ledger
+    record = {
+        "ts": _now_iso(),
+        "trace_id": f"{trace.get_current_span().get_span_context().trace_id:032x}" if span else None,
+        "span_id": f"{trace.get_current_span().get_span_context().span_id:016x}" if span else None,
+        **asdict(step),
+    }
+    if run_ledger:
+        run_ledger.append(record)
+
+    # (3) std log (structured JSON for local grep)
+    try:
+        LOGGER.info("codeintel.step %s", json.dumps(record, ensure_ascii=False, sort_keys=True))
+    except Exception:
+        LOGGER.info("codeintel.step %s", record)
```

---

### 4) **New** — JSONL Run Ledger

**`codeintel_rev/observability/ledger.py` (new)**

```diff
*** /dev/null
--- a/codeintel_rev/observability/ledger.py
+++ b/codeintel_rev/observability/ledger.py
@@ -0,0 +1,142 @@
+from __future__ import annotations
+import io
+import json
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Mapping, Any
+
+@dataclass(slots=True)
+class RunLedger:
+    run_id: str
+    session_id: str | None
+    path: Path
+    _fh: io.TextIOWrapper | None = None
+
+    @classmethod
+    def open(cls, root_dir: Path, run_id: str, session_id: str | None) -> "RunLedger":
+        root_dir.mkdir(parents=True, exist_ok=True)
+        path = root_dir / f"{run_id}.jsonl"
+        fh = path.open("a", encoding="utf-8")
+        return cls(run_id=run_id, session_id=session_id, path=path, _fh=fh)
+
+    def append(self, record: Mapping[str, Any]) -> None:
+        if not self._fh:
+            self._fh = self.path.open("a", encoding="utf-8")
+        obj = {"run_id": self.run_id, "session_id": self.session_id, **dict(record)}
+        self._fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
+        self._fh.flush()
+
+    def close(self) -> None:
+        if self._fh:
+            try:
+                self._fh.flush()
+            finally:
+                self._fh.close()
+                self._fh = None
```

> We’ll store ledgers under `DATA_DIR/telemetry/runs/YYYY‑MM‑DD/` (see use below). Your app already has a settings/context object with `data_dir` or similar; hook there. 

---

### 5) Extend OTel bootstrap to include Logs (keep Phase 2 traces/metrics)

**`codeintel_rev/observability/otel.py` (extend)**

```diff
--- a/codeintel_rev/observability/otel.py
+++ b/codeintel_rev/observability/otel.py
@@
-from opentelemetry import trace, metrics
+from opentelemetry import trace, metrics
@@
 def init_otel(
     service_name: str = "codeintel-mcp",
     exporters: Iterable[str] = ("console", "otlp"),
     otlp_endpoint: str | None = None,
 ) -> None:
@@
     _INIT_DONE = True
+
+def init_all_telemetry(service_name: str = "codeintel-mcp") -> None:
+    """
+    Convenience: initialize traces, metrics, and logs in one call.
+    Logs are optional if OTLP log exporter is not installed.
+    """
+    init_otel(service_name=service_name)
+    try:
+        from .logs import init_otel_logging
+        init_otel_logging(service_name=service_name)
+    except Exception:
+        # Logging bridge is optional; don't fail app start
+        pass
```

The module you already have (`observability/otel.py`) is flagged in your map; the delta above only appends an optional “init all” convenience that we call from app boot. 

---

### 6) FastAPI boot — generate/propagate `run_id`, attach to trace, open header

**`codeintel_rev/app/main.py` (augment)**

```diff
--- a/codeintel_rev/app/main.py
+++ b/codeintel_rev/app/main.py
@@
-from .middleware import set_mcp_context, disable_nginx_buffering
+from .middleware import set_mcp_context, disable_nginx_buffering
+from uuid import uuid4
 from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
 from opentelemetry import trace
-from codeintel_rev.observability.otel import init_otel
+from codeintel_rev.observability.otel import init_all_telemetry
 from codeintel_rev.observability.semantic_conventions import Attrs
 from starlette.middleware.base import BaseHTTPMiddleware
 from starlette.requests import Request
 from starlette.responses import Response
@@
-    # Initialize tracing only once; safe if called multiple times by tests.
-    init_otel(service_name="codeintel-mcp")
+    # Initialize traces+metrics+logs in one place
+    init_all_telemetry(service_name="codeintel-mcp")
@@
     class _TraceHeadersMiddleware(BaseHTTPMiddleware):
         async def dispatch(self, request: Request, call_next):
             # Propagate session/run into the current root span
             session_id = request.headers.get("X-Session-ID")
-            run_id = request.headers.get("X-Run-ID")
+            run_id = request.headers.get("X-Run-ID") or str(uuid4())
+            # expose run_id to downstream handlers
+            request.state.run_id = run_id
             span = trace.get_current_span()
             if span and span.is_recording():
                 if session_id:
                     span.set_attribute(Attrs.MCP_SESSION_ID, session_id)
                 if run_id:
-                    span.set_attribute(Attrs.MCP_RUN_ID, run_id)
+                    span.set_attribute(Attrs.MCP_RUN_ID, run_id)
             response: Response = await call_next(request)
             # return trace id to clients for correlation
             ctx = trace.get_current_span().get_span_context()
             if ctx and ctx.trace_id:
                 response.headers["X-Trace-Id"] = format(ctx.trace_id, "032x")
+            response.headers["X-Run-Id"] = run_id
             return response
```

Your `app/main.py` is already present and is the correct place to mount middleware and OTel instrumentation. 

---

### 7) Semantic MCP adapters — open a ledger and narrate steps

Patch **both** `mcp_server/adapters/semantic.py` and `mcp_server/adapters/semantic_pro.py` in the same way at the top‑level handler that constructs and returns the `AnswerEnvelope`.

**`codeintel_rev/mcp_server/adapters/semantic.py` (key fragments)**

```diff
--- a/codeintel_rev/mcp_server/adapters/semantic.py
+++ b/codeintel_rev/mcp_server/adapters/semantic.py
@@
 from fastapi import Request
 from opentelemetry import trace
 from opentelemetry.trace import SpanKind, Status, StatusCode
 from codeintel_rev.observability.semantic_conventions import Attrs
+from codeintel_rev.observability.ledger import RunLedger
+from codeintel_rev.telemetry.steps import StepEvent, emit_step
@@
 async def semantic_search(request: Request, params: SemanticParams) -> AnswerEnvelope:
-    tracer = trace.get_tracer(__name__)
-    with tracer.start_as_current_span("mcp.semantic_search", kind=SpanKind.SERVER) as span:
+    tracer = trace.get_tracer(__name__)
+    with tracer.start_as_current_span("mcp.semantic_search", kind=SpanKind.SERVER) as span:
         if span.is_recording():
             span.set_attribute(Attrs.MCP_TOOL, "search:semantic")
             span.set_attribute(Attrs.MCP_SESSION_ID, getattr(request.state, "session_id", None) or request.headers.get("X-Session-ID"))
-            span.set_attribute(Attrs.MCP_RUN_ID, request.headers.get("X-Run-ID"))
+            span.set_attribute(Attrs.MCP_RUN_ID, getattr(request.state, "run_id", None) or request.headers.get("X-Run-ID"))
+
+        # Open run ledger under data_dir/telemetry/runs/YYYY-MM-DD
+        appctx = request.app.state.app_context  # created at startup in your context builder
+        runs_dir = (appctx.paths.data_dir / "telemetry" / "runs" / appctx.now_utc().date().isoformat())
+        run_id = getattr(request.state, "run_id", None) or "unknown"
+        session_id = getattr(request.state, "session_id", None) or request.headers.get("X-Session-ID")
+        ledger = RunLedger.open(runs_dir, run_id=run_id, session_id=session_id)
+        if span.is_recording():
+            span.set_attribute(Attrs.RUN_LEDGER_PATH, str(ledger.path))
+            span.set_attribute(Attrs.RUN_ID, run_id)
+
+        emit_step(ledger, StepEvent(kind="tool.begin", status="completed", payload={"tool": "search:semantic"}))
         try:
             # .. existing logic: embed → hybrid search → hydrate → envelope ..
             envelope = await _do_semantic_search(request, params, ledger)
-            return envelope
+            emit_step(ledger, StepEvent(kind="tool.finish", status="completed", payload={"tool": "search:semantic"}))
+            return envelope
         except Exception as e:
             if span.is_recording():
                 span.record_exception(e)
                 span.set_status(Status(StatusCode.ERROR, str(e)))
+            emit_step(ledger, StepEvent(kind="tool.error", status="failed", detail=str(e)))
             raise
+        finally:
+            ledger.close()
```

> *Where to wire `appctx` and `now_utc`*: your app already centralizes paths and time helpers in the `ApplicationContext`/settings and middleware; use those to resolve `data_dir` safely. The adapters file exists and is the right seam to wrap tool invocations. 

Now, inside your internal implementation (where you currently collect results), emit **fine‑grained steps**. For example, if you have a helper like `_do_semantic_search`, pass the ledger through and emit steps as stages complete.

---

### 8) vLLM embedding — add step events alongside the existing CLIENT span

**`codeintel_rev/io/vllm_client.py` (append within embed path)**

```diff
--- a/codeintel_rev/io/vllm_client.py
+++ b/codeintel_rev/io/vllm_client.py
@@
 from codeintel_rev.observability.semantic_conventions import Attrs, to_label_str
+from codeintel_rev.telemetry.steps import StepEvent, emit_step
+from typing import Optional
+from codeintel_rev.observability.ledger import RunLedger
@@
-    def embed_batch(self, texts: Sequence[str]) -> NDArrayF32:
+    def embed_batch(self, texts: Sequence[str], *, _ledger: Optional[RunLedger] = None) -> NDArrayF32:
@@
-            try:
+            try:
+                emit_step(_ledger, StepEvent(
+                    kind="vllm.embed_batch",
+                    status="completed",
+                    payload={"count": len(texts), "mode": mode, "model": self.model_name},
+                ))
                 if self._http_client is not None:
                     out = self._embed_batch_http(texts)
                 else:
                     out = self._local_engine.embed_batch(texts)
                 return out
             except Exception as e:  # map to trace error
                 if span.is_recording():
                     span.record_exception(e)
                     span.set_status(Status(StatusCode.ERROR, str(e)))
+                emit_step(_ledger, StepEvent(
+                    kind="vllm.embed_batch",
+                    status="failed",
+                    detail=str(e),
+                    payload={"count": len(texts), "mode": mode, "model": self.model_name},
+                ))
                 raise
```

`io/vllm_client.py` is present in your tree and was instrumented in the previous phase for spans—this change simply surfaces an **explicit step event** that lands in the ledger. 

---

### 9) Hybrid retrieval — step events for gather/fuse/boost/hydrate

**`codeintel_rev/io/hybrid_search.py` (augment where you already added spans)**

```diff
--- a/codeintel_rev/io/hybrid_search.py
+++ b/codeintel_rev/io/hybrid_search.py
@@
 from codeintel_rev.observability.semantic_conventions import Attrs, to_label_str
+from codeintel_rev.telemetry.steps import StepEvent, emit_step
+from codeintel_rev.observability.ledger import RunLedger
@@
-    def search(
+    def search(
         self,
         query: str,
         *,
         semantic_hits: Sequence[tuple[int, float]],
         limit: int,
-        options: HybridSearchOptions | None = None
-    ) -> HybridSearchResult:
+        options: HybridSearchOptions | None = None,
+        _ledger: RunLedger | None = None,
+    ) -> HybridSearchResult:
@@
-            # gather channels
+            # gather channels
             with tracer.start_as_current_span("retrieval.gather_channels") as gspan:
                 runs, warnings = self._gather_channel_hits(query, semantic_hits)
                 if gspan.is_recording():
                     gspan.set_attribute(Attrs.CHANNELS_USED, to_label_str(list(runs.keys())))
                     if warnings:
                         gspan.set_attribute(Attrs.WARNINGS, to_label_str(warnings))
+                emit_step(_ledger, StepEvent(
+                    kind="retrieval.gather_channels",
+                    status="completed",
+                    payload={"channels": list(runs.keys()), "warnings": warnings},
+                ))
@@
-            # pool/fuse
+            # pool/fuse
             docs, per_doc_contrib = self._execute_fusion(runs, limit)
             with tracer.start_as_current_span("retrieval.fuse") as fspan:
                 if fspan.is_recording():
                     fspan.set_attribute(Attrs.FUSED_DOCS, len(docs))
+            emit_step(_ledger, StepEvent(
+                kind="retrieval.fuse",
+                status="completed",
+                payload={"fused_docs": len(docs)},
+            ))
@@
-            if boosted_count:
+            if boosted_count:
                 trace.get_current_span().set_attribute(Attrs.RECENCY_BOOSTED, int(boosted_count))
+                emit_step(_ledger, StepEvent(
+                    kind="retrieval.recency_boost",
+                    status="completed",
+                    payload={"boosted": int(boosted_count)},
+                ))
```

You already have this file and stages; this adds **explicit step events** so the ledger tells you what happened even if the next stages are skipped or fail. 

---

### 10) DuckDB hydration — step events with row counts

**`codeintel_rev/io/duckdb_catalog.py` (wrap your hydrate/get calls)**

```diff
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@
 from opentelemetry import trace
 from codeintel_rev.observability.semantic_conventions import Attrs
+from codeintel_rev.telemetry.steps import StepEvent, emit_step
+from codeintel_rev.observability.ledger import RunLedger
@@
-    def hydrate(self, ids: Sequence[int]) -> list[DocRecord]:
+    def hydrate(self, ids: Sequence[int], *, _ledger: RunLedger | None = None) -> list[DocRecord]:
         tracer = trace.get_tracer(__name__)
         with tracer.start_as_current_span("duckdb.hydrate") as span:
             rows = self._hydrate_rows(ids)
             if span.is_recording():
                 span.set_attribute(Attrs.DUCKDB_ROWS, len(rows))
-            return [self._row_to_doc(r) for r in rows]
+            docs = [self._row_to_doc(r) for r in rows]
+            emit_step(_ledger, StepEvent(
+                kind="duckdb.query",
+                status="completed",
+                payload={"rows": len(rows), "op": "hydrate"},
+            ))
+            return docs
```

This file exists in your tree; the exact method name may be `_hydrate`/`hydrate_*`—wrap the hydration surface that returns doc metadata. 

---

### 11) Git client — step events for `blame`/`history`

**`codeintel_rev/io/git_client.py` (selected fragment)**

```diff
--- a/codeintel_rev/io/git_client.py
+++ b/codeintel_rev/io/git_client.py
@@
 from codeintel_rev.observability.semantic_conventions import Attrs
+from codeintel_rev.telemetry.steps import StepEvent, emit_step
+from codeintel_rev.observability.ledger import RunLedger
@@
-    async def blame_range(self, path: str, start_line: int, end_line: int) -> list[BlameRecord]:
+    async def blame_range(self, path: str, start_line: int, end_line: int, *, _ledger: RunLedger | None = None) -> list[BlameRecord]:
         tracer = trace.get_tracer(__name__)
         with tracer.start_as_current_span("git.blame") as span:
             if span.is_recording():
                 span.set_attribute(Attrs.GIT_OP, "blame")
                 span.set_attribute(Attrs.GIT_PATH, path)
                 span.set_attribute(Attrs.GIT_LINE_RANGE, f"{start_line}-{end_line}")
-            return await self._do_blame(path, start_line, end_line)
+            out = await self._do_blame(path, start_line, end_line)
+            emit_step(_ledger, StepEvent(
+                kind="git.blame",
+                status="completed",
+                payload={"path": path, "range": [start_line, end_line]},
+            ))
+            return out
```

File exists under `io/` and is listed in your map. 

---

### 12) Error handling — emit “stopped‑because” hints as step events

**`codeintel_rev/mcp_server/error_handling.py` (augment)**

```diff
--- a/codeintel_rev/mcp_server/error_handling.py
+++ b/codeintel_rev/mcp_server/error_handling.py
@@
 from opentelemetry import trace
 from opentelemetry.trace import Status, StatusCode
+from codeintel_rev.telemetry.steps import StepEvent, emit_step
+from codeintel_rev.observability.ledger import RunLedger
@@
-def map_exception(exc: Exception) -> ProblemDetails:
+def map_exception(exc: Exception, *, _ledger: RunLedger | None = None) -> ProblemDetails:
     span = trace.get_current_span()
     if span and span.is_recording():
         span.record_exception(exc)
         span.set_status(Status(StatusCode.ERROR, str(exc)))
+    # Emit a diagnostic step that helps postmortems connect the dots
+    emit_step(_ledger, StepEvent(
+        kind="error",
+        status="failed",
+        detail=type(exc).__name__,
+        payload={"message": str(exc)},
+    ))
     return _to_problem_details(exc)
```

This module exists and already centralizes error → Problem Details mapping; add step emission so the ledger explicitly records *why* a run ended early. 

---

### 13) Run Report v2.1 — assemble from spans + ledger & route

**`codeintel_rev/observability/run_report.py` (new)**

```diff
*** /dev/null
--- a/codeintel_rev/observability/run_report.py
+++ b/codeintel_rev/observability/run_report.py
@@ -0,0 +1,168 @@
+from __future__ import annotations
+import json
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Any, Iterable, Mapping
+
+@dataclass(slots=True)
+class RunReport:
+    run_id: str
+    stopped_because: str | None
+    steps: list[Mapping[str, Any]]
+    warnings: list[str]
+    ledger_path: str
+
+def load_ledger(ledger_path: Path) -> list[dict[str, Any]]:
+    steps: list[dict[str, Any]] = []
+    if not ledger_path.exists():
+        return steps
+    with ledger_path.open("r", encoding="utf-8") as fh:
+        for line in fh:
+            try:
+                steps.append(json.loads(line))
+            except Exception:
+                continue
+    return steps
+
+def infer_stop_reason(steps: Iterable[Mapping[str, Any]]) -> str | None:
+    # Very simple heuristic: last failed/timed_out step, else None
+    last = None
+    for s in steps:
+        if s.get("status") in {"failed", "timed_out"}:
+            last = s
+    if last:
+        return f"{last.get('kind')}::{last.get('status')}"
+    return None
+
+def build_run_report(run_id: str, ledger_path: Path) -> RunReport:
+    steps = load_ledger(ledger_path)
+    stopped_because = infer_stop_reason(steps)
+    warnings = []
+    return RunReport(
+        run_id=run_id,
+        stopped_because=stopped_because,
+        steps=steps,
+        warnings=warnings,
+        ledger_path=str(ledger_path),
+    )
```

**`codeintel_rev/app/routers/index_admin.py` (add route)**

```diff
--- a/codeintel_rev/app/routers/index_admin.py
+++ b/codeintel_rev/app/routers/index_admin.py
@@
 from fastapi import APIRouter, HTTPException
+from fastapi import Request
+from pathlib import Path
+from codeintel_rev.observability.run_report import build_run_report
+from codeintel_rev.observability.ledger import RunLedger
@@
 router = APIRouter()
@@
+@router.get("/observability/run/{run_id}/report")
+async def get_run_report(run_id: str, request: Request):
+    appctx = request.app.state.app_context
+    runs_dir = appctx.paths.data_dir / "telemetry" / "runs" / appctx.now_utc().date().isoformat()
+    ledger_path = runs_dir / f"{run_id}.jsonl"
+    if not ledger_path.exists():
+        raise HTTPException(status_code=404, detail="Run ledger not found")
+    report = build_run_report(run_id, ledger_path)
+    return report.__dict__
```

This router file exists in your repo and already hosts admin/index endpoints; it’s a natural place for an observability report route. 

---

## Where else to place **step emitters** (brief callouts)

You have several seams worth one‑line `emit_step(...)` calls; they’re all present in your tree:

* `io/faiss_manager.py` — after the search call, record `{"k": k, "nprobe": nprobe, "gpu": bool}` with kind `faiss.search`. 
* `io/bm25_manager.py` — upon query finish, `bm25.search` with hit count & query len. 
* `io/splade_manager.py` — `splade.search` with hit count & doc frequency info if available. 
* `retrieval/gating.py` — when budgets are decided, `retrieval.budget` with per‑channel depths/rrf_k. (You surfaced budgets in Phase 2 spans; add an explicit step.) 

These are all in your latest map; add emitters at the top‑level public methods (the ones your search pipeline calls). 

---

## Design rationale & implementation callouts

* **Why JSONL ledger?**
  It’s *append‑only*, resilient to partial runs, trivial to grep, and trivial for an agent to replay offline. Span events are great for live UIs; the **ledger is source‑of‑truth** for postmortems and agent reasoning.

* **No speculative inference.**
  Every “did”/“skipped” is a literal step event. “Stopped‑because” is an **explicit error step** (from error handling) or a trivial heuristic over the last `failed`/`timed_out` step.

* **Trace/log convergence.**
  With the OTel Logging bridge, your existing logs (e.g., warnings in hybrid retrieval) inherit trace IDs, so Kibana/Loki/Grafana/Tempo‑style stacks correlate instantly—**without** changing your logging calls.

* **Agent‑friendly payloads.**
  Keep payloads small, crisp, and normalized (counts, lists, boolean flags, identifiers). Avoid embedding raw blobs or large arrays—let the agent pull details via URIs when needed.

* **Zero gating.**
  There’s no CI/service gating here. Everything is *observational* and designed to help a human or LLM understand what truly occurred.

---

## Minimal usage changes (thread the ledger)

* Pass `_ledger=ledger` from the adapter down into vLLM/Hybrid/DuckDB/Git functions you instrumented above. This is a mechanical addition to existing call sites:

  * `vllm_client.embed_batch(texts, _ledger=ledger)`
  * `hybrid_engine.search(query, ..., _ledger=ledger)`
  * `duckdb_catalog.hydrate(ids, _ledger=ledger)`
  * `git_client.blame_range(path, ..., _ledger=ledger)`

(These entry points all exist in your repo and are already used by your semantic adapters.) 

---

## Run it / validate it

1. **Install deps** (superset; logs exporter is optional):

```bash
pip install "opentelemetry-sdk>=1.26" \
            "opentelemetry-exporter-otlp-proto-http>=1.26" \
            "opentelemetry-instrumentation-fastapi>=0.46b0" \
            "opentelemetry-instrumentation-logging>=0.46b0"
```

2. **Start the server** and call a semantic tool. The response headers will include `X-Trace-Id` and `X-Run-Id`.

3. **Inspect the ledger** at `DATA_DIR/telemetry/runs/<YYYY-MM-DD>/<run_id>.jsonl` and fetch the structured report:

```
GET /observability/run/{run_id}/report
```

4. **Failure case sanity check:** Force a DuckDB path error; you should see:

   * a `duckdb.query` step with `status="failed"` (or a subsequent `error` step with the exception type),
   * `stopped_because` reflecting that last failed step in the report.

---

## What this unlocks next (Phase 4 preview)

* **Exemplars**: link Prometheus histograms to traces with exemplars so you can click from a latency spike to its run ledger.
* **Lightweight runbook hooks**: map `kind`+`status` to suggested fix or self‑healing action (displayed in the Run Report).

---

### Cross‑checks against your repo

* `app/main.py`, `observability/otel.py`, `observability/timeline.py`, `telemetry/*`, `io/*`, `mcp_server/adapters/*`, and `mcp_server/error_handling.py` are present and the correct seams to instrument. 
* SCIP confirms module presence and structure for the CodeIntel package (e.g., `codeintel_rev` package, CLI/enrich structure, and observability/telemetry modules exist). 

---

## Cut‑and‑paste checklist

* [ ] Add new files: `observability/logs.py`, `observability/ledger.py`, `telemetry/steps.py`, `observability/run_report.py`.
* [ ] Patch `observability/semantic_conventions.py` with step constants.
* [ ] Patch `observability/otel.py` to expose `init_all_telemetry`.
* [ ] Patch `app/main.py` to call `init_all_telemetry`, generate/propagate `run_id`, return headers.
* [ ] Patch `mcp_server/adapters/semantic*.py` to open/close ledger, emit `tool.begin/finish/error`, and thread `_ledger` into downstream calls.
* [ ] Patch `io/*` seams and `mcp_server/error_handling.py` to emit step events.
* [ ] Add route `GET /observability/run/{run_id}/report` in `app/routers/index_admin.py`.
* [ ] Verify one end‑to‑end run; inspect JSONL ledger; fetch report.

If you’d like, I can generate a **single patch file** that includes all the diffs above, plus a tiny “hello‑world” semantic search call you can run to see the ledger & report fill in.
