Below is an end‑to‑end, *do‑this‑then‑that* implementation plan to refactor the “god” CLI module `cli/enrich_pipeline.py` into a thin Typer shell with testable service modules under `services/enrich/`. I’ve included concrete steps, file trees, code snippets, and acceptance checks so an engineer—or an AI agent—can execute the plan without ambiguity.

---

## 0) Objectives & Non‑Goals

**Objectives**

* Reduce `cli/enrich_pipeline.py` from a monolith (877 stmts, cyclo 199, fan_out 21) to **small CLI shims** (5–20 lines each) that delegate to **pure service functions**.
* Introduce `services/enrich/` modules: `scan.py`, `exports.py`, `to_duckdb.py`, `overlays.py`, `analytics.py`.
* Introduce a **shared Pipeline Context** (config + paths + dependencies) that is **injected** into services; avoid global imports of env, logging, DuckDB, etc.
* Preserve CLI behavior and outputs (modules.jsonl, repo map, tag index, Markdown sheets, etc.) while improving testability.

**Non‑Goals**

* Changing CLI flags or user‑visible output formats, unless called out below.
* Re‑designing analytics logic; only relocating and clarifying it.

---

## 1) Target File/Package Layout (Create First)

> Create these files/directories; don’t delete the old CLI yet.

```
repo-root/
├─ cli/
│  ├─ enrich/                 # NEW: CLI group package
│  │  ├─ __init__.py
│  │  ├─ __main__.py          # `python -m cli.enrich` entry; attaches to Typer app
│  │  ├─ scan.py              # Typer subcommand (thin)
│  │  ├─ exports.py           # Typer subcommand (thin)
│  │  ├─ to_duckdb.py         # Typer subcommand (thin)
│  │  ├─ overlays.py          # Typer subcommand (thin)
│  │  └─ analytics.py         # Typer subcommand (thin)
│  └─ enrich_pipeline.py      # OLD: will be dismantled in phases
├─ services/
│  └─ enrich/                 # NEW: business logic lives here
│     ├─ __init__.py
│     ├─ context.py           # PipelineContext + dependency wiring
│     ├─ models.py            # Dataclasses / TypedDicts for data contracts
│     ├─ scan.py              # Repo scanning, AST, metadata extraction
│     ├─ exports.py           # Write modules.jsonl, repo map, tag index, md sheets
│     ├─ overlays.py          # Overlay application (YAML/JSON)
│     ├─ analytics.py         # Aggregations, summaries
│     ├─ to_duckdb.py         # Sink to DuckDB
│     └─ io.py                # IO helpers (atomic write, JSONL streaming, etc.)
└─ tests/
   └─ services/
      └─ enrich/              # New unit/integration tests
```

---

## 2) Shared Pipeline Context (Dependency Injection Backbone)

> Single place to construct/configure logger, paths, config, and optional DB handles. Services receive **only** this context and their own parameters. No service reads globals or environment directly.

**`services/enrich/context.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol
import logging
import os

try:
    import duckdb  # optional; only used if to_duckdb is invoked
except Exception:  # pragma: no cover
    duckdb = None  # type: ignore[assignment]

class Clock(Protocol):
    def now(self) -> float: ...

@dataclass(frozen=True)
class PipelinePaths:
    repo_root: Path
    out_dir: Path
    temp_dir: Path

@dataclass
class PipelineContext:
    """
    Shared context injected into all services. Keeps IO, logging, config, and DB
    in one place to maximize testability and minimize hidden dependencies.
    """
    paths: PipelinePaths
    config: Mapping[str, Any]
    logger: logging.Logger
    clock: Clock
    db: Optional["duckdb.DuckDBPyConnection"] = None  # lazy/optional

    @classmethod
    def from_env(
        cls,
        *,
        repo_root: str | Path,
        out_dir: str | Path,
        temp_dir: str | Path | None = None,
        config: Mapping[str, Any] | None = None,
        enable_db: bool = False,
        duckdb_path: str | Path | None = None,
        clock: Clock | None = None,
    ) -> "PipelineContext":
        import time

        p = PipelinePaths(
            repo_root=Path(repo_root).resolve(),
            out_dir=Path(out_dir).resolve(),
            temp_dir=Path(temp_dir or (Path(out_dir) / ".tmp")).resolve(),
        )
        p.temp_dir.mkdir(parents=True, exist_ok=True)
        p.out_dir.mkdir(parents=True, exist_ok=True)

        logger = logging.getLogger("enrich")
        if not logger.handlers:
            handler = logging.StreamHandler()
            fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            handler.setFormatter(fmt)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

        if clock is None:
            class _Clock:  # simple default
                def now(self) -> float: return time.time()
            clock = _Clock()

        db_conn = None
        if enable_db:
            if duckdb is None:
                raise RuntimeError("DuckDB not available; install duckdb or disable DB.")
            duckdb_path = duckdb_path or (Path(out_dir) / "enrich.duckdb")
            db_conn = duckdb.connect(str(duckdb_path))

        return cls(paths=p, config=config or {}, logger=logger, clock=clock, db=db_conn)

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
```

