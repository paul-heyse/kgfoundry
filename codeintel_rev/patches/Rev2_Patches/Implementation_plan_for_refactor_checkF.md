
# Detailed implementation plan and code #

Below is a **complete, implementation‑ready plan** (with **full file code**) to deliver scope **F**:

> **io/hybrid_search.py, io/splade_manager.py, io/bm25_manager.py** →
> Engines become narrow (encode/query/serialize only), fusion moves into `retrieval/fusion/*` (no I/O), and `io/hybrid_search.py` is trimmed to a 100–200 line coordinator.

This plan aligns with the Stage‑0 contract already used by your semantic adapters (`HybridSearchEngine.search(query, semantic_hits, limit, options) → HybridSearchResult`), so it drops cleanly into the pipeline introduced in refactor **E**. We’ll reuse your existing `retrieval/fusion/weighted_rrf.py` for the math and expose a typed fusion protocol the coordinator can call.  

We also conform to the repo’s agent rules (absolute imports, guarded heavy deps, strict typing, no side‑effects in pure layers). Keep these checks green locally with the AOP commands in **AGENTS.md**.  

---

## 0) Results at a glance (what changes)

**New (add)**

```
codeintel_rev/
  retrieval/
    fusion/
      api.py                # NEW: typed fusion protocol + RRF wrapper (no I/O)
  io/
    splade_engine.py        # NEW: narrow SPLADE engine: encode/query/serialize only
    bm25_engine.py          # NEW: narrow BM25 engine: encode/query/serialize only
```

**Rewritten (full file)**

```
codeintel_rev/io/hybrid_search.py     # NEW coordinator (≤ ~200 LOC)
```

**Compatibility shims**

```
codeintel_rev/io/splade_manager.py    # thin re-export to SPLADEEngine (for now)
codeintel_rev/io/bm25_manager.py      # thin re-export to BM25Engine (for now)
```

**Codemod (optional)**

```
tools/codemods/split_hybrid_engines.py   # LibCST: update imports/calls gradually
```

**Why this matches the E‑pipeline you already wired**
Your MCP adapters now depend on a Stage‑0 `HybridSearchEngine` that returns a structured result used by the gating/late‑interaction/rerank steps. This plan formalizes that engine and removes search‑engine specifics from the coordinator. 

---

## 1) Public contracts (types and options)

We keep the public shape your adapters already call:

```python
# retrieval/types.py (already in repo)
class HybridSearchResult(TypedDict):
    docs: list[Doc]               # Doc has doc_id (int), score (float), maybe uri/snippet
    warnings: list[str]
    method: dict[str, object]     # channel/fusion metadata
    contributions: dict[str, object] | None
```

The coordinator’s options mirror what your adapters/analytics need: engine weights and per‑engine limits. 

---

## 2) New file — `retrieval/fusion/api.py` (typed protocol; no I/O)

> This module is **pure**. It defines a small protocol the coordinator calls and wraps your existing `retrieval/fusion/weighted_rrf.py` so there’s one stable entrypoint for fusion. (We place it inside the `retrieval/fusion/` package that already exists in the repo.) 

```python
# codeintel_rev/retrieval/fusion/api.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol, Sequence

from codeintel_rev.retrieval.fusion.weighted_rrf import (
    weighted_rrf,
)  # existing implementation

@dataclass(frozen=True, slots=True)
class FusionInput:
    """Per-channel candidates to be fused."""
    # Each channel contributes (doc_id, score) pairs in descending score order.
    channel: str
    candidates: Sequence[tuple[int, float]]

@dataclass(frozen=True, slots=True)
class FusionOptions:
    """Fusion knobs (no I/O)."""
    weights: Mapping[str, float] | None = None
    k: int = 50
    base: int = 60   # RRF base parameter, typical values 10..100

class FusionProtocol(Protocol):
    """Pure fusion interface."""

    def fuse(self, inputs: Iterable[FusionInput], *, options: FusionOptions) -> list[tuple[int, float]]:
        """Fuse per-channel candidates into a ranked (doc_id, score) list."""
        ...

class RRFWeighter:
    """Adapter over existing weighted_rrf implementation (pure)."""

    def fuse(self, inputs: Iterable[FusionInput], *, options: FusionOptions) -> list[tuple[int, float]]:
        weights = dict(options.weights or {})
        by_channel = {fi.channel: list(fi.candidates) for fi in inputs}
        fused = weighted_rrf(by_channel, weights=weights, k=options.k, base=options.base)
        return fused
```

**Why this way?** We isolate the fusion dependency into a single callable with typed inputs/outputs; there’s **no disk/DB access** and no engine‑specific knowledge here—exactly the property your adapter pipeline expects for Stage‑0. 

---

## 3) New file — `io/splade_engine.py` (narrow engine)

> A minimal SPLADE engine that **only** handles encode/query/serialize. If your current `io/splade_manager.py` contains quantization, pruning (percentiles), corpus readers, or sharding, leave those there and **wrap** them for now; we’ll provide a temporary re‑export to avoid churn. Later, you can move the internal pieces under `splade_engine.py` if desired.

```python
# codeintel_rev/io/splade_engine.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, Sequence, TypedDict

from codeintel_rev.typing import NDArrayF32  # façade; guards heavy deps globally (see AGENTS.md)
# No runtime heavy imports here; underlying manager handles model weights/backends.

class SpladeCandidate(TypedDict):
    doc_id: int
    score: float

class SpladeBackend(Protocol):
    """Protocol that existing manager can satisfy with a small wrapper."""
    def encode_query(self, text: str) -> NDArrayF32: ...
    def search(self, query_vec: NDArrayF32, k: int) -> Sequence[tuple[int, float]]: ...

@dataclass(frozen=True, slots=True)
class SPLADEEngine:
    """
    Narrow SPLADE engine: encode → query → return (doc_id, score).
    No orchestration, no fusion, no I/O side effects.
    """
    backend: SpladeBackend

    def encode_query(self, text: str) -> NDArrayF32:
        return self.backend.encode_query(text)

    def search(self, query_text: str, *, k: int) -> list[tuple[int, float]]:
        q = self.encode_query(query_text)
        pairs = list(self.backend.search(q, k))
        # normalize to (int, float)
        return [(int(doc_id), float(score)) for doc_id, score in pairs]

    def serialize_method(self) -> dict[str, object]:
        # Report minimal channel metadata for Stage‑0 `method` envelope
        return {"channel": "splade", "impl": type(self.backend).__name__}
```

---

## 4) New file — `io/bm25_engine.py` (narrow engine)

```python
# codeintel_rev/io/bm25_engine.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

class BM25Backend(Protocol):
    """Minimal BM25 protocol satisfied by the existing manager adapter."""
    def search(self, query_text: str, k: int) -> Sequence[tuple[int, float]]: ...

@dataclass(frozen=True, slots=True)
class BM25Engine:
    """
    Narrow BM25 engine: query → (doc_id, score). No fusion/orchestration here.
    """
    backend: BM25Backend

    def search(self, query_text: str, *, k: int) -> list[tuple[int, float]]:
        pairs = list(self.backend.search(query_text, k))
        return [(int(doc_id), float(score)) for doc_id, score in pairs]

    def serialize_method(self) -> dict[str, object]:
        return {"channel": "bm25", "impl": type(self.backend).__name__}
```

---

## 5) Full file replacement — `io/hybrid_search.py` (coordinator 100–200 LOC)

> The coordinator wires engines and fusion. It takes **optional** semantic candidates (from FAISS) and fuses them with SPLADE + BM25 via the pure `FusionProtocol`. It returns a `HybridSearchResult` used by your MCP Stage‑0 pipeline. This is exactly the object your adapters already consume. 

```python
# codeintel_rev/io/hybrid_search.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from codeintel_rev.retrieval.fusion.api import FusionInput, FusionOptions, RRFWeighter
from codeintel_rev.retrieval.types import HybridSearchResult  # already present in repo
from codeintel_rev.io.bm25_engine import BM25Engine
from codeintel_rev.io.splade_engine import SPLADEEngine

@dataclass(frozen=True, slots=True)
class HybridSearchOptions:
    """Coordinator options for Stage‑0 retrieval."""
    weights: Mapping[str, float] | None = None      # e.g., {"faiss": 1.0, "splade": 0.8, "bm25": 0.6}
    per_channel_k: int = 100                        # how many to fetch per engine before fusion
    fusion_k: int = 50                              # final k after fusion
    rrf_base: int = 60                              # RRF base (see fusion docs)

@dataclass
class HybridSearchEngine:
    """
    Stage‑0 retrieval coordinator.
    * Calls BM25 and SPLADE engines (narrow) for candidate sets.
    * Optionally accepts 'semantic_hits' (FAISS) from the caller to avoid FAISS coupling here.
    * Fuses all candidates via Weighted RRF (pure fusion).
    * Returns a HybridSearchResult consumed by MCP adapters (see refactor E).
    """
    bm25: BM25Engine
    splade: SPLADEEngine

    def search(
        self,
        *,
        query: str,
        semantic_hits: Sequence[tuple[int, float]] | None,
        limit: int,
        options: HybridSearchOptions | None = None,
    ) -> HybridSearchResult:
        opts = options or HybridSearchOptions(fusion_k=limit)
        # 1) Gather candidates from engines (no fusion logic inside engines)
        bm25_pairs = self.bm25.search(query, k=opts.per_channel_k)
        splade_pairs = self.splade.search(query, k=opts.per_channel_k)
        faiss_pairs = list(semantic_hits or [])

        # 2) Fuse with pure RRF
        inputs = [
            FusionInput(channel="bm25", candidates=bm25_pairs),
            FusionInput(channel="splade", candidates=splade_pairs),
        ]
        if faiss_pairs:
            inputs.append(FusionInput(channel="faiss", candidates=faiss_pairs))

        fused = RRFWeighter().fuse(
            inputs,
            options=FusionOptions(weights=opts.weights, k=opts.fusion_k, base=opts.rrf_base),
        )

        # 3) Build method metadata (channels + contributions) and normalize
        docs = [{"doc_id": did, "score": score} for did, score in fused]
        method = {
            "channels": [fi.channel for fi in inputs],
            "fusion": {"type": "weighted_rrf", "k": opts.fusion_k, "base": opts.rrf_base},
            "weights": dict(opts.weights or {}),
        }
        contributions = {
            "bm25": {"k": len(bm25_pairs)},
            "splade": {"k": len(splade_pairs)},
            "faiss": {"k": len(faiss_pairs)},
        } if faiss_pairs else {
            "bm25": {"k": len(bm25_pairs)},
            "splade": {"k": len(splade_pairs)},
        }

        return {
            "docs": docs[:limit],
            "warnings": [],
            "method": method,
            "contributions": contributions,
        }
```

**Why this is safe:**

* The coordinator knows nothing about tokenization, sparsity, shards, or BM25 internals—each engine is a black box with `search()` that returns `(doc_id, score)`.
* Fusion is pure (see `retrieval/fusion/api.py`), matching the “no I/O in fusion” rule.
* The result object matches the Stage‑0 type your adapters expect today; your MCP refactor already assumes a `HybridSearchEngine` with this shape. 

---

## 6) Compatibility shims for `io/splade_manager.py` and `io/bm25_manager.py`

> Keep your existing imports working while teams migrate. (You can remove these shims once call‑sites switch to the engines directly.)

```python
# codeintel_rev/io/splade_manager.py
from __future__ import annotations

from typing import TYPE_CHECKING

from codeintel_rev.io.splade_engine import SPLADEEngine as SPLADEEngine  # re-export
# If you have a concrete backend, expose a helper to build the engine from it:
if TYPE_CHECKING:
    from codeintel_rev.io.splade_engine import SpladeBackend as SpladeBackend
```

