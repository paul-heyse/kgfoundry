Amazing — let’s ship the immediate follow‑ups as **PR‑ready patches**, with branch names, commit messages, diffs, and a crisp validation plan. I’ve structured them to drop straight into your current tree (post PR‑B & PR‑D) and to align with your AGENTS doctrine (typing gates, Problem Details, tests, lint, docs). Where I anchor choices in your repo’s standards or surfaces, I cite the source so reviewers can jump to the right file quickly. 

Below are **three small PRs**:

1. **PR‑T1** — Observability backbone (OTel bootstrap + local JSONL “flight recorder”) and safe edge instrumentation
2. **PR‑T2** — Hydration diagnostics (DuckDB) with counts: asked/returned/missing
3. **PR‑T3** — Git tools spans (blame/history) and request/session correlation

> These are intentionally additive and side‑effect‑free (no behavior changes; only telemetry), and they sit on top of the gated runtime/server architecture you just implemented.

---

## PR‑T1 — *feat(observability): OpenTelemetry bootstrap + timeline flight‑recorder + safe path instrumentation*

**Branch**: `feat/telemetry-backbone`
**Why**: Give you complete “what ran / what skipped / for how long / in which mode” timelines for semantic retrieval — vLLM embeddings, FAISS search (GPU/CPU), and hybrid BM25/SPLADE channels — without changing behavior. These are the exact seams your code documents (FAISS manager, hybrid provider, vLLM engine/client), so spans & events map 1:1 to current responsibilities.

### Files

```
A  src/codeintel_rev/observability/otel.py
A  src/codeintel_rev/observability/timeline.py
A  src/codeintel_rev/observability/runtime_observer.py
M  src/codeintel_rev/app/main.py
M  src/codeintel_rev/io/vllm_client.py
M  src/codeintel_rev/io/faiss_manager.py
M  src/codeintel_rev/io/hybrid_search.py
A  src/codeintel_rev/diagnostics/report_cli.py
```

> We keep **top‑level imports light** and attach observers lazily (no heavy import at module import time), consistent with your typing‑gate policy. 

---

### Commit 1 — **obs: add OTel bootstrap + JSONL timeline (“flight recorder”)**

**`src/codeintel_rev/observability/otel.py`** (new)

```python
from __future__ import annotations
from contextlib import contextmanager
from typing import Iterator, Mapping, Any

def _enabled() -> bool:
    import os
    return os.getenv("CODEINTEL_TELEMETRY", "0") == "1"

def init_telemetry(app) -> None:
    """Lazy OTel bootstrap; safe no-op if OTel is not installed/enabled."""
    if not _enabled():
        return
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry import trace
        import os

        resource = Resource.create({"service.name": "codeintel_rev"})
        provider = TracerProvider(resource=resource)
        ep = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=ep) if ep else ConsoleSpanExporter())
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        app.state._otel_tracer = trace.get_tracer("codeintel_rev")
    except Exception:
        # Stay silent: telemetry must never break startup
        app.state._otel_tracer = None

@contextmanager
def as_span(app, name: str, attrs: Mapping[str, Any] | None = None) -> Iterator[None]:
    """Start a span if telemetry is enabled."""
    tracer = getattr(app.state, "_otel_tracer", None)
    if tracer is None:
        yield
        return
    with tracer.start_as_current_span(name) as span:
        if attrs:
            for k, v in attrs.items():
                span.set_attribute(str(k), v)
        yield
```

**`src/codeintel_rev/observability/timeline.py`** (new)

```python
from __future__ import annotations
import json, os, time, threading, uuid
from contextlib import contextmanager
from dataclasses import dataclass

_LOG_LOCK = threading.Lock()

@dataclass(slots=True)
class Timeline:
    session_id: str
    run_id: str

    def _write(self, event: dict) -> None:
        path = os.getenv("CODEINTEL_DIAG_DIR", "./data/diagnostics")
        os.makedirs(path, exist_ok=True)
        fn = os.path.join(path, f"events-{time.strftime('%Y%m%d')}.jsonl")
        with _LOG_LOCK, open(fn, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def event(self, typ: str, name: str, status: str = "ok", **attrs) -> None:
        self._write({
            "ts": time.time(),
            "type": typ, "name": name, "status": status,
            "session_id": self.session_id, "run_id": self.run_id,
            "attrs": attrs or {},
        })

    @contextmanager
    def step(self, name: str, **attrs):
        self.event("step.start", name, **attrs)
        t0 = time.time()
        try:
            yield
            self.event("step.end", name, duration_ms=int(1000 * (time.time() - t0)))
        except Exception as e:
            self.event("step.end", name, status="error", error=type(e).__name__, message=str(e))
            raise

def new_timeline(session_id: str) -> Timeline:
    return Timeline(session_id=session_id or "unknown", run_id=str(uuid.uuid4()))
```

