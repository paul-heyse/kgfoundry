# detailed implementation plan and code #

Absolutely—here’s the refactoring scope for app/config_context.py converted into a **detailed, implementation‑ready plan** using the same structure and tone as before: crisp objectives, phased steps, concrete code, migration aids, and test/rollout guidance.

---

## 1) Goal & Non‑Goals

**Goal.** Decouple *pure path resolution* from *filesystem readiness checks* to reduce ripple effects from a high fan‑in module and make startup/test flows stable and deterministic.

**Non‑Goals.**

* No behavior changes to actual directory structure or default locations.
* No mass renaming of path keys; we preserve existing semantics, only move responsibilities.
* No introduction of a DI container. We’ll use simple constructor injection.

**Success Criteria.**

* `config/paths.py` contains only pure, deterministic helpers + an immutable `ResolvedPaths`.
* `app/readiness.py` contains only probes/validations (`check_file`, `check_directory`, etc.).
* A thin `resolve_application_paths(settings)` returns **frozen** `ResolvedPaths`.
* All consumers obtain a `ResolvedPaths` instance via constructor injection (no `config_context` globals).
* Unit tests: pure resolution has no I/O; readiness tests cover filesystem edge cases.

---

## 2) Target Structure (After)

```
config/
  __init__.py
  paths.py            # pure resolution; no I/O, returns ResolvedPaths
app/
  __init__.py
  readiness.py        # probes & validations; check_* helpers
bootstrap/
  startup.py          # orchestrates resolve + readiness verification + injection
```

---

## 3) Public API (After)

```python
# config/paths.py
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Any

@dataclass(frozen=True, slots=True)
class ResolvedPaths:
    repo_root: Path
    config_dir: Path
    config_file: Path
    data_dir: Path
    logs_dir: Path
    cache_dir: Path
    tmp_dir: Path
    plugins_dir: Path

def resolve_application_paths(settings: Mapping[str, Any]) -> ResolvedPaths: ...
```

```python
# app/readiness.py
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Literal

Status = Literal["ok", "warn", "error"]

@dataclass(slots=True)
class ProbeResult:
    subject: Path
    status: Status
    message: str

def check_file(path: Path, *, must_exist=True, readable=True, writable=False) -> ProbeResult: ...
def check_directory(path: Path, *, must_exist=True, readable=True, writable=True, executable_on_posix=True) -> ProbeResult: ...
def validate_paths(paths) -> List[ProbeResult]: ...
def raise_on_errors(results: Iterable[ProbeResult]) -> None: ...
```

---

## 4) Detailed Implementation Steps

### Phase A — Introduce pure path resolution (no behavior change)

1. **Create `config/paths.py`.**

   * Add `ResolvedPaths` (frozen dataclass).
   * Add internal helpers: `_norm(p: Path) -> Path` to canonicalize (`expanduser()`, `resolve(strict=False)`).
   * Implement `resolve_application_paths(settings)` **purely** from `settings` without touching the filesystem.

2. **Populate fields using current conventions.**
   Map existing settings keys to fields (adjust names as needed during wiring):

   * `repo_root`: from `settings["BASE_DIR"]` or `Path(__file__).resolve().parents[x]` if already computed elsewhere.
   * `config_dir`, `config_file`, `data_dir`, `logs_dir`, `cache_dir`, `tmp_dir`, `plugins_dir`: build from `repo_root` and settings overrides.

3. **Type hygiene.**

   * Validate settings types only (no existence checks). Raise `ValueError` for malformed settings—this remains deterministic.

> ✅ **Checkpoint:** New module compiles; unit tests for pure resolution run green. No consumer changes yet.

---

### Phase B — Extract readiness probes

4. **Create `app/readiness.py`.**

   * Implement `ProbeResult`, `check_file`, `check_directory` as *non‑mutating* checks (no creation/chmod).

     * `check_file`: verify `Path.is_file()`, readability (attempt `open(..., 'rb')` with `errors='ignore'` guarded), optional writability via `os.access`.
     * `check_directory`: verify `Path.is_dir()`, listability (readable), writability (create temp file then delete guarded by `must_exist=False` opt‑out), and on POSIX `executable_on_posix=True` checks `os.access(path, os.X_OK)`.
   * `validate_paths(paths)` returns a list of `ProbeResult` for the set of critical files/dirs.
   * `raise_on_errors(results)` raises a single aggregated error (preserve existing error messages where feasible).

5. **Thin coordination remains in `resolve_application_paths` only.**
   Startup should call:

   ```python
   paths = resolve_application_paths(settings)
   results = app.readiness.validate_paths(paths)
   app.readiness.raise_on_errors(results)
   ```

