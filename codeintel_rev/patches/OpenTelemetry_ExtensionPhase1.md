Below is **Phase 1**: a surgical, repo‑aware implementation plan that wires OpenTelemetry + your existing Timeline/metrics into the *critical path* (MCP tool adapters → VLLM → FAISS → DuckDB → Hybrid fuse), and adds a partial‑run–aware **Run Report** you can call from an MCP tool or CLI.

I’ve tailored file paths, function names, and seams to your codebase (citations inline). Where the repo already has scaffolding (e.g., `observability.otel`, stage timers, Timeline), Phase 1 connects and extends it rather than reinventing it.

---

## What Phase 1 accomplishes

1. **Trace stitching from the edge to the engines.**

   * Start an OTel span per MCP tool call inside `tool_operation_scope`, bridge it to your `Timeline`, and surface structured events (start, end, error, stop‑reason). Your repo already exposes this context manager in `mcp_server.telemetry`, so we graft tracing here once, and it covers all tools that use it. 
2. **Deep spans in the hot path** with attributes you’ll actually debug against:

   * **VLLM** (`embed_batch`) already emits timeline events and even calls `as_span`; we standardize attrs and error events.
   * **FAISS** (`FAISSManager.search`) gets spans around primary/secondary searches and merge.
   * **DuckDB** (`DuckDBCatalog.query_by_uri`, `get_embeddings_by_ids`) gets DB spans with row counts and strictness flags.
   * **Hybrid fuse** (`HybridSearchEngine.search`) adds stage spans for channel collection + RRF fuse, recording *per‑channel fan‑in / contributions*. 
3. **Stage/gating decision breadcrumbs** recorded as events + metrics, using your existing stage‑telemetry helpers (`track_stage`, `record_stage_decision`, `record_stage_metric`).
4. **Run Report** (partial‑run aware): compact JSON/Markdown summarizing *what ran vs. what was skipped and why*, stitched from the Timeline JSONL (your `FlightRecorder`) and span events. We expose it as a tiny CLI and an MCP tool endpoint. 
5. **Zero CI gating** (as requested): all additions are passive diagnostics; nothing blocks tool execution.

---

## Implementation plan (step‑by‑step)

### A) Turn on tracing at the edge and propagate identity

* **Wrap `tool_operation_scope` with an OTel span** and mirror start/end/error into span events and the Timeline. This single change ensures every MCP tool call gets a top‑level span tied to your already‑present Timeline ledger. 
* **Attach a `X-Trace-Id` response header** from the current span (best effort; no hard runtime dependency if OTel is not installed).
* **Initialize OTel once** in FastAPI startup (safe no‑op if disabled): your `observability.otel` already exposes `init_telemetry`, `as_span`, and `record_span_event`.

### B) Instrument the hot path with spans + timeline events

* **VLLM**: `VLLMClient.embed_batch()` is already partially instrumented with `as_span`; we add consistent attributes (`mode`, `model`, `texts_count`, `dim`) and error events when HTTP fallback or backoff triggers.
* **FAISS**: `FAISSManager.search()`—add a parent span with `k`, `nprobe`, `has_secondary`, then child spans for `search_primary`, `search_secondary`, and `merge`. Emit timeline events for degraded CPU/GPU modes (your `ApplicationContext` already tracks GPU state).
* **DuckDB**: `DuckDBCatalog.query_by_uri()` and `get_embeddings_by_ids()`—wrap in spans with `uri`, `limit`, `rows`, `strict` and emit a timeline event when result‑sets are clipped.
* **Hybrid fuse**: `HybridSearchEngine.search()`—surround channel collection and `reciprocal_rank_fusion` with spans, record per‑channel counts, unique doc IDs, and contribution map presence. Your hybrid module already defines the types we can reference (e.g., `SearchHit`, RRF); we just expose diagnostics.

### C) Record gating decisions as first‑class events

* Your `retrieval.telemetry` module already provides a `track_stage()` context manager and `record_stage_decision/metric`. We’ll **call `record_span_event` with the same labels** so the spans and Prom metrics line up (stage name, budget, exceeded budget, reason).
* If you route through `retrieval.gating.should_run_secondary_stage()` / budget deciders, capture the input `QueryProfile` + output `StageDecision` into a structured event. 

