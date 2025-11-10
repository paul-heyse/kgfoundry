Fantastic—here’s a focused **pre‑flight audit & hardening checklist** for `codeintel_rev`, based strictly on the `index.json` (scip) signals you shared. I’ve grouped findings by runtime area and kept them actionable.

---

## 0) What I reviewed (quick scope)

* FastAPI app startup/lifespan and FAISS preload, plus readiness surface. 
* MCP server context handling, HTTP exposure, and error envelopes.
* Error taxonomy & Problem Details mapping.
* GPU warmup flow (torch + FAISS) and result shape. 
* DuckDB catalog access patterns for retrieval hydration. 
* Global Settings (immutability, Redis defaults, paths/index/limits, etc.). 

---

## 1) Startup, readiness & context handling

1. **Background work outside request context can break tool handlers.**
   `get_context()` relies on a contextvar set by middleware; it raises if missing. Any background Task/cron kicked off in startup (or long‑lived async tasks) that call tool adapters indirectly may see “context not initialized.”
   **Harden:**

   * Set a *global default* `ApplicationContext` in startup (before scheduling tasks) and have `get_context()` fall back to it with a clear error if truly absent.
   * Document that tool code should *not* run before lifespan has set context, or wrap tasks with a helper that seeds the contextvar. 

2. **FAISS preloading at startup can harm availability.**
   `_preload_faiss_index(context)` runs during startup to avoid first‑request latency. If the index is large or storage is cold, your process can sit in `ContainerCreating/NotReady` for a long time.
   **Harden:**

   * Gate preloading behind a config flag (e.g., `INDEX_PRELOAD=1`).
   * Add a timeout + warning path that starts the app in *degraded* mode while readiness keeps reporting “warming up” until preloading completes.
   * Log index size & load duration. 

3. **CORS defaults may be overly permissive.**
   App advertises CORS support; if configured loosely, browser clients could exfiltrate results.
   **Harden:**

   * Restrict allowed origins/headers/methods explicitly via env‑driven allowlist.
   * Add tests asserting the expected CORS headers on the health/readiness endpoints. 

---

## 2) GPU warmup flow (torch + FAISS)

4. **Import/feature probing is likely fragile on mixed FAISS installs.**
   `_check_faiss_gpu_support()` infers GPU capability by checking for GPU symbols (e.g., `StandardGpuResources`, `GpuClonerOptions`, `index_cpu_to_gpu`). If the CPU‑only build of `faiss` is present, attribute probing returns false—but if `faiss` itself isn’t importable, this probably surfaces as an exception rather than a clean “no GPU” state.
   **Harden:**

   * Wrap `import faiss` in `try/except ImportError` and return `(False, "faiss not installed")`.
   * Keep symbol checks, but ensure any `AttributeError` becomes `(False, "faiss installed without GPU symbols")`. 

5. **Result contract mixes value types.**
   `warmup_gpu()` returns a dict with booleans and strings under a single `dict[str, bool | str]` annotation; clients can’t strongly type it and might mis-handle failures.
   **Harden:**

   * Introduce a `TypedDict` (or msgspec `Struct`) with explicit fields and literal status:

     * `cuda_available: bool`, `faiss_gpu_available: bool`, `torch_gpu_test: bool`, `faiss_gpu_test: bool`, `overall_status: Literal["ready","degraded","unavailable"]`, `details: str`.
   * Treat unexpected exceptions as `"unavailable"` but include a terse `details`. 

6. **Torch GPU test should avoid device churn on multi‑GPU hosts.**
   The private test function creates tensors on CUDA. If multiple devices exist, default device selection may surprise you (e.g., MIG or zero‑memory contexts).
   **Harden:**

   * Respect `CUDA_VISIBLE_DEVICES` or accept a preferred device index via env; ensure a small allocation (e.g., 1–2 MB) and catch OOM separately. 

---

## 3) Error taxonomy & envelopes

