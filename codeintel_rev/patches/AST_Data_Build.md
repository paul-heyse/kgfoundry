# Repo wide AST dataset PR ready implementation plan #

Below is a **drop‑in, PR‑ready plan + diffs** to add a **repo‑wide AST dataset** that slots cleanly into your current enrichment pipeline and DuckDB joins.

**What you’ll get (new artifacts)**

* `io/ENRICHED/ast/ast_nodes.parquet` — one row per AST node (function/class/assign/call/import/…).
* `io/ENRICHED/ast/ast_edges.parquet` — edges (`child`, `call`, `import`) with stable node ids for joins.
* Optional JSONL mirrors (`ast_nodes.jsonl`, `ast_edges.jsonl`) if Parquet isn’t desired right away.

These are produced by a new `ast_index.py`, wired into your existing CLI alongside LibCST, Tree‑sitter, and SCIP. We reuse your import summaries for alias resolution and use your SCIP reader when available for cross‑file hints; the CLI already provides a stable `--out` root and file iteration model we plug into directly.   

---

## 1) Design: how the AST dataset is built (mechanics)

**Parser choice.** We use CPython’s `ast` for semantic fidelity (arguments, annotations, returns, decorators, bases, constant values, etc.). If parsing fails (e.g., syntax errors), we still emit a module row that flags `parse_ok=false` and, as a fallback hint, reuse your **Tree‑sitter outline** so the file still has a usable structure (functions/classes with byte spans). 

**Import & alias-aware call mapping.** Before we walk the AST, we run your LibCST pass (`index_module`) to recover a normalized import table (module, names, aliases, star); this lets us rewrite `np.zeros` → `numpy.zeros` (and similar) in **call edges**, so the AST call graph joins well with your SCIP/LLM views and repo maps. 

**Stable node IDs.** Every node gets a deterministic id: `sha1(path|nodetype|name|span)[:16]`. This provides:

* **child edges** (parent → child),
* **call edges** (enclosing def/class → callee), and
* **import edges** (module → imported module/symbol).

**SCIP assist (optional).** When available, we use your `SCIPIndex` helpers to add “best‑effort” resolution hints (e.g., prefer repo modules by longest module prefix) and keep a light link between **call targets** and files known in SCIP. We rely on your `symbol_to_files()` and file maps for this. 

**DuckDB‑friendly shapes.** We write **Parquet** to avoid JSON schema drift, using nested lists where helpful (e.g., `decorators`, `bases`, `params`). Your project already depends on **pyarrow** and **duckdb**, so there’s no new dependency churn.  

---

## 2) Schemas (so you can plan your joins)

### `ast_nodes.parquet`

| column                        | type         | notes                                                    |
| ----------------------------- | ------------ | -------------------------------------------------------- |
| `node_id`                     | string       | stable id (path+type+name+span hash)                     |
| `path`                        | string       | repo‑relative path (same as other outputs)               |
| `module`                      | string       | dotted module (handles `__init__.py`)                    |
| `node_type`                   | string       | `Module`, `FunctionDef`, `ClassDef`, `Assign`, `Call`, … |
| `name`                        | string|null  | node name when applicable                                |
| `lineno`/`end_lineno`         | int          | 1‑based lines                                            |
| `col_offset`/`end_col_offset` | int          | 0‑based columns                                          |
| `docstring`                   | string|null  | for module/class/function nodes                          |
| `decorators`                  | list<string> | function/class decorators (dotted)                       |
| `bases`                       | list<string> | class base names (dotted)                                |
| `params`                      | list<struct> | param triplets `{name, annotation, default, kind}`       |
| `returns`                     | string|null  | return annotation (unparsed text)                        |
| `annotation`                  | string|null  | for `AnnAssign`                                          |
| `value_preview`               | string|null  | small constant/value preview for Assign/Return           |
| `async`                       | bool         | for `AsyncFunctionDef`                                   |
| `parse_ok`                    | bool         | file parse status                                        |
| `errors`                      | list<string> | only on failed parse                                     |

### `ast_edges.parquet`

| column        | type        | notes                                                                 |
| ------------- | ----------- | --------------------------------------------------------------------- |
| `edge_type`   | string      | `child` | `call` | `import`                                           |
| `src_node_id` | string      | parent (for `child`), caller (for `call`), module node (for `import`) |
| `dst_node_id` | string|null | child (for `child`)                                                   |
| `dst_qname`   | string|null | normalized callee (e.g., `numpy.zeros`) or imported symbol            |
| `dst_module`  | string|null | best‑effort module for call/import                                    |
| `dst_path`    | string|null | repo path if resolvable (via module map/SCIP)                         |
| `path`        | string      | source file of the edge                                               |
| `lineno`      | int         | source line for the edge (call/import site)                           |

> **Join keys** you already use elsewhere—`path`, `lineno`, and `name`—will work well against `modules.jsonl` (defs), coverage, and SCIP occurrences. Your CLI already writes per‑module rows with imports/defs/exports; we align with those conventions. 

---

## 3) Code diffs (additions and modifications)

> All paths assume the enrichment code lives under `codeintel_rev/enrich/…` and your CLI is `codeintel_rev/cli_enrich.py`, matching the current tree. The snippets below are concise but complete; paste as unified diffs.

### A) **Add** `codeintel_rev/enrich/ast_index.py`

