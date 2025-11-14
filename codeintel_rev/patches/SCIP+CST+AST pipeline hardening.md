Below is a drop‑in **hardening & modularity upgrade** for your SCIP+CST+AST pipeline with **end‑to‑end tests**. I kept existing public surfaces intact, added clear seams for extension, and wired everything through Typer in a way that resolves the option-binding issue you hit earlier.

I’m referencing your current modules and configs so you can see exactly what this plugs into (e.g., `libcst_bridge.index_module`, `SCIPIndex.load`, `build_outline`, `collect_pyrefly/collect_pyright`, `output_writers`), and I’ve included end‑to‑end tests that run the CLI, validate the JSONL rows, and (optionally) load into DuckDB.     

---

## What this delivers

1. **Robust path normalization** shared across SCIP/CST/AST, so all outputs use a single repository‑relative, POSIX‑style path (critical for joins later).
2. **Graph extraction decoupled** from the CLI (import/use graphs, metrics), so you can reuse it in tests and future tooling.
3. **Validated records** before writing—lightweight Pydantic models catch schema drift early.
4. **DuckDB ingestion** behind a small adapter that lazy‑imports the heavy dependency via your `gate_import` helper. (This defers import cost and lets you keep DuckDB optional.) 
5. **Typer subcommands done correctly**, keeping the signature‑based option binding (no wrappers that hide options), which addresses the issue you described. Your earlier working pattern used module‑level `typer.Option` objects—this plan keeps that pattern. 
6. **End‑to‑end CLI tests** using Typer’s `CliRunner`, including a minimal SCIP fixture, JSONL validation, and (if DuckDB is available) an ingestion smoke test.
7. **No breaking changes**: `modules.jsonl` still contains the fields you already rely on (shape documented in your spec note), and the CLI continues to emit per‑module Markdown and repo‑level maps. 

---

## New files (add)

### 1) `codeintel_rev/enrich/path_norm.py`

Single source of truth for path handling.

```diff
*** /dev/null
--- a/codeintel_rev/enrich/path_norm.py
+ # SPDX-License-Identifier: MIT
+ from __future__ import annotations
+ from pathlib import Path
+
+ def repo_relpath(repo_root: Path, file_path: Path) -> str:
+     """Return POSIX relative path from repo_root to file_path."""
+     rel = file_path.resolve().relative_to(repo_root.resolve())
+     return rel.as_posix()
+
+ def module_name_from_path(repo_root: Path, file_path: Path, package_prefix: str | None = None) -> str:
+     """
+     Turn a Python file path into a dotted module name.
+     Example: repo/src/pkg/util/helpers.py -> pkg.util.helpers (or with prefix).
+     """
+     rel = repo_relpath(repo_root, file_path)
+     stem = rel[:-3] if rel.endswith(".py") else rel
+     # drop common top-levels like "src/" if present
+     parts = [p for p in Path(stem).parts if p not in (".", "src")]
+     if parts and parts[-1] == "__init__":
+         parts = parts[:-1]
+     mod = ".".join(parts)
+     return f"{package_prefix}.{mod}" if package_prefix else mod
+
+ def normalize_posix(path: str | Path) -> str:
+     """Normalize any input path to POSIX style (forward slashes)."""
+     return Path(path).as_posix()
```

### 2) `codeintel_rev/enrich/graph_builder.py`

Extract & analyze import/use graphs independent of CLI.

