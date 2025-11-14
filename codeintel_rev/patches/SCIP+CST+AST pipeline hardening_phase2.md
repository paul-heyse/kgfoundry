Awesome — I integrated every point from the reviewer and turned the plan into concrete, ready‑to‑paste changes plus end‑to‑end tests. I’ve kept the changes surgical and mapped them to the modules and symbols already present in your repo (e.g., `cli_enrich.py`, `enrich/output_writers.py`, `enrich/stubs_overlay.py`, `enrich/libcst_bridge.py`, `enrich/tree_sitter_bridge.py`, `enrich/scip_reader.py`, `enrich/duckdb_store.py`). 

Below is the revised implementation plan, with code patches and tests. Where I reference advanced library features (LibCST Providers, Tree‑sitter Query, DuckDB’s native JSON readers, and Arrow/Parquet dataset writing), those calls and trade‑offs are documented in your “Python Libraries Technical Reference” attachment. 

---

## Phase 0 — Guardrails and success criteria (what “done” looks like)

**Functional:**

1. `codeintel-enrich --help` shows all global options and each subcommand binds `ROOT/SCIP/OUT/PYREFLY/TAGS` correctly (no post‑registration wrapping). 
2. Overlays generated **only** for (a) star‑import modules, or (b) export hubs (large `__all__`), or (c) modules carrying an `overlay-needed` tag. (No more “stubs everywhere”.) 
3. Artifact writers (`modules.jsonl`, graphs, etc.) are deterministic byte‑for‑byte across runs (`orjson` with sorted keys + newline). 
4. SCIP reader uses `msgspec.Struct` and preserves existing public methods (`load()`, `by_file`, `documents`, `symbol_to_files`). 
5. JSONL → DuckDB ingestion uses `read_json_auto()` + `MERGE` instead of row‑by‑row Python loops. 
6. Parquet writes use `pyarrow.dataset.write_dataset` with ZSTD + dictionary encoding and partitioning for pruning. 

**Quality gates (tests below):** CLI option contract, JSONL determinism, overlay gating behavior, SCIP decode parity, DuckDB ingestion round‑trip, Parquet options honored.

**Roll‑out toggles:**
`ENRICH_JSONL_WRITER=v2` and `USE_DUCKDB_JSON=1` environment flags (default to “new behavior on”; set to “off” to back out instantly).

---

## Phase 1 — Must‑fix nits (with diffs)

### 1) Typer option binding (no post‑registration wrapping)

> **Why:** Your CLI defines constants like `ROOT_OPTION = typer.Option(...)`. These must be used as **default values on typed parameters** at function definition time for Typer/Click to register them. 

**File:** `cli_enrich.py` (excerpt — apply the same pattern to other subcommands)

```python
# cli_enrich.py

@app.command("build")
def build_cmd(
    ctx: typer.Context,
    root: Path = ROOT_OPTION,
    scip: Path = SCIP_OPTION,
    out: Path = OUT_OPTION,
    pyrefly_json: Path | None = PYREFLY_OPTION,
    tags_yaml: Path | None = TAGS_OPTION,
    coverage_xml: Path | None = COVERAGE_OPTION,
    only: list[str] = ONLY_OPTION,
    max_file_bytes: int = MAX_FILE_BYTES_OPTION,
    owners: bool = OWNERS_OPTION,
    history_window_days: int = HISTORY_WINDOW_OPTION,
    commits_window: int = COMMITS_WINDOW_OPTION,
    emit_slices: bool = EMIT_SLICES_OPTION,
    slices_filter: list[str] = SLICES_FILTER_OPTION,
    emit_ast: bool = EMIT_AST_OPTION,
    overlays_config: Path | None = OVERLAYS_CONFIG_OPTION,
    overlays_set: str | None = OVERLAYS_SET_OPTION,
    # new: a direct --dry-run; default already defined in constants
    dry_run: bool = typer.Option(DEFAULT_DRY_RUN, "--dry-run", help="Compute only; do not write artifacts."),
):
    state = _ensure_state(ctx)
    # ...existing staging & pipeline orchestration...
```

This pattern aligns with the existing `ROOT_OPTION`/`SCIP_OPTION`/… constants in your file. 

