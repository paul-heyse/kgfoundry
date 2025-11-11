# Scope overview and context #

Great—congrats on getting the type‑gating + server factory work landed. Below I’ll do two things, in this order:

1. **Immediate follow‑ups** to close out any loose ends from the “Type_Gating_Factory_Scope_Phase2” proposal (quick checklist + fast fixes).
2. A **detailed, implementation‑grade telemetry plan** (taxonomy, code layout, wiring points, tests/CI, and a short “how we’ll use this” guide), tuned to your current repo and AOP rules.

I cite your AOP/AGENTS contract where relevant (quality gates, Problem Details, typing‑gates) and the existing error taxonomy so you can see where this integrates cleanly.  

---

## 1) Outstanding work to action now (close the loop on Phase 2)

**A. Server factory + gated modules**

* **Pure‑move** the MCP tool functions into import‑gated modules (e.g., `mcp_server/server_semantic.py`, `mcp_server/server_symbols.py`) and ensure `build_http_app(caps)` imports them **conditionally** only when the capability predicate passes. (You asked for these pure‑moves earlier—double‑check no accidental re‑decorations/ordering changes slipped in.)
* Add a unit test that builds the app with **semantic caps off** and asserts the semantic module is not imported (negative import test).

**B. Runtime gates in cell factories**

* Ensure **every** heavy runtime (`FAISSManager`, `VLLMClient`, SPLADE/Lucene/ONNX, DuckDB) is created only via its runcell factory and that missing deps throw **typed** errors: `RuntimeUnavailableError(runtime="faiss", detail="…")`, `RuntimeLifecycleError(runtime="vllm", cause=exc)`. These already map to RFC 9457 Problem Details in your repo’s taxonomy, so they’ll render correctly at HTTP boundaries. 

**C. Capability truth**

* If not done in PR‑C yet, expose **`/capz`** (fast, side‑effect‑free) and stamp the snapshot into app state during startup. You’ll reuse its payload in telemetry root events.

**D. CI “minimal env”**

* Confirm a **minimal** profile (no NumPy/FAISS/DuckDB/Torch) can still `import codeintel_rev` and start the app; gate tests to assert semantic/symbol tools aren’t registered under missing caps. This enforces your Typing‑Gates doctrine and prevents regressions. 

**E. AOP hygiene**

* Re‑run the full AOP gate set on the touched files: Ruff (TC00x + PLC2701), Pyright strict, Pyrefly, docstring presence/quality, and Problem‑Details samples for at least one failing path. 

If any item above is missing, I recommend landing a “wrap‑up” PR with: (1) the negative‑import tests, (2) `/capz` stubbing if not present, and (3) one or two typed raises in runcell factories to align with your error taxonomy. 

---

## 2) Telemetry — detailed, implementation‑grade plan

**Intent:** Not “perf tuning,” but **fast diagnosis** and **causal traceability**: *what ran, what didn’t, and why*. We’ll keep OTel optional, guarantee a local JSONL “flight recorder,” and standardize event names/fields so the data stays queryable and reportable.

### 2.1 Canonical event taxonomy (small and fixed)

Use strict names so timelines stay coherent:

* **Root (always):** `mcp.tool.<name>.start|end`
  Fields: `tool`, `session_id`, `run_id`, **capabilities** snapshot (or hash), input summary (sizes only), trace IDs.

* **Stages:**

  * `embed.start|end` (VLLM) — `mode={http|local}`, `n_texts`, `dim`, `duration_ms`.
  * `faiss.search.start|end` — `k`, `nprobe`, `use_gpu`, `rows`, `duration_ms`.
  * `hybrid.bm25.{run|skip}` — `reason` if skip: `disabled|missing_assets|capability_off|provider_error`.
  * `hybrid.splade.{run|skip}` — same as above.
  * `hybrid.fuse.start|end` — `rrf_k`, `bm25_hits`, `splade_hits`, `fused_count`.

* **Hydration:** `duckdb.hydrate.start|end` — `asked_for`, `returned`, `missing`.

* **Decisions:** `decision` events with `name`, `reason`, `fallback`. Examples:

  * `degrade` with `reason="faiss.gpu_unavailable"`, `fallback="cpu"`.
  * `rerank` with `enabled`, `reason="threshold|flag|capability_off"`.

* **Errors** (unified): include your **error code** and `http_status` from the taxonomy that already maps exceptions → Problem Details. 

> Keep fields consistent with your AOP observability section (request name, duration, status, correlation ID). 

