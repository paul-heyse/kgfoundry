Below is a **Phase‑0 implementation plan** targeted to your current repo layout, followed by **ready‑to‑apply code diffs** (new modules + surgical edits). This leans into *deep diagnostics*, not gating or CI; it produces a consolidated, human‑readable report for partial or complete runs and extends your existing timeline instrumentation across the whole pipeline.

---

## What Phase‑0 delivers (scope, no CI hooks)

**A. Single, coherent “run report.”**
We turn your timeline JSONL stream into a structured report for a given session (and run), with:

* **Operation → step tree** (tools, stages, discrete sub‑steps) with start/stop and durations, plus *where a run stopped and why* (exception, early return, short‑circuit, or client cancel).
* **Decision breadcrumbs** (budgeting, gating, degraded modes) and *what was skipped*.
* **Counts & sizes** (inputs, tokens, hits, hydrated rows) for each step.
* **Method metadata** snapshot (index types, GPU/CPU path, dims, parameters).

You already have the core building blocks: a **timeline** that emits `operation` and `step` events and persists as JSONL with rotation (via `_FlightRecorder.write`), and a CLI that renders events as Markdown reports. Phase‑0 exposes this as a **programmatic service + MCP tool**, and wires the remaining high‑value code paths to emit detailed steps.

**B. Instrumentation coverage (no gating).**
You already instrument MCP tools with `tool_operation_scope(...)` and Hybrid Search steps (channel runs/skips). Phase‑0 fills the gaps:

* **Embeddings:** `VLLMClient.embed_batch` (HTTP + in‑proc) — record mode, batch size, dim, durations, and transport failures (you already emit error events; we add scoped step timing).
* **Stage‑0 dense:** `FAISSManager.search` — record index type (Flat/IVF/IVF‑PQ), GPU/CPU path, k, and effective search knobs (ef_search/nprobe).
* **Catalog hydration:** `DuckDBCatalog.query_by_ids/query_by_filters` — input ids, filter knobs, row count.
* **Late‑interaction (XTR/WARP):** `XTRIndex.encode_query_tokens/search/rescore`, `WarpEngine.rerank` — token counts, dims, candidate sizes, explainability on/off.
* **Budgeting decisions:** ensure `describe_budget_decision(...)` payloads are attached as timeline `decision` events (available today; we standardize their shape).
* **Runtime lifecycle:** your `TimelineRuntimeObserver` + app lifespan already exist; we keep it as the default observer so startup/warmup/readyz events are captured.

**C. Access paths (local‑first).**

* **MCP tool:** `diagnostics.generate_run_report(session_id, run_id?, format=md|json)` returns Markdown (or JSON) report.
* **HTTP route (optional):** `/diag/report/{session_id}` to fetch Markdown; useful when inspecting outside MCP.

> No CI hooks, no gates. All telemetry is **best‑effort** (never breaks the request path) and is **dev‑friendly** for local runs.

---

## Implementation notes (why these patches align with your code today)

* **Timeline API**: `Timeline.event/operation/step(...)` exists; events are persisted to JSONL with rotation via `_FlightRecorder`.
* **MCP surface**: Tools are already wrapped with `tool_operation_scope(...)` and error envelopes via `handle_adapter_errors(...)`.
* **Hybrid/XTR/WARP/DuckDB**: Public docstrings indicate clear seams to record inputs/outputs/sizes and config; we hook timeline steps exactly here.
* **Capabilities snapshot**: Keep using `Capabilities.from_context()` stamp in the report header so readers see *what was available for that run*.

---

## Files added in Phase‑0

```
codeintel_rev/
  diagnostics/
    report_service.py        # load timeline JSONL, assemble → markdown/json report
  mcp_server/adapters/
    diagnostics.py           # MCP tool: diagnostics.generate_run_report(...)
```

## Files edited in Phase‑0

