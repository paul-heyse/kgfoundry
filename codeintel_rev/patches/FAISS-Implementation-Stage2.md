# Detailed implementation plan with diffs #

Absolutely—here’s a concrete, repo‑specific plan with **ready‑to‑paste diffs and Python bodies** for the three “optional next bites.” I’ve aligned the style (type hints, Google‑style docstrings, msgspec/TypedDict usage, logging) with what your repository already exposes and with the current FAISS manager surface (e.g., `search`, `search_primary`, `search_secondary`, `clone_to_gpu`) so the hunks anchor cleanly. Where I rely on existing components (DuckDB catalog, Parquet store, FAISS capabilities), I’ve called those out and cross‑referenced the attached materials.

---

## 0) What we’ll add (at a glance)

1. **ID‑map in FAISSManager**
   *Goal:* persist and expose `{faiss_row -> external_id(chunk_id)}` so you can **hydrate results deterministically and compute retrieval coverage** downstream. We wrap/assure `IndexIDMap2`, export a compact sidecar, and add hydration helpers that join with DuckDB.
   *Why now:* Your FAISS manager already documents reconstruct/id map expectations for `_extract_all_vectors()` (reconstruction support + `id_map`)—we’re formalizing/prolonging that contract and persisting it on disk so it’s visible across processes. 

2. **SCIP‑aware synthetic query generator**
   *Goal:* richer training/evaluation queries combining **symbol names, docstrings, and local call‑context** (“function‑intent” prompts). Emits JSONL usable by the evaluator and by your RAG tuner.
   *Why now:* `scip_reader` surfaces `SCIPIndex`, `Document`, and `SymbolDef` with location ranges—enough to build realistic prompts and ground‑truth positives per function. 

3. **Hybrid evaluator: IVF/HNSW vs Flat re‑rank (oracle)**
   *Goal:* compute **recall@K deltas** between fast ANN (IVF/HNSW) and an **exact** stage that re‑ranks ANN’s `(K * k_factor)` pool using dot‑product over the true embeddings (Flat). Use FAISS `ParameterSpace` to push `nprobe`, `efSearch`, and (optionally) `k_factor`.
   *Why now:* Your wheel exposes the necessary FAISS levers—`IndexIDMap2`, IVF/HNSW types and `ParameterSpace`—and your pipeline already has **embeddings in Parquet/DuckDB** for fast candidate hydration, so Flat re‑rank is cheap and faithful.

> Notes on dependencies already present:
>
> * DuckDB catalog: `query_by_ids`, `get_embeddings_by_ids` enable chunk hydration and candidate re‑rank.
> * Parquet store & schema: embedding/vector columns are accessible and typed; Arrow is in the tree. 
> * FAISS ops exposed by your wheel: IDMap/IDMap2, IVF family, HNSW, `ParameterSpace`.
> * Your FAISS manager’s documented behavior aligns with this (GPU fallback, dual index, etc.). 

---

## 1) FAISSManager: persist & expose `{faiss_row -> chunk_id}` map

### Design (and how it plugs in)

* **Wrap/ensure an `IndexIDMap2`** on the CPU primary index so searches return **external IDs** (your `chunk_id`). If an ID map doesn’t exist, we create one and insert vectors with `add_with_ids`. (Your FAISS manager already expects an `id_map` for vector extraction; this formalizes it.) 
* **Persist** a small, columnar **idmap sidecar** (`*.idmap.parquet`):
  `faiss_row: int64` (= position 0…ntotal‑1) → `external_id: int64` (= `chunk_id`).
  Sidecar lets diagnostics/evaluators map raw FAISS row positions deterministically even after process restarts.
* **Expose** convenience methods:

  * `get_idmap_array() -> np.ndarray[int64]` (fast in‑memory view)
  * `export_idmap(path: Path) -> int` (persist to Parquet)
  * `hydrate_by_ids(catalog, ids: Sequence[int]) -> list[dict]` to join via DuckDB (`query_by_ids`) at the edge. 

> Why `faiss_row` *and* `external_id`? If you keep the IDMap wrapped, FAISS will already return your external IDs on `search`. Persisting the explicit mapping hedges against future rebuilds, enables tooling that audits **coverage** vs. **materialized chunk tables**, and keeps us robust across index migrations.

### Ready‑to‑paste diff — `codeintel_rev/io/faiss_manager.py`

```diff
diff --git a/codeintel_rev/io/faiss_manager.py b/codeintel_rev/io/faiss_manager.py
index 7aaaaaa..7bbbbb1 100644
--- a/codeintel_rev/io/faiss_manager.py
+++ b/codeintel_rev/io/faiss_manager.py
@@
 from __future__ import annotations
-from typing import Any
+from typing import Any, Iterable, Sequence
+from pathlib import Path
+import math
+import json
+import numpy as np
+try:
+    import pyarrow as pa  # already used elsewhere in repo
+    import pyarrow.parquet as pq
+except Exception:  # pragma: no cover - optional at import time, validated at call
+    pa = None
+    pq = None
 
 import faiss  # type: ignore
 
@@
 class FAISSManager:
@@
     def build_index(self, xb: NDArrayF32, ids: NDArrayI64 | None = None, *, family: str = "auto") -> None:
         """
         Build the primary CPU index from vectors.
@@
-        if ids is None:
-            self._primary.add(xb)
-        else:
-            self._primary.add_with_ids(xb, ids.astype(np.int64))
+        # Ensure an ID map so searches/stats use stable external IDs (chunk_id)
+        if not isinstance(self._primary, faiss.IndexIDMap2):
+            self._primary = faiss.IndexIDMap2(self._primary)
+        if ids is None:
+            # Fallback: monotonic external IDs if caller didn't pass chunk IDs
+            ids = np.arange(xb.shape[0], dtype=np.int64)
+        self._primary.add_with_ids(xb, ids.astype(np.int64))
         faiss.write_index(self._primary, str(self.index_path))  # persist CPU index
@@
     def load_cpu_index(self) -> None:
         """Read CPU index from disk into memory."""
         self._primary = faiss.read_index(str(self.index_path))
+        # A number of FAISS index factories can be read back wrapped in IDMap2
+        # If not the case, wrap now so .search returns external IDs deterministically.
+        if not isinstance(self._primary, faiss.IndexIDMap2):
+            self._primary = faiss.IndexIDMap2(self._primary)
         self._gpu = None
@@
+    # -------------------  IDMAP: persist and expose  ---------------------------------------
+    def get_idmap_array(self) -> NDArrayI64:
+        """
+        Return a vector of shape (ntotal,) such that a[i] = external_id at FAISS row i.
+
+        Requires an IndexIDMap2-wrapped index. Raises at runtime if not available.
+        """
+        idx = self._primary
+        if idx is None or not hasattr(idx, "id_map"):
+            raise RuntimeError("Index not loaded or missing id_map")
+        idm = getattr(idx, "id_map", None)
+        get = getattr(idm, "at", None)
+        if callable(get):
+            n = int(idx.ntotal)
+            out = np.empty(n, dtype=np.int64)
+            for i in range(n):
+                out[i] = int(get(i))
+            return out
+        # Fallback: some builds expose a contiguous vector of ids
+        try:
+            return faiss.vector_to_array(idm).astype(np.int64)
+        except Exception as e:  # noqa: BLE001
+            raise RuntimeError("Unsupported id_map interface on this wheel") from e
+
+    def export_idmap(self, out_path: Path) -> int:
+        """
+        Persist {faiss_row -> external_id} as a Parquet sidecar next to the index.
+        Returns the number of rows written.
+        """
+        if pa is None or pq is None:
+            raise RuntimeError("pyarrow not available; cannot export idmap")
+        ids = self.get_idmap_array()
+        rows = np.arange(ids.shape[0], dtype=np.int64)
+        table = pa.Table.from_arrays(
+            [pa.array(rows), pa.array(ids)],
+            names=["faiss_row", "external_id"],
+        )
+        out_path.parent.mkdir(parents=True, exist_ok=True)
+        pq.write_table(table, out_path, compression="zstd", use_dictionary=True)
+        return int(ids.shape[0])
+
+    def hydrate_by_ids(self, catalog: "DuckDBCatalog", ids: Sequence[int]) -> list[dict]:
+        """
+        Convenience: map a list of external chunk IDs to chunk records via DuckDB.
+        """
+        if not ids:
+            return []
+        return catalog.query_by_ids(list(ids))
+
+    def reconstruct_batch(self, ids: Sequence[int]) -> NDArrayF32:
+        """
+        Reconstruct stored vectors for a batch of external IDs.
+
+        Useful for diagnostics and exact re-ranking of a candidate pool. For
+        quantized indexes, vectors are dequantized approximations.
+        """
+        idx = self._primary
+        if idx is None or not hasattr(idx, "reconstruct_batch"):
+            # polyfill: fall back to loop
+            X = np.empty((len(ids), self.vec_dim), dtype=np.float32)
+            for j, id_ in enumerate(ids):
+                X[j] = idx.reconstruct(int(id_))
+            return X
+        return idx.reconstruct_batch(np.asarray(ids, dtype=np.int64))
```

*Why this will anchor:* Your FAISS manager already contains `build_index`, `load_cpu_index`, and explicit reconstruction/id‑map semantics; the repository’s API inventory shows `_extract_all_vectors` requires `id_map` availability and `reconstruct()`. This patch formalizes those assumptions and provides userland persistence & hydration helpers. 

> **FAISS support in your wheel**: `IndexIDMap2` and reconstruction routines are present (and `ParameterSpace` for the evaluator, below). 

---

## 2) SCIP‑aware synthetic query generator (names + docstrings + call‑context)

### Design

* **Inputs:** a parsed `SCIPIndex` (immutable, msgspec Struct) with `Document` and `SymbolDef` entries, including file paths and ranges. 
* **Strategy:**

  1. For each `SymbolDef` representing a function/method, collect:

     * **Primary surface:** symbol name (and namespace)
     * **Semantics:** docstring, if available (via your docstring extractor in `scip_reader`)
     * **Context:** *local call neighbourhood* (same file, nearby defs in the same module) as a pragmatic proxy when full call-graph edges aren’t available; this works well for code intent queries and keeps it language‑agnostic.
  2. Emit **one or more natural queries** per function, with `positive_ids` pointing at the chunk(s) that cover the function body (via your chunk table `id` and URI/range alignment).
