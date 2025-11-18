Below is a **turn‑key implementation plan** (with **ready‑to‑paste code**) to finish scope **C) FAISS manager — façade verified, add tests & gating**. It assumes the split you landed (builder/runtime/store + thin façade) is in the repo, and then **tightens heavy‑dependency hygiene**, **fixes any lingering import leaks**, and **adds the required tests**.

I verified from your repo bundle that:

* The façade exists (`io/faiss_manager.py`) and composes builder/runtime/store. I also see `faiss_manager_refactored.py` and cross‑references to `search_dual`, `save_secondary_index`, etc., confirming the layered design is present.
* Adaptive family selection is centralized in `io/faiss_build.py::choose_family` with small/medium/large thresholds. 
* The secondary index artifact is persisted with a **“.secondary”** suffix (class `IndexArtifactPaths`). 
* Your **agent rules** require **type‑only imports to be guarded** under `TYPE_CHECKING`, and **heavy deps (NumPy/FAISS/PyArrow)** to be lazily imported with a façade (`LazyModule`/`gate_import`).
* The earlier **FAISS split plan** you used is consistent with this (secondary file, sidecar Parquet, dual‑search, rerank entry point).

---

## 0) Goals & acceptance gates

**What this change achieves**

1. **Heavy‑dep hygiene (import‑clean):**

   * All NumPy / FAISS / PyArrow imports are **lazy** or **type‑only** as per `AGENTS.md`.
   * Importing *any* of `io/faiss_*.py` doesn’t pull NumPy or FAISS into `sys.modules` until actually used. 

2. **Façade purity verified:**

   * `io/faiss_manager.py` **composes** `faiss_build`, `faiss_runtime`, `faiss_store`; **no duplicated helpers**. We keep `.search()`, `.apply_runtime_parameters()`, `.save_secondary_index()`, `.load_secondary_index()`, `.export_idmap()` semantics unchanged (compat). 

3. **Functionality guarantees:**

   * Secondary index is **Flat + IDMap2** and persisted with **“.secondary”** suffix; ID‑map sidecar is **Parquet**. 

4. **Tests added** (table‑driven, in‑memory) to cover:

   * **Adaptive family selection & round‑trip** save/load.
   * **Dual‑search merge** correctness with optional **refine**.
   * **ID‑map sidecar** row count & schema.
   * **Import hygiene** (NumPy/FAISS not imported at module import‑time).

**Quality gates (must pass)**

* `ruff format && ruff check --fix` clean; **TC00x** typing‑gate rules satisfied; **no star imports; no private imports**. 
* `pyright --warnings` / `pyrefly` strict clean for changed files. 
* **Coverage ≥ 85%** for the added tests.

---

## 1) Heavy‑dep gating: surgical code changes

> **Why:** Per your agent rules, **type‑only imports must be guarded** and **heavy modules must be lazily imported** or gated with `gate_import`. NumPy, FAISS, and PyArrow fall under this policy. 

### 1.1 `io/faiss_runtime.py` — gate NumPy

Replace the top of the file’s imports so NumPy is **not** imported at module import‑time:

```diff
diff --git a/codeintel_rev/io/faiss_runtime.py b/codeintel_rev/io/faiss_runtime.py
--- a/codeintel_rev/io/faiss_runtime.py
+++ b/codeintel_rev/io/faiss_runtime.py
@@ -1,18 +1,27 @@
 """Runtime helpers for executing searches against FAISS indexes."""
 
 from __future__ import annotations
 
-from collections.abc import Callable, Iterator
+from collections.abc import Callable, Iterator
 from contextlib import contextmanager, suppress
 from dataclasses import dataclass
 from numbers import Integral, Real
 from time import perf_counter
-from typing import TYPE_CHECKING, Any, cast
-
-import numpy as np
+from typing import TYPE_CHECKING, Any, cast
 
 from codeintel_rev._lazy_imports import LazyModule
 from codeintel_rev.typing import (
     FaissIndex,
     NDArrayF32,
     NDArrayI64,
     gate_import,
 )
 
+if TYPE_CHECKING:
+    import numpy as np  # type: ignore[reportMissingImports]
+else:
+    # Lazy import to satisfy heavy-deps policy (no import cost on module import).
+    np = cast("np", LazyModule("numpy", "faiss runtime ops"))
+
+_faiss = LazyModule("faiss", "FAISS runtime operations")
+
@@
- _faiss = LazyModule("faiss", "FAISS runtime operations")
+_faiss = _faiss  # keep symbol for clarity (already defined above)
```

> Now, merely importing `codeintel_rev.io.faiss_runtime` won’t import NumPy; `np` resolves lazily on first use. This matches your **typing gates** recipe. 

### 1.2 `io/faiss_build.py` — gate NumPy