### 2) Overlay generation guardrails

> **Why:** `generate_overlay_for_file()` currently triggers overlays too broadly. Gate overlays to star‑import modules or export hubs (large `__all__`), and optionally to files tagged `overlay-needed` by the CLI. 

**File:** `enrich/stubs_overlay.py` (predicate only)

```python
# enrich/stubs_overlay.py

def generate_overlay_for_file(ctx: OverlayContext, path: Path, index: ModuleIndex) -> bool:
    # ...existing preamble...
    star_exports = any(x.kind == "star" for x in index.exports)
    is_hub = len(index.exports) >= ctx.policy.export_hub_threshold  # existing threshold wiring

    # Optional: consult CLI tag index (populated via ctx.inputs or ctx.policy)
    overlay_needed = ctx.inputs.tag_index.get("overlay-needed", [])
    rel = path.relative_to(ctx.root).as_posix()
    has_tag = rel in overlay_needed

    should_overlay = star_exports or is_hub or has_tag
    if not should_overlay:
        return False

    # ...proceed to emit the .pyi stub...
```

The constants such as `EXPORT_HUB_THRESHOLD` and the overlay policy plumbing already exist in `cli_enrich.py` and `enrich/stubs_overlay.py`; this change narrows creation sites. 

### 3) Deterministic JSON/JSONL writers (`orjson`, bytes, sorted keys)

> **Why:** Artifact diffs must be stable and fast. `orjson` + `OPT_SORT_KEYS|OPT_APPEND_NEWLINE` with `ab` improves throughput and determinism. 

**File:** `enrich/output_writers.py`

```python
# enrich/output_writers.py
from __future__ import annotations
import os, io
import orjson

_ORJSON_OPTS = orjson.OPT_SORT_KEYS | orjson.OPT_APPEND_NEWLINE

def _dumps_bytes(obj: object) -> bytes:
    return orjson.dumps(obj, option=_ORJSON_OPTS)

def write_jsonl(path: Path, rows: list[object]) -> None:
    # Backstop env toggle; defaults to v2
    writer_ver = os.getenv("ENRICH_JSONL_WRITER", "v2")
    if writer_ver != "v2":
        # fallback to previous behavior (pretty text)
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(orjson.dumps(row).decode("utf-8"))
                f.write("\n")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as f:
        for row in rows:
            f.write(_dumps_bytes(row))

def write_json(path: Path, obj: object, *, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if pretty:
        # keep human-facing pretty JSON for docs
        text = orjson.dumps(obj, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS).decode("utf-8")
        path.write_text(text + "\n", encoding="utf-8")
    else:
        path.write_bytes(_dumps_bytes(obj))
```

---

## Phase 1.5 — “Strongly recommended” refinements (robustness wins)

### 4) LibCST: add Providers + matchers (fidelity without heuristics)

> **Why:** You already build a `ModuleIndex` from LibCST. Add `ScopeProvider` and `QualifiedNameProvider` to avoid string heuristics and switch bespoke node branching to `libcst.matchers` for resilience. Your `index_module` and `ModuleIndex` are in `enrich/libcst_bridge.py`. 

**Advanced feature context:** Providers & matchers and their roles are summarized in your technical reference. 

**File:** `enrich/libcst_bridge.py` (skeleton of the inner core)

```python
# enrich/libcst_bridge.py
import libcst as cst
from libcst import metadata as cst_metadata
from libcst import matchers as m

def index_module(src: str) -> ModuleIndex:
    module = cst.parse_module(src)  # lossless CST
    wrapper = cst_metadata.MetadataWrapper(module)
    # Attach Providers to this wrapper
    wrapper.resolve((
        cst_metadata.PositionProvider,
        cst_metadata.ScopeProvider,
        cst_metadata.QualifiedNameProvider,
    ))

    class _Visitor(cst.CSTVisitor):
        METADATA_DEPENDENCIES = (
            cst_metadata.PositionProvider,
            cst_metadata.ScopeProvider,
            cst_metadata.QualifiedNameProvider,
        )
        # ...use self.get_metadata(...) where needed...

        def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
            if m.matches(node, m.FunctionDef()):
                qns = self.get_metadata(cst_metadata.QualifiedNameProvider, node, set())
                # record defs/exports using qualified names, not strings

        def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
            if node.names and any(getattr(n, "name", None) == "*" for n in node.names):
                # mark star-import presence precisely
                ...

    v = _Visitor()
    wrapper.visit(v)
    return v.build_index()
```