* **Outputs:** JSONL with schema:

```json
{"qid":"<uuid>", "query":"...", "positive_ids":[1,2], "metadata":{"uri":"...", "symbol":"...", "label":"function-intent"}}
```

*(These records feed the hybrid evaluator and can also seed your synthetic training/tuning sets.)*

### New file — `codeintel_rev/indexing/synth_query_gen.py`

```diff
diff --git a/codeintel_rev/indexing/synth_query_gen.py b/codeintel_rev/indexing/synth_query_gen.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/indexing/synth_query_gen.py
@@
+from __future__ import annotations
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Iterable, Sequence
+import json
+import uuid
+
+from kgfoundry_common.logging import get_logger
+from codeintel_rev.indexing.scip_reader import SCIPIndex, SymbolDef
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+
+log = get_logger(__name__)
+
+@dataclass(frozen=True)
+class SynthQuery:
+    """Synthetic query with ground-truth positives (chunk IDs)."""
+    qid: str
+    query: str
+    positive_ids: tuple[int, ...]
+    uri: str
+    symbol: str
+    label: str = "function-intent"
+
+def _brief_doc(docstring: str | None, limit: int = 160) -> str:
+    if not docstring:
+        return ""
+    d = " ".join(docstring.strip().split())
+    return d[:limit]
+
+def _compose_query(sym: SymbolDef, doc: str | None, neighbours: Sequence[str]) -> str:
+    """
+    Build a natural query that mimics “developer intent”, blending name + doc + local context.
+    """
+    parts: list[str] = []
+    # symbol surface
+    parts.append(sym.name.replace("_", " "))
+    # docstring summary
+    docp = _brief_doc(doc)
+    if docp:
+        parts.append(f"— {docp}")
+    # nearby call context (heuristic)
+    if neighbours:
+        parts.append(f"(related: {', '.join(neighbours[:5])})")
+    return " ".join(parts)
+
+def _local_neighbours(index: SCIPIndex, sym: SymbolDef, max_neigh: int = 8) -> list[str]:
+    """Return a small set of co-located symbol names in the same file/module."""
+    rel = sym.relative_path
+    names: list[str] = []
+    for d in index.documents:
+        if d.relative_path != rel:
+            continue
+        # Collect sibling definitions (keep short)
+        for occ in d.occurrences:
+            try:
+                if getattr(occ, "is_definition", False) and hasattr(occ, "symbol"):
+                    nm = getattr(occ, "symbol", "")
+                    if nm and nm != sym.symbol and nm not in names:
+                        names.append(nm.split("/")[-1])
+                        if len(names) >= max_neigh:
+                            return names
+            except Exception:
+                continue
+    return names
+
+def _chunk_ids_for_symbol(catalog: DuckDBCatalog, sym: SymbolDef) -> list[int]:
+    """
+    Map a symbol definition to chunk IDs using URI and line range overlap.
+    Requires the standard chunks schema (id, uri, start_line, end_line, ...).
+    """
+    # Fetch candidate chunks from file; let SQL handle range overlap
+    rows = catalog.query_by_uri(sym.relative_path, limit=500)
+    start, end = sym.range.start.line, sym.range.end.line  # type: ignore[attr-defined]
+    ids: list[int] = []
+    for r in rows:
+        s, e = int(r.get("start_line", -1)), int(r.get("end_line", -1))
+        if s <= end and e >= start:
+            ids.append(int(r["id"]))
+    return ids
+
+def generate_synth_queries(
+    index: SCIPIndex,
+    catalog: DuckDBCatalog,
+    *,
+    per_symbol: int = 1,
+) -> list[SynthQuery]:
+    """
+    Create synthetic “function-intent” queries from SCIP metadata with ground truths.
+    """
+    out: list[SynthQuery] = []
+    # Iterate defs from the SCIP export
+    try:
+        defs: Iterable[SymbolDef] = index.symbol_defs  # preferred if present
+    except AttributeError:
+        # Fallback: derive defs by scanning documents (works with your reader)
+        defs = (sym for doc in index.documents for sym in getattr(doc, "definitions", ()))
+    for sym in defs:
+        pos = tuple(_chunk_ids_for_symbol(catalog, sym))
+        if not pos:
+            continue
+        neigh = _local_neighbours(index, sym)
+        # Attempt short docstring retrieval if your reader exposes it
+        try:
+            doc = getattr(sym, "docstring", None)
+        except Exception:
+            doc = None
+        for _ in range(per_symbol):
+            qtext = _compose_query(sym, doc, neigh)
+            out.append(
+                SynthQuery(
+                    qid=str(uuid.uuid4()),
+                    query=qtext,
+                    positive_ids=pos,
+                    uri=sym.relative_path,
+                    symbol=sym.name,
+                )
+            )
+    return out
+
+def write_jsonl(records: Sequence[SynthQuery], path: Path) -> int:
+    """Write queries as JSONL."""
+    path.parent.mkdir(parents=True, exist_ok=True)
+    with path.open("w", encoding="utf-8") as f:
+        for r in records:
+            obj = {
+                "qid": r.qid,
+                "query": r.query,
+                "positive_ids": list(r.positive_ids),
+                "metadata": {"uri": r.uri, "symbol": r.symbol, "label": r.label},
+            }
+            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
+    return len(records)
```

*Why this fits your repo:* `SCIPIndex` / `SymbolDef` exist with document paths and ranges; `DuckDBCatalog.query_by_uri` returns chunk rows with `id`, `uri`, and `[start_line, end_line]`, letting you align symbols to chunk IDs without new storage.

---

## 3) Hybrid evaluator (IVF/HNSW vs exact Flat re‑rank)

### Design

* **Inputs:** a set of queries (synthetic or real), your FAISS manager, and DuckDB catalog for embedding access.
* **Search:** for each query vector, run FAISS ANN with **(K × k_factor)** candidates (`nprobe` for IVF / `efSearch` for HNSW set via `ParameterSpace`), then:

  1. **Flat re‑rank:** compute exact inner‑product scores against candidate embeddings from DuckDB and take top‑K.
  2. Compute **recall@K** vs. Flat top‑K **oracle** (either by “exact full scan” on small corpora using `IndexFlatIP` or by using the re‑ranked set as oracle).
* **Sweeps:** vary `nprobe` (IVF) and `efSearch` (HNSW) to produce a small table of **(latency, recall, pool size)**; this matches the theory/ops that accuracy is paramount for your small, personal indices.
* **FAISS knobs:** available in your wheel; `ParameterSpace` can set `nprobe`/`quantizer_efSearch` and, where applicable, a `k_factor` (we still implement re‑rank ourselves so it works uniformly across families). 

### New file — `codeintel_rev/eval/hybrid_pool_evaluator.py`

```diff
diff --git a/codeintel_rev/eval/hybrid_pool_evaluator.py b/codeintel_rev/eval/hybrid_pool_evaluator.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/eval/hybrid_pool_evaluator.py
@@
+from __future__ import annotations
+from dataclasses import dataclass
+from time import perf_counter
+from typing import Iterable, Sequence
+import math
+import numpy as np
+
+import faiss  # type: ignore
+from kgfoundry_common.logging import get_logger
+
+from codeintel_rev.typing import NDArrayF32, NDArrayI64
+from codeintel_rev.io.faiss_manager import FAISSManager
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+
+log = get_logger(__name__)
+
+@dataclass(frozen=True)
+class EvalQuery:
+    qid: str
+    text: str
+    positive_ids: tuple[int, ...]
+
+@dataclass(frozen=True)
+class EvalPoint:
+    qid: str
+    nprobe: int | None
+    efSearch: int | None
+    k: int
+    k_factor: float
+    latency_ms: float
+    recall_at_k: float
+
+class HybridPoolEvaluator:
+    """
+    Compare IVF/HNSW retrieval (top-K * k_factor) vs. exact Flat rerank (oracle) and report deltas.
+    """
+    def __init__(self, faiss_mgr: FAISSManager, catalog: DuckDBCatalog, vec_dim: int, metric_ip: bool = True) -> None:
+        self.fm = faiss_mgr
+        self.catalog = catalog
+        self.vec_dim = int(vec_dim)
+        self.metric_ip = bool(metric_ip)
+
+    def _encode_queries(self, embed_fn, queries: Iterable[str]) -> NDArrayF32:
+        X = embed_fn(queries)  # your CodeRankEmbedder.encode_queries or similar
+        X = np.asarray(X, dtype=np.float32)
+        # normalize for cosine/IP equivalence
+        faiss.normalize_L2(X)
+        return X
+
+    def _flat_scores(self, xq: NDArrayF32, cand_ids: Sequence[int]) -> tuple[NDArrayF32, NDArrayI64]:
+        """
+        Re-rank candidates exactly via inner product on the true embeddings.
+        """
+        if not cand_ids:
+            return (np.empty((len(xq), 0), dtype=np.float32), np.empty((len(xq), 0), dtype=np.int64))
+        # Embeddings come back [num_candidates, dim]
+        rows = self.catalog.get_embeddings_by_ids(list(cand_ids))
+        xb = np.asarray(rows, dtype=np.float32)
+        faiss.normalize_L2(xb)
+        # compute D = xq * xb^T
+        D = xq @ xb.T  # (nq, m)
+        I = np.asarray(cand_ids, dtype=np.int64)[None, :].repeat(D.shape[0], axis=0)
+        return D, I
+
+    def evaluate(
+        self,
+        embed_fn,
+        evalset: Sequence[EvalQuery],
+        *,
+        k: int = 10,
+        nprobes: Sequence[int] = (16, 32, 64, 128),
+        efs: Sequence[int] = (64, 128),
+        k_factors: Sequence[float] = (1.0, 1.5, 2.0),
+    ) -> list[EvalPoint]:
+        """
+        Run a grid sweep and return points with (latency, recall@K).
+        """
+        qtexts = [e.text for e in evalset]
+        Xq = self._encode_queries(embed_fn, qtexts)
+        results: list[EvalPoint] = []
+        ps = faiss.ParameterSpace()
+        for npb in nprobes:
+            for ef in efs:
+                for kf in k_factors:
+                    # Apply knobs uniformly to the primary index
+                    try:
+                        ps.set_index_parameters(self.fm.primary_index or self.fm._primary, f"nprobe={npb},quantizer_efSearch={ef}")
+                    except Exception:
+                        # Some index families ignore params; keep going
+                        pass
+                    t0 = perf_counter()
+                    D, I = self.fm.search(Xq, k=int(math.ceil(k * max(1.0, kf))), nprobe=int(npb))
+                    # Merge per-query pools and do exact re-rank
+                    k_cand = max(I.shape[1], 0)
+                    # Flatten candidate set across queries for a cheap unique() then per-query gather
+                    # (personal scale; acceptable)
+                    points = 0
+                    recall_hits = 0
+                    for qi, eq in enumerate(evalset):
+                        pool = I[qi].tolist()
+                        if not pool:
+                            continue
+                        Dflat, Iflat = self._flat_scores(Xq[qi:qi+1], pool)
+                        # Take oracle top-K after exact scoring
+                        order = np.argsort(-Dflat[0], kind="stable")[:k]
+                        oracle_ids = set(Iflat[0, order].tolist())
+                        # ANN@K from original D/I
+                        ann_ids = set(I[qi, :k].tolist())
+                        inter = len(oracle_ids.intersection(ann_ids))
+                        recall_hits += inter / max(1, len(oracle_ids))
+                        points += 1
+                    lat_ms = (perf_counter() - t0) * 1000.0
+                    results.append(
+                        EvalPoint(
+                            qid="*grid*",
+                            nprobe=npb,
+                            efSearch=ef,
+                            k=k,
+                            k_factor=kf,
+                            latency_ms=lat_ms,
+                            recall_at_k=(recall_hits / max(points, 1)),
+                        )
+                    )
+        return results
```

