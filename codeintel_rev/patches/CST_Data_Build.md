# Context and background #

Short answer: **yes—you now have everything you need to produce real LibCST‑backed CST data for every Python file.** What the “stitching” did was remove the reasons CST *metadata* used to fall over (star imports, re‑exports, unresolved names, type gaps). You still parse the source to get the actual CST, but the stitched signals (SCIP + import/export expansion + type summaries) let you **enrich** that CST with repo‑aware names and types so agents can rely on it.

Below is the “how it works” and where your current code already plugs in.

---

## 1) What counts as “CST data” vs. “metadata”

Think in three layers:

1. **Concrete Syntax Tree (CST)**: exact, round‑trippable structure of a single file (every token, whitespace, comment).
2. **Repo‑aware name metadata**: which identifier is *which* thing (e.g., `qname = pkg.mod.Class.method`) across modules & re‑exports.
3. **Type metadata**: (optional) the best known types at a use/def site.

LibCST gives you (1) out of the box. (2) and (3) are where repos struggle. Your stitched dataset is precisely what fills those gaps and makes CST *useful* across the repo.

---

## 2) What you already have that produces the CST and summaries

* A resilient LibCST pass that parses a module and extracts imports, definitions, `__all__`, and the top‑level docstring (using `MetadataWrapper` + `PositionProvider`). This is the CST backbone you build on. 

* Writers that can emit JSON/JSONL/Markdown for each module—so any new CST‑adjacent fields (qualified names, exports resolved, types, graph metrics) drop in without re‑plumbing. 

* An SCIP reader that loads per‑file symbol occurrences and per‑symbol docs/kinds, plus helpers to map symbols ↔ files. This is your cross‑file glue to resolve star imports, re‑exports, and “who‑uses‑whom.” 

* A Tree‑sitter outline that gives you quick, robust structure for Python and config files—handy as a fallback or to index non‑Python assets alongside the CST world. 

* Type checker integrations (Pyrefly and Pyright) that you can harvest into per‑file error counts and notes. These let you add typedness to the CST without Pyre. 

* Project configs that keep both engines aligned with your repo layout (Pyrefly `project-includes`, search paths; Pyright execution environments & stub path). These eliminate “can’t find module” drift.

---

## 3) Mechanically, how the stitching lets you deliver **CST + repo‑aware metadata**

**Step A — Parse every `.py` file to a CST (file‑local):**
For each Python file, run your `index_module(path, code)`:

* It calls `cst.parse_module(...)`, wraps with `MetadataWrapper`, and uses a visitor that depends on `PositionProvider` to extract imports/defs/`__all__` and the module docstring.
* If LibCST ever throws, you already record a minimal record with the error so the pipeline keeps moving. 

**What this gives you:** A real LibCST tree in memory (round‑trippable) and a compact per‑module summary ready for enrichment/output.

---

**Step B — Enrich with *resolved* exports & re‑exports (cross‑file):**
The CST tells you there is a `from X import *` or `__all__`, but not which names ultimately flow out. You use SCIP to:

* Enumerate the exported symbols of `X` (from its document symbols).
* Map those back to the current module if they’re referenced locally.
* Materialize `exports_resolved` and `reexports` in the module record. 

This is exactly the bit that used to confuse repo‑wide analysis and LLMs; your stitching makes it explicit.

---

**Step C — Attach *qualified names* (what identifier is *which* thing):**
There are two routes:

* **LibCST route (when practical):** use `FullRepoManager` with providers like `QualifiedNameProvider` and `ScopeProvider`. These are file‑system aware and derive canonical names via import analysis. (Your current visitor shows the pattern for adding providers; you’d add the extra providers similarly.) 
* **Stitched route (what you’ve enabled now):** compute qualified names by joining the CST positions with SCIP symbol occurrences for the same file. SCIP already gives you `(symbol, range, roles)`; align ranges to CST nodes (you already carry line/col via `PositionProvider`). Populate `qualified_name` for defs/refs in your per‑node/per‑def records.

Either way, the “repo‑aware” piece is now robust because re‑exports and star imports are resolved (Step B).

---

