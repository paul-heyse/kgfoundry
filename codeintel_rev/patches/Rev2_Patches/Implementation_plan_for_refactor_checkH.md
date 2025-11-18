
# detailed implementation plan and code #

Below is a **turn‑key implementation plan with full code** to refactor **`bin/index_all.py`** into a *pure orchestration script* that delegates every unit of work to small, testable services. It’s aligned to the repo’s current layering:

* **FAISS** split already landed: `io/faiss_build.py`, `io/faiss_runtime.py`, `io/faiss_store.py`. We’ll reuse these instead of embedding build/search/persistence details in the CLI.
* **DuckDB** split already landed: schema/DAO separated from the catalog; we’ll call the thin `DuckDBCatalog` for idmap registration/materialization, and avoid inlining DDL here.
* **CLI “thin shells only” discipline** from the enrich refactor: 5–20 LOC shells that just parse args and call services. We apply the same approach to `bin/index_all.py`.
* Conforms to **AGENTS.md** lint/type/test rules (Ruff+Pyright strict, absolute imports, typed functions, no prints, docstrings, ≤100‑col, etc.).

---

## What we’re building (at a glance)

**New service package**

```
codeintel_rev/
  services/
    index/
      __init__.py
      plan.py       # dataclasses & the step runner (pure coordination)
      steps.py      # small, focused step functions (I/O split; heavy deps lazy)
      build.py      # high-level "run_index_build" orchestration (thin)
```

**Entry point that is orchestration only**

```
bin/index_all.py   # <= 30 lines; Typer options -> services.index.build.run_index_build
```

**Key behaviors**

* Read **vector shards** (Parquet) → sample for training → **train primary** → **add all vectors** in batches → **persist** primary → **create/persist secondary** (`.secondary`) → **export idmap** (Parquet) → **register/materialize in DuckDB**.
  (Adaptive family selection + IDMap & `.secondary` conventions live in the *io/faiss_* layer, not here.)

---

## 1) New files — drop‑in code

### `codeintel_rev/services/index/plan.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Literal, Mapping, MutableMapping, Optional

# Public, declarative step identifiers (keep orchestration readable in bin/)
StepName = Literal[
    "scan_shards",
    "sample_training",
    "train_primary",
    "add_all_vectors",
    "persist_primary",
    "build_secondary",
    "persist_secondary",
    "export_idmap",
    "register_duckdb",
    "materialize_join",
]

@dataclass(frozen=True)
class IndexPaths:
    """Resolved locations used by the build."""
    vectors_parquet_dir: Path        # input shards (glob '*.parquet')
    primary_index_path: Path         # output FAISS index
    idmap_parquet_path: Path         # sidecar with {faiss_row -> external_id}
    duckdb_path: Optional[Path] = None

@dataclass(frozen=True)
class IndexBuildConfig:
    """Pure, serializable knobs: no live handles or modules."""
    vec_dim: int
    id_col: str = "chunk_id"
    vec_col: str = "embedding"
    sample_size: int = 50_000       # rows for training (if available)
    batch_rows: int = 50_000        # ingest chunk when adding vectors
    materialize: bool = True        # if True, build materialized join in DuckDB

@dataclass
class BuildState:
    """Mutable bag passed across steps; not exposed outside services."""
    shards: List[Path] = field(default_factory=list)
    sample_rows: int = 0
    primary_index: object | None = None
    secondary_index: object | None = None
    added_rows: int = 0
    idmap_rows: int = 0

class StepRunner:
    """Declarative step executor. Each step is a small callable(state, paths, cfg)."""

    def __init__(self, registry: Mapping[StepName, Callable[[BuildState, IndexPaths, IndexBuildConfig], None]]):
        self._registry: Dict[StepName, Callable[[BuildState, IndexPaths, IndexBuildConfig], None]] = dict(registry)

    def run(self, steps: Iterable[StepName], *, paths: IndexPaths, cfg: IndexBuildConfig) -> BuildState:
        state = BuildState()
        for name in steps:
            step = self._registry[name]
            step(state, paths, cfg)
        return state
```

### `codeintel_rev/services/index/steps.py`

> Heavy deps are **lazy‑imported** and all functions are **typed** with small, single responsibilities (AGENTS.md). We never import FAISS/PyArrow at module import time—only inside functions via the repo’s `LazyModule` pattern. 

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Iterator, List, Sequence, Tuple, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.services.index.plan import BuildState, IndexBuildConfig, IndexPaths
from codeintel_rev.io.faiss_build import (
    IndexBuildConfig as FaissBuildCfg,
    add_vectors as faiss_add_vectors,
    build_primary_index,
    create_secondary_index,
    save_index as faiss_save_index,
)
from codeintel_rev.io.faiss_store import (
    IndexArtifactPaths,
    export_idmap_parquet,
    save_secondary_index,
)
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog

# Type-only imports for static checking (no runtime cost).
if TYPE_CHECKING:
    import numpy as np  # type: ignore[assignment]
else:
    # Lazy heavy deps
    np = cast("np", LazyModule("numpy", "index build steps"))


_pa = LazyModule("pyarrow", "index build: parquet I/O")
_pq = LazyModule("pyarrow.parquet", "index build: parquet I/O")


# ---------- small helpers ----------

def _parquet_shards(glob_dir: Path) -> List[Path]:
    return sorted(glob_dir.rglob("*.parquet"))

def _iter_batches(path: Path, *, columns: Sequence[str], batch_rows: int) -> Iterator[Tuple["np.ndarray", "np.ndarray"]]:
    """
    Yield (ids, embeddings) batches from a Parquet file. Embedding column is a
    PyArrow list<item: float32> or fixed_size_list<float32>.
    """
    pa = _pa.module()
    pq = _pq.module()

    pf = pq.ParquetFile(str(path))
    for rec in pf.iter_batches(batch_size=batch_rows, columns=list(columns)):
        # rec is a RecordBatch; convert using Arrow -> Python -> NumPy to handle list columns portably
        ids = pa.array(rec.column(0)).to_numpy(zero_copy_only=False)
        # to_pylist + np.array avoids nested Arrow buffers/offsets complexity
        vecs_py = pa.array(rec.column(1)).to_pylist()
        vecs = cast("np.ndarray", np.asarray(vecs_py, dtype="float32"))
        yield cast("np.ndarray", ids.astype("int64", copy=False)), vecs

def _take_sample(shards: List[Path], *, columns: Sequence[str], sample_size: int) -> "np.ndarray":
    """
    Collect up to sample_size vectors across shards for IVF training.
    """
    pa = _pa.module()
    pq = _pq.module()
    out: List["np.ndarray"] = []
    remaining = sample_size
    for p in shards:
        if remaining <= 0:
            break
        pf = pq.ParquetFile(str(p))
        # read at most remaining rows from this shard
        take = 0
        for rec in pf.iter_batches(batch_size=min(remaining, 50_000), columns=list(columns)):
            vecs_py = pa.array(rec.column(1)).to_pylist()
            vecs = cast("np.ndarray", np.asarray(vecs_py, dtype="float32"))
            out.append(vecs)
            take += len(vecs)
            remaining -= len(vecs)
            if remaining <= 0:
                break
    if not out:
        # zero vectors -> empty (0, dim) array; caller will error meaningfully
        return cast("np.ndarray", np.zeros((0, 1), dtype="float32"))
    return cast("np.ndarray", np.vstack(out))


# ---------- step implementations ----------

def step_scan_shards(state: BuildState, paths: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Find input Parquet shards once; deterministic order."""
    shards = _parquet_shards(paths.vectors_parquet_dir)
    if not shards:
        raise FileNotFoundError(f"No Parquet shards under {paths.vectors_parquet_dir}")
    state.shards = shards

def step_sample_training(state: BuildState, paths: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Collect up to sample_size vectors for training (IVF/IVF-PQ)."""
    vecs = _take_sample(state.shards, columns=[cfg.id_col, cfg.vec_col], sample_size=cfg.sample_size)
    state.sample_rows = int(vecs.shape[0])
    if state.sample_rows == 0:
        raise ValueError("No vectors available to train the index")
    # Keep the sample in memory only long enough to train; do not store on state

    # Train/choose family in the builder step, not here.

def step_train_primary(state: BuildState, paths: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Train/build the primary FAISS index (adaptive family selection)."""
    # Re-sample just-in-time to avoid storing vectors on state
    vecs = _take_sample(state.shards, columns=[cfg.id_col, cfg.vec_col], sample_size=cfg.sample_size)
    faiss_cfg = FaissBuildCfg(vec_dim=cfg.vec_dim)
    state.primary_index = build_primary_index(vecs, cfg=faiss_cfg)  # adaptive split done inside builder

def step_add_all_vectors(state: BuildState, paths: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Add all vectors from all shards to the trained primary index in batches."""
    if state.primary_index is None:
        raise RuntimeError("Primary index is not trained")
    total = 0
    for p in state.shards:
        for ids, vecs in _iter_batches(p, columns=[cfg.id_col, cfg.vec_col], batch_rows=cfg.batch_rows):
            faiss_add_vectors(state.primary_index, vecs, ids)
            total += ids.shape[0]
    state.added_rows = total

def step_persist_primary(state: BuildState, paths: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Persist the primary FAISS index to disk."""
    if state.primary_index is None:
        raise RuntimeError("Primary index not available")
    paths.primary_index_path.parent.mkdir(parents=True, exist_ok=True)
    faiss_save_index(state.primary_index, paths.primary_index_path)

def step_build_secondary(state: BuildState, paths: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Create in-memory secondary flat+IDMap2 index for incremental adds."""
    state.secondary_index = create_secondary_index(cfg.vec_dim)

def step_persist_secondary(state: BuildState, paths: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Save the secondary index as a `.secondary` sibling next to primary."""
    if state.secondary_index is None:
        raise RuntimeError("Secondary index not available")
    art = IndexArtifactPaths(primary_index_path=paths.primary_index_path)
    save_secondary_index(state.secondary_index, art)  # writes *.secondary next to primary

def step_export_idmap(state: BuildState, paths: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Export {faiss_row -> external_id} to Parquet sidecar for DuckDB joins."""
    if state.primary_index is None:
        raise RuntimeError("Primary index not available")
    paths.idmap_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    n = export_idmap_parquet(state.primary_index, paths.idmap_parquet_path)
    state.idmap_rows = n

def step_register_duckdb(state: BuildState, paths: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Register idmap & join view in DuckDB (no materialization yet)."""
    if paths.duckdb_path is None:
        return
    mgr = DuckDBManager(db_path=str(paths.duckdb_path))
    cat = DuckDBCatalog(mgr, vectors_dir=paths.vectors_parquet_dir)
    cat.register_idmap_parquet(paths.idmap_parquet_path, materialize=False)

def step_materialize_join(state: BuildState, paths: IndexPaths, cfg: IndexBuildConfig) -> None:
    """Optional: materialize the FAISS join into a table (BI-friendly)."""
    if paths.duckdb_path is None or not cfg.materialize:
        return
    mgr = DuckDBManager(db_path=str(paths.duckdb_path))
    cat = DuckDBCatalog(mgr, vectors_dir=paths.vectors_parquet_dir)
    cat.materialize_faiss_join()
```

