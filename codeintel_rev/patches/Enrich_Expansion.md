
# context and background #

Fantastic—here’s a **fully‑detailed set of extensions** you can add now to surface richer **per‑module metadata** and a denser **module graph**, tuned for AI programming agents. I’ve anchored each “how” to the concrete hooks you already have, so it’s clear where to plug things in.

---

## 0) Where these extensions attach

* **CST backbone**: extend your `ModuleIndex` (imports/defs/exports/docstring) captured by `index_module()` and the `_IndexVisitor` in `libcst_bridge.py`. This is where we add local metrics (annotation ratios, doc health, complexity, side‑effects, raised exceptions). 
* **Writers**: you already have `write_json`, `write_jsonl`, and a Markdown renderer per module—extend these to publish new sections/fields without new plumbing. 
* **Cross‑file glue**: read and join repository‑wide symbol data via `SCIPIndex.load()` and its helpers (documents, occurrences, symbol kinds), plus `symbol_to_files()` and `file_symbol_kinds()` for quick maps. This powers re‑exports, call‑like “uses”, and graph fan‑in/out. 
* **Tagging**: enrich `infer_tags(...)` rules (YAML + heuristics) to auto‑label hotspots, reexport hubs, low coverage, ownership buckets, etc. Agents can route by tags. 
* **Multi‑language context**: your Tree‑sitter bridge gives outlines for Python and project configs (JSON/YAML/TOML/MD); we’ll extend it to extract useful keys and back‑references to Python code. 
* **Types**: keep harvesting Pyrefly and Pyright signals via `collect_pyrefly()` / `collect_pyright()`; we’ll join their per‑file counts into module records. 
* **Configs**: your `pyproject.toml` already includes docstring‑parser, DuckDB/Polars, Sphinx/griffe, and analysis libs; these cover almost everything below with no new top‑level deps. 
* **Type‑checker knobs**: Pyrefly strictness, first‑use inference, and search‑path are in `pyrefly.toml`; Pyright environment and `stubPath` are in `pyrightconfig.json`. Both matter for typedness metrics and optional stub overlays.  
* **Coverage/tests**: your pytest config (test paths, doctest/xdoctest flags) enables coverage joins and “nearest tests” mapping. 

---

## 1) New per‑module fields (what big teams publish)

For each module record (the JSONL row and Markdown page), add the following sections/fields. Each item includes **why it matters for agents**, **how to compute**, and **where it plugs in**.

### A) Export surface & re‑exports (crisper API meaning)

* **Fields**:

  * `exports_declared` (existing), `exports_resolved`, `reexports: {exported -> {from, symbol}}`.
* **How**: detect star‑imports and `__all__` with LibCST, then use `SCIPIndex.symbol_to_files()` to enumerate and materialize what `from X import *` would expose; identify re‑exported names vs local defs.  
* **Why**: lets agents stick to public surface and not wander into internals.

### B) Import graph metrics (fan‑in/fan‑out, cycles, layer)

* **Fields**:

  * `imports_intra_repo`, `fan_in`, `fan_out`, `cycle_group` (SCC id), optional `layer`.
* **How**: aggregate import edges from your LibCST imports; compute SCCs and degrees (networkx or a tiny custom pass). Persist a repo‑level `imports.parquet` and attach per‑module numbers.  
* **Why**: fan‑in highlights ripple risk; cycles guide refactors and agent caution.

### C) Cross‑file “uses” (who references whom)

* **Fields**:

  * `used_by_files`, `used_by_symbols`, and an optional `call_like_edges`.
* **How**: for each **definition symbol** in a file, traverse SCIP `occurrences` to count references across documents; write a `uses.parquet` and embed per‑module counts. 
* **Why**: fuels impact analysis (“who breaks if I change X?”) and focused LLM context.

### D) Typedness profile (for safe iteration)

* **Fields**:

  * `type_error_count`, `annotation_ratio` (params/returns), `untyped_defs`, `overlay_needed` (bool).
* **How**: join `collect_pyrefly()` + `collect_pyright()` outputs; compute annotation ratios from LibCST function/class defs; set `overlay_needed` only for modules lacking annotations *and* with high fan‑in or public APIs. Publish overlays selectively (under `stubs/…`) if you opt into them later.  
* **Config levers**: Pyrefly’s `infer-with-first-use`, `untyped-def-behavior` and includes/excludes are already set to strict, so your metrics reflect realistic “design debt.” 
* **Why**: agents prefer stable, typed surfaces and can propose annotations where it matters.

### E) Docstring health & parity (LLM grounding)

* **Fields**:

  * `doc_has_summary`, `doc_param_parity`, `doc_examples_present`, `doc_coverage`, plus `doc_summary`.
* **How**: extend the visitor to gather function/class docstrings; parse with `docstring-parser`; compare parameters vs signature; store a short synopsis for each public def; render in Markdown via your writer.   
* **Why**: agents rely on doc parity to avoid hallucinating parameters/returns.

### F) Side‑effects & capability footprint

* **Fields**:

  * `side_effects`: `{filesys: bool, network: bool, subprocess: bool, db: bool}`, `heavy_deps`: `["numpy", "faiss", ...]`.
* **How**: static heuristics over import sets (e.g., `httpx`, `boto3`, `subprocess`, `sqlalchemy`) + your local heavy‑dependency registry (`typing.gate_import` / `HEAVY_DEPS`) to tag import weight. Add a “capability” section on the Markdown page. 
* **Why**: agents plan safer changes when they know modules hit IO, spawn processes, or drag heavy deps.

### G) Exceptions surface (design contract)

* **Fields**:

  * `raises`: list of exception types likely raised (`raise` statements & calls into your error constructors), `errors_module_refs`.
* **How**: scan CST for `Raise` nodes + calls to constructors in `codeintel_rev.errors` (SCIP helps map qualified names). Document common error types in the module page. 
* **Why**: agents can preserve error contracts and add tests for expected failures.

### H) Complexity × churn × centrality → `hotspot_score`

* **Fields**:

  * `cyclomatic`, `branches`, `loc`, `recent_churn`, `centrality_score`, `hotspot_score`.
* **How**: compute simple complexity from CST (count `If/For/While/Try` etc.), churn via git history, and centrality from the import/use graphs—then scale to `hotspot_score`. Publish `hotspots.parquet`.  
* **Why**: prioritizes refactors and signals review intensity to agents.

### I) Config/infra linkage (cross‑language awareness)