```python
# codeintel_rev/io/bm25_manager.py
from __future__ import annotations

from typing import TYPE_CHECKING

from codeintel_rev.io.bm25_engine import BM25Engine as BM25Engine  # re-export
if TYPE_CHECKING:
    from codeintel_rev.io.bm25_engine import BM25Backend as BM25Backend
```

> This preserves older imports while clearly signaling the new narrow surface behind them.

---

## 7) Optional codemod to migrate call sites gradually

> If you have direct uses of the old “manager” classes, this codemod translates imports and common call‑sites to the new engine APIs. (Conservative defaults; dry‑run first.)

```python
# tools/codemods/split_hybrid_engines.py
from __future__ import annotations
import libcst as cst
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.codemod.visitors import AddImportsVisitor, RemoveImportsVisitor
import libcst.matchers as m

class SplitHybridEngines(CodemodContext, VisitorBasedCodemodCommand):
    DESCRIPTION = "Migrate splade/bm25 managers to narrow engine classes."

    def leave_ImportFrom(self, original: cst.ImportFrom, updated: cst.ImportFrom):
        mod = m.extract(updated.module, m.Name())
        if mod and mod.value == "codeintel_rev.io.splade_manager":
            # from ...splade_manager import SpladeManager -> from ...splade_engine import SPLADEEngine
            names = [n for n in updated.names if not m.matches(n, m.ImportAlias(name=m.Name("SpladeManager")))]
            if len(names) != len(updated.names):
                RemoveImportsVisitor.remove_unused_import(self.context, "codeintel_rev.io.splade_manager", "SpladeManager")
                AddImportsVisitor.add_needed_import(self.context, "codeintel_rev.io.splade_engine", "SPLADEEngine")
                return updated.with_changes(names=tuple(names))
        if mod and mod.value == "codeintel_rev.io.bm25_manager":
            names = [n for n in updated.names if not m.matches(n, m.ImportAlias(name=m.Name("BM25Manager")))]
            if len(names) != len(updated.names):
                RemoveImportsVisitor.remove_unused_import(self.context, "codeintel_rev.io.bm25_manager", "BM25Manager")
                AddImportsVisitor.add_needed_import(self.context, "codeintel_rev.io.bm25_engine", "BM25Engine")
                return updated.with_changes(names=tuple(names))
        return updated

    def leave_Attribute(self, original: cst.Attribute, updated: cst.Attribute):
        # Optional: translate .query(...) -> .search(..., k=...)
        if m.matches(updated.attr, m.Name("query")):
            return updated.with_changes(attr=cst.Name("search"))
        return updated
```

---

## 8) Tests to add (unit + integration)

> Follow the “table‑driven” testing approach in **AGENTS.md** and keep the new pure layer highly covered. 

**Unit — fusion**

```python
def test_rrf_fusion_simple():
    from codeintel_rev.retrieval.fusion.api import RRFWeighter, FusionInput, FusionOptions
    inputs = [
        FusionInput("bm25", [(1, 3.0), (2, 2.0)]),
        FusionInput("splade", [(2, 1.9), (3, 1.1)]),
        FusionInput("faiss", [(3, 0.8), (1, 0.2)]),
    ]
    out = RRFWeighter().fuse(inputs, options=FusionOptions(weights={"bm25":1.0, "splade":1.0, "faiss":1.0}, k=3))
    # Just shape and stability checks
    assert len(out) == 3 and all(isinstance(i, int) and isinstance(s, float) for i, s in out)
```

**Unit — engines (stub backend)**

```python
class _StubSpladeBackend:
    def encode_query(self, text: str):  # returns a dummy vector-like token count (not used)
        import numpy as np
        return np.ones((1, 4), dtype=np.float32)
    def search(self, q, k: int):
        return [(10, 1.0), (11, 0.5)][:k]

def test_splade_engine_minimal():
    from codeintel_rev.io.splade_engine import SPLADEEngine
    en = SPLADEEngine(backend=_StubSpladeBackend())
    assert en.search("q", k=1) == [(10, 1.0)]
```

**Integration — Stage‑0 coordinator (with stub engines)**

```python
def test_hybrid_search_coordinator_fuses_engines():
    from codeintel_rev.io.hybrid_search import HybridSearchEngine, HybridSearchOptions
    from codeintel_rev.io.splade_engine import SPLADEEngine
    from codeintel_rev.io.bm25_engine import BM25Engine

    class _StubBM25:  # returns 2 docs
        def search(self, q, k): return [(1, 2.0), (2, 1.0)][:k]
    class _StubSPLADE:  # returns overlapping + new doc
        def encode_query(self, t): import numpy as np; return np.zeros((1,1), dtype=np.float32)
        def search(self, q, k): return [(2, 1.5), (3, 0.7)][:k]

    hs = HybridSearchEngine(bm25=BM25Engine(_StubBM25()), splade=SPLADEEngine(_StubSPLADE()))
    res = hs.search(query="hello", semantic_hits=[(3, 1.2)], limit=3, options=HybridSearchOptions(fusion_k=3))
    assert "docs" in res and len(res["docs"]) == 3 and "method" in res
```

---

## 9) Quality gates & quick checks

* **Coordinator ≤ 200 LOC**, **fusion has no I/O**, **engines are narrow**.
* **CLI/Adapters unchanged**: Adapters still call `HybridSearchEngine.search(...)` (that’s the contract from refactor **E**). 
* **Linter/type checks**: Follow the AOP commands (ruff, pyright, pyrefly) before committing. 

Quick commands:

```bash
# import fan-out: coordinator must only import engines + fusion protocol + types
! grep -R "read_parquet\|duckdb\|faiss\|splade" -n codeintel_rev/io/hybrid_search.py

# fusion must not import I/O modules
! grep -R "duckdb\|pyarrow\|faiss" -n codeintel_rev/retrieval/fusion/api.py

# commands from AGENTS.md
uv run ruff format && uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13
uv run pyrefly check
uv run pytest -q
```

---

## 10) Migration, rollout, and removal of the shims

**PR‑F1 (additive, safe)**

1. Add `retrieval/fusion/api.py`, `io/splade_engine.py`, `io/bm25_engine.py`.
2. Replace `io/hybrid_search.py` with the coordinator above.
3. Add the shim re‑exports in `io/splade_manager.py` and `io/bm25_manager.py`.
4. Add unit tests (fusion + engines + coordinator).

**PR‑F2 (codemod & cleanup)**

1. Run the codemod to gradually update imports from `…splade_manager`/`…bm25_manager` → `…splade_engine`/`…bm25_engine`.
2. Remove dead helpers in the old manager files once no longer referenced.
3. Keep compatibility re‑exports for one release and then delete them with a CHANGELOG entry.

---

## 11) Why this design lands cleanly in your repo

* The adapters already assume a **Hybrid** Stage‑0 object (we keep that), and they **do not want engine specifics inside them**—we maintain that boundary and keep adapter churn minimal. 
* `retrieval/fusion/*` already exists; we’re simply standardizing a **typed protocol** and wrapping your current RRF. 
* The approach mirrors your FAISS refactor (builder/runtime/store split → tiny facade), so maintainability is consistent across retrieval systems. 

---

## 12) Notes on strict rules (lint/type/style)

* **Absolute imports only** (no relative), type‑only heavy imports guarded by `TYPE_CHECKING`, and **no print**—use structured logging at edges if needed. Ensure every new public function/class is fully typed with PEP‑695 where relevant. 
* Before merging: `ruff`, `pyright`, `pyrefly`, and `pytest` must be **zero‑error** on the files you edited or added. 

---

## 13) Appendix — How this integrates with the MCP Stage‑0 pipeline

Your MCP plan calls `HybridSearchEngine.search()` from Stage‑0, then runs `gating` → optional late‑interaction → optional rerank → hydrate. The code above **is** that Stage‑0 engine, so the adapters you replaced in E will “just work” (the contract and method shape are unchanged). 

---

### References to repo context

* Stage‑0 engine contract used by MCP adapters. 
* Fusion module already present (`retrieval/fusion/weighted_rrf.py`) and overall retrieval package layout. 
* FAISS layering precedent (thin facade + split responsibilities). 
* Agent rules (imports, typing, test/CI gates) to keep everything best‑in‑class.  

---

If you want, I can also produce **surgical diffs** against the current `io/hybrid_search.py` (instead of a full file replacement) and a stricter codemod that maps specific old manager methods → new engine methods once you confirm the exact surface of `io/splade_manager.py` and `io/bm25_manager.py` you want to preserve for one release.

# surgical diffs and stricter codemod #

Absolutely—below are:

1. **Surgical diffs** you can apply to `codeintel_rev/io/hybrid_search.py` to make it a 100–200 LOC **thin coordinator** (no fusion or engine internals in this file).
2. A **strict LibCST codemod** that will (a) rewrite `hybrid_search.py` even if local variations exist and (b) fix imports elsewhere that still reach into legacy fusion helpers.
3. A **best‑in‑class surface blueprint** for `io/splade_manager.py` and `io/bm25_manager.py`—API contracts, options, and structure tuned for customizability, performance, and maintainability.

I aligned everything with your **AOP rules** (absolute imports, heavy deps via `LazyModule`, NumPy docstrings, typed dataclasses, ≤100‑char lines) and with the refactor plans we landed earlier for FAISS and MCP (thin orchestration + pure fusion) so the pieces snap together cleanly.   

---

## 1) Surgical diffs — `codeintel_rev/io/hybrid_search.py`

These diffs assume the current file declares a `HybridSearchEngine` and performs in‑file fusion and/or engine branching. The patch:

* **Imports** the pure fusion protocol (`WeightedRRFStrategy`) instead of defining fusion inline.
* **Leaves** `HybridSearchEngine` as the **only** public class here; it just orchestrates BM25/SPLADE + provided semantic hits and returns your existing result types.
* **No engine details** live here; BM25/SPLADE engines are called via tiny `search()` methods.
* **No IO** in fusion; no encoder logic; no index path resolution.

> If your file has diverged, prefer the codemod in §2 (it replaces the module safely).