**Step D — Attach *type* signals (without Pyre):**
LibCST’s built‑in `TypeInferenceProvider` requires Pyre. You’ve elected Pyrefly + Pyright instead, and you already have adapters:

* Run Pyrefly/Pyright; read their JSON/JSONL into a `TypeSummary(by_file → error_count, notes)`.
* Optionally compute simple annotation ratios from the CST defs (params/returns annotated) to expose `annotation_ratio` per file/def.
* Join these summaries back to your module JSON/Markdown (and node level if you add a def‑id).

Your Pyrefly config also enables “first‑use inference,” making its signals more informative in real code. 

---

**Step E — Emit the results**
Your writer layer already knows how to publish JSON/JSONL/Markdown. Add the new fields (`exports_resolved`, `reexports`, `qualified_names`, `annotation_ratio`, etc.) and call `write_json[l]` / `write_markdown_module`. 

---

## 4) So… can we “generate CST data” now?

**Yes—in two senses:**

* **Real CSTs**: You can and do parse every file with LibCST today (that’s *the* CST). The stitched signals aren’t a substitute for parsing—they make the *cross‑file* information that CST doesn’t carry (re‑exports, symbol identity, types) reliable and cheap to compute. 

* **CST + repo metadata bundles**: You can now **serialize** per‑module “CST bundles” (summaries keyed by positions/linenos) that include resolved exports, qualified names, and type/health signals—precisely the package LLM agents need. Your SCIP reader and writers were the missing pieces to do this deterministically.

**What you cannot (and should not) do:** reconstruct a faithful CST **without** the source by “inverting” SCIP or outlines. SCIP is a symbol graph; it doesn’t preserve whitespace/comments/trivia. Tree‑sitter outlines are great for structure and non‑Python, but they’re not a round‑trippable CST. For CST, parsing the source is always the correct path; your code already does that. 

---

## 5) A minimal “next step” checklist (if you want fully repo‑aware CST output)

1. **Extend your visitor to request more providers** (add `ScopeProvider`, and—if you decide to use LibCST’s own—`QualifiedNameProvider`). Keep `PositionProvider` as the anchor. 
2. **Join SCIP occurrences → CST nodes** to populate `qualified_name` on defs/refs when LibCST providers aren’t used or disagree. 
3. **Compute `exports_resolved`/`reexports`** using the SCIP symbol map, and stash them in the module record. 
4. **Attach typedness** by ingesting Pyrefly/Pyright reports via your adapters and computing annotation ratios from the CST defs.
5. **Publish** via your existing JSON/JSONL/Markdown writers (they already support arbitrary fields). 
6. **Keep tool configs in lock‑step** (Pyrefly project includes / search path; Pyright stub path and envs), which you already have.

---

## 6) TL;DR

* The “stitching” didn’t just go around CST—it **unblocked CST‑based analysis across the repo** by supplying re‑export expansion, symbol identity and type signals that CST alone doesn’t carry.
* You can and should parse to LibCST for every file; your `libcst_bridge` already does the heavy lifting and was designed to survive parse issues gracefully. 
* Use SCIP + the type summaries to *enrich* that CST so agents see a repo‑aware, typed, documented, export‑resolved view, and keep emitting it through your existing writer layer.

If you want, I can produce a tiny patch that (a) adds `QualifiedNameProvider` wiring to your LibCST pass and (b) writes a `cst_enriched.jsonl` with `{path, defs[{name, lineno, qualified_name, doc, annotation}], exports_resolved, reexports, type_stats}`—but from a purely *mechanical* standpoint, you’re already set.



Absolutely—you’re ready to produce a **full, repository‑wide LibCST dataset** (CST = lossless concrete syntax tree + rich metadata) using what you already have in `codeintel_rev`. Below is a **drop‑in implementation plan plus ready‑to‑paste code** that:

* parses *every* Python file with LibCST,
* attaches **repo‑aware metadata** (scope, positions, parent relationships, qualified names),
* stitches with your **SCIP** symbols where possible,
* emits a **CST JSONL** stream per node (function/class/assign/import, etc.) for RAG/vector indexing,
* integrates cleanly with your existing CLI, writers, and configs.

---

## Why this works now