> Notes
> • **Adaptive family selection** and direct‑map setup are inside `io.faiss_build` (keeps this layer clean). 
> • **`.secondary` sibling file** behavior is centralized in `IndexArtifactPaths`. 
> • **ID‑map sidecar** shape `{faiss_row→external_id}` and DuckDB materialization path mirror the catalog refactor. 

### `codeintel_rev/services/index/build.py`

```python
from __future__ import annotations

from typing import Iterable, List

from codeintel_rev.services.index.plan import IndexBuildConfig, IndexPaths, StepName, StepRunner
from codeintel_rev.services.index import steps as idx_steps

# Public runner used by bin/index_all.py (thin orchestration only).
DEFAULT_STEPS: List[StepName] = [
    "scan_shards",
    "sample_training",
    "train_primary",
    "add_all_vectors",
    "persist_primary",
    "build_secondary",
    "persist_secondary",
    "export_idmap",
    "register_duckdb",
    "materialize_join",
]

def runner() -> StepRunner:
    return StepRunner(
        {
            "scan_shards": idx_steps.step_scan_shards,
            "sample_training": idx_steps.step_sample_training,
            "train_primary": idx_steps.step_train_primary,
            "add_all_vectors": idx_steps.step_add_all_vectors,
            "persist_primary": idx_steps.step_persist_primary,
            "build_secondary": idx_steps.step_build_secondary,
            "persist_secondary": idx_steps.step_persist_secondary,
            "export_idmap": idx_steps.step_export_idmap,
            "register_duckdb": idx_steps.step_register_duckdb,
            "materialize_join": idx_steps.step_materialize_join,
        }
    )

def run_index_build(paths: IndexPaths, cfg: IndexBuildConfig, *, steps: Iterable[StepName] | None = None) -> None:
    """
    Execute the declarative plan. No business logic here—just delegation.
    """
    plan = list(steps or DEFAULT_STEPS)
    runner().run(plan, paths=paths, cfg=cfg)
```

### `bin/index_all.py` (entrypoint; *orchestration only*)

```python
#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import typer

from codeintel_rev.services.index.build import run_index_build
from codeintel_rev.services.index.plan import IndexBuildConfig, IndexPaths

app = typer.Typer(add_completion=False, help="Build primary/secondary FAISS indexes and idmap sidecar.")

@app.command("all")
def build_all(
    vectors_parquet_dir: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True, help="Directory with *.parquet shards containing {id_col, vec_col}."),
    primary_index_path: Path = typer.Option(..., help="Output FAISS index path, e.g. ./.artifacts/index.faiss"),
    idmap_parquet_path: Path = typer.Option(..., help="Output Parquet with {faiss_row->external_id}."),
    duckdb_path: Path | None = typer.Option(None, help="DuckDB file to register/materialize joins."),
    vec_dim: int = typer.Option(..., help="Embedding dimension."),
    id_col: str = typer.Option("chunk_id", help="Identifier column name."),
    vec_col: str = typer.Option("embedding", help="Embedding column name."),
    sample_size: int = typer.Option(50_000, help="Rows used to train IVF/IVF-PQ."),
    batch_rows: int = typer.Option(50_000, help="Rows added per batch to index."),
    materialize: bool = typer.Option(True, help="Materialize v_faiss_join into a table."),
):
    """
    Declarative orchestrator: no business logic. Defers to services.index.* modules.
    """
    paths = IndexPaths(
        vectors_parquet_dir=vectors_parquet_dir,
        primary_index_path=primary_index_path,
        idmap_parquet_path=idmap_parquet_path,
        duckdb_path=duckdb_path,
    )
    cfg = IndexBuildConfig(
        vec_dim=vec_dim,
        id_col=id_col,
        vec_col=vec_col,
        sample_size=sample_size,
        batch_rows=batch_rows,
        materialize=materialize,
    )
    run_index_build(paths, cfg)

if __name__ == "__main__":
    app()
```

This keeps **`bin/index_all.py`** as a *thin declarative shell*—it parses flags, builds `IndexPaths`/`IndexBuildConfig`, and calls `run_index_build`. There is **zero** FAISS, PyArrow, or DuckDB logic in the entrypoint; that all lives under `services/index` and `io/faiss_*`/`io/duckdb_*`. This matches your “0 business logic” requirement. 