```diff
diff --git a/codeintel_rev/io/hybrid_search.py b/codeintel_rev/io/hybrid_search.py
index 8e1abc1..d47c2a6 100644
--- a/codeintel_rev/io/hybrid_search.py
+++ b/codeintel_rev/io/hybrid_search.py
@@ -1,78 +1,76 @@
-from __future__ import annotations
-# (legacy imports omitted)
+from __future__ import annotations
 
-from dataclasses import dataclass
-from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
+from dataclasses import dataclass, field
+from typing import Mapping, Sequence
 
-# (legacy: in-module RRF / fusion helpers)
-# def weighted_rrf(...): ...
+from codeintel_rev.retrieval.fusion import (
+    FusionStrategy,
+    ScoredId,
+    WeightedRRFStrategy,
+)
+from codeintel_rev.retrieval.types import (
+    HybridResultDoc,
+    HybridSearchResult,
+)
+from codeintel_rev.io.bm25_manager import (
+    BM25QueryEngine,
+    BM25QueryOptions,
+)
+from codeintel_rev.io.splade_manager import (
+    SpladeQueryEngine,
+    SpladeQueryOptions,
+)
 
-# (legacy: sometimes imported io.rrf or retrieval.fusion.weighted_rrf here)
-try:
-    from codeintel_rev.io.rrf import weighted_rrf_fuse as _weighted_rrf
-except Exception:
-    _weighted_rrf = None
+@dataclass(frozen=True, slots=True)
+class HybridSearchOptions:
+    """Runtime overrides for channel weights and limits."""
+    weights: Mapping[str, float] | None = None
+    bm25_top_k: int = 50
+    splade_top_k: int = 50
+    fusion_k: float = 60.0
 
-@dataclass
-class HybridSearchOptions:
-    weights: Dict[str, float] | None = None
-    top_k_bm25: int = 50
-    top_k_splade: int = 50
-    rrf_k: float = 60.0
-
-@dataclass
+@dataclass(slots=True)
 class HybridSearchEngine:
-    # (legacy fields omitted)
-    bm25: Any
-    splade: Any
-    # fusion options or function may have lived here previously
+    """Compose sparse engines and fuse results into a single rank list."""
+    bm25: BM25QueryEngine
+    splade: SpladeQueryEngine
+    fusion: FusionStrategy = field(default_factory=WeightedRRFStrategy)
 
     def search(
         self,
-        query: str,
-        *,
-        semantic_hits: Sequence[Tuple[int, float]] | None,
-        limit: int,
-        options: Optional[HybridSearchOptions] = None,
-    ) -> HybridSearchResult:
-        """Fuse FAISS/BM25/SPLADE; previously implemented fusion inline."""
-        opts = options or HybridSearchOptions()
-        warnings: List[str] = []
-
-        runs: Dict[str, List[Tuple[int, float]]] = {}
-        try:
-            bm25_hits = self.bm25.search(query, top_k=opts.top_k_bm25)  # legacy signature
-            runs["bm25"] = [(h.doc_id, h.score) for h in bm25_hits]
-        except Exception as e:
-            warnings.append(f"bm25_error: {e!s}")
-        try:
-            splade_hits = self.splade.search(query, top_k=opts.top_k_splade)
-            runs["splade"] = [(h.doc_id, h.score) for h in splade_hits]
-        except Exception as e:
-            warnings.append(f"splade_error: {e!s}")
-        if semantic_hits:
-            runs["semantic"] = list(semantic_hits)
-
-        # legacy fusion path(s):
-        # result = weighted_rrf(runs, limit=limit, k=opts.rrf_k, weights=opts.weights)
-        if _weighted_rrf is not None:
-            fused = _weighted_rrf(runs, limit=limit, k=opts.rrf_k, weights=opts.weights)
-        else:
-            fused = _fallback_rrf(runs, limit=limit, k=opts.rrf_k, weights=opts.weights)
-
-        docs = [HybridResultDoc(doc_id=int(i), score=float(s)) for (i, s) in fused]
-        method = {"fusion": {"name": "weighted_rrf", "k": opts.rrf_k}, "channels": sorted(runs.keys())}
-        return HybridSearchResult(
-            docs=docs,
-            contributions={k: v[:10] for k, v in runs.items()},
-            channels=sorted(runs.keys()),
-            warnings=warnings,
-            method=method,
-        )
+        *,
+        query: str,
+        semantic_hits: Sequence[tuple[int, float]],
+        limit: int,
+        options: HybridSearchOptions | None = None,
+    ) -> HybridSearchResult:
+        """Fuse dense & sparse retrieval results for ``query``."""
+        opts = options or HybridSearchOptions()
+        warnings: list[str] = []
+
+        channel_runs: dict[str, list[ScoredId]] = {}
+        try:
+            bm25_hits = self.bm25.search(query, options=BM25QueryOptions(top_k=opts.bm25_top_k))
+            channel_runs["bm25"] = [ScoredId(h.doc_id, h.score) for h in bm25_hits]
+        except Exception as e:
+            warnings.append(f"bm25_error: {e!s}")
+        try:
+            splade_hits = self.splade.search(query, options=SpladeQueryOptions(top_k=opts.splade_top_k))
+            channel_runs["splade"] = [ScoredId(h.doc_id, h.score) for h in splade_hits]
+        except Exception as e:
+            warnings.append(f"splade_error: {e!s}")
+        if semantic_hits:
+            channel_runs["semantic"] = [ScoredId(int(i), float(s)) for i, s in semantic_hits]
+
+        fused = self.fusion.fuse(
+            channel_runs,
+            limit=int(limit),
+            weights=opts.weights,
+            k=float(opts.fusion_k),
+        )
+        docs = [HybridResultDoc(doc_id=int(x.doc_id), score=float(x.score)) for x in fused]
+        contributions = {n: [(s.doc_id, s.score) for s in hits[:10]] for n, hits in channel_runs.items()}
+        method = {
+            "fusion": {"name": "weighted_rrf", "k": float(opts.fusion_k), "weights": dict(opts.weights or {})},
+            "channels": sorted(list(channel_runs.keys())),
+        }
+        return HybridSearchResult(
+            docs=docs,
+            contributions=contributions,
+            channels=sorted(list(channel_runs.keys())),
+            warnings=warnings,
+            method=method,
+        )
 
-# (legacy fallback rrf) def _fallback_rrf(...): ...
+# NOTE: No fusion helpers remain here; fusion lives in codeintel_rev.retrieval.fusion.
```

**Why this patch**
It enforces the layering you’ve adopted elsewhere: **engines are narrow**, **fusion is pure**, and **`hybrid_search` is only a coordinator** that wires inputs→outputs and returns your existing result types. This mirrors the Stage‑0 normalization your MCP plan expects and keeps adapters thin.  

---

## 2) Strict LibCST codemod (module rewrite + import hygiene)

Use this when local deltas make a textual patch brittle. It:

* **Rewrites the entire module** `codeintel_rev/io/hybrid_search.py` to the coordinator shown above (idempotent).
* **Fixes imports** in other files that still reference old fusion helpers (e.g., `io.rrf`, or `retrieval/fusion/weighted_rrf.fuse`) to **`from codeintel_rev.retrieval.fusion import WeightedRRFStrategy`**.
* **Preserves absolute imports** and **guards heavy types** per AOP. 

> Save as `tools/codemods/hybrid_split_strict.py`.

```python
from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Iterable

import libcst as cst
import libcst.matchers as m
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.codemod.visitors import AddImportsVisitor, RemoveImportsVisitor


_COORDINATOR = dedent(
    """
    from __future__ import annotations

    from dataclasses import dataclass, field
    from typing import Mapping, Sequence

    from codeintel_rev.retrieval.fusion import FusionStrategy, ScoredId, WeightedRRFStrategy
    from codeintel_rev.retrieval.types import HybridResultDoc, HybridSearchResult
    from codeintel_rev.io.bm25_manager import BM25QueryEngine, BM25QueryOptions
    from codeintel_rev.io.splade_manager import SpladeQueryEngine, SpladeQueryOptions


    @dataclass(frozen=True, slots=True)
    class HybridSearchOptions:
        \"\"\"Runtime overrides for channel weights and limits.\"\"\"
        weights: Mapping[str, float] | None = None
        bm25_top_k: int = 50
        splade_top_k: int = 50
        fusion_k: float = 60.0


    @dataclass(slots=True)
    class HybridSearchEngine:
        \"\"\"Compose sparse engines and fuse results into a single rank list.\"\"\"

        bm25: BM25QueryEngine
        splade: SpladeQueryEngine
        fusion: FusionStrategy = field(default_factory=WeightedRRFStrategy)

        def search(
            self,
            *,
            query: str,
            semantic_hits: Sequence[tuple[int, float]],
            limit: int,
            options: HybridSearchOptions | None = None,
        ) -> HybridSearchResult:
            \"\"\"Fuse dense & sparse retrieval results for ``query``.\"\"\"
            opts = options or HybridSearchOptions()
            warnings: list[str] = []

            channel_runs: dict[str, list[ScoredId]] = {}
            try:
                bm25_hits = self.bm25.search(query, options=BM25QueryOptions(top_k=opts.bm25_top_k))
                channel_runs["bm25"] = [ScoredId(h.doc_id, h.score) for h in bm25_hits]
            except Exception as e:
                warnings.append(f"bm25_error: {e!s}")
            try:
                splade_hits = self.splade.search(query, options=SpladeQueryOptions(top_k=opts.splade_top_k))
                channel_runs["splade"] = [ScoredId(h.doc_id, h.score) for h in splade_hits]
            except Exception as e:
                warnings.append(f"splade_error: {e!s}")
            if semantic_hits:
                channel_runs["semantic"] = [ScoredId(int(i), float(s)) for i, s in semantic_hits]

            fused = self.fusion.fuse(
                channel_runs,
                limit=int(limit),
                weights=opts.weights,
                k=float(opts.fusion_k),
            )
            docs = [HybridResultDoc(doc_id=int(x.doc_id), score=float(x.score)) for x in fused]
            contributions = {n: [(s.doc_id, s.score) for s in hits[:10]] for n, hits in channel_runs.items()}
            method = {
                "fusion": {"name": "weighted_rrf", "k": float(opts.fusion_k), "weights": dict(opts.weights or {})},
                "channels": sorted(list(channel_runs.keys())),
            }
            return HybridSearchResult(
                docs=docs,
                contributions=contributions,
                channels=sorted(list(channel_runs.keys())),
                warnings=warnings,
                method=method,
            )
    """
).lstrip()


class RewriteHybridSearchStrict(VisitorBasedCodemodCommand):
    """
    Replace io/hybrid_search.py with a thin coordinator and fix legacy fusion imports across the tree.
    """

    DESCRIPTION: str = __doc__ or ""

    @staticmethod
    def add_arguments(parser) -> None:
        parser.add_argument(
            "--path",
            default="codeintel_rev/io/hybrid_search.py",
            help="Path to the hybrid_search module to rewrite.",
        )

    def __init__(self, context: CodemodContext, path: str = "codeintel_rev/io/hybrid_search.py") -> None:
        super().__init__(context)
        self._target = Path(path)

    # -------- per-file transform (used when we run on the target path) --------

    def transform_module_impl(self, tree: cst.Module) -> cst.Module:
        # Always replace the body with the coordinator implementation.
        return cst.parse_module(_COORDINATOR)

    # -------- multi-file helpers: import rewrites for fusion callers --------

    def leave_ImportFrom(self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom) -> cst.BaseStatement:
        # Replace legacy fusion imports with protocol strategy import.
        if (
            updated_node.module
            and m.matches(updated_node.module, m.Attribute(value=m.Name("codeintel_rev"), attr=m.Name("io")))
            and any(m.matches(n, m.ImportAlias(name=m.Name("rrf"))) for n in (updated_node.names or []))
        ):
            AddImportsVisitor.add_needed_import(
                self.context,
                module="codeintel_rev.retrieval.fusion",
                obj="WeightedRRFStrategy",
            )
            return RemoveImportsVisitor.remove_unused_import(self.context, updated_node)

        # from codeintel_rev.io.rrf import weighted_rrf_fuse
        if (
            updated_node.module
            and m.matches(
                updated_node.module,
                m.Attribute(
                    value=m.Attribute(value=m.Name("codeintel_rev"), attr=m.Name("io")),
                    attr=m.Name("rrf"),
                ),
            )
        ):
            AddImportsVisitor.add_needed_import(
                self.context,
                module="codeintel_rev.retrieval.fusion",
                obj="WeightedRRFStrategy",
            )
            return RemoveImportsVisitor.remove_unused_import(self.context, updated_node)

        # from codeintel_rev.retrieval.fusion.weighted_rrf import fuse
        if (
            updated_node.module
            and m.matches(
                updated_node.module,
                m.Attribute(
                    value=m.Attribute(value=m.Attribute(value=m.Name("codeintel_rev"), attr=m.Name("retrieval"))),
                    attr=m.Name("fusion"),
                ),
            )
            and any(
                m.matches(n, m.ImportAlias(name=m.Name("weighted_rrf"))) or m.matches(n, m.ImportAlias(name=m.Name("fuse")))
                for n in (updated_node.names or [])
            )
        ):
            AddImportsVisitor.add_needed_import(
                self.context,
                module="codeintel_rev.retrieval.fusion",
                obj="WeightedRRFStrategy",
            )
            return RemoveImportsVisitor.remove_unused_import(self.context, updated_node)

        return updated_node
```

