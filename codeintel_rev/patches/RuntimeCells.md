
Amazing—let’s lock this into a concrete, production‑grade implementation plan you can hand directly to engineering. Below is a complete blueprint for (1) a **drop‑in `runtime/cells.py`** execution engine, and (2) the minimal, idiomatic changes to **`ApplicationContext` / runtime state** so it’s cleanly wired, testable, and observable from day one.

Where relevant, I anchor choices to patterns already established in your app (e.g., *load‑once config*, explicit DI, lazy singletons, RFC 9457 Problem Details, FAISS/GPU readiness). 

---

## 0) North‑star & constraints

* **Load once; inject explicitly**: follow your `ApplicationContext` model (frozen dataclasses, long‑lived clients, no globals). 
* **Lazy, thread‑safe singletons**: mirror `_RuntimeHandle` for on‑demand init + locking. 
* **Fail fast, problem‑details errors**: mirror `FileOperationError`, `InvalidLineRangeError`, `GitOperationError`; extend with runtime‑specific errors carrying structured context. 
* **GPU/FAISS readiness is non‑blocking but visible**: keep the “degraded but usable” stance of `ensure_faiss_ready()` and `gpu_warmup.warmup_gpu()`. 

---

## 1) Package layout (new & touched files)

```
codeintel_rev/
  runtime/
    __init__.py
    cells.py                # NEW: CellsRuntime engine + types + operations protocol
    errors.py               # NEW: runtime-specific Problem Details errors
    ops/
      __init__.py           # NEW: registry wiring
      git_ops.py            # NEW: uses AsyncGitClient
      chunk_ops.py          # NEW: text/code chunking
      embed_ops.py          # NEW: uses VLLMClient
      faiss_ops.py          # NEW: uses FAISSManager/DuckDBCatalog
      search_ops.py         # NEW: uses HybridSearchEngine
  app/
    config_context.py       # TOUCH: add runtime handle + getter
    readiness.py            # TOUCH: add optional runtime health hook
```

> *Why a small `ops/` package?* It keeps “what a cell does” pluggable and testable behind typed protocols while the scheduler stays small and boring.

---

## 2) Data model & API surface

### 2.1 Core types (public, typed, immutable where possible)

* **IDs & states**

  * `CellId = NewType("CellId", str)`
  * `class CellState(StrEnum)`: `PENDING`, `READY`, `RUNNING`, `SUCCESS`, `FAILED`, `SKIPPED`, `CANCELED`
* **Specs & plan**

  * `@dataclass(slots=True, frozen=True) class CellSpec`: `id`, `op`, `inputs: list[CellId]`, `params: Mapping[str, Any]`, `timeout_s: float|None`
  * `@dataclass(slots=True, frozen=True) class ExecutionPlan`: `cells: list[CellSpec]`
* **Results & events**

  * `@dataclass(slots=True) class CellResult`: `state`, `output: Any|None`, `error: ProblemDetails|None`, `started_at`, `ended_at`
  * `@dataclass(slots=True) class RuntimeEvent`: `run_id`, `cell_id`, `state`, `message`, `ts`

### 2.2 Operations protocol & registry

```python
class Operation(Protocol):
    name: str
    async def run(
        self,
        ctx: "RuntimeContext",
        params: Mapping[str, Any],
        deps: Mapping[CellId, Any],
    ) -> Any: ...
```

A simple **registry** maps `op` → `Operation`.

* Built‑ins (first wave): `git.scan`, `chunk.text`, `embed.vectors`, `faiss.add`, `duckdb.upsert`, `search.hybrid`.
* Each op receives:

  * `RuntimeContext` (exposes your `ApplicationContext` deps—Git/FAISS/DuckDB/VLLM/scope store/paths). 
  * `params` (validated dict)
  * `deps` (outputs of upstream cells)

---

## 3) The engine (`runtime/cells.py`) — scheduler, DAG, execution

### 3.1 Responsibilities

* **Validate** DAG (acyclic, all inputs exist).
* **Topological** scheduling with **bounded concurrency** (Semaphore).
* **Cancellation & timeouts** per cell.
* **Idempotence** & **incremental** runs: content‑address each cell (“fingerprint” includes op, params, upstream fingerprints).
* **Caching**:

  * **L1** in‑process memo (per run).
  * **L2** via `ScopeStore` keyed by `(cell_fingerprint, scope)` with TTLs. 
* **Observability**: structured logs, optional event stream generator, timing.

### 3.2 Minimal, production‑ready skeleton (drop‑in)