**Acceptance checks**

* Creating a `PipelineContext` does not touch business logic.
* No service imports `os.getenv`, `logging.getLogger`, or `duckdb.connect` directly.

---

## 3) Service Data Contracts

> Define the shapes we pass around, documented and typed.

**`services/enrich/models.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

@dataclass(frozen=True)
class ModuleRecord:
    path: Path              # absolute or repo-root-relative
    module: str             # dotted module path if applicable
    language: str           # "python", "md", etc. if you support multi-file types
    loc: int                # lines of code
    tags: tuple[str, ...]   # normalized tag set
    meta: Mapping[str, Any] = field(default_factory=dict)  # extensible

@dataclass(frozen=True)
class ExportResult:
    modules_jsonl: Path
    repo_map: Path
    tag_index: Path
    markdown_dir: Path
```

---

## 4) Implement Services (Business Logic Only)

### 4.1 IO Helpers (atomic writes, JSONL streaming)

**`services/enrich/io.py`**

```python
from __future__ import annotations
from pathlib import Path
from typing import Iterable, Mapping, Any
import json
import os
import tempfile

def atomic_write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent)) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)

def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n
```

### 4.2 Scan: walk repo, parse, build `ModuleRecord`s

**`services/enrich/scan.py`**

```python
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Iterator
import ast

from .context import PipelineContext
from .models import ModuleRecord

def _iter_python_files(root: Path, include_globs: tuple[str, ...], exclude_globs: tuple[str, ...]) -> Iterator[Path]:
    # Keep simple; can be replaced with ripgrep or git-aware walk if needed.
    for p in root.rglob("*.py"):
        rp = p.relative_to(root)
        if include_globs and not any(rp.match(g) for g in include_globs):
            continue
        if exclude_globs and any(rp.match(g) for g in exclude_globs):
            continue
        yield p

def _py_module_name(repo_root: Path, file_path: Path) -> str:
    # Best-effort: convert path to dotted module; falls back to stem.
    try:
        rel = file_path.relative_to(repo_root)
    except ValueError:
        rel = file_path
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)

def _loc(text: str) -> int:
    return sum(1 for _ in text.splitlines())

def scan_repo(
    ctx: PipelineContext,
    *,
    include: tuple[str, ...] = (),
    exclude: tuple[str, ...] = ("**/.venv/**", "**/build/**", "**/dist/**"),
    infer_tags: bool = True,
) -> list[ModuleRecord]:
    ctx.logger.info("Scanning repo at %s", ctx.paths.repo_root)
    results: list[ModuleRecord] = []
    for fp in _iter_python_files(ctx.paths.repo_root, include, exclude):
        text = fp.read_text(encoding="utf-8", errors="ignore")
        try:
            ast.parse(text)  # sanity check + enables later analytics
        except SyntaxError:
            ctx.logger.warning("Skipping non-parseable file: %s", fp)
            continue
        tags: set[str] = set()
        if infer_tags:
            if "cli" in fp.parts: tags.add("cli")
            if "tests" in fp.parts: tags.add("test")
        rec = ModuleRecord(
            path=fp,
            module=_py_module_name(ctx.paths.repo_root, fp),
            language="python",
            loc=_loc(text),
            tags=tuple(sorted(tags)),
            meta={"mtime": fp.stat().st_mtime},
        )
        results.append(rec)
    ctx.logger.info("Scan complete: %d modules", len(results))
    return results
```

### 4.3 Exports: JSONL, repo map, tag index, Markdown sheets

**`services/enrich/exports.py`**