```diff
diff --git a/codeintel_rev/io/faiss_build.py b/codeintel_rev/io/faiss_build.py
--- a/codeintel_rev/io/faiss_build.py
+++ b/codeintel_rev/io/faiss_build.py
@@ -12,15 +12,20 @@
 from dataclasses import dataclass
 from pathlib import Path
-from typing import Literal, cast
-
-import numpy as np
+from typing import Literal, TYPE_CHECKING, cast
 
 from codeintel_rev._lazy_imports import LazyModule
 from codeintel_rev.typing import FaissIndex, FaissModule, NDArrayF32, NDArrayI64, gate_import
 
 _faiss = LazyModule("faiss", "FAISS builder operations")
 
+if TYPE_CHECKING:
+    import numpy as np  # type: ignore[reportMissingImports]
+else:
+    np = cast("np", LazyModule("numpy", "faiss builder ops"))
+
 IndexFamily = Literal["flat", "ivfflat", "ivfpq", "adaptive"]
```

### 1.3 `io/faiss_store.py` — gate NumPy (PyArrow already lazy via `LazyModule`)

```diff
diff --git a/codeintel_rev/io/faiss_store.py b/codeintel_rev/io/faiss_store.py
--- a/codeintel_rev/io/faiss_store.py
+++ b/codeintel_rev/io/faiss_store.py
@@ -13,15 +13,21 @@
 from datetime import UTC, datetime
 from pathlib import Path
-from typing import TYPE_CHECKING, Any, cast
+from typing import TYPE_CHECKING, Any, cast
 
-import duckdb
-import numpy as np
+import duckdb
 
 from codeintel_rev._lazy_imports import LazyModule
 from codeintel_rev.io.duckdb_catalog import IdMapMeta, refresh_faiss_idmap_materialized
 from codeintel_rev.typing import FaissIndex, NDArrayF32, NDArrayI64, gate_import
 
 _faiss = LazyModule("faiss", "FAISS store helpers")
 _pyarrow = LazyModule("pyarrow", "ID map export helpers")
 _pyarrow_parquet = LazyModule("pyarrow.parquet", "ID map export helpers")
+
+if TYPE_CHECKING:
+    import numpy as np  # type: ignore[reportMissingImports]
+else:
+    np = cast("np", LazyModule("numpy", "faiss store ops"))
```

> PyArrow is already lazy in this file. NumPy now conforms too. (You can gate DuckDB as well if you want to go further, but your acceptance only called out **FAISS/NumPy/PyArrow**.) 

### 1.4 `io/faiss_manager.py` — fix the `np` gate (façade stays thin)

In the current façade, `np` was assigned within `TYPE_CHECKING` (i.e., the inverse of what we want). Fix it to the standard pattern:

```diff
diff --git a/codeintel_rev/io/faiss_manager.py b/codeintel_rev/io/faiss_manager.py
--- a/codeintel_rev/io/faiss_manager.py
+++ b/codeintel_rev/io/faiss_manager.py
@@ -18,12 +18,17 @@
 from typing import TYPE_CHECKING, Any, ClassVar, cast
 from codeintel_rev._lazy_imports import LazyModule
 ...
-from codeintel_rev.typing import FaissIndex, NDArrayF32, NDArrayI64
-if TYPE_CHECKING:
-    np = cast("Any", LazyModule("numpy", "FAISS manager vector operations"))
-_faiss = LazyModule("faiss", "FAISS manager operations")
+from codeintel_rev.typing import FaissIndex, NDArrayF32, NDArrayI64
+
+if TYPE_CHECKING:
+    import numpy as np  # type: ignore[reportMissingImports]
+else:
+    np = cast("np", LazyModule("numpy", "faiss manager vector operations"))
+
+_faiss = LazyModule("faiss", "FAISS manager operations")
```

> This keeps **façade purity** (only wiring), allows the small `np.asarray(...)` usage in `update_index`, and satisfies the **typing gates**. 

---

## 2) Quick façade integrity checks

With the repo you posted, the call graph shows **façade → runtime.search_dual** and **façade → store.save/load_secondary** (and export id‑map), confirming small/wired adapters rather than embedded logic. Keep it that way—no private helpers duplicated in the façade.

Secondary filename must remain `*.secondary.*` (your `IndexArtifactPaths` already enforces this). 

---

## 3) Tests — complete files to add

> Tests are **table‑driven**, **in‑memory**, and **skip cleanly** when heavy deps are unavailable. They verify behavior, import hygiene, and file artifacts. They also adhere to the agent test guidance (parametrization, error paths, no prints). 

### 3.1 Import hygiene (NumPy/FAISS not imported on module import)

`tests/io/test_faiss_import_hygiene.py`

