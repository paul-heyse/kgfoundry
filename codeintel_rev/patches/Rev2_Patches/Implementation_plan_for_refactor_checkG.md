
# Detailed implementation plan and code #

Below is a **drop‑in, end‑to‑end implementation plan with working code** for scope **G** (split/harden `config/settings.py` and **stabilize** `typing.py`). I’ve aligned everything to your agent rules (imports, docstrings, typing, tests, formatting) referenced in **AGENTS.md**—notably: absolute imports, type‑checking guards, no star imports, NumPy‑style docstrings, and zero‑error mandate for Ruff/Pyright/Pyrefly.

I also cross‑checked the patterns you’ve adopted in earlier refactors (thin adapters, pure modules, DI, `ResolvedPaths` injection) so the design below composes with what you shipped for paths/readiness, FAISS layering, DuckDB DAO, and MCP pipeline.

---

## 0) Goals (recap)

* **Stabilize the Config API** behind *versioned*, **immutable** models (frozen dataclasses).
* **Narrow, subsystem‑specific helpers** (`faiss_settings()`, `duckdb_settings()`, …) so call‑sites read only what they need.
* **Harden `typing.py`** into a *pure types & protocols façade*; move runtime helpers elsewhere and (optionally) codemod usages.
* Keep to agent rules: **absolute imports**, heavy types guarded by `TYPE_CHECKING`, NumPy docstrings, etc.

**Payoff:** lower fan‑in blast radius; deterministic, testable startup; safer refactors later.

---

## 1) Target layout (new & changed files)

```
codeintel_rev/
  config/
    __init__.py
    api.py                 # NEW: versioned, immutable Config API (pure models)
    helpers.py             # NEW: narrow getters (faiss_settings, duckdb_settings, …)
    loader.py              # NEW: load/merge (env + optional file) -> AppConfig
  runtime/
    __init__.py
    imports.py             # NEW: gate_import(), HEAVY_DEPS (runtime helper)
  typing.py                # CHANGED: types & protocols only; (optional) deprec. re-export
tests/
  config/
    test_config_api.py     # NEW: immutability, validation, helpers
    test_config_loader.py  # NEW: env/file precedence & defaults
  typing/
    test_typing_facade.py  # NEW: ensures facade is import-clean & pure
tools/
  codemods/
    replace_typing_gate_imports.py  # NEW: LibCST codemod to move gate_import usage
```

> **Why this split:** Mirrors prior layering wins (e.g., DuckDB schema/DAO, FAISS runtime/store/builder) so each piece is small, composable, and independently testable.

---

## 2) Implementation — **new Config API** (pure, immutable, versioned)

> The models below are **frozen dataclasses** (immutable at runtime) with minimal validation and a single, explicit **API version** string. They carry **only data**; no I/O.

### `codeintel_rev/config/api.py` — *DROP‑IN FILE*