### D) Partial‑run–aware **Run Report**

* Read the current session’s Timeline JSONL (via `FlightRecorder`) and span events, then synthesize an ordered ledger with **first failure/stop‑reason**, **which stages ran or were skipped**, **degraded modes**, and **top contributes** (e.g., FAISS vs. BM25 vs. SPLADE). Add a tiny CLI (`codeintel telemetry report`) and an MCP tool (`telemetry.get_report`). 

---

## Patches (unified diffs)

> Notes
> • Paths/identifiers match your repo structure and documented APIs in the index.
> • These diffs *extend* existing code; where functions already use the Timeline, we add `as_span`/`record_span_event`.
> • OTel remains optional: imports are either via your `observability.otel` shims or inside `try` blocks.

### 1) Edge tracing for all MCP tools

```diff
*** a/codeintel_rev/mcp_server/telemetry.py
--- b/codeintel_rev/mcp_server/telemetry.py
@@
-from contextlib import contextmanager
-from typing import Iterator
-from codeintel_rev.observability.timeline import current_or_new_timeline
+from contextlib import contextmanager
+from typing import Iterator
+from codeintel_rev.observability.timeline import current_or_new_timeline
+from codeintel_rev.observability.otel import as_span, record_span_event
@@
-@contextmanager
-def tool_operation_scope(tool_name: str, **attrs: object) -> Iterator[object]:
-    timeline = current_or_new_timeline()
-    with timeline.operation(f"tool.{tool_name}", **attrs):
-        yield timeline
+@contextmanager
+def tool_operation_scope(tool_name: str, **attrs: object) -> Iterator[object]:
+    """
+    Start a Timeline operation AND an OpenTelemetry span for an MCP tool call.
+    Mirrors start/end/error into span events so traces align with the JSONL ledger.
+    """
+    timeline = current_or_new_timeline()
+    with as_span(f"mcp.tool.{tool_name}", tool=tool_name, **attrs):
+        record_span_event("mcp.tool.start", tool=tool_name, **attrs)
+        with timeline.operation(f"tool.{tool_name}", **attrs):
+            try:
+                yield timeline
+            except Exception as exc:  # bubble up, but mark the span/timeline
+                record_span_event("mcp.tool.error", tool=tool_name, error=str(exc))
+                timeline.event("error", f"tool.{tool_name}", attrs={"error": str(exc)})
+                raise
+            finally:
+                record_span_event("mcp.tool.end", tool=tool_name)
```

Rationale: `tool_operation_scope` is already the canonical wrapper for MCP tool bodies; layering a span here ensures all tools gain consistent traces without touching every adapter. 

---

### 2) FastAPI startup & trace id header

```diff
*** a/codeintel_rev/app/main.py
--- b/codeintel_rev/app/main.py
@@
-from fastapi import FastAPI, Request
+from fastapi import FastAPI, Request
+from codeintel_rev.observability.otel import init_telemetry
@@
-app = FastAPI(title="CodeIntel MCP")
+app = FastAPI(title="CodeIntel MCP")
+# Initialize OpenTelemetry once (no-op if disabled/not installed)
+init_telemetry(app, service_name="codeintel-mcp")
@@
 async def set_mcp_context(request: Request, call_next):
     # existing context binding & timeline creation
     response = await call_next(request)
-    return response
+    # Best-effort: attach current trace id so clients can correlate logs/traces
+    try:
+        from opentelemetry.trace import get_current_span  # type: ignore
+        span = get_current_span()
+        ctx = getattr(span, "get_span_context", lambda: None)()
+        trace_id = getattr(ctx, "trace_id", 0)
+        if trace_id:
+            response.headers["X-Trace-Id"] = f"{trace_id:032x}"
+    except Exception:
+        # OTel may be disabled or unavailable; never fail the request
+        pass
+    return response
```

Rationale: your `set_mcp_context` already centralizes request context & Timeline; this safely exposes the trace id back to clients. 

---

### 3) FAISS search spans (primary/secondary/merge)