7. **Line range validation is good—ensure *all* callers normalize.**
   `InvalidLineRangeError(path, line_range)` is mapped to a 400 (“invalid-parameter”). Ensure every adapter that accepts `start_line/end_line` routes through the *same* validator to catch negatives, inverted ranges, and excessive spans (large spans can blow up token budgets).
   **Harden:**

   * Add a common `normalize_line_range(path, start, end)` helper that clamps, swaps if inverted, and caps max span (configurable).
   * Include `line_range` in Problem Details extensions consistently. 

8. **Git errors: status code & context are well‑defined—prefer `raise … from`.**
   `GitOperationError` carries `path` and `git_command`, maps to 500, and encourages `raise … from` to preserve chains. Make sure adapters *always* populate `git_command` (“blame”, “log”, etc.).
   **Harden:**

   * Add a tiny helper: `raise_git_error(cmd, path, exc)` to standardize context and reduce drift.
   * Consider downgrading a few known “expected” conditions (e.g., repo missing) to 404/409 via a different exception class. 

9. **Uniform error envelope is clear but success detection can be brittle.**
   The decorator returns either the success payload or an “empty_result + error + problem {…}” envelope. Some clients probe `error`/`problem` fields; others might rely on HTTP status.
   **Harden:**

   * Add `ok: bool` (true on success) to the envelope so clients can branch reliably without mixing transport semantics with payload shape.
   * Keep the readable `problem.type/title/status/code` you already standardize. 

---

## 4) Data access & hydration (DuckDB)

10. **IN‑clause fan‑out in `query_by_ids()` can degrade badly.**
    Hydrating FAISS results by `ids: Sequence[int]` uses a single SQL `IN (…)`. That’s fine for dozens, but hundreds/thousands of ids can blow up the query string or planner.
    **Harden:**

    * Chunk into batches (e.g., 256–512 ids) and `UNION ALL` results.
    * Or materialize an in‑memory relation (VALUES) and join, which DuckDB handles well.
    * Keep the documented “empty list → empty result” fast path. 

11. **Catalog probes should avoid racey existence checks.**
    `_relation_exists(conn, name)` tests if a relation exists in `main`. A create‑or‑replace call right after can still race with a concurrent writer.
    **Harden:**

    * Prefer atomic `CREATE OR REPLACE` where possible and treat existence checks as advisory only. 

---

## 5) Settings & ops

12. **Redis defaults are “localhost”, which is dangerous in prod.**
    `RedisConfig.url` defaults to `redis://127.0.0.1:6379/0`. In multi‑container environments you’ll silently fall back to local (non‑HA) Redis or simply fail.
    **Harden:**

    * Require `REDIS_URL` in non‑dev environments; fail fast if missing.
    * Consider TLS options and tighter timeouts for the L2 cache. 

13. **Settings are immutable (good)—document override points.**
    `Settings` is a frozen msgspec `Struct`. Make sure your deployment docs call out *exactly* which env vars control FAISS preloading, BM25 prep, limits, etc., to prevent ad‑hoc monkeypatching at runtime. 

---

## 6) HTTP surface & MCP wiring

14. **ASGI exposure of FastMCP is clear—ensure mount path stays stable.**
    The server provides `asgi_app = mcp.http_app()`. Document that path and keep it backward compatible, because clients may persist routes. Also ensure your FastAPI app wraps request context so MCP handlers can reach `ApplicationContext`. 

15. **Lifespan error classification**
    `ConfigurationError` is raised on bad config; anything else is re‑raised to keep the process from starting. That’s the right default—just make sure logs include the *operation* that failed (e.g., “faiss:preload”, “duckdb:open”).
    **Harden:** add `operation` fields to logs, using your structured logging helpers. 

---

## 7) Low‑effort tests I’d add **before** the next wave

* **GPU warmup contract test**: Assert keys and types, including that `overall_status` ∈ {ready,degraded,unavailable} and `details` is a string for all branches (torch missing, faiss CPU‑only, full GPU). 
* **Line‑range normalization**: Fuzz with negative, inverted, and enormous ranges; assert `InvalidLineRangeError` or clamping behavior consistently. 
* **Hydration fan‑out**: Feed `query_by_ids()` with 0, 1, 100, 1,000 ids and assert latency/plan sanity (or chunking behavior if you implement it). 
* **Context presence**: Call a simple MCP tool from a background task to ensure the context fallback behavior works (or raises a *clear* error). 