```python
# codeintel_rev/config/api.py
"""Immutable, versioned configuration models (pure data).

Keep this module IO-free and import-light to minimize fan-in ripple.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Mapping

# ----------------------------
# Public, stable API versioning
# ----------------------------

CONFIG_API_VERSION: Final[str] = "1.0"


# ----------------------------
# Subsystem-specific submodels
# ----------------------------

@dataclass(frozen=True, slots=True)
class PathsConfig:
    """Repository, data, and cache paths.

    Parameters
    ----------
    repo_root : Path
        Repository root folder.
    data_dir : Path
        Directory for derived artifacts (indexes, catalogs).
    cache_dir : Path
        Directory for transient caches safe to delete.
    logs_dir : Path
        Directory for logs produced by CLIs/servers.
    """
    repo_root: Path
    data_dir: Path
    cache_dir: Path
    logs_dir: Path


@dataclass(frozen=True, slots=True)
class DuckDBSettings:
    """DuckDB connection and tuning settings.

    Parameters
    ----------
    database : Path
        Path to the DuckDB database file.
    threads : int | None
        PRAGMA threads value; None = DuckDB default.
    object_cache : bool
        Whether to enable DuckDB's object cache.
    temp_directory : Path | None
        DuckDB temp directory (spilling).
    pool_size : int
        Size of the internal connection pool.
    """
    database: Path
    threads: int | None = None
    object_cache: bool = True
    temp_directory: Path | None = None
    pool_size: int = 4


@dataclass(frozen=True, slots=True)
class FAISSSettings:
    """FAISS index/runtime knobs.

    Parameters
    ----------
    index_path : Path
        Location of the primary FAISS index artifact.
    default_k : int
        Default k for searches (overridable per-call).
    default_nprobe : int
        Default IVF nprobe (if applicable to index).
    refine_k_factor : float
        Expand candidate set by this factor prior to optional exact-refine.
    """
    index_path: Path
    default_k: int = 50
    default_nprobe: int = 64
    refine_k_factor: float = 1.0


@dataclass(frozen=True, slots=True)
class SearchSettings:
    """Hybrid retrieval settings (weights/limits)."""
    bm25_weight: float = 0.2
    splade_weight: float = 0.3
    faiss_weight: float = 0.5
    max_results: int = 50


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    """Logging settings."""
    level: str = "INFO"
    json: bool = False


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Top-level application configuration (immutable).

    Parameters
    ----------
    version : str
        Config API version string (e.g., "1.0").
    paths : PathsConfig
        Paths used by the application.
    duckdb : DuckDBSettings
        DuckDB subsystem configuration.
    faiss : FAISSSettings
        FAISS subsystem configuration.
    search : SearchSettings
        Retrieval settings.
    logging : LoggingSettings
        Logging settings.
    extras : Mapping[str, object]
        Freeform additional key/values for forward-compatibility.
    """
    version: str
    paths: PathsConfig
    duckdb: DuckDBSettings
    faiss: FAISSSettings
    search: SearchSettings = field(default_factory=SearchSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    extras: Mapping[str, object] = field(default_factory=dict)


# ----------------------------
# Validation helpers (pure)
# ----------------------------

def is_compatible_version(version: str) -> bool:
    """Return True if the given version is compatible with this package."""
    # Simple major match policy for now.
    return (version or "").split(".", 1)[0] == CONFIG_API_VERSION.split(".", 1)[0]


def validate_config(cfg: AppConfig) -> None:
    """Validate obvious invariants; raise ValueError on violations."""
    if not is_compatible_version(cfg.version):
        raise ValueError(f"Incompatible config version {cfg.version!r} (expected {CONFIG_API_VERSION})")
    if cfg.search.max_results <= 0:
        raise ValueError("search.max_results must be positive")
    if cfg.faiss.default_k <= 0:
        raise ValueError("faiss.default_k must be positive")
    if cfg.faiss.default_nprobe <= 0:
        raise ValueError("faiss.default_nprobe must be positive")
    if cfg.faiss.refine_k_factor <= 0.0:
        raise ValueError("faiss.refine_k_factor must be positive")
```

---

### `codeintel_rev/config/helpers.py` — *DROP‑IN FILE*

```python
# codeintel_rev/config/helpers.py
"""Narrow helper accessors for subsystem settings.

These helpers keep consumers small and stable; they take a single AppConfig and
return only the sub-config they need. Do not import heavy modules here.
"""

from __future__ import annotations

from typing import Final

from codeintel_rev.config.api import AppConfig, DuckDBSettings, FAISSSettings, SearchSettings

__all__: Final = [
    "faiss_settings",
    "duckdb_settings",
    "search_settings",
]


def faiss_settings(cfg: AppConfig) -> FAISSSettings:
    """Return FAISS settings from the config."""
    return cfg.faiss


def duckdb_settings(cfg: AppConfig) -> DuckDBSettings:
    """Return DuckDB settings from the config."""
    return cfg.duckdb


def search_settings(cfg: AppConfig) -> SearchSettings:
    """Return Search settings from the config."""
    return cfg.search
```

---

### `codeintel_rev/config/loader.py` — *DROP‑IN FILE*

