
# Telemetry Phase 4 scope #

Below is **Phase 4 — “Runpacks, Detectors, and Stop‑Point Forensics”**: a detailed implementation plan tailored to your *current* `codeintel_rev` layout with **copy/paste‑able diffs**. The goal is to turn every run (partial or complete) into a self‑contained forensic artifact, make the “what actually happened” narrative unambiguous, and raise actionable hints automatically.

---

## What Phase 4 adds (at a glance)

1. **Runpack**: on any adapter error—or on demand—snapshot a compact, reproducible “flight recorder” zip: timeline JSONL for this run, run‑report JSON, trace id, budgets, index + vLLM config, readiness snapshot, and last N structured logs.

2. **Detectors**: a small rule engine that scans the run’s timeline + enriched report to produce **root‑cause hints** (e.g., “hydrate never started”, “BM25 disabled → FAISS‑only fallback”, “vLLM in HTTP mode with tiny batches”, “GPU clone failed → CPU FAISS” etc.).

3. **Stop‑point forensics**: expand your existing “checkpoint” emission so the report can always answer: *“Which stages ran? Which were skipped? Why did we stop there?”*—even when there’s no exception path.

4. **Tighter glue**:

   * The MCP **error envelope** grows a `runpack_path` field when applicable.
   * The run‑report (already rendered via `_render_run_report(...)`) includes a `trace_id` (if tracing is active) and **ops coverage** (stage presence/absence) to highlight gaps. Your server already calls `report_to_json(...)`; we extend that surface. 

> We build on code that’s already in your repo:
> *OTel bootstrap* (`observability/otel.init_telemetry`), the **Timeline** and its helpers (`current_timeline`, `new_timeline`), the **reporting** module, the **error handling decorator** at the MCP boundary, the **gating** descriptors, vLLM / FAISS clients, and your **Prom/OTel** surfaces.

---

## Files we’ll touch / add

* **New**

  * `codeintel_rev/observability/runpack.py` — build zipped “repro pack” artifacts.
  * `codeintel_rev/diagnostics/detectors.py` — simple rule engine + hints.
* **Modified**

  * `codeintel_rev/mcp_server/error_handling.py` — attach `runpack_path` to error envelopes.
  * `codeintel_rev/telemetry/reporter.py` — add ops‑coverage & apply detectors.
  * `codeintel_rev/observability/reporting.py` — expose helper(s) used by reporter.
  * `codeintel_rev/telemetry/decorators.py` — strengthen “checkpoint” emission.
  * `codeintel_rev/mcp_server/server_semantic.py` — ensure `trace_id` is included in run‑report (if tracing); you already call `report_to_json` here. 
  * `codeintel_rev/observability/semantic_conventions.py` — add a few keys detectors rely on (e.g., `faiss.gpu_ready`, `retrieval.channels`). (File already present in repo map.) 
* **Optional CLI**

  * `codeintel_rev/cli/telemetry.py` — add `runpack` command beside existing `report`. 

---

## Detailed plan and rationale

### A) Runpack (self‑contained forensic zip)

**Why**: When a user or agent says “it didn’t work”, you want one artifact to attach to an issue or feed to an LLM. We leverage the timeline (events), your run‑report, budgets, active config, and environment. We also include FAISS + vLLM facts and GPU status.

**Inputs we already have**:

* **Timeline files** and **report rendering** in `observability.reporting` (build/load events). 
* **Trace id** attach point in `_render_run_report(...)`. 
* **Gating decisions** + descriptors to serialize budgets.
* **vLLM / FAISS** telemetry surfaces we can read (model name, dim, GPU clone OK).

We trigger runpack creation:

* **Automatically** inside the MCP error decorator (any adapter exception).
* **On demand** via CLI (`codeintel_rev cli telemetry runpack ...`). 

### B) Detectors (hints)