```diff
*** a/codeintel_rev/io/faiss_manager.py
--- b/codeintel_rev/io/faiss_manager.py
@@
 from typing import Iterable
+from codeintel_rev.observability.otel import as_span, record_span_event
@@
 def search(
     self,
     query: NDArrayF32,
     k: int | None = None,
     *,
     nprobe: int | None = None,
     runtime: SearchRuntimeOverrides | None = None,
 ) -> tuple[NDArrayF32, NDArrayI64]:
-    # existing search logic...
+    has_secondary = self.secondary_index is not None
+    with as_span("faiss.search", k=(k or -1), nprobe=(nprobe or -1), has_secondary=has_secondary):
+        try:
+            with as_span("faiss.search_primary", nprobe=(nprobe or -1)):
+                d1, i1 = self.search_primary(query, k or 50, nprobe or self._default_nprobe)
+            if has_secondary:
+                with as_span("faiss.search_secondary"):
+                    d2, i2 = self.search_secondary(query, k or 50)
+            else:
+                d2, i2 = None, None
+            with as_span("faiss.merge_results"):
+                distances, ids = self._merge_results(d1, i1, d2, i2, k or 50)
+            record_span_event("faiss.search.result", ids_returned=int(ids.shape[-1]))
+            return distances, ids
+        except Exception as exc:
+            record_span_event("faiss.search.error", error=str(exc))
+            raise
```

Rationale: the FAISS manager exposes a single `search()` with primary/secondary merge; instrumenting at this layer gives you cause‑level clarity on slowdowns or degraded behavior.

---

### 4) DuckDB hydration spans

```diff
*** a/codeintel_rev/io/duckdb_catalog.py
--- b/codeintel_rev/io/duckdb_catalog.py
@@
 from .duckdb_manager import DuckDBQueryBuilder, DuckDBQueryOptions
+from codeintel_rev.observability.otel import as_span, record_span_event
@@
 def query_by_uri(self, uri: str, limit: int = 100) -> list[dict]:
-    with self.connection() as con:
-        # existing query...
+    with as_span("duckdb.query_by_uri", uri=uri, limit=limit):
+        with self.connection() as con:
+            # existing query...
+            rows = results  # assign your variable name here
+            record_span_event("duckdb.query_by_uri.result", rows=len(rows))
+            return rows
@@
 def get_embeddings_by_ids(self, chunk_ids: Iterable[int], *, strict: bool = False) -> list[list[float]]:
-    with self.connection() as con:
-        # existing query...
+    with as_span("duckdb.get_embeddings_by_ids", ids=len(list(chunk_ids)), strict=strict):
+        with self.connection() as con:
+            # existing query...
+            record_span_event("duckdb.get_embeddings_by_ids.result", rows=len(vectors))
+            return vectors
```

Rationale: `query_by_uri()` and `get_embeddings_by_ids()` are the main I/O surfaces in hydration. Bound spans make “empty result vs. no‑run” easy to disambiguate.

---

### 5) Hybrid fuse & channel collection

```diff
*** a/codeintel_rev/io/hybrid_search.py
--- b/codeintel_rev/io/hybrid_search.py
@@
 from .retrieval.hybrid import reciprocal_rank_fusion, create_hit_list, SearchHit
+from codeintel_rev.observability.otel import as_span, record_span_event
+from codeintel_rev.observability.timeline import current_or_new_timeline
@@
 def search(
     self,
     query: str,
     *,
     semantic_hits: Sequence[tuple[int, float]],
     limit: int,
     extra_channels: Mapping[str, Sequence[ChannelHit]] | None = None,
     weights: Mapping[str, float] | None = None,
 ) -> HybridSearchResult:
-    # existing gather → fuse → clip
+    timeline = current_or_new_timeline()
+    with as_span("hybrid.collect_channels"):
+        # gather BM25/SPLADE if enabled, count hits per channel
+        # ...
+        record_span_event("hybrid.channels.collected",
+                          semantic=len(semantic_hits),
+                          bm25=len(bm25_hits) if bm25_hits else 0,
+                          splade=len(splade_hits) if splade_hits else 0)
+        timeline.event("stage", "hybrid.collect", attrs={
+            "semantic": len(semantic_hits),
+            "bm25": len(bm25_hits) if bm25_hits else 0,
+            "splade": len(splade_hits) if splade_hits else 0,
+        })
+    with as_span("hybrid.rrf_fuse"):
+        # existing reciprocal_rank_fusion(...)
+        record_span_event("hybrid.rrf.result", candidates=len(fused_ids))
+    # existing clip to limit + return
```

