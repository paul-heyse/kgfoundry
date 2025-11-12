#Concept and scope overview#


Absolutely—here’s the **mechanistic narrative** of how your enrichment stack “stitches” repo intelligence together, what each layer contributes, and why this composition is robust for both humans and LLM agents.

---

## 1) What we treat as the *truths* we stitch

1. **Per‑file structural truth (LibCST).**
   For every Python file, we parse to a tolerant concrete syntax tree and extract:

* imports (absolute/relative, aliases, star‑imports),
* top‑level definitions (classes/functions) with line numbers,
* `__all__`‑declared exports,
* the module docstring,
* a resilient `parse_ok`/`errors` flag so one bad file doesn’t block the run.
  Mechanically, this is done by `index_module()` which wraps LibCST with the `PositionProvider` to capture exact locations, and a visitor (`_IndexVisitor`) that records `ImportEntry`, `DefEntry`, and `exports` if it finds `__all__` assignments. On any exception, we emit a minimal record with `parse_ok=False` and the error text. 

2. **Cross‑file symbol truth (SCIP).**
   SCIP gives us the graph that LibCST can’t: which symbol is defined where, and where it’s referenced. We load your index once (`SCIPIndex.load`) and keep two fast maps:

* `by_file()` → **document → occurrences/symbols**, and
* `symbol_to_files()` → **symbol → list of files where it occurs** (used to resolve star‑imports and re‑exports).
  The loader explicitly tolerates schema variants (different field names in real‑world SCIP dumps), so we don’t break on format drift. 

3. **Multi‑language outline truth (Tree‑sitter).**
   To understand configs and docs that drive Python behavior, we run a lightweight outline over JSON/YAML/TOML/Markdown (plus Python). For Python, we pull function/class nodes; for other formats we keep a skeletal outline and can extend extractors as needed. This lets us later join “code that uses setting X” ↔ “config file where X is defined.” 

4. **Type‑checker truth (Pyrefly & Pyright).**
   We ingest per‑file error counts from **Pyrefly** (JSON/JSONL report) and **Pyright** (machine‑readable `--outputjson`). Both are summarized into `TypeSummary.by_file[file].error_count` so we can tag/measure typedness *without* changing your code. The collectors are defensive: if a tool isn’t present or the JSON is malformed, they quietly return `None` rather than fail the build. 

5. **Tagging truth (policy encoded in YAML + heuristics).**
   A small rule engine turns facts into actionable tags: e.g., `public-api` if `__all__` exists; `reexport-hub` if star‑imports or large `__all__`; `needs-types` if type errors > 0; `fastapi`, `pydantic`, etc., by import detection. The engine can load your rule file (`tagging_rules.yaml`) or fall back to defaults; it also records **reasons** for each tag to aid review. 

6. **Publisher truth (writers).**
   All stitched results are emitted in simple, tool‑friendly formats:

* `write_json` / `write_jsonl` for machine pipelines and
* `write_markdown_module` for a human/LLM‑readable snapshot (docstring, imports, defs, tags, errors).
  Writers are zero‑friction and orjson‑aware for speed on large outputs. 

---

## 2) The join keys that make stitching possible

* **Path is the primary join key.**
  Every source (CST, Tree‑sitter, Pyrefly/Pyright output) is keyed by the normalized file path. That lets us union structural facts, type signals, and outlines into one *module record* per file.

* **SCIP symbol strings are the cross‑file key.**
  When we need to “leave” the file boundary—e.g., to expand `from X import *`—we use SCIP’s **symbol → files** map and each document’s **occurrences** to find the source module and symbol kind. This is how re‑exports and use‑graphs are materialized. 

* **Consistent search paths & stub precedence are guaranteed by config.**
  Pyrefly and Pyright are both pointed at the same roots (`include`/`project‑includes`) and the same `stubs/` directory, so they agree about module discovery and **prefer real code unless a purposeful stub exists**—preventing the “overlay dominates real code everywhere” failure mode you hit earlier. (Pyright: `stubPath`, `executionEnvironments`; Pyrefly: `search-path`, `project-includes/excludes`, error policy.)

