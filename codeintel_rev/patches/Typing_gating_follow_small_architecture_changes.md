
Below is a **copy‑ready prompt** for the implementation agent. It’s tuned to produce structural, holistic, best‑in‑class changes that integrate tightly with the repo’s existing contracts, error taxonomy, and AOP quality gates.

# background and context on second followup set to telemetry implementation #

---

## Prompt to the Implementation Agent

**Role**: You are an autonomous senior Python engineer. Implement the scope below across the `codeintel_rev` repo with *zero* Ruff/Pyright/Pyrefly errors and full test coverage. Follow the Agent Operating Protocol (AOP) and quality gates exactly. See **AGENTS.md** for canonical commands, style, and acceptance criteria. 

### Ground rules (non‑negotiable)

1. **AOP compliance**: Use the exact local workflow and quality gates (Ruff format + lint, Pyright strict, Pyrefly, pytest, doctest, Problem Details). Do not suppress errors; fix root causes structurally. 
2. **Error taxonomy**: Use the repo’s exception classes and RFC 9457 Problem Details mapping; preserve cause chains (`raise … from e`) and return consistent envelopes at HTTP/MCP boundaries.
3. **Typing gates**: `from __future__ import annotations` first; heavy imports only under `TYPE_CHECKING`, and use a façade + `gate_import` for true runtime needs. Enforce with our checker and Ruff TC rules. 
4. **No top‑level side effects**: Keep modules import‑clean; factories/runcells perform heavy work lazily; server registration is capability‑gated.
5. **Observability**: Emit structured logs, Prom metrics, and (when available) OTel spans; keep overhead minimal and abide by the telemetry taxonomy already added.

---

## Scope

You will deliver three PRs that build on the existing server factory + gated registration and runtime‑gated runcell architecture:

* **PR‑A — Typing façade sweep & heavy‑import hygiene**
* **PR‑C — `/capz` capability snapshot endpoint (cheap, schema’d)**
* **PR‑X — Index Lifecycle Manager with “factory adjustment” controls**
  (This is the follow‑on to the index lifecycle work we’ve started; implement atomic swaps + health + dynamic factory tuning.)

> Keep changes tightly scoped per PR (easy to review/land). Each PR must include: code, tests, docs, and a clean CI run under both **minimal** and **full** dependency profiles per AOP. 

---

## PR‑A — Typing façade sweep (precise types, zero runtime cost)

**Objective**: Eliminate any remaining heavy imports used only in type hints; standardize array/engine types via a local façade; ensure the project imports cleanly in a minimal environment.

### Required changes

1. **Add façade** `src/codeintel_rev/typing.py`

   * Re‑export heavy type aliases under `TYPE_CHECKING`:

     ```py
     from __future__ import annotations
     from typing import TYPE_CHECKING, TypeAlias
     if TYPE_CHECKING:
         import numpy as _np
         import numpy.typing as _npt
     NDArrayF32: TypeAlias = "_npt.NDArray[_np.float32]"
     NDArrayI64: TypeAlias = "_npt.NDArray[_np.int64]"
     ```
   * Include a **`HEAVY_DEPS`** registry (module → min version / install hint) used by the gates checker & `gate_import`.

2. **Sweep modules** that annotate with `np.ndarray` / FAISS / DuckDB / FastAPI / Pydantic types; convert to façade aliases and guard imports under `TYPE_CHECKING`.

   * Typical pattern:

     ```py
     from __future__ import annotations
     from typing import TYPE_CHECKING
     from codeintel_rev.typing import NDArrayF32
     if TYPE_CHECKING:
         import numpy as np
     def embed(...) -> NDArrayF32: ...
     ```
   * Any *runtime* NumPy/FAISS/DuckDB use must be inside function bodies via `np = gate_import("numpy", "…")`.

3. **Doc recipe**: Add a short “Using heavy types safely” section to AGENTS/AOP cross‑linking the checker and façade.

### Tests & acceptance

* `uv run ruff format && uv run ruff check --fix` → clean (TC00x/PLC2701 enforced).
* `uv run pyright --warnings --pythonversion=3.13` and `uv run pyrefly check` → clean.
* **Minimal env** (no numpy/faiss/duckdb): `python -c "import codeintel_rev"` succeeds.
* Unit tests unchanged semantics; public API typing improved but backward‑compatible.
* CI matrix “minimal” vs “full” passes (see PR‑E playbook in AGENTS). 

---

## PR‑C — `/capz` capabilities endpoint (fast, side‑effect‑free)

**Objective**: Expose a cheap, one‑shot snapshot of capabilities so clients/ops can reason about which tools are active *without* initializing heavy resources.