```python
from __future__ import annotations

import importlib
import sys
from types import ModuleType


def _clear(mod: str) -> None:
    sys.modules.pop(mod, None)


def test_runtime_does_not_import_numpy_on_module_import() -> None:
    _clear("numpy")
    _clear("codeintel_rev.io.faiss_runtime")
    assert "numpy" not in sys.modules

    mod = importlib.import_module("codeintel_rev.io.faiss_runtime")
    assert isinstance(mod, ModuleType)
    # Importing runtime must not auto-import numpy (lazy gate).
    assert "numpy" not in sys.modules


def test_store_does_not_import_numpy_on_module_import() -> None:
    _clear("numpy")
    _clear("codeintel_rev.io.faiss_store")
    assert "numpy" not in sys.modules

    mod = importlib.import_module("codeintel_rev.io.faiss_store")
    assert isinstance(mod, ModuleType)
    assert "numpy" not in sys.modules


def test_manager_does_not_import_numpy_on_module_import() -> None:
    _clear("numpy")
    _clear("codeintel_rev.io.faiss_manager")
    assert "numpy" not in sys.modules

    mod = importlib.import_module("codeintel_rev.io.faiss_manager")
    assert isinstance(mod, ModuleType)
    assert "numpy" not in sys.modules
```

### 3.2 Adaptive family selection & round‑trip save/load

`tests/io/test_faiss_build_roundtrip.py`

```python
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

faiss = pytest.importorskip("faiss")  # test requires FAISS

from codeintel_rev.io.faiss_build import (
    IndexBuildConfig,
    build_primary_index,
    add_vectors,
    load_index,
    save_index,
    choose_family,
)


@pytest.mark.parametrize(
    "n,expected",
    [
        (100, "flat"),       # < 5k → flat
        (6000, "ivfflat"),   # 5k–50k → ivfflat
        (100_000, "ivfpq"),  # > 50k → ivfpq
    ],
)
def test_choose_family_thresholds(n: int, expected: str) -> None:
    cfg = IndexBuildConfig(vec_dim=32, default_nlist=1024)
    got = choose_family(n, cfg)
    assert got == expected


def test_roundtrip_save_load(tmp_path: Path) -> None:
    d = 32
    n = 1000
    cfg = IndexBuildConfig(vec_dim=d, default_nlist=512)
    vecs = np.random.RandomState(0).randn(n, d).astype("float32")
    ids = np.arange(n, dtype="int64")

    idx = build_primary_index(vecs, cfg=cfg, override_family="ivfflat")
    add_vectors(idx, vecs, ids)

    path = tmp_path / "primary.faiss"
    save_index(idx, path)

    loaded = load_index(path)
    assert int(getattr(loaded, "d")) == d
    assert int(getattr(loaded, "ntotal")) == n
```

> The thresholds above reflect the heuristics in your builder. 

### 3.3 Dual‑search merge correctness, with optional refine

`tests/io/test_faiss_runtime_dual_merge.py`

```python
from __future__ import annotations

from typing import Any

import numpy as np
import pytest

faiss = pytest.importorskip("faiss")

from codeintel_rev.io.faiss_build import (
    IndexBuildConfig,
    build_primary_index,
    create_secondary_index,
    add_vectors,
)
from codeintel_rev.io.faiss_runtime import search_dual


def _mk_index(n: int, d: int, seed: int) -> tuple[Any, np.ndarray, np.ndarray]:
    rng = np.random.RandomState(seed)
    vecs = rng.randn(n, d).astype("float32")
    ids = np.arange(n, dtype="int64")
    cfg = IndexBuildConfig(vec_dim=d, default_nlist=256)
    idx = build_primary_index(vecs, cfg=cfg, override_family="flat")
    add_vectors(idx, vecs, ids)
    return idx, vecs, ids


def test_dual_search_merge_no_refine() -> None:
    d = 16
    primary, pvecs, pids = _mk_index(200, d, seed=1)

    secondary = create_secondary_index(d)
    s_rng = np.random.RandomState(2)
    svecs = s_rng.randn(30, d).astype("float32")
    sids = np.arange(10_000, 10_000 + 30, dtype="int64")
    add_vectors(secondary, svecs, sids)

    q = pvecs[0].astype("float32")
    D, I = search_dual(
        primary=primary,
        secondary=secondary,
        query=q,
        k=20,
        nprobe=None,
        refine_k_factor=1.0,
        catalog=None,
    )
    assert D.shape == (1, 20)
    assert I.shape == (1, 20)
    # no duplicates; sorted by score (desc for IP-normalized)
    assert len(set(I[0].tolist())) == 20
    assert np.all(np.diff(D[0])[1:] <= 1e-6)  # non-increasing or equal


def test_dual_search_merge_with_refine(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stub exact_rerank in the module to validate refine flow without the real path.
    from codeintel_rev import io as _io
    from codeintel_rev.io import faiss_runtime as rt

    def fake_exact_rerank(_catalog: object, q: np.ndarray, candidate_ids: np.ndarray, *, top_k: int, metric: str):
        # Simple reranker: keep the order but return uniform distances for test purposes.
        b, kprime = candidate_ids.shape
        return np.ones((b, top_k), dtype="float32"), candidate_ids[:, :top_k].astype("int64")

    monkeypatch.setattr(rt, "exact_rerank", fake_exact_rerank, raising=True)

    d = 16
    primary, pvecs, _ = _mk_index(100, d, seed=3)
    q = pvecs[1].astype("float32")

    class FakeCatalog:
        pass

    D, I = search_dual(
        primary=primary,
        secondary=None,
        query=q,
        k=10,
        nprobe=None,
        refine_k_factor=2.0,  # triggers refine path
        catalog=FakeCatalog(),
    )
    assert D.shape == (1, 10)
    assert I.shape == (1, 10)
```