---

## 8) Drop‑in patch checklist (copy/paste into a PR)

```markdown
### Hardening tasks
- [ ] GPU: add robust `import faiss` guard + clearer messages in `_check_faiss_gpu_support()`.
- [ ] GPU: replace `dict[str, bool | str]` with a `TypedDict` (or msgspec Struct) for warmup result; use `Literal` for `overall_status`.
- [ ] Start-up: add `INDEX_PRELOAD` flag; move FAISS preload to a timed task that sets readiness gate and logs duration.
- [ ] Context: seed a global default `ApplicationContext` at startup; make `get_context()` fall back to it with a helpful error.
- [ ] DuckDB: chunk `query_by_ids()` IN-lists or join against a VALUES relation.
- [ ] Errors: add `ok: bool` to the decorator envelope; ensure all adapters populate `git_command` when raising `GitOperationError`.
- [ ] Lines: centralize `normalize_line_range()` and use everywhere.
- [ ] CORS: restrict to an explicit allowlist via env.
- [ ] Redis: require `REDIS_URL` outside dev; add timeouts/TLS envs.
- [ ] Logs: include `operation` field for all startup steps and critical exceptions.
```

---

### Closing note

The core architecture reads clean and deliberate—immutable settings, explicit lifespan, consistent Problem Details, and a clear warmup signal are all solid foundations. The items above are mostly operational hardening and contract‑clarity tweaks; they should reduce edge‑case breakage and make client behavior more predictable as you scale out the next set of features.

If you want, I can turn the checklist into small PR‑ready patches (typed warmup result, chunked DuckDB hydration, and a context fallback) or tailor it to your deployment topology.

**References pulled from your `index.json` (scip) snapshot:** GPU warmup & symbols, FastAPI lifespan & preload, MCP error envelopes & contextvar accessors, DuckDB catalog helpers, and Settings/Redis defaults.




Awesome — I turned the “spot‑fixes” we discussed into a handful of tiny, PR‑ready patches. Each patch is independent, has a crisp commit message, and comes with a short test plan. I’ve kept them small and surgical so they’re easy to review and merge.

Below I first summarize the issues (with citations into your SCIP index), then provide unified diffs you can apply directly (`git apply`), and finally list quick test steps.

---

## What I’m fixing (at a glance)

1. **Typing bug/footgun:** `_RuntimeHandle` is used as a *generic* (e.g. `_RuntimeHandle[HybridSearchEngine]`) but the class itself isn’t declared `Generic`, so the subscripted usage only succeeds due to “pretend generics” and loses type information at runtime. Making the class `Generic[T]` and the `.value` property `T | None` tightens correctness and improves IDE/type checker behavior.  

2. **Warmup fragility & duplicate work:** `warmup_gpu()` can be called multiple times during app lifetime; it currently re‑does the same checklist and logs each time. Memoizing it (`@lru_cache(maxsize=1)`) makes the warmup idempotent and cheap after the first call, and switching to your structured logger aligns it with the rest of the app logging. 

3. **Path readiness vs. docs mismatch:** The path resolver advertises “fail‑fast, resolve and validate,” and the rest of the app expects certain *directories* to exist by the time readiness checks run. Guaranteeing the directory tree (e.g., `data_dir`, `vectors_dir`, `coderank_vectors_dir`, `warp_index_dir`, `xtr_dir`) eliminates a class of “works on my machine” flakiness and matches how readiness treats filesystem resources.  

4. **Noisy/duplicated readiness limits:** `ApplicationContext.ensure_faiss_ready()` appends the same “GPU disabled reason” warning more than once under some paths; the code even uses `list.count()` to detect this but still ends up with duplicates. Deduping while preserving order makes the envelope downstream nicer (and deterministic). 

5. **Middleware order (CORS):** CORS middleware is safer/cleaner when mounted *before* custom middleware so preflights don’t get entangled with session/scoping concerns. Reordering keeps the same semantics but reduces risk on OPTIONS preflights. 

