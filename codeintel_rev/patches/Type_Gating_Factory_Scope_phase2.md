# Context and overview #

Wonderful — with PR‑B (runtime gates in cell factories) and PR‑D (server factory + gated registration) underway, here’s a best‑in‑class, *implementation‑grade* scope for the remaining three:

* **PR‑A — Typing façade sweep (and heavy‑import hygiene)**
* **PR‑C — `/capz` capabilities endpoint (capability snapshot + schema + metrics)**
* **PR‑E — CI matrices + automated gate enforcer (typing‑gates checker + negative‑deps tests)**

I’ve aligned each scope with your AOP/AGENTS doctrine (ruff+pyright+pyrefly zero‑error mandate, Problem Details, observability), and with the runcells + capability‑gated server architecture you’re adopting. Where concrete file paths or behaviors are referenced, I cite the current tree so reviewers can jump straight to source. 

---

## Shared baseline & invariants (post PR‑B/PR‑D)

* **Runtime is lazy and import‑clean:** heavy clients (FAISS, XTR, Hybrid) are produced *only* by runcell factories, and the `ApplicationContext` just *attaches observers* on init — no heavy work at import time. Keep this invariant intact in all three PRs. 
* **Factories own failure modes:** `RuntimeCell.get_or_initialize` handles concurrency, idempotency, and “fail‑fast then retry later”, so any new checks we add should throw typed errors there (converted to Problem Details by your existing wrappers). 
* **Adapters are the orchestration surface:** semantic/semantic_pro fan‑out (embedding → FAISS → fusion → DuckDB hydration → optional LI/reranker) is already documented; our gating should never re‑orchestrate those steps in wrappers — just short‑circuit gracefully when a capability is missing. 

---

# PR‑A — **Typing façade sweep** (heavy‑import hygiene across the repo)

### Goal

Eliminate *all* remaining “typing‑gate” violations by centralizing heavy type hints behind a façade, guarding imports with `TYPE_CHECKING`, and using `gate_import(...)` **only** inside the few runtime paths that truly need them. This locks in import‑time lightness, complements the runcell gates, and matches your AOP rules (postponed annotations, TC001–TC006, PLC2701). 

### Design decisions

1. **Façade module(s)**

   * **Canonical:** `kgfoundry_common.typing` (public, shared) + **thin re‑export:** `codeintel_rev.typing` (keeps first‑party imports short).
   * Expose typed aliases under `TYPE_CHECKING` only:

     * `NDArrayF32`, `NDArrayI64` (→ `numpy.typing.NDArray[np.float32]`, etc.)
     * `DuckDBConn` (→ `duckdb.DuckDBPyConnection`), `FaissIndexLike` (→ `faiss.Index`)
     * `FastAPI`/`Pydantic` symbols used solely in annotations (app code may still return `JSONResponse` to avoid forcing Pydantic at runtime).
   * Provide a single `gate_import(name, purpose, *, min_version=None, extra_hint=None) -> ModuleType` helper that standardizes the error message + “how to enable” hint (e.g., `pip install kgfoundry[faiss]`). The façade keeps the install‑hint registry in one place.

2. **Postponed annotations everywhere**

   * Ensure `from __future__ import annotations` is *the first import* in every touched module (AGENTS requires this; we’ll add it where missing). 

3. **Sweep patterns**

   * Replace `import numpy as np` (annotation‑only) with:

     ```py
     from typing import TYPE_CHECKING
     from codeintel_rev.typing import NDArrayF32
     if TYPE_CHECKING:
         import numpy as np
     ```

     Signatures use `NDArrayF32`; any *runtime* `numpy` usage occurs inside functions via `np = gate_import("numpy", "…")`.
   * **DuckDB/FAISS/FastAPI/Pydantic**: same pattern — type aliases from the façade; runtime modules only in runcell factories or adapter functions that *actually* call the libraries (never at module top‑level).
   * **Adapters**: keep annotations precise but ensure all heavy imports are type‑only; the runtime work remains in the adapter body. (E.g., semantic/semantic_pro annotations refer to `np.ndarray` via the façade; actual FAISS calls happen in the adapter/runcell code.) 

4. **Docs + AOP alignment**

   * Add a short recipe (“Using heavy types safely”) under `AGENTS.md` or link to the existing Typing Gates section; include before/after examples and the one‑liner “when to reach for `gate_import`.” 

### Files (illustrative — exact list from search)

* **New/extended:** `src/kgfoundry_common/typing/__init__.py`, `src/codeintel_rev/typing.py` (re‑export).
* **Touched:**

  * `src/codeintel_rev/mcp_server/adapters/semantic*.py` (annotation aliases; ensure runtime np/faiss only inside functions). 
  * `src/codeintel_rev/io/*` (e.g., FAISS/XTR/VLLM/SPLADE managers) — annotation‑only imports behind `TYPE_CHECKING`; runtime stays in factories. 
  * `src/codeintel_rev/io/duckdb_catalog.py` (type aliases for DuckDB connection types). 

### Tests & acceptance

* **Static gates:** `ruff check --fix` (TC001–TC006, PLC2701), `python -m tools.lint.check_typing_gates src/ tools/` must be green. 
* **Minimal env import:** in a venv **without** numpy/faiss/duckdb/pydantic, `python -c "import codeintel_rev"` must succeed; no ImportError from type‑only references.
* **Runtime parity:** existing unit tests for semantic/semantic_pro still pass; adapters continue to import heavy deps only inside call paths (proved by import‑graph diff + a smoke test that calls light endpoints).
* **No interface drift:** public signatures unchanged except for improved typing (aliases).

---

# PR‑C — **`/capz` capability snapshot** (schema’d, observable, cheap)

> You can treat PR‑C as the “truth source” for the server’s ability to offer specific tools, complementing the deeper `/readyz` health checks. It’s deliberately *cheap*: dynamic imports + file/flag checks only (no network, no index loads).

### API shape

* `GET /capz` → JSON document:

  ```json
  {
    "faiss": {"available": true, "reason": null},
    "faiss_gpu": {"available": false, "reason": "FAISS GPU libs not detected"},
    "duckdb": {"available": true, "reason": null},
    "vllm": {"available": true, "reason": null},
    "scip_index": {"available": true, "reason": null},
    "coderank_index": {"available": true, "reason": null},
    "warp_index_dir": {"available": false, "reason": "path missing"},
    "xtr": {"available": false, "reason": "torch not installed"}
  }
  ```

  This matches the capability set the MCP server needs to decide whether to register semantic and symbol tools (your adapter contracts/paths already make these requirements explicit). 

