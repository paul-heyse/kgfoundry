
# Detailed implementation plan and code diffs #

Below is a *repo‑aware*, best‑in‑class implementation plan—with concrete code diffs—to take your **CodeIntel MCP (`codeintel_rev`)** telemetry from “good” to “exhaustive.” The plan uses the observability surfaces that already exist in your tree (OpenTelemetry bootstrap + Timeline/flight‑recorder, MCP tool scopes, retriever gates, IO clients) and stitches them into a unified, query/run‑level “ledger” that tells you **what happened** (not just how fast) during any run, where it stopped, and why.

Where I reference symbols or files, I cite your repository’s SCIP index and module metadata so you can trace the surfaces I am extending.

---

## What you already have (surfaces to build on)

* **Timeline / flight recorder** with `Timeline.event()`, `Timeline.operation()`, and `Timeline.step()` to emit structured events + scoped timing—with helpers to bind a per‑request timeline and to always retrieve a safe instance via `current_or_new_timeline()` / `bind_timeline()`. 【observability.timeline API: 】
* **MCP tool scopes**: `tool_operation_scope(tool_name, **attrs)` emits start/end operation events for tool handlers (great hook point). 【mcp_server.telemetry: 】
* **OTel glue**: `observability.otel` already exposes `init_telemetry()` and a span helper `as_span()` you can wrap around important work. 【observability.otel: 】
* **Hybrid search engine** with clear entrypoint and internal helpers; it already touches the timeline in places and records Prometheus counters. We’ll tighten this to produce stage‑level timings + decisions. 【io.hybrid_search search(): 】【observability.metrics used in search: 】
* **Budget gating** that derives per‑channel depths (BM25/SPLADE/semantic), RRF k, and RM3 flags—with a formatter to serialize decisions; we’ll make those decisions *first‑class events*. 【retrieval.gating: decide_budgets / describe_budget_decision(): 】
* IO clients for **vLLM embeddings**, **FAISS**, **DuckDB**, **XTR/WARP**—all perfect for step‑level spans + “did we actually do X?” checkpoints. (e.g., `VLLMClient.embed_batch()` already emits timeline events on failure.) 【vLLM client: 】【FAISS search() docstring: 】【DuckDB manager pool + connection ctx: 】

---

## Design goals and the shape of the solution

1. **Do not gate service.** These changes are diagnostic, not enforcement. Everything is opt‑in, cheap when off, and failure‑tolerant.
2. **Every run becomes a narrative.** A *ledger* ties together request/session IDs, tool operations, steps, gates, IO calls, and outcomes—so the LLM (or a human) can read exactly what happened.
3. **Single‑source-of-truth events.** We emit Timeline events (compact, structured) and *optionally* mirror the key ones as OTel spans/events so you can stream to any backend later.
4. **Partial‑run reports.** On any early abort, you can render a concise “where it stopped and why,” including last successful checkpoint and pending expectations.

---

## What we’ll add (high level)

* **Bootstrap OTel once** and auto‑instrument FastAPI + httpx (when available), using your lazy import helper to avoid heavy deps on local installs. 【lazy import helper: 】
* **Bind a Timeline per request** in `SessionScopeMiddleware`, then expose the `run_id` and `session_id` to spans and to the log context. 【bind/new timeline: 】
* **Wrap all MCP tools** with *both* Timeline and OTel spans (inside `tool_operation_scope()`), automatically tagging the operation and capturing exceptions as status. 【mcp_server.telemetry scope: 】
* **Make gates observable**: when budgets are decided, emit a `decision/gate.budget` event containing the serialized decision for what to try and why. 【gating serializers: 】
* **Make hybrid search explain itself**: add stage‑level timings (`embed`, `search.faiss`, `search.bm25`, `search.splade`, `fusion.rrf`, `hydrate.duckdb`), explicit channel run/skip events, and enrich the outgoing `MethodInfo.stages`. 【MethodInfo.stages: 】【hybrid entrypoints: 】
* **IO client spans + checkpoints**: vLLM/FAISS/DuckDB/WARP/XTR emit “started/done” steps with key attributes (batch size, k, SQL, candidates). These are *affirmative* “we did X” facts to disambiguate “fast success” vs “didn’t run.” 【vLLM embed hook point: 】【DuckDB Manager exec + pool: 】
* **Run‑end report**: `observability.reporting.render_run_report()` summarizes the last run’s ledger into a Markdown (or HTML) artifact: what ran, what was skipped, warnings, and the first failing step if any. (You already have the reporting module stub—this fills it out.) 【observability.reporting module: 】