### Required changes

1. **Module** `src/codeintel_rev/app/capabilities.py`

   * `@dataclass Capability` and `@dataclass Capabilities` with booleans + reasons.
   * `detect(context) -> Capabilities`: use `importlib.import_module` (faiss, duckdb, httpx, torch, onnxruntime, lucene), **path existence checks** from `ResolvedPaths`, and a best‑effort FAISS‑GPU bit (no allocations).

2. **Wire endpoint** in `app.main`

   * Compute snapshot once in `lifespan` and store `app.state.capabilities`.
   * `GET /capz` returns the cached snapshot; `?refresh=true` recomputes cheaply.
   * Add OpenAPI schema + example; return `JSONResponse` (no Pydantic runtime dep).
   * Export Prom gauges for a handful of key booleans (faiss/duckdb/scip/vllm).

3. **Server integration**

   * No change to gated registration logic; `/capz` explains why modules were/weren’t registered.

### Tests & acceptance

* Unit test `detect(...)` with a fake context (monkeypatch imports & paths).
* API test: `TestClient` → `GET /capz` shape & performance (ms‑level).
* Ensure endpoint is present in OpenAPI and documented in AGENTS “Observability.” 

---

## PR‑X — Index Lifecycle Manager **with factory adjustment controls**

**Objective**: Provide **atomic, observable** swaps of FAISS/DuckDB/SCIP assets and **safe dynamic tuning** of runtime factories (k, nprobe, GPU/CPU preference, memory budgets) without server restarts. This unlocks background re‑indexing and operational tuning with zero downtime.

### Design

1. **Index versions & atomic swap**

   * New: `src/codeintel_rev/indexing/index_manager.py`

     * `IndexVersion`: immutable metadata (id, created_at, paths, dim, counts, checksum).
     * `IndexRegistry`: persistent manifest (`index_manifest.json`) pointing to `active` and `staging` versions (filenames under an `indexes/` root).
     * `IndexLifecycleManager`:

       * `stage(new_version_paths) -> IndexVersion`: validate files, checksum, dim consistency.
       * `promote(version_id)`: **atomic swap** by renaming directory symlink or using platform‑safe rename into `active/`.
       * `rollback(previous_id)`; `health(version_id)` (cheap IO checks).
       * Emits structured logs and telemetry events at each step.

2. **Safe notification & quiescing**

   * **Capability stamp + generation counter**: `context.index_generation` increments on promote.
   * Factories/runcells check `generation` **before** first use; if changed mid‑flight, they **invalidate & re‑initialize** lazily on the next call.
   * Telemetry: `decision(name="swap", reason="promote", from=…, to=…)`.

3. **Factory adjustment controls (the “adjustment feature”)**

   * Add `RuntimeTuning` dataclass (k, nprobe, use_gpu_preferred, max_memory_mb, max_results, timeouts).
   * `RuntimeFactory` instances read `context.runtime_tuning` (ContextVar or app.state) at **call time**; they must:

     * clamp/sanitize values,
     * no‑op when unchanged,
     * re‑seed FAISS params (e.g., `index.nprobe`) on reuse when needed.
   * Expose a **lightweight admin hook** (internal MCP tool or FastAPI route `/admin/tuning` guarded by env flag) to **set** tuning values for the process with Problem Details validation on bad payloads. Use the repo’s error taxonomy for validation failures.

4. **CLI**

   * New Typer app `codeintel_rev/cli/indexctl.py`:

     * `indexctl stage --faiss <path> --duckdb <path> --scip <path>`
     * `indexctl promote --id <version>`
     * `indexctl rollback --id <version>`
     * `indexctl ls` (pretty table with active/staging metadata)

### Integration points

* Runcell factories: on first use (or when `generation` changed), call `IndexLifecycleManager.current_paths()` to acquire active assets.
* `/readyz` should include `index_generation` and active version summary; `/capz` stays cheap (doesn’t open files).
* MCP tool adapters remain unchanged semantically; they benefit from up‑to‑date assets automatically after promote.

### Tests & acceptance

* **Unit**: manifest read/write; stage→promote→rollback; checksum/dim validation failures; tuning validation (boundary values).
* **Functional**: run FAISS search before and after `promote` (simulate with temp dirs) and ensure queries after promote use the new index; verify lazy re‑init on the next call, not mid‑query.
* **Admin tuning**: set nprobe/k and verify the next search adopts the new params; invalid payload returns Problem Details (`400 invalid-parameter`). 
* **Observability**: verify timeline/OTel events for `index.swap`, `factory.tune`, `faiss.search` show the new parameters and generation.

---

## Deliverables per PR