```python
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Any
import json

from .context import PipelineContext
from .io import write_jsonl, atomic_write_text
from .models import ModuleRecord, ExportResult

def emit_modules_jsonl(ctx: PipelineContext, records: Iterable[ModuleRecord]) -> Path:
    path = ctx.paths.out_dir / "modules.jsonl"
    count = write_jsonl(path, (record_to_json(r) for r in records))
    ctx.logger.info("Wrote %d rows to %s", count, path)
    return path

def record_to_json(r: ModuleRecord) -> Mapping[str, Any]:
    return {
        "path": str(r.path),
        "module": r.module,
        "language": r.language,
        "loc": r.loc,
        "tags": list(r.tags),
        "meta": dict(r.meta),
    }

def emit_repo_map(ctx: PipelineContext, records: Iterable[ModuleRecord]) -> Path:
    by_pkg: dict[str, list[str]] = defaultdict(list)
    for r in records:
        pkg = r.module.split(".")[0] if "." in r.module else r.module
        by_pkg[pkg].append(r.module)
    path = ctx.paths.out_dir / "repo_map.json"
    atomic_write_text(path, json.dumps(by_pkg, indent=2))
    ctx.logger.info("Wrote repo map: %s", path)
    return path

def emit_tag_index(ctx: PipelineContext, records: Iterable[ModuleRecord]) -> Path:
    tags: dict[str, int] = defaultdict(int)
    for r in records:
        for t in r.tags:
            tags[t] += 1
    path = ctx.paths.out_dir / "tag_index.json"
    atomic_write_text(path, json.dumps(tags, indent=2))
    ctx.logger.info("Wrote tag index: %s", path)
    return path

def emit_markdown_sheets(ctx: PipelineContext, records: Iterable[ModuleRecord]) -> Path:
    md_dir = ctx.paths.out_dir / "sheets"
    md_dir.mkdir(parents=True, exist_ok=True)
    for r in records:
        slug = r.module.replace(".", "-")
        md = f"# {r.module}\n\n- Path: `{r.path}`\n- LOC: {r.loc}\n- Tags: {', '.join(r.tags) or '—'}\n"
        atomic_write_text(md_dir / f"{slug}.md", md)
    ctx.logger.info("Wrote markdown sheets: %s", md_dir)
    return md_dir

def run_all_exports(ctx: PipelineContext, records: list[ModuleRecord]) -> ExportResult:
    return ExportResult(
        modules_jsonl=emit_modules_jsonl(ctx, records),
        repo_map=emit_repo_map(ctx, records),
        tag_index=emit_tag_index(ctx, records),
        markdown_dir=emit_markdown_sheets(ctx, records),
    )
```

### 4.4 Overlays (apply external annotations)

**`services/enrich/overlays.py`**

```python
from __future__ import annotations
from pathlib import Path
from typing import Iterable, Mapping, Any
import json

from .context import PipelineContext
from .models import ModuleRecord

def apply_overlays(
    ctx: PipelineContext,
    records: list[ModuleRecord],
    overlay_files: Iterable[Path],
) -> list[ModuleRecord]:
    """
    Merge overlay metadata (e.g., tags or scores) into ModuleRecord.meta.
    Overlay files can be JSON or JSONL maps {module: {...}} or rows with "module".
    """
    overlay_map: dict[str, dict[str, Any]] = {}
    for f in overlay_files:
        text = f.read_text(encoding="utf-8")
        if any(line.strip().startswith("{") for line in text.splitlines()[0:3]):
            try:
                data = json.loads(text)  # JSON dict
                for k, v in data.items():
                    overlay_map.setdefault(k, {}).update(v)
            except json.JSONDecodeError:
                # JSONL
                for line in text.splitlines():
                    if not line.strip(): continue
                    row = json.loads(line)
                    overlay_map.setdefault(row["module"], {}).update(row)
        else:
            ctx.logger.warning("Skipping overlay (unknown format): %s", f)

    updated: list[ModuleRecord] = []
    for r in records:
        meta = dict(r.meta)
        if r.module in overlay_map:
            meta.update(overlay_map[r.module])
        updated.append(ModuleRecord(
            path=r.path, module=r.module, language=r.language, loc=r.loc, tags=r.tags, meta=meta
        ))
    ctx.logger.info("Applied overlays from %d files", len(list(overlay_files)))
    return updated
```

### 4.5 Analytics (summaries; keep pure)

**`services/enrich/analytics.py`**

```python
from __future__ import annotations
from typing import Mapping, Any
from collections import Counter

from .context import PipelineContext
from .models import ModuleRecord

def basic_stats(ctx: PipelineContext, records: list[ModuleRecord]) -> Mapping[str, Any]:
    loc_total = sum(r.loc for r in records)
    tags = Counter(t for r in records for t in r.tags)
    ctx.logger.info("Analytics: %d files, %d LOC, %d distinct tags", len(records), loc_total, len(tags))
    return {"files": len(records), "loc_total": loc_total, "tags": dict(tags)}
```

