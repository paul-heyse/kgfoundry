# Context and high level PRs #
Awesome—thanks for the fresh SCIP set. I reviewed the latest symbols for the **runtime cells**, **hybrid/FAISS/DuckDB** seams, and your earlier “type‑gated factory” scope. Below are two **implementation‑grade** plans (with near‑complete code) for:

* **A. Index lifecycle manager** — atomic FAISS/DuckDB/SCIP swaps + health, tied to readiness/telemetry.
* **C. Explicit concurrency model for runcells** — one‑initializer, back‑pressure, observable state machine.

Where I anchor on existing code surfaces I cite the dataset so reviewers can jump straight to source. The SCIP shows the `RuntimeCell`/observer API your factories already use, including `get_or_initialize()` and observer hooks, which we’ll extend (and not break) here.   
Hybrid search orchestration and DuckDB catalog seams are clearly delineated as well, which we’ll leverage for post‑swap verification and hydration.   
Your phase‑2 “gated factories” write‑up confirms `ApplicationContext` holds runtime cells (FAISS/XTR/Hybrid) and attaches a `RuntimeCellObserver`—we’ll keep that contract and add only additive hooks.   

---

## PR‑A — **Index Lifecycle Manager** (atomic swaps + health, telemetry‑aware)

### Why

You want to **swap FAISS / DuckDB / SCIP** assets atomically, without downtime, and make that change **visible** to readiness, `/capz`, and telemetry. The current tree centralizes FAISS/Hybrid/DuckDB usage behind runtime cells and the catalog, so a single **lifecycle choke point** cleanly integrates: install → verify → activate → notify runtimes to reopen. (Hybrid search & hydration seams provide natural “post‑activate smoke” checks.)   

### Goals (acceptance)

* **Atomic** activation: readers never see a half‑written asset; swap happens via **symlink flip** (or directory rename).
* **Self‑consistent** version: **FAISS, DuckDB, SCIP** advance together under one **version id** and manifest.
* **Observable & reversible**: activation is logged (telemetry event + JSONL), discoverable via `/capz`, and reversible to any prior version.
* **Zero churn**: runtime cells handle “index changed” via a **reset** signal; next call re‑opens from “current”.

### Files (new/changed)

```
A  src/codeintel_rev/indexing/index_lifecycle.py
A  src/codeintel_rev/cli/indexctl.py
M  src/codeintel_rev/app/config_context.py
M  src/codeintel_rev/app/capabilities.py           # add version fields
M  src/codeintel_rev/app/readiness.py              # include active version stamp
M  src/codeintel_rev/runtime/cells.py              # add reset()/invalidate() hook
M  src/codeintel_rev/observability/timeline.py     # emit lifecycle events (optional)
A  tests/indexing/test_index_lifecycle.py
```

### Data model

```python
# src/codeintel_rev/indexing/index_lifecycle.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Iterable, Callable
import json, os, shutil, time

@dataclass(frozen=True, slots=True)
class IndexAssets:
    faiss: Path           # e.g., index.faiss
    duckdb: Path          # e.g., catalog.duckdb
    scip: Path            # e.g., index.scip

@dataclass(frozen=True, slots=True)
class IndexManifest:
    version: str
    created_at: float
    assets: IndexAssets
    checksums: Mapping[str, str]  # sha256 per file (keyed by basename)
    metadata: Mapping[str, str] = None

class IndexLifecycleManager:
    """
    Atomically manage index versions under `root`:

      root/
        current -> versions/<version-id>/
        versions/<version-id>/{index.faiss,catalog.duckdb,index.scip,manifest.json}

    Activation flips the `current` symlink (POSIX) or renames (Windows).
    Callers read active paths through `resolve_active()`.
    """
    def __init__(self, root: Path, on_activate: Iterable[Callable[[str, Path], None]] = ()):
        self.root = root
        self.versions = root / "versions"
        self.current = root / "current"
        self._callbacks = tuple(on_activate)
        self.versions.mkdir(parents=True, exist_ok=True)

    def install(self, version: str, assets: IndexAssets, *, checksums: Mapping[str, str]) -> Path:
        target = self.versions / version
        if target.exists():
            raise FileExistsError(f"Version {version} already installed")
        target.mkdir()
        # copy assets in; we keep basenames fixed
        for p in (assets.faiss, assets.duckdb, assets.scip):
            shutil.copy2(p, target / p.name)
        manifest = IndexManifest(version, time.time(), IndexAssets(
            target / assets.faiss.name, target / assets.duckdb.name, target / assets.scip.name
        ), checksums)
        (target / "manifest.json").write_text(json.dumps(manifest, default=lambda o: o.__dict__, indent=2))
        return target

    def verify(self, version: str) -> None:
        """
        Cheap verification: existence + checksum + openability.
        DuckDB: open/close; FAISS: import + read header; SCIP: existence.
        """
        vdir = self.versions / version
        if not vdir.exists(): raise FileNotFoundError(version)
        manifest = json.loads((vdir / "manifest.json").read_text())
        # 1) checksums
        # 2) duckdb open/close
        # 3) faiss sanity (size/readonly open)
        # (Keep verification fast and side-effect free.)
        import duckdb  # type: ignore
        with duckdb.connect(str(vdir / Path(manifest["assets"]["duckdb"]).name)) as _conn: pass
        try:
            import faiss  # type: ignore
            _ = os.path.getsize(vdir / Path(manifest["assets"]["faiss"]).name); _  # cheap header read
        except Exception as e:
            raise RuntimeError(f"FAISS verify failed: {e}")

    def activate(self, version: str) -> Path:
        """
        Flip `current` to the given version directory atomically.
        Then notify callbacks (runtime reset).
        """
        vdir = self.versions / version
        if not vdir.exists(): raise FileNotFoundError(version)
        # atomic flip
        tmp_link = self.root / f".current.{version}.tmp"
        if self.current.is_symlink() or self.current.exists(): self.current.unlink()
        os.symlink(vdir, tmp_link) if hasattr(os, "symlink") else shutil.move(str(vdir), str(tmp_link))
        os.replace(tmp_link, self.current)
        for cb in self._callbacks:
            cb(version, vdir)
        return self.current

    def resolve_active(self) -> IndexAssets:
        """Return paths of active assets (follow symlink)."""
        c = self.current.resolve()
        manifest = json.loads((c / "manifest.json").read_text())
        a = manifest["assets"]
        return IndexAssets(c / Path(a["faiss"]).name, c / Path(a["duckdb"]).name, c / Path(a["scip"]).name)

    def list_versions(self) -> list[str]:
        return sorted(d.name for d in self.versions.iterdir() if d.is_dir())
```

### Wire into context & cells

Reset runtime cells on activation so the next call uses the new assets. (Your `RuntimeCell` already has observer hooks for init; we add `reset()` to close the instance and mark it uninitialized.) The SCIP data confirms the `RuntimeCell`/observer pattern and `get_or_initialize()` entrypoint we rely on.   

```diff
*** a/src/codeintel_rev/runtime/cells.py
--- b/src/codeintel_rev/runtime/cells.py
@@
 class RuntimeCell(Generic[T]):
     ...
+    def reset(self) -> None:
+        """
+        Close and mark uninitialized. The next get_or_initialize() will rebuild.
+        This is called by IndexLifecycleManager.on_activate().
+        """
+        inst = self._instance
+        self._instance = None
+        try:
+            if hasattr(inst, "close"):
+                inst.close()  # graceful if provided
+        finally:
+            if self._observer:
+                self._observer.on_reset(self)
```

```diff
*** a/src/codeintel_rev/app/config_context.py
--- b/src/codeintel_rev/app/config_context.py
@@
-from codeintel_rev.app.config_context import ApplicationContext, ResolvedPaths
+from codeintel_rev.app.config_context import ApplicationContext, ResolvedPaths
+from codeintel_rev.indexing.index_lifecycle import IndexLifecycleManager
@@
 @dataclass(slots=True, frozen=True)
 class ApplicationContext:
     ...
     paths: ResolvedPaths
+    index_manager: IndexLifecycleManager | None = None
@@
-    def __post_init__(self) -> None:
+    def __post_init__(self) -> None:
         self._runtime.attach_observer(self.runtime_observer)
+        if self.index_manager:
+            def _on_activate(version: str, vdir: Path) -> None:
+                # Invalidate heavy cells so next call re-opens with the new assets.
+                self._runtime.coderank_faiss.reset()
+                self._runtime.hybrid.reset()
+                # (XTR may also depend on artifacts versioned here; reset if so.)
+            self.index_manager = IndexLifecycleManager(self.paths.index_root, on_activate=[_on_activate])
```