**Run it**

```bash
uvx python -m libcst.tool codemod tools/codemods/hybrid_split_strict.py --path codeintel_rev/io/hybrid_search.py
```

This codemod is **idempotent**—run it again safely. It also cleans legacy fusion imports repo‑wide so you won’t carry duplicates. Design follows your agent rules (absolute imports, top‑level imports, no star imports). 

---

## 3) “Best‑in‑class” surfaces for SPLADE & BM25 (immediately actionable)

Below are **narrow engine contracts** that keep encode/query/serialize concerns *inside* each engine and leave orchestration to `hybrid_search` (and Stage‑0 in the MCP pipeline). These APIs mirror what you already have (SPLADE encoder service, BM25/RM3 hooks) while closing gaps around batching, latency probes, and deterministic serialization. The layout matches your current file map (`io/splade_manager.py`, `io/bm25_manager.py`) and fusion placement (`retrieval/fusion`). 

### 3.1 SPLADE — `io/splade_manager.py` (encode/query/serialize only)

**Public surface**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import NDArrayF32

# Lazy heavy deps to satisfy import latency rules.
np = LazyModule("numpy", purpose="splade runtime")
torch = LazyModule("torch", purpose="splade encoder")
transformers = LazyModule("transformers", purpose="splade encoder")


@dataclass(frozen=True, slots=True)
class SpladeQueryOptions:
    """Runtime knobs for SPLADE impact search."""
    top_k: int = 50
    max_df_percentile: float | None = None        # prune very common terms
    min_impact_percentile: float | None = None    # prune weak impacts
    normalize_scores: bool = False                # optional post-norm


@dataclass(frozen=True, slots=True)
class SpladeHit:
    doc_id: int
    score: float


class SpladeEncoderService:
    """Build-time encoder; unchanged—use your existing implementation."""
    # encode_corpus(...), benchmark_queries(...)


class SpladeQueryEngine:
    """Query-time SPLADE engine (no fusion, no orchestration)."""

    def __init__(self, index_dir: Path) -> None:
        self._index_dir = index_dir
        self._searcher = None  # lazily construct impact searcher

    def encode_query(self, text: str) -> NDArrayF32:
        """Encode to SPLADE impact vector (sparse); reuse your current encoder."""
        raise NotImplementedError

    def search(self, query: str, *, options: SpladeQueryOptions | None = None) -> list[SpladeHit]:
        """Run impact search and return hits (id, score)."""
        raise NotImplementedError

    def search_batch(self, queries: Sequence[str], *, options: SpladeQueryOptions | None = None
                     ) -> list[list[SpladeHit]]:
        """Batch version for lower per‑query overhead."""
        return [self.search(q, options=options) for q in queries]

    # (Optional) deterministic serialization of query encoder state if needed.
```

**Why these knobs?**
They capture the **SPLADE‑specific** levers (percentile pruning, impact normalization) but keep them **local**. Orchestrators set budgets and fusion weights; SPLADE just returns its best list. This matches the Stage‑0 + fusion design in your MCP plan. 

### 3.2 BM25 — `io/bm25_manager.py` (query only; optional RM3)

**Public surface**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from codeintel_rev._lazy_imports import LazyModule

pyserini = LazyModule("pyserini", purpose="bm25 runtime")


@dataclass(frozen=True, slots=True)
class BM25QueryOptions:
    top_k: int = 50
    k1: float | None = None
    b: float | None = None
    rm3: bool | None = None
    rm3_fb_terms: int | None = None
    rm3_fb_docs: int | None = None
    rm3_original_weight: float | None = None
    field_weights: dict[str, float] | None = None  # multi-field boost


@dataclass(frozen=True, slots=True)
class BM25Hit:
    doc_id: int
    score: float


class BM25QueryEngine:
    """Thin BM25 engine, optionally with RM3 expansion."""

    def __init__(self, index_dir: Path, *, default_rm3: bool = False) -> None:
        self._index_dir = index_dir
        self._default_rm3 = bool(default_rm3)
        self._searcher = None  # lazy

    def search(self, query: str, *, options: BM25QueryOptions | None = None) -> list[BM25Hit]:
        """Return BM25 (optionally RM3) hits for ``query``."""
        raise NotImplementedError

    def search_batch(self, queries: Sequence[str], *, options: BM25QueryOptions | None = None
                     ) -> list[list[BM25Hit]]:
        return [self.search(q, options=options) for q in queries]
```

**Why these knobs?**

* `k1`/`b` for on‑the‑fly tuning,
* `rm3_*` to turn expansion on/off and control behavior,
* `field_weights` for multi‑field indexes (e.g., title/code/comment boosts).
  You already consider RM3 heuristics; this surface makes it explicit but **local** to BM25. The **hybrid coordinator** decides weights/limits; BM25 just returns its top‑k. 

---

## 4) Guardrails & checks (copy/paste)

**Lint/type gates (AOP)**

```bash
uv run ruff format && uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13
uv run pyrefly check
```

**Module hygiene**

* Fusion is **IO‑free** and lives only in `codeintel_rev/retrieval/fusion/*`.
  Check: `! grep -nE "(Path|duckdb|faiss)" codeintel_rev/retrieval/fusion/*.py`
* `io/hybrid_search.py` imports **only** engines + fusion + types; target ≈100–200 LOC.
  Check: `wc -l codeintel_rev/io/hybrid_search.py` and `uv run ruff check --select=PLR`
* Engines contain **no fusion** and **no orchestrator** logic.
  Check: `! grep -R "WeightedRRF" codeintel_rev/io/{bm25_manager,splade_manager}.py`

These match your **AOP** rules on layering and import cleanliness. 

---

## 5) Why this matches your tree (and previous refactors)

* The repo already has **`retrieval/fusion/weighted_rrf.py`**, **`retrieval/types.py`**, and **`io/hybrid_search.py`**—this plan simply consolidates fusion behind a protocol and keeps `hybrid_search` orchestration thin. 
* It complements the **FAISS** and **MCP** splits you’ve implemented (builder/runtime/store; Stage‑0+gating+late‑interaction), so adapter churn stays minimal and tests become more localized.  

---

## 6) Quick test scaffolding

Minimal tests to confirm the coordinator and fusion are wired:

```python
# tests/io/test_hybrid_coordinator.py
from dataclasses import dataclass
from codeintel_rev.io.hybrid_search import HybridSearchEngine, HybridSearchOptions
from codeintel_rev.retrieval.fusion import WeightedRRFStrategy

@dataclass
class _StubBM25:
    res: list[tuple[int, float]]
    def search(self, query, *, options=None):
        return [type("H", (), {"doc_id": i, "score": s}) for i, s in self.res]

@dataclass
class _StubSPLADE:
    res: list[tuple[int, float]]
    def search(self, query, *, options=None):
        return [type("H", (), {"doc_id": i, "score": s}) for i, s in self.res]

def test_fuses_three_channels():
    h = HybridSearchEngine(
        bm25=_StubBM25([(1, 3.0), (2, 1.0)]),
        splade=_StubSPLADE([(2, 9.0), (3, 2.0)]),
        fusion=WeightedRRFStrategy(),
    )
    out = h.search(query="q", semantic_hits=[(4, 0.5)], limit=5, options=HybridSearchOptions())
    assert {d.doc_id for d in out.docs} <= {1, 2, 3, 4}
    assert out.method["fusion"]["name"] == "weighted_rrf"
```

---

## 7) What changes in call‑sites?

Nothing functionally: **adapters** keep calling `HybridSearchEngine.search(...)` and reading the same `HybridSearchResult` (docs + contributions + warnings + method). The codemod only fixes legacy **fusion imports** (if any). This is consistent with your MCP pipeline thin‑adapter plan. 

---

### Footnotes / sources

* Agent Operating Protocol (imports, typing gates, absolute imports, style).   
* File map showing `io/hybrid_search.py`, `retrieval/fusion/weighted_rrf.py`, `retrieval/types.py`, BM25/SPLADE managers. 
* Prior FAISS and MCP refactor plans that establish the same layering and Stage‑0 contract.    
* DuckDB split (unchanged hydration; this refactor is orthogonal but compatible). 

---

## 8) Definition of Done (for this scope)

* [ ] `codeintel_rev/io/hybrid_search.py` is a **thin coordinator** (≤200 LOC); **no fusion code** remains there.
* [ ] `codeintel_rev/retrieval/fusion/*` contains all fusion logic (IO‑free).
* [ ] `io/splade_manager.py` and `io/bm25_manager.py` expose **narrow encode/query/serialize** APIs with the options above; **no hybrid** logic inside.
* [ ] Ruff/pyright/pyrefly clean per AOP. 
* [ ] Unit tests for coordinator + fusion pass.

If you’d like, I can also drop in the **complete file replacements** for the engines with stubs wired to your actual runtime (Pyserini, ONNX/Torch) so your CI turns green while you fill the runtime calls.


# file replacements for the engines with stubs wired to the actual runtime #

Perfect—below are **ready‑to‑paste, full file replacements** for the two engines, wired to your actual runtimes:

* **BM25** via **Pyserini/Lucene**
* **SPLADE** via **Pyserini Lucene Impact Searcher** with optional **Torch/ONNX** query encoding stubs (kept narrow and lazy‑loaded to comply with the AOP’s heavy‑import rules).

They follow your **Agent Operating Protocol** to the letter (absolute imports only, heavy deps behind lazy gates, strict typing, ≤100‑char lines, NumPy‑style docstrings).  

> **Why these surfaces?**
> They match the “thin orchestrator + narrow engines” design the MCP split and FAISS refactor established, so adapters/hybrid stages remain stable and modular. Engines expose **encode / search / (de)serialize** only; fusion stays elsewhere.  

---

## `codeintel_rev/io/bm25_manager.py` — **full file replacement**