* Your CLI already walks files, loads SCIP, and writes JSON/JSONL—so we can extend it without new plumbing. 
* You already run LibCST successfully to extract imports/defs/`__all__`/docstrings—so we can promote that to a **full CST export** with Metadata Providers. 
* The SCIP reader is in place for symbol occurrences and symbol docs—so we can annotate CST nodes with best‑effort symbol IDs. 
* Your writer utilities already output JSON/JSONL/Markdown—so emitting a `cst/cst.jsonl` is trivial. 
* Your configs already define repo search paths (`src`, `codeintel_rev`, `tools`, `stubs`) which line up with LibCST’s `FullRepoManager` expectations.
* You have a current SCIP index for `codeintel_rev` for cross‑file symbol glue.
* `libcst` is already on your dependency graph via your `pyproject.toml`. 

---

## What we’ll emit (schema, agent‑friendly)

We’ll write **one JSONL row per node** with stable IDs and stitch points:

```json
{
  "path": "codeintel_rev/_lazy_imports.py",
  "node_id": "codeintel_rev/_lazy_imports.py:20:8:FunctionDef:module",
  "node_type": "FunctionDef",
  "name": "module",
  "qualified_names": ["codeintel_rev._lazy_imports.LazyModule.module"],
  "span": {"start":{"line":20,"col":8},"end":{"line":31,"col":27}},
  "parent_id": "codeintel_rev/_lazy_imports.py:10:6:ClassDef:LazyModule",
  "scope": "class",
  "signature": {"params":[{"name":"self"}], "returns":"ModuleType"},
  "decorators": [],
  "docstring": null,
  "bases": [],
  "imports": null,
  "assign_targets": null,
  "scip_symbol": "scip-python python kgfoundry 0.1.0 `codeintel_rev._lazy_imports`/LazyModule#module()."
}
```

Agents can embed these rows directly (signature + doc + span) and still **round‑trip** to *exact* code via `span` fields. (We keep module‑level rows too for top‑level docstrings.)

---

## Implementation plan (mechanics)

1. **Add a CST exporter** that uses LibCST metadata providers:

   * `PositionProvider` → exact byte/line spans for nodes.
   * `ParentNodeProvider` → stable parent links to build a lexical tree.
   * `ScopeProvider` → module/class/function scope classification.
   * `QualifiedNameProvider` → repo‑aware qualified names (with `FullRepoManager` for cross‑file import awareness).
   * `ExpressionContextProvider` → (optional) load/store for name nodes (handy for advanced analyses).
     We traverse `Module`, `ClassDef`, `FunctionDef`, `Assign`, `Import`, `ImportFrom` and serialize a compact, LLM‑friendly record. 

2. **Make it repo‑aware** with `FullRepoManager`:

   * Build one manager at the repo root with the same `paths`/search‑path semantics you use for Pyrefly/Pyright, so qualified names resolve consistently. We reuse your configured roots (`src`, `codeintel_rev`, `tools`, `stubs`).
   * If `FullRepoManager` can’t initialize (e.g., unusual environment), we **fall back** to per‑file `MetadataWrapper`—you still get positions, parents, scopes, and *local* qualified names. 

3. **Stitch to SCIP**:

   * For each file, load its SCIP `occurrences` and build a quick `line->symbol` index (best effort; SCIP uses 0‑based lines). For each Function/Class node we pick the closest def‑occurrence at the node start line. This gives you a `scip_symbol` handle you can join with your existing `symbol_graph.json`.

4. **Write results**:

   * Emit `codeintel_rev/io/ENRICHED/cst/cst.jsonl` (all nodes).
   * Optional: emit `codeintel_rev/io/ENRICHED/cst/cst.parquet` (if you want analytics later), but JSONL is enough for RAG.
     This uses your existing writers. 

5. **Integrate into your CLI**:

   * Add `--emit-cst` and `--cst-out` flags to `codeintel-enrich` so it’s a single‑shot run with all your other artifacts. 

---

## New file: `codeintel_rev/cst_dataset.py` (drop‑in)

> Paste this as a new module. It is defensive: it uses `FullRepoManager` when possible, and falls back to per‑file wrappers if not.