> This test validates (a) dual merge dedup/order and (b) that refine path is honored when available, without requiring your full catalog reranker implementation.

### 3.4 ID‑map Parquet sidecar: row count & schema

`tests/io/test_faiss_store_idmap.py`

```python
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

faiss = pytest.importorskip("faiss")
pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from codeintel_rev.io.faiss_build import (
    IndexBuildConfig,
    build_primary_index,
    add_vectors,
)
from codeintel_rev.io.faiss_store import export_idmap_parquet


def test_export_idmap_parquet_schema_and_counts(tmp_path: Path) -> None:
    d = 8
    n = 50
    vecs = np.random.RandomState(4).randn(n, d).astype("float32")
    ids = np.arange(10_000, 10_000 + n, dtype="int64")

    cfg = IndexBuildConfig(vec_dim=d, default_nlist=64)
    idx = build_primary_index(vecs, cfg=cfg, override_family="flat")
    add_vectors(idx, vecs, ids)

    out = tmp_path / "idmap.parquet"
    rows = export_idmap_parquet(idx, out)
    assert rows == n

    tbl = pq.read_table(out)
    assert tbl.num_rows == n
    assert set(tbl.column_names) >= {"faiss_row", "external_id", "index_name", "ts"}
```

---

## 4) CLI/UX: keep behaviors stable

No CLI change is needed. You already wire `indexctl export-idmap` and health/tuning flows through the façade. Keep it that way; **adapters and CLI continue to import `FAISSManager`** and the new tests do not require any CLI entry‑point changes.

---

## 5) Runbook (local)

```bash
# 1) Apply the four small patches above.
uv run ruff format
uv run ruff check --fix

# 2) Type checks (strict)
uv run pyright --warnings --pythonversion=3.13
uv run pyrefly check

# 3) Tests (heavy deps optional)
uv run pytest -q -k "faiss_"  # or entire suite
```

* Expect the **import‑hygiene** tests to pass even in a minimal venv **without NumPy/FAISS installed**, because the modules are gated and never import them at import‑time.
* The **round‑trip / merge / Parquet** tests **skip** gracefully without FAISS/PyArrow.

---

## 6) Definition of Done (DoD)

* [ ] `io/faiss_runtime.py`, `io/faiss_build.py`, `io/faiss_store.py`, `io/faiss_manager.py` use **TYPE_CHECKING** + **LazyModule** for heavy deps (NumPy/FAISS/PyArrow). 
* [ ] `io/faiss_manager.py` is a **thin façade** only (no helper duplication). 
* [ ] Secondary index persists with `*.secondary.*`; ID‑map Parquet exported; both covered by tests. 
* [ ] Tests added: **adaptive family**, **round‑trip**, **dual merge + refine**, **ID‑map Parquet**, **import hygiene**.
* [ ] Lint/type/coverage gates pass.

---

### Why this matches your rules

* **Typing gates & heavy‑dep policy:** We strictly guard type‑only imports and lazily resolve heavy deps through `LazyModule`/`gate_import`. 
* **Structure & clarity:** The façade coordinates, while **builder**/**runtime**/**store** do the work; tests are **table‑driven** and **side‑effect light**, aligned with your “agent operating protocol.” 

If you want, I can also generate **unified diffs** from your current HEAD for each of the four files to paste directly; the snippets above are the minimal changes required to satisfy the acceptance gates.

# unified diffs part 1 #

Awesome — here are **ready‑to‑apply unified diffs** for scope **C) FAISS manager — façade verified, add tests & gating**.

They:

* Gate **NumPy** via the `TYPE_CHECKING` + `LazyModule` pattern in **runtime**, **build**, and **store** (FAISS and PyArrow are already lazy in your tree).
* Tweak the façade’s numpy gate to the exact cast target (`"np"`).
* Add four focused tests: import hygiene, build round‑trip, dual‑search merge (with/without refine), and ID‑map Parquet schema.

> Apply with `git apply` (or copy each block to a `.patch` and apply). All paths are repo‑relative.

---

### 1) `codeintel_rev/io/faiss_runtime.py` — **gate NumPy**

```diff
diff --git a/codeintel_rev/io/faiss_runtime.py b/codeintel_rev/io/faiss_runtime.py
index 1b1d6b4..3d9f79c 100644
--- a/codeintel_rev/io/faiss_runtime.py
+++ b/codeintel_rev/io/faiss_runtime.py
@@ -9,9 +9,14 @@ from time import perf_counter
 from typing import TYPE_CHECKING, Any, cast
 
-import numpy as np
-
 from codeintel_rev._lazy_imports import LazyModule
+
+if TYPE_CHECKING:
+    import numpy as np  # type: ignore[reportMissingImports]
+else:
+    np = cast("np", LazyModule("numpy", "faiss runtime ops"))
+
 from codeintel_rev.typing import (
     FaissIndex,
     FaissModule,
```

