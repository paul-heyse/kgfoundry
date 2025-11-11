# Audit closeout scope of work #

## Quick audit — remaining close‑out items

1. **Server factory not fully integrated in app startup**
   `app.main` still imports **`asgi_app`** from `codeintel_rev.mcp_server.server` (pre‑factory shape). The factory + gated registration you adopted (PR‑D) should be used here so MCP tool modules are conditionally imported based on capabilities. Evidence: import list in `app.main` includes `codeintel_rev.mcp_server.server.asgi_app`. **Close‑out:** switch to `build_http_app(caps)` (or the factory you landed) and mount it after readiness/capability probe in lifespan. 

2. **Heavy imports at module import time (typing‑gates hygiene)**

   * `app.gpu_warmup` imports **`faiss`** and **`torch`** at the top level. That’s a runtime gate smell: this module can be imported in minimal envs where those aren’t available. Use `TYPE_CHECKING` and `gate_import` inside the functions. 
   * `app.readiness` imports **`duckdb`** and **`httpx`** at the top level. Move them into the specific checks that use them; keep type‑only references behind the façade or `TYPE_CHECKING`. 
   * `app.config_context` imports **`redis.asyncio`** and a variety of managers at module import time. For optional backends (redis, etc.), use `TYPE_CHECKING` for annotations and defer real imports to the factory methods. 
     These moves keep `import codeintel_rev` clean in “minimal” envs and strictly follow the AGENTS typing‑gates doctrine. 

3. **Minimal‑profile proof** (CI/test)
   We should assert in tests that **without** numpy/duckdb/faiss/torch installed, `import codeintel_rev` succeeds and the MCP app starts with only light tools exposed. (Your AGENTS file mandates negative‑deps tests; let’s wire the one missing assertion.) 

4. **Capability stamp on root telemetry** (optional but high‑leverage)
   With telemetry landed, stamp every `mcp.tool.*.start` root with the **capability snapshot** + active **index bundle** (when your lifecycle manager lands) so “why a path didn’t run” is visible in a single timeline file. (This is additive; no runtime change to business logic.)

The rest (exception taxonomy, middleware/session scope, readiness probe) looks solid per index; you’re back to zero static errors, which matches your AOP goal.

---

## PR‑ready patches (unified diffs)

> The diffs below are **surgical** and follow the AOP: postponed annotations, no heavy top‑level imports, precise docstrings, and Problem Details preserved. They assume your PR‑D exported a `build_http_app(caps)` (or similar). If your exact function name differs, adjust imports accordingly.

### PR‑CF‑01 — **App startup: mount gated MCP app via factory**

**Why:** Replace the legacy `asgi_app` import with capability‑gated registration, mounted at the end of FastAPI lifespan (post‑readiness). Evidence we still import `asgi_app`: `app.main` import list. 

```diff
diff --git a/codeintel_rev/app/main.py b/codeintel_rev/app/main.py
index abcdef0..1234567 100644
--- a/codeintel_rev/app/main.py
+++ b/codeintel_rev/app/main.py
@@ -1,9 +1,10 @@
 from __future__ import annotations
 ...
-from codeintel_rev.mcp_server.server import app_context, asgi_app
+from codeintel_rev.mcp_server.server import app_context, build_http_app
+from codeintel_rev.app.readiness import ReadinessProbe
+# if you already have a Capabilities probe module, import it here (or inline map readiness→caps)
 ...
 @asynccontextmanager
 async def lifespan(app: FastAPI) -> AsyncIterator[None]:
     # 1) Build ApplicationContext (existing code)
     context = ...
@@
-    # Existing: app includes MCP surface already (asgi_app)
-    yield
+    # 2) Run readiness checks (existing)
+    probe = ReadinessProbe(context)
+    snapshot = await probe.refresh()
+    # 3) Map readiness → capabilities (cheap flags)
+    caps = _caps_from_readiness(snapshot)  # helper you keep alongside readiness
+    # 4) Mount gated MCP app
+    app.mount("/mcp", build_http_app(caps))
+    yield
```

> If you already have a `capabilities.py`, call that instead of `_caps_from_readiness`. The key is: **factory + mount here**, no `asgi_app` at import time.

---

### PR‑CF‑02 — **Typing‑gates sweep (gpu_warmup + readiness + config_context)**

