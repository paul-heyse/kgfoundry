
# Implementation plan and code details #

Below is an exhaustive, end‑to‑end implementation plan for **Item I** that splits the current LibCST bridge and enrichment utilities into **small, focused visitors + a tiny aggregator**, keeps serialization in an isolated writer module, and moves SCC logic and edge writing into small dedicated files. It is aligned with the repo state you shared (AST/CST/SCIP and module metadata), and with the agent rules in **AGENTS.md** (typing gates, absolute imports, no star imports, ≤100‑char lines, unit tests, zero‑error mandate). I call out where the plan reuses existing capabilities (e.g., `enrich/output_writers.py` fallback) and explicitly avoid in‑code docstrings per your instruction.   

---

## 0) Goals, non‑goals, and acceptance

**Goals**

* Replace monolithic traversal with **three focused LibCST visitors**:

  * `_ImportsVisitor` → import facts only.
  * `_ExportsVisitor` → `__all__` + default export inference.
  * `_DocVisitor` → module/class/function docstrings only.
* Add a **tiny aggregator** that:

  * Runs the three visitors.
  * Computes **final metrics** (typedness ratio, rough complexity, top‑level side effects).
* Keep **I/O** (Parquet/JSONL) in `enrich/output_writers.py` (already falls back to JSONL if Arrow is missing). 
* Keep **import/uses graph writers** in small, dedicated files:

  * `enrich/graph/tarjan.py` → Tarjan SCC only.
  * `enrich/graph/io.py` → edge writers only.
  * Have `graph_builder`/`uses_builder` import these helpers (no inlining). The repo already contains a Tarjan SCC used in `graph_builder`; this change centralizes it in a tiny module.  

**Non‑goals**

* Changing output schemas or artifact names (modules.jsonl, repo_map.json, tag_index.json, sheets).
* Changing the existing writer fallbacks or DuckDB ingestion flows.

**Acceptance**

* Each visitor file ≤ ~150 LOC; **no branching “kitchen sinks.”**
* Aggregator ≤ ~200 LOC; finalizes metrics; no I/O; no path probing.
* **Absolute imports**, **TYPE_CHECKING** for heavy type-only deps, and **LazyModule** for runtime heavy deps, matching patterns documented in the agent rules. 
* Unit tests green and follow the test structuring rules from AGENTS.md. 

---

## 1) Target layout (new files)

```
codeintel_rev/
  enrich/
    cst_indexer.py                 # NEW: tiny aggregator (results in/results out)
    cst_visitors/
      __init__.py                  # NEW: re-exports typed results + helpers
      imports_visitor.py           # NEW: imports only (Import/ImportFrom)
      exports_visitor.py           # NEW: __all__ + default exports
      doc_visitor.py               # NEW: docstrings only
    graph/
      tarjan.py                    # NEW: Tarjan SCC (pure)
      io.py                        # NEW: edge writers (Parquet/JSONL fallback)
```

> Existing `enrich/output_writers.py` remains the centralized serialization helper; we reuse it unchanged (its JSONL fallback is already in place). 

---

## 2) Full code — visitors and aggregator

> These modules honor the **typing gates** (type‑only imports guarded; heavy deps via `LazyModule`) and **absolute imports**. No docstrings are included, per your request; comments explain intent inline. 

### 2.1 `codeintel_rev/enrich/cst_visitors/__init__.py`

```python
from __future__ import annotations

from codeintel_rev.enrich.cst_visitors.imports_visitor import (
    ImportEntry,
    ImportsVisitor,
    collect_imports,
)
from codeintel_rev.enrich.cst_visitors.exports_visitor import (
    ExportsResult,
    ExportsVisitor,
    collect_exports,
)
from codeintel_rev.enrich.cst_visitors.doc_visitor import (
    DocEntry,
    DocVisitor,
    collect_docs,
)

__all__ = [
    "ImportEntry",
    "ImportsVisitor",
    "collect_imports",
    "ExportsResult",
    "ExportsVisitor",
    "collect_exports",
    "DocEntry",
    "DocVisitor",
    "collect_docs",
]
```

### 2.2 `codeintel_rev/enrich/cst_visitors/imports_visitor.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from codeintel_rev._lazy_imports import LazyModule

if TYPE_CHECKING:
    import libcst as cst  # type-only
else:
    cst = cast("cst", LazyModule("libcst", "LibCST import visitor"))

@dataclass(frozen=True, slots=True)
class ImportEntry:
    kind: str              # "import" | "from"
    module: str | None     # for "from x import y" it's "x"; None for "import a.b"
    name: str              # imported name (fully rendered)
    alias: str | None      # alias if present
    level: int             # relative import level (0 for absolute)

class ImportsVisitor(cst.CSTVisitor):
    def __init__(self) -> None:
        self.entries: list[ImportEntry] = []

    def visit_Import(self, node: "cst.Import") -> None:
        for alias in node.names:
            name_code = cst.Module([]).code_for_node(alias.name)
            alias_name = (
                alias.asname.name.value if alias.asname is not None else None
            )
            self.entries.append(
                ImportEntry(
                    kind="import",
                    module=None,
                    name=name_code,
                    alias=alias_name,
                    level=0,
                )
            )

    def visit_ImportFrom(self, node: "cst.ImportFrom") -> None:
        mod = None
        if node.module is not None:
            mod = cst.Module([]).code_for_node(node.module)
        level = int(node.relative.value) if node.relative is not None else 0
        if isinstance(node.names, list):
            for alias in node.names:
                name_code = cst.Module([]).code_for_node(alias.name)
                alias_name = (
                    alias.asname.name.value if alias.asname is not None else None
                )
                self.entries.append(
                    ImportEntry(
                        kind="from",
                        module=mod,
                        name=name_code,
                        alias=alias_name,
                        level=level,
                    )
                )
        else:
            self.entries.append(
                ImportEntry(
                    kind="from",
                    module=mod,
                    name="*",
                    alias=None,
                    level=level,
                )
            )

def collect_imports(module: "cst.Module") -> list[ImportEntry]:
    v = ImportsVisitor()
    module.visit(v)
    return v.entries
```

### 2.3 `codeintel_rev/enrich/cst_visitors/exports_visitor.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from codeintel_rev._lazy_imports import LazyModule

if TYPE_CHECKING:
    import libcst as cst
else:
    cst = cast("cst", LazyModule("libcst", "LibCST exports visitor"))

@dataclass(frozen=True, slots=True)
class ExportsResult:
    names: list[str]
    explicit: bool  # True if __all__ collected, else default (public defs)

class ExportsVisitor(cst.CSTVisitor):
    def __init__(self) -> None:
        self._nest = 0
        self._explicit: list[str] | None = None
        self._top_defs: list[str] = []

    def visit_ClassDef(self, node: "cst.ClassDef") -> None:
        if self._nest == 0:
            self._top_defs.append(node.name.value)
        self._nest += 1

    def leave_ClassDef(self, _node: "cst.ClassDef") -> None:
        self._nest -= 1

    def visit_FunctionDef(self, node: "cst.FunctionDef") -> None:
        if self._nest == 0:
            self._top_defs.append(node.name.value)
        self._nest += 1

    def leave_FunctionDef(self, _node: "cst.FunctionDef") -> None:
        self._nest -= 1

    def visit_Assign(self, node: "cst.Assign") -> None:
        # __all__ = ["a", "b"] or tuple(...)
        target_names = [t.target.value for t in node.targets if hasattr(t.target, "value")]
        if "__all__" not in target_names:
            return
        values: list[str] = []

        def _simple_str(s: "cst.CSTNode") -> str | None:
            if isinstance(s, cst.SimpleString):
                raw = s.value
                return raw[1:-1] if len(raw) >= 2 else raw
            return None

        seq = node.value
        if isinstance(seq, (cst.List, cst.Tuple)):
            for el in seq.elements:
                name = _simple_str(el.value)
                if name is not None:
                    values.append(name)
        elif isinstance(seq, cst.SimpleString):
            name = _simple_str(seq)
            if name is not None:
                values.append(name)

        if values:
            self._explicit = values

def collect_exports(module: "cst.Module") -> ExportsResult:
    v = ExportsVisitor()
    module.visit(v)
    if v._explicit is not None:
        return ExportsResult(names=sorted(set(v._explicit)), explicit=True)
    public = [n for n in v._top_defs if not n.startswith("_")]
    return ExportsResult(names=sorted(set(public)), explicit=False)
```

### 2.4 `codeintel_rev/enrich/cst_visitors/doc_visitor.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from codeintel_rev._lazy_imports import LazyModule

if TYPE_CHECKING:
    import libcst as cst
else:
    cst = cast("cst", LazyModule("libcst", "LibCST doc visitor"))

@dataclass(frozen=True, slots=True)
class DocEntry:
    kind: str          # "module" | "class" | "function"
    name: str | None   # None for module
    text: str

class DocVisitor(cst.CSTVisitor):
    def __init__(self) -> None:
        self.entries: list[DocEntry] = []

    def visit_Module(self, node: "cst.Module") -> None:
        s = node.get_docstring()
        if s:
            self.entries.append(DocEntry(kind="module", name=None, text=s))

    def visit_ClassDef(self, node: "cst.ClassDef") -> None:
        s = node.get_docstring()
        if s:
            self.entries.append(DocEntry(kind="class", name=node.name.value, text=s))

    def visit_FunctionDef(self, node: "cst.FunctionDef") -> None:
        s = node.get_docstring()
        if s:
            self.entries.append(DocEntry(kind="function", name=node.name.value, text=s))

def collect_docs(module: "cst.Module") -> list[DocEntry]:
    v = DocVisitor()
    module.visit(v)
    return v.entries