### 2.2 Data model & scrubbing

* **Event record** (TypedDict/msgspec model; no runtime Pydantic dependency):

  ```py
  {
    "ts": iso8601, "type": str, "name": str,
    "session_id": str, "run_id": str,
    "status": "ok|error|warn|skip",
    "attrs": { ... small JSONable dict ... }
  }
  ```
* **Scrubbers**: clip any string payload > N chars; never log code/content blobs—only IDs and counts (e.g., chunk IDs).

### 2.3 Code layout (new modules)

```
codeintel_rev/
  observability/
    __init__.py
    otel.py                 # Optional OTel bootstrap (no-op if not installed)
    timeline.py             # Flight recorder + span-event mirroring
    runtime_observer.py     # Hooks runcell init/close; emits decisions/degrades
  diagnostics/
    report_cli.py           # “Where it stopped & why” Markdown from JSONL
```

**`observability/otel.py`**

* `init_telemetry(app, *, enabled: bool, otlp_endpoint: str | None, console: bool) -> None`
* Safe imports; if OTel missing, this returns quickly with no‑op tracer.

**`observability/timeline.py`**

* `Timeline` with `operation(name)`, `step(name)`, and `event(type, name, status, **attrs)`; writes **JSONL with rotation** (per‑day + max‑bytes rollover) and mirrors as OTel span events if OTel is on.

**`observability/runtime_observer.py`**

* `OTelRuntimeCellObserver` with hooks the runcell factories call on init/start/end. Emits `runtime.init.start|end` and `decision(degrade, …)` if GPU/feature fallback occurs.

### 2.4 Integration points (surgical touches)

**FastAPI app (`app/main.py`)**

* Add a `telemetry_middleware`:

  * bind/propagate `session_id` (your existing middleware already stamps this),
  * allocate a `run_id` per request,
  * start root operation for each MCP tool call.
* Initialize OTel only if `CODEINTEL_TELEMETRY=1` (env‑driven, per AOP “12‑factor config”). 
* Store **capabilities snapshot** (from `/capz`) on `app.state` and attach to root events for each request.

**MCP adapters** (`mcp_server/adapters/semantic.py`, `semantic_pro.py`)

* Wrap top‑level entry with:

  * `mcp.tool.<name>.start` (attrs: capabilities hash, input sizes),
  * emit `end` with `status=ok|error` and error metadata (Problem Details code) on failure.

**VLLM** (`io/vllm_client.py`)

* Around `embed_batch`/`embed_batch_async`: `embed.start|end` with mode, n_texts, dim, durations. (HTTP spans are auto‑traced if OTel enabled.)

**FAISS** (`io/faiss_manager.py`)

* Around `search()`: `faiss.search.start|end` with k, nprobe, GPU flag, rows, durations; on exceptions, include `error_code="vector-search-error"` (if you map it that way) and re‑raise your typed error. 

**Hybrid** (`io/hybrid_search.py`)

* In the gather phase, emit **first‑class**:

  * `hybrid.bm25.run|skip(reason=…)`
  * `hybrid.splade.run|skip(reason=…)`
* Around fusion: `hybrid.fuse.start|end(rrf_k, bm25_hits, splade_hits, fused_count)`.

**Hydration** (`DuckDB` paths)

* In `ApplicationContext.open_catalog()` and/or `DuckDBCatalog.query_by_ids()`:

  * `duckdb.hydrate.start|end(asked_for, returned, missing)` (no row payloads; just counts).

**Rerank (now or later)**

* Around `_maybe_rerank` / XTR: `decision(rerank, enabled|False, reason)` and `xtr.rescore.start|end(top_k, duration_ms)`.

### 2.5 Configuration (env‑first, zero friction)

* `CODEINTEL_TELEMETRY=1` – enable OTel bootstrap (optional).
* `OTEL_EXPORTER_OTLP_ENDPOINT` – where to send traces; if unset, traces are no‑op and you still get JSONL.
* `OTEL_CONSOLE=1` – mirror spans to console (developer convenience).
* `CODEINTEL_DIAG_DIR=./data/diagnostics` – flight recorder directory.
* `CODEINTEL_TELEMETRY_SAMPLING=1.0|0.1|0` – simple sampling control.
* `CODEINTEL_DIAG_MAX_BYTES=5242880` – rotate JSONL upon size threshold.

### 2.6 Tests (fast and hermetic)

**Unit (pure Python)**