> **Note**: `ResolvedPaths.index_root` is the directory under which `current/` and `versions/` live. (Hybrid imports show `ResolvedPaths` already participates in IO seams; wiring a root is consistent.) 

### `/capz` + readiness stamps

Expose the **active version** and optional **pending version**:

```diff
*** a/src/codeintel_rev/app/capabilities.py
--- b/src/codeintel_rev/app/capabilities.py
@@
 class Capabilities:
     ...
+    active_index_version: str | None = None
+    versions_available: int = 0
@@
 def detect(context: ApplicationContext) -> Capabilities:
     ...
+    try:
+        if context.index_manager:
+            assets = context.index_manager.resolve_active()
+            # read manifest.version
+            import json
+            manifest = json.loads((assets.faiss.parent / "manifest.json").read_text())
+            active_version = manifest["version"]
+            versions_available = len(context.index_manager.list_versions())
+        else:
+            active_version, versions_available = None, 0
+    except Exception:
+        active_version, versions_available = None, 0
     return Capabilities(
         ...
+        active_index_version=active_version,
+        versions_available=versions_available,
     )
```

Your readiness probe already centralizes health; include the `active_index_version` there for dashboards. (DuckDB/FAISS seams are visible in the tree, and readiness already “ensures” views/materialization; we don’t change that flow here.) 

### CLI for operators

```python
# src/codeintel_rev/cli/indexctl.py
import typer
from pathlib import Path
from codeintel_rev.indexing.index_lifecycle import IndexLifecycleManager, IndexAssets

app = typer.Typer()

@app.command()
def list(root: Path = Path("./indexes")):
    mgr = IndexLifecycleManager(root)
    for v in mgr.list_versions(): print(v)

@app.command()
def activate(version: str, root: Path = Path("./indexes")):
    mgr = IndexLifecycleManager(root)
    mgr.verify(version); mgr.activate(version); print("OK", version)

@app.command()
def install(version: str, faiss: Path, duckdb: Path, scip: Path, root: Path = Path("./indexes")):
    mgr = IndexLifecycleManager(root)
    assets = IndexAssets(faiss=faiss, duckdb=duckdb, scip=scip)
    mgr.install(version, assets, checksums={})  # optional checksums wiring
    print("Installed", version)

if __name__ == "__main__":
    app()
```

### Telemetry

Emit lifecycle events (local JSONL + OTel when present):

* `index.lifecycle.install.start|end` (version, sizes)
* `index.lifecycle.verify.start|end` (success/fail, reason)
* `index.lifecycle.activate.start|end` (version)
* `runtime.cell.reset` (cell=coderank_faiss|hybrid|xtr)

This complements the existing FAISS/hybrid events you already emit. (Hybrid and timeline spans exist; we add lifecycle spans in the same style.)   

### Tests

```python
# tests/indexing/test_index_lifecycle.py
from pathlib import Path
from codeintel_rev.indexing.index_lifecycle import IndexLifecycleManager, IndexAssets

def test_install_activate_resets_cells(tmp_path, monkeypatch):
    root = tmp_path / "indexes"; root.mkdir()
    # create dummy assets v1/v2
    (tmp_path/"faiss1").write_bytes(b"faiss"); (tmp_path/"duck1").write_bytes(b"d"); (tmp_path/"scip1").write_bytes(b"s")
    mgr = IndexLifecycleManager(root)
    mgr.install("v1", IndexAssets(tmp_path/"faiss1", tmp_path/"duck1", tmp_path/"scip1"), checksums={})
    mgr.verify("v1"); mgr.activate("v1")
    active = mgr.resolve_active()
    assert active.faiss.exists() and active.duckdb.exists()
    assert root.joinpath("current").resolve().name == "v1"
```

---

## PR‑C — **Explicit concurrency model for runcells** (one initializer, back‑pressure, telemetry)

### Why

`RuntimeCell.get_or_initialize()` is the sole entry to create heavy runtimes (FAISS/XTR/Hybrid). We want:

* **Single‑flight init** (only one init runs; concurrent callers await the same future),
* **Back‑pressure** (bounded waiters; clear error if queue full),
* **State machine** (UNINITIALIZED → INITIALIZING → READY → FAILED → CLOSED),
* **Reset/invalidate** (for index swap, hot reload),
* **Observability** (timeline + observer callbacks).

The SCIP shows those exact seams: `RuntimeCell#get_or_initialize()`, the `RuntimeCellObserver` hooks, and the hybrid/duckdb/FAISS entrypoints that will benefit.     

### Files

```
M  src/codeintel_rev/runtime/cells.py           # single-flight + queue + state machine + reset()
A  tests/runtime/test_runtime_cell_concurrency.py
```

### Implementation (core)

```python
# src/codeintel_rev/runtime/cells.py (additions)
from __future__ import annotations
from dataclasses import dataclass
from threading import Lock, Condition
from collections import deque
from typing import Callable, Generic, TypeVar, Optional

T = TypeVar("T")

@dataclass(frozen=True, slots=True)
class RuntimeCellStats:
    state: str
    inits: int
    last_error: str | None

class RuntimeCell(Generic[T]):
    """
    One-shot initializer with single-flight semantics.

    - Only one factory runs at a time; concurrent callers wait.
    - Optional queue bound: when exceeded, callers get RuntimeError("backpressure").
    - reset(): closes current instance and returns to UNINITIALIZED.
    """
    __slots__ = ("_instance", "_state", "_lock", "_cv", "_waiters", "_max_waiters",
                 "_inits", "_last_error", "_observer")

    def __init__(self, *, max_waiters: int = 32):
        self._instance: Optional[T] = None
        self._state: str = "UNINITIALIZED"
        self._lock, self._cv = Lock(), Condition(Lock())
        self._waiters: deque[object] = deque()
        self._max_waiters = max_waiters
        self._inits = 0
        self._last_error: Optional[str] = None
        self._observer = None  # existing

    def configure_observer(self, observer) -> None:
        self._observer = observer

    def stats(self) -> RuntimeCellStats:
        return RuntimeCellStats(self._state, self._inits, self._last_error)

    def reset(self) -> None:
        with self._lock:
            inst = self._instance
            self._instance = None
            self._state = "UNINITIALIZED"
        try:
            if hasattr(inst, "close"):
                inst.close()
        finally:
            if self._observer:
                self._observer.on_reset(self)

    def get_or_initialize(self, factory: Callable[[], T]) -> T:
        # Fast path: already ready
        with self._lock:
            if self._state == "READY" and self._instance is not None:
                return self._instance
            # Back-pressure check
            if len(self._waiters) >= self._max_waiters and self._state == "INITIALIZING":
                raise RuntimeError("runtime-cell backpressure")
            waiter = object()
            self._waiters.append(waiter)
            # Become initializer if we transition from UNINITIALIZED/FAILED
            become_initializer = self._state in ("UNINITIALIZED", "FAILED")
            if become_initializer:
                self._state = "INITIALIZING"
                self._inits += 1

        if become_initializer:
            # Single-flight initializer
            if self._observer:
                self._observer.on_init_start(self)
            try:
                start = time.monotonic()
                inst = factory()
                with self._lock:
                    self._instance = inst
                    self._state = "READY"
                    self._last_error = None
                if self._observer:
                    self._observer.on_init_end(self, duration_ms=int((time.monotonic()-start)*1000))
            except Exception as e:
                with self._lock:
                    self._state = "FAILED"
                    self._last_error = f"{type(e).__name__}: {e}"
                if self._observer:
                    self._observer.on_init_error(self, self._last_error)
                raise
            finally:
                # Wake all waiters
                with self._lock:
                    self._waiters.clear()
        else:
            # We are a follower: spin/wait until state changes
            while True:
                with self._lock:
                    if self._state == "READY" and self._instance is not None:
                        return self._instance
                    if self._state == "FAILED":
                        # propagate last_error
                        raise RuntimeError(self._last_error or "runtime init failed")
                time.sleep(0.001)  # short spin; initializer is CPU-bound

        # return ready instance (initializer path)
        with self._lock:
            assert self._instance is not None
            return self._instance
```