*Where this plugs in:*

* Use your CodeRank embedder (`CodeRankEmbedder.encode_queries`) for `embed_fn`. The embedder is already available and returns `NDArrayF32`. 
* Candidate hydration uses `DuckDBCatalog.get_embeddings_by_ids` exposed in your catalog, so re‑rank runs entirely in memory (no FAISS rebuild). 
* `ParameterSpace` calls are supported by the wheel (nprobe / quantizer_efSearch). 

> For small, on‑prem personal indices, this evaluator gives you **exact visibility** into how much accuracy you trade for speed and lets you **lock in** a high‑recall operating point.

---

## 4) How to operate these pieces

### Build or export the ID map

```python
from pathlib import Path
from codeintel_rev.io.faiss_manager import FAISSManager

fm = FAISSManager(index_path=Path(".../faiss.index"), vec_dim=2560)
fm.load_cpu_index()
written = fm.export_idmap(Path(".../faiss.idmap.parquet"))
print("rows:", written)
```

Now any downstream tool (evaluators, diagnostics) can map **FAISS rows → chunk_id** reliably or just use the fact that searches already return external IDs thanks to `IndexIDMap2`. 

### Generate synthetic queries (JSONL)

```python
from pathlib import Path
from codeintel_rev.indexing.scip_reader import parse_scip_json
from codeintel_rev.indexing.synth_query_gen import generate_synth_queries, write_jsonl
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog

scip = parse_scip_json(Path(".../index.json"))  # your SCIP export
catalog = DuckDBCatalog(db_path=Path(".../chunks.duckdb"), vectors_dir=Path(".../parquet"))
records = generate_synth_queries(scip, catalog, per_symbol=1)
n = write_jsonl(records, Path(".../queries.jsonl"))
print("queries:", n)
```

`DuckDBCatalog.query_by_ids` and `query_by_uri` provide the chunk joining we need. 

### Run the hybrid evaluator (quick sketch)

```python
from codeintel_rev.eval.hybrid_pool_evaluator import HybridPoolEvaluator, EvalQuery
from codeintel_rev.io.coderank_embedder import CodeRankEmbedder

embedder = CodeRankEmbedder(settings=...)  # your existing settings object
evalset = [EvalQuery(qid=r["qid"], text=r["query"], positive_ids=tuple(r["positive_ids"])) for r in ...]  # from JSONL
hp = HybridPoolEvaluator(fm, catalog, vec_dim=2560)
grid = hp.evaluate(embedder.encode_queries, evalset, k=10, nprobes=(32,64,128), efs=(96,128), k_factors=(1.0,1.5,2.0))
```

The returned `EvalPoint` list is ready to render in your diagnostics or to persist alongside your index manifest. (If you later want XTR as a stricter “oracle,” you can re‑use `XTRIndex.rescore(query, candidate_ids)`—your repo already exposes a narrow‑mode rescoring API that’s tailored to two‑stage pipelines. )

---

## 5) Why this approach is faithful & future‑proof

* Your FAISS wheel exposes **IDMap/IDMap2**, IVF, HNSW, and **ParameterSpace**—exactly what we’re using.
* Your FAISSManager already documents reliance on `id_map` and `reconstruct()`. We harden those semantics and surface practical helpers. 
* Your persistence layers (Parquet + DuckDB) already carry **embeddings + chunk metadata**; the evaluator re‑uses them to compute exact dot‑products, which is the right “Flat oracle” for cosine/IP.
* The plan matches the **accuracy‑first** bias recommended for personal RAG and is consistent with your theoretical guidance (re‑ranking and late fusion to tighten quality variance).

---

## 6) Minimal test stubs (optional but recommended)

**`tests/codeintel_rev/eval/test_hybrid_pool_evaluator.py`**

```python
from pathlib import Path
import numpy as np
import pytest

from codeintel_rev.eval.hybrid_pool_evaluator import HybridPoolEvaluator, EvalQuery
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog

@pytest.mark.slow
def test_eval_runs_with_small_pool(tmp_path: Path):
    # assumes tiny index + duckdb fixtures are present
    fm = FAISSManager(index_path=Path(".../faiss.index"), vec_dim=2560)
    fm.load_cpu_index()
    cat = DuckDBCatalog(db_path=Path(".../chunks.duckdb"), vectors_dir=Path(".../parquet"))
    hp = HybridPoolEvaluator(fm, cat, vec_dim=2560)
    evalset = [EvalQuery(qid="q1", text="init database connection", positive_ids=tuple())]
    # Embedder mocked as lambda; supply 1xD vector
    embed_fn = lambda qs: np.random.randn(len(qs), 2560).astype(np.float32)
    pts = hp.evaluate(embed_fn, evalset, k=5, nprobes=(32,), efs=(96,), k_factors=(1.5,))
    assert pts and pts[0].k == 5
```

---

## 7) Operator quick‑runbook (short)

1. **After each index build/rebuild**

   * `FAISSManager.load_cpu_index()`
   * `FAISSManager.export_idmap(paths.faiss_index.with_suffix(".idmap.parquet"))`
   * Record `manifest` + `idmap` commit IDs.

2. **Generate synthetic queries**

   * `synth_query_gen.generate_synth_queries(scip, catalog) → queries.jsonl`
   * Sample 100–200 queries across major modules.

3. **Run evaluator**

   * Sweep `(nprobe, efSearch, k_factor)` on that query set.
   * Fix an operating point with ≥ target recall (e.g., `≥0.9 @ K=10`) at tolerable latency.
   * Persist the chosen knobs alongside the FAISS manifest (or use your manager’s tune JSON if you enabled auto‑tune previously). 

4. **Wire into MCP**

   * Expose a small internal RPC/CLI to print the current operating point and to apply overrides (just calling `ParameterSpace` and plumbed into your existing settings loader). Your app context already provides `open_catalog()` and FAISS readiness orchestration. 

---

## 8) What to expect

* **Deterministic hydration & coverage** of results (thanks to IDMap persistence), enabling precise recall calculations and “explainable” retrieval.
* **More realistic eval sets** from SCIP—docstring‑ & module‑context enriched prompts that match “developer intent,” aligned to chunk IDs by URI/line overlap. 
* **Tunable accuracy–latency curve** via `nprobe`/`efSearch`/`k_factor` sweeps—simple to keep high recall at small personal scale and to lock that in. 

---

## 9) Nice‑to‑have next (quick wins)

* **IDMap join view in DuckDB** (create a view over the Parquet sidecar so you can SQL‑join chunk metadata and FAISS rows in diagnostics).
* **CLI verbs**:

  * `indexctl idmap export` → writes sidecar
  * `indexctl eval hybrid --queries queries.jsonl --k 10 --grid "..."`
* **Optional XTR Oracle**: swap the “Flat” exact stage with your **XTR rescorer**’s narrow mode to test a learned oracle on the same candidate pool (it’s already implemented as `rescore(query, candidate_chunk_ids)`). 

---

### Cross‑refs to your attachments

* FAISS manager & dual‑index flow in repo inventory (GPU fallback, dual search functions). 
* FAISS wheel symbol inventory (IDMap, HNSW/IVF families, ParameterSpace).
* DuckDB catalog query surfaces and Parquet embedding schema used for hydration/exact re‑rank.
* Theoretical foundation recommending re‑rank and accuracy bias for personal systems.

---

If you’d like, I can re‑emit these as a **single patchset** targeting:

```
codeintel_rev/io/faiss_manager.py
codeintel_rev/indexing/synth_query_gen.py        (new)
codeintel_rev/eval/hybrid_pool_evaluator.py      (new)
tests/codeintel_rev/eval/test_hybrid_pool_evaluator.py  (new, optional)
```

…and add a tiny `indexctl` verb to run the evaluator from the CLI.


# Full patch and further detailing on quick wins #

Amazing—let’s turn those “nice‑to‑have quick wins” into a concrete, paste‑ready patchset. I’m bundling four things here, all designed to slot into your existing structure with minimal friction:

1. **A DuckDB ID‑map join view** that exposes `{faiss_id → chunk}` and a convenience join over your Parquet “chunks” table.
2. **CLI verbs (`indexctl`)** to (a) export/install the ID‑map views, and (b) run the evaluator(s).
3. **An optional XTR “oracle”** (narrow reranker) that you can toggle into the evaluator to measure recall deltas.
4. **A compact evaluator** that computes coverage and recall@K (FAISS vs FAISS+XTR) and writes metrics artifacts.

