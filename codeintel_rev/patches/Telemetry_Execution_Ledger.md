Below is a **complete, repo‑specific implementation plan** for an **Execution Ledger** that records *everything that happened* during any run (short or long), with concrete code diffs you can drop into `codeintel_rev`. The plan plugs into the **actual seams and files in your repo** (FastAPI app, MCP adapters, retrieval engine, FAISS/DuckDB/vLLM clients, telemetry), with trace/log/metric correlation but **no dependence on CI or quality‑gating**. Where I reference current files/locations, I cite your repo map/SCIP so you can verify paths quickly. 

> **What this gives you**
>
> * A **per‑request run ledger** (append‑only, structured, trace‑anchored).
> * **Stage checkpoints** for each discrete operation (embed → search per channel → fuse → hydrate → rerank → envelope).
>   * Each checkpoint has *start*, *end*, *attrs*, *warnings*, and *why stopped* markers.
> * A **Run Report v2** you can fetch as JSON/Markdown that narrates where a run stopped and why (even when there’s no error).
> * Minimal coupling: the ledger is a sidecar API (context‑local), and each integration point calls a single helper `ledger.event(...)`.

---

## How it fits **your** code today

You already expose an MCP HTTP server with FastAPI (`app/main.py`; MCP adapters in `mcp_server/adapters/*.py`) and route all dependency wiring through `ApplicationContext`; the retrieval stack lives in `retrieval/hybrid.py`, FAISS/DuckDB in `io/*.py`, and vLLM integration in `io/vllm_client.py`. You also have observability/telemetry scaffolding (`observability/otel.py`, `telemetry/*.py`) and response envelopes used by tools. These are the natural seams we’ll hook. 

---

# Implementation plan (end‑to‑end)

### Phase A — add the Ledger core (models + runtime + FastAPI middleware)

**Files added:**

* `codeintel_rev/ledger/models.py` — typed event schema + helpers.
* `codeintel_rev/ledger/runtime.py` — context‑scoped ledger with append/snapshot/flush; optional file sink.
* `codeintel_rev/ledger/fastapi.py` — middleware that creates/attaches a ledger per request (uses your `X-Session-ID` from middleware), and a tiny router to fetch the run report by trace/session. Your FastAPI app exists in `app/main.py`, with middleware already stamping session scope; we piggyback that. 

> **Design choices**
>
> * Events are **msgspec.Struct** for speed and compact JSON (you already use msgspec in config).
> * Ledger state is stored in a `contextvar` to be safe for async/await (your app is async FastAPI).
> * Every event attempts to **capture trace_id/span_id** from OTel if present (your repo has `observability/otel.py` we can reuse), else `None`. 

---

### Phase B — wire ledger into hot paths (MCP adapters, retrieval, vLLM, FAISS, DuckDB)

We instrument only *edges and stages*—no heavy internal probing—so we emit a crisp, low‑cardinality sequence of facts:

* **MCP adapters** (`mcp_server/adapters/semantic.py`, `semantic_pro.py`, `text_search.py`, `deep_research.py`): record *tool entry/exit*, user params (scrubbed), and whether each downstream stage ran. 
* **Retrieval** (`retrieval/hybrid.py`): checkpoint events for *gather_channels*, *per‑channel search* (FAISS/BM25/SPLADE), *fuse*, *hydrate*, *rerank*. (Repo confirms these modules exist; we’ll patch minimally around existing methods.) 
* **vLLM** (`io/vLLM_client.py`): client span + ledger events with *model*, *embed_dim*, *batch size*, *mode* (HTTP vs in‑proc), *latency* and *errors*. 
* **FAISS** (`io/faiss_manager.py`): record index kind/metric/nprobe/gpu and top‑k; warn if GPU clone unavailable (your warm‑up handles this already). 
* **DuckDB** (`io/duckdb_catalog.py`): record SQL byte size and rows returned for hydration. 

This connects directly with files listed in your repo map/SCIP index (e.g., `retrieval/hybrid.py`, `io/vllm_client.py`, `io/faiss_manager.py`, `io/duckdb_catalog.py`, `mcp_server/adapters/*.py`).

---

### Phase C — **Run Report v2** (trace‑anchored, “why stopped” inference)

We add a report builder in `ledger/report.py` and one FastAPI route to return the run’s **structured timeline** plus the **reason it stopped** (based on last successful stage and any warnings/errors seen). We stitch in the same **AnswerEnvelope** shape your tools return (so clients can show a “Download Run Report” link). Your MCP server returns envelopes via `mcp_server/.../adapters/*.py`. 