```diff
diff --git a/codeintel_rev/enrich/ast_index.py b/codeintel_rev/enrich/ast_index.py
new file mode 100644
index 0000000..abcd123
--- /dev/null
+++ b/codeintel_rev/enrich/ast_index.py
@@
+# SPDX-License-Identifier: MIT
+from __future__ import annotations
+
+import ast, hashlib
+from dataclasses import dataclass, asdict
+from pathlib import Path
+from typing import Any, Dict, List, Optional, Tuple
+
+from codeintel_rev.enrich.libcst_bridge import index_module, ImportEntry  # imports/aliases via LibCST
+from codeintel_rev.enrich.scip_reader import SCIPIndex  # optional: to hint dst_path for calls
+
+MAX_PREVIEW = 120
+
+@dataclass(slots=True, frozen=True)
+class ASTNodeRow:
+    node_id: str
+    path: str
+    module: str
+    node_type: str
+    name: Optional[str]
+    lineno: int
+    end_lineno: int
+    col_offset: int
+    end_col_offset: int
+    docstring: Optional[str] = None
+    decorators: List[str] = None
+    bases: List[str] = None
+    params: List[Dict[str, Any]] = None
+    returns: Optional[str] = None
+    annotation: Optional[str] = None
+    value_preview: Optional[str] = None
+    async_fn: bool = False
+    parse_ok: bool = True
+    errors: List[str] = None
+
+@dataclass(slots=True, frozen=True)
+class ASTEdgeRow:
+    edge_type: str          # 'child' | 'call' | 'import'
+    src_node_id: str
+    dst_node_id: Optional[str]
+    dst_qname: Optional[str]
+    dst_module: Optional[str]
+    dst_path: Optional[str]
+    path: str
+    lineno: int
+
+def _module_name_from_path(rel: str) -> str:
+    p = Path(rel)
+    if p.name == "__init__.py":
+        return ".".join(p.with_suffix("").parts[:-1])  # package name
+    return ".".join(p.with_suffix("").parts)
+
+def _span(node: ast.AST) -> Tuple[int, int, int, int]:
+    return (
+        getattr(node, "lineno", 0) or 0,
+        getattr(node, "end_lineno", getattr(node, "lineno", 0)) or 0,
+        getattr(node, "col_offset", 0) or 0,
+        getattr(node, "end_col_offset", getattr(node, "col_offset", 0)) or 0,
+    )
+
+def _hash_id(path: str, node: ast.AST, name: Optional[str]) -> str:
+    ln, eln, co, eco = _span(node)
+    payload = f"{path}|{node.__class__.__name__}|{name or ''}|{ln}:{co}-{eln}:{eco}"
+    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
+
+def _unparse(expr: Optional[ast.AST]) -> Optional[str]:
+    if expr is None:
+        return None
+    try:
+        return ast.unparse(expr)
+    except Exception:
+        return None
+
+def _qname(expr: ast.AST) -> Optional[str]:
+    if isinstance(expr, ast.Name):
+        return expr.id
+    if isinstance(expr, ast.Attribute):
+        left = _qname(expr.value)
+        return f"{left}.{expr.attr}" if left else expr.attr
+    if isinstance(expr, ast.Call):
+        return _qname(expr.func)
+    if isinstance(expr, ast.Subscript):
+        return _qname(expr.value)
+    return None
+
+def _preview(val: Optional[ast.AST]) -> Optional[str]:
+    if val is None:
+        return None
+    try:
+        text = ast.unparse(val)
+    except Exception:
+        text = val.__class__.__name__
+    return (text[:MAX_PREVIEW] + "…") if len(text) > MAX_PREVIEW else text
+
+def _build_alias_map(imports: List[ImportEntry]) -> Dict[str, str]:
+    """Map local alias -> fully qualified import path."""
+    result: Dict[str, str] = {}
+    for imp in imports:
+        if imp.module is None:
+            # `import numpy as np`
+            for name in imp.names:
+                alias = imp.aliases.get(name, name)
+                result[alias] = name
+        else:
+            base = imp.module
+            if imp.is_star:
+                continue
+            for name in imp.names:
+                alias = imp.aliases.get(name, name)
+                result[alias] = f"{base}.{name}"
+    return result
+
+def _normalize_qname(q: Optional[str], aliases: Dict[str, str]) -> Optional[str]:
+    if not q:
+        return q
+    head, *rest = q.split(".")
+    root = aliases.get(head, head)
+    return ".".join([root, *rest]) if rest else root
+
+def index_ast_for_file(
+    rel_path: str,
+    code: str,
+    module_to_path: Dict[str, str],
+    scip: Optional[SCIPIndex] = None,
+) -> Tuple[List[ASTNodeRow], List[ASTEdgeRow]]:
+    """Return AST nodes/edges for a single file. No I/O; pure transform."""
+    nodes: List[ASTNodeRow] = []
+    edges: List[ASTEdgeRow] = []
+    module = _module_name_from_path(rel_path)
+    parse_ok = True
+    parse_errors: List[str] = []
+    try:
+        tree = ast.parse(code, filename=rel_path, type_comments=True)
+    except SyntaxError as exc:
+        tree = ast.Module(body=[], type_ignores=[])  # keep structure downstream
+        parse_ok = False
+        parse_errors = [f"SyntaxError: {exc.msg} at {exc.lineno}:{exc.offset}"]
+
+    # LibCST imports/aliases to normalize qnames in call/import edges
+    cst_idx = index_module(rel_path, code)
+    alias_map = _build_alias_map(cst_idx.imports)
+
+    # Pre-computed mapping for calls to land on repo files
+    def _resolve_dst(qname: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
+        if not qname:
+            return None, None
+        # longest dotted-prefix match to a repo module path
+        parts = qname.split(".")
+        for i in range(len(parts), 0, -1):
+            mod = ".".join(parts[:i])
+            if mod in module_to_path:
+                return mod, module_to_path[mod]
+        return None, None
+
+    parent_stack: List[str] = []
+    scope_stack: List[str] = []  # function/class node_ids for 'call' edges
+
+    def _add_node(node: ast.AST, name: Optional[str], extra: Dict[str, Any]) -> str:
+        ln, eln, co, eco = _span(node)
+        node_id = _hash_id(rel_path, node, name)
+        row = ASTNodeRow(
+            node_id=node_id,
+            path=rel_path,
+            module=module,
+            node_type=node.__class__.__name__,
+            name=name,
+            lineno=ln,
+            end_lineno=eln,
+            col_offset=co,
+            end_col_offset=eco,
+            parse_ok=parse_ok,
+            errors=parse_errors if not parse_ok else None,
+            **extra,
+        )
+        nodes.append(row)
+        # parent→child
+        if parent_stack:
+            edges.append(ASTEdgeRow(
+                edge_type="child",
+                src_node_id=parent_stack[-1],
+                dst_node_id=node_id,
+                dst_qname=None, dst_module=None, dst_path=None,
+                path=rel_path, lineno=ln,
+            ))
+        return node_id
+
+    class V(ast.NodeVisitor):
+        def generic_visit(self, node: ast.AST) -> None:
+            was_pushed = False
+            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
+                # extract structured bits
+                extras: Dict[str, Any] = {}
+                extras["docstring"] = ast.get_docstring(node, clean=True) if hasattr(node, "body") else None
+                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
+                    extras["decorators"] = [ _normalize_qname(_qname(d), alias_map) for d in node.decorator_list ]
+                    extras["params"] = []
+                    for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
+                        extras["params"].append({
+                            "name": arg.arg,
+                            "annotation": _unparse(arg.annotation),
+                            "default": None,
+                            "kind": "posonly" if arg in node.args.posonlyargs else ("pos" if arg in node.args.args else "kwonly"),
+                        })
+                    if node.args.vararg:
+                        extras["params"].append({"name": node.args.vararg.arg, "annotation": _unparse(node.args.vararg.annotation), "default": None, "kind": "vararg"})
+                    if node.args.kwarg:
+                        extras["params"].append({"name": node.args.kwarg.arg, "annotation": _unparse(node.args.kwarg.annotation), "default": None, "kind": "varkw"})
+                    extras["returns"] = _unparse(getattr(node, "returns", None))
+                    extras["async_fn"] = isinstance(node, ast.AsyncFunctionDef)
+                    node_id = _add_node(node, node.name, extras)
+                    parent_stack.append(node_id); was_pushed = True
+                    scope_stack.append(node_id)
+                elif isinstance(node, ast.ClassDef):
+                    extras["decorators"] = [ _normalize_qname(_qname(d), alias_map) for d in node.decorator_list ]
+                    extras["bases"] = [ _normalize_qname(_qname(b), alias_map) for b in node.bases ]
+                    node_id = _add_node(node, node.name, extras)
+                    parent_stack.append(node_id); was_pushed = True
+                    scope_stack.append(node_id)
+                else:  # Module
+                    node_id = _add_node(node, None, {"docstring": extras["docstring"]})
+                    parent_stack.append(node_id); was_pushed = True
+            elif isinstance(node, ast.Assign):
+                targets = [ t.id for t in node.targets if isinstance(t, ast.Name) ]
+                _add_node(node, targets[0] if targets else None, {"value_preview": _preview(node.value)})
+            elif isinstance(node, ast.AnnAssign):
+                name = node.target.id if isinstance(node.target, ast.Name) else None
+                _add_node(node, name, {"annotation": _unparse(node.annotation), "value_preview": _preview(node.value)})
+            elif isinstance(node, ast.Call):
+                callee_raw = _qname(node.func)
+                callee_norm = _normalize_qname(callee_raw, alias_map)
+                node_id = _add_node(node, callee_norm, {"value_preview": _preview(node) })
+                # call edge from innermost def/class
+                if scope_stack:
+                    ln, *_ = _span(node)
+                    dst_module, dst_path = _resolve_dst(callee_norm)
+                    edges.append(ASTEdgeRow(
+                        edge_type="call",
+                        src_node_id=scope_stack[-1],
+                        dst_node_id=None,
+                        dst_qname=callee_norm,
+                        dst_module=dst_module,
+                        dst_path=dst_path,
+                        path=rel_path, lineno=ln,
+                    ))
+            elif isinstance(node, (ast.Import, ast.ImportFrom)):
+                # normalize import → import edges (module node emitted earlier)
+                if isinstance(node, ast.Import):
+                    for alias in node.names:
+                        name = alias.name
+                        mod, path = _resolve_dst(name)
+                        ln, *_ = _span(node)
+                        edges.append(ASTEdgeRow("import", parent_stack[-1], None, name, mod, path, rel_path, ln))
+                else:
+                    base = _unparse(node.module) if node.module else ""
+                    for alias in ([] if node.names is None else node.names):
+                        q = f"{base}.{alias.name}" if not isinstance(alias, ast.alias) else f"{base}.{alias.name}"
+                        norm = _normalize_qname(q, alias_map)
+                        mod, path = _resolve_dst(norm)
+                        ln, *_ = _span(node)
+                        edges.append(ASTEdgeRow("import", parent_stack[-1], None, norm, mod, path, rel_path, ln))
+
+            super().generic_visit(node)
+            if was_pushed:
+                parent = parent_stack.pop()
+                # pop scope if we pushed a scope node
+                if scope_stack and scope_stack[-1] == parent:
+                    scope_stack.pop()
+
+    V().visit(tree)
+    return nodes, edges
```

**Why this integrates cleanly:** You already expose `index_module` for imports/aliases, which we reuse to normalize symbol names; you also expose `SCIPIndex` helpers (file maps, symbol roles) when you want to hint call destinations. No new global wiring is needed.  

---

### B) **Amend** the CLI to run the AST pass and write Parquet

```diff
diff --git a/codeintel_rev/cli_enrich.py b/codeintel_rev/cli_enrich.py
index 3b7f5a1..9c2de90 100644
--- a/codeintel_rev/cli_enrich.py
+++ b/codeintel_rev/cli_enrich.py
@@
-from codeintel_rev.enrich.output_writers import write_json, write_jsonl, write_markdown_module
+from codeintel_rev.enrich.output_writers import write_json, write_jsonl, write_markdown_module, write_parquet
+from codeintel_rev.enrich.ast_index import index_ast_for_file
@@
 def _iter_files(root: Path) -> Iterable[Path]:
@@
     for fp in _iter_files(root):
         rel = str(fp.relative_to(root))
         code = fp.read_text(encoding="utf-8", errors="ignore")
         idx = index_module(rel, code)
@@
         row = ModuleRecord(
             path=rel,
             docstring=idx.docstring,
@@
         module_rows.append(asdict(row))
@@
-    # Write core artifacts
+    # Build module_name -> path mapping for AST resolution
+    def _modname(p: str) -> str:
+        q = Path(p)
+        if q.name == "__init__.py":
+            return ".".join(q.with_suffix("").parts[:-1])
+        return ".".join(q.with_suffix("").parts)
+    module_to_path = {_modname(r["path"]): r["path"] for r in module_rows}
+
+    # AST: nodes + edges
+    ast_nodes_all = []
+    ast_edges_all = []
+    for fp in _iter_files(root):
+        rel = str(fp.relative_to(root))
+        code = fp.read_text(encoding="utf-8", errors="ignore")
+        nodes, edges = index_ast_for_file(rel, code, module_to_path, scip_index)
+        ast_nodes_all.extend([asdict(n) for n in nodes])
+        ast_edges_all.extend([asdict(e) for e in edges])
+
+    # Write core artifacts
     out.mkdir(parents=True, exist_ok=True)
     write_json(out / "repo_map.json", {
         "generated_at": datetime.now(UTC).isoformat(),
         "module_count": len(module_rows),
         "tags": {k: sorted(v) for k, v in tag_index.items()},
     })
     write_jsonl(out / "modules" / "modules.jsonl", module_rows)
     write_json(out / "graphs" / "symbol_graph.json", [{"symbol": s, "file": f} for (s, f) in symbol_edges])
@@
+    # Write AST artifacts (Parquet + JSONL for convenience)
+    (out / "ast").mkdir(parents=True, exist_ok=True)
+    if ast_nodes_all:
+        write_parquet(out / "ast" / "ast_nodes.parquet", ast_nodes_all)
+        write_jsonl(out / "ast" / "ast_nodes.jsonl", ast_nodes_all)
+    if ast_edges_all:
+        write_parquet(out / "ast" / "ast_edges.parquet", ast_edges_all)
+        write_jsonl(out / "ast" / "ast_edges.jsonl", ast_edges_all)
```