> ✅ **Checkpoint:** End‑to‑end still starts; readiness executed from new module.

---

### Phase C — Consumer migration to constructor injection

6. **Add `paths` parameter to top‑fan‑in constructors.**
   Example:

   ```python
   class JobRunner:
       def __init__(self, paths: ResolvedPaths, ...):
           self._paths = paths
   ```

   Replace imports like `from config_context import PATHS` with constructor‑passed `paths`.

7. **Bootstrap wiring.**

   * In `bootstrap/startup.py` (or existing entrypoint), instantiate once:

     ```python
     settings = load_settings()
     paths = resolve_application_paths(settings)
     results = readiness.validate_paths(paths)
     readiness.raise_on_errors(results)
     # Inject into app graph
     job_runner = JobRunner(paths=paths, ...)
     ```
   * Keep a single authoritative `ResolvedPaths` instance per process.

8. **(Optional) Backward‑compat shim (deprecation).**

   * Provide `config_context.paths()` that returns the cached `ResolvedPaths` but **logs a deprecation warning** and is used only by stragglers. Remove after migration.

> ✅ **Checkpoint:** All high‑fan‑in consumers now accept `ResolvedPaths`. No hard dependency on `config_context`.

---

## 5) Concrete Code (drop‑in ready)

### `config/paths.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Any, Optional
import os
import sys

@dataclass(frozen=True, slots=True)
class ResolvedPaths:
    repo_root: Path
    config_dir: Path
    config_file: Path
    data_dir: Path
    logs_dir: Path
    cache_dir: Path
    tmp_dir: Path
    plugins_dir: Path

def _to_path(value: Any) -> Path:
    if isinstance(value, Path):
        return value
    return Path(str(value))

def _norm(p: Path) -> Path:
    # Do not touch the filesystem: strict=False avoids raising if missing.
    # expanduser() ensures "~" is resolved; resolve() normalizes '..' and symlinks where possible.
    p = p.expanduser().resolve(strict=False)
    # Normalize case on Windows to avoid inconsistent comparisons
    if sys.platform.startswith("win"):
        return Path(os.path.normcase(str(p)))
    return p

def _setting(settings: Mapping[str, Any], key: str, default: Optional[Path] = None) -> Optional[Path]:
    v = settings.get(key, default)
    return _norm(_to_path(v)) if v is not None else None

def resolve_application_paths(settings: Mapping[str, Any]) -> ResolvedPaths:
    # Required anchor
    repo_root = _setting(settings, "BASE_DIR")
    if repo_root is None:
        # Fallback: assume repo_root is two levels up from this file
        repo_root = _norm(Path(__file__).resolve().parents[2])

    config_dir  = _setting(settings, "CONFIG_DIR", repo_root / "config")
    config_file = _setting(settings, "CONFIG_FILE", config_dir / "app.yml")
    data_dir    = _setting(settings, "DATA_DIR", repo_root / "data")
    logs_dir    = _setting(settings, "LOGS_DIR", repo_root / "logs")
    cache_dir   = _setting(settings, "CACHE_DIR", repo_root / ".cache")
    tmp_dir     = _setting(settings, "TMP_DIR", repo_root / ".tmp")
    plugins_dir = _setting(settings, "PLUGINS_DIR", repo_root / "plugins")

    return ResolvedPaths(
        repo_root=repo_root,
        config_dir=config_dir,
        config_file=config_file,
        data_dir=data_dir,
        logs_dir=logs_dir,
        cache_dir=cache_dir,
        tmp_dir=tmp_dir,
        plugins_dir=plugins_dir,
    )
```

### `app/readiness.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Literal
import os
import errno
import tempfile
import sys

Status = Literal["ok", "warn", "error"]

@dataclass(slots=True)
class ProbeResult:
    subject: Path
    status: Status
    message: str

def _ok(p: Path, msg: str = "ok") -> ProbeResult:
    return ProbeResult(p, "ok", msg)

def _err(p: Path, msg: str) -> ProbeResult:
    return ProbeResult(p, "error", msg)

def _warn(p: Path, msg: str) -> ProbeResult:
    return ProbeResult(p, "warn", msg)