LibCST’s fidelity and Providers are the right tool for resolving re‑exports and star imports without brittle string logic. 

### 5) Tree‑sitter: compiled `Query` patterns with DFS fallback

> **Why:** Your `tree_sitter_bridge.build_outline()` currently does manual DFS filtering by node types; compiled `Query` runs in C and is easier to extend. Keep the current code as a fallback. `build_outline` is present in `enrich/tree_sitter_bridge.py`. 

**Advanced feature context:** Tree‑sitter’s Query language and capturing pattern usage are covered in your reference. 

**File:** `enrich/tree_sitter_bridge.py` (excerpt)

```python
# enrich/tree_sitter_bridge.py
from tree_sitter import Parser, Language

# Language bootstrap same as today...
PY_LANG = Language(tree_sitter_python.language())
_OUTLINE_QUERY = PY_LANG.query("""
  (function_definition name: (identifier) @name) @func
  (class_definition    name: (identifier) @name) @class
""")

def build_outline(source_bytes: bytes) -> list[tuple[str, tuple[int,int]]]:
    parser = Parser(PY_LANG)
    tree = parser.parse(source_bytes)
    caps = _OUTLINE_QUERY.captures(tree.root_node)

    items: list[tuple[str, tuple[int,int]]] = []
    seen_nodes = set()
    for node, label in caps:
        if label in ("func", "class") and node.id not in seen_nodes:
            name_node = None
            # walk sibling capture to get @name for this def
            # (the Python binding returns pairs; we can correlate by parent)
            # simplified for brevity
            items.append((label, node.start_point))
            seen_nodes.add(node.id)

    if items:
        return items

    # Fallback: your existing DFS
    return _fallback_outline(source_bytes)
```

### 6) SCIP decode: unify on `msgspec` for speed & validation

> **Why:** `msgspec.Struct` gives typed, validated models and fast JSON decode. Your public surface (`SCIPIndex.load/by_file/documents`) stays the same. `Document` and `SCIPIndex` already exist. 

**File:** `enrich/scip_reader.py` (core sketch)

```python
# enrich/scip_reader.py
from __future__ import annotations
from pathlib import Path
import msgspec, orjson
from typing import Mapping

class Document(msgspec.Struct, frozen=True):
    path: str
    symbols: list[str] = []
    kinds: list[str] = []   # align to existing usage
    # add fields you already depend on

class _IndexModel(msgspec.Struct, frozen=True):
    documents: list[Document] = []
    # add other needed top-level fields

class SCIPIndex:
    def __init__(self, model: _IndexModel) -> None:
        self._model = model
        self._by_file = {d.path: d for d in model.documents}

    @classmethod
    def load(cls, path: Path) -> "SCIPIndex":
        raw = path.read_bytes()
        model = msgspec.json.decode(raw, type=_IndexModel)
        return cls(model)

    def documents(self) -> Mapping[str, Document]:
        return self._by_file

    def by_file(self, path: str) -> Document | None:
        return self._by_file.get(path)

    # keep symbol_to_files(), etc., with the same signatures/behavior
```

---

## Phase 2 — Storage/format improvements

### 7) JSONL → DuckDB via native readers + MERGE

> **Why:** This removes Python row loops and preserves nested types. Your `DuckConn` and `ingest_modules_jsonl()` exist in `enrich/duckdb_store.py`; wire the load with `read_json_auto` and `MERGE`. 

**Advanced feature context:** DuckDB’s native readers & Relation API are in the reference. 

**File:** `enrich/duckdb_store.py` (new implementation)