---

## Implementation plan (step‑by‑step with diffs)

> The diffs are additive and conservative. They assume the file/module names and signatures as indexed in your SCIP metadata. If a local branch has drifted, the changes are trivial to adapt.

### 1) Strengthen OpenTelemetry bootstrap & FastAPI/httpx auto‑instrumentation

**Why**: keep OTel optional but ready; push `service.*` resource attrs; wire correlation IDs.
**Where**: `codeintel_rev/observability/otel.py` (extends your `init_telemetry()` and adds `instrument_fastapi()` + `instrument_httpx()` using lazy imports). 【otel helpers exist: 】【LazyModule exists: 】

```diff
diff --git a/codeintel_rev/observability/otel.py b/codeintel_rev/observability/otel.py
@@
-from __future__ import annotations
+from __future__ import annotations
+from typing import Any, Mapping, Optional
+from contextlib import suppress
+
+from codeintel_rev._lazy_imports import LazyModule
+_fastapi_instr = LazyModule("opentelemetry.instrumentation.fastapi", "instrument FastAPI")
+_httpx_instr    = LazyModule("opentelemetry.instrumentation.httpx", "instrument httpx")
+_logging_instr  = LazyModule("opentelemetry.instrumentation.logging", "instrument logging")
+
+# Existing exports: init_telemetry(), as_span(), record_span_event()  # (present in repo)
+# We extend init_telemetry to accept resource hints and keep it idempotent.

-def init_telemetry(...):
-    ...
+def init_telemetry(
+    service_name: str = "codeintel-mcp",
+    service_version: str | None = None,
+    *,
+    enable_logging_instrumentation: bool = True,
+) -> None:
+    """
+    Initialize OpenTelemetry once (idempotent), honoring env-driven exporters.
+    Also attaches Resource(service.name, service.version) if SDK present.
+    """
+    # call existing bootstrap if present; this keeps compatibility
+    with suppress(Exception):
+        _init_telemetry_impl = globals().get("_init_telemetry_impl")
+        if callable(_init_telemetry_impl):
+            _init_telemetry_impl(service_name=service_name, service_version=service_version)
+
+    # Optional logging correlation
+    if enable_logging_instrumentation:
+        with suppress(Exception):
+            _logging_instr.LoggingInstrumentor().instrument(set_logging_format=True)
+
+def instrument_fastapi(app) -> None:
+    """Attach FastAPI instrumentation if available (no-op otherwise)."""
+    with suppress(Exception):
+        _fastapi_instr.FastAPIInstrumentor.instrument_app(app)
+
+def instrument_httpx() -> None:
+    """Attach httpx client instrumentation if available (no-op otherwise)."""
+    with suppress(Exception):
+        _httpx_instr.HTTPXClientInstrumentor().instrument()
```

### 2) Bind a per‑request Timeline (and propagate IDs to spans)

**Why**: every request has a *run ledger*; IDs flow into Timeline *and* OTel.
**Where**: `codeintel_rev/app/middleware.py` – extend `SessionScopeMiddleware` to **create/bind** a new timeline using the session ID you already mint, and ensure it’s available to all called code via `bind_timeline()`. 【SessionScopeMiddleware design notes + request context: 】【new_timeline/bind/current: 】

```diff
diff --git a/codeintel_rev/app/middleware.py b/codeintel_rev/app/middleware.py
@@
-from __future__ import annotations
+from __future__ import annotations
+from codeintel_rev.observability.timeline import new_timeline, bind_timeline
+from codeintel_rev.runtime.request_context import get_session_id
@@ class SessionScopeMiddleware:
     async def __call__(self, request: Request, call_next):
-        # existing: extract or create X-Session-ID and stash into request.state / contextvar
+        # existing: extract or create X-Session-ID and stash into request.state / contextvar
         session_id: str = self._ensure_session_id(request)
-        response = await call_next(request)
-        return response
+        # Bind a new per-request timeline so everything downstream can emit events
+        timeline = new_timeline(session_id=session_id, force=False)
+        with bind_timeline(timeline):
+            response = await call_next(request)
+        return response
```