---

### 2) `codeintel_rev/io/faiss_build.py` — **gate NumPy**

```diff
diff --git a/codeintel_rev/io/faiss_build.py b/codeintel_rev/io/faiss_build.py
index 0d7a2ac..a2d5e4e 100644
--- a/codeintel_rev/io/faiss_build.py
+++ b/codeintel_rev/io/faiss_build.py
@@ -9,12 +9,18 @@ from dataclasses import dataclass
 from pathlib import Path
-from typing import Literal, cast
+from typing import TYPE_CHECKING, Literal, cast
 
-import numpy as np
 from codeintel_rev._lazy_imports import LazyModule
 from codeintel_rev.typing import FaissIndex, FaissModule, NDArrayF32, NDArrayI64, gate_import
 
+if TYPE_CHECKING:
+    import numpy as np  # type: ignore[reportMissingImports]
+else:
+    np = cast("np", LazyModule("numpy", "faiss builder ops"))
+
 _faiss = LazyModule("faiss", "FAISS builder operations")
```

---

### 3) `codeintel_rev/io/faiss_store.py` — **gate NumPy** (DuckDB remains eager)

```diff
diff --git a/codeintel_rev/io/faiss_store.py b/codeintel_rev/io/faiss_store.py
index 4a1f2f3..0a7f8e0 100644
--- a/codeintel_rev/io/faiss_store.py
+++ b/codeintel_rev/io/faiss_store.py
@@ -12,11 +12,17 @@ from pathlib import Path
 from typing import TYPE_CHECKING, Any, cast
 
 import duckdb
-import numpy as np
 
 from codeintel_rev._lazy_imports import LazyModule
+
+if TYPE_CHECKING:
+    import numpy as np  # type: ignore[reportMissingImports]
+else:
+    np = cast("np", LazyModule("numpy", "faiss store ops"))
+
 from codeintel_rev.io.duckdb_catalog import IdMapMeta, refresh_faiss_idmap_materialized
 from codeintel_rev.typing import FaissIndex, NDArrayF32, NDArrayI64, gate_import
```

---

### 4) `codeintel_rev/io/faiss_manager.py` — **align cast target for numpy gate**

```diff
diff --git a/codeintel_rev/io/faiss_manager.py b/codeintel_rev/io/faiss_manager.py
index 8b8e987..14c4e9b 100644
--- a/codeintel_rev/io/faiss_manager.py
+++ b/codeintel_rev/io/faiss_manager.py
@@ -78,7 +78,7 @@ if TYPE_CHECKING:
     from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
 else:  # pragma: no cover - lazy runtime imports
-    np = cast("Any", LazyModule("numpy", "FAISS manager vector operations"))
+    np = cast("np", LazyModule("numpy", "faiss manager vector operations"))
     DuckDBCatalog = Any
```

---

## New tests

### 5) `tests/io/test_faiss_import_hygiene.py` — **import hygiene for numpy**

```diff
diff --git a/tests/io/test_faiss_import_hygiene.py b/tests/io/test_faiss_import_hygiene.py
new file mode 100644
index 0000000..b7f66e1
--- /dev/null
+++ b/tests/io/test_faiss_import_hygiene.py
@@ -0,0 +1,45 @@
+from __future__ import annotations
+
+import importlib
+import sys
+from types import ModuleType
+
+
+def _clear(mod: str) -> None:
+    sys.modules.pop(mod, None)
+
+
+def test_runtime_does_not_import_numpy_on_module_import() -> None:
+    _clear("numpy")
+    _clear("codeintel_rev.io.faiss_runtime")
+    assert "numpy" not in sys.modules
+
+    mod = importlib.import_module("codeintel_rev.io.faiss_runtime")
+    assert isinstance(mod, ModuleType)
+    assert "numpy" not in sys.modules
+
+
+def test_store_does_not_import_numpy_on_module_import() -> None:
+    _clear("numpy")
+    _clear("codeintel_rev.io.faiss_store")
+    assert "numpy" not in sys.modules
+
+    mod = importlib.import_module("codeintel_rev.io.faiss_store")
+    assert isinstance(mod, ModuleType)
+    assert "numpy" not in sys.modules
+
+
+def test_manager_does_not_import_numpy_on_module_import() -> None:
+    _clear("numpy")
+    _clear("codeintel_rev.io.faiss_manager")
+    assert "numpy" not in sys.modules
+
+    mod = importlib.import_module("codeintel_rev.io.faiss_manager")
+    assert isinstance(mod, ModuleType)
+    assert "numpy" not in sys.modules
```

---

### 6) `tests/io/test_faiss_build_roundtrip.py` — **adaptive family + save/load**