6. **Public exports:** Add explicit `__all__` for the modules that are meant to be imported by others (`app`, `config_context`, `gpu_warmup`). This prevents star‑imports from leaking internal symbols and makes the public surface obvious. (Your other packages already do this in several places; e.g., `errors.__all__`.) 

---

## Patches

> Apply individually with `git apply <<'PATCH'` … `PATCH` (or use your favorite patch workflow). Paths are relative to the repo root.

---

### 1) typing: make `_RuntimeHandle` truly generic + type its `.value`

**Rationale:** You subscript `_RuntimeHandle[...]` across the context runtime state, but the class isn’t declared `Generic`. This change makes the intent explicit and prevents a class of subtle typing issues.  

```diff
diff --git a/codeintel_rev/app/config_context.py b/codeintel_rev/app/config_context.py
--- a/codeintel_rev/app/config_context.py
+++ b/codeintel_rev/app/config_context.py
@@
-from dataclasses import dataclass, field
+from dataclasses import dataclass, field
+from typing import Generic, TypeVar
 from contextlib import contextmanager
@@
-class _RuntimeHandle:
+T = TypeVar("T")
+
+class _RuntimeHandle(Generic[T]):
     """
     Mutable holder for lazily initialized singletons.
     """
     __slots__ = ("_lock", "value")
 
     def __init__(self) -> None:
         self._lock = Lock()
-        self.value = None
+        self.value: T | None = None
@@
 @dataclass(slots=True, frozen=True)
 class _ContextRuntimeState:
-    hybrid: _RuntimeHandle[HybridSearchEngine] = field(default_factory=_RuntimeHandle)
-    coderank_faiss: _RuntimeHandle[FAISSManager] = field(default_factory=_RuntimeHandle)
-    xtr: _RuntimeHandle[XTRIndex] = field(default_factory=_RuntimeHandle)
+    hybrid: _RuntimeHandle[HybridSearchEngine] = field(default_factory=_RuntimeHandle)
+    coderank_faiss: _RuntimeHandle[FAISSManager] = field(default_factory=_RuntimeHandle)
+    xtr: _RuntimeHandle[XTRIndex] = field(default_factory=_RuntimeHandle)
     faiss: _FaissRuntimeState = field(default_factory=_FaissRuntimeState)
```

*Touchpoints that already use the subscripted form (works better after this change):* your `_ContextRuntimeState` fields and getters for CodeRank/XTR.

---

### 2) gpu: memoize warmup + align logger with app’s structured logger

**Rationale:** Make warmup idempotent and cheap, and ensure logs follow your standard logger. 

```diff
diff --git a/codeintel_rev/app/gpu_warmup.py b/codeintel_rev/app/gpu_warmup.py
--- a/codeintel_rev/app/gpu_warmup.py
+++ b/codeintel_rev/app/gpu_warmup.py
@@
-import logging
+from functools import lru_cache
+from kgfoundry_common.logging import get_logger
@@
-logger = logging.getLogger(__name__)
+LOGGER = get_logger(__name__)
@@
-def warmup_gpu() -> dict[str, bool | str]:
+@lru_cache(maxsize=1)
+def warmup_gpu() -> dict[str, bool | str]:
     """
     Run best-effort GPU readiness checks (PyTorch + FAISS).
 
-    Returns a dict with per-subsystem results and an overall status.
+    Results are cached after the first successful run to avoid repeating
+    heavyweight checks on subsequent calls. Use ``warmup_gpu.cache_clear()``
+    in tests to force a re-run.
@@
-    logger.info("Starting GPU warmup checks")
+    LOGGER.info("Starting GPU warmup checks")
@@
-        logger.warning("Torch CUDA check failed", extra={"error": str(e)})
+        LOGGER.warning("Torch CUDA check failed", extra={"error": str(e)})
@@
-        logger.warning("FAISS GPU check failed", extra={"error": str(e)})
+        LOGGER.warning("FAISS GPU check failed", extra={"error": str(e)})
@@
-    logger.info(
+    LOGGER.info(
         "GPU warmup completed",
         extra={"torch_ok": torch_ok, "faiss_ok": faiss_ok, "overall": overall},
     )
```