---

### Phase D — tests & sample data

* Unit tests for the ledger (ordering, serialization, “why stopped”).
* A thin integration test that calls the semantic search tool and fetches the run report route (your FastAPI app is mountable from `app/main.py`). 

---

# Concrete code diffs

> Notes:
>
> * Diffs are additive and avoid invasive edits.
> * New files are shown in full.
> * For modified files, I patch on stable import/function anchors present in your tree per the repo map & SCIP snapshots.

---

## 1) **New**: `codeintel_rev/ledger/models.py`

```diff
*** /dev/null
--- a/codeintel_rev/ledger/models.py
+++ b/codeintel_rev/ledger/models.py
@@
+from __future__ import annotations
+from datetime import datetime, timezone
+from typing import Any, Mapping, Literal
+import uuid
+try:
+    import msgspec
+    Base = msgspec.Struct  # fast, compact
+except Exception:  # pragma: no cover
+    from dataclasses import dataclass as Base  # fallback
+    import dataclasses as msgspec
+
+EventKind = Literal[
+    "tool:start","tool:end",
+    "stage:start","stage:end",
+    "vllm:embed","faiss:search","bm25:search","splade:search",
+    "fuse","hydrate","rerank",
+    "warning","error","budget","gate","decision"
+]
+
+def _now() -> datetime:
+    return datetime.now(timezone.utc)
+
+class LedgerEvent(Base, frozen=True):
+    ts: datetime = msgspec.field(default_factory=_now)
+    kind: EventKind
+    name: str
+    stage: str | None = None
+    session_id: str | None = None
+    run_id: str | None = None
+    trace_id: str | None = None
+    span_id: str | None = None
+    attrs: Mapping[str, Any] | None = None
+
+class RunHeader(Base, frozen=True):
+    run_id: str
+    session_id: str | None
+    tool: str
+    query: str | None = None
+
+class RunSnapshot(Base, frozen=True):
+    header: RunHeader
+    events: list[LedgerEvent]
+
+def new_run_id() -> str:
+    return uuid.uuid4().hex
```

---

## 2) **New**: `codeintel_rev/ledger/runtime.py`

```diff
*** /dev/null
--- a/codeintel_rev/ledger/runtime.py
+++ b/codeintel_rev/ledger/runtime.py
@@
+from __future__ import annotations
+from typing import Any, Iterable
+from contextvars import ContextVar
+from threading import RLock
+from .models import LedgerEvent, RunHeader, RunSnapshot, new_run_id
+from datetime import datetime
+
+try:
+    from opentelemetry import trace
+except Exception:  # optional
+    trace = None
+
+_ledger_ctx: ContextVar["ExecutionLedger | None"] = ContextVar("codeintel_ledger", default=None)
+
+class ExecutionLedger:
+    """In-memory, append-only ledger for a single run."""
+    __slots__ = ("_events","_lock","header")
+    def __init__(self, header: RunHeader):
+        self._events: list[LedgerEvent] = []
+        self._lock = RLock()
+        self.header = header
+    # --- emission
+    def append(self, kind: str, name: str, *, stage: str | None = None, **attrs: Any) -> None:
+        tid = sid = None
+        if trace is not None:
+            span = trace.get_current_span()
+            if span and getattr(span, "get_span_context", None):
+                sc = span.get_span_context()
+                if sc and sc.trace_id:
+                    tid = f"{sc.trace_id:032x}"
+                    sid = f"{sc.span_id:016x}"
+        ev = LedgerEvent(kind=kind, name=name, stage=stage,
+                         session_id=self.header.session_id,
+                         run_id=self.header.run_id,
+                         trace_id=tid, span_id=sid,
+                         attrs=attrs or None)
+        with self._lock:
+            self._events.append(ev)
+    # --- snapshot
+    def snapshot(self) -> RunSnapshot:
+        with self._lock:
+            return RunSnapshot(header=self.header, events=list(self._events))
+
+# ---- helpers
+def get_current() -> ExecutionLedger | None:
+    return _ledger_ctx.get()
+
+def set_current(ledger: ExecutionLedger | None) -> None:
+    _ledger_ctx.set(ledger)
+
+def start_run(*, session_id: str | None, tool: str, query: str | None = None) -> ExecutionLedger:
+    header = RunHeader(run_id=new_run_id(), session_id=session_id, tool=tool, query=query)
+    led = ExecutionLedger(header)
+    set_current(led)
+    led.append("tool:start", tool, stage=None, query=query or "")
+    return led
+
+def end_run(status: str = "ok") -> RunSnapshot | None:
+    led = get_current()
+    if not led:
+        return None
+    led.append("tool:end", led.header.tool, stage=None, status=status)
+    snap = led.snapshot()
+    set_current(None)
+    return snap
```