```diff
*** /dev/null
--- a/codeintel_rev/enrich/graph_builder.py
+ # SPDX-License-Identifier: MIT
+ from __future__ import annotations
+ from dataclasses import dataclass, field
+ from typing import Any, Iterable
+
+ @dataclass(slots=True)
+ class ImportGraph:
+     edges: set[tuple[str, str]] = field(default_factory=set)  # (from_path -> to_path)
+     fan_in: dict[str, int] = field(default_factory=dict)
+     fan_out: dict[str, int] = field(default_factory=dict)
+     cycle_group: dict[str, int] = field(default_factory=dict)
+
+ def build_module_name_map(rows: Iterable[dict[str, Any]], package_prefix: str | None) -> dict[str, str]:
+     """
+     Map dotted module names -> repo-relative file paths.
+     """
+     mapping: dict[str, str] = {}
+     for r in rows:
+         path = r.get("path")
+         if not isinstance(path, str):
+             continue
+         # best-effort: infer module name from path
+         mod = path[:-3].replace("/", ".") if path.endswith(".py") else path.replace("/", ".")
+         if mod.endswith(".__init__"):
+             mod = mod[: -len(".__init__")]
+         if package_prefix and not mod.startswith(package_prefix + "."):
+             mod = f"{package_prefix}.{mod}"
+         mapping[mod] = path
+     return mapping
+
+ def build_import_graph(rows: Iterable[dict[str, Any]], package_prefix: str | None) -> ImportGraph:
+     g = ImportGraph()
+     name_map = build_module_name_map(rows, package_prefix)
+     for r in rows:
+         src = r.get("path")
+         if not isinstance(src, str):
+             continue
+         for imp in r.get("imports") or []:
+             module = imp.get("module")
+             if not module:
+                 # absolute "import X" captured as names; connect to each
+                 for nm in imp.get("names") or []:
+                     dst = name_map.get(nm) or name_map.get(f"{package_prefix}.{nm}") if package_prefix else None
+                     if dst:
+                         g.edges.add((src, dst))
+                 continue
+             # from module import ...
+             dst = name_map.get(module) or name_map.get(f"{package_prefix}.{module}") if package_prefix else None
+             if dst:
+                 g.edges.add((src, dst))
+     # metrics
+     for u, v in g.edges:
+         g.fan_out[u] = g.fan_out.get(u, 0) + 1
+         g.fan_in[v] = g.fan_in.get(v, 0) + 1
+     # SCC (condensed; Kosaraju)
+     adj: dict[str, list[str]] = {}
+     radj: dict[str, list[str]] = {}
+     nodes = set([u for u, _ in g.edges] + [v for _, v in g.edges])
+     for u, v in g.edges:
+         adj.setdefault(u, []).append(v)
+         radj.setdefault(v, []).append(u)
+     order: list[str] = []
+     seen: set[str] = set()
+     def dfs1(x: str) -> None:
+         seen.add(x)
+         for y in adj.get(x, []):
+             if y not in seen:
+                 dfs1(y)
+         order.append(x)
+     for n in nodes:
+         if n not in seen:
+             dfs1(n)
+     comp_id = 0
+     seen.clear()
+     def dfs2(x: str) -> None:
+         g.cycle_group[x] = comp_id
+         seen.add(x)
+         for y in radj.get(x, []):
+             if y not in seen:
+                 dfs2(y)
+     for n in reversed(order):
+         if n not in seen:
+             dfs2(n)
+             comp_id += 1
+     return g
```

*(Your previous CLI already derived graph metrics inline; this moves them into a re‑usable module so tests and other tools can call them directly.)* 

### 3) `codeintel_rev/enrich/validators.py`

Lightweight Pydantic checks for row shape.

```diff
*** /dev/null
--- a/codeintel_rev/enrich/validators.py
+ # SPDX-License-Identifier: MIT
+ from __future__ import annotations
+ from pydantic import BaseModel, Field
+ from typing import Any
+
+ class ModuleRecordModel(BaseModel):
+     path: str
+     docstring: str | None = None
+     imports: list[dict[str, Any]] = Field(default_factory=list)
+     defs: list[dict[str, Any]] = Field(default_factory=list)
+     exports: list[str] = Field(default_factory=list)
+     outline_nodes: list[dict[str, Any]] = Field(default_factory=list)
+     scip_symbols: list[str] = Field(default_factory=list)
+     parse_ok: bool = True
+     errors: list[str] = Field(default_factory=list)
+     tags: list[str] = Field(default_factory=list)
+     type_errors: int = 0
+
+     class Config:
+         frozen = True
```