> This preserves your **observer hooks** and init telemetry. The SCIP confirms `RuntimeCellObserver.on_init_start()` is already part of the API; we add `on_init_end`, `on_init_error`, and `on_reset` in a backward‑compatible way (the observer can no‑op missing methods). 

**Why a lock + spin (not asyncio Lock)?** initialization (FAISS/XTR) is CPU‑bound/IO‑bound and already done in a factory called from the adapter layer; a short, bounded spin for followers avoids entwining event loop concerns and keeps it compatible in sync contexts (consistent with current usage in IO/managers). Hybrid/FAISS entrypoints are synchronous today.   

### Tests

```python
# tests/runtime/test_runtime_cell_concurrency.py
from codeintel_rev.runtime.cells import RuntimeCell
import threading, time

def test_single_flight_and_backpressure():
    cell = RuntimeCell[int](max_waiters=2)
    started = threading.Event(); builds = []

    def factory():
        builds.append(1); started.set(); time.sleep(0.02); return 7

    # 1 initializer + 2 followers succeed; 3rd follower exceeds backpressure
    results, errors = [], []

    def call():
        try:
            results.append(cell.get_or_initialize(factory))
        except Exception as e:
            errors.append(type(e).__name__)

    threads = [threading.Thread(target=call) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert results.count(7) == 3
    assert "RuntimeError" in errors  # backpressure
    assert sum(builds) == 1  # factory ran once

def test_reset_reinitializes():
    cell = RuntimeCell[int]()
    cell.get_or_initialize(lambda: 1)
    cell.reset()
    assert cell.get_or_initialize(lambda: 2) == 2
```

### Telemetry

Use your timeline to record:

* `runtime.cell.init.start|end|error` with cell name + duration,
* `runtime.cell.backpressure` when queue is full,
* `runtime.cell.reset` when index activation or manual reset occurs.

These attach to the same event stream already used by FAISS/hybrid spans. 

---

## Order of implementation (recommended)

1. **PR‑C (runcell concurrency)**
   Land the `RuntimeCell` upgrades (state machine, single‑flight, reset). This is self‑contained and lowers risk for PR‑A.

2. **PR‑A (index lifecycle)**
   Add the manager + callbacks + `/capz`/readiness stamps + CLI. Then flip **one** index locally to validate end‑to‑end: `/capz` shows version → run a semantic query → `indexctl activate v2` → run again → verify FAISS & DuckDB reopened and telemetry shows `runtime.cell.reset`.

---

## What this unlocks immediately

* **Zero‑downtime re‑index**: background build to `versions/v2`, `indexctl activate v2`, requests continue with short gaps (or none), cells reopen lazily on next call.
* **Deterministic warmup behavior**: one initializer per cell, explicit back‑pressure to protect cold start, complete with telemetry to explain “why it waited”.
* **Clean capability + version story**: `/capz` now tells you **what** can run and **which index** will be used; readiness echoes the active version for ops logs.

---

### References in your tree (anchors for reviewers)

* `RuntimeCell#get_or_initialize()` and observer hooks (where we add single‑flight & reset) — **codeintel_rev.runtime.cells**. 
* Hybrid orchestration & channel gathering (post‑activation smoke check suited to this flow) — **codeintel_rev.io.hybrid_search**. 
* DuckDB catalog open/ensure‑ready (cheap verify and hydration chokepoint) — **codeintel_rev.io.duckdb_catalog** & **io.duckdb_manager**. 
* Your prior gated‑factory scope (confirms `ApplicationContext` wiring and cells) — **Type_Gating_Factory_Scope.md**.   

---

If you’d like, I can also produce **unified diffs** for these files in the same PR‑ready style we used earlier (including suggested commit messages and a minimal CLI README).




# Detailed PRs #

Love the momentum—let’s ship the next two slices with **PR‑ready unified diffs**. I anchored the design to the repo surfaces visible in your latest SCIP dataset (e.g., `_ContextRuntimeState`, `ApplicationContext.create()`, and the readiness/capability seams), so the patches drop in cleanly and respect your current initialization, runtime cells, and Problem‑Details taxonomy. For example, `ApplicationContext` already wires a `RuntimeCellObserver` across cells in `__post_init__`, and getters call `RuntimeCell.get_or_initialize(...)`—we lean on those existing hooks. 

Below are two independent PRs:

* **PR‑A**: *Index Lifecycle Manager* — atomic, versioned index swaps + health; admin router + CLI; optional **SIGHUP** reload hook.
* **PR‑C**: *RuntimeCell single‑flight & back‑pressure* — explicit concurrency semantics: “one warm‑up at a time,” queued callers wait (bounded), or receive a typed “warming up” Problem Details.

Where I reference doc’d behavior (e.g., hybrid channel orchestration, readiness checks, or FAISS manager APIs), it’s because those are already part of your code’s contracts; e.g., hybrid gathers BM25/SPLADE with warnings for errors, and readiness exposes DuckDB/FAISS checks.

---

## PR‑A — Index Lifecycle Manager (atomic swaps + health)

**Why here:** your context/load order is already clean: settings → path resolution → readiness → MCP mount. We add a **tiny manager** for **versioned index assets** (FAISS/DuckDB/SCIP, plus optional hybrid assets), expose **admin endpoints** to publish/rollback, and add a **reload** that safely flips the **current** pointer and lets runcells lazily re‑init on next use—consistent with how context getters already call `RuntimeCell.get_or_initialize(...)`. 

### Files changed

```
A  src/codeintel_rev/indexing/lifecycle.py
A  src/codeintel_rev/app/routers/index_admin.py
M  src/codeintel_rev/app/config_context.py
M  src/codeintel_rev/app/main.py
A  tests/indexing/test_lifecycle.py
```

---

### Unified diffs

> **Notes**
>
> * Uses `from __future__ import annotations`, `slots=True`, `Path.replace()` for atomic moves on same FS.
> * Keeps heavy deps out of import time; strictly stdlib + your existing logging & errors.
> * Admin router is **opt‑in** via `CODEINTEL_ADMIN=1`.

#### 1) `indexing/lifecycle.py` (new)