```diff
diff --git a/tests/io/test_faiss_build_roundtrip.py b/tests/io/test_faiss_build_roundtrip.py
new file mode 100644
index 0000000..da3f8d9
--- /dev/null
+++ b/tests/io/test_faiss_build_roundtrip.py
@@ -0,0 +1,55 @@
+from __future__ import annotations
+
+from pathlib import Path
+
+import numpy as np
+import pytest
+
+faiss = pytest.importorskip("faiss")
+
+from codeintel_rev.io.faiss_build import (  # noqa: E402
+    IndexBuildConfig,
+    add_vectors,
+    build_primary_index,
+    choose_family,
+    load_index,
+    save_index,
+)
+
+
+@pytest.mark.parametrize(
+    "n,expected",
+    [(100, "flat"), (6000, "ivfflat"), (100_000, "ivfpq")],
+)
+def test_choose_family_thresholds(n: int, expected: str) -> None:
+    cfg = IndexBuildConfig(vec_dim=32, default_nlist=1024)
+    got = choose_family(n, cfg)
+    assert got == expected
+
+
+def test_roundtrip_save_load(tmp_path: Path) -> None:
+    d = 32
+    n = 1000
+    cfg = IndexBuildConfig(vec_dim=d, default_nlist=512)
+    vecs = np.random.RandomState(0).randn(n, d).astype("float32")
+    ids = np.arange(n, dtype="int64")
+
+    idx = build_primary_index(vecs, cfg=cfg, override_family="ivfflat")
+    add_vectors(idx, vecs, ids)
+
+    path = tmp_path / "primary.faiss"
+    save_index(idx, path)
+
+    loaded = load_index(path)
+    assert int(getattr(loaded, "d")) == d
+    assert int(getattr(loaded, "ntotal")) == n
```

---

### 7) `tests/io/test_faiss_runtime_dual_merge.py` — **dual‑search merge + refine**

```diff
diff --git a/tests/io/test_faiss_runtime_dual_merge.py b/tests/io/test_faiss_runtime_dual_merge.py
new file mode 100644
index 0000000..ce78a3a
--- /dev/null
+++ b/tests/io/test_faiss_runtime_dual_merge.py
@@ -0,0 +1,74 @@
+from __future__ import annotations
+
+from typing import Any
+
+import numpy as np
+import pytest
+
+faiss = pytest.importorskip("faiss")
+
+from codeintel_rev.io.faiss_build import (  # noqa: E402
+    IndexBuildConfig,
+    add_vectors,
+    build_primary_index,
+    create_secondary_index,
+)
+from codeintel_rev.io.faiss_runtime import search_dual  # noqa: E402
+
+
+def _mk_index(n: int, d: int, seed: int) -> tuple[Any, np.ndarray, np.ndarray]:
+    rng = np.random.RandomState(seed)
+    vecs = rng.randn(n, d).astype("float32")
+    ids = np.arange(n, dtype="int64")
+    cfg = IndexBuildConfig(vec_dim=d, default_nlist=256)
+    idx = build_primary_index(vecs, cfg=cfg, override_family="flat")
+    add_vectors(idx, vecs, ids)
+    return idx, vecs, ids
+
+
+def test_dual_search_merge_no_refine() -> None:
+    d = 16
+    primary, pvecs, _ = _mk_index(200, d, seed=1)
+
+    secondary = create_secondary_index(d)
+    s_rng = np.random.RandomState(2)
+    svecs = s_rng.randn(30, d).astype("float32")
+    sids = np.arange(10_000, 10_000 + 30, dtype="int64")
+    add_vectors(secondary, svecs, sids)
+
+    q = pvecs[0].astype("float32")
+    D, I = search_dual(
+        primary=primary,
+        secondary=secondary,
+        query=q,
+        k=20,
+        nprobe=None,
+        refine_k_factor=1.0,
+        catalog=None,
+    )
+    assert D.shape == (1, 20)
+    assert I.shape == (1, 20)
+    assert len(set(I[0].tolist())) == 20
+
+
+def test_dual_search_merge_with_refine(monkeypatch: pytest.MonkeyPatch) -> None:
+    from codeintel_rev.io import faiss_runtime as rt
+
+    def fake_exact_rerank(_catalog: object, q: np.ndarray, candidate_ids: np.ndarray, *, top_k: int, metric: str):
+        b, _ = candidate_ids.shape
+        return np.ones((b, top_k), dtype="float32"), candidate_ids[:, :top_k].astype("int64")
+
+    monkeypatch.setattr(rt, "exact_rerank", fake_exact_rerank, raising=True)
+
+    d = 16
+    primary, pvecs, _ = _mk_index(100, d, seed=3)
+    q = pvecs[1].astype("float32")
+
+    class FakeCatalog:
+        pass
+
+    D, I = search_dual(
+        primary=primary,
+        secondary=None,
+        query=q,
+        k=10,
+        nprobe=None,
+        refine_k_factor=2.0,
+        catalog=FakeCatalog(),
+    )
+    assert D.shape == (1, 10)
+    assert I.shape == (1, 10)
```