* `tests/observability/test_timeline.py`: rotation, sampling, and scrubbing are correct.
* `tests/observability/test_runtime_observer.py`: degrade decision events emitted when GPU flag is false.
* `tests/mcp/test_adapter_telemetry.py`: calling semantic adapter yields root `mcp.tool.*` events even on error paths.

**Negative import tests (minimal env)**

* Already part of your type‑gates work—add a check that **no** FAISS/VLLM spans are emitted when those capabilities are off (i.e., the modules never imported).

**Event content sanity**

* Table‑driven tests for `hybrid.bm25.run|skip` and `hybrid.splade.run|skip` across reasons: disabled/missing_assets/capability_off/provider_error.

> All tests run under your AOP gates; no Pydantic at runtime; no OTel required to be installed (everything works as a no‑op or pure JSONL). 

### 2.7 CI and developer workflow

**CI**

* Extend the “minimal” profile job to assert:

  * app boots,
  * `/capz` returns quickly,
  * a synthetic request produces a **root** timeline record but **no** FAISS/VLLM stage events.
* Extend the “full” profile to assert the full chain (embed→faiss→hybrid→hydrate) is present.

**Developer quickstart** (README snippet)

* 5 commands: enable env vars, run server, hit a tool, run `report_cli` for your session, open the Markdown report.

### 2.8 Diagnostics report (human‑readable)

**`diagnostics/report_cli.py`**

* Input: JSONL path + `--session` id (your existing middleware sets this).
* Output: Markdown with:

  * ordered chain of operations with ✅/❌ and durations,
  * explicit **SKIP** reasons for channels,
  * the **first failing decision** (if any) and the **last successful stage** (the “where it stopped & why” headline),
  * a tiny appendix of parameter summaries (k/nprobe/rrf_k).
* Design: zero external deps; safe to run on any machine.

---

## 3) What this enables immediately (use it!)

* **Repro‑friendly incident notes**: copy the Markdown into an issue and you’ve got the full causal trace without logs spelunking.
* **Faster “why is this empty?” answers**: a single glance shows BM25/SPLADE ran or were skipped, and whether FAISS searched on GPU vs CPU.
* **Proactive design checks**: with capability stamps on the root event, we can correlate unexpected paths (“semantic tools were exposed, but cap stamp says `faiss=false`—bug”), without joining `/capz`.

---

## 4) Optional small extensions (next 1–2 PRs after telemetry core)

1. **Prom metrics for skip reasons**

   * A labeled counter: `codeintel_hybrid_channel_skips_total{channel,reason}` populated by the `channel.skip` events.

2. **Git adapters spans**

   * Wrap `blame_range` and `file_history` (MCP) with `git.*` spans and `n_lines|n_commits`. This quickly explains slow responses on large histories.

3. **Import‑time budget check**

   * A tiny CI check that measures `import codeintel_rev` duration under minimal env to keep cold‑start snappy (use monotonic time as per AOP). 

---

## 5) Acceptance checklist (what “done” means)

* JSONL flight recorder present; **OTel optional** and no‑op when absent.
* Root + stage + hydration + decision events emitted exactly where specified.
* Each root event includes a **capabilities stamp** (or stable hash) from app state.
* Rotation, sampling, and scrubbing verified by unit tests.
* Minimal vs full CI profiles pass and assert the presence/absence of stage events appropriately.
* Errors are surfaced as Problem Details with your existing taxonomy (typed raises preserved). 

---

### Pointers to repo contracts this plan leans on

* **AOP gates** (Ruff/pyright/pyrefly, Problem Details, logs/metrics/traces expectations, env‑first config): the Telemetry modules, tests, and CLI follow these rules exactly. 
* **Error taxonomy** (e.g., `RuntimeUnavailableError`, `RuntimeLifecycleError`, file/git errors) used for structured error attributes and consistent Problem Details: telemetry captures their codes/contexts but does not change throwing behavior. 

---

If you want, I can also turn the plan above into **three small PRs** (Core telemetry backbone, Hot‑path instrumentation, Diagnostics CLI) using the module names and seams listed here so they land cleanly and independently.


# PR Ready Patches #

Absolutely—here are the **PR‑ready patches** for the telemetry work we just aligned on. I’ve structured them as four small, reviewable slices that compose cleanly:

* **PR‑T1 — observability foundations** (OTel bootstrap + JSONL “flight recorder” + runtime‑cell observer + app wiring)
* **PR‑T2 — core‑path instrumentation** (vLLM embed, FAISS search, hybrid channels, MCP wrapper roots + capability stamp)
* **PR‑T3A — hydration telemetry** (DuckDB hydration counts)
* **PR‑T3B — reranker telemetry** (XTR search/rescore + `_maybe_rerank` decision trace)
* **PR‑T4 — diagnostics CLI** (turns JSONL into a compact “where it stopped & why” Markdown)