> *Note*: `runtime.request_context` already exposes contextvar helpers; those are still the source of truth for `X-Session-ID`. We only add the Timeline bind. 【request context helpers: 】

### 3) Ensure OTel is bootstrapped and instrument FastAPI at app startup

**Where**: `codeintel_rev/app/main.py` (or wherever you assemble `FastAPI` / build the MCP HTTP app). The index shows `app/main.py` provides the FastAPI entry and sets MCP context. We’ll call our new helpers there. 【app main & set_mcp_context mention: 】

```diff
diff --git a/codeintel_rev/app/main.py b/codeintel_rev/app/main.py
@@
-from __future__ import annotations
+from __future__ import annotations
+from importlib.metadata import version, PackageNotFoundError
+from codeintel_rev.observability.otel import init_telemetry, instrument_fastapi, instrument_httpx
@@
-app = FastAPI(...)
+app = FastAPI(...)
+
+# --- Observability bootstrap (no-op when deps/env not present) ---
+try:
+    _ver = version("kgfoundry")  # or your dist name; fall back when unknown
+except PackageNotFoundError:
+    _ver = None
+init_telemetry(service_name="codeintel-mcp", service_version=_ver)
+instrument_fastapi(app)
+instrument_httpx()
```

### 4) Make MCP tool scopes emit OTel spans in lockstep with Timeline

**Why**: you already emit Timeline start/end events via `tool_operation_scope()`; let’s add an *inner* OTel span with the same attributes (session/run IDs, tool name, input size), capturing errors/status automatically. 【tool_operation_scope(): 】【Timeline.operation(): 】【as_span(): 】

```diff
diff --git a/codeintel_rev/mcp_server/telemetry.py b/codeintel_rev/mcp_server/telemetry.py
@@
 from contextlib import contextmanager
-from codeintel_rev.observability.timeline import current_or_new_timeline
+from codeintel_rev.observability.timeline import current_or_new_timeline
+from codeintel_rev.observability.otel import as_span
+from codeintel_rev.runtime.request_context import get_session_id
@@
 @contextmanager
 def tool_operation_scope(tool_name: str, **attrs: object) -> Iterator[Timeline]:
-    tl = current_or_new_timeline()
-    with tl.operation(f"tool:{tool_name}", **attrs) as scope:
-        yield tl
+    tl = current_or_new_timeline()
+    # enrich attrs with correlation
+    enriched = dict(attrs)
+    enriched["session_id"] = getattr(tl, "session_id", None) or get_session_id()
+    enriched["run_id"]     = getattr(tl, "run_id", None)
+    with tl.operation(f"tool:{tool_name}", **enriched):
+        # mirror as OTel span (no-op if SDK/exporter not present)
+        with as_span(f"mcp.tool:{tool_name}", attributes=enriched):
+            yield tl
```

Now every MCP tool handler gets **two perfectly aligned scopes**: Timeline start/end events and an OTel span you can ship to any backend.

### 5) Record budget/gating decisions as first‑class events

**Why**: “why did we search/skip a channel?” should be explicit and machine‑readable.
**Where**: `codeintel_rev/retrieval/gating.py`—after producing a `BudgetDecision`, serialize via your `describe_budget_decision()` and emit a `decision/gate.budget` event. 【decide_budgets + describe function: 】

```diff
diff --git a/codeintel_rev/retrieval/gating.py b/codeintel_rev/retrieval/gating.py
@@
 from codeintel_rev.observability.timeline import current_timeline
@@ def decide_budgets(profile: QueryProfile, cfg: StageGateConfig) -> BudgetDecision:
     decision = ...
+    # Emit a structured decision event (only when a timeline is active/sampled)
+    tl = current_timeline()
+    if tl is not None:
+        tl.event(
+            "decision",
+            "gate.budget",
+            attrs=describe_budget_decision(profile, decision),
+        )
     return decision
```

### 6) Make *hybrid search* self‑documenting (stages + channel run/skip + method metadata)

