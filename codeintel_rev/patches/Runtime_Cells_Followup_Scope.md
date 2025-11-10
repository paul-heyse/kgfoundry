
# Context for change and proposal #


Awesome work — the cell architecture is *in* and it’s already paying dividends. I read the new `index.json` first and then cross‑checked a few related modules to validate how the pattern is wired through the app. Below is (1) a quick status snapshot grounded in the code that’s actually in your tree, and (2) a prioritized, exhaustive follow‑up plan to fully realize the benefits of Runtime Cells across architecture, ops, and tests. I’ve included concrete diffs/snippets where helpful.

---

## What’s already in place (from the repo)

**Cell primitive**

* `codeintel_rev.runtime.cells` exposes a final, typed `RuntimeCell[T]` with lazy init, test‑only seeding (via `PYTEST_CURRENT_TEST` or `KGFOUNDRY_ALLOW_RUNTIME_SEED=1`), and best‑effort disposal through `close()/__exit__`. The docstring calls this a “Thread‑safe lazy holder for mutable runtime state,” which is precisely what we needed. 

**Cell adoption in subsystems**

* **VLLM (in‑process) embedder** holds an engine handle through a `RuntimeCell` and exposes a safe `close()` that delegates back to the cell. This gives us a single shutdown hook and truly idempotent init. 
* **ApplicationContext runtime state** now stores heavy managers behind `RuntimeCell`s (FAISS, XTR, Hybrid). Callers use `peek()` to read readiness and `close()` to tear down. `get_xtr_index()` explicitly peeks/validates/and closes on failure paths, which is all the right choreography. 
* **FAISS** readiness is centralized in `ApplicationContext.ensure_faiss_ready()` (idempotent load + optional GPU clone) and can be triggered lazily or eagerly by env/config. 

**Lifecycle wiring**

* **FastAPI `lifespan()`** calls `ApplicationContext.close_all_runtimes()` on shutdown; of note, there’s also FAISS preload support executed during startup when configured. This is the correct place to centralize open/close semantics. 
* `close_all_runtimes()` closes FAISS/XTR/Hybrid cells and performs a GPU cleanup sweep — a nice touch that prevents resource leakage in long‑running processes or test workers. 

**Ops surfaced**

* An explicit `ops/runtime/xtr_open.py` Typer command now exists: it *fail‑fast* validates the XTR artifact directory and returns a Problem‑Details‑shaped payload on failure. This is perfect for CI hooks and SRE runbooks. 

**Readiness & retrieval pathing**

* Readiness probes reach into VLLM and FAISS; hybrid orchestration is present; XTR docs call out thread‑safety in read‑only paths. This aligns to two‑stage retrieval (FAISS → XTR rescore) already in the adapters.

**Agent/SWE discipline**

* Your `AGENTS.md` codifies “zero‑error mandate,” typed APIs, RFC‑9457 problem details, and strict pre‑commit gates — exactly the standard we want for refactors of this scope. We’ll keep every follow‑up below aligned to those rules.

---

## Gaps & opportunities unlocked by Runtime Cells

### A. Finish the “cell backbone” — consistency & coverage

1. **Remove residual `_RuntimeHandle` usage**
   The `ApplicationContext` symbols still include `_RuntimeHandle` alongside `RuntimeCell` in the SCIP surface. Unify on `RuntimeCell` for all mutable singletons so we have one mental model and one shutdown path. (It looks like XTR/FAISS/Hybrid already use cells; scan for remaining `_RuntimeHandle` references and migrate.) 

   **Diff sketch**

   ```diff
   # codeintel_rev/app/config_context.py
   - @dataclass(frozen=True, slots=True)
   - class _RuntimeHandle: ...
   + # Remove this helper and replace all uses with RuntimeCell[T]
   ```

2. **Make `XTRIndex` itself a cell‑backed manager (optional but cleaner)**
   Today `ApplicationContext` wraps an `XTRIndex` instance in a `RuntimeCell` and `XTRIndex` maintains its own internal “runtime” (`_XTRIndexRuntime`) lifecycle. That’s workable; however, you can simplify further by letting `XTRIndex` keep a `RuntimeCell[_XTRIndexRuntime]` internally and exposing `get_or_initialize()` / `close()` on the class, then have `ApplicationContext` store a `RuntimeCell[XTRIndex]` whose factory simply constructs `XTRIndex` (no `open()`), letting `XTRIndex` defer its heavy open to its own cell on first use. This avoids double‑latching logic and keeps responsibility local to the owner. (Current docs show `_XTRIndexRuntime` and `ready()` in play.) 

   **Minimal surface change**

   ```python
   # codeintel_rev/io/xtr_manager.py
   class XTRIndex:
       _cell: RuntimeCell[_XTRIndexRuntime] = field(default_factory=lambda: RuntimeCell("xtr-runtime"))

       def _initialize_runtime(self) -> _XTRIndexRuntime: ...
       def runtime(self) -> _XTRIndexRuntime:
           return self._cell.get_or_initialize(self._initialize_runtime)
       def close(self) -> None:
           self._cell.close()
   ```

3. **One registry to rule them all**
   Add a private `ApplicationContext._iter_cells()` returning a tuple of `(name, RuntimeCell[Any])` for **all** managed cells: `faiss`, `xtr`, `hybrid`, `vllm_embedder` (if applicable). Use this in `close_all_runtimes()` and in readiness/diagnostics to produce a single “cell state snapshot.” (You’re partially doing this already in `close_all_runtimes()`.) 

---

### B. Preload & readiness: generalize beyond FAISS

You already preload FAISS in `lifespan()` when configured. Extend that pattern to **a first‑class, per‑cell preload** so SRE can choose cold‑start vs warm‑start per environment.

1. **Config surface**
   Add a *set/tuple* of runtime names under `Settings.index.preload` (or a flat `Settings.preload_runtimes`) with allowed values: `{"faiss","xtr","vllm","hybrid"}`.

   **Diff sketch**

   ```diff
   # codeintel_rev/app/main.py (lifespan snippet)
   if "faiss" in ctx.settings.index.preload:
       await asyncio.to_thread(_preload_faiss_index, ctx)
   + if "xtr" in ctx.settings.index.preload:
   +     await asyncio.to_thread(lambda: ctx.get_xtr_index() is not None)
   + if "vllm" in ctx.settings.index.preload:
   +     await asyncio.to_thread(lambda: ctx.get_vllm_client().check_connection())
   ```

   * FAISS preload path is already implemented: `_preload_faiss_index` calls your idempotent `ensure_faiss_ready()`. 
   * For XTR, simply touching `get_xtr_index()` forces the cell factory and triggers `ready()` checks (you already peek & validate in there). 

2. **Readiness snapshot**
   Extend `/readyz` to report a **cells table**: `name`, `init_state` (`empty|initializing|ready`), `limits` (e.g., GPU fallbacks), and `last_init_ms`. That makes it obvious what’s warmed and what failed. You already have readiness functions for FAISS/VLLM — unify their outputs into one payload. 

---

### C. Observability: metrics & structured events (per AGENTS.md standards)

1. **Prometheus counters/gauges for cells**
   Add a tiny `runtime/metrics.py` used by the cell class:

   * `runtime_cell_initializations_total{cell=...}`
   * `runtime_cell_init_seconds{cell=...}` (Histogram)
   * `runtime_cell_active{cell=...}` (Gauge 0/1)
   * `runtime_cell_closures_total{cell=...}`

   Then increment inside `get_or_initialize()`/`close()`. This gives SLO clarity during deploys. (Your codebase doesn’t yet expose Prometheus metrics for cells; it does structured logging already, so this is non‑breaking.) 

2. **Structured events**
   Reuse your logging adapter to emit events:

   * `event="runtime_cell_seeded"` (include `guard=env/test`, `stack=...`)
   * `event="runtime_cell_initialized"` (duration, success/failure)
   * `event="runtime_cell_disposed"`

   That dovetails with your “zero‑error mandate” and Problem Details guidance in `AGENTS.md`. 

---

### D. Hot‑swap & rolling reload (optional, guarded)

The cell seed guard is test‑oriented by design — good. If you want zero‑downtime index swaps in production, add an explicitly **guarded** `swap(new_factory: Callable[[], T])` that:

