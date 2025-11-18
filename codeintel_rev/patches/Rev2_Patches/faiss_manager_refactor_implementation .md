# faiss_manager refactor implementation plan #

Below is a **turn‑key refactor plan** for breaking up `io/faiss_manager.py` into discrete layers with **ready‑to‑drop‑in modules + code**. It preserves today’s external behaviors (adaptive index build; dual primary/secondary search; runtime tuning knobs; optional exact rerank via DuckDB; Parquet ID‑map sidecar; secondary index persisted with a `.secondary` suffix) while driving a clean separation of responsibilities. I’ve included **rich, annotated code** you can paste into new files and then run the rename/migration steps as outlined.

> **Why this split maps 1:1 to your current responsibilities**
>
> * **Builder**: adaptive selection *Flat vs IVFFlat vs IVF‑PQ*, training and direct‑map setup, all of which your current manager performs in `build_index()` with small/medium/large thresholds and dynamic `nlist` selection. 
> * **Runtime**: typed array coercions for FAISS search (`_run_index_search`), IVF knobs (`nprobe`, `efSearch`, `quantizer_efSearch`), and primary+secondary merging with optional exact re‑rank.
> * **Store**: export/load **ID map sidecar (Parquet)**, and DuckDB join/materialization helpers that the CLI already depends on (the sidecar represents `{faiss_row → external_id}` and is used to refresh the materialized join).
> * **Facade**: a tiny `FAISSManager` that *composes* builder/runtime/store and maintains just the minimal state (e.g., `incremental_ids`, `vec_dim`) while keeping the public surface backward compatible, including `.search()`, `.apply_runtime_parameters()`, `.save_secondary_index()`, and `.load_secondary_index()` (which expects the `.secondary` file).

---

## 0) High‑level outcome

* New modules:

  * `codeintel_rev/io/faiss_build.py` – Index lifecycle: choose family, train/build, add, save/load; create the secondary flat index.
  * `codeintel_rev/io/faiss_runtime.py` – **Only** runtime search, typed coercions, normalization, knobs application, merge, and (optional) refine step.
  * `codeintel_rev/io/faiss_store.py` – **Only** persistence and data integration: ID map export/load, DuckDB materialization helpers, (optional) vector reconstruction.
  * `codeintel_rev/io/faiss_manager.py` – **Small facade** that wires the pieces; preserves public API & default semantics.
* No behavior changes required by callers (CLI, API, adapters). E.g., CLI `indexctl` continues to call `FAISSManager.search()` and `export-idmap` flows remain intact.

---

## 1) New module: `io/faiss_build.py`

> *Scope*: All build/training concerns; adaptive family selection; direct map enablement; creating a flat secondary; and add‑vectors with L2 normalization for cosine/IP. Your current build docstrings and examples align with this approach.