```python
# enrich/duckdb_store.py
import duckdb
from pathlib import Path

def ingest_modules_jsonl(con: duckdb.DuckDBPyConnection, jsonl_path: Path, table: str = "modules") -> None:
    if not jsonl_path.exists():
        raise FileNotFoundError(jsonl_path)

    if not con.execute(f"SELECT 1 FROM information_schema.tables WHERE table_name = '{table}'").fetchone():
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_json_auto('{jsonl_path.as_posix()}') WHERE 0=1")

    con.execute(f"CREATE TEMP TABLE modules_stage AS SELECT * FROM read_json_auto('{jsonl_path.as_posix()}')")
    con.execute(f"""
        MERGE INTO {table} t
        USING modules_stage s
        ON t.path = s.path
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *;
    """)
```

Optionally guard this behind `USE_DUCKDB_JSON=1` during rollout.

### 8) Parquet standardization via Arrow Datasets

> **Why:** ZSTD + dictionary encoding + partitioning improves scan & prune in DuckDB. You already expose `write_parquet()` in `enrich/output_writers.py`. 

**Advanced feature context:** Arrow dataset writing and Parquet tuning are summarized in your reference. 

**File:** `enrich/output_writers.py` (new dataset writer)

```python
# enrich/output_writers.py
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
from pathlib import Path
from typing import Iterable

def write_parquet_dataset(
    table: pa.Table | Iterable[pa.RecordBatch],
    out_dir: Path,
    partitioning: list[str] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = ds.ParquetFileFormat()
    write_opts = fmt.make_write_options(compression="zstd", use_dictionary=True)

    ds.write_dataset(
        data=table,
        base_dir=str(out_dir),
        format=fmt,
        file_options=write_opts,
        partitioning=partitioning or [],
        existing_data_behavior="delete_matching",
    )
```

---

## Phase 3 — Quality & ergonomics

### 9) Exclude `stubs/` from scans; keep docstring parity non‑blocking

In `cli_enrich._discover_py_files()` add an exclusion for `stubs/` (and your overlays directory) to prevent feedback loops when overlays are activated. Lower docstring parity checks to warnings for non‑public modules inside your validators (you already have `ModuleRecordModel` and tag machinery) so CI noise stays low until adoption. 

### 10) Keep type‑checker posture aligned

No code change required now; just ensure overlays hit `stubPath`/search‑path for Pyright/Pyrefly as you toggle overlay policies (your configs are already strict and consistent). This mirrors the guidance in the library reference’s best‑practices section. 

---

## Tests (ready to drop into `tests/`)

> These guard every behavior change. They use minimal fixtures and the public entry points you already expose (CLI, writers, overlay policy, SCIP reader). The repo summary shows candidate tags like `reexport-hub` and `low-coverage` we can use for fixtures; you also track tag counts that will help pick overlay candidates during smoke runs. 

### A) CLI contract (Typer options visible & bound)

**File:** `tests/test_cli_contract.py`

```python
import subprocess, sys

def test_help_shows_global_options():
    out = subprocess.check_output([sys.executable, "-m", "codeintel_rev.cli_enrich", "--help"], text=True)
    for opt in ["--root", "--scip", "--out", "--pyrefly-json", "--tags-yaml", "--dry-run"]:
        assert opt in out
```

(Your CLI app is `app = Typer(...)` in `cli_enrich.py`, so `-m codeintel_rev.cli_enrich` is the simplest smoke path.) 

### B) JSONL determinism

**File:** `tests/test_jsonl_writer_determinism.py`

```python
from pathlib import Path
from codeintel_rev.enrich.output_writers import write_jsonl

def test_jsonl_sorted_and_stable(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ENRICH_JSONL_WRITER", "v2")
    p = tmp_path / "mods.jsonl"
    rows = [{"b":2,"a":1}, {"d":4,"c":3}]
    write_jsonl(p, rows)
    b1 = p.read_bytes()
    write_jsonl(p, rows)  # overwrite
    b2 = p.read_bytes()
    assert b1 == b2
    assert b1.endswith(b"\n")
```

### C) Overlay gating

**File:** `tests/test_overlay_gating.py`