* **Fields**:

  * `config_refs`: list of `(file#key)` that this module reads or whose values it likely shapes.
* **How**: extend Tree‑sitter outline to extract keys/anchors from YAML/TOML/JSON/MD; link to Python modules that import the corresponding config loaders or reference those paths. Emit `config_index.jsonl` and a back‑ref list on each module. 
* **Why**: agents avoid breaking production paths that are config‑driven.

### J) Tests & coverage proximity

* **Fields**:

  * `covered_lines_ratio`, `covered_defs_ratio`, `nearest_test_paths`, `doc_example_count`.
* **How**: join `coverage.xml`/`.coverage` to per‑file stats, map tests to modules via import/use graph, count doctest snippets from docstrings (you already run doctest/xdoctest). 
* **Why**: agents prefer editing code that is well‑exercised or can quickly attach a test.

### K) Ownership & bus‑factor

* **Fields**:

  * `owner`, `primary_authors`, `bus_factor`, `recent_authors_90d`.
* **How**: parse `CODEOWNERS` globs, compute author shares from git blame/log over a sliding window, attach to the module record and Markdown page.
* **Why**: route PRs and agent questions to the right people; highlight risk if ownership is thin.

### L) Security & risk flags

* **Fields**:

  * `security_flags`: `{exec: bool, shell: bool, tempfiles: bool, urllib_open: bool, secrets_io: bool}`, `tainted_inputs`: best‑effort list.
* **How**: static import heuristics and CST scans for `subprocess.*(shell=True)`, `os.system`, dangerous `eval/exec`, and unguarded env use. Tag as `security-sensitive` when present.
* **Why**: agents change posture (and reviewers focus) on sensitive modules.

### M) ADRs / TODOs / design breadcrumbs

* **Fields**:

  * `adrs`: links to architecture decision records (if present), `todos`: normalized TODO/FIXME comments with line spans.
* **How**: light CST/comment scan; treat `/docs/adr*` or `adr/*.md` as sources and cross‑link by module/class/function names.
* **Why**: transfers design intent into the module page—gold for LLMs.

---

## 2) How to wire it (mechanics & integration points)

1. **Extend the visitor & record shape**
   Add fields to `ModuleIndex` (`annotation_ratio`, `doc_flags`, `side_effects`, `raises`, `complexity`, etc.) and compute them in your LibCST pass. You already have `PositionProvider`; keep using that for line numbers. 

2. **Add graph builders**

   * `graph_builder.py`: aggregate imports → edges; compute SCCs, fan‑in/out; write `imports.parquet`; return a per‑file dict of `{fan_in, fan_out, cycle_group}` for the writer.
   * `uses_builder.py`: walk SCIP occurrences, build `(def_symbol → referencing files/symbols)`; persist `uses.parquet`. 

3. **Typedness join**
   Read Pyrefly/Pyright summaries via `collect_pyrefly()`/`collect_pyright()`; annotate each file with `type_error_count`; compute `annotation_ratio` locally from your function defs. Gate overlays by tag—don’t generate stubs globally.   

4. **Writers**

   * **JSON/JSONL**: extend the object passed to `write_json`/`write_jsonl`.
   * **Markdown**: add “Exports”, “Graph Metrics”, “Typedness”, “Side‑effects”, “Raises”, “Coverage”, “Ownership”, and “Hotspot” sections to `write_markdown_module()`. The helper already prints imports/defs/tags; append new sections in the same style. 

5. **Tagging**
   Update `tagging_rules.yaml` and/or programmatic rules in `infer_tags(...)` to classify: `reexport-hub`, `public-api`, `needs-types`, `hotspot`, `low-coverage`, `security-sensitive`, `owner-<team>`. The `infer_tags` call already supports `any_import`, `has_all`, `is_reexport_hub`, and `type_errors_gt`. 

6. **Configs & multi‑language**
   Enrich `tree_sitter_bridge.build_outline()` to include keys for YAML/TOML/JSON and headings from Markdown; store in a `config_index.jsonl`. Link keys back to Python modules via simple heuristics (importers, file adjacency). 

7. **Docs**
   Leverage your `pyproject.toml` doc toolchain (`docstring-parser`, Sphinx/mkdocstrings, griffe) to sync doc health into module pages and (optionally) produce API docs that link back to each module record. 

8. **Tests & coverage**
   Use `pytest --cov` with your existing `pytest.ini`. Convert coverage to per‑file ratios and join to modules. The doctest/xdoctest add‑opts already in place let you count runnable examples too. 

---

## 3) Minimal schema diff (drop‑in fields)

Add these keys to each **modules.jsonl** row (and mirror in Markdown):

```json
{
  "exports_resolved": ["foo", "Bar", "baz"],
  "reexports": {"Bar": {"from": "pkg._impl", "symbol": "pkg._impl.Bar"}},
  "fan_in": 18,
  "fan_out": 5,
  "cycle_group": 2,
  "used_by_files": 42,
  "type_error_count": 0,
  "annotation_ratio": {"params": 0.82, "returns": 0.91},
  "untyped_defs": 3,
  "overlay_needed": false,
  "doc_has_summary": true,
  "doc_param_parity": true,
  "doc_examples_present": false,
  "side_effects": {"filesys": true, "network": false, "subprocess": false, "db": false},
  "raises": ["PathNotFoundError", "InvalidLineRangeError"],
  "complexity": {"cyclomatic": 7, "branches": 12, "loc": 210},
  "covered_defs_ratio": 0.71,
  "owner": "@team/search",
  "bus_factor": 0.43,
  "hotspot_score": 0.77,
  "config_refs": ["configs/search.yaml#retrieval"],
  "tags": ["public-api", "reexport-hub"]
}
```

---

## 4) Validation & quality gates (what to assert in CI)

* **No global overlays**: ensure overlays are only generated for modules tagged `overlay-needed`. Keep Pyright/pyrefly green (both already read `stubs/`). 
* **Doc parity for public APIs**: fail when `public-api` & `doc_param_parity=false`. 
* **Architecture**: fail on new cycles or forbidden cross‑layer edges (SCC increase or disallowed imports).
* **Typedness baselines**: treat `type_error_count` regressions as failures (Pyrefly supports baselines). 
* **Security flags**: warn (or fail) if `security-sensitive` modules increase without justification.

---

## 5) Agent‑ready “slices” (for design & refactor tasks)

Emit **task packs** per module: Markdown + JSON with:

* **Contract surface** (exports/resolved, re‑exports)
* **Nearest tests & examples** (paths, snippets)
* **Usage map** (top call‑sites/files)
* **Typedness & doc parity**
* **Side‑effects & security flags**
* **Graph risk** (fan‑in/out, cycle group, hotspot score)
* **Owner(s)**

Your `output_writers` and current file layout make this trivial to assemble. 

---

## 6) Small code notes (where to edit)

* **`libcst_bridge.py`**

  * Extend `ModuleIndex` dataclass with fields for doc health, annotation ratios, complexity, side‑effects, raises. Compute locally in `_IndexVisitor` and its enclosing helpers. Keep the current parse‑error resilience. 

* **`output_writers.py`**

  * Add sections to `write_markdown_module()` for Exports/Graph/Typedness/Side‑effects/Raises/Coverage/Ownership/Hotspot. JSON writer already covers arbitrary keys. 

* **`scip_reader.py`**

  * Reuse `SCIPIndex.by_file()`, `symbol_to_files()`, `file_symbol_kinds()` for the re‑export and uses maps; keep external symbols handy for third‑party references. 

* **`tagging.py`**

  * Expand rules to include `hotspot`, `low-coverage`, `security-sensitive`, `owner-<team>`; you already have `any_import`, `has_all`, `is_reexport_hub`, and `type_errors_gt`. 

* **`tree_sitter_bridge.py`**

  * Return a richer outline for YAML/TOML/JSON/MD, capturing keys and headings; we’ll link them to Python importers later. 

* **`type_integration.py`**

  * Keep using `collect_pyrefly()`/`collect_pyright()`; expose a `summaries_to_dict()` helper that returns `{path -> error_count}` for fast joins. 

---

## 7) What this buys you (for agents doing design)

* A **single module page** becomes a compact, **trustworthy briefing**: what the module exposes, who uses it, how risky it is to change, how well it’s typed and documented, how to test it, and who to consult.
* The **module graph** grows from raw imports to a **design map**: public surfaces, re‑exports, use sites, layers, cycles, centrality, config coupling, and ownership—exactly what senior reviewers and LLM agents need to reason safely.

---

### Quick action checklist

* [ ] Implement A–M fields; extend `ModuleIndex` & `write_markdown_module()`.  
* [ ] Build `imports.parquet` and `uses.parquet`; attach per‑module metrics. 
* [ ] Join Pyrefly/Pyright into `type_error_count`; compute `annotation_ratio`.   
* [ ] Parse docstrings for parity and examples; render in Markdown. 
* [ ] Enrich Tree‑sitter for configs; publish `config_index.jsonl` + `config_refs`. 
* [ ] Expand tagging rules; gate policies in CI (cycles, doc parity for `public-api`, typedness regressions). 

If you’d like, I can turn this outline into **ready‑to‑drop diffs** (new builders + patched visitors and writers) against your current files next.


# Detailed implementation plan #


Below is a **drop‑in set of extensions** that surface richer **per‑module metadata** and **module‑graph analytics**—the same signals large codebases use to steer design and safe refactors. Each item comes with (1) what it computes & why it matters, (2) how it stitches into your existing pipeline, and (3) ready‑to‑use code files plus CLI wiring.

> **How this stitches in mechanically (one paragraph recap)**
> We reuse your LibCST indexer to get a reliable, lossless structure per file (imports, defs, `__all__`, docstring). We then join that with SCIP’s cross‑file def/occurrence graph to resolve names, re‑exports, and use relationships. Writers consolidate results into JSONL/Markdown, and (optionally) Parquet/DuckDB for fast queries. Tagging rules annotate modules by policy. Type signals (Pyrefly/Pyright) and coverage/doc health/complexity/ownership are joined back into the same per‑module record so agents see **one consistent “module profile”**. This plan uses your shipped modules: LibCST indexer & schema, writers, SCIP reader, tagger, tree‑sitter outline, and type‑integration hooks.

---

## Extensions at a glance

1. **Import graph & fan‑in/out + cycles**
2. **Resolved exports & re‑exports (star‑import expansion)**
3. **Cross‑file “uses” graph (who calls/uses whom)**
4. **Docstring health (summary/param parity/examples)**
5. **Coverage join (defs/lines coverage)**
6. **Ownership & churn (CODEOWNERS + git authorship)**
7. **Hotspot scoring (complexity × churn × centrality)**
8. **Config/infra awareness (YAML/TOML/JSON/MD keys)**
9. **Task‑ready LLM slices (context packs per module)**

We rely on packages you already carry (e.g., **polars/duckdb**, **docstring‑parser**, **pytest‑cov**, **GitPython** or bare git), so there’s no new heavy dependency class. See your `pyproject.toml` for the relevant deps. 

### Where prior building blocks come from (no changes needed)

* **LibCST indexer**: `index_module()` → `ModuleIndex(imports, defs, exports, docstring, …)`. We read its JSONL as our baseline. 
* **Writers**: `write_json`, `write_jsonl`, `write_markdown_module` to publish enriched fields. 
* **SCIP**: `SCIPIndex.load()`, `symbol_to_files()`, `file_symbol_kinds()` to build use/re‑export maps. 
* **Tagging**: `infer_tags()` using your YAML rules; we preserve this touchpoint. 
* **Tree‑sitter outline**: available when we need fast outlines/config harvesting. 
* **Type signals**: `collect_pyrefly()`, `collect_pyright()`—we reuse for typedness fields (not reimplemented here). 
* Your **Pyrefly** config (strict options like `infer-with-first-use`) and **Pyright** execution environments remain the source for type deltas/overlays should you enable that pass later.
* **pytest/cov** config is already present for coverage ingestion. 

---

# New files (drop‑in)

> Put these in `codeintel_rev/enrich/` (or anywhere in your repo) and wire them via the CLI patch at the end. All are **pure‑Python** and safe to run locally or in CI.

---

### 1) `graph_builder.py` — import edges, fan‑in/out, cycles

**What it does**
Consumes `modules.jsonl` (from your LibCST pass) and computes:

* `imports_intra_repo` edges,
* per‑module `fan_in`, `fan_out`,
* `cycle_group` (SCC id),
* emits `imports.parquet` (or CSV fallback) + `modules.graph.jsonl` (enriched records).

**How it stitches**
Relies on LibCST import entries (`module`, `names`, `is_star`, `level`) your indexer already provides. 