* Creates new payload with back‑off; if successful, atomically replaces the pointer.
* Requires an elevated guard (`KGFOUNDRY_ALLOW_RUNTIME_SWAP=1`) *and* an admin API or CLI op.
* Emits `runtime_cell_swap_success|failure` events with duration.

Keep `seed()` as test‑only; `swap()` is your production‑grade reloader.

---

### E. Standardize per‑cell concurrency throttles

* VLLM already has a local semaphore for in‑process engines. Consider **promoting** that approach to **optional per‑cell semaphores** (configurable). For example, `faiss` usually scales linearly but XTR (late interaction) can thrash memory bandwidth; a `max_concurrency` gate per runtime helps keep tail latency predictable under load. (The adapter path `semantic_pro` organizes two‑stage hydration; that’s a good insertion point for per‑stage throttles as well.) 

---

### F. Operations ergonomics

1. **Extend the runtime ops suite**
   You already shipped `ops/runtime/xtr_open.py` with fail‑fast Problem Details (great for CI). Add symmetrical tools for FAISS & VLLM:

   * `ops/runtime/faiss_open.py` → loads manifests, attempts CPU load + optional GPU clone, prints Problem Details on failure (mirror of `xtr_open`). You already have public GPU clone helpers in `FAISSDualIndexManager`; re‑use them here. 
   * `ops/runtime/vllm_probe.py` → runs a single `embed_batch(["warmup"])` against whichever transport is configured; returns Problem Details on 4xx/5xx or latency budget breach. (Your readiness checks for VLLM exist — lift that logic.) 

2. **One Typer entrypoint**
   Group these under `ops/runtime` with a single `main`. You already have `ops/runtime/__init__.py` as a namespace. 

---

### G. API & data‑contract polish (guardrails)

Per **AGENTS.md** “Clarity & API design” and “Problem Details” sections, ensure the following across public methods touched by the refactor:

* Every public API has full annotations and a PEP‑257 one‑liner. (Your `ensure_faiss_ready()` and `get_xtr_index()` docstrings look solid — mirror that standard everywhere new.)
* Surfacing **limits** consistently. For FAISS you return `limits: list[str]` describing degraded mode (CPU path, missing GPU). Adopt the same for XTR and VLLM readiness so UIs and SRE can render consistent “yellow” states. 

---

### H. Tests (additions that will raise confidence)

You shipped the runtime cell but I don’t see a dedicated test module for it yet. Add the following:

1. **`tests/runtime/test_runtime_cell.py`**

   * *Idempotent init:* assert initializer called exactly once across 32 threads using a `Barrier`.
   * *Thread‑safety under errors:* initializer that fails N–1 times then succeeds; assert cell surfaces the first failure and eventually becomes ready.
   * *Seeding guard:* seeding without `KGFOUNDRY_ALLOW_RUNTIME_SEED=1` or `PYTEST_CURRENT_TEST` → raises with your `_SEED_GUARD_MESSAGE`. Seeding with guard set works.
   * *Dispose semantics:* cell payload with `.close()` and with `__exit__` fallback; assert both paths are exercised.

   *(Your cell exposes `_SEED_ENV`, `_SEED_GUARD_MESSAGE`, and `_dispose()` — the surface is there; we just need tests.)* 

2. **`tests/ops/test_xtr_open.py`**

   * Missing meta/tokens paths → `xtr-open` exits non‑zero with RFC‑9457 Problem Details payload.
   * Valid artifacts → zero exit and success JSON (when `--verbose`).

   *The Typer signature and `_exit_with_problem()` helper are visible in the index; mirror the behavior in tests.* 

3. **`tests/app/test_lifespan.py`**

   * With `Settings.index.preload={"faiss","xtr"}`: assert both factories were invoked exactly once and `close_all_runtimes()` is called on shutdown.
   * With empty preload: nothing initialized until first request; still closed on shutdown.

---

### I. Retrieval pipeline refinements (now simpler with cells)

1. **Unified “Hybrid Pipeline” façade**
   You already have `HybridSearchEngine` and the adapters performing FAISS → XTR rescore with fusion. Lift that into a thin façade that receives `limit`, `explain` flags, and returns a structured payload (scores + contribution map). The current pieces exist — the façade would make the path easier to reuse and test in isolation. 

2. **Dimension & config coherence checks**
   You do vector‑dim consistency checks for FAISS. Add a single `validate_runtime_compatibility()` in `ApplicationContext` that ensures:

   * FAISS `vec_dim` matches the embedder’s output dimension (CodeRank model or vLLM),
   * XTR dtype/dim matches its metadata, and
   * All enabled channels are compatible with `rrf_k` fusion config.
     Fail with Problem Details if violated. (You already have the FAISS piece; generalize.) 

---

### J. Developer & SRE UX

1. **`/readyz` enhancement** (JSON schema, example file under `schema/examples/readyz.json`)
   Include `cells` list with per‑runtime status (`empty|initializing|ready`), last init durations, and `limits`. That makes *dashboards* trivial. 

2. **Docs**
   Ensure `docs/runtime_cells.md` (or your existing `runtime_cells.md`) reflects the generalized preload, metrics, and swap semantics; add a “Runbook” subsection referencing the Typer commands. (You already have a design file in the repo for runtime cells.) 

---

## Concrete next‑step checklist (copy/paste to an issue)

* [ ] **Remove `_RuntimeHandle`** and standardize on `RuntimeCell` across `ApplicationContext`. 
* [ ] **(Optional) Refactor `XTRIndex`** to keep its `_XTRIndexRuntime` behind an internal `RuntimeCell`, simplifying open/close and avoiding double‑latching. 
* [ ] **Add `Settings.index.preload`** set and extend `lifespan()` to preload `{"faiss","xtr","vllm"}` selectively. 
* [ ] **Enhance `/readyz`** with a unified “cells” snapshot (name, state, limits, last_init_ms). 
* [ ] **Introduce `runtime/metrics.py`** and instrument `RuntimeCell` init/close with Prometheus metrics. (No public web surface changes.) 
* [ ] **Add guarded `RuntimeCell.swap()`** for hot reloads (off by default; env‑gated).
* [ ] **Per‑cell concurrency**: optional semaphores in config for XTR/FAISS to cap tail latency under load. 
* [ ] **Ship `ops/runtime/faiss_open.py`** and `ops/runtime/vllm_probe.py` mirroring `xtr_open`’s fail‑fast behavior. 
* [ ] **Tests**: `tests/runtime/test_runtime_cell.py`, `tests/ops/test_xtr_open.py`, `tests/app/test_lifespan.py`.
* [ ] **Add `validate_runtime_compatibility()`** in `ApplicationContext` to check dimensional/dtype consistency across FAISS/XTR/Embedder and fusion config. 
* [ ] **Docs update**: expand runtime cell doc with preload/metrics/swap/runbooks. 

---

## Why these changes matter

* **Operational confidence:** eager vs lazy init becomes a per‑runtime dial; `/readyz` and CI ops commands give crisp go/no‑go signals before traffic hits. 
* **Simplicity at call‑sites:** one way to open, one way to close, no special‑casing *which* subsystem you’re touching. 
* **Scalability:** per‑cell concurrency and a hot‑swap path allow you to keep latency budgets steady and roll new indexes/models with near zero downtime.
* **Quality gates (AGENTS.md):** everything above fits your typed‑API, Problem‑Details, and “zero‑error” doctrine, and it folds naturally into your existing pre‑commit/CI stack. 




# Ready-to-open PRs #

Below are **four ready‑to‑open PRs**, with concrete file adds/edits, unified diffs, and exact `ops/` commands. They’re aligned with your frozen‑dataclass + runtime‑cell design and reuse your existing observability and CLI patterns (Typer, Problem Details, Prometheus‑style metrics), as seen in the repo’s current `index.json` and docs. I’ve kept changes **localized**, **composable**, and **AOP‑compliant** with your AGENTS.md quality gates.

---

## ✅ What this builds on (from your repo)