```
codeintel_rev/io/vllm_client.py          # add step-scoped timing around embed_batch()
codeintel_rev/io/faiss_manager.py        # add step-scoped timing in search()
codeintel_rev/io/duckdb_catalog.py       # add step for hydrate.duckdb
codeintel_rev/io/xtr_manager.py          # add steps for encode/search/rescore
codeintel_rev/io/warp_engine.py          # add step for warp.rerank
codeintel_rev/mcp_server/server.py       # register MCP diagnostics tool (no gating)
(codeintel_rev/app/main.py)              # optional: HTTP route /diag/report/{session}
```

---

# Code diffs

> **Note:** Diffs are minimal and defensive. If `current_timeline()` returns `None`, code runs without telemetry. Event attributes are tiny, JSON‑safe, and never include payload contents.

---

### 1) New: `codeintel_rev/diagnostics/report_service.py`

````diff
diff --git a/codeintel_rev/diagnostics/report_service.py b/codeintel_rev/diagnostics/report_service.py
new file mode 100644
index 0000000..e1b3b9a
--- /dev/null
+++ b/codeintel_rev/diagnostics/report_service.py
@@
+from __future__ import annotations
+
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Any, Iterable, Tuple
+import json
+import itertools
+import datetime as dt
+
+# Internal timeline plumbing is already present; we reuse it.
+from codeintel_rev.observability.timeline import _FlightRecorder  # type: ignore
+from codeintel_rev.app.capabilities import Capabilities
+from codeintel_rev.app.config_context import ApplicationContext
+
+@dataclass(frozen=True)
+class RunReport:
+    session_id: str
+    run_id: str | None
+    started_at: str | None
+    finished_at: str | None
+    status: str                     # "ok" | "error" | "incomplete"
+    stop_reason: str | None         # exception class/message, cancel, short-circuit
+    operations: list[dict]          # tree of operations → steps with durations/attrs
+    decisions: list[dict]           # gating/budget decisions
+    warnings: list[dict]            # skips/degraded notes
+    errors: list[dict]              # structured errors (problem details)
+    capabilities: dict              # snapshot for the run
+
+def _events_dir() -> Path:
+    # Reuse the recorder's directory; do not hardcode paths.
+    return _FlightRecorder._current_file().parent  # noqa: SLF001
+
+def _iter_jsonl(paths: Iterable[Path]) -> Iterable[dict]:
+    for p in paths:
+        if not p.exists():
+            continue
+        with p.open("r", encoding="utf-8") as fh:
+            for line in fh:
+                line = line.strip()
+                if not line:
+                    continue
+                try:
+                    yield json.loads(line)
+                except Exception:
+                    # best-effort: ignore malformed lines
+                    continue
+
+def _pick_files_for_session(session_id: str) -> list[Path]:
+    # Read recent files (today ± 2 previous rotations).
+    d = _events_dir()
+    glob = sorted(d.glob("events_*.jsonl"))
+    return glob[-3:] if len(glob) > 3 else glob
+
+def _group_by_run(events: list[dict], session_id: str) -> list[Tuple[str | None, list[dict]]]:
+    # Some runs may not set run_id; group them as None.
+    filtered = [e for e in events if e.get("session_id") == session_id]
+    filtered.sort(key=lambda e: e.get("ts", ""))
+    key = lambda e: e.get("run_id")
+    grouped: list[Tuple[str | None, list[dict]]] = []
+    for run_id, chunk in itertools.groupby(filtered, key=key):
+        grouped.append((run_id, list(chunk)))
+    return grouped
+
+def _summarize_run(run_id: str | None, evs: list[dict], caps: Capabilities) -> RunReport:
+    ops: dict[str, dict] = {}
+    steps: dict[str, dict] = {}
+    decisions: list[dict] = []
+    warnings: list[dict] = []
+    errors: list[dict] = []
+    started_at = None
+    finished_at = None
+    stop_reason: str | None = None
+    status = "incomplete"
+
+    for e in evs:
+        etype = e.get("type")
+        name = e.get("name")
+        ts = e.get("ts")
+        st = e.get("status")
+        attrs = e.get("attrs") or {}
+        msg = e.get("message")
+        if etype == "tool" and st == "start":
+            started_at = started_at or ts
+            ops[name] = {"name": name, "started_at": ts, "finished_at": None, "duration_ms": None,
+                         "attrs": attrs, "steps": []}
+        elif etype == "tool" and st == "end":
+            finished_at = ts
+            if name in ops:
+                ops[name]["finished_at"] = ts
+                ops[name]["duration_ms"] = attrs.get("duration_ms")
+            status = "ok" if status != "error" else status
+        elif etype == "step" and st == "start":
+            steps[name] = {"name": name, "started_at": ts, "finished_at": None,
+                           "duration_ms": None, "attrs": attrs}
+        elif etype == "step" and st == "end":
+            if name in steps:
+                steps[name]["finished_at"] = ts
+                steps[name]["duration_ms"] = attrs.get("duration_ms")
+        elif etype == "decision":
+            decisions.append({"name": name, "ts": ts, "attrs": attrs})
+        elif etype in ("skip", "warning"):
+            warnings.append({"name": name, "ts": ts, "message": msg, "attrs": attrs})
+        elif etype in ("error", "exception"):
+            status = "error"
+            stop_reason = msg or stop_reason
+            errors.append({"name": name, "ts": ts, "message": msg, "attrs": attrs})
+
+    # Attach steps to the sole top-level tool op if present
+    op_list = list(ops.values())
+    if op_list:
+        op_list[0]["steps"] = list(steps.values())
+    finished_at = finished_at or (op_list[0]["finished_at"] if op_list else None)
+
+    return RunReport(
+        session_id=evs[0].get("session_id", ""),
+        run_id=run_id,
+        started_at=started_at,
+        finished_at=finished_at,
+        status=status,
+        stop_reason=stop_reason,
+        operations=op_list,
+        decisions=decisions,
+        warnings=warnings,
+        errors=errors,
+        capabilities=caps.stamp({}),  # lightweight dict stamp
+    )
+
+def build_report(context: ApplicationContext, session_id: str, run_id: str | None = None) -> RunReport | None:
+    files = _pick_files_for_session(session_id)
+    events = list(_iter_jsonl(files))
+    runs = _group_by_run(events, session_id)
+    if not runs:
+        return None
+    chosen: Tuple[str | None, list[dict]]
+    if run_id is None:
+        chosen = runs[-1]
+    else:
+        matches = [r for r in runs if r[0] == run_id]
+        if not matches:
+            return None
+        chosen = matches[-1]
+    caps = Capabilities.from_context(context)
+    return _summarize_run(chosen[0], chosen[1], caps)
+
+def render_markdown(report: RunReport) -> str:
+    def _kv(d: dict[str, Any]) -> str:
+        return "\n".join(f"- **{k}**: `{v}`" for k,v in d.items() if v not in (None, "", [], {}))
+    lines: list[str] = []
+    lines.append(f"# Run report — session `{report.session_id}`  \n")
+    rid = report.run_id or "(no run id)"
+    lines.append(f"*Run:* `{rid}`  \n*Status:* **{report.status}**  ")
+    if report.stop_reason:
+        lines.append(f"\n> Stop reason: {report.stop_reason}\n")
+    lines.append("\n## Capabilities snapshot\n")
+    lines.append("```json\n" + json.dumps(report.capabilities, indent=2) + "\n```\n")
+    if report.operations:
+        op = report.operations[0]
+        lines.append("## Operation\n")
+        lines.append(f"- **name**: `{op['name']}`")
+        lines.append(f"- **started**: {op['started_at']}  \n- **finished**: {op['finished_at']}  \n- **duration_ms**: {op['duration_ms']}")
+        if op["attrs"]:
+            lines.append("\n### Operation attributes\n" + _kv(op["attrs"]) + "\n")
+        if op["steps"]:
+            lines.append("\n### Steps\n")
+            for s in op["steps"]:
+                lines.append(f"#### {s['name']}\n- duration_ms: `{s['duration_ms']}`\n" + _kv(s["attrs"]) + "\n")
+    if report.decisions:
+        lines.append("## Decisions\n")
+        for d in report.decisions:
+            lines.append(f"- `{d['name']}` @ {d['ts']}  \n  " + _kv(d["attrs"]) + "\n")
+    if report.warnings:
+        lines.append("## Warnings / Skips\n")
+        for w in report.warnings:
+            lines.append(f"- `{w['name']}` @ {w['ts']} — {w.get('message','')}  \n  " + _kv(w["attrs"]) + "\n")
+    if report.errors:
+        lines.append("## Errors\n")
+        for err in report.errors:
+            lines.append(f"- `{err['name']}` @ {err['ts']} — {err.get('message','')}  \n  " + _kv(err["attrs"]) + "\n")
+    return "\n".join(lines)
````