### Implementation

* **Module:** `codeintel_rev/app/capabilities.py`

  * `@dataclass Capability { available: bool; reason: str | None; extra: dict }`
  * `@dataclass Capabilities { faiss, faiss_gpu, duckdb, vllm, scip_index, coderank_index, warp_index_dir, xtr, … }`
  * `probe_capabilities(context) -> Capabilities`:

    * *Imports only*: `importlib.import_module("faiss")`, `"duckdb"`, `"httpx"`, `"torch"`, `"redis.asyncio"`; no client creation.
    * *Paths only*: truthily check `ApplicationContext.paths` for FAISS/SCIP/DuckDB artifacts (no open). 
    * *GPU bit*: best‑effort `faiss.get_num_gpus()` or presence of `StandardGpuResources` (guarded; still zero‑cost).
* **Route:** `app.main`

  * During `lifespan`, compute once and store `app.state.capabilities`.
  * `GET /capz` returns the cached snapshot; allow a `?refresh=true` query to recompute cheaply.
  * Log a structured line per probe (fields mirror the response) and expose a Prometheus gauge per capability.
* **Schema/Docs:** add OpenAPI for `/capz` with examples; for a light footprint, return `JSONResponse` (no Pydantic runtime requirement).

> This integrates cleanly with the server factory from PR‑D (which conditionally imports/ registers MCP tool modules based on the capability snapshot). 

### Tests & acceptance

* **Unit:** monkeypatch `importlib.import_module` to simulate missing modules (faiss, torch), verify JSON shape & reasons, and confirm no IO on probe.
* **E2E (light):** start the app in a minimal environment and assert that `/capz` aligns with *visible* MCP tools exposed by `build_http_app(caps)` (e.g., semantic tools absent if `faiss/duckdb` are false). 
* **Observability:** verify one info log line per startup; verify Prom metrics exported.

---

# PR‑E — **CI matrices + automated gate enforcer**

### Objectives

1. **Prove import‑cleanliness** in a *minimal* environment (no heavy deps installed).
2. **Prove full behavior** in a *full* environment.
3. **Detect regressions** automatically: new unguarded heavy imports or added suppressions.
4. Keep parity with the AOP local flow so engineers and agents get identical results. 

### CI layout (`.github/workflows/ci.yml`)

* **Jobs & matrices (illustrative):**

  * `precommit`: run pre‑commit hooks (format, basic lint).
  * `lint`: `ruff format && ruff check --fix`.
  * `types`: `pyright --warnings --pythonversion=3.13` + `pyrefly check`.
  * `tests` (**matrix**):

    * `profile: minimal | full`
    * **minimal**: install only base extras (no numpy/faiss/duckdb/pydantic/torch); run:

      * `python -c "import codeintel_rev"` (sanity)
      * `pytest -q -m "not integration and not gpu"` (fast unit set; skip semantic/e2e)
      * `python -m tools.lint.check_typing_gates src tools docs`
    * **full**: install with `[all]` or the specific extras you ship; run full test suite (integration allowed).
  * `security`: `pip-audit` (fail on critical vulns).
  * **Artifacts:** coverage.xml, htmlcov, portal/docs artifacts (if any), JUnit.

### Gate enforcer (tooling)

* **`tools/lint/check_typing_gates.py`**

  * **Source of truth list** of heavy modules (and min versions) imported from the façade registry (PR‑A); scan AST for imports of those names *outside* `TYPE_CHECKING`.
  * Emit pinpoint diagnostics: *file:line:col* with a suggested autofix (e.g., “Move `import numpy` into `if TYPE_CHECKING:`; replace annotation with `codeintel_rev.typing.NDArrayF32`; for runtime, wrap in `gate_import('numpy', '…')`.”).
  * Optionally provide a `--write` mode that applies the mechanical parts (adds `from __future__ import annotations` if missing; inserts `TYPE_CHECKING` block).
* **Suppression guard:** `tools/check_new_suppressions.py` fails CI if new `# type: ignore` or per‑file Ruff ignores appear without a ticket in the comment (this is already listed in your Quick Commands — wire it into CI for parity). 
* **Import graph check:** optional “import‑time smoke” that times `import codeintel_rev` and asserts a budget (keeps cold‑start snappy).

### Tests & acceptance

* **Minimal profile:** proves the package imports and light endpoints run with *no* heavy deps installed — a direct assertion of the Typing‑Gates doctrine.
* **Full profile:** proves parity for semantic/semantic_pro, symbol tools, and SPLADE/XTR behaviors on environments where those capabilities are present. (Adapters’ docstrings explicitly describe the pipeline stages; tests assert those stages appear in the method metadata of `AnswerEnvelope`.) 

---

## Cross‑PR integration points & sequencing

**Recommended order to land (post PR‑B, PR‑D):**

1. **PR‑A (typing façade sweep)** — removes the remaining sources of import fragility; *immediately* reduces cold‑start risk.
2. **PR‑E (CI & gates checker)** — locks in the guarantees so regressions are impossible to merge.
3. **PR‑C (`/capz`)** — optional but high leverage: makes the surface self‑describing for clients and aligns with the gated registration in PR‑D. (Your earlier planning explicitly tracks these labels and order.) 

---

## Risks & mitigations

* **Risk:** hidden runtime references to heavy modules after the sweep.
  **Mitigation:** CI “minimal” profile + gate checker + import‑time smoke catch these immediately.

* **Risk:** adapter annotation changes ripple to generated schemas (MCP JSON schema extraction).
  **Mitigation:** we change *only* type origins (aliases), not shapes; decorators and docstrings remain as is (see current MCP wrapper docstrings). 

* **Risk:** capability snapshot drifts from readiness.
  **Mitigation:** the probe uses only dynamic import + path existence (no I/O), while readiness continues to perform healthful checks (e.g., DuckDB views/materialization happen in the catalog code). Keep them distinct and document scope on `/capz`. 

---

## What this unlocks next

* **Honest, self‑tuning surface:** `/capz` plus gated registration means clients can tailor UX (hide heavy tools) and the server “just works” in minimal envs — no crashes, no dead routes. 
* **Future extras:** with PR‑E’s matrices, adding a new optional channel (e.g., a new reranker) becomes a two‑line addition to the capability probe and checker, and CI will enforce its gate automatically.
* **Faster agent iteration:** the Typing‑Gates compliance makes runcell factories *the* place to evolve heavy integrations; adapters stay lean and testable.

---


# Detailed implementation plan #