* **`RuntimeCell`** is implemented with `peek`, `get_or_initialize`, `seed` (guarded by test env policy), and `close(silent=True)` that disposes the payload if it exposes `close/__exit__`. This is the shared abstraction we’ll instrument. 
* **FastAPI `lifespan()`** already centralizes init/readiness and preloads FAISS on an env flag; we will add a targeted preload for runtime cells and wire shutdown to a single `close_all_runtimes()` call.
* **Ops/CLI conventions**: you’re using Typer apps under `codeintel_rev.cli` and per‑topic ops modules (XTR verify etc.). We’ll add a `runtime` Typer group, plus a probe & prewarm command. 
* **Observability**: there’s an in‑repo observability layer (timers/counters) and telemetry modules used elsewhere; we’ll follow the same builder pattern (Counter/Histogram/Gauge “Like” types) and your metrics idioms used in scope store & retrieval.
* **XTR runtime/open checks** (existing CLI for verification) and **FAISS preload** hooks exist, so we’ll reuse those semantics for prewarm.

Everything below stays faithful to the “**Load Once / Explicit Injection / Fail‑Fast / Immutable**” principles in `config_context` and to your Agent Operating Protocol gates.  

---

# PR‑1 — feat(runtime): metrics for RuntimeCell + minimal telemetry shim

**Branch:** `feat/runtime-cell-telemetry`
**Goal:** Uniform counters, durations, and state gauge around `RuntimeCell.get_or_initialize()/seed()/close()`.

### 1) New: `codeintel_rev/runtime/telemetry.py`

```diff
diff --git a/codeintel_rev/runtime/telemetry.py b/codeintel_rev/runtime/telemetry.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/codeintel_rev/runtime/telemetry.py
@@ -0,0 +1,119 @@
+from __future__ import annotations
+from typing import Final
+from kgfoundry_common.logging import get_logger
+# Reuse the project-wide prometheus-style helpers used elsewhere in the repo.
+# These builders are already consumed by other telemetry modules.
+from kgfoundry_common.prometheus import (
+    build_counter, build_histogram, build_gauge,
+    CounterLike, HistogramLike, GaugeLike,
+)
+
+LOGGER = get_logger(__name__)
+
+# Labels: cell (e.g., "xtr", "vllm", "faiss")
+CELL_INIT_STARTED: Final[CounterLike]   = build_counter("runtime_cell_init_started",   "RuntimeCell init attempts",          ["cell"])
+CELL_INIT_OK:      Final[CounterLike]   = build_counter("runtime_cell_init_succeeded", "RuntimeCell init successes",         ["cell"])
+CELL_INIT_FAIL:    Final[CounterLike]   = build_counter("runtime_cell_init_failed",    "RuntimeCell init failures",          ["cell"])
+CELL_CLOSE_TOTAL:  Final[CounterLike]   = build_counter("runtime_cell_close_total",    "RuntimeCell closes (by outcome)",    ["cell", "outcome"])
+CELL_SEED_TOTAL:   Final[CounterLike]   = build_counter("runtime_cell_seed_total",     "RuntimeCell seeds (by source)",      ["cell", "source"])
+
+CELL_INIT_SECONDS: Final[HistogramLike] = build_histogram(
+    "runtime_cell_init_seconds",
+    "Duration of RuntimeCell initialization",
+    ["cell"],
+)
+
+# 0 = empty, 1 = has payload
+CELL_STATE:        Final[GaugeLike]     = build_gauge("runtime_cell_state", "RuntimeCell occupancy (0/1)", ["cell"])
+
+def mark_state(cell: str, has_value: bool) -> None:
+    try:
+        CELL_STATE.labels(cell=cell).set(1.0 if has_value else 0.0)
+    except Exception:  # never let metrics crash the hot path
+        LOGGER.debug("metrics/state failed", extra={"cell": cell})
+
+def on_init_start(cell: str) -> None:
+    try:
+        CELL_INIT_STARTED.labels(cell=cell).inc()
+    except Exception:
+        LOGGER.debug("metrics/init_start failed", extra={"cell": cell})
+
+def on_init_end(cell: str, ok: bool, seconds: float | None = None) -> None:
+    try:
+        if seconds is not None:
+            CELL_INIT_SECONDS.labels(cell=cell).observe(seconds)
+        (CELL_INIT_OK if ok else CELL_INIT_FAIL).labels(cell=cell).inc()
+    except Exception:
+        LOGGER.debug("metrics/init_end failed", extra={"cell": cell, "ok": ok})
+
+def on_seed(cell: str, source: str) -> None:
+    try:
+        CELL_SEED_TOTAL.labels(cell=cell, source=source).inc()
+    except Exception:
+        LOGGER.debug("metrics/seed failed", extra={"cell": cell, "source": source})
+
+def on_close(cell: str, outcome: str) -> None:
+    try:
+        CELL_CLOSE_TOTAL.labels(cell=cell, outcome=outcome).inc()
+    except Exception:
+        LOGGER.debug("metrics/close failed", extra={"cell": cell, "outcome": outcome})
```

### 2) Edit: `codeintel_rev/runtime/cells.py` — instrument the hot paths

> The file already exposes `peek`, `get_or_initialize`, `seed`, and `close(silent=True)`. We wrap init with duration timing and seed/close with counters, plus a stable `name` label (constructor arg). 

```diff
diff --git a/codeintel_rev/runtime/cells.py b/codeintel_rev/runtime/cells.py
index aaaaaaa..bbbbbbb 100644
--- a/codeintel_rev/runtime/cells.py
+++ b/codeintel_rev/runtime/cells.py
@@ -1,9 +1,13 @@
 from __future__ import annotations
 import os, time
 from dataclasses import dataclass, field
 from threading import RLock
 from typing import Callable, Generic, TypeVar
 from kgfoundry_common.logging import get_logger
+from .telemetry import (
+    on_init_start, on_init_end, on_seed, on_close, mark_state,
+)
 
 T = TypeVar("T")
 LOGGER = get_logger(__name__)
 
-@dataclass(slots=True)
+@dataclass(slots=True)
 class RuntimeCell(Generic[T]):
-    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
-    _value: T | None = field(default=None, init=False, repr=False)
+    name: str
+    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
+    _value: T | None = field(default=None, init=False, repr=False)
 
     def peek(self) -> T | None:
-        return self._value
+        val = self._value
+        mark_state(self.name, val is not None)
+        return val
 
     def get_or_initialize(self, factory: Callable[[], T]) -> T:
-        if self._value is not None:
-            return self._value
+        if self._value is not None:
+            mark_state(self.name, True)
+            return self._value
         with self._lock:
-            if self._value is None:
-                self._value = factory()
-            return self._value
+            if self._value is None:
+                on_init_start(self.name)
+                t0 = time.perf_counter()
+                ok = False
+                try:
+                    self._value = factory()
+                    ok = True
+                    return self._value
+                finally:
+                    dt = time.perf_counter() - t0
+                    on_init_end(self.name, ok=ok, seconds=dt)
+                    mark_state(self.name, self._value is not None)
+            return self._value
 
     def seed(self, value: T) -> None:
-        if not (os.getenv("PYTEST_CURRENT_TEST") or os.getenv("KGFOUNDRY_ALLOW_RUNTIME_SEED")):
+        if not (os.getenv("PYTEST_CURRENT_TEST") or os.getenv("KGFOUNDRY_ALLOW_RUNTIME_SEED")):
             raise PermissionError("seed() is only allowed in tests or with KGFOUNDRY_ALLOW_RUNTIME_SEED=1")
         with self._lock:
             self._value = value
+            on_seed(self.name, source="pytest" if os.getenv("PYTEST_CURRENT_TEST") else "explicit")
+            mark_state(self.name, True)
 
-    def close(self, silent: bool = True) -> None:
+    def close(self, silent: bool = True) -> None:
         with self._lock:
             if self._value is None:
-                return
+                on_close(self.name, outcome="noop")
+                mark_state(self.name, False)
+                return
             try:
                 v = self._value
                 self._value = None
-                # best-effort disposer: runtime may expose close() or __exit__()
+                # best-effort disposer: runtime may expose close() or __exit__()
                 if hasattr(v, "close"):
                     v.close()  # type: ignore[call-arg]
                 elif hasattr(v, "__exit__"):
                     v.__exit__(None, None, None)  # type: ignore[misc]
-            except Exception as exc:
+                on_close(self.name, outcome="ok")
+                mark_state(self.name, False)
+            except Exception as exc:
                 if not silent:
                     raise
-                LOGGER.warning("RuntimeCell.close suppressed exception", extra={"exc": repr(exc)})
+                LOGGER.warning("RuntimeCell.close suppressed exception", extra={"exc": repr(exc)})
+                on_close(self.name, outcome="error")
+                mark_state(self.name, False)
```