**Why here?** Your existing diagnostics CLI already reads JSONL and renders Markdown; this service consolidates that logic for programmatic use by adapters and HTTP routes.

---

### 2) New MCP tool: `codeintel_rev/mcp_server/adapters/diagnostics.py`

```diff
diff --git a/codeintel_rev/mcp_server/adapters/diagnostics.py b/codeintel_rev/mcp_server/adapters/diagnostics.py
new file mode 100644
index 0000000..f2a53ef
--- /dev/null
+++ b/codeintel_rev/mcp_server/adapters/diagnostics.py
@@
+from __future__ import annotations
+
+from typing import Literal
+from fastmcp import mcp
+
+from codeintel_rev.mcp_server.server import get_context, mcp as _mcp
+from codeintel_rev.mcp_server.error_handling import handle_adapter_errors
+from codeintel_rev.mcp_server.telemetry import tool_operation_scope
+from codeintel_rev.diagnostics.report_service import build_report, render_markdown
+
+@_mcp.tool()
+@handle_adapter_errors(operation="diagnostics:generate_run_report", empty_result={"markdown": "", "json": {}})
+def generate_run_report(session_id: str, run_id: str | None = None, fmt: Literal["md","json"] = "md") -> dict:
+    """
+    Generate a consolidated run report for a session (optionally a specific run_id).
+    Returns Markdown (`fmt="md"`) or JSON (`fmt="json"`).
+    """
+    ctx = get_context()
+    with tool_operation_scope("diagnostics.generate_run_report", session_id=session_id, run_id=run_id, fmt=fmt):
+        report = build_report(ctx, session_id, run_id)
+        if report is None:
+            return {"markdown": "", "json": {}, "error": "No events for session/run"}
+        if fmt == "json":
+            return {"json": report.__dict__, "markdown": ""}
+        return {"markdown": render_markdown(report), "json": {}}
```