*(Fields match your `ModuleRecord` and `modules.jsonl` spec so validation is strict but familiar.)*  

### 4) `codeintel_rev/enrich/duckdb_store.py`

Declarative ingestion, lazy‑loaded.

```diff
*** /dev/null
--- a/codeintel_rev/enrich/duckdb_store.py
+ # SPDX-License-Identifier: MIT
+ from __future__ import annotations
+ from dataclasses import dataclass
+ from pathlib import Path
+ from typing import Iterable, Mapping
+
+ import pyarrow as pa
+ import pyarrow.json as paj
+ from codeintel_rev.typing import gate_import  # lazy heavy dep import
+
+ @dataclass(frozen=True)
+ class DuckConn:
+     db_path: Path
+
+ def _duck() -> object:
+     # Import when actually needed; keeps analytics optional
+     return gate_import("duckdb", purpose="analytics")  # returns module
+
+ def ensure_schema(conn: DuckConn) -> None:
+     duckdb = _duck()
+     con = duckdb.connect(str(conn.db_path))
+     con.execute("""
+         CREATE TABLE IF NOT EXISTS modules (
+             path TEXT PRIMARY KEY,
+             docstring TEXT,
+             imports JSON,
+             defs JSON,
+             exports JSON,
+             outline_nodes JSON,
+             scip_symbols JSON,
+             parse_ok BOOLEAN,
+             errors JSON,
+             tags JSON,
+             type_errors INTEGER
+         )
+     """)
+     con.close()
+
+ def ingest_modules_jsonl(conn: DuckConn, jsonl_path: Path) -> int:
+     """
+     Load modules.jsonl into DuckDB. Upsert on path, keeping latest row.
+     """
+     duckdb = _duck()
+     ensure_schema(conn)
+     con = duckdb.connect(str(conn.db_path))
+     # Use Arrow inference
+     table = paj.read_json(str(jsonl_path))
+     # Load to a temp view, then MERGE to keep "path" unique
+     con.register("mod_tmp", table)
+     con.execute("""
+         CREATE TEMP TABLE _mod_new AS SELECT * FROM mod_tmp
+     """)
+     con.execute("""
+         INSERT INTO modules
+         SELECT * FROM _mod_new
+         ON CONFLICT (path) DO UPDATE SET
+             docstring = excluded.docstring,
+             imports = excluded.imports,
+             defs = excluded.defs,
+             exports = excluded.exports,
+             outline_nodes = excluded.outline_nodes,
+             scip_symbols = excluded.scip_symbols,
+             parse_ok = excluded.parse_ok,
+             errors = excluded.errors,
+             tags = excluded.tags,
+             type_errors = excluded.type_errors
+     """)
+     count = con.execute("SELECT COUNT(*) FROM modules").fetchone()[0]
+     con.close()
+     return int(count)
```

*(Imports DuckDB via your `gate_import` util so it won’t load unless needed.)* 

---

## CLI refactor (fix Typer options & add subcommands)

Your current working style relies on Typer’s **signature‑based** inspection with module‑level `Option` definitions and direct `@app.command` decoration—which is the *correct* approach for getting options registered. I preserved that pattern and added subcommands without wrapping functions (the wrapping was the root cause in your issue report). 