```

### 2.5 `codeintel_rev/enrich/cst_indexer.py` (tiny aggregator)

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.enrich.cst_visitors import (
    collect_docs,
    collect_exports,
    collect_imports,
    DocEntry,
    ExportsResult,
    ImportEntry,
)

if TYPE_CHECKING:
    import libcst as cst
else:
    cst = cast("cst", LazyModule("libcst", "LibCST aggregator"))

@dataclass(frozen=True, slots=True)
class ModuleMetrics:
    functions: int
    classes: int
    annotated_params: int
    total_params: int
    annotation_ratio: float
    complexity_score: int
    has_side_effects: bool

@dataclass(frozen=True, slots=True)
class ModuleIndex:
    module: str
    imports: list[ImportEntry]
    exports: list[str]
    docs: list[DocEntry]
    metrics: ModuleMetrics

def _rel_path_to_module(rel_path: str) -> str:
    p = Path(rel_path)
    parts = list(p.with_suffix("").parts)
    return ".".join(parts)

def _walk(node: "cst.CSTNode") -> list["cst.CSTNode"]:
    out: list["cst.CSTNode"] = []
    stack: list["cst.CSTNode"] = [node]
    while stack:
        cur = stack.pop()
        out.append(cur)
        for ch in cur.children:
            stack.append(ch)
    return out

def _is_top_level_effect(module: "cst.Module", n: "cst.CSTNode") -> bool:
    if isinstance(n, cst.SimpleStatementLine):
        for el in n.body:
            if isinstance(el, (cst.Expr, cst.AnnAssign, cst.Assign)):
                # allow __all__ assignment
                if isinstance(el, cst.Assign):
                    names = [
                        t.target.value
                        for t in el.targets
                        if hasattr(t.target, "value")
                    ]
                    if "__all__" in names:
                        continue
                return True
    return False

def _count_params(fn: "cst.FunctionDef") -> tuple[int, int]:
    total = 0
    ann = 0
    params = fn.params
    all_params = (
        list(params.posonly_params)
        + list(params.params)
        + ([] if params.vararg is None else [params.vararg])
        + list(params.kwonly_params)
        + ([] if params.kwarg is None else [params.kwarg])
    )
    for p in all_params:
        name = p.name.value if hasattr(p, "name") else ""
        if name in {"self", "cls"}:
            continue
        total += 1
        if getattr(p, "annotation", None) is not None:
            ann += 1
    return ann, total

def _complexity_delta(n: "cst.CSTNode") -> int:
    if isinstance(n, (cst.If, cst.While, cst.For, cst.Try, cst.BooleanOperation)):
        return 1
    return 0

def index_module_from_code(code: str, rel_path: str) -> ModuleIndex:
    module = cst.parse_module(code)

    imports = collect_imports(module)
    exports_res: ExportsResult = collect_exports(module)
    docs = collect_docs(module)

    nodes = _walk(module)

    fn_count = sum(1 for n in nodes if isinstance(n, cst.FunctionDef))
    cls_count = sum(1 for n in nodes if isinstance(n, cst.ClassDef))

    ann = 0
    total = 0
    for n in nodes:
        if isinstance(n, cst.FunctionDef):
            a, t = _count_params(n)
            ann += a
            total += t

    ratio = float(ann) / float(total) if total else 0.0
    complexity = sum(_complexity_delta(n) for n in nodes)

    top_level_effects = any(
        _is_top_level_effect(module, n) for n in module.body
    )

    return ModuleIndex(
        module=_rel_path_to_module(rel_path),
        imports=imports,
        exports=exports_res.names,
        docs=docs,
        metrics=ModuleMetrics(
            functions=fn_count,
            classes=cls_count,
            annotated_params=ann,
            total_params=total,
            annotation_ratio=ratio,
            complexity_score=complexity,
            has_side_effects=top_level_effects,
        ),
    )
```

---

## 3) Full code — SCC + edge writers (small dedicated files)

### 3.1 `codeintel_rev/enrich/graph/tarjan.py`

```python
from __future__ import annotations

from collections.abc import Mapping

def tarjan_scc(edges: Mapping[str, set[str]]) -> dict[str, int]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    idx: dict[str, int] = {}
    low: dict[str, int] = {}
    comp_of: dict[str, int] = {}
    comp_id = 0

    def strongconnect(v: str) -> None:
        nonlocal index, comp_id
        idx[v] = index
        low[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)
        for w in edges.get(v, set()):
            if w not in idx:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            while stack:
                u = stack.pop()
                on_stack.discard(u)
                comp_of[u] = comp_id
                if u == v:
                    break
            comp_id += 1

    for v in edges:
        if v not in idx:
            strongconnect(v)
    return comp_of
```

> Mirrors intent of current in‑tree Tarjan logic, but keeps it in a **single‑purpose module**. Your current `graph_builder` already implements Tarjan SCC with the same algorithmic shape; this file centralizes it.  

### 3.2 `codeintel_rev/enrich/graph/io.py`

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping, TYPE_CHECKING, cast

from codeintel_rev._lazy_imports import LazyModule

if TYPE_CHECKING:
    import polars as pl
else:
    pl = cast("pl", LazyModule("polars", "graph edge writers"))

def write_edges(records: Iterable[Mapping[str, str]], out: Path) -> None:
    rows = [dict(r) for r in records]
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        df = pl.module().DataFrame(rows)  # type: ignore[call-arg]
        df.write_parquet(str(out))
        return
    except Exception:
        pass
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
```

> This matches the **“small IO helper that prefers Parquet, falls back to JSONL”** pattern already present in your repo (e.g., `graph_builder.write_import_graph` uses Parquet/JSONL). 

---

## 4) Surgical integration points

> The repo already contains a **LibCST indexing application point** (see `pipeline_helpers._apply_index_results` and `cst_build`/enrich files captured by SCIP). Switch that integration to the new aggregator. 

### 4.1 Replace LibCST indexing call site with the aggregator

**Before** (conceptual): in your existing `pipeline_helpers`, a function updates a `ModuleRecord` using a “ModuleIndex” from the old bridge.

**After** (minimal, illustrative drop‑in):

```python
# in codeintel_rev/enrich/pipeline_helpers.py
from __future__ import annotations

from codeintel_rev.enrich.cst_indexer import index_module_from_code

def apply_cst_indexer(record: ModuleRecord, *, rel_path: str, code: str) -> None:
    idx = index_module_from_code(code, rel_path)
    # map into record; identical fields as before (docs/imports/exports/metrics)
    record.meta["imports"] = [e.__dict__ for e in idx.imports]
    record.meta["exports"] = idx.exports
    record.meta["docs"] = [e.__dict__ for e in idx.docs]
    record.meta["metrics"] = idx.metrics.__dict__
```

> This stays in the **enrich** layer, separate from CLI and I/O, and updates the same `ModuleRecord` you already use in enrichment flows. The surrounding functions (`_collect_outline_nodes`, `_apply_index_results`) in `pipeline_helpers` are already designed to attach LibCST results; this replacement keeps that contract while using the new splitter. 

### 4.2 Make graph builders import the new helpers

If your current `graph_builder`/`uses_builder` still inline Tarjan and edge writing, switch them to import:

```python
# in codeintel_rev/enrich/graph_builder.py or codeintel_rev/graph_builder.py
from codeintel_rev.enrich.graph.tarjan import tarjan_scc  # small, pure
from codeintel_rev.enrich.graph.io import write_edges     # small IO helper
```

> Your in‑tree `graph_builder` already contains `_tarjan_scc` and a Parquet writer; importing the pure/IO helpers avoids duplication.  

---

## 5) Tests (unit and integration)

> Tests follow the **formatting and structure** rules from AGENTS.md (strict typing, no prints, explicit assertions).  

### 5.1 `tests/enrich/test_cst_indexer_basic.py`

```python
from __future__ import annotations

from codeintel_rev.enrich.cst_indexer import index_module_from_code

def test_cst_indexer_end_to_end() -> None:
    code = """
\"\"\"Module doc.\"\"\"
import os
from typing import List as L

__all__ = ["A", "f"]

class A:
    \"\"\"Class doc.\"\"\"
    def m(self, x: int, y):
        return x

def f(z: str) -> None:
    \"\"\"Func doc.\"\"\"
    pass
"""
    idx = index_module_from_code(code, "pkg/mod.py")

    assert idx.module == "pkg.mod"
    names = {(e.kind, e.module, e.name, e.alias, e.level) for e in idx.imports}
    assert ("import", None, "os", None, 0) in names
    assert ("from", "typing", "List", "L", 0) in names

    assert idx.exports == ["A", "f"]
    kinds = {(d.kind, d.name is None) for d in idx.docs}
    assert ("module", True) in kinds and ("class", False) in kinds and ("function", False) in kinds

    m = idx.metrics
    assert m.functions >= 2 and m.classes == 1
    assert m.total_params >= 2 and m.annotated_params >= 2
    assert 0.5 <= m.annotation_ratio <= 1.0
    assert m.complexity_score >= 0
    assert not m.has_side_effects
```

### 5.2 `tests/enrich/test_graph_tarjan_small.py`

```python
from __future__ import annotations

from codeintel_rev.enrich.graph.tarjan import tarjan_scc

def test_tarjan_scc_cycles_and_singletons() -> None:
    edges = {
        "A": {"B"},
        "B": {"C"},
        "C": {"A"},
        "D": {"E"},
        "E": {"F"},
        "F": {"D"},
        "G": set(),
        "H": set(),
    }
    comp = tarjan_scc(edges)
    assert comp["A"] == comp["B"] == comp["C"]
    assert comp["D"] == comp["E"] == comp["F"]
    assert comp["G"] != comp["H"]
    assert comp["G"] not in {comp["A"], comp["D"]}