**`src/codeintel_rev/observability/runtime_observer.py`** (new)

```python
from __future__ import annotations
from .timeline import Timeline

class RuntimeCellObserver:
    """Minimal interface used by ApplicationContext to report cell lifecycle."""
    def on_init_start(self, name: str): ...
    def on_init_end(self, name: str, ok: bool, **attrs): ...
    def on_close(self, name: str): ...

class TimelineRuntimeObserver(RuntimeCellObserver):
    def __init__(self, timeline: Timeline): self._tl = timeline

    def on_init_start(self, name: str):
        self._tl.event("runtime.init.start", name)

    def on_init_end(self, name: str, ok: bool, **attrs):
        self._tl.event("runtime.init.end", name, status=("ok" if ok else "error"), **attrs)

    def on_close(self, name: str):
        self._tl.event("runtime.close", name)
```

> These helpers are **dependency‑light** (OTel optional; JSONL recorder always available) and follow your “import‑clean at module import” policy. 

---

### Commit 2 — **app: wire telemetry middleware + session binding**

**`src/codeintel_rev/app/main.py`** (excerpt)

```diff
 from __future__ import annotations
@@
-from fastapi import FastAPI, Request
+from fastapi import FastAPI, Request
 from fastapi.responses import JSONResponse
@@
+from codeintel_rev.observability.otel import init_telemetry, as_span
+from codeintel_rev.observability.timeline import new_timeline
+from codeintel_rev.observability.runtime_observer import TimelineRuntimeObserver
@@
 app = FastAPI(...)
@@
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     # existing: build ApplicationContext, readiness
@@
-    yield
+    # Init telemetry (safe no-op if disabled)
+    init_telemetry(app)
+    yield
@@
 @app.middleware("http")
 async def set_mcp_context(request: Request, call_next):
-    # existing: bind ApplicationContext into MCP handlers
+    # existing: bind ApplicationContext into MCP handlers
     ...
+    # Bind per-request timeline (session id from existing middleware or header)
+    session_id = request.headers.get("X-Session-ID") or getattr(request.state, "session_id", "") or "anonymous"
+    request.state.timeline = new_timeline(session_id)
+    with as_span(request.app, "http.request", {"path": request.url.path, "method": request.method}):
+        resp = await call_next(request)
+    return resp
```

> This sits alongside your existing session scoping middleware and contextvar hand‑off to MCP tools; it does **not** change handler semantics. Your error taxonomy (Problem Details) remains the single place that shapes error envelopes. 

---

### Commit 3 — **instrument vLLM, FAISS, Hybrid at safe seams**

**`src/codeintel_rev/io/vllm_client.py`** (excerpt)

```diff
 from __future__ import annotations
@@
+from fastapi import Request  # only to access request.state.timeline at call sites
@@
 class VLLMClient:
     ...
-    async def embed_batch(self, texts: list[str]) -> NDArrayF32:
+    async def embed_batch(self, texts: list[str], request: Request | None = None) -> NDArrayF32:
         """
         Embed texts; HTTP or in-process depending on config.
         """
+        tl = getattr(getattr(request, "state", None), "timeline", None)
+        if tl: tl.event("embedding.start", "vllm", mode=("http" if self._http else "local"), n_texts=len(texts))
         t0 = time.perf_counter()
         arr = await self._runtime.embed(texts)  # existing call
-        return arr
+        if tl: tl.event("embedding.end", "vllm", duration_ms=int(1000*(time.perf_counter()-t0)), dim=arr.shape[1])
+        return arr
```

**`src/codeintel_rev/io/faiss_manager.py`** (excerpt)

```diff
 from __future__ import annotations
@@
 class FAISSManager:
     ...
-    def search(self, query: NDArrayF32, k: int) -> tuple[NDArrayF32, NDArrayI64]:
+    def search(self, query: NDArrayF32, k: int, *, request: Request | None = None) -> tuple[NDArrayF32, NDArrayI64]:
         """
         Vector search. GPU or CPU depending on availability.
         """
+        tl = getattr(getattr(request, "state", None), "timeline", None)
+        if tl: tl.event("faiss.search.start", "faiss", k=k, use_gpu=bool(self._gpu_resources))
         t0 = time.perf_counter()
         D, I = self._index.search(query, k)  # existing call
-        return D, I
+        if tl: tl.event("faiss.search.end", "faiss", duration_ms=int(1000*(time.perf_counter()-t0)), rows=len(I))
+        return D, I
```