```python
from pathlib import Path
from codeintel_rev.enrich.stubs_overlay import generate_overlay_for_file, OverlayContext, OverlayPolicy
from codeintel_rev.enrich.libcst_bridge import ModuleIndex

def _idx(exports: list[tuple[str,str]]) -> ModuleIndex:
    # build a minimal ModuleIndex stub adequate for the predicate
    idx = ModuleIndex()
    idx.exports = [type("E", (), {"kind": k, "name": n}) for k, n in exports]
    return idx

def test_no_overlay_without_star_or_hub(tmp_path: Path):
    ctx = OverlayContext(root=tmp_path, package_name="x", overlays_root=tmp_path/"over", stubs_root=tmp_path/"stubs",
                         scip_index=None, type_counts={}, policy=OverlayPolicy(export_hub_threshold=10),
                         inputs=None)
    f = tmp_path/"pkg"/"mod.py"; f.parent.mkdir(parents=True); f.write_text("x=1")
    assert not generate_overlay_for_file(ctx, f, _idx([("named","a")]))

def test_overlay_for_star_import(tmp_path: Path):
    ctx = OverlayContext(root=tmp_path, package_name="x", overlays_root=tmp_path/"over", stubs_root=tmp_path/"stubs",
                         scip_index=None, type_counts={}, policy=OverlayPolicy(export_hub_threshold=10),
                         inputs=type("I", (), {"tag_index":{"overlay-needed":[]}}))
    f = tmp_path/"pkg"/"mod.py"; f.parent.mkdir(parents=True); f.write_text("from x import *")
    assert generate_overlay_for_file(ctx, f, _idx([("star","*")]))
```

(Adjust `OverlayContext`/`OverlayPolicy` construction to match your actual constructor signatures.) 

### D) SCIP decode round‑trip (parity)

**File:** `tests/test_scip_reader_roundtrip.py`

```python
from pathlib import Path
from codeintel_rev.enrich.scip_reader import SCIPIndex

def test_scip_load_by_file(tmp_path: Path):
    sample = {
        "documents": [
            {"path":"a.py","symbols":["s:a"],"kinds":["function"]},
            {"path":"b.py","symbols":["s:b"],"kinds":["class"]},
        ]
    }
    p = tmp_path/"index.scip.json"
    p.write_text(__import__("json").dumps(sample), encoding="utf-8")
    idx = SCIPIndex.load(p)
    assert idx.by_file("a.py").symbols == ["s:a"]
    assert set(idx.documents().keys()) == {"a.py", "b.py"}
```

### E) DuckDB ingestion

**File:** `tests/test_duckdb_ingestion.py`

```python
import duckdb
from pathlib import Path
from codeintel_rev.enrich.duckdb_store import ingest_modules_jsonl

def test_ingest_jsonl_merge(tmp_path: Path):
    p = tmp_path/"mods.jsonl"
    p.write_text('{"path":"a.py","n":1}\n{"path":"b.py","n":2}\n', encoding="utf-8")

    con = duckdb.connect(":memory:")
    ingest_modules_jsonl(con, p, table="modules")
    assert con.sql("SELECT COUNT(*) FROM modules").fetchone()[0] == 2

    # upsert
    p.write_text('{"path":"b.py","n":3}\n{"path":"c.py","n":1}\n', encoding="utf-8")
    ingest_modules_jsonl(con, p, table="modules")
    rows = dict(con.sql("SELECT path,n FROM modules ORDER BY path").fetchall())
    assert rows == {"a.py":1, "b.py":3, "c.py":1}
```

### F) Parquet dataset options

**File:** `tests/test_parquet_dataset_write.py`

```python
import pyarrow as pa, pyarrow.parquet as pq, pyarrow.dataset as ds
from pathlib import Path
from codeintel_rev.enrich.output_writers import write_parquet_dataset

def test_parquet_dataset_options(tmp_path: Path):
    tbl = pa.table({"language":["py","py","ts"], "pkg":["a","a","b"], "n":[1,2,3]})
    out = tmp_path/"ds"
    write_parquet_dataset(tbl, out, partitioning=["language","pkg"])
    # ensure partitioning wrote multiple files and metadata exists
    assert any(out.rglob("*.parquet"))
    # quick scan through dataset
    scanned = ds.dataset(out, format="parquet").to_table()
    assert scanned.num_rows == 3
```