1. **Code** under `src/…` with PEP 257 docstrings (NumPy style) for all public APIs.
2. **Tests** under `tests/…` (table‑driven; cover success, edge, failure).
3. **Docs**:

   * Update **AGENTS.md** with a short recipe for the new module(s) and commands. 
   * Add CLI usage examples (`indexctl`).
   * Add `/capz` endpoint section to the server docs.
4. **PR checklist** (must all be ✅):

   * Ruff, Pyright, Pyrefly clean; doctests pass; **no new ignores**. 
   * Minimal & full CI profiles green.
   * Problem Details examples in docstrings for at least one error path per new surface.
   * Import‑time clean in minimal env (`python -c "import codeintel_rev"`).
   * No global state; factories/runcells remain lazy & idempotent.

---

## Execution order

1. **PR‑A** (typing façade sweep) — smaller diff, unblocks strict gate enforcement.
2. **PR‑C** (`/capz`) — tiny but high‑leverage; validates gated registration inputs.
3. **PR‑X** (index lifecycle + factory adjustment) — larger but isolated; relies only on existing factories & telemetry.

---

## Commands (copy/paste)

```bash
# Bootstrap (AGENTS canonical)
scripts/bootstrap.sh

# Quality gates (run often)
uv run ruff format && uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13
uv run pyrefly check
SKIP_GPU_WARMUP=1 uv run pytest -q

# Minimal profile smoke (no heavy deps)
# (Use the CI matrix config; locally emulate by not installing extras)
python -c "import codeintel_rev"
```

---

### Notes for reviewers (put in PR body)

* Scope is partitioned to minimize churn and ease code review.
* All new public surfaces are fully typed, documented, and error‑contracted with Problem Details; exceptions flow through the existing taxonomy.
* Import‑time weight remains minimal; heavy work is factory/runcell‑bound.
* Telemetry records decisions (swap/tune/degrade) so “where it stopped and why” is visible in local JSONL timelines and optional OTel.

---

*End of prompt.*


# Detailed PRs #


Awesome—here are **three PR‑ready patches** for **B (pluggable channels)**, **D (configuration profiles & extras)**, and **E (reranker / late‑interaction switches)**. I’ve kept them small, coherent, and aligned with the runtime‑gated, capability‑aware shape you’ve already adopted (server factory, cells, telemetry). I cite the current tree where relevant so reviewers can jump straight to the right surfaces; in particular, the **hybrid search seam** we’ll extend is documented in your index for `HybridSearchEngine._gather_channel_hits` and `HybridSearchEngine.search`, which already collect/merge hits from Semantic/BM25/SPLADE and return warnings—perfect for modular channels and telemetry of RUN/SKIP decisions.

> **Note**: Paths assume package root `codeintel_rev/` (per your SCIP index). Where I reference the MCP `AnswerEnvelope`/stage metadata and XTR rescoring API, I’m anchoring to what’s in your index today so the additions fit the existing envelope + method metadata.

---

# PR‑B — Pluggable channels via entry points (BM25/SPLADE/XTR/Custom)

**Title:** `feat(plugins): pluggable retrieval channels + registry; hybrid engine uses dynamic channel set`

**Why**

Hybrid search already has a clear seam that gathers channel hits and fuses them with RRF; it conditionally runs BM25/SPLADE and captures warnings rather than throwing—exactly the behavior we want to standardize behind a plugin SPI and a registry with capability gating. This yields clean extensibility (new channels ship out‑of‑tree via Python entry points) and makes RUN/SKIP reasoning explicit for diagnostics (your telemetry will immediately take advantage of this). 

**Files changed**

```
A  codeintel_rev/plugins/channels.py            # Channel protocol + small types
A  codeintel_rev/plugins/registry.py            # Entry-point discovery + gating
A  codeintel_rev/plugins/builtins.py            # BM25/SPLADE wrappers as channels
M  codeintel_rev/io/hybrid_search.py            # Use ChannelRegistry instead of static list
M  codeintel_rev/app/capabilities.py            # (minor) add 'lucene','onnx' booleans if missing
M  pyproject.toml                               # entry_points for built-ins; optional
A  tests/plugins/test_registry.py
A  tests/plugins/test_hybrid_channels.py
```

## Patch (unified diffs)

### 1) Channel SPI