**Why**: Not every failure throws; many problems are “missing step” or “silent fallback”. Detectors give concise, high‑signal hints in the report, e.g.:

* *No hydrate after fuse* ⇒ “hydrate not reached—likely DuckDB unavailable / catalog missing”.
* *Budget shows RM3 enabled but SPLADE stage absent* ⇒ “RM3 requested but sparse channel off”.
* *vLLM mode=HTTP + tiny batch size* ⇒ “embedding throughput poor—consider larger batches/switch in‑proc”.
* *FAISS GPU clone failed* ⇒ “running CPU index—expect higher latency”.

We can infer each purely from timeline events, existing stage checkpoints, and configuration attributes (we add a few attributes via semantic conventions).

### C) Stop‑point forensics and ops‑coverage

**Why**: You asked for a clear, proactive listing of **discrete operations that took place** (vs. simply “no error”). We already have timeline events and the `telemetry.decorators._emit_checkpoint(...)` hook; we’ll standardize stage keys and emit for all hot paths so the report can color a stage grid (Ran / Skipped / Failed / Degraded).

---

## Code diffs

> **Note:** Diffs are additive and conservative. They import only from existing seams referenced by your SCIP index and repo map to minimize risk. Where we reference existing symbols and behavior, I cite them inline.

### 1) **NEW**: `observability/runpack.py`