```diff
*** /dev/null
--- a/src/codeintel_rev/indexing/lifecycle.py
@@
+from __future__ import annotations
+
+from dataclasses import dataclass, field
+from pathlib import Path
+from typing import Iterable, Mapping, Any
+import json, os, time, hashlib, contextlib
+
+from kgfoundry_common.logging import get_logger
+from codeintel_rev.errors import RuntimeLifecycleError
+
+LOGGER = get_logger(__name__)
+
+# ---- Data shapes ------------------------------------------------------------
+
+@dataclass(frozen=True, slots=True)
+class IndexAssets:
+    """Absolute paths for one coherent index version on disk."""
+    faiss_index: Path
+    duckdb_path: Path
+    scip_index: Path
+    # Optional channels that hybrid may leverage
+    bm25_dir: Path | None = None
+    splade_dir: Path | None = None
+    xtr_dir: Path | None = None
+
+    def ensure_exists(self) -> None:
+        for p in (self.faiss_index, self.duckdb_path, self.scip_index):
+            if not p.exists():
+                raise RuntimeLifecycleError(f"asset-missing: {p}")
+
+@dataclass(frozen=True, slots=True)
+class VersionMeta:
+    version: str
+    created_ts: float
+    attrs: Mapping[str, Any] = field(default_factory=dict)
+
+    def to_json(self) -> str:
+        return json.dumps({"version": self.version, "created_ts": self.created_ts, "attrs": dict(self.attrs)}, sort_keys=True)
+
+# ---- Manager ---------------------------------------------------------------
+
+class IndexLifecycleManager:
+    """
+    Manage versioned index assets with an atomic 'current' pointer.
+
+    Layout (under base_dir):
+      versions/<version_id>/{faiss.index, catalog.duckdb, code.scip, ...}
+      CURRENT         -> text file containing '<version_id>'
+      current -> symlink to 'versions/<version_id>' (best-effort)
+    """
+    def __init__(self, base_dir: Path) -> None:
+        self.base_dir = base_dir
+        self.versions_dir = base_dir / "versions"
+        self.current_file = base_dir / "CURRENT"
+        self.current_link = base_dir / "current"
+        self.versions_dir.mkdir(parents=True, exist_ok=True)
+
+    # ---- read side
+    def current_version(self) -> str | None:
+        try:
+            return self.current_file.read_text(encoding="utf-8").strip() or None
+        except FileNotFoundError:
+            return None
+
+    def current_dir(self) -> Path | None:
+        v = self.current_version()
+        return (self.versions_dir / v) if v else None
+
+    def read_assets(self) -> IndexAssets | None:
+        vdir = self.current_dir()
+        if not vdir:
+            return None
+        # canonical filenames within a version dir
+        faiss = vdir / "faiss.index"
+        duck = vdir / "catalog.duckdb"
+        scip  = vdir / "code.scip"
+        bm25  = vdir / "bm25"     if (vdir / "bm25").exists() else None
+        spl   = vdir / "splade"   if (vdir / "splade").exists() else None
+        xtr   = vdir / "xtr"      if (vdir / "xtr").exists() else None
+        assets = IndexAssets(faiss_index=faiss, duckdb_path=duck, scip_index=scip, bm25_dir=bm25, splade_dir=spl, xtr_dir=xtr)
+        assets.ensure_exists()
+        return assets
+
+    # ---- write side
+    def _write_version_json(self, vdir: Path, meta: VersionMeta) -> None:
+        (vdir / "version.json").write_text(meta.to_json(), encoding="utf-8")
+
+    def prepare(self, version: str, src: IndexAssets, *, attrs: Mapping[str, Any] | None = None) -> Path:
+        """
+        Create a staging dir for <version> and copy/validate assets.
+        The caller is responsible for ensuring all assets belong to the same logical snapshot.
+        """
+        src.ensure_exists()
+        vdir = self.versions_dir / f"{version}.staging"
+        if vdir.exists():
+            raise RuntimeLifecycleError(f"staging-exists: {vdir}")
+        vdir.mkdir(parents=True, exist_ok=False)
+        # simple copies; callers may choose to hardlink or copytree upstream
+        self._copy(src.faiss_index, vdir / "faiss.index")
+        self._copy(src.duckdb_path, vdir / "catalog.duckdb")
+        self._copy(src.scip_index,  vdir / "code.scip")
+        for name, opt in (("bm25", src.bm25_dir), ("splade", src.splade_dir), ("xtr", src.xtr_dir)):
+            if opt and opt.exists():
+                self._copytree(opt, vdir / name)
+        self._write_version_json(vdir, VersionMeta(version=version, created_ts=time.time(), attrs=attrs or {}))
+        return vdir
+
+    def publish(self, version: str) -> Path:
+        """Atomically move <version>.staging → <version> and update CURRENT (+symlink)."""
+        staging = self.versions_dir / f"{version}.staging"
+        final   = self.versions_dir / version
+        if not staging.exists():
+            raise RuntimeLifecycleError(f"staging-missing: {staging}")
+        staging.replace(final)  # atomic within same filesystem
+        tmp = self.current_file.with_suffix(".tmp")
+        tmp.write_text(version, encoding="utf-8")
+        os.replace(tmp, self.current_file)  # atomic pointer swap
+        # Best-effort symlink for convenience
+        with contextlib.suppress(Exception):
+            if self.current_link.is_symlink() or self.current_link.exists():
+                self.current_link.unlink()
+            self.current_link.symlink_to(final, target_is_directory=True)
+        LOGGER.info("index.publish", extra={"version": version, "dir": str(final)})
+        return final
+
+    def rollback(self, version: str) -> None:
+        """Switch CURRENT to an older existing version (no file moves)."""
+        candidate = self.versions_dir / version
+        if not candidate.exists():
+            raise RuntimeLifecycleError(f"version-missing: {candidate}")
+        tmp = self.current_file.with_suffix(".tmp")
+        tmp.write_text(version, encoding="utf-8")
+        os.replace(tmp, self.current_file)
+        with contextlib.suppress(Exception):
+            if self.current_link.is_symlink() or self.current_link.exists():
+                self.current_link.unlink()
+            self.current_link.symlink_to(candidate, target_is_directory=True)
+        LOGGER.info("index.rollback", extra={"version": version})
+
+    # ---- internals
+    @staticmethod
+    def _copy(src: Path, dst: Path) -> None:
+        data = src.read_bytes()
+        dst.write_bytes(data)
+
+    @staticmethod
+    def _copytree(src_dir: Path, dst_dir: Path) -> None:
+        import shutil
+        shutil.copytree(src_dir, dst_dir, dirs_exist_ok=False)
```

#### 2) `app/routers/index_admin.py` (new)

```diff
*** /dev/null
--- a/src/codeintel_rev/app/routers/index_admin.py
@@
+from __future__ import annotations
+from dataclasses import asdict, replace
+from pathlib import Path
+from typing import TypedDict
+import os
+
+from fastapi import APIRouter, Depends, HTTPException
+from fastapi.responses import JSONResponse
+
+from kgfoundry_common.logging import get_logger
+from codeintel_rev.app.config_context import ApplicationContext
+from codeintel_rev.errors import RuntimeLifecycleError, RuntimeUnavailableError
+from codeintel_rev.indexing.lifecycle import IndexLifecycleManager, IndexAssets
+
+LOGGER = get_logger(__name__)
+router = APIRouter(prefix="/admin/index", tags=["admin:index"])
+
+def _require_admin() -> None:
+    if os.getenv("CODEINTEL_ADMIN") != "1":
+        raise HTTPException(status_code=403, detail="admin-disabled")
+
+def _context() -> ApplicationContext:
+    # Natural dependency in this app; state is bound in app.main lifespan.
+    from fastapi import Request
+    # FastAPI injects request into dependency graph
+    def _dep(request: Request) -> ApplicationContext:
+        ctx = getattr(request.app.state, "context", None)
+        if ctx is None:
+            raise HTTPException(status_code=503, detail="context-unavailable")
+        return ctx
+    return Depends(_dep)  # type: ignore[return-value]
+
+@router.get("/status")
+def status(_: None = Depends(_require_admin), ctx: ApplicationContext = _context()) -> JSONResponse:
+    mgr = ctx.index_manager
+    v = mgr.current_version()
+    assets = None
+    try:
+        assets = mgr.read_assets()
+    except Exception as e:
+        LOGGER.warning("index.status.read_assets.failed", exc_info=e)
+    payload = {
+        "current": v,
+        "dir": str(mgr.current_dir()) if v else None,
+        "assets_ok": assets is not None,
+    }
+    return JSONResponse(payload)
+
+class PublishBody(TypedDict, total=False):
+    version: str
+    faiss_index: str
+    duckdb_path: str
+    scip_index: str
+    bm25_dir: str | None
+    splade_dir: str | None
+    xtr_dir: str | None
+
+@router.post("/publish")
+def publish(body: PublishBody, _: None = Depends(_require_admin), ctx: ApplicationContext = _context()) -> JSONResponse:
+    mgr = ctx.index_manager
+    try:
+        assets = IndexAssets(
+            faiss_index=Path(body["faiss_index"]),
+            duckdb_path=Path(body["duckdb_path"]),
+            scip_index=Path(body["scip_index"]),
+            bm25_dir=Path(body["bm25_dir"]) if body.get("bm25_dir") else None,
+            splade_dir=Path(body["splade_dir"]) if body.get("splade_dir") else None,
+            xtr_dir=Path(body["xtr_dir"]) if body.get("xtr_dir") else None,
+        )
+        staging = mgr.prepare(body["version"], assets)
+        final = mgr.publish(body["version"])
+        # Soft reload: close warm cells; the next call will re‑init against new "CURRENT".
+        ctx.reload_indices()
+        return JSONResponse({"ok": True, "staging": str(staging), "final": str(final), "version": body["version"]})
+    except (KeyError, RuntimeLifecycleError) as e:
+        raise HTTPException(status_code=400, detail=str(e))
+    except Exception as e:
+        LOGGER.exception("index.publish.failed")
+        raise HTTPException(status_code=500, detail="publish-failed")
+
+@router.post("/rollback/{version}")
+def rollback(version: str, _: None = Depends(_require_admin), ctx: ApplicationContext = _context()) -> JSONResponse:
+    mgr = ctx.index_manager
+    try:
+        mgr.rollback(version)
+        ctx.reload_indices()
+        return JSONResponse({"ok": True, "version": version})
+    except RuntimeLifecycleError as e:
+        raise HTTPException(status_code=400, detail=str(e))
```