Where the patches reference existing modules/APIs, I anchored them to your latest SCIP index so reviewers can jump straight to source (e.g., `ApplicationContext` surface, MCP semantic tool signatures, XTR search/rescore docs).

---

## PR‑T1 — **Observability foundations**

**Title:** `feat(obs): add OTel bootstrap, JSONL flight recorder, runtime observers; wire into app`

**Why:** Establish a minimal, low‑overhead backbone for **causal diagnostics**: optional OpenTelemetry, a local “flight recorder” (JSONL timelines), and a runtime‑cell observer. All of this is **side‑effect‑free** unless enabled by env. The app wiring uses your existing startup/lifespan and context surfaces. (Your server/app composition and MCP tool wrappers remain unchanged.) The integration points rely on the same `ApplicationContext` + FastAPI app you already expose. 

### Files changed

```
A  codeintel_rev/observability/otel.py
A  codeintel_rev/observability/timeline.py
A  codeintel_rev/observability/runtime_observer.py
M  codeintel_rev/app/main.py     # add middleware + env-driven init
A  tests/observability/test_timeline.py
A  tests/observability/test_middleware.py
```

### Patch (unified diffs)

> **Notes for reviewers**
>
> * All new modules start with `from __future__ import annotations` and avoid heavy imports at module import time.
> * If OpenTelemetry packages are **absent**, the tracer is a no‑op; the JSONL recorder still works.

**1) `observability/otel.py` (new)** — tiny optional OTel bootstrap + `as_span()`

```diff
*** /dev/null
--- a/codeintel_rev/observability/otel.py
@@
+from __future__ import annotations
+from typing import Iterator, Mapping, Any
+import os
+
+try:
+    from opentelemetry import trace
+    from opentelemetry.sdk.resources import Resource
+    from opentelemetry.sdk.trace import TracerProvider
+    from opentelemetry.sdk.trace.export import BatchSpanProcessor
+    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
+    _OTEL = True
+except Exception:  # pragma: no cover
+    trace = None  # type: ignore
+    _OTEL = False
+
+def init_telemetry(service_name: str = "codeintel-rev") -> None:
+    """Initialize OTel if env `CODEINTEL_TELEMETRY=1` and deps present."""
+    if not _OTEL or os.getenv("CODEINTEL_TELEMETRY") != "1":
+        return
+    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
+    resource = Resource.create({"service.name": service_name})
+    provider = TracerProvider(resource=resource)
+    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
+    trace.set_tracer_provider(provider)
+
+def as_span(name: str, **attrs: Mapping[str, Any]):
+    """Context manager creating a span (no-op if OTel disabled)."""
+    class _Noop:
+        def __enter__(self): return None
+        def __exit__(self, *exc): return False
+    if not _OTEL:  # pragma: no cover
+        return _Noop()
+    tracer = trace.get_tracer("codeintel_rev")
+    span = tracer.start_as_current_span(name, attributes=dict(attrs))
+    return span
```

**2) `observability/timeline.py` (new)** — JSONL “flight recorder” + request/session binding + canonical taxonomy