> FAISS manager is exactly where your index/search responsibilities live; we report GPU/CPU mode from the manager itself. (Your indexed symbols and docs show FAISS manager methods and GPU fields.) 

**`src/codeintel_rev/io/hybrid_search.py`** (excerpt)

```diff
@@
-    def _gather_channel_hits(...):
+    def _gather_channel_hits(...):
+        tl = getattr(getattr(request, "state", None), "timeline", None)
         hits = []
-        if self._bm25_enabled:
+        if self._bm25_enabled:
+            if tl: tl.event("channel.run", "bm25")
             hits.extend(self._bm25.search(q, limit=limit))
         else:
+            if tl: tl.event("channel.skip", "bm25", reason="disabled")
             ...
-        if self._splade_enabled:
+        if self._splade_enabled:
+            if tl: tl.event("channel.run", "splade")
             hits.extend(self._splade.search(q, limit=limit))
         else:
+            if tl: tl.event("channel.skip", "splade", reason="disabled")
             ...
-        # fuse
+        # fuse
+        if tl: tl.event("hybrid.rrf.start", "fusion", n=len(hits))
         fused = rrf_fuse(hits)
-        return fused
+        if tl: tl.event("hybrid.rrf.end", "fusion", n=len(fused))
+        return fused
```

> Hybrid provider already separates channels and fusion in your adapters; this makes *RUN vs SKIP* explicit, which is central to your “where it stopped and why” goal. 

**`src/codeintel_rev/diagnostics/report_cli.py`** (new: turn JSONL into markdown)

```python
from __future__ import annotations
import json, argparse, sys
from collections import defaultdict

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    lines = []
    with open(args.events, "r", encoding="utf-8") as f:
        for line in f:
            try: lines.append(json.loads(line))
            except Exception: pass

    lines = [e for e in lines if e.get("session_id")==args.session]
    lines.sort(key=lambda e: e["ts"])

    md = ["# CodeIntel run report", "", f"**Session**: `{args.session}`", ""]
    for e in lines:
        tag = {"ok":"✅","error":"❌","skip":"⏭️"}.get(e.get("status","ok"), "•")
        md.append(f"- {tag} **{e['type']}** `{e['name']}` — {e.get('attrs',{})}")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(args.out)

if __name__ == "__main__":
    sys.exit(main())
```

---

### Validation

* **No behavior change**: only spans/events; handlers & adapters unchanged.
* **Local smoke**: `CODEINTEL_TELEMETRY=1 uvicorn codeintel_rev.app.main:app` → issue a semantic search; JSONL under `./data/diagnostics/` contains events for `embedding`, `faiss.search`, `channel.run/skip`, `hybrid.rrf`.
* **Problem Details unchanged**: your errors module continues to shape envelopes system‑wide; this PR does not alter that contract. 

---

## PR‑T2 — *feat(observability): DuckDB hydration spans and counts (asked / returned / missing)*

**Branch**: `feat/telemetry-hydration`
**Why**: Add explicit observability to hydration, which is the other critical leg in your semantic pipeline (catalog lookups on IDs). Your `DuckDBCatalog` module and `open_catalog()` access pattern provide single, safe choke points to instrument. 

### Files

```
M  src/codeintel_rev/app/main.py               (tiny: import helper)
M  src/codeintel_rev/io/duckdb_catalog.py      (wrap query_by_ids with timeline events)
```

**`src/codeintel_rev/io/duckdb_catalog.py`** (excerpt)

```diff
 from __future__ import annotations
@@
 class DuckDBCatalog:
     ...
-    def query_by_ids(self, ids: list[int]) -> list[Row]:
+    def query_by_ids(self, ids: list[int], *, request: Request | None = None) -> list[Row]:
+        tl = getattr(getattr(request, "state", None), "timeline", None)
+        if tl: tl.event("duckdb.hydrate.start", "catalog", asked_for=len(ids))
         rows = self._conn.execute(...).fetchall()  # existing SQL
-        return rows
+        if tl:
+            tl.event("duckdb.hydrate.end", "catalog",
+                     returned=len(rows),
+                     missing=max(0, len(ids)-len(rows)))
+        return rows
```

> This makes the availability and completeness of metadata **measurable**, and it will show up in the session report next to FAISS/Hybrid events. (Your catalog module doc already establishes this as the query workhorse.) 

### Validation

* Exercise a semantic query; confirm `duckdb.hydrate.*` events appear with counts.
* Ensure minimal overhead (2 events per hydration).

---

## PR‑T3 — *feat(observability): Git adapters spans (blame/history) tied to session*

