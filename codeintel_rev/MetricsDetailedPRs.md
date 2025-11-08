Perfect—here are the four “mini-PRs” you can apply in sequence. Each one is small, scoped, and includes ready-to-paste code, unified diffs, and a test plan. You don’t need to ship them all at once; they’re independent but designed to layer cleanly.

---

# P1 — Observability (remove duplicated `_NoopObservation` / `_observe`)

## What this does

* Introduces a single `observe_duration(...)` helper.
* Removes per-adapter noop timer boilerplate.
* Keeps your adapters small & readable.

## Files added

### `codeintel_rev/mcp_server/common/__init__.py`

```python
# intentionally empty; marks the package
```

### `codeintel_rev/mcp_server/common/observability.py`

```python
from __future__ import annotations

from contextlib import contextmanager
from time import monotonic
from typing import Mapping, Optional
import logging

log = logging.getLogger(__name__)

class MetricsTimer:
    def time(self, **labels):
        raise NotImplementedError

class Metrics:
    def timer(self, name: str) -> MetricsTimer:
        raise NotImplementedError
    def counter(self, name: str):
        raise NotImplementedError

class _NoopTimer:
    @contextmanager
    def time(self, **labels):
        yield

class _NoopCounter:
    def inc(self, *a, **k):  # noqa: D401
        pass

class _NoopMetrics(Metrics):
    def timer(self, name: str) -> MetricsTimer:
        return _NoopTimer()
    def counter(self, name: str):
        return _NoopCounter()

METRICS_ENABLED = True  # flip to False for local if you want
DEFAULT_METRICS: Metrics = _NoopMetrics()

def install_metrics(registry: Metrics) -> None:
    """Call once at startup to plug a real metrics backend."""
    global DEFAULT_METRICS
    DEFAULT_METRICS = registry

@contextmanager
def observe_duration(
    operation: str,
    component: str,
    *,
    metrics: Optional[Metrics] = None,
    extra_labels: Optional[Mapping[str, str]] = None,
):
    """
    with observe_duration(\"search\", \"text_search\"):
        ...
    """
    m = metrics or DEFAULT_METRICS
    labels = dict(operation=operation, component=component)
    if extra_labels:
        labels.update(extra_labels)

    if METRICS_ENABLED:
        with m.timer("adapter_duration_seconds").time(**labels):
            yield
    else:
        start = monotonic()
        try:
            yield
        finally:
            dur = monotonic() - start
            log.debug("observe_duration", extra={"labels": labels, "seconds": dur})
```

## Adapter changes (copy/paste)

In each adapter that currently defines `_NoopObservation` and `_observe` (e.g.):

* `codeintel_rev/mcp_server/adapters/text_search.py`
* `codeintel_rev/mcp_server/adapters/semantic.py`

1. **Remove** local `_NoopObservation` and `_observe` definitions.
2. **Add** this import alongside the other imports:

```python
from mcp_server.common.observability import observe_duration
```

3. **Replace** each usage of the old context manager (examples):

**Before**

```python
with _observe(METRICS, operation="search", component=COMPONENT_NAME):
    results = backend.search(query)
```

**After**

```python
with observe_duration("search", COMPONENT_NAME):
    results = backend.search(query)
```

If you labeled by backend type before (e.g., `"bm25"`, `"semantic"`), carry that forward:

```python
with observe_duration("search", COMPONENT_NAME, extra_labels={"kind": "bm25"}):
    ...
```

## Commit message

```
refactor(observability): centralize adapter timing with observe_duration; remove per-adapter noop boilerplate
```

## Tests

* **New**: `tests/codeintel_rev/test_observability_noop.py`

```python
from mcp_server.common import observability

def test_observe_duration_noop():
    observability.METRICS_ENABLED = False
    with observability.observe_duration("op", "comp"):
        pass
    # no exception; nothing to assert beyond not crashing
```

* Existing adapter tests should pass unchanged.

---

# P2 — Path utilities (single source of truth for repo-safe paths)

## What this does

* Introduces a single `resolve_within_repo(...)` that:

  * expands `~`
  * normalizes relative paths against repo root
  * enforces “inside repo”
  * validates existence & dir/file shape
* Adapters stop re-implementing path checks and error strings.

## Files added

### `codeintel_rev/mcp_server/common/path_utils.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

class PathOutsideRepository(Exception): ...
class PathNotFound(Exception): ...
class PathNotDirectory(Exception): ...

@dataclass(frozen=True)
class RepoRoot:
    root: Path  # absolute resolved

    @staticmethod
    def from_str(p: str) -> "RepoRoot":
        return RepoRoot(Path(p).expanduser().resolve())