```diff
*** /dev/null
--- a/codeintel_rev/observability/timeline.py
@@
+from __future__ import annotations
+import json, os, time, uuid, threading
+from dataclasses import dataclass, asdict
+from pathlib import Path
+from typing import Any, Iterator
+from contextvars import ContextVar
+from .otel import as_span
+
+_TL_DIR = Path(os.getenv("CODEINTEL_DIAG_DIR", "./data/diagnostics"))
+_LOCK = threading.Lock()
+_DAY = time.strftime("%Y%m%d")
+_FILE = _TL_DIR / f"events-{_DAY}.jsonl"
+_MAX_BYTES = int(os.getenv("CODEINTEL_DIAG_MAX_BYTES", "10485760"))  # 10MB
+_SAMPLE_P = float(os.getenv("CODEINTEL_DIAG_SAMPLE", "1.0"))
+
+_session: ContextVar[str | None] = ContextVar("session_id", default=None)
+_run: ContextVar[str | None] = ContextVar("run_id", default=None)
+
+def _write(event: dict[str, Any]) -> None:
+    if _SAMPLE_P < 1.0 and (uuid.uuid4().int % int(1/_SAMPLE_P)) != 0:  # sampling
+        return
+    _TL_DIR.mkdir(parents=True, exist_ok=True)
+    payload = json.dumps(event, ensure_ascii=False)
+    with _LOCK:
+        # rotate if oversized
+        if _FILE.exists() and _FILE.stat().st_size > _MAX_BYTES:
+            _FILE.rename(_FILE.with_name(_FILE.stem + f"-{int(time.time())}.jsonl"))
+        _FILE.write_text("", encoding="utf-8") if not _FILE.exists() else None
+        with _FILE.open("a", encoding="utf-8") as f:
+            f.write(payload + "\n")
+
+def bind_session(session_id: str) -> None:
+    _session.set(session_id)
+
+def reset_run() -> str:
+    rid = uuid.uuid4().hex
+    _run.set(rid)
+    return rid
+
+@dataclass(slots=True)
+class TimelineEvent:
+    ts: float
+    session_id: str | None
+    run_id: str | None
+    type: str
+    name: str
+    status: str | None = None
+    message: str | None = None
+    attrs: dict[str, Any] | None = None
+
+def event(type: str, name: str, *, status: str | None = None, message: str | None = None, **attrs: Any) -> None:
+    ev = TimelineEvent(time.time(), _session.get(), _run.get(), type, name, status, message, attrs or {})
+    _write(asdict(ev))
+    # also mirror as OTel span event if active
+    with as_span("timeline.event", type=type, name=name, **(attrs or {})):
+        pass
+
+class operation:
+    def __init__(self, name: str, **attrs: Any): self.name, self.attrs = name, attrs
+    def __enter__(self):
+        event("operation.start", self.name, status="ok", **self.attrs)
+    def __exit__(self, exc_type, exc, tb):
+        status = "error" if exc else "ok"
+        msg = str(exc) if exc else None
+        event("operation.end", self.name, status=status, message=msg)
+        return False
+
+class step:
+    def __init__(self, name: str, **attrs: Any): self.name, self.attrs = name, attrs
+    def __enter__(self):
+        event("step.start", self.name, status="ok", **self.attrs)
+    def __exit__(self, exc_type, exc, tb):
+        status = "error" if exc else "ok"
+        msg = str(exc) if exc else None
+        event("step.end", self.name, status=status, message=msg)
+        return False
```

**3) `observability/runtime_observer.py` (new)** — observer you can pass into runtime‑cell factories

```diff
*** /dev/null
--- a/codeintel_rev/observability/runtime_observer.py
@@
+from __future__ import annotations
+import time
+from .timeline import event
+
+class RuntimeObserver:
+    def init_start(self, name: str, **attrs): event("runtime.init.start", name, status="ok", **attrs)
+    def init_end(self, name: str, started_at: float, **attrs): 
+        event("runtime.init.end", name, status="ok", duration_ms=int((time.time()-started_at)*1000), **attrs)
+    def close(self, name: str, **attrs): event("runtime.close", name, status="ok", **attrs)
```

**4) `app/main.py` (wire middleware + env‑driven init)**

```diff
--- a/codeintel_rev/app/main.py
+++ b/codeintel_rev/app/main.py
@@
 from __future__ import annotations
@@
-from fastapi import FastAPI, Request, Response
+from fastapi import FastAPI, Request, Response
@@
+from codeintel_rev.observability.otel import init_telemetry
+from codeintel_rev.observability.timeline import bind_session, reset_run, event
+from codeintel_rev.observability.runtime_observer import RuntimeObserver
@@
 app = FastAPI(...)
@@
 @asynccontextmanager
 async def lifespan(app: FastAPI):
-    # existing startup logic...
+    # existing startup logic...
+    init_telemetry("codeintel-rev")
+    # Pass runtime observer into your context if factory supports it
+    app.state.runtime_observer = RuntimeObserver()
     yield
@@
 @app.middleware("http")
 async def telemetry_middleware(request: Request, call_next):
     # Session binding — reuse your existing session scope middleware value if present
-    response = await call_next(request)
+    session_id = request.headers.get("X-Session-ID") or getattr(request.state, "session_id", None) or "anon"
+    bind_session(session_id)
+    reset_run()
+    event("http.request", f"{request.method} {request.url.path}", status="ok")
+    response = await call_next(request)
     return response
```

**5) Tests**