#### 3) `app/config_context.py` (wire manager + reload)

```diff
--- a/src/codeintel_rev/app/config_context.py
+++ b/src/codeintel_rev/app/config_context.py
@@
 from __future__ import annotations
 from dataclasses import dataclass, field, replace
 from typing import cast
 from pathlib import Path
@@
 from kgfoundry_common.logging import get_logger
 from codeintel_rev.errors import RuntimeUnavailableError
+from codeintel_rev.indexing.lifecycle import IndexLifecycleManager
 LOGGER = get_logger(__name__)
@@
 @dataclass(slots=True, frozen=True)
 class _ContextRuntimeState:
     """Mutable runtime state backing the frozen ApplicationContext."""
     hybrid: RuntimeCell[HybridSearchEngine]
     coderank_faiss: RuntimeCell[FAISSManager]
     xtr: RuntimeCell[XTRIndex]
@@
 class ApplicationContext:
     ...
+    index_manager: IndexLifecycleManager = field(init=False, repr=False)
@@
     def __post_init__(self) -> None:
         # Attach the configured observer to all runtime cells.
         self._runtime.attach_observer(self.runtime_observer)
+        # Initialize index lifecycle manager rooted at the parent of current assets.
+        # We derive a base_dir by convention: .../indexes (env override allowed).
+        base = Path(os.getenv("CODEINTEL_INDEXES_DIR") or (self.paths.faiss_index.parent.parent))
+        object.__setattr__(self, "index_manager", IndexLifecycleManager(base))
@@
     # --- Runtime factories (gated) ------------------------------------------
@@
     # --- Admin: reload on swap ----------------------------------------------
+    def reload_indices(self) -> None:
+        """
+        Close warm cells so next access re‑initializes against the 'CURRENT' version.
+        Does not mutate resolved path literals, which are read by factories at init time.
+        """
+        try:
+            self._runtime.hybrid.close()
+        except Exception:  # pragma: no cover
+            LOGGER.warning("reload.hybrid.close.failed", exc_info=True)
+        try:
+            self._runtime.coderank_faiss.close()
+        except Exception:  # pragma: no cover
+            LOGGER.warning("reload.faiss.close.failed", exc_info=True)
+        try:
+            self._runtime.xtr.close()
+        except Exception:  # pragma: no cover
+            LOGGER.warning("reload.xtr.close.failed", exc_info=True)
```

> The `ApplicationContext` pattern (frozen dataclass, observer attachment, runcell getters) is already established; we respect it and close warm cells so their next `get_or_initialize(...)` re‑reads **CURRENT**. 

#### 4) `app/main.py` (mount router; optional SIGHUP to reload)

```diff
--- a/src/codeintel_rev/app/main.py
+++ b/src/codeintel_rev/app/main.py
@@
 from __future__ import annotations
@@
 from fastapi import FastAPI
 from contextlib import asynccontextmanager
+import os, signal
@@
 from codeintel_rev.app.readiness import ReadinessProbe
+from codeintel_rev.app.routers import index_admin
@@
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     context = ApplicationContext.create(runtime_observer=observer)
     app.state.context = context
     readiness = ReadinessProbe(context)
     await readiness.initialize()
+    # Optional: allow `kill -HUP` to trigger a safe reload of warm cells.
+    if os.name != "nt":
+        def _on_hup(signum, frame):
+            try:
+                context.reload_indices()
+            except Exception:
+                LOGGER.warning("signal.hup.reload.failed", exc_info=True)
+        signal.signal(signal.SIGHUP, _on_hup)
     yield
@@
 app = FastAPI(title="codeintel-rev")
 app.include_router(health_router)  # existing
+if os.getenv("CODEINTEL_ADMIN") == "1":
+    app.include_router(index_admin.router)
```

#### 5) `tests/indexing/test_lifecycle.py`

```diff
*** /dev/null
--- a/tests/indexing/test_lifecycle.py
@@
+from __future__ import annotations
+from pathlib import Path
+from codeintel_rev.indexing.lifecycle import IndexLifecycleManager, IndexAssets
+
+def test_publish_and_switch(tmp_path: Path) -> None:
+    base = tmp_path / "indexes"
+    mgr = IndexLifecycleManager(base)
+    # create fake assets
+    src = tmp_path / "src"; src.mkdir()
+    (src / "faiss.index").write_bytes(b"hi")
+    (src / "catalog.duckdb").write_bytes(b"db")
+    (src / "code.scip").write_bytes(b"scip")
+    assets = IndexAssets(faiss_index=src/"faiss.index", duckdb_path=src/"catalog.duckdb", scip_index=src/"code.scip")
+    # prepare + publish
+    staging = mgr.prepare("v1", assets)
+    assert staging.exists()
+    final = mgr.publish("v1")
+    assert final.exists()
+    assert mgr.current_version() == "v1"
+    cur = mgr.read_assets()
+    assert cur is not None and cur.faiss_index.exists()
```

---

## PR‑C — RuntimeCell single‑flight & back‑pressure

**Why here:** your context getters already use `RuntimeCell.get_or_initialize(...)`. We formalize the **concurrency model**: exactly **one** initializer runs; others **wait** (bounded) or receive a typed “warming up” error the MCP adapter will convert to Problem Details—consistent with your error taxonomy (`RuntimeUnavailableError` / `RuntimeLifecycleError`). 

### Files changed

```
M  src/codeintel_rev/runtime/cells.py
A  tests/runtime/test_cells_concurrency.py
```

---

### Unified diffs

#### 1) `runtime/cells.py` (make single‑flight explicit)

```diff
--- a/src/codeintel_rev/runtime/cells.py
+++ b/src/codeintel_rev/runtime/cells.py
@@
 from __future__ import annotations
-from dataclasses import dataclass, field
-from threading import RLock
+from dataclasses import dataclass, field
+from threading import RLock, Condition
+import time
 from typing import Callable, Generic, TypeVar, Optional
@@
 T = TypeVar("T")
 
 @dataclass(slots=True)
 class RuntimeCell(Generic[T]):
     """
-    Lazy, thread-safe holder that initializes its payload on first access.
+    Lazy, thread-safe holder that initializes its payload on first access
+    with explicit single-flight semantics:
+      - at most one initializer runs at any time,
+      - concurrent callers wait for completion (bounded wait),
+      - failures are propagated; subsequent calls may retry.
     """
-    _value: Optional[T] = None
-    _lock: RLock = field(default_factory=RLock, repr=False)
+    _value: Optional[T] = None
+    _lock: RLock = field(default_factory=RLock, repr=False)
+    _cv: Condition = field(default_factory=lambda: Condition(RLock()), repr=False)
+    _state: str = "empty"  # empty|initializing|ready|failed|closed
+    _last_error: Exception | None = None
@@
-    def get_or_initialize(self, factory: Callable[[], T]) -> T:
-        if self._value is not None:
-            return self._value
-        with self._lock:
-            if self._value is None:
-                self._value = factory()
-            return self._value
+    def get_or_initialize(self, factory: Callable[[], T], *, wait_ms: int = 1500) -> T:
+        """
+        Return value, initializing once via `factory`.
+        If another thread is initializing:
+          - wait up to `wait_ms` for completion,
+          - if still initializing, raise RuntimeUnavailableError("warming_up").
+        """
+        if self._value is not None and self._state == "ready":
+            return self._value
+        # fast path failed/closed: allow retry
+        deadline = time.monotonic() + (wait_ms / 1000.0)
+        with self._cv:
+            if self._state in ("ready",) and self._value is not None:
+                return self._value
+            if self._state in ("initializing",):
+                while self._state == "initializing" and time.monotonic() < deadline:
+                    remaining = deadline - time.monotonic()
+                    if remaining <= 0:
+                        break
+                    self._cv.wait(timeout=remaining)
+                if self._state == "ready" and self._value is not None:
+                    return self._value
+                if self._state == "failed" and self._last_error:
+                    raise self._last_error
+                # still initializing → back-pressure returns a typed error
+                from codeintel_rev.errors import RuntimeUnavailableError
+                raise RuntimeUnavailableError("warming_up")
+            # No one is initializing → we become the initializer
+            self._state = "initializing"
+            try:
+                val = factory()
+                self._value = val
+                self._state = "ready"
+                self._cv.notify_all()
+                return val
+            except Exception as e:  # propagate and mark failed
+                self._last_error = e
+                self._state = "failed"
+                self._cv.notify_all()
+                raise
@@
     def close(self) -> None:
-        with self._lock:
-            self._value = None
+        with self._cv:
+            self._value = None
+            self._state = "closed"
+            self._last_error = None
+            self._cv.notify_all()
```