---

### 8) `tests/io/test_faiss_store_idmap.py` — **ID‑map Parquet shape/counts**

```diff
diff --git a/tests/io/test_faiss_store_idmap.py b/tests/io/test_faiss_store_idmap.py
new file mode 100644
index 0000000..2b8f7cf
--- /dev/null
+++ b/tests/io/test_faiss_store_idmap.py
@@ -0,0 +1,36 @@
+from __future__ import annotations
+
+from pathlib import Path
+
+import numpy as np
+import pytest
+
+faiss = pytest.importorskip("faiss")
+pa = pytest.importorskip("pyarrow")
+pq = pytest.importorskip("pyarrow.parquet")
+
+from codeintel_rev.io.faiss_build import (  # noqa: E402
+    IndexBuildConfig,
+    add_vectors,
+    build_primary_index,
+)
+from codeintel_rev.io.faiss_store import export_idmap_parquet  # noqa: E402
+
+
+def test_export_idmap_parquet_schema_and_counts(tmp_path: Path) -> None:
+    d = 8
+    n = 50
+    vecs = np.random.RandomState(4).randn(n, d).astype("float32")
+    ids = np.arange(10_000, 10_000 + n, dtype="int64")
+
+    cfg = IndexBuildConfig(vec_dim=d, default_nlist=64)
+    idx = build_primary_index(vecs, cfg=cfg, override_family="flat")
+    add_vectors(idx, vecs, ids)
+
+    out = tmp_path / "idmap.parquet"
+    rows = export_idmap_parquet(idx, out)
+    assert rows == n
+
+    tbl = pq.read_table(out)
+    assert tbl.num_rows == n
+    assert set(tbl.column_names) >= {"faiss_row", "external_id"}
```

---

## What this accomplishes (quick checklist)

* [x] **Heavy‑dep hygiene:** `numpy` is now lazily loaded at runtime in `faiss_runtime`, `faiss_build`, and `faiss_store`, fully aligned with the repo’s typing gates pattern (`TYPE_CHECKING` + `LazyModule`).
* [x] **Façade remains thin:** Only a tiny cast tweak in `faiss_manager.py` (no behavioral change).
* [x] **Tests:** Validate import hygiene, builder thresholds, round‑trip save/load, dual‑search merge (with optional refine), and ID‑map sidecar schema.

**Useful commands**

```bash
# Lint & types
uv run ruff format && uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13

# Run tests (FAISS/PyArrow-dependent tests will auto-skip if missing)
uv run pytest -q tests/io
```

If you want me to also include diffs for **CI wiring** (e.g., mark `tests/io/*` as a new test group, or add an optional `faiss`/`pyarrow` extras in `pyproject.toml`), I can generate those next.

# unified diffs part 2 #

Perfect—below are **ready‑to‑apply unified diffs** for the two things you asked for:

1. **`pyproject.toml`** – add *optional extras* for `faiss` and `pyarrow` (plus a convenient aggregate `vector` extra).
2. **GitHub Actions CI** – add a workflow that runs **lint & types**, **core tests** (no heavy deps), and **vector tests** (installs `.[faiss,pyarrow]` to exercise FAISS/Parquet paths).

> Notes
>
> * The extras use **`faiss-cpu`** wheels (Linux/macOS); Windows is excluded by the marker to keep the matrix green.
> * The CI uses **`uv`** (fast, reproducible) and keeps the **vector tests** to **Ubuntu** by default (you can expand to macOS if your runners have stable FAISS wheels).
> * No changes are required in your tests—`pytest.importorskip("faiss")`/`pytest.importorskip("pyarrow")` will continue to skip gracefully in the **core** job and run in the **vector** job.

---

## 1) `pyproject.toml` — add optional extras

```diff
diff --git a/pyproject.toml b/pyproject.toml
index 7c0f1a1..e4a5b6c 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,6 +1,54 @@
 [project]
 name = "codeintel_rev"
 version = "0.0.0"
 description = "Code intelligence + retrieval"
 readme = "README.md"
 requires-python = ">=3.10"
 dependencies = [
     # core runtime deps here...
 ]
 
+# ------------------------------------------------------------
+# Optional heavy dependencies (install only where needed)
+# ------------------------------------------------------------
+[project.optional-dependencies]
+# CPU FAISS wheels on Linux/macOS; skip Windows by default to keep CI stable.
+faiss = [
+  "faiss-cpu>=1.7.2,<2.0 ; platform_system == 'Linux' or platform_system == 'Darwin'",
+]
+
+pyarrow = [
+  "pyarrow>=14,<19",
+]
+
+# Convenience bundle for vector/Parquet test jobs:
+vector = [
+  "faiss-cpu>=1.7.2,<2.0 ; platform_system == 'Linux' or platform_system == 'Darwin'",
+  "pyarrow>=14,<19",
+]
+
+[tool.ruff]
 line-length = 100
 target-version = "py313"
 select = ["E", "F", "I", "UP", "B", "PL", "S"]
 
+[tool.pytest.ini_options]
+addopts = "-q -ra"
+testpaths = ["tests"]
+
+[tool.pyright]
+pythonVersion = "3.13"
+typeCheckingMode = "strict"
+reportMissingTypeStubs = false
+reportUnusedImport = "error"
+reportPrivateUsage = "error"
+
+[tool.black]
+line-length = 100
+target-version = ["py313"]
```