*Why this shape?* Mirrors your other adapters (decorated with `@mcp.tool()` and `@handle_adapter_errors(...)`) and emits operation‑scoped telemetry via `tool_operation_scope(...)`.

---

### 3) Register the tool: `codeintel_rev/mcp_server/server.py`

```diff
diff --git a/codeintel_rev/mcp_server/server.py b/codeintel_rev/mcp_server/server.py
@@
-from codeintel_rev.mcp_server.telemetry import tool_operation_scope
+from codeintel_rev.mcp_server.telemetry import tool_operation_scope
+from codeintel_rev.mcp_server.adapters.diagnostics import generate_run_report
@@
 # (existing tools)
 # ...
+# Diagnostics / reporting (no gating)
+# FastMCP discovers it via decorator; no extra wrapper needed.
+# generate_run_report(session_id, run_id?, fmt)
```

This piggybacks your existing adapter registration pattern; decorators do the heavy lifting.

---

### 4) Deeper coverage: `codeintel_rev/io/vllm_client.py` (embed timings)

```diff
diff --git a/codeintel_rev/io/vllm_client.py b/codeintel_rev/io/vllm_client.py
@@
 from typing import Sequence
+from codeintel_rev.observability.timeline import current_timeline
@@ class VLLMClient:
     def embed_batch(self, texts: Sequence[str]) -> NDArrayF32:
-        if self._local_engine is not None:
-            vecs = self._local_engine.embed_batch(texts)
-            return vecs
-        try:
-            return self._embed_batch_http(texts)
-        except Exception as exc:
-            tl = current_timeline()
-            if tl:
-                tl.event("error", "embed.vllm", status="exception",
-                         message=str(exc),
-                         attrs={"mode": "http", "n_texts": len(texts)})
-            raise
+        tl = current_timeline()
+        mode = "local" if self._local_engine is not None else "http"
+        if tl:
+            with tl.step("embed.vllm", mode=mode, n_texts=len(texts)):
+                return self._embed_impl(texts)
+        # no timeline available: do the work directly
+        return self._embed_impl(texts)
+
+    def _embed_impl(self, texts: Sequence[str]) -> NDArrayF32:
+        if self._local_engine is not None:
+            return self._local_engine.embed_batch(texts)
+        try:
+            return self._embed_batch_http(texts)
+        except Exception as exc:
+            tl = current_timeline()
+            if tl:
+                tl.event("error", "embed.vllm", status="exception",
+                         message=str(exc),
+                         attrs={"mode": "http", "n_texts": len(texts)})
+            raise
```