---

## 3) The stitching flow (end‑to‑end)

**Step A — Parse and index each Python file**
We call `index_module(path, code)`. It produces a `ModuleIndex` with `imports`, `defs`, `exports`, `docstring`, and `parse_ok`. This record is *purely structural* and local to the file. If LibCST chokes on edge cases, we still emit a valid record with `errors=[…]` so nothing downstream fails. 

**Step B — Load SCIP once and build lookups**
`SCIPIndex.load(index.scip.json)` ingests the repository symbol graph. We derive:

* `symbol_to_files()` for star‑import expansion and re‑export mapping,
* `file_symbol_kinds()` to understand symbol kinds per file (helpful for summaries).
  The loader tolerates schema differences and unnamed fields—important when your SCIP producer evolves. 

**Step C — Resolve exports & re‑exports (CST ⨯ SCIP)**
For modules with `__all__` or star‑imports, we use CST facts to decide *where* to expand and use SCIP symbol maps to decide *what* to expand into. The result becomes two fields on the record:

* `exports_resolved` (materialized list of names) and
* `reexports` (mapping `exported_name → (source_module, symbol)`),
  so agents see the *contract surface* clearly without spelunking through hubs. (You can see from your SCIP dump how rich the symbol and documentation payload is for this step.)

**Step D — Add multi‑language context (Tree‑sitter)**
We run `build_outline` for Python (defs) and for configs/markdown (keys/headings). That yields `TSOutline` nodes we can associate back to Python modules by import usage later (e.g., *which FastAPI router reads which YAML section*). The outline pass is fast and graceful—even if a language pack is missing, Python still works via the fallback. 

**Step E — Ingest typedness signals**
`collect_pyrefly()` and `collect_pyright()` summarize error counts per file. We attach `type_error_count` (and later `annotation_ratio` computed from CST defs) to the module record. Because both collectors are optional and defensive, the pipeline remains stable on developer machines and in CI. 

**Step F — Tag for routing & policy**
With imports, `__all__`, and type error counts in hand, we call `infer_tags(...)`. Default rules mark CLIs, FastAPI surfaces, test files, reexport hubs, public APIs, and files needing types; your YAML can extend or override this. We store both `tags` and `reasons` for transparency. 

**Step G — Publish artifacts**
We serialize:

* **Per‑module JSONL** for LLM/agent ingestion,
* **Module Markdown** for human review (docstring, imports/defs, tags, parse notes),
* **Auxiliary indices** (e.g., symbol/use graphs) when built.
  The writers handle directories automatically and switch to `orjson` if available for speed. 

---

## 4) Why the stitching is robust (failure modes & guardrails)

* **Parser resilience:** `index_module` never panics; it records a failure and moves on, keeping the build whole. 
* **SCIP schema drift:** the loader accepts multiple field spellings (`relativePath` vs `relative_path`) so you don’t rewrite code each time your indexer updates. 
* **Config alignment:** Pyrefly/Pyright both see `stubs/` and the same roots; Pyrefly opts into strict error families (`implicit-any`, `implicitly-defined-attribute`, etc.). This prevents accidental global stub dominance and encourages targeted overlays only where needed.
* **Dependency footing:** your `pyproject.toml` already includes the exact libraries we rely on (LibCST, docstring‑parser, DuckDB/Polars, Sphinx/Griffe), so the enrichment stack runs without side‑install steps. 
* **Test/coverage integration ready:** your `pytest.ini` sets consistent test paths and doctest flags—handy when you later join coverage and doc health into the same per‑file record. 

---

## 5) What this unlocks (immediately)

* **Clear public surface:** `exports_declared` + `exports_resolved` + `reexports` give an unambiguous API view per module for agents and reviewers. (The SCIP example you attached shows symbol docs rich enough to annotate those surfaces directly.) 
* **Focused typedness work:** `type_error_count` and tags like `needs-types` route strictness fixes to the *right* files without refactors or blanket overlays.
* **Config/code linkage:** Tree‑sitter outlines seed the “who uses which setting” join—crucial for safe refactors where behavior is configuration‑driven. 
* **LLM‑ready slices:** because everything is normalized by path and symbol, your writers can emit small, task‑specific context packs that stay *on contract* and avoid overwhelming models. 