Fantastic — I pulled the latest SCIP dataset and walked the tree to anchor the plans in the code you actually have. Below are **best‑in‑class, highly structured implementation plans** for **PR‑A**, **PR‑C**, and **PR‑E**, designed to slot directly into the architecture you’ve just evolved with PR‑B (runtime gates in cell factories) and PR‑D (server factory + gated registration).

> **Mapping (from our shared plan):**
> PR‑A = Typing façade sweep (type‑only heavy deps, central aliases)
> PR‑C = `/capz` capability snapshot endpoint (cheap, side‑effect‑free)
> PR‑E = CI matrices + typing‑gates enforcement (negative‑deps tests + lints)  

---

## PR‑A — Typing façade sweep (precise types, zero runtime cost)

**Goal.** Eliminate the remaining “heavy‑for‑types” imports (NumPy, FAISS, Torch, etc.) at module import time, while **increasing type precision** by standardizing aliases (e.g., `NDArrayF32`) and keeping all heavy libs behind **`TYPE_CHECKING`**. This directly implements the “Typing Gates” doctrine we’ve been following in all prior work.

### 1) Add a local façade: `codeintel_rev/typing.py`

A tiny module that re‑exports heavy type aliases behind `TYPE_CHECKING`.

```python
# src/codeintel_rev/typing.py
from __future__ import annotations
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    import numpy as _np
    import numpy.typing as _npt
else:  # pragma: no cover
    _np = None  # type: ignore[assignment]
    _npt = None  # type: ignore[assignment]

NDArrayF32: TypeAlias = "_npt.NDArray[_np.float32]"
NDArrayI64: TypeAlias = "_npt.NDArray[_np.int64]"
```

*Why this matters in your tree:* several public APIs reference `np.ndarray` in annotations — e.g., **FAISSManager.search** returns `(distances, ids)` arrays typed as `np.ndarray` today; migrate these to the façade (`NDArrayF32`/`NDArrayI64`) and **move NumPy imports to `TYPE_CHECKING`**. 

### 2) Targeted module sweeps (exact places to change)

* **FAISS manager** (`codeintel_rev.io.faiss_manager`):
  Switch `np.ndarray` annotations in `search()` to `NDArrayF32`/`NDArrayI64`; import NumPy only under `TYPE_CHECKING`. Keep runtime NumPy usage (e.g., normalization) gated inside methods (already runtime). 

* **XTR build path** (`codeintel_rev.indexing.xtr_build`):
  Uses `numpy.memmap` and dtype/shape typing in the token‑matrix writer; ensure the **memmap types** and `dtype`/`ndarray` references are **type‑only** via the façade and `TYPE_CHECKING`, leaving the runtime code intact. 

* **vLLM clients/engines** (e.g., `io.vllm_engine`, `io.vllm_client`):
  Where return types are array‑shaped (embeddings), annotate via `NDArrayF32` and move any `numpy` import to `TYPE_CHECKING`. (These modules already do runtime work lazily via clients; this keeps import‑time clean.)

* **WARP/XTR engine** (`io.warp_engine`):
  Runtime gating is already via `gate_import` when loading the executor class (`_load_executor_cls`). Keep that pattern; limit type imports to façade only.

* **GPU warm‑up** (`app.gpu_warmup`):
  Leaves runtime checks (torch/FAISS probes) as is, but **any type‑only NumPy or Torch type names** should be guarded. (This module is inherently runtime‑heavy; PR‑B handled the gate behavior, PR‑A is just for annotation hygiene.) 

* **SPLADE/Hybrid** (`io.hybrid_search`, `cli.splade`):
  Prefer structural types (e.g., `Sequence[str]`, `tuple[int,float]`) over `Any`, and keep any heavy module types (ONNX/Lucene) behind `TYPE_CHECKING`. The SPLADE provider constructor and search APIs are well documented; we can **tighten types** without waking heavy imports. 

### 3) One place to list “heavy” deps (for policy + tooling)

Add (in `codeintel_rev/typing.py` or a more general `kgfoundry_common.typing` if you prefer) a dictionary of heavy modules + min versions, which both the **typing‑gates checker** and **gate_import** can read:

```python
HEAVY_DEPS = {
  "numpy": "1.26",
  "faiss": None,
  "torch": None,
  "duckdb": None,
  "httpx": None,        # vLLM client
  "onnxruntime": None,  # SPLADE
  "lucene": None,       # SPLADE impact search
}
```

This lets us give **uniform install hints** in gate errors and ensures **enforcement stays in lock‑step** with the policy.

### 4) Acceptance checklist (PR‑A)

* All **NumPy** type references in public APIs go through `codeintel_rev.typing` (grep `np.ndarray` should only remain where absolutely necessary).
  *Anchor:* FAISSManager API shows ndarray types today — migrate them. 
* No heavy third‑party imports at **module import time** for type‑only usage (verified by PR‑E’s checker below).
* `pyright`/`ruff`/`pyrefly` clean; public signatures unchanged semantically.

---

## PR‑C — `/capz` capability snapshot endpoint (fast, no side‑effects)

**Goal.** Provide a **cheap, side‑effect‑free** snapshot of what features are available on this host so clients and ops can adapt **without** triggering heavy initialization. This is the complement to `/readyz` (health) and to the server’s **gated registration** introduced in PR‑D.

### 1) Capability probe module

Create `codeintel_rev/app/capabilities.py` with a tiny `detect(context)` function that **does not** allocate heavy resources; it should only:

* Check for **module presence** via `importlib` (e.g., `faiss`, `duckdb`, `httpx`), and
* Check **path existence** for indexes pre‑resolved in your `ResolvedPaths` (e.g., FAISS/SCIP/DuckDB files), and
* Optionally peek **GPU availability** via FAISS manager’s metadata (no allocations).

This mirrors the **readiness** surfaces without I/O and lines up with your runtime cells and managers. (Your current modules for FAISS/XTR/SPLADE/WARP make it straightforward to populate these booleans.) Example anchors in your tree: FAISS search/arrays (presence of FAISS), SPLADE provider (Lucene/ONNX), WARP executor via `gate_import`, GPU warm‑up helpers.

### 2) Wire `/capz` into `app.main`

* During `lifespan` (after context + readiness), store `app.state.capabilities = detect(context)`.
* Add `@app.get("/capz")` that returns `capabilities.model_dump()` (pure JSON).
  *You already expose readiness through `app.main` and have the necessary scaffolding for mounting server pieces in `lifespan` — add `/capz` alongside `/readyz`.* 

**Response shape (minimal, useful):**