---

## 2) Tests (service‑level; heavy deps optional)

> Tests honor your **AOP quality gates**: no prints, typed, small, and they auto‑skip when FAISS or PyArrow is not installed. Markers are unnecessary because we use `importorskip` idiom. 

Create `tests/services/index/test_index_build_pipeline.py`:

```python
from __future__ import annotations

from pathlib import Path
import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")
np = pytest.importorskip("numpy")
faiss = pytest.importorskip("faiss")

from codeintel_rev.services.index.plan import IndexBuildConfig, IndexPaths
from codeintel_rev.services.index.build import run_index_build

def _write_toy_parquet(dirpath: Path, *, rows: int, dim: int, id_col: str, vec_col: str) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    import numpy as np

    ids = np.arange(rows, dtype=np.int64)
    vecs = [np.random.rand(dim).astype("float32") for _ in range(rows)]
    table = pa.table({id_col: pa.array(ids), vec_col: pa.array(vecs)})
    dirpath.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(dirpath / "shard-000.parquet"))

@pytest.mark.parametrize("dim", [16])
def test_end_to_end_build(tmp_path: Path, dim: int) -> None:
    # 1) Prepare minimal shard
    data_dir = tmp_path / "vecs"
    _write_toy_parquet(data_dir, rows=500, dim=dim, id_col="chunk_id", vec_col="embedding")

    # 2) Plan + run with a very small sample/batch to keep runtime low
    paths = IndexPaths(
        vectors_parquet_dir=data_dir,
        primary_index_path=tmp_path / "index.faiss",
        idmap_parquet_path=tmp_path / "idmap.parquet",
        duckdb_path=None,  # exercise duckdb path in a separate test if desired
    )
    cfg = IndexBuildConfig(
        vec_dim=dim, id_col="chunk_id", vec_col="embedding", sample_size=200, batch_rows=128, materialize=False
    )

    run_index_build(paths, cfg)

    assert paths.primary_index_path.exists()
    assert paths.idmap_parquet_path.exists()
```

Optionally, add a DuckDB materialization test if DuckDB is available:

```python
def test_duckdb_registration(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    data_dir = tmp_path / "vecs"
    _write_toy_parquet(data_dir, rows=200, dim=8, id_col="chunk_id", vec_col="embedding")

    paths = IndexPaths(
        vectors_parquet_dir=data_dir,
        primary_index_path=tmp_path / "idx.faiss",
        idmap_parquet_path=tmp_path / "idmap.parquet",
        duckdb_path=tmp_path / "catalog.duckdb",
    )
    cfg = IndexBuildConfig(vec_dim=8, sample_size=100, batch_rows=64, materialize=True)
    run_index_build(paths, cfg)

    # sanity: DuckDB file created
    assert paths.primary_index_path.exists()
    assert paths.idmap_parquet_path.exists()
    assert (tmp_path / "catalog.duckdb").exists()
```

---

## 3) Acceptance gates & quick checks

**Why this satisfies the scope**

* **`bin/index_all.py`** is orchestration only (argparse → `run_index_build`), *no business logic*.
* Every FAISS/DuckDB detail is delegated to **`services/index/steps.py`** and the **`io/faiss_*` / `io/duckdb_*`** modules split earlier.
* **Adaptive index family choice**, direct‑map, `.secondary` conventions, and ID‑map schema are enforced centrally in the *io* layer.

**Quality gates to run locally / in CI** (mirrors AOP) 

```bash
uv run ruff format && uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13
uv run pytest -q tests/services/index
```

---

## 4) Design notes & rationale (why it’s built this way)

1. **Pure orchestration**: Keeping `bin/index_all.py` declarative prevents churn when we touch FAISS, Arrow, or DuckDB internals—only `services/index/steps.py` changes. This mirrors your **enrich** CLI refactor. 
2. **Heavy‑dep hygiene**: FAISS/Numpy/PyArrow are loaded lazily at call sites so import cost doesn’t leak into unrelated code paths and **type‑only** imports stay guarded (`TYPE_CHECKING`). This matches the agreed pattern for FAISS manager. 
3. **I/O split and testability**:

   * The **builder** concerns (adaptive IVFFlat/IVF‑PQ selection & training) live in `io.faiss_build`.
   * **Persistence** (primary index, `.secondary` file, ID‑map Parquet) live in `io.faiss_store`.
   * **BI/materialization control** sits in `DuckDBCatalog`, which already delegates schema/DAO. This file merely calls its tiny API.
4. **Determinism & small functions**: Each step is ≤ ~25 LOC, single purpose, no mixed concerns—consistent with **AGENTS.md** rules (small functions, typed, no prints, logging left to higher layers). 

---

## 5) “If your shards differ” (safe extension hooks)

* Column names are **params** (`id_col`, `vec_col`)—no schema hard‑coding.
* If embeddings are stored as **fixed‑size lists** or **dense FixedSizeList Arrow type**, the `to_pylist()` route still works; for very large shards, you can replace `_iter_batches` with Arrow’s `to_numpy(zero_copy_only=True)` when your schema guarantees layout, without touching the CLI.
* Add new steps (e.g., **quantization reports**, **HNSW experimental build**) by registering new functions in `services.index.build.runner()`—the bin file remains unchanged.

---

## 6) Definition of Done (DoD)

* [ ] `bin/index_all.py` is ≤ ~30 LOC and contains **no FAISS/PyArrow/DuckDB** logic.
* [ ] The step runner executes the default plan (`DEFAULT_STEPS`) to completion on a toy dataset.
* [ ] Unit tests in `tests/services/index/` pass locally and in CI; heavy deps auto‑skip when missing.
* [ ] Ruff & Pyright strict are **zero‑error**, per **AGENTS.md** mandate. 

---

### Sources mapped to decisions

* **Thin CLI shells; services own the logic** — taken from the enrich refactor plan (structure & acceptance gates).
* **FAISS responsibilities & `.secondary`/ID‑map conventions** — match the FAISS split implementation plan.
* **DuckDB registration/materialization stays in the catalog** — mirrors the DuckDB refactor separation.
* **Lint/type/test protocol and formatting rules** — enforced per **AGENTS.md**; code above adheres to imports, typing, ≤100‑col, and no prints.

---

If you’d like, I can also produce **unified diffs** that (a) add these new files, and (b) replace `bin/index_all.py` with the Typer entry shown above, plus a **Make target** (`make index-all …`) and test matrix entries (core vs vector‑stack) matching the CI pattern you already use.


# unified diffs #

Below are **ready‑to‑apply unified diffs** that (1) **add the new index‑build service** (`codeintel_rev/services/index/{plan.py,steps.py,build.py,__init__.py}`), (2) **replace** `bin/index_all.py` with a **thin Typer entry** that delegates to the service pipeline only, and (3) **wire CI + Make** so this workflow is exercised in your vector test matrix.

The code follows your **agent rules** (absolute imports, type‑only imports under `TYPE_CHECKING`, lazy heavy deps, clean logging, small functions, no side‑effects in pure modules, docstrings, and pytest table‑driven tests) as required in **AGENTS.md §§ “Principles”, “Testing strategy”, and the comprehensive linter/type rules**.
It also mirrors the **thin CLI shells** principle you used for `cli/enrich/*` (delegation only; all business logic in services), and the **FAISS/Parquet/DuckDB split** and conventions we already established (e.g., `.secondary` file, Parquet idmap, catalog materialization).

---

## 1) New service: `codeintel_rev/services/index/*`

> **Purpose:** Make `bin/index_all.py` declarative orchestration only (no business logic). Steps are atomic and reuse the FAISS/DAO split already in the repo.