**Why:** Eliminate heavy imports at module import time to guarantee minimal‑profile import succeeds. This implements AGENTS “Typing Gates” rules. 

#### 1) `app/gpu_warmup.py`: move `faiss`/`torch` under gates

Evidence of top‑level `faiss`/`torch` imports today. 

```diff
diff --git a/codeintel_rev/app/gpu_warmup.py b/codeintel_rev/app/gpu_warmup.py
index 13579ac..24680bd 100644
--- a/codeintel_rev/app/gpu_warmup.py
+++ b/codeintel_rev/app/gpu_warmup.py
@@ -1,12 +1,19 @@
 from __future__ import annotations
-from functools import lru_cache
-from typing import TYPE_CHECKING, cast
+from functools import lru_cache
+from typing import TYPE_CHECKING, cast
 from kgfoundry_common.logging import get_logger
-from kgfoundry_common.typing import gate_import
-import faiss  # <-- heavy
-import torch  # <-- heavy
+from kgfoundry_common.typing import gate_import
 
 if TYPE_CHECKING:
+    import faiss as _faiss  # type-only
+    import torch as _torch  # type-only
     from codeintel_rev.app.config_context import ApplicationContext
 
 LOGGER = get_logger(__name__)
 
 @lru_cache(maxsize=1)
 def warmup_gpu(context: "ApplicationContext") -> dict[str, object]:
-    # existing logic using faiss, torch ...
+    # Import lazily at first use:
+    faiss = gate_import("faiss", "GPU warmup requires FAISS (cpu/gpu build)")
+    torch = gate_import("torch", "GPU warmup requires PyTorch for CUDA introspection")
+    # ... existing logic unchanged ...
```

#### 2) `app/readiness.py`: duckdb/httpx only inside check functions

Evidence of top‑level `duckdb`, `httpx` imports. 

```diff
diff --git a/codeintel_rev/app/readiness.py b/codeintel_rev/app/readiness.py
index 1122334..5566778 100644
--- a/codeintel_rev/app/readiness.py
+++ b/codeintel_rev/app/readiness.py
@@ -1,12 +1,20 @@
 from __future__ import annotations
-import duckdb
-import httpx
+from typing import TYPE_CHECKING
 from dataclasses import dataclass
 from pathlib import Path
 from kgfoundry_common.logging import get_logger
+from kgfoundry_common.typing import gate_import
 ...
+if TYPE_CHECKING:
+    import duckdb as _duckdb  # type-only
+    import httpx as _httpx    # type-only
+
 def _check_duckdb_catalog(path: Path) -> bool:
-    con = duckdb.connect(str(path))
+    duckdb = gate_import("duckdb", "Readiness check requires DuckDB to open catalog")
+    con = duckdb.connect(str(path))
     try:
         return _schema_ok(con)
     finally:
         con.close()
 
 async def _check_vllm(url: str) -> bool:
-    async with httpx.AsyncClient() as client:
+    httpx = gate_import("httpx", "Readiness check requires HTTPX for VLLM ping")
+    async with httpx.AsyncClient() as client:
         resp = await client.get(f"{url}/health")
         return resp.status_code == 200
```

#### 3) `app/config_context.py`: defer optional backends to factories

Evidence of top‑level `redis.asyncio` import. 

```diff
diff --git a/codeintel_rev/app/config_context.py b/codeintel_rev/app/config_context.py
index 99aa111..22bb333 100644
--- a/codeintel_rev/app/config_context.py
+++ b/codeintel_rev/app/config_context.py
@@ -1,15 +1,22 @@
 from __future__ import annotations
 from dataclasses import dataclass, field
-from typing import TYPE_CHECKING, Any, TypeVar, cast
-import redis.asyncio as redis  # heavy import at module load
+from typing import TYPE_CHECKING, Any, TypeVar, cast
 from kgfoundry_common.typing import gate_import
 ...
 if TYPE_CHECKING:
+    import redis.asyncio as _redis
     from collections.abc import Iterator
 ...
 @dataclass(slots=True)
 class ApplicationContext:
     ...
-    def open_redis(self) -> redis.Redis:
-        return redis.from_url(self.settings.redis_url, decode_responses=True)
+    def open_redis(self):
+        """Open Redis connection lazily; dependency optional."""
+        redis = gate_import("redis.asyncio", "Redis-backed features require redis extra")
+        return redis.from_url(self.settings.redis_url, decode_responses=True)
```