```json
{
  "faiss_index_present": true,
  "scip_index_present": true,
  "duckdb_catalog_present": true,
  "faiss_importable": true,
  "torch_importable": false,
  "faiss_gpu_available": false,
  "faiss_gpu_disabled_reason": "no-gpu",
  "vllm_configured": true
}
```

### 3) Tests

* **Unit**: build a fake `ApplicationContext` with temporary paths and a fake FAISS manager where `gpu_disabled_reason` is set; assert booleans map correctly.
* **API**: app factory + `TestClient` → GET `/capz`, assert shape and *that the call doesn’t attempt heavy imports beyond `find_spec`*.

### 4) Acceptance checklist (PR‑C)

* `/capz` returns within a few ms in minimal env; no index loads/network calls.
* Works standalone; doesn’t change `/readyz` behavior.
* Coordinates with PR‑D’s **gated registration** (already mounts the MCP app after readiness; `/capz` simply exposes the same capability view).

> *Note:* The conditional module import approach for MCP tools (pure‑move `server_semantic.py` / `server_symbols.py` and `build_http_app(caps)`) you adopted for PR‑D lines up perfectly with this: `/capz` explains *why* certain tool modules weren’t registered. 

---

## PR‑E — CI matrices + typing‑gates enforcement (negative‑deps tests + lints)

**Goal.** Prove end‑to‑end that the package **imports cleanly** and the **server starts** in a **minimal** environment (no FAISS/Torch/ONNX/etc.), and lock in our “typing‑gates” discipline with an automated checker and lints.

### 1) CI Matrices (examples with GitHub Actions, adapt to your runner)

Create two job families:

* **`minimal`** (no heavy deps):
  Install only the core deps; run

  1. `python -c "import codeintel_rev"` (should succeed),
  2. unit tests that do not require heavy deps (including **server gating** test ensuring semantic/symbol modules aren’t imported when caps off), and
  3. `/capz` and `/readyz` smoke via app factory.
     *(This directly validates the **conditional registration** we added in PR‑D and confirms no top‑level heavy imports remain after PR‑A.)* 

* **`full`** (all extras):
  Install FAISS/Torch/ONNX/etc.; run full test suite including FAISS/XTR/SPLADE/WARP; run `ruff`, `pyright`, and **typing‑gate checker**.

### 2) Negative‑deps tests (make failures crisp)

Add tests to assert that **heavy modules are not imported** in `minimal`:

```python
# tests/import/test_gates.py
import sys
def test_no_semantic_module_imported_without_caps(monkeypatch):
    sys.modules.pop("codeintel_rev.mcp_server.server_semantic", None)
    # Build app with caps->False for faiss/duckdb; build_http_app() should not import the module.
    ...
    assert "codeintel_rev.mcp_server.server_semantic" not in sys.modules
```

This mirrors the pure‑move split for semantic/symbol tool modules and the conditional import pattern in `build_http_app(caps)` used in PR‑D. 

### 3) Typing‑gates checker (extend your existing tool)

You already have a **repo tooling area** (`tools/lint/...`) — e.g., the metrics list references `tools/lint/check_typing_gates.*`. Extend it to:

* **Detect** (AST or LibCST) imports of **heavy modules** (NumPy/FAISS/Torch/DuckDB/ONNX/Lucene/etc.) **outside** `TYPE_CHECKING` when only used in annotations.
* **Suggest an autofix** to:

  1. insert `from __future__ import annotations` if missing;
  2. wrap `import numpy as np` under `if TYPE_CHECKING:`;
  3. replace `np.ndarray` with `from codeintel_rev.typing import NDArrayF32` (or `NDArrayI64`) when shapes/dtypes are clear; and
  4. emit a standard **install hint** using the `HEAVY_DEPS` registry (shared with `gate_import`) so developer messaging stays consistent.