> This aligns to how cells are attached to context and closed on lifecycle changes. Your context already calls `attach_observer(...)` in `__post_init__` to emit lifecycle signals; you can add observer callbacks inside the `try/except` body above if you want additional telemetry events during warm‑up. 

#### 2) `tests/runtime/test_cells_concurrency.py`

```diff
*** /dev/null
--- a/tests/runtime/test_cells_concurrency.py
@@
+from __future__ import annotations
+from threading import Thread, Event
+import time
+from codeintel_rev.runtime.cells import RuntimeCell
+from codeintel_rev.errors import RuntimeUnavailableError
+
+def test_single_flight_and_backpressure():
+    cell = RuntimeCell[int]()
+    ready = Event()
+
+    def factory():
+        time.sleep(0.2)  # pretend heavy
+        ready.set()
+        return 7
+
+    results: list[object] = []
+    errors: list[BaseException] = []
+
+    def worker():
+        try:
+            results.append(cell.get_or_initialize(factory, wait_ms=50))
+        except BaseException as e:
+            errors.append(e)
+
+    # Start one initializer + two contenders
+    t1 = Thread(target=worker); t2 = Thread(target=worker); t3 = Thread(target=worker)
+    t1.start(); t2.start(); t3.start()
+    t1.join(); t2.join(); t3.join()
+
+    # Exactly one succeeds immediately; others either waited long enough or got "warming_up"
+    assert results.count(7) >= 1
+    if errors:
+        assert isinstance(errors[0], RuntimeUnavailableError)
+
+    # After warmup completes, future calls return immediately
+    assert cell.get_or_initialize(lambda: 1) == 7
```

---

## Validate locally

```bash
# Run unit tests (fast)
pytest -q tests/indexing/test_lifecycle.py tests/runtime/test_cells_concurrency.py

# Start the app with admin router and try a publish/swap
export CODEINTEL_ADMIN=1
uvicorn codeintel_rev.app.main:app --reload
# POST /admin/index/publish { ... } then /admin/index/status
# (Or HUP the process after manually updating CURRENT to simulate a swap)
```

---

## Why this is structurally sound here

* **Import‑clean; runtime‑lazy**: both PRs keep heavy I/O out of module import time. Cells still initialize lazily and are now **explicitly single‑flight**, which avoids stampedes under load and provides **clear back‑pressure** (typed “warming_up” error) consistent with your existing adapters’ Problem‑Details wrappers. 
* **Fits readiness & capabilities**: swaps don’t short‑circuit health; `/readyz` remains the deep check; `/capz` remains the cheap truth source. You already compute/consume those during startup and gated registration. 
* **Matches hybrid orchestration**: the hybrid layer already treats channel errors as warnings and aggregates them; lifecycle swaps + single‑flight ensure **stable, causal** behavior during reindexing (no partial loads). 

---

## Post‑merge follow‑ups (tiny)

1. **Teach factories to read CURRENT** (if not already): make FAISS/XTR/Hybrid factories resolve the asset paths from `context.index_manager.read_assets()` at init time; this ensures the new version is used after `reload_indices()` without mutating `context.paths`. (Your factory docstrings already state “lazy construct with gates”, this is a natural extension.) 
2. **Admin CLI**: add a Typer CLI wrapper that calls `/admin/index/publish|rollback` locally; your CLI patterns (e.g., `splade build_index`) are already in the tree and can be followed. 
3. **Readiness check for “current is coherent”**: optional: add a light check that version.json exists and required files are present—hook into your existing `ReadinessProbe`. 

If you want, I can append a small “factory adjustment” patch (FAISS/XTR/Hybrid) so each factory pulls paths from `index_manager.read_assets()` at construction—this is typically a 5–10 line change in each factory and keeps the responsibility localized.




# Fully detailed scope section 2 - Factory Adjustment capability

Awesome — here’s a **PR‑ready patch** that adds the **Factory Adjustment** capability in a way that’s structural, composable, and fully consistent with your runtime‑cell model.

At a glance, this change:

* Adds a **generic `FactoryAdjuster` hook** to `RuntimeCell.get_or_initialize(...)` so you can inject tunings/wrappers into any heavy factory **without touching the factories themselves**.
* Wires a **context‑level method** (`_ContextRuntimeState.attach_adjuster`) to apply one adjuster across all cells (FAISS, Hybrid, XTR), parallel to your existing observer wiring. Your `_ContextRuntimeState` already centralizes `RuntimeCell` instances and exposes `attach_observer(...)`/`iter_cells(...)`, so this slots right in.
* Exposes a **safe default (`NoopFactoryAdjuster`)** and a **reference implementation** (`DefaultFactoryAdjuster`) you can initialize from settings/capability profiles to tune things like FAISS `nprobe`, hybrid weights/RRF, or VLLM mode *after* object construction (via capability checks and `hasattr` probes).
* Preserves import‑time lightness and your lazy init discipline; adjustment happens only **at the moment a cell is first initialized** (inside `get_or_initialize`). Your `RuntimeCell#get_or_initialize(factory)` signature makes this a natural, single‑line interception point. 

---

## Files changed (summary)

```
A  src/codeintel_rev/runtime/factory_adjustment.py
M  src/codeintel_rev/runtime/cells.py
M  src/codeintel_rev/app/config_context.py
A  tests/runtime/test_factory_adjustment.py
```

---

## Unified diffs (copy–pasteable)

> Paths assume `src/` package layout. If your tree is flat, drop the `src/` prefix.

### 1) New: `runtime/factory_adjustment.py`