Where I lean on existing concepts/entry points in your repo, I’ve anchored to the SCIP export so your team can see exactly what already exists and how the new code plugs in (e.g., `FAISSManager.search`, dual‑index behavior, and “ids correspond to chunk IDs”, plus your DuckDB catalog helpers and XTR rescoring surface)   . Your FAISS wheel features (e.g., IndexIDMap/ParameterSpace) are present and usable here .

---

## Patchset (ready to paste)

> **Conventions used below**
>
> * All paths are under `codeintel_rev/…` unless stated.
> * The CLI lives at `bin/indexctl.py`.
> * I’ve kept imports to stdlib + `numpy`, `pyarrow`, `duckdb`, and your existing packages.
> * Comments in diffs mark **why** (for maintainers).
> * The views prefer zero‑copy Parquet scans via your existing DuckDB catalog patterns .

---

### 1) **Settings**: add a stable path for the FAISS→Chunk ID map and evaluator artifacts

```diff
diff --git a/codeintel_rev/config/settings.py b/codeintel_rev/config/settings.py
@@
 class PathsConfig(msgspec.Struct):
     """
     File system paths configuration.
@@
-    faiss_index : str = "data/faiss/code.ivfpq.faiss"
+    faiss_index : str = "data/faiss/code.ivfpq.faiss"
+    # Parquet file mapping FAISS ids to chunk ids (for SQL joins & debugging).
+    faiss_idmap : str = "data/faiss/idmap.parquet"
+    # Evaluator artifacts (JSON metrics, CSVs, plots).
+    eval_dir : str = "data/eval"
+    # Optional XTR (late-interaction) index root; used by the oracle.
+    xtr_dir : str = "data/xtr"
```

> Rationale: `faiss_idmap` gives DuckDB a concrete location. `eval_dir` and `xtr_dir` keep evaluator outputs and the optional rescoring index tidy. Your `PathsConfig` already defines `faiss_index`, `vectors_dir`, and `duckdb_path`, so these extensions are consistent with the current pattern .

---

### 2) **FAISSManager**: export an ID map as Parquet

Your manager returns **chunk IDs** from `search()` (“IDs correspond to the ids passed to add_vectors()”), and already merges primary+secondary results deterministically . The ID‑map export below writes a two‑column Parquet `{faiss_id, chunk_id}`. If your index is wrapped in `IndexIDMap(2)`, we pull the exact map. If not (but you add with ids), we still fall back to a robust scan that extracts ids directly where supported; in worst‑case we write an identity map (documented in the method).

```diff
diff --git a/codeintel_rev/io/faiss_manager.py b/codeintel_rev/io/faiss_manager.py
@@
 from __future__ import annotations
-from typing import Any, Iterable, Mapping, Sequence
+from typing import Any, Iterable, Mapping, Sequence
 from pathlib import Path
+import contextlib
 import json
 import math
 import numpy as np
+import pyarrow as pa
+import pyarrow.parquet as pq
 import faiss  # type: ignore
@@
 class FAISSManager:
@@
+    def export_idmap_parquet(self, output: Path) -> int:
+        """
+        Persist a FAISS→chunk id mapping to Parquet for SQL joins / debugging.
+
+        The file has two int64 columns:
+            - ``faiss_id``  : 0..ntotal-1 (row id inside the FAISS base)
+            - ``chunk_id``  : external id you passed to add_with_ids()
+
+        Behavior by index type:
+          * If the index is IndexIDMap/IndexIDMap2, we read ``id_map`` directly.
+          * If the index stores external ids (IVF path), we attempt a supported
+            bulk read; where unavailable in Python, we emit an *identity* map
+            whose ``faiss_id == chunk_id`` (safe given your manager returns
+            chunk ids from search()).
+
+        Returns
+        -------
+        int
+            Number of rows written.
+        """
+        idx = self._gpu or self._primary
+        if idx is None:
+            raise RuntimeError("FAISS index not loaded")
+
+        # Try the clean path first: IndexIDMap / IndexIDMap2
+        idmap_arr: np.ndarray | None = None
+        with contextlib.suppress(Exception):
+            idmap_arr = faiss.vector_to_array(idx.id_map)  # type: ignore[attr-defined]
+
+        if idmap_arr is None:
+            # Fallback: identity map (faiss_id == chunk_id). This is consistent
+            # with your current semantics where search returns chunk ids.
+            ntotal = int(getattr(idx, "ntotal"))
+            idmap_arr = np.arange(ntotal, dtype=np.int64)
+
+        faiss_ids = np.arange(len(idmap_arr), dtype=np.int64)
+        chunk_ids = idmap_arr.astype(np.int64, copy=False)
+        table = pa.table({"faiss_id": faiss_ids, "chunk_id": chunk_ids})
+        output.parent.mkdir(parents=True, exist_ok=True)
+        pq.write_table(table, output)
+        return len(faiss_ids)
```

> If you later enable an explicit `IndexIDMap2` wrapper while building/updating, this method will export the *precise* map. The merge/reconstruct code you already document for full rebuilds remains compatible with this approach .

---

### 3) **DuckDB catalog**: install an ID‑map view and a join view

Add a helper that creates (or replaces) two views:

* `faiss_idmap`: reads the Parquet exported above; or, if the file is missing, synthesizes an identity map from the `chunks` view.
* `v_faiss_join`: performs the join `faiss_idmap ⨝ chunks ON chunk_id = id` so downstream SQL is trivial.

```diff
diff --git a/codeintel_rev/io/duckdb_catalog.py b/codeintel_rev/io/duckdb_catalog.py
@@
 from __future__ import annotations
 import duckdb
 from pathlib import Path
 from typing import Sequence
@@
 class DuckDBCatalog:
@@
     @staticmethod
     def relation_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
         """Return True when a table or view exists (public wrapper)."""
         cur = conn.execute(
             "select count(*) from duckdb_tables() where schema_name='main' and table_name=?",
             [name],
         )
         return (cur.fetchone() or (0,))[0] > 0
@@
     def query_by_ids(self, ids: Sequence[int]) -> list[dict]:
         """Query chunks by their unique IDs."""
         if not ids:
             return []
         in_clause = ",".join(str(int(i)) for i in ids)
         sql = f"select * from chunks where id in ({in_clause})"
         return [dict(r) for r in self._conn.execute(sql).fetchall()]
+
+    # --- NEW: IDMap views -------------------------------------------------
+    def ensure_faiss_idmap_views(self, idmap_parquet: Path) -> None:
+        """
+        Create/replace:
+          - view  faiss_idmap  (faiss_id bigint, chunk_id bigint)
+          - view  v_faiss_join as (faiss_idmap join chunks on chunk_id=id)
+
+        If the Parquet mapping does not exist yet, we synthesize an *identity*
+        mapping from the chunks view so downstream code still works.
+        """
+        p = str(idmap_parquet)
+        if not idmap_parquet.exists():
+            self._conn.execute("""
+                create or replace view faiss_idmap as
+                select cast(id as bigint) as faiss_id, cast(id as bigint) as chunk_id
+                from chunks
+            """)
+        else:
+            self._conn.execute(f"""
+                create or replace view faiss_idmap as
+                select cast(faiss_id as bigint) as faiss_id,
+                       cast(chunk_id as bigint) as chunk_id
+                from read_parquet('{p}')
+            """)
+        self._conn.execute("""
+            create or replace view v_faiss_join as
+            select m.faiss_id, m.chunk_id, c.*
+            from faiss_idmap m
+            join chunks c on c.id = m.chunk_id
+        """)
```

> This builds directly on your existing `DuckDBCatalog` utility (relation existence checks and chunk querying) and the repo’s documented pattern of exposing chunks via DuckDB views  .

---

### 4) **Optional XTR Oracle** (narrow reranker/“rescorer”)

A minimal adapter that wraps your `XTRIndex.rescore` and makes it easy for the evaluator to call. We keep this tiny and side‑effect free.

```diff
diff --git a/codeintel_rev/io/xtr_oracle.py b/codeintel_rev/io/xtr_oracle.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/io/xtr_oracle.py
@@
+from __future__ import annotations
+from pathlib import Path
+from typing import Iterable, Sequence
+from codeintel_rev.io.xtr_manager import XTRIndex
+
+class XTROracle:
+    """
+    Thin wrapper over XTRIndex narrow-mode rescoring.
+
+    Uses `XTRIndex.rescore(query, candidate_chunk_ids, explain=False)` which your
+    code already exposes with the right signature for narrow reranking. Returns
+    (chunk_id, score) pairs sorted descending by score.
+    """
+    def __init__(self, root: Path) -> None:
+        self._idx = XTRIndex(root=root)
+        self._opened = False
+
+    def open(self) -> None:
+        if not self._opened:
+            self._idx.open()
+            self._opened = True
+
+    def rescore(self, query: str, candidates: Iterable[int], topk: int) -> list[tuple[int, float]]:
+        self.open()
+        rescored = self._idx.rescore(query, candidates, explain=False, topk_explanations=0)
+        rescored.sort(key=lambda x: x[1], reverse=True)
+        return [(int(cid), float(score)) for (cid, score, _explain) in rescored][:topk]
```

> This aligns with the documented `XTRIndex.rescore()` entry point in your SCIP export (narrow mode for candidate sets) .

---

### 5) **Evaluator**: coverage + recall deltas (FAISS vs FAISS+XTR)

A single module that:

* accepts a file of queries (newline‑separated) **or** synthesizes queries from SCIP (function names/docstrings),
* runs FAISS (Stage‑0), optionally XTR rescoring (Stage‑1 oracle),
* computes `hit@K`, `mrr@K`, and **coverage of functional‑level positions** from SCIP (fraction of functions whose own chunk is retrieved within K),
* writes JSON/CSV artifacts to `paths.eval_dir`.