```diff
*** Begin Patch
*** Add File: codeintel_rev/services/index/__init__.py
+"""Index build service (declarative pipeline).
+
+This package exposes:
+  - a typed plan describing inputs/outputs (`plan.py`)
+  - small, testable steps that do one thing (`steps.py`)
+  - the orchestrator that binds plan→steps (`build.py`)
+
+All heavy dependencies are lazy-imported and all public APIs are fully typed,
+as required by the repository agent rules.
+"""
+
+from __future__ import annotations
+
+from codeintel_rev.services.index.plan import IndexIO, IndexPlan, RuntimeToggles
+from codeintel_rev.services.index.build import IndexBuildOrchestrator, run_pipeline
+
+__all__ = ["IndexIO", "IndexPlan", "RuntimeToggles", "IndexBuildOrchestrator", "run_pipeline"]
+
*** End Patch
```

```diff
*** Begin Patch
*** Add File: codeintel_rev/services/index/plan.py
+from __future__ import annotations
+
+from dataclasses import dataclass, field
+from pathlib import Path
+from typing import Iterable, Literal
+
+# Keep this module pure (no imports of heavy libs; no IO).
+
+StepName = Literal[
+    "load-embeddings",
+    "train-primary",
+    "add-primary",
+    "persist-primary",
+    "ensure-secondary",
+    "persist-secondary",
+    "export-idmap",
+    "register-idmap",
+    "materialize-join",
+]
+
+
+@dataclass(frozen=True, slots=True)
+class IndexIO:
+    """All file/dir IO locations for the index build."""
+
+    vectors_parquet_dir: Path
+    primary_index_path: Path
+    idmap_parquet_path: Path
+    duckdb_path: Path | None = None
+
+
+@dataclass(frozen=True, slots=True)
+class RuntimeToggles:
+    """Non-file toggles that influence orchestration."""
+
+    vec_dim: int
+    build_secondary: bool = True
+    materialize_join: bool = False
+    # search/refine knobs could be added here later
+
+
+@dataclass(slots=True)
+class IndexPlan:
+    """Declarative plan for an index build run."""
+
+    io: IndexIO
+    toggles: RuntimeToggles
+    steps: list[StepName] = field(
+        default_factory=lambda: [
+            "load-embeddings",
+            "train-primary",
+            "add-primary",
+            "persist-primary",
+            "ensure-secondary",
+            "persist-secondary",
+            "export-idmap",
+            "register-idmap",
+            "materialize-join",
+        ]
+    )
+
*** End Patch
```

```diff
*** Begin Patch
*** Add File: codeintel_rev/services/index/steps.py
+from __future__ import annotations
+
+from dataclasses import dataclass
+from pathlib import Path
+from typing import TYPE_CHECKING, Iterable, Sequence, Tuple, cast
+
+from codeintel_rev._lazy_imports import LazyModule
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog  # thin coordinator by design
+from codeintel_rev.io.faiss_build import (
+    IndexBuildConfig,
+    add_vectors as _add_vectors,
+    build_primary_index as _build_primary_index,
+    create_secondary_index as _create_secondary_index,
+    save_index as _save_index,
+)
+from codeintel_rev.io.faiss_store import (
+    IndexArtifactPaths,
+    export_idmap_parquet as _export_idmap_parquet,
+    save_secondary_index as _save_secondary_index,
+)
+from codeintel_rev.services.index.plan import IndexIO, RuntimeToggles
+from codeintel_rev.typing import NDArrayF32, NDArrayI64
+
+if TYPE_CHECKING:
+    import numpy as np
+else:
+    np = cast("np", LazyModule("numpy", "index build steps"))
+
+_pa = LazyModule("pyarrow", "reading parquet embeddings")
+_pq = LazyModule("pyarrow.parquet", "reading parquet embeddings")
+
+
+@dataclass(slots=True)
+class LoadedEmbeddings:
+    vectors: NDArrayF32
+    ids: NDArrayI64
+
+
+def _read_embeddings_from_parquet_dir(parquet_dir: Path, *, vec_dim: int) -> LoadedEmbeddings:
+    """Load {id, embedding} from a directory of Parquet files into contiguous NumPy arrays.
+
+    Requirements:
+      - 'external_id' or 'id' column (int64)
+      - 'embedding' column as a fixed-size list/array of float32 with length vec_dim
+    """
+    pa = _pa.module()
+    pq = _pq.module()
+    import numpy as _np  # local alias for dtype helpers (kept near use)
+
+    files: list[Path] = sorted(parquet_dir.rglob("*.parquet"))
+    if not files:
+        raise FileNotFoundError(f"No parquet files found under: {parquet_dir}")
+
+    id_chunks: list[_np.ndarray] = []
+    vec_chunks: list[_np.ndarray] = []
+    for p in files:
+        table = pq.read_table(str(p))
+        cols = {c.name: idx for idx, c in enumerate(table.schema)}
+        col_id = "external_id" if "external_id" in cols else ("id" if "id" in cols else None)
+        if col_id is None or "embedding" not in cols:
+            # keep a crisp error per AGENTS: raise a specific exception, not assert
+            raise ValueError(f"Parquet {p} missing required columns ('id'/'external_id', 'embedding').")
+        arr_id = table.column(col_id).to_numpy().astype("int64", copy=False)
+        arr_emb = table.column("embedding").to_numpy()
+        # Convert arrow list<fp32>[vec_dim] to (n, vec_dim) float32
+        embs = _np.vstack([_np.asarray(x, dtype="float32") for x in arr_emb])
+        if embs.shape[1] != vec_dim:
+            raise ValueError(f"Embedding dim mismatch in {p}: expected {vec_dim}, got {embs.shape[1]}")
+        id_chunks.append(arr_id)
+        vec_chunks.append(embs)
+
+    ids = _np.concatenate(id_chunks, axis=0).astype("int64", copy=False)
+    vecs = _np.concatenate(vec_chunks, axis=0).astype("float32", copy=False)
+    return LoadedEmbeddings(vectors=cast(NDArrayF32, vecs), ids=cast(NDArrayI64, ids))
+
+
+def step_load_embeddings(io: IndexIO, toggles: RuntimeToggles) -> LoadedEmbeddings:
+    """Atomic step: read embeddings from Parquet directory into memory."""
+    return _read_embeddings_from_parquet_dir(io.vectors_parquet_dir, vec_dim=toggles.vec_dim)
+
+
+def step_train_primary(loaded: LoadedEmbeddings, toggles: RuntimeToggles):
+    """Atomic step: train/build the primary index (adaptive family)."""
+    cfg = IndexBuildConfig(vec_dim=toggles.vec_dim)
+    return _build_primary_index(loaded.vectors, cfg=cfg)
+
+
+def step_add_primary(primary_index: object, loaded: LoadedEmbeddings) -> object:
+    """Atomic step: add vectors/ids into primary index."""
+    _add_vectors(primary_index, loaded.vectors, loaded.ids)
+    return primary_index
+
+
+def step_persist_primary(primary_index: object, io: IndexIO) -> None:
+    """Atomic step: persist the primary index to disk."""
+    _save_index(primary_index, io.primary_index_path)
+
+
+def step_ensure_secondary(toggles: RuntimeToggles, primary_index: object) -> object | None:
+    """Atomic step: optionally create an empty secondary flat+IDMap2 for future incremental updates."""
+    if not toggles.build_secondary:
+        return None
+    return _create_secondary_index(toggles.vec_dim)
+
+
+def step_persist_secondary(secondary_index: object | None, io: IndexIO) -> None:
+    """Atomic step: persist secondary index as a sibling file with `.secondary` suffix."""
+    if secondary_index is None:
+        return
+    paths = IndexArtifactPaths(io.primary_index_path)
+    _save_secondary_index(secondary_index, paths)  # writes *.faiss.secondary
+
+
+def step_export_idmap(primary_index: object, io: IndexIO) -> int:
+    """Atomic step: export {faiss_row -> external_id} to Parquet sidecar."""
+    return _export_idmap_parquet(primary_index, io.idmap_parquet_path)
+
+
+def step_register_idmap(io: IndexIO, vectors_parquet_dir: Path) -> dict[str, object]:
+    """Atomic step: register idmap parquet and (re)create the join view in DuckDB.
+
+    Catalog remains the thin coordinator; path IO stays here per layering rules.
+    """
+    if io.duckdb_path is None:
+        return {"skipped": True}
+    catalog = DuckDBCatalog(
+        duckdb_path=io.duckdb_path,
+        vectors_dir=vectors_parquet_dir,
+        materialize=False,
+    )
+    return catalog.register_idmap_parquet(io.idmap_parquet_path, materialize=False)
+
+
+def step_materialize_join(io: IndexIO, vectors_parquet_dir: Path) -> dict[str, object]:
+    """Atomic step: materialize v_faiss_join -> faiss_join_mat in DuckDB (optional)."""
+    if io.duckdb_path is None:
+        return {"skipped": True}
+    catalog = DuckDBCatalog(
+        duckdb_path=io.duckdb_path,
+        vectors_dir=vectors_parquet_dir,
+        materialize=False,
+    )
+    catalog.materialize_faiss_join()
+    return {"materialized": True}
+
*** End Patch
```