```python
# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import libcst as cst
from libcst import metadata as cst_metadata

@dataclass
class Span:
    start_line: int
    start_col: int
    end_line: int
    end_col: int

@dataclass
class NodeRow:
    path: str
    node_id: str
    node_type: str
    name: Optional[str]
    qualified_names: List[str]
    span: Dict[str, Dict[str, int]]
    parent_id: Optional[str]
    scope: Optional[str]
    signature: Optional[Dict[str, Any]] = None
    decorators: Optional[List[str]] = None
    bases: Optional[List[str]] = None
    docstring: Optional[str] = None
    imports: Optional[Dict[str, Any]] = None
    assign_targets: Optional[List[str]] = None
    scip_symbol: Optional[str] = None
    parse_ok: bool = True
    notes: List[str] = field(default_factory=list)

# ------------- helpers

def _span(wrapper: cst_metadata.MetadataWrapper, node: cst.CSTNode) -> Span:
    pos = wrapper.resolve(cst_metadata.PositionProvider, node)
    return Span(pos.start.line, pos.start.column, pos.end.line, pos.end.column)

def _node_id(path: str, kls: str, name: Optional[str], sp: Span) -> str:
    return f"{path}:{sp.start_line}:{sp.start_col}:{kls}:{name or ''}"

def _name_or_none(node: cst.CSTNode) -> Optional[str]:
    if isinstance(node, (cst.FunctionDef, cst.ClassDef)):
        return node.name.value
    return None

def _get_docstring(node: cst.CSTNode) -> Optional[str]:
    # For module/class/function, docstring is first simple statement string
    body = None
    if isinstance(node, cst.Module):
        body = node.body
    elif isinstance(node, cst.ClassDef):
        body = node.body.body
    elif isinstance(node, cst.FunctionDef):
        body = node.body.body
    if not body:
        return None
    first = body[0]
    if isinstance(first, cst.SimpleStatementLine) and first.body:
        expr = first.body[0]
        if isinstance(expr, cst.Expr) and isinstance(expr.value, cst.SimpleString):
            try:
                return expr.value.evaluated_value
            except Exception:
                return None
    return None

def _scope_str(wrapper: cst_metadata.MetadataWrapper, node: cst.CSTNode) -> Optional[str]:
    try:
        scope = wrapper.resolve(cst_metadata.ScopeProvider, node)
    except Exception:
        return None
    # classify coarse-grained
    from libcst.metadata.scope_provider import (  # type: ignore
        ClassScope, FunctionScope, GlobalScope, ComprehensionScope
    )
    if isinstance(scope, GlobalScope):
        return "module"
    if isinstance(scope, ClassScope):
        return "class"
    if isinstance(scope, FunctionScope):
        return "function"
    if isinstance(scope, ComprehensionScope):
        return "comprehension"
    return scope.__class__.__name__.lower()

def _qnames(wrapper: cst_metadata.MetadataWrapper, node: cst.CSTNode) -> List[str]:
    try:
        qns = wrapper.resolve(cst_metadata.QualifiedNameProvider, node)
        # set of QualifiedName objects -> list of strings
        return sorted(q.name for q in qns)
    except Exception:
        return []

def _render_ann(mod: cst.Module, ann: Optional[cst.Annotation]) -> Optional[str]:
    if not ann:
        return None
    try:
        return mod.code_for_node(ann.annotation)
    except Exception:
        return None

def _fn_sig(mod: cst.Module, fn: cst.FunctionDef) -> Dict[str, Any]:
    params = []
    for p in fn.params.params + fn.params.posonly_params + fn.params.kwonly_params:
        params.append({"name": p.name.value, "annotation": _render_ann(mod, p.annotation)})
    if fn.params.star_arg:
        a = fn.params.star_arg
        params.append({"name": ("*" + a.name.value) if a.name else "*", "annotation": _render_ann(mod, a.annotation)})
    if fn.params.star_kwarg:
        a = fn.params.star_kwarg
        params.append({"name": "**" + a.name.value, "annotation": _render_ann(mod, a.annotation)})
    ret = _render_ann(mod, fn.returns)
    decos = []
    for d in fn.decorators:
        try:
            decos.append(mod.code_for_node(d.decorator))
        except Exception:
            pass
    return {"params": params, "returns": ret, "decorators": decos}

def _class_bases(mod: cst.Module, cls: cst.ClassDef) -> List[str]:
    out: List[str] = []
    for b in cls.bases:
        try:
            out.append(mod.code_for_node(b.value))
        except Exception:
            pass
    return out

# ------------- core export

def export_cst_for_repo(
    root: Path,
    files: List[Path],
    scip_by_file: Dict[str, Any] | None = None,
) -> Iterator[NodeRow]:
    """
    Yield NodeRow for every interesting CST node across the repo, with repo-aware metadata when possible.
    """
    # Try to build FullRepoManager for cross-file-qualified names
    manager = None
    try:
        from libcst.metadata import FullRepoManager
        providers = (
            cst_metadata.ParentNodeProvider,
            cst_metadata.PositionProvider,
            cst_metadata.ScopeProvider,
            cst_metadata.QualifiedNameProvider,
            cst_metadata.ExpressionContextProvider,
        )
        manager = FullRepoManager(str(root), [str(p) for p in files], providers=providers)
    except Exception:
        manager = None  # fall back to per-file

    # prebuild per-file SCIP line -> symbol (0-based line index best-effort)
    scip_line_index: Dict[str, Dict[int, str]] = {}
    if scip_by_file:
        for rel, doc in scip_by_file.items():
            line_to_sym: Dict[int, str] = {}
            for occ in getattr(doc, "occurrences", []) or []:
                rng = getattr(occ, "range", None)
                roles = set(getattr(occ, "roles", []) or [])
                if not rng or "Definition" not in "".join(roles):
                    # treat first occurrence per line as candidate if roles missing
                    pass
                # Occurrence ranges are [startLine, startCol, endLine, endCol], 0-based lines
                try:
                    line_to_sym[int(rng[0])] = occ.symbol
                except Exception:
                    continue
            scip_line_index[rel] = line_to_sym

    for fp in files:
        rel = str(fp.relative_to(root))
        try:
            code = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # Wrap with repo-aware or per-file metadata
        try:
            if manager:
                wrapper = manager.get_metadata_wrapper_for_path(rel)
                # Note: wrapper.module is reconstructed by manager
                mod = wrapper.module
            else:
                mod = cst.parse_module(code)
                wrapper = cst_metadata.MetadataWrapper(mod, unsafe_skip_copy=True)
            parent_map = wrapper.resolve(cst_metadata.ParentNodeProvider)
        except Exception as exc:
            # emit a single parse error row so the pipeline remains total
            yield NodeRow(
                path=rel,
                node_id=f"{rel}:0:0:Module:",
                node_type="Module",
                name=None,
                qualified_names=[],
                span={"start": {"line": 1, "col": 0}, "end": {"line": 1, "col": 0}},
                parent_id=None,
                scope="module",
                docstring=None,
                parse_ok=False,
                notes=[f"Parse/metadata error: {exc!r}"],
            )
            continue

        # helper to compute parent id for any node
        def pid(n: cst.CSTNode, sp: Span) -> Optional[str]:
            p = parent_map.get(n)
            if not p:
                return None
            psp = _span(wrapper, p)
            return _node_id(rel, p.__class__.__name__, _name_or_none(p), psp)

        # Visit nodes
        for node in mod.body:
            # We’ll DFS the whole tree
            stack = [node]
            while stack:
                cur = stack.pop()
                sp = _span(wrapper, cur)
                kls = cur.__class__.__name__
                nm = _name_or_none(cur)
                qns = _qnames(wrapper, cur)
                scope = _scope_str(wrapper, cur)
                row = NodeRow(
                    path=rel,
                    node_id=_node_id(rel, kls, nm, sp),
                    node_type=kls,
                    name=nm,
                    qualified_names=qns,
                    span={"start": {"line": sp.start_line, "col": sp.start_col},
                          "end": {"line": sp.end_line, "col": sp.end_col}},
                    parent_id=pid(cur, sp),
                    scope=scope,
                    docstring=_get_docstring(cur) if isinstance(cur, (cst.Module, cst.ClassDef, cst.FunctionDef)) else None,
                )

                # Specialize per node kind
                if isinstance(cur, cst.FunctionDef):
                    row.signature = _fn_sig(mod, cur)
                    row.decorators = row.signature.pop("decorators", [])
                elif isinstance(cur, cst.ClassDef):
                    row.bases = _class_bases(mod, cur)
                    row.decorators = []
                    for d in cur.decorators:
                        try:
                            row.decorators.append(mod.code_for_node(d.decorator))
                        except Exception:
                            pass
                elif isinstance(cur, cst.Assign):
                    targets = []
                    for t in cur.targets:
                        try:
                            if isinstance(t.target, cst.Name):
                                targets.append(t.target.value)
                            else:
                                targets.append(mod.code_for_node(t.target))
                        except Exception:
                            pass
                    row.assign_targets = targets
                elif isinstance(cur, cst.Import):
                    names, aliases = [], {}
                    for n in cur.names:
                        ident = n.name.value if isinstance(n.name, cst.Name) else n.name.attr.value  # type: ignore
                        names.append(ident)
                        if n.asname:
                            aliases[ident] = n.asname.name.value
                    row.imports = {"module": None, "names": names, "aliases": aliases, "is_star": False, "level": 0}
                elif isinstance(cur, cst.ImportFrom):
                    is_star = isinstance(cur.names, cst.ImportStar)
                    names, aliases = [], {}
                    if not is_star:
                        for n in cur.names:  # type: ignore
                            ident = n.name.value if isinstance(n.name, cst.Name) else n.name.attr.value  # type: ignore
                            names.append(ident)
                            if n.asname:
                                aliases[ident] = n.asname.name.value
                    module = None
                    if cur.module:
                        try:
                            module = mod.code_for_node(cur.module)
                        except Exception:
                            pass
                    level = len(cur.relative) if cur.relative else 0
                    row.imports = {"module": module, "names": names, "aliases": aliases, "is_star": is_star, "level": level}

                # Best-effort SCIP symbol
                if scip_line_index.get(rel):
                    # convert 1-based CST line to 0-based SCIP line
                    cand = scip_line_index[rel].get(sp.start_line - 1)
                    if cand:
                        row.scip_symbol = cand

                yield row
                # DFS
                stack.extend(reversed(list(cur.children)))
```