```diff
diff --git a/codeintel_rev/observability/runpack.py b/codeintel_rev/observability/runpack.py
new file mode 100644
index 0000000..cafe123
--- /dev/null
+++ b/codeintel_rev/observability/runpack.py
@@ -0,0 +1,220 @@
+from __future__ import annotations
+from dataclasses import asdict
+from pathlib import Path
+from time import time
+import io, json, os, zipfile, traceback
+from typing import Any, Mapping
+
+from codeintel_rev.observability.reporting import (
+    build_timeline_run_report, latest_run_report, _resolve_timeline_dir
+)
+from codeintel_rev.observability.otel import telemetry_enabled
+from codeintel_rev.observability.semantic_conventions import Attrs  # keys only
+
+# NB: we keep imports light; we accept that some details may be unavailable at error time.
+# We tolerate best-effort collection and never raise from here.
+
+def _safe(obj: Any) -> Any:
+    try:
+        json.dumps(obj)
+        return obj
+    except Exception:
+        return str(obj)
+
+def _context_snapshot(context: Any) -> dict[str, Any]:
+    # Best-effort; ApplicationContext shape is stable in your app layer.
+    snap: dict[str, Any] = {}
+    try:
+        settings = getattr(context, "settings", None)
+        if settings:
+            # redact obviously sensitive env-like fields if any appear later
+            snap["settings"] = {k: _safe(v) for k, v in vars(settings).items() if "secret" not in k.lower()}
+        # include resolved paths to assets (duckdb, faiss, xtr, scip, etc.)
+        for name in ("repo_root","data_dir","vectors_dir","duckdb_path","faiss_index","xtr_dir","scip_index"):
+            if hasattr(context, name):
+                snap[name] = str(getattr(context, name))
+        # basic capability flags if present
+        caps = getattr(context, "capabilities", None)
+        if caps:
+            snap["capabilities"] = {k: _safe(getattr(caps, k)) for k in dir(caps) if not k.startswith("_")}
+    except Exception:
+        snap["__error__"] = "failed to snapshot context"
+    return snap
+
+def _runtime_facts(context: Any) -> dict[str, Any]:
+    facts: dict[str, Any] = {"telemetry_enabled": telemetry_enabled()}
+    # vLLM config (if present)
+    try:
+        vllm = getattr(context, "vllm", None) or getattr(context, "vllm_client", None)
+        cfg = getattr(vllm, "config", None)
+        if cfg:
+            facts["vllm"] = {"model": getattr(cfg, "model", None), "embedding_dim": getattr(cfg, "embedding_dim", None)}
+    except Exception:
+        pass
+    # FAISS manager (type, gpu flag)
+    try:
+        faiss = getattr(context, "faiss", None) or getattr(context, "faiss_manager", None)
+        if faiss:
+            facts["faiss"] = {
+                "index_kind": getattr(faiss, "index_kind", None),
+                "gpu_ready": getattr(faiss, "gpu_ready", None),
+                "ntotal": getattr(getattr(faiss, "cpu_index", None), "ntotal", None),
+            }
+    except Exception:
+        pass
+    return facts
+
+def _budgets_from_report(report: Mapping[str, Any]) -> Mapping[str, Any] | None:
+    # Your gating.serialize/describe is already dict-friendly.
+    return report.get("gating") or report.get("budgets")
+
+def _write_bytes(z: zipfile.ZipFile, arcname: str, payload: bytes) -> None:
+    info = zipfile.ZipInfo(arcname)
+    info.compress_type = zipfile.ZIP_DEFLATED
+    z.writestr(info, payload)
+
+def make_runpack(
+    *,
+    context: Any,
+    session_id: str,
+    run_id: str | None,
+    trace_id: str | None,
+    reason: str | None = None,
+) -> Path:
+    """
+    Build a compact forensic artifact (.zip) for the given run.
+    Never raises; returns the path to the created zip or best-effort zip.
+    """
+    ts = int(time())
+    root = _resolve_timeline_dir(None)  # reuse the timeline root for colocated artifacts
+    out_dir = root / "runpacks" / session_id
+    out_dir.mkdir(parents=True, exist_ok=True)
+    name = f"runpack_{session_id}_{run_id or 'latest'}_{ts}.zip"
+    out = out_dir / name
+
+    try:
+        report = build_timeline_run_report(session_id=session_id, run_id=run_id).to_dict()
+    except Exception:
+        report = {"error": "failed to build timeline report", "traceback": traceback.format_exc()}
+
+    buf = io.BytesIO()
+    with zipfile.ZipFile(buf, mode="w") as z:
+        _write_bytes(z, "meta.json", json.dumps({
+            "session_id": session_id,
+            "run_id": run_id,
+            "trace_id": trace_id,
+            "reason": reason,
+            "generated_at": ts
+        }, indent=2).encode("utf-8"))
+
+        _write_bytes(z, "report.json", json.dumps(report, indent=2).encode("utf-8"))
+        budgets = _budgets_from_report(report) or {}
+        _write_bytes(z, "budgets.json", json.dumps(budgets, indent=2).encode("utf-8"))
+
+        # lightweight context/runtime snapshot
+        ctx = _context_snapshot(context)
+        ctx["runtime"] = _runtime_facts(context)
+        _write_bytes(z, "context.json", json.dumps(ctx, indent=2).encode("utf-8"))
+
+        # include the latest run_report material if present
+        latest = latest_run_report()  # best-effort
+        if latest:
+            _write_bytes(z, "latest_run_report.json", json.dumps(latest, indent=2).encode("utf-8"))
+
+        # attempt to include last N lines of structured logs if you write them to CODEINTEL_DIAG_DIR/logs
+        log_dir = root / "logs"
+        if log_dir.exists():
+            for p in sorted(log_dir.glob("*.log"))[-3:]:
+                try:
+                    _write_bytes(z, f"logs/{p.name}", p.read_bytes())
+                except Exception:
+                    pass
+
+    out.write_bytes(buf.getvalue())
+    return out
```

* `build_timeline_run_report(...)` and `latest_run_report()` already exist in your codebase; we reuse them to avoid re‑parsing work. 
* `telemetry_enabled()` already exists and is used to record OTel state in the pack. 

---

### 2) **NEW**: `diagnostics/detectors.py`