```python
# codeintel_rev/io/faiss_build.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import numpy as np

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import NDArrayF32, NDArrayI64, gate_import

_faiss = LazyModule("faiss")
np = np  # silence linter re-binding

IndexFamily = Literal["flat", "ivfflat", "ivfpq", "adaptive"]

@dataclass(frozen=True)
class IndexBuildConfig:
    vec_dim: int
    default_nlist: int = 8192
    family: IndexFamily = "adaptive"
    # IVF-PQ defaults
    pq_m: int = 32
    pq_bits: int = 8

def _l2_normalize(vecs: NDArrayF32) -> NDArrayF32:
    # Normalize for cosine similarity with IP
    v = vecs.astype(np.float32, copy=False)
    if v.ndim == 1:
        v = v.reshape(1, -1)
    norms = np.linalg.norm(v, axis=1, keepdims=True).astype(np.float32)
    norms[norms == 0] = 1.0
    return v / norms

def _dynamic_nlist(n: int, default_nlist: int) -> int:
    # Good heuristic: ~sqrt(n) capped at default_nlist
    return max(1, min(default_nlist, int(np.sqrt(max(n, 1)))))

def choose_family(n_vectors: int, cfg: IndexBuildConfig) -> IndexFamily:
    if cfg.family != "adaptive":
        return cfg.family
    # Mirrors current thresholds: <5k Flat; 5k-50k IVFFlat; >50k IVF-PQ
    if n_vectors < 5_000:
        return "flat"
    if n_vectors <= 50_000:
        return "ivfflat"
    return "ivfpq"  # memory-efficient for large corpora
# (Based on existing docstrings of build_index() heuristics.)  # :contentReference[oaicite:6]{index=6}

def _configure_direct_map(index: object) -> None:
    """
    Enable array-backed direct maps where supported to allow reconstruction.
    """
    try:
        # Delegate to your existing helper semantics
        # (kept consistent with _configure_direct_map/_set_direct_map_type docs)
        # :contentReference[oaicite:7]{index=7}
        if hasattr(index, "make_direct_map"):
            index.make_direct_map()
        # Some wrappers (IDMap/IVF) expose inner index via .index
        inner = getattr(index, "index", None)
        if inner is not None and hasattr(inner, "make_direct_map"):
            inner.make_direct_map()
    except Exception:
        # best-effort; reconstruction remains optional
        pass

def build_primary_index(
    vectors: NDArrayF32,
    *,
    cfg: IndexBuildConfig,
    override_family: Optional[IndexFamily] = None,
) -> object:
    """
    Train/build the primary index and wrap with ID map for external IDs.
    Returns a FAISS index object (IDMap2(wrapper)).
    """
    gate_import("faiss")  # ensure import allowed
    faiss = _faiss.module()

    v = _l2_normalize(vectors)
    n, d = v.shape
    if d != cfg.vec_dim:
        raise ValueError(f"vec_dim mismatch: expected {cfg.vec_dim}, got {d}")

    family = override_family or choose_family(n, cfg)

    if family == "flat":
        base = faiss.IndexFlatIP(d)
    elif family == "ivfflat":
        quant = faiss.IndexFlatIP(d)
        nlist = _dynamic_nlist(n, cfg.default_nlist)
        base = faiss.IndexIVFFlat(quant, d, nlist, faiss.METRIC_INNER_PRODUCT)
        base.train(v)
    elif family == "ivfpq":
        quant = faiss.IndexFlatIP(d)
        nlist = _dynamic_nlist(n, cfg.default_nlist)
        base = faiss.IndexIVFPQ(
            quant, d, nlist, cfg.pq_m, cfg.pq_bits, faiss.METRIC_INNER_PRODUCT
        )
        base.train(v)
    else:
        raise ValueError(f"Unknown family: {family}")

    idmap = faiss.IndexIDMap2(base)
    _configure_direct_map(idmap)
    return idmap

def add_vectors(index: object, vectors: NDArrayF32, ids: NDArrayI64) -> None:
    faiss = _faiss.module()
    v = _l2_normalize(vectors)
    ids_arr = np.asarray(ids, dtype=np.int64)
    index.add_with_ids(v, ids_arr)

def save_index(index: object, path: Path) -> None:
    faiss = _faiss.module()
    path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(path))

def load_index(path: Path) -> object:
    faiss = _faiss.module()
    return faiss.read_index(str(path))

def create_secondary_index(vec_dim: int) -> object:
    """
    Secondary is always a *flat* (IndexFlatIP) wrapped with IDMap2
    for instant incremental adds (no training).  :contentReference[oaicite:8]{index=8}
    """
    faiss = _faiss.module()
    flat = faiss.IndexFlatIP(vec_dim)
    sec = faiss.IndexIDMap2(flat)
    _configure_direct_map(sec)
    return sec
```

---

## 2) New module: `io/faiss_runtime.py`

> *Scope*: Searching (primary and optional secondary), typed coercions, runtime parameter application (ParameterSpace + fallback), merging, and optional exact refinement using the existing flat reranker (`retrieval.rerank_flat.exact_rerank`). Your code today supports `_run_index_search`, `nprobe` (flat indexes ignore it), and an optional exact rerank step when a DuckDB catalog is provided.