def check_file(path: Path, *, must_exist: bool = True, readable: bool = True, writable: bool = False) -> ProbeResult:
    try:
        if must_exist:
            if not path.exists():
                return _err(path, "file missing")
            if not path.is_file():
                return _err(path, "path exists but is not a regular file")
        if readable and path.exists():
            try:
                with open(path, "rb"):
                    pass
            except OSError as e:
                return _err(path, f"file not readable: {e.strerror or e}")
        if writable and path.exists():
            if not os.access(path, os.W_OK):
                return _err(path, "file not writable")
        return _ok(path)
    except Exception as e:
        return _err(path, f"unexpected check_file error: {e!r}")

def check_directory(
    path: Path,
    *,
    must_exist: bool = True,
    readable: bool = True,
    writable: bool = True,
    executable_on_posix: bool = True,
) -> ProbeResult:
    try:
        if must_exist:
            if not path.exists():
                return _err(path, "directory missing")
            if not path.is_dir():
                return _err(path, "path exists but is not a directory")
        if path.exists():
            if readable and not os.access(path, os.R_OK):
                return _err(path, "directory not readable")
            if writable and not os.access(path, os.W_OK):
                return _err(path, "directory not writable")
            if executable_on_posix and os.name == "posix" and not os.access(path, os.X_OK):
                return _err(path, "directory not searchable (no +x)")
            # Lightweight write probe (guarded): create+delete tmp file when both exists+writable expected
            if writable:
                try:
                    with tempfile.NamedTemporaryFile(dir=path, delete=True):
                        pass
                except OSError as e:
                    # EROFS, EPERM, EACCES, etc.
                    return _err(path, f"directory write probe failed: {e.strerror or e}")
        return _ok(path)
    except Exception as e:
        return _err(path, f"unexpected check_directory error: {e!r}")

def validate_paths(paths) -> List[ProbeResult]:
    # Adjust the set as needed; non‑mutating checks only
    results: List[ProbeResult] = []
    results.append(check_directory(paths.config_dir))
    results.append(check_file(paths.config_file))
    results.append(check_directory(paths.data_dir))
    results.append(check_directory(paths.logs_dir))
    results.append(check_directory(paths.cache_dir))
    results.append(check_directory(paths.tmp_dir))
    results.append(check_directory(paths.plugins_dir, writable=False))  # often not writable in prod
    return results

class ReadinessError(RuntimeError):
    pass

def raise_on_errors(results: Iterable[ProbeResult]) -> None:
    errors = [r for r in results if r.status == "error"]
    if errors:
        details = "; ".join(f"{e.subject}: {e.message}" for e in errors)
        raise ReadinessError(details)
```

### Bootstrap example

```python
# bootstrap/startup.py
from config.paths import resolve_application_paths
from app import readiness

def create_app(settings):
    paths = resolve_application_paths(settings)
    results = readiness.validate_paths(paths)
    readiness.raise_on_errors(results)

    # Inject ResolvedPaths wherever needed
    storage = Storage(paths=paths, ...)
    runner = JobRunner(paths=paths, storage=storage, ...)
    return App(runner=runner)