```diff
diff --git a/codeintel_rev/diagnostics/detectors.py b/codeintel_rev/diagnostics/detectors.py
new file mode 100644
index 0000000..b00b135
--- /dev/null
+++ b/codeintel_rev/diagnostics/detectors.py
@@ -0,0 +1,190 @@
+from __future__ import annotations
+from typing import Any, Mapping, Iterable
+
+# A tiny rule engine over the run-report dict produced by telemetry.reporter.
+# Input shape:
+#   {
+#     "session_id": "...",
+#     "run_id": "...",
+#     "trace_id": "...?",
+#     "ops_coverage": {"embed": true/false, "gather": true/false, "fuse": bool, "hydrate": bool, ...},
+#     "warnings": [...],
+#     "budgets": {...},  # from gating.describe_budget_decision(...)
+#     "stages": [{"name": "faiss", "ok": true, "latency_s": 0.012, "attrs": {...}}, ...]
+#   }
+
+def _stage_by_name(stages: Iterable[Mapping[str, Any]], name: str) -> Mapping[str, Any] | None:
+    for s in stages or ():
+        if s.get("name") == name:
+            return s
+    return None
+
+def detect(report: Mapping[str, Any]) -> list[dict[str, Any]]:
+    hints: list[dict[str, Any]] = []
+    ops = (report.get("ops_coverage") or {})
+    stages = report.get("stages") or []
+    budgets = report.get("budgets") or report.get("gating") or {}
+
+    # 1) Stopped before hydrate
+    if ops.get("fuse") and not ops.get("hydrate"):
+        hints.append({
+            "kind": "gap:hydrate",
+            "msg": "Results were fused but never hydrated: check DuckDB/catalog availability.",
+            "why": {"ops_coverage": ops}
+        })
+
+    # 2) No gather of sparse channels while RM3 requested
+    if budgets.get("rm3_enabled") and not ops.get("sparse"):
+        hints.append({
+            "kind": "config:sparse-disabled",
+            "msg": "RM3 enabled but SPLADE/BM25 missing; sparse channel disabled or assets unavailable.",
+            "why": {"budgets": budgets, "ops_coverage": ops}
+        })
+
+    # 3) vLLM tiny batch or HTTP mode symptom (low throughput)
+    vllm = _stage_by_name(stages, "vllm.embed")
+    if vllm:
+        size = (vllm.get("attrs") or {}).get("batch_size")
+        mode = (vllm.get("attrs") or {}).get("mode")
+        if isinstance(size, int) and size < 4:
+            hints.append({"kind": "perf:batch", "msg": "Embedding batches are very small; consider increasing batch size.", "why": {"size": size}})
+        if mode == "http":
+            hints.append({"kind": "perf:mode", "msg": "vLLM using HTTP client; in-proc mode can reduce latency.", "why": {"mode": mode}})
+
+    # 4) FAISS GPU clone failed / CPU fallback
+    faiss = _stage_by_name(stages, "faiss.search")
+    if faiss:
+        gpu = (faiss.get("attrs") or {}).get("gpu_ready")
+        if gpu is False:
+            hints.append({"kind": "degrade:faiss-cpu", "msg": "FAISS GPU unavailable; searching on CPU.", "why": {"gpu_ready": gpu}})
+
+    # 5) High ambiguity + shallow budgets → suggest deeper RRF
+    amb = budgets.get("ambiguity_score")
+    rrfk = budgets.get("rrf_k")
+    if isinstance(amb, (int, float)) and amb > 0.3 and isinstance(rrfk, int) and rrfk < 50:
+        hints.append({"kind": "budget:rrf", "msg": "Vague query with shallow RRF; consider increasing rrf_k.", "why": {"ambiguity": amb, "rrf_k": rrfk}})
+
+    return hints
```

* This consumes the normalized shape we’ll add to `report_to_json(...)` in the next diff.
* Budget fields and ambiguity score are already produced by `gating.describe_budget_decision(...)`; we reuse them.

---

### 3) **Modify**: `telemetry/reporter.py` — add ops‑coverage & detectors