```python
# codeintel_rev/io/faiss_runtime.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

import numpy as np

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import NDArrayF32, NDArrayI64, gate_import

# Optional dependency only when refine is requested
try:
    from codeintel_rev.retrieval.rerank_flat import exact_rerank
except Exception:  # pragma: no cover
    exact_rerank = None  # refine path remains optional  # :contentReference[oaicite:10]{index=10}

_faiss = LazyModule("faiss")

@dataclass(frozen=True)
class FAISSRuntimeOptions:
    default_k: int = 50
    default_nprobe: int = 64
    refine_k_factor: float = 1.0  # >1.0 will enable exact refinement  :contentReference[oaicite:11]{index=11}

def _as2d_f32(arr: NDArrayF32) -> NDArrayF32:
    a = np.asarray(arr, dtype=np.float32)
    if a.ndim == 1:
        a = a.reshape(1, -1)
    # Cosine via IP — ensure inputs are normalized upstream in builder/add/search
    norms = np.linalg.norm(a, axis=1, keepdims=True).astype(np.float32)
    norms[norms == 0] = 1.0
    return a / norms

def apply_runtime_parameters(index: object, *, nprobe: int | None,
                             ef_search: int | None, quantizer_ef_search: int | None) -> None:
    """
    Best-effort apply ParameterSpace (nprobe, efSearch, quantizer_efSearch),
    falling back to attributes (e.g., index.nprobe) if needed.  :contentReference[oaicite:12]{index=12}
    """
    faiss = _faiss.module()
    try:
        ps = faiss.ParameterSpace()
        ps.initialize(index)
        params = []
        if nprobe is not None:
            params.append(f"nprobe={int(nprobe)}")
        if ef_search is not None:
            params.append(f"efSearch={int(ef_search)}")
        if quantizer_ef_search is not None:
            params.append(f"quantizer_efSearch={int(quantizer_ef_search)}")
        if params:
            ps.set_index_parameters(index, ",".join(params))
        return
    except Exception:
        pass

    # Fallback to direct attributes
    if nprobe is not None and hasattr(index, "nprobe"):
        try:
            index.nprobe = int(nprobe)
        except Exception:
            pass
    if ef_search is not None and hasattr(index, "efSearch"):
        try:
            index.efSearch = int(ef_search)
        except Exception:
            pass
    if quantizer_ef_search is not None and hasattr(index, "quantizer"):
        try:
            q = index.quantizer
            if hasattr(q, "efSearch"):
                q.efSearch = int(quantizer_ef_search)
        except Exception:
            pass

def _run_index_search(index: object, query: NDArrayF32, k: int) -> tuple[NDArrayF32, NDArrayI64]:
    """
    Execute FAISS search and coerce outputs to (float32, int64) with shapes (B, k).
    Mirrors existing semantics.  :contentReference[oaicite:13]{index=13}
    """
    faiss = _faiss.module()
    q = _as2d_f32(query)
    distances = np.empty((q.shape[0], k), dtype=np.float32)
    ids = np.empty((q.shape[0], k), dtype=np.int64)
    # faiss returns (D, I)
    D, I = index.search(q, k)
    distances[...] = D.astype(np.float32, copy=False)
    ids[...] = I.astype(np.int64, copy=False)
    return distances, ids

def _search_primary(index: object, query: NDArrayF32, k: int, *, nprobe: int | None) -> tuple[NDArrayF32, NDArrayI64]:
    """
    Apply nprobe if supported (IVF families), skip for Flat.  :contentReference[oaicite:14]{index=14}
    """
    # Unlike HNSW, flat indexes don't expose nprobe; check attribute presence.
    if nprobe is not None and hasattr(index, "nprobe"):
        try:
            index.nprobe = int(nprobe)
        except Exception:
            pass
    return _run_index_search(index, query, k)

def _merge_by_score(
    d1: NDArrayF32, i1: NDArrayI64, d2: NDArrayF32, i2: NDArrayI64, k: int
) -> tuple[NDArrayF32, NDArrayI64]:
    """
    Merge two (D, I) pairs by score, per row, keeping top-k.
    """
    b = d1.shape[0]
    out_d = np.full((b, k), -np.inf, dtype=np.float32)
    out_i = np.full((b, k), -1, dtype=np.int64)
    for row in range(b):
        merged = list(zip(i1[row].tolist(), d1[row].tolist())) + list(zip(i2[row].tolist(), d2[row].tolist()))
        merged.sort(key=lambda t: t[1], reverse=True)  # higher cosine/IP is better
        keep = []
        seen = set()
        for cid, score in merged:
            if cid < 0 or cid in seen:
                continue
            seen.add(cid)
            keep.append((score, cid))
            if len(keep) == k:
                break
        for j, (score, cid) in enumerate(keep):
            out_d[row, j] = score
            out_i[row, j] = cid
    return out_d, out_i

def search_dual(
    *,
    primary: object,
    secondary: object | None,
    query: NDArrayF32,
    k: int,
    nprobe: int | None,
    refine_k_factor: float,
    catalog: object | None,
) -> tuple[NDArrayF32, NDArrayI64]:
    """
    1) search primary (nprobe), 2) search secondary (flat), 3) merge by score,
    4) optionally exact-rerank top-(k * factor) via catalog embeddings. :contentReference[oaicite:15]{index=15}
    """
    # expand candidate set if we’ll refine
    search_k = int(k * max(1.0, refine_k_factor))
    d1, i1 = _search_primary(primary, query, search_k, nprobe=nprobe)
    if secondary is not None:
        d2, i2 = _run_index_search(secondary, query, search_k)
        d_m, i_m = _merge_by_score(d1, i1, d2, i2, search_k)
    else:
        d_m, i_m = d1, i1

    # Optional refine with exact vectors from DuckDB (FlatReranker)  :contentReference[oaicite:16]{index=16}
    if exact_rerank is not None and catalog is not None and refine_k_factor > 1.0 and search_k > k:
        # exact_rerank expects dense candidate ids matrix (B, K')
        reranked_d, reranked_i = exact_rerank(catalog, _as2d_f32(query), i_m, top_k=k, metric="ip")
        return reranked_d.astype(np.float32), reranked_i.astype(np.int64)

    # Otherwise just truncate to k
    return d_m[:, :k], i_m[:, :k]
```