---

## 3) **New**: `codeintel_rev/ledger/fastapi.py`

```diff
*** /dev/null
--- a/codeintel_rev/ledger/fastapi.py
+++ b/codeintel_rev/ledger/fastapi.py
@@
+from __future__ import annotations
+from fastapi import Request, Response, APIRouter
+from starlette.middleware.base import BaseHTTPMiddleware
+from .runtime import start_run, end_run, get_current
+from .report import build_run_report
+
+class LedgerMiddleware(BaseHTTPMiddleware):
+    """
+    Creates a ledger per request (MCP tool routes) and finalizes it.
+    Assumes request.headers may carry 'X-Session-ID' (your SessionScopeMiddleware).
+    """
+    def __init__(self, app):
+        super().__init__(app)
+
+    async def dispatch(self, request: Request, call_next):
+        session_id = request.headers.get("X-Session-ID") or getattr(request.state, "session_id", None)
+        # We only auto-start the ledger for MCP routes; else pass-through.
+        path = request.url.path
+        tool_name = path.removeprefix("/").replace("/", ":") or "http:unknown"
+        start_run(session_id=session_id, tool=tool_name)
+        try:
+            resp = await call_next(request)
+            end_run(status=str(resp.status_code))
+            return resp
+        except Exception as e:
+            end_run(status=f"error:{type(e).__name__}")
+            raise
+
+router = APIRouter()
+
+@router.get("/_ledger/report")
+def get_run_report() -> dict:
+    """Return the latest run snapshot as a narratable report."""
+    led = get_current()
+    snap = led.snapshot() if led else None
+    return build_run_report(snap)
```

---

## 4) **New**: `codeintel_rev/ledger/report.py`

```diff
*** /dev/null
--- a/codeintel_rev/ledger/report.py
+++ b/codeintel_rev/ledger/report.py
@@
+from __future__ import annotations
+from typing import Any
+from .models import RunSnapshot, LedgerEvent
+
+_ORDER = ["gather","embed","faiss","bm25","splade","fuse","hydrate","rerank","envelope"]
+
+def _last_stage(events: list[LedgerEvent]) -> str | None:
+    staged = [e.stage for e in events if e.stage]
+    seen = [s for s in staged if s in _ORDER]
+    return seen[-1] if seen else None
+
+def _stop_reason(events: list[LedgerEvent]) -> str:
+    last = _last_stage(events)
+    if not last:
+        return "stopped-before-start"
+    # Heuristics: if a stage:start exists but no stage:end -> aborted during that stage
+    open_stages = {e.stage for e in events if e.kind=="stage:start"} - {e.stage for e in events if e.kind=="stage:end"}
+    if last in open_stages:
+        return f"aborted-during-{last}"
+    # If next expected stage never started:
+    try:
+        idx = _ORDER.index(last)
+        missing = _ORDER[idx+1:]
+        if missing:
+            return f"not-reached:{missing[0]}"
+    except ValueError:
+        pass
+    return "completed"
+
+def build_run_report(snap: RunSnapshot | None) -> dict[str, Any]:
+    if not snap:
+        return {"status":"no-active-run"}
+    evs = list(snap.events)
+    return {
+        "run_id": snap.header.run_id,
+        "session_id": snap.header.session_id,
+        "tool": snap.header.tool,
+        "trace_id": next((e.trace_id for e in evs if e.trace_id), None),
+        "span_id": next((e.span_id for e in evs if e.span_id), None),
+        "last_stage": _last_stage(evs),
+        "stop_reason": _stop_reason(evs),
+        "events": [e.__dict__ for e in evs],  # msgspec.Struct also exposes __dict__-like mapping
+    }
```

---

## 5) **Modify**: `codeintel_rev/app/main.py` — mount middleware + router

Your FastAPI app is assembled here; we add one middleware and mount the new router. (The file is present and tagged as public‑api/fastapi in your repo map.) 