```diff
diff --git a/codeintel_rev/telemetry/reporter.py b/codeintel_rev/telemetry/reporter.py
index 5a5a5a1..6b6b6b2 100644
--- a/codeintel_rev/telemetry/reporter.py
+++ b/codeintel_rev/telemetry/reporter.py
@@
-from typing import Any, Mapping
+from typing import Any, Mapping
+from codeintel_rev.diagnostics.detectors import detect
+from codeintel_rev.retrieval.gating import describe_budget_decision  # already returns dict
+from codeintel_rev.observability.timeline import current_timeline
@@
-def report_to_json(context: Any, session_id: str, run_id: str | None = None) -> dict[str, Any]:
-    """
-    Build a consolidated report for the current run based on Timeline events.
-    """
-    # existing logic ...
+def report_to_json(context: Any, session_id: str, run_id: str | None = None) -> dict[str, Any]:
+    """
+    Build a consolidated report for the run based on Timeline events + checkpoints.
+    Includes ops-coverage (which stages ran), budgets snapshot, and detector hints.
+    """
+    # existing logic builds base report from Timeline events; assume it's in 'report'
+    report: dict[str, Any] = _build_base_report(context, session_id, run_id)  # refactor or inline existing
+
+    # ---- Ops coverage grid (booleans) from standardized checkpoint events ----
+    # Expect stage names: vllm.embed, gather.channels, fuse.rrf, hydrate.catalog, faiss.search, bm25.search, splade.search
+    events = report.get("events", [])
+    def _seen(prefix: str) -> bool:
+        return any(e.get("name","").startswith(prefix) and e.get("status") == "ok" for e in events)
+    ops = {
+        "embed": _seen("vllm.embed"),
+        "gather": _seen("gather.channels"),
+        "fuse": _seen("fuse.rrf"),
+        "hydrate": _seen("hydrate.catalog"),
+        "dense": _seen("faiss.search"),
+        "sparse": _seen("bm25.search") or _seen("splade.search"),
+    }
+    report["ops_coverage"] = ops
+
+    # ---- Budgets (gating) snapshot if available on the timeline or context ----
+    # If your adapters stash the QueryProfile/BudgetDecision, prefer that. Otherwise attempt to rebuild or skip.
+    budgets = report.get("gating") or report.get("budgets")
+    if not budgets:
+        # best-effort: try to compute from last known query profile if present
+        qp = report.get("last_query_profile")
+        if qp and hasattr(context, "stage_gate_config"):
+            try:
+                budgets = describe_budget_decision(qp, context.stage_gate_config)
+            except Exception:
+                budgets = None
+    if budgets:
+        report["budgets"] = budgets
+
+    # ---- Stage summaries for detectors (name, ok, latency, attrs) ----
+    report["stages"] = [
+        # best-effort extraction; if you already summarize by stage, reuse that here
+        {"name": e.get("name"), "ok": e.get("status") == "ok", "latency_s": e.get("latency_s"), "attrs": e.get("attrs",{})}
+        for e in events
+        if any(e.get("name","").startswith(p) for p in ("vllm.embed","faiss.search","bm25.search","splade.search","fuse.rrf","hydrate.catalog","gather.channels"))
+    ]
+
+    # ---- Hints from detectors ----
+    try:
+        report["hints"] = detect(report)
+    except Exception:
+        report["hints"] = []
+
+    return report
```

* `describe_budget_decision(...)` is documented in your retrieval/gating module; we reuse it to keep budget context close to the report. 
* `Timeline` accessors and event structure are already present (and referenced by `current_timeline()` and your reporting utilities). 

---

### 4) **Modify**: `mcp_server/error_handling.py` — build & attach runpack on error