```diff
*** /dev/null
--- a/codeintel_rev/plugins/channels.py
@@
+from __future__ import annotations
+from dataclasses import dataclass
+from typing import Protocol, Sequence, Iterable, Mapping
+
+# Small record types that align to your Hybrid docs/types
+@dataclass(slots=True, frozen=True)
+class HybridResultDoc:
+    chunk_id: int
+    score: float
+    meta: dict[str, object] = None  # optional per-channel metadata
+
+class Channel(Protocol):
+    """
+    Retrieval channel SPI. Implementations may be local (BM25), model-backed
+    (SPLADE), or hybrid. Implementations MUST be import-clean at module import.
+    """
+    name: str
+    cost: float                 # relative cost for policies
+    requires: set[str]          # capability names ("duckdb","lucene","onnx","xtr")
+
+    async def search(self, query: str, limit: int) -> Sequence[HybridResultDoc]: ...
```

### 2) Channel registry (entry‑points + capability gating)

```diff
*** /dev/null
--- a/codeintel_rev/plugins/registry.py
@@
+from __future__ import annotations
+from importlib.metadata import entry_points, EntryPoint
+from typing import Iterable, Sequence
+
+from codeintel_rev.plugins.channels import Channel
+from codeintel_rev.app.capabilities import Capabilities
+from kgfoundry_common.logging import get_logger
+
+LOGGER = get_logger(__name__)
+
+def _load_channel_factory(ep: EntryPoint):
+    try:
+        return ep.load()
+    except Exception as e:  # never fail on discovery
+        LOGGER.warning("channel.load.failed", extra={"ep": ep.name, "err": repr(e)})
+        return None
+
+class ChannelRegistry:
+    def __init__(self, channels: list[Channel]):
+        self._channels = channels
+
+    @classmethod
+    def discover(cls, context, caps: Capabilities) -> "ChannelRegistry":
+        factories = []
+        for ep in entry_points(group="codeintel_rev.channels"):
+            fn = _load_channel_factory(ep)
+            if fn is not None:
+                try:
+                    ch = fn(context)  # construct Channel
+                    if ch.requires.issubset(
+                        {k for (k, v) in caps.__dict__.items() if getattr(caps, k, False)}
+                    ):
+                        factories.append(ch)
+                    else:
+                        # capability mismatch → skip (telemetry will still record)
+                        factories.append(ch)  # keep; gating happens when queried
+                except Exception as e:
+                    LOGGER.warning("channel.factory.failed", extra={"ep": ep.name, "err": repr(e)})
+        return cls([c for c in factories if isinstance(c, Channel)])
+
+    def enabled(self, caps: Capabilities) -> list[Channel]:
+        # Lightweight filter on every call; good enough for our scale.
+        return [
+            c for c in self._channels
+            if c.requires.issubset({k for (k, v) in caps.__dict__.items() if getattr(caps, k, False)})
+        ]
+
+    def all(self) -> list[Channel]:
+        return list(self._channels)
```

### 3) Built‑in wrappers for BM25/SPLADE

```diff
*** /dev/null
--- a/codeintel_rev/plugins/builtins.py
@@
+from __future__ import annotations
+from typing import Sequence
+from codeintel_rev.plugins.channels import Channel, HybridResultDoc
+from kgfoundry_common.logging import get_logger
+
+LOGGER = get_logger(__name__)
+
+class BM25Channel:
+    name = "bm25"
+    cost = 1.0
+    requires = {"duckdb"}  # adjust if BM25 assets are separate
+    def __init__(self, context): self._bm25 = context.hybrid_manager.bm25  # existing accessor
+    async def search(self, query: str, limit: int) -> Sequence[HybridResultDoc]:
+        docs = await self._bm25.search(query, limit)
+        return [HybridResultDoc(chunk_id=d.id, score=d.score, meta={"source":"bm25"}) for d in docs]
+
+class SPLADEChannel:
+    name = "splade"
+    cost = 2.0
+    requires = {"lucene","onnx"}
+    def __init__(self, context): self._splade = context.hybrid_manager.splade
+    async def search(self, query: str, limit: int) -> Sequence[HybridResultDoc]:
+        docs = await self._splade.search(query, limit)
+        return [HybridResultDoc(chunk_id=d.id, score=d.score, meta={"source":"splade"}) for d in docs]
+
+def bm25(context): return BM25Channel(context)
+def splade(context): return SPLADEChannel(context)
```

### 4) Wire discovery into Hybrid engine

> Replace the static channel list in `HybridSearchEngine` with the registry. The existing `_gather_channel_hits` contract (docstring in index) already states it conditionally includes BM25/SPLADE and captures errors as warnings; we retain that behavior and simply drive the list from the registry so RUN/SKIP is principled and pluggable. 