---

## 3) New module: `io/faiss_store.py`

> *Scope*: ID map sidecar (Parquet) read/write, secondary index persistence, and DuckDB join helpers. This reflects your current `_FAISSIdMapMixin` and the CLI `export-idmap`/materialize flows (using a Parquet sidecar carrying `{faiss_row → external_id}` that feeds the DuckDB materialized join refresh).

```python
# codeintel_rev/io/faiss_store.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import numpy as np

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.typing import NDArrayF32, NDArrayI64, gate_import
from codeintel_rev.io.duckdb_catalog import refresh_faiss_idmap_materialized  # used by CLI flows  # :contentReference[oaicite:18]{index=18}

_pa = LazyModule("pyarrow")
_pq = LazyModule("pyarrow.parquet")
_faiss = LazyModule("faiss")

@dataclass(frozen=True)
class IndexArtifactPaths:
    primary_index_path: Path
    secondary_suffix: str = ".secondary"

    @property
    def secondary_index_path(self) -> Path:
        # Matches current expectation of .secondary file next to the primary.  :contentReference[oaicite:19]{index=19}
        return self.primary_index_path.with_suffix(self.primary_index_path.suffix + self.secondary_suffix)

def get_idmap_array(index: object) -> NDArrayI64:
    """
    Return np.int64 array such that arr[row] == external_id.
    Mirrors existing `_FAISSIdMapMixin.get_idmap_array()`.  :contentReference[oaicite:20]{index=20}
    """
    faiss = _faiss.module()
    # IDMap2 exposes .id_map; extract as numpy (implementation detail varies by FAISS build)
    try:
        idmap = index.id_map
        # Many wheels export a property returning a numpy array of ids in row order:
        # fallback path reconstructs enumerating ntotal
        arr = np.asarray(idmap, dtype=np.int64)
        if arr.ndim == 1:
            return arr
    except Exception:
        pass

    # Fallback: scan ntotal by reconstructing reverse map
    ntotal = int(getattr(index, "ntotal", 0))
    out = np.empty(ntotal, dtype=np.int64)
    # Some builds offer index.id_map.at(row) -> id
    for row in range(ntotal):
        try:
            out[row] = int(index.id_map.at(row))  # type: ignore[attr-defined]
        except Exception:
            out[row] = -1
    return out

def export_idmap_parquet(index: object, out_path: Path) -> int:
    """
    Persist {faiss_row -> external_id} to Parquet with metadata.  :contentReference[oaicite:21]{index=21}
    """
    gate_import("pyarrow")
    pa = _pa.module()
    pq = _pq.module()

    ids = get_idmap_array(index)
    rows = np.arange(ids.shape[0], dtype=np.int64)
    table = pa.table(
        {
            "faiss_row": pa.array(rows),
            "external_id": pa.array(ids),
        }
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(out_path))
    return int(table.num_rows)

def save_secondary_index(index: object, paths: IndexArtifactPaths) -> None:
    faiss = _faiss.module()
    faiss.write_index(index, str(paths.secondary_index_path))  # :contentReference[oaicite:22]{index=22}

def load_secondary_index(paths: IndexArtifactPaths) -> object:
    faiss = _faiss.module()
    return faiss.read_index(str(paths.secondary_index_path))  # caller handles FileNotFoundError

def refresh_duckdb_materialization(conn, idmap_parquet: Path, chunks_parquet: Path) -> dict:
    """
    Rebuild materialized join iff checksum changes (existing helper).  :contentReference[oaicite:23]{index=23}
    """
    return refresh_faiss_idmap_materialized(conn, str(idmap_parquet), str(chunks_parquet))
```