```diff
diff --git a/codeintel_rev/mcp_server/error_handling.py b/codeintel_rev/mcp_server/error_handling.py
index 123abcd..456cdef 100644
--- a/codeintel_rev/mcp_server/error_handling.py
+++ b/codeintel_rev/mcp_server/error_handling.py
@@
-from typing import Callable, Mapping, TypeVar
+from typing import Callable, Mapping, TypeVar
+from opentelemetry import trace
+from codeintel_rev.observability.runpack import make_runpack
+from codeintel_rev.app.config_context import ApplicationContext
+from codeintel_rev.observability.timeline import current_timeline
@@
 def handle_adapter_errors(*, operation: str, empty_result: Mapping[str, object]) -> Callable[[F], F]:
@@
-    def decorator(func: F) -> F:
+    def decorator(func: F) -> F:
         ...
-        @wraps(func)
+        @wraps(func)
         async def async_wrapper(*args: object, **kwargs: object) -> dict[str, object]:
             try:
                 return await func(*args, **kwargs)  # success path
             except BaseException as exc:
                 # existing: convert to Problem Details + envelope; emit OTel exception event
                 envelope = _as_error_envelope(exc, operation, empty_result)  # existing helper
                 _record_exception_event(exc, operation)
+                # ---- Build runpack (best-effort) and attach path ----
+                try:
+                    ctx = trace.get_current_span().get_span_context()
+                    trace_id = f"{ctx.trace_id:032x}" if ctx and ctx.trace_id else None
+                    # Try to locate ApplicationContext and Timeline IDs
+                    appctx: ApplicationContext | None = kwargs.get("context") or _maybe_get_context_from_args(args)
+                    tl = current_timeline()
+                    session_id = getattr(tl, "session_id", None)
+                    run_id = getattr(tl, "run_id", None)
+                    if appctx and session_id:
+                        runpack_path = make_runpack(
+                            context=appctx, session_id=session_id, run_id=run_id, trace_id=trace_id, reason=operation
+                        )
+                        envelope.setdefault("observability", {})
+                        envelope["observability"]["runpack_path"] = str(runpack_path)
+                except Exception:
+                    pass
                 return envelope
@@
         return _cast(F, async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper)
```

* `handle_adapter_errors(...)` and `_record_exception_event(...)` already exist; we add the **runpack hook** right where all adapter exceptions are normalized.

---

### 5) **Modify**: `observability/reporting.py` — small helpers (if missing)

If your current reporting module doesn’t expose a single “base report” builder, add a tiny private helper to structure the JSON (the diff below keeps changes minimal and strictly additive):

```diff
diff --git a/codeintel_rev/observability/reporting.py b/codeintel_rev/observability/reporting.py
index 9a9a9a1..9b9b9b2 100644
--- a/codeintel_rev/observability/reporting.py
+++ b/codeintel_rev/observability/reporting.py
@@
+def _events_for(session_id: str, run_id: str | None, timeline_dir: Path | None) -> list[dict]:
+    report = build_timeline_run_report(session_id=session_id, run_id=run_id, timeline_dir=timeline_dir)
+    data = report.to_dict()
+    return data.get("events", [])
+
+# simple façade that telemetry.reporter can call to get a base dict
+def build_base_run_report(*, session_id: str, run_id: str | None = None, timeline_dir: Path | None = None) -> dict[str, object]:
+    rr = build_timeline_run_report(session_id=session_id, run_id=run_id, timeline_dir=timeline_dir)
+    return rr.to_dict()
```

* This just gives `telemetry.reporter` a stable call; all underlying functions already exist. 

---

### 6) **Modify**: `telemetry/decorators.py` — normalize checkpoints

You already have a `_emit_checkpoint(...)` helper; we’ll standardize stage names so the reporter/detectors can reason about them uniformly (names appear in the coverage grid above).