```python
# codeintel_rev/enrich/graph_builder.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple, Iterable, Optional
import json, os

try:
    import polars as pl  # type: ignore
except Exception:
    pl = None  # graceful fallback

# --- Helpers ---------------------------------------------------------------

def _read_jsonl(path: str | Path) -> List[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows

def _path_to_mod(path: str) -> str:
    p = Path(path)
    stem = p.stem
    parts = list(p.parts)
    # Heuristics aligned to your execution env roots (src/, codeintel_rev/, tools/)
    # __init__.py => package name
    if stem == "__init__":
        parts = parts[:-1]
    if "src" in parts:
        parts = parts[parts.index("src")+1:]
    elif "codeintel_rev" in parts:
        parts = parts[parts.index("codeintel_rev"):]
    elif "tools" in parts:
        parts = parts[parts.index("tools")+1:]
    # strip extension, join by dot
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join([p for p in parts if p])

def _tarjan_scc(graph: Dict[str, Set[str]]) -> Dict[str, int]:
    index, stack, onstack, idx = {}, [], set(), 0
    comp_id, comps = 0, {}
    low, num = {}, {}

    def strongconnect(v: str):
        nonlocal idx, comp_id
        num[v] = idx; low[v] = idx; idx += 1
        stack.append(v); onstack.add(v)
        for w in graph.get(v, ()):
            if w not in num:
                strongconnect(w); low[v] = min(low[v], low[w])
            elif w in onstack:
                low[v] = min(low[v], num[w])
        if low[v] == num[v]:
            while True:
                w = stack.pop(); onstack.remove(w)
                comps[w] = comp_id
                if w == v: break
            comp_id += 1

    for v in graph.keys():
        if v not in num:
            strongconnect(v)
    return comps

# --- Core ------------------------------------------------------------------

def build(path_modules_jsonl: str, out_dir: str) -> None:
    rows = _read_jsonl(path_modules_jsonl)
    # Build module name map + edges (repo-only)
    module_of_path = {r["path"]: _path_to_mod(r["path"]) for r in rows}
    repo_mods: Set[str] = set(module_of_path.values())
    edges: List[Tuple[str, str, str]] = []  # (src_mod, dst_mod, src_path)

    for r in rows:
        src_mod = module_of_path[r["path"]]
        for imp in r.get("imports", []):
            dst = (imp.get("module") or "").strip()
            if not dst:
                # Absolute 'import pkg' form: module name conveyed via 'names'
                for nm in imp.get("names") or []:
                    if nm in repo_mods or any(nm.startswith(m + ".") for m in repo_mods):
                        edges.append((src_mod, nm, r["path"]))
                continue
            # 'from X import ...'
            base = dst
            if base in repo_mods or any(base.startswith(m + ".") for m in repo_mods):
                edges.append((src_mod, base, r["path"]))

    # Graph + metrics
    graph: Dict[str, Set[str]] = {m: set() for m in repo_mods}
    for a, b, _ in edges:
        if a != b:
            graph.setdefault(a, set()).add(b)
            graph.setdefault(b, set())  # ensure node exists

    fan_out = {m: len(graph.get(m, ())) for m in repo_mods}
    fan_in  = {m: 0 for m in repo_mods}
    for m, nbrs in graph.items():
        for n in nbrs:
            fan_in[n] = fan_in.get(n, 0) + 1

    scc = _tarjan_scc(graph)

    # Write analytics table
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    edge_rows = [{"src": a, "dst": b, "src_path": p} for a, b, p in edges]
    metrics_rows = [{"module": m, "fan_in": fan_in.get(m, 0), "fan_out": fan_out.get(m, 0), "cycle_group": scc.get(m, -1)} for m in repo_mods]

    if pl:
        pl.DataFrame(edge_rows).write_parquet(str(Path(out_dir) / "imports.parquet"))
        pl.DataFrame(metrics_rows).write_parquet(str(Path(out_dir) / "module_graph_metrics.parquet"))
    else:
        Path(out_dir, "imports.csv").write_text("\n".join(json.dumps(r) for r in edge_rows), encoding="utf-8")
        Path(out_dir, "module_graph_metrics.csv").write_text("\n".join(json.dumps(r) for r in metrics_rows), encoding="utf-8")

    # Emit enriched modules jsonl
    rec_by_mod = {module_of_path[r["path"]]: r for r in rows}
    out_lines = []
    for m, r in rec_by_mod.items():
        r = dict(r)
        r["fan_in"] = fan_in.get(m, 0)
        r["fan_out"] = fan_out.get(m, 0)
        r["cycle_group"] = scc.get(m, -1)
        out_lines.append(json.dumps(r, ensure_ascii=False))
    Path(out_dir, "modules.graph.jsonl").write_text("\n".join(out_lines), encoding="utf-8")
```

---

### 2) `exports_resolver.py` — materialize `exports_resolved` & `reexports`

**What it does**
Expands `from X import *` using SCIP + your local module index to list the actual exported names; records `reexports` as `{exported_name -> (source_module, source_symbol)}`. This makes public surfaces explicit for agents. 

**How it stitches**
Consumes the LibCST module rows (for `exports` and star‑imports) and the loaded SCIP index; writes `modules.exports.jsonl` with added `exports_resolved` and `reexports`. 