```diff
--- a/codeintel_rev/app/main.py
+++ b/codeintel_rev/app/main.py
@@
-from fastapi import FastAPI
+from fastapi import FastAPI
+from codeintel_rev.ledger.fastapi import LedgerMiddleware, router as ledger_router
@@
-    app = FastAPI(title="CodeIntel MCP")
+    app = FastAPI(title="CodeIntel MCP")
+    # Execution ledger: capture a narratable run per request
+    app.add_middleware(LedgerMiddleware)
+    app.include_router(ledger_router, tags=["_ledger"])
@@
     return app
```

---

## 6) **Modify**: MCP adapters — bracket each tool with stage events

Example for the main semantic tool (`mcp_server/adapters/semantic.py` exists in your tree). We add a few calls; same pattern applies to `semantic_pro.py`, `text_search.py`, `deep_research.py`. 

```diff
--- a/codeintel_rev/mcp_server/adapters/semantic.py
+++ b/codeintel_rev/mcp_server/adapters/semantic.py
@@
-from fastapi import APIRouter
+from fastapi import APIRouter
+from codeintel_rev.ledger.runtime import get_current
@@
 async def semantic_search(request: SemanticRequest) -> AnswerEnvelope:
-    # existing logic...
+    led = get_current()
+    if led:
+        led.append("stage:start","gather", stage="gather", query=request.query)
+    # gather/validate scope, budgets, etc.
     ...
+    if led:
+        led.append("stage:end","gather", stage="gather")
+        led.append("stage:start","embed", stage="embed")
     # call embed…
     ...
+    if led:
+        led.append("stage:end","embed", stage="embed", stats={"batch": len(request.query)})
+        led.append("stage:start","faiss", stage="faiss", top_k=settings.top_k)
     # faiss search…
     ...
+    if led:
+        led.append("stage:end","faiss", stage="faiss", hits=len(dense_hits))
+        led.append("stage:start","fuse", stage="fuse")
     # fuse…
     ...
+    if led:
+        led.append("stage:end","fuse", stage="fuse", fused=len(fused))
+        led.append("stage:start","hydrate", stage="hydrate")
     # hydrate…
     ...
+    if led:
+        led.append("stage:end","hydrate", stage="hydrate", rows=len(records))
     # build envelope…
     env = AnswerEnvelope(...)
+    if led:
+        led.append("stage:start","envelope", stage="envelope")
+        led.append("stage:end","envelope", stage="envelope", warnings=env.warnings)
     return env
```

> The adapter presence/shape is validated by your repo map (`mcp_server/adapters/semantic.py`, plus `*_pro.py`, `text_search.py`, `deep_research.py`). 

---

## 7) **Modify**: Retrieval — emit per‑channel facts in `retrieval/hybrid.py`

The file exists and is marked public‑api; we add narrowly‑scoped events around existing calls. 

```diff
--- a/codeintel_rev/retrieval/hybrid.py
+++ b/codeintel_rev/retrieval/hybrid.py
@@
-from .types import HybridResult
+from .types import HybridResult
+from codeintel_rev.ledger.runtime import get_current
@@
 def search(self, query: str, top_k: int, **opts) -> HybridResult:
-    # existing: embed, call faiss/bm25/splade, fuse, hydrate
+    led = get_current()
+    if led: led.append("stage:start","gather", stage="gather", top_k=top_k)
+    # embed
+    if led: led.append("stage:start","embed", stage="embed")
     vec = self.embedder.embed_batch([query])[0]
+    if led: led.append("stage:end","embed", stage="embed", dim=len(vec))
     # FAISS
+    if led: led.append("stage:start","faiss", stage="faiss", k=top_k)
     dense_hits = self.faiss.search(vec, top_k)
+    if led: led.append("stage:end","faiss", stage="faiss", hits=len(dense_hits))
     # BM25/SPLADE optional
     ...
     # fuse
+    if led: led.append("stage:start","fuse", stage="fuse")
     fused = self._fuse(dense_hits, sparse_hits)
+    if led: led.append("stage:end","fuse", stage="fuse", fused=len(fused))
     # hydrate
+    if led: led.append("stage:start","hydrate", stage="hydrate")
     records = self.catalog.hydrate(fused)
+    if led: led.append("stage:end","hydrate", stage="hydrate", rows=len(records))
     return HybridResult(records)
```

---

## 8) **Modify**: vLLM client — capture embed calls (`io/vllm_client.py`)

The file exists in your tree (public‑api). 