Rationale: The hybrid layer is where discrete operations (collect/fuse/clip) are often “silent” when they skip; explicit events avoid “no error but nothing happened” ambiguity. 

---

### 6) Gating decisions → span + timeline

```diff
*** a/codeintel_rev/retrieval/gating.py
--- b/codeintel_rev/retrieval/gating.py
@@
-from .telemetry import record_stage_decision
+from .telemetry import record_stage_decision
+from codeintel_rev.observability.otel import record_span_event
+from codeintel_rev.observability.timeline import current_or_new_timeline
@@
 def should_run_secondary_stage(signals: StageSignals, config: StageGateConfig) -> StageDecision:
     decision = _compute_decision(signals, config)
     record_stage_decision(COMPONENT_NAME, "secondary", decision)
+    attrs = {
+        "should_run": decision.should_run,
+        "reason": decision.reason,
+        "fanout": signals.fanout,
+        "score_margin": signals.score_margin,
+    }
+    record_span_event("retrieval.gating", **attrs)
+    current_or_new_timeline().event("decision", "retrieval.gating", attrs=attrs)
     return decision
```

Rationale: you already emit Prom metrics via `record_stage_decision`; this ties the same decision into the trace & Timeline so the single “Run Report” can narrate *why* stages ran. 

---

### 7) Minimal **Run Report** builder (new)

```diff
*** /dev/null
--- b/codeintel_rev/observability/reporting.py
@@
+from __future__ import annotations
+from dataclasses import dataclass
+from pathlib import Path
+import json
+from typing import Iterable
+
+@dataclass(frozen=True)
+class RunReport:
+    session_id: str
+    operations: list[dict]
+    first_error: dict | None
+    summary: dict
+
+def build_run_report(*, session_id: str, timeline_dir: Path) -> RunReport:
+    """
+    Parse the Timeline JSONL for a session and summarize:
+    - operations executed in order
+    - channel participation & counts
+    - degraded modes
+    - first error/stop reason (if any)
+    """
+    events: list[dict] = []
+    for path in sorted(timeline_dir.glob(f"{session_id}*.jsonl")):
+        with path.open("r", encoding="utf-8") as fh:
+            for line in fh:
+                try:
+                    events.append(json.loads(line))
+                except Exception:
+                    continue
+    operations = [e for e in events if e.get("kind") in {"stage", "operation", "decision"}]
+    first_error = next((e for e in events if e.get("kind") == "error"), None)
+    # lightweight synthesis
+    channels = {"semantic": 0, "bm25": 0, "splade": 0}
+    for e in events:
+        if e.get("name") == "hybrid.channels.collected":
+            a = e.get("attrs", {})
+            for k in channels:
+                channels[k] += int(a.get(k, 0)) if a.get(k) is not None else 0
+    summary = {"channels": channels, "had_error": first_error is not None}
+    return RunReport(session_id=session_id, operations=operations, first_error=first_error, summary=summary)
```

And expose it via a small CLI:

```diff
*** /dev/null
--- b/codeintel_rev/cli/telemetry.py
@@
+import typer
+from pathlib import Path
+from codeintel_rev.observability.reporting import build_run_report
+
+app = typer.Typer(help="Telemetry utilities")
+
+@app.command("report")
+def report(session_id: str, timeline_dir: Path):
+    rr = build_run_report(session_id=session_id, timeline_dir=timeline_dir)
+    typer.echo(rr)
```

The builder reads your `FlightRecorder` JSONL (already present in Timeline) and emits a single structured summary—designed for humans and LLMs alike to verify “what actually happened.” 

---

### 8) MCP tool: `telemetry.get_report` (new)