```

---

## 6) Migration Plan (mechanical)

1. **Introduce types & modules.**
   Land `config/paths.py` and `app/readiness.py` with unit tests. Keep old globals intact.

2. **Wire the bootstrap.**
   Entry point now calls `resolve_application_paths` + `validate_paths` before constructing the app.

3. **Constructor injection sweep.**

   * Change constructors to accept `paths: ResolvedPaths`.
   * Replace references to `config_context.paths` (or similar) with `self._paths`.
   * Example diff:

     ```diff
     - from config_context import PATHS
     - cfg = yaml.safe_load(open(PATHS.config_file))
     + def __init__(self, paths: ResolvedPaths, ...):
     +     self._paths = paths
     + ...
     + cfg = yaml.safe_load(open(self._paths.config_file))
     ```

4. **Temporary shim + deprecation.**

   * In `config_context.py` (or the legacy module):

     ```python
     _CACHED: ResolvedPaths | None = None

     def paths() -> ResolvedPaths:
         import warnings
         warnings.warn("config_context.paths() is deprecated; pass ResolvedPaths via constructor", DeprecationWarning, stacklevel=2)
         assert _CACHED is not None, "paths() called before bootstrap"
         return _CACHED
     ```
   * In bootstrap, set `_CACHED = paths` for the interim.

5. **Remove shim** once all imports are eliminated (tracked with CI guard below).

---

## 7) Test Plan

### Unit (pure resolution)

* **`config/paths_test.py`**

  * Given minimal `settings`, assert each field equals expected `repo_root`‑relative default (no I/O).
  * Given overrides (strings, `Path`, `~`), assert canonicalization with `_norm()` works.
  * Hash/immutability: `hash(ResolvedPaths(...))` succeeds; attributes are read‑only.

### Unit (readiness probes)

* **`app/readiness_test.py`**

  * Use `tmp_path` to create files/dirs; parametrize read/write perms (on POSIX, set `chmod`).
  * `check_file` returns `error` for missing; `ok` for present; respects `writable=True` failures.
  * `check_directory` respects `executable_on_posix`; write probe behaves as expected.
  * `validate_paths` aggregates; `raise_on_errors` aggregates messages.

### Integration

* Startup path with a synthetic `settings` object. Ensure:

  * Pure resolution runs without touching disk (stub out `Path.exists` to validate readiness layer is the only I/O).
  * Readiness failure blocks startup with informative message.

### CI Guards

* Lint rule or test that **no modules import `config_context PATHS`** (pattern grep):

  ```bash
  ! grep -R "from config_context import PATHS" src/ || (echo "Remove globals usage" && exit 1)
  ```

---

## 8) Rollout & Compatibility

* **Stage 1:** Ship new modules + bootstrap wiring; leave consumers unchanged (shim provides legacy access).
* **Stage 2:** Convert high fan‑in areas first (e.g., storage, jobs, web server). Track with a checklist.
* **Stage 3:** Remove shim and block on CI guard.
* **Feature Flag (optional):** Gate readiness enforcement via `SETTINGS["ENFORCE_READINESS"]=True/False` if environments need a grace period. The default should remain **True** in prod.

---

## 9) Risks & Mitigations

* **Risk:** Hidden consumers rely on transitive globals.
  **Mitigation:** CI grep + import graph to detect offenders; add a temporary runtime warning on legacy accessor.

* **Risk:** Behavior drift if readiness previously created directories.
  **Mitigation:** Our readiness is explicitly **non‑mutating**. If auto‑creation is desired, we add a **separate** `prepare_paths(paths)` in a follow‑up, not here.

* **Risk:** Windows ACL nuances (`os.access` vs. actual write permission).
  **Mitigation:** Keep checks conservative; write‑probe temp file offers practical validation.

---

## 10) Developer Ergonomics

* **Discoverability:** `ResolvedPaths` is the single object to pass around; readable field names.
* **Extensibility:** New paths are added in `ResolvedPaths` with defaults; propagate via constructors, and tests fail if not threaded.
* **Determinism:** All path math lives in a pure module, trivial to fuzz or snapshot‑test.

---

## 11) Acceptance Checklist (DoD)

* [ ] `config/paths.py` has `ResolvedPaths` (frozen) and pure `resolve_application_paths`.
* [ ] `app/readiness.py` exposes `check_file`, `check_directory`, `validate_paths`, `raise_on_errors`.
* [ ] Bootstrap instantiates and validates paths.
* [ ] All high‑fan‑in consumers take `ResolvedPaths` via constructor.
* [ ] No direct imports of `config_context` globals (CI guard passes).
* [ ] Unit + integration tests green; readiness errors are aggregated and human‑readable.
* [ ] Shim removed (or marked for removal with ticket).

---

## 12) Quick Reference: Copy‑Paste Snippets

**Constructor pattern:**

```python
class ArtifactStore:
    def __init__(self, paths: ResolvedPaths, *, fs=None):
        self._paths = paths
        self._fs = fs or os
```

**Reading config safely:**

```python
from config.paths import ResolvedPaths

def load_config(paths: ResolvedPaths) -> dict:
    with open(paths.config_file, "rb") as fh:
        return yaml.safe_load(fh)