### 4.6 Sink to DuckDB (optional)

**`services/enrich/to_duckdb.py`**

```python
from __future__ import annotations
from typing import Any
import json

from .context import PipelineContext
from .models import ModuleRecord

def write_to_duckdb(
    ctx: PipelineContext,
    records: list[ModuleRecord],
    *,
    table: str = "modules",
    replace: bool = True,
) -> None:
    if ctx.db is None:
        raise RuntimeError("DuckDB connection is not enabled in context.")
    cur = ctx.db.cursor()
    if replace:
        cur.execute(f"DROP TABLE IF EXISTS {table}")
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            path TEXT,
            module TEXT,
            language TEXT,
            loc INTEGER,
            tags JSON,
            meta JSON
        )
    """)
    # Insert in batches
    rows = [(str(r.path), r.module, r.language, r.loc, json.dumps(list(r.tags)), json.dumps(r.meta)) for r in records]
    cur.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?)", rows)
    ctx.db.commit()
```

---

## 5) Thin Typer CLI (5–20 lines per command)

> The CLI should parse args, construct `PipelineContext`, call service functions, and handle exit codes.

**`cli/enrich/__init__.py`**

```python
import typer
app = typer.Typer(help="Enrichment pipeline commands.")
```

**`cli/enrich/__main__.py`**

```python
from . import app
from . import scan as _scan  # registers subcommands via module import side-effects
from . import exports as _exports
from . import overlays as _overlays
from . import analytics as _analytics
from . import to_duckdb as _to_duckdb

if __name__ == "__main__":
    app()
```

**`cli/enrich/scan.py`**

```python
from pathlib import Path
import typer
from services.enrich.context import PipelineContext
from services.enrich.scan import scan_repo
from . import app

@app.command("scan")
def scan(
    repo_root: Path = typer.Option(".", help="Repository root"),
    out_dir: Path = typer.Option("./.enrich", help="Output directory"),
    include: list[str] = typer.Option([], help="Include glob(s) relative to repo_root"),
    exclude: list[str] = typer.Option(["**/.venv/**", "**/build/**", "**/dist/**"], help="Exclude glob(s)"),
    infer_tags: bool = typer.Option(True, help="Infer basic tags from paths"),
):
    """Scan repository and print count. Other commands will consume exports."""
    ctx = PipelineContext.from_env(repo_root=repo_root, out_dir=out_dir)
    records = scan_repo(ctx, include=tuple(include), exclude=tuple(exclude), infer_tags=infer_tags)
    typer.echo(f"Scanned {len(records)} modules.")
```

**`cli/enrich/exports.py`**

```python
from pathlib import Path
import typer
from services.enrich.context import PipelineContext
from services.enrich.scan import scan_repo
from services.enrich.exports import run_all_exports
from . import app

@app.command("exports")
def exports(
    repo_root: Path = typer.Option(".", help="Repository root"),
    out_dir: Path = typer.Option("./.enrich", help="Output dir"),
    include: list[str] = typer.Option([], help="Include globs"),
    exclude: list[str] = typer.Option(["**/.venv/**", "**/build/**", "**/dist/**"], help="Exclude globs"),
):
    """Emit modules.jsonl, repo_map.json, tag_index.json, and Markdown sheets/."""
    ctx = PipelineContext.from_env(repo_root=repo_root, out_dir=out_dir)
    recs = scan_repo(ctx, include=tuple(include), exclude=tuple(exclude))
    res = run_all_exports(ctx, recs)
    typer.echo(f"Wrote: {res.modules_jsonl}, {res.repo_map}, {res.tag_index}, {res.markdown_dir}")
```

**`cli/enrich/overlays.py`**

```python
from pathlib import Path
from typing import Optional
import typer
from services.enrich.context import PipelineContext
from services.enrich.scan import scan_repo
from services.enrich.overlays import apply_overlays
from services.enrich.exports import run_all_exports
from . import app

@app.command("overlays")
def overlays(
    repo_root: Path = typer.Option(".", help="Repository root"),
    out_dir: Path = typer.Option("./.enrich", help="Output dir"),
    overlay: list[Path] = typer.Option([], "--overlay", help="Overlay file(s) JSON or JSONL"),
    write_exports: bool = typer.Option(True, help="Re-emit outputs after overlay"),
):
    ctx = PipelineContext.from_env(repo_root=repo_root, out_dir=out_dir)
    recs = scan_repo(ctx)
    recs = apply_overlays(ctx, recs, overlay)
    if write_exports:
        run_all_exports(ctx, recs)
    typer.echo(f"Overlays applied to {len(recs)} modules.")
```