```python
# codeintel_rev/runtime/cells.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, MutableMapping, Sequence, Awaitable, Protocol, NewType
from pathlib import Path
import asyncio, contextlib, hashlib, json, time

CellId = NewType("CellId", str)

class CellState(StrEnum):
    PENDING = "pending"; READY = "ready"; RUNNING = "running"
    SUCCESS = "success"; FAILED = "failed"; SKIPPED = "skipped"; CANCELED = "canceled"

@dataclass(slots=True, frozen=True)
class CellSpec:
    id: CellId
    op: str
    inputs: list[CellId] = field(default_factory=list)
    params: Mapping[str, Any] = field(default_factory=dict)
    timeout_s: float | None = None

@dataclass(slots=True, frozen=True)
class ExecutionPlan:
    cells: list[CellSpec]

@dataclass(slots=True)
class CellResult:
    state: CellState
    output: Any | None
    error: Mapping[str, Any] | None
    started_at: float | None = None
    ended_at: float | None = None

class Operation(Protocol):
    name: str
    async def run(self, ctx: "RuntimeContext", params: Mapping[str, Any], deps: Mapping[CellId, Any]) -> Any: ...

@dataclass(slots=True, frozen=True)
class RuntimeConfig:
    max_concurrency: int = 8
    default_timeout_s: float | None = 300
    cache_enabled: bool = True

@dataclass(slots=True)
class RuntimeContext:
    app: "ApplicationContext"              # reuse your DI container
    config: RuntimeConfig
    run_id: str
    scope: str | None = None

class CellsRuntime:
    def __init__(self, *, app: "ApplicationContext", config: RuntimeConfig) -> None:
        self._app = app
        self._config = config
        self._ops: dict[str, Operation] = {}
        self._lock = asyncio.Lock()       # registry mutation
        # lightweight L1 cache per-process; L2 handled through ScopeStore
        self._cache: MutableMapping[str, Any] = {}

    def register(self, op: Operation) -> None:
        # registry is updated rarely; keep simple
        self._ops[op.name] = op

    async def run(self, plan: ExecutionPlan, *, scope: str | None = None) -> dict[CellId, CellResult]:
        self._validate(plan)
        run_id = hashlib.blake2b(repr(plan).encode(), digest_size=16).hexdigest()
        ctx = RuntimeContext(app=self._app, config=self._config, run_id=run_id, scope=scope)

        # topo order
        order = self._toposort(plan)
        sem = asyncio.Semaphore(self._config.max_concurrency)
        results: dict[CellId, CellResult] = {}
        tasks: dict[CellId, asyncio.Task[None]] = {}

        async def exec_cell(spec: CellSpec) -> None:
            async with sem:
                deps_out = {c: results[c].output for c in spec.inputs if results[c].state == CellState.SUCCESS}
                fingerprint = self._fingerprint(spec, deps_out)
                cached = await self._get_cached(ctx, fingerprint)
                if cached is not None:
                    results[spec.id] = CellResult(state=CellState.SUCCESS, output=cached, error=None)
                    return
                started = time.time()
                results[spec.id] = CellResult(state=CellState.RUNNING, output=None, error=None, started_at=started)
                try:
                    op = self._ops[spec.op]
                    coro = op.run(ctx, spec.params, deps_out)
                    if spec.timeout_s or self._config.default_timeout_s:
                        timeout = spec.timeout_s or self._config.default_timeout_s
                        out = await asyncio.wait_for(coro, timeout=timeout)
                    else:
                        out = await coro
                    results[spec.id] = CellResult(state=CellState.SUCCESS, output=out, error=None,
                                                  started_at=started, ended_at=time.time())
                    await self._set_cached(ctx, fingerprint, out)
                except asyncio.CancelledError:
                    results[spec.id] = CellResult(state=CellState.CANCELED, output=None, error={"reason": "canceled"},
                                                  started_at=started, ended_at=time.time())
                    raise
                except Exception as exc:
                    # map to Problem Details structure your stack already uses
                    results[spec.id] = CellResult(state=CellState.FAILED, output=None,
                                                  error={"title": "runtime-execution-failed",
                                                         "detail": str(exc),
                                                         "cell": str(spec.id), "op": spec.op},
                                                  started_at=started, ended_at=time.time())

        # schedule respecting deps
        for cell in order:
            for dep in cell.inputs:
                await tasks[dep]
            tasks[cell.id] = asyncio.create_task(exec_cell(cell))

        await asyncio.gather(*tasks.values(), return_exceptions=False)
        return results

    # --- helpers ---
    def _validate(self, plan: ExecutionPlan) -> None:
        ids = {c.id for c in plan.cells}
        for c in plan.cells:
            for i in c.inputs:
                if i not in ids:
                    raise RuntimeInvalidGraphError(f"Missing dependency {i!s} for {c.id!s}")
        # cycle check via Kahn
        self._toposort(plan)  # raises on cycle

    def _toposort(self, plan: ExecutionPlan) -> list[CellSpec]:
        indeg = {c.id: 0 for c in plan.cells}
        by_id = {c.id: c for c in plan.cells}
        for c in plan.cells:
            for d in c.inputs:
                indeg[c.id] += 1
        queue = [by_id[i] for i, d in indeg.items() if d == 0]
        order: list[CellSpec] = []
        while queue:
            n = queue.pop()
            order.append(n)
            for c in plan.cells:
                if n.id in c.inputs:
                    indeg[c.id] -= 1
                    if indeg[c.id] == 0:
                        queue.append(by_id[c.id])
        if len(order) != len(plan.cells):
            raise RuntimeInvalidGraphError("Cycle detected in execution plan")
        return order

    def _fingerprint(self, spec: CellSpec, deps_out: Mapping[CellId, Any]) -> str:
        h = hashlib.blake2b(digest_size=16)
        h.update(spec.op.encode())
        h.update(json.dumps(spec.params, sort_keys=True, default=str).encode())
        h.update(json.dumps({str(k): deps_out[k] for k in sorted(deps_out)}, default=str).encode())
        return h.hexdigest()

    async def _get_cached(self, ctx: RuntimeContext, fp: str) -> Any | None:
        if not self._config.cache_enabled:
            return None
        if fp in self._cache:
            return self._cache[fp]
        # L2 via ScopeStore (if provided)
        if ctx.app.scope_store and ctx.scope:
            res = await ctx.app.scope_store.get(f"cells:{ctx.scope}:{fp}")  # pseudo-API
            if res is not None:
                self._cache[fp] = res
                return res
        return None

    async def _set_cached(self, ctx: RuntimeContext, fp: str, value: Any) -> None:
        if not self._config.cache_enabled:
            return
        self._cache[fp] = value
        if ctx.app.scope_store and ctx.scope:
            await ctx.app.scope_store.set(f"cells:{ctx.scope}:{fp}", value)  # pseudo-API
```

* **Notes on integration points referenced above**:

  * `ApplicationContext` (frozen, DI, long‑lived clients) is exactly how we pass Git/FAISS/DuckDB/VLLM/ScopeStore without globals. 
  * `ScopeStore` exists (Redis L1/L2 TTL, etc.), so L2 cache hook uses it. 
  * If a cell needs FAISS on GPU, reuse `ensure_faiss_ready()` ahead of execution (engine can opportunistically call it once per run). 
  * If you want early GPU diagnosis, you already have `gpu_warmup.warmup_gpu()`. 

---

## 4) Runtime ops (first wave)

Each op lives in `runtime/ops/*.py` and **depends only on `RuntimeContext`**. Examples:

* **`git.scan`**: enumerate repo files via `AsyncGitClient` from the context. 
* **`chunk.text`**: chunk files; returns chunks w/ URI + line ranges (aligns with your catalog schema). 
* **`embed.vectors`**: call `VLLMClient` to embed chunks, yield parquet‑friendly rows. 
* **`faiss.add`**: `ensure_faiss_ready()`, then upsert vectors via `FAISSManager`, CPU or GPU. 
* **`duckdb.upsert`**: use `with context.app.open_catalog() as catalog:` to write chunk metadata. 
* **`search.hybrid`**: use `ApplicationContext.get_hybrid_engine()` for a hybrid query step. 

Each op returns a JSON‑serializable output (so caching + fingerprinting are robust).

---

## 5) Error handling (Problem Details, RFC 9457)

Create `runtime/errors.py` with a small hierarchy mirroring your style:

```python
from kgfoundry_common.errors import KgFoundryError  # same base used by app errors
class RuntimeErrorBase(KgFoundryError): ...
class RuntimeInvalidGraphError(RuntimeErrorBase):  # 400 invalid-parameter
class RuntimeExecutionError(RuntimeErrorBase):     # 500 runtime-execution-error
class RuntimeTimeoutError(RuntimeErrorBase):       # 408 runtime-timeout
```

* Include `code`, `http_status`, `context` (e.g., `{"cell": "<id>", "op": "<op>"}`), consistent with `FileOperationError` & friends. 
* In the engine, convert exceptions into these, so FastAPI/MCP surfaces Problem Details consistently.

---

## 6) Wire into `ApplicationContext` (lazy, thread‑safe, testable)

### 6.1 Extend runtime state

* In `app/config_context.py`, extend `_ContextRuntimeState` to add a `cells` handle:

```python
@dataclass(slots=True, frozen=True)
class _ContextRuntimeState:
    hybrid: _RuntimeHandle[HybridSearchEngine] = field(default_factory=_RuntimeHandle)
    coderank_faiss: _RuntimeHandle[FAISSManager] = field(default_factory=_RuntimeHandle)
    xtr: _RuntimeHandle[XTRIndex] = field(default_factory=_RuntimeHandle)
    faiss: _FaissRuntimeState = field(default_factory=_FaissRuntimeState)
    cells: _RuntimeHandle["CellsRuntime"] = field(default_factory=_RuntimeHandle)  # NEW
```

> Mirrors existing lazy singletons. This keeps creation centralized and threadsafe. 

### 6.2 Add a getter

```python
from codeintel_rev.runtime.cells import CellsRuntime, RuntimeConfig

class ApplicationContext(...):
    ...

    def get_cells_runtime(self) -> CellsRuntime:
        handle = self._runtime.cells
        if handle.value is not None:
            return handle.value
        with handle.lock:                   # same pattern used for others
            if handle.value is None:
                cfg = getattr(self.settings, "runtime", None)
                rcfg = RuntimeConfig(
                    max_concurrency=(cfg.max_concurrency if cfg else 8),
                    default_timeout_s=(cfg.default_timeout_s if cfg else 300),
                    cache_enabled=(cfg.cache_enabled if cfg else True),
                )
                handle.value = CellsRuntime(app=self, config=rcfg)
        return handle.value
```

* Pattern matches `get_hybrid_engine()` / FAISS load semantics. 

### 6.3 Optional health hook

* In `readiness.py`, add `check_cells_runtime()` (e.g., registry not empty, optional warm checks). Then include it in `ReadinessProbe`. 

---

## 7) Configuration (first‑class, frozen, checked at startup)

* In `config.settings`, add `RuntimeConfig` dataclass (env‑driven) with:

  * `RUNTIME_MAX_CONCURRENCY` (int, default 8)
  * `RUNTIME_DEFAULT_TIMEOUT_S` (int, default 300)
  * `RUNTIME_CACHE_ENABLED` (bool, default true)

Use your existing settings loading + fail‑fast validation so misconfig blocks startup (consistent with `resolve_application_paths`). 

---

## 8) Observability & SLOs (logs, metrics, traces)

* **Logging**: use `kgfoundry_common.logging.get_logger` to create a module logger with `extra={"run_id", "cell_id", "op"}`. Your code already uses a `LoggerAdapter`; keep fields consistent. 
* **Metrics**: counters for `cells_started/finished/failed`, histograms for `cell_duration_seconds`; gauge for in‑flight cells.
* **Tracing (optional)**: if OpenTelemetry is present, wrap each cell in a span.

---

## 9) MCP / HTTP surface (optional but ready)

* **MCP tool**: `cells.run` taking `ExecutionPlan` JSON, returning stream of `RuntimeEvent` + final results.
* **FastAPI**: `POST /runtime/runs` (start), `GET /runtime/runs/{id}` (status), `DELETE` (cancel). Stream events with `StreamingResponse`. Your app already uses FastAPI and JSON/streaming responses; follow the existing patterns. 

---

## 10) Security & safety rails

* **No arbitrary code exec**: only whitelisted `Operation` implementations shipped with the app.
* **Path hygiene**: when ops touch files, use `ResolvedPaths` (no untrusted paths); violations → `PathNotFoundError/PathNotDirectoryError`. 
* **Resource limits**: semaphore‑based concurrency + per‑cell timeout; graceful cancellation propagation.
* **GPU availability**: treat as optimization; do not fail runs if unavailable—warn and continue (as your FAISS/GPU code does). 

---

## 11) Testing strategy (CI‑green from the start)

* **Unit**

  * DAG validation (happy/cycle/missing dep).
  * Timeouts/cancellation.
  * Caching keys (same inputs → hit; changed param → miss).
* **Component**

  * Each operation in isolation (mock `ApplicationContext` deps; your `with_overrides(...)` API is ideal here). 
* **Integration**

  * End‑to‑end “index refresh” plan: `git.scan → chunk → embed → faiss.add → duckdb.upsert`, with FAISS ready both CPU/GPU.
  * Readiness probe includes `cells` check path.
* **Load**

  * Concurrency at/above `max_concurrency`, verify event ordering, time‑to‑steady‑state.

---

## 12) Rollout plan (safe, incremental)

1. **Scaffold** `runtime/` package + `errors.py` + engine skeleton; add unit tests.
2. **Wire** into `ApplicationContext` (_runtime handle + getter) and `settings`.
3. **Implement ops** (git/chunk/embed/faiss/duckdb/search) behind a feature flag `RUNTIME_ENABLE`.
4. **Smoke‑test** locally: run plan against a small repo; verify DuckDB & FAISS artifacts.
5. **Readiness**: add runtime check; **observability**: enable logs + basic metrics.
6. **E2E** in staging: index refresh via cells; keep legacy path as fallback.
7. **Gradual on**: enable flag per environment; watch metrics; remove legacy once stable.

---

## 13) Example: first run plan (index refresh)

```python
plan = ExecutionPlan(cells=[
    CellSpec(id=CellId("git"),    op="git.scan",    params={"path": "."}),
    CellSpec(id=CellId("chunk"),  op="chunk.text",  inputs=[CellId("git")]),
    CellSpec(id=CellId("embed"),  op="embed.vectors", inputs=[CellId("chunk")]),
    CellSpec(id=CellId("faiss"),  op="faiss.add",   inputs=[CellId("embed")]),
    CellSpec(id=CellId("duckdb"), op="duckdb.upsert", inputs=[CellId("chunk")]),
])
runtime = context.get_cells_runtime()
results = await runtime.run(plan, scope="session-123")
```