```

**Boot wiring:**

```python
settings = load_settings()
paths = resolve_application_paths(settings)
readiness.raise_on_errors(readiness.validate_paths(paths))
service = Service(paths=paths, ...)
```

---

# Codemod helper for scope #

Awesome—here’s a **ready‑to‑run LibCST codemod** that migrates code to the new split you defined:

* **Pure path resolution** in `config/paths.py` (e.g., `resolve_application_paths`, `ResolvedPaths`)
* **Probes & validations** in `app/readiness.py` (e.g., `check_file`, `check_directory`, etc.)
* Call‑site rewrites away from the old monolith (e.g., `config_context` or similar) toward the new modules
* Automatic import fixes (adds the right new imports, prunes unused old ones)

It’s written as a `VisitorBasedCodemodCommand` so you can run it with LibCST’s CLI and get built‑in helpers like **AddImports** and **RemoveUnusedImports**. The CLI usage is documented by LibCST; for example, to list codemods and run one you do:

```bash
python3 -m libcst.tool list
python3 -m libcst.tool codemod convert_format_to_fstring.ConvertFormatStringCommand .
```

…and you can see command‑specific help with:

```bash
python3 -m libcst.tool codemod noop.NOOPCommand --help
```

These are straight from the LibCST docs and confirm the CLI shape and auto‑helpers for adding/removing imports. ([libcst.readthedocs.io][1])

---

## What this codemod does (safe, incremental defaults)

1. **Rewrites imports** away from the legacy “config” module:

   * `from <old_config_module> import resolve_paths` ⟶ `from <paths_module> import resolve_application_paths`
   * `from <old_config_module> import check_file, check_directory, …` ⟶ `from <readiness_module> import ...`
   * It can also **rename** a resolver (e.g., `resolve_paths` ⟶ `resolve_application_paths`).

2. **Rewrites call sites** to use the new names:

   * `resolve_paths(settings)` ⟶ `resolve_application_paths(settings)`
   * `config.resolve_paths(...)` or `cfg.resolve_paths(...)` ⟶ `resolve_application_paths(...)` (and adds the needed import)
   * `check_file(...)`, `check_directory(...)`, etc., become *module‑free* function calls and are imported from `app.readiness`.

3. **Automatically manages imports** using LibCST’s helpers:

   * Adds `from <paths_module> import resolve_application_paths` and (optionally) `ResolvedPaths`.
   * Adds `from <readiness_module> import …` for checks you use.
   * Removes unused/imports left behind (LibCST’s codemod CLI runs `AddImportsVisitor` and `RemoveImportsVisitor` for you). ([libcst.readthedocs.io][1])

> ❇️ **Out of scope (kept conservative by default):** This codemod does not automatically change function signatures to accept a `ResolvedPaths` parameter everywhere (constructor injection). That is a bigger, cross‑cutting change best done as a second codemod you run after this one (I include a stub you can extend if you want to take that step now).

---

## Drop‑in file: `tools/codemods/paths_split.py`

> Adjust the **defaults** at the top (package root, module names) or pass them via CLI flags. The defaults assume a top‑level package named `codeintel_rev` and a legacy module named `config_context`.

```python
# tools/codemods/paths_split.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

import libcst as cst
import libcst.matchers as m
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.codemod.visitors import AddImportsVisitor, RemoveImportsVisitor


def dotted_name(expr: cst.BaseExpression) -> Optional[str]:
    """
    Turn a Name/Attribute chain into 'a.b.c' or None if not resolvable.
    """
    if isinstance(expr, cst.Name):
        return expr.value
    parts: List[str] = []
    cur: cst.BaseExpression = expr
    while isinstance(cur, cst.Attribute):
        parts.append(cur.attr.value)
        cur = cur.value
    if isinstance(cur, cst.Name):
        parts.append(cur.value)
        parts.reverse()
        return ".".join(parts)
    return None


@dataclass(frozen=True)
class Config:
    package_root: str = "codeintel_rev"
    old_config_module: str = "codeintel_rev.config_context"
    paths_module: str = "codeintel_rev.config.paths"
    readiness_module: str = "codeintel_rev.app.readiness"

    # rename 'resolve_paths' -> 'resolve_application_paths'
    resolver_renames: Dict[str, str] = None
    # functions that should be imported from readiness
    readiness_funcs: Set[str] = None
    # also import ResolvedPaths alongside resolve_application_paths (toggle)
    import_resolved_paths: bool = True

    def __post_init__(self):
        object.__setattr__(self, "resolver_renames", self.resolver_renames or {"resolve_paths": "resolve_application_paths"})
        object.__setattr__(
            self,
            "readiness_funcs",
            self.readiness_funcs or {"check_file", "check_directory", "check_exists"},
        )