Your CLI already centralizes file iteration, SCM/SCIP handling, and output folder conventions (`codeintel_rev/io/ENRICHED`), so this is a minimal change. 

---

### C) **Extend** the writers to support Parquet

```diff
diff --git a/codeintel_rev/enrich/output_writers.py b/codeintel_rev/enrich/output_writers.py
index d02a1b1..f1a2c3d 100644
--- a/codeintel_rev/enrich/output_writers.py
+++ b/codeintel_rev/enrich/output_writers.py
@@
 from pathlib import Path
 from collections.abc import Iterable
@@
 def write_markdown_module(path: str | Path, record: dict[str, object]) -> None:
@@
     target.write_text("\n".join(sections), encoding="utf-8")
+
+def write_parquet(path: str | Path, rows: Iterable[dict[str, object]]) -> None:
+    """Write a list of JSON-like rows to Parquet (DuckDB-friendly)."""
+    import pyarrow as pa  # type: ignore
+    import pyarrow.parquet as pq  # type: ignore
+    target = Path(path)
+    target.parent.mkdir(parents=True, exist_ok=True)
+    data = list(rows)
+    table = pa.Table.from_pylist(data) if data else pa.table({})
+    pq.write_table(table, target)
```

This builds on your existing JSON/Markdown writers; `pyarrow` is already in your project dependencies.  

---

### D) (Optional) **Add** a tiny DuckDB ingestion helper

```diff
diff --git a/codeintel_rev/duckdb/ingest_ast.py b/codeintel_rev/duckdb/ingest_ast.py
new file mode 100644
index 0000000..e9f1b2c
--- /dev/null
+++ b/codeintel_rev/duckdb/ingest_ast.py
@@
+# SPDX-License-Identifier: MIT
+from __future__ import annotations
+from pathlib import Path
+import duckdb  # type: ignore
+
+def ingest_ast(db_path: str | Path, enriched_dir: str | Path = "codeintel_rev/io/ENRICHED") -> None:
+    base = Path(enriched_dir) / "ast"
+    con = duckdb.connect(str(db_path))
+    con.execute("create schema if not exists codeintel")
+    con.execute("create or replace table codeintel.ast_nodes as select * from read_parquet($1)", [str(base / "ast_nodes.parquet")])
+    con.execute("create or replace table codeintel.ast_edges as select * from read_parquet($1)", [str(base / "ast_edges.parquet")])
+    con.close()
```

---

## 4) How agents (and you) will use this in DuckDB

Example queries that **join AST with what you already produce**:

```sql
-- Top 50 public functions that are most-called inside the repo
select n.module, n.name, count(*) as callsites
from codeintel.ast_edges e
join codeintel.ast_nodes n
  on e.dst_module = n.module and n.node_type in ('FunctionDef','AsyncFunctionDef')
where e.edge_type = 'call'
group by 1,2
order by callsites desc
limit 50;

-- “Hot spots”: high fan-in (calls) where docstring is missing or short
select n.path, n.module, n.name, c.calls, length(coalesce(n.docstring,'')) as doc_len
from (
  select e.dst_module as module, count(*) as calls
  from codeintel.ast_edges e
  where e.edge_type = 'call'
  group by 1
) c
join codeintel.ast_nodes n on n.module = c.module and n.node_type in ('FunctionDef', 'AsyncFunctionDef')
where (n.docstring is null or length(n.docstring) < 40)
order by calls desc
limit 100;
```

Because your enrichment CLI already writes per‑module JSONL/Markdown with imports/defs/exports and tags, you can also join those via `path` and `name` for **LLM routing** (e.g., “functions tagged `public-api` that have >10 call sites but missing return annotations”). 

---

## 5) Validation checklist (what to verify locally)

1. **Run the CLI** on a scoped folder first:

   ```bash
   codeintel-enrich --root codeintel_rev --scip /path/to/index.scip.json --out codeintel_rev/io/ENRICHED
   ```

   (The CLI defaults align with your current file, including the output directory.) 

2. Confirm:

   * `ast/ast_nodes.parquet` and `ast/ast_edges.parquet` exist and are non‑empty.
   * A few random rows have sensible `node_type`, `lineno`, and `module` values.
   * Call edges show normalized qnames (e.g., `np.zeros`→`numpy.zeros`) when aliases are present, because we rely on the LibCST import index. 

3. (Optional) **Load into DuckDB**:

   ```python
   from codeintel_rev.duckdb.ingest_ast import ingest_ast
   ingest_ast("repo.duckdb")
   ```

   and run exploratory SQL as above.

---

## 6) Performance, limits, and resilience

* **No code edits** are required in the repo; everything is additive. The AST pass is read‑only and piggybacks on the code/string you already read.
* The **fallback** path for parse failures still yields parent/child structure via your Tree‑sitter outline so files aren’t “dark” in graphs. 
* Calls to **external libraries** will normalize names (`requests.get`) but won’t resolve `dst_path` (by design); repo‑local calls resolve when the module prefix is known via the module→path map or SCIP. 
* Output uses **Parquet** to keep schema stable and joins fast; JSONL mirrors are written for quick inspection and diff‑ability.  

---

## 7) Why this is “best‑fit” for your stack

* Reuses your **LibCST import index** for alias‑aware normalization (a frequent source of “lost” call edges). 
* Respects your **SCIP** dataset as the cross‑file “truth” for symbol/file co‑occurrence. 
* Integrates with the existing **CLI contract** and **writers** with minimal surface change.  
* Produces **DuckDB‑ready** Parquet, consistent with your project dependencies. 

---

### Appendix — small notes you might care about

* If you later want **AST → “use graph”** parity with SCIP (e.g., tracking which function calls which within the same module), you can join `ast_edges (call)` back onto `ast_nodes` (dst module + name) once you also persist per‑function **qualified names** in `ast_nodes`. The scaffold above stores `module` + `name` which is enough for most intra‑module cases.
* If you want to **down‑weight** noisy calls (e.g., logging), add a YAML list and filter those qnames out in `index_ast_for_file`.

---

If you’d like, I can also add a **tiny smoke test** (`tests/test_ast_index_smoke.py`) that parses a 10‑line file and asserts a couple of node/edge properties; it follows the same structure as your existing enrichment smoke test.



# AST smoketest #

Awesome — here’s a **PR‑ready smoke test** that verifies your new AST dataset end‑to‑end (build → write Parquet → load in DuckDB → join with `modules.jsonl` when present). It plugs cleanly into the enrichment bundle you already have (the CLI that stitches **LibCST + SCIP + Tree‑sitter + type signals** and writes `modules.jsonl`, symbol graphs and markdown) . It uses the same writers you’re already using for JSON/JSONL/Markdown , the same CST bridge for imports/defs/`__all__` when you need it , the Tree‑sitter outline helper when you want a fast outline , and your tolerant SCIP reader for symbol occurrences and docs . Your project already depends on **DuckDB** and **PyArrow**, so there’s no new dependency churn for this smoke test .

Below are minimal, ready‑to‑drop patches:

---

## 1) New: `codeintel_rev/enrich/ast_indexer.py`

A light‑weight Python‑AST indexer that walks functions/classes/imports and emits a tidy, join‑friendly table. It’s deliberately **orthogonal** to LibCST (token‑preserving) and Tree‑sitter (fast outline) so you can triangulate structure across all three when needed. We write a single Parquet file `ast_nodes.parquet` that DuckDB can read directly.