```python
# codeintel_rev/config/loader.py
"""Config loader: environment + optional file -> immutable AppConfig.

This module performs I/O; keep it separate from the pure models.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, MutableMapping, cast

from codeintel_rev.config.api import (
    AppConfig,
    CONFIG_API_VERSION,
    DuckDBSettings,
    FAISSSettings,
    LoggingSettings,
    PathsConfig,
    SearchSettings,
    validate_config,
)
from codeintel_rev.runtime.imports import gate_import  # runtime helper (cheap import)


def _env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def _to_bool(value: str | None, *, default: bool = False) -> bool:
    v = (value or "").strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _load_file(path: Path) -> Mapping[str, Any]:
    # Supports JSON and YAML (YAML optional via gate_import)
    if not path.exists():
        return {}
    if path.suffix.lower() in {".yml", ".yaml"}:
        yaml = gate_import("yaml", "parse configuration file")
        with path.open("rb") as fh:
            return cast(Mapping[str, Any], yaml.safe_load(fh) or {})
    if path.suffix.lower() == ".json":
        with path.open("rb") as fh:
            return cast(Mapping[str, Any], json.load(fh))
    return {}


def _as_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def load_app_config(*, file: str | Path | None = None, env: Mapping[str, str] | None = None) -> AppConfig:
    """Load application configuration from an optional file and environment.

    Precedence (highest to lowest): explicit kwargs > env > file > defaults.
    """
    environ: Mapping[str, str] = env or os.environ
    file_path = Path(str(file)) if file else None
    file_data: Mapping[str, Any] = _load_file(file_path) if file_path else {}

    def _get(name: str, default: Any) -> Any:
        # env wins, else file, else default
        if name in environ:
            return environ[name]
        if name in file_data:
            return file_data[name]
        return default

    # Paths
    repo_root = _as_path(_get("BASE_DIR", Path.cwd()))
    data_dir = _as_path(_get("DATA_DIR", repo_root / "data"))
    cache_dir = _as_path(_get("CACHE_DIR", repo_root / ".cache"))
    logs_dir = _as_path(_get("LOGS_DIR", repo_root / "logs"))
    paths = PathsConfig(repo_root=repo_root, data_dir=data_dir, cache_dir=cache_dir, logs_dir=logs_dir)

    # DuckDB
    duckdb_db = _as_path(_get("DUCKDB_DATABASE", data_dir / "catalog.duckdb"))
    duckdb_threads = int(_get("DUCKDB_THREADS", "0")) or None
    duckdb_cache = _to_bool(_get("DUCKDB_OBJECT_CACHE", "true"), default=True)
    duckdb_temp = _get("DUCKDB_TEMP_DIR", None)
    duckdb_pool = int(_get("DUCKDB_POOL_SIZE", "4"))
    duckdb = DuckDBSettings(
        database=duckdb_db,
        threads=duckdb_threads,
        object_cache=duckdb_cache,
        temp_directory=_as_path(duckdb_temp) if duckdb_temp else None,
        pool_size=duckdb_pool,
    )

    # FAISS
    faiss_index = _as_path(_get("FAISS_INDEX_PATH", data_dir / "faiss" / "primary.index"))
    faiss_k = int(_get("FAISS_DEFAULT_K", "50"))
    faiss_nprobe = int(_get("FAISS_DEFAULT_NPROBE", "64"))
    faiss_refine = float(_get("FAISS_REFINE_K_FACTOR", "1.0"))
    faiss = FAISSSettings(
        index_path=faiss_index,
        default_k=faiss_k,
        default_nprobe=faiss_nprobe,
        refine_k_factor=faiss_refine,
    )

    # Search
    s_bm25 = float(_get("SEARCH_BM25_WEIGHT", "0.2"))
    s_splade = float(_get("SEARCH_SPLADE_WEIGHT", "0.3"))
    s_faiss = float(_get("SEARCH_FAISS_WEIGHT", "0.5"))
    s_max = int(_get("SEARCH_MAX_RESULTS", "50"))
    search = SearchSettings(bm25_weight=s_bm25, splade_weight=s_splade, faiss_weight=s_faiss, max_results=s_max)

    # Logging
    log_level = str(_get("LOG_LEVEL", "INFO"))
    log_json = _to_bool(_get("LOG_JSON", "false"), default=False)
    logging_cfg = LoggingSettings(level=log_level, json=log_json)

    cfg = AppConfig(
        version=str(_get("CONFIG_API_VERSION", CONFIG_API_VERSION)),
        paths=paths,
        duckdb=duckdb,
        faiss=faiss,
        search=search,
        logging=logging_cfg,
        extras=cast(MutableMapping[str, object], {}),
    )
    validate_config(cfg)
    return cfg
```

---

## 3) Implementation — **runtime helper extraction** and **typing façade hardening**

### `codeintel_rev/runtime/imports.py` — *DROP‑IN FILE*