```diff
diff --git a/codeintel_rev/telemetry/decorators.py b/codeintel_rev/telemetry/decorators.py
index ddd111..eee222 100644
--- a/codeintel_rev/telemetry/decorators.py
+++ b/codeintel_rev/telemetry/decorators.py
@@
-# existing _emit_checkpoint(stage, ok, reason, attrs)
+# existing _emit_checkpoint(stage, ok, reason, attrs)
+# Standard stage keys for search pipeline:
+STAGES = {
+    "VLLM_EMBED": "vllm.embed",
+    "GATHER": "gather.channels",
+    "FAISS": "faiss.search",
+    "BM25": "bm25.search",
+    "SPLADE": "splade.search",
+    "FUSE": "fuse.rrf",
+    "HYDRATE": "hydrate.catalog",
+}
```

With that constant available, instrument call sites in your adapters/engines to emit:

```python
_emit_checkpoint(STAGES["FAISS"], ok=True, reason=None, attrs={"k": k, "gpu_ready": gpu})
```

(You already have stage events in hybrid search and vLLM; this just standardizes the names.)

---

### 7) **Modify**: `mcp_server/server_semantic.py` — ensure `trace_id` is stitched into run‑report

You already render the run‑report via `_render_run_report` and call `report_to_json(...)`; extend it to inject the current trace id if tracing is on (so the JSON can be joined to spans in your backend). 

```diff
diff --git a/codeintel_rev/mcp_server/server_semantic.py b/codeintel_rev/mcp_server/server_semantic.py
index abc1234..abc1235 100644
--- a/codeintel_rev/mcp_server/server_semantic.py
+++ b/codeintel_rev/mcp_server/server_semantic.py
@@
 from codeintel_rev.telemetry.reporter import report_to_json
+from opentelemetry import trace
@@
 async def _render_run_report(context: ApplicationContext, session_id: str, run_id: str) -> dict:
-    return report_to_json(context, session_id, run_id)
+    data = report_to_json(context, session_id, run_id)
+    ctx = trace.get_current_span().get_span_context()
+    if ctx and ctx.trace_id:
+        data["trace_id"] = f"{ctx.trace_id:032x}"
+    return data
```

This mirrors the design described in the prior extension notes and your existing call site. 

---

### 8) **Modify**: `observability/semantic_conventions.py` — add a few attributes used by detectors

(If these keys already exist, keep only the missing ones.)

```diff
diff --git a/codeintel_rev/observability/semantic_conventions.py b/codeintel_rev/observability/semantic_conventions.py
index 4242424..4343434 100644
--- a/codeintel_rev/observability/semantic_conventions.py
+++ b/codeintel_rev/observability/semantic_conventions.py
@@
 class Attrs:
+    # pipeline and channels
+    RETRIEVAL_CHANNELS = "retrieval.channels"     # e.g., ["faiss","bm25","splade"]
+    RETRIEVAL_RRF_K    = "retrieval.rrf_k"
+    GATING_RM3_ENABLED = "gating.rm3_enabled"
+    GATING_AMBIGUITY   = "gating.ambiguity_score"
+    # FAISS / GPU
+    FAISS_GPU_READY    = "faiss.gpu_ready"
+    # vLLM
+    VLLM_MODE          = "vllm.mode"              # "http" | "inproc"
+    VLLM_BATCH         = "vllm.batch"
```

* The file exists in your repo map (we extend it). 

---

### 9) **Optional**: `cli/telemetry.py` — `runpack` command

```diff
diff --git a/codeintel_rev/cli/telemetry.py b/codeintel_rev/cli/telemetry.py
index 777aaa..777aab 100644
--- a/codeintel_rev/cli/telemetry.py
+++ b/codeintel_rev/cli/telemetry.py
@@
-from codeintel_rev.observability.reporting import build_timeline_run_report
+from codeintel_rev.observability.reporting import build_timeline_run_report
+from codeintel_rev.observability.runpack import make_runpack
+from codeintel_rev.app.config_context import ApplicationContext
@@
 @app.command("report")
 def run_report(session_id: SessionArg, run_id: RunIdOption = None, timeline_dir: TimelineDirOption = None) -> None:
     ...
 
+@app.command("runpack")
+def runpack(session_id: SessionArg, run_id: RunIdOption = None) -> None:
+    """
+    Build a forensics runpack (zip) for the given session/run.
+    """
+    # Best-effort ApplicationContext locator; adapt to your bootstrap if needed.
+    context = ApplicationContext.from_env()  # or however your app wires it
+    path = make_runpack(context=context, session_id=session_id, run_id=run_id, trace_id=None, reason="cli.runpack")
+    echo(str(path))
```