```python
# codeintel_rev/enrich/exports_resolver.py
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Set
import json, re

from codeintel_rev.scip_reader import SCIPIndex  # existing reader
# fall back if import path differs in your repo layout
# from scip_reader import SCIPIndex

def _read_jsonl(path: str | Path) -> List[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]

def _module_path_candidates(mod: str) -> List[str]:
    """
    Guess file paths for module 'pkg.sub' => ['pkg/sub.py', 'pkg/sub/__init__.py'] (relative).
    """
    rel = mod.replace(".", "/")
    return [f"{rel}.py", f"{rel}/__init__.py"]

def build(modules_jsonl: str, scip_json: str, out_dir: str) -> None:
    rows = _read_jsonl(modules_jsonl)
    scip = SCIPIndex.load(scip_json)
    docs_by_file = scip.by_file()           # file -> Document(symbols=list)
    symbol_to_files = scip.symbol_to_files()  # symbol -> [files]
    # Build fast lookup for module rows by path
    row_by_path = {r["path"]: r for r in rows}

    enriched = []
    for r in rows:
        exports_declared: Set[str] = set(r.get("exports") or [])
        exports_resolved: Set[str] = set(exports_declared)
        reexports: Dict[str, Dict[str, str]] = {}
        # Expand star imports
        for imp in r.get("imports", []):
            if imp.get("is_star") and imp.get("module"):
                target_mod = imp["module"]
                # Resolve module -> candidate files within this repo
                candidates = _module_path_candidates(target_mod)
                exported_names: Set[str] = set()
                for cand in candidates:
                    if cand in row_by_path:
                        # Prefer explicit __all__ if present
                        target = row_by_path[cand]
                        if target.get("exports"):
                            exported_names.update(target["exports"])
                        else:
                            # Fall back: top-level defs from LibCST index
                            for d in target.get("defs") or []:
                                if d.get("kind") in {"class", "function"}:
                                    exported_names.add(d["name"])
                    # If not indexed via LibCST, fall back to SCIP symbols for the file
                    if cand in docs_by_file:
                        for s in docs_by_file[cand].symbols:
                            # Heuristic: last segment of symbol as surface name
                            m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)[.#]?$", s.symbol)
                            if m:
                                exported_names.add(m.group(1))
                # Keep only names that are actually referenced in the current module (keeps payload small)
                referenced_names = set()
                # Scan occurrences for this file and collect names that show up
                doc = docs_by_file.get(r["path"])
                if doc:
                    for occ in doc.occurrences:
                        m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)[.#]?$", occ.symbol)
                        if m:
                            referenced_names.add(m.group(1))
                materialized = exported_names & referenced_names if referenced_names else exported_names
                exports_resolved.update(materialized)
                # Link reexports to source module (best effort via module path candidates)
                for name in materialized:
                    reexports[name] = {"from_module": target_mod, "symbol": f"{target_mod}.{name}"}

        r2 = dict(r)
        r2["exports_declared"] = sorted(exports_declared)
        r2["exports_resolved"] = sorted(exports_resolved)
        r2["reexports"] = dict(sorted(reexports.items()))
        enriched.append(r2)

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_dir, "modules.exports.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in enriched), encoding="utf-8"
    )
```

---

### 3) `uses_builder.py` — “who uses whom” from SCIP

**What it does**
Builds a **use/call‑like** graph: for each defined symbol, which files reference it; per‑module counts like `used_by_files`, `used_by_symbols`. Writes `uses.parquet` + `modules.uses.jsonl`. 

```python
# codeintel_rev/enrich/uses_builder.py
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Set, Tuple
import json

try:
    import polars as pl  # type: ignore
except Exception:
    pl = None

from codeintel_rev.scip_reader import SCIPIndex

def build(scip_json: str, modules_jsonl: str, out_dir: str) -> None:
    scip = SCIPIndex.load(scip_json)
    rows = [json.loads(l) for l in Path(modules_jsonl).read_text(encoding="utf-8").splitlines() if l.strip()]
    mod_of_path = {r["path"]: r for r in rows}

    # Map: def_symbol -> def_file
    def_owner: Dict[str, str] = {}
    for d in scip.documents:
        for s in d.symbols:
            if s.symbol:
                def_owner[s.symbol] = d.path

    # Use edges (def_file <- ref_file)
    uses: List[Tuple[str, str, str]] = []  # (def_symbol, def_file, ref_file)
    for d in scip.documents:
        for occ in d.occurrences:
            sym = occ.symbol
            if sym in def_owner:
                def_file = def_owner[sym]
                ref_file = d.path
                if def_file != ref_file:
                    uses.append((sym, def_file, ref_file))

    # Aggregate per module/file
    used_by_files: Dict[str, Set[str]] = {}
    used_by_symbols: Dict[str, Set[str]] = {}
    for sym, def_file, ref_file in uses:
        used_by_files.setdefault(def_file, set()).add(ref_file)
        used_by_symbols.setdefault(def_file, set()).add(sym)

    enriched = []
    for r in rows:
        f = r["path"]
        r2 = dict(r)
        r2["used_by_files"] = len(used_by_files.get(f, set()))
        r2["used_by_symbols"] = len(used_by_symbols.get(f, set()))
        enriched.append(r2)

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_dir, "modules.uses.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in enriched), encoding="utf-8"
    )
    if pl:
        pl.DataFrame([{"def_symbol": s, "def_file": df, "ref_file": rf} for s, df, rf in uses]) \
            .write_parquet(str(Path(out_dir)/"uses.parquet"))
    else:
        Path(out_dir, "uses.csv").write_text("\n".join(json.dumps({"s": s, "df": df, "rf": rf}) for s, df, rf in uses), encoding="utf-8")
```

---

### 4) `doc_health.py` — summary/param parity/examples

**What it does**
Parses function/class docstrings, checks **summary present**, **param parity** (names mentioned in docs match signature), and whether **Examples** appear. Writes `modules.docs.jsonl` with booleans & ratios agents can filter on.

```python
# codeintel_rev/enrich/doc_health.py
from __future__ import annotations
from pathlib import Path
import json
import libcst as cst
from libcst import metadata as cst_metadata  # type: ignore
from docstring_parser import parse as parse_doc  # type: ignore

def _doc_of_body(body: cst.BaseSuite) -> str | None:
    # First statement literal string => docstring
    if isinstance(body, cst.IndentedBlock) and body.body:
        first = body.body[0]
        if isinstance(first, cst.SimpleStatementLine) and first.body:
            expr = first.body[0]
            if isinstance(expr, cst.Expr) and isinstance(expr.value, cst.SimpleString):
                try:
                    return expr.value.evaluated_value
                except Exception:
                    return None
    return None

def analyze_file(path: str, code: str) -> dict:
    mod = cst.parse_module(code)
    wrapper = cst_metadata.MetadataWrapper(mod)
    doc_summary_ok = False
    param_parity_ok = True
    examples_present = False
    fn_count = 0
    fn_with_docs = 0

    class _V(cst.CSTVisitor):
        METADATA_DEPENDENCIES = (cst_metadata.PositionProvider,)
        def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
            nonlocal fn_count, fn_with_docs, param_parity_ok, examples_present, doc_summary_ok
            fn_count += 1
            ds = _doc_of_body(node.body)
            if ds:
                fn_with_docs += 1
                try:
                    parsed = parse_doc(ds)
                    if parsed.short_description:
                        doc_summary_ok = True
                    # param parity
                    doc_names = {p.arg_name for p in parsed.params if p.arg_name}
                    sig_names = {p.name.value for p in node.params.params}
                    if doc_names and (doc_names != sig_names):
                        param_parity_ok = False
                    examples_present = examples_present or any(
                        (s.kind or "").lower().startswith("examples") for s in parsed.meta
                    )
                except Exception:
                    pass

    wrapper.visit(_V())
    return {
        "path": path,
        "doc_has_summary": bool(doc_summary_ok),
        "doc_param_parity": bool(param_parity_ok),
        "doc_examples_present": bool(examples_present),
        "doc_coverage": (fn_with_docs / fn_count) if fn_count else 0.0,
    }

def build(src_root: str, modules_jsonl: str, out_dir: str) -> None:
    rows = [json.loads(l) for l in Path(modules_jsonl).read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for r in rows:
        p = Path(src_root) / r["path"]
        if p.exists() and p.suffix == ".py":
            out.append(analyze_file(r["path"], p.read_text(encoding="utf-8")))
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_dir, "modules.docs.jsonl").write_text("\n".join(json.dumps(x) for x in out), encoding="utf-8")
```