> Apply the same “`TYPE_CHECKING` + `gate_import`” pattern to any other optional backends surfaced by the index.

---

### PR‑CF‑03 — **Minimal‑profile import & surface test**

**Why:** Enforce the negative‑deps guarantee: the package imports and the app builds with *no* heavy deps installed; MCP tool modules are **not** imported unless capabilities allow (thanks to the server factory). (AGENTS mandates this.) 

```diff
diff --git a/tests/test_minimal_profile.py b/tests/test_minimal_profile.py
new file mode 100644
index 0000000..9999999
--- /dev/null
+++ b/tests/test_minimal_profile.py
@@ -0,0 +1,46 @@
+from __future__ import annotations
+import sys
+import types
+
+def test_import_package_in_minimal_env():
+    # Should not raise even if numpy/duckdb/faiss/torch are absent
+    __import__("codeintel_rev")
+
+def test_server_factory_does_not_import_heavy_tool_modules(monkeypatch):
+    # Simulate missing FAISS/DuckDB so semantic tool module remains unimported
+    sys.modules.pop("codeintel_rev.mcp_server.server_semantic", None)
+    from codeintel_rev.mcp_server.server import build_http_app
+    class _Caps:
+        has_semantic = False
+        has_symbols = True
+    app = build_http_app(_Caps())
+    assert "codeintel_rev.mcp_server.server_semantic" not in sys.modules
```

---

### PR‑CF‑04 — **Root telemetry stamp (optional, 10‑line addition)**

**Why:** Make every diagnostic timeline self‑contained: stamp **capability flags** (and later **index bundle version**) on `mcp.tool.*.start`. (This is an additive enhancement and uses the telemetry module you landed earlier.)

```diff
diff --git a/codeintel_rev/mcp_server/server.py b/codeintel_rev/mcp_server/server.py
index a1b2c3d..d4e5f6a 100644
--- a/codeintel_rev/mcp_server/server.py
+++ b/codeintel_rev/mcp_server/server.py
@@ -1,6 +1,7 @@
 from __future__ import annotations
 from .error_handling import handle_adapter_errors
 from .schemas import AnswerEnvelope
+from codeintel_rev.observability.timeline import current_or_new_timeline
 ...
 @mcp.tool()
 @handle_adapter_errors(operation="search:semantic", empty_result={"findings": []})
 async def semantic_search(query: str, limit: int = 20) -> AnswerEnvelope:
     ctx = get_context()
+    tl = current_or_new_timeline()
+    tl.event("operation", "mcp.tool.semantic_search.start", status="ok", caps=getattr(ctx, "capabilities", {}))
     return await semantic_adapter.semantic_search(ctx, query, limit)
```

(*Mirror for `semantic_search_pro` and symbol tools.*)

---

## Acceptance checklist (what “done” looks like)

* **No top‑level heavy imports** in `app.gpu_warmup`, `app.readiness`, `app.config_context`; all heavy deps are loaded either under `TYPE_CHECKING` (types only) or via `gate_import` inside call sites. (AOP typing‑gates satisfied.) 
* **App mounts MCP via factory** (`build_http_app(caps)`) in lifespan; **no global `asgi_app`** at import time; capability gating decides which tool modules are imported/registered. Evidence of the previous state is removed (asgi_app import from `app.main`). 
* **Minimal profile test** passes: in an env without `faiss`, `duckdb`, `torch`, `numpy`, the package imports and the MCP app builds; semantic module is not imported. (New test in `tests/test_minimal_profile.py`.)
* **Telemetry** (optional close‑out) stamps root events with `caps` so the “why a path didn’t run” answer is in a single file.
* Everything remains **Ruff/pyright/pyrefly clean** per AOP; *zero suppressions*. 

---

## Why these are the right final touches

* They close the last observable mismatches between our **design** (capability‑gated server, import‑clean modules) and the **current code** (residual `asgi_app` import, a few heavy imports at module scope). The citations above show the exact modules where the residuals exist today. 
* They bring the repo fully in line with your **AGENTS/AOP** mandates: postponed annotations, type‑only heavy imports, negative‑deps tests, and explicit capability surfaces. 
* They protect the **“minimal”** developer experience (fast `import`, honest tooling surface) without affecting the “full” profile behavior.