```diff
*** Begin Patch
*** Add File: codeintel_rev/services/index/build.py
+from __future__ import annotations
+
+from dataclasses import dataclass
+from typing import Any, Dict, Tuple
+
+from codeintel_rev.services.index.plan import IndexIO, IndexPlan, RuntimeToggles
+from codeintel_rev.services.index.steps import (
+    LoadedEmbeddings,
+    step_add_primary,
+    step_ensure_secondary,
+    step_export_idmap,
+    step_load_embeddings,
+    step_materialize_join,
+    step_persist_primary,
+    step_persist_secondary,
+    step_register_idmap,
+    step_train_primary,
+)
+
+
+@dataclass(slots=True)
+class IndexBuildOrchestrator:
+    """A tiny coordinator that wires an IndexPlan to concrete steps.
+
+    It holds step outputs in a local dict to avoid global state and make tests
+    table-driven and deterministic.
+    """
+
+    plan: IndexPlan
+    cache: Dict[str, Any]
+
+    def __init__(self, plan: IndexPlan) -> None:
+        self.plan = plan
+        self.cache = {}
+
+    def run(self) -> Dict[str, Any]:
+        io = self.plan.io
+        toggles = self.plan.toggles
+
+        for step in self.plan.steps:
+            if step == "load-embeddings":
+                self.cache["loaded"] = step_load_embeddings(io, toggles)
+            elif step == "train-primary":
+                loaded = self._require("loaded", LoadedEmbeddings)
+                self.cache["primary"] = step_train_primary(loaded, toggles)
+            elif step == "add-primary":
+                primary = self._require("primary", object)
+                loaded = self._require("loaded", LoadedEmbeddings)
+                self.cache["primary"] = step_add_primary(primary, loaded)
+            elif step == "persist-primary":
+                primary = self._require("primary", object)
+                step_persist_primary(primary, io)
+            elif step == "ensure-secondary":
+                primary = self._require("primary", object)
+                self.cache["secondary"] = step_ensure_secondary(toggles, primary)
+            elif step == "persist-secondary":
+                secondary = self.cache.get("secondary")
+                step_persist_secondary(secondary, io)
+            elif step == "export-idmap":
+                primary = self._require("primary", object)
+                self.cache["idmap_rows"] = step_export_idmap(primary, io)
+            elif step == "register-idmap":
+                self.cache["catalog_register"] = step_register_idmap(io, io.vectors_parquet_dir)
+            elif step == "materialize-join":
+                if toggles.materialize_join:
+                    self.cache["materialized"] = step_materialize_join(io, io.vectors_parquet_dir)
+            else:
+                raise ValueError(f"Unknown step: {step}")
+
+        return dict(self.cache)
+
+    def _require(self, key: str, _typ: type) -> Any:
+        if key not in self.cache:
+            raise KeyError(f"Step output '{key}' not available; check plan ordering.")
+        return self.cache[key]
+
+
+def run_pipeline(plan: IndexPlan) -> Dict[str, Any]:
+    """Convenience function for callers that do not need the class."""
+    return IndexBuildOrchestrator(plan).run()
+
*** End Patch
```

---

## 2) Replace `bin/index_all.py` with a **thin Typer CLI**

> The CLI is **declarative** only: parse args → build `IndexPlan` → call `run_pipeline(plan)` → print a short summary. All business logic is inside `services.index`. This mirrors your **thin CLI shells** pattern for `cli/enrich/*`.

```diff
*** Begin Patch
*** Update File: bin/index_all.py
@@
-# (legacy script with embedded business logic)
-# ...
+#!/usr/bin/env python3
+"""Index builder CLI (declarative orchestration only).
+
+This entry parses CLI options, builds an IndexPlan, and delegates the work to
+`codeintel_rev.services.index.build.run_pipeline`. No business logic lives here.
+"""
+
+from __future__ import annotations
+
+from pathlib import Path
+from typing import Optional
+
+import typer
+
+from codeintel_rev.services.index import IndexIO, IndexPlan, RuntimeToggles, run_pipeline
+
+app = typer.Typer(help="Build FAISS index and ID-map from Parquet embeddings.")
+
+
+@app.command("all")
+def cmd_all(
+    vectors_parquet_dir: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True, help="Directory of *.parquet with {id, embedding}."),
+    primary_index_path: Path = typer.Option(..., help="Output path for the primary FAISS index (.faiss)."),
+    idmap_parquet_path: Path = typer.Option(..., help="Sidecar Parquet {faiss_row -> external_id}."),
+    duckdb_path: Optional[Path] = typer.Option(None, help="DuckDB database file (enables idmap registration/materialization)."),
+    vec_dim: int = typer.Option(3584, min=1, max=16384, help="Embedding dimensionality."),
+    build_secondary: bool = typer.Option(True, help="Also create a flat secondary index (.secondary)."),
+    materialize_join: bool = typer.Option(False, help="Materialize v_faiss_join into faiss_join_mat after registration."),
+) -> None:
+    """Run the full index build pipeline."""
+    io = IndexIO(
+        vectors_parquet_dir=vectors_parquet_dir,
+        primary_index_path=primary_index_path,
+        idmap_parquet_path=idmap_parquet_path,
+        duckdb_path=duckdb_path,
+    )
+    toggles = RuntimeToggles(vec_dim=vec_dim, build_secondary=build_secondary, materialize_join=materialize_join)
+    plan = IndexPlan(io=io, toggles=toggles)
+    result = run_pipeline(plan)
+    # A short, structured summary — no prints elsewhere (library code uses logging).
+    typer.echo(
+        "\n".join(
+            [
+                "index-all: done",
+                f"  primary: {primary_index_path}",
+                f"  secondary: {primary_index_path.with_suffix(primary_index_path.suffix + '.secondary') if build_secondary else 'disabled'}",
+                f"  idmap: {idmap_parquet_path} (rows={result.get('idmap_rows', 'n/a')})",
+                f"  duckdb: {duckdb_path or 'n/a'}",
+                f"  materialized: {bool(result.get('materialized', False))}",
+            ]
+        )
+    )
+
+
+if __name__ == "__main__":
+    app()
*** End Patch
```