---

## Phase 4 — CLI ergonomics & small hardeners

1. **Shell completion**: Expose Typer completion (`--install-completion`) and surface `--dry-run` on all mutating subcommands. (Your `app = Typer(add_completion=True, ...)` is already in place.) 
2. **Exclude `stubs/`** in `_discover_py_files(root, patterns)` by filtering paths that contain `/stubs/` or the overlays folder. 
3. **Docstring parity severity**: In `enrich/validators.py` reduce non‑public parity checks to warnings; keep public modules (tag `public-api`) as errors later. Your tag inventory shows many “public‑api” classifiers to leverage. 

---

## Phase 5 — End‑to‑end smoke (local workflow)

1. `codeintel-enrich build --root . --scip index.scip.json --out out/ --dry-run` (no writes).
2. `ENRICH_JSONL_WRITER=v2 codeintel-enrich build ...` then run tests B–F.
3. `USE_DUCKDB_JSON=1` to validate ingestion on your real `modules.jsonl`.
4. Toggle overlays via your existing overlay CLI/config; confirm only star‑import/“hub”/tagged modules get `.pyi` and `stubs/` is excluded from scans. 

---

## Where this plan uses “library power” you weren’t fully exploiting

* **LibCST Providers & matchers** instead of manual heuristics → fewer edge‑case bugs around exports/re‑exports, and more reliable overlay gates. (Parsing fidelity: why LibCST is chosen.) 
* **Tree‑sitter `Query`** instead of hand DFS → faster, declarative outlines and easier language extension. 
* **`msgspec.Struct`** as the canonical SCIP model → stricter schema & faster decode for large indices (no API drift). 
* **DuckDB native readers + `MERGE`** → simpler, faster ingestion; keeps nested JSON and scales better. 
* **Arrow dataset write** with ZSTD + dictionary + partitioning → lower storage + better scan pruning in DuckDB. 

---

## Appendix — Small diffs you can drop in now

### A) `_discover_py_files`: ignore `stubs/` and overlays

**File:** `cli_enrich.py` (predicate inside `_iter_files` or filter stage)

```python
def _iter_files(root: Path, patterns: tuple[str, ...]) -> Iterable[Path]:
    for p in root.rglob("*.py"):
        rel = p.as_posix()
        if "/stubs/" in rel or "/overlays/" in rel:
            continue
        if any(fnmatch.fnmatch(rel, pat) for pat in patterns):
            yield p
```

(Integrate with your existing `_discover_py_files` helper.) 

### B) Make overlay thresholds configurable (they already are)

You already define `EXPORT_HUB_THRESHOLD`, `OVERLAY_PARAM_THRESHOLD`, `OVERLAY_FAN_IN_THRESHOLD`, etc., in `cli_enrich.py`; ensure your CLI surface lets users override them (they are read today via overlay options & config readers). Tie the new `is_hub` check to `export_hub_threshold`. 

---

## Observability hooks (optional but easy)

* Use your existing `_stage_span()` in `cli_enrich.py` to emit elapsed time and row counts after each stage (write JSONL, ingest DuckDB, write Parquet). It already logs `perf_counter()` timing and stage metadata; add `rows=N`, `bytes=B` to the metadata map for quick “what changed” diffing in CI logs. 

---

## Summary of areas of opportunity (diagnostic to prescriptive)

* **Bespoke traversal logic** in CST/TS: replace with **LibCST matchers** & **TS Query** to blunt syntactic edge‑cases. 
* **Home‑grown JSON writing**: use **`orjson` bytes** with sorted keys for deterministic artifacts. 
* **Python‑driven ingestion**: switch to **DuckDB native readers** and SQL `MERGE` for both simplicity and speed. 
* **Ad‑hoc overlay triggers**: narrow with **export hubs + star‑imports + tag gating**, backed by your existing thresholds and tag index. Your repo summary shows 15 modules tagged `reexport-hub`; those are ideal candidates to start with while keeping the blast radius small. 

If you want, I can also produce a tiny PR script that applies these patches and runs the test matrix (pytest + a short end‑to‑end `build` run) so you get a one‑shot CI signal.