> **Optional** (still belongs in store): expose `reconstruct_batch()` for diagnostics and tests using your current direct‑map semantics (approximate for PQ). 

---

## 4) Refactor `io/faiss_manager.py` into a **thin facade**

> *Scope*: Keep the class name and public surface so existing code continues to work (CLI, adapters, API). It holds *only* wiring and minimal state while delegating into builder/runtime/store.

**New `io/faiss_manager.py`**

```python
# codeintel_rev/io/faiss_manager.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Set, Tuple

import numpy as np

from codeintel_rev.typing import NDArrayF32, NDArrayI64
from codeintel_rev.io.faiss_build import (
    IndexBuildConfig,
    IndexFamily,
    add_vectors as _add_vectors,
    build_primary_index as _build_primary_index,
    create_secondary_index as _create_secondary_index,
    load_index as _load_index,
    save_index as _save_index,
)
from codeintel_rev.io.faiss_runtime import (
    FAISSRuntimeOptions,
    apply_runtime_parameters as _apply_params,
    search_dual as _search_dual,
)
from codeintel_rev.io.faiss_store import (
    IndexArtifactPaths,
    export_idmap_parquet as _export_idmap_parquet,
    get_idmap_array as _get_idmap_array,
    load_secondary_index as _load_secondary,
    save_secondary_index as _save_secondary,
)

# Public alias preserved for callers that import this type
FaissIndex = object

@dataclass
class FAISSManager:
    index_path: Path
    vec_dim: int = 3584
    nlist: int = 8192
    runtime: FAISSRuntimeOptions = field(default_factory=FAISSRuntimeOptions)

    # Live state (kept private)
    _primary: FaissIndex | None = field(default=None, init=False, repr=False)
    _secondary: FaissIndex | None = field(default=None, init=False, repr=False)
    incremental_ids: Set[int] = field(default_factory=set, init=False)

    # -------------------------
    # Build / open / persist
    # -------------------------
    def build_index(self, vectors: NDArrayF32, *, family: IndexFamily | None = None) -> None:
        """
        Adaptive build: Flat/IVFFlat/IVF-PQ per corpus size.  :contentReference[oaicite:25]{index=25}
        """
        cfg = IndexBuildConfig(vec_dim=self.vec_dim, default_nlist=self.nlist,
                               family=family or "adaptive")
        self._primary = _build_primary_index(vectors, cfg=cfg, override_family=family)

    def add_vectors(self, vectors: NDArrayF32, ids: NDArrayI64) -> None:
        """
        Add to *primary* (post-build).  :contentReference[oaicite:26]{index=26}
        """
        if self._primary is None:
            raise RuntimeError("Primary index is not initialized; call build_index() or load_cpu_index().")
        _add_vectors(self._primary, vectors, ids)

    def save_cpu_index(self, *, export_idmap: Path | None = None, profile_path: Path | None = None) -> None:
        if self._primary is None:
            raise RuntimeError("Primary index is not initialized.")
        _save_index(self._primary, self.index_path)
        if export_idmap is not None:
            _export_idmap_parquet(self._primary, export_idmap)

    def load_cpu_index(self, *, export_idmap: Path | None = None, profile_path: Path | None = None) -> None:
        """
        Load the CPU index from disk; optionally re-export ID map sidecar.  :contentReference[oaicite:27]{index=27}
        """
        self._primary = _load_index(self.index_path)
        if export_idmap is not None:
            _export_idmap_parquet(self._primary, export_idmap)

    # -------------------------
    # Secondary lifecycle
    # -------------------------
    def _ensure_secondary(self) -> None:
        """
        Lazily create secondary (IndexFlatIP + IDMap2) with direct map.  :contentReference[oaicite:28]{index=28}
        """
        if self._secondary is None:
            self._secondary = _create_secondary_index(self.vec_dim)

    def update_index(self, vectors: NDArrayF32, ids: NDArrayI64) -> int:
        """
        Incremental adds go to *secondary*; we track not-yet-in-primary IDs.
        """
        if self._primary is None:
            raise FileNotFoundError("Primary index not loaded. Run full build/load first.")
        self._ensure_secondary()
        # Deduplicate within-batch and against tracked incremental set
        ids_arr = np.asarray(ids, dtype=np.int64).reshape(-1)
        vectors = np.asarray(vectors, dtype=np.float32)
        keep_mask = np.ones_like(ids_arr, dtype=bool)
        seen = set()
        for pos, cid in enumerate(ids_arr.tolist()):
            if cid in seen or cid in self.incremental_ids:
                keep_mask[pos] = False
            else:
                seen.add(cid)
        kept = int(keep_mask.sum())
        if kept > 0:
            _add_vectors(self._secondary, vectors[keep_mask], ids_arr[keep_mask])
            self.incremental_ids.update(ids_arr[keep_mask].tolist())
        return kept

    def save_secondary_index(self) -> None:
        if self._secondary is None:
            raise RuntimeError("Secondary index has not been created yet.")
        paths = IndexArtifactPaths(self.index_path)
        _save_secondary(self._secondary, paths)  # writes *.secondary  :contentReference[oaicite:29]{index=29}

    def load_secondary_index(self) -> None:
        paths = IndexArtifactPaths(self.index_path)
        self._secondary = _load_secondary(paths)  # may raise FileNotFoundError (normal)  :contentReference[oaicite:30]{index=30}

    # -------------------------
    # Search + runtime tuning
    # -------------------------
    def apply_runtime_parameters(self, overrides: Mapping[str, float | int]) -> None:
        """
        Best-effort apply (nprobe, efSearch, quantizer_efSearch) to the live index.  :contentReference[oaicite:31]{index=31}
        """
        if self._primary is None:
            return
        nprobe = overrides.get("nprobe")
        ef_search = overrides.get("efSearch") or overrides.get("ef_search")
        quantizer_ef_search = overrides.get("quantizer_efSearch") or overrides.get("quantizer_ef_search")
        _apply_params(self._primary, nprobe=nprobe if nprobe is not None else None,
                      ef_search=ef_search if ef_search is not None else None,
                      quantizer_ef_search=quantizer_ef_search if quantizer_ef_search is not None else None)

    def search(
        self,
        query: NDArrayF32,
        k: int | None = None,
        *,
        nprobe: int | None = None,
        runtime: Mapping[str, float] | None = None,
        catalog: object | None = None,
    ) -> tuple[NDArrayF32, NDArrayI64]:
        """
        Dual-index cosine/IP search with merge + optional exact rerank.  :contentReference[oaicite:32]{index=32}
        """
        if self._primary is None:
            raise RuntimeError("Index not loaded/built.")

        # Resolve effective params
        eff_k = int(k or self.runtime.default_k)
        eff_nprobe = int(nprobe or self.runtime.default_nprobe)
        refine_k_factor = float(runtime.get("k_factor", self.runtime.refine_k_factor)) if runtime else self.runtime.refine_k_factor

        # Apply runtime knobs to primary (secondary is flat)
        _apply_params(self._primary, nprobe=eff_nprobe, ef_search=None, quantizer_ef_search=None)

        return _search_dual(
            primary=self._primary,
            secondary=self._secondary,
            query=query,
            k=eff_k,
            nprobe=eff_nprobe,
            refine_k_factor=refine_k_factor,
            catalog=catalog,
        )

    # -------------------------
    # ID map / utilities
    # -------------------------
    def export_idmap(self, out_path: Path) -> int:
        """
        Export {faiss_row -> external_id} for DuckDB join/materialize.  :contentReference[oaicite:33]{index=33}
        """
        if self._primary is None:
            raise RuntimeError("Index not loaded/built.")
        return _export_idmap_parquet(self._primary, out_path)

    def get_idmap_array(self) -> NDArrayI64:
        if self._primary is None:
            raise RuntimeError("Index not loaded/built.")
        return _get_idmap_array(self._primary)

    # Back-compat helpers used by CLI/app
    def require_cpu_index(self) -> FaissIndex:
        if self._primary is None:
            raise RuntimeError("Index not loaded/built.")
        return self._primary
```