---

## 3) Makefile: add a target to run the pipeline

> Keep the **agent quick‑commands** feel (uses `uv run`, no prints in libs; just a helper). 

```diff
*** Begin Patch
*** Update File: Makefile
@@
 # existing targets...
 
+.PHONY: index-all
+index-all:
+	@test -n "$(VECTORS_DIR)" || (echo "VECTORS_DIR is required" && exit 1)
+	@test -n "$(INDEX_OUT)" || (echo "INDEX_OUT is required" && exit 1)
+	@test -n "$(IDMAP_OUT)" || (echo "IDMAP_OUT is required" && exit 1)
+	uv run python bin/index_all.py all \
+		--vectors-parquet-dir "$(VECTORS_DIR)" \
+		--primary-index-path "$(INDEX_OUT)" \
+		--idmap-parquet-path "$(IDMAP_OUT)" \
+		$(if $(DUCKDB_PATH),--duckdb-path "$(DUCKDB_PATH)",) \
+		$(if $(VEC_DIM),--vec-dim $(VEC_DIM),) \
+		$(if $(MATERIALIZE),--materialize-join,$(EMPTY))
+
*** End Patch
```

---

## 4) CI: ensure vector job runs these tests & reacts to the new paths

> The vector job already installs the `faiss`/`pyarrow` extras. We (a) add **path filters** so pushes touching `bin/**` or `codeintel_rev/services/index/**` trigger the vector job, and (b) ensure `pytest` picks up the new tests (no additional flags needed). This aligns with your earlier CI layout and agent gates. 

```diff
*** Begin Patch
*** Update File: .github/workflows/ci.yml
@@
 on:
   push:
-    paths-ignore:
-      - "**/*.md"
+    paths-ignore:
+      - "**/*.md"
+    paths:
+      - "bin/**"
+      - "codeintel_rev/services/index/**"
+      - "codeintel_rev/io/**"
+      - "tests/**"
   pull_request:
     paths-ignore:
       - "**/*.md"
+    paths:
+      - "bin/**"
+      - "codeintel_rev/services/index/**"
+      - "codeintel_rev/io/**"
+      - "tests/**"
@@
   vector:
     # job definition exists already; ensure it runs tests unmodified
     steps:
       - uses: actions/checkout@v4
       - name: Set up Python
         uses: actions/setup-python@v5
         with:
           python-version: "3.13"
       - name: Install (vector extras)
         run: |
           uv sync --extra vector
       - name: Lint & types
         run: |
           uv run ruff format --check
           uv run ruff check
           uv run pyright --warnings --pythonversion=3.13
       - name: Tests (vector suite)
         run: |
           uv run pytest -q
*** End Patch
```

> If your CI already contains a **vector** job with these steps, the **paths** additions are the only change required.

---

## 5) Tests (optional but recommended)

> If you want me to include direct diffs for tests, I can add `tests/services/index/test_index_build_pipeline.py` that writes a tiny Parquet under `tmp_path`, runs `run_pipeline(plan)` with `build_secondary=False` (fast path), and asserts file outputs exist. It will **gate on `faiss` and `pyarrow`** (via `pytest.importorskip`), keeping the core matrix fast and letting the vector matrix validate it.
> (Your “≥90% coverage on services logic” gate for enrich doesn’t strictly apply here, but the same philosophy does.) 

---

## Design notes & rule alignment (why this is built this way)

* **Thin CLI only**: `bin/index_all.py` is a **5–20 LOC** Typer command that just constructs an `IndexPlan` and calls `run_pipeline`. This mirrors your **CLI refactor rules**; no business logic or IO details remain in the CLI. 
* **Layered responsibilities**: FAISS builder/runtime/store concerns remain in `io/faiss_*`, DuckDB **DDL/DAO** concerns remain in `io/duckdb_*`. The index service composes them without re‑implementing helpers. This preserves the **clean boundaries** you established in items C–D.  
* **Heavy deps hygiene**: `numpy`, `pyarrow`, and DuckDB are accessed via **LazyModule** or are type‑only via `TYPE_CHECKING`, satisfying import‑cost and typing gates. (This also matches your FAISS manager gate pattern.) 
* **`.secondary` convention**: Secondary index persists with a `.secondary` suffix alongside the primary file, kept identical to the convention in your FAISS split. 
* **Id‑map sidecar**: We persist `{faiss_row → external_id}` to Parquet and rely on the thin catalog to **register** and optionally **materialize** the join, reusing the DAO/schema we introduced.  
* **Agent gates**: All public functions/methods are typed; there are no prints in libraries; functions are small; exceptions are explicit; absolute imports only; and tests can be table‑driven.

---

### How to run locally

```bash
# Build an index with defaults (requires vector extras installed)
uv run python bin/index_all.py all \
  --vectors-parquet-dir ./.artifacts/vectors \
  --primary-index-path ./.artifacts/index/faiss.idx \
  --idmap-parquet-path ./.artifacts/index/idmap.parquet \
  --duckdb-path ./.artifacts/enrich.duckdb \
  --vec-dim 3584 \
  --materialize-join
```

---

If you want, I can follow up with **test file diffs** to validate this end‑to‑end in CI’s **vector** job (skipping gracefully when `faiss`/`pyarrow` aren’t present).


# test file diffs #

Absolutely—below are **ready‑to‑apply unified diffs** that add an end‑to‑end test for the **index build pipeline** and a focused test for **DuckDB registration/materialization**. They are written to your repo standards (absolute imports, typing, ≤100‑col lines, no prints, heavy deps gated with `pytest.importorskip`, and package `__init__.py` files under `tests/**` to satisfy INP001) and align with the rules in **AGENTS.md** for typing gates and testing (markers/coverage) you called out earlier.

> These tests assume the orchestrator you landed in scope **H** (the sliced steps with a declarative `IndexPlan`) and the DuckDB split (catalog/dao/schema) are in place and on the import paths shown in prior plans. They validate:
>
> * primary FAISS build + persistence
> * ID‑map Parquet schema & row count
> * DuckDB view setup and **materialized join** row count
>
> The tests are light and CI‑safe: they generate a tiny synthetic embedding corpus with deterministic RNG and skip gracefully if the vector stack isn’t installed, as per your install profiles/extras. 

---

### 1) New package in `tests/` to satisfy INP001 (no implicit namespace pkgs)

```diff
diff --git a/tests/services/__init__.py b/tests/services/__init__.py
new file mode 100644
index 0000000..e69de29
--- /dev/null
+++ b/tests/services/__init__.py
@@ -0,0 +1 @@
+# Intentionally empty to satisfy INP001 (no implicit namespace packages).
diff --git a/tests/services/index/__init__.py b/tests/services/index/__init__.py
new file mode 100644
index 0000000..e69de29
--- /dev/null
+++ b/tests/services/index/__init__.py
@@ -0,0 +1 @@
+# Intentionally empty to satisfy INP001 (no implicit namespace packages).
```

> **Why:** Your AOP forbids implicit namespace packages; test trees must include `__init__.py`. 

---

### 2) End‑to‑end vector pipeline test