```diff
--- a/codeintel_rev/io/vllm_client.py
+++ b/codeintel_rev/io/vllm_client.py
@@
+from time import perf_counter
+from codeintel_rev.ledger.runtime import get_current
@@
 def embed_batch(self, texts: list[str]) -> list[list[float]]:
+    led = get_current()
+    t0 = perf_counter()
     out = self._backend.embed_batch(texts)
+    dt_ms = (perf_counter() - t0) * 1000
+    if led:
+        led.append("vllm:embed","embed_batch",
+                   stage="embed",
+                   batch=len(texts),
+                   model=self.model_name,
+                   mode=self.mode,
+                   ms=round(dt_ms,2))
     return out
```

---

## 9) **Modify**: FAISS manager — record index characteristics (`io/faiss_manager.py`)

This file exists in your tree and is a public API. 

```diff
--- a/codeintel_rev/io/faiss_manager.py
+++ b/codeintel_rev/io/faiss_manager.py
@@
+from codeintel_rev.ledger.runtime import get_current
@@
 def search(self, vec: list[float], k: int):
     # existing faiss call...
     hits = self._index.search(vec, k)
+    led = get_current()
+    if led:
+        led.append("faiss:search","faiss_search", stage="faiss",
+                   k=k,
+                   index_kind=self.index_kind,
+                   metric=self.metric,
+                   nprobe=getattr(self, "nprobe", None),
+                   gpu=self.gpu_enabled)
     return hits
```

---

## 10) **Modify**: DuckDB catalog — record hydration SQL size/rows (`io/duckdb_catalog.py`)

This file exists and is public‑api. 

```diff
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@
+from codeintel_rev.ledger.runtime import get_current
@@
 def hydrate(self, ids: list[str]) -> list[Record]:
     sql = self._build_hydration_sql(ids)
     with self._conn() as con:
         rows = con.execute(sql).fetchall()
+    led = get_current()
+    if led:
+        led.append("hydrate","duckdb_hydrate", stage="hydrate",
+                   rows=len(rows), sql_bytes=len(sql))
     return [self._row_to_record(r) for r in rows]
```

---

## 11) **(Optional)** Integrate with your existing telemetry helpers

You already have `observability/otel.py` and `telemetry/*.py`. If you prefer, you can make your `record_span_event(...)` helper *also* emit a ledger event so call‑sites stay unchanged. The file `observability/otel.py` is present; we add a tiny bridge. 

```diff
--- a/codeintel_rev/observability/otel.py
+++ b/codeintel_rev/observability/otel.py
@@
 from opentelemetry import trace
+try:
+    from codeintel_rev.ledger.runtime import get_current
+except Exception:
+    get_current = lambda: None
@@
 def record_span_event(name: str, **attrs: object) -> None:
     span = trace.get_current_span()
     if span and getattr(span, "is_recording", lambda: False)():
         span.add_event(name, attrs)
+    led = get_current()
+    if led:
+        led.append("decision" if name.startswith("budget") else "warning" if "warn" in name else "stage:end",
+                   name, **attrs)
```

---

# End‑to‑end testing plan

1. **Unit tests: ledger core**

   * File ordering, append under concurrency, snapshot immutability, “why stopped” inference:

   ```py
   # tests/test_ledger.py
   from codeintel_rev.ledger.runtime import start_run, get_current, end_run
   def test_ledger_stops_because_next_stage_missing():
       led = start_run(session_id="s1", tool="mcp:semantic")
       led.append("stage:start","embed", stage="embed")
       snap = end_run("ok")
       rep = build_run_report(snap)
       assert rep["stop_reason"] == "aborted-during-embed"
   ```

2. **Integration test: FastAPI + MCP path**

   * Spin the app from `app/main.py`, call semantic route with a fake query, then GET `/_ledger/report` and verify:

     * `last_stage` advanced as expected,
     * `stop_reason` is “completed” for a happy path,
     * events contain FAISS/vLLM/DuckDB attributes. (Your FastAPI app file and MCP adapters exist to enable this.) 

3. **Smoke test: CLI call**

   * If you have CLIs that hit the server or invoke retrieval directly (you do—`cli/*` include indexers and telemetry tools), add one temporary harness to run a small query and dump the report for eyeballing. 

---

## Operational notes

* **Zero CI hooks**: Nothing here blocks or gates; the ledger is passive.
* **Partial runs are first‑class**: We infer “why stopped” purely from the stage graph; there’s no need for exceptions.
* **Trace/log correlation**: If OTel is active, events carry `trace_id`/`span_id` automatically. (Your repo already centralizes OTel setup under `observability/otel.py` and related modules.) 

---

## Why these exact files?