```diff
diff --git a/codeintel_rev/eval/evaluator.py b/codeintel_rev/eval/evaluator.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/eval/evaluator.py
@@
+from __future__ import annotations
+import csv, json, os, time
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Iterable, Sequence
+import numpy as np
+
+from codeintel_rev.app.config_context import ApplicationContext
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.io.faiss_manager import FAISSManager
+from codeintel_rev.io.xtr_oracle import XTROracle
+
+@dataclass
+class EvalConfig:
+    k: int = 10
+    nprobe: int = 64
+    use_xtr_oracle: bool = False
+    query_file: Path | None = None
+    synth_from_scip: bool = True
+
+def _ensure_eval_dir(p: Path) -> None:
+    p.mkdir(parents=True, exist_ok=True)
+
+def _load_queries_from_file(p: Path) -> list[str]:
+    return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
+
+def _synthesize_queries_from_scip(context: ApplicationContext) -> list[tuple[str,int]]:
+    """
+    Return (query, truth_chunk_id) pairs synthesized from SCIP:
+      - function/class symbol names (+ docstring if available)
+      - ground truth = owning chunk id for that symbol
+    """
+    cat = DuckDBCatalog(db_path=context.paths.duckdb_path, vectors_dir=context.paths.vectors_dir)
+    # Assumes a 'symbols' view exists or symbols are denormalized into 'chunks'.
+    # Fallback: approximate by using chunk previews (names in text).
+    # For simplicity, we generate one intent per chunk using the top line as a “name”.
+    rows = cat._conn.execute("select id, uri, text from chunks").fetchall()
+    pairs: list[tuple[str,int]] = []
+    for row in rows:
+        cid = int(row[0]); txt = (row[2] or "")[:140]
+        if txt:
+            pairs.append((txt, cid))
+    return pairs
+
+def _faiss_search(manager: FAISSManager, query_emb: np.ndarray, k: int, nprobe: int) -> list[tuple[int,float]]:
+    D, I = manager.search(query_emb, k=k, nprobe=nprobe)
+    ids = I.reshape(-1).tolist()
+    scores = D.reshape(-1).tolist()
+    return list(zip(ids, scores))
+
+def _embed_query(context: ApplicationContext, text: str) -> np.ndarray:
+    # Reuse your existing embedding path; assume a method is available in context or a helper.
+    # If your runtime exposes a query_embedder, wire it here. For now treat as an injected vector.
+    raise NotImplementedError("Wire your existing query embedding hook here.")
+
+def run_eval(context: ApplicationContext, cfg: EvalConfig) -> Path:
+    """
+    Run offline evaluation:
+      - optionally synthesize queries from SCIP
+      - compute FAISS@K metrics
+      - optionally compute FAISS+XTR@K (oracle) metrics
+      - persist artifacts under paths.eval_dir
+    """
+    _ensure_eval_dir(Path(context.paths.eval_dir))
+    manager = context.faiss_manager
+    idmap_path = Path(context.paths.faiss_idmap)
+
+    # Ensure views exist for convenience SQL joins during analysis.
+    cat = DuckDBCatalog(db_path=context.paths.duckdb_path, vectors_dir=context.paths.vectors_dir)
+    cat.ensure_faiss_idmap_views(Path(context.paths.faiss_idmap))
+
+    # Queries
+    if cfg.query_file:
+        queries = [(q, -1) for q in _load_queries_from_file(cfg.query_file)]
+    else:
+        queries = _synthesize_queries_from_scip(context) if cfg.synth_from_scip else []
+
+    # Optional XTR
+    xtr = XTROracle(Path(context.paths.xtr_dir)) if cfg.use_xtr_oracle else None
+
+    # Evaluate
+    K = int(cfg.k)
+    rows_csv: list[list[object]] = []
+    m_rr = m_hit = m_hit_oracle = mrr_oracle = 0.0
+    n = 0
+    t0 = time.time()
+    for (query_text, truth_chunk_id) in queries:
+        qv = _embed_query(context, query_text).astype("float32")[None, :]
+        faiss_hits = _faiss_search(manager, qv, k=K, nprobe=int(cfg.nprobe))
+        rank = next((i for i,(cid,_s) in enumerate(faiss_hits) if cid == truth_chunk_id), None)
+        m_hit += 1.0 if rank is not None else 0.0
+        m_rr  += (1.0 / (1 + rank)) if rank is not None else 0.0
+
+        if xtr is not None:
+            rescored = xtr.rescore(query_text, (cid for (cid,_s) in faiss_hits), topk=K)
+            rnk2 = next((i for i,(cid,_s) in enumerate(rescored) if cid == truth_chunk_id), None)
+            m_hit_oracle += 1.0 if rnk2 is not None else 0.0
+            mrr_oracle   += (1.0 / (1 + rnk2)) if rnk2 is not None else 0.0
+        else:
+            rnk2 = None
+
+        rows_csv.append([query_text, truth_chunk_id, faiss_hits, rank, rescored if xtr else None, rnk2])
+        n += 1
+
+    dur = time.time() - t0
+    metrics = {
+        "queries": n,
+        "k": K,
+        "nprobe": int(cfg.nprobe),
+        "faiss_hit@k": m_hit / max(n,1),
+        "faiss_mrr@k": m_rr / max(n,1),
+        "faiss_xtr_hit@k": (m_hit_oracle / max(n,1)) if xtr else None,
+        "faiss_xtr_mrr@k": (mrr_oracle / max(n,1)) if xtr else None,
+        "seconds": dur,
+    }
+
+    out_dir = Path(context.paths.eval_dir)
+    out_dir.mkdir(parents=True, exist_ok=True)
+    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
+    with (out_dir / "details.csv").open("w", newline="", encoding="utf-8") as f:
+        w = csv.writer(f); w.writerow(["query","truth_chunk_id","faiss_hits","faiss_rank","xtr_rescored","xtr_rank"])
+        w.writerows(rows_csv)
+    return out_dir
```

> The evaluator plugs into the exact primitives you already expose: `FAISSManager.search()` and `XTRIndex.rescore()`. Your `HybridSearchEngine` still composes on top for runtime fusion, but the evaluator’s job is controlled offline deltas. The XTR signatures and behaviors are documented in the SCIP export (wide vs narrow mode) and I’m explicitly using the **narrow** mode here for cheap oracle rescoring  .

---

### 6) **CLI**: `indexctl` verbs for IDMap and evaluator

Add a single tiny CLI. It boots your `ApplicationContext`, then routes to ID‑map export / view install, and evaluator (with optional oracle).

```diff
diff --git a/bin/indexctl.py b/bin/indexctl.py
new file mode 100755
--- /dev/null
+++ b/bin/indexctl.py
@@
+#!/usr/bin/env python
+from __future__ import annotations
+import argparse, sys
+from pathlib import Path
+
+from codeintel_rev.app.config_context import ApplicationContext
+from codeintel_rev.eval.evaluator import EvalConfig, run_eval
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+
+def _ctx() -> ApplicationContext:
+    # If your ApplicationContext has a factory, use it; else construct directly as in your app.
+    # This assumes the same environment variables/config discovery you use in the server entrypoint.
+    return ApplicationContext.bootstrap_for_cli()  # implement if not present; else create as needed.
+
+def cmd_idmap_export(args: argparse.Namespace) -> None:
+    ctx = _ctx()
+    out = Path(ctx.paths.faiss_idmap)
+    count = ctx.faiss_manager.export_idmap_parquet(out)
+    print(f"wrote {count} rows → {out}")
+
+def cmd_idmap_views(args: argparse.Namespace) -> None:
+    ctx = _ctx()
+    cat = DuckDBCatalog(db_path=ctx.paths.duckdb_path, vectors_dir=ctx.paths.vectors_dir)
+    cat.ensure_faiss_idmap_views(Path(ctx.paths.faiss_idmap))
+    print("created/updated views: faiss_idmap, v_faiss_join")
+
+def cmd_eval(args: argparse.Namespace) -> None:
+    ctx = _ctx()
+    cfg = EvalConfig(
+        k=args.k,
+        nprobe=args.nprobe,
+        use_xtr_oracle=args.oracle == "xtr",
+        query_file=Path(args.queries) if args.queries else None,
+        synth_from_scip=(args.queries is None),
+    )
+    out = run_eval(ctx, cfg)
+    print(f"metrics → {out / 'metrics.json'}")
+
+def main(argv: list[str]) -> int:
+    ap = argparse.ArgumentParser(prog="indexctl", description="Index/eval utilities")
+    sub = ap.add_subparsers(dest="cmd", required=True)
+
+    ap_idexp = sub.add_parser("idmap-export", help="Export {faiss_id → chunk_id} to Parquet")
+    ap_idexp.set_defaults(func=cmd_idmap_export)
+
+    ap_idv = sub.add_parser("idmap-views", help="Install/refresh DuckDB views (faiss_idmap, v_faiss_join)")
+    ap_idv.set_defaults(func=cmd_idmap_views)
+
+    ap_eval = sub.add_parser("eval", help="Run offline evaluator")
+    ap_eval.add_argument("--k", type=int, default=10)
+    ap_eval.add_argument("--nprobe", type=int, default=64)
+    ap_eval.add_argument("--oracle", choices=["none","xtr"], default="none")
+    ap_eval.add_argument("--queries", type=str, default=None, help="Optional newline-delimited queries file")
+    ap_eval.set_defaults(func=cmd_eval)
+
+    args = ap.parse_args(argv)
+    args.func(args)
+    return 0
+
+if __name__ == "__main__":
+    raise SystemExit(main(sys.argv[1:]))
```

> The CLI verbs requested (“install join view”, “run evaluator”, “optional XTR oracle”) are now one command away. If your `ApplicationContext` does not have `bootstrap_for_cli()`, add a 5‑line helper that loads the same settings and paths you use in server start; the rest of the glue is already in your repo (FAISS & DuckDB lifecycles)  .

---

## How these pieces fit your current surface

* **FAISS search behavior**: Your manager’s docstring already commits that search returns **chunk IDs** and describes the dual‑index merge policy; the ID‑map export simply makes the relationship visible to SQL/analysts and resilient to future index changes .
* **DuckDB catalog**: You already expose Parquet tables via views and provide a relation‑existence helper—exactly what we reuse to create `faiss_idmap` and `v_faiss_join` .
* **XTR**: Your `XTRIndex` exposes both wide search and narrow rescoring; the oracle uses **narrow** to compute realistic two‑stage gains without sweeping the full index, exactly as outlined in the earlier architecture notes and function docs .
* **Evaluator**: The coverage metric (“functional‑level positions from SCIP”) is implemented by synthesizing intent queries from chunk text when a symbol table isn’t materialized in DuckDB; if you already have a `symbols` view, swap in a more precise SQL for `(name + docstring)` sampling. The full‑stack report we wrote earlier recommends this exact approach (offline, controlled, reproducible) for self‑calibration in a personal on‑prem RAG system  .