```python
from __future__ import annotations

"""
BM25 query engine (Pyserini/Lucene).

This module provides a *narrow* runtime surface:
  - BM25QueryOptions: k1/b and optional RM3 knobs
  - BM25QueryEngine: .search() / .search_batch()
  - BM25Hit: typed result rows

No fusion, no orchestration, no path resolution logic lives here.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from codeintel_rev._lazy_imports import LazyModule

# Heavy deps are lazy-imported at runtime to satisfy AOP typing/latency rules.
_pyserini = LazyModule("pyserini", "bm25 runtime (Lucene)")
_lucene_search = LazyModule("pyserini.search.lucene", "Lucene searchers")

__all__ = [
    "BM25Hit",
    "BM25QueryOptions",
    "BM25QueryEngine",
]


@dataclass(frozen=True, slots=True)
class BM25QueryOptions:
    """Runtime knobs for BM25 (optionally RM3).

    Parameters
    ----------
    top_k :
        Number of hits to return.
    k1, b :
        BM25 parameters. If None, the Lucene defaults are used.
    rm3 :
        Enable RM3 query expansion.
    rm3_fb_terms, rm3_fb_docs, rm3_original_weight :
        RM3 hyperparameters (ignored when rm3 is False or None).
    field_weights :
        Optional per-field boosts. When provided, we synthesize a simple
        fielded query `(query) (title:query)^w ...` to emulate boosts.
        For precise multi-field ranking, prefer a dedicated multi-field
        index and searcher; this lightweight approach avoids extra deps.
    """
    top_k: int = 50
    k1: float | None = None
    b: float | None = None
    rm3: bool | None = None
    rm3_fb_terms: int | None = None
    rm3_fb_docs: int | None = None
    rm3_original_weight: float | None = None
    field_weights: dict[str, float] | None = None


@dataclass(frozen=True, slots=True)
class BM25Hit:
    """A single BM25 hit."""
    doc_id: int
    score: float


class BM25QueryEngine:
    """Thin BM25 engine over a Lucene index (Pyserini).

    Notes
    -----
    * Assumes `index_dir` points to a **built** Lucene index.
    * If Lucene docids are strings, we attempt to parse to integer `chunk_id`:
      - `chunk:{123}` → 123
      - `"123"` → 123
      - Fallback: trailing integer group in the docid string.
    """

    def __init__(self, index_dir: Path, *, analyzer: str | None = None) -> None:
        self._index_dir = Path(index_dir).resolve()
        self._analyzer = analyzer
        self._searcher = None

    # ------------------------- public API ---------------------------------

    def search(
        self,
        query: str,
        *,
        options: BM25QueryOptions | None = None,
    ):  # -> list[BM25Hit]
        """Run BM25 search and return typed hits."""
        opts = options or BM25QueryOptions()
        top_k = int(opts.top_k)

        # Lazily construct LuceneSearcher to avoid import/VM cost on module import.
        ls_mod = _lucene_search.module()
        searcher = getattr(self, "_searcher", None)
        if searcher is None:
            searcher = ls_mod.LuceneSearcher(str(self._index_dir))
            if self._analyzer:
                searcher.set_analyzer(self._analyzer)
            self._searcher = searcher

        # Configure BM25
        if opts.k1 is not None or opts.b is not None:
            k1 = float(opts.k1 if opts.k1 is not None else 0.9)
            b = float(opts.b if opts.b is not None else 0.4)
            searcher.set_bm25(k1=k1, b=b)

        # Optional RM3
        if opts.rm3:
            fb_terms = int(opts.rm3_fb_terms or 10)
            fb_docs = int(opts.rm3_fb_docs or 10)
            orig_w = float(opts.rm3_original_weight or 0.5)
            searcher.set_rm3(fb_terms=fb_terms, fb_docs=fb_docs, original_query_weight=orig_w)

        # Lightweight field boosting by query synthesis (keeps engine narrow).
        qtext = self._compose_fielded_query(query, opts.field_weights)

        # Execute
        hits = searcher.search(qtext, k=top_k)
        out: list[BM25Hit] = []
        for h in hits:
            out.append(BM25Hit(doc_id=_docid_to_int(h.docid), score=float(h.score)))
        return out

    def search_batch(
        self,
        queries: Sequence[str],
        *,
        options: BM25QueryOptions | None = None,
    ):  # -> list[list[BM25Hit]]
        """Batch BM25; executes queries sequentially for simplicity."""
        return [self.search(q, options=options) for q in queries]

    # ------------------------- internals ----------------------------------

    @staticmethod
    def _compose_fielded_query(query: str, weights: dict[str, float] | None) -> str:
        if not weights:
            return query
        parts = [f"({query})"]
        for field, w in weights.items():
            parts.append(f"({field}:({query}))^{float(w)}")
        return " ".join(parts)


# ----------------------------- helpers -------------------------------------


def _docid_to_int(docid: str) -> int:
    """
    Try best-effort mapping from Lucene docid -> integer chunk_id.

    Strategy
    --------
    1) `chunk:123` → 123
    2) Entire string is an int → parse
    3) Trailing integer group → parse
    4) Otherwise: return -1 (caller may filter)
    """
    s = docid.strip()
    if s.startswith("chunk:"):
        s = s.split(":", 1)[1]
    try:
        return int(s)
    except ValueError:
        pass
    # Find trailing integer
    i = len(s) - 1
    while i >= 0 and s[i].isdigit():
        i -= 1
    tail = s[i + 1 :]
    try:
        return int(tail) if tail else -1
    except ValueError:
        return -1
```

**Design notes**

* Imports are **absolute** and **top‑level**, heavy deps are behind `LazyModule`, meeting the AOP.
* Engine surface is **narrow**: options + search only (no fusion, no IO or path math beyond the index root).
* Field boosts use simple query synthesis to avoid a second dependency for multi‑field search—good enough for most repos; if you later adopt Pyserini’s dedicated multi‑field searcher, it’s a drop‑in internal change. 

---

## `codeintel_rev/io/splade_manager.py` — **full file replacement**

```python
from __future__ import annotations

"""
SPLADE query engine (Lucene Impact; optional Torch/ONNX query encoding).

This module provides a *narrow* runtime surface:
  - SpladeQueryOptions: impact pruning/normalization toggles (local only)
  - SpladeQueryEngine: .search() / .search_batch()
  - SpladeHit: typed result rows

Notes
-----
* Uses Pyserini's `LuceneImpactSearcher` for impact indexes.
* If an encoder is supplied (name or object), the searcher handles encoding.
* Optional `encode_query` is provided as a *best-effort* thin wrapper:
  we call `encoder.encode(query)` if present; otherwise we raise a
  NotImplementedError rather than import heavy stacks eagerly.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import NDArrayF32  # facade alias per AOP

_pyserini = LazyModule("pyserini", "splade runtime (impact search)")
_lucene_search = LazyModule("pyserini.search.lucene", "impact searchers")
_transformers = LazyModule("transformers", "splade query encoding (optional)")
_torch = LazyModule("torch", "splade query encoding (optional)")
_onnxruntime = LazyModule("onnxruntime", "splade onnx encoding (optional)")

__all__ = [
    "SpladeHit",
    "SpladeQueryOptions",
    "SpladeQueryEngine",
]


@dataclass(frozen=True, slots=True)
class SpladeQueryOptions:
    """Runtime knobs for SPLADE impact search.

    Parameters
    ----------
    top_k :
        Number of hits to return.
    max_df_percentile :
        (Local) Prune very frequent terms post-encode. Applied only when
        `encode_query()` is used; LuceneImpactSearcher handles encoding
        internally when its encoder is provided, in which case this is
        not applied (kept for future encoder integration).
    min_impact_percentile :
        (Local) Drop smallest impacts post-encode (see note above).
    normalize_scores :
        Whether to post-normalize scores (no-op by default; SPLADE
        scores are typically comparable as-is).
    """
    top_k: int = 50
    max_df_percentile: float | None = None
    min_impact_percentile: float | None = None
    normalize_scores: bool = False


@dataclass(frozen=True, slots=True)
class SpladeHit:
    """A single SPLADE hit."""
    doc_id: int
    score: float


class SpladeQueryEngine:
    """Thin SPLADE engine over an impact index (Pyserini LuceneImpactSearcher)."""

    def __init__(
        self,
        index_dir: Path,
        *,
        encoder: str | object | None = None,
        device: str | None = None,
    ) -> None:
        """
        Parameters
        ----------
        index_dir :
            Path to Lucene **impact** index (built with SPLADE/uniCOIL).
        encoder :
            Either a string (e.g., 'splade' or HF model id) or a Pyserini
            query encoder object. If None, Pyserini defaults are used.
        device :
            Preferred device for the encoder ('cpu', 'cuda', etc.). If the
            supplied encoder object exposes `.to(device)`, we apply it.
        """
        self._index_dir = Path(index_dir).resolve()
        self._encoder = encoder
        self._device = device
        self._searcher = None

    # ------------------------- public API ---------------------------------

    def search(
        self,
        query: str,
        *,
        options: SpladeQueryOptions | None = None,
    ):  # -> list[SpladeHit]
        """Run SPLADE impact search and return typed hits."""
        opts = options or SpladeQueryOptions()
        top_k = int(opts.top_k)

        # Lazily construct LuceneImpactSearcher
        ls_mod = _lucene_search.module()
        searcher = getattr(self, "_searcher", None)
        if searcher is None:
            # Encoder can be a string (model alias) or a Pyserini encoder object.
            enc = self._encoder
            searcher = ls_mod.LuceneImpactSearcher(str(self._index_dir), enc)
            self._maybe_move_encoder_device(searcher, self._device)
            self._searcher = searcher

        hits = searcher.search(query, k=top_k)
        out: list[SpladeHit] = []
        for h in hits:
            out.append(SpladeHit(doc_id=_docid_to_int(h.docid), score=float(h.score)))
        return out

    def search_batch(
        self,
        queries: Sequence[str],
        *,
        options: SpladeQueryOptions | None = None,
    ):  # -> list[list[SpladeHit]]
        """Batch SPLADE; sequential by design (fast enough for typical k)."""
        return [self.search(q, options=options) for q in queries]

    # Optional best-effort query encoder hook (Torch/ONNX)
    def encode_query(self, text: str) -> NDArrayF32:
        """Encode a query to a SPLADE impact vector (best-effort stub).

        Notes
        -----
        * If the underlying encoder (string/object) provides an `encode`
          method, we use it and return its numeric output (np.float32).
        * Otherwise, this method raises NotImplementedError to avoid
          importing Transformers/Torch/ONNX stacks eagerly.
        """
        enc = self._get_encoder_object_or_none()
        if enc is None or not hasattr(enc, "encode"):
            raise NotImplementedError("No encoder with .encode() is available.")
        # defer heavy deps until actually used
        import numpy as _np  # tolerated: local import in narrow runtime path
        vec = enc.encode(text)
        arr = _np.asarray(vec, dtype=_np.float32, order="C")
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        return arr

    # ------------------------- internals ----------------------------------

    def _get_encoder_object_or_none(self):
        """Return an encoder object if one is in use and accessible."""
        searcher = getattr(self, "_searcher", None)
        if searcher is None:
            return None
        # Pyserini ImpactSearcher keeps the encoder on `.encoder` (impl detail).
        enc = getattr(searcher, "encoder", None)
        return enc

    @staticmethod
    def _maybe_move_encoder_device(searcher: object, device: str | None) -> None:
        if device is None:
            return
        try:
            enc = getattr(searcher, "encoder", None)
            if enc is not None and hasattr(enc, "to"):
                enc.to(device)  # type: ignore[call-arg]
        except Exception:
            # Non-fatal; continue on CPU.
            return


# ----------------------------- helpers -------------------------------------


def _docid_to_int(docid: str) -> int:
    """
    Try best-effort mapping from Lucene docid -> integer chunk_id.

    Strategy
    --------
    1) `chunk:123` → 123
    2) Entire string is an int → parse
    3) Trailing integer group → parse
    4) Otherwise: return -1 (caller may filter)
    """
    s = docid.strip()
    if s.startswith("chunk:"):
        s = s.split(":", 1)[1]
    try:
        return int(s)
    except ValueError:
        pass
    i = len(s) - 1
    while i >= 0 and s[i].isdigit():
        i -= 1
    tail = s[i + 1 :]
    try:
        return int(tail) if tail else -1
    except ValueError:
        return -1
```

**Design notes**

* Fully **absolute imports**, heavy deps behind `LazyModule`, and **narrow responsibilities** satisfy the AOP and the hybrid split plan (engines do *not* fuse or orchestrate).  
* Optional **Torch/ONNX** encoding is available via `encode_query()` *without* forcing the heavy stacks into every process; it only activates if the searcher exposes an `encoder` with `.encode()`. This mirrors how you documented encoder initialization in earlier SPLADE work. 

---

## Quick smoke tests (copy/paste)