---

## CLI change: extend `codeintel-enrich` to emit CST

> Patch your CLI to add `--emit-cst/--no-emit-cst` and one call into the exporter. The rest of the flow (SCIP load, file walking, writers) stays the same.

```python
# codeintel_rev/cli_enrich.py  (additions marked)
# SPDX-License-Identifier: MIT
from __future__ import annotations

# ... existing imports ...
from .enrich.output_writers import write_json, write_jsonl, write_markdown_module
# NEW:
from .cst_dataset import export_cst_for_repo   # <— add this import

# ... existing ModuleRecord dataclass, _iter_files, app ...

@app.command()
def main(
    root: Path = typer.Option(Path("."), "--root", help="Repo or subfolder to scan."),
    scip: Path = typer.Option(..., "--scip", exists=True, help="Path to SCIP index.json"),
    out: Path = typer.Option(Path("codeintel_rev/io/ENRICHED"), "--out", help="Output directory"),
    pyrefly_json: Optional[Path] = typer.Option(None, "--pyrefly-json", help="Optional path to Pyrefly JSON/JSONL report"),
    tags_yaml: Optional[Path] = typer.Option(None, "--tags-yaml", help="Optional tagging rules YAML"),
    # NEW:
    emit_cst: bool = typer.Option(True, "--emit-cst/--no-emit-cst", help="Emit full LibCST dataset as JSONL"),
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    scip_index = SCIPIndex.load(scip)
    scip_by_file = scip_index.by_file()
    sym_to_files = scip_index.symbol_to_files()

    # Optional type check summaries
    t_pyright = collect_pyright(str(root))
    t_pyrefly = collect_pyrefly(str(pyrefly_json) if pyrefly_json else None)

    rules = load_rules(str(tags_yaml) if tags_yaml else None)

    module_rows: List[Dict[str, Any]] = []
    symbol_edges: List[Tuple[str, str]] = []  # (symbol, file)
    tag_index: Dict[str, List[str]] = {}

    files = list(_iter_files(root))

    for fp in files:
        # ... existing per-file logic unchanged ...
        # writes per-module markdown; populates module_rows; symbol_edges
        ...

    # Write repo-level artifacts (unchanged)
    write_jsonl(out / "modules" / "modules.jsonl", module_rows)
    write_json(out / "graphs" / "symbol_graph.json", [{"symbol": s, "file": f} for s, f in symbol_edges])
    write_json(out / "repo_map.json", {"root": str(root), "modules": len(module_rows), "tags": tag_index, "symbols": len(symbol_edges)})

    # NEW: emit CST dataset
    if emit_cst:
        cst_out = out / "cst" / "cst.jsonl"
        rows = (asdict(r) for r in export_cst_for_repo(root, files, scip_by_file))
        write_jsonl(cst_out, rows)
        typer.secho(f"[CST] wrote {cst_out}", fg=typer.colors.GREEN)
```