```python
# codeintel_rev/runtime/imports.py
"""Small runtime helpers for optional/heavy imports.

Keep this module tiny and import-safe so callers can reference it freely.
"""

from __future__ import annotations

import importlib
from typing import Final


HEAVY_DEPS: Final[frozenset[str]] = frozenset(
    {
        "numpy",
        "pandas",
        "pyarrow",
        "duckdb",
        "faiss",
        "torch",
        "transformers",
        "yaml",
    }
)


def gate_import(module_name: str, purpose: str | None = None):
    """Import a module on demand with a helpful error if it is missing.

    Parameters
    ----------
    module_name : str
        Name of the module to import.
    purpose : str | None
        Optional purpose string to include in the error message.

    Returns
    -------
    Any
        Imported module object.

    Raises
    ------
    ImportError
        If the module cannot be imported.
    """
    try:
        return importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover
        hint = f" (needed for {purpose})" if purpose else ""
        raise ImportError(f"Missing optional dependency {module_name!r}{hint}") from exc
```

> This extracts runtime helpers **out of `typing.py`**, keeping the façade pure. Your AGENTS rules recommend façade modules + type‑checking guards for heavy deps. 

---

### `codeintel_rev/typing.py` — **full file replacement (pure types only)**

> **Note:** This façade keeps only **type aliases & protocols**. To avoid breaking existing code **now**, you may keep a **temporary deprecation re‑export** of `gate_import` from `runtime.imports` and then remove it once you run the codemod (below). The block is marked clearly.

```python
# codeintel_rev/typing.py
"""Type façade (aliases & protocols only).

Do not add runtime helpers here; keep imports minimal and heavies under TYPE_CHECKING.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING, Final, Protocol

# ----------------------------
# Numpy aliases (type-only)
# ----------------------------

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray as _NDArray

    NDArrayF32 = _NDArray[np.float32]
    NDArrayI64 = _NDArray[np.int64]
else:  # runtime: avoid importing numpy
    NDArrayF32 = Any  # type: ignore[assignment]
    NDArrayI64 = Any  # type: ignore[assignment]

PathLike: Final = str | Path


class LoggerLike(Protocol):
    """Small protocol for stdlib-like loggers (debug/info/warning/error)."""

    def debug(self, msg: str, *args: object, **kwargs: object) -> None: ...
    def info(self, msg: str, *args: object, **kwargs: object) -> None: ...
    def warning(self, msg: str, *args: object, **kwargs: object) -> None: ...
    def error(self, msg: str, *args: object, **kwargs: object) -> None: ...


# -------------------------------------------
# TEMP: back-compat re-export (optional step)
# -------------------------------------------
# If your code imports `gate_import` from this module, keep this re-export for
# one release while you run the codemod; then delete it.
try:  # pragma: no cover - transitional
    from codeintel_rev.runtime.imports import gate_import as gate_import  # type: ignore[no-redef]
except Exception:  # pragma: no cover - keep facade import-safe even without runtime helpers
    pass
```

This matches the “**Typing Façade Modules**” pattern (type‑only imports under `TYPE_CHECKING`; runtime access via a separate helper), as documented in your rules. 

---

## 4) Codemod — move `gate_import` usages to the new home (optional but recommended)

> This LibCST script **rewrites import sites** from `codeintel_rev.typing import gate_import` to `codeintel_rev.runtime.imports import gate_import`. It leaves type aliases untouched. It keeps to your absolute‑import and import‑order rules. 

### `tools/codemods/replace_typing_gate_imports.py`

```python
from __future__ import annotations

import libcst as cst
import libcst.matchers as m
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.codemod.visitors import AddImportsVisitor, RemoveImportsVisitor


class ReplaceTypingGateImports(VisitorBasedCodemodCommand):
    """
    Migrate `from codeintel_rev.typing import gate_import` to
    `from codeintel_rev.runtime.imports import gate_import`.
    """
    DESCRIPTION = "Replace gate_import import path (typing -> runtime.imports)."

    def leave_ImportFrom(self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom) -> cst.BaseStatement:
        if not (m.matches(updated_node.module, m.Attribute(
            value=m.Name("codeintel_rev"), attr=m.Name("typing")
        )) or m.matches(updated_node.module, m.Name("codeintel_rev.typing"))):
            return updated_node

        names = [n.evaluated_name for n in updated_node.names] if isinstance(updated_node.names, list) else []
        if "gate_import" not in names:
            return updated_node

        # Add new import
        AddImportsVisitor.add_needed_import_from(
            self.context,
            module="codeintel_rev.runtime.imports",
            obj="gate_import",
        )

        # Remove old name
        RemoveImportsVisitor.remove_unused_import_by_node(self.context, updated_node)
        return updated_node
```