*Rationale:* you already record errors; the added `step(...)` yields consistent start/stop + duration for embedding batches.

---

### 5) Deeper coverage: `codeintel_rev/io/faiss_manager.py` (search timings)

```diff
diff --git a/codeintel_rev/io/faiss_manager.py b/codeintel_rev/io/faiss_manager.py
@@
 from typing import Sequence
+from codeintel_rev.observability.timeline import current_timeline
@@ class FAISSManager:
-    def search(self, vector: NDArrayF32, k: int) -> list[tuple[int, float]]:
-        # ... existing code ...
-        return results
+    def search(self, vector: NDArrayF32, k: int) -> list[tuple[int, float]]:
+        tl = current_timeline()
+        attrs = {
+            "k": int(k),
+            "index_type": getattr(self, "_index_type", "unknown"),
+            "gpu": bool(getattr(self, "_gpu", False)),
+            "params": {
+                "nprobe": getattr(self, "_nprobe", None),
+                "ef_search": getattr(self, "_ef_search", None),
+            },
+        }
+        if tl:
+            with tl.step("search.faiss", **attrs):
+                return self._search_impl(vector, k)
+        return self._search_impl(vector, k)
+
+    def _search_impl(self, vector: NDArrayF32, k: int) -> list[tuple[int, float]]:
+        # (existing concrete search body moved here unchanged)
+        # ... existing code ...
+        return results
```

*Rationale:* align FAISS with Hybrid channel steps you already emit, and surface the effective knobs used at runtime (helps reproduce “why did this query return only N?”). The docstring indicates the search seam explicitly.

---

### 6) Deeper coverage: `codeintel_rev/io/duckdb_catalog.py` (hydration timings)

```diff
diff --git a/codeintel_rev/io/duckdb_catalog.py b/codeintel_rev/io/duckdb_catalog.py
@@
 from typing import Sequence, Iterable
+from codeintel_rev.observability.timeline import current_timeline
@@ class DuckDBCatalog:
     def query_by_ids(self, ids: Sequence[int]) -> list[dict]:
-        # ... existing code ...
-        return rows
+        tl = current_timeline()
+        if tl:
+            with tl.step("hydrate.duckdb", op="query_by_ids", in_ids=len(ids)):
+                return self._query_by_ids_impl(ids)
+        return self._query_by_ids_impl(ids)
+
+    def _query_by_ids_impl(self, ids: Sequence[int]) -> list[dict]:
+        # existing logic here
+        return rows
@@
     def query_by_filters(
         self,
         ids: Sequence[int],
         *,
         include_globs: list[str] | None = None,
         exclude_globs: list[str] | None = None,
         languages: list[str] | None = None,
     ) -> list[dict]:
-        # ... existing code ...
-        return rows
+        tl = current_timeline()
+        attrs = {
+            "op": "query_by_filters",
+            "in_ids": len(ids),
+            "include_globs": bool(include_globs),
+            "exclude_globs": bool(exclude_globs),
+            "languages": languages or [],
+        }
+        if tl:
+            with tl.step("hydrate.duckdb", **attrs):
+                return self._query_by_filters_impl(ids, include_globs=include_globs,
+                                                   exclude_globs=exclude_globs, languages=languages)
+        return self._query_by_filters_impl(ids, include_globs=include_globs,
+                                           exclude_globs=exclude_globs, languages=languages)
+
+    def _query_by_filters_impl(self, ids: Sequence[int], *,
+                               include_globs: list[str] | None,
+                               exclude_globs: list[str] | None,
+                               languages: list[str] | None) -> list[dict]:
+        # existing logic here
+        return rows
```