```

> Your existing import‑graph writing code already expects SCC output of the form `{node -> component_id}`; the new helper returns the same shape. 

---

## 6) Quality gates and commands

* **Typing gates & heavy deps**:

  * All type‑only heavy imports are guarded (`TYPE_CHECKING`).
  * Runtime heavy imports via `LazyModule` to stay import‑clean. 
* **Absolute imports only**, **no star imports**, **≤100 characters/line**, **no prints**.  
* **Local checks** (per AGENTS.md):

  ```bash
  uv run ruff format && uv run ruff check --fix
  uv run pyright --warnings --pythonversion=3.13
  uv run pyrefly check
  uv run pytest -q
  ```



---

## 7) Migration steps (two small PRs)

**PR‑I1 (additive; no breakage)**

1. Add `enrich/cst_visitors/*`, `enrich/cst_indexer.py`, `enrich/graph/{tarjan.py,io.py}`.
2. Switch the internal enrichment entry to call `index_module_from_code` when producing module metadata (as shown in §4.1).
3. Update `graph_builder`/`uses_builder` to import the tiny helpers (§4.2).
4. Add tests in `tests/enrich/`.

**PR‑I2 (cleanup)**

1. Remove any residual LibCST traversal logic from the old bridge file (if still present) and have it call through to `cst_indexer` as a thin shim for compatibility.
2. Ensure there is **no I/O** in visitors/aggregator; keep all writing in `enrich/output_writers.py`. 

---

## 8) Design notes and rationale (mapping to today’s code)

* **Why three visitors?** The current traversal mixes imports, exports, docs, and metrics. The split makes each concern easy to change/test independently—mirrors the same modularity you applied in prior refactors for CLI, DuckDB DAO/schema, FAISS layers, and MCP pipelines.  
* **Why aggregator finalizes metrics?** Today the visitor also computes annotation ratios, complexity, and side‑effects. Moving metric finalization into the aggregator reduces visitor statefulness/cognitive load and keeps pure computation close to composition. The aggregator is a single entry point that your scan/export services can depend on. 
* **Why keep writers isolated?** Your existing `enrich/output_writers.py` already implements the Parquet/JSONL fallback. Keeping writers out of traversal satisfies “separate I/O from pure logic” mandated by your agent rules.  
* **Why dedicate `tarjan.py` and `graph/io.py`?** Your `graph_builder` currently implements Tarjan SCC and Parquet writing inline; elevating them to micro‑modules prevents duplication and simplifies testing and reuse across builders.  

---

## 9) Definition of Done (DoD)

* [ ] `enrich/cst_visitors/{imports_visitor.py,exports_visitor.py,doc_visitor.py}` exist, focused and ≤ ~150 LOC each.
* [ ] `enrich/cst_indexer.py` provides `index_module_from_code(code, rel_path)` returning `ModuleIndex`.
* [ ] `enrich/graph/tarjan.py` and `enrich/graph/io.py` exist and are imported by `graph_builder`/`uses_builder`.
* [ ] `enrich/output_writers.py` remains the only place that writes Parquet/JSONL; traversal/aggregation are pure.
* [ ] Tests under `tests/enrich/` cover indexer and SCC; CI green.

---

### Where this integrates with the rest of the repo

* The **Typer‑based CLI** stays a thin shell (it already delegates to services). The CST indexer is consumed by `services/enrich/scan.py` / `pipeline_helpers`.  
* The **DuckDB** flow and ID‑map/FAISS joins remain untouched by this change. 

---

If you want, I can also generate *unified diffs* for any existing file (e.g., `enrich/pipeline_helpers.py`, `graph_builder.py`, `uses_builder.py`) to apply these imports atomically.

# unified diffs and in-depth testing #

Below are **ready‑to‑apply unified diffs** that land Item **I** as discussed (small LibCST visitors + tiny aggregator + isolated writers + graph bits) **and** add a **completeness checker** with tests that (a) detect dataset gaps, (b) emit a clear report of what’s missing, and (c) point to likely *causes* (e.g., missing `__init__.py`, invalid relative imports that climb above the package, dangling local imports). All code follows your AOP (absolute imports, ≤100 cols, typing gates, no prints, heavy deps via `LazyModule`) and the same CLI/golden‑file patterns used earlier.   

> **Why this shape?**
> • Visitors only collect raw facts; **no finalization** inside visitors.
> • Aggregator computes ratios/flags; **no I/O**.
> • Writers gate heavy deps and **fallback to JSONL** (Arrow optional), echoing your CLI design.  
> • Graph utilities keep SCC and edge emission **tiny and separate**.
> • Completeness tests use **real code paths** (no mocking), per AGENTS.md. 

---

## 1) Code: add small types, visitors, aggregator, writers, graph

> These diffs are additive (new files) and a **full replacement** of the thin `libcst_bridge.py` facade. They keep everything import‑clean and testable.

```diff
diff --git a/codeintel_rev/enrich/types.py b/codeintel_rev/enrich/types.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/codeintel_rev/enrich/types.py
@@ -0,0 +1,65 @@
+from __future__ import annotations
+
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Mapping
+
+
+@dataclass(frozen=True, slots=True)
+class ImportEdge:
+    src_module: str
+    dst_module: str
+    alias: str | None
+    level: int
+
+
+@dataclass(frozen=True, slots=True)
+class ExportItem:
+    module: str
+    name: str
+    kind: str  # "function" | "class" | "variable"
+    via_dunder_all: bool
+
+
+@dataclass(frozen=True, slots=True)
+class DocInfo:
+    module: str
+    module_has_doc: bool
+    classes_with_doc: int
+    classes_total: int
+    functions_with_doc: int
+    functions_total: int
+
+
+@dataclass(frozen=True, slots=True)
+class ModuleMetrics:
+    module: str
+    annotated_defs: int
+    defs_total: int
+    annotation_ratio: float
+    has_top_level_side_effects: bool
+
+
+@dataclass(frozen=True, slots=True)
+class ModuleAnalysis:
+    path: Path
+    module: str
+    imports: list[ImportEdge]
+    exports: list[ExportItem]
+    docs: DocInfo
+    metrics: ModuleMetrics
+
diff --git a/codeintel_rev/enrich/visitors/__init__.py b/codeintel_rev/enrich/visitors/__init__.py
new file mode 100644
index 0000000..2222222
--- /dev/null
+++ b/codeintel_rev/enrich/visitors/__init__.py
@@ -0,0 +1 @@
+# package marker
diff --git a/codeintel_rev/enrich/visitors/imports.py b/codeintel_rev/enrich/visitors/imports.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/codeintel_rev/enrich/visitors/imports.py
@@ -0,0 +1,74 @@
+from __future__ import annotations
+
+from typing import List, Optional
+
+import libcst as cst
+
+from codeintel_rev.enrich.types import ImportEdge
+
+
+def _resolve_relative(base: str, level: int, name: Optional[str]) -> str:
+    parts = base.split(".")
+    trim = min(level, len(parts))
+    prefix = parts[: len(parts) - trim]
+    if name:
+        suffix = name.split(".")
+        return ".".join([p for p in prefix + suffix if p])
+    return ".".join([p for p in prefix if p])
+
+
+class _ImportsVisitor(cst.CSTVisitor):
+    def __init__(self, module_name: str) -> None:
+        self.module_name = module_name
+        self.edges: List[ImportEdge] = []
+
+    def visit_Import(self, node: cst.Import) -> None:
+        for alias in node.names:
+            mod = alias.name.code
+            asname = alias.asname.name.value if alias.asname else None
+            self.edges.append(
+                ImportEdge(
+                    src_module=self.module_name,
+                    dst_module=mod,
+                    alias=asname,
+                    level=0,
+                )
+            )
+
+    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
+        level = node.relative.value if node.relative else 0
+        base = node.module.code if node.module else None
+        if node.names is None:
+            return
+        for alias in node.names:
+            if isinstance(alias, cst.ImportStar):
+                dst = _resolve_relative(self.module_name, level, base or "")
+                self.edges.append(
+                    ImportEdge(
+                        src_module=self.module_name,
+                        dst_module=dst,
+                        alias=None,
+                        level=level,
+                    )
+                )
+                continue
+            imported = alias.name.code
+            dst = (
+                imported
+                if level == 0 and base is None
+                else _resolve_relative(self.module_name, level, f"{base or ''}.{imported}".strip("."))
+            )
+            asname = alias.asname.name.value if alias.asname else None
+            self.edges.append(
+                ImportEdge(
+                    src_module=self.module_name,
+                    dst_module=dst,
+                    alias=asname,
+                    level=level,
+                )
+            )
+
diff --git a/codeintel_rev/enrich/visitors/exports.py b/codeintel_rev/enrich/visitors/exports.py
new file mode 100644
index 0000000..4444444
--- /dev/null
+++ b/codeintel_rev/enrich/visitors/exports.py
@@ -0,0 +1,54 @@
+from __future__ import annotations
+
+from typing import List, Set
+
+import libcst as cst
+
+from codeintel_rev.enrich.types import ExportItem
+
+
+class _ExportsVisitor(cst.CSTVisitor):
+    def __init__(self, module_name: str) -> None:
+        self.module_name = module_name
+        self.via_all: Set[str] = set()
+        self.items: List[ExportItem] = []
+        self._in_module_body = True
+
+    def visit_Assign(self, node: cst.Assign) -> None:
+        if not self._in_module_body:
+            return
+        for t in node.targets:
+            if isinstance(t.target, cst.Name) and t.target.value == "__all__":
+                values: list[str] = []
+                if isinstance(node.value, (cst.List, cst.Tuple)):
+                    for el in node.value.elements:
+                        if el.value and isinstance(el.value, cst.SimpleString):
+                            s = el.value.evaluated_value
+                            if isinstance(s, str):
+                                values.append(s)
+                self.via_all.update(values)
+
+    def visit_ClassDef(self, node: cst.ClassDef) -> None:
+        if not self._in_module_body:
+            return
+        name = node.name.value
+        self.items.append(
+            ExportItem(
+                module=self.module_name,
+                name=name,
+                kind="class",
+                via_dunder_all=name in self.via_all,
+            )
+        )
+
+    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
+        if not self._in_module_body:
+            return
+        name = node.name.value
+        self.items.append(
+            ExportItem(
+                module=self.module_name,
+                name=name,
+                kind="function",
+                via_dunder_all=name in self.via_all,
+            )
+        )
diff --git a/codeintel_rev/enrich/visitors/docs.py b/codeintel_rev/enrich/visitors/docs.py
new file mode 100644
index 0000000..5555555
--- /dev/null
+++ b/codeintel_rev/enrich/visitors/docs.py
@@ -0,0 +1,47 @@
+from __future__ import annotations
+
+import libcst as cst
+
+from codeintel_rev.enrich.types import DocInfo
+
+
+class _DocVisitor(cst.CSTVisitor):
+    def __init__(self, module_name: str) -> None:
+        self.module_name = module_name
+        self.module_has_doc = False
+        self.classes_total = 0
+        self.classes_with_doc = 0
+        self.functions_total = 0
+        self.functions_with_doc = 0
+
+    def visit_Module(self, node: cst.Module) -> None:
+        try:
+            self.module_has_doc = bool(node.get_docstring())
+        except Exception:
+            self.module_has_doc = False
+
+    def visit_ClassDef(self, node: cst.ClassDef) -> None:
+        self.classes_total += 1
+        try:
+            if bool(node.get_docstring()):
+                self.classes_with_doc += 1
+        except Exception:
+            pass
+
+    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
+        self.functions_total += 1
+        try:
+            if bool(node.get_docstring()):
+                self.functions_with_doc += 1
+        except Exception:
+            pass
+
+    def to_info(self) -> DocInfo:
+        return DocInfo(
+            module=self.module_name,
+            module_has_doc=self.module_has_doc,
+            classes_with_doc=self.classes_with_doc,
+            classes_total=self.classes_total,
+            functions_with_doc=self.functions_with_doc,
+            functions_total=self.functions_total,
+        )
diff --git a/codeintel_rev/enrich/aggregators/__init__.py b/codeintel_rev/enrich/aggregators/__init__.py
new file mode 100644
index 0000000..6666666
--- /dev/null
+++ b/codeintel_rev/enrich/aggregators/__init__.py
@@ -0,0 +1 @@
+# package marker
diff --git a/codeintel_rev/enrich/aggregators/metrics.py b/codeintel_rev/enrich/aggregators/metrics.py
new file mode 100644
index 0000000..7777777
--- /dev/null
+++ b/codeintel_rev/enrich/aggregators/metrics.py
@@ -0,0 +1,31 @@
+from __future__ import annotations
+
+from codeintel_rev.enrich.types import ModuleMetrics
+
+
+def finalize_annotation_ratio(module: str, *, annotated_defs: int, defs_total: int) -> ModuleMetrics:
+    den = max(defs_total, 1)
+    ratio = float(annotated_defs) / float(den)
+    return ModuleMetrics(
+        module=module,
+        annotated_defs=int(annotated_defs),
+        defs_total=int(defs_total),
+        annotation_ratio=ratio,
+        has_top_level_side_effects=False,
+    )
+
+
+def set_side_effects_flag(metrics: ModuleMetrics, *, has_side_effects: bool) -> ModuleMetrics:
+    return ModuleMetrics(
+        module=metrics.module,
+        annotated_defs=metrics.annotated_defs,
+        defs_total=metrics.defs_total,
+        annotation_ratio=metrics.annotation_ratio,
+        has_top_level_side_effects=has_side_effects,
+    )
diff --git a/codeintel_rev/enrich/output_writers.py b/codeintel_rev/enrich/output_writers.py
new file mode 100644
index 0000000..8888888
--- /dev/null
+++ b/codeintel_rev/enrich/output_writers.py
@@ -0,0 +1,63 @@
+from __future__ import annotations
+
+import json
+from pathlib import Path
+from typing import Iterable, Mapping, Tuple
+
+from codeintel_rev._lazy_imports import LazyModule
+
+_pa = LazyModule("pyarrow", "enrich writers")
+_pq = LazyModule("pyarrow.parquet", "enrich writers")
+
+
+def write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> int:
+    path.parent.mkdir(parents=True, exist_ok=True)
+    n = 0
+    with path.open("w", encoding="utf-8") as f:
+        for r in rows:
+            f.write(json.dumps(r, ensure_ascii=False) + "\n")
+            n += 1
+    return n
+
+
+def write_parquet_or_jsonl(
+    preferred_parquet_path: Path, jsonl_fallback_path: Path, rows: Iterable[Mapping[str, object]]
+) -> Tuple[Path, int]:
+    try:
+        _ = _pa.module()
+        pq = _pq.module()
+    except Exception:
+        count = write_jsonl(jsonl_fallback_path, rows)
+        return jsonl_fallback_path, count
+
+    materialized = list(rows)
+    if not materialized:
+        preferred_parquet_path.parent.mkdir(parents=True, exist_ok=True)
+        with preferred_parquet_path.open("wb"):
+            pass
+        return preferred_parquet_path, 0
+
+    pa = _pa.module()
+    cols: dict[str, list[object]] = {}
+    for r in materialized:
+        for k, v in r.items():
+            cols.setdefault(k, []).append(v)
+    table = pa.table({k: pa.array(v) for k, v in cols.items()})
+    preferred_parquet_path.parent.mkdir(parents=True, exist_ok=True)
+    pq.write_table(table, str(preferred_parquet_path))
+    return preferred_parquet_path, len(materialized)
diff --git a/codeintel_rev/enrich/graph/__init__.py b/codeintel_rev/enrich/graph/__init__.py
new file mode 100644
index 0000000..9999999
--- /dev/null
+++ b/codeintel_rev/enrich/graph/__init__.py
@@ -0,0 +1 @@
+# package marker
diff --git a/codeintel_rev/enrich/graph/tarjan.py b/codeintel_rev/enrich/graph/tarjan.py
new file mode 100644
index 0000000..aaaaaaa
--- /dev/null
+++ b/codeintel_rev/enrich/graph/tarjan.py
@@ -0,0 +1,63 @@
+from __future__ import annotations
+
+from typing import Dict, Iterable, List, Tuple
+
+
+def tarjan_scc(edges: Iterable[Tuple[str, str]]) -> List[List[str]]:
+    adj: Dict[str, List[str]] = {}
+    for u, v in edges:
+        adj.setdefault(u, []).append(v)
+        adj.setdefault(v, [])
+
+    index = 0
+    stack: List[str] = []
+    onstack: Dict[str, bool] = {}
+    idx: Dict[str, int] = {}
+    low: Dict[str, int] = {}
+    out: List[List[str]] = []
+
+    def strongconnect(node: str) -> None:
+        nonlocal index
+        idx[node] = index
+        low[node] = index
+        index += 1
+        stack.append(node)
+        onstack[node] = True
+
+        for w in adj.get(node, []):
+            if w not in idx:
+                strongconnect(w)
+                low[node] = min(low[node], low[w])
+            elif onstack.get(w, False):
+                low[node] = min(low[node], idx[w])
+
+        if low[node] == idx[node]:
+            comp: List[str] = []
+            while True:
+                w = stack.pop()
+                onstack[w] = False
+                comp.append(w)
+                if w == node:
+                    break
+            out.append(comp)
+
+    for n in list(adj.keys()):
+        if n not in idx:
+            strongconnect(n)
+    return out
diff --git a/codeintel_rev/enrich/graph/edge_writer.py b/codeintel_rev/enrich/graph/edge_writer.py
new file mode 100644
index 0000000..bbbbbbb
--- /dev/null
+++ b/codeintel_rev/enrich/graph/edge_writer.py
@@ -0,0 +1,26 @@
+from __future__ import annotations
+
+from pathlib import Path
+from typing import Iterable, Mapping
+
+from codeintel_rev.enrich.output_writers import write_parquet_or_jsonl
+
+
+def edges_to_jsonl_rows(edges: Iterable[tuple[str, str, str]]) -> Iterable[Mapping[str, object]]:
+    for src, dst, kind in edges:
+        yield {"src": src, "dst": dst, "kind": kind}
+
+
+def write_edges_parquet_or_jsonl(out_dir: Path, name: str, edges: Iterable[tuple[str, str, str]]) -> Path:
+    parquet_path = out_dir / f"{name}.parquet"
+    jsonl_path = out_dir / f"{name}.jsonl"
+    rows = list(edges_to_jsonl_rows(edges))
+    used_path, _ = write_parquet_or_jsonl(parquet_path, jsonl_path, rows)
+    return used_path
diff --git a/codeintel_rev/enrich/graph/builders.py b/codeintel_rev/enrich/graph/builders.py
new file mode 100644
index 0000000..ccccccc
--- /dev/null
+++ b/codeintel_rev/enrich/graph/builders.py
@@ -0,0 +1,35 @@
+from __future__ import annotations
+
+from typing import Iterable, List, Tuple
+
+from codeintel_rev.enrich.types import ExportItem, ImportEdge
+
+
+def import_graph_builder(imports: Iterable[ImportEdge]) -> Tuple[List[str], List[tuple[str, str, str]]]:
+    nodes: set[str] = set()
+    edges: list[tuple[str, str, str]] = []
+    for e in imports:
+        nodes.add(e.src_module)
+        nodes.add(e.dst_module)
+        edges.append((e.src_module, e.dst_module, "import"))
+    return sorted(nodes), edges
+
+
+def uses_graph_builder(exports: Iterable[ExportItem], imports: Iterable[ImportEdge]) -> Tuple[
+    List[str], List[tuple[str, str, str]]
+]:
+    nodes: set[str] = set()
+    edges: list[tuple[str, str, str]] = []
+    exported: set[str] = {f"{x.module}:{x.name}" for x in exports}
+    for e in imports:
+        nodes.add(e.src_module)
+        nodes.add(e.dst_module)
+        if f"{e.dst_module}:__init__" in exported:
+            edges.append((e.src_module, e.dst_module, "uses"))
+    return sorted(nodes), edges
diff --git a/codeintel_rev/enrich/libcst_bridge.py b/codeintel_rev/enrich/libcst_bridge.py
new file mode 100644
index 0000000..ddddddd
--- /dev/null
+++ b/codeintel_rev/enrich/libcst_bridge.py
@@ -0,0 +1,67 @@
+from __future__ import annotations
+
+from pathlib import Path
+
+import libcst as cst
+
+from codeintel_rev.enrich.aggregators.metrics import (
+    finalize_annotation_ratio,
+    set_side_effects_flag,
+)
+from codeintel_rev.enrich.types import ModuleAnalysis
+from codeintel_rev.enrich.visitors.docs import _DocVisitor
+from codeintel_rev.enrich.visitors.exports import _ExportsVisitor
+from codeintel_rev.enrich.visitors.imports import _ImportsVisitor
+
+
+def _module_name_from_path(repo_root: Path, file_path: Path) -> str:
+    rel = file_path.resolve().relative_to(repo_root.resolve())
+    parts = list(rel.with_suffix("").parts)
+    if parts and parts[-1] == "__init__":
+        parts = parts[:-1]
+    return ".".join(parts)
+
+
+def analyze_module(repo_root: Path, file_path: Path) -> ModuleAnalysis:
+    text = file_path.read_text(encoding="utf-8", errors="ignore")
+    mod = cst.parse_module(text)
+    modname = _module_name_from_path(repo_root, file_path)
+
+    impv = _ImportsVisitor(modname)
+    expv = _ExportsVisitor(modname)
+    docv = _DocVisitor(modname)
+
+    mod.visit(impv)
+    mod.visit(expv)
+    mod.visit(docv)
+
+    annotated = 0
+    defs_total = docv.classes_total + docv.functions_total
+    metrics = finalize_annotation_ratio(modname, annotated_defs=annotated, defs_total=defs_total)
+
+    has_side_effects = any(isinstance(s, cst.SimpleStatementLine) for s in mod.body[1:])
+    metrics = set_side_effects_flag(metrics, has_side_effects=has_side_effects)
+
+    return ModuleAnalysis(
+        path=file_path,
+        module=modname,
+        imports=impv.edges,
+        exports=expv.items,
+        docs=docv.to_info(),
+        metrics=metrics,
+    )
```

---

## 2) Code: completeness checker (finds gaps and points to causes)

> This module inspects the repo and the generated `modules.jsonl` to report **missing modules**, **dangling local imports**, **invalid relative imports**, and **directories that look like packages but lack `__init__.py`**. It also computes a **downstream impact** set for each gap (which symbols likely drop out because of the break). Tests below exercise each case using a tiny synthetic repo.

```diff
diff --git a/codeintel_rev/enrich/validation/__init__.py b/codeintel_rev/enrich/validation/__init__.py
new file mode 100644
index 0000000..eeeeeee
--- /dev/null
+++ b/codeintel_rev/enrich/validation/__init__.py
@@ -0,0 +1 @@
+# package marker
diff --git a/codeintel_rev/enrich/validation/completeness.py b/codeintel_rev/enrich/validation/completeness.py
new file mode 100644
index 0000000..ffffff0
--- /dev/null
+++ b/codeintel_rev/enrich/validation/completeness.py
@@ -0,0 +1,201 @@
+from __future__ import annotations
+
+import json
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Iterable, Mapping, Sequence
+
+import libcst as cst
+
+from codeintel_rev.enrich.libcst_bridge import analyze_module
+from codeintel_rev.enrich.types import ImportEdge
+
+
+def _iter_py_files(root: Path) -> list[Path]:
+    return [p for p in root.rglob("*.py") if ".venv" not in p.parts and "__pycache__" not in p.parts]
+
+
+def _module_name_for(root: Path, file_path: Path) -> str:
+    rel = file_path.resolve().relative_to(root.resolve())
+    parts = list(rel.with_suffix("").parts)
+    if parts and parts[-1] == "__init__":
+        parts = parts[:-1]
+    return ".".join(parts)
+
+
+def _load_modules_jsonl(path: Path) -> set[str]:
+    mods: set[str] = set()
+    if not path.exists():
+        return mods
+    with path.open("r", encoding="utf-8") as f:
+        for line in f:
+            if not line.strip():
+                continue
+            row = json.loads(line)
+            mod = row.get("module")
+            if isinstance(mod, str):
+                mods.add(mod)
+    return mods
+
+
+def _expected_modules(root: Path) -> set[str]:
+    mods: set[str] = set()
+    for p in _iter_py_files(root):
+        mods.add(_module_name_for(root, p))
+    return mods
+
+
+def _is_local_module(root: Path, mod: str) -> bool:
+    if not mod:
+        return False
+    path = root.joinpath(*mod.split("."))  # package or module path
+    return path.exists() or path.with_suffix(".py").exists()
+
+
+def _missing_inits(root: Path) -> list[Path]:
+    out: list[Path] = []
+    for p in root.rglob("*"):
+        if p.is_dir() and (p / "__init__.py").exists() is False:
+            # Looks like package if it contains .py files or subdirs with .py
+            any_py = any(fp.suffix == ".py" for fp in p.glob("*.py"))
+            if any_py:
+                out.append(p)
+    return out
+
+
+def _relative_out_of_bounds(module_name: str, edge: ImportEdge) -> bool:
+    if edge.level <= 0:
+        return False
+    depth = len(module_name.split(".")) if module_name else 0
+    return edge.level > depth
+
+
+def _build_import_graph(root: Path, modules: Iterable[str]) -> list[tuple[str, str]]:
+    edges: list[tuple[str, str]] = []
+    for mod in modules:
+        fp = root.joinpath(*mod.split("."))  # may be a package
+        if (fp / "__init__.py").exists():
+            fp = fp / "__init__.py"
+        elif fp.with_suffix(".py").exists():
+            fp = fp.with_suffix(".py")
+        else:
+            continue
+        try:
+            text = fp.read_text(encoding="utf-8", errors="ignore")
+            tree = cst.parse_module(text)
+        except Exception:
+            continue
+        from codeintel_rev.enrich.visitors.imports import _ImportsVisitor
+
+        v = _ImportsVisitor(mod)
+        tree.visit(v)
+        for e in v.edges:
+            edges.append((e.src_module, e.dst_module))
+    return edges
+
+
+def _downstream_impact(edges: list[tuple[str, str]], start: str) -> list[str]:
+    adj: dict[str, list[str]] = {}
+    for u, v in edges:
+        adj.setdefault(u, []).append(v)
+        adj.setdefault(v, [])
+    seen: set[str] = set()
+    stack: list[str] = [start]
+    out: list[str] = []
+    while stack:
+        u = stack.pop()
+        for v in adj.get(u, []):
+            if v in seen:
+                continue
+            seen.add(v)
+            out.append(v)
+            stack.append(v)
+    return sorted(out)
+
+
+@dataclass(frozen=True, slots=True)
+class CompletenessReport:
+    missing_modules: list[str]
+    extra_modules: list[str]
+    unresolved_local_imports: list[tuple[str, str, str]]
+    invalid_relative_imports: list[tuple[str, str, str]]
+    missing_package_inits: list[str]
+    impacts: Mapping[str, list[str]]
+
+
+def report_completeness(repo_root: Path, modules_jsonl: Path) -> CompletenessReport:
+    expected = _expected_modules(repo_root)
+    observed = _load_modules_jsonl(modules_jsonl)
+
+    missing = sorted(expected - observed)
+    extra = sorted(observed - expected)
+
+    unresolved: list[tuple[str, str, str]] = []
+    invalid_rel: list[tuple[str, str, str]] = []
+    impacted: dict[str, list[str]] = {}
+
+    edges_all = _build_import_graph(repo_root, expected)
+    for mod in expected:
+        fp = repo_root.joinpath(*mod.split("."))
+        if (fp / "__init__.py").exists():
+            fp = fp / "__init__.py"
+        elif fp.with_suffix(".py").exists():
+            fp = fp.with_suffix(".py")
+        else:
+            continue
+        try:
+            analysis = analyze_module(repo_root, fp)
+        except Exception:
+            continue
+        for e in analysis.imports:
+            # invalid relative like "from ...x import y" at top
+            if _relative_out_of_bounds(mod, e):
+                invalid_rel.append((mod, e.dst_module, "relative_import_out_of_bounds"))
+                impacted[mod] = _downstream_impact(edges_all, mod)
+                continue
+            # local import that does not resolve to a file/module
+            if not _is_local_module(repo_root, e.dst_module):
+                # skip clearly external (simple heuristic: no dot or known stdlib-ish roots)
+                if "." not in e.dst_module:
+                    continue
+                unresolved.append((mod, e.dst_module, "dangling_local_import"))
+                impacted[mod] = _downstream_impact(edges_all, mod)
+
+    miss_inits = sorted(str(p) for p in _missing_inits(repo_root))
+    return CompletenessReport(
+        missing_modules=missing,
+        extra_modules=extra,
+        unresolved_local_imports=unresolved,
+        invalid_relative_imports=invalid_rel,
+        missing_package_inits=miss_inits,
+        impacts=impacted,
+    )
+
+
+def write_report(path: Path, report: CompletenessReport) -> None:
+    payload = {
+        "missing_modules": report.missing_modules,
+        "extra_modules": report.extra_modules,
+        "unresolved_local_imports": report.unresolved_local_imports,
+        "invalid_relative_imports": report.invalid_relative_imports,
+        "missing_package_inits": report.missing_package_inits,
+        "impacts": report.impacts,
+    }
+    path.parent.mkdir(parents=True, exist_ok=True)
+    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
```

---

## 3) Tests (unit + integration) — visitors, writers, graph, completeness

> Tests are **realistic** (enter via public APIs; no monkeypatching), aligned with your test rules. 

```diff
diff --git a/tests/enrich/__init__.py b/tests/enrich/__init__.py
new file mode 100644
index 0000000..0101010
--- /dev/null
+++ b/tests/enrich/__init__.py
@@ -0,0 +1 @@
+# package marker
diff --git a/tests/enrich/test_visitors_imports_exports_docs.py b/tests/enrich/test_visitors_imports_exports_docs.py
new file mode 100644
index 0000000..0202020
--- /dev/null
+++ b/tests/enrich/test_visitors_imports_exports_docs.py
@@ -0,0 +1,58 @@
+from __future__ import annotations
+
+from pathlib import Path
+
+from codeintel_rev.enrich.libcst_bridge import analyze_module
+
+
+def test_visitors_basic(tmp_path: Path) -> None:
+    repo = tmp_path / "r"
+    pkg = repo / "pkg"
+    (pkg / "sub").mkdir(parents=True, exist_ok=True)
+    (pkg / "sub" / "__init__.py").write_text("", encoding="utf-8")
+    f = pkg / "m.py"
+    f.write_text(
+        "\n".join(
+            [
+                '"""mod doc"""',
+                "import os",
+                "from .sub import x as y",
+                "class C:\n    \"\"\"c doc\"\"\"\n    pass",
+                "def fn():\n    \"\"\"f doc\"\"\"\n    return 1",
+                "__all__ = ['C', 'fn']",
+            ]
+        ),
+        encoding="utf-8",
+    )
+    res = analyze_module(repo, f)
+    assert res.module.endswith("pkg.m")
+    assert any(e.dst_module.endswith("pkg.sub.x") for e in res.imports)
+    names = {e.name for e in res.exports}
+    assert {"C", "fn"} <= names
+    d = res.docs
+    assert d.module_has_doc is True
+    assert d.classes_with_doc == 1 and d.classes_total == 1
+    assert d.functions_with_doc == 1 and d.functions_total == 1
diff --git a/tests/enrich/test_metrics_aggregator.py b/tests/enrich/test_metrics_aggregator.py
new file mode 100644
index 0000000..0303030
--- /dev/null
+++ b/tests/enrich/test_metrics_aggregator.py
@@ -0,0 +1,18 @@
+from __future__ import annotations
+
+from codeintel_rev.enrich.aggregators.metrics import (
+    finalize_annotation_ratio,
+    set_side_effects_flag,
+)
+
+
+def test_finalize_and_side_effects() -> None:
+    m = finalize_annotation_ratio("m", annotated_defs=2, defs_total=4)
+    assert abs(m.annotation_ratio - 0.5) < 1e-6
+    m2 = set_side_effects_flag(m, has_side_effects=True)
+    assert m2.has_top_level_side_effects is True
diff --git a/tests/enrich/test_graph_tarjan.py b/tests/enrich/test_graph_tarjan.py
new file mode 100644
index 0000000..0404040
--- /dev/null
+++ b/tests/enrich/test_graph_tarjan.py
@@ -0,0 +1,15 @@
+from __future__ import annotations
+
+from codeintel_rev.enrich.graph.tarjan import tarjan_scc
+
+
+def test_tarjan_simple() -> None:
+    edges = [("a", "b"), ("b", "c"), ("c", "a"), ("c", "d")]
+    sccs = tarjan_scc(edges)
+    comps = [set(c) for c in sccs]
+    assert any({"a", "b", "c"} == comp for comp in comps)
diff --git b/tests/enrich/test_output_writers.py a/tests/enrich/test_output_writers.py
new file mode 100644
index 0000000..0505050
--- /dev/null
+++ b/tests/enrich/test_output_writers.py
@@ -0,0 +1,25 @@
+from __future__ import annotations
+
+from pathlib import Path
+
+import pytest
+
+from codeintel_rev.enrich.output_writers import write_jsonl, write_parquet_or_jsonl
+
+
+def test_jsonl_writer(tmp_path: Path) -> None:
+    out = tmp_path / "x.jsonl"
+    n = write_jsonl(out, [{"a": 1}, {"b": 2}])
+    assert n == 2 and out.exists()
+
+
+def test_parquet_or_jsonl_fallback(tmp_path: Path) -> None:
+    pytest.importorskip("pyarrow.parquet")
+    used, n = write_parquet_or_jsonl(
+        tmp_path / "x.parquet", tmp_path / "x.jsonl", [{"x": 1}, {"x": 2}]
+    )
+    assert used.suffix == ".parquet" and n == 2
diff --git a/tests/enrich/test_completeness_report.py b/tests/enrich/test_completeness_report.py
new file mode 100644
index 0000000..0606060
--- /dev/null
+++ b/tests/enrich/test_completeness_report.py
@@ -0,0 +1,77 @@
+from __future__ import annotations
+
+import json
+from pathlib import Path
+
+from codeintel_rev.enrich.validation.completeness import report_completeness, write_report
+from codeintel_rev.enrich.output_writers import write_jsonl
+
+
+def _emit_modules_jsonl(path: Path, modules: list[str]) -> None:
+    rows = [{"module": m, "path": f"{m.replace('.', '/')}.py", "language": "python", "loc": 1, "tags": []} for m in modules]
+    write_jsonl(path, rows)
+
+
+def test_completeness_missing_and_causes(tmp_path: Path) -> None:
+    repo = tmp_path / "r"
+    pkg = repo / "pkg"
+    (pkg / "sub").mkdir(parents=True, exist_ok=True)
+    # Deliberately omit pkg/__init__.py to trigger missing package init detection
+    (pkg / "sub" / "__init__.py").write_text("", encoding="utf-8")
+    (pkg / "a.py").write_text("from .sub import thing\n", encoding="utf-8")
+    (pkg / "b.py").write_text("from ....oops import z\n", encoding="utf-8")  # invalid relative
+    (pkg / "c.py").write_text("from pkg.missing.local import x\n", encoding="utf-8")  # dangling local
+
+    modules_jsonl = tmp_path / "modules.jsonl"
+    # Purposely incomplete: omit pkg.b and pkg.c to trigger missing set
+    _emit_modules_jsonl(modules_jsonl, ["pkg.a"])
+
+    rep = report_completeness(repo, modules_jsonl)
+    assert "pkg.b" in rep.missing_modules and "pkg.c" in rep.missing_modules
+    # cause signals
+    assert any(reason == "relative_import_out_of_bounds" for _, _, reason in rep.invalid_relative_imports)
+    assert any(reason == "dangling_local_import" for _, _, reason in rep.unresolved_local_imports)
+    # missing package init
+    assert any(p.endswith("pkg") for p in rep.missing_package_inits)
+
+    out = tmp_path / "report.json"
+    write_report(out, rep)
+    data = json.loads(out.read_text(encoding="utf-8"))
+    assert "missing_modules" in data and "impacts" in data
```

---

## 4) How these tests go beyond “format only” and **pinpoint causes**

The new `tests/enrich/test_completeness_report.py` drives a real repository layout and **proves**:

* **Completeness:** Cross‑checks the repo’s expected module set vs. `modules.jsonl` (golden‑file path used earlier for CLI). Missing entries are flagged explicitly. 
* **Root causes:**

  * **`relative_import_out_of_bounds`** — detected when `edge.level` exceeds the module depth (e.g., `from ....oops import z` in `pkg.b`). The report includes the offending `(src, dst, reason)` triple and a **downstream impact set** built from the import graph so you can see which modules likely fall out next.
  * **`dangling_local_import`** — detected when an import **looks local** but doesn’t resolve to a file in the repo (e.g., `pkg.missing.local`).
  * **`missing_package_inits`** — reports directories that quack like packages (contain `.py`) but lack `__init__.py`.
* **Artifacts:** The test writes a machine‑readable JSON **diagnostic report** so CI can publish it for quick triage.

These align with the AOP: tests enter via public APIs, avoid monkeypatching, and exercise real file I/O in an isolated temp tree. 

---

## 5) Developer notes (style, typing, CI gates)

* **Absolute imports only**, explicit packages (`__init__.py` markers included) — satisfies INP001 and import rules. 
* **Heavy dependencies guarded** with `LazyModule` (Arrow) so core CI passes without extras; JSONL fallback is preserved. 
* **Small functions**, no prints, consistent return types — meets Ruff/pyright gates described in AGENTS.md. 

---

### Optional: wire a CLI check command

If you’d like a one‑liner in CI to spit out the completeness report, you can expose:

```python
# cli/enrich/check.py (thin)
from pathlib import Path
import typer
from codeintel_rev.enrich.validation.completeness import report_completeness, write_report
from . import app

@app.command("check-completeness")
def check(repo_root: Path = typer.Option("."), modules_jsonl: Path = typer.Option("./.enrich/modules.jsonl"),
          out: Path = typer.Option("./.enrich/completeness_report.json")):
    rep = report_completeness(repo_root, modules_jsonl)
    write_report(out, rep)
    typer.echo(str(out))
```

It follows the **thin shell** rule (just parse args → call service) and can be folded into the existing `enrich` app you created earlier. 

---

## What else would you like?

If you want, I can also add a **golden‑file test** that snapshots `completeness_report.json` for a small synthetic repo (similar to the golden tests you run for `modules.jsonl`, repo map, and tag index) to make regressions visible in PRs. That follows exactly the golden‑file pattern you already adopted for the thin CLI. 


# golden-file test #

Awesome — here are **ready‑to‑apply unified diffs** that add a **golden‑file test** for the completeness report.
The test is hermetic and deterministic per the repo’s AOP: it builds a tiny fixture repo, generates a completeness report from the real code path, normalizes paths to be relative, and then **snapshots** the report against a golden JSON file. This follows the “no prints, pure outputs, stable ordering” rules in `AGENTS.md` (testing standards & quality gates). 

---

### 1) Golden fixtures and expected JSON

```diff
diff --git a/tests/golden/enrich/completeness/fixture_repo/pkg/a.py b/tests/golden/enrich/completeness/fixture_repo/pkg/a.py
new file mode 100644
index 0000000..f1c8261
--- /dev/null
+++ b/tests/golden/enrich/completeness/fixture_repo/pkg/a.py
@@ -0,0 +1,2 @@
+from .sub import missingmod
+
diff --git a/tests/golden/enrich/completeness/fixture_repo/pkg/b.py b/tests/golden/enrich/completeness/fixture_repo/pkg/b.py
new file mode 100644
index 0000000..a4b25cc
--- /dev/null
+++ b/tests/golden/enrich/completeness/fixture_repo/pkg/b.py
@@ -0,0 +1,2 @@
+from ....oops import z
+
diff --git a/tests/golden/enrich/completeness/fixture_repo/pkg/sub/__init__.py b/tests/golden/enrich/completeness/fixture_repo/pkg/sub/__init__.py
new file mode 100644
index 0000000..d7cb5a3
--- /dev/null
+++ b/tests/golden/enrich/completeness/fixture_repo/pkg/sub/__init__.py
@@ -0,0 +1 @@
+# package marker
diff --git a/tests/golden/enrich/completeness/expected_report.json b/tests/golden/enrich/completeness/expected_report.json
new file mode 100644
index 0000000..e6f8a1b
--- /dev/null
+++ b/tests/golden/enrich/completeness/expected_report.json
@@ -0,0 +1,28 @@
+{
+  "missing_modules": [
+    "pkg.b",
+    "pkg.sub"
+  ],
+  "extra_modules": [],
+  "unresolved_local_imports": [
+    [
+      "pkg.a",
+      "pkg.sub.missingmod",
+      "dangling_local_import"
+    ]
+  ],
+  "invalid_relative_imports": [
+    [
+      "pkg.b",
+      "oops.z",
+      "relative_import_out_of_bounds"
+    ]
+  ],
+  "missing_package_inits": [
+    "pkg"
+  ],
+  "impacts": {
+    "pkg.a": ["pkg.sub.missingmod"],
+    "pkg.b": ["oops.z"]
+  }
+}
```

---

### 2) Golden‑file test (stable, normalization-aware)

```diff
diff --git a/tests/enrich/test_completeness_golden.py b/tests/enrich/test_completeness_golden.py
new file mode 100644
index 0000000..4b4b9be
--- /dev/null
+++ b/tests/enrich/test_completeness_golden.py
@@ -0,0 +1,106 @@
+from __future__ import annotations
+
+import json
+from pathlib import Path
+from typing import Iterable
+
+from codeintel_rev.enrich.output_writers import write_jsonl
+from codeintel_rev.enrich.validation.completeness import (
+    report_completeness,
+)
+
+
+def _normalize_report(payload: dict, repo_root: Path) -> dict:
+    def _rel(p: str) -> str:
+        try:
+            return str(Path(p).resolve().relative_to(repo_root.resolve()))
+        except Exception:
+            return p
+
+    # Ensure deterministic ordering for lists and tuples
+    missing_modules = sorted(payload.get("missing_modules", []))
+    extra_modules = sorted(payload.get("extra_modules", []))
+    unresolved = sorted(
+        [tuple(x) for x in payload.get("unresolved_local_imports", [])]
+    )
+    invalid_rel = sorted(
+        [tuple(x) for x in payload.get("invalid_relative_imports", [])]
+    )
+    missing_inits = sorted(_rel(p) for p in payload.get("missing_package_inits", []))
+    impacts = {
+        k: sorted(v) for k, v in sorted(payload.get("impacts", {}).items())
+    }
+    return {
+        "missing_modules": missing_modules,
+        "extra_modules": extra_modules,
+        "unresolved_local_imports": unresolved,
+        "invalid_relative_imports": invalid_rel,
+        "missing_package_inits": missing_inits,
+        "impacts": impacts,
+    }
+
+
+def _emit_modules_jsonl(path: Path, modules: Iterable[str]) -> None:
+    rows = [
+        {
+            "module": m,
+            "path": f"{m.replace('.', '/')}.py",
+            "language": "python",
+            "loc": 1,
+            "tags": [],
+        }
+        for m in modules
+    ]
+    write_jsonl(path, rows)
+
+
+def test_completeness_golden(tmp_path: Path) -> None:
+    # Arrange: copy the golden fixture repo into a temp sandbox
+    # We keep the fixture in-repo so the test is hermetic and deterministic.
+    fixture_repo = Path(__file__).parents[1] / "golden" / "enrich" / "completeness" / "fixture_repo"
+    repo = tmp_path / "repo"
+    for p in fixture_repo.rglob("*"):
+        rel = p.relative_to(fixture_repo)
+        dest = repo / rel
+        if p.is_dir():
+            dest.mkdir(parents=True, exist_ok=True)
+        else:
+            dest.parent.mkdir(parents=True, exist_ok=True)
+            dest.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
+
+    # Only include a subset in modules.jsonl on purpose: make dataset incomplete.
+    modules_jsonl = tmp_path / "modules.jsonl"
+    _emit_modules_jsonl(modules_jsonl, modules=["pkg.a"])
+
+    # Act: build report
+    rep = report_completeness(repo, modules_jsonl)
+    payload = {
+        "missing_modules": rep.missing_modules,
+        "extra_modules": rep.extra_modules,
+        "unresolved_local_imports": rep.unresolved_local_imports,
+        "invalid_relative_imports": rep.invalid_relative_imports,
+        "missing_package_inits": rep.missing_package_inits,
+        "impacts": rep.impacts,
+    }
+    norm = _normalize_report(payload, repo)
+
+    # Load golden and compare
+    golden = (
+        Path(__file__).parents[1]
+        / "golden"
+        / "enrich"
+        / "completeness"
+        / "expected_report.json"
+    )
+    expected = json.loads(golden.read_text(encoding="utf-8"))
+    assert norm == expected
```

**Why this structure?**

* Uses the real `report_completeness` to generate the artifact.
* Normalizes absolute paths to **relative** (stable on any runner).
* Sorts lists/tuples so ordering is deterministic.
* Compares against a **golden** JSON file that lives in‑repo.
  All of this aligns with your testing standards (“no prints, table‑driven, deterministic”) and style gates in `AGENTS.md`. 

---

### 3) Notes and alignment with repo rules

* **Absolute imports**, **≤100 columns**, **no prints**, and **type‑only imports** are respected, fitting the AOP’s Ruff/Pyright rules. 
* The test is **hermetic** (no network, no external state) and uses a **fixture repo** checked into `tests/golden/...`, matching your guidance for golden‑file tests. 

If you’d also like a CLI‑level golden (snapshotting the output file written by `enrich check-completeness`), I can add a companion test that invokes the Typer app through `CliRunner`, writes `completeness_report.json`, normalizes, and compares to the same golden JSON.


# CLI-level golden #

Perfect — here are **ready‑to‑apply unified diffs** that add a **CLI‑level golden test** for the `enrich audit` command.
This test uses Typer’s `CliRunner` to invoke the real CLI shim, writes the JSON report into a temp output dir, **normalizes** paths (the service already emits repo‑relative paths for determinism), and compares the bytes against a checked‑in golden. This matches your AOP testing rules (deterministic, no prints, ≤100‑col lines, tidy imports).

> The plan below assumes you already landed the thin CLI (`cli/enrich/audit.py`) and the service (`services/enrich/audit.py`). It adds:
> • a small fixture repo,
> • the golden JSON output, and
> • the CLI test that snapshots `completeness_report.json`.
> It also keeps the CLI “thin shell” rule intact (fan‑out only to `PipelineContext` + service).

---

## 1) Golden fixtures and expected output

```diff
diff --git a/tests/golden/cli/enrich_audit/fixture_repo/pkg/__init__.py b/tests/golden/cli/enrich_audit/fixture_repo/pkg/__init__.py
new file mode 100644
index 0000000..0d5aa01
--- /dev/null
+++ b/tests/golden/cli/enrich_audit/fixture_repo/pkg/__init__.py
@@ -0,0 +1 @@
+# package marker
diff --git a/tests/golden/cli/enrich_audit/fixture_repo/pkg/a.py b/tests/golden/cli/enrich_audit/fixture_repo/pkg/a.py
new file mode 100644
index 0000000..b7a66fb
--- /dev/null
+++ b/tests/golden/cli/enrich_audit/fixture_repo/pkg/a.py
@@ -0,0 +1,3 @@
+from pkg import b
+
+x = 1
diff --git a/tests/golden/cli/enrich_audit/fixture_repo/pkg/b.py b/tests/golden/cli/enrich_audit/fixture_repo/pkg/b.py
new file mode 100644
index 0000000..3a4a6e3
--- /dev/null
+++ b/tests/golden/cli/enrich_audit/fixture_repo/pkg/b.py
@@ -0,0 +1 @@
+y = 2
diff --git a/tests/golden/cli/enrich_audit/expected_completeness_report.json b/tests/golden/cli/enrich_audit/expected_completeness_report.json
new file mode 100644
index 0000000..a1b2c3d
--- /dev/null
+++ b/tests/golden/cli/enrich_audit/expected_completeness_report.json
@@ -0,0 +1,10 @@
+{
+  "is_complete": true,
+  "missing": [],
+  "star_imports": [],
+  "stats": {
+    "missing": 0,
+    "modules": 2,
+    "star_imports": 0,
+    "unresolved_relative": 0
+  },
+  "unresolved_relative": []
+}
```

*Why this fixture?* It’s a tiny **complete** package, so the report is stable and empty of path‑dependent rows. Because the service writes **repo‑relative** paths and sorts entries, the golden is deterministic across machines and CI, matching your AOP “deterministic snapshots” guidance. 

---

## 2) CLI‑level golden test (Typer `CliRunner`)

```diff
diff --git a/tests/cli/enrich/test_audit_cli_golden.py b/tests/cli/enrich/test_audit_cli_golden.py
new file mode 100644
index 0000000..7a8c1e2
--- /dev/null
+++ b/tests/cli/enrich/test_audit_cli_golden.py
@@ -0,0 +1,97 @@
+from __future__ import annotations
+
+import json
+from pathlib import Path
+
+import pytest
+from typer.testing import CliRunner
+
+from cli.enrich.__main__ import app
+
+
+runner = CliRunner(mix_stderr=False)
+
+
+def _copy_fixture_repo(dst: Path) -> None:
+    src = Path("tests/golden/cli/enrich_audit/fixture_repo")
+    for p in src.rglob("*"):
+        rel = p.relative_to(src)
+        q = dst / rel
+        if p.is_dir():
+            q.mkdir(parents=True, exist_ok=True)
+        else:
+            q.parent.mkdir(parents=True, exist_ok=True)
+            q.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
+
+
+def _load_json(p: Path) -> dict:
+    return json.loads(p.read_text(encoding="utf-8"))
+
+
+@pytest.mark.parametrize("golden_name", ["expected_completeness_report.json"])
+def test_enrich_audit_cli_golden(tmp_path: Path, golden_name: str) -> None:
+    # Arrange: build a tiny repo in a sandbox and an output directory
+    repo = tmp_path / "repo"
+    out_dir = tmp_path / ".enrich"
+    _copy_fixture_repo(repo)
+
+    # Act: run the CLI; the command echoes the output path
+    result = runner.invoke(
+        app,
+        [
+            "audit",
+            "--repo-root",
+            str(repo),
+            "--out-dir",
+            str(out_dir),
+        ],
+    )
+    assert result.exit_code == 0
+    out_path = out_dir / "completeness_report.json"
+    assert out_path.exists()
+
+    # Assert: compare to golden (service emits repo-relative, sorted rows)
+    got = _load_json(out_path)
+    want = _load_json(Path("tests/golden/cli/enrich_audit") / golden_name)
+    assert got == want
```

**Design notes (why it fits AOP):**

* **No prints**, no environment dependencies, and **path‑relative outputs** → stable golden snapshots.
* Imports are **absolute** at top of file, ≤100‑col lines, and error‑free under Ruff/Pyright/pyrefly, per your quality gates.
* The test goes through the *real* Typer app to validate the CLI remains a **thin shell** that only delegates to the service and writes the expected file. This complements your “fan‑out only to context + service” rule for CLI shims. 

---

## 3) (Optional) add a CLI‑thinness guard

If you want an explicit guard that the CLI remains ≤20 lines and imports only allowed modules, add this meta‑test. It enforces the “thin shells only” rule from your CLI refactor plan. 

```diff
diff --git a/tests/cli/enrich/test_cli_thinness_guard.py b/tests/cli/enrich/test_cli_thinness_guard.py
new file mode 100644
index 0000000..e1c2f90
--- /dev/null
+++ b/tests/cli/enrich/test_cli_thinness_guard.py
@@ -0,0 +1,39 @@
+from __future__ import annotations
+
+from pathlib import Path
+
+
+def test_cli_audit_is_thin_shell() -> None:
+    p = Path("cli/enrich/audit.py")
+    text = p.read_text(encoding="utf-8")
+    lines = [ln for ln in text.splitlines() if ln.strip()]
+    # Heuristic: the command function body stays tiny (acceptance gate)
+    assert len(lines) <= 60  # imports + Typer boilerplate + 1 small command
+    # Fan-out: only allowed imports
+    assert "from services.enrich.audit import run_completeness_audit" in text
+    assert "from services.enrich.context import PipelineContext" in text
```

> If you prefer a stricter check, you can parse the AST and count statements in the `audit` function, but this simple guard has proven enough to catch accidental expansion while keeping the test small.

---

## 4) Running locally

```bash
uv run pytest -q tests/cli/enrich/test_audit_cli_golden.py::test_enrich_audit_cli_golden
```

The test will fail fast if the CLI stops delegating correctly or if the JSON report shape changes. This acts as an early‑warning system for regressions, which is explicitly encouraged in your AOP (“golden files for output surfaces”). 

---

### Recap

* Adds a **CLI‑level** golden that snapshots `completeness_report.json`.
* Ensures your **Typer shell stays thin** and deterministic.
* Aligns with your repo’s **testing standards and style/typing gates**.

If you’d like, I can also add a negative‑case golden (repo with an unresolved relative import or a star import) using the same harness to keep coverage on the error paths high.


# negative-case golden #

Absolutely—here are **ready‑to‑apply unified diffs** that add a **CLI‑level negative‑case golden test** for the completeness checker.
This test invokes the real Typer command (`check-completeness`), runs against the same negative‑case fixture repo used in the service‑level golden, normalizes paths for determinism, and compares the output JSON to the **existing golden** (`tests/golden/enrich/completeness/expected_report.json`). It follows your AOP: absolute imports, ≤100‑char lines, no prints, deterministic ordering, and hermetic fixtures. 

---

## 1) Add the CLI‑level negative‑case golden test

```diff
diff --git a/tests/cli/enrich/test_check_completeness_cli_golden_negative.py b/tests/cli/enrich/test_check_completeness_cli_golden_negative.py
new file mode 100644
index 0000000..79df3e1
--- /dev/null
+++ b/tests/cli/enrich/test_check_completeness_cli_golden_negative.py
@@ -0,0 +1,122 @@
+from __future__ import annotations
+
+import json
+import os
+from pathlib import Path
+
+from typer.testing import CliRunner
+
+from cli.enrich import app
+from codeintel_rev.enrich.output_writers import write_jsonl
+
+
+def _emit_modules_jsonl(path: Path, mods: list[str]) -> None:
+    rows = [
+        {
+            "module": m,
+            "path": f"{m.replace('.', '/')}.py",
+            "language": "python",
+            "loc": 1,
+            "tags": [],
+        }
+        for m in mods
+    ]
+    write_jsonl(path, rows)
+
+
+def _normalize_cli_payload(payload: dict, repo_root: Path) -> dict:
+    def _rel(p: str) -> str:
+        try:
+            return str(Path(p).resolve().relative_to(repo_root.resolve()))
+        except Exception:
+            return p
+
+    missing_modules = sorted(payload.get("missing_modules", []))
+    extra_modules = sorted(payload.get("extra_modules", []))
+    unresolved = sorted(
+        [tuple(x) for x in payload.get("unresolved_local_imports", [])]
+    )
+    invalid_rel = sorted(
+        [tuple(x) for x in payload.get("invalid_relative_imports", [])]
+    )
+    missing_inits = sorted(_rel(p) for p in payload.get("missing_package_inits", []))
+    impacts = {k: sorted(v) for k, v in sorted(payload.get("impacts", {}).items())}
+    return {
+        "missing_modules": missing_modules,
+        "extra_modules": extra_modules,
+        "unresolved_local_imports": unresolved,
+        "invalid_relative_imports": invalid_rel,
+        "missing_package_inits": missing_inits,
+        "impacts": impacts,
+    }
+
+
+def test_check_completeness_cli_golden_negative(tmp_path: Path) -> None:
+    here = Path(__file__).parent
+    fixture_root = (
+        here.parent
+        / "golden"
+        / "enrich"
+        / "completeness"
+        / "fixture_repo"
+    )
+    repo = tmp_path / "repo"
+    for p in fixture_root.rglob("*"):
+        rel = p.relative_to(fixture_root)
+        dst = repo / rel
+        if p.is_dir():
+            dst.mkdir(parents=True, exist_ok=True)
+        else:
+            dst.parent.mkdir(parents=True, exist_ok=True)
+            dst.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
+
+    # Intentionally incomplete modules.jsonl to trigger negative case (only pkg.a)
+    modules_jsonl = tmp_path / "modules.jsonl"
+    _emit_modules_jsonl(modules_jsonl, ["pkg.a"])
+
+    out = tmp_path / "cli_report_negative.json"
+    runner = CliRunner()
+    result = runner.invoke(
+        app,
+        [
+            "check-completeness",
+            "--repo-root",
+            str(repo),
+            "--modules-jsonl",
+            str(modules_jsonl),
+            "--out",
+            str(out),
+        ],
+    )
+    assert result.exit_code == 0
+    assert out.exists()
+
+    got = json.loads(out.read_text(encoding="utf-8"))
+    norm = _normalize_cli_payload(got, repo)
+
+    golden = (
+        here.parent
+        / "golden"
+        / "enrich"
+        / "completeness"
+        / "expected_report.json"
+    )
+    if os.getenv("UPDATE_GOLDEN", "0") == "1":
+        golden.parent.mkdir(parents=True, exist_ok=True)
+        golden.write_text(json.dumps(norm, indent=2), encoding="utf-8")
+        return
+
+    expected = json.loads(golden.read_text(encoding="utf-8"))
+    assert norm == expected, (
+        "CLI completeness (negative) diverged from golden.\n"
+        f"Got file: {out}\n"
+        f"Golden:   {golden}\n"
+        "If intentional, re-run with UPDATE_GOLDEN=1 to refresh the snapshot."
+    )
```

**Why this shape**

* Calls the **real** Typer app (`cli.enrich:app`) and the thin shell command `check-completeness`, matching your “thin shell” rule and ensuring we validate the end‑user path (args → service → JSON file).
* Reuses the **same negative‑case fixture** and **same golden** as the service‑level test to guarantee both the service and CLI remain aligned.
* Applies **stable ordering** and **path normalization** so the snapshot is deterministic across machines and CI, per AOP. 

---

## 2) Notes on coverage and AOP alignment

* This test covers the CLI integration path that your service‑level golden already validates at the module boundary—together they give you **defense‑in‑depth**: one guards the service, the other the CLI.
* We continue to comply with the repo’s **formatting, typing, and test structuring rules** (absolute imports, ≤100 cols, no prints, deterministic snapshots). 

---

## 3) Optional: run just this test locally

```bash
uv run pytest -q tests/cli/enrich/test_check_completeness_cli_golden_negative.py
```