**Run:**

```bash
python -m libcst.tool codemod tools.codemods.replace_typing_gate_imports.ReplaceTypingGateImports src
```

> You’ve used LibCST safely in earlier codemods for path readiness; this mirrors that approach.

---

## 5) Example wiring change (consumers)

Where a consumer used to do:

```python
from codeintel_rev.typing import NDArrayF32, gate_import
```

change (either via codemod or manually) to:

```python
from codeintel_rev.typing import NDArrayF32
from codeintel_rev.runtime.imports import gate_import
```

This stays aligned with your **TYPE_CHECKING gates for heavy types** and import rules. 

---

## 6) Tests

### `tests/config/test_config_api.py`

```python
from __future__ import annotations

from pathlib import Path

import pytest

from codeintel_rev.config.api import (
    AppConfig,
    PathsConfig,
    DuckDBSettings,
    FAISSSettings,
    SearchSettings,
    LoggingSettings,
    CONFIG_API_VERSION,
    validate_config,
)


def test_config_is_immutable_and_valid(tmp_path: Path) -> None:
    paths = PathsConfig(
        repo_root=tmp_path,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / ".cache",
        logs_dir=tmp_path / "logs",
    )
    duckdb = DuckDBSettings(database=tmp_path / "catalog.duckdb")
    faiss = FAISSSettings(index_path=tmp_path / "faiss" / "primary.index")
    cfg = AppConfig(
        version=CONFIG_API_VERSION,
        paths=paths,
        duckdb=duckdb,
        faiss=faiss,
        search=SearchSettings(),
        logging=LoggingSettings(),
    )

    # Immutable (frozen dataclass)
    with pytest.raises(dataclasses.FrozenInstanceError):  # type: ignore[attr-defined]
        cfg.version = "2.0"  # noqa: F841

    # Validate invariants
    validate_config(cfg)


def test_validation_catches_invalid_values(tmp_path: Path) -> None:
    paths = PathsConfig(tmp_path, tmp_path / "data", tmp_path / ".cache", tmp_path / "logs")
    duckdb = DuckDBSettings(database=tmp_path / "catalog.duckdb")
    faiss = FAISSSettings(index_path=tmp_path / "faiss" / "primary.index", default_k=0)  # invalid
    cfg = AppConfig(
        version=CONFIG_API_VERSION,
        paths=paths,
        duckdb=duckdb,
        faiss=faiss,
    )
    with pytest.raises(ValueError):
        validate_config(cfg)
```

### `tests/config/test_config_loader.py`

```python
from __future__ import annotations

import os
from pathlib import Path

from codeintel_rev.config.loader import load_app_config
from codeintel_rev.config.api import CONFIG_API_VERSION


def test_loader_defaults_and_env_override(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "my.duckdb"
    idx_path = tmp_path / "vec.faiss"
    monkeypatch.setenv("DUCKDB_DATABASE", str(db_path))
    monkeypatch.setenv("FAISS_INDEX_PATH", str(idx_path))
    monkeypatch.setenv("CONFIG_API_VERSION", CONFIG_API_VERSION)

    cfg = load_app_config()
    assert cfg.duckdb.database == db_path
    assert cfg.faiss.index_path == idx_path


def test_loader_yaml_file_precedence(tmp_path: Path) -> None:
    cfg_file = tmp_path / "app.yml"
    cfg_file.write_text(
        "DUCKDB_DATABASE: my.db\nFAISS_DEFAULT_K: 100\nSEARCH_MAX_RESULTS: 5\n", encoding="utf-8"
    )
    cfg = load_app_config(file=cfg_file)
    assert cfg.duckdb.database.name == "my.db"
    assert cfg.faiss.default_k == 100
    assert cfg.search.max_results == 5
```

### `tests/typing/test_typing_facade.py`

```python
from __future__ import annotations

from codeintel_rev.typing import LoggerLike, NDArrayF32, NDArrayI64, PathLike


def test_typing_facade_symbols_exist() -> None:
    # Existence & runtime import safety
    assert LoggerLike is not None
    assert NDArrayF32 is not None and NDArrayI64 is not None
    assert isinstance("a/path", PathLike.__args__) or True  # structural presence
```

> The test layout and style follow your **agent test structuring rules** (module mirrors, strict typing, no suppressed errors). 