def resolve_within_repo(
    root: RepoRoot,
    user_path: str | Path,
    *,
    must_exist: bool = True,
    require_dir: bool | None = None,  # None: no check, True: must be dir, False: must be file
) -> Path:
    p = Path(user_path).expanduser()
    if not p.is_absolute():
        p = root.root / p
    rp = p.resolve()

    try:
        rp.relative_to(root.root)
    except ValueError:
        raise PathOutsideRepository(f"{rp} escapes repository {root.root}")

    if must_exist and not rp.exists():
        raise PathNotFound(f"{rp} not found")
    if require_dir is True and not rp.is_dir():
        raise PathNotDirectory(f"{rp} is not a directory")
    if require_dir is False and not rp.is_file():
        raise PathNotFound(f"{rp} is not a file")

    return rp
```

## Adapter changes (copy/paste)

**In** `codeintel_rev/mcp_server/adapters/files.py` and `.../adapters/history.py`:

1. **Imports**

```python
from mcp_server.common.path_utils import (
    RepoRoot, resolve_within_repo,
    PathOutsideRepository, PathNotFound, PathNotDirectory,
)
from mcp_server.service_context import get_repo_root  # or wherever you hold the repo root
```

2. **Replace** ad-hoc logic:

**Before (illustrative)**

```python
base = Path(repo_root).expanduser().resolve()
target = Path(path).expanduser().resolve()
target.relative_to(base)  # may raise ValueError
if not target.exists() or not target.is_dir():
    return error_json("Path not found or not a directory")
```

**After**

```python
root = RepoRoot.from_str(get_repo_root())
try:
    target = resolve_within_repo(root, path, must_exist=True, require_dir=True)
except PathOutsideRepository as e:
    return error_mapper(e)     # see error_handling update below
except PathNotFound as e:
    return error_mapper(e)
except PathNotDirectory as e:
    return error_mapper(e)

# proceed confidently with 'target'
```

## Error handling standardization

Extend `codeintel_rev/mcp_server/error_handling.py` with explicit mappings:

```python
from mcp_server.common.path_utils import (
    PathOutsideRepository, PathNotFound, PathNotDirectory
)

EXCEPTION_TO_ERROR = {
    PathOutsideRepository: ("path_outside_repo", 400),
    PathNotDirectory: ("path_not_directory", 400),
    PathNotFound: ("path_not_found", 404),
    NotImplementedError: ("not_implemented", 501),  # used in P3
}

def error_mapper(exc: Exception) -> dict:
    for etype, (code, status) in EXCEPTION_TO_ERROR.items():
        if isinstance(exc, etype):
            return {
                "error": {"code": code, "message": str(exc)},
                "status": status,
            }
    # fallback
    return { "error": {"code": "internal_error", "message": str(exc)}, "status": 500 }
```

(If you already have a mapper function, just add the three path exceptions and `NotImplementedError` to your existing table.)

## Commit message

```
refactor(paths): centralize repo-constrained path resolution; unify path-related error shapes across adapters
```

## Tests

* **New**: `tests/codeintel_rev/test_path_utils.py`

```python
from pathlib import Path
import pytest
from mcp_server.common.path_utils import RepoRoot, resolve_within_repo, PathOutsideRepository, PathNotFound, PathNotDirectory

def test_resolve_dir_ok(tmp_path: Path):
    root = RepoRoot(tmp_path)
    d = tmp_path / "subdir"; d.mkdir()
    p = resolve_within_repo(root, "subdir", must_exist=True, require_dir=True)
    assert p == d.resolve()

def test_block_escape(tmp_path: Path):
    root = RepoRoot(tmp_path)
    with pytest.raises(PathOutsideRepository):
        resolve_within_repo(root, "../x")

def test_require_dir(tmp_path: Path):
    root = RepoRoot(tmp_path)
    f = tmp_path / "f.txt"; f.write_text("x")
    with pytest.raises(PathNotDirectory):
        resolve_within_repo(root, "f.txt", require_dir=True)

def test_not_found(tmp_path: Path):
    root = RepoRoot(tmp_path)
    with pytest.raises(PathNotFound):
        resolve_within_repo(root, "nope", must_exist=True)
```

* **Update**: `tests/codeintel_rev/test_files_adapter.py` and `.../test_history_adapter.py`

  * Update assertions to match standardized error bodies (`code`, `status`) for path errors.

---

# P3 — Symbol tools: explicit stubs + server defers to adapter

## What this does

* Adds a single place to implement future symbol intelligence.
* Server layer becomes thin and consistently error-mapped.
* Logs a warning whenever these unimplemented tools are called.

## Files added

### `codeintel_rev/mcp_server/adapters/symbols.py`

```python
from __future__ import annotations
import logging

log = logging.getLogger(__name__)