**Why**: most “why did we get these results?” questions are answered here.
**Where**: `codeintel_rev/io/hybrid_search.py` (or the retrieval facade calling it). We wrap `search()` with a root operation, emit stage steps with counts/latencies, and *populate* `MethodInfo.stages` on the envelope. 【HybridSearchEngine.search(): 】【MethodInfo.stages: 】

```diff
diff --git a/codeintel_rev/io/hybrid_search.py b/codeintel_rev/io/hybrid_search.py
@@
 from time import perf_counter
-from codeintel_rev.observability.timeline import current_timeline
+from codeintel_rev.observability.timeline import current_timeline
@@ class HybridSearchEngine:
-    def search(self, query: str, semantic_hits: Sequence[tuple[int,int,float]], limit: int, options: HybridSearchOptions) -> HybridSearchResult:
-        tl = current_timeline()
-        ...
+    def search(self, query: str, semantic_hits: Sequence[tuple[int,int,float]], limit: int, options: HybridSearchOptions) -> HybridSearchResult:
+        tl = current_timeline()
+        stages: list[dict] = []
+        op_attrs = {"query_chars": len(query), "limit": int(limit)}
+        ctx = tl.operation("hybrid.search", **op_attrs) if tl else nullcontext()
+        with ctx:
+            # --- Stage: embed (if needed) ---
+            t0 = perf_counter()
+            # (your existing embedding / prep work)
+            t1 = perf_counter()
+            if tl: stages.append({"name": "embed", "duration_ms": round((t1 - t0)*1000, 2)})
+
+            # --- Stage: channels ---
+            # semantic (FAISS), bm25, splade – each recorded as run/skip with reasons
+            for channel_name in ("semantic","bm25","splade"):
+                c0 = perf_counter()
+                ran, count, reason = self._run_or_skip_channel(channel_name, query, options)
+                c1 = perf_counter()
+                if tl:
+                    tl.event("channel", f"channel.{('run' if ran else 'skip')}", attrs={
+                        "name": channel_name, "count": count, "reason": reason
+                    })
+                    stages.append({"name": f"search.{channel_name}",
+                                   "duration_ms": round((c1 - c0)*1000, 2),
+                                   "output": {"hits": count},
+                                   "notes": ([] if ran else [f"skipped: {reason}"])})
+
+            # --- Stage: fusion (RRF) ---
+            f0 = perf_counter()
+            # (your existing RRF fusion)
+            f1 = perf_counter()
+            if tl: stages.append({"name": "fusion.rrf", "duration_ms": round((f1 - f0)*1000, 2)})
+
+            # --- Stage: hydrate (DuckDB) ---
+            h0 = perf_counter()
+            # (your existing hydration via DuckDBCatalog)
+            h1 = perf_counter()
+            if tl: stages.append({"name": "hydrate.duckdb", "duration_ms": round((h1 - h0)*1000, 2)})
+
+        # Attach stage timings into MethodInfo so clients see what happened
+        result = ...  # existing HybridSearchResult
+        if hasattr(result, "method") and isinstance(result.method, dict):
+            result.method.setdefault("stages", stages)
+        return result
```

> You already have *channel emitters* (`_emit_channel_run/_emit_channel_skip`) and a method‑metadata composer; the snippet above illustrates the pattern—wire the same info into both **Timeline** and `MethodInfo.stages` so downstream UIs/agents never lose it. 【emit/compose helpers surfaced in index: 】

### 7) vLLM embeddings: positive proof of work

**Why**: disambiguate “no error” from “didn’t call.”
**Where**: `codeintel_rev/io/vllm_client.py`—wrap `embed_batch()` with `step()` + an OTel span; emit batch/model/dim and record counts. (You already emit failure events; we add “ok” with attributes.) 【vLLM embed points: 】

```diff
diff --git a/codeintel_rev/io/vllm_client.py b/codeintel_rev/io/vllm_client.py
@@
 from codeintel_rev.observability.timeline import current_timeline
+from codeintel_rev.observability.otel import as_span
@@ class VLLMClient:
     def embed_batch(self, texts: list[str]) -> list[list[float]]:
-        tl = current_timeline()
+        tl = current_timeline()
+        attrs = {"batch": len(texts), "model": self._model_name, "dim": self._embedding_dim}
+        ctx = tl.step("embed.vllm", **attrs) if tl else nullcontext()
+        with ctx, as_span("embed.vllm", attributes=attrs):
             try:
                 if self._local_engine is not None:
                     return self._local_engine.embed_batch(texts)
                 return self._embed_batch_http(texts)
             except Exception as exc:
                 if tl:
                     tl.event("error", "embed.vllm", message=str(exc), attrs={"batch": len(texts)})
                 raise
```