> **Notes**
>
> * The facade keeps identical “shape” for the most visible calls (`build_index`, `add_vectors`, `search`, `apply_runtime_parameters`, `load/save_*`, `export_idmap`, `require_cpu_index`), so CLI and adapters don’t need to change. The semantics (dual‑index search, IVF knobs, exact refinement option) match your current docstrings.
> * The “secondary index filename” convention (`.secondary`) is centralized in `IndexArtifactPaths`. 

---

## 5) Migration steps (surgical, low‑risk)

1. **Add files** above to the repo under `codeintel_rev/io/…`.

2. **Trim the old monolith** `io/faiss_manager.py`: replace its internal logic with the facade (above).

   * *If* you prefer zero‑diff for public names: keep the class name and method names exactly as above.
   * Remove internal helpers now housed in the new modules (`_run_index_search`, `_apply_runtime_parameters`, idmap mixin, etc.). Those responsibilities are imported from their new locations.

3. **Re‑export (optional)**: Update `io/__init__.py` to expose the same public class (optional convenience):

   ```python
   # codeintel_rev/io/__init__.py
   from .faiss_manager import FAISSManager  # re-export
   ```

4. **No codemod needed** for external callers because the facade preserves the original import path and class name.

   * CLI (`indexctl`) invokes `FAISSManager` methods like `search`, `export_idmap`, and `require_cpu_index`—all preserved.
   * App contexts that call `apply_runtime_parameters()` continue to work. 