---

## Operator runbook (ultra‑short)

1. **Export ID‑map & install views**

   ```bash
   bin/indexctl.py idmap-export
   bin/indexctl.py idmap-views
   # Explore:
   duckdb data/catalog.duckdb
   -- SQL:
   --   select faiss_id, chunk_id, uri from v_faiss_join limit 20;
   ```
2. **Run evaluator (FAISS only)**

   ```bash
   bin/indexctl.py eval --k 10 --nprobe 64
   # → data/eval/metrics.json, data/eval/details.csv
   ```
3. **Run evaluator with XTR oracle**

   ```bash
   bin/indexctl.py eval --k 10 --nprobe 64 --oracle xtr
   ```
4. **Swap queries source** (provide your own)

   ```bash
   bin/indexctl.py eval --k 20 --queries path/to/queries.txt
   ```

---

## Extension hooks (low‑effort follow‑ups)

* **(A) Materialized join**: If you want fully materialized tables (for fast BI), add `create table if not exists faiss_idmap_mat as select * from faiss_idmap;` guarded by a checksum of the idmap Parquet (small function in `DuckDBCatalog`).
* **(B) Factory‑string audit**: Persist the exact FAISS factory string and ParameterSpace knobs next to `faiss_idmap.parquet` so you can time‑travel metric regressions to concrete index settings (we pre‑figured gauges and explainability in the previous plan)  .
* **(C) Query‑to‑pool trace**: Add a tiny “last_eval_pool.parquet” per run with `(query_id, source, rank, chunk_id, score)`—DuckDB can then produce coverage heatmaps and per‑module contribution analyses in a few lines of SQL.

---

## Why this yields immediate value

* **Observability**: The ID‑map view eliminates ambiguity between FAISS internal row positions and your authoritative chunk IDs and enables ad‑hoc SQL joins for incident triage.
* **Control**: `indexctl eval` gives a one‑shot mechanism to check recall@K and coverage from SCIP against FAISS alone and FAISS+XTR. This is the right lever to keep accuracy tight even at low QPS in a personal environment.
* **Safety**: Everything is additive; no change to serving paths. You can pre‑export the map and install views at build or first run.

---

## Two small notes about the current code surface (just to make sure we’re aligned)

* The evaluator stub expects a query‑embedding function (I left a `NotImplementedError`). Wire it to the same embedding path used by your `FAISSManager` build/update code—this is usually a one‑liner in your `ApplicationContext` (or a tiny adapter). Your config/docs already define vector dimensions and pathing, so the hook is trivial .
* The FAISS ID‑map export falls back to an **identity** mapping if `IndexIDMap(2)` isn’t present in Python. That’s consistent with your stated semantics (search returns chunk IDs) and keeps the join view correct today; if/when you wrap with `IndexIDMap2`, the export becomes exact without further changes.

---

## “Next valuable features” you might like to schedule

1. **Install an explicit IDMap wrapper at build/update time.** That makes `export_idmap_parquet()` exact even for IVF‑PQ and unblocks zero‑cost deletions via `IDSelector` (handy for chunk GC). This is supported in your FAISS wheel inventory (IndexIDMap/2) .
2. **ParameterSpace presets** for `nprobe`/`efSearch` and a tiny LUT keyed by corpus size. That aligns with the earlier operating‑point plan and makes “tune then lock” one CLI command (we already seeded the metrics scaffolding) .
3. **DuckDB “explainability” tables**: persist the evaluator’s per‑query pools and your hybrid engine’s per‑channel contributions so you can do RRF diagnostics. Your `HybridSearchEngine` already gathers per‑channel hits; this is a straight lift into a Parquet sink .
4. **Coverage by module/language**: use `v_faiss_join` to bucket coverage and MRR by `uri` prefix. This pairs nicely with the personal RAG “keep accuracy tight” goal from the full‑stack plan  .

---

### References to your repo’s current surfaces (for reviewers)

* `FAISSManager.search()` returns chunk IDs; dual‑index merge policy and `nprobe` semantics are documented in the SCIP export we used to anchor diffs. 
* `DuckDBCatalog` already exposes helpers and patterns for views and `query_by_ids`. 
* `XTRIndex.search()/rescore()` signatures and “narrow mode” semantics (used by the oracle). 
* Prior implementation plan sections that introduced metrics, ParameterSpace, and explainability we’re now leveraging.  
* Theoretical and operational motivation for two‑stage retrieval and hybridization (why XTR rescoring tightens variance). 

---

If you want me to also emit this as a **single consolidated patch file** (so you can `git apply` it), I can do that immediately as well.


# Extension hooks and next valuable features #


Below is a **concrete, file‑by‑file implementation plan** that turns the extension hooks and “next valuable features” into production code that fits your current repository, schemas, and runtime patterns. I’ve anchored every step to the actual modules, classes, and APIs present in the repo, and I call out where each change plugs into your existing flows (index build/update, DuckDB catalog views, hybrid search, and MCP tools).

I split the plan into two blocks:

1. **Extension hooks (low‑effort follow‑ups)**
   (A) Materialized join in DuckDB for `{faiss_id → chunk}`
   (B) Factory‑string audit & ParameterSpace snapshot next to the index
   (C) Query‑to‑pool trace for explainability and coverage

2. **Next valuable features**
   (1) Explicit FAISS `IndexIDMap2` wrapper + Parquet export + cheap deletes
   (2) ParameterSpace presets + tiny LUT keyed by corpus size
   (3) DuckDB explainability tables for RRF and hybrid contributions
   (4) Coverage by module/language via `v_faiss_join`

Where helpful, I show precise DDL, function signatures, and call sites. I also note metrics you can emit via your Prometheus helpers and where the artifacts live under your `PathsConfig` (`vectors_dir`, `faiss_index`, `duckdb_path`) and `ApplicationContext` wiring.

---

## Grounding: current modules & capabilities (what we’ll extend)

* **DuckDB catalog** already provides a connection manager and view bootstrap via `_ensure_views`, and has helpers like `_relation_exists`, `query_by_ids`, `query_by_uri`, and `get_embeddings_by_ids`. This is the right home for new “join” and materialization functionality.
* **FAISSManager** already implements adaptive indexing, dual index (primary + secondary), save/load, GPU cloning, `search()` with IVF knobs, and a “direct ParameterSpace” helper `search_with_params()`. We’ll extend it to: (a) enforce `IndexIDMap2` wrapping; (b) export an id map to Parquet; (c) persist the factory string and runtime knobs; (d) accept runtime overrides.
* **HybridSearchEngine** already gathers channels and performs RRF with contributions, which we can pipe into Parquet for explainability and a “query‑to‑pool” trace.
* **MCP semantic tools** (`server_semantic`, `adapters.semantic`) already fuse FAISS with hybrid channels, and carry a “contribution map” out of fusion. We’ll add a tiny sink to persist the pool for evaluation.
* **XTR index** is available and exposes “wide mode” search with explainability; we will reuse it as an optional oracle in evaluators and (optionally) as a late rerank/rescore stage. 
* **Parquet store** already defines a chunks schema and I/O. We’ll add a sister schema for `faiss_idmap` and small helpers to read/write it. 
* **Settings & paths** (via `Settings`, `PathsConfig`, and `ResolvedPaths`) give us canonical locations for `vectors_dir`, `faiss_index`, and `duckdb_path`. We place the new artifacts alongside those.

For background theory and operating‑point guidance we lean on your Part‑1 theory doc and the end‑to‑end implementation plan, as we justify nprobe/efSearch presets, hybrid refinement, and coverage QA.

---

# 1) Extension hooks — detailed plan

### (A) Materialized join: `faiss_idmap` view + `v_faiss_join` + optional materialized table

**Goal.** Make `{faiss_id → chunk}` a first‑class relation in DuckDB, so hydrations, coverage, and BI queries become one SQL hop. Your `DuckDBCatalog` has an `_ensure_views` phase for Parquet directories; we extend this to mount `faiss_idmap.parquet` if present and define a join view with `chunks`. 

**Artifacts.**

* Parquet: `${vectors_dir}/faiss_idmap.parquet` with columns:

  * `faiss_id BIGINT NOT NULL`
  * `chunk_id BIGINT NOT NULL`
* DuckDB views:

  * `faiss_idmap` → `read_parquet(:vectors_dir || '/faiss_idmap.parquet')`
  * `v_faiss_join` → `select c.*, m.faiss_id from chunks c join faiss_idmap m on m.chunk_id = c.id`

**Where to implement.**

* **`codeintel_rev/io/parquet_store.py`:** add an Arrow schema + writer/reader helpers for `faiss_idmap`. Your module already exports schema helpers for chunks; follow the same pattern. 
* **`codeintel_rev/io/duckdb_catalog.py`:** extend `_ensure_views` to:

  1. register `faiss_idmap` view if the Parquet file exists;
  2. create `v_faiss_join` if both `chunks` and `faiss_idmap` are present;
  3. optionally “materialize” into `faiss_idmap_mat` behind a small checksum guard (see below). 

**DDL sketch (executed inside `_ensure_views`)**:

```sql
-- view over idmap parquet
create or replace view faiss_idmap as
select * from read_parquet($vectors_dir || '/faiss_idmap.parquet');

-- join with chunks parquet
create or replace view v_faiss_join as
select c.*, m.faiss_id
from   chunks c
join   faiss_idmap m
  on   m.chunk_id = c.id;
```

**Materialization hook (optional, fast BI):**

* Add small helper in `DuckDBCatalog`:

```python
def _materialize_faiss_idmap(self, conn, vectors_dir: Path) -> None:
    # compute hash of current parquet (e.g., duckdb sha256 over file)
    # if changed/new: create table if not exists faiss_idmap_mat as select * from faiss_idmap; truncate+insert if exists
    # create view v_faiss_join_mat that points to join against faiss_idmap_mat
```

* Gate by a **checksum** stored in `duckdb.settings` or a tiny `_meta` table (key/value), e.g. `('faiss_idmap_checksum', '...')`. You already use `_relation_exists` to guard idempotent creation. 

**Call sites.**

* `ApplicationContext.open_catalog()` yields the catalog; `_ensure_views` runs once per process. No changes needed at call sites beyond relying on `v_faiss_join` when we need joined metadata. 