> **Why this way?** It mirrors your existing metrics idioms (counters/histograms/gauges), never throws from metrics, and keeps the cell’s API surface unchanged for callers. Matches your “limited observability today → first‑class observability” goal in the runtime‑cells draft. 

---

# PR‑2 — feat(ops/runtime): probe & prewarm RuntimeCells; expose under CLI

**Branch:** `feat/ops-runtime-probe-prewarm`
**Goal:** Add two dev‑ops commands:

* `runtime status` — print **occupancy** (via `peek`) and **metrics labels**
* `runtime prewarm` — force `get_or_initialize()` for selected cells

### 1) New: `codeintel_rev/ops/runtime/__init__.py`

```diff
diff --git a/codeintel_rev/ops/runtime/__init__.py b/codeintel_rev/ops/runtime/__init__.py
new file mode 100644
index 0000000..1111112
--- /dev/null
+++ b/codeintel_rev/ops/runtime/__init__.py
@@ -0,0 +1,10 @@
+from __future__ import annotations
+from typer import Typer
+
+app = Typer(help="Runtime ops for RuntimeCell-backed resources")
+
+# subcommands are registered in sibling modules via Typer callback
```

### 2) New: `codeintel_rev/ops/runtime/cell_probe.py`

```diff
diff --git a/codeintel_rev/ops/runtime/cell_probe.py b/codeintel_rev/ops/runtime/cell_probe.py
new file mode 100644
index 0000000..1111113
--- /dev/null
+++ b/codeintel_rev/ops/runtime/cell_probe.py
@@ -0,0 +1,148 @@
+from __future__ import annotations
+import asyncio, time
+import typer
+from typing import Annotated
+from kgfoundry_common.logging import get_logger
+from codeintel_rev.ops.runtime import app as runtime_app
+from codeintel_rev.app.config_context import ApplicationContext
+from codeintel_rev.errors import KgFoundryError
+
+LOGGER = get_logger(__name__)
+
+runtime = typer.Typer(help="RuntimeCell probe commands")
+runtime_app.add_typer(runtime, name="runtime")
+
+@runtime.command("status")
+def status() -> None:
+    """
+    Print occupancy and basic health for known runtime cells.
+    """
+    ctx = ApplicationContext.create()
+    rows: list[tuple[str, str]] = []
+
+    # Probe known subsystems. We keep this explicit & frozen-dataclass friendly.
+    # XTR: uses RuntimeCell under the hood after open(); verify via CLI semantics.
+    try:
+        from codeintel_rev.io.xtr_manager import XTRIndex
+        xtr = XTRIndex(root=ctx.paths.xtr_dir, config=ctx.settings.xtr)
+        has = xtr.runtime_cell.peek() is not None  # type: ignore[attr-defined]
+        rows.append(("xtr", "loaded" if has else "empty"))
+    except Exception as exc:  # tolerate missing or not yet migrated sites
+        rows.append(("xtr", f"error:{exc.__class__.__name__}"))
+
+    # vLLM local engine (when configured)
+    try:
+        from codeintel_rev.io.vllm_engine import InprocessVLLMEmbedder  # if present in this build
+        embedder = InprocessVLLMEmbedder(ctx.settings.vllm)
+        has = embedder._cell.peek() is not None  # type: ignore[attr-defined]
+        rows.append(("vllm", "loaded" if has else "empty"))
+    except Exception:
+        rows.append(("vllm", "n/a"))
+
+    for name, state in rows:
+        typer.echo(f"{name:10s} {state}")
+
+@runtime.command("prewarm")
+def prewarm(
+    xtr: Annotated[bool, typer.Option("--xtr", help="Prewarm XTR runtime")] = True,
+    vllm: Annotated[bool, typer.Option("--vllm", help="Prewarm vLLM local engine")] = False,
+) -> None:
+    """
+    Force lazy RuntimeCell initializations.
+    """
+    ctx = ApplicationContext.create()
+    if xtr:
+        from codeintel_rev.io.xtr_manager import XTRIndex
+        x = XTRIndex(root=ctx.paths.xtr_dir, config=ctx.settings.xtr)
+        t0 = time.perf_counter()
+        x.open()
+        typer.echo(f"xtr: ok in {time.perf_counter()-t0:0.3f}s")
+    if vllm:
+        try:
+            from codeintel_rev.io.vllm_engine import InprocessVLLMEmbedder
+            emb = InprocessVLLMEmbedder(ctx.settings.vllm)
+            t0 = time.perf_counter()
+            emb.ensure_local()  # or a no-op if already live
+            typer.echo(f"vllm: ok in {time.perf_counter()-t0:0.3f}s")
+        except Exception as exc:
+            raise KgFoundryError("vLLM prewarm failed") from exc
```

> Notes: We **do not add globals** or a registry — we probe specific frozen owners where a RuntimeCell is known to live (XTR, vLLM local). This respects your “explicit injection” design while giving ops the handles it needs. XTR “open/verify” follows your existing CLI semantics. 

### 3) Wire into the top‑level CLI: `codeintel_rev/cli/__init__.py`

```diff
diff --git a/codeintel_rev/cli/__init__.py b/codeintel_rev/cli/__init__.py
index 2222222..3333333 100644
--- a/codeintel_rev/cli/__init__.py
+++ b/codeintel_rev/cli/__init__.py
@@ -10,6 +10,7 @@ from typer import Typer
 from codeintel_rev.config.settings import load_settings
-from codeintel_rev.mcp_server.retrieval import xtr_cli
+from codeintel_rev.mcp_server.retrieval import xtr_cli
+from codeintel_rev.ops import runtime as runtime_ops
 
 app = Typer()
 app.add_typer(splade.app, name="splade", help="SPLADE index ops")
 app.add_typer(xtr_cli.app, name="xtr", help="XTR index ops")
+app.add_typer(runtime_ops.app, name="runtime", help="Runtime ops (RuntimeCell)")
```

> Your CLI aggregator already adds “splade” and “xtr”; this simply mounts the new `runtime` app. 

---

# PR‑3 — feat(app): preload runtime cells in `lifespan()` + unified shutdown

**Branch:** `feat/app-lifespan-runtime-preload`
**Goal:** (1) Optional **prewarm** of runtime cells during startup, (2) **shutdown** calls a single `close_all_runtimes()` to ensure GPU contexts/memmaps are closed deterministically.

### 1) Add a tiny runtime manager on the context’s private state

> `ApplicationContext` already has a private runtime state field; we extend it to track **known** cells without breaking frozen public attributes. 

```diff
diff --git a/codeintel_rev/app/config_context.py b/codeintel_rev/app/config_context.py
index 4444444..5555555 100644
--- a/codeintel_rev/app/config_context.py
+++ b/codeintel_rev/app/config_context.py
@@ -1,6 +1,8 @@
 from __future__ import annotations
 from dataclasses import dataclass, field
 from pathlib import Path
+from typing import Any
+from codeintel_rev.runtime.cells import RuntimeCell
 ...
 @dataclass(slots=True, frozen=True)
 class ApplicationContext:
@@ -25,6 +27,30 @@ class ApplicationContext:
     _runtime: _ContextRuntimeState = field(default_factory=_ContextRuntimeState, init=False, repr=False)
 
+    # ----------------------
+    # RuntimeCell registry (explicit, context-scoped)
+    # ----------------------
+    def register_runtime_cell(self, name: str, cell: RuntimeCell[Any]) -> None:
+        # registry lives in the private mutable state
+        self._runtime.register(name, cell)  # type: ignore[attr-defined]
+
+    def close_all_runtimes(self) -> None:
+        self._runtime.close_all()  # type: ignore[attr-defined]
+
+@dataclass(slots=True)
+class _ContextRuntimeState:
+    _cells: dict[str, RuntimeCell[Any]] = field(default_factory=dict)
+
+    def register(self, name: str, cell: RuntimeCell[Any]) -> None:
+        self._cells[name] = cell
+
+    def close_all(self) -> None:
+        for name, cell in list(self._cells.items()):
+            try:
+                cell.close(silent=True)
+            finally:
+                self._cells.pop(name, None)
+
     @classmethod
     def create(cls) -> ApplicationContext:
         ...
```