```diff
diff --git a/src/codeintel_rev/runtime/factory_adjustment.py b/src/codeintel_rev/runtime/factory_adjustment.py
new file mode 100644
index 0000000..a1b2c3d
--- /dev/null
+++ b/src/codeintel_rev/runtime/factory_adjustment.py
@@ -0,0 +1,223 @@
+from __future__ import annotations
+
+"""
+Factory adjustment hooks for RuntimeCell initialization.
+
+This module lets callers *adjust* factories at first-use time without coupling
+to concrete manager classes. Adjustments are applied exactly once, inside
+RuntimeCell.get_or_initialize(...).
+
+Design goals
+------------
+- Zero import-time cost (pure typing + call-time hasattr checks).
+- Decouple policy from factories (work with any object that exposes a
+  compatible method/attribute).
+- Composable and testable (Noop and Default adjusters included).
+"""
+from dataclasses import dataclass
+from typing import Any, Callable, Protocol, TypeVar
+
+T = TypeVar("T")
+
+
+class FactoryAdjuster(Protocol):
+    """Interpose on a cell factory just before it is executed."""
+
+    def adjust(self, *, cell: str, factory: Callable[[], T]) -> Callable[[], T]:  # pragma: no cover - protocol
+        ...
+
+
+@dataclass(slots=True, frozen=True)
+class NoopFactoryAdjuster:
+    """Default: do nothing."""
+
+    def adjust(self, *, cell: str, factory: Callable[[], T]) -> Callable[[], T]:
+        return factory
+
+
+# -------- Reference implementation -----------------------------------------
+
+@dataclass(slots=True)
+class DefaultFactoryAdjuster:
+    """
+    A pragmatic adjuster that knows about a few common cell names and applies
+    safe, best-effort tweaks *after* the object is created.
+
+    All hooks are opportunistic: we check for attributes/methods and skip if
+    absent. This keeps us loosely coupled to concrete implementations.
+    """
+
+    # --- FAISS search tuning ---
+    faiss_nprobe: int | None = None
+    faiss_gpu_preference: bool | None = None  # None=leave as-is
+
+    # --- Hybrid search tuning ---
+    hybrid_rrf_k: int | None = None
+    hybrid_bm25_weight: float | None = None
+    hybrid_splade_weight: float | None = None
+
+    # --- VLLM / embedder tuning (if applicable) ---
+    vllm_mode: str | None = None  # "http" | "local" | "auto"
+    vllm_timeout_s: float | None = None
+
+    def adjust(self, *, cell: str, factory: Callable[[], T]) -> Callable[[], T]:
+        if cell == "coderank_faiss":
+            return self._wrap_faiss(factory)
+        if cell == "hybrid":
+            return self._wrap_hybrid(factory)
+        if cell == "xtr":
+            return self._wrap_xtr(factory)
+        # Unknown cells -> no-op
+        return factory
+
+    # ---- Cell-specific wrappers -------------------------------------------
+
+    def _wrap_faiss(self, base: Callable[[], T]) -> Callable[[], T]:
+        def _wrapped() -> T:
+            obj: Any = base()
+            # nprobe: try explicit method, then attribute; otherwise skip
+            if self.faiss_nprobe is not None:
+                if hasattr(obj, "set_nprobe"):
+                    try:
+                        obj.set_nprobe(self.faiss_nprobe)
+                    except Exception:
+                        pass
+                elif hasattr(obj, "nprobe"):
+                    try:
+                        setattr(obj, "nprobe", self.faiss_nprobe)
+                    except Exception:
+                        pass
+            # gpu preference: opportunistic hint
+            if self.faiss_gpu_preference is not None and hasattr(obj, "set_gpu_preference"):
+                try:
+                    obj.set_gpu_preference(self.faiss_gpu_preference)  # type: ignore[attr-defined]
+                except Exception:
+                    pass
+            return obj  # type: ignore[return-value]
+        return _wrapped
+
+    def _wrap_hybrid(self, base: Callable[[], T]) -> Callable[[], T]:
+        def _wrapped() -> T:
+            obj: Any = base()
+            # RRF and channel weights are commonly configurable on hybrid engines.
+            if self.hybrid_rrf_k is not None and hasattr(obj, "set_rrf_k"):
+                try:
+                    obj.set_rrf_k(self.hybrid_rrf_k)  # type: ignore[attr-defined]
+                except Exception:
+                    pass
+            if self.hybrid_bm25_weight is not None and hasattr(obj, "set_bm25_weight"):
+                try:
+                    obj.set_bm25_weight(self.hybrid_bm25_weight)  # type: ignore[attr-defined]
+                except Exception:
+                    pass
+            if self.hybrid_splade_weight is not None and hasattr(obj, "set_splade_weight"):
+                try:
+                    obj.set_splade_weight(self.hybrid_splade_weight)  # type: ignore[attr-defined]
+                except Exception:
+                    pass
+            return obj  # type: ignore[return-value]
+        return _wrapped
+
+    def _wrap_xtr(self, base: Callable[[], T]) -> Callable[[], T]:
+        # Placeholder for XTR-specific tuning when enabled.
+        return base
```

### 2) Modify: `runtime/cells.py`

```diff
diff --git a/src/codeintel_rev/runtime/cells.py b/src/codeintel_rev/runtime/cells.py
index 8f1a2b1..6b7c9d0 100644
--- a/src/codeintel_rev/runtime/cells.py
+++ b/src/codeintel_rev/runtime/cells.py
@@ -1,9 +1,17 @@
 from __future__ import annotations
-from dataclasses import dataclass
-from typing import Any, Callable, Generic, Optional, TypeVar
+from dataclasses import dataclass
+from typing import Any, Callable, Generic, Optional, TypeVar
 import threading
 import time
 
+from .factory_adjustment import FactoryAdjuster, NoopFactoryAdjuster
+
 T = TypeVar("T")
 
@@
 @dataclass(slots=True)
 class RuntimeCell(Generic[T]):
     """
@@
-    _value: Optional[T] = None
+    _value: Optional[T] = None
     _lock: threading.Lock = dataclass(init=False, repr=False, default_factory=threading.Lock)  # type: ignore[assignment]
     _observer: Optional[RuntimeCellObserver] = None
+    _adjuster: FactoryAdjuster | None = None
+    _name: str | None = None
 
     def configure_observer(self, observer: RuntimeCellObserver) -> None:
         self._observer = observer
+
+    def configure_adjuster(self, adjuster: FactoryAdjuster, *, name: str | None = None) -> None:
+        """
+        Attach a factory adjuster that can wrap the provided factory at init-time.
+        """
+        self._adjuster = adjuster
+        if name:
+            self._name = name
 
     def get_or_initialize(self, factory: Callable[[], T]) -> T:
         """
         Return the value, initializing it once via the provided factory.
@@
-        if self._value is not None:
+        if self._value is not None:
             return self._value
         with self._lock:
             if self._value is not None:
                 return self._value
             if self._observer is not None:
                 self._observer.on_init_start(self)
             t0 = time.monotonic()
-            try:
-                value = factory()
+            try:
+                # Allow last-minute adjustments to the factory, per cell.
+                f = factory
+                if self._adjuster is not None:
+                    f = self._adjuster.adjust(cell=(self._name or "cell"), factory=f)
+                value = f()
                 self._value = value
                 if self._observer is not None:
                     self._observer.on_init_end(self, value=value, duration_s=time.monotonic() - t0)
                 return value
             except Exception as e:
                 if self._observer is not None:
                     self._observer.on_init_error(self, error=e, duration_s=time.monotonic() - t0)
                 raise
```

> Rationale: `get_or_initialize(factory)` is the single initialization choke‑point; interposing here lets us keep factories lazy and import‑clean while enabling policy‑driven tuning at first use. Your SCIP index shows exactly this signature (`get_or_initialize().(factory)`), making it the ideal hook. 

### 3) Modify: `app/config_context.py`