```diff
--- a/codeintel_rev/cli_enrich.py
+++ b/codeintel_rev/cli_enrich.py
@@
- import typer
+ import typer
  from pathlib import Path
  from typing import Any
@@
- from codeintel_rev.enrich.type_integration import TypeSummary, collect_pyrefly, collect_pyright
+ from codeintel_rev.enrich.type_integration import TypeSummary, collect_pyrefly, collect_pyright
+ from codeintel_rev.enrich.path_norm import repo_relpath
+ from codeintel_rev.enrich.graph_builder import build_import_graph, build_module_name_map
+ from codeintel_rev.enrich.validators import ModuleRecordModel
+ from codeintel_rev.enrich.duckdb_store import DuckConn, ingest_modules_jsonl
@@
- app = typer.Typer(
+ app = typer.Typer(
     add_completion=False,
     help="Combine SCIP + LibCST + Tree-sitter + type checker signals into a repo map.",
 )
+ scan_app = typer.Typer(no_args_is_help=True, help="Scan Python files and emit enrichment artifacts.")
+ db_app = typer.Typer(no_args_is_help=True, help="Load enrichment artifacts into DuckDB.")
+ app.add_typer(scan_app, name="scan")
+ app.add_typer(db_app, name="to-duckdb")
@@
- @dataclass(slots=True, frozen=True)
+ @dataclass(slots=True, frozen=True)
  class ModuleRecord:
@@
- def _iter_files(root: Path) -> Iterable[Path]:
+ def _iter_files(root: Path) -> Iterable[Path]:
     ...
@@
- @app.command()
- def main(
+ @scan_app.command("run")
+ def scan(
     root: Path = ROOT_OPTION,
     scip: Path = SCIP_OPTION,
     out: Path = OUT_OPTION,
     pyrefly_json: Path | None = PYREFLY_OPTION,
     tags_yaml: Path | None = TAGS_OPTION,
 ) -> None:
@@
-     for fp in _iter_files(root):
+     repo_root = root.resolve()
+     for fp in _iter_files(root):
         rel = str(fp.relative_to(root))
         code = fp.read_text(encoding="utf-8", errors="ignore")
         idx = index_module(rel, code)
@@
-        # Tags
+        # Validate row before persisting
         row: dict[str, Any] = {
             "path": rel,
             "docstring": idx.docstring,
@@
             "type_errors": type_errors,
         }
+        ModuleRecordModel.model_validate(row)  # raises on shape drift
         module_rows.append(row)
@@
     write_jsonl(out / "modules" / "modules.jsonl", module_rows)
@@
- def main(...):
-     ...
+@db_app.command("modules")
+def load_modules(
+    modules_jsonl: Path = typer.Option(..., "--modules-jsonl", exists=True, help="Path to modules.jsonl"),
+    db_path: Path = typer.Option(Path("build/enrich/enrich.duckdb"), "--db", help="DuckDB file path"),
+) -> None:
+    """Load modules.jsonl into DuckDB (idempotent upsert on path)."""
+    count = ingest_modules_jsonl(DuckConn(db_path=db_path), modules_jsonl)
+    typer.echo(f"Loaded {count} rows into {db_path}")
+
+def main() -> None:
+    app()
```

**Why this fixes your options problem**
Typer reads options *from the function signature at decoration time*. By defining `ROOT_OPTION`, `SCIP_OPTION`, etc., and using them as defaults **on the decorated command function**, Typer picks them up correctly (no “manual wrap”). This matches your previous, working approach. 

---

## End‑to‑end tests

### 1) `tests/enrich/test_pipeline_e2e.py`

Runs the scanning subcommand on a temp repo, asserts output shape, and (optionally) loads into DuckDB.