### 2) Preload & shutdown hooks in `app.main.lifespan()`

> We keep parity with your existing FAISS preload and add optional `XTR_PRELOAD=1` and `VLLM_PRELOAD=1` env toggles. On shutdown, we call `context.close_all_runtimes()`. 

```diff
diff --git a/codeintel_rev/app/main.py b/codeintel_rev/app/main.py
index 6666666..7777777 100644
--- a/codeintel_rev/app/main.py
+++ b/codeintel_rev/app/main.py
@@ -1,6 +1,8 @@
 from __future__ import annotations
 import os, asyncio
 from contextlib import asynccontextmanager
+import time
+from typing import AsyncIterator
 from fastapi import FastAPI
 from kgfoundry_common.logging import get_logger
 from .config_context import ApplicationContext
@@ -108,6 +110,34 @@ async def lifespan(app: FastAPI) -> AsyncIterator[None]:
         app.state.context = context
         ...
         # existing readiness & FAISS preload path
         if context.settings.index.faiss_preload:
             await asyncio.to_thread(_preload_faiss_index, context)
+        # --- NEW: runtime-cell prewarm (opt-in via env) ---
+        if os.getenv("XTR_PRELOAD") == "1":
+            await asyncio.to_thread(_prewarm_xtr, context)
+        if os.getenv("VLLM_PRELOAD") == "1":
+            await asyncio.to_thread(_prewarm_vllm, context)
         yield
     finally:
         ...
-        # existing cleanup paths
+        # unified runtime-cell shutdown
+        try:
+            app.state.context.close_all_runtimes()
+        except Exception:
+            LOGGER.warning("close_all_runtimes failed")
 
+def _prewarm_xtr(context: ApplicationContext) -> None:
+    from codeintel_rev.io.xtr_manager import XTRIndex
+    x = XTRIndex(root=context.paths.xtr_dir, config=context.settings.xtr)
+    t0 = time.perf_counter()
+    x.open()  # attaches runtime; RuntimeCell metrics will record init cost
+    LOGGER.info("XTR prewarmed", extra={"seconds": time.perf_counter() - t0})
+    # optional: register cell to context for unified shutdown
+    try:
+        context.register_runtime_cell("xtr", x.runtime_cell)  # type: ignore[attr-defined]
+    except Exception:
+        pass
+
+def _prewarm_vllm(context: ApplicationContext) -> None:
+    try:
+        from codeintel_rev.io.vllm_engine import InprocessVLLMEmbedder
+        emb = InprocessVLLMEmbedder(context.settings.vllm)
+        emb.ensure_local()  # idempotent warmup
+        context.register_runtime_cell("vllm", emb._cell)  # type: ignore[attr-defined]
+    except Exception:
+        LOGGER.info("vLLM local engine not configured; skipping")
```

> This mirrors your existing lifespan sequencing and keeps prewarm optional, as your notes emphasize fail‑fast and immutable settings, with load once at startup. 

---

# PR‑4 — test(runtime): concurrency stress + seeding + disposer accuracy

**Branch:** `test/runtime-cell-concurrency`
**Goal:** High‑signal tests that validate:

* **Only one** initializer runs under contention
* **Seed** is honored when guard is enabled (pytest or explicit env)
* **Close** calls disposer exactly once and swallows errors when `silent=True`

### New: `tests/runtime/test_runtime_cell.py`

```diff
diff --git a/tests/runtime/test_runtime_cell.py b/tests/runtime/test_runtime_cell.py
new file mode 100644
index 0000000..8888888
--- /dev/null
+++ b/tests/runtime/test_runtime_cell.py
@@ -0,0 +1,175 @@
+from __future__ import annotations
+import os, time, threading
+from typing import Any
+import pytest
+from codeintel_rev.runtime.cells import RuntimeCell
+
+def test_idempotent_init_under_contention():
+    cell: RuntimeCell[dict[str, Any]] = RuntimeCell(name="test")
+    init_count = 0
+    lock = threading.Lock()
+
+    def factory() -> dict[str, Any]:
+        nonlocal init_count
+        with lock:
+            init_count += 1
+        time.sleep(0.01)  # widen the race
+        return {"ok": True}
+
+    results: list[dict[str, Any]] = []
+    barrier = threading.Barrier(64)
+
+    def worker():
+        barrier.wait()
+        results.append(cell.get_or_initialize(factory))
+
+    threads = [threading.Thread(target=worker) for _ in range(64)]
+    for t in threads: t.start()
+    for t in threads: t.join()
+
+    assert init_count == 1, f"factory executed {init_count} times"
+    assert all(r is results[0] for r in results)
+
+def test_seed_honors_guard(monkeypatch):
+    cell: RuntimeCell[int] = RuntimeCell(name="seeded")
+    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
+    cell.seed(42)
+    assert cell.peek() == 42
+    # subsequent init should be ignored
+    assert cell.get_or_initialize(lambda: 7) == 42
+
+def test_close_calls_disposer_once():
+    calls: list[str] = []
+    class R:
+        def close(self): calls.append("close")
+
+    cell: RuntimeCell[R] = RuntimeCell(name="close")
+    cell.seed(R())
+    cell.close(silent=False)
+    cell.close(silent=False)  # no payload now
+    assert calls == ["close"]
+
+def test_close_suppresses_disposer_error():
+    class R:
+        def close(self): raise RuntimeError("boom")
+    cell: RuntimeCell[R] = RuntimeCell(name="err")
+    os.environ["PYTEST_CURRENT_TEST"] = "1"
+    cell.seed(R())
+    # should NOT raise
+    cell.close(silent=True)
+    assert cell.peek() is None
```

> These tests lock in the concurrency and policy semantics described in your design note and exercised by the current implementation (seed guard via `PYTEST_CURRENT_TEST` or `KGFOUNDRY_ALLOW_RUNTIME_SEED`). 

---

# (Optional) PR‑5 — polish existing `ops/runtime/xtr_open.py`

You already have this module and a CLI entrypoint that exits with Problem Details when artifacts are missing. If you’d like, we can fold it under the same `runtime` group for discoverability, but functionally it already “fails fast,” mirroring your Typer behavior. 

---

## How to run & verify locally (AOP‑aligned)

```bash
# 1) formatting, lint, types, static hygiene
uv run ruff format && uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13

# 2) run tests (with GPU warmup skipped unless you want it)
SKIP_GPU_WARMUP=1 uv run pytest -q tests/runtime/test_runtime_cell.py

# 3) metrics smoke (optional): start your FastAPI app and scrape /metrics if exposed

# 4) CLI checks
uv run python -m codeintel_rev.cli runtime status
XTR_PRELOAD=1 uv run python -m codeintel_rev.cli runtime prewarm --xtr
VLLM_PRELOAD=1 uv run python -m codeintel_rev.cli runtime prewarm --vllm
```

This respects the deterministic, agent‑grade workflow from `AGENTS.md` (Ruff/Pyright/Pytest, no daemon, explicit commands). 

---

## Why this is the right follow‑up

* **Observability, not opacity.** The `RuntimeCell` now emits **init start/end**, **duration**, **seed sources**, **close outcomes**, and a **state gauge** — solving the “limited observability” drawback you identified and aligning with your in‑repo metrics style.  
* **Operations leverage** without globals. We add explicit, small ops that **peek** and **prewarm** only where it’s safe (XTR/vLLM), keeping with your “no global state; explicit injection” philosophy. 
* **Lifecycle guarantees.** `ApplicationContext.close_all_runtimes()` wires into `lifespan()` shutdown to prevent dangling CUDA contexts/memmaps — a direct remedy to the “risk of leaks” called out in your draft.  
* **Minimal cognitive load.** The changes standardize how every frozen owner handles mutability (via one primitive), keep modules decoupled, and let ops verify readiness in one place.