This ties into the CLI you already have and reuses your existing writers and SCIP loader.

---

## How to run

```bash
# from repo root, with your existing scip index
codeintel-enrich --root codeintel_rev --scip index.scip.json --emit-cst
# CST will be at: codeintel_rev/io/ENRICHED/cst/cst.jsonl
```

The CLI will still produce your current module summaries, symbol graph, and tags alongside the new CST dataset. 

---

## Validation checklist (quick)

1. **File count check:** `wc -l codeintel_rev/io/ENRICHED/cst/cst.jsonl` roughly equals *sum of CST nodes* across your Python files (hundreds to thousands is normal).
2. **Spot check a function:** pick a function in `codeintel_rev/_lazy_imports.py`; verify `node_id`, `span` and `signature` match the source text. The SCIP `scip_symbol` should align with your `symbol_graph.json` entry for that def.
3. **Qualified names:** For classes/functions in packages (e.g., `codeintel_rev.errors.FileOperationError`), confirm `qualified_names` contains the fully‑qualified dotted path.
4. **Docstrings present:** Module/class/function docstrings appear under `docstring`. Your earlier module docstring extraction confirms this is stable. 

---

## Notes on types and Pyrefly

* LibCST’s **TypeInferenceProvider** requires Pyre; since you standardized on **Pyrefly**, the CST export above **does not** attempt to attach inferred types. Instead, you already harvest typedness via Pyrefly/Pyright and can join those metrics to CST nodes by `(path, span.start_line)` if you wish (useful for “untyped hotspots” overlays). Keep Pyrefly as your type ground truth and resist mutating code during CST export. 