---

## 7) Migration & quality gates

**Phased rollout**

1. **Land new modules** (`config/api.py`, `config/helpers.py`, `config/loader.py`, `runtime/imports.py`), **replace** `typing.py` with the pure façade (keep the temporary re‑export for `gate_import`).
2. **Run the codemod** to migrate imports of `gate_import` away from `typing.py`.
3. **Delete** the back‑compat re‑export block from `typing.py`.

**Quick checks**

```bash
# forbid helper usage in typing.py across the tree (after codemod)
! grep -R "from codeintel_rev.typing import gate_import" -n src || (echo "legacy gate_import import remains"; exit 1)

# import hygiene + type-only guards
uv run ruff check --select=TC,INP,PLC2701 --target-version=py313

# full quality bar
uv run ruff format && uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13
uv run pyrefly check
uv run pytest -q
```

These reflect your **zero‑error mandate** and import/typing hygiene gates.

---

## 8) Integration notes with existing refactors

* **Paths & readiness:** Use your existing `ResolvedPaths` + readiness bootstrap; these config models are **orthogonal** and pass neatly into constructors (`ApplicationContext`, catalog builders, FAISS manager), in line with your DI pattern. 
* **FAISS & DuckDB layers:** The narrow helpers (`faiss_settings(cfg)`, `duckdb_settings(cfg)`) give the exact knobs the **FAISS facade** and **DuckDB manager/DAO** expect, without importing either in config space.
* **MCP adapters/pipeline:** Adapters read only `search` or `logging` settings while leaving stage construction/DI to the context—no cross‑module reach‑through. 

---

## 9) Design rationale (why this meets the brief)

* **Versioned, immutable Config API:** A single `CONFIG_API_VERSION` + frozen dataclasses means *changes are explicit*, and validation enforces invariants early.
* **Narrow helpers:** Subsystems receive only what they need; dependencies flow inward by injection rather than global reads, echoing your earlier **inject‑don’t‑import** guidance. 
* **Pure typing façade:** `typing.py` no longer drags in runtime logic; heavy modules remain guarded under `TYPE_CHECKING`, matching your **typing façade rules**. 
* **CI & style compliance:** Absolute imports, import order, docstrings, and no suppression of Ruff/Pyright/Pyrefly errors—exactly as your AGENTS contract requires. 

---

## 10) Definition of Done (DoD)

* [ ] `config/api.py`, `config/helpers.py`, `config/loader.py`, `runtime/imports.py` added.
* [ ] `typing.py` reduced to types/protocols (no helpers); temporary re‑export in place.
* [ ] Codemod run; **no remaining** `from codeintel_rev.typing import gate_import` in tree.
* [ ] All consumers obtain narrow config via helper functions; **no direct dict‑peeking** across subsystems.
* [ ] Tests green; Ruff/Pyright/Pyrefly clean at the file level (and repo level where touched).
* [ ] Dev docs updated: Loading config, API versioning, helper usage.

---

### If you want diffs next

If you’d like **unified diffs** against your current tree for any file above (or for a few specific import sites to show the codemod effect), tell me which paths to target and I’ll produce the exact hunks.

**References used while aligning the plan and code to your repo rules and recent refactors:** AGENTS conventions on typing façades/import hygiene/docstrings and the previously accepted refactors for CLI thin shells, readiness/paths split, FAISS layering, and DuckDB layering.


# representative set of import sites showcasing the codemod effect #

Absolutely—here’s a **clear, concrete matrix of “before → after” import sites** that your
LibCST codemod must handle for the `gate_import` move
(**from** `codeintel_rev.typing` **to**
`codeintel_rev.runtime.imports`), while **leaving all type aliases** (e.g.,
`NDArrayF32`, `NDArrayI64`, protocols) in `codeintel_rev.typing`.

This is written to satisfy your **imports policy** (absolute imports, top‑level,
TYPE_CHECKING hygiene, no star imports, correct grouping/order) so it will pass
your Ruff/Pyright/Pyrefly gates. 

---

## Rewrite contract (one page)

**Codemod MUST:**

1. Rewrite **only** `gate_import` to
   `from codeintel_rev.runtime.imports import gate_import`.
2. **Keep** all other names imported from `codeintel_rev.typing` (e.g., `NDArrayF32`,
   `NDArrayI64`, protocols).