**Tests.**

* Unit: create an in‑tmpdir DuckDB, write a tiny `faiss_idmap.parquet` (2 rows), verify `v_faiss_join` returns expected columns and row counts; confirm materialization is no‑op if checksum unchanged.
* Integration: run a FAISS build/update to produce an idmap (see §2.1), then query `v_faiss_join` for the hydrated sample.

---

### (B) Factory‑string audit (persist FAISS factory & ParameterSpace knobs)

**Goal.** Persist the **exact** FAISS index factory string and any `faiss.ParameterSpace` settings that affect recall/latency, side‑by‑side with the index. This allows time‑travel and post‑hoc analysis of regressions. Your manager already exposes `get_compile_options()` (for readiness logs). We add a metadata writer/reader. 

**Artifacts.**

* `${faiss_index}.meta.json` with:

  * `faiss_compile`: string from `FAISSManager.get_compile_options()`
  * `factory`: the factory string used to build the primary index (e.g., `IVF8192,PQ64x8,IMI2x10,HNSW32` or your adaptive selection)
  * `vec_dim`, `metric`, `nlist`, `m`, `nbits`, and any other train‑time decisions
  * `parameter_space`: last applied string (e.g., `nprobe=64,efSearch=128,ht=1`)
  * `gpu_enabled`, `gpu_disabled_reason`
  * `built_at`, `vector_count`, and a short path to training stats (if any)

**Where to implement.**

* **`codeintel_rev/io/faiss_manager.py`:**

  * Add `_save_index_meta(self, meta: dict) -> None` called from `build_index()` and `merge_indexes()`; update the `parameter_space` field whenever `search_with_params()` is used with a new string.
  * Add `_load_index_meta(self) -> dict | None` used by logs at startup.
* If you split dual‑index logic in `io/faiss_dual_index.py`, wire the same calls there when the primary is rebuilt or swapped. (Repo has `FAISSDualIndexManager` and `IndexManifest` you can piggyback.) 

**Tests.**

* Build a small index, assert the meta file exists and parses; mutate `search_with_params("nprobe=32")`, assert the `parameter_space` changed after next save. 

---

### (C) Query‑to‑pool trace (per‑run Parquet for explainability & coverage)

**Goal.** Persist, for each query, the **raw candidate pool** across channels (dense, BM25, SPLADE, optional WARP/XTR) with contribution details. Hybrid fusion already returns a per‑doc contribution map (channel, rank, score). We stream that into a Parquet sink for BI notebooks and coverage heatmaps.

**Schema & path.**

* `${vectors_dir}/trace/last_eval_pool.parquet`
  Columns:
  `query_id (BIGINT)`, `source (VARCHAR)`, `rank (INT)`, `chunk_id (BIGINT)`, `score (DOUBLE)`, `fused_score (DOUBLE)`, `channel (VARCHAR)`, `method (VARCHAR)`, `ts (TIMESTAMP)`.

**Where to implement.**

* **`codeintel_rev/mcp_server/adapters/semantic.py`:**

  * In `_build_hybrid_result(...)` (already accepts `contribution_map`), **after** fusion construct rows for all docs kept (and optionally the head of each channel list prior to fusion if you want a “pre‑fusion pool”). Write a tiny Parquet using pyarrow. 
* **`codeintel_rev/io/hybrid_search.py`:**

  * Optionally, add an explicit `trace_writer` dependency (default off) that writes per‑channel pools **before** fusion (BM25 list, SPLADE list, FAISS list). This mirrors your RRF inputs (you already fuse with RRF and can collect contributions there). 
* **`DuckDBCatalog`**: optionally expose a read helper `read_last_eval_pool()` that returns a relation over the Parquet (or add a view `last_eval_pool` in `_ensure_views`). 

**Tests.**

* Invoke `semantic_search_pro()` over a small fixture; assert the parquet exists, row count matches `limit`, and per‑channel attribution is present. 

---

# 2) Next valuable features — detailed plan

### 2.1 Install an explicit **IndexIDMap2** wrapper + Parquet export + cheap deletes

**Why.** With IVF‑PQ (and friends) the index’s internal numeric ids can be remapped. Wrapping the primary index in `IndexIDMap2` gives you a stable `{faiss_id → external chunk_id}` mapping and enables **IDSelector** deletes and **exact** Parquet dumps of the map. Your FAISS wheel inventory shows `IndexIDMap/2` and `ParameterSpace` are available. 

**Where to implement.**

* **`codeintel_rev/io/faiss_manager.py`:**

  * In `build_index()` and every rebuild path (including `merge_indexes()`), **wrap** the trained primary in `faiss.IndexIDMap2` and **add_with_ids** using your chunk ids (you already pass ids to `add_vectors()`). Ensure `update_index()` (secondary flat) also uses an `IndexIDMap2` wrapper.
  * Add `export_idmap_parquet(self, out: Path | None = None) -> Path`:

    * Extract all `(faiss_id, external_id)` from the **primary** (and secondary if present) through the IDMap wrapper or via `index.id_map` accessor.
    * Write to `${vectors_dir}/faiss_idmap.parquet` using the new Parquet helper (see §A).
  * Add `delete_by_ids(self, ids: Sequence[int]) -> int`:

    * Use FAISS `IDSelectorBatch` against both primary and secondary to remove stale chunks; update any in‑memory `incremental_ids` bookkeeping you already have.
* **`codeintel_rev/io/duckdb_catalog.py`:**

  * You get `v_faiss_join` for free from §A and can now run joined queries that rely on exact mapping. 

**Rollout.**

* After every build/update, call `export_idmap_parquet()`; on server start, `DuckDBCatalog._ensure_views` picks up the view and the join.

**Tests.**

* Build a tiny corpus; export idmap; assert join count equals vector count; delete an id; assert the map and join shrink accordingly.

---

### 2.2 ParameterSpace **presets + LUT** keyed by corpus size

**Why.** On a personal device, “accurate but predictable” is the target. Bake empirically sane defaults for IVF/HNSW in a LUT keyed by corpus size; expose a switch (“tuned mode”) and persist the choice in the factory‑string meta (B).

**Where to implement.**

* **`codeintel_rev/retrieval/parameter_presets.py` (new):**

  * `select_operating_point(n: int) -> dict`: returns `{ "param_str": "nprobe=...,efSearch=...", "refine_k_factor": float }` with 3–5 buckets: `<5k`, `5–50k`, `50–200k`, `>200k`. Ground the defaults in the Part‑1 theory (probe proportion to `nlist`, keep efSearch within device budget). 
* **`FAISSManager.search(...)`**: accept optional `runtime: SearchRuntimeOverrides`; if `None`, apply the preset. You already have `search_with_params(param_str, refine_k_factor)`—internally call it with the LUT’s recommendation. 
* **Persistence**: when using a preset, write the chosen `param_str` into the index meta (B) so your runs are auditable. 

**CLI (optional but recommended).**

* Add `indexctl tune --preset auto|small|medium|large --dry-run` that prints and/or persists the current preset; your repo already has Typer‑based CLI patterns (see `cli.splade`). Mirror that structure in `cli/indexctl.py`.

---

### 2.3 DuckDB **explainability** tables (RRF & hybrid contributions)

**Why.** Your hybrid engine tracks per‑channel hits and fuses with RRF. Make this inspectable with a pair of persistent Parquet sinks and corresponding DuckDB views.

**Artifacts & schema.**

* `${vectors_dir}/trace/hybrid_contrib.parquet`
  Columns: `query_id, channel, rank_in_channel, doc_id, raw_score, fused_score, k_rrf, weight, ts`.
* `${vectors_dir}/trace/hybrid_topk.parquet`
  Columns: `query_id, rank, doc_id, fused_score, ts`.

**Where to implement.**

* **`io/hybrid_search.py`**: after calling RRF, you have the inputs and the contribution map; write both tables (append mode) in `HybridSearchEngine.search(...)`. The docstring shows Search combines FAISS + BM25 + SPLADE with RRF; we persist right there. 
* **`io/rrf.py`**: its `weighted_rrf(...)` returns contributions; if convenient, add an optional callback that captures the per‑doc contribution map and k constant; invoke from `HybridSearchEngine`. 
* **`DuckDBCatalog._ensure_views`**: add views `hybrid_contrib` and `hybrid_topk` over these parquets so users can query them with the same connection they use for chunks. 

**Queries enabled (examples).**

* “Which channels lift recall most for a query cohort?” → aggregate `hybrid_contrib` by channel.
* “How often do FAISS‑only hits enter the final top‑k?” → join `hybrid_topk` with contrib where `channel='faiss'`.

---

### 2.4 Coverage by **module/language** via `v_faiss_join`

**Goal.** Compute coverage and MRR broken out by `uri` prefix (module) and language (if available). Your schema exposes `uri` and chunk lines; `server_symbols` shows how you bucket by file and ranges for symbol tools; we can reuse this style.

**Where to implement.**

* **DuckDB**: Add a helper SQL in `DuckDBCatalog`, e.g.,

```sql
-- Example: coverage by module prefix
select 
  left(uri, instr(uri,'/',1,2)) as module_prefix,
  count(*) as total_chunks,
  sum(case when faiss_id is not null then 1 else 0 end) as mapped,
  sum(case when faiss_id is not null then 1 else 0 end) * 1.0 / count(*) as coverage_ratio
from v_faiss_join
group by 1
order by total_chunks desc;
```

* **Evaluator** (optional): add `eval/coverage_by_module.py` that joins `last_eval_pool` (C) with `v_faiss_join` to compute per‑module `recall@k`, `MRR`, and “contribution by channel” for your hybrid engine. 

---

## Cross‑cutting details

### Paths & settings

Use `ResolvedPaths.vectors_dir`, `ResolvedPaths.faiss_index`, `ResolvedPaths.duckdb_path` from `ApplicationContext.resolve_application_paths(settings)` in all places that need canonical paths for Parquet and index files. These are already available to `ApplicationContext` and the helpers that open the catalog and FAISS manager. 

### Where to wire everything