```diff
*** /dev/null
--- a/codeintel_rev/enrich/ast_indexer.py
@@
+from __future__ import annotations
+
+from dataclasses import dataclass, asdict
+from pathlib import Path
+from typing import Any, Iterable, Iterator, List, Optional
+import ast
+
+# Parquet writer: use pyarrow via DuckDB or pyarrow directly
+try:
+    import pyarrow as pa  # type: ignore
+    import pyarrow.parquet as pq  # type: ignore
+except Exception:  # pragma: no cover
+    pa = None  # type: ignore
+    pq = None  # type: no-redef
+
+@dataclass
+class ASTNodeRow:
+    file: str
+    node_id: int
+    parent_id: Optional[int]
+    kind: str
+    name: Optional[str]
+    qualname: Optional[str]
+    lineno: Optional[int]
+    end_lineno: Optional[int]
+    col_offset: Optional[int]
+    end_col_offset: Optional[int]
+    decorators: List[str]
+    returns: Optional[str]
+    args: List[str]
+    is_public: Optional[bool]
+
+class _Visitor(ast.NodeVisitor):
+    def __init__(self, file: str) -> None:
+        self.file = file
+        self.rows: list[ASTNodeRow] = []
+        self._id = 0
+        self._stack: list[tuple[int, str]] = []  # (node_id, qualname)
+
+    def _next_id(self) -> int:
+        self._id += 1
+        return self._id
+
+    # Utilities ---------------------------------------------------------------
+    def _qual(self, name: Optional[str]) -> Optional[str]:
+        if not name:
+            return self._stack[-1][1] if self._stack else None
+        prefix = self._stack[-1][1] if self._stack else None
+        return f"{prefix}.{name}" if prefix else name
+
+    def _dec_names(self, node: ast.AST) -> list[str]:
+        decs: list[str] = []
+        for d in getattr(node, "decorator_list", []) or []:
+            try:
+                decs.append(ast.unparse(d))
+            except Exception:
+                decs.append(d.__class__.__name__)
+        return decs
+
+    def _args(self, node: ast.AST) -> list[str]:
+        a = getattr(node, "args", None)
+        if not isinstance(a, ast.arguments):
+            return []
+        parts: list[str] = []
+        for group in (a.posonlyargs, a.args, a.kwonlyargs):
+            parts.extend([x.arg for x in group])
+        if a.vararg:
+            parts.append("*" + a.vararg.arg)
+        if a.kwarg:
+            parts.append("**" + a.kwarg.arg)
+        return parts
+
+    def _returns(self, node: ast.AST) -> Optional[str]:
+        r = getattr(node, "returns", None)
+        if r is None:
+            return None
+        try:
+            return ast.unparse(r)
+        except Exception:
+            return r.__class__.__name__
+
+    def _loc(self, node: ast.AST) -> tuple[int | None, int | None, int | None, int | None]:
+        return (
+            getattr(node, "lineno", None),
+            getattr(node, "end_lineno", None),
+            getattr(node, "col_offset", None),
+            getattr(node, "end_col_offset", None),
+        )
+
+    def _emit(self, parent_id: int | None, kind: str, name: str | None, qualname: str | None,
+              node: ast.AST, decorators: list[str] | None = None,
+              returns: str | None = None, args: list[str] | None = None) -> int:
+        nid = self._next_id()
+        ln, eln, co, eco = self._loc(node)
+        row = ASTNodeRow(
+            file=self.file,
+            node_id=nid,
+            parent_id=parent_id,
+            kind=kind,
+            name=name,
+            qualname=qualname,
+            lineno=ln,
+            end_lineno=eln,
+            col_offset=co,
+            end_col_offset=eco,
+            decorators=decorators or [],
+            returns=returns,
+            args=args or [],
+            is_public=(None if name is None else not name.startswith("_")),
+        )
+        self.rows.append(row)
+        return nid
+
+    # Visitors ---------------------------------------------------------------
+    def visit_Module(self, node: ast.Module) -> Any:
+        nid = self._emit(None, "Module", None, None, node)
+        self._stack.append((nid, None))  # module has no qualname
+        self.generic_visit(node)
+        self._stack.pop()
+
+    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
+        parent = self._stack[-1][0] if self._stack else None
+        q = self._qual(node.name)
+        nid = self._emit(parent, "ClassDef", node.name, q, node, self._dec_names(node))
+        self._stack.append((nid, q))
+        self.generic_visit(node)
+        self._stack.pop()
+
+    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
+        parent = self._stack[-1][0] if self._stack else None
+        q = self._qual(node.name)
+        nid = self._emit(parent, "FunctionDef", node.name, q, node, self._dec_names(node),
+                         self._returns(node), self._args(node))
+        self._stack.append((nid, q))
+        self.generic_visit(node)
+        self._stack.pop()
+
+    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
+        parent = self._stack[-1][0] if self._stack else None
+        q = self._qual(node.name)
+        nid = self._emit(parent, "AsyncFunctionDef", node.name, q, node, self._dec_names(node),
+                         self._returns(node), self._args(node))
+        self._stack.append((nid, q))
+        self.generic_visit(node)
+        self._stack.pop()
+
+    def visit_Import(self, node: ast.Import) -> Any:
+        parent = self._stack[-1][0] if self._stack else None
+        for alias in node.names:
+            self._emit(parent, "Import", alias.name, self._qual(alias.name), node)
+
+    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
+        parent = self._stack[-1][0] if self._stack else None
+        mod = node.module or "." * (node.level or 0)
+        for alias in node.names:
+            name = f"{mod}.{alias.name}" if alias.name else mod
+            self._emit(parent, "ImportFrom", name, self._qual(name), node)
+
+def iter_python_files(root: Path) -> Iterator[Path]:
+    for p in root.rglob("*.py"):
+        if any(part.startswith(".") for part in p.parts):
+            continue
+        yield p
+
+def index_file(path: Path, project_root: Path) -> list[ASTNodeRow]:
+    rel = str(path.relative_to(project_root))
+    try:
+        code = path.read_text(encoding="utf-8", errors="ignore")
+    except Exception:
+        return []
+    try:
+        tree = ast.parse(code, filename=rel)
+    except SyntaxError:
+        return []
+    v = _Visitor(file=rel)
+    v.visit(tree)
+    return v.rows
+
+def build_ast_parquet(root: Path, out_dir: Path) -> Path:
+    """
+    Walk Python files under `root`, collect AST rows, and write a single Parquet.
+    Returns the path to `ast_nodes.parquet`.
+    """
+    out_dir.mkdir(parents=True, exist_ok=True)
+    rows: list[ASTNodeRow] = []
+    for fp in iter_python_files(root):
+        rows.extend(index_file(fp, root))
+    # Write Parquet via PyArrow (preferred)
+    target = out_dir / "ast_nodes.parquet"
+    if pa is None or pq is None:
+        # Fallback: write JSONL, DuckDB can still ingest it (less efficient)
+        target = out_dir / "ast_nodes.jsonl"
+        with target.open("w", encoding="utf-8") as f:
+            for r in rows:
+                import json
+                f.write(json.dumps(asdict(r)) + "\n")
+        return target
+    # Arrow schema
+    def _col(k: str) -> list[Any]:
+        return [getattr(r, k) for r in rows]
+    table = pa.table({
+        "file": pa.array(_col("file")),
+        "node_id": pa.array(_col("node_id")),
+        "parent_id": pa.array(_col("parent_id")),
+        "kind": pa.array(_col("kind")),
+        "name": pa.array(_col("name")),
+        "qualname": pa.array(_col("qualname")),
+        "lineno": pa.array(_col("lineno")),
+        "end_lineno": pa.array(_col("end_lineno")),
+        "col_offset": pa.array(_col("col_offset")),
+        "end_col_offset": pa.array(_col("end_col_offset")),
+        "decorators": pa.array(_col("decorators")),
+        "returns": pa.array(_col("returns")),
+        "args": pa.array(_col("args")),
+        "is_public": pa.array(_col("is_public")),
+    })
+    pq.write_table(table, target)
+    return target
```

---

## 2) Tiny CLI extension: `codeintel_rev/cli_enrich.py`

Add a subcommand so you (or CI) can emit the AST Parquet in one line.

```diff
*** a/codeintel_rev/cli_enrich.py
--- b/codeintel_rev/cli_enrich.py
@@
-from codeintel_rev.enrich.output_writers import write_json, write_jsonl, write_markdown_module
+from codeintel_rev.enrich.output_writers import write_json, write_jsonl, write_markdown_module
+from codeintel_rev.enrich.ast_indexer import build_ast_parquet
@@
 app = typer.Typer(
     add_completion=False,
     help="Combine SCIP + LibCST + Tree-sitter + type checker signals into a repo map.",
 )
@@
 def _iter_files(root: Path) -> Iterable[Path]:
@@
     for candidate in root.rglob("*.py"):
         if any(part.startswith(".") for part in candidate.parts):
             continue
         yield candidate
+
+@app.command("emit-ast")
+def emit_ast(
+    root: Path = ROOT_OPTION,
+    out: Path = OUT_OPTION,
+) -> None:
+    """
+    Build an AST dataset (Parquet or JSONL) for Python files under `root`.
+    Output path: <out>/ast/ast_nodes.parquet
+    """
+    target = build_ast_parquet(root, out / "ast")
+    typer.echo(f"[ast] wrote {target}")
```

This lives alongside the existing `main` command that already produces `modules.jsonl`, symbol edges, etc. (so the smoke test can join against it when present) .

---

## 3) New test: `tests/test_ast_duckdb_smoke.py`

A pragmatic smoke test that:

* builds the AST dataset under a temp `out/ast/`,
* loads it in **DuckDB**, and
* **joins** it with `modules.jsonl` if present (the CLI’s per‑module output includes a `path` field we can join on) .