**`cli/enrich/analytics.py`**

```python
from pathlib import Path
import json, typer
from services.enrich.context import PipelineContext
from services.enrich.scan import scan_repo
from services.enrich.analytics import basic_stats
from . import app

@app.command("analytics")
def analytics(
    repo_root: Path = typer.Option(".", help="Repository root"),
    out_dir: Path = typer.Option("./.enrich", help="Output dir"),
    pretty: bool = typer.Option(True, help="Pretty-print JSON"),
):
    ctx = PipelineContext.from_env(repo_root=repo_root, out_dir=out_dir)
    recs = scan_repo(ctx)
    stats = basic_stats(ctx, recs)
    typer.echo(json.dumps(stats, indent=2 if pretty else None))
```

**`cli/enrich/to_duckdb.py`**

```python
from pathlib import Path
import typer
from services.enrich.context import PipelineContext
from services.enrich.scan import scan_repo
from services.enrich.to_duckdb import write_to_duckdb
from . import app

@app.command("to-duckdb")
def to_duckdb(
    repo_root: Path = typer.Option(".", help="Repository root"),
    out_dir: Path = typer.Option("./.enrich", help="Output dir (also holds .duckdb)"),
    duckdb_path: Path = typer.Option(None, help="Override DuckDB file path", dir_okay=True, file_okay=True),
    table: str = typer.Option("modules", help="Target table name"),
    replace: bool = typer.Option(True, help="Drop & recreate table"),
):
    ctx = PipelineContext.from_env(
        repo_root=repo_root,
        out_dir=out_dir,
        enable_db=True,
        duckdb_path=duckdb_path,
    )
    recs = scan_repo(ctx)
    write_to_duckdb(ctx, recs, table=table, replace=replace)
    typer.echo(f"Wrote {len(recs)} rows to {duckdb_path or (out_dir / 'enrich.duckdb')}::{table}")
```

**Acceptance checks**

* Each command function is ≤ 20 lines excluding imports/docstring.
* No business logic in the CLI; only context construction + service calls.

---

## 6) Bridge the Old CLI → New Commands

1. **Add a command group** entry point (if you expose a console script):

   * In `pyproject.toml` (or `setup.cfg`), keep the **same** console script name users call today (e.g., `enrich` or your project’s CLI), but point to `cli.enrich.__main__:app`.
   * If your old script name was `enrich-pipeline`, keep it as a *shim* that imports and calls `cli.enrich.__main__:app()`.

2. **Within `cli/enrich_pipeline.py`** (old), replace its Typer app with:

   ```python
   # TEMPORARY COMPAT SHIM; delete after deprecation window
   from .enrich.__main__ import app

   if __name__ == "__main__":
       app()
   ```

3. Ensure old subcommands map 1:1 to new ones. Where names differ, add **hidden aliases**:

   ```python
   @app.command("exports", hidden=True)
   def _exports_alias(...):
       return exports(...)
   ```

---

## 7) Tests (add before moving logic)

> The whole point of the refactor is testability. Start by writing unit tests against the **services**.

**Examples**

* `tests/services/enrich/test_scan.py`

  * Creates a temp repo with a few `.py` files; asserts count, module names, LOC > 0.
* `tests/services/enrich/test_exports.py`

  * Asserts files are created and JSON/JSONL content shape.
* `tests/services/enrich/test_overlays.py`

  * Applies overlay to one module; asserts `meta` merged.
* `tests/services/enrich/test_to_duckdb.py`

  * Requires duckdb marker; asserts table exists and row count matches.

**Minimal test snippet**

```python
from pathlib import Path
from services.enrich.context import PipelineContext
from services.enrich.scan import scan_repo
from services.enrich.exports import run_all_exports

def test_exports_happy_path(tmp_path: Path):
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text("")
    (repo / "pkg" / "mod.py").write_text("def f():\n    return 1\n")

    ctx = PipelineContext.from_env(repo_root=repo, out_dir=tmp_path / ".out")
    recs = scan_repo(ctx)
    res = run_all_exports(ctx, recs)

    assert res.modules_jsonl.exists()
    assert res.repo_map.exists()
    assert res.tag_index.exists()
    assert res.markdown_dir.is_dir()
```

---

## 8) Migration Steps (Phased, Safe)