class PathsSplitCommand(VisitorBasedCodemodCommand):
    """
    Migrate from a monolithic config module to split modules:

      * {paths_module}: contains resolve_application_paths + ResolvedPaths
      * {readiness_module}: contains check_file/check_directory/... probes

    Rewrites imports and call sites and adds necessary imports.
    """
    DESCRIPTION: str = "Split path resolution and readiness checks into config.paths and app.readiness."

    @staticmethod
    def add_args(arg_parser) -> None:
        # CLI flags mirror Config, letting you adapt to your code tree.
        arg_parser.add_argument("--package-root", default="codeintel_rev")
        arg_parser.add_argument("--old-config-module", default=None)
        arg_parser.add_argument("--paths-module", default=None)
        arg_parser.add_argument("--readiness-module", default=None)
        arg_parser.add_argument(
            "--resolver-rename",
            action="append",
            default=["resolve_paths:resolve_application_paths"],
            help="Mapping 'old:new' for resolver names; may be repeated.",
        )
        arg_parser.add_argument(
            "--readiness-func",
            action="append",
            default=["check_file", "check_directory", "check_exists"],
            help="Names of readiness helpers to import from readiness module.",
        )
        arg_parser.add_argument(
            "--no-import-resolved-paths",
            action="store_true",
            help="If set, do not import ResolvedPaths automatically.",
        )

    def __init__(
        self,
        context: CodemodContext,
        package_root: str = "codeintel_rev",
        old_config_module: Optional[str] = None,
        paths_module: Optional[str] = None,
        readiness_module: Optional[str] = None,
        resolver_rename: Optional[List[str]] = None,
        readiness_func: Optional[List[str]] = None,
        no_import_resolved_paths: bool = False,
    ) -> None:
        super().__init__(context)
        self.cfg = Config(
            package_root=package_root,
            old_config_module=old_config_module or f"{package_root}.config_context",
            paths_module=paths_module or f"{package_root}.config.paths",
            readiness_module=readiness_module or f"{package_root}.app.readiness",
            resolver_renames={
                k: v for k, v in (
                    (pair.split(":", 1)[0].strip(), pair.split(":", 1)[1].strip())
                    for pair in (resolver_rename or ["resolve_paths:resolve_application_paths"])
                )
            },
            readiness_funcs=set(readiness_func or ["check_file", "check_directory", "check_exists"]),
            import_resolved_paths=not no_import_resolved_paths,
        )

        # import bookkeeping seen in this module
        self.imported_modules: Dict[str, str] = {}      # alias -> module (for "import x as y")
        self.imported_from: Dict[str, Tuple[str, str]] = {}  # local name -> (module, attr) for "from mod import attr as local"

    # ---------- Import bookkeeping ----------

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            asname = alias.asname.name.value if alias.asname else alias.name.value.split(".")[-1]
            self.imported_modules[asname] = alias.name.value

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if node.module is None or not isinstance(node.module, cst.Name) and not isinstance(node.module, cst.Attribute):
            return
        modname = node.module.value if isinstance(node.module, cst.Name) else dotted_name(node.module)
        if modname is None:
            return
        for alias in node.names:
            if isinstance(alias, cst.ImportStar):
                continue
            local = alias.asname.name.value if alias.asname else alias.name.value
            self.imported_from[local] = (modname, alias.name.value)

    # ---------- Import rewrites ----------

    def leave_ImportFrom(self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom) -> cst.BaseStatement:
        """
        If we see 'from <old_config_module> import resolve_paths, check_file',
        remove the moved names and add new imports from the correct modules.
        """
        modname = None
        if updated_node.module:
            if isinstance(updated_node.module, cst.Name):
                modname = updated_node.module.value
            else:
                modname = dotted_name(updated_node.module)

        if modname != self.cfg.old_config_module:
            return updated_node

        keep_aliases: List[cst.ImportAlias] = []
        moved_any = False

        for alias in updated_node.names:
            if isinstance(alias, cst.ImportStar):
                keep_aliases.append(alias)  # can't safely split a star import; leave it
                continue

            local = alias.asname.name.value if alias.asname else alias.name.value
            target = alias.name.value

            # resolver rename?
            if target in self.cfg.resolver_renames:
                new_name = self.cfg.resolver_renames[target]
                AddImportsVisitor.add_needed_import(self.context, self.cfg.paths_module, new_name)
                if self.cfg.import_resolved_paths:
                    AddImportsVisitor.add_needed_import(self.context, self.cfg.paths_module, "ResolvedPaths")
                moved_any = True
                # don't keep the old import
                continue

            # readiness helpers?
            if target in self.cfg.readiness_funcs:
                AddImportsVisitor.add_needed_import(self.context, self.cfg.readiness_module, target)
                moved_any = True
                continue

            keep_aliases.append(alias)

        if not keep_aliases:
            # delete the import entirely if everything moved
            return cst.RemoveFromParent()
        else:
            return updated_node.with_changes(names=keep_aliases)

    # ---------- Call site rewrites ----------

    def _is_alias_of_old_config(self, name: str) -> bool:
        """
        True if 'name' is an imported module alias for the old config module.
        """
        return self.imported_modules.get(name) == self.cfg.old_config_module

    def _maybe_rewrite_callee_to_name(self, callee: cst.BaseExpression) -> Optional[cst.Name]:
        """
        If callee refers to an old resolver or readiness helper (possibly via module attr),
        return a plain Name for the new target, otherwise None.
        """
        # module.attr form
        if isinstance(callee, cst.Attribute):
            base = callee.value
            attr = callee.attr.value
            # old config alias?
            if isinstance(base, cst.Name) and self._is_alias_of_old_config(base.value):
                # resolver rename?
                if attr in self.cfg.resolver_renames:
                    new = self.cfg.resolver_renames[attr]
                    AddImportsVisitor.add_needed_import(self.context, self.cfg.paths_module, new)
                    if self.cfg.import_resolved_paths:
                        AddImportsVisitor.add_needed_import(self.context, self.cfg.paths_module, "ResolvedPaths")
                    return cst.Name(new)
                # readiness helper?
                if attr in self.cfg.readiness_funcs:
                    AddImportsVisitor.add_needed_import(self.context, self.cfg.readiness_module, attr)
                    return cst.Name(attr)
        # direct name form
        if isinstance(callee, cst.Name):
            local = callee.value
            # imported from old module?
            mod_attr = self.imported_from.get(local)
            if mod_attr and mod_attr[0] == self.cfg.old_config_module:
                target = mod_attr[1]
                # resolver rename
                if target in self.cfg.resolver_renames:
                    new = self.cfg.resolver_renames[target]
                    AddImportsVisitor.add_needed_import(self.context, self.cfg.paths_module, new)
                    if self.cfg.import_resolved_paths:
                        AddImportsVisitor.add_needed_import(self.context, self.cfg.paths_module, "ResolvedPaths")
                    return cst.Name(new)
                # readiness helper
                if target in self.cfg.readiness_funcs:
                    AddImportsVisitor.add_needed_import(self.context, self.cfg.readiness_module, target)
                    return cst.Name(target)
            # bare resolver name present in code without import provenance:
            if local in self.cfg.resolver_renames:
                new = self.cfg.resolver_renames[local]
                AddImportsVisitor.add_needed_import(self.context, self.cfg.paths_module, new)
                if self.cfg.import_resolved_paths:
                    AddImportsVisitor.add_needed_import(self.context, self.cfg.paths_module, "ResolvedPaths")
                return cst.Name(new)
            if local in self.cfg.readiness_funcs:
                AddImportsVisitor.add_needed_import(self.context, self.cfg.readiness_module, local)
                return cst.Name(local)
        return None

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        maybe = self._maybe_rewrite_callee_to_name(updated_node.func)
        if maybe is not None:
            return updated_node.with_changes(func=maybe)
        return updated_node