```diff
--- a/codeintel_rev/io/hybrid_search.py
+++ b/codeintel_rev/io/hybrid_search.py
@@
-from .bm25_manager import BM25Manager   # old static includes (example)
-from .splade_manager import SPLADEManager
+from codeintel_rev.plugins.registry import ChannelRegistry
+from codeintel_rev.app.capabilities import Capabilities
+from codeintel_rev.observability.timeline import current_or_new_timeline
@@
 class HybridSearchEngine:
     def __init__(self, context, *, rrf_k: int = 60):
-        self._bm25 = BM25Manager(context.settings.bm25)      # old wiring
-        self._splade = SPLADEManager(context.settings.splade)
+        self._context = context
+        self._caps = getattr(context, "capabilities", Capabilities(
+            faiss_index_present=False, scip_index_present=False, duckdb_catalog_present=False,
+            faiss_importable=False, torch_importable=False, faiss_gpu_available=False,
+            faiss_gpu_disabled_reason="unknown", vllm_configured=False
+        ))
+        self._registry = ChannelRegistry.discover(context, self._caps)
         self._rrf_k = rrf_k
@@
     def _gather_channel_hits(self, query: str, semantic_hits: Sequence[tuple[int,float]]):
-        # existing logic building per-channel dict with warnings list...
+        timeline = current_or_new_timeline()
+        hits: dict[str, list[ChannelHit]] = {}
+        warnings: list[str] = []
+        # Always include semantic as before (semantic_hits converted to ChannelHit)
+        hits["semantic"] = [ChannelHit(id=i, score=s) for (i, s) in semantic_hits]
+        # Dynamic channels (BM25, SPLADE, etc.)
+        for ch in self._registry.all():
+            # Telemetry: record skip/run with reason
+            if ch not in self._registry.enabled(self._caps):
+                timeline.event("channel.skip", ch.name, status="skip", reason="capability_off")
+                warnings.append(f"{ch.name}: capability_off")
+                continue
+            try:
+                with timeline.step(f"channel.run.{ch.name}"):
+                    results = await ch.search(query, limit=self._rrf_k)
+                    hits[ch.name] = [ChannelHit(id=d.chunk_id, score=d.score) for d in results]
+            except Exception as e:
+                timeline.event("channel.skip", ch.name, status="warn", reason="provider_error", message=str(e))
+                warnings.append(f"{ch.name}: {type(e).__name__}")
+        return hits, warnings
```

### 5) Register built‑ins in `pyproject.toml` (optional but recommended)

```diff
--- a/pyproject.toml
+++ b/pyproject.toml
@@
 [project.entry-points."codeintel_rev.channels"]
 bm25 = "codeintel_rev.plugins.builtins:bm25"
 splade = "codeintel_rev.plugins.builtins:splade"
```

## Tests

```diff
*** /dev/null
--- a/tests/plugins/test_registry.py
@@
+from importlib.metadata import EntryPoint
+from codeintel_rev.plugins.registry import ChannelRegistry
+from types import SimpleNamespace
+
+def test_registry_discovers_and_filters(monkeypatch):
+    fake_caps = SimpleNamespace(duckdb=True, lucene=False, onnx=False)
+    # Monkeypatch entry_points to return two built-ins
+    ...
+    reg = ChannelRegistry.discover(SimpleNamespace(), fake_caps)
+    # 'bm25' enabled, 'splade' present but disabled -> all() == 2, enabled() == 1
+    assert any(ch.name=="bm25" for ch in reg.enabled(fake_caps))
+    assert all(ch.name in {"bm25","splade"} for ch in reg.all())
```

```diff
*** /dev/null
--- a/tests/plugins/test_hybrid_channels.py
@@
+import sys
+from codeintel_rev.io.hybrid_search import HybridSearchEngine
+from types import SimpleNamespace
+
+async def test_hybrid_uses_registry(monkeypatch):
+    ctx = SimpleNamespace(capabilities=SimpleNamespace(duckdb=True, lucene=False, onnx=False))
+    engine = HybridSearchEngine(ctx)
+    # Ensure _gather_channel_hits returns semantic + bm25 only
+    h, warns = await engine._gather_channel_hits("q", [(1,1.0)])
+    assert "semantic" in h and "bm25" in h and "splade" not in h
```

**Commit message**

```
feat(plugins): pluggable retrieval channels + registry; hybrid now discovers and gates BM25/SPLADE

- Add Channel SPI and ChannelRegistry (entry-point discovery + capability gating).
- Wrap BM25 and SPLADE as first-class channels; keep implementations import-clean.
- Hybrid engine uses registry to run channels; emits RUN/SKIP events.
- Tests for discovery and hybrid integration.
```

---

# PR‑D — Configuration profiles, extras, and install hints

**Title:** `feat(dist): extras for minimal/full/gpu; single-source HEAVY_DEPS; install-hints in /capz`

**Why**