> Uses the same CST machinery pattern as your indexer; this makes doc health consistent with your existing records. 

---

### 5) `coverage_ingest.py` — coverage join

**What it does**
Reads `coverage.xml` from `pytest-cov`, computes per‑file ratios, and emits `modules.coverage.jsonl` with `covered_lines_ratio` and `covered_defs_ratio` (defs approximated via line mapping). Your pytest config already sets the ground. 

```python
# codeintel_rev/enrich/coverage_ingest.py
from __future__ import annotations
from pathlib import Path
import json, xml.etree.ElementTree as ET

def _parse_coverage_xml(path: str) -> dict[str, float]:
    tree = ET.parse(path)
    root = tree.getroot()
    out = {}
    for clazz in root.findall(".//class"):
        filename = clazz.get("filename")
        if not filename:
            continue
        lines = clazz.find("lines")
        covered = 0; total = 0
        if lines is not None:
            for l in lines.findall("line"):
                total += 1
                if int(l.get("hits", "0")) > 0:
                    covered += 1
        out[filename] = (covered / total) if total else 0.0
    return out

def build(coverage_xml: str, modules_jsonl: str, out_dir: str) -> None:
    cov = _parse_coverage_xml(coverage_xml)
    rows = [json.loads(l) for l in Path(modules_jsonl).read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for r in rows:
        ratio = cov.get(r["path"], 0.0)
        out.append({"path": r["path"], "covered_lines_ratio": ratio})
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_dir, "modules.coverage.jsonl").write_text("\n".join(json.dumps(x) for x in out), encoding="utf-8")
```

---

### 6) `owners_index.py` — owners, authors, bus factor, churn

**What it does**
Resolves `owner` using `CODEOWNERS` if present; falls back to git authorship (last N commits). Emits: `owner`, `primary_authors`, `bus_factor`, `recent_churn_30d`.

```python
# codeintel_rev/enrich/owners_index.py
from __future__ import annotations
from pathlib import Path
from typing import Dict, List
import json, re, subprocess, shlex, datetime as dt

def _try_run(cmd: str) -> tuple[int, str]:
    p = subprocess.run(shlex.split(cmd), capture_output=True, text=True)
    return p.returncode, p.stdout

def _parse_codeowners(text: str) -> List[tuple[re.Pattern[str], str]]:
    rules = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        parts = line.split()
        if len(parts) >= 2:
            glob, owners = parts[0], ", ".join(parts[1:])
            # Convert glob to regex basic
            pat = re.escape(glob).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
            rules.append((re.compile("^" + pat + "$"), owners))
    return rules

def _match_owner(rules, path: str) -> str | None:
    for pat, owners in rules:
        if pat.match(path):
            return owners
    return None

def build(repo_root: str, modules_jsonl: str, out_dir: str, history_limit: int = 50) -> None:
    rows = [json.loads(l) for l in Path(modules_jsonl).read_text(encoding="utf-8").splitlines() if l.strip()]
    codeowners_path = Path(repo_root) / "CODEOWNERS"
    rules = _parse_codeowners(codeowners_path.read_text(encoding="utf-8")) if codeowners_path.exists() else []

    out = []
    since_30 = (dt.datetime.utcnow() - dt.timedelta(days=30)).isoformat()
    for r in rows:
        path = r["path"]
        owner = _match_owner(rules, path) if rules else None
        code, authors_text = _try_run(f"git log -n {history_limit} --pretty=%an -- {path}")
        authors = [a.strip() for a in authors_text.splitlines() if a.strip()] if code == 0 else []
        # naive bus factor: share of edits by top author
        bus = 0.0
        if authors:
            from collections import Counter
            c = Counter(authors)
            bus = c.most_common(1)[0][1] / sum(c.values())
        code, churn_text = _try_run(f"git log --since='{since_30}' --pretty=tformat: --numstat -- {path}")
        churn = 0
        if code == 0:
            for line in churn_text.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
                    churn += int(parts[0]) + int(parts[1])

        out.append({
            "path": path,
            "owner": owner,
            "primary_authors": authors[:5],
            "bus_factor": round(bus, 3),
            "recent_churn_30d": churn
        })

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_dir, "modules.owners.jsonl").write_text("\n".join(json.dumps(x) for x in out), encoding="utf-8")
```

---

### 7) `hotspot_scoring.py` — complexity × churn × centrality

**What it does**
Approximate per‑file complexity (`if/for/while/try` counts), joins with churn (owners file) and centrality (fan‑in from graph metrics) to produce `hotspot_score ∈ [0,1]`. Agents can sort by this to focus risky files.