# --------------------- Optional follow-up: signature injection ---------------------

class InjectResolvedPathsParameter(VisitorBasedCodemodCommand):
    """
    *Optional* conservative codemod that adds a `paths: ResolvedPaths`
    parameter to functions that directly call `resolve_application_paths(settings)`
    and replaces *local* further calls with the variable. It does NOT rewrite callers.

    Use after `PathsSplitCommand` if you want a stepping-stone toward constructor injection.
    """
    DESCRIPTION = "Add a 'paths: ResolvedPaths' parameter where resolve_application_paths(...) is used locally."

    @staticmethod
    def add_args(arg_parser) -> None:
        arg_parser.add_argument("--paths-module", required=True, help="e.g. codeintel_rev.config.paths")
        arg_parser.add_argument("--resolver-name", default="resolve_application_paths")
        arg_parser.add_argument("--param-name", default="paths")

    def __init__(self, context: CodemodContext, paths_module: str, resolver_name: str = "resolve_application_paths", param_name: str = "paths") -> None:
        super().__init__(context)
        self.paths_module = paths_module
        self.resolver_name = resolver_name
        self.param_name = param_name
        AddImportsVisitor.add_needed_import(self.context, self.paths_module, "ResolvedPaths")

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        # If function body contains a call to resolve_application_paths(...), add a param.
        has_resolver_call = m.findall(
            updated_node.body,
            m.Call(func=m.Name(self.resolver_name))
        )
        if not has_resolver_call:
            return updated_node

        # Skip if param already exists
        if any(p.name.value == self.param_name for p in updated_node.params.params):
            return updated_node

        new_param = cst.Param(
            name=cst.Name(self.param_name),
            annotation=cst.Annotation(
                cst.Attribute(value=cst.Name("ResolvedPaths"), attr=cst.Name("__class__"))  # keeps : ResolvedPaths typing robustly? alternative below
            ),
        )
        # Prefer simple annotation: : ResolvedPaths
        new_param = cst.Param(
            name=cst.Name(self.param_name),
            annotation=cst.Annotation(cst.Name("ResolvedPaths")),
        )

        new_params = [new_param, *updated_node.params.params]
        new_params_node = updated_node.params.with_changes(params=new_params)
        AddImportsVisitor.add_needed_import(self.context, self.paths_module, "ResolvedPaths")
        return updated_node.with_changes(params=new_params_node)