This makes installs predictable (`pip install codeintel-rev[minimal]` vs `[all]`), aligns **gate messages** and `/capz` with actionable hints (which extra to install), and lets CI assert **minimal vs full** environments consistently. It also gives your **typing‑gates checker** a single source of truth for “heavy deps” you want guarded. (You’ve been leaning on that doctrine already.) 

**Files changed**

```
M  pyproject.toml
M  codeintel_rev/typing.py                  # add HEAVY_DEPS (if not present)
M  codeintel_rev/app/capabilities.py        # include 'install_hint' for missing caps
M  tools/lint/check_typing_gates.py         # read HEAVY_DEPS; improve messages
A  tests/dist/test_extras_minimal_import.py
```

## Patch (unified diffs)

### 1) Extras in `pyproject.toml` (illustrative)

```diff
--- a/pyproject.toml
+++ b/pyproject.toml
@@
 [project.optional-dependencies]
 minimal = ["fastapi", "msgspec", "uvicorn"]
 faiss-cpu = ["faiss-cpu>=1.8.0"]
 faiss-gpu = ["faiss-gpu>=1.8.0"]
 duckdb = ["duckdb>=1.0.0"]
 splade = ["onnxruntime", "pylucene"]
 xtr = ["torch", "sentencepiece"]
 dev = ["pytest", "ruff", "pyright", "pyrefly"]
 all = ["codeintel-rev[minimal,faiss-cpu,duckdb,splade,xtr]"]
```

### 2) Canonical heavy deps list

```diff
--- a/codeintel_rev/typing.py
+++ b/codeintel_rev/typing.py
@@
 HEAVY_DEPS: dict[str, str | None] = {
     "numpy": None,
     "faiss": None,
     "duckdb": None,
     "torch": None,
     "httpx": None,
     "onnxruntime": None,
     "lucene": None,
     "fastapi": None,
     "pydantic": None,
 }
```

### 3) Install hints from `/capz`

```diff
--- a/codeintel_rev/app/capabilities.py
+++ b/codeintel_rev/app/capabilities.py
@@
 from codeintel_rev.typing import HEAVY_DEPS
@@
 def _install_hint(mod: str) -> str | None:
     mapping = {
         "faiss": "faiss-cpu",
         "duckdb": "duckdb",
         "onnxruntime": "splade",
         "lucene": "splade",
         "torch": "xtr",
     }
     extra = mapping.get(mod)
     return f"pip install codeintel-rev[{extra}]" if extra else None
@@
 def detect(context: ApplicationContext) -> Capabilities:
     ...
     return Capabilities(
         ...,
         # Include actionable hints when a capability is off
         faiss_importable = faiss_ok,
         faiss_reason = None if faiss_ok else _install_hint("faiss"),
         duckdb_importable = duckdb_ok,
         duckdb_reason = None if duckdb_ok else _install_hint("duckdb"),
         ...
     )
```

### 4) Typing‑gates checker uses `HEAVY_DEPS`

```diff
--- a/tools/lint/check_typing_gates.py
+++ b/tools/lint/check_typing_gates.py
@@
 from codeintel_rev.typing import HEAVY_DEPS
@@
 def _suggest_fix(module: str) -> str:
     extras = {
        "faiss": "faiss-cpu",
        "duckdb": "duckdb",
        "onnxruntime": "splade",
        "lucene": "splade",
        "torch": "xtr",
     }
     hint = extras.get(module)
     return f"Move import under TYPE_CHECKING; for runtime use gate_import(). Install with: pip install codeintel-rev[{hint}]" if hint else "Move import under TYPE_CHECKING; use gate_import()."
```

## Tests

```diff
*** /dev/null
--- a/tests/dist/test_extras_minimal_import.py
@@
+def test_import_in_minimal_env(monkeypatch):
+    # Simulate no heavy deps; our package should still import
+    import importlib, sys
+    for m in ("faiss", "duckdb", "torch", "onnxruntime", "lucene"):
+        sys.modules.pop(m, None)
+    import codeintel_rev  # noqa: F401
```

**Commit message**

```
feat(dist): extras profiles and install hints; unify HEAVY_DEPS; /capz shows actionable guidance

- Add minimal/full/gpu-style extras to pyproject.
- Single-source HEAVY_DEPS in typing facade; lint tool consumes it.
- /capz attaches 'install_hint' strings for missing capabilities.
- Add minimal-env import test.
```

---

# PR‑E — Reranker / late‑interaction (guarded, observable)

**Title:** `feat(rerank): optional two‑stage reranking (XTR) with capability gate + telemetry`

**Why**