### 8) DuckDB: explicit SQL exec events (guarded by config)

**Why**: hydration bugs are often “what query actually ran?”—we’ll emit `sql.exec` events (sanitized), timing, and row counts when `duckdb.config.log_queries` (or similar) is set. **All low‑overhead** when off.
**Where**: `codeintel_rev/io/duckdb_manager.py`—wrap `execute()` and connection context with Timeline steps + OTel spans. (The manager and connection/pool APIs are present). 【DuckDB Manager APIs: 】

```diff
diff --git a/codeintel_rev/io/duckdb_manager.py b/codeintel_rev/io/duckdb_manager.py
@@
 from time import perf_counter
 from contextlib import contextmanager
 from typing import Iterator
+from codeintel_rev.observability.timeline import current_timeline
+from codeintel_rev.observability.otel import as_span
@@ class DuckDBManager:
-    def execute(self, query: Statement | str, parameters: object = None) -> DuckDBPyConnection:
-        conn = self._acquire_connection()
-        try:
-            return conn.execute(query, parameters)
-        finally:
-            self._release_connection(conn)
+    def execute(self, query: Statement | str, parameters: object = None) -> DuckDBPyConnection:
+        conn = self._acquire_connection()
+        tl = current_timeline()
+        q = str(query)
+        attrs = {"sql_len": len(q)}
+        if self._config and getattr(self._config, "log_queries", False):
+            attrs["sql"] = q[:5000]  # truncate to keep events small
+        t0 = perf_counter()
+        with (tl.step("sql.exec", **attrs) if tl else nullcontext()), as_span("duckdb.exec", attributes=attrs):
+            try:
+                res = conn.execute(query, parameters)
+                return res
+            finally:
+                dt = round((perf_counter() - t0)*1000, 2)
+                if tl:
+                    tl.event("io", "sql.exec.done", attrs={"duration_ms": dt})
+                self._release_connection(conn)
```

### 9) Wire a concise *run report* (partial runs included)

**Why**: on any failure/abort, a single artifact answers: *what ran, what didn’t, and why*.
**Where**: extend `codeintel_rev/observability/reporting.py` with `render_run_report(timeline)` and a simple CLI target (optional) to dump Markdown/JSON to `data/observability/runs/<run_id>.md`. 【reporting module exists: 】

```diff
diff --git a/codeintel_rev/observability/reporting.py b/codeintel_rev/observability/reporting.py
@@
+from __future__ import annotations
+from pathlib import Path
+from typing import Mapping, Any
+from datetime import datetime
+from codeintel_rev.observability.timeline import current_timeline
+
+def render_run_report(tl=None, *, out_dir: Path | None = None) -> Path:
+    """
+    Build a self-contained Markdown report for the active (or passed) timeline.
+    Includes: session/run IDs, ordered operations/steps, decisions, warnings,
+    first error (if any), and a brief 'Where it stopped and why' section.
+    """
+    tl = tl or current_timeline()
+    if tl is None:
+        raise RuntimeError("No active timeline to render")
+    run_id = getattr(tl, "run_id", "unknown")
+    session_id = getattr(tl, "session_id", "anonymous")
+    events = getattr(tl, "events", None)  # timeline keeps an in-memory ledger
+    lines: list[str] = [f"# Run Report — {run_id}", ""]
+    lines += [f"- **session**: `{session_id}`", f"- **run**: `{run_id}`", f"- **generated**: {datetime.utcnow().isoformat()}Z", ""]
+    first_error = None
+    for e in (events or []):
+        et, name, status, msg, attrs = e.get("type"), e.get("name"), e.get("status"), e.get("message"), e.get("attrs", {})
+        if et == "error" and first_error is None:
+            first_error = (name, msg, attrs)
+        pretty = ", ".join(f"{k}={v}" for k,v in attrs.items()) if attrs else ""
+        lines.append(f"- `{et}` **{name}** {('['+status+']' if status else '')} {msg or ''} {pretty}")
+    lines.append("")
+    if first_error:
+        lines.append("## First error")
+        lines.append(f"- **where**: {first_error[0]}")
+        lines.append(f"- **why**: {first_error[1]}")
+    else:
+        lines.append("## Status")
+        lines.append("- No errors recorded.")
+    out_dir = out_dir or Path("data/observability/runs")
+    out_dir.mkdir(parents=True, exist_ok=True)
+    out_path = out_dir / f"{run_id}.md"
+    out_path.write_text("\n".join(lines), encoding="utf-8")
+    return out_path
```