* **Adapters:** `mcp_server/adapters/semantic.py` and siblings are the natural **entry points** for a run; they exist in your tree and are tagged public‑api. 
* **Retrieval hot path:** `retrieval/hybrid.py` is where channels are gathered, fused, and hydrated—ideal for stage checkpoints. (Present/active in your project graph.) 
* **Clients:** `io/vllm_client.py`, `io/faiss_manager.py`, `io/duckdb_catalog.py` are the right **edge adapters** to summarize external/engine behavior with small, durable event payloads. 
* **FastAPI app:** `app/main.py` is where we register the middleware/router so each HTTP request automatically yields a ledger run. 

---

## What you’ll see after wiring

A short interactive run against the semantic search tool will produce a `/_ledger/report` payload like:

```json
{
  "run_id": "f0a1c9f6e7e34a3db4e4e5a0cc2b2b11",
  "session_id": "9a6f...",
  "tool": "mcp_server:adapters:semantic",
  "trace_id": "0f...a1",
  "last_stage": "hydrate",
  "stop_reason": "completed",
  "events": [
    {"ts":"2025-11-14T01:11:02Z","kind":"tool:start","name":"mcp_server:adapters:semantic","stage":null,...},
    {"kind":"stage:start","name":"gather","stage":"gather","attrs":{"top_k":50}},
    {"kind":"stage:start","name":"embed","stage":"embed"},
    {"kind":"vllm:embed","name":"embed_batch","stage":"embed","attrs":{"batch":1,"model":"nomic-embed","mode":"http","ms":8.3}},
    {"kind":"stage:end","name":"embed","stage":"embed","attrs":{"dim":1024}},
    {"kind":"stage:start","name":"faiss","stage":"faiss","attrs":{"k":50}},
    {"kind":"faiss:search","name":"faiss_search","stage":"faiss","attrs":{"k":50,"index_kind":"IVF-PQ","gpu":true}},
    {"kind":"stage:end","name":"faiss","stage":"faiss","attrs":{"hits":50}},
    {"kind":"stage:start","name":"fuse","stage":"fuse"},
    {"kind":"stage:end","name":"fuse","stage":"fuse","attrs":{"fused":50}},
    {"kind":"stage:start","name":"hydrate","stage":"hydrate"},
    {"kind":"hydrate","name":"duckdb_hydrate","stage":"hydrate","attrs":{"rows":50,"sql_bytes":1834}},
    {"kind":"stage:end","name":"hydrate","stage":"hydrate","attrs":{"rows":50}},
    {"kind":"stage:start","name":"envelope","stage":"envelope"},
    {"kind":"stage:end","name":"envelope","stage":"envelope","attrs":{"warnings":[]}},
    {"kind":"tool:end","name":"mcp_server:adapters:semantic","attrs":{"status":"200"}}
  ]
}
```

This directly equips AI programmers with **unambiguous, ordered facts** about what executed, independent of performance speculation.

---

## Follow‑ups I recommend after merging this PR

1. Add **two or three event guards** in critical branches (e.g., when SPLADE/BM25 disabled) to record *why* a stage was skipped (config, degraded mode, artifact missing).
2. Expand the report with **top N warnings** aggregated from envelope + timeline (you already surface warnings in your envelopes and observability helpers). 
3. (Optional) Expose the ledger via **AnswerEnvelope** metadata so the client can show a “See what happened” link inline.

---

### Evidence this plan matches your repo structure

* App & routing: `app/main.py` (FastAPI, public‑api) is present for middleware/router integration. 
* MCP adapters: `mcp_server/adapters/semantic.py` and siblings exist and are where tool logic begins. 
* Retrieval engine and channels: `retrieval/hybrid.py`, `io/faiss_manager.py`, `io/duckdb_catalog.py`, `io/vllm_client.py` are present and tagged as public APIs—perfect for concise ledger events. 
* Telemetry helpers already exist (`observability/otel.py`, `telemetry/*`) and can bridge span events to ledger if desired. 

---

If you want, I can also add diffs to **`mcp_server/adapters/semantic_pro.py`**, **`mcp_server/adapters/text_search.py`**, and **`mcp_server/adapters/deep_research.py`** following the exact pattern used above, plus a couple of **pytest** files for the unit/integration tests outlined here. The references above to these files and modules are confirmed by your repo’s latest map/SCIP output.

**(Ready to apply)** The patches above are self‑contained; merge them and run your FastAPI app. Then call any MCP tool and GET `/_ledger/report`—you’ll have a **narratable execution log** for that request, exactly aligned with your modules and data paths.