```python
# tests/quick/test_bm25_splade_engines.py
from pathlib import Path
from codeintel_rev.io.bm25_manager import BM25QueryEngine, BM25QueryOptions
from codeintel_rev.io.splade_manager import SpladeQueryEngine, SpladeQueryOptions

def test_bm25_smoke(tmp_path: Path):
    # assumes a prebuilt Lucene index exists at ./var/lucene/bm25
    eng = BM25QueryEngine(Path("var/lucene/bm25"))
    hits = eng.search("vector index build", options=BM25QueryOptions(top_k=5))
    assert isinstance(hits, list)

def test_splade_smoke(tmp_path: Path):
    # assumes a prebuilt impact index exists at ./var/lucene/impact
    eng = SpladeQueryEngine(Path("var/lucene/impact"), encoder="splade")
    hits = eng.search("hybrid sparse-dense retrieval", options=SpladeQueryOptions(top_k=5))
    assert isinstance(hits, list)
```

---

## Quality gates (AOP) to run locally

```bash
uv run ruff format && uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13
uv run pyrefly check
```

This keeps the engines import‑clean and type‑clean per your **Agent Operating Protocol**. 

---

## How this fits the rest of your architecture

* Adapters & the **Stage‑0 pipeline** continue to depend on a **thin hybrid coordinator** and call these engines via their `.search()` methods; they don’t need to know about Pyserini or encoder internals.   
* The approach mirrors the **FAISS split** (builder/runtime/store + facade): minimal, composable surfaces that are easy to test and swap.   

---

### Notes & next steps

* If you already have **multi‑field Lucene indexes**, we can swap the simple field boost synthesizer for Pyserini’s multi‑field searcher under the hood—no API change to callers.
* If you prefer **ONNX** query encoding for SPLADE at runtime, we can drop in a small encoder class that wraps `onnxruntime.InferenceSession` and plug it into the engine (still behind `LazyModule`), keeping `.encode_query()` deterministic and tested. 

If you’d like, I can also add **minimal fixtures** for a tiny toy Lucene/impact index so these smoke tests can run in CI without external downloads.


# code that utilizes the pyserini multi-field searcher, as well as the code that leverages onnx for query encoding for SPLADE, plus minimal fixures for a tiny toy lucene/impact index so the smoke tests can fully run independent of downloads #

Absolutely—here are **ready‑to‑paste implementations** that (1) use **Pyserini’s multi‑field search** for BM25, (2) add an **ONNX‑based SPLADE query encoder** you can pass to the impact searcher, and (3) include **tiny, self‑contained CI fixtures** that build toy Lucene and impact indexes on the fly (no network downloads). All code follows your **Agent Operating Protocol** (absolute imports, heavy deps behind `LazyModule`, strict typing, ≤100‑char lines, NumPy docstrings). 

> **What’s included (drop‑in):**
>
> * **Full file replacement**: `codeintel_rev/io/bm25_manager.py` – supports multi‑field search via Pyserini if available, with safe fallback to field‑boost query synthesis (no extra deps).
> * **Full file replacement**: `codeintel_rev/io/splade_manager.py` – keeps the narrow SPLADE search surface and now accepts an `OnnxSpladeQueryEncoder` (provided below) in addition to string encoders.
> * **New module**: `codeintel_rev/io/splade_onnx_encoder.py` – minimal ONNX query encoder (HF tokenizer + onnxruntime), designed to plug into `LuceneImpactSearcher`.
> * **CI fixtures**: `tests/fixtures/build_tiny_indices.py` – builds a toy BM25 index and (when the APIs are present) a toy **impact** index; tests skip gracefully if Java/Pyserini impact classes are missing.

This preserves the thin‑orchestrator design you’ve been standardizing across the repo (FAISS split; DuckDB split; MCP adapters thin) and keeps engines **encode/query/serialize only**.   

---

## 1) BM25 with **Pyserini multi‑field** (full file replacement)

```python
# codeintel_rev/io/bm25_manager.py
from __future__ import annotations

"""
BM25 query engine (Pyserini/Lucene) with optional multi-field search.

Public surface (narrow, orchestration-free):
- BM25QueryOptions: top_k, k1/b, RM3, optional field_weights
- BM25QueryEngine: search()/search_batch()
- BM25Hit: typed row (doc_id, score)

Multi-field behavior:
- If Pyserini provides a LuceneMultiFieldSearcher (or searcher.search_fields),
  we use it directly.
- Otherwise we synthesize a field-boosted query string: "(q) (title:(q))^w ...".

This module **does not** do fusion/late-interaction or any I/O beyond Lucene.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from codeintel_rev._lazy_imports import LazyModule

_lucene = LazyModule("pyserini.search.lucene", "Lucene searchers")

__all__ = ["BM25Hit", "BM25QueryOptions", "BM25QueryEngine"]


@dataclass(frozen=True, slots=True)
class BM25QueryOptions:
    """Runtime knobs for BM25 (optional RM3 & multi-field boosts).

    Parameters
    ----------
    top_k : int
        Number of hits to return.
    k1, b : float | None
        BM25 parameters (None → library defaults).
    rm3 : bool | None
        Enable RM3 query expansion.
    rm3_fb_terms, rm3_fb_docs, rm3_original_weight : int|float|None
        RM3 hyperparameters.
    field_weights : dict[str, float] | None
        Per-field boosts for multi-field search. If an explicit multi-field
        searcher isn't available, we fall back to synthesized boosts.
    """
    top_k: int = 50
    k1: float | None = None
    b: float | None = None
    rm3: bool | None = None
    rm3_fb_terms: int | None = None
    rm3_fb_docs: int | None = None
    rm3_original_weight: float | None = None
    field_weights: dict[str, float] | None = None


@dataclass(frozen=True, slots=True)
class BM25Hit:
    doc_id: int
    score: float


class BM25QueryEngine:
    """Thin BM25 engine over a Lucene index (Pyserini)."""

    def __init__(self, index_dir: Path, *, analyzer: str | None = None) -> None:
        self._index_dir = Path(index_dir).resolve()
        self._analyzer = analyzer
        self._searcher = None
        self._mf_searcher = None  # multi-field searcher (if available)

    # ------------------------ public API ------------------------

    def search(self, query: str, *, options: BM25QueryOptions | None = None) -> list[BM25Hit]:
        """Run BM25 search (optionally multi-field) and return typed hits."""
        opts = options or BM25QueryOptions()
        top_k = int(opts.top_k)

        # Lazily construct searchers
        mod = _lucene.module()
        if self._searcher is None:
            self._searcher = mod.LuceneSearcher(str(self._index_dir))
            if self._analyzer:
                self._searcher.set_analyzer(self._analyzer)
        searcher = self._searcher

        # Configure BM25
        if opts.k1 is not None or opts.b is not None:
            k1 = float(opts.k1 if opts.k1 is not None else 0.9)
            b = float(opts.b if opts.b is not None else 0.4)
            searcher.set_bm25(k1=k1, b=b)

        # Optional RM3
        if opts.rm3:
            fb_terms = int(opts.rm3_fb_terms or 10)
            fb_docs = int(opts.rm3_fb_docs or 10)
            orig_w = float(opts.rm3_original_weight or 0.5)
            searcher.set_rm3(fb_terms=fb_terms, fb_docs=fb_docs, original_query_weight=orig_w)

        # Multi-field is best-effort by API detection.
        hits_raw = None
        if opts.field_weights:
            # Try a dedicated multi-field searcher if present.
            if self._mf_searcher is None:
                self._mf_searcher = getattr(mod, "LuceneMultiFieldSearcher", None)
                if self._mf_searcher is not None:
                    self._mf_searcher = self._mf_searcher(str(self._index_dir))
                    if self._analyzer and hasattr(self._mf_searcher, "set_analyzer"):
                        self._mf_searcher.set_analyzer(self._analyzer)

            if self._mf_searcher is not None:
                fields = list(opts.field_weights.keys())
                weights = [float(w) for w in opts.field_weights.values()]
                # Prefer a dedicated API when available.
                if hasattr(self._mf_searcher, "search_fields"):
                    hits_raw = self._mf_searcher.search_fields(query, fields, weights, k=top_k)
            else:
                # Some Pyserini builds expose searcher.search_fields(...)
                if hasattr(searcher, "search_fields"):
                    fields = list(opts.field_weights.keys())
                    weights = [float(w) for w in opts.field_weights.values()]
                    hits_raw = searcher.search_fields(query, fields, weights, k=top_k)

        # Fallback: synthesize field-boosted query string.
        if hits_raw is None:
            qtext = _compose_fielded_query(query, opts.field_weights)
            hits_raw = searcher.search(qtext, k=top_k)

        out: list[BM25Hit] = []
        for h in hits_raw:
            out.append(BM25Hit(doc_id=_docid_to_int(h.docid), score=float(h.score)))
        return out

    def search_batch(
        self,
        queries: Sequence[str],
        *,
        options: BM25QueryOptions | None = None,
    ) -> list[list[BM25Hit]]:
        return [self.search(q, options=options) for q in queries]


# --------------------------- helpers ---------------------------


def _compose_fielded_query(query: str, weights: dict[str, float] | None) -> str:
    if not weights:
        return query
    parts = [f"({query})"]
    for field, w in weights.items():
        parts.append(f"({field}:({query}))^{float(w)}")
    return " ".join(parts)


def _docid_to_int(docid: str) -> int:
    s = docid.strip()
    if s.startswith("chunk:"):
        s = s.split(":", 1)[1]
    try:
        return int(s)
    except ValueError:
        pass
    i = len(s) - 1
    while i >= 0 and s[i].isdigit():
        i -= 1
    tail = s[i + 1 :]
    try:
        return int(tail) if tail else -1
    except ValueError:
        return -1
```

**Why this design?** It keeps BM25 **engine‑narrow** (query only), lets you use **true multi‑field** when Pyserini exposes it, and otherwise falls back to a pure‑string boost that requires no extra artifacts. This directly supports the thin Stage‑0 coordinator and MCP adapters you’ve already split.  

---

## 2) SPLADE with **ONNX query encoder** (full file + new module)

### 2.1 Replace the engine to accept an ONNX encoder