> The snippet assumes your `Timeline` keeps an in‑memory `events` buffer (the index shows a flight‑recorder pattern and event methods; if the buffer is named differently, pass through a `to_dict()` API or expose a `get_events()`—the map is trivial). 【timeline scopes + event API context: 】

---

## Optional (but recommended) very‑light enhancements

* **Add a `Timeline.checkpoint()` convenience** that’s just a thin wrapper on `event("checkpoint", ...)` for “asserted progress” signals (e.g., *module imported → import check done → next stage*). This helps AI agents test hypotheses about control‑flow with no perf cost. (If you prefer no API change, just use `event("checkpoint", "…")` consistently.) 【Timeline.event(): 】

* **Expose `run report` via a lightweight MCP tool** (`tools:report:latest_run`) that returns the last report path + a summary snippet, so your agents can fetch/inspect it mid‑debug.

---

## How this satisfies your three priorities

1. **No CI hooks / no gating** – All additions are observational. When a dependency isn’t installed (e.g., `opentelemetry-instrumentation-fastapi`) the lazy loader no‑ops, Timeline still works, and your server keeps running. 【lazy imports: 】
2. **Partial‑run reporting** – The Timeline is bound on every request; on any abort you have a chronological ledger and a Markdown “where it stopped and why.” 【binding and report generation: 】
3. **Even more to measure** (without chasing perf):

   * *Decision transparency*: budget gates (per‑channel depth, RM3) become explicit events, so you can see when a channel was skipped and why. 【gating: 】
   * *I/O truth*: SQL execs (sanitized), embed batches, FAISS/XTR/WARP calls emit “we did X” events.
   * *Stage‑level clarity*: `MethodInfo.stages` exposes what happened to the client alongside Timeline—great for agents to correlate inputs/outputs. 【MethodInfo.stages: 】

---

## Acceptance checklist (test it the same day)

* [ ] Start the app; verify no errors if OTel instrumentations are absent (lazy no‑ops).
* [ ] Hit `search.semantic`/`search.pro` tools and confirm:

  * Timeline shows: `tool:*` root → `hybrid.search` op → `embed.*` → `search.{semantic|bm25|splade}` → `fusion.rrf` → `hydrate.duckdb` and any `sql.exec` events.
  * The tool response `method.stages` is populated with timings. 【hybrid + stages surfacing: 】
* [ ] Force a failure (e.g., disconnect DuckDB); run report shows the first error and the last successful checkpoint, with “hydrate.duckdb” present and a captured exception message.
* [ ] If you install OTel SDK + an OTLP endpoint, verify traces contain `mcp.tool:*`, `hybrid.search`, `embed.vllm`, and `duckdb.exec` child spans with `session_id`/`run_id`.

---

## Notes on footprint and safety

* All event writes are **O(1)** and conditional on sampling (Timeline), and span creation is **no‑op** when OTel SDK/exporters are missing.
* SQL is truncated and only emitted when `DuckDBConfig.log_queries=True`. 【DuckDB manager & config fields present: 】
* All changes are local, don’t modify business logic, and won’t change results.

---

## Appendix — Additional touch‑ups you may consider (no diffs provided here)

* **FAISS/XTR/WARP hooks** mirroring the vLLM/DuckDB pattern (same `step()` + `as_span()` wrappers). 【FAISS search surface: 】【XTR search/rescore surfaces: 】
* **Ser/de of Timeline** to Parquet/JSON for offline forensics (you already have an Arrow/Parquet helper for chunk data; mirroring that shape is straightforward). 【parquet_store module exists: 】
* **Expose `tool_operation_scope`** attrs consistently across all adapters—your `server` and `semantic_pro` adapters already centralize error envelopes, so adding attrs like `query_chars`, `limit`, and `paths` is easy. 【adapters & server tools: 】