*Rationale:* pairs precisely with the documented query methods you use post‑FAISS to hydrate findings.

---

### 7) Deeper coverage: `codeintel_rev/io/xtr_manager.py` (encode/search/rescore)

```diff
diff --git a/codeintel_rev/io/xtr_manager.py b/codeintel_rev/io/xtr_manager.py
@@
 from typing import Iterable, Sequence
+from codeintel_rev.observability.timeline import current_timeline
@@ class XTRIndex:
     def encode_query_tokens(self, text: str) -> NDArrayF32:
-        # ... existing code ...
-        return token_vecs
+        tl = current_timeline()
+        if tl:
+            with tl.step("xtr.encode_query", text_chars=len(text)):
+                return self._encode_query_tokens_impl(text)
+        return self._encode_query_tokens_impl(text)
+
+    def _encode_query_tokens_impl(self, text: str) -> NDArrayF32:
+        # existing logic here
+        return token_vecs
@@
     def search(self, query: str, k: int, *, explain: bool = False, topk_explanations: int = 5):
-        # ... existing code ...
-        return results
+        tl = current_timeline()
+        attrs = {"k": int(k), "explain": bool(explain), "topk_explanations": int(topk_explanations)}
+        if tl:
+            with tl.step("xtr.search", **attrs):
+                return self._search_impl(query, k, explain=explain, topk_explanations=topk_explanations)
+        return self._search_impl(query, k, explain=explain, topk_explanations=topk_explanations)
+
+    def _search_impl(self, query: str, k: int, *, explain: bool, topk_explanations: int):
+        # existing logic here
+        return results
@@
     def rescore(self, query: str, candidate_chunk_ids: Iterable[int], *, explain: bool = False, topk_explanations: int = 5):
-        # ... existing code ...
-        return rescored
+        tl = current_timeline()
+        attrs = {"candidates": len(list(candidate_chunk_ids)), "explain": bool(explain), "topk_explanations": int(topk_explanations)}
+        if tl:
+            with tl.step("xtr.rescore", **attrs):
+                return self._rescore_impl(query, candidate_chunk_ids, explain=explain, topk_explanations=topk_explanations)
+        return self._rescore_impl(query, candidate_chunk_ids, explain=explain, topk_explanations=topk_explanations)
+
+    def _rescore_impl(self, query: str, candidate_chunk_ids: Iterable[int], *, explain: bool, topk_explanations: int):
+        # existing logic here
+        return rescored
```

*Rationale:* aligns with the documented XTR API (“tokens→MaxSim wide→narrow rescore”) so diagnostic reports can show *exactly which late‑interaction path ran and with what sizes*.

---

### 8) Deeper coverage: `codeintel_rev/io/warp_engine.py` (rerank timings)

```diff
diff --git a/codeintel_rev/io/warp_engine.py b/codeintel_rev/io/warp_engine.py
@@
 from typing import Sequence
+from codeintel_rev.observability.timeline import current_timeline
@@ class WarpEngine:
     def rerank(self, *, query: str, candidate_ids: Sequence[int], top_k: int) -> list[tuple[int, float]]:
-        # ... existing code ...
-        return ranked
+        tl = current_timeline()
+        attrs = {"candidates": len(candidate_ids), "top_k": int(top_k)}
+        if tl:
+            with tl.step("warp.rerank", **attrs):
+                return self._rerank_impl(query=query, candidate_ids=candidate_ids, top_k=top_k)
+        return self._rerank_impl(query=query, candidate_ids=candidate_ids, top_k=top_k)
+
+    def _rerank_impl(self, *, query: str, candidate_ids: Sequence[int], top_k: int) -> list[tuple[int, float]]:
+        # existing logic here
+        return ranked
```