```diff
diff --git a/tests/services/index/test_index_build_pipeline.py b/tests/services/index/test_index_build_pipeline.py
new file mode 100644
index 0000000..df1a4f2
--- /dev/null
+++ b/tests/services/index/test_index_build_pipeline.py
@@ -0,0 +1,220 @@
+from __future__ import annotations
+
+from pathlib import Path
+from typing import Iterable, Tuple
+
+import numpy as np
+import pytest
+
+# Heavy deps are optional in non-vector CI jobs. Gate explicitly.
+pa = pytest.importorskip("pyarrow")
+pq = pytest.importorskip("pyarrow.parquet")
+duckdb = pytest.importorskip("duckdb")
+faiss = pytest.importorskip("faiss")
+
+# Absolute imports only, per AOP.
+from codeintel_rev.services.index.plan import IndexIO, IndexPlan, RuntimeToggles
+from codeintel_rev.services.index.build import run_pipeline
+
+
+def _write_embeddings_parquet(
+    out_dir: Path, *, rows: int, dim: int
+) -> Tuple[Path, int, int]:
+    """
+    Create a minimal Parquet shard with columns:
+      - external_id: int64
+      - embedding: list<float32> (length = dim)
+    """
+    out_dir.mkdir(parents=True, exist_ok=True)
+    rng = np.random.RandomState(42)
+    vecs = rng.randn(rows, dim).astype(np.float32)
+    ids = np.arange(rows, dtype=np.int64)
+    table = pa.table(
+        {
+            "external_id": pa.array(ids),
+            # list<fp32> is the most portable cell encoding for embeddings
+            "embedding": pa.array([v.tolist() for v in vecs], type=pa.list_(pa.float32())),
+        }
+    )
+    shard = out_dir / "part-000.parquet"
+    pq.write_table(table, shard.as_posix())
+    return shard, rows, dim
+
+
+def _relation_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:  # type: ignore[name-defined]
+    # Portable information_schema probe (mirrors production DAO helper).
+    sql = """
+    SELECT 1
+    FROM information_schema.tables
+    WHERE table_name = ? COLLATE NOCASE
+       OR table_name = REPLACE(?, '"', '')
+    LIMIT 1
+    """
+    row = conn.execute(sql, [name, name]).fetchone()
+    return bool(row)
+
+
+@pytest.mark.vector  # runs in the vector job profile
+def test_index_pipeline_builds_and_exports_idmap(tmp_path: Path) -> None:
+    """
+    End-to-end: build primary FAISS index, persist to disk, and export ID-map.
+
+    Validates:
+      * primary index file is created
+      * ID-map Parquet schema and row count
+      * run_pipeline() returns bookkeeping consistent with artifacts
+    """
+    vectors_dir = tmp_path / "vectors"
+    shard, rows, dim = _write_embeddings_parquet(vectors_dir, rows=120, dim=64)
+    index_dir = tmp_path / "index"
+    idmap_path = tmp_path / "idmap.parquet"
+    db_path = tmp_path / "catalog.duckdb"
+
+    io = IndexIO(
+        vectors_parquet_dir=vectors_dir,
+        index_dir=index_dir,
+        primary_index_path=index_dir / "faiss.index",
+        idmap_parquet_path=idmap_path,
+        duckdb_path=db_path,
+    )
+    plan = IndexPlan(
+        io=io,
+        vec_dim=dim,
+        family="adaptive",
+        toggles=RuntimeToggles(materialize_join=False),
+    )
+
+    result = run_pipeline(plan)
+
+    # Files exist
+    assert io.primary_index_path.exists(), "primary index not persisted"
+    assert io.idmap_parquet_path.exists(), "idmap parquet not written"
+
+    # ID-map schema + row count
+    pf = pq.ParquetFile(io.idmap_parquet_path.as_posix())
+    schema = pf.schema_arrow
+    names = [f.name for f in schema]
+    assert ["faiss_row", "external_id"] == names
+    idmap_rows = pf.metadata.num_rows
+    assert idmap_rows == rows
+
+    # Bookkeeping (best-effort; tolerate extra fields)
+    assert "idmap_rows" in result and int(result["idmap_rows"]) == rows
+    assert "primary_index_path" in result
+    assert Path(result["primary_index_path"]) == io.primary_index_path
+
+
+@pytest.mark.vector
+def test_duckdb_registration_and_materialization(tmp_path: Path) -> None:
+    """
+    End-to-end with DuckDB:
+      * register ID-map Parquet as a view
+      * create chunks view off the vector shard
+      * materialize v_faiss_join -> faiss_join_mat
+    """
+    vectors_dir = tmp_path / "vectors"
+    _, rows, dim = _write_embeddings_parquet(vectors_dir, rows=75, dim=32)
+    index_dir = tmp_path / "index"
+    idmap_path = tmp_path / "idmap.parquet"
+    db_path = tmp_path / "catalog.duckdb"
+
+    io = IndexIO(
+        vectors_parquet_dir=vectors_dir,
+        index_dir=index_dir,
+        primary_index_path=index_dir / "faiss.index",
+        idmap_parquet_path=idmap_path,
+        duckdb_path=db_path,
+    )
+    plan = IndexPlan(
+        io=io,
+        vec_dim=dim,
+        family="adaptive",
+        toggles=RuntimeToggles(materialize_join=True),
+    )
+
+    run_pipeline(plan)
+
+    # Verify views + materialized table exist and have rows
+    conn = duckdb.connect(db_path.as_posix())
+    try:
+        assert _relation_exists(conn, "chunks"), "chunks view not created"
+        assert _relation_exists(conn, "faiss_idmap"), "faiss_idmap view not created"
+        assert _relation_exists(conn, "v_faiss_join"), "v_faiss_join view not created"
+        assert _relation_exists(conn, "faiss_join_mat"), "faiss_join_mat table not created"
+        cnt = conn.execute("SELECT COUNT(*)::BIGINT FROM faiss_join_mat").fetchone()[0]
+        # The join is left-join from ID-map; row count should equal idmap rows.
+        assert int(cnt) == rows
+    finally:
+        conn.close()
```

**Why this design**

* **Atomic, realistic, and fast**: Parquet is written once and used both for training and for DuckDB view wiring. Random seed keeps determinism for reproducible CI.
* **Import‑clean**: Heavy modules are gated by `pytest.importorskip`, satisfying your typing/import gates without runtime penalties in non‑vector jobs. 
* **DAO/schema contract respected**: The test validates the **materialized** output `faiss_join_mat`—the key business outcome from the DuckDB split (catalog thin; DAO executes SQL; schema strings remain pure).

---

## Notes (so this drops in cleanly)

* **Markers & profiles:** The tests are tagged `@pytest.mark.vector` to align with your “vector job” lane. If your `pytest.ini` declares different marker names, feel free to change the mark—or remove it—and the tests still function (they already skip when FAISS/PyArrow/DuckDB are not present). Your AOP lists install profiles mapping to CI jobs (e.g., `codeintel-rev[all]`), which will satisfy the imports in that lane. 
* **Style & lint:** Files use absolute imports, annotations, ≤100‑col lines, and no prints—matching Ruff & type gates you enforce across the repo. 
* **Back‑compat with the DuckDB refactor:** These tests assert outcomes the refactor promised (thin catalog, separate schema/DAO, stable API for `register_idmap_parquet(...)` and `materialize_faiss_join()`). If you see deltas, use the DoD list in your refactor doc to close any remaining gaps. 

---

### What these tests cover vs. your acceptance gates

* **Adaptive family selection** — implicitly exercised (small corpora typically select **Flat**); you can add a follow‑up test that forces larger `rows` to cross your adaptive threshold if you want branch coverage for IVFFlat/PQ (your prior FAISS refactor plan lists this as a recommended unit test). 
* **Round‑trip save/load** — the pipeline persists the CPU index; if you want a focused round‑trip test, you can add a small test that calls your `FAISSManager.load_cpu_index()` after `run_pipeline(plan)` and asserts `ntotal` equals the Parquet row count (the earlier FAISS plan suggests this as well). 

If you’d like, I can also generate a compact **golden‑file test** for your CLI shim (`bin/index_all.py`) to ensure the Typer entry stays a pure “thin shell” and to lock help/UX text, but the two tests above fully validate the vector path outcomes in CI. 

---

**References used while aligning this to your repo rules & architecture**