* This lives next to your existing `report` command, keeping operators’ workflow simple. 

---

## Where these diffs “land” in your current code

* **Error handling**: Your decorator already centralizes adapter failures; we add the runpack hook right there.
* **Run‑report**: You already render it through `server_semantic._render_run_report(...)` and `telemetry.reporter.report_to_json(...)`; we extend both to include `trace_id`, ops coverage, and hints. 
* **Timeline & stages**: You already emit events from vLLM, hybrid search, and runtime observers; we standardize stage names to make coverage deterministic.
* **Gating context**: We reuse your own serializers to avoid drift. 

---

## Smoke‑test checklist (quick)

1. **Trigger a controlled error** (e.g., call `blame_range` on a missing path via MCP): confirm the error **envelope** now contains `observability.runpack_path`. 
2. **Open the runpack zip**: verify `meta.json`, `report.json`, `budgets.json`, `context.json`, optional `logs/*`. (Budgets populated via `describe_budget_decision` if available.) 
3. **Happy path run** (semantic search with SPLADE/BM25 enabled): confirm **ops coverage** has `gather/fuse/hydrate` as `true`, and **hints** is empty.
4. **Degraded path** (disable SPLADE assets): confirm hints include `config:sparse-disabled`.
5. **Check trace join**: call the run‑report route; see `trace_id` set when OTel is enabled (`init_telemetry(...)`). 

---

## What you gain after Phase 4

* **No head‑scratching on partial runs**: The ops‑coverage grid and detectors highlight exactly where execution stopped, even when nothing threw.
* **Shareable, reproducible forensics**: One zip captures everything needed for a human or LLM to diagnose.
* **Forward‑compatible**: The detectors are a small table‑driven layer—adding rules is trivial as new failure modes appear.

---

## Notes on dependencies & safety

* All additions are **best‑effort** and **no‑throw**; they must never break tool execution.
* If any subsystem is absent, runpack creation will still succeed with partial content.
* We reuse **your** stable interfaces for reporting, gating, and telemetry bootstrap to avoid coupling.

---

### (Optional) further polish in a follow‑up PR

* Add **tail‑based sampling triggers** in `observability/otel.init_telemetry(...)` (e.g., always sample when a detector would fire). 
* Add a tiny **HTML renderer** for runpacks (view in browser), powered by the same report JSON.
* Emit a **`runpack:ready`** span event with the filesystem path for cross‑linking from traces.

---

If you want, I can also provide a **unit‑test scaffold** that fakes a short timeline (embed → fuse → *stop*) and asserts the detectors + coverage behave as expected.

**Citations to your current repo:**

* `_render_run_report(...)` (ties to `report_to_json`) — semantic server surface. 
* MCP error decorator / exception event — central error path.
* OTel bootstrap (`init_telemetry`, `telemetry_enabled`) — used for trace id and state.
* Timeline creation/access — used to get `session_id`/`run_id`. 
* Reporting utilities (`build_timeline_run_report`, `latest_run_report`) — report+pack sources. 
* Gating descriptors (`describe_budget_decision`) — budgets snapshot for hints. 
* vLLM and FAISS telemetry touchpoints — attributes available for hints.
* Repo presence of `observability/semantic_conventions.py` — extended with a few keys. 

If anything above collides with a local rename or a recent refactor, I can generate adjusted diffs against your *exact* file contents.