1. **Phase 0 – Scaffold**

   * Add new `services/enrich/*` and `cli/enrich/*` files above with initial implementations.
   * Add tests and run CI.

2. **Phase 1 – Extract scanning**

   * Identify scanning logic in old CLI; replace it with `services.enrich.scan.scan_repo`.
   * Confirm outputs (record counts) match on a staging repo.

3. **Phase 2 – Extract exports**

   * Replace in‑CLI JSON/Markdown emissions with `services.enrich.exports.*`.
   * Validate generated artifacts are byte‑for‑byte compatible, or document deltas.

4. **Phase 3 – Extract overlays/analytics**

   * Move overlay+analytics logic; verify behavior via tests.

5. **Phase 4 – DuckDB sink**

   * Move DuckDB interaction; use the context’s `db` to control side effects.

6. **Phase 5 – CLI replacement + shim**

   * Wire new Typer app; make the old module a shim (Section 6).
   * Keep aliases for old subcommand names if needed.

7. **Phase 6 – Cleanup**

   * Remove dead code from the old file.
   * Run static analyzers (ruff/mypy) and ensure import cycles are gone.

---

## 9) Backward Compatibility & Help/UX

* Maintain existing flags. If you must rename flags, keep the old ones as aliases (hidden) and log a **deprecation** message.
* Ensure `enrich --help` shows tidy groups:

  ```
  enrich scan        # repo scan
  enrich exports     # emit modules.jsonl, repo_map.json, tag_index.json, sheets/
  enrich overlays    # apply overlay files
  enrich analytics   # basic stats
  enrich to-duckdb   # write results to DuckDB
  ```
* Each command returns non‑zero exit codes on failure; services raise informative exceptions.

---

## 10) Quality Gates

* **Cyclomatic complexity**: No CLI function > 5 branch points; no service function > 15 (prefer smaller).
* **Lines per CLI command**: 5–20 lines.
* **Fan‑out**: CLI imports only `PipelineContext` and the service it calls.
* **Typing**: mypy passes in `services/enrich/*`.
* **Tests**: ≥ 90% coverage for `services/enrich/*` (bar is intentional to encourage isolation).

---

## 11) Observability & Perf

* **Structured logging** in services via `ctx.logger`.
* **Atomic writes** for all outputs (`atomic_write_text`).
* Optional: parallelize AST parsing in `scan_repo` using `concurrent.futures` if profiling indicates it’s needed (behind a flag; keep default simple).

---

## 12) Risks & Mitigations

* **Silent behavior changes** in outputs
  → Mitigate with **golden files** tests comparing old vs new outputs for a sample repo.

* **DuckDB optionality** causing runtime errors
  → `PipelineContext.from_env(enable_db=True)` validates availability and raises early.

* **Import cycles**
  → Keep `cli/*` → `services/*` one‑way imports. `services` never import from `cli`.

---

## 13) Example: Full Pipeline Invocation (after refactor)

```
# scan + outputs
$ enrich exports --repo-root . --out-dir ./.enrich

# apply overlays (jsonl) and re-emit
$ enrich overlays --overlay overlays/tags.jsonl

# write to DuckDB
$ enrich to-duckdb --duckdb-path ./.enrich/enrich.duckdb --table modules
```

---

## 14) Definition of Done (DoD)

* [ ] `cli/enrich_pipeline.py` replaced by a compatibility shim calling the new Typer app.
* [ ] New `enrich` command group exposes `scan`, `exports`, `overlays`, `analytics`, `to-duckdb`.
* [ ] All business logic resides in `services/enrich/*`.
* [ ] Running the new CLI reproduces **all** original artifacts: `modules.jsonl`, `repo_map.json`, `tag_index.json`, `sheets/*.md`.
* [ ] Unit tests cover services; CI green; static analysis clean.
* [ ] Developer docs updated to reflect the new structure and command help.

---

### Notes on Adapting to Your Current Code

* When you move logic out of the old CLI, **do thin adapters only**: e.g., if your old code has a function `emit_tag_index(...)` inside `cli/enrich_pipeline.py`, copy its body verbatim into `services/enrich/exports.py` and leave a wrapper in the CLI that simply calls the service. Iterate until the CLI contains no logic.
* If your current CLI already uses Typer groups, you can mount our `app` into your root app instead of using a separate entry point.

If you want, I can tailor this plan even further by mapping **your current subcommands/flags** to the exact new function signatures once you share (or point me to) the existing `cli/enrich_pipeline.py` contents.