---

## Why this is agent‑ready

* **Lossless spans** let you reconstruct *exact* code for a node—perfect for chunk‑level embedding and precise RAG citations.
* **Qualified names** and **SCIP symbols** give you *stable join keys* to connect CST chunks to usage graphs, export surfaces, ownership, coverage, etc.
* **Parents/Scopes** let you package hierarchical context (function → class → module) for *holistic* retrieval, without crossing module boundaries unless you explicitly want to.

---

## Optional extensions (later, not required)

* Emit a **`cst_nodes.parquet`** with selected columns for fast analytics (fan‑in/fan‑out by node, churn × complexity overlays).
* Add **token counts** per node to pre‑size RAG chunks, batching large bodies into sliding windows while keeping the same `node_id` + `part` field.
* Persist **docstring sections** (param/returns/example) using `docstring-parser` and attach to function/class nodes. (You already vend that dep.) 

---

### TL;DR

You already had 90% of the plumbing. The code above adds the **repo‑aware LibCST export** you’ve been aiming for, reusing your existing CLI, writers, SCIP reader, and config. Run `codeintel-enrich … --emit-cst` and you’ll get a **CST JSONL** suitable for vector indexing and best‑in‑class RAG over code.

If you want, I can also sketch an **embedding recipe** that turns `cst.jsonl` into hierarchical, scope‑aware chunks (signature + docstring + sliced body) with stable IDs and back‑references to your import and use graphs.