**Branch**: `feat/telemetry-git`
**Why**: Your Git client wrappers are a common source of “why did this result include that commit?” questions. Add spans + lightweight facts (n_lines/n_commits) without touching behavior. The SCIP index confirms `codeintel_rev.io.git_client.GitClient` and `Repo` interactions.

### Files

```
M  src/codeintel_rev/io/git_client.py
```

**`src/codeintel_rev/io/git_client.py`** (excerpt)

```diff
 from __future__ import annotations
@@
 class GitClient:
     ...
-    def blame_range(self, path: str, start: int, end: int) -> list[tuple[str,int]]:
+    def blame_range(self, path: str, start: int, end: int, *, request: Request | None = None) -> list[tuple[str,int]]:
+        tl = getattr(getattr(request, "state", None), "timeline", None)
+        if tl: tl.event("git.blame.start", path, n_lines=(end-start+1))
         out = self._repo.blame(path, L=f"{start},{end}")  # existing
-        return out
+        if tl: tl.event("git.blame.end", path, n_lines=len(out))
+        return out

-    def file_history(self, path: str, max_commits: int = 50) -> list[str]:
+    def file_history(self, path: str, max_commits: int = 50, *, request: Request | None = None) -> list[str]:
+        tl = getattr(getattr(request, "state", None), "timeline", None)
+        if tl: tl.event("git.history.start", path, max=max_commits)
         commits = self._repo.iter_commits(path, max_count=max_commits)
         result = [c.hexsha for c in commits]
-        return result
+        if tl: tl.event("git.history.end", path, n_commits=len(result))
+        return result
```

### Validation

* Run blame/history via the MCP tools; confirm git.* events with counts in JSONL.

---

## How these PRs align with your rules

* **Typing gates / import‑clean**: no heavy imports at module import time; everything is lazy and opt‑in, as your AGENTS doc mandates (TC001–TC006 / PLC2701). 
* **Problem Details**: unchanged; errors keep flowing through `kgfoundry_common.errors` patterns referenced by your AGENTS page. 
* **Runtime ownership**: all heavy runtime creation remains in your gated factories (PR‑B) and the server remains capability‑gated (PR‑D), consistent with the phase‑2 plan. 

---

## Suggested PR bodies (copy/paste)

### PR‑T1 body

> **feat(observability): OTel bootstrap + local JSONL “flight recorder” + safe path instrumentation**
>
> * Adds optional OpenTelemetry and a timeline JSONL recorder (env‑driven).
> * Instruments vLLM embeddings, FAISS search (GPU/CPU), and Hybrid channels (BM25/SPLADE) with **RUN vs SKIP** and durations.
> * Adds a small CLI to produce a Markdown “where it stopped and why” report per session.
>
> **Design constraints**
>
> * No behavior changes. Import‑time remains clean; runtime stays lazy (matches Typing‑Gates). 
> * Error envelopes remain governed by Problem Details. 
>
> **How to use**
>
> ```
> export CODEINTEL_TELEMETRY=1
> export CODEINTEL_DIAG_DIR=./data/diagnostics
> uvicorn codeintel_rev.app.main:app --reload
> python -m codeintel_rev.diagnostics.report_cli --events <jsonl> --session <id> --out report.md
> ```

### PR‑T2 body

> **feat(observability): DuckDB hydration spans + counts**
>
> * Adds `duckdb.hydrate.start/end` events with `asked_for`, `returned`, `missing` so metadata completeness is visible per request.
> * Single‑point instrumentation in `DuckDBCatalog.query_by_ids(...)`. 

### PR‑T3 body

> **feat(observability): Git blame/history spans & counts**
>
> * Adds `git.blame.*` and `git.history.*` events; no behavior change.
> * Correlates with session id for end‑to‑end narratives. (Git surfaces are present in `codeintel_rev.io.git_client`.)

---

## Reviewer checklist (quick)

* [ ] App still boots with telemetry disabled (default).
* [ ] Semantic run shows `embedding.*`, `faiss.search.*`, `channel.*`, `hybrid.rrf.*` events. 
* [ ] Hydration produces `duckdb.hydrate.*` counts. 
* [ ] Git tools emit counts.
* [ ] Lint/type/tests stay green under your AGENTS rules. 

---

## What I’ll detail next (architecture refinement)

Once you merge PR‑T1..T3, I’ll follow with a revised implementation plan to (a) enrich `/capz` with the same capability booleans that the server factory uses, (b) add **negative‑deps tests** & gate checker integration (so import‑cleanliness never regresses), and (c) wire rerank/XTR spans behind its capability bit (kept optional) — all aligned with your Type‑Gating / Capability‑Gated architecture. 

If you want me to include these PRs as patch files you can apply with `git apply`, I can generate them in‑place as well.