*Notes:* The public surface stays the same (`warmup_gpu()`), and the function is still safe in CPU‑only environments—it simply reports degraded mode. (It already returns a dict of booleans/strings; this preserves that contract.) 

---

### 3) paths: proactively create expected directory tree

**Rationale:** Your resolver/docstring implies “validated and ready” paths; readiness probes also assume certain directories exist. Creating the directories once during startup removes class‑of‑errors where later file writes or checks fail purely because a parent dir doesn’t exist.  

```diff
diff --git a/codeintel_rev/app/config_context.py b/codeintel_rev/app/config_context.py
--- a/codeintel_rev/app/config_context.py
+++ b/codeintel_rev/app/config_context.py
@@
 def resolve_application_paths(settings: Settings, *, context: Mapping[str, object] | None = None) -> ResolvedPaths:
@@
     paths = ResolvedPaths(
         repo_root=repo_root,
         data_dir=data_dir,
         vectors_dir=vectors_dir,
         faiss_index=faiss_index,
         coderank_vectors_dir=coderank_vectors_dir,
         coderank_faiss_index=coderank_faiss_index,
         warp_index_dir=warp_index_dir,
         xtr_dir=xtr_dir,
         duckdb_catalog=duckdb_catalog,
         scip_index=scip_index,
     )
+
+    # Ensure directory hierarchy exists for downstream components that
+    # write files on demand (fail fast on permission issues).
+    for d in (
+        paths.data_dir,
+        paths.vectors_dir,
+        paths.coderank_vectors_dir,
+        paths.warp_index_dir,
+        paths.xtr_dir,
+    ):
+        d.mkdir(parents=True, exist_ok=True)
+        LOGGER.debug("Ensured path exists", extra={"path": str(d)})
 
     return paths
```

*Why now?* The app already treats missing files as “optional/limits” in readiness, but *directories* are a safer “always present” invariant and match the rest of the system’s expectations. 

---

### 4) faiss: deduplicate “limits” in `ensure_faiss_ready()`

**Rationale:** Under certain interleavings, the same GPU‑disabled warning is appended more than once. Dedup while preserving order for cleaner envelopes/logs. 

```diff
diff --git a/codeintel_rev/app/config_context.py b/codeintel_rev/app/config_context.py
--- a/codeintel_rev/app/config_context.py
+++ b/codeintel_rev/app/config_context.py
@@
     # ... existing logic that fills `limits` list ...
@@
-    return ready, limits, error
+    # Preserve order while removing duplicates.
+    limits = list(dict.fromkeys(limits))
+    return ready, limits, error
```

*Where duplicates come from:* the method may append the same `gpu_disabled_reason` across different branches; the index shows multiple `limits.append(...)` calls and even a `list.count()` check around the same reason. This keeps the signal once. 

---

### 5) web: mount CORS before custom middleware

**Rationale:** Put CORS first so preflights aren’t affected by session/scope middleware. Safe change; behavior of both middlewares is preserved. 

```diff
diff --git a/codeintel_rev/app/main.py b/codeintel_rev/app/main.py
--- a/codeintel_rev/app/main.py
+++ b/codeintel_rev/app/main.py
@@
 app = FastAPI(title="CodeIntel MCP Server")
 
-# Session/context middleware (uses contextvars)
-app.add_middleware(SessionScopeMiddleware)
-
-# CORS
-app.add_middleware(
+# CORS first (handle preflights early)
+app.add_middleware(
     CORSMiddleware,
     allow_origins=settings.server.cors_allow_origins,
     allow_credentials=True,
     allow_methods=["*"],
     allow_headers=["*"],
 )
+
+# Session/context middleware (uses contextvars)
+app.add_middleware(SessionScopeMiddleware)
```

---

### 6) hygiene: declare explicit public exports

**Rationale:** Make the public surface explicit, mirroring patterns elsewhere (e.g., `errors.__all__`). 