```diff
*** a/codeintel_rev/mcp_server/server_semantic.py
--- b/codeintel_rev/mcp_server/server_semantic.py
@@
 from fastmcp import mcp
+from codeintel_rev.observability.reporting import build_run_report
+from codeintel_rev.observability.timeline import current_timeline
@@
+@mcp.tool()
+async def telemetry_get_report() -> dict:
+    """
+    Return a partial-run–aware Run Report for the current session.
+    """
+    tl = current_timeline()
+    rr = build_run_report(session_id=tl.session_id, timeline_dir=tl.record_dir)
+    return {
+        "session_id": rr.session_id,
+        "summary": rr.summary,
+        "first_error": rr.first_error,
+        "operations": rr.operations[:200],  # cap to keep payload small
+    }
```

Rationale: the semantic server file is already the home for MCP tools; adding a small, read‑only tool keeps the contract simple for agents. 

---

## Dependency tweak (optional)

If not already present, add OTel libs (your `observability.otel` expects them but degrades gracefully):

```diff
*** a/pyproject.toml
--- b/pyproject.toml
@@
 [project.optional-dependencies]
 telemetry = [
-]
+  "opentelemetry-api>=1.25.0",
+  "opentelemetry-sdk>=1.25.0",
+  "opentelemetry-exporter-otlp>=1.25.0",
+  "opentelemetry-instrumentation-fastapi>=0.46b0",
+]
```

Your `observability.otel.init_telemetry()` will pick up `OTEL_SERVICE_NAME`/`OTEL_EXPORTER_OTLP_ENDPOINT` when you want to ship traces; otherwise the code runs locally with console/no‑op exporters. 

---

## Verification checklist (what to run now)

1. **Start the app** (local): ensure startup logs include “OTel initialized” (if enabled) and no errors. Your FastAPI app and middleware already exist; we’re just calling `init_telemetry` from startup. 
2. **Call a semantic search tool** with `limit=3`. Confirm:

   * Top‑level span **`mcp.tool.search:semantic`** with `query_chars`, `limit`. (Tool docs confirm the adapter signature & wrapper.) 
   * Child spans for **`vllm.embed_batch`**, **`faiss.search`** (and its children), **`duckdb.query_by_uri`**, **`hybrid.rrf_fuse`**.
   * Response headers include `X-Trace-Id`.
   * Timeline JSONL shows stages/events in order; `telemetry report` prints a Run Report with channel counts and any first error.
3. **Induce a skip/degraded scenario** (disable SPLADE or BM25, or switch off GPU): confirm **explicit “skip/degraded” events** appear in Timeline and corresponding span events are recorded. Your `ApplicationContext` and FAISS manager already expose CPU/GPU state, which we surface. 

---

## Why this gets you to “no‑mystery runs”

* **Disentangles “silent skip” vs “fast success”**: channel‑collection and gating decisions are now first‑class events, not inferred from absence. 
* **Per‑stage explainability**: every hot stage has a span with grounded, domain‑specific attributes (k, nprobe, strict, rows, contributions), not just a generic timer.
* **Partial‑run narrative**: the Run Report takes your Timeline ledger (via `FlightRecorder`) and composes a single, concise story—exactly what an AI agent or human needs to *validate understanding* and determine next actions. 

If you want, in a follow‑up we can push this further by **auto‑attaching the Run Report to each `AnswerEnvelope`** (it already has `method`/`stages` hooks), giving clients an always‑on miniature audit trail with zero extra calls. Your `MethodInfo`/`StageTiming` types are already defined to carry this. 

---

### Appendix — Source cues I targeted

* `tool_operation_scope` (wrap point for all tools). 
* `init_telemetry(…)`, `as_span`, `record_span_event` (OTel shim).
* `VLLMClient.embed_batch()` (already calling `as_span`, extend attrs). 
* `FAISSManager.search()` (dual index + merge). 
* `DuckDBCatalog.query_by_uri()` / `get_embeddings_by_ids()` (hydration path). 
* `HybridSearchEngine.search()` (collect + RRF). 
* Stage timers & gating telemetry for decisions and budgets.
* Timeline `FlightRecorder` JSONL (report input). 

---

If you want me to generate the exact files (ready to copy/paste) for any of the new modules (`observability/reporting.py`, `cli/telemetry.py`) or extend the MCP catalog with `telemetry.get_report`, I can provide the full content immediately.