---

### In one sentence

We **index structure with LibCST**, **link files via SCIP’s symbol graph**, **bring in config/doc context with Tree‑sitter**, **fold in typedness from Pyrefly/Pyright**, **label with a small policy engine**, and **publish compact JSONL/Markdown views**—all keyed by file path and SCIP symbols, and all guarded to keep the pipeline resilient on real‑world code.

If you’d like, I can now extend the writers with the new `exports_resolved`/`reexports`, `type_error_count`, and outline fields so your `modules.jsonl` and module pages surface these stitched facts directly.



# Detailed implementation plan with code #

Below I’m giving you **drop‑in code** that “stitches” the data you already have (LibCST module indices + SCIP + tags + type signals) into richer per‑module records. It does three things:

1. **Exports & re‑exports** (resolves `from X import *` against your own modules, using `__all__` if present, otherwise falling back to top‑level defs).
2. **Import graph analytics** (fan‑in, fan‑out, SCC cycle groups).
3. **Join type signals** and preserve the current JSONL/Markdown publishing.

The glue is a new `stitch.py` module plus a tiny patch in `cli_enrich.py` to call it.

---

## 1) New module: `codeintel_rev/enrich/stitch.py`

```python
# SPDX-License-Identifier: MIT
"""
Stitch LibCST + SCIP + tags into enriched per-module records.

Adds:
- exports_resolved: {origin_module -> [names]} for star imports and re-exports
- reexports: {public_name -> {"from": origin_module, "symbol": fq_name}}
- import graph metrics: fan_in, fan_out, cycle_group
- preserves type_errors and tags computed earlier

This module is dependency-light and operates on the dict rows already
produced in cli_enrich.py (ModuleRecord as dicts).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .scip_reader import SCIPIndex  # used for context/features we might add later


# ---------- Utilities for module name <-> path ----------

def _package_root(row_path: str) -> str:
    # Heuristic: derive 'codeintel_rev' from 'codeintel_rev/...' paths
    parts = Path(row_path).parts
    return parts[0] if parts else ""

def _module_name_from_path(row_path: str) -> str:
    p = Path(row_path)
    parts = list(p.parts)
    if not parts:
        return ""
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    # Special case: __init__.py -> package
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)

def _path_from_module_name(modname: str) -> str:
    # Turn "pkg.sub.module" -> "pkg/sub/module.py"
    # And "pkg.sub" (a package) -> "pkg/sub/__init__.py"
    parts = modname.split(".")
    return str(Path(*parts).with_suffix(".py"))

def _candidate_init_path(modname: str) -> str:
    return str(Path(*modname.split(".")) / "__init__.py")


# ---------- Import graph builders (fan-in/out, cycles) ----------

@dataclass
class _Graph:
    out_edges: Dict[str, Set[str]]
    in_edges: Dict[str, Set[str]]

def _build_import_graph(rows: List[Dict[str, Any]]) -> _Graph:
    """Build a repo-internal import graph using LibCST import summaries."""
    out: Dict[str, Set[str]] = defaultdict(set)
    inn: Dict[str, Set[str]] = defaultdict(set)

    # Map module -> path and path -> module to resolve repo-local edges
    path_to_mod = {r["path"]: _module_name_from_path(r["path"]) for r in rows}
    mod_to_path = {m: p for p, m in path_to_mod.items() if m}

    # Determine package root to constrain "internal" modules
    roots: Set[str] = { _package_root(r["path"]) for r in rows if r.get("path") }
    # Usually just {"codeintel_rev"} for this repo
    for row in rows:
        src_path = row["path"]
        src_mod = path_to_mod.get(src_path, "")
        if not src_mod:
            continue
        for imp in row.get("imports", []):
            mod = imp.get("module")
            level = int(imp.get("level") or 0)

            # Resolve relative imports into absolute dotted names when possible
            if level and src_mod:
                parts = src_mod.split(".")
                # remove 'level' parts from the right (stay within package)
                if level <= len(parts):
                    base = parts[: len(parts) - level]
                    if mod:
                        abs_mod = ".".join(base + [mod])
                    else:
                        # from . import foo  -> we can't know foo's module without name binding analysis
                        abs_mod = ".".join(base)  # at least mark the package
                else:
                    abs_mod = mod or ""  # give up gracefully
            else:
                abs_mod = mod or ""

            if not abs_mod:
                continue

            # Only keep edges inside our package root(s)
            # e.g., codeintel_rev.something...
            root_match = any(abs_mod.split(".")[0] == Root for Root in roots)
            if not root_match:
                continue

            # Map abs_mod to a path if we know it
            dst_path = mod_to_path.get(abs_mod)
            if not dst_path:
                # Try package form (__init__.py)
                init_path = _candidate_init_path(abs_mod)
                if init_path in path_to_mod:
                    dst_path = init_path

            if not dst_path:
                continue  # unresolved external or non-Python module

            if src_path != dst_path:
                out[src_path].add(dst_path)
                inn[dst_path].add(src_path)

    # Ensure every file appears in both maps
    for r in rows:
        out.setdefault(r["path"], set())
        inn.setdefault(r["path"], set())

    return _Graph(out_edges=out, in_edges=inn)


def _tarjan_scc(nodes: Iterable[str], edges: Dict[str, Set[str]]) -> Dict[str, int]:
    """Tarjan's algorithm to assign a cycle_group id per node (SCC id)."""
    index = 0
    indices: Dict[str, int] = {}
    lowlink: Dict[str, int] = {}
    stack: List[str] = []
    onstack: Set[str] = set()
    group_id = 0
    comp: Dict[str, int] = {}

    def strongconnect(v: str) -> None:
        nonlocal index, group_id
        indices[v] = index
        lowlink[v] = index
        index += 1
        stack.append(v)
        onstack.add(v)

        for w in edges.get(v, ()):
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in onstack:
                lowlink[v] = min(lowlink[v], indices[w])

        if lowlink[v] == indices[v]:
            # root of an SCC
            while True:
                w = stack.pop()
                onstack.remove(w)
                comp[w] = group_id
                if w == v:
                    break
            group_id += 1

    for v in nodes:
        if v not in indices:
            strongconnect(v)
    return comp


# ---------- Exports & re-exports ----------

def _module_record_by_name(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Build a map of fully-qualified module name -> module row dict."""
    result: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        m = _module_name_from_path(r["path"])
        if m:
            result[m] = r
    return result

def _public_names_from_row(row: Dict[str, Any]) -> Set[str]:
    """Prefer __all__; otherwise fall back to top-level def names."""
    exports = set(row.get("exports") or [])
    if exports:
        return exports
    names: Set[str] = set()
    for d in row.get("defs", []):
        kind = d.get("kind")
        name = d.get("name")
        if kind in {"function", "class"} and name and not name.startswith("_"):
            names.add(name)
    return names

def _resolve_star_imports_for_row(
    row: Dict[str, Any],
    module_rows_by_name: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, List[str]], Dict[str, Dict[str, str]]]:
    """
    Return (exports_resolved, reexports) for a single module row.

    exports_resolved: {origin_module -> [names]}
    reexports: {public_name -> {"from": origin_module, "symbol": "<origin_module>.<name>"}}
    """
    resolved: Dict[str, List[str]] = {}
    reexports: Dict[str, Dict[str, str]] = {}

    for imp in row.get("imports", []):
        if not imp.get("is_star"):
            continue
        origin = imp.get("module")
        level = int(imp.get("level") or 0)
        src_mod = _module_name_from_path(row["path"])
        if level and src_mod:
            # best-effort absolute module for "from .foo import *"
            base_parts = src_mod.split(".")
            if level <= len(base_parts):
                base = base_parts[: len(base_parts) - level]
                origin = ".".join(base + ([origin] if origin else []))
        if not origin:
            continue

        origin_row = module_rows_by_name.get(origin)
        if not origin_row:
            # Try package (__init__.py) for the origin
            alt_origin = origin + ".__init__"
            origin_row = module_rows_by_name.get(alt_origin)
            if not origin_row:
                continue

        names = sorted(_public_names_from_row(origin_row))
        if not names:
            continue
        resolved[origin] = names
        for n in names:
            # Don't clobber local defs if present
            if any(d.get("name") == n for d in row.get("defs", [])):
                continue
            reexports.setdefault(n, {"from": origin, "symbol": f"{origin}.{n}"})
    return resolved, reexports


# ---------- Top-level API ----------

def stitch_records(
    rows: List[Dict[str, Any]],
    scip_index: Optional[SCIPIndex] = None,  # reserved for future use
) -> List[Dict[str, Any]]:
    """
    Mutate/extend rows with:
      - exports_resolved, reexports
      - fan_in, fan_out, cycle_group
    """
    # 1) Graph metrics
    graph = _build_import_graph(rows)
    scc = _tarjan_scc(graph.out_edges.keys(), graph.out_edges)

    # 2) Exports & re-exports
    by_name = _module_record_by_name(rows)

    enriched: List[Dict[str, Any]] = []
    for r in rows:
        exports_resolved, reexports = _resolve_star_imports_for_row(r, by_name)
        r2 = dict(r)  # shallow copy
        r2["fan_in"] = len(graph.in_edges.get(r["path"], ()))
        r2["fan_out"] = len(graph.out_edges.get(r["path"], ()))
        r2["cycle_group"] = scc.get(r["path"], -1)
        if exports_resolved:
            r2["exports_resolved"] = {k: sorted(v) for k, v in exports_resolved.items()}
        if reexports:
            r2["reexports"] = dict(sorted(reexports.items()))
        enriched.append(r2)
    return enriched
```