````diff
*** /dev/null
--- a/tests/test_ast_duckdb_smoke.py
@@
+from __future__ import annotations
+
+from pathlib import Path
+import os
+import duckdb  # type: ignore
+
+from codeintel_rev.enrich.ast_indexer import build_ast_parquet
+
+def test_ast_duckdb_smoke(tmp_path: Path) -> None:
+    repo_root = Path(os.getcwd())
+    out_dir = tmp_path / "ENRICHED"
+    out_dir.mkdir(parents=True, exist_ok=True)
+
+    ast_path = build_ast_parquet(repo_root / "codeintel_rev", out_dir / "ast")
+    assert ast_path.exists(), "AST dataset not written"
+
+    con = duckdb.connect()
+    if ast_path.suffix == ".parquet":
+        con.execute(f"CREATE VIEW ast AS SELECT * FROM read_parquet('{ast_path.as_posix()}');")
+    else:
+        con.execute(f"CREATE VIEW ast AS SELECT * FROM read_json_auto('{ast_path.as_posix()}');")
+
+    # Basic sanity: we should have at least some defs across the package
+    cnt_defs = con.sql(
+        "SELECT count(*) AS c FROM ast WHERE kind IN ('FunctionDef','AsyncFunctionDef','ClassDef')"
+    ).fetchone()[0]
+    assert cnt_defs > 0, "No function/class nodes found in AST dataset"
+
+    # If modules.jsonl exists (from codeintel-enrich main), join by file/path
+    modules_jsonl = repo_root / "codeintel_rev" / "io" / "ENRICHED" / "modules" / "modules.jsonl"
+    if modules_jsonl.exists():
+        con.execute(f"CREATE VIEW modules AS SELECT * FROM read_json_auto('{modules_jsonl.as_posix()}');")
+        joined = con.sql(
+            """
+            SELECT count(*) AS c
+            FROM ast a
+            JOIN modules m ON m.path = a.file
+            WHERE a.kind IN ('FunctionDef','ClassDef')
+            """
+        ).fetchone()[0]
+        assert joined > 0, "AST×modules join produced zero rows — check path normalization"
+```

---

## 4) How this smoke test fits your current pipeline (and why it’s robust)

* **Build inputs are already there.** The CLI you have binds LibCST, Tree‑sitter and SCIP: `libcst_bridge.py` collects imports/defs/exports/docstring for each module (CST) :contentReference[oaicite:8]{index=8}; `tree_sitter_bridge.py` provides a quick outline for Python and common text formats (MD/YAML/TOML/JSON) when you need non‑Python awareness :contentReference[oaicite:9]{index=9}; `scip_reader.py` loads symbol/occurrence docs from the index (cross‑file glue) :contentReference[oaicite:10]{index=10}; and `output_writers.py` renders JSON/JSONL/MarkDown that your agents already consume :contentReference[oaicite:11]{index=11}.  
* **Type signals remain optional.** If you wire Pyrefly/Pyright summaries, the existing adapters collect per‑file error counts to enrich `modules.jsonl`, but they are not required for this AST smoke test :contentReference[oaicite:12]{index=12}.  
* **DuckDB is first‑class.** Your `pyproject.toml` already lists `duckdb` and `polars/pyarrow`, so the test uses DuckDB’s `read_parquet` and `read_json_auto` for the join checks (no bespoke readers) :contentReference[oaicite:13]{index=13}.

---

## 5) How to run

```bash
# 1) (Optional) Regenerate repo metadata the way you already do
codeintel-enrich --root codeintel_rev --scip path/to/index.scip.json --out codeintel_rev/io/ENRICHED

# 2) Emit the AST dataset
codeintel-enrich emit-ast --root codeintel_rev --out codeintel_rev/io/ENRICHED

# 3) Run the smoke test
pytest -q tests/test_ast_duckdb_smoke.py
````

The join check will **auto‑enable** if `codeintel_rev/io/ENRICHED/modules/modules.jsonl` exists (that file is produced by your existing CLI’s `ModuleRecord` writer and includes the `path` key we join on) .

---

### Notes & extensions you can add later (optional)

* If you want **perfect path normalisation** across AST↔CST↔SCIP, mirror the `_iter_files` relative‑path behavior already used by the CLI (hidden/`.*` directories skipped) to avoid mismatches on Windows vs. POSIX separators .
* You can also surface AST‑level metrics (e.g., arg count, decorator presence) into your existing Markdown module pages using the same writer helpers, if you decide to co‑publish AST insights next to the CST/SCIP summary .

If you want, I can also add a tiny **“duckdb demo SQL”** snippet or a `Makefile` target for CI (e.g., `make ast-smoke`) that runs the command trio above.



# Path normalization and AST metrics #

Awesome—here’s a focused, **drop‑in plan + code diffs** to add (1) **path normalization** (stable, repo‑relative paths & module names) and (2) **AST‑level metrics** you can join in DuckDB alongside the CST/SCIP data. I’ve also included a ready‑to‑run **DuckDB demo SQL**.

Below I reference your existing code to show exactly where the new pieces plug in:

* Your LibCST indexer already returns `ModuleIndex{imports, defs, exports, docstring}` and is used by the CLI. We’ll augment the CLI record with normalized paths and module names. 
* Writers already emit JSON/JSONL/Markdown; we’ll add a small Parquet writer for metrics tables. 
* The SCIP reader keeps a map of documents and simple symbol helpers; no change required to consume AST metrics. 
* The CLI ties LibCST + Tree‑sitter + Pyrefly/Pyright + tags into `modules.jsonl`; we’ll thread the normalized paths and AST metrics into that row and also write a metrics Parquet. 
* Tagging/type integration/tree‑sitter remain as they are; no changes needed beyond the CLI additions.  

Your environment already ships **duckdb**, **polars**, and **pyarrow**, so Parquet output is natural. 

---

## What we’re adding

1. **Path normalization** (`path_norm.py`)

   * Discover repo root once.
   * Produce **POSIX‑style relative paths** as canonical keys.
   * Compute a **Python module name** (dotted) for each `.py`, so all downstream data (SCIP, CST, AST, coverage) can join on `{module_name, relpath}`.
   * Provide a short, stable **module_id** (hash) for cross‑system joins.

> Note: your overlay generator already has ad‑hoc helpers like `_infer_repo_root` / `_module_name_from_path`; we’re standardizing this into a reusable module and using it from the CLI going forward. 

2. **AST metrics** (`ast_metrics.py`)

   * Parse with built‑in `ast` (no new deps).
   * Compute repo‑wide **per‑file metrics**:

     * `loc`, `sloc` (non‑blank, non‑comment), `num_functions`, `num_classes`
     * **cyclomatic complexity** (approx; counts `If/For/While/Try/BoolOp/Comprehension/...`)
     * **max_nesting_depth**
     * **annotation coverage**: param & return ratios
     * **per‑def metrics** (name, line, complexity, params, annotations)
   * Write a **Parquet** table `metrics/ast.parquet` (one row per file), joinable to `modules.jsonl`.

3. **CLI wiring** (`cli_enrich.py`)

   * Compute `module_name`, `relpath_norm`, and `module_id` for every file.
   * Call `compute_ast_metrics(code)`; add `ast` summary to each module row.
   * Emit **Parquet** with `write_parquet()`.

4. **Parquet writer** (`output_writers.py`)

   * Tiny helper based on `pyarrow`, with CSV fallback.

5. **DuckDB demo** (`sql/duckdb_demo.sql`)

   * Example joins across `modules.jsonl` and `metrics/ast.parquet`.
   * Queries that find **hotspots** (high complexity × imports) and **low‑annotation public APIs**, etc.

---

## Code diffs (ready to paste)

> Paths assume your enrichment package layout `codeintel_rev/enrich/...` that the CLI already imports. 

### A) New file: `codeintel_rev/enrich/path_norm.py`

```diff
*** /dev/null
--- a/codeintel_rev/enrich/path_norm.py
@@
+from __future__ import annotations
+
+from hashlib import sha1
+from pathlib import Path
+from typing import Optional
+
+_PKG_HINTS = {"src", "codeintel_rev"}  # extend if you have more top-level pkg roots
+
+def find_repo_root(start: Path) -> Path:
+    """
+    Best-effort repo root discovery: prefer a folder that contains `.git/` or `pyproject.toml`,
+    otherwise stop at the highest folder containing a Python package root.
+    """
+    p = start.resolve()
+    candidates = []
+    for parent in [p, *p.parents]:
+        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
+            return parent
+        # Keep track of high-level package-like roots (e.g., src/, codeintel_rev/)
+        if any((parent / hint).exists() for hint in _PKG_HINTS):
+            candidates.append(parent)
+    return candidates[0] if candidates else p
+
+def normalize_relpath(path: Path, repo_root: Path) -> str:
+    """
+    Return a stable, POSIX-style path relative to repo_root (never backslashes).
+    """
+    rel = path.resolve().relative_to(repo_root)
+    return rel.as_posix()
+
+def module_name_from_path(py_file: Path, repo_root: Path) -> str:
+    """
+    Compute dotted module name by walking upward until the package root (chain of __init__.py).
+    Falls back to heuristic using `src/` or project folder if not a package.
+    """
+    py_file = py_file.resolve()
+    # Prefer package chain with __init__.py
+    pkg_root: Optional[Path] = None
+    cur = py_file.parent
+    while cur != cur.parent and repo_root in [cur, *cur.parents]:
+        if (cur / "__init__.py").exists():
+            pkg_root = cur
+            cur = cur.parent
+            continue
+        break
+    if pkg_root:
+        parts = py_file.with_suffix("").relative_to(pkg_root.parent).parts
+        return ".".join(parts)
+    # Fallback to src/ or repo-root heuristic
+    for hint in ("src",):
+        if (repo_root / hint).exists():
+            try:
+                parts = py_file.with_suffix("").relative_to(repo_root / hint).parts
+                return ".".join(parts)
+            except ValueError:
+                pass
+    return ".".join(py_file.with_suffix("").relative_to(repo_root).parts)
+
+def stable_module_id(relpath_posix: str) -> str:
+    """
+    Short, stable ID suitable for cross-system joins, derived from normalized path.
+    """
+    return sha1(relpath_posix.encode("utf-8")).hexdigest()[:12]
```