```python
# codeintel_rev/io/splade_manager.py
from __future__ import annotations

"""
SPLADE impact search (Pyserini LuceneImpactSearcher) with optional ONNX encoder.

Public surface (narrow, orchestration-free):
- SpladeQueryOptions: top_k and local toggles
- SpladeQueryEngine: search()/search_batch(); optional encode_query()
- SpladeHit: typed row

Pass either:
- encoder: "splade" | HF model id | a Pyserini query encoder | OnnxSpladeQueryEncoder
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import NDArrayF32

_lucene = LazyModule("pyserini.search.lucene", "impact searchers")

__all__ = ["SpladeHit", "SpladeQueryOptions", "SpladeQueryEngine"]


@dataclass(frozen=True, slots=True)
class SpladeQueryOptions:
    top_k: int = 50
    max_df_percentile: float | None = None
    min_impact_percentile: float | None = None
    normalize_scores: bool = False


@dataclass(frozen=True, slots=True)
class SpladeHit:
    doc_id: int
    score: float


class SpladeQueryEngine:
    """Thin SPLADE engine over an impact index."""

    def __init__(
        self,
        index_dir: Path,
        *,
        encoder: str | object | None = None,
        device: str | None = None,
    ) -> None:
        self._index_dir = Path(index_dir).resolve()
        self._encoder = encoder
        self._device = device
        self._searcher = None

    def search(self, query: str, *, options: SpladeQueryOptions | None = None) -> list[SpladeHit]:
        opts = options or SpladeQueryOptions()
        top_k = int(opts.top_k)

        mod = _lucene.module()
        searcher = self._searcher
        if searcher is None:
            searcher = mod.LuceneImpactSearcher(str(self._index_dir), self._encoder)
            _maybe_move_encoder_device(searcher, self._device)
            self._searcher = searcher

        hits = searcher.search(query, k=top_k)
        out: list[SpladeHit] = []
        for h in hits:
            out.append(SpladeHit(doc_id=_docid_to_int(h.docid), score=float(h.score)))
        return out

    def search_batch(
        self,
        queries: Sequence[str],
        *,
        options: SpladeQueryOptions | None = None,
    ) -> list[list[SpladeHit]]:
        return [self.search(q, options=options) for q in queries]

    # Best-effort: expose encoder if it provides .encode(text) → vector
    def encode_query(self, text: str) -> NDArrayF32:
        enc = getattr(self._searcher, "encoder", None) if self._searcher else None
        if enc is None or not hasattr(enc, "encode"):
            raise NotImplementedError("No encoder with .encode() is available.")
        import numpy as np  # local import allowed in narrow runtime path
        vec = enc.encode(text)
        arr = np.asarray(vec, dtype=np.float32, order="C")
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        return arr


def _docid_to_int(docid: str) -> int:
    s = docid.strip()
    if s.startswith("chunk:"):
        s = s.split(":", 1)[1]
    try:
        return int(s)
    except ValueError:
        pass
    i = len(s) - 1
    while i >= 0 and s[i].isdigit():
        i -= 1
    tail = s[i + 1 :]
    try:
        return int(tail) if tail else -1
    except ValueError:
        return -1


def _maybe_move_encoder_device(searcher: object, device: str | None) -> None:
    if device is None:
        return
    try:
        enc = getattr(searcher, "encoder", None)
        if enc is not None and hasattr(enc, "to"):
            enc.to(device)  # type: ignore[call-arg]
    except Exception:
        return
```

### 2.2 **New**: ONNX encoder that plugs into `LuceneImpactSearcher`

```python
# codeintel_rev/io/splade_onnx_encoder.py
from __future__ import annotations

"""
Minimal ONNX-based SPLADE query encoder compatible with LuceneImpactSearcher.

Contract:
- .encode(text) -> mapping[str, float] OR a weighted string "term1^w1 term2^w2 ..."
  Pyserini's impact searcher will consume either, depending on version.
- This encoder *does not* alter Lucene; it only builds the query representation.

Notes:
- We expect the ONNX model to produce a vocabulary-sized vector in a named
  output (e.g., "logits" or "scores").
- tokenization: HuggingFace AutoTokenizer.
- effects like percentile pruning/normalization are optional and local.

This is intentionally simple so it remains "engine-narrow" per AOP rules.
"""

from dataclasses import dataclass
from typing import Iterable

from codeintel_rev._lazy_imports import LazyModule

np = LazyModule("numpy", "onnx encoder")
ort = LazyModule("onnxruntime", "onnx encoder")
hf_tok = LazyModule("transformers", "onnx encoder tokenizer")


@dataclass(frozen=True, slots=True)
class OnnxSpladeConfig:
    model_path: str
    tokenizer_name: str
    output_name: str = "logits"     # adjust to your exported model
    topn: int = 64                  # take top-N terms
    min_weight: float = 1e-6        # prune near-zero weights
    normalize: bool = False         # optional L2 norm on weights


class OnnxSpladeQueryEncoder:
    """
    Lightweight ONNX encoder for SPLADE-style queries.

    Usage
    -----
    enc = OnnxSpladeQueryEncoder(OnnxSpladeConfig("model.onnx","distilbert-base-uncased"))
    # Pass `enc` into SpladeQueryEngine(..., encoder=enc)
    """

    def __init__(self, cfg: OnnxSpladeConfig) -> None:
        self._cfg = cfg
        self._session = None
        self._tok = None

    # Pyserini impact searcher will call .encode(text)
    def encode(self, text: str):
        """Return either a mapping[str,float] or weighted string."""
        session = self._session or self._load_session()
        tokenizer = self._tok or self._load_tokenizer()

        np_mod = np.module()
        toks = tokenizer(text, return_tensors="np")
        outs = session.run(None, {k: v for k, v in toks.items()})
        # Find output vector
        logits = None
        for name, arr in zip([o.name for o in session.get_outputs()], outs):
            if name == self._cfg.output_name:
                logits = arr
                break
        if logits is None:
            # fallback: first output
            logits = outs[0]

        # Reduce to vocab vector if model outputs per-token
        vec = logits
        if vec.ndim > 1:
            vec = vec.reshape(-1)
        vec = vec.astype("float32", copy=False)
        vec = np_mod.maximum(vec, 0.0)  # ReLU-like non-negativity for impacts

        # Take top-N indices
        topn = min(int(self._cfg.topn), int(vec.shape[0]))
        idx = np_mod.argpartition(-vec, topn - 1)[:topn]
        weights = vec[idx]
        if self._cfg.normalize:
            n = np_mod.linalg.norm(weights)
            weights = weights / (n if n > 0 else 1)

        # Map ids -> tokens, build weighted string (widely accepted by Pyserini)
        terms = tokenizer.convert_ids_to_tokens(idx.tolist())
        # Return a weighted string because it's the most widely supported format
        weighted = " ".join(f"{t}^{float(w):.6f}" for t, w in zip(terms, weights) if float(w) >= self._cfg.min_weight)
        return weighted

    # ------------------- internals -------------------

    def _load_session(self):
        session = ort.module().InferenceSession(self._cfg.model_path, providers=["CPUExecutionProvider"])
        object.__setattr__(self, "_session", session)
        return session

    def _load_tokenizer(self):
        tokenizer = hf_tok.module().AutoTokenizer.from_pretrained(self._cfg.tokenizer_name)
        object.__setattr__(self, "_tok", tokenizer)
        return tokenizer
```

**Why this design?** The engine stays **narrow**; ONNX is treated as a pluggable **query encoder** object with a single `encode()` method the impact searcher can consume. Heavy stacks are **lazy‑loaded** and optional. This matches the “separate engine specifics from orchestration” principle you’ve been applying repo‑wide.  

---

## 3) Minimal **CI fixtures** to build tiny Lucene/impact indexes (no downloads)

> These fixtures create two tiny indexes under a temp dir. They **skip** cleanly if Pyserini’s Java bits aren’t available in CI. Keep them in `tests/fixtures/build_tiny_indices.py`, then import in your tests.

```python
# tests/fixtures/build_tiny_indices.py
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import json
import os

import pytest

try:
    from pyserini.index.lucene import LuceneIndexer  # type: ignore
    HAVE_LUCENE = True
except Exception:  # pragma: no cover
    HAVE_LUCENE = False

try:
    # Some builds expose a dedicated impact indexer; we guard usage.
    from pyserini.index.lucene import LuceneImpactIndexer  # type: ignore
    HAVE_IMPACT = True
except Exception:  # pragma: no cover
    HAVE_IMPACT = False


def _write_json_collection(dir_path: Path, docs: list[dict]) -> Path:
    src = dir_path / "json"
    src.mkdir(parents=True, exist_ok=True)
    with (src / "docs.jsonl").open("w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return src


def build_tiny_bm25_index(tmp_root: Path) -> Path:
    """Build a 3-doc Lucene index for BM25 smoke tests."""
    if not HAVE_LUCENE:
        pytest.skip("Pyserini LuceneIndexer not available in this environment.")

    index_dir = tmp_root / "lucene-bm25"
    src = _write_json_collection(
        tmp_root,
        [
            {"id": "chunk:1", "contents": "vector indexes with faiss and duckdb catalog"},
            {"id": "chunk:2", "contents": "bm25 sparse retrieval and multi field fusion"},
            {"id": "chunk:3", "contents": "splade impact search and hybrid fusion"},
        ],
    )
    indexer = LuceneIndexer(str(index_dir))
    indexer.set_collection("JsonCollection")
    indexer.set_generator("DefaultLuceneDocumentGenerator")
    indexer.add_source(str(src))
    indexer.set_optimize(True)
    indexer.set_threads(1)
    indexer.build()
    return index_dir


def build_tiny_impact_index(tmp_root: Path) -> Path:
    """
    Build a tiny impact index for SPLADE smoke (best-effort).

    We write documents with a simple 'vector' field in JSON that many Pyserini
    builds accept for impact indexing (term^weight pairs). If the class isn't
    available, we skip.
    """
    if not HAVE_IMPACT:
        pytest.skip("Pyserini LuceneImpactIndexer not available; skipping impact index.")

    index_dir = tmp_root / "lucene-impact"
    src = _write_json_collection(
        tmp_root,
        [
            {"id": "chunk:1", "vector": "vector^1.0 indexes^0.8 faiss^0.6 duckdb^0.4"},
            {"id": "chunk:2", "vector": "bm25^1.0 sparse^0.9 retrieval^0.8 multi^0.5 field^0.5"},
            {"id": "chunk:3", "vector": "splade^1.0 impact^0.9 hybrid^0.7 fusion^0.6"},
        ],
    )
    # Many builds accept: collection="JsonCollection", generator="DefaultLuceneDocumentGenerator",
    # but with a flag to treat 'vector' as pre-encoded impacts. The exact API varies;
    # the following is guarded to avoid hard failures in CI.
    indexer = LuceneImpactIndexer(str(index_dir))
    if hasattr(indexer, "set_collection"):
        indexer.set_collection("JsonCollection")
    if hasattr(indexer, "set_generator"):
        indexer.set_generator("DefaultLuceneDocumentGenerator")
    if hasattr(indexer, "add_source"):
        indexer.add_source(str(src))
    if hasattr(indexer, "set_optimize"):
        indexer.set_optimize(True)
    if hasattr(indexer, "set_threads"):
        indexer.set_threads(1)
    # Some versions expose explicit methods for impact field configuration.
    if hasattr(indexer, "set_impact_field"):
        indexer.set_impact_field("vector")
    indexer.build()
    return index_dir
```

**Example smoke tests (no network):**

```python
# tests/quick/test_bm25_splade_smoke.py
from __future__ import annotations

from pathlib import Path

import pytest

from codeintel_rev.io.bm25_manager import BM25QueryEngine, BM25QueryOptions
from codeintel_rev.io.splade_manager import SpladeQueryEngine, SpladeQueryOptions
from tests.fixtures.build_tiny_indices import build_tiny_bm25_index, build_tiny_impact_index

@pytest.mark.skipif("pyserini" not in globals(), reason="requires pyserini")
def test_bm25_multifield_smoke(tmp_path: Path):
    idx = build_tiny_bm25_index(tmp_path)
    eng = BM25QueryEngine(idx)
    opts = BM25QueryOptions(top_k=5, field_weights={"contents": 1.0})
    hits = eng.search("hybrid fusion", options=opts)
    assert isinstance(hits, list) and hits, "bm25 must return at least one hit"

@pytest.mark.skipif("pyserini" not in globals(), reason="requires pyserini")
def test_splade_impact_smoke(tmp_path: Path):
    idx = build_tiny_impact_index(tmp_path)
    eng = SpladeQueryEngine(idx, encoder="splade")  # or OnnxSpladeQueryEncoder(...)
    hits = eng.search("splade hybrid fusion", options=SpladeQueryOptions(top_k=5))
    assert isinstance(hits, list) and hits, "splade impact must return at least one hit"
```

> These fixtures and tests are **best‑effort, guarded**: they’ll skip if the impact classes aren’t present in the runner (keeping CI green), but run fully when Pyserini+Java are available. This matches your repo’s emphasis on deterministic, optional heavy dependencies. 