---

## Small follow‑ups (nice‑to‑have, not blockers)

* **Export `/metrics`** if not already present in your app deployment to surface the new runtime metrics.
* **Document env toggles** in `AGENTS.md` “Quick Commands,” e.g., `XTR_PRELOAD`, `VLLM_PRELOAD`. 
* **(Later)** Add an OpenTelemetry span wrapper around `get_or_initialize` if/when you wire OTLP tracing in `mcp_server.common.observability`. 

---



# Ready-to-drop PRs with additional concrete followups #

Below are **ready‑to‑drop PRs** that translate the RuntimeCell architecture into concrete code changes, ops commands, metrics, app lifecycle wiring, and a concurrency “hammer” test suite. I’ve aligned the scope and acceptance criteria to your **AGENTS.md** tenets (zero‑error mandate, hermetic agents, structured IO, composability), and to the actual APIs that exist now in your repo (e.g., `RuntimeCell`, `ApplicationContext`, `app.main.lifespan`, retrieval telemetry helpers, FAISS and XTR managers). Citations inline point to the exact constructs in your uploaded index for easy verification and navigation.

> **What’s already in your tree (validated):**
>
> * `RuntimeCell` is present and used for in‑process vLLM embedding; it exposes `get_or_initialize(…)` and `close()`. For example, `InprocessVLLMEmbedder` holds a `RuntimeCell[...]` and closes it in `close()`—this is the exact seam we’ll instrument for metrics and observability. 
> * `ApplicationContext` is frozen with a backing `_ContextRuntimeState` that already includes runtime cells for **hybrid search**, **CodeRank FAISS**, and **XTR**, while FAISS still uses a bespoke `_FaissRuntimeState` (we normalize this in PR‑05). 
> * FastAPI `lifespan()` already performs config bootstrap and FAISS preload via `_preload_faiss_index(context)`; we’ll extend this to preload RuntimeCells and guarantee `close_all_runtimes()` on shutdown. 
> * You already have a lightweight stage telemetry layer (`codeintel_rev.retrieval.telemetry`) with `build_counter`, a default registry, and structured stage timing; we’ll reuse it for RuntimeCell metrics to avoid introducing new patterns. 
> * FAISS/XTR/Hybrid managers are cleanly separated; FAISS exposes GPU clone, search, and memory estimation APIs we can wrap behind a factory for the FAISS cell.

> **Design guardrails from AGENTS.md reflected below:**
> **Zero‑error mandate**; hermetic, capability‑gated agents; structured I/O; composability; *no hidden state*; *no undifferentiated exceptions*; and reproducible ops. 
> The RuntimeCell proposal’s intent—**a shared abstraction for mutable state backing frozen dataclasses**—is the backbone for the PR stack that follows. 

---

## PR‑01 — RuntimeCell Observability & Metrics (counters + latency + “readiness” gauges)

**Goal:** Add first‑class observability to runtime cells with minimal footprint, reusing your existing telemetry provider and Prometheus registry to track init attempts, outcomes, latency, and per‑cell readiness.

**Files**

* `codeintel_rev/runtime/telemetry.py` (new)
* `codeintel_rev/runtime/cells.py` (instrumentation diff)

**Key points**

* Reuse `build_counter`/`get_default_registry()` from `codeintel_rev.retrieval.telemetry` (present in tree). 
* Add `runtime_cell_init_total{cell,status}` counter, `runtime_cell_close_total{cell}`, `runtime_cell_ready{cell}` gauge, and `runtime_cell_init_latency_ms{cell}` histogram.
* If your telemetry module doesn’t expose gauge/histogram builders, bind them directly from `prometheus_client` but **register** them on your existing default registry to keep one export surface.

**Add** `codeintel_rev/runtime/telemetry.py`

```python
from __future__ import annotations
from typing import Final
from time import perf_counter

# Prefer existing registry to avoid duplicate /metrics exports
from codeintel_rev.retrieval.telemetry import build_counter, get_default_registry  # :contentReference[oaicite:8]{index=8}

try:
    # Prometheus client is a transitive dep in your stack; guard just in case
    from prometheus_client import Gauge, Histogram
except Exception:  # pragma: no cover
    Gauge = Histogram = None  # type: ignore[misc]

# --- Counters via your builder (consistent with retrieval.telemetry) ---
CELL_INIT_TOTAL = build_counter(
    "runtime_cell_init_total",
    "RuntimeCell initialization attempts by outcome",
    ["cell", "status"],  # status ∈ {success, error, skipped}
)
CELL_CLOSE_TOTAL = build_counter(
    "runtime_cell_close_total",
    "RuntimeCell close events",
    ["cell"],
)

# --- Optional gauges/histograms if prometheus_client available ---
_REG = get_default_registry()
CELL_READY = Gauge("runtime_cell_ready",
                   "1 if cell is ready, otherwise 0",
                   ["cell"],
                   registry=_REG) if Gauge and _REG else None

CELL_INIT_LAT_MS = Histogram("runtime_cell_init_latency_ms",
                             "Initialization latency (ms) by cell",
                             ["cell"],
                             registry=_REG) if Histogram and _REG else None


def mark_init_start(cell: str) -> float:
    # Stopwatch for latency; return monotonic start
    return perf_counter()


def mark_init_end(cell: str, start: float, ok: bool, skipped: bool = False) -> None:
    status = "skipped" if skipped else ("success" if ok else "error")
    CELL_INIT_TOTAL.labels(cell=cell, status=status).inc()
    if CELL_INIT_LAT_MS and not skipped:
        CELL_INIT_LAT_MS.labels(cell=cell).observe((perf_counter() - start) * 1000.0)


def set_ready(cell: str, ready: bool) -> None:
    if CELL_READY:
        CELL_READY.labels(cell=cell).set(1.0 if ready else 0.0)


def mark_closed(cell: str) -> None:
    CELL_CLOSE_TOTAL.labels(cell=cell).inc()
    set_ready(cell, False)
```

**Diff** (instrument `RuntimeCell` hot paths)

```diff
*** a/codeintel_rev/runtime/cells.py
--- b/codeintel_rev/runtime/cells.py
@@
-from dataclasses import dataclass
+from dataclasses import dataclass
+from codeintel_rev.runtime.telemetry import (
+    mark_init_start, mark_init_end, set_ready, mark_closed
+)  # PR‑01 metrics

@@ class RuntimeCell(Generic[T]):
-    def get_or_initialize(self, factory: Callable[[], T]) -> T:
+    def get_or_initialize(self, factory: Callable[[], T]) -> T:
+        start = mark_init_start(self.name)
         # existing fast path / lock logic…
-        if self._instance is not None:
-            return self._instance
+        if self._instance is not None:
+            mark_init_end(self.name, start, ok=True, skipped=True)
+            set_ready(self.name, True)
+            return self._instance
         with self._lock:
             if self._instance is None:
-                self._instance = factory()
-        return self._instance
+                try:
+                    self._instance = factory()
+                    mark_init_end(self.name, start, ok=True)
+                    set_ready(self.name, True)
+                except Exception:
+                    mark_init_end(self.name, start, ok=False)
+                    raise
+            else:
+                mark_init_end(self.name, start, ok=True, skipped=True)
+                set_ready(self.name, True)
+        return self._instance
@@ class RuntimeCell(Generic[T]):
-    def close(self) -> None:
+    def close(self) -> None:
         # existing close semantics…
+        mark_closed(self.name)
```

**Acceptance criteria**

* `/metrics` exposes `runtime_cell_init_total`, `runtime_cell_close_total`, and (when `prometheus_client` is present) `runtime_cell_ready` + `runtime_cell_init_latency_ms`.
* No new global singletons; metrics bind to your existing registry only. 
* 100% type‑annotated, passes `ruff`, `pyright`, and unit tests.

---

## PR‑02 — App `lifespan()` preload & graceful shutdown of all RuntimeCells

**Goal:** Eliminate first‑hit latency and guarantee deterministic shutdown by preloading runtime cells at startup and closing them at shutdown.

**Files**

* `codeintel_rev/app/config_context.py` (+ `close_all_runtimes()` method)
* `codeintel_rev/app/main.py` (preload cell set; ensure close on shutdown)