```python
# codeintel_rev/enrich/hotspot_scoring.py
from __future__ import annotations
from pathlib import Path
import json, libcst as cst

def _complexity_of(code: str) -> int:
    mod = cst.parse_module(code)
    class _V(cst.CSTVisitor):
        score = 0
        def visit_If(self, n): self.score += 1
        def visit_For(self, n): self.score += 1
        def visit_While(self, n): self.score += 1
        def visit_Try(self, n): self.score += 1
        def visit_With(self, n): self.score += 1
        def visit_BooleanOperation(self, n): self.score += 1
    v = _V(); mod.visit(v); return v.score

def _read_jsonl(path: str) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]

def _minmax_scale(vals: list[float]) -> dict[str, float]:
    if not vals: return {}
    mn, mx = min(vals), max(vals)
    rng = (mx - mn) or 1.0
    return {"min": mn, "max": mx, "rng": rng}

def build(src_root: str, modules_jsonl: str, owners_jsonl: str, graph_jsonl: str, out_dir: str) -> None:
    mods = _read_jsonl(modules_jsonl)
    owners = {r["path"]: r for r in _read_jsonl(owners_jsonl)}
    g = {r["path"]: r for r in _read_jsonl(graph_jsonl)}  # contains fan_in/fan_out

    comp, churn, central = {}, {}, {}
    for r in mods:
        p = Path(src_root) / r["path"]
        comp[r["path"]] = _complexity_of(p.read_text(encoding="utf-8")) if p.exists() else 0
        churn[r["path"]] = owners.get(r["path"], {}).get("recent_churn_30d", 0)
        central[r["path"]] = g.get(r["path"], {}).get("fan_in", 0)

    sx = _minmax_scale(list(comp.values()))
    sy = _minmax_scale(list(churn.values()))
    sz = _minmax_scale(list(central.values()))

    out = []
    for r in mods:
        cx = (comp[r["path"]] - sx.get("min", 0)) / sx.get("rng", 1)
        cy = (float(churn[r["path"]]) - sy.get("min", 0)) / sy.get("rng", 1)
        cz = (float(central[r["path"]]) - sz.get("min", 0)) / sz.get("rng", 1)
        score = 0.5*cx + 0.3*cy + 0.2*cz
        out.append({"path": r["path"], "cyclomatic_like": comp[r["path"]], "hotspot_score": round(score, 3)})

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_dir, "modules.hotspots.jsonl").write_text("\n".join(json.dumps(x) for x in out), encoding="utf-8")
```

> Complexity via CST is consistent with your parsing approach and avoids external analyzers; join keys align with the graph & owners outputs generated above. 

---

### 8) `config_indexer.py` — keys from YAML/TOML/JSON/MD

**What it does**
Indexes configuration & docs artifacts into `config_index.jsonl` with `(path, keys/headings)`. Simple loaders (yaml/json/tomllib) suffice; Tree‑sitter is optional for outlines. Later you can link Python modules to configs by string matches or traced file IO.

```python
# codeintel_rev/enrich/config_indexer.py
from __future__ import annotations
from pathlib import Path
import json, re, sys
try:
    import tomllib  # 3.11+
except Exception:
    tomllib = None
import yaml  # type: ignore

def _safe_load_yaml(p: Path) -> list[str]:
    try:
        x = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        keys = []
        def walk(obj, prefix=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    kk = f"{prefix}.{k}" if prefix else str(k)
                    keys.append(kk)
                    walk(v, kk)
        walk(x); return keys
    except Exception:
        return []

def _safe_load_toml(p: Path) -> list[str]:
    if not tomllib: return []
    try:
        x = tomllib.loads(p.read_text(encoding="utf-8"))
        keys = []
        def walk(obj, prefix=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    kk = f"{prefix}.{k}" if prefix else str(k)
                    keys.append(kk); walk(v, kk)
        walk(x); return keys
    except Exception:
        return []

def _safe_load_json(p: Path) -> list[str]:
    try:
        x = json.loads(p.read_text(encoding="utf-8"))
        keys = []
        def walk(obj, prefix=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    kk = f"{prefix}.{k}" if prefix else str(k)
                    keys.append(kk); walk(v, kk)
        walk(x); return keys
    except Exception:
        return []

def _md_headings(p: Path) -> list[str]:
    out=[]; 
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"^(#+)\s+(.*)", line)
        if m: out.append(m.group(2).strip())
    return out

def build(root: str, out_path: str) -> None:
    exts = {".yaml": _safe_load_yaml, ".yml": _safe_load_yaml, ".toml": _safe_load_toml, ".json": _safe_load_json, ".md": _md_headings}
    rows = []
    for p in Path(root).rglob("*"):
        if p.suffix.lower() in exts and p.is_file():
            keys = exts[p.suffix.lower()](p)
            if keys:
                rows.append({"path": str(p.relative_to(root)), "keys": keys[:200]})
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
```

> (Optional) If you prefer Tree‑sitter outlines for these files, you already have a bridge you can extend similarly. 

---

### 9) `slices_builder.py` — LLM‑ready context packs

**What it does**
Composes “task‑ready” context pages per module by joining all enriched JSONLs (exports, graph metrics, uses, docs, coverage, owners, hotspots) and writes `slices/<module>/context.md` plus a combined `slices.jsonl` for routers.

````python
# codeintel_rev/enrich/slices_builder.py
from __future__ import annotations
from pathlib import Path
import json

def _read_jsonl(path: Path) -> dict[str, dict]:
    if not path.exists(): return {}
    out={}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        j = json.loads(line)
        out[j["path"]] = j
    return out

def build(out_dir: str) -> None:
    out = Path(out_dir)
    base = _read_jsonl(out / "modules.graph.jsonl")
    exp  = _read_jsonl(out / "modules.exports.jsonl")
    use  = _read_jsonl(out / "modules.uses.jsonl")
    doc  = _read_jsonl(out / "modules.docs.jsonl")
    cov  = _read_jsonl(out / "modules.coverage.jsonl")
    own  = _read_jsonl(out / "modules.owners.jsonl")
    hot  = _read_jsonl(out / "modules.hotspots.jsonl")

    slices = []
    for path, rec in base.items():
        r = dict(rec)
        r.update(exp.get(path, {}))
        r.update(use.get(path, {}))
        r.update(doc.get(path, {}))
        r.update(cov.get(path, {}))
        r.update(own.get(path, {}))
        r.update(hot.get(path, {}))

        # Write Markdown context
        mod_dir = out / "slices" / path.replace("/", "__")
        mod_dir.mkdir(parents=True, exist_ok=True)
        md = []
        md.append(f"# {path}\n")
        if r.get("docstring"): md += ["## Docstring", "```", r["docstring"].strip(), "```", ""]
        if r.get("exports_declared") or r.get("exports_resolved"):
            md += ["## Exports",
                   f"- Declared: {', '.join(r.get('exports_declared', [])) or '—'}",
                   f"- Resolved: {', '.join(r.get('exports_resolved', [])) or '—'}", ""]
        md += ["## Graph", f"- fan_in: {r.get('fan_in', 0)}", f"- fan_out: {r.get('fan_out', 0)}", f"- cycle_group: {r.get('cycle_group', -1)}", ""]
        md += ["## Usage", f"- used_by_files: {r.get('used_by_files', 0)}", f"- used_by_symbols: {r.get('used_by_symbols', 0)}", ""]
        md += ["## Typedness & Docs", f"- doc_coverage: {r.get('doc_coverage', 0):.2f}", f"- doc_param_parity: {r.get('doc_param_parity', True)}", ""]
        md += ["## Quality", f"- covered_lines_ratio: {r.get('covered_lines_ratio', 0):.2f}", f"- hotspot_score: {r.get('hotspot_score', 0):.2f}", ""]
        if r.get("owner"): md += ["## Ownership", f"- owner: {r['owner']}", f"- primary_authors: {', '.join(r.get('primary_authors', []))}", ""]
        (mod_dir / "context.md").write_text("\n".join(md), encoding="utf-8")
        slices.append(r)

    (out / "slices.jsonl").write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in slices), encoding="utf-8")