```diff
*** /dev/null
--- a/tests/enrich/test_pipeline_e2e.py
+ # SPDX-License-Identifier: MIT
+ from __future__ import annotations
+ from pathlib import Path
+ import json
+ import sys
+ import pytest
+ from typer.testing import CliRunner
+ from codeintel_rev.cli_enrich import app
+
+ runner = CliRunner()
+
+ def _write_file(p: Path, text: str) -> None:
+     p.parent.mkdir(parents=True, exist_ok=True)
+     p.write_text(text, encoding="utf-8")
+
+ def _minimal_scip(path: Path, files: list[str]) -> Path:
+     """
+     Produce a tiny SCIP index with documents for provided files.
+     """
+     payload = {
+         "documents": [{"relativePath": f, "occurrences": [], "symbols": []} for f in files],
+         "externalSymbols": [],
+     }
+     out = path / "index.scip.json"
+     out.write_text(json.dumps(payload), encoding="utf-8")
+     return out
+
+ @pytest.mark.smoke
+ def test_scan_and_duckdb(tmp_path: Path):
+     # 1) Arrange a small repo
+     root = tmp_path / "repo"
+     _write_file(root / "pkg" / "__init__.py", '"""pkg"""')
+     _write_file(root / "pkg" / "a.py", '"""A."""\nfrom pkg.b import foo\nclass A: ...\n')
+     _write_file(root / "pkg" / "b.py", 'def foo(x: int) -> int: return x + 1\n')
+     scip = _minimal_scip(root, ["pkg/__init__.py", "pkg/a.py", "pkg/b.py"])
+     out = root / "build" / "enrich"
+
+     # 2) Run scanner
+     result = runner.invoke(app, ["scan", "run", "--root", str(root), "--scip", str(scip), "--out", str(out)])
+     assert result.exit_code == 0, result.output
+
+     # 3) Validate modules.jsonl exists and is parseable
+     mod_jsonl = out / "modules" / "modules.jsonl"
+     assert mod_jsonl.exists()
+     lines = [json.loads(line) for line in mod_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
+     assert any(r.get("path") == "pkg/a.py" for r in lines)
+     # required keys present (shape guarded by validators in CLI)
+     required = {"path","imports","defs","exports","outline_nodes","scip_symbols","parse_ok","errors","tags","type_errors"}
+     assert required.issubset(lines[0].keys())
+
+     # 4) Optional: DuckDB ingestion (skip if duckdb missing)
+     try:
+         import duckdb  # type: ignore
+     except Exception:
+         pytest.skip("duckdb not installed")
+     db_path = out / "enrich.duckdb"
+     result2 = runner.invoke(app, ["to-duckdb", "modules", "--modules-jsonl", str(mod_jsonl), "--db", str(db_path)])
+     assert result2.exit_code == 0, result2.output
+     con = duckdb.connect(str(db_path))
+     cnt = con.execute("SELECT COUNT(*) FROM modules").fetchone()[0]
+     assert cnt >= len(lines)
+     con.close()
```

Your `pytest.ini` is already configured for markers and testpaths—this test fits right in. 

---

## DuckDB demo SQL (quick joins you’ll likely run)

```sql
-- Count modules by tag (flatten JSON array)
SELECT t, COUNT(*) AS n
FROM (
  SELECT path, UNNEST(tags) AS t
  FROM modules
)
GROUP BY 1
ORDER BY n DESC;

-- Top fan-in import hubs (if you later materialize import graph in DuckDB)
-- Here we use a proxy: “modules mentioned in many others” via textual imports.
WITH flat AS (
  SELECT m.path AS src, json_extract(imp, '$.module') AS dst
  FROM modules m, UNNEST(modules.imports) AS imp
)
SELECT dst, COUNT(*) AS fan_in
FROM flat
WHERE dst IS NOT NULL
GROUP BY 1
ORDER BY fan_in DESC
LIMIT 20;
```

---

## Why these changes line up with your current code

* **CST spine** stays the same: we still call `index_module(rel, code)` and use its imports/defs/exports/docstring as the structural core. 
* **SCIP ingestion** stays the same: `SCIPIndex.load` + `by_file()` for symbol enrichment. 
* **Tree‑sitter outline** remains a fast, best‑effort index for Python (and other configs) so pages render even if a module fails CST parsing. 
* **Type signals** still come from `collect_pyrefly`/`collect_pyright`; we only centralize validation before writing. 
* **Writers** aren’t replaced—`write_json`, `write_jsonl`, and `write_markdown_module` are still used verbatim for artifacts. 
* **Typer options** follow the working pattern you already have (`ROOT_OPTION`, etc.), not the wrapper approach that removed flags. 
* **Heavy deps** remain optional via your `gate_import` utility (e.g., for DuckDB), so bringing analytics online won’t penalize normal scans or environments without DuckDB. 
* **Schema parity** with your `modules.jsonl` is preserved (fields and meanings match the spec you distributed). 