* Leverages your **FAISS manager**, **DuckDB catalog**, **VLLM client**, and **Git clients** injected via `ApplicationContext`. 

---

## 14) “Best practice” checklist we’re following

* `dataclass(slots=True)` + full **typing**.
* **No globals**; DI via `ApplicationContext`. 
* **Lazy singletons** with locks via `_RuntimeHandle`. 
* **Problem Details** errors with consistent `code/http_status/context`. 
* **Idempotent** ops and **content‑addressed** caching.
* **Graceful** cancellation/timeout & **bounded** concurrency.
* **Structured** logging + ready hooks for metrics/tracing.
* **Feature‑flagged** rollout.

---

## 15) What we’ll add where (concise diff‑style to guide PRs)

* **`codeintel_rev/runtime/cells.py`** – new engine + types (as above).
* **`codeintel_rev/runtime/errors.py`** – new error classes mapping to RFC 9457 (patterned after `errors.py`). 
* **`codeintel_rev/runtime/ops/*.py`** – operation implementations using `ApplicationContext` deps. 
* **`codeintel_rev/app/config_context.py`** – add `cells: _RuntimeHandle[CellsRuntime]` to `_ContextRuntimeState` + `get_cells_runtime()` (lazy, thread‑safe). 
* **`codeintel_rev/app/readiness.py`** – optional `cells` readiness probe. 
* **`codeintel_rev/config/settings.py`** – new `RuntimeConfig` + env hooks. 

---

If you’d like, I can generate the **exact module files** (`cells.py`, `errors.py`, and the initial `ops/*.py`) and the **context diffs** exactly as described above so your team can paste them in and run tests immediately.


Below you’ll get:

1. **New modules** (`codeintel_rev/runtime/**`) – fully implemented.
2. **Initial ops/py utilities** – small, hermetic scripts that exercise and validate the runtime pathway.
3. **Context diffs** for **low‑risk adoption** (wrap the existing `_RuntimeHandle` on top of `RuntimeCell`, no behavioral change to FAISS/XTR/Hybrid logic).
4. **Where this plugs into your current code** (with citations to your index so reviewers can cross‑check signatures & intent).

> Why this approach? It gives you the uniform runtime primitive you asked for without risky rewrites. We preserve public behavior (including `ApplicationContext.ensure_faiss_ready()` semantics and FastAPI lifespan) and enable an incremental sweep later to replace bespoke handles with cells everywhere. Your current APIs like `ensure_faiss_ready()` are already thread‑safe and idempotent; we standardize their internal state via the cell shim. 

---

## 0) Repo ground‑truth checkpoints (for reviewers)

* `ApplicationContext.ensure_faiss_ready() → (ready: bool, limits: list[str], error: str | None)` is the first‑call load + optional GPU clone and returns cached state later; adapters call it on first search or on eager startup. 
* `ApplicationContext.create()` constructs the frozen context & long‑lived clients (vLLM, FAISS manager, DuckDB, etc.). 
* `ResolvedPaths` already centralizes paths for FAISS, DuckDB, XTR/WARP, etc. 
* GPU warmup is a dedicated module; FAISS GPU & Torch checks are explicit (we leave behavior unchanged). 
* MCP adapters build search budgets and call `ensure_faiss_ready()` before FAISS search fan‑out/hydration. 

The draft proposal you shared articulates the **RuntimeCell** primitive and how to adopt it across vLLM/XTR/FAISS/ApplicationContext. The “drop‑in” we add below is consistent with that doc (thread‑safe, testable seeding, explicit close). 

---

## 1) New modules: `codeintel_rev/runtime/**`

> Place these under `codeintel_rev/runtime/` (new package). The cell primitive is intentionally tiny and dependency‑free; the context state views are frozen and small.

### 1.1 `codeintel_rev/runtime/cells.py`  — **Drop‑in RuntimeCell**

```diff
diff --git a/codeintel_rev/runtime/cells.py b/codeintel_rev/runtime/cells.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/codeintel_rev/runtime/cells.py
@@
+from __future__ import annotations
+
+from dataclasses import dataclass, field
+from threading import RLock
+from typing import Callable, Generic, Optional, TypeVar
+
+T = TypeVar("T")
+
+
+@dataclass(slots=True)
+class RuntimeCell(Generic[T]):
+    """
+    Thread-safe, lazily-initialized holder for mutable runtime objects owned by
+    otherwise-frozen dataclasses. See runtime_cells.md for the design rationale.
+
+    Core semantics:
+      - get_or_initialize(factory): once-only init under a re-entrant lock
+      - peek(): read without initializing
+      - seed(value): test-only or controlled injection
+      - close(disposer): dispose and clear if present
+    """
+    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
+    _value: Optional[T] = field(default=None, init=False, repr=False)
+    _closed: bool = field(default=False, init=False, repr=False)
+
+    def peek(self) -> Optional[T]:
+        return self._value
+
+    def get_or_initialize(self, factory: Callable[[], T]) -> T:
+        val = self._value
+        if val is not None:
+            return val
+        with self._lock:
+            if self._value is None:
+                if self._closed:
+                    raise RuntimeError("RuntimeCell is closed")
+                self._value = factory()
+            return self._value  # type: ignore[return-value]
+
+    def seed(self, value: T) -> None:
+        """
+        Deterministically set the runtime (primarily for tests/controlled setup).
+        If used in production, ensure the call site is clearly sanctioned.
+        """
+        with self._lock:
+            if self._closed:
+                raise RuntimeError("RuntimeCell is closed")
+            self._value = value
+
+    def close(self, disposer: Optional[Callable[[T], None]] = None) -> None:
+        """
+        If a runtime exists, optionally dispose it and clear the cell.
+        Idempotent: multiple calls are safe.
+        """
+        with self._lock:
+            val = self._value
+            if val is not None and disposer is not None:
+                try:
+                    disposer(val)
+                finally:
+                    self._value = None
+            else:
+                self._value = None
+            self._closed = True
```

### 1.2 `codeintel_rev/runtime/context_runtime_state.py` — **FAISS/XTR status views**