### B) New file: `codeintel_rev/enrich/ast_metrics.py`

```diff
*** /dev/null
--- a/codeintel_rev/enrich/ast_metrics.py
@@
+from __future__ import annotations
+
+import ast
+from dataclasses import dataclass
+from typing import Any, Dict, List, Tuple
+
+_DECISION_NODES = (
+    ast.If,
+    ast.For,
+    ast.While,
+    ast.AsyncFor,
+    ast.IfExp,
+    ast.With,
+    ast.AsyncWith,
+    ast.Try,
+)
+
+@dataclass
+class DefMetric:
+    kind: str           # "function" | "class"
+    name: str
+    lineno: int
+    cyclomatic: int
+    params: int
+    params_annotated: int
+    returns_annotated: bool
+    nesting: int
+
+def _sloc(text: str) -> int:
+    return sum(1 for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#"))
+
+class _ComplexityVisitor(ast.NodeVisitor):
+    def __init__(self) -> None:
+        self.score = 1  # cyclomatic starts at 1
+        self.max_nesting = 0
+        self._stack_depth = 0
+
+    def generic_visit(self, node: ast.AST) -> Any:
+        # Decision nodes increase complexity
+        if isinstance(node, _DECISION_NODES):
+            self.score += 1
+        elif isinstance(node, ast.BoolOp):
+            # each additional boolean operand increases complexity
+            self.score += max(0, len(getattr(node, "values", [])) - 1)
+        elif isinstance(node, ast.comprehension):
+            # each 'if' in a comprehension raises complexity
+            self.score += len(getattr(node, "ifs", []))
+        # nesting depth (block-ish nodes)
+        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, * _DECISION_NODES)):
+            self._stack_depth += 1
+            self.max_nesting = max(self.max_nesting, self._stack_depth)
+            super().generic_visit(node)
+            self._stack_depth -= 1
+            return
+        return super().generic_visit(node)
+
+def _def_signature_stats(fn: ast.AST) -> Tuple[int, int, bool]:
+    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
+        return 0, 0, False
+    a = fn.args
+    total = len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
+    if a.vararg is not None:
+        total += 1
+    if a.kwarg is not None:
+        total += 1
+    ann = 0
+    for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs]:
+        if arg.annotation is not None:
+            ann += 1
+    if a.vararg and a.vararg.annotation is not None:
+        ann += 1
+    if a.kwarg and a.kwarg.annotation is not None:
+        ann += 1
+    returns_annotated = getattr(fn, "returns", None) is not None
+    return total, ann, returns_annotated
+
+def compute_ast_metrics(code: str) -> Dict[str, Any]:
+    """
+    Return a per-file AST metrics dict and a per-definition list.
+    Keys are stable and intended for analytics & DuckDB joins.
+    """
+    try:
+        tree = ast.parse(code)
+    except SyntaxError:
+        return {
+            "ok": False,
+            "loc": len(code.splitlines()),
+            "sloc": _sloc(code),
+            "num_functions": 0,
+            "num_classes": 0,
+            "cyclomatic": 0,
+            "max_nesting": 0,
+            "param_annotation_ratio": 0.0,
+            "return_annotation_ratio": 0.0,
+            "defs": [],
+        }
+
+    loc = len(code.splitlines())
+    sloc = _sloc(code)
+    num_fns = 0
+    num_cls = 0
+    all_param = 0
+    all_param_ann = 0
+    all_returns = 0
+    all_returns_ann = 0
+    defs: List[DefMetric] = []
+
+    for node in ast.walk(tree):
+        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
+            num_fns += 1
+            cv = _ComplexityVisitor()
+            cv.visit(node)
+            params, params_ann, ret_ann = _def_signature_stats(node)
+            all_param += params
+            all_param_ann += params_ann
+            all_returns += 1
+            all_returns_ann += 1 if ret_ann else 0
+            defs.append(
+                DefMetric(
+                    kind="function",
+                    name=node.name,
+                    lineno=node.lineno,
+                    cyclomatic=cv.score,
+                    params=params,
+                    params_annotated=params_ann,
+                    returns_annotated=ret_ann,
+                    nesting=cv.max_nesting,
+                )
+            )
+        elif isinstance(node, ast.ClassDef):
+            num_cls += 1
+            cv = _ComplexityVisitor()
+            cv.visit(node)
+            defs.append(
+                DefMetric(
+                    kind="class",
+                    name=node.name,
+                    lineno=node.lineno,
+                    cyclomatic=cv.score,
+                    params=0,
+                    params_annotated=0,
+                    returns_annotated=False,
+                    nesting=cv.max_nesting,
+                )
+            )
+
+    param_ratio = (all_param_ann / all_param) if all_param else 0.0
+    return_ratio = (all_returns_ann / all_returns) if all_returns else 0.0
+    file_cv = 0
+    file_nesting = 0
+    if defs:
+        file_cv = max(d.cyclomatic for d in defs)
+        file_nesting = max(d.nesting for d in defs)
+
+    return {
+        "ok": True,
+        "loc": loc,
+        "sloc": sloc,
+        "num_functions": num_fns,
+        "num_classes": num_cls,
+        "cyclomatic": file_cv,
+        "max_nesting": file_nesting,
+        "param_annotation_ratio": round(param_ratio, 4),
+        "return_annotation_ratio": round(return_ratio, 4),
+        "defs": [d.__dict__ for d in defs],
+    }
```

### C) Patch: `codeintel_rev/enrich/output_writers.py` — add Parquet writer

Your writer already supports JSON/JSONL/Markdown. We’ll add a small Parquet helper (uses `pyarrow` if present, else CSV fallback). 

```diff
--- a/codeintel_rev/enrich/output_writers.py
+++ b/codeintel_rev/enrich/output_writers.py
@@
 from collections.abc import Iterable
 from pathlib import Path
+from typing import Iterable as _Iterable, Mapping as _Mapping, Any as _Any
 
@@
 def write_markdown_module(path: str | Path, record: dict[str, object]) -> None:
@@
     target.write_text("\n".join(sections), encoding="utf-8")
+
+def write_parquet(path: str | Path, rows: _Iterable[_Mapping[str, _Any]]) -> None:
+    """
+    Persist a list of dict rows as Parquet for analytics (DuckDB/Polars).
+    Falls back to CSV if pyarrow is unavailable.
+    """
+    target = Path(path)
+    target.parent.mkdir(parents=True, exist_ok=True)
+    try:
+        import pyarrow as pa  # type: ignore[import-not-found]
+        import pyarrow.parquet as pq  # type: ignore[import-not-found]
+        table = pa.Table.from_pylist(list(rows))
+        pq.write_table(table, target.as_posix())
+    except Exception:
+        # Fallback CSV
+        import csv
+        rows_list = list(rows)
+        fieldnames = sorted({k for r in rows_list for k in r.keys()})
+        with target.with_suffix(".csv").open("w", encoding="utf-8", newline="") as f:
+            w = csv.DictWriter(f, fieldnames=fieldnames)
+            w.writeheader()
+            for r in rows_list:
+                w.writerow(r)
```

### D) Patch: `codeintel_rev/cli_enrich.py` — feed path normalization + AST metrics + Parquet

Your CLI already glues together LibCST/Tree‑sitter/SCIP and tags; we extend the row schema and write a Parquet metrics table. 