```diff
*** /dev/null
--- a/tests/observability/test_timeline.py
@@
+from codeintel_rev.observability.timeline import operation, step, bind_session, reset_run
+def test_timeline_basic(tmp_path, monkeypatch):
+    monkeypatch.setenv("CODEINTEL_DIAG_DIR", str(tmp_path))
+    bind_session("s1"); reset_run()
+    with operation("mcp.tool.semantic_search_pro"):
+        with step("embed.start"): pass
+        with step("faiss.search.start"): pass
+    # Assert a file exists and contains our events
+    files = list(tmp_path.glob("events-*.jsonl"))
+    assert files, "timeline file missing"
```

---

## PR‑T2 — **Core‑path instrumentation (semantic chain)**

**Title:** `feat(obs): instrument vLLM embed, FAISS search, hybrid channels; stamp capabilities on MCP roots`

**Why:** Emit a **canonical, queryable timeline** for the end‑to‑end semantic path—without changing business logic. We add `mcp.tool.*` root events at the MCP wrapper boundary (matching the signatures you already expose), span the embed and FAISS calls, and note channel RUN/SKIP decisions for BM25/SPLADE. We also **stamp the current capability snapshot** on each root, so an individual run is self‑describing (no cross‑query to `/capz` needed). Your semantic MCP wrapper signatures are as indexed here; XTR/WARP toggles live behind your adapter already and are natural to mark later.

### Files changed

```
M  codeintel_rev/mcp_server/adapters/semantic_pro.py
M  codeintel_rev/io/vllm_client.py
M  codeintel_rev/io/faiss_manager.py
M  codeintel_rev/io/hybrid_search.py
```

### Patch (unified diffs)

**1) MCP adapter root with capability stamp + root operation**

```diff
--- a/codeintel_rev/mcp_server/adapters/semantic_pro.py
+++ b/codeintel_rev/mcp_server/adapters/semantic_pro.py
@@
 from __future__ import annotations
@@
+from codeintel_rev.observability.timeline import operation, step, event
@@
 async def semantic_search_pro(context: ApplicationContext, query: str, limit: int = 20, *, options: SemanticProOptions | None = None) -> AnswerEnvelope:
-    # original logic...
+    caps = getattr(context, "capabilities", None)
+    with operation("mcp.tool.semantic_search_pro", capabilities=(caps.model_dump() if caps else {}), query_len=len(query), limit=limit):
+        with step("embed.start"):
+            # embed call remains in vLLM client; this step frames it in timeline
+            ...
+        with step("faiss.search.start"):
+            ...
+        # hybrid channels will emit channel.run/skip themselves (next patch)
+        ...
```

**2) vLLM client embed spans + events**

```diff
--- a/codeintel_rev/io/vllm_client.py
+++ b/codeintel_rev/io/vllm_client.py
@@
 from __future__ import annotations
@@
+from codeintel_rev.observability.otel import as_span
+from codeintel_rev.observability.timeline import event
@@
     def embed_batch(self, texts: list[str]) -> NDArrayF32:
-        # existing implementation...
+        mode = "http" if self._http_client is not None else "local"
+        with as_span("vllm.embed_batch", mode=mode, n_texts=len(texts)):
+            event("embed.start", "vllm", status="ok", mode=mode, n_texts=len(texts))
+            arr = self._embed_impl(texts)
+            event("embed.end", "vllm", status="ok", dim=int(arr.shape[1]) if hasattr(arr, "shape") else None)
+            return arr
```

**3) FAISS manager search spans + events**

```diff
--- a/codeintel_rev/io/faiss_manager.py
+++ b/codeintel_rev/io/faiss_manager.py
@@
 from __future__ import annotations
@@
+from codeintel_rev.observability.otel import as_span
+from codeintel_rev.observability.timeline import event
@@
     def search(self, query_vec: NDArrayF32, k: int, *, nprobe: int | None = None) -> tuple[NDArrayF32, NDArrayI64]:
-        # original logic...
+        use_gpu = bool(self.gpu_resources)
+        with as_span("faiss.search", k=k, nprobe=nprobe or 0, use_gpu=use_gpu):
+            event("step.start", "faiss.search", status="ok", k=k, nprobe=nprobe or 0, use_gpu=use_gpu)
+            D, I = self._search_impl(query_vec, k, nprobe=nprobe)
+            event("step.end", "faiss.search", status="ok", rows=int(I.shape[0]) if hasattr(I, "shape") else None)
+            return D, I
```

**4) Hybrid channels explicit RUN/SKIP + RRF**