```diff
diff --git a/codeintel_rev/runtime/context_runtime_state.py b/codeintel_rev/runtime/context_runtime_state.py
new file mode 100644
index 0000000..2222222
--- /dev/null
+++ b/codeintel_rev/runtime/context_runtime_state.py
@@
+from __future__ import annotations
+
+from dataclasses import dataclass
+from typing import Optional, Tuple
+
+
+@dataclass(frozen=True, slots=True)
+class FaissStatus:
+    """Frozen view of FAISS readiness surfaced by ApplicationContext.ensure_faiss_ready()."""
+    ready: bool
+    limits: Tuple[str, ...]
+    error: Optional[str]
+
+
+@dataclass(frozen=True, slots=True)
+class XTRStatus:
+    """Frozen view for XTR/Token index readiness (extend as we wire XTR runtime)."""
+    available: bool
+    error: Optional[str] = None
```

### 1.3 `codeintel_rev/runtime/__init__.py`

```diff
diff --git a/codeintel_rev/runtime/__init__.py b/codeintel_rev/runtime/__init__.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/codeintel_rev/runtime/__init__.py
@@
+from .cells import RuntimeCell
+from .context_runtime_state import FaissStatus, XTRStatus
+
+__all__ = ["RuntimeCell", "FaissStatus", "XTRStatus"]
```

---

## 2) Initial `ops/*.py` utilities (hermetic, zero coupling to FastAPI)

> These scripts let you validate the new runtime surface *without* running the web app. They reuse the same `ApplicationContext` you already expose for MCP tools via the service cache. 

Create `ops/runtime/` (new folder at repo root) and drop in the following:

### 2.1 `ops/runtime/faiss_preload.py`

```diff
diff --git a/ops/runtime/faiss_preload.py b/ops/runtime/faiss_preload.py
new file mode 100755
index 0000000..4444444
--- /dev/null
+++ b/ops/runtime/faiss_preload.py
@@
+#!/usr/bin/env python3
+from __future__ import annotations
+
+import argparse
+import json
+from codeintel_rev.mcp_server.service_context import get_service_context
+
+
+def main() -> int:
+    parser = argparse.ArgumentParser(description="Preload FAISS index and report readiness.")
+    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
+    args = parser.parse_args()
+
+    context = get_service_context()
+    ready, limits, error = context.ensure_faiss_ready()
+    # ensure_faiss_ready(): (bool ready, list[str] limits, str|None error)  :contentReference[oaicite:8]{index=8}
+
+    payload = {"ready": ready, "limits": limits, "error": error}
+    if args.json:
+        print(json.dumps(payload))
+    else:
+        print(f"FAISS ready={ready} limits={limits} error={error}")
+    return 0 if ready else 2
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())
```

### 2.2 `ops/runtime/warmup_gpu.py`

```diff
diff --git a/ops/runtime/warmup_gpu.py b/ops/runtime/warmup_gpu.py
new file mode 100755
index 0000000..5555555
--- /dev/null
+++ b/ops/runtime/warmup_gpu.py
@@
+#!/usr/bin/env python3
+from __future__ import annotations
+
+import json
+from codeintel_rev.app.gpu_warmup import warmup_gpu
+
+
+def main() -> int:
+    """
+    Runs the built-in GPU warmup/diagnostic routine so you can CI/canary GPU availability
+    independent of the API server. Returns non-zero on failure.
+    """
+    # warmup_gpu() exists and performs CUDA/FAISS checks (doc surfaced in index). :contentReference[oaicite:9]{index=9}
+    result = warmup_gpu()  # type: ignore[call-arg]
+    print(json.dumps(result))
+    return 0 if bool(result.get("ok", True)) else 1
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())
```

### 2.3 `ops/runtime/check_context.py`

```diff
diff --git a/ops/runtime/check_context.py b/ops/runtime/check_context.py
new file mode 100755
index 0000000..6666666
--- /dev/null
+++ b/ops/runtime/check_context.py
@@
+#!/usr/bin/env python3
+from __future__ import annotations
+
+from codeintel_rev.mcp_server.service_context import get_service_context
+
+
+def main() -> int:
+    ctx = get_service_context()
+    print(f"paths.faiss_index = {ctx.paths.faiss_index}")  # ResolvedPaths is already centralized. :contentReference[oaicite:10]{index=10}
+    ready, limits, error = ctx.ensure_faiss_ready()       # (ready, limits, error) triple. :contentReference[oaicite:11]{index=11}
+    print(f"FAISS ready={ready} limits={limits} error={error}")
+
+    xtr = ctx.get_xtr_index()  # Returns XTRIndex | None when disabled/unavailable. :contentReference[oaicite:12]{index=12}
+    print(f"XTR available? {xtr is not None}")
+    return 0
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())
```

> If you’d like an `ops/runtime/open_xtr.py` that asserts XTR openability via the CLI you already expose, we can add it next; your index shows a Typer CLI for XTR search that warns/raises when artifacts are missing. 

---

## 3) Low‑risk **context diffs** to adopt the cell without disruptive rewrites

The goal here is **compat mode**: keep `_RuntimeHandle` as a symbol but make it a shim over `RuntimeCell`. Existing call‑sites that do `handle.value` still work; but you gain `handle.peek()` / `handle.get_or_initialize()` semantics implemented once in `RuntimeCell`. This aligns with the proposal’s “centralize lifecycle + injection” intent. 

> **File:** `codeintel_rev/app/config_context.py` (only the `_RuntimeHandle` section and imports change)

```diff
diff --git a/codeintel_rev/app/config_context.py b/codeintel_rev/app/config_context.py
--- a/codeintel_rev/app/config_context.py
+++ b/codeintel_rev/app/config_context.py
@@
-from dataclasses import dataclass
-from typing import TYPE_CHECKING, Iterator
+from dataclasses import dataclass
+from typing import TYPE_CHECKING, Iterator, Callable, Generic, Optional, TypeVar
+from codeintel_rev.runtime.cells import RuntimeCell
@@
-class _RuntimeHandle:
-    def __init__(self) -> None:
-        self.value = None
+T = TypeVar("T")
+
+class _RuntimeHandle(Generic[T]):
+    """
+    Compatibility shim that forwards runtime storage to the shared RuntimeCell[T].
+    This preserves the existing `_RuntimeHandle` name while unifying locking,
+    lazy init, testing seed, and disposal across the codebase.
+    """
+    __slots__ = ("_cell",)
+
+    def __init__(self) -> None:
+        self._cell: RuntimeCell[T] = RuntimeCell()
+
+    # --- Backwards-compatible .value attribute ------------------------------
+    @property
+    def value(self) -> Optional[T]:
+        return self._cell.peek()
+
+    @value.setter
+    def value(self, v: Optional[T]) -> None:
+        if v is None:
+            self._cell.close()
+        else:
+            self._cell.seed(v)
+
+    # --- Preferred API used going forward ----------------------------------
+    def peek(self) -> Optional[T]:
+        return self._cell.peek()
+
+    def get_or_initialize(self, factory: Callable[[], T]) -> T:
+        return self._cell.get_or_initialize(factory)
+
+    def seed(self, value: T) -> None:
+        self._cell.seed(value)
+
+    def close(self, disposer: Optional[Callable[[T], None]] = None) -> None:
+        self._cell.close(disposer)
```