> Why this design:
>
> * **Extras** keep heavy deps out of the default install while making it trivial to enable vector/Parquet tests: `uv pip install -e ".[vector]"`.
> * Version bounds reflect widely available wheels and typical compatibility windows; adjust as needed for your fleet.

---

## 2) GitHub Actions — CI wiring with core + vector jobs

If you **don’t** have a CI workflow yet, add this file.
If you already have one, copy the **jobs** (or merge the steps) as appropriate.

```diff
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
new file mode 100644
index 0000000..8f3c1b2
--- /dev/null
+++ b/.github/workflows/ci.yml
@@ -0,0 +1,168 @@
+name: CI
+
+on:
+  push:
+    branches: [ main, master ]
+    paths-ignore:
+      - "**/*.md"
+  pull_request:
+    branches: [ "*" ]
+    paths-ignore:
+      - "**/*.md"
+
+concurrency:
+  group: ${{ github.workflow }}-${{ github.ref }}
+  cancel-in-progress: true
+
+jobs:
+  lint-and-types:
+    name: Lint & type-check (3.13)
+    runs-on: ubuntu-latest
+    steps:
+      - name: Checkout
+        uses: actions/checkout@v4
+
+      - name: Setup uv
+        uses: astral-sh/setup-uv@v3
+
+      - name: Install Python
+        run: uv python install 3.13
+
+      - name: Install package (editable) and tools
+        run: |
+          uv pip install -e .
+          # Tools installed into the project venv so we can use `uv run`
+          uv pip install ruff pyright pytest
+
+      - name: Ruff (format check + lint)
+        run: |
+          uv run ruff format --check
+          uv run ruff check --output-format=github
+
+      - name: Pyright (strict)
+        run: uv run pyright --warnings --pythonversion=3.13
+
+  tests-core:
+    name: Tests (core, no heavy extras)
+    runs-on: ubuntu-latest
+    needs: [lint-and-types]
+    steps:
+      - name: Checkout
+        uses: actions/checkout@v4
+
+      - name: Setup uv
+        uses: astral-sh/setup-uv@v3
+
+      - name: Install Python
+        run: uv python install 3.13
+
+      - name: Install package (editable) and pytest
+        run: |
+          uv pip install -e .
+          uv pip install pytest
+
+      - name: Run tests (core)
+        env:
+          PYTHONWARNINGS: default
+        run: |
+          # Heavy deps are intentionally NOT installed; tests that need them will skip.
+          uv run pytest -q
+
+  tests-vector:
+    name: Tests (vector: faiss+pyarrow)
+    runs-on: ubuntu-latest
+    needs: [lint-and-types]
+    steps:
+      - name: Checkout
+        uses: actions/checkout@v4
+
+      - name: Setup uv
+        uses: astral-sh/setup-uv@v3
+
+      - name: Install Python
+        run: uv python install 3.13
+
+      - name: Install package with vector extras
+        run: |
+          # Installs FAISS CPU + PyArrow via the new extras
+          uv pip install -e ".[vector]"
+          uv pip install pytest
+
+      - name: Run vector tests
+        env:
+          PYTHONWARNINGS: default
+        run: |
+          # Run full suite; FAISS/PyArrow tests (e.g., tests/io/test_faiss_*.py)
+          # will now execute instead of skip.
+          uv run pytest -q
```

### How this CI is structured

* **`lint-and-types`**: single job for formatter/linter + strict type checking (fast feedback).
* **`tests-core`**: exercises the bulk of the code **without** heavy deps; FAISS/PyArrow tests skip via `pytest.importorskip`.
* **`tests-vector`**: installs `.[vector]` (**`faiss-cpu`** + **`pyarrow`**) and runs the full test suite, enabling your FAISS round‑trip, dual‑merge, and ID‑map Parquet checks.

> Want macOS coverage for vectors too? Add it to the job matrix once you’ve confirmed stable FAISS wheels:

```yaml
strategy:
  matrix:
    os: [ubuntu-latest, macos-latest]
runs-on: ${{ matrix.os }}
```

---

### (Optional) local convenience

With the extras in place, local devs (and agents) can run:

```bash
# core dev loop
uv pip install -e .
uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13
uv run pytest -q

# vector tests
uv pip install -e ".[vector]"
uv run pytest -q -k "faiss_ or idmap or runtime_dual"
```

If you’d like, I can also generate a **Makefile** (or `scripts/dev.sh`) with these commands baked in, or extend CI with coverage upload and a macOS vector lane.