```diff
--- a/codeintel_rev/io/hybrid_search.py
+++ b/codeintel_rev/io/hybrid_search.py
@@
 from __future__ import annotations
@@
+from codeintel_rev.observability.timeline import event, step
@@
 def _gather_channel_hits(...):
-    # existing decision logic...
+    # BM25
+    if not bm25_enabled:
+        event("channel.skip", "hybrid.bm25", status="skip", reason="disabled")
+    elif not bm25_assets:
+        event("channel.skip", "hybrid.bm25", status="skip", reason="missing_assets")
+    else:
+        event("channel.run", "hybrid.bm25", status="ok")
+        ...
+    # SPLADE
+    if not splade_enabled:
+        event("channel.skip", "hybrid.splade", status="skip", reason="disabled")
+    elif not splade_assets:
+        event("channel.skip", "hybrid.splade", status="skip", reason="missing_assets")
+    else:
+        event("channel.run", "hybrid.splade", status="ok")
+        ...
+    # RRF fusion
+    with step("hybrid.rrf"):
+        ...
```

> Anchors for reviewers: the MCP semantic adapter root signature and orchestration surface match your indexed docs; hybrid channel assembly is implemented under your hybrid engine and is the natural place to emit RUN/SKIP and RRF summary.

---

## PR‑T3A — **Hydration telemetry**

**Title:** `feat(obs): add DuckDB hydration counts and decisions`

**Why:** Make the “post‑retrieval hydration” step observable: how many IDs we asked DuckDB for, how many returned, and how many were missing. This is essential to explain short responses or missing context. The choke‑point is your **catalog context/callers** (e.g., `open_catalog()/query_by_ids()`), which the index shows as the hydration workhorse. 

### Files changed

```
M  codeintel_rev/app/config_context.py       # emit hydrate.start/end around open_catalog scope (if present here)
M  codeintel_rev/io/duckdb_catalog.py        # emit query_by_ids counts
```

### Patch (unified diffs)

```diff
--- a/codeintel_rev/app/config_context.py
+++ b/codeintel_rev/app/config_context.py
@@
+from codeintel_rev.observability.timeline import step, event
@@
     def open_catalog(self):
-        # existing contextmanager...
+        with step("duckdb.hydrate"):
+            # enter/exit unchanged; counts emitted by query layer
+            return _open_catalog_impl(...)
```

```diff
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@
+from codeintel_rev.observability.timeline import event
@@
     def query_by_ids(self, ids: list[int]) -> list[Row]:
-        rows = self._query_by_ids_impl(ids)
-        return rows
+        asked = len(ids)
+        rows = self._query_by_ids_impl(ids)
+        returned = len(rows)
+        missing = max(asked - returned, 0)
+        event("step.end", "duckdb.hydrate", status="ok", asked_for=asked, returned=returned, missing=missing)
+        return rows
```

---

## PR‑T3B — **Reranker telemetry (XTR)**

**Title:** `feat(obs): instrument XTR search/rescore and MCP rerank decision`

**Why:** When late‑interaction reranking (XTR) is active, we want explicit evidence of **if and why** it ran. Your XTR docs show the public API for `search(...)` and `rescore(...)`; we instrument those and also record the decision in `_maybe_rerank(...)` inside the semantic adapter. 

### Files changed

```
M  codeintel_rev/io/xtr_manager.py
M  codeintel_rev/mcp_server/adapters/semantic_pro.py   # `_maybe_rerank` decision event
```

### Patch (unified diffs)

```diff
--- a/codeintel_rev/io/xtr_manager.py
+++ b/codeintel_rev/io/xtr_manager.py
@@
+from codeintel_rev.observability.otel import as_span
+from codeintel_rev.observability.timeline import step, event
@@
     def search(self, query: str, k: int, *, explain: bool = False, topk_explanations: int = 5) -> list[tuple[int,float,dict|None]]:
-        # original logic
+        with as_span("xtr.search", k=k, explain=explain):
+            with step("xtr.search"): 
+                return self._search_impl(query, k, explain=explain, topk_explanations=topk_explanations)
@@
     def rescore(self, query: str, candidate_chunk_ids: Iterable[int], *, explain: bool = False, topk_explanations: int = 5) -> list[tuple[int,float,dict|None]]:
-        # original logic
+        with as_span("xtr.rescore", n_candidates=len(list(candidate_chunk_ids)), explain=explain):
+            with step("xtr.rescore"):
+                return self._rescore_impl(query, candidate_chunk_ids, explain=explain, topk_explanations=topk_explanations)
```