*Rationale:* ensures Phase‑0 reports show if/when WARP fired and how many candidates it saw.

---

### 9) Optional: HTTP endpoint for reports (`codeintel_rev/app/main.py`)

If you’d like an HTTP surface in addition to the MCP tool:

```diff
diff --git a/codeintel_rev/app/main.py b/codeintel_rev/app/main.py
@@
 from fastapi import APIRouter, FastAPI, HTTPException
 from codeintel_rev.app.config_context import ApplicationContext
+from codeintel_rev.diagnostics.report_service import build_report, render_markdown
@@
 router = APIRouter()
@@
 @router.get("/diag/report/{session_id}")
 def get_report(session_id: str, run_id: str | None = None) -> PlainTextResponse:
     ctx = app.state.context  # type: ignore[attr-defined]
     rep = build_report(ctx, session_id, run_id)
     if rep is None:
         raise HTTPException(status_code=404, detail="No events for session/run")
     return PlainTextResponse(render_markdown(rep))
```

---

## What you’ll see after Phase‑0

* **Every query** through `semantic_search` / `semantic_search_pro` already brackets tool operation timing; now the sub‑steps (embed, FAISS, SPLADE/BM25, RRF, DuckDB hydrate, XTR, WARP) appear as **concise, timed steps** in the run report.
* **Budget & gating** decisions show up as “Decisions,” using `describe_budget_decision(...)` payloads you already expose.
* **Partial run detection**: if an exception or skip ends the run, the report status becomes `error` or `incomplete` and includes the first stop reason (from your error envelope handling).
* **Capabilities snapshot** stamped into each report so future readers immediately see the environment that produced the results (GPU present? WARP/XTR available? FAISS type?).

---

## A few design callouts

* **Never‑break principle**: the timeline sink already writes JSONL append‑only and ignores serialization errors (best‑effort) so you never lose a request to diagnostics code.
* **Unification, not proliferation**: we reuse `tool_operation_scope(...)` and the existing `Timeline.operation/step(...)` rather than adding competing mechanisms.
* **Local‑first**: the MCP tool is enough for agent workflows; the HTTP endpoint is optional for quick human inspection.

---

## Next steps checklist

1. **Apply patches** and run locally.
2. Fire a few `semantic_search` / `semantic_search_pro` queries and run:

   * MCP: `diagnostics.generate_run_report(session_id="<your-session>")`
   * HTTP (optional): `GET /diag/report/<session_id>`
3. Skim the Markdown. Confirm you see:

   * `embed.vllm` → `search.faiss` → `hydrate.duckdb` (+ optional `xtr.*` / `warp.rerank`) steps with durations and sizes.
   * “Decisions” and any “Skips/Warnings".
4. Iterate on **attrs** you want in the report (e.g., FAISS pq_m, IVF nlist, BM25/SPLADE term counts); just add to the `attrs` maps in the step wrappers.

If you want, I can also derive a **tiny smoke‑suite** of queries to demonstrate each branch (GPU vs CPU FAISS, XTR wide vs narrow, WARP on/off) so you can validate coverage in a single session.

---

### Pinned references to your codebase (for traceability)

* Timeline API (`Timeline.event/operation/step`) and JSONL recorder with rotation are already present.
* MCP tool wrapper: `tool_operation_scope(...)` is the standard way we bracket tool operations and is used broadly in your servers.
* Diagnostics CLI that renders timeline → Markdown is present (we mirrored its behavior programmatically).
* Hybrid search / channel plumbing already emits timeline events (we add the missing I/O‑heavy steps).
* XTR tokens/search/rescore seams and their characteristics are documented in your interfaces (we instrument precisely there).
* DuckDB hydration APIs provide the right granularity for “what was hydrated and how much”.
* Capabilities snapshot used for context stamping lives at `Capabilities.from_context()`.

---

If you want me to also wire a **Prometheus view** for a few coarse counters/timers (purely informational, not gating), I can layer it after this—keeping your directive to avoid CI/quality gates intact while giving quick dashboards for “how many” and “how long”.