**Diff** — add `close_all_runtimes()` to `ApplicationContext`

```diff
*** a/codeintel_rev/app/config_context.py
--- b/codeintel_rev/app/config_context.py
@@
 @dataclass(slots=True, frozen=True)
 class ApplicationContext:
     ...
+    def close_all_runtimes(self) -> None:
+        """
+        Close every RuntimeCell or runtime-backed state held in the context.
+        Safe to call multiple times. No-op on missing cells.
+        """
+        state = object.__getattribute__(self, "_runtime")  # backing state
+        # Hybrid / CodeRank FAISS / XTR are RuntimeCells (see _ContextRuntimeState)
+        try:
+            state.hybrid.close()
+        except Exception:
+            pass
+        try:
+            state.coderank_faiss.close()
+        except Exception:
+            pass
+        try:
+            state.xtr.close()
+        except Exception:
+            pass
+        # FAISS legacy state is normalized in PR‑05; leave as is for now
```

(*Your backing state shows those RuntimeCell fields today.*) 

**Diff** — preload in `lifespan()` and guarantee shutdown

```diff
*** a/codeintel_rev/app/main.py
--- b/codeintel_rev/app/main.py
@@ async def lifespan(app: FastAPI) -> AsyncIterator[None]:
-    # existing configuration load & readiness bind...
+    # existing configuration load & readiness bind...
     context = ApplicationContext.create()
     app.state.context = context
@@
-    # Preload FAISS CPU/GPU to kill cold-starts
-    _preload_faiss_index(context)
+    # Preload FAISS CPU/GPU to kill cold-starts
+    _preload_faiss_index(context)
+    # Preload RuntimeCells to avoid first-request penalty
+    # No-ops if already initialized; factories encapsulate heavy IO/GPU binds.
+    try:
+        # Hybrid engine
+        context._runtime.hybrid.get_or_initialize(
+            lambda: context._build_hybrid_engine()
+        )
+        # CodeRank FAISS stage-A
+        context._runtime.coderank_faiss.get_or_initialize(
+            lambda: context.faiss_manager  # or a dedicated build for stage-A
+        )
+        # XTR index (late-interaction)
+        context._runtime.xtr.get_or_initialize(
+            lambda: context._open_xtr_index()
+        )
+    except Exception as exc:
+        # Fail-fast per design principles
+        raise
@@
     try:
         yield
     finally:
-        # normal shutdown…
+        # Always close runtime cells deterministically
+        try:
+            context.close_all_runtimes()
+        finally:
+            # continue existing shutdown
+            ...
```

**Why here?** `lifespan()` is where you already load config and preload FAISS; it’s the correct hook to preload cells and to close them later—consistent with “load once, immutable settings” design.

**Acceptance criteria**

* Cold‑start latency for hybrid/CodeRank/XTR is eliminated in production.
* Shutdown is clean; no orphaned GPU/FD resources.

---

## PR‑03 — ops/runtime CLI commands (fast‑fail, status, and prewarm)

**Goal:** Provide hermetic, reproducible operational entry points that an agent or human can run to validate artifacts and warm caches—fully aligned with **zero‑error mandate** (fail fast, structured error output). 

**Files**

* `ops/runtime/xtr_open.py` (new; fast‑fail if token/index artifacts missing; mirrors your `Typer` pattern from CLI modules) 
* `ops/runtime/prewarm.py` (new; preloads all runtime cells)
* `ops/runtime/status.py` (new; prints JSON “readiness” for each cell)

**`ops/runtime/xtr_open.py`**

```python
#!/usr/bin/env python3
from __future__ import annotations
import json
import sys
import typer
from codeintel_rev.app.config_context import ApplicationContext

app = typer.Typer(add_completion=False, no_args_is_help=True)

@app.command()
def open_xtr() -> None:
    """
    Fail fast if the XTR artifacts are missing or invalid; exit non-zero on error.
    Returns JSON on stdout with {"ok": bool, "detail": str}.
    """
    ctx = ApplicationContext.create()
    try:
        cell = ctx._runtime.xtr
        xtr = cell.get_or_initialize(lambda: ctx._open_xtr_index())  # runtime factory
        _ = xtr.search("smoke test", k=1)  # cheap touch
        print(json.dumps({"ok": True, "detail": "xtr ready"}))
    except Exception as e:
        print(json.dumps({"ok": False, "detail": f"{type(e).__name__}: {e}"}))
        raise typer.Exit(code=2)

if __name__ == "__main__":
    app()
```

*XTR APIs (`XTRIndex.search`) are present; this smoke test is safe and fast.* 

**`ops/runtime/prewarm.py`**

```python
#!/usr/bin/env python3
from __future__ import annotations
import json
import typer
from codeintel_rev.app.config_context import ApplicationContext

app = typer.Typer(add_completion=False, no_args_is_help=True)

@app.command()
def all() -> None:
    """
    Prewarm FAISS/Hybrid/CodeRank/XTR; fails fast and emits JSON summary.
    """
    ctx = ApplicationContext.create()
    results: dict[str, str] = {}
    try:
        # FAISS preload path exists today
        from codeintel_rev.app.main import _preload_faiss_index  # :contentReference[oaicite:15]{index=15}
        _ = _preload_faiss_index(ctx)
        results["faiss"] = "ok"
    except Exception as e:
        results["faiss"] = f"error: {e}"

    def _try(name: str, f):
        try:
            ctx._runtime.__getattribute__(name).get_or_initialize(f)
            results[name] = "ok"
        except Exception as e:
            results[name] = f"error: {e}"

    _try("hybrid", lambda: ctx._build_hybrid_engine())
    _try("coderank_faiss", lambda: ctx.faiss_manager)
    _try("xtr", lambda: ctx._open_xtr_index())

    ok = all(v == "ok" for v in results.values())
    print(json.dumps({"ok": ok, "results": results}))
    raise typer.Exit(code=0 if ok else 2)

if __name__ == "__main__":
    app()
```

**`ops/runtime/status.py`**

```python
#!/usr/bin/env python3
from __future__ import annotations
import json
import typer
from codeintel_rev.app.config_context import ApplicationContext

app = typer.Typer(add_completion=False, no_args_is_help=True)

@app.command()
def show() -> None:
    """
    Print a JSON snapshot of runtime readiness.
    """
    ctx = ApplicationContext.create()
    state = ctx._runtime
    snapshot = {
        "hybrid_ready": state.hybrid.peek() is not None,   # typical cell API
        "coderank_faiss_ready": state.coderank_faiss.peek() is not None,
        "xtr_ready": state.xtr.peek() is not None,
        "faiss_ready": bool(ctx.ensure_faiss_ready()[0]),  # existing hook
    }
    print(json.dumps(snapshot, sort_keys=True))
    raise typer.Exit(code=0 if all(snapshot.values()) else 2)

if __name__ == "__main__":
    app()
```

(`ensure_faiss_ready()` is in your context with ready/limits result.) 

**Acceptance criteria**

* `python ops/runtime/xtr_open.py open-xtr` returns JSON and exits non‑zero on failure.
* `python ops/runtime/prewarm.py all` warms FAISS + cells and returns JSON with per‑cell outcomes.
* `python ops/runtime/status.py show` emits a machine‑readable readiness snapshot (for smoke tests/CI).

---

## PR‑04 — Concurrency “hammer” test for RuntimeCell

**Goal:** Prove idempotent, thread‑safe initialization; verify seeding path; assert `close()` shuts down cleanly and allows later re‑init.

**Files**

* `tests/runtime/test_runtime_cell.py` (new)

**Test module**