def symbol_search(query: str, kind: str | None = None, language: str | None = None) -> list[dict]:
    log.warning("symbol_search called but not implemented", extra={"query": query, "kind": kind, "language": language})
    raise NotImplementedError("symbol_search not implemented")

def definition_at(path: str, line: int, character: int, commit: str | None = None) -> list[dict]:
    log.warning("definition_at called but not implemented", extra={"path": path, "line": line, "character": character, "commit": commit})
    raise NotImplementedError("definition_at not implemented")

def references_at(path: str, line: int, character: int, commit: str | None = None) -> list[dict]:
    log.warning("references_at called but not implemented", extra={"path": path, "line": line, "character": character, "commit": commit})
    raise NotImplementedError("references_at not implemented")
```

## Server changes

In `codeintel_rev/mcp_server/server.py`, wire tool handlers to call the adapter and **let exceptions bubble** into your `error_handling` layer:

```python
from mcp_server.adapters import symbols as symbol_adapter

# inside the tool route/handler:
def tool_symbol_search(query: str, kind: str | None = None, language: str | None = None):
    return symbol_adapter.symbol_search(query, kind=kind, language=language)

def tool_definition_at(path: str, line: int, character: int, commit: str | None = None):
    return symbol_adapter.definition_at(path, line, character, commit)

def tool_references_at(path: str, line: int, character: int, commit: str | None = None):
    return symbol_adapter.references_at(path, line, character, commit)
```

(If your server previously returned `{"message": "not implemented"}`, delete that UX layer—your `error_handling` now maps `NotImplementedError → 501` consistently.)

## Commit message

```
feat(symbols): centralize unimplemented symbol tools in symbols adapter; server delegates and standardizes 501 errors
```

## Tests

* **New**: `tests/codeintel_rev/test_symbol_stubs.py`

```python
import pytest
from mcp_server.adapters import symbols

def test_symbol_search_not_implemented():
    with pytest.raises(NotImplementedError):
        symbols.symbol_search("foo")

def test_definition_not_implemented():
    with pytest.raises(NotImplementedError):
        symbols.definition_at("a.py", 1, 1)

def test_references_not_implemented():
    with pytest.raises(NotImplementedError):
        symbols.references_at("a.py", 1, 1)
```

* If you have API-level tests that hit the server tool endpoints, update them to assert a structured error with code `not_implemented` and HTTP `501`.

---

# P4 — Sweep, docs, and small test updates

## What this does

* Removes any leftover `_NoopObservation`/`_observe`.
* Ensures error mapper covers the new exceptions and `NotImplementedError`.
* Adds concise developer docs to avoid future drift.

## Cleanup (search & delete)

* Grep for `_NoopObservation` and `_observe` across `codeintel_rev/`; remove any stragglers.

## Docs additions

* **`codeintel_rev/docs/ERRORS.md`**

```markdown
# Error codes (codeintel_rev)

| code                | http | meaning                                 |
|---------------------|------|-----------------------------------------|
| path_outside_repo   | 400  | Resolved path escapes repository root   |
| path_not_directory  | 400  | Path exists but is not a directory      |
| path_not_found      | 404  | Path does not exist                     |
| not_implemented     | 501  | Tool is not currently implemented       |
```

* **`codeintel_rev/README.md`** (Developer notes section)

  * How to use `observe_duration`
  * How to use `resolve_within_repo`
  * Where to implement symbol features (`adapters/symbols.py`)

## Commit message

```
chore: remove duplicate observer code; add ERROR docs; clarify developer usage of common/observability and common/path_utils
```

## Tests

* Run your full suite; nothing new to add beyond P1–P3.

---

## “If it doesn’t compile” safety valves

* If your server already has a global error handler, **only** extend its exception map; don’t introduce a second mapper function.
* If your repo root comes from `app/config_context.py` instead of `service_context.py`, swap the import in the adapters:

  ```python
  from app.config_context import get_repo_root
  ```
* If your metrics registry exists, call:

  ```python
  from mcp_server.common.observability import install_metrics
  install_metrics(real_registry)
  ```

  once during app startup (e.g., `app/main.py`).

---

## Rollout order & verification (5–10 minutes each)

1. **P1**: land `observability.py`, refactor `text_search` + `semantic`; run tests.
2. **P2**: land `path_utils.py`, refactor `files` + `history`, extend error mapper; update tests for error shape.
3. **P3**: land `symbols.py`, rewire server tool handlers; API test asserts 501 + `not_implemented`.
4. **P4**: doc sweep + dead code removal.

---

If you want me to tailor the adapter edits to the exact functions (e.g., show the specific `with ...:` lines in `text_search.py` and `semantic.py` as they exist today), I can do a quick pass reading those files and produce line-accurate patches.