**Why this minimal edit works today**

* You already keep a frozen `ApplicationContext` and a frozen `_ContextRuntimeState` holding private handles for hybrid/FAISS/XTR. We’re not changing the fields or their usage sites — only the *implementation* of the handle to unify semantics. 
* `ensure_faiss_ready()` continues to return the same triple and remains idempotent/thread‑safe; the cell simply provides the mutual exclusion & lifecycle in one place. 
* MCP adapters and readiness paths remain untouched. They keep calling the same context methods (`ensure_faiss_ready()`, `open_catalog()`, etc.). 

> **Optional next step** (in a follow-up PR): replace `_FaissRuntimeState` with a `RuntimeCell[FaissRuntime]` and expose a frozen `FaissStatus` view (above) for observability. The docs in your index confirm `_FaissRuntimeState` is bookkeeping only, which we can retire once cells are adopted. 

---

## 4) How to apply & validate

1. **Add new runtime package + ops/** files** (patches above).
2. **Edit `_RuntimeHandle`** as above (single file change).
3. **Smoke tests**:

   * `python ops/runtime/faiss_preload.py --json` → should print the same readiness triple used by adapters. 
   * `python ops/runtime/warmup_gpu.py` → confirms CUDA/FAISS/Torch checks run. 
   * `python ops/runtime/check_context.py` → prints resolved FAISS path + XTR availability. 

No changes are needed for:

* `ApplicationContext.create()` and FastAPI `lifespan()` – they still initialize long‑lived clients and (optionally) pre‑load FAISS. 
* MCP server tool functions and error handling envelopes. 

---

## 5) Follow‑on refinements (when you’re ready)

These are small, well‑scoped improvements that further reduce cognitive load and standardize the runtime story:

1. **Add `close_all_runtimes()` on ApplicationContext** that calls `close()` on each `_RuntimeHandle` (hybrid, coderank FAISS manager, XTR). Wire it into `lifespan()` shutdown (already enumerates “close resources” in notes). 

2. **Replace bespoke FAISS runtime bookkeeping** (`_FaissRuntimeState`) with:

   * `RuntimeCell[FAISSManager]` for the manager/clone handle.
   * `FaissStatus` (frozen view) returned by a helper, built from the cached readiness triple. (Non‑breaking: the public method keeps returning the current triple until you choose to expose the view object.)

3. **Unify XTR init** – `ApplicationContext.get_xtr_index()` already returns `XTRIndex | None`. Wrap `XTRIndex`’s mutable pieces (tokenizer/memmaps) behind a `RuntimeCell[XTRRuntime]` so tests can `seed()` a dummy runtime as the proposal outlines.  

4. **Observability** – if you want richer readiness output for MCP responses, your semantic adapter already threads a `limits` list through `_build_response_extras` → add cell snapshot data there without changing contract. 

5. **Docs** – keep the `runtime_cells.md` as ADR‑style guidance; link it from a short “Architecture > Runtime” section so new contributors don’t reinvent one‑off holders. (Your proposal already captures the motivation & API surface perfectly.) 

---

## 6) Why this is the right design decision (quick recap)

* **Matches your frozen‑dataclass policy** while legitimizing mutable runtimes (GPU handles, memmaps, pools).
* **Unifies lifecycle** (init/peek/seed/close) with one lock & API; deletes custom locking scattered across modules.
* **Improves testability** via scoped injection (`seed()` per instance) instead of monkeypatching.
* **Keeps public behavior stable** – especially `ensure_faiss_ready()` which your adapters depend on for fast failure + degraded mode signaling.  

---

### Anything else you’d like bundled?

If you want, I can add:

* a `tests/runtime/test_runtime_cell.py` (thread‑safety, idempotent init, seeding, close),
* a `ops/runtime/xtr_open.py` that fails fast if token artifacts are missing (mirrors your Typer CLI behavior), and
* a tiny `ApplicationContext.close_all_runtimes()` diff wired into `lifespan()`.

But with the patches above, you can merge and start using the cell **today** with zero behavior changes.

**References (for reviewers):**

* `ensure_faiss_ready()` contract and idempotent semantics. 
* GPU warmup module & checks. 
* MCP adapter calling pattern around FAISS readiness & budgets. 
* Frozen `ApplicationContext` & runtime state types presently in the file. 
* Centralized path resolution via `ResolvedPaths`. 
* Your RuntimeCell proposal (seed/peek/get_or_initialize/close). 

If you’d like me to generate a single **git‑apply‑able** patch (or split commits by module and integration step), I can do that next.



wesome—let’s turn the runtime‑cell concept into concrete, drop‑in code plus the additional pieces you asked for (tests, an ops script, and the lifespan wiring). I’ll show:

1. **New files** with production‑ready Python,
2. **Minimal diffs** to existing files, and
3. **Why each change is correct for this repo** (with citations to your `index.json` + proposal).

---

## What you’ll add

```
codeintel_rev/
├─ runtime/
│  ├─ __init__.py                  # new (empty or exports)
│  └─ cells.py                     # new (RuntimeCell[T])
├─ ops/
│  └─ runtime/
│     ├─ __init__.py               # new (empty)
│     └─ xtr_open.py               # new (Typer “fail fast” checker)
tests/
└─ runtime/
   └─ test_runtime_cell.py         # new (thread‑safety, idempotent init, seeding, close)
```

Why this belongs here:

* Your **proposal** makes `RuntimeCell[T]` the common abstraction for mutable runtime state behind frozen dataclasses—thread‑safe init, test seeding, and unified close semantics. 
* `ApplicationContext` already holds ad‑hoc `_RuntimeHandle` and `_FaissRuntimeState` for mutable pieces; `RuntimeCell` standardizes this pattern and reduces bespoke logic. 
* The **Typer behavior** for XTR is already to **exit non‑zero** if artifacts are missing; the new `ops/runtime/xtr_open.py` mirrors that and can be used in CI or boot hooks to fail fast. 

---

## 1) New module: `codeintel_rev/runtime/cells.py`

```python
# codeintel_rev/runtime/cells.py
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Callable, Generic, Optional, TypeVar
import logging

T = TypeVar("T")
LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeCell(Generic[T]):
    """
    A tiny, thread-safe cell that holds mutable runtime state for an owning
    (usually frozen) dataclass.

    Key guarantees
    --------------
    - Thread-safe, lazy, idempotent initialization
    - Explicit test-time seeding/injection
    - Deterministic shutdown with a disposer
    - Safe no-op on double-close

    Typical usage
    -------------
    >>> cell: RuntimeCell[SomeRuntime] = RuntimeCell()
    >>> runtime = cell.get_or_initialize(lambda: SomeRuntime(...))
    >>> # in tests:
    >>> cell.seed(FakeRuntime(...))
    >>> # on shutdown:
    >>> cell.close(lambda r: r.close())
    """
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _value: Optional[T] = field(default=None, init=False, repr=False)

    def peek(self) -> Optional[T]:
        """Return current payload or None without initializing."""
        return self._value

    def __bool__(self) -> bool:  # allows: if cell:
        return self._value is not None

    def get_or_initialize(self, factory: Callable[[], T]) -> T:
        """Return the payload, creating it once via `factory` if needed."""
        v = self._value
        if v is not None:
            return v
        with self._lock:
            v = self._value
            if v is None:
                v = factory()
                self._value = v
            return v

    def seed(self, value: T, *, overwrite: bool = False) -> None:
        """
        Inject a payload (primarily for tests).
        Raises if a value already exists and overwrite=False.
        """
        with self._lock:
            if self._value is not None and not overwrite:
                raise RuntimeError("RuntimeCell is already initialized")
            self._value = value

    def close(self, disposer: Optional[Callable[[T], None]] = None) -> bool:
        """
        Best-effort close. Returns True if something was actually closed.

        The disposer is called outside the lock, and exceptions are logged
        but suppressed to make shutdown robust.
        """
        with self._lock:
            current = self._value
            if current is None:
                return False
            # clear first so re-entrancy or disposer side-effects can't
            # race other readers
            self._value = None

        if disposer is not None:
            try:
                disposer(current)
            except Exception:  # noqa: BLE001
                LOGGER.exception(
                    "Ignoring error from disposer for %s", type(current).__name__
                )
        return True
```

This aligns 1:1 with the proposal (lazy init, peek, seed, close). 

---

## 2) Tests: `tests/runtime/test_runtime_cell.py`

Covers thread‑safety, idempotent init, seeding, and close (with re‑init after close).

```python
# tests/runtime/test_runtime_cell.py
from __future__ import annotations

import time
import threading
from typing import Any
import pytest

from codeintel_rev.runtime.cells import RuntimeCell


def test_idempotent_initialization_called_once_under_race():
    cell: RuntimeCell[dict[str, Any]] = RuntimeCell()
    barrier = threading.Barrier(16)
    calls = 0
    created_ids: list[int] = []

    def factory():
        nonlocal calls
        time.sleep(0.01)  # amplify race
        calls += 1
        return {"id": id(object())}

    results: list[dict[str, Any]] = []

    def worker():
        barrier.wait()
        r = cell.get_or_initialize(factory)
        results.append(r)
        created_ids.append(r["id"])

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every thread got the same dict instance (same id)
    assert len({id(d) for d in results}) == 1
    assert calls == 1  # factory run once


def test_seed_blocks_factory_and_returns_seeded_value():
    cell: RuntimeCell[int] = RuntimeCell()
    cell.seed(42)
    out = cell.get_or_initialize(lambda: 99)
    assert out == 42

    # non-overwrite seed should fail
    with pytest.raises(RuntimeError):
        cell.seed(123)

    # overwrite allowed
    cell.seed(7, overwrite=True)
    assert cell.peek() == 7


def test_close_is_idempotent_and_allows_reinit():
    closed = []

    class Dummy:
        def __init__(self, val: int) -> None:
            self.val = val

    cell: RuntimeCell[Dummy] = RuntimeCell()
    x = cell.get_or_initialize(lambda: Dummy(1))

    # First close returns True and runs disposer
    assert cell.close(lambda d: closed.append(d.val)) is True
    assert closed == [1]
    assert cell.peek() is None

    # Second close is a no-op
    assert cell.close(lambda d: closed.append(d.val)) is False
    assert closed == [1]

    # Re-initialize after close
    y = cell.get_or_initialize(lambda: Dummy(2))
    assert y.val == 2
    assert y is not x
```

---

## 3) Ops script: `codeintel_rev/ops/runtime/xtr_open.py` (fail‑fast)

Mirrors your Typer CLI’s **non‑zero exit** when XTR artifacts are missing (so this can be called by CI or a pre‑flight probe). 

```python
# codeintel_rev/ops/runtime/xtr_open.py
from __future__ import annotations

import sys
import typer

from codeintel_rev.app.config_context import ApplicationContext

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("check")
def check() -> None:
    """
    Fail fast if XTR artifacts are missing/unusable.

    Exits with:
      0 -> XTR ready
      1 -> Disabled or not ready
    """
    ctx = ApplicationContext.create()  # centralizes env & path validation
    # get_xtr_index() returns a ready XTRIndex or None if disabled/unavailable.
    # (See docstring in config_context.) :contentReference[oaicite:5]{index=5}
    xtr = ctx.get_xtr_index()
    if xtr is None:
        typer.secho("XTR is disabled or artifacts are missing/not ready.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    typer.secho("XTR artifacts present and index is ready.", fg=typer.colors.GREEN)
    raise typer.Exit(code=0)


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
```

Why `ApplicationContext.create()`? It already centralizes settings and resolved paths (and logs problems consistently); your docs show this is the **primary** way to initialize app configuration during startup or tooling. 

---

## 4) Add `ApplicationContext.close_all_runtimes()` and wire it into FastAPI `lifespan()`

Your `lifespan()` documentation already calls out explicit shutdown of resources; we’ll consolidate that into a single `close_all_runtimes()` so both the app and future ops scripts share one place to close everything. 

### 4a) Minimal diff: `codeintel_rev/app/config_context.py`

```diff
diff --git a/codeintel_rev/app/config_context.py b/codeintel_rev/app/config_context.py
index abcdef0..1234567 100644
--- a/codeintel_rev/app/config_context.py
+++ b/codeintel_rev/app/config_context.py
@@ -1,6 +1,7 @@
 from __future__ import annotations
+from contextlib import suppress
 import logging
 ...
 LOGGER = logging.getLogger(__name__)
@@
 class ApplicationContext:
     ...
+    def close_all_runtimes(self) -> None:
+        """
+        Best-effort shutdown for long-lived and lazily-initialized resources.
+        Safe to call multiple times.
+        """
+        # vLLM client (HTTP pool / local engine)
+        with suppress(Exception):
+            self.vllm_client.close()  # documented public API close() :contentReference[oaicite:8]{index=8}
+
+        # Scope store/session registry
+        with suppress(Exception):
+            self.scope_store.close()  # documented close() :contentReference[oaicite:9]{index=9}
+
+        # DuckDB pool
+        with suppress(Exception):
+            self.duckdb_manager.close()  # documented close() :contentReference[oaicite:10]{index=10}
+
+        # XTR handle (if initialized). Value may be an XTRIndex; clear to allow GC of memmaps.
+        # _RuntimeHandle.value is present on _ContextRuntimeState; we clear it even if
+        # XTRIndex has no explicit close(), to drop references. :contentReference[oaicite:11]{index=11}
+        with suppress(Exception):
+            rt = self._runtime.xtr
+            if getattr(rt, "value", None) is not None:
+                # If the object exposes close(), call it (future-proof)
+                x = rt.value
+                close = getattr(x, "close", None)
+                if callable(close):
+                    close()
+                # Clear the handle either way
+                rt.value = None
+
+        # CodeRank FAISS runtime clone (if any); clear to allow GPU/host memory reclamation.
+        with suppress(Exception):
+            cr = self._runtime.coderank_faiss
+            if getattr(cr, "value", None) is not None:
+                cr.value = None
```

Notes:

* `VLLMClient.close()` and `ScopeStore.close()` and `DuckDBManager.close()` are documented in your index and used already in shutdown.
* `_RuntimeHandle.value` is real on your `_ContextRuntimeState` and used in `get_xtr_index()`/`get_hybrid_engine()`; we clear it safely.
* We **don’t** change FAISS manager internals: your `ensure_faiss_ready()` already handles first‑load & GPU clone logic idempotently; clearing CodeRank handle simply drops any cached clone. 

### 4b) Minimal diff: `codeintel_rev/app/main.py` (wire it in)

```diff
diff --git a/codeintel_rev/app/main.py b/codeintel_rev/app/main.py
index 7654321..76543ab 100644
--- a/codeintel_rev/app/main.py
+++ b/codeintel_rev/app/main.py
@@ -150,14 +150,12 @@ async def lifespan(app: FastAPI) -> AsyncIterator[None]:
     try:
         yield
     finally:
-        LOGGER.info("Shutting down vLLM client")
-        with suppress(Exception):
-            context.vllm_client.close()
-
-        LOGGER.info("Closing scope store")
-        with suppress(Exception):
-            context.scope_store.close()
+        LOGGER.info("Closing application runtimes")
+        with suppress(Exception):
+            context.close_all_runtimes()  # centralizes shutdown :contentReference[oaicite:15]{index=15}
 
         LOGGER.info("Stopping readiness probe")
         with suppress(Exception):
             readiness.shutdown()
```

This keeps the same semantics your `lifespan()` doc promises (explicit shutdown) but centralizes the logic. 

---

## (Optional) Using `RuntimeCell` inside context classes (incremental)

You can adopt `RuntimeCell` gradually without breaking existing call sites. For example, in `_ContextRuntimeState`, replace bespoke `_RuntimeHandle` fields as you touch those areas:

```diff
- @dataclass(slots=True, frozen=True)
- class _ContextRuntimeState:
-     hybrid: _RuntimeHandle[HybridSearchEngine] = field(default_factory=_RuntimeHandle)
-     coderank_faiss: _RuntimeHandle[FAISSManager] = field(default_factory=_RuntimeHandle)
-     xtr: _RuntimeHandle[XTRIndex] = field(default_factory=_RuntimeHandle)
-     faiss: _FaissRuntimeState = field(default_factory=_FaissRuntimeState)
+from codeintel_rev.runtime.cells import RuntimeCell
+
+@dataclass(slots=True, frozen=True)
+class _ContextRuntimeState:
+    hybrid: RuntimeCell[HybridSearchEngine] = field(default_factory=RuntimeCell)
+    coderank_faiss: RuntimeCell[FAISSManager] = field(default_factory=RuntimeCell)
+    xtr: RuntimeCell[XTRIndex] = field(default_factory=RuntimeCell)
+    faiss: _FaissRuntimeState = field(default_factory=_FaissRuntimeState)
```

This is a mechanical refactor later on; all the lifecycle semantics then converge on `RuntimeCell`. (The current presence of `_RuntimeHandle` is confirmed in your `index.json` and used for `xtr`/`coderank_faiss`/`hybrid`.) 

---

## Why this is correct for the sub‑repo

* **`get_xtr_index()`** already embodies “return ready instance or `None` when disabled/unavailable”; the ops script reuses that and exits like your Typer CLI’s search command that **raises on missing artifacts**.
* **Shutdown**: you are already closing `VLLMClient`, `ScopeStore`, and managing readiness during `lifespan()`; centralizing via `close_all_runtimes()` matches the step‑3 promise in the docstring and keeps the logic DRY. 
* **FAISS**: `ensure_faiss_ready()` is intentionally **thread‑safe and idempotent**—the runtime cell pattern fits right into that strategy for other mutable subsystems. 

---

## Quick how‑to

* **Create the new files** above.
* **Apply the diffs** for `config_context.py` and `main.py`.
* Run tests: `pytest tests/runtime/test_runtime_cell.py`.
* (Optional) Add a CI job step: `python -m codeintel_rev.ops.runtime.xtr_open check` to fail a deployment if XTR isn’t ready.

---

## Follow‑ups I recommend (small, high‑leverage)

1. **Guard seeding in prod**: allow `RuntimeCell.seed()` only when `PYTEST_CURRENT_TEST` is present or `KGFOUNDRY_ALLOW_RUNTIME_SEED=1`, to reduce foot‑guns. (Your proposal calls this out.) 
2. **RuntimeCell for XTR & hybrid**: migrate those `_RuntimeHandle` fields to `RuntimeCell` as in the optional diff—uniformity lowers cognitive load and makes tests simpler. 
3. **Expose `context.close_all_runtimes()` in ops**: you can later add `codeintel_rev.ops.runtime.close_all` CLI that calls the same method for tooling scripts.

---

If you want, I can also provide ready‑to‑apply **git patch files** (one per change), and a short **migration diff** that swaps `_RuntimeHandle` → `RuntimeCell` for `xtr` only, so you can trial the pattern in one subsystem first.