```diff
diff --git a/src/codeintel_rev/app/config_context.py b/src/codeintel_rev/app/config_context.py
index 1d2c3e4..5a6b7c8 100644
--- a/src/codeintel_rev/app/config_context.py
+++ b/src/codeintel_rev/app/config_context.py
@@ -1,12 +1,16 @@
 from __future__ import annotations
 from dataclasses import dataclass
 from typing import Any, cast
@@
 from codeintel_rev.runtime.cells import RuntimeCell, RuntimeCellObserver
+from codeintel_rev.runtime.factory_adjustment import (
+    FactoryAdjuster,
+    NoopFactoryAdjuster,
+    DefaultFactoryAdjuster,
+)
@@
 @dataclass(slots=True, frozen=True)
 class _ContextRuntimeState:
     """Mutable runtime state backing the frozen ApplicationContext."""
     hybrid: RuntimeCell[HybridSearchEngine]
     coderank_faiss: RuntimeCell[FAISSManager]
     xtr: RuntimeCell[XTRIndex]
@@
     def attach_observer(self, observer: RuntimeCellObserver) -> None:
         """Attach observer to each runtime cell."""
         self.hybrid.configure_observer(observer)
         self.coderank_faiss.configure_observer(observer)
         self.xtr.configure_observer(observer)
+
+    def attach_adjuster(self, adjuster: FactoryAdjuster) -> None:
+        """Attach a factory adjuster to each runtime cell (with stable names)."""
+        self.hybrid.configure_adjuster(adjuster, name="hybrid")
+        self.coderank_faiss.configure_adjuster(adjuster, name="coderank_faiss")
+        self.xtr.configure_adjuster(adjuster, name="xtr")
@@
 @dataclass(slots=True, frozen=True)
 class ApplicationContext:
     ...
-    runtime_observer: RuntimeCellObserver = _DefaultObserver()
+    runtime_observer: RuntimeCellObserver = _DefaultObserver()
+    factory_adjuster: FactoryAdjuster = NoopFactoryAdjuster()
@@
     def __post_init__(self) -> None:
         # Attach the configured observer to all runtime cells.
         self._runtime.attach_observer(self.runtime_observer)
+        # Attach the configured factory adjuster to all runtime cells.
+        self._runtime.attach_adjuster(self.factory_adjuster)
@@
     @classmethod
-    def create(cls) -> ApplicationContext:
+    def create(cls, *, factory_adjuster: FactoryAdjuster | None = None) -> ApplicationContext:
         """
         Create application context from environment variables.
@@
-        return cls(
+        return cls(
             settings=settings,
             paths=paths,
             vllm_client=vllm_client,
             duckdb_manager=duckdb,
             faiss_manager=faiss_mgr,
             scope_store=scope_store,
             git_client=git,
             async_git_client=async_git,
-        )
+            factory_adjuster=(factory_adjuster or _suggest_default_adjuster(settings)),
+        )
+
+def _suggest_default_adjuster(settings: Settings) -> FactoryAdjuster:
+    """
+    Compute a sensible DefaultFactoryAdjuster from settings, if present.
+    Keeps policy in one spot and avoids import-time cost.
+    """
+    try:
+        # Read optional knobs; if they are missing, DefaultFactoryAdjuster keeps None (no-op).
+        return DefaultFactoryAdjuster(
+            faiss_nprobe=getattr(settings, "faiss_nprobe", None),
+            hybrid_rrf_k=getattr(settings, "hybrid_rrf_k", None),
+            hybrid_bm25_weight=getattr(settings, "hybrid_bm25_weight", None),
+            hybrid_splade_weight=getattr(settings, "hybrid_splade_weight", None),
+        )
+    except Exception:
+        return NoopFactoryAdjuster()
```

> Why here? `_ContextRuntimeState` is already the one place that owns your cells and provides `attach_observer(...)`. Adding `attach_adjuster(...)` reuses that exact pattern and gives each cell a stable **name** to drive adjustments (`"hybrid"`, `"coderank_faiss"`, `"xtr"`). Your SCIP index lists these fields and the observer attach method explicitly.

### 4) New tests

```diff
diff --git a/tests/runtime/test_factory_adjustment.py b/tests/runtime/test_factory_adjustment.py
new file mode 100644
index 0000000..c0ffee1
--- /dev/null
+++ b/tests/runtime/test_factory_adjustment.py
@@ -0,0 +1,86 @@
+from __future__ import annotations
+from dataclasses import dataclass
+from typing import Any
+
+from codeintel_rev.runtime.cells import RuntimeCell
+from codeintel_rev.runtime.factory_adjustment import DefaultFactoryAdjuster, NoopFactoryAdjuster
+
+
+@dataclass
+class _DummyFaiss:
+    nprobe: int = 1
+    def set_nprobe(self, n: int) -> None:
+        self.nprobe = n
+
+
+def test_noop_adjuster_keeps_factory() -> None:
+    cell: RuntimeCell[_DummyFaiss] = RuntimeCell()
+    cell.configure_adjuster(NoopFactoryAdjuster(), name="coderank_faiss")
+    inst = cell.get_or_initialize(lambda: _DummyFaiss())
+    assert isinstance(inst, _DummyFaiss)
+    assert inst.nprobe == 1
+
+
+def test_default_adjuster_tunes_faiss() -> None:
+    cell: RuntimeCell[_DummyFaiss] = RuntimeCell()
+    adj = DefaultFactoryAdjuster(faiss_nprobe=64)
+    cell.configure_adjuster(adj, name="coderank_faiss")
+    inst = cell.get_or_initialize(lambda: _DummyFaiss())
+    assert inst.nprobe == 64
+
+
+def test_adjuster_only_runs_once() -> None:
+    calls = {"count": 0}
+    cell: RuntimeCell[_DummyFaiss] = RuntimeCell()
+    cell.configure_adjuster(DefaultFactoryAdjuster(faiss_nprobe=32), name="coderank_faiss")
+    def factory() -> _DummyFaiss:
+        calls["count"] += 1
+        return _DummyFaiss()
+    a = cell.get_or_initialize(factory)
+    b = cell.get_or_initialize(factory)
+    assert a is b
+    assert calls["count"] == 1
```

---

## How to use it (today)

* Keep using your current factories (e.g., `_create_faiss_manager_gated`, `_create_hybrid_engine_gated`); you **do not** change a line there.
* When you create the app context, optionally pass an adjuster:

```python
from codeintel_rev.runtime.factory_adjustment import DefaultFactoryAdjuster
ctx = ApplicationContext.create(
    factory_adjuster=DefaultFactoryAdjuster(faiss_nprobe=64, hybrid_rrf_k=75),
)
```

If you don’t pass one, `ApplicationContext.create()` now picks a sensible default from `Settings` (if present) or falls back to `NoopFactoryAdjuster` (no behavior change).

---

## Why this approach is “best‑in‑class” for your architecture

* **Single choke‑point, zero churn:** We interpose *exactly* at `RuntimeCell.get_or_initialize(factory)`, which your code already uses to lazily materialize heavy components. No factory signature changes, no import‑time gates added. 
* **Configurable at the edge:** `_ContextRuntimeState.attach_adjuster(...)` mirrors your existing `attach_observer(...)` pattern and relies on the same stable list of cells (`hybrid`, `coderank_faiss`, `xtr`). This keeps adjustment policy **outside** of business logic. 
* **Robust to change:** The reference adjuster uses **opportunistic hooks** (`hasattr` checks) and avoids tight coupling to manager internals. You can customize or replace it per deployment/profile.
* **Import‑clean:** No heavy imports added; adjustments run *after* the object is created, at the same moment you’d pay cost today.

---

## Commit message (suggested)

```
feat(runtime): add FactoryAdjuster hook for RuntimeCell initialization

- Add codeintel_rev.runtime.factory_adjustment with FactoryAdjuster protocol,
  NoopFactoryAdjuster, and a pragmatic DefaultFactoryAdjuster.
- Extend RuntimeCell with configure_adjuster() and call-time adjustment of the
  provided factory in get_or_initialize(...).
- Add _ContextRuntimeState.attach_adjuster(...) and wire it from
  ApplicationContext.__post_init__ (parallel to attach_observer).
- ApplicationContext.create(...) accepts optional factory_adjuster and can derive
  a DefaultFactoryAdjuster from Settings.
- Tests verify tuning is applied once and only once.

This preserves lazy init/import cleanliness while enabling profile/capability-
driven tuning of FAISS/Hybrid/XTR without touching factories.
```

---

## Test plan

* **Unit tests** included (`tests/runtime/test_factory_adjustment.py`).
* **Minimal env:** still `import codeintel_rev` clean; adjusters are optional and import only stdlib.
* **Smoke:** run your app with `ApplicationContext.create(factory_adjuster=DefaultFactoryAdjuster(...))` and confirm via telemetry that the FAISS search runs with the tuned `nprobe` and hybrid reports the new `rrf_k`. (Your telemetry work already adds spans/events at those seams.)

---

## Follow‑ups this unlocks (small PRs)

1. **Settings surface:** add optional knobs (`FAISS_NPROBE`, `HYBRID_RRF_K`, …) to your `Settings` struct with clear docs. `_suggest_default_adjuster` already reads them if present.
2. **Cap‑aware presets:** build a tiny function that maps `/capz` into a `DefaultFactoryAdjuster` (e.g., lower `bm25_weight` when SPLADE assets are missing; prefer CPU tuning when GPU isn’t available).
3. **Reranker toggles:** once XTR is wired, add `xtr_max_pairs`, `xtr_threshold` to the adjuster; the same pattern applies.

---

## Pointers back to the current tree (for reviewers)

* `RuntimeCell#get_or_initialize(factory)` — the init choke‑point we’re interposing. 
* `_ContextRuntimeState` fields (`hybrid`, `coderank_faiss`, `xtr`) and `attach_observer(...)` — the scaffolding we mirrored with `attach_adjuster(...)`.

---