**Notes**

* For **star‑imports**, we first try to resolve the origin module, accounting for relative imports using the importing module’s dotted name. We prefer the origin module’s `__all__`, falling back to its top‑level defs. That’s consistent with your overlay sidecar writer, which already emits these same data points (`has_all`, `defs`) — just without generating stubs now. 
* Graph metrics are purely intra‑repo: we keep edges whose dotted module starts with the repo’s top‑level package (e.g., `codeintel_rev`).
* The SCC id (`cycle_group`) is a compact way to annotate cycles.

---

## 2) Minimal patch to `cli_enrich.py`

Add an import and a call to `stitch_records` right before writing the final artifacts.

```python
# near the top
from .enrich.stitch import stitch_records
```

…and replace the final write block with:

```python
    # ---- NEW: stitch/augment the per-module rows before writing ----
    module_rows = stitch_records(module_rows, scip_index)

    # Write repo-level artifacts (unchanged)
    write_jsonl(out / "modules" / "modules.jsonl", module_rows)
    write_json(out / "graphs" / "symbol_graph.json", [{"symbol": symbol, "file": rel} for symbol, rel in symbol_edges])
    write_json(out / "repo_map.json", {
        "root": str(root),
        "module_count": len(module_rows),
        "symbol_edge_count": len(symbol_edges),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tags": tag_index,
    })
```