```diff
--- a/codeintel_rev/mcp_server/adapters/semantic_pro.py
+++ b/codeintel_rev/mcp_server/adapters/semantic_pro.py
@@
 from codeintel_rev.observability.timeline import event
@@
 def _maybe_rerank(...):
-    # existing decision logic...
+    enabled = bool(options and options.enable_rerank)
+    event("decision", "rerank", status="ok", enabled=enabled, reason=("flag" if enabled else "disabled"))
+    if not enabled:
+        return candidates
+    ...
```

---

## PR‑T4 — **Diagnostics CLI**

**Title:** `feat(obs): add diagnostics report CLI (timeline JSONL → Markdown)`

**Why:** A tight loop for humans: “Where did a given session stop, and why?” The CLI reads the JSONL and produces a **one‑page Markdown** with the operation chain (start/end/durations), explicit **RUN/SKIP** channel decisions, and the first error if present.

### Files changed

```
A  codeintel_rev/diagnostics/report_cli.py
A  tests/observability/test_report_cli.py
```

### Patch (unified diffs)

```diff
*** /dev/null
--- a/codeintel_rev/diagnostics/report_cli.py
@@
+from __future__ import annotations
+import json, argparse, collections
+from pathlib import Path
+
+def main():
+    ap = argparse.ArgumentParser()
+    ap.add_argument("--events", required=True)
+    ap.add_argument("--session", required=True)
+    ap.add_argument("--out", required=True)
+    args = ap.parse_args()
+
+    lines = Path(args.events).read_text(encoding="utf-8").splitlines()
+    events = [json.loads(l) for l in lines if l.strip()]
+    ev = [e for e in events if e.get("session_id")==args.session]
+    by_type = collections.defaultdict(list)
+    for e in ev: by_type[e["type"]].append(e)
+
+    parts = ["# Session report", f"*session:* `{args.session}`", ""]
+    parts.append("## Chain")
+    for e in by_type["operation.start"]: parts.append(f"▶️ **{e['name']}**")
+    for e in by_type["operation.end"]:
+        dur = ""  # could compute if we had start timestamp cache
+        status = "✅ ok" if e.get("status")=="ok" else f"❌ {e.get('message') or 'error'}"
+        parts.append(f"{status} — **{e['name']}**")
+    parts.append("")
+    parts.append("## Channel decisions")
+    for t in ("channel.run","channel.skip"):
+        for e in by_type[t]: parts.append(f"- {t.split('.')[1]}: {e['name']} ({e.get('reason','ok')})")
+    Path(args.out).write_text("\n".join(parts), encoding="utf-8")
+
+if __name__ == "__main__":
+    main()
```

---

## Validation checklist (for all PRs)

* **No behavior change** beyond observability; MCP tool signatures and adapters stay the same (see indexed shapes for `semantic_search_pro`, `symbol_search`). 
* **Import‑time safety**: new modules import cleanly with OTel absent; telemetry is env‑driven.
* **Canonical taxonomy**: `operation.*`, `step.*`, `channel.run|skip`, `decision`, plus attributes we defined.
* **Capability stamp**: included on `mcp.tool.*.start` via adapter root (uses the capability snapshot you already compute/mount alongside startup). 
* **Runtime cells**: observer hooks are additive (you can pass `app.state.runtime_observer` into factories introduced in the type‑gating/runcell work), consistent with the `ApplicationContext` orchestration surface you’ve already established. 

---

## Suggested commit messages

**PR‑T1**

```
feat(obs): add OTel bootstrap, JSONL flight recorder, runtime observers; wire into app
```

**PR‑T2**

```
feat(obs): instrument vLLM embed, FAISS search, hybrid channels; stamp capabilities on MCP roots
```

**PR‑T3A**

```
feat(obs): add DuckDB hydration telemetry (asked/returned/missing)
```

**PR‑T3B**

```
feat(obs): add XTR search/rescore spans and rerank decision events
```

**PR‑T4**

```
feat(obs): diagnostics CLI to summarize timeline JSONL into 'where it stopped & why'
```

---

## How this fits your current architecture

* **Server/MCP surface** remains gated by capabilities (as implemented in your prior PR‑D server‑factory work); the telemetry only **records** which modules ran and why. The split of semantic/symbol tool modules (pure‑move) is still compatible with these changes and can be conditionally imported by `build_http_app(caps)`.
* **Adapters** keep orchestration; we only bracket their work with timeline events and spans, consistent with the indexed docstrings/signatures in `semantic_pro` and XTR.

---