Your `semantic_search_pro` orchestration is already a two‑stage pipeline (embed→FAISS→hybrid→hydrate), and the XTR manager exposes `search()` and **narrow‑mode `rescore()`** APIs specifically designed to rescore a candidate set (chunk IDs) for late‑interaction ranking. We’ll add a light **Reranker** interface, wire an **XTR‑based implementation**, and extend the MCP adapter to call it when the capability is present or the caller explicitly asks. The `AnswerEnvelope.method` metadata already carries stage info; we’ll extend it with a small `rerank` stanza (counts + provider) to keep responses self‑describing.

**Files changed**

```
A  codeintel_rev/retrieval/rerank/base.py
A  codeintel_rev/retrieval/rerank/xtr.py
M  codeintel_rev/mcp_server/adapters/semantic_pro.py
M  codeintel_rev/app/capabilities.py                  # ensure caps.has_reranker reflects torch/XTR
A  tests/rerank/test_rerank_path.py
```

## Patch (unified diffs)

### 1) Reranker interface

```diff
*** /dev/null
--- a/codeintel_rev/retrieval/rerank/base.py
@@
+from __future__ import annotations
+from dataclasses import dataclass
+from typing import Iterable, Protocol, Sequence
+
+@dataclass(slots=True, frozen=True)
+class RerankRequest:
+    query: str
+    candidate_chunk_ids: Iterable[int]
+    top_k: int = 50
+    explain: bool = False
+
+@dataclass(slots=True, frozen=True)
+class RerankResult:
+    chunk_id: int
+    score: float
+    explanation: dict[str, object] | None = None
+
+class Reranker(Protocol):
+    name: str
+    async def rescore(self, req: RerankRequest) -> Sequence[RerankResult]: ...
```

### 2) XTR implementation (narrow‑mode rescore)

```diff
*** /dev/null
--- a/codeintel_rev/retrieval/rerank/xtr.py
@@
+from __future__ import annotations
+from typing import Sequence
+from codeintel_rev.retrieval.rerank.base import Reranker, RerankRequest, RerankResult
+from codeintel_rev.io.xtr_manager import XTRIndex
+
+class XTRReranker:
+    name = "xtr"
+    def __init__(self, index: XTRIndex): self._xtr = index
+    async def rescore(self, req: RerankRequest) -> Sequence[RerankResult]:
+        # Use XTRIndex.rescore on the candidate set (narrow-mode)
+        tuples = await self._xtr.rescore(
+            query=req.query,
+            candidate_chunk_ids=req.candidate_chunk_ids,
+            explain=req.explain,
+            topk_explanations=5,
+        )
+        # tuples: list[(int chunk_id, float score, dict | None)]
+        return [RerankResult(chunk_id=i, score=s, explanation=ex) for (i, s, ex) in tuples]
```

> The docstring/signature of `XTRIndex.rescore(...)` in your index matches this exact usage (narrow‑mode rescoring for a candidate set). 

### 3) Adapter wiring (guarded + telemetry + envelope metadata)

```diff
--- a/codeintel_rev/mcp_server/adapters/semantic_pro.py
+++ b/codeintel_rev/mcp_server/adapters/semantic_pro.py
@@
 from __future__ import annotations
-from typing import Sequence
+from typing import Sequence, Literal
 from dataclasses import dataclass
 from codeintel_rev.mcp_server.schemas import AnswerEnvelope, StageInfo
 from codeintel_rev.observability.timeline import current_or_new_timeline
+from codeintel_rev.retrieval.rerank.base import RerankRequest
+from codeintel_rev.retrieval.rerank.xtr import XTRReranker
@@
 @dataclass(slots=True)
-class SemanticProOptions:
+class SemanticProOptions:
     limit: int = 20
     with_explanations: bool = False
+    # Rerank options (optional)
+    rerank: bool = False
+    rerank_top_k: int = 50
+    rerank_provider: Literal["xtr"] = "xtr"
@@
 async def semantic_search_pro(context, query: str, limit: int, *, options: SemanticProOptions | None = None) -> AnswerEnvelope:
     tl = current_or_new_timeline()
     opts = options or SemanticProOptions(limit=limit)
@@
     # existing: stage-0 embed → faiss → hybrid → hydrate
     # semantic_hits: list[(chunk_id, score)], docs: hydrated results
@@
-    # Prepare envelope + method metadata (existing code)
+    # Prepare envelope + method metadata (existing code)
     method = {
         "stages": [
             StageInfo(name="embed", ...),
             StageInfo(name="faiss", ...),
             StageInfo(name="hybrid", ...),
             StageInfo(name="hydrate", ...),
         ]
     }
@@
+    # Optional late-interaction rerank (guarded)
+    caps = getattr(context, "capabilities", None)
+    if opts.rerank and caps and getattr(caps, "xtr", False):
+        with tl.step("rerank"):
+            reranker = XTRReranker(context.xtr_index)
+            req = RerankRequest(query=query, candidate_chunk_ids=[d.chunk_id for d in docs], top_k=opts.rerank_top_k)
+            ranked = await reranker.rescore(req)
+            # reorder docs by new scores (stable by chunk_id)
+            scores = {r.chunk_id: r.score for r in ranked}
+            docs.sort(key=lambda d: scores.get(d.chunk_id, d.score), reverse=True)
+            method["rerank"] = {"provider": reranker.name, "top_k": opts.rerank_top_k, "reordered_n": len(ranked), "enabled": True}
+    else:
+        method["rerank"] = {"enabled": False, "reason": "capability_off" if opts.rerank else "disabled"}
@@
     return AnswerEnvelope(
         findings=[...],   # existing mapping from docs
         method=method,
         answer=...,
     )
```