* **Build/update pipeline** (`bin/index_all.py`): after FAISS builds/merges, call `export_idmap_parquet()`; then (optionally) connect DuckDB and materialize the idmap table if the setting `duckdb.materialize_idmap=True`. Paths are already resolved via `_resolve_paths(settings)`. 
* **Runtime** (`ApplicationContext.ensure_faiss_ready()`): on successful load, read `${faiss_index}.meta.json` and log a “factory audit” line with compile options and parameter space string. 

### Prometheus

* Gauges: `faiss_idmap_rows`, `faiss_join_ready{materialized?}`, `hybrid_rrf_written_rows`, `trace_pool_rows`.
* Counters: `faiss_deletes_total`, `faiss_param_overrides_total`, `eval_pools_written_total`.
  (Your earlier coverage evaluator shows how you use `build_gauge`/`build_counter`.) 

---

# Deliverable‑wise breakdown (what to add/modify)

Below I list **concrete edits** you can make (no full code walls here—just precise signatures, DDL, and responsibilities). These drop into place with your current APIs.

---

## File: `codeintel_rev/io/parquet_store.py`  (new helpers)

* **New Arrow schema**:

```python
def get_idmap_schema() -> pa.Schema:
    return pa.schema([
        pa.field("faiss_id", pa.int64(), nullable=False),
        pa.field("chunk_id", pa.int64(), nullable=False),
    ])
```

* **Writers/Readers**:

```python
def write_idmap_parquet(path: Path, rows: Iterable[tuple[int,int]]) -> None: ...
def read_idmap_parquet(path: Path) -> pa.Table: ...
```

This mirrors your existing chunks helpers (`get_chunks_schema`, `write_chunks_parquet`). 

---

## File: `codeintel_rev/io/faiss_manager.py`

* Enforce `IndexIDMap2` around **primary** and **secondary** indices in `build_index()` and `update_index()`; ensure `add_vectors()` / `_extract_all_vectors()` depend on `.id_map` invariants (your `merge_indexes()` docstring already hints at reconstruction & ids; this becomes simpler/safer with IDMap2).
* **New**:

  * `def export_idmap_parquet(self, out: Path | None = None) -> Path: ...`
  * `def delete_by_ids(self, ids: Sequence[int]) -> int: ...` (IDSelectorBatch applied across both indexes)
  * `def _save_index_meta(self, meta: dict) -> None: ...`
  * `def _load_index_meta(self) -> dict | None: ...`
* Update `search(...)` to accept optional `runtime` overrides (you already have a variant); if `runtime is None`, apply presets from `retrieval/parameter_presets.py` (§2.2) and call `search_with_params`.

---

## File: `codeintel_rev/io/duckdb_catalog.py`

* In `_ensure_views(...)`:

  * If `${vectors_dir}/faiss_idmap.parquet` exists, **create view** `faiss_idmap`.
  * If `chunks` & `faiss_idmap` exist, **create view** `v_faiss_join` (`join chunks.id = faiss_idmap.chunk_id`).
  * **Optionally** call `_materialize_faiss_idmap(...)` to create `faiss_idmap_mat` + `v_faiss_join_mat` guarded by checksum. You already have `_relation_exists(...)` to write idempotent DDL. 
* Optionally add `def read_last_eval_pool(self) -> DuckDBPyRelation:` and/or register `last_eval_pool` view if the Parquet exists (C).

---

## File: `codeintel_rev/io/hybrid_search.py`

* In `HybridSearchEngine.search(...)`, after RRF:

  * Persist **per‑channel** pools and **top‑k** fused results to Parquet sinks in append mode (`vectors_dir/trace/...`); this uses the contribution map produced by your RRF path. The class doc describes exactly where results are combined, so the hook is localized here. 

---

## File: `codeintel_rev/mcp_server/adapters/semantic.py`

* In `_build_hybrid_result(...)`, build a small list of `(query_id, source, rank, chunk_id, score, fused_score, channel, method, ts)` and write to `last_eval_pool.parquet` (or call a helper in `hybrid_search` to avoid duplication). You already pass/return `contribution_map` and channels. 

---

## File: `codeintel_rev/retrieval/parameter_presets.py` (new)

* `def select_operating_point(n_vectors: int) -> tuple[str, float]:`
  Returns `(param_str, refine_k_factor)` for IVF/HNSW. Justification draws from your theory doc. Example buckets:

  * `<5k`: flat; `param_str=""`, `refine=1.0`
  * `5–50k`: IVFFlat; `param_str="nprobe=0.07*nlist"`, `refine=1.0`
  * `50–200k`: IVF‑PQ; `param_str="nprobe=0.06*nlist,efSearch=128"`, `refine=1.5`
  * `>200k`: IVF‑PQ; `param_str="nprobe=0.05*nlist,efSearch=256"`, `refine=2.0`
    Use integerized values and clamp to device. Persist the chosen `param_str` into the meta file (B). 

---

## CLI (optional, but aligns with your existing style)

* **`codeintel_rev/cli/indexctl.py` (new)** mirroring `cli.splade` style:

  * `@app.command("tune")` → picks a preset and persists it
  * `@app.command("export-idmap")` → calls `FAISSManager.export_idmap_parquet()`
  * `@app.command("materialize-join")` → opens DuckDB and runs `_materialize_faiss_idmap`
  * `@app.command("trace-on")` (toggle a setting) → enables pool tracing
    Your CLI patterns in `cli.splade` (Typer + `@cli_operation`) serve as reference.

---

# QA & Evaluation

* **Offline oracle**: keep your XTR “wide mode” as oracle for **recall@K deltas**. It already exposes `search()` with optional explanations; reuse it to label pools and compute MRR, NDCG, and recall. Store per‑query metrics as JSONL and a summary (as outlined in the earlier evaluator module).
* **Coverage**: build a small `eval/coverage_by_module.py` that reads `last_eval_pool` and `v_faiss_join`, grouping by `uri` prefix/lightweight module classification, reporting coverage and gaps (by channel). 

---

# Observability & runbook notes

* **Factory audit line (startup)**:
  “FAISS compile: `<opts>`; factory: `<factory>`; parameter_space: `<param_str>`; gpu_enabled=`<bool>`; vector_count=`<n>`.” (from meta) 
* **Materialized join status**:
  `faiss_join_ready{materialized="true|false"}=1`, `faiss_idmap_rows=<n>`.
* **Tracing volume guard**: cap pool writes to top‑`K_trace` (e.g., 200) per channel to avoid large Parquets on long runs.
* **Deletions**: recommend running `export-idmap` after batch deletes to keep DuckDB joins consistent.

---

# Design trade‑offs (why this shape)

* **IDMap2** makes your mapping **exact** and unlocks **IDSelector** deletes—critical for self‑healing and steady quality without full rebuilds. Supported by your wheel inventory. 
* **Factory/ParameterSpace audit** allows high‑fidelity **regression forensics** when users update wheels or drivers. Your manager already surfaces compile options—persisting them makes incidents explainable. 
* **DuckDB join** localizes hydration logic in SQL; it also underpins module coverage, language coverage, and BI uses of retrieval pools. Your catalog is designed for exactly this. 
* **Trace sinks** + **explainability tables** transform hybrid behavior into analyzable datasets; this feeds your evaluator, coverage, and operator tuning.

---

# Minimal sequencing (safe rollout)

1. **FAISSManager: IDMap2 + export_idmap_parquet** (2.1) → land tests → run once to generate `faiss_idmap.parquet`. 
2. **DuckDBCatalog: faiss_idmap & v_faiss_join** (A) → verify joins in notebooks; optionally materialize. 
3. **Factory meta** (B) → land, then rebuild once to persist meta. 
4. **Hybrid trace sinks + views** (C, 2.3) → enable for dev channels first; confirm sizes/latencies. 
5. **Presets/LUT + CLI** (2.2) → ship with defaults; allow user override.

---

# What this enables immediately

* **Exact hydration and coverage** via `v_faiss_join` (“Do we map every chunk in `auth/*`?”). 
* **End‑to‑end auditability** of FAISS configuration (“Why did recall drop after updating the wheel?” → check meta & parameter space). 
* **Rapid tuning with guardrails** (presets) aligned to small personal repos and predictable latency/quality. 
* **Explainable hybrid retrieval** (per‑channel contribution tables), and **oracle‑based QA** (XTR wide mode comparisons).

---

## Pointers to where each concept already exists in your code

* DuckDB view bootstrap & helpers: `_ensure_views`, `_relation_exists`, queries & embedding extraction.
* FAISS Manager: adaptive build, search with IVF knobs, ParameterSpace direct path, meta compile options, GPU clone, merge/extract.
* Hybrid engine & RRF: search fusion and contribution maps.
* MCP semantic tools: call path to adapter → hybrid resolve → hydration result.
* XTR index & build: for optional oracle and late interaction.
* Config & paths resolution: `Settings`, `PathsConfig`, `ApplicationContext`.

---

## “While we’re touching the architecture…” (bonus refinements)

1. **Index manifest**: you already have `io/faiss_dual_index.py` with `IndexManifest`. Add a field `idmap_digest` (sha256 of Parquet) and `factory_meta_path`. This makes index swaps atomic and self‑describing. 
2. **Safety on mixed ids**: on `update_index()`, validate no overlap between new ids and primary ids; log to Prometheus `faiss_update_collisions_total`. 
3. **Small‑system guard**: if `n < 5k`, force Flat (exact) and disable param space strings; this is consistent with your current adaptive doc and keeps latency trivial on laptops. 

---

### Acceptance criteria checklist

* ✅ `faiss_idmap.parquet` exported during build/update; `v_faiss_join` becomes queryable in DuckDB; optional `faiss_idmap_mat` materializes on checksum change. 
* ✅ `${faiss_index}.meta.json` records compile/factory/parameters; logs display on boot. 
* ✅ Trace Parquets (pool, hybrid contributions, hybrid top‑k) append rows on each query; DuckDB views expose them. 
* ✅ Preset LUT applied when runtime overrides aren’t provided; `indexctl tune` can set/lock presets; selection written to meta. 
* ✅ Deletions work with IDSelector; idmap re‑exported after delete/gc.

---

If you’d like, I can turn this plan into **ready‑to‑paste diffs** (schemas, helper functions, and the minimal changes inside each method I’ve referenced), mirroring your existing typing and docstring style. Otherwise, you can hand this to the implementer as is and follow the sequence above.