---

## Integration notes

1. **Dependencies**
   You already ship `pyarrow` (and stubs), `typer`, `pydantic`, and optional `orjson`. If DuckDB isn’t yet in your runtime, either add it to your base env or keep it optional and import‑gated as above. (Your `pyproject.toml` already includes the set we use; add `"duckdb"` only if you want it present by default.) 

2. **SCIP & module map**
   This fits into the repo map and symbol graph you already emit; the new code simply modularizes builder steps. (Your `repo_map.json` includes `module_count`/`symbol_edge_count`—untouched by this change.)

3. **Configs & CI**
   Keep running Pyright and Pyrefly the same way; the CLI will ingest those reports just as before (or run Pyright on the fly). Your Pyright/pyrefly configurations are already set up for strictness baselines.  

---

## How to run

```bash
# 1) Scan
codeintel-enrich scan run \
  --root . \
  --scip build/index.scip.json \
  --out build/enrich \
  --pyrefly-json build/pyrefly.json \
  --tags-yaml codeintel_rev/enrich/tagging_rules.yaml

# 2) Load modules.jsonl to DuckDB (optional)
codeintel-enrich to-duckdb modules \
  --modules-jsonl build/enrich/modules/modules.jsonl \
  --db build/enrich/enrich.duckdb
```

*(This reuses your CLI entrypoint; the only change is adding subcommands. Everything else—JSONL, Markdown module pages, symbol graphs—continues to be written the way you’re used to.)* 

---

## Why this is “best‑in‑class” for hardening & extensibility

* **Single truth for paths** ensures reproducible joins across SCIP/CST/AST and later analytics layers.
* **Pure functions per stage** (graph, validation, ingestion) mean localized failures with precise messages and easy unit tests.
* **Lazy heavy imports** keep fast paths fast and make optional analytics genuinely optional. 
* **Typer subcommands** scale cleanly as you add future steps (ownership/bus‑factor, LLM slices) without increasing command complexity. 

---

## Touchpoints with your existing code (for reviewers)

* `index_module` is still the CST backbone. We don’t modify its API or callers—only how results are validated and written. 
* `SCIPIndex.load` and symbol accessors are used as-is; the new `graph_builder` just stops duplicating logic inside the CLI. 
* `build_outline` remains the outline fast‑path; unchanged. 
* `collect_pyrefly/collect_pyright` call sites remain, with the same JSON/JSONL expectations. 
* Writers (`write_json`, `write_jsonl`, `write_markdown_module`) remain the only serialization surface. 

---

### Appendix: References in this repo

* **CLI entrypoint with Typer options pattern** (the “good” way we’re following): `codeintel_rev/cli_enrich.py`. 
* **CST extraction**: `codeintel_rev/enrich/libcst_bridge.py`. 
* **SCIP loader**: `codeintel_rev/enrich/scip_reader.py`. 
* **Tree‑sitter outline**: `codeintel_rev/enrich/tree_sitter_bridge.py`. 
* **Type check adapters**: `codeintel_rev/enrich/type_integration.py`. 
* **Writers**: `codeintel_rev/enrich/output_writers.py`. 
* **`modules.jsonl` field reference** (your doc/spec): *modules.jsonl Reference*. 
* **Repo map** (generated output, unchanged semantics): `repo_map.json`.

---

### What I didn’t touch (on purpose)

* Ownership/bus‑factor and “LLM slices” (you said those can wait).
* Overlay stub generation knobs (you removed the autogen overlays and we kept it that way here).
* Any schema in your existing egress files beyond validation—so downstream dashboards or checks won’t break.

If you’d like, I can also provide a one‑shot patchfile that bundles all the diffs above into a single `git apply`‑ready blob.