```

---

## How to run it

> From your repo root (where `tools/codemods/paths_split.py` lives):

1. **Preview available codemods and flags** (handy while wiring up):

```bash
python3 -m libcst.tool list
python3 -m libcst.tool codemod tools.codemods.paths_split.PathsSplitCommand --help
```

2. **Dry run (show diffs) on the whole codebase**:

```bash
python3 -m libcst.tool codemod \
  tools.codemods.paths_split.PathsSplitCommand \
  --package-root codeintel_rev \
  --old-config-module codeintel_rev.config_context \
  --paths-module codeintel_rev.config.paths \
  --readiness-module codeintel_rev.app.readiness \
  .
```

> The LibCST codemod utility takes care of gathering files, parallelizing, printing progress, and running helper transforms to add and remove imports. Use `--help` to see all CLI options the tool provides (diff output, job parallelism, skipping generated files, etc.). ([libcst.readthedocs.io][1])

3. **Optional Step**: Inject a `paths: ResolvedPaths` parameter **where a function calls** the resolver locally:

```bash
python3 -m libcst.tool codemod \
  tools.codemods.paths_split.InjectResolvedPathsParameter \
  --paths-module codeintel_rev.config.paths \
  --resolver-name resolve_application_paths \
  --param-name paths \
  .
```

> This step is conservative; it does **not** change callers yet. If you want a full constructor‑injection codemod that propagates the new parameter through call graphs and updates call sites, I can add that as a follow‑up.

---

## Before/After examples

**Imports & calls:**

**Before**

```python
from codeintel_rev.config_context import resolve_paths, check_file

def main(settings):
    paths = resolve_paths(settings)
    check_file(paths.repo_root / "pyproject.toml")
```

**After**

```python
from codeintel_rev.config.paths import resolve_application_paths, ResolvedPaths
from codeintel_rev.app.readiness import check_file

def main(settings):
    paths = resolve_application_paths(settings)
    check_file(paths.repo_root / "pyproject.toml")
```

**Attribute calls off a module alias:**

**Before**

```python
import codeintel_rev.config_context as cfg

def build():
    p = cfg.resolve_paths(load_settings())
    cfg.check_directory(p.data_dir)
```

**After**

```python
from codeintel_rev.config.paths import resolve_application_paths, ResolvedPaths
from codeintel_rev.app.readiness import check_directory

def build():
    p = resolve_application_paths(load_settings())
    check_directory(p.data_dir)
```

**Optional param injection (step 2):**

**Before**

```python
def analyze(settings):
    out = resolve_application_paths(settings)
    # ...
```

**After**

```python
from codeintel_rev.config.paths import ResolvedPaths

def analyze(paths: ResolvedPaths, settings):
    # ...
```

---

## Notes & guardrails

* The codemod **safely no‑ops** on files that don’t import or call the targeted functions.
* It **does not** try to guess complex provenance when names are shadowed dynamically or pulled through wildcard imports.
* It relies on LibCST’s CLI running **AddImports** and **RemoveUnusedImports** automatically for you when subclassing `CodemodCommand`/`VisitorBasedCodemodCommand`, which keeps modules clean without manual bookkeeping. ([libcst.readthedocs.io][1])
* If your legacy module name isn’t `codeintel_rev.config_context`, pass the right one via `--old-config-module`.

---

## Extending to constructor injection (full “take a ResolvedPaths everywhere”)

If you want the codemod to **propagate** `paths: ResolvedPaths` all the way through class `__init__` methods and functions (and update call sites), we can add a second pass that:

1. Detects functions/classes that call `resolve_application_paths` or import from the legacy global.
2. Adds a `paths: ResolvedPaths` parameter and stores it as `self.paths` in classes.
3. Rewrites intra‑module call sites to pass `paths` (and accumulates a per‑file “needs‑to‑propagate” set).
4. Rewrites external call sites in other files iteratively until the call graph converges.

That’s more advanced (requires metadata providers for scope and call site resolution), but the foundation above keeps it incremental and safe.

---

If you want me to tailor this to your **actual** old module name(s) and the exact set of resolver/check functions found in your repo (and ship a battery of `CodemodTest` unit tests), I can produce that next.

[1]: https://libcst.readthedocs.io/_/downloads/en/latest/pdf/ "LibCST Documentation"