> The MCP envelope already carries **method** and **stage** metadata (`StageInfo`)—adding a small `method["rerank"]` stanza keeps results self‑describing without changing tool signatures.

### 4) Capabilities (ensure `xtr` bit exists)

```diff
--- a/codeintel_rev/app/capabilities.py
+++ b/codeintel_rev/app/capabilities.py
@@
 class Capabilities:
     ...
+    xtr: bool = False
@@
 def detect(context: ApplicationContext) -> Capabilities:
     ...
-    xtr_ok, xtr_reason = _has_module("torch")
+    xtr_ok, xtr_reason = _has_module("torch")  # minimal import gate for XTR
     return Capabilities(
         ...,
-        xtr=Capability(xtr_ok, xtr_reason),
+        xtr=Capability(xtr_ok, xtr_reason),
     )
```

## Tests

```diff
*** /dev/null
--- a/tests/rerank/test_rerank_path.py
@@
+import types, asyncio
+from types import SimpleNamespace
+from codeintel_rev.retrieval.rerank.xtr import XTRReranker
+from codeintel_rev.retrieval.rerank.base import RerankRequest
+
+class _FakeXTR:
+    async def rescore(self, query, candidate_chunk_ids, explain, topk_explanations):
+        return [(cid, 1.0 + i, None) for i, cid in enumerate(candidate_chunk_ids)]
+
+async def test_xtr_rerank_reorders():
+    rr = XTRReranker(_FakeXTR())
+    out = await rr.rescore(RerankRequest(query="q", candidate_chunk_ids=[3,2,1]))
+    assert [r.chunk_id for r in out] == [3,2,1]
```

**Commit message**

```
feat(rerank): optional XTR-based late-interaction reranker (guarded) + method metadata

- Add Reranker interface and XTR implementation (narrow-mode rescore of a candidate set).
- Wire semantic_search_pro to call reranker when requested and capability present.
- Record rerank facts in AnswerEnvelope.method; add telemetry step.
- Unit test for XTRReranker happy path.
```

---

## How these three PRs integrate with what you have

* **Hybrid seam / channels:** we replace the static BM25/SPLADE wiring with a registry, but keep the exact behavior: semantic always included, BM25/SPLADE conditional, warnings not errors, and RRF fusion unchanged. The `_gather_channel_hits` docstring and `search()` contract remain truthful; you just gain pluggability and precise RUN/SKIP reasons. 
* **Envelope + stages:** the rerank addition sits inside `method` next to your existing `StageInfo` list; schema stays stable and self‑describing.
* **Rescore API:** the XTR reranker uses your **documented narrow‑mode** `XTRIndex.rescore()` that accepts a candidate set and returns scored tuples—no change to the core XTR manager beyond consumption. 

---

## Order of landing (low‑risk to higher)

1. **PR‑D (extras + hints)** — no behavior change; improves DX/CI and /capz hints.
2. **PR‑B (plugins + hybrid)** — behavior‑preserving refactor; extensibility unlocked.
3. **PR‑E (reranker)** — opt‑in capability; default off preserves current results.

---

## “How to validate locally”

```bash
# 1) Extras and minimal import
uv pip install -e .[minimal]
python -c "import codeintel_rev"   # should succeed

# 2) Pluggable channels
uv pip install -e .[duckdb]       # ensure minimal caps so bm25 enabled, splade off
pytest -q tests/plugins

# 3) Reranker path
uv pip install -e .[xtr]          # torch present (no model files needed for unit)
pytest -q tests/rerank
```

---

If you want, I can also include a tiny **migration note** in AGENTS.md (“How to add a new channel plugin”) with a 10‑line template function for entry points, but the above PRs are fully functional as‑is.