This integrates cleanly with the CLI you already have (iterating `_iter_files`, building LibCST, Tree‑sitter outlines, and type signal summaries) and extends each row with `exports_resolved`, `reexports`, `fan_in`, `fan_out`, `cycle_group`. 

---

## 3) (Optional) One screenful update to `write_markdown_module`

If you want the Markdown pages to show the new fields, add a few lines in your `write_markdown_module` implementation to render sections:

````python
def write_markdown_module(path: Path, record: dict) -> None:
    lines = []
    lines.append(f"# {record['path']}\n")

    if record.get("docstring"):
        lines.append("## Docstring\n")
        lines.append("```text\n" + record["docstring"].strip() + "\n```\n")

    lines.append("## Graph\n")
    lines.append(f"- **fan_in**: {record.get('fan_in', 0)}")
    lines.append(f"- **fan_out**: {record.get('fan_out', 0)}")
    lines.append(f"- **cycle_group**: {record.get('cycle_group', -1)}\n")

    if record.get("exports"):
        lines.append("## Declared Exports (__all__)\n")
        lines.append(", ".join(sorted(record["exports"])) + "\n")

    if record.get("exports_resolved"):
        lines.append("## Resolved Star Imports\n")
        for origin, names in sorted(record["exports_resolved"].items()):
            lines.append(f"- **from {origin}**: {', '.join(names)}")
        lines.append("")

    if record.get("reexports"):
        lines.append("## Re-exports\n")
        for name, meta in sorted(record["reexports"].items()):
            lines.append(f"- `{name}` ← **{meta['from']}** ({meta['symbol']})")
        lines.append("")

    # ... existing sections for imports/defs/outline/tags/type_errors ...
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
````