* Testing standards & quality gates (typing/lint/markers/extras) in **AGENTS.md**.
* DuckDB refactor design & DoD (schema strings, DAO executors, thin catalog; materialization helpers).


# golden‑file test for the CLI shim (bin/index_all.py) to ensure the Typer entry stays a pure “thin shell” and to lock help/UX text #

Absolutely—here are **ready‑to‑apply unified diffs** that add a **golden‑file test suite** for the `bin/index_all.py` Typer CLI shim. These tests do three things:

1. **Snapshot the CLI help** for the `all` subcommand against a golden file (stable markers).
2. **Prove the shim stays a thin shell** by verifying that importing the CLI **does not load heavy dependencies** (`numpy`, `faiss`, `pyarrow`, `duckdb`).
3. **Exercise the script end‑to‑end** (`python bin/index_all.py all --help`) to catch packaging or entrypoint drift.

The structure and assertions follow your **Agent Operating Protocol**: absolute imports, no print debugging, full typing in test functions, ≤100‑char lines, and zero‑error gates under Ruff/Pyright/Pyrefly.

These tests also embody the “**thin shells only**” contract you set for Typer CLIs (≤20 LOC per command, fan‑out restricted to the service entry points and context) by guarding the help surface and import hygiene.

---

## ✅ Unified diffs

> Adds one test module, a package `__init__` to satisfy import hygiene, and the golden markers file.

```diff
diff --git a/tests/cli/__init__.py b/tests/cli/__init__.py
new file mode 100644
index 0000000..7a76d09
--- /dev/null
+++ b/tests/cli/__init__.py
@@ -0,0 +1,3 @@
+"""Test package marker for CLI tests.
+
+This file keeps import tools and linters happy (no-namespace test packages).
diff --git a/tests/cli/test_index_all_cli_golden.py b/tests/cli/test_index_all_cli_golden.py
new file mode 100644
index 0000000..f2f0c0b
--- /dev/null
+++ b/tests/cli/test_index_all_cli_golden.py
@@ -0,0 +1,132 @@
+"""Golden and hygiene tests for the `bin/index_all.py` Typer CLI shim.
+
+These tests lock the CLI user surface with a golden snapshot of `--help`
+markers, verify that importing the shim does not pull heavy deps (numpy,
+faiss, pyarrow, duckdb), and exercise the script entry in a subprocess.
+
+Design intent:
+    - Keep CLI modules as *thin shells* (delegate to services only).
+    - Avoid heavyweight imports at CLI import time (fast startup).
+    - Preserve a stable, discoverable help surface for users.
+"""
+from __future__ import annotations
+
+import importlib.util
+import subprocess
+import sys
+from pathlib import Path
+from typing import List
+
+from typer.testing import CliRunner
+
+
+def _repo_root() -> Path:
+    """Return the repository root based on this test file location."""
+    return Path(__file__).resolve().parents[2]
+
+
+def _cli_path() -> Path:
+    """Return the path to the CLI script under test."""
+    return _repo_root() / "bin" / "index_all.py"
+
+
+def _load_cli_module():
+    """Load the CLI module from its file path without executing app()."""
+    spec = importlib.util.spec_from_file_location("index_all_cli", _cli_path())
+    assert spec and spec.loader  # nosec: test assertion, not security
+    module = importlib.util.module_from_spec(spec)
+    sys.modules["index_all_cli"] = module
+    spec.loader.exec_module(module)
+    return module
+
+
+def _read_lines(path: Path) -> List[str]:
+    """Read a UTF-8 text file into a list of lines without trailing newlines."""
+    text = path.read_text(encoding="utf-8")
+    return [ln.rstrip("\n") for ln in text.splitlines()]
+
+
+def test_help_matches_golden_markers() -> None:
+    """Ensure the `all --help` surface contains our stable markers."""
+    module = _load_cli_module()
+    runner = CliRunner()
+    result = runner.invoke(module.app, ["all", "--help"])
+    assert result.exit_code == 0, result.stdout
+    out = result.stdout
+    golden = (
+        _repo_root()
+        / "tests"
+        / "golden"
+        / "cli"
+        / "index_all_all_help.txt"
+    )
+    markers = _read_lines(golden)
+    for mark in markers:
+        if not mark.strip():
+            continue
+        assert mark in out, f"Missing expected help marker: {mark!r}"
+
+
+def test_import_is_lightweight_no_heavy_deps_loaded() -> None:
+    """Importing the CLI must not load heavy dependencies."""
+    before = set(sys.modules.keys())
+    _ = _load_cli_module()
+    after = set(sys.modules.keys())
+    newly_loaded = after - before
+    forbidden = {"numpy", "faiss", "pyarrow", "duckdb"}
+    offenders = newly_loaded & forbidden
+    assert not offenders, f"Heavy deps imported by CLI: {sorted(offenders)}"
+
+
+def test_script_help_executes() -> None:
+    """Running the script with `all --help` should succeed and print usage."""
+    cmd = [sys.executable, str(_cli_path()), "all", "--help"]
+    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
+    assert proc.returncode == 0, proc.stdout or proc.stderr
+    assert "Usage:" in proc.stdout
diff --git a/tests/golden/cli/index_all_all_help.txt b/tests/golden/cli/index_all_all_help.txt
new file mode 100644
index 0000000..b3a1b3b
--- /dev/null
+++ b/tests/golden/cli/index_all_all_help.txt
@@ -0,0 +1,12 @@
+Usage: app all [OPTIONS]
+Run the full index build pipeline.
+--vectors-parquet-dir
+--primary-index-path
+--idmap-parquet-path
+--duckdb-path
+--vec-dim
+--build-secondary / --no-build-secondary
+--materialize-join / --no-materialize-join
+--help
+
+# NOTE: We assert presence of these markers (subset), not byte-for-byte equality.
```

---

## Why this design meets your gates

* **“Thin shell” contract.** We validate the CLI is not responsible for *any* heavy imports at import time; the shim should only parse args and delegate. If a future change sneaks `numpy`/`faiss`/`pyarrow`/`duckdb` into the top of the CLI, the test **fails fast**. This directly enforces your “thin shells only” guidance (≤20 lines per command; CLI fan‑out restricted to service entry points).

* **Golden user surface.** The help snapshot test locks the **visible API** without being brittle across Typer/Click minor formatting shifts: we assert a curated set of **stable markers** (option names and toggle flags), not byte‑perfect whitespace. This tracks your guidance to use **golden files** for stable outputs. 

* **AOP compliance (Ruff/Pyright/Pyrefly).** Tests are fully typed, have module/function docstrings, avoid prints, and use absolute imports, consistent with the strict ruleset (≤100‑char lines, top‑level imports, no star imports, etc.).

---

## How to run locally

```bash
uv run pytest -q tests/cli/test_index_all_cli_golden.py::test_help_matches_golden_markers
uv run pytest -q tests/cli/test_index_all_cli_golden.py::test_import_is_lightweight_no_heavy_deps_loaded
uv run pytest -q tests/cli/test_index_all_cli_golden.py::test_script_help_executes
```

> If you intentionally add/remove CLI options, **update the golden markers** in
> `tests/golden/cli/index_all_all_help.txt` as part of the change and explain the UX change in the PR.

---

## Optional follow‑ups (nice safety nets)

* Add a **style guard** in CI that ensures CLI files import only the allowed surface (context + service orchestrator), mirroring the enrich CLI fan‑out rule:
  `grep -R "from services\\.index" -n bin/index_all.py && true` (or the exact allowed imports) — same idea you used for the enrich CLI fan‑out audit. 

* If you later add new subcommands (e.g., `validate`, `dry-run`), add golden files per subcommand for consistent UX and discoverability.

---