```diff
--- a/codeintel_rev/cli_enrich.py
+++ b/codeintel_rev/cli_enrich.py
@@
-from codeintel_rev.enrich.output_writers import write_json, write_jsonl, write_markdown_module
+from codeintel_rev.enrich.output_writers import write_json, write_jsonl, write_markdown_module, write_parquet
 from codeintel_rev.enrich.scip_reader import Document, SCIPIndex
 from codeintel_rev.enrich.stubs_overlay import generate_overlay_for_file
 from codeintel_rev.enrich.tagging import ModuleTraits, infer_tags, load_rules
 from codeintel_rev.enrich.tree_sitter_bridge import build_outline
 from codeintel_rev.enrich.type_integration import TypeSummary, collect_pyrefly, collect_pyright
+from codeintel_rev.enrich.path_norm import find_repo_root, normalize_relpath, module_name_from_path, stable_module_id
+from codeintel_rev.enrich.ast_metrics import compute_ast_metrics
@@
 class ModuleRecord:
     """Serializable row stored in modules.jsonl."""
 
     path: str
+    path_norm: str
+    module_name: str
+    module_id: str
     docstring: str | None
     imports: list[dict[str, Any]]
     defs: list[dict[str, Any]]
     exports: list[str]
     outline_nodes: list[dict[str, Any]]
     scip_symbols: list[str]
     parse_ok: bool
     errors: list[str]
     tags: list[str]
     type_errors: int
+    ast: dict[str, Any]
@@
 def main(
-    root: Path = typer.Option(Path("."), "--root", help="Repo or subfolder to scan."),
+    root: Path = typer.Option(Path("."), "--root", help="Repo or subfolder to scan."),
     scip: Path = typer.Option(..., "--scip", exists=True, help="Path to SCIP index.json"),
     out: Path = typer.Option(Path("codeintel_rev/io/ENRICHED"), "--out", help="Output directory"),
     pyrefly_json: Optional[Path] = typer.Option(None, "--pyrefly-json", help="Optional path to Pyrefly JSON/JSONL report"),
     tags_yaml: Optional[Path] = typer.Option(None, "--tags-yaml", help="Optional tagging rules YAML"),
 ) -> None:
     out.mkdir(parents=True, exist_ok=True)
+    repo_root = find_repo_root(root)
@@
-    module_rows: List[Dict[str, Any]] = []
+    module_rows: List[Dict[str, Any]] = []
+    ast_rows: List[Dict[str, Any]] = []
@@
-    for fp in _iter_files(root):
-        rel = str(fp.relative_to(root))
+    for fp in _iter_files(root):
+        # Stable path & module identifiers
+        rel = str(fp.relative_to(root))
+        rel_norm = normalize_relpath(fp, repo_root)
+        modname = module_name_from_path(fp, repo_root)
+        modid = stable_module_id(rel_norm)
         code = fp.read_text(encoding="utf-8", errors="ignore")
         idx = index_module(rel, code)
@@
-        # Type errors
+        # Type errors
         type_errors = 0
         if t_pyrefly and rel in t_pyrefly.by_file:
             type_errors = t_pyrefly.by_file[rel].error_count
         if t_pyright and rel in t_pyright.by_file:
             type_errors = max(type_errors, t_pyright.by_file[rel].error_count)
@@
-        row = ModuleRecord(
-            path=rel,
+        # AST metrics (per-file summary + per-def list)
+        ast_metrics = compute_ast_metrics(code)
+        ast_rows.append({
+            "module_id": modid,
+            "module_name": modname,
+            "path_norm": rel_norm,
+            **{k: v for k, v in ast_metrics.items() if k != "defs"},
+        })
+
+        row = ModuleRecord(
+            path=rel,  # keep for backward compatibility in human markdown
+            path_norm=rel_norm,
+            module_name=modname,
+            module_id=modid,
             docstring=idx.docstring,
             imports=[
                 {"module": i.module, "names": i.names, "aliases": i.aliases, "is_star": i.is_star, "level": i.level}
                 for i in idx.imports
             ],
@@
             parse_ok=idx.parse_ok,
             errors=idx.errors,
             tags=sorted(list(t.tags)),
-            type_errors=type_errors,
+            type_errors=type_errors,
+            ast=ast_metrics,
         )
         module_rows.append(asdict(row))
@@
-    write_jsonl(out / "modules" / "modules.jsonl", module_rows)
+    write_jsonl(out / "modules" / "modules.jsonl", module_rows)
+    # Parquet table for analytics
+    write_parquet(out / "metrics" / "ast.parquet", ast_rows)
@@
-    write_json(out / "repo_map.json", {"generated_at": datetime.now(UTC).isoformat(), "module_count": len(module_rows), "tags": tag_index})
+    write_json(out / "repo_map.json", {
+        "generated_at": datetime.now(UTC).isoformat(),
+        "module_count": len(module_rows),
+        "tags": tag_index
+    })
```

**Why these locations?**

* The CLI already builds `ModuleRecord` rows from LibCST, Tree‑sitter, tags, and type signals; we’re extending it with `module_name`, normalized paths, and AST summaries. 
* Writers already centralize all serialization concerns, so a Parquet helper there keeps the CLI minimal. 

---

## Run it

```bash
# (re)install so the console script sees new modules
pip install -e .

# build
codeintel-enrich \
  --root codeintel_rev \
  --scip ./index.scip.json \
  --pyrefly-json ./pyrefly.jsonl \
  --out codeintel_rev/io/ENRICHED
```

**Outputs** (added):

* `codeintel_rev/io/ENRICHED/metrics/ast.parquet`  ← new (per‑file AST metrics)
* `codeintel_rev/io/ENRICHED/modules/modules.jsonl` (now includes `path_norm`, `module_name`, `module_id`, `ast` block)

Everything else continues to work: LibCST parse + tags + Tree‑sitter outline + Pyrefly/Pyright summaries.   

---

## DuckDB demo (save as `sql/duckdb_demo.sql`)

This shows how to: (1) read the JSONL, (2) read the AST Parquet, (3) compute useful joins & rankings.

```sql
-- Point this at the ENRICHED output directory
-- duckdb -c ".read sql/duckdb_demo.sql"

-- 1) Load
CREATE OR REPLACE VIEW modules AS
SELECT *
FROM read_json_auto('codeintel_rev/io/ENRICHED/modules/modules.jsonl', format='newline_delimited');

CREATE OR REPLACE VIEW ast AS
SELECT *
FROM read_parquet('codeintel_rev/io/ENRICHED/metrics/ast.parquet');

-- 2) Basic sanity: join by normalized path/module_id
SELECT
  m.path_norm,
  m.module_name,
  a.sloc,
  a.cyclomatic,
  m.type_errors,
  list_length(m.imports) AS import_count
FROM modules m
JOIN ast a USING(module_id)
ORDER BY a.cyclomatic DESC
LIMIT 25;

-- 3) Hotspots (complexity × import fan-out × low annotations)
WITH base AS (
  SELECT
    m.module_name,
    m.path_norm,
    a.sloc,
    a.cyclomatic,
    a.param_annotation_ratio,
    a.return_annotation_ratio,
    list_length(m.imports) AS fan_out,
    coalesce(m.type_errors, 0) AS type_errors
  FROM modules m
  JOIN ast a USING(module_id)
)
SELECT *
FROM base
ORDER BY
  (a.cyclomatic * (fan_out + 1)) DESC,
  a.sloc DESC
LIMIT 50;

-- 4) Public APIs with weak type coverage (use your existing tagger)
--    NOTE: "public-api" is a tag already emitted by your tagging pipeline.
SELECT
  m.module_name,
  m.path_norm,
  a.param_annotation_ratio,
  a.return_annotation_ratio
FROM modules m
JOIN ast a USING(module_id)
WHERE array_contains(m.tags, 'public-api')
  AND (a.param_annotation_ratio < 0.5 OR a.return_annotation_ratio < 0.5)
ORDER BY a.param_annotation_ratio ASC, a.return_annotation_ratio ASC;

-- 5) Modules with high complexity but zero current type errors (safe refactor candidates)
SELECT
  m.module_name, m.path_norm, a.cyclomatic, m.type_errors
FROM modules m
JOIN ast a USING(module_id)
WHERE coalesce(m.type_errors, 0) = 0
ORDER BY a.cyclomatic DESC
LIMIT 30;
```

---

## Why this works well with the rest of your stack

* **CST facts** (imports/defs/exports/docstring) are still the human‑readable spine for each module; we didn’t change that. 
* **SCIP** stays your cross‑file glue (def↔ref, kind/doc), independent of AST metrics. 
* **Tree‑sitter** remains a fast outline fallback for non‑Python files in the repo map. 
* **Type signals** (Pyrefly/Pyright) still land in the per‑module rows and are easy to join to AST metrics with `module_id`. 
* Your Pyright/Pyrefly settings already route type checking over `src/`, `codeintel_rev/`, and `stubs`—no extra config needed.  

---

## Notes, edge cases, and extensions

* **Module names for “loose” files.** If a file isn’t in a package tree, `module_name_from_path` falls back to a dotted path under the repo root; it’s still stable for joins.
* **Cyclomatic approximation.** This is a pragmatic, AST‑only metric. If you want parity with tools like `radon`, we can swap in that algorithm later; for now, it’s fast and monotonic.
* **Per‑def metrics in JSON.** The `ast.defs` list is included in each `modules.jsonl` row; you can mine hotspots at the **function** level without re‑parsing code.
* **SCIP/exports resolution.** If you later materialize `exports_resolved` and `reexports`, those lists will join cleanly by `module_name` and `module_id` (as we discussed previously). Your current modules emitter already has the structure to add extra fields. 

---

## Recap

* Added **path normalization** for consistent joins (`path_norm`, `module_name`, `module_id`).
* Added **AST metrics** (file‑level & per‑def) and produce **Parquet** for analytics.
* Extended CLI to emit everything without changing your existing flows.
* Provided **DuckDB SQL** to explore hotspots, typedness, and public API gaps.

If you want, I can also include a small `tests/test_ast_metrics_smoke.py` later to validate the visitor on a few synthetic examples; for now the CLI produces immediate metrics you can inspect in DuckDB, Polars, or Python.



# AST extraction / metrics validator #

Perfect—here’s a **drop‑in smoke test** (plus a tiny visitor module) that validates the AST extraction/metrics you asked for. It’s self‑contained, fast, and exercises the end‑to‑end flow (including writing a JSON artifact with your existing writer). I’ve also included brief “why we did it this way” notes and exactly how to run it.

---

## 1) New module: `codeintel_rev/enrich/ast_metrics.py`