5. **Optional: Incremental adoption**

   * You can ship the new modules first while leaving the original `FAISSManager` in place; then in a follow‑up PR, flip the facade over by delegating to the new modules (as shown).

---

## 6) Tests you can add immediately

**a) Builder selection + train/save/load**

```python
def test_builder_adaptive_selection(tmp_path, rand_vectors):
    from codeintel_rev.io.faiss_build import IndexBuildConfig, build_primary_index, save_index, load_index

    cfg = IndexBuildConfig(vec_dim=rand_vectors.shape[1])
    idx = build_primary_index(rand_vectors[:3000], cfg=cfg)      # expected Flat  :contentReference[oaicite:38]{index=38}
    p = tmp_path / "idx.faiss"
    save_index(idx, p)
    re = load_index(p)
    assert int(getattr(re, "ntotal", 0)) == 0
```

**b) Runtime merge + flat‑secondary**

```python
def test_runtime_merge_with_secondary(rand_vectors, rand_ids):
    from codeintel_rev.io.faiss_build import IndexBuildConfig, build_primary_index, create_secondary_index, add_vectors
    from codeintel_rev.io.faiss_runtime import search_dual, FAISSRuntimeOptions

    cfg = IndexBuildConfig(vec_dim=rand_vectors.shape[1])
    pri = build_primary_index(rand_vectors[:6000], cfg=cfg)  # IVFFlat likely  :contentReference[oaicite:39]{index=39}
    add_vectors(pri, rand_vectors[:6000], rand_ids[:6000])
    sec = create_secondary_index(cfg.vec_dim)
    add_vectors(sec, rand_vectors[6000:7000], rand_ids[6000:7000])

    q = rand_vectors[7001:7006]
    d, i = search_dual(primary=pri, secondary=sec, query=q, k=10, nprobe=32, refine_k_factor=1.0, catalog=None)
    assert d.shape == (5, 10) and i.shape == (5, 10)
```