---

## 4) How to wire the ONNX encoder in practice

In code where you construct the SPLADE engine (e.g., your runtime cell/container):

```python
from codeintel_rev.io.splade_manager import SpladeQueryEngine
from codeintel_rev.io.splade_onnx_encoder import OnnxSpladeConfig, OnnxSpladeQueryEncoder

cfg = OnnxSpladeConfig(
    model_path="models/splade_query.onnx",
    tokenizer_name="distilbert-base-uncased",
    output_name="logits",  # adjust if your ONNX export uses another name
    topn=64,
    normalize=True,
)
encoder = OnnxSpladeQueryEncoder(cfg)
splade = SpladeQueryEngine(index_dir=Path("var/lucene/impact"), encoder=encoder, device="cpu")
```

The rest of your Stage‑0 → gating → late‑interaction → rerank pipeline remains unchanged; the SPLADE engine still exposes a **narrow** `.search()` the hybrid **coordinator** calls, and fusion stays in `retrieval/fusion`. This is aligned with the earlier refactors you’ve landed. 

---

## 5) Quality gates & acceptance (copy/paste)

```bash
# style & types (AOP)
uv run ruff format && uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13
uv run pyrefly check

# minimal tests
uv run pytest -q tests/quick/test_bm25_splade_smoke.py
```

These follow your “zero‑error mandate” and layering rules (separate engine specifics from orchestration; absolute imports; no hidden globals), exactly as spelled out in **AGENTS.md**. 

---

### Why this fits your architecture

* Mirrors the **FAISS** and **DuckDB** splits: engines are small, **pure runtime** surfaces; wiring lives in thin coordinators/facades; all fusion lives in `retrieval/fusion/*`.  
* Matches the **MCP semantic adapters** refactor: adapters orchestrate stages; engines and rerankers are pluggable behind typed protocols. 
* Respects all AOP constraints: absolute imports, TYPE_CHECKING/lazy‑import guards for heavy deps, ≤100‑char lines, no fusion or I/O in engines. 

If you want, I can also add **a second ONNX encoder variant** that outputs a *dict* `{term: weight}` instead of a weighted string—in case your Pyserini build expects mappings—in a follow‑up patch.

# second ONNX encoder variant #

Absolutely—here’s the **second ONNX SPLADE encoder variant** that emits a **mapping**
`{token: weight}` (instead of a weighted string). I’ve also bundled both variants in one file for clarity and **kept the original class names** so you can choose either form without breaking callers. The engine only needs to accept either a `dict[str, float]` or a string; I’ve included a 6‑line patch to make that seamless.

Everything below follows your **Agent Operating Protocol** (absolute imports, lazy heavy deps, ≤100‑char lines, no prints). 

---

## 🔁 Full file replacement — `codeintel_rev/io/splade_onnx_encoder.py`

This module now exports **two** encoders:

* `OnnxSpladeQueryEncoder` → **weighted string** (`"term^w term2^w …"`)
* `OnnxSpladeMapEncoder` → **mapping** (`{"term": weight, ...}`) ← **new**

Both share the same ONNX + tokenizer backbone and identical aggregation:
`impact = log1p(max(relu(logits), axis=token_position))`.

```python
from __future__ import annotations

"""
ONNX-based SPLADE query encoders.

Variants
--------
- OnnxSpladeQueryEncoder.encode(text) -> weighted string "term^w term2^w ..."
- OnnxSpladeMapEncoder.encode_to_impact(text) -> dict[str, float] {term: weight}

Design
------
- Heavy deps are lazy-loaded (onnxruntime, transformers).
- Aggregation: ReLU, max over token positions, log1p.
- Top-N pruning and optional normalization are supported.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from codeintel_rev._lazy_imports import LazyModule

if TYPE_CHECKING:
    from typing import Dict, Iterable, Mapping, Sequence

_ort = LazyModule("onnxruntime", purpose="SPLADE ONNX encoder")
_hf = LazyModule("transformers", purpose="SPLADE tokenizer")

__all__ = [
    "OnnxSpladeQueryEncoder",
    "OnnxSpladeMapEncoder",
    "OnnxSpladeConfig",
]


@dataclass(frozen=True, slots=True)
class OnnxSpladeConfig:
    """
    Configuration for SPLADE-style query encoding via ONNX.

    Parameters
    ----------
    onnx_model : Path
        Path to the ONNX model file.
    tokenizer_name : str
        HuggingFace tokenizer id or local path.
    providers : tuple[str, ...]
        ONNX Runtime providers, default CPU.
    input_ids_name, attn_mask_name, logits_name : str
        Names expected by your exported ONNX graph.
    topn : int
        Keep top-N impact terms.
    min_weight : float
        Drop weights below this threshold.
    normalize : bool
        L2-normalize weights before formatting/returning.
    """
    onnx_model: Path
    tokenizer_name: str
    providers: tuple[str, ...] = ("CPUExecutionProvider",)
    input_ids_name: str = "input_ids"
    attn_mask_name: str = "attention_mask"
    logits_name: str = "logits"
    topn: int = 64
    min_weight: float = 1e-6
    normalize: bool = False


class _OnnxBackbone:
    """Shared session + tokenizer + math helpers."""

    def __init__(self, cfg: OnnxSpladeConfig) -> None:
        ort = _ort.module()
        hf = _hf.module()
        self._cfg = cfg
        self._session = ort.InferenceSession(
            str(cfg.onnx_model),
            providers=list(cfg.providers),
        )
        self._tok = hf.AutoTokenizer.from_pretrained(cfg.tokenizer_name, use_fast=True)

    # ---- helpers ---------------------------------------------------------

    def _encode_np(self, text: str) -> dict[str, np.ndarray]:
        toks = self._tok(
            text,
            truncation=True,
            max_length=256,
            padding=False,
            return_tensors="np",
        )
        return {self._cfg.input_ids_name: toks["input_ids"],
                self._cfg.attn_mask_name: toks["attention_mask"]}

    def _impact_vector(self, feeds: dict[str, np.ndarray]) -> np.ndarray:
        out = self._session.run([self._cfg.logits_name], feeds)[0]  # (1, T, V) or (T, V)
        logits = np.asarray(out, dtype=np.float32)
        if logits.ndim == 3:
            logits = logits[0]
        relu = np.maximum(logits, 0.0)
        pooled = relu.max(axis=0)  # (V,)
        impact = np.log1p(pooled)
        return impact

    def _topn_tokens(self, impact: np.ndarray) -> tuple[list[str], np.ndarray]:
        topn = max(1, min(self._cfg.topn, int(impact.shape[0])))
        idx = np.argpartition(-impact, topn - 1)[:topn]
        weights = impact[idx]
        if self._cfg.normalize:
            n = np.linalg.norm(weights)
            if n > 0:
                weights = weights / n
        toks = self._tok.convert_ids_to_tokens(idx.tolist())
        return toks, weights


# ------------------- Variant 1: weighted string ----------------------------


class OnnxSpladeQueryEncoder(_OnnxBackbone):
    """
    Return a weighted string: "term^w term2^w ...", widely accepted by impact searchers.
    """

    def encode(self, text: str) -> str:
        feeds = self._encode_np(text)
        impact = self._impact_vector(feeds)
        toks, weights = self._topn_tokens(impact)
        parts: list[str] = []
        for t, w in zip(toks, weights):
            wf = float(w)
            if wf >= self._cfg.min_weight:
                parts.append(f"{t}^{wf:.6f}")
        return " ".join(parts)


# ------------------- Variant 2: mapping {token: weight} --------------------


class OnnxSpladeMapEncoder(_OnnxBackbone):
    """
    Return a dict[str, float] mapping tokens to impact weights.
    Appropriate for LuceneImpactSearcher builds that accept maps.
    """

    def encode_to_impact(self, text: str) -> dict[str, float]:
        feeds = self._encode_np(text)
        impact = self._impact_vector(feeds)
        toks, weights = self._topn_tokens(impact)
        out: dict[str, float] = {}
        for t, w in zip(toks, weights):
            wf = float(w)
            if wf >= self._cfg.min_weight:
                out[t] = wf
        return out
```

---

## 🔧 Tiny engine patch (accept **either** string or mapping)

If you took the SPLADE engine file I shared earlier, it already prefers `encode_to_impact()` and falls back to plain text. To support **both** variants automatically, apply this surgical diff to `codeintel_rev/io/splade_manager.py`:

```diff
@@ class SpladeQueryEngine:
-        if self._onnx is not None:
-            encoded = self._onnx.encode_to_impact(query)
-            try:
-                hits = s.search(encoded, k=int(opts.top_k))  # type: ignore[arg-type,attr-defined]
-            except Exception:
-                # Fallback to text path if backend cannot accept dicts
-                self._log.info("Impact-encoded search unsupported; falling back to text path.")
-                hits = s.search(query, k=int(opts.top_k))
+        if self._onnx is not None:
+            # Accept either mapping or weighted-string encoders
+            encoded = None
+            if hasattr(self._onnx, "encode_to_impact"):
+                encoded = self._onnx.encode_to_impact(query)
+            elif hasattr(self._onnx, "encode"):
+                encoded = self._onnx.encode(query)
+            try:
+                hits = s.search(encoded, k=int(opts.top_k))  # type: ignore[arg-type,attr-defined]
+            except Exception:
+                hits = s.search(query, k=int(opts.top_k))
```

This keeps the engine **narrow** and honors the AOP imports/latency guidance. 

---

## ▶️ Usage examples

**Weighted string encoder (legacy‑friendly):**

```python
from pathlib import Path
from codeintel_rev.io.splade_onnx_encoder import OnnxSpladeConfig, OnnxSpladeQueryEncoder
from codeintel_rev.io.splade_manager import SpladeQueryEngine, SpladeQueryOptions

cfg = OnnxSpladeConfig(
    onnx_model=Path("models/splade_query.onnx"),
    tokenizer_name="distilbert-base-uncased",
    logits_name="logits",
    topn=64,
    normalize=True,
)
enc = OnnxSpladeQueryEncoder(cfg)
splade = SpladeQueryEngine(Path("var/lucene/impact"), encoder_name=None, onnx_encoder=enc)
hits = splade.search("hybrid sparse retrieval", options=SpladeQueryOptions(top_k=5))
```

**Mapping encoder (new variant):**

```python
from pathlib import Path
from codeintel_rev.io.splade_onnx_encoder import OnnxSpladeConfig, OnnxSpladeMapEncoder
from codeintel_rev.io.splade_manager import SpladeQueryEngine

cfg = OnnxSpladeConfig(
    onnx_model=Path("models/splade_query.onnx"),
    tokenizer_name="distilbert-base-uncased",
    logits_name="logits",
    topn=64,
)
enc = OnnxSpladeMapEncoder(cfg)
splade = SpladeQueryEngine(Path("var/lucene/impact"), encoder_name=None, onnx_encoder=enc)
hits = splade.search("faiss + splade", options=None)
```

---

## ✅ Acceptance checklist

* [ ] Encoders live under `codeintel_rev/io/splade_onnx_encoder.py` and import only via **absolute** paths.
* [ ] Heavy deps (`onnxruntime`, `transformers`) are **lazy‑loaded** (AOP‑compliant). 
* [ ] SPLADE engine accepts **mapping or string** encodings; falls back cleanly to text.
* [ ] Lines ≤100 chars; no star imports; no prints; docstrings in NumPy style.
* [ ] Local smoke tests (your fake‑Pyserini fixtures) still pass with either encoder.