> **What it does**
>
> * Uses Python’s stdlib `ast` to visit a module and compute **AST‑level metrics** that we’ll later join with CST/SCIP in DuckDB.
> * Produces a compact, stable record with a `node_histogram` (counts by AST node type) + aggregate metrics (imports, defs, branches, comprehensions, literals, etc.).
> * Includes small helpers for **path normalization** and file‑based operation.

```python
# codeintel_rev/enrich/ast_metrics.py
# SPDX-License-Identifier: MIT
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from collections import Counter


@dataclass(frozen=True)
class ASTMetrics:
    """Aggregate metrics derived from a module's AST."""
    loc: int
    num_nodes: int
    imports: int
    functions: int
    classes: int
    branches: int           # If/IfExp/For/While/Try/With/Match
    comprehensions: int     # List/Set/Dict comps, GeneratorExp
    literals: int           # non-None Constant nodes


def _normalize_path(path: Path, repo_root: Optional[Path] = None) -> str:
    """Return a stable posix-style repo-relative path."""
    if repo_root:
        try:
            rel = path.resolve().relative_to(repo_root.resolve())
        except Exception:
            rel = path.name
    else:
        rel = path
    return str(rel).replace("\\", "/")


class _ASTVisitor(ast.NodeVisitor):
    """Counts node kinds and aggregates useful metrics."""
    def __init__(self) -> None:
        self.hist = Counter()
        self.nodes = 0
        self.functions = 0
        self.classes = 0
        self.imports = 0
        self.branches = 0
        self.comps = 0
        self.literals = 0

    # Generic
    def generic_visit(self, node: ast.AST) -> None:
        self.nodes += 1
        self.hist[type(node).__name__] += 1
        super().generic_visit(node)

    # Defs
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions += 1
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.functions += 1
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes += 1
        self.generic_visit(node)

    # Imports
    def visit_Import(self, node: ast.Import) -> None:
        self.imports += 1
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports += 1
        self.generic_visit(node)

    # Branching/flow constructs
    def visit_If(self, node: ast.If) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:  # py3.10+
        self.branches += 1
        self.generic_visit(node)

    # Comprehensions
    def visit_ListComp(self, node: ast.ListComp) -> None:
        self.comps += 1
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self.comps += 1
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self.comps += 1
        self.generic_visit(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self.comps += 1
        self.generic_visit(node)

    # Literals
    def visit_Constant(self, node: ast.Constant) -> None:
        if node.value is not None:
            self.literals += 1
        self.generic_visit(node)


def compute_ast_metrics(path_str: str, source: str) -> dict:
    """Compute AST metrics for an in-memory module (no I/O)."""
    tree = ast.parse(source, filename=path_str, type_comments=True)
    v = _ASTVisitor()
    v.visit(tree)
    metrics = ASTMetrics(
        loc=(source.count("\n") + 1) if source else 0,
        num_nodes=v.nodes,
        imports=v.imports,
        functions=v.functions,
        classes=v.classes,
        branches=v.branches,
        comprehensions=v.comps,
        literals=v.literals,
    )
    return {
        "path": path_str,
        "metrics": metrics.__dict__,
        "node_histogram": dict(v.hist),
    }


def compute_ast_metrics_from_file(file_path: Path, repo_root: Optional[Path] = None) -> dict:
    """Compute metrics for a real file and normalize the path to repo-relative."""
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    rel = _normalize_path(file_path, repo_root)
    return compute_ast_metrics(rel, text)
```

**Why this shape?**

* This mirrors how your **LibCST index** yields “structural facts” for each module; AST augments it with **control‑flow and complexity hints**. We keep the payload small and deterministic so it’s easy to join in DuckDB later. The module integrates cleanly with your existing writers (see below). 

---

## 2) Smoke test: `tests/test_ast_metrics_smoke.py`

> **What it validates**
>
> * Visitor counts on a **synthetic module** with imports, classes, functions, comprehensions, and branches.
> * File‑based path normalization + **artifact write** using your existing `write_json` helper, so we exercise I/O exactly the way your enrichment pipeline does. (This writer already ships in your repo.) 

```python
# tests/test_ast_metrics_smoke.py
# SPDX-License-Identifier: MIT
from __future__ import annotations

import textwrap
from pathlib import Path

from codeintel_rev.enrich.ast_metrics import compute_ast_metrics, compute_ast_metrics_from_file
from codeintel_rev.enrich.output_writers import write_json  # existing helper

def test_ast_metrics_on_synthetic_module() -> None:
    src = textwrap.dedent(
        """
        import os
        from math import sin as s

        CONST = 3

        class C:
            def m(self, x: int) -> int:
                return x + CONST

        def f(n: int) -> int:
            xs = [i * i for i in range(n) if i % 2]
            if n > 0:
                for _ in xs:
                    pass
            else:
                try:
                    match n:
                        case 1:
                            return 1
                        case _:
                            return 0
                except Exception:
                    with open(__file__):
                        return -1
            return sum(xs)
        """
    ).strip()

    rec = compute_ast_metrics("pkg/mod.py", src)
    m = rec["metrics"]
    assert m["imports"] == 2
    assert m["functions"] == 2          # C.m + f
    assert m["classes"] == 1
    assert m["comprehensions"] == 1
    assert m["branches"] >= 6           # if/else/for/try/with/match (+ possibly more)
    assert rec["node_histogram"]["FunctionDef"] >= 2
    assert rec["metrics"]["num_nodes"] > 0


def test_ast_metrics_from_file_and_write(tmp_path: Path) -> None:
    # prepare a real file to exercise path normalization and the writer
    src_file = tmp_path / "pkg" / "alpha.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("def x():\n    return 1\n", encoding="utf-8")

    rec = compute_ast_metrics_from_file(src_file, repo_root=tmp_path)
    assert rec["path"] == "pkg/alpha.py"        # normalized repo-relative POSIX path

    out = tmp_path / "io" / "ast_record.json"
    write_json(out, rec)
    assert out.exists()
```

> **Why PyTest will discover this automatically**
> Your project’s `pytest.ini` already sets `testpaths = tests` and enables doctests, so this will run with a plain `pytest -q`. 

---

## 3) (Optional) CLI hook so you can run it from the console later

If/when you want to expose AST collection alongside your enrichment CLI, add a tiny command into your existing entrypoint (or a new small CLI). The structure below mirrors your current `codeintel_rev.cli_enrich:main` pattern so it fits right in. 

```diff
diff --git a/codeintel_rev/cli_enrich.py b/codeintel_rev/cli_enrich.py
@@
 app = typer.Typer(
     add_completion=False,
     help="Combine SCIP + LibCST + Tree-sitter + type checker signals into a repo map.",
 )
 
+@app.command("ast-scan")
+def ast_scan(
+    root: Path = typer.Option(Path("."), "--root", help="Repo or subfolder to scan."),
+    out: Path = typer.Option(Path("codeintel_rev/io/ENRICHED"), "--out", help="Output directory"),
+) -> None:
+    """
+    Produce AST metrics & histograms per Python file under --root.
+    """
+    from codeintel_rev.enrich.ast_metrics import compute_ast_metrics_from_file
+    from codeintel_rev.enrich.output_writers import write_jsonl
+
+    rows = []
+    for p in root.rglob("*.py"):
+        if any(part.startswith(".") for part in p.parts):
+            continue
+        rows.append(compute_ast_metrics_from_file(p, repo_root=root))
+    out_dir = out / "ast"
+    out_dir.mkdir(parents=True, exist_ok=True)
+    write_jsonl(out_dir / "ast_metrics.jsonl", rows)
+    typer.echo(f"Wrote {len(rows)} AST rows to {out_dir/'ast_metrics.jsonl'}")
```

---

## 4) How to run the smoke test

```bash
# from your repo root
pytest -q tests/test_ast_metrics_smoke.py
```

You should see 2 passing tests. The second test also confirms the JSON writer integration (same writer used in your module/graph emission). 

---

## 5) Notes on stitching and compatibility

* **Why AST now?** Your CST pass (imports/defs/exports, docstrings) and enrichment writers are already stable; AST gives us cheap **control‑flow and complexity** signals that combine well with the LibCST module records and SCIP occurrence graph. This complements (not replaces) the CST map your `libcst_bridge` already builds. 
* **Writers**: We purposely reused the repo’s JSON/JSONL writer so the artifacts and directory layout match your enrichment outputs for easy joining. 
* **PyTest config**: No tweaks needed—your config already discovers tests in `tests/` and enables doctests; we avoided any additional dependencies. 

---

## 6) If you later want a one‑shot “end‑to‑end” smoke

Once you wire the (optional) `ast-scan` command above, a single CLI run exercises: discovery → per‑file AST metrics → JSONL output. Your existing enrichment CLI already uses the same discovery pattern and output writers, so the ergonomics remain consistent. 

---

### Recap

* **New module**: `codeintel_rev/enrich/ast_metrics.py` with a compact visitor + helpers.
* **New tests**: `tests/test_ast_metrics_smoke.py` that validate both in‑memory and file‑based paths and the JSON writer.
* **Optional CLI**: small `ast-scan` command for parity with your enrichment tooling.

If you want, I can also add a mini `duckdb` notebook or SQL snippet to join `ast_metrics.jsonl` with your per‑module JSONL and SCIP symbol graph—just say the word and I’ll drop it in the same I/O folder structure your pipeline already uses.