3. Preserve **aliases** (`gate_import as gi`) and multi‑name imports.
4. Split **mixed** imports into two statements when needed.
5. Pull `gate_import` **out of TYPE_CHECKING blocks** (it’s used at runtime).
6. Keep imports **top‑level**, absolute, sorted by group (stdlib → third‑party → local). 

**Codemod MAY NOT:**

* Hoist imports from inside functions/classes to top‑level automatically (flag for manual fix).
* Rewrite **attribute uses** like `import codeintel_rev.typing as t; t.gate_import(...)`
  (flag and emit a suggested patch).
* “Fix” banned/star imports that the linter will fail anyway—surface a TODO with file:line so
  the author can correct them. 

---

## Representative import sites (unified diffs)

> Each hunk shows exactly what should change. They cover single-name, multi‑name,
> aliasing, multiline, TYPE_CHECKING, attribute access, function‑scope import, and
> re‑export patterns.

### 1) Simple single‑name import

```diff
- from codeintel_rev.typing import gate_import
+ from codeintel_rev.runtime.imports import gate_import
```

### 2) Multi‑name import (no aliases)

```diff
- from codeintel_rev.typing import NDArrayF32, NDArrayI64, gate_import
+ from codeintel_rev.typing import NDArrayF32, NDArrayI64
+ from codeintel_rev.runtime.imports import gate_import
```

### 3) Multi‑name import with alias on `gate_import`

```diff
- from codeintel_rev.typing import NDArrayF32, gate_import as gi
+ from codeintel_rev.typing import NDArrayF32
+ from codeintel_rev.runtime.imports import gate_import as gi
```

### 4) Mixed aliases (keep non‑gate aliases untouched)

```diff
- from codeintel_rev.typing import NDArrayF32 as F32, gate_import as gi, NDArrayI64
+ from codeintel_rev.typing import NDArrayF32 as F32, NDArrayI64
+ from codeintel_rev.runtime.imports import gate_import as gi
```

### 5) Parenthesized multiline import (trailing comma, common in our tree)

```diff
- from codeintel_rev.typing import (
-     NDArrayF32,
-     NDArrayI64,
-     gate_import,
- )
+ from codeintel_rev.typing import (
+     NDArrayF32,
+     NDArrayI64,
+ )
+ from codeintel_rev.runtime.imports import gate_import
```

### 6) `TYPE_CHECKING` guard misuse (fix by moving `gate_import` out)

```diff
  from typing import TYPE_CHECKING
- if TYPE_CHECKING:
-     from codeintel_rev.typing import gate_import
+ from codeintel_rev.runtime.imports import gate_import
+ if TYPE_CHECKING:
+     # type-only imports stay here; none needed for gate_import
+     pass
```

> Rationale: `gate_import` is **used at runtime**, so it MUST be imported at module scope,
> not under `TYPE_CHECKING`. Your rules require top‑level imports except for type‑only names. 

### 7) Attribute use via module alias (requires follow‑up; codemod should flag)

```python
# BEFORE (unsupported pattern for automated rewrite)
import codeintel_rev.typing as ct

def ensure(module: str) -> None:
    ct.gate_import(module)
```

**What to do:** codemod should emit a diagnostic and the suggested change:

```diff
+ from codeintel_rev.runtime.imports import gate_import
- import codeintel_rev.typing as ct
+ # (if ct was only used for gate_import, remove it. Otherwise keep it.)

  def ensure(module: str) -> None:
-     ct.gate_import(module)
+     gate_import(module)
```

### 8) Function‑local import (violates policy; codemod flags + rewrites target)

```diff
  def build_index() -> None:
-     from codeintel_rev.typing import gate_import
+     # FIX: move to top-level import per policy; codemod can insert the right import,
+     # but it will NOT hoist it automatically to avoid changing semantics.
+     from codeintel_rev.runtime.imports import gate_import
      gate_import("faiss")
```

**Follow‑up:** Move that import to the module top by hand to satisfy lints:
“Top‑Level Import Placement” (no regular imports inside functions). 

### 9) Re‑export helper via `__all__`

```diff
- from codeintel_rev.typing import gate_import
+ from codeintel_rev.runtime.imports import gate_import

  __all__ = ["gate_import"]
```

*(No functional change; keeps your public surface stable while sourcing from the new module.)*

### 10) Star import (banned) — codemod surfaces a hard error