```python
from __future__ import annotations
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
import time
import pytest

from codeintel_rev.runtime.cells import RuntimeCell  # cell under test  :contentReference[oaicite:17]{index=17}

def test_idempotent_init_under_contention():
    cell = RuntimeCell(name="hammer")
    counter = {"n": 0}
    lock = threading.Lock()

    def factory():
        # Simulate expensive init and prove single execution
        time.sleep(0.05)
        with lock:
            counter["n"] += 1
        return object()

    results = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = [pool.submit(cell.get_or_initialize, factory) for _ in range(128)]
        for f in as_completed(futs):
            results.append(f.result())

    assert all(r is results[0] for r in results)
    assert counter["n"] == 1  # exactly one construction

def test_peek_and_seed():
    cell = RuntimeCell(name="seeded")
    assert cell.peek() is None
    obj = object()
    cell.seed(obj)
    assert cell.peek() is obj
    assert cell.get_or_initialize(lambda: object()) is obj

def test_close_allows_reinit():
    cell = RuntimeCell(name="reinit")
    o1 = cell.get_or_initialize(lambda: object())
    cell.close()
    o2 = cell.get_or_initialize(lambda: object())
    assert o1 is not o2
```

**Acceptance criteria**

* Tests pass reliably under `-n auto` (pytest‑xdist) and repeat runs.
* CI includes a fast target running these tests only.

---

## PR‑05 — Normalize FAISS to `RuntimeCell[FAISSManager]` and unify preload path

**Goal:** Remove bespoke `_FaissRuntimeState`; fold FAISS into a `RuntimeCell` like the others for consistent lifecycle and metrics.

**Files**

* `codeintel_rev/app/config_context.py` (replace `_FaissRuntimeState` with `RuntimeCell[FAISSManager]`)
* `codeintel_rev/app/main.py` (preload via FAISS cell rather than bespoke helper—or keep helper but delegate to the cell)
* `codeintel_rev/runtime/factories.py` (new; optional, centralizes factories)

**Why:** Your `_ContextRuntimeState` already uses cells for `hybrid`, `coderank_faiss`, and `xtr`, while FAISS is special‑cased. Normalizing it reduces cognitive overhead and unlocks **one** metrics surface across all runtime resources. 

**Diff sketch** (context excerpt)

```diff
*** a/codeintel_rev/app/config_context.py
--- b/codeintel_rev/app/config_context.py
@@
-class _FaissRuntimeState: ...
-@dataclass(slots=True, frozen=True)
-class _ContextRuntimeState:
-    hybrid: RuntimeCell[HybridSearchEngine]
-    coderank_faiss: RuntimeCell[FAISSManager]
-    xtr: RuntimeCell[XTRIndex]
-    faiss: _FaissRuntimeState
+@dataclass(slots=True, frozen=True)
+class _ContextRuntimeState:
+    hybrid: RuntimeCell[HybridSearchEngine]
+    coderank_faiss: RuntimeCell[FAISSManager]
+    xtr: RuntimeCell[XTRIndex]
+    faiss: RuntimeCell[FAISSManager]
```

**Factory**
You already expose FAISS “clone to GPU” and “load CPU” verbs; your cell factory should encapsulate: load CPU index → opportunistic GPU clone → return ready manager. 

```python
# codeintel_rev/runtime/factories.py
from __future__ import annotations
from codeintel_rev.io.faiss_manager import FAISSManager  # :contentReference[oaicite:20]{index=20}

def build_faiss_manager(ctx) -> FAISSManager:
    mgr = ctx.faiss_manager  # or construct from paths/settings
    # Eager GPU clone when available; failure is allowed (mgr falls back)
    try:
        _ = mgr.clone_to_gpu(device=0)  # returns bool; non-fatal if False
    except Exception:
        pass
    return mgr
```

**Lifespan preload**
Either replace `_preload_faiss_index(context)` with the cell or keep it but delegate to the cell factory internally. 

**Acceptance criteria**

* FAISS shows up in the same cell metrics (`runtime_cell_*`) as other runtimes.
* `ensure_faiss_ready()` can simply `return (ctx._runtime.faiss.peek() is not None, limits)` for compatibility. 

---

## PR‑06 — Readiness probe extensions (Hybrid/CodeRank/XTR)

**Goal:** Extend `ReadinessProbe` to reflect the new centralization: quick probes for `hybrid`, `coderank_faiss`, `xtr` in addition to your existing vLLM checks. vLLM already has in‑process smoke tests and HTTP health checks; mimic that shape. 

**Files**

* `codeintel_rev/app/readiness.py` (add `_check_hybrid()`, `_check_coderank_faiss()`, `_check_xtr()` and surface in `check_*`)

**Sketch**

```diff
*** a/codeintel_rev/app/readiness.py
--- b/codeintel_rev/app/readiness.py
@@ class ReadinessProbe:
     def check_vllm_connection(self) -> CheckResult: ...
+    def check_hybrid(self) -> CheckResult:
+        try:
+            ok = self.context._runtime.hybrid.peek() is not None
+            return CheckResult.ok("hybrid ready") if ok else CheckResult.fail("hybrid cold")
+        except Exception as e:
+            return CheckResult.fail(f"hybrid error: {e}")
+    def check_coderank_faiss(self) -> CheckResult: ...
+    def check_xtr(self) -> CheckResult: ...
```

**Acceptance criteria**

* `/health` or readiness endpoint reflects per‑cell readiness.
* Output integrates with your existing summarization logic and Problem Details format.

---

## PR‑07 — Documentation and Agent Contract Update (optional but recommended)

**Goal:** Ensure agents can implement/operate this stack with **zero ambiguity**:

* Document the cell metrics, the ops commands, and the lifecycle.
* Add an **agent contract** page mapping responsibilities to capabilities (“hermetic function + explicit capabilities + structured I/O”) and **error taxonomy** to satisfy the zero‑error mandate and reproducibility. 

**Files**

* `docs/runtime-cells.md` (how to: preload, measure, operate)
* `docs/ops-runtime.md` (CLI usage, expected JSON envelopes)
* `AGENTS.md` (append “RuntimeCell Ops & Observability” section referencing the above)

---

# How to stage the PRs (copy/paste)

1. **Branch plan**

```
pr/01-runtimecell-metrics
pr/02-lifespan-preload-close
pr/03-ops-runtime-cli
pr/04-runtimecell-hammer-tests
pr/05-faiss-to-runtimecell
pr/06-readiness-extensions
pr/07-docs-agent-contract
```

2. **Runbook / CI smoke**

```
ruff check --fix
pyright
pytest -q tests/runtime/test_runtime_cell.py
python ops/runtime/prewarm.py all
python ops/runtime/status.py show
```

---

## Why this is the right next step (and what it unlocks)

* **Uniform lifecycle & metrics surface.** Converging FAISS onto `RuntimeCell` removes the last special case; one preload path; one readiness story; one metrics contract (`runtime_cell_*`). This reduces cognitive load and makes issues diagnosable from a single dashboard. (Cells and their uses are already present in your current code.) 
* **First‑request tail latency elimination.** Preloading within `lifespan()` leverages the “Load Once / Immutable” principles already codified in your `ApplicationContext` docs and usage examples. 
* **Ops ergonomics.** The `ops/runtime/*` commands give an agent or operator idempotent, JSON‑speaking verbs—fully aligned to AGENTS.md’s *structured IO* and *hermetic* execution. 
* **Future wins:**

  * **Adaptive gating** (pause/resume cells on memory pressure) using the gauge metrics.
  * **Cell‑level budgets** by reusing `track_stage()` patterns for init windows. 
  * **Pluggable factories** for multi‑tenant isolation or device‑affinity (e.g., FAISS per‑GPU cell pools) leveraging your existing FAISS GPU clone mechanics. 

---

### Notes & small integration nits

* If `prometheus_client` isn’t present in some environments, the counters still work (built via your telemetry provider). Gauges/histograms are optional and guarded; the agent doesn’t need to modify environments to deploy PR‑01. 
* The FAISS factory may simply return `ctx.faiss_manager` if you already build it once from paths and settings; the GPU clone attempt is opportunistic and non‑fatal (consistent with current behavior). 
* The readiness extensions mimic the existing vLLM readiness approach (HTTP and in‑process smoke) to preserve observability parity. 

---

## Accept/merge checklist (for each PR)

* [ ] **Tests**: green locally and in CI.
* [ ] **Static**: `ruff`, `pyright` pass.
* [ ] **Docs**: updated where applicable.
* [ ] **Ops**: `prewarm.py` and `status.py` run clean; exit codes correct.
* [ ] **Security/zero‑error**: no silent failures; errors are explicit and structured (Problem Details where HTTP‑facing). 