---

### Why these exact seams?

* They match the concrete symbols you already ship: Timeline APIs, OTel glue, MCP scopes, gating, hybrid retrieval, IO managers. I’m not introducing abstractions you don’t have; I’m *finishing the circuits* so an LLM can reconstruct **ground truth** for any run from a single ledger and a compact `method.stages` companion.
* They also satisfy your “consumer product” debugging emphasis—**proactive, affirmative reporting** of discrete operations, not just performance counters.

If you want me to also generate the minimal **migration PR checklist** (files to touch, local test commands, perf guardrails) and a *sample* run report output, say the word and I’ll include those immediately.


# migration checklist and sample run report #

Awesome — here are the two artifacts you asked for, ready to use:

* **Telemetry Readiness & Run Checklist** → [Download](sandbox:/mnt/data/telemetry_checklist.md)
* **Sample run report — CLI (index/enrichment)** → JSON: [Download](sandbox:/mnt/data/sample_run_report_cli.json) · Markdown: [Download](sandbox:/mnt/data/sample_run_report_cli.md)
* **Sample run report — HTTP (semantic_search)** → JSON: [Download](sandbox:/mnt/data/sample_run_report_http.json) · Markdown: [Download](sandbox:/mnt/data/sample_run_report_http.md)

Below I’ve inlined a concise view of what’s in each file and why it fits your repo. I’ve also anchored the design to concrete seams in your codebase so it’s easy for an AI agent (or you) to map telemetry to real execution.

---

## 1) What the checklist covers (and where it hooks into your code)

**A. Repo & artifacts sanity**
Ensures SCIP, DuckDB, FAISS, and optional XTR/WARP assets exist before a run — these are surfaced by the capability-gating and readiness flow in your app’s startup/lifespan sequence (GPU warmup, long‑lived clients, readiness checks). 

**B. Runtime environment**
GPU availability (CUDA/torch/FAISS‑GPU) validated via your **GPU doctor** tool surface and warm‑up path. The checklist directs an operator/agent to run “GPU doctor” up front. 

**C. Telemetry controls**

* Structured JSON logs & log level (env).
* **Timeline event bus**: a thin per‑stage “what happened” channel that complements metrics/traces.
* **Session correlation** across CLI & HTTP flows via `X-Session-ID` and the per‑request middleware. Your `SessionScopeMiddleware` and context middleware are the places to thread the session id and contextvars.

**D. HTTP server wiring (MCP)**

* **Context middleware** sets `ApplicationContext` into a contextvar so tool handlers can access it without request injection. 
* **Session scope middleware** generates/extracts `X-Session-ID`. 
* **Capability‑gated tool registration** in `build_http_app()` chooses tool groups based on `Capabilities` (semantic vs. symbols), enabling graceful degraded modes.
* **Problem Details error envelopes** backed by your domain error types (`FileOperationError`, `InvalidLineRangeError`, `GitOperationError`, `RuntimeUnavailableError`, etc.) so failures are consistently reported. 

**E. CLI pipeline (index/enrich)**
The checklist mirrors the stages in your index/enrichment pipeline (SCIP load → type‑signal collection → coverage mapping → import/use graph build → write artifacts), as orchestrated by your CLI/driver layer.

**F. Pre‑/Post‑run**

* Pre‑run snapshot: config, versions, paths.
* Post‑run outputs: JSON + Markdown “run reports,” top warnings, artifact inventory.

---

## 2) Sample run reports (how they read, how to produce them)

### A) CLI run (index + enrichment)

**What you’ll see in the sample:**

* Session header (commit/branch), environment snapshot, and **timeline spans** for each discrete stage: readiness probe → load SCIP → collect type signals → collect coverage → build graphs → write artifacts.
* Each stage records **status (OK/WARN/ERR)**, **duration**, and **attrs** (e.g., counts, reasons).
* Summarized **warnings** (e.g., “SPLADE disabled”, “coverage missing”).
* **Artifacts** written (parquet tables, graphs) with the output directory.

These steps align directly with your enrichment/scan flow and CLI driver (e.g., `index_all` entry), and the symbols/graph building that consume SCIP/metadata.