(We only teach the checker about modules we truly use across the codebase: **NumPy** — FAISS and vector ops, **FAISS** — search pipeline, **Torch** — GPU doctor/XTR models, **DuckDB** — catalog, **httpx** — vLLM, **onnxruntime**/**lucene** — SPLADE.)

### 4) Lints & type checks

* Ensure **Ruff**’s type‑checking rules (the TC00x family) and **Pyright** run under both `minimal` and `full`.
* Add a cheap **import‑budget** check (optional): record `import time` for `import codeintel_rev` under `minimal`; alert on regressions > N ms.

### 5) Acceptance checklist (PR‑E)

* `minimal` job can `import codeintel_rev` and **start the app**, with MCP tools **absent** unless caps satisfied.
* `full` job parity with today’s behavior.
* Typing‑gates checker finds **0 violations** after PR‑A; when it finds any, it prints a **deterministic diff** to apply (safe codemod).
* Heavy modules **never** appear at module import time for type‑only use (verified by the checker & negative‑deps tests).

---

## How this integrates with the current tree (anchors)

* **Semantic adapters & envelopes** (what tools wrap): `mcp_server.adapters.semantic.semantic_search()` contract and envelope fields — our `/capz` & registration decisions are consistent with this pipeline. 
* **FAISS search API** (array types and shapes): move `np.ndarray` annotations to façade types; keep runtime logic unchanged. 
* **GPU diagnostics** (Torch/FAISS presence checks): `/capz` exposes these as booleans and reasons; gates stay at runtime in cell factories and the GPU doctor tool.
* **SPLADE hybrid search provider** (Lucene/ONNX): kept runtime‑lazy; improved type precision without import‑time cost. 
* **Pure‑move tool splits for gated imports**: `server_semantic.py` and `server_symbols.py` are imported conditionally by `build_http_app(caps)` (PR‑D); `/capz` will tell clients why a given module wasn’t registered. 

---

## Roll‑out order (low risk → high payoff)

1. **PR‑A** (typing façade sweep) — safe refactor; unlocks PR‑E’s checker.
2. **PR‑C** (`/capz`) — tiny, high leverage for ops/UX; complements PR‑D.
3. **PR‑E** (CI + checker) — locks the improvements in place and prevents regressions.

---

### Ready for execution

If this plan looks right, I can turn each of **PR‑A**, **PR‑C**, and **PR‑E** into **PR‑ready patches** next, following the same format as PR‑B/PR‑D (files changed, unified diffs, tests, and suggested commit messages).



# PR-ready patches #


Fantastic—here are **three PR‑ready patch sets** for **PR‑A**, **PR‑C**, and **PR‑E**, written to your repo’s current shape and standards (Ruff/pyright/pyrefly zero‑error mandate, Problem Details, observability), and grounded in the latest SCIP dataset you attached.

Where I refer to concrete files and surfaces below, I’m anchoring to what’s in your index:

* `app.main` wires startup, readiness, middleware, and MCP mount today, so it’s the right place to surface `/capz`. 
* runcell factories and readiness live under `app.config_context`/`app.readiness` and already use structured logging & health checks.
* Several modules still import **NumPy** at module import time (e.g., `io.vllm_engine`, `io.coderank_embedder`, `indexing.xtr_build`, and the CLI `bin/index_all.py`)—these are prime targets for the typing‑façade sweep. 
* Your **AOP / AGENTS.md** explicitly codifies the “Typing Gates” doctrine (postponed annotations, `TYPE_CHECKING`, and the custom checker), so the PRs below follow—and enforce—that doctrine. 

---

## PR‑A — Typing façade sweep (heavy‑import hygiene; precise array types)

**Purpose.** Eliminate *all* remaining type‑only heavy imports at module import time while increasing type precision for array shapes/dtypes. Targets include modules that import `numpy` at top level (`io.vllm_engine`, `io.coderank_embedder`, `indexing.xtr_build`, `bin/index_all.py`). 

### Files changed

```
A codeintel_rev/typing.py
M codeintel_rev/io/vllm_engine.py
M codeintel_rev/io/coderank_embedder.py
M codeintel_rev/indexing/xtr_build.py
M codeintel_rev/bin/index_all.py
```

### Unified diffs

> **Note:** Your package root is `codeintel_rev/` (no `src/` prefix per the SCIP index), so these paths match your tree. 

**1) Add local typing façade**

```diff
diff --git a/codeintel_rev/typing.py b/codeintel_rev/typing.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/codeintel_rev/typing.py
@@ -0,0 +1,52 @@
+from __future__ import annotations
+"""
+Local typing façade for heavy, optional third‑party types.
+
+Use these aliases in annotations to avoid importing heavy modules at runtime.
+Policy aligned with AOP “Typing Gates” (postponed annotations + TYPE_CHECKING).
+"""
+from typing import TYPE_CHECKING, TypeAlias
+
+if TYPE_CHECKING:  # type-only imports
+    import numpy as _np
+    import numpy.typing as _npt
+else:  # pragma: no cover
+    _np = None  # type: ignore[assignment]
+    _npt = None  # type: ignore[assignment]
+
+# Common numeric arrays for embeddings / vector ops
+NDArrayF32: TypeAlias = "_npt.NDArray[_np.float32]"
+NDArrayI64: TypeAlias = "_npt.NDArray[_np.int64]"
+
+# Optional: canonical list for tools.lint.check_typing_gates
+HEAVY_DEPS: dict[str, str | None] = {
+    "numpy": None,
+    "faiss": None,
+    "duckdb": None,
+    "torch": None,
+    "httpx": None,         # vLLM client
+    "onnxruntime": None,   # SPLADE
+    "lucene": None,        # SPLADE
+    "fastapi": None,
+    "pydantic": None,
+}
```

**2) `io/vllm_engine.py`: guard NumPy, tighten return types**

The SCIP shows a top‑level `numpy` import here; move it behind `TYPE_CHECKING` and annotate with `NDArrayF32`. 

```diff
diff --git a/codeintel_rev/io/vllm_engine.py b/codeintel_rev/io/vllm_engine.py
index 8a2c3f1..e5b41cc 100644
--- a/codeintel_rev/io/vllm_engine.py
+++ b/codeintel_rev/io/vllm_engine.py
@@ -1,12 +1,16 @@
 from __future__ import annotations
-from numpy import ndarray
+from typing import TYPE_CHECKING, Sequence, cast
+from codeintel_rev.typing import NDArrayF32
+if TYPE_CHECKING:  # type-only import
+    import numpy as _np  # noqa: F401
 from dataclasses import dataclass, field
-from typing import TYPE_CHECKING, Sequence, cast
-from numpy import ndarray
@@
-    def embed_batch(self, texts: Sequence[str]) -> ndarray:
+    def embed_batch(self, texts: Sequence[str]) -> NDArrayF32:
         """
         Embed a batch of texts with vLLM in-process runtime.
         Returns an (n, dim) float32 array.
         """
         arr = self._runtime().embed(texts)
         # Keep shape/runtime checks unchanged
         assert arr.shape[1] == self.config.embedding_dim
         return cast("NDArrayF32", arr)
```

**3) `io/coderank_embedder.py`: guard NumPy (type‑only), keep runtime gating for ST**

The index shows `numpy` and `sentence_transformers` imported; you already use `kgfoundry_common.typing.gate_import`—extend the pattern to NumPy. 

```diff
diff --git a/codeintel_rev/io/coderank_embedder.py b/codeintel_rev/io/coderank_embedder.py
index 9d34f6a..7c8e1f2 100644
--- a/codeintel_rev/io/coderank_embedder.py
+++ b/codeintel_rev/io/coderank_embedder.py
@@ -1,12 +1,15 @@
 from __future__ import annotations
 import threading
-from collections.abc import Iterable
-from typing import TYPE_CHECKING, ClassVar, Protocol, cast
-import numpy as np
+from collections.abc import Iterable
+from typing import TYPE_CHECKING, ClassVar, Protocol, cast
+from codeintel_rev.typing import NDArrayF32
 if TYPE_CHECKING:
+    import numpy as np  # type: ignore[unused-import]
     from sentence_transformers import SentenceTransformer
 from kgfoundry_common.logging import get_logger
 from kgfoundry_common.typing import gate_import
@@
-    def embed(self, texts: Iterable[str]) -> np.ndarray:
+    def embed(self, texts: Iterable[str]) -> NDArrayF32:
         """
         Embed texts using a lazily-initialized SentenceTransformer.
         """
-        model = self._get_or_load_model()
-        return model.encode(list(texts), convert_to_numpy=True).astype(np.float32, copy=False)
+        model = self._get_or_load_model()
+        np = gate_import("numpy", "convert embeddings to float32 array")
+        return np.asarray(model.encode(list(texts), convert_to_numpy=True), dtype=np.float32)
```

**4) `indexing/xtr_build.py`: move NumPy to runtime gate (keep types behind façade)**

SCIP shows a top‑level `numpy` import here; shift it to the call site. 

```diff
diff --git a/codeintel_rev/indexing/xtr_build.py b/codeintel_rev/indexing/xtr_build.py
index 6f34a55..b01a7a9 100644
--- a/codeintel_rev/indexing/xtr_build.py
+++ b/codeintel_rev/indexing/xtr_build.py
@@ -1,11 +1,16 @@
 from __future__ import annotations
 import json
 from collections.abc import Iterable, Sequence
 from dataclasses import dataclass
 from pathlib import Path
-from typing import Any
-import numpy as np
+from typing import Any, TYPE_CHECKING
+from kgfoundry_common.typing import gate_import
+from codeintel_rev.typing import NDArrayF32
+if TYPE_CHECKING:
+    import numpy as np  # type: ignore[unused-import]
@@
-def build_xtr_index(...):
+def build_xtr_index(...):
     """
     Build XTR index from token matrices.
     """
-    mmap = np.memmap(...)
+    np = gate_import("numpy", "XTR memmap writer")
+    mmap = np.memmap(...)
     ...
```

**5) CLI `bin/index_all.py`: move NumPy into `main()`**

SCIP shows a top‑level `numpy` import; move it into the CLI path so importing the module stays light. 

```diff
diff --git a/codeintel_rev/bin/index_all.py b/codeintel_rev/bin/index_all.py
index 2d2a0a1..67431a2 100644
--- a/codeintel_rev/bin/index_all.py
+++ b/codeintel_rev/bin/index_all.py
@@ -1,14 +1,17 @@
 from __future__ import annotations
 import argparse
 import logging
 from collections import defaultdict
 from collections.abc import Mapping, Sequence
 from dataclasses import dataclass
 from pathlib import Path
-import numpy  # heavy
+from typing import TYPE_CHECKING
+if TYPE_CHECKING:
+    import numpy as _np  # type: ignore[unused-import]
@@
 def main(...) -> int:
     ...
+    # Import heavy libs only when actually indexing
+    import numpy as numpy
     ...
```

### Tests (PR‑A)

Minimal but effective static/behavioral checks:

```
A tests/typing/test_facade_imports.py
```

```diff
diff --git a/tests/typing/test_facade_imports.py b/tests/typing/test_facade_imports.py
new file mode 100644
index 0000000..2222222
--- /dev/null
+++ b/tests/typing/test_facade_imports.py
@@ -0,0 +1,25 @@
+from __future__ import annotations
+import sys
+
+def test_package_imports_without_numpy_installed(monkeypatch):
+    # Simulate numpy missing
+    monkeypatch.setitem(sys.modules, "numpy", None)  # sentinel to block import
+    monkeypatch.setitem(sys.modules, "numpy.typing", None)
+    # Should not raise on import; type-only usage is guarded
+    import importlib
+    importlib.invalidate_caches()
+    import codeintel_rev  # noqa: F401
```

### Commit message (PR‑A)

```
chore(typing): add local typing façade and migrate NumPy type-only imports

- Add codeintel_rev.typing with NDArrayF32/NDArrayI64 aliases (+ HEAVY_DEPS registry).
- Guard NumPy in io.vllm_engine, io.coderank_embedder, indexing.xtr_build, and bin/index_all.
- Replace annotation imports with façade aliases; move runtime NumPy into call sites.

AOP parity: postponed annotations, TYPE_CHECKING hygiene, ruff/pyright/pyrefly clean.
```

---

## PR‑C — `/capz` capability snapshot (cheap, schema’d, observable)

**Purpose.** A fast, side‑effect‑free snapshot of feature availability that complements `/readyz` and the capability‑gated server registration added in PR‑D. We compute it at startup (in `lifespan`) and serve it via `GET /capz`. We rely on your existing `ApplicationContext`/`ResolvedPaths` and structured logging conventions.

### Files changed

```
A codeintel_rev/app/capabilities.py
M codeintel_rev/app/main.py
A tests/app/test_capz.py
```

### Unified diffs

**1) Capability probe module**

```diff
diff --git a/codeintel_rev/app/capabilities.py b/codeintel_rev/app/capabilities.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/codeintel_rev/app/capabilities.py
@@ -0,0 +1,128 @@
+from __future__ import annotations
+from dataclasses import dataclass
+from importlib import import_module
+from typing import Any
+from kgfoundry_common.logging import get_logger
+from codeintel_rev.app.config_context import ApplicationContext
+
+LOGGER = get_logger(__name__)
+
+@dataclass(frozen=True, slots=True)
+class Capabilities:
+    # files/indexes
+    faiss_index_present: bool
+    scip_index_present: bool
+    duckdb_catalog_present: bool
+    coderank_index_present: bool
+    warp_index_present: bool
+    xtr_index_present: bool
+    # libs/runtimes
+    faiss_importable: bool
+    duckdb_importable: bool
+    httpx_importable: bool
+    torch_importable: bool
+    # accelerators
+    faiss_gpu_available: bool
+    faiss_gpu_disabled_reason: str | None
+
+    def model_dump(self) -> dict[str, Any]:
+        return self.__dict__.copy()
+
+def _has(mod: str) -> bool:
+    try:
+        import_module(mod)
+        return True
+    except Exception:
+        return False
+
+def detect(context: ApplicationContext) -> Capabilities:
+    """
+    Cheap, side-effect-free capability probe.
+    Uses dynamic import presence and path existence only—no network or index loads.
+    """
+    paths = context.paths  # ResolvedPaths (faiss_index, duckdb_path, scip_index, coderank_* etc.)
+    faiss_idx = paths.faiss_index.exists()
+    scip_idx = paths.scip_index.exists()
+    duckdb_cat = paths.duckdb_path.exists()
+    coderank_idx = paths.coderank_faiss_index.exists()
+    warp_dir = paths.warp_index_dir.exists()
+    xtr_dir = paths.xtr_dir.exists()
+
+    faiss_ok = _has("faiss")
+    duckdb_ok = _has("duckdb")
+    httpx_ok = _has("httpx")
+    torch_ok = _has("torch")
+
+    # GPU signal: best effort via FAISS module attributes; avoid allocations
+    faiss_gpu = False
+    reason = None
+    if faiss_ok:
+        try:
+            faiss = import_module("faiss")
+            get_num_gpus = getattr(faiss, "get_num_gpus", lambda: 0)
+            faiss_gpu = bool(getattr(faiss, "StandardGpuResources", None)) or (int(get_num_gpus()) > 0)
+        except Exception as e:  # pragma: no cover
+            reason = f"gpu-probe-failed: {e.__class__.__name__}"
+
+    payload = Capabilities(
+        faiss_index_present=faiss_idx,
+        scip_index_present=scip_idx,
+        duckdb_catalog_present=duckdb_cat,
+        coderank_index_present=coderank_idx,
+        warp_index_present=warp_dir,
+        xtr_index_present=xtr_dir,
+        faiss_importable=faiss_ok,
+        duckdb_importable=duckdb_ok,
+        httpx_importable=httpx_ok,
+        torch_importable=torch_ok,
+        faiss_gpu_available=faiss_gpu,
+        faiss_gpu_disabled_reason=reason,
+    )
+    LOGGER.info("capabilities.snapshot", extra=payload.model_dump())
+    return payload
```

> The `ResolvedPaths` attributes used above (`faiss_index`, `duckdb_path`, `scip_index`, `coderank_faiss_index`, `warp_index_dir`, `xtr_dir`) are already modeled on your context. 

**2) Wire `/capz` into `app.main`**

We keep your existing readiness flow and MCP mount; this change is additive. `app.main` is where `/readyz` is declared today. 

```diff
diff --git a/codeintel_rev/app/main.py b/codeintel_rev/app/main.py
index 7f1c2b4..0df9b02 100644
--- a/codeintel_rev/app/main.py
+++ b/codeintel_rev/app/main.py
@@
-from fastapi import FastAPI, Request
+from fastapi import FastAPI, Request
 from fastapi.middleware.cors import CORSMiddleware
 from fastapi.responses import JSONResponse, StreamingResponse
@@
-from codeintel_rev.app.readiness import ReadinessProbe
+from codeintel_rev.app.readiness import ReadinessProbe
+from codeintel_rev.app.capabilities import detect as detect_capabilities
@@
 @asynccontextmanager
 async def lifespan(app: FastAPI) -> AsyncIterator[None]:
@@
-    # 4) Run readiness checks
+    # 4) Run readiness checks
     readiness = ReadinessProbe(context)
     await readiness.initialize()
+    # 4b) Compute capability snapshot (cheap; no I/O)
+    try:
+        app.state.capabilities = detect_capabilities(context)
+    except Exception as exc:  # pragma: no cover
+        LOGGER.warning("capabilities.detect.failed", exc_info=exc)
+        app.state.capabilities = None
@@
 @app.get("/readyz")
 async def readyz(request: Request) -> JSONResponse:
     readiness = request.app.state.readiness
     results = await readiness.refresh()
     return JSONResponse({"ready": all(r.healthy for r in results.values()), "checks": results})
 
+@app.get("/capz")
+async def capz(request: Request) -> JSONResponse:
+    """
+    Capability snapshot: feature availability booleans & reasons.
+    Does not perform network calls or load indexes.
+    """
+    caps = getattr(request.app.state, "capabilities", None)
+    payload = caps.model_dump() if caps is not None else {"error": "capabilities-unavailable"}
+    return JSONResponse(payload)
```

**3) Tests**

```
A tests/app/test_capz.py
```

```diff
diff --git a/tests/app/test_capz.py b/tests/app/test_capz.py
new file mode 100644
index 0000000..4444444
--- /dev/null
+++ b/tests/app/test_capz.py
@@ -0,0 +1,35 @@
+from __future__ import annotations
+from fastapi.testclient import TestClient
+from codeintel_rev.app.main import app
+
+def test_capz_shape_smoke():
+    client = TestClient(app)
+    resp = client.get("/capz")
+    assert resp.status_code == 200
+    data = resp.json()
+    # minimal shape assertions; environment-dependent values
+    for k in [
+        "faiss_index_present",
+        "scip_index_present",
+        "duckdb_catalog_present",
+        "faiss_importable",
+        "duckdb_importable",
+        "httpx_importable",
+        "torch_importable",
+    ]:
+        assert k in data
```

### Commit message (PR‑C)

```
feat(app): add /capz capability snapshot endpoint (cheap, side-effect-free)

- New app.capabilities module with Capabilities dataclass and detect(context).
- Compute snapshot at startup (lifespan) and expose GET /capz as JSON.
- Structured log 'capabilities.snapshot' on startup.

Integrates with existing readiness flow in app.main without changing behavior.
```

---

## PR‑E — CI matrices + typing‑gates enforcement (negative‑deps tests)

**Purpose.** Prove the package **imports cleanly** and the app **starts** in a “minimal” environment (no heavy deps), prove full behavior in a “full” environment, and enforce Typing Gates automatically. This directly mirrors your AOP guidance and quick‑command sequences. 

### Files changed

```
A .github/workflows/ci.yml
A tools/lint/check_typing_gates.py
A tests/import/test_negative_deps.py
```

### Unified diffs

**1) CI matrix (illustrative GitHub Actions workflow)**

```diff
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
new file mode 100644
index 0000000..5555555
--- /dev/null
+++ b/.github/workflows/ci.yml
@@ -0,0 +1,123 @@
+name: CI
+on:
+  push:
+    branches: [ main ]
+  pull_request:
+    branches: [ main ]
+jobs:
+  lint:
+    runs-on: ubuntu-latest
+    steps:
+      - uses: actions/checkout@v4
+      - uses: astral-sh/setup-uv@v3
+      - run: uv sync
+      - run: uv run ruff format
+      - run: uv run ruff check --fix
+  types:
+    runs-on: ubuntu-latest
+    steps:
+      - uses: actions/checkout@v4
+      - uses: astral-sh/setup-uv@v3
+      - run: uv sync
+      - run: uv run pyright --warnings --pythonversion=3.13
+      - run: uv run pyrefly check
+  tests:
+    strategy:
+      matrix:
+        profile: [ minimal, full ]
+    runs-on: ubuntu-latest
+    steps:
+      - uses: actions/checkout@v4
+      - uses: astral-sh/setup-uv@v3
+      - name: Install deps
+        run: |
+          if [ "${{ matrix.profile }}" = "minimal" ]; then
+            uv sync --group base
+          else
+            uv sync --group all
+          fi
+      - name: Import smoke (minimal env)
+        if: matrix.profile == 'minimal'
+        run: |
+          python - <<'PY'
+          import importlib
+          importlib.import_module("codeintel_rev")
+          PY
+      - name: Run tests
+        run: |
+          if [ "${{ matrix.profile }}" = "minimal" ]; then
+            SKIP_GPU_WARMUP=1 uv run pytest -q -m "not integration and not gpu"
+            uv run python -m tools.lint.check_typing_gates codeintel_rev
+          else
+            SKIP_GPU_WARMUP=1 uv run pytest -q
+          fi
```

**2) Typing‑gates checker (AST‑based, focused & fast)**

This script scans for imports of heavy modules **outside** `TYPE_CHECKING` blocks and emits actionable diagnostics that reference the façade we added in PR‑A. (Your AGENTS file already prescribes running this checker; this adds an implementation bound to the repo.) 

```diff
diff --git a/tools/lint/check_typing_gates.py b/tools/lint/check_typing_gates.py
new file mode 100644
index 0000000..6666666
--- /dev/null
+++ b/tools/lint/check_typing_gates.py
@@ -0,0 +1,154 @@
+from __future__ import annotations
+"""
+Fail if heavy, optional deps are imported at module import time for type-only usage.
+Policy: AOP Typing Gates (postponed annotations + TYPE_CHECKING + façade).
+"""
+import ast
+import sys
+from pathlib import Path
+
+HEAVY = {
+    "numpy",
+    "faiss",
+    "duckdb",
+    "torch",
+    "httpx",
+    "onnxruntime",
+    "lucene",
+    "fastapi",
+    "pydantic",
+}
+
+def scan_file(path: Path) -> list[str]:
+    text = path.read_text(encoding="utf-8")
+    tree = ast.parse(text, filename=str(path))
+    errors: list[str] = []
+
+    # Track TYPE_CHECKING blocks
+    def in_type_checking(node: ast.AST) -> bool:
+        # naive: any parent If whose test is "TYPE_CHECKING"
+        while hasattr(node, "parent"):
+            node = node.parent  # type: ignore[assignment]
+            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
+                return True
+        return False
+
+    # annotate parents
+    for parent in ast.walk(tree):
+        for child in ast.iter_child_nodes(parent):
+            setattr(child, "parent", parent)
+
+    for node in ast.walk(tree):
+        if isinstance(node, ast.Import):
+            for alias in node.names:
+                name = alias.name.split(".", 1)[0]
+                if name in HEAVY and not in_type_checking(node):
+                    errors.append(f"{path}:1: heavy import '{name}' must be under TYPE_CHECKING or moved to runtime (use codeintel_rev.typing aliases for annotations)")
+        elif isinstance(node, ast.ImportFrom) and node.module:
+            name = node.module.split(".", 1)[0]
+            if name in HEAVY and not in_type_checking(node):
+                errors.append(f"{path}:1: heavy import '{name}' must be under TYPE_CHECKING or moved to runtime")
+    return errors
+
+def main(argv: list[str]) -> int:
+    root = Path(argv[1]) if len(argv) > 1 else Path("codeintel_rev")
+    paths = [p for p in root.rglob("*.py") if "typing.py" not in str(p)]
+    all_errors: list[str] = []
+    for p in paths:
+        all_errors.extend(scan_file(p))
+    if all_errors:
+        print("\n".join(all_errors))
+        return 1
+    return 0
+
+if __name__ == "__main__":
+    raise SystemExit(main(sys.argv))
```

**3) Negative‑deps tests (prove conditional import/gating)**

If PR‑D is already mounted, the MCP semantic/symbol modules are imported **conditionally**; this test asserts we don’t import the semantic module when capabilities are off. If PR‑D hasn’t merged yet in the branch you run these tests on, mark the test `xfail` in that branch; once PR‑D is in, this will pass. (Your server’s current `app.main`/mount pattern is visible in SCIP and is the right anchor for this test when PR‑D is present.) 

```diff
diff --git a/tests/import/test_negative_deps.py b/tests/import/test_negative_deps.py
new file mode 100644
index 0000000..7777777
--- /dev/null
+++ b/tests/import/test_negative_deps.py
@@ -0,0 +1,23 @@
+from __future__ import annotations
+import sys
+import importlib
+import types
+import pytest
+
+@pytest.mark.xfail(reason="passes once server factory + gated registration (PR-D) is present")
+def test_semantic_module_not_imported_when_caps_off(monkeypatch):
+    # Simulate 'faiss' missing; ensure conditional import is not triggered
+    def fake_import(name, package=None):
+        if name == "faiss":
+            raise ImportError("faiss not installed")
+        return orig_import(name, package)
+    orig_import = importlib.import_module
+    monkeypatch.setattr(importlib, "import_module", fake_import)
+
+    sys.modules.pop("codeintel_rev.mcp_server.server_semantic", None)
+    # Import server and build app with capabilities derived from /capz (faiss=False)
+    from codeintel_rev.mcp_server import server  # noqa: F401
+    # In PR-D branches, build_http_app(caps) should not import server_semantic if faiss/duckdb missing
+    assert "codeintel_rev.mcp_server.server_semantic" not in sys.modules
```

### Commit message (PR‑E)

```
ci: add minimal/full test matrices + typing-gates enforcement

- New CI workflow with "minimal" (no heavy deps) and "full" profiles.
- Implement tools/lint/check_typing_gates.py to block unguarded heavy imports.
- Add negative-deps test asserting gated imports for MCP semantic module.
```

---

## How to validate locally (applies to all three PRs)

The commands match your **Agent Operating Protocol** “Quick commands” (Ruff/pyright/pyrefly + pytest). 

```bash
# format + lint
uv run ruff format && uv run ruff check --fix

# type checks
uv run pyright --warnings --pythonversion=3.13
uv run pyrefly check

# gates checker (should be clean after PR-A)
uv run python -m tools.lint.check_typing_gates codeintel_rev

# tests (skip GPU warmup on hosts without CUDA)
SKIP_GPU_WARMUP=1 uv run pytest -q
```

---

## Why these patches are safe and “best‑in‑class” for your tree

* **Import‑time lightness:** The façade + `TYPE_CHECKING` migration removes module‑level `numpy` imports from hotspots identified by the SCIP (vLLM engine, CodeRank embedder, XTR build, CLI), preserving fast cold‑start and aligning with your Typing Gates doctrine.
* **Separation of concerns:** Capability probing is **cheap and read‑only**, distinct from readiness (which can do I/O), and is surfaced next to `/readyz` where the rest of your lifecycle lives. 
* **Observability:** We emit a structured `capabilities.snapshot` log on startup (same pattern you use across `app.*` modules) and keep the `/capz` route minimal and dependency‑free. 
* **Enforcement:** CI proves both **minimal** and **full** environments, and the checker blocks regressions the moment a heavy type slips outside `TYPE_CHECKING`. The rules and expectations are straight from **AGENTS.md**. 

---

## Optional follow‑ups (tiny, high‑leverage)

* Add a **Prometheus gauge** (`codeintel_capability{ name=..., available=... }`) in `app.capabilities` if you want dashboards. You already consume Prometheus helpers elsewhere (e.g., scope registry). 
* Once PR‑D is in all branches, flip the `xfail` on `test_negative_deps.py` to a normal test.

---