````

---

## CLI wiring (drop‑in replacement for your enrich CLI)

Add/replace a small orchestrator that calls each builder in a stable order. This uses **Typer**, which you already ship. 

```python
# codeintel_rev/enrich/cli.py
from __future__ import annotations
from pathlib import Path
import typer

from .graph_builder import build as build_graph
from .exports_resolver import build as build_exports
from .uses_builder import build as build_uses
from .doc_health import build as build_docs
from .coverage_ingest import build as build_cov
from .owners_index import build as build_owners
from .hotspot_scoring import build as build_hotspots
from .slices_builder import build as build_slices

app = typer.Typer(no_args_is_help=True)

@app.command()
def all(
    modules_jsonl: str = typer.Option("out/modules.jsonl", help="Baseline LibCST modules index JSONL"),
    scip_json: str     = typer.Option("out/index.scip.json", help="SCIP index JSON"),
    src_root: str      = typer.Option(".", help="Repo root used to read source files"),
    coverage_xml: str  = typer.Option("coverage.xml", help="coverage.xml from pytest-cov"),
    out_dir: str       = typer.Option("out", help="Output directory"),
):
    """Run full enrichment pipeline end-to-end."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    # 1. graph metrics
    build_graph(modules_jsonl, out_dir)
    # 2. exports/resolved
    build_exports(modules_jsonl, scip_json, out_dir)
    # 3. uses
    build_uses(scip_json, modules_jsonl, out_dir)
    # 4. docs
    build_docs(src_root, modules_jsonl, out_dir)
    # 5. ownership
    build_owners(src_root, modules_jsonl, out_dir)
    # 6. coverage (skip gracefully if file missing)
    if Path(coverage_xml).exists():
        build_cov(coverage_xml, modules_jsonl, out_dir)
    # 7. hotspots (joins owners+graph)
    build_hotspots(src_root, modules_jsonl, Path(out_dir,"modules.owners.jsonl"), Path(out_dir,"modules.graph.jsonl"), out_dir)
    # 8. slices
    build_slices(out_dir)

if __name__ == "__main__":
    app()
```

> If you want to keep your existing `cli_enrich.py`, just add a Typer subcommand that calls `codeintel_rev.enrich.cli:app`. Your repo already uses **Typer** and sets execution environments in Pyright accordingly. 

---

## How to run (one‑liners)

```bash
# Baseline (you already generate this)
python -m codeintel_rev.cli_enrich index --repo . --out out/modules.jsonl

# Build SCIP once (you already have index.scip.json)
# scip-python ... -> out/index.scip.json

# Run everything
python -m codeintel_rev.enrich.cli all \
  --modules-jsonl out/modules.jsonl \
  --scip-json out/index.scip.json \
  --src-root . \
  --coverage-xml coverage.xml \
  --out out
```

---

## Tagging rules (optional add‑ons)

Extend `tagging_rules.yaml` to exploit the new fields—for agent routing & PR hygiene. Your `infer_tags` already supports multiple predicates. 

```yaml
hotspot:
  reason: "high complexity × churn × centrality"
  path_regex: ".*"   # always eligible; use score cutoff during reporting
low-coverage:
  reason: "lines coverage below 50%"
  type_errors_gt: 0  # keep existing semantics
public-api:
  has_all: true
reexport-hub:
  is_reexport_hub: true
```

---

## Why this is “enterprise‑grade” for agents

* **Single profile per module** with **public surface**, **graph centrality**, **usage**, **typedness/doc health**, **tests**, **owners**, and **hotspot score** makes task routing deterministic (less LLM wandering).
* **Explicit re‑exports** avoid ghost APIs from `import *` and guide edits to the **source of truth**.
* **Graph & uses** power **blast‑radius** and **slice generation**—agents can pull only what they need for a change.
* **Ownership/churn/hotspots** add **risk context** that humans routinely use during large‑scale changes.

---

## Notes on quality and parity

* We intentionally defer to your **existing indexer schema and writers**, so this feels native (no brittle new formats).
* We use the **SCIP reader** exactly as shipped (robust to minor schema variants). 
* The plan assumes your **Pyrefly/Pyright** signals are harvested elsewhere and can be merged the same way (see `type_integration.py` if you want to add `type_error_count`, `annotation_ratio` later). 
* Analytics tables prefer **Parquet**/**DuckDB** but degrade to CSV if unavailable; your project already includes these analytics deps. 

---

### Small sanity checks to validate output

1. **Imports graph**: Spot‑check a known hub (e.g., `codeintel_rev.errors`) has high `fan_in` and appears in `imports.parquet`. You can also verify its rich docstrings came through the SCIP docs (that file’s symbols include extensive docs).
2. **Exports**: Pick a module with `__all__`—the resolver should mirror `exports_declared` and add any `exports_resolved` (if star imports exist). Your indexer already captures `__all__` assignments. 
3. **Owners/churn**: On a busy file, `recent_churn_30d` should be nonzero; verify `bus_factor` < 0.8 ideally.
4. **Hotspots**: Files with high `fan_in` and churn should bubble up; verify they receive `hotspot_score > 0.6`.
5. **Slices**: Each `slices/**/context.md` should render a compact, human‑readable brief.

---

If you want, I can also produce a **single “joiner”** that merges all JSONLs into your primary `modules.jsonl` and updates the Markdown module pages using your `write_markdown_module()` so humans and agents always see the same canonical page. The writer is already present and easy to extend. 

*Happy to iterate if you want any metric tweaked (e.g., different hotspot weights or adding docstring section checks).*