Your `output_writers` module already centralizes JSON and Markdown emission, so this is a localized enhancement. 

---

## 4) What “good” looks like for your artifacts (quick checks)

Use the checklist below to sanity‑check the new, stitched output:

1. **`modules.jsonl`** rows now have the extra keys (`fan_in`, `fan_out`, `cycle_group`), and (only when applicable) `exports_resolved` + `reexports`. The base fields should remain intact (path, docstring, imports, defs, exports, outline_nodes, scip_symbols, parse_ok, errors, tags, type_errors). 
2. **`repo_map.json`** reflects the same module count as the number of JSONL lines; `symbol_edge_count` didn’t change (we didn’t alter symbol edges in this patch). 
3. **`symbol_graph.json`** remains a flat list of `{symbol, file}` objects—unchanged by stitching. 
4. **No new type errors**—we are not generating overlays or editing code, only enriching metadata. Your Pyright/Pyrefly configs remain in effect; the CLI just *reads* their summaries via `type_integration.py`. 

---

## 5) Why this meets the “next step” goals

* **A. Public API & Re‑exports.** You’ll see explicit, materialized names for star‑imports and re‑exports, per module, which LLM agents can rely on directly. This fulfills the “easy win” we outlined earlier. 
* **B. Import graph insights.** We add `fan_in`, `fan_out`, and `cycle_group` using a fast built‑in SCC pass so agents and reviewers can spot risk and cycles at a glance.
* **C. Ready to layer symbol‑use analytics.** We didn’t change your SCIP ingestion; you can now add a follow‑up `uses_builder.py` to compute “used_by_files” counts per module using SCIP `occurrences` without changing any schema we introduced here. The CLI already emits the simple symbol→file edges; we can expand that to defs→refs in a small next patch. 

---

## 6) A note on overlays and type checkers

It’s correct that removing the global overlays fixed the explosion of Pyright errors — Pyright/pyrefly prefer `.pyi` over `.py` when both exist, so “skeletal” global stubs will hide rich definitions. If you reintroduce overlays, do it only for modules tagged by policy (e.g., `overlay-needed`) and keep them **sparse and precise**. The current writer for stub sidecars already captures what agents need to review before we ever write a `.pyi`. 

Your environment and configs (tooling, indexes, and strictness settings) already align with this approach.

---

### TL;DR

* Yes — the outputs you attached are what I’d expect at this phase, and they’re a solid basis for the enrichment we planned.
* Drop in `stitch.py` above and add the 1‑line call in `cli_enrich.py`.
* You’ll immediately get per‑module `exports_resolved`, `reexports`, and import graph metrics — the foundation the next stages (symbol uses, coverage joins, doc parity, hotspots) will build on.

If you’d like, I can follow up with a second patch that adds `uses_builder.py` (defs↔refs from SCIP), and a small expansion in the Markdown writer to show “Used by N files / symbols” and “Nearest tests,” continuing from this stitched baseline.