```diff
diff --git a/codeintel_rev/app/config_context.py b/codeintel_rev/app/config_context.py
--- a/codeintel_rev/app/config_context.py
+++ b/codeintel_rev/app/config_context.py
@@
 __all__ = [
-    # existing if any
+    "ResolvedPaths",
+    "ApplicationContext",
+    "resolve_application_paths",
 ]
 
diff --git a/codeintel_rev/app/gpu_warmup.py b/codeintel_rev/app/gpu_warmup.py
--- a/codeintel_rev/app/gpu_warmup.py
+++ b/codeintel_rev/app/gpu_warmup.py
@@
+__all__ = ["warmup_gpu"]
 
diff --git a/codeintel_rev/app/main.py b/codeintel_rev/app/main.py
--- a/codeintel_rev/app/main.py
+++ b/codeintel_rev/app/main.py
@@
+__all__ = ["app"]
```

---

## Quick test plans

**Patch 1 (typing/generic)**

* Run `pyright` or your type checker; usages like `_RuntimeHandle[FAISSManager]` should now be fully typed rather than “pretend generics”. Confirm attributes accessed through `.value` are correctly type‑narrowed. (See `_RuntimeHandle` value/type and generic usage in the index.)

**Patch 2 (gpu warmup)**

* Start app twice (or call `warmup_gpu()` twice in a REPL). The second call should log only the “completed” line (no repeated checks) and be near‑instant. Ensure logs now use your structured logger like the rest of the app.

**Patch 3 (paths)**

* With a fresh repo checkout and *no* pre‑created data dirs, start the app. Confirm no subsequent file‑write paths fail with `ENOENT` and that readiness checks referencing these directories don’t report “not found” purely due to missing parents. 

**Patch 4 (limits dedup)**

* Simulate an environment where GPU is “disabled” twice (e.g., call `ensure_faiss_ready()` before/after a preload path that sets the same `gpu_disabled_reason`). You should see the single warning string once in the returned `limits`. 

**Patch 5 (middleware order)**

* Send an `OPTIONS` preflight request and verify CORS headers are present without being affected by scope middleware. Regular requests should behave exactly as before. 

**Patch 6 (exports)**

* Try `from codeintel_rev.app.config_context import *` in a scratch script; only public objects should be present. This matches your pattern in other modules (e.g., `errors.__all__`). 

---

## Why these are “best-of-class” fixes for the codebase

* **No feature drift**: All patches are strictly about correctness, resilience, and maintainability.
* **Low risk, high leverage**: They target glue code (context wiring, warmup, readiness) where small improvements ripple across many flows.
* **Typed & explicit**: Bringing `_RuntimeHandle` in line with how it’s used protects you from subtle future regressions in the runtime cache/handles.
* **Production ergonomics**: Warmup memoization + path creation reduce noisy logs, redundant work, and one‑off “missing directory” errors when deploying fresh.

If you’d like, I can bundle these into separate PR branches (e.g., `chore/typing-runtime-handle`, `fix/gpu-warmup-memoize`, `chore/paths-ensure-dirs`, `fix/faiss-limits-dedup`, `chore/cors-first`, `chore/public-exports`) with commit messages matching the titles above.

---

### Citations (from your `index.json` SCIP index)

* `_RuntimeHandle` definition & non‑generic property: class shows `.value: None` and no `Generic` in current state. 
* `_RuntimeHandle[...]` usage inside `_ContextRuntimeState` and getters:
* `warmup_gpu()` and logger usage in `gpu_warmup.py`:
* Path resolution contract and readiness’ file semantics: ; readiness file check semantics. 
* Duplicate `limits` appends in `ensure_faiss_ready()` paths: see the multiple `append`/`count` occurrences. 
* `main.py` middleware registration order (Session then CORS today): 
* Existing explicit `__all__` pattern (e.g., `errors.__all__`): 

---

If you want me to extend this into CI checks (e.g., a simple unit that asserts warmup is cached or that `ensure_faiss_ready()` returns unique `limits`), I can add those as follow‑on patches in the same style.