> Download the full sample:
> JSON: [sample_run_report_cli.json](sandbox:/mnt/data/sample_run_report_cli.json) · Markdown: [sample_run_report_cli.md](sandbox:/mnt/data/sample_run_report_cli.md)

### B) HTTP run (one `semantic_search` request)

**What you’ll see in the sample:**

* Session header (route/method), request parameters, and a **span tree** that records the exact operations performed:

  1. `embed.query` (vLLM) →
  2. `search.faiss` →
  3. `search.bm25` (disabled) →
  4. `search.splade` (not configured) →
  5. `fusion.rrf` →
  6. `hydrate.duckdb` (symbol joins).
* Response summary (HTTP status, result count) and **channel‑level WARNs**.

Those steps reflect your hybrid search implementation and the capability‑gated registration of semantic tools in `build_http_app()` (and how they degrade cleanly when channels are unavailable).

> Download the full sample:
> JSON: [sample_run_report_http.json](sandbox:/mnt/data/sample_run_report_http.json) · Markdown: [sample_run_report_http.md](sandbox:/mnt/data/sample_run_report_http.md)

---

## 3) How this maps to concrete seams in your repo (for the AI implementer)

* **Capability gating & degraded modes:** `Capabilities.has_semantic/has_symbols` determine tool registration; be sure to emit timeline events whenever a capability is missing so the run report explains *why* functionality was skipped. 
* **HTTP request context:** the `set_mcp_context` middleware stores `ApplicationContext` in a contextvar for use inside MCP tool handlers — perfect place to stamp `session_id`, start a “request” span, and attach a **timeline recorder** object onto the context for nested spans. 
* **Session scoping:** `SessionScopeMiddleware` is where we extract/generate `X-Session-ID` and initialize per‑request correlation; make sure every span carries this id. 
* **Tool catalog & handlers:** `build_http_app()` is your single wiring point; have it register a lightweight “telemetry bootstrap” that wraps FastMCP handlers to record the stage‑level spans (embed/search/fuse/hydrate) you see in the HTTP sample. 
* **Hybrid search internals:** expose micro‑spans inside the hybrid engine (embed, per‑channel searches, fusion, hydration). This mirrors the *compose method metadata* pattern in your hybrid layer and yields the “what happened” detail we need for diagnosis. 
* **Domain errors → Problem Details:** continue using your error types so the run report can include a structured `errors[]` section (code, http_status, context) that corresponds 1:1 to your exception hierarchy. 
* **CLI pipeline:** frame each phase (`readiness`, `load.scip_index`, `enrich.collect_*`, `graph.*`, `write.artifacts`) as a span in the same timeline format; that gives parity between CLI and HTTP reports and makes partial runs obvious. 

---

## 4) Next step to operationalize

1. **Drop‑in timeline recorder** (context‑aware):

   * Construct a tiny utility that exposes `start_span(name, **attrs)` / `end_span(status, **attrs)` and auto‑nests under the current span. Bind it to the per‑request `ApplicationContext` (HTTP) and to a root span (CLI). 

2. **Wire it at the right edges:**

   * HTTP: in `set_mcp_context` and in each tool adapter (semantic, symbols). 
   * CLI: at the entrypoint (e.g., `index_all`/pipeline driver) so every major stage emits its own child span. 

3. **Emit the run report artifacts** at the end of each session (success **or** failure) — the JSON model I used in the sample is intentionally flat and friendly for an LLM to parse, and the Markdown is optimized for quick human scanning.

---

### Why this format works for LLM‑driven debugging

* It records **discrete operations** (e.g., “enrich.collect_type_signals”, “fusion.rrf”) with **status** even when there’s **no error**, which lets an AI spot “skipped/omitted” vs. “ran successfully but did nothing” — the ambiguity you called out earlier.
* It is **capability‑aware**: missing assets naturally appear as WARNs on the timeline (e.g., BM25/SPLADE disabled), so agents can propose corrective actions rather than guessing. 
* It is **context‑aware** via the session id, so multi‑call MCP interactions can be stitched into a single narrative (your SessionScopeMiddleware is the anchor). 

If you’d like, I can now generate the small **timeline recorder** helper module and the minimal patches for `set_mcp_context`, the semantic tool adapter, and the CLI driver to produce reports exactly like the samples above.