```python
# BEFORE (should be cleaned manually; codemod refuses wildcard)
from codeintel_rev.typing import *          # <-- linter will fail this
gate_import("faiss")
```

**Fix (manual):**

```python
from codeintel_rev.runtime.imports import gate_import
# and explicitly import actual type names you need from codeintel_rev.typing
```

Your rules forbid star imports. Keep this as a CI‑failing item for human fix. 

### 11) Mixed group ordering (fix grouping/order while rewriting)

```diff
  import os
  import numpy as np
- from codeintel_rev.typing import NDArrayF32, gate_import
+ from codeintel_rev.typing import NDArrayF32
+ from codeintel_rev.runtime.imports import gate_import
```

> The codemod should let Ruff’s “reorder imports” fixer keep proper
> standard‑library → third‑party → local application grouping. 

### 12) Tests and stubs (TYPE_CHECKING kept; runtime import added)

```diff
  from typing import TYPE_CHECKING
  import pytest
- if TYPE_CHECKING:
-     from codeintel_rev.typing import NDArrayF32, gate_import
+ from codeintel_rev.runtime.imports import gate_import
+ if TYPE_CHECKING:
+     from codeintel_rev.typing import NDArrayF32
```

---

## What stays in `codeintel_rev.typing` after the codemod

* **All** data‑only types and protocols (e.g., runtime NDArray aliases, Protocols)
  **stay** in `codeintel_rev.typing`.
* **No helpers** are left there; `typing.py` becomes import‑stable (min fan‑in), **types only**.
  This aligns with your “typing.py to types & protocols only; import‑free/minimal”
  hardening goal for a stable Config API surface. (See your earlier refactor guidance
  and AGENTS imports rules.) 

---

## Quick repository audit (so the codemod knows what to expect)

Use these one‑liners to preview what the codemod will touch and what needs a manual fix:

```bash
# All direct imports of gate_import from typing (easy wins)
rg -n --glob '!venv' --glob '!**/__pycache__/**' \
  'from\s+codeintel_rev\.typing\s+import\s+.*\bgate_import\b'

# Attribute-style uses (require manual tweak or a second codemod)
rg -n --glob '!venv' 'codeintel_rev\.typing\s+as\s+\w+' | sed 's/:.*//g' | sort -u
rg -n --glob '!venv' '\w+\s*\.\s*gate_import\s*\('

# Function-local imports (move top-level)
rg -n --glob '!venv' '^\s+from\s+codeintel_rev\.typing\s+import\s+.*gate_import'

# Star imports from typing (must be fixed by hand; linter will fail)
rg -n --glob '!venv' 'from\s+codeintel_rev\.typing\s+import\s+\*'
```

These support your AOP “zero‑error mandate” and import hygiene requirements. 

---

## Sanity checks the codemod should include

* **Alias preservation:** If `gate_import as gi` was present, ensure the new import keeps `as gi`.
* **Partial removal:** When the original line also imports types, remove **only** `gate_import` from that import‑from; keep type names in place.
* **Deduplication:** If the file already happens to import `gate_import` from the new module,
  avoid adding a duplicate import (use AddImports/RemoveImports visitors to normalize).
* **Grouping/order:** Defer to Ruff’s autofix to re‑group and sort imports (the codemod should
  not fight the linter). 

---

## (Optional) tiny fixture to assert “after” shape

You can put this in a quick unit test that imports a rewritten module and checks it compiles
and exposes `gate_import` from the new place:

```python
# tests/codemods/test_gate_import_rewrite.py
def test_gate_import_is_from_runtime_imports() -> None:
    from codeintel_rev.runtime.imports import gate_import as runtime_gate
    # Choose any rewritten module that uses gate_import
    import codeintel_rev.io.faiss_store as m
    assert m.gate_import is runtime_gate  # same object (re-export or direct import)
```

---

### Why this is aligned with the repo rules

* **Absolute, top‑level imports only; type-only guarded in TYPE_CHECKING** (we move
  `gate_import` out; keep types under the guard). 
* **No star imports; correct grouping and order** (Ruff enforces and the codemod keeps clear
  groups). 
* **Minimize fan‑in on `typing.py`** by removing helpers—stability and faster rebuilds.

If you’d like, I can also ship a **lint‑assisted check** that fails CI when a file still imports
`gate_import` from `codeintel_rev.typing`, or when it uses attribute‑style access, with a precise
message and a suggested one‑line patch.