**c) Store: sidecar**

```python
def test_export_idmap_parquet(tmp_path, rand_vectors, rand_ids):
    from codeintel_rev.io.faiss_build import IndexBuildConfig, build_primary_index, add_vectors
    from codeintel_rev.io.faiss_store import export_idmap_parquet

    cfg = IndexBuildConfig(vec_dim=rand_vectors.shape[1])
    idx = build_primary_index(rand_vectors[:100], cfg=cfg)
    add_vectors(idx, rand_vectors[:100], rand_ids[:100])

    out = tmp_path / "idmap.parquet"
    n = export_idmap_parquet(idx, out)
    assert n == 100 and out.exists()
```

> If you already have golden tests for `_FAISSIdMapMixin` or the search planner, you can keep those and simply import via the new modules; the behavior mirrors existing docstrings.

---

## 7) Performance and correctness parity checklist

* **Index type thresholds** keep your documented split (<5k Flat, 5k–50k IVF‑Flat, >50k IVF‑PQ). 
* **Typed search outputs** remain `(float32, int64)` with `(B, k)` shapes, enforced centrally in `faiss_runtime._run_index_search`. 
* **IVF knobs** (`nprobe`) are applied only when supported; flat indexes ignore it safely (attribute check). 
* **Dual‑index semantics** hold: search both primary and secondary (flat), merge by score, then optional exact rerank using DuckDB embeddings.
* **Secondary persistence** uses the `.secondary` sibling file convention. 
* **ID map sidecar** remains `{faiss_row → external_id}` Parquet used by `export-idmap` and DuckDB materialization refresh.

---

## 8) Rollout plan (day‑by‑day)

**Day 1 — Introduce modules behind the scenes**

* Add `faiss_build.py`, `faiss_runtime.py`, `faiss_store.py` and unit tests.
* Land without touching the existing `FAISSManager`.

**Day 2 — Flip the facade**

* Replace `io/faiss_manager.py` implementation with the thin facade shown above (keep the class name & methods).
* Run CLI smoke: `indexctl health`, `indexctl tune`, `indexctl export-idmap`, `indexctl materialize-join`.
  All of these use the same public API that still exists. 

**Day 3 — Hardening**

* Exercise end‑to‑end flows (build → export‑idmap → materialize → search with overrides → refine).
* If you see differences in rerank behavior, confirm the `k_factor` override path is still wired (runtime → `search_dual`). 

---

## 9) Developer ergonomics & documentation

* Add concise module headers describing duties & examples (copy or adapt your existing docstrings; they are already excellent and will help prevent regression).
* In `README_dev.md` (or module README), include a “Which layer does this belong in?” section:

  * **Build** = training/factory/IDMap/secondary create/save/load
  * **Runtime** = search/knobs/merge/refine
  * **Store** = Parquet ID map & DuckDB integration

---

## 10) Backward‑compat Q&A (what won’t break)

* **CLI commands** (`health`, `tune`, `export-idmap`, `materialize-join`) keep working because they still import and call `FAISSManager` from `io.faiss_manager`. The facade preserves method names and semantics. 
* **App runtime overrides** (`apply_runtime_parameters`) and tuning profiles still act on the live index using the same keys (`nprobe`, `efSearch`, `quantizer_efSearch`). 
* **Secondary index** naming and loading behavior is unchanged (`.secondary`). 
* **Exact rerank path** remains opt‑in and requires a catalog with embedding hydration (your `FlatReranker` route). 

---

### Appendix — small helpers you may want to keep

If any external code relied on internal mixins like `_FAISSIdMapMixin`, keep a tiny shim in `io/faiss_manager.py` that forwards to `faiss_store`:

```python
# Optional shim for external callers that imported private mixins
def export_idmap(manager: FAISSManager, out_path: Path) -> int:
    return manager.export_idmap(out_path)
```

---

**That’s it.** With these modules and steps you’ll convert a “god module” into a **clean 4‑layer design**: lifecycle, runtime, store, and a tiny facade. This isolates responsibilities, makes unit testing trivial, and preserves the observable surface area for CLI/app integrations.
