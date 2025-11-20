
# Implementation plan and detailed code #

Here’s an implementation plan for **per‑function metrics** and **per‑function typedness**, mirroring the structure and level of detail of the previous plan, and aligned with the existing CodeIntel artifacts like `goids.jsonl`, `ast_nodes.jsonl`, and `typedness.jsonl`. 

---

## 1. Goals & context

We want two new JSONL artifacts, produced by the enrichment pipeline and dropped under `Document Output/`:

1. **`function_metrics.jsonl`**
   Fine‑grained structural and complexity metrics per function/method.

2. **`function_types.jsonl`**
   Fine‑grained typedness and signature info per function/method (complementing the existing per‑file `typedness.jsonl`).

Both should:

* Use **GOIDs** as the primary join key (via `goid_h128` + `urn`). 
* Be joinable with:

  * `goids.jsonl` (entity registry)
  * `goid_crosswalk.jsonl` (file/qualname/span anchor)
  * `cfg_blocks.*` / `dfg_edges.*` for deeper graph analytics later.
* Fit into the same **Parquet → JSONL** document generation flow as existing artifacts. 

---

## 2. Target artifacts & schemas

### 2.1 `function_metrics.jsonl`

**Purpose**: Structural/complexity metrics per function or method.

**One row per**: callable GOID of kind `function`, `method`, `lambda`, `async_function`, `__call__`‑like class callables.

**Schema (JSONL row)**

```jsonc
{
  "function_goid_h128": "12345678901234567890", // decimal(38) as string
  "urn": "goid:repo/path#python:function:pkg.mod.Foo.bar?s=10&e=42",
  "repo": "kgfoundry",
  "commit": "deadbeef...",
  "rel_path": "codeintel_rev/app/routes/catalog_read.py",
  "language": "python",
  "kind": "method",                   // function | method | lambda | async_function | class_call
  "qualname": "codeintel_rev.app.routes.catalog_read.CatalogReader.get",
  "start_line": 101,
  "end_line": 158,

  "loc": 32,                          // end_line - start_line + 1
  "logical_loc": 24,                  // non-blank, non-comment lines within body
  "param_count": 3,
  "positional_params": 2,
  "keyword_only_params": 1,
  "has_varargs": false,
  "has_varkw": true,

  "is_async": false,
  "is_generator": false,
  "return_count": 2,
  "yield_count": 0,
  "raise_count": 1,

  "cyclomatic_complexity": 7,         // 1 + decision points
  "max_nesting_depth": 3,             // depth of control flow nesting
  "stmt_count": 18,                   // executable statements
  "decorator_count": 1,
  "has_docstring": true,

  "complexity_bucket": "medium",      // low | medium | high (configurable thresholds)
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Notes**

* `function_goid_h128` matches `goids.goid_h128` from the registry. 
* `kind` should mirror `goids.kind` for callables (e.g., `method` vs `function`).
* `cyclomatic_complexity` is computed from AST/CST, but we can optionally refine it later from CFG blocks.

---

### 2.2 `function_types.jsonl`

**Purpose**: Detailed typedness stats and signature type data per function.

**One row per**: same callable GOID universe as `function_metrics.jsonl`.

**Schema (JSONL row)**

```jsonc
{
  "function_goid_h128": "12345678901234567890",
  "urn": "goid:repo/path#python:function:pkg.mod.Foo.bar?s=10&e=42",
  "repo": "kgfoundry",
  "commit": "deadbeef...",
  "rel_path": "codeintel_rev/app/routes/catalog_read.py",
  "language": "python",
  "kind": "method",
  "qualname": "codeintel_rev.app.routes.catalog_read.CatalogReader.get",
  "start_line": 101,
  "end_line": 158,

  "total_params": 3,
  "annotated_params": 3,
  "unannotated_params": 0,
  "param_typed_ratio": 1.0,

  "has_return_annotation": true,
  "return_type": "CatalogResponse",
  "return_type_source": "annotation",   // annotation | type_comment | inferred | unknown

  "type_comment": null,                 // '# type: (...) -> ...' if present
  "param_types": {                      // param name -> text form of type
    "self": null,
    "request": "Request",
    "limit": "int | None"
  },

  "fully_typed": true,                  // all params + return annotated
  "partial_typed": false,
  "untyped": false,

  "typedness_bucket": "typed",          // typed | partial | untyped (aligns with typedness.jsonl)
  "typedness_source": "annotations",    // annotations | mixed | unknown

  "created_at": "2024-01-01T00:00:00Z"
}
```

**Relationship to existing `typedness.jsonl`**

* Existing `typedness.jsonl` is **per file**, with fields like `function_count`, `typed_functions`, `partial_functions`, `untyped_functions`, and `typed_ratio`. 
* `function_types.jsonl` is **per function**, and can be aggregated to reproduce file‑level stats (sanity check).

---

## 3. Data sources & joins

We’ll leverage existing artifacts:

* **GOID Registry (`goids.*`)** – canonical entity IDs, including functions & methods. 
* **GOID Crosswalk (`goid_crosswalk.*`)** – maps GOID URN to `file_path`, `module_path`, `ast_qualname`, `start_line`, `end_line`, `chunk_id`, etc. 
* **AST/CST index (`ast_nodes.*` and LibCST/AST in-memory)** – for node spans, qualnames, decorators, docstrings, etc. 
* **Existing typedness analytics (`typedness.jsonl`)** – for file‑level validation and for sharing any helper logic. 

**Join key**:

* Primary: `(goid_h128)` or `urn` from `goids.jsonl`.
* For mapping GOIDs to concrete syntax nodes: join `goids` → `goid_crosswalk` via GOID and then match `(file_path, start_line, end_line)` to AST/CST nodes.

---

## 4. Implementation plan (phased)

### Phase 1 – Scaffolding & contracts

#### 4.1.1 Create analytics module stubs

Add two new modules, parallel to existing analytics modules like `hotspots` and `typedness`: 

```bash
codeintel_rev/
  services/
    enrich/
      analytics/
        function_metrics.py
        function_types.py
```

In each, define:

* Public entrypoint: `build_function_metrics(...)` / `build_function_types(...)`
* Reusable visitors/analyzers for AST/CST.

Example `function_metrics.py` scaffold:

```python
# codeintel_rev/services/enrich/analytics/function_metrics.py
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, List, Dict, Optional

import datetime
import json
import libcst as cst

from codeintel_rev.enrich.goid_builder import GOIDRegistry
from codeintel_rev.enrich.goid_utils import lookup_function_goid
from codeintel_rev.io.fs import open_text_out


@dataclass
class FunctionMetricsRow:
    function_goid_h128: str
    urn: str
    repo: str
    commit: str
    rel_path: str
    language: str
    kind: str
    qualname: str
    start_line: int
    end_line: int

    loc: int
    logical_loc: int
    param_count: int
    positional_params: int
    keyword_only_params: int
    has_varargs: bool
    has_varkw: bool

    is_async: bool
    is_generator: bool
    return_count: int
    yield_count: int
    raise_count: int

    cyclomatic_complexity: int
    max_nesting_depth: int
    stmt_count: int
    decorator_count: int
    has_docstring: bool

    complexity_bucket: str
    created_at: str


class FunctionMetricsVisitor(cst.CSTVisitor):
    def __init__(self, *, rel_path: str, goid_registry: GOIDRegistry):
        self.rel_path = rel_path
        self.goid_registry = goid_registry
        self.rows: List[FunctionMetricsRow] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        row = self._build_row_from_function(node)
        if row:
            self.rows.append(row)

    def _build_row_from_function(self, node: cst.FunctionDef) -> Optional[FunctionMetricsRow]:
        # Implementation stub; filled in Phase 3
        return None


def build_function_metrics(
    *,
    repo: str,
    commit: str,
    rel_path: str,
    module: cst.Module,
    goid_registry: GOIDRegistry,
) -> Iterable[FunctionMetricsRow]:
    visitor = FunctionMetricsVisitor(rel_path=rel_path, goid_registry=goid_registry)
    module.visit(visitor)
    now = datetime.datetime.utcnow().isoformat() + "Z"
    for row in visitor.rows:
        row.created_at = now
        yield row


def write_function_metrics_jsonl(
    rows: Iterable[FunctionMetricsRow],
    out_path: str,
) -> None:
    with open_text_out(out_path) as f:
        for row in rows:
            f.write(json.dumps(asdict(row), sort_keys=True))
            f.write("\n")
```

A similar scaffold goes into `function_types.py`.

---

### Phase 2 – Function discovery & GOID join

We need a robust way to associate each function CST node with a GOID.

#### 4.2.1 GOID lookup helper

Assuming we have something like `GOIDRegistry` that can query by `(rel_path, kind, qualname, span)`, add a helper function.

```python
# codeintel_rev/enrich/goid_utils.py
from __future__ import annotations

from typing import Optional
import libcst as cst

from codeintel_rev.enrich.goid_builder import GOIDRegistry, EntityKind


def function_node_span(node: cst.FunctionDef) -> tuple[int, int]:
    # LibCST nodes expose get_metadata for PositionProvider in the existing pipeline.
    # We assume that metadata has already been filled by AstIndexer.
    from libcst.metadata import PositionProvider

    position = node._metadata[PositionProvider]
    return position.start.line, position.end.line


def lookup_function_goid(
    *,
    registry: GOIDRegistry,
    rel_path: str,
    node: cst.FunctionDef,
    qualname: str,
) -> Optional[tuple[str, str]]:
    """
    Returns (goid_h128, urn) for a given function node if present in the registry.
    """
    start_line, end_line = function_node_span(node)
    return registry.lookup(
        rel_path=rel_path,
        language="python",
        kind=EntityKind.FUNCTION,
        qualname=qualname,
        start_line=start_line,
        end_line=end_line,
    )
```

This depends on how `GOIDRegistry.lookup` is actually implemented, but the idea is:

* **Input**: file path, kind, qualname, span.
* **Output**: GOID hash + URN (consistent with `goids.jsonl`). 

#### 4.2.2 Qualname resolution

We need a way to compute full qualnames (`pkg.mod.Class.method`) in the CST visitor. Often this is already present in `ast_nodes.jsonl` and/or AST metadata; but for the visitor we can maintain a stack.

```python
# codeintel_rev/services/enrich/analytics/qualname_stack.py
from __future__ import annotations
from typing import List
import libcst as cst


class QualnameVisitor(cst.CSTVisitor):
    def __init__(self) -> None:
        self.scope_stack: List[str] = []
        self.qualname_by_node: dict[cst.CSTNode, str] = {}

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        name = node.name.value
        self.scope_stack.append(name)

    def leave_ClassDef(self, node: cst.ClassDef) -> None:
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        name = node.name.value
        parts = self.scope_stack + [name]
        qname = ".".join(parts)
        self.qualname_by_node[node] = qname
        self.scope_stack.append(name)

    def leave_FunctionDef(self, node: cst.FunctionDef) -> None:
        self.scope_stack.pop()
```

We can reuse or embed this logic inside the metrics/types visitors.

---

### Phase 3 – Function metrics extraction

Now we implement `_build_row_from_function` and supporting helpers inside `FunctionMetricsVisitor`.

#### 4.3.1 Structural helpers

```python
# function_metrics.py
import libcst.matchers as m

def _count_returns(node: cst.FunctionDef) -> int:
    return sum(1 for _ in node.body.visit(cst.CSTVisitor(), lambda n: isinstance(n, cst.Return)))

def _count_yields(node: cst.FunctionDef) -> int:
    class YieldCounter(cst.CSTVisitor):
        def __init__(self) -> None:
            self.count = 0
        def visit_Yield(self, _node: cst.Yield) -> None:
            self.count += 1
        def visit_YieldFrom(self, _node: cst.YieldFrom) -> None:
            self.count += 1

    v = YieldCounter()
    node.body.visit(v)
    return v.count


class _ReturnCounter(cst.CSTVisitor):
    def __init__(self) -> None:
        self.count = 0
    def visit_Return(self, _node: cst.Return) -> None:
        self.count += 1


def count_returns(node: cst.FunctionDef) -> int:
    v = _ReturnCounter()
    node.body.visit(v)
    return v.count


class _RaiseCounter(cst.CSTVisitor):
    def __init__(self) -> None:
        self.count = 0
    def visit_Raise(self, _node: cst.Raise) -> None:
        self.count += 1


def count_raises(node: cst.FunctionDef) -> int:
    v = _RaiseCounter()
    node.body.visit(v)
    return v.count
```

#### 4.3.2 Nesting depth & cyclomatic complexity

A simple approximation based on common control‑flow constructs:

```python
CONTROL_NODES = (
    cst.If,
    cst.While,
    cst.For,
    cst.AsyncFor,
    cst.With,
    cst.AsyncWith,
    cst.Try,
    cst.IfExp,
)

class _NestingAndComplexityVisitor(cst.CSTVisitor):
    def __init__(self) -> None:
        self.current_depth = 0
        self.max_depth = 0
        self.decision_points = 0

    def _enter_control(self) -> None:
        self.current_depth += 1
        self.max_depth = max(self.max_depth, self.current_depth)
        self.decision_points += 1

    def _leave_control(self) -> None:
        self.current_depth -= 1

    def visit_If(self, node: cst.If) -> None:
        self._enter_control()

    def leave_If(self, node: cst.If) -> None:
        self._leave_control()

    def visit_While(self, node: cst.While) -> None:
        self._enter_control()

    def leave_While(self, node: cst.While) -> None:
        self._leave_control()

    def visit_For(self, node: cst.For) -> None:
        self._enter_control()

    def leave_For(self, node: cst.For) -> None:
        self._leave_control()

    def visit_AsyncFor(self, node: cst.AsyncFor) -> None:
        self._enter_control()

    def leave_AsyncFor(self, node: cst.AsyncFor) -> None:
        self._leave_control()

    def visit_With(self, node: cst.With) -> None:
        self._enter_control()

    def leave_With(self, node: cst.With) -> None:
        self._leave_control()

    def visit_AsyncWith(self, node: cst.AsyncWith) -> None:
        self._enter_control()

    def leave_AsyncWith(self, node: cst.AsyncWith) -> None:
        self._leave_control()

    def visit_Try(self, node: cst.Try) -> None:
        self._enter_control()

    def leave_Try(self, node: cst.Try) -> None:
        self._leave_control()

    def visit_IfExp(self, node: cst.IfExp) -> None:
        self.decision_points += 1

    def visit_BooleanOperation(self, node: cst.BooleanOperation) -> None:
        # each 'and/or' adds an additional path
        if isinstance(node.operator, (cst.And, cst.Or)):
            self.decision_points += len(node.left if isinstance(node.left, list) else [node.left])
```

Complexity & depth from this visitor:

```python
def compute_complexity_and_depth(node: cst.FunctionDef) -> tuple[int, int]:
    v = _NestingAndComplexityVisitor()
    node.body.visit(v)
    cyclomatic = 1 + v.decision_points
    return cyclomatic, v.max_depth
```

#### 4.3.3 LOC & logical LOC

Use LibCST positions and raw text:

```python
from libcst.metadata import PositionProvider

def compute_loc(node: cst.FunctionDef) -> tuple[int, int]:
    pos = node._metadata[PositionProvider]
    start, end = pos.start.line, pos.end.line
    loc = end - start + 1

    if node.body.body:
        first_stmt = node.body.body[0]
        last_stmt = node.body.body[-1]
        body_pos_first = first_stmt._metadata[PositionProvider].start.line
        body_pos_last = last_stmt._metadata[PositionProvider].end.line
    else:
        body_pos_first = start
        body_pos_last = end

    # Logical LOC can be refined by slicing actual source; for now we
    # approximate as the number of statement lines.
    logical_loc = body_pos_last - body_pos_first + 1
    return loc, logical_loc
```

#### 4.3.4 Implement `_build_row_from_function`

```python
# in FunctionMetricsVisitor

from libcst.metadata import PositionProvider

def _build_row_from_function(self, node: cst.FunctionDef) -> Optional[FunctionMetricsRow]:
    from .qualname_stack import QualnameVisitor  # or reuse in-class logic

    # Assume we have qualname mapping in metadata; otherwise recompute
    qualname = getattr(node, "_qualname", node.name.value)

    goid = lookup_function_goid(
        registry=self.goid_registry,
        rel_path=self.rel_path,
        node=node,
        qualname=qualname,
    )
    if not goid:
        return None
    goid_h128, urn = goid

    pos = node._metadata[PositionProvider]
    start_line, end_line = pos.start.line, pos.end.line

    loc, logical_loc = compute_loc(node)
    returns = count_returns(node)
    yields = _count_yields(node)
    raises = count_raises(node)
    cyclomatic, max_depth = compute_complexity_and_depth(node)

    params = node.params
    all_params = (
        list(params.posonly_params)
        + list(params.params)
        + list(params.kwonly_params)
    )
    param_count = len(all_params)
    positional_params = len(params.posonly_params) + len(params.params)
    keyword_only_params = len(params.kwonly_params)
    has_varargs = params.star_arg is not None
    has_varkw = params.star_kwarg is not None

    decorator_count = len(node.decorators)
    has_docstring = bool(cst.get_docstring(node))

    is_async = node.asynchronous is not None
    is_generator = yields > 0

    stmt_count = len(node.body.body)

    def bucket_complexity(c: int) -> str:
        if c <= 5:
            return "low"
        if c <= 10:
            return "medium"
        return "high"

    return FunctionMetricsRow(
        function_goid_h128=str(goid_h128),
        urn=urn,
        repo=self.goid_registry.repo,
        commit=self.goid_registry.commit,
        rel_path=self.rel_path,
        language="python",
        kind="async_function" if is_async else "function",  # can refine for methods via scope
        qualname=qualname,
        start_line=start_line,
        end_line=end_line,

        loc=loc,
        logical_loc=logical_loc,
        param_count=param_count,
        positional_params=positional_params,
        keyword_only_params=keyword_only_params,
        has_varargs=has_varargs,
        has_varkw=has_varkw,

        is_async=is_async,
        is_generator=is_generator,
        return_count=returns,
        yield_count=yields,
        raise_count=raises,

        cyclomatic_complexity=cyclomatic,
        max_nesting_depth=max_depth,
        stmt_count=stmt_count,
        decorator_count=decorator_count,
        has_docstring=has_docstring,

        complexity_bucket=bucket_complexity(cyclomatic),
        created_at="",  # filled in build_function_metrics
    )
```

You can refine `kind` based on whether the current function is nested under a `ClassDef` scope.

---

### Phase 4 – Typedness extraction (`function_types.jsonl`)

Now we do per‑function typedness, reusing any helpers from existing `analytics.typedness`. 

#### 4.4.1 Data model & visitor

```python
# codeintel_rev/services/enrich/analytics/function_types.py
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Dict, List, Optional
import datetime
import json

import libcst as cst
from libcst.metadata import PositionProvider

from codeintel_rev.enrich.goid_builder import GOIDRegistry
from codeintel_rev.enrich.goid_utils import lookup_function_goid
from codeintel_rev.io.fs import open_text_out


@dataclass
class FunctionTypesRow:
    function_goid_h128: str
    urn: str
    repo: str
    commit: str
    rel_path: str
    language: str
    kind: str
    qualname: str
    start_line: int
    end_line: int

    total_params: int
    annotated_params: int
    unannotated_params: int
    param_typed_ratio: float

    has_return_annotation: bool
    return_type: Optional[str]
    return_type_source: str              # annotation | type_comment | inferred | unknown

    type_comment: Optional[str]          # '# type: (...) -> ...'
    param_types: Dict[str, Optional[str]]

    fully_typed: bool
    partial_typed: bool
    untyped: bool

    typedness_bucket: str                # typed | partial | untyped
    typedness_source: str                # annotations | mixed | unknown

    created_at: str


class FunctionTypesVisitor(cst.CSTVisitor):
    def __init__(self, *, rel_path: str, goid_registry: GOIDRegistry):
        self.rel_path = rel_path
        self.goid_registry = goid_registry
        self.rows: List[FunctionTypesRow] = []

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        row = self._build_row(node)
        if row:
            self.rows.append(row)

    def _build_row(self, node: cst.FunctionDef) -> Optional[FunctionTypesRow]:
        qualname = getattr(node, "_qualname", node.name.value)

        goid = lookup_function_goid(
            registry=self.goid_registry,
            rel_path=self.rel_path,
            node=node,
            qualname=qualname,
        )
        if not goid:
            return None
        goid_h128, urn = goid

        pos = node._metadata[PositionProvider]
        start_line, end_line = pos.start.line, pos.end.line

        params = node.params
        all_params = (
            list(params.posonly_params)
            + list(params.params)
            + list(params.kwonly_params)
        )
        total_params = len(all_params)

        param_types: Dict[str, Optional[str]] = {}
        annotated_params = 0
        unannotated_params = 0

        def annotation_to_str(ann: Optional[cst.Annotation]) -> Optional[str]:
            if ann is None:
                return None
            return ann.annotation.code  # LibCST preserves source formatting

        for entry in all_params:
            name = entry.name.value
            ann_str = annotation_to_str(entry.annotation)
            param_types[name] = ann_str
            if ann_str is None:
                unannotated_params += 1
            else:
                annotated_params += 1

        if params.star_arg:
            name = params.star_arg.name.value if params.star_arg.name else "*args"
            ann_str = annotation_to_str(params.star_arg.annotation)
            param_types[name] = ann_str
            if ann_str is None:
                unannotated_params += 1
            else:
                annotated_params += 1
            total_params += 1

        if params.star_kwarg:
            name = params.star_kwarg.name.value if params.star_kwarg.name else "**kwargs"
            ann_str = annotation_to_str(params.star_kwarg.annotation)
            param_types[name] = ann_str
            if ann_str is None:
                unannotated_params += 1
            else:
                annotated_params += 1
            total_params += 1

        param_typed_ratio = (
            annotated_params / total_params if total_params else 1.0
        )

        return_ann = annotation_to_str(node.returns)
        has_return_annotation = return_ann is not None

        # Type comments support can be added by reading metadata or raw source;
        # treat as unknown for now.
        type_comment = None
        return_type_source = "annotation" if has_return_annotation else "unknown"

        fully_typed = total_params > 0 and annotated_params == total_params and has_return_annotation
        untyped = (annotated_params == 0) and not has_return_annotation
        partial_typed = not fully_typed and not untyped

        if fully_typed:
            typedness_bucket = "typed"
        elif partial_typed:
            typedness_bucket = "partial"
        else:
            typedness_bucket = "untyped"

        typedness_source = "annotations" if annotated_params > 0 or has_return_annotation else "unknown"

        return FunctionTypesRow(
            function_goid_h128=str(goid_h128),
            urn=urn,
            repo=self.goid_registry.repo,
            commit=self.goid_registry.commit,
            rel_path=self.rel_path,
            language="python",
            kind="function",
            qualname=qualname,
            start_line=start_line,
            end_line=end_line,

            total_params=total_params,
            annotated_params=annotated_params,
            unannotated_params=unannotated_params,
            param_typed_ratio=param_typed_ratio,

            has_return_annotation=has_return_annotation,
            return_type=return_ann,
            return_type_source=return_type_source,

            type_comment=type_comment,
            param_types=param_types,

            fully_typed=fully_typed,
            partial_typed=partial_typed,
            untyped=untyped,

            typedness_bucket=typedness_bucket,
            typedness_source=typedness_source,
            created_at="",  # filled in builder
        )
```

Builder & writer:

```python
def build_function_types(
    *,
    repo: str,
    commit: str,
    rel_path: str,
    module: cst.Module,
    goid_registry: GOIDRegistry,
) -> Iterable[FunctionTypesRow]:
    visitor = FunctionTypesVisitor(rel_path=rel_path, goid_registry=goid_registry)
    module.visit(visitor)
    now = datetime.datetime.utcnow().isoformat() + "Z"
    for row in visitor.rows:
        row.created_at = now
        yield row


def write_function_types_jsonl(
    rows: Iterable[FunctionTypesRow],
    out_path: str,
) -> None:
    with open_text_out(out_path) as f:
        for row in rows:
            f.write(json.dumps(asdict(row), sort_keys=True))
            f.write("\n")
```

Later, you can enhance:

* Detection of `# type:` comments (from CST or from raw source).
* Integration with any type‑inference or mypy outputs (to set `return_type_source="inferred"`).

---

### Phase 5 – Pipeline wiring & Document Output integration

#### 5.1 Enrich pipeline CLI

Assuming an existing CLI command like:

```bash
codeintel_rev.cli.enrich_pipeline all
```

and subcommands like `goids`, `callgraph`, `cfg`, `dfg`. 

Add two new subcommands:

* `analytics-function-metrics`
* `analytics-function-types`

Example CLI stubs:

```python
# codeintel_rev/cli/enrich_pipeline.py
import click

from codeintel_rev.services.enrich.pipeline import (
    run_function_metrics,
    run_function_types,
)

@click.group()
def enrich():
    ...

@enrich.command("function-metrics")
@click.option("--repo-root", required=True)
@click.option("--enriched-dir", required=True)
def function_metrics_cmd(repo_root: str, enriched_dir: str) -> None:
    run_function_metrics(repo_root=repo_root, enriched_dir=enriched_dir)


@enrich.command("function-types")
@click.option("--repo-root", required=True)
@click.option("--enriched-dir", required=True)
def function_types_cmd(repo_root: str, enriched_dir: str) -> None:
    run_function_types(repo_root=repo_root, enriched_dir=enriched_dir)
```

#### 5.2 Pipeline runners

Implement the runners in `services/enrich/pipeline.py`, similar to other analytics:

```python
# codeintel_rev/services/enrich/pipeline.py
from pathlib import Path
import libcst as cst

from codeintel_rev.enrich.goid_builder import load_goid_registry
from codeintel_rev.services.enrich.analytics.function_metrics import (
    build_function_metrics,
    write_function_metrics_jsonl,
)
from codeintel_rev.services.enrich.analytics.function_types import (
    build_function_types,
    write_function_types_jsonl,
)
from codeintel_rev.io.ast_cache import iter_cst_modules


def run_function_metrics(*, repo_root: str, enriched_dir: str) -> None:
    repo_root_path = Path(repo_root)
    enriched_path = Path(enriched_dir)
    goid_registry = load_goid_registry(enriched_path)

    out_path = enriched_path / "function_metrics.jsonl"

    all_rows = []
    for rel_path, module in iter_cst_modules(repo_root_path):
        rows = build_function_metrics(
            repo=goid_registry.repo,
            commit=goid_registry.commit,
            rel_path=rel_path,
            module=module,
            goid_registry=goid_registry,
        )
        all_rows.extend(rows)

    write_function_metrics_jsonl(all_rows, str(out_path))


def run_function_types(*, repo_root: str, enriched_dir: str) -> None:
    repo_root_path = Path(repo_root)
    enriched_path = Path(enriched_dir)
    goid_registry = load_goid_registry(enriched_path)

    out_path = enriched_path / "function_types.jsonl"

    all_rows = []
    for rel_path, module in iter_cst_modules(repo_root_path):
        rows = build_function_types(
            repo=goid_registry.repo,
            commit=goid_registry.commit,
            rel_path=rel_path,
            module=module,
            goid_registry=goid_registry,
        )
        all_rows.extend(rows)

    write_function_types_jsonl(all_rows, str(out_path))
```

`iter_cst_modules` should give you `(rel_path: str, module: cst.Module)` pairs reusing whatever AST/CST cache the `AstIndexer` already uses. 

#### 5.3 Document Output / Parquet integration

Follow the pattern for existing datasets like `goids` and `typedness`:

1. Write raw JSONL to `enriched/function_metrics.jsonl` and `enriched/function_types.jsonl`.

2. In `generate_documents.sh` (or equivalent), add DuckDB steps:

   ```sql
   CREATE TABLE function_metrics AS
   SELECT * FROM read_json_auto('enriched/function_metrics.jsonl');

   COPY function_metrics TO 'Document Output/function_metrics.parquet' (FORMAT PARQUET);
   COPY function_metrics TO 'Document Output/function_metrics.jsonl' (FORMAT JSON);
   ```

   Same for `function_types`.

3. Update the **CodeIntel Metadata Outputs** docs to describe the new sections “Function Metrics” and “Function Types” with their fields.

---

### Phase 6 – Testing & validation

#### 6.1 Unit tests

Create focused tests in e.g. `tests/enrich/test_function_metrics.py` and `tests/enrich/test_function_types.py`:

* Synthetic modules with:

  * Nested classes & methods.
  * Async functions, generators, functions with `raise`, `try/except`, `with`, comprehensions.
  * Various annotation patterns (fully typed, partial, untyped, `*args/**kwargs`).

Assertions:

* GOID join works and `function_goid_h128` matches a stubbed registry.
* Metrics (LOC, complexity, nesting depth, counts) match expectations.
* Typedness buckets (`typed`, `partial`, `untyped`) align with file‑level `typedness.jsonl` when aggregated.

Example test skeleton:

```python
def test_simple_function_metrics(goid_registry_for_test):
    code = '''
    def f(x: int, y: int) -> int:
        if x > 0:
            return x + y
        else:
            return y
    '''
    module = cst.parse_module(code)
    # attach PositionProvider metadata, etc.
    rows = list(build_function_metrics(
        repo="test", commit="deadbeef", rel_path="mod.py",
        module=module, goid_registry=goid_registry_for_test,
    ))
    assert len(rows) == 1
    row = rows[0]
    assert row.return_count == 2
    assert row.cyclomatic_complexity == 2  # if => 1 decision + base 1
    assert row.complexity_bucket == "low"
```

#### 6.2 Cross‑artifact sanity checks

Implement an integration test or small script:

* Aggregate `function_types.jsonl` by `rel_path` to compute:

  * `function_count`
  * `typed_functions`
  * `partial_functions`
  * `untyped_functions`
  * `typed_ratio`

  Then compare with `typedness.jsonl` on the same fields; they should match or be very close (accounting for any different filtering of what counts as a “function”). 

* Correlate `function_metrics.jsonl.cyclomatic_complexity` with `ast_metrics.jsonl.complexity` for a given file as a rough check. 

---

## 5. Future extensions (optional, but easy to add later)

Once these artifacts exist, it’s straightforward to:

* Add **type‑inferred types** (`inferred_return_type`, `inferred_param_types`) from a type checker.
* Surface **CFG‑backed metrics** (e.g., exact path counts) by joining `function_metrics` to `cfg_blocks` and `cfg_edges`. 
* Tag functions with **hotspot scores** by joining to `hotspots.jsonl` via `rel_path`. 

---

If you’d like, I can next:

* Tighten the schemas into a single shared `FunctionDescriptor` + `FunctionMetrics`/`FunctionTypes` model, or
* Draft the doc sections you’d add to your “CodeIntel Metadata Outputs” markdown for these two new datasets.

# tightened schemas and draft doc sections #

Awesome, let’s do it. Below are four concrete “drop-in” artifacts you can save as separate files in your repo.

---

## 1. `DOCUMENTATION_OVERVIEW.md`

```markdown
# CodeIntel Repository Graph – Documentation Overview

This directory contains the **pre-computed graph + metadata datasets** generated by the CodeIntel enrichment pipeline. The intent is to let humans and AI agents reason about the repository without rerunning heavy analysis jobs.

All artifacts live under:

- `Document Output/` – JSONL + Parquet exports of the repo graph
- `enriched/` (internal) – intermediate enrichment outputs that the doc generator copies from

The core concepts and files are summarized below. :contentReference[oaicite:0]{index=0}

---

## Key Concept: GOIDs

A **GOID** (Global Object ID) is a stable identifier for any Python entity in the repo (module, function, class, method, or CFG block).

- Canonical table:
  - `goids.parquet`, `goids.jsonl`
- Each row represents **one code entity** and contains:
  - `goid_h128`: 128‑bit hash used as a foreign key everywhere
  - `urn`: human-readable GOID (`goid:<repo>/<path>#python:<kind>:<qualname>?s=<start>&e=<end>`)
  - `rel_path`, `language`, `kind`, `qualname`, `start_line`, `end_line`, `commit`, `repo`

Think of GOIDs as “primary keys” for code.

---

## Core Datasets

### 1. GOID Registry

- Files: `goids.parquet`, `goids.jsonl`
- Grain: **one row per code entity**
- Use when you need:
  - A canonical list of modules, functions, classes
  - Line ranges / paths for an entity
  - A join key for other graph tables

### 2. GOID Crosswalk

- Files: `goid_crosswalk.parquet`, `goid_crosswalk.jsonl`
- Grain: **one row per GOID × structural source**
- Bridges GOIDs to:
  - AST (qualname + line spans)
  - SCIP symbols (`scip_symbol`)
  - Embedding chunks (`chunk_id`)
  - File/module paths
- Use to:
  - Map from “whatever identifier I have” → GOID
  - Link embeddings or SCIP data back into the graph

---

### 3. Call Graph

- Files: `call_graph_nodes.*`, `call_graph_edges.*`
- Nodes: one row per callable (function, method, class `__call__`)
- Edges: one row per callsite:
  - `caller_goid_h128`, `callee_goid_h128`
  - `callsite_path`, `callsite_line`, `callsite_col`
  - `kind` (direct, builtin, etc.), `resolved_via` (scip/scope/heuristic), `confidence`
- Use for:
  - Impact analysis (who calls what)
  - Finding entrypoints, leaf functions, or highly connected hubs

---

### 4. Control-Flow Graph (CFG)

- Files: `cfg_blocks.*`, `cfg_edges.*`
- Blocks:
  - Grain: **per basic block** within a function
  - Includes `block_idx`, `kind` (entry/body/exit/handler), line range, and `stmts_json`
- Edges:
  - Grain: **per control-flow edge** (fallthrough/true/false/loop/exception)
  - Includes source/destination block indices and optional guard condition (`cond_json`)
- Use for:
  - Control-flow reasoning per function
  - Detecting complex branching and exception handling

---

### 5. Data-Flow Graph (DFG)

- Files: `dfg_edges.*`
- Grain: **per def→use relationship** between basic blocks in a function
- Columns include:
  - `src_block_idx`, `dst_block_idx`
  - `src_symbol`, `dst_symbol`
  - `use_kind` (read/write/update)
  - `via_phi` (SSA-style merges)
- Use for:
  - Tracing how values propagate through a function
  - Spotting where critical variables are defined/used

---

### 6. AST-Level Datasets

- `ast_nodes.jsonl`
  - Raw LibCST/AST node records with qualnames, spans, parent scopes, docstrings
- `ast_metrics.jsonl`
  - Per-file aggregate metrics: node counts, function/class counts, nesting depth, complexity

Use these when you need:
- Low-level structural detail (AST-level refactoring, doc generation)
- Heuristics such as “most complex files” or “deeply nested code”

---

### 7. Analytics: Hotspots & Typedness

- `hotspots.jsonl`
  - Per-file commit/churn metrics + complexity + a composite hotspot score
- `typedness.jsonl`
  - Per-file/function type annotation coverage and typed ratio

Use for:
- Prioritizing refactors
- Targeting type-hint migration work
- Finding risky or frequently changing files

---

### 8. Tagging & Ownership

- `tags_index.yaml`
  - Rules mapping paths to semantic tags (e.g., `api`, `infra`, `ml`)
  - Lists matched files and inferred owners

Use for:
- Filtering analyses (e.g., only `api` modules)
- Routing ownership / reviews to the right teams

---

### 9. SCIP Index

- `index.scip.json`
  - Language-agnostic symbol graph from `scip-python`
  - Contains:
    - `documents` (files)
    - `occurrences` (definitions & references)
    - `symbols` (metadata, docs, signatures)
- Cross-join to GOIDs via `goid_crosswalk.scip_symbol`

Use for:
- Cross-language search and navigation
- High-fidelity definition/reference info

---

### 10. Modules & Repo Map

- `modules.jsonl`
  - One row per module: module name, path, repo, commit, tags, owners
- `repo_map.json`
  - Top-level repo metadata:
    - `repo`, `commit`
    - Module→path mappings
    - Overlays and generation timestamp

Use for:
- High-level indexing
- Mapping module names to files and vice versa

---

### 11. CST Nodes

- `cst_nodes.jsonl`
  - Concrete Syntax Tree nodes with exact spans, parent stacks, and previews
- Use when:
  - You need exact whitespace/comments or precise editing locations
  - Building tools that rewrite code while preserving formatting

---

## Typical Workflows

### For Data/Analytics Folks

- Load Parquet into DuckDB or similar
- Use `goid_h128` (or GOID URN) to:
  - Join call graph nodes/edges
  - Join CFG/DFG to functions
  - Join AST/SCIP data via the crosswalk

### For AI Agents

- Use `goids.jsonl` as the master entity list
- Resolve any symbol, file, or chunk → GOID via `goid_crosswalk`
- Traverse call graph, CFG, DFG, or hotspots using GOIDs as keys
- Re-run `generate_documents.sh` after code changes to refresh everything

For examples and recipes, see:

- `DATASET_CHEATSHEET.md`
- `DUCKDB_STARTER_QUERIES.sql`
- `LLM_AGENT_PLAYBOOK.md`
```

---

## 2. `DATASET_CHEATSHEET.md`

```markdown
# CodeIntel Datasets – Quick Cheatsheet

This is a compact reference for the graph + metadata tables under `Document Output/`.

---

## Legend

- **Row grain**: “What does one row represent?”
- **PK**: Primary key (or closest equivalent)
- **Joins**: How this table typically links to others

---

### GOID Registry

- Files: `goids.parquet`, `goids.jsonl`
- Row grain: **one code entity (module/function/class/method/block)**
- PK: `goid_h128`
- Joins:
  - `call_graph_nodes.goid_h128`
  - `cfg_blocks.function_goid_h128`
  - `dfg_edges.function_goid_h128`
  - `goid_crosswalk.goid` / `goid_h128` (via URN or hash)
- Typical questions:
  - “What file and line range does this entity live in?”
  - “Show me all entities in `codeintel_rev/app/routes`.”

---

### GOID Crosswalk

- Files: `goid_crosswalk.parquet`, `goid_crosswalk.jsonl`
- Row grain: **one GOID × structural source (AST, SCIP, embedding chunk, etc.)**
- PK-ish: `(goid, chunk_id, scip_symbol, start_line, end_line)` (not strictly enforced)
- Joins:
  - `goids.urn` ↔ `goid_crosswalk.goid`
  - `index.scip.json.symbol` ↔ `goid_crosswalk.scip_symbol`
  - Embedding tables via `chunk_id`
- Typical questions:
  - “Given this SCIP symbol / chunk ID, what code entity is it?”
  - “Where in the file is this GOID anchored?”

---

### Call Graph

**Nodes**

- Files: `call_graph_nodes.*`
- Row grain: **one callable**
- PK: `goid_h128` (matches `goids.goid_h128`)
- Joins:
  - `goids.goid_h128` for qualname, path, etc.
- Questions:
  - “List all callables in this module.”
  - “Which callables are public vs private?”

**Edges**

- Files: `call_graph_edges.*`
- Row grain: **one callsite**
- PK-ish: `(caller_goid_h128, callee_goid_h128, callsite_line, callsite_col)`
- Joins:
  - `call_graph_nodes.goid_h128` (caller/callee)
  - `goids.goid_h128` for richer metadata
- Questions:
  - “Who calls function X?”
  - “Which functions are heavily depended on?”
  - “What’s the fan-in/out of a given module?”

---

### Control-Flow Graph (CFG)

**Blocks**

- Files: `cfg_blocks.*`
- Row grain: **one basic block in a function**
- PK: `(function_goid_h128, block_idx)`
- Joins:
  - `goids.goid_h128` (function metadata)
  - `cfg_edges` via `(function_goid_h128, block_idx)`
- Questions:
  - “How many blocks does this function have?”
  - “Where are the entry/exit/exception blocks?”

**Edges**

- Files: `cfg_edges.*`
- Row grain: **one control-flow edge**
- PK: `(function_goid_h128, src_block_idx, dst_block_idx, edge_type)`
- Joins:
  - `cfg_blocks` on `function_goid_h128` + block indices
- Questions:
  - “Show the branching structure for function X.”
  - “Where does this loop back-edge go?”

---

### Data-Flow Graph (DFG)

- Files: `dfg_edges.*`
- Row grain: **one def→use flow between blocks**
- PK-ish: `(function_goid_h128, src_block_idx, dst_block_idx, src_symbol, dst_symbol)`
- Joins:
  - `cfg_blocks` via block indices
  - `goids` via `function_goid_h128`
- Questions:
  - “Where is variable `foo` defined and used?”
  - “What blocks consume data from this block?”

---

### AST Datasets

**AST Nodes**

- Files: `ast_nodes.jsonl`
- Row grain: **one AST node**
- Joins:
  - `goid_crosswalk` via path + qualname + line range (indirect)
- Questions:
  - “What’s the docstring for this function?”
  - “Give me all `ClassDef` nodes in a file.”

**AST Metrics**

- Files: `ast_metrics.jsonl`
- Row grain: **one file**
- PK: `rel_path`
- Questions:
  - “What are the most complex files?”
  - “Which files have the deepest nesting?”

---

### Analytics

**Hotspots**

- Files: `hotspots.jsonl`
- Row grain: **one file**
- PK: `rel_path`
- Questions:
  - “What are the top N hotspot files?”
  - “Which files saw the most churn recently?”

**Typedness**

- Files: `typedness.jsonl`
- Row grain: **one file (plus aggregated function stats)**
- PK: `rel_path`
- Questions:
  - “Which files are least typed?”
  - “Where should we invest in type hints first?”

---

### Tags & Repo Metadata

**Tags Index**

- Files: `tags_index.yaml`
- Row grain: **one tag rule**, including its matched files
- Questions:
  - “Which files are tagged `api`?”
  - “What tags apply to a given path?”

**Modules**

- Files: `modules.jsonl`
- Row grain: **one module**
- PK: `module`
- Questions:
  - “What path corresponds to this module name?”
  - “What tags/owners does this module have?”

**Repo Map**

- Files: `repo_map.json`
- Row grain: **single JSON object describing the repo**
- Questions:
  - “What’s the current commit?”
  - “List all module→path mappings.”

---

### SCIP & CST

**SCIP Index**

- Files: `index.scip.json`
- Row grain: **per SCIP document / occurrence / symbol**
- Joins:
  - `goid_crosswalk.scip_symbol`
- Questions:
  - “Where is symbol X defined and referenced?”
  - “What’s the signature and docs for this symbol?”

**CST Nodes**

- Files: `cst_nodes.jsonl`
- Row grain: **one CST node**
- Questions:
  - “What’s the exact text and span for this syntax node?”
  - “Where are comments around this function/class?”
```

---

## 3. `DUCKDB_STARTER_QUERIES.sql`

```sql
-- DUCKDB_STARTER_QUERIES.sql
-- Utility queries for exploring the CodeIntel graph datasets.

-- 1. Setup: enable Parquet
INSTALL parquet;
LOAD parquet;

-- Adjust the paths if your directory layout differs.
-- Using views keeps things simple for ad-hoc querying.

CREATE OR REPLACE VIEW goids AS
    SELECT * FROM read_parquet('Document Output/goids.parquet');

CREATE OR REPLACE VIEW goid_crosswalk AS
    SELECT * FROM read_parquet('Document Output/goid_crosswalk.parquet');

CREATE OR REPLACE VIEW call_nodes AS
    SELECT * FROM read_parquet('Document Output/call_graph_nodes.parquet');

CREATE OR REPLACE VIEW call_edges AS
    SELECT * FROM read_parquet('Document Output/call_graph_edges.parquet');

CREATE OR REPLACE VIEW cfg_blocks AS
    SELECT * FROM read_parquet('Document Output/cfg_blocks.parquet');

CREATE OR REPLACE VIEW cfg_edges AS
    SELECT * FROM read_parquet('Document Output/cfg_edges.parquet');

CREATE OR REPLACE VIEW dfg_edges AS
    SELECT * FROM read_parquet('Document Output/dfg_edges.parquet');

CREATE OR REPLACE VIEW ast_metrics AS
    SELECT * FROM read_parquet('Document Output/ast_metrics.parquet');

CREATE OR REPLACE VIEW hotspots AS
    SELECT * FROM read_parquet('Document Output/hotspots.parquet');

CREATE OR REPLACE VIEW typedness AS
    SELECT * FROM read_parquet('Document Output/typedness.parquet');

---------------------------------------------------------------------
-- A. Repo-Level Summaries
---------------------------------------------------------------------

-- A1. Count entities by kind
SELECT kind, COUNT(*) AS entity_count
FROM goids
GROUP BY kind
ORDER BY entity_count DESC;

-- A2. Top 20 files by number of entities
SELECT rel_path, COUNT(*) AS entity_count
FROM goids
GROUP BY rel_path
ORDER BY entity_count DESC
LIMIT 20;

-- A3. Most complex files by AST complexity
SELECT rel_path, complexity, node_count, function_count, class_count
FROM ast_metrics
ORDER BY complexity DESC
LIMIT 20;

---------------------------------------------------------------------
-- B. Call Graph Exploration
---------------------------------------------------------------------

-- B1. Fan-out: functions that call many other functions
SELECT
    g.qualname AS caller_qualname,
    g.rel_path AS caller_path,
    COUNT(DISTINCT e.callee_goid_h128) AS callee_count
FROM call_edges e
JOIN goids g ON e.caller_goid_h128 = g.goid_h128
WHERE e.callee_goid_h128 IS NOT NULL
GROUP BY g.qualname, g.rel_path
ORDER BY callee_count DESC
LIMIT 20;

-- B2. Fan-in: functions that are heavily depended on
SELECT
    g.qualname AS callee_qualname,
    g.rel_path AS callee_path,
    COUNT(DISTINCT e.caller_goid_h128) AS caller_count
FROM call_edges e
JOIN goids g ON e.callee_goid_h128 = g.goid_h128
GROUP BY g.qualname, g.rel_path
ORDER BY caller_count DESC
LIMIT 20;

-- B3. Calls within a specific module (replace with your module path)
-- Example: focus on calls inside "codeintel_rev/app/routes"
SELECT
    caller.qualname AS caller,
    callee.qualname AS callee,
    e.callsite_path,
    e.callsite_line
FROM call_edges e
JOIN goids caller ON e.caller_goid_h128 = caller.goid_h128
JOIN goids callee ON e.callee_goid_h128 = callee.goid_h128
WHERE caller.rel_path LIKE 'codeintel_rev/app/routes/%'
ORDER BY e.callsite_path, e.callsite_line
LIMIT 200;

---------------------------------------------------------------------
-- C. Hotspots & Typedness
---------------------------------------------------------------------

-- C1. Top hotspots by score
SELECT rel_path, score, commit_count, author_count, lines_added, lines_deleted, complexity
FROM hotspots
ORDER BY score DESC
LIMIT 20;

-- C2. Files with the worst type coverage
SELECT
    rel_path,
    typed_ratio,
    typed_functions,
    partial_functions,
    untyped_functions
FROM typedness
ORDER BY typed_ratio ASC
LIMIT 20;

---------------------------------------------------------------------
-- D. CFG & DFG Examples
---------------------------------------------------------------------

-- D1. Size of functions in terms of CFG blocks
SELECT
    g.qualname AS function_name,
    g.rel_path,
    COUNT(*) AS block_count
FROM cfg_blocks b
JOIN goids g ON b.function_goid_h128 = g.goid_h128
GROUP BY g.qualname, g.rel_path
ORDER BY block_count DESC
LIMIT 20;

-- D2. Data-flow edges for a specific function (by qualname pattern)
-- Adjust the WHERE clause to match your function name.
WITH target_function AS (
    SELECT DISTINCT goid_h128
    FROM goids
    WHERE qualname LIKE '%your_function_name_here%'
)
SELECT
    d.function_goid_h128,
    d.src_block_idx,
    d.dst_block_idx,
    d.src_symbol,
    d.dst_symbol,
    d.use_kind,
    d.via_phi
FROM dfg_edges d
JOIN target_function t ON d.function_goid_h128 = t.goid_h128
ORDER BY d.src_block_idx, d.dst_block_idx
LIMIT 200;

---------------------------------------------------------------------
-- E. Mapping External Identifiers Back to GOIDs
---------------------------------------------------------------------

-- E1. Given a file path and line range, find corresponding GOIDs
-- Replace the path and line bounds as needed.
SELECT *
FROM goid_crosswalk
WHERE file_path = 'codeintel_rev/app/routes/catalog_read.py'
  AND start_line <= 100
  AND (end_line IS NULL OR end_line >= 80)
ORDER BY start_line;

-- E2. Count GOIDs per module
SELECT
    module_path,
    COUNT(DISTINCT goid) AS goid_count
FROM goid_crosswalk
GROUP BY module_path
ORDER BY goid_count DESC
LIMIT 50;
```

---

## 4. `LLM_AGENT_PLAYBOOK.md`

```markdown
# LLM Agent Playbook for CodeIntel Graph Datasets

This document is intended to be **fed directly to AI agents** that need to answer questions about the repository using the precomputed graph datasets.

---

## Mental Model

- The codebase is represented as a set of **graph tables** under `Document Output/`.
- **GOIDs** are the universal identifiers for code entities (functions, classes, modules, blocks).
- You should:
  1. Map any external reference (file, symbol, chunk, SCIP symbol) → GOID
  2. Use GOIDs to traverse call graphs, control-flow graphs, data-flow graphs, and analytics
  3. Provide answers in terms of **file paths, line ranges, and qualified names** so humans and tools can act on them

---

## Step 1: Resolve Entities to GOIDs

Given a question, your first goal is to identify which entities are involved.

### If you have a file + line range

- Use `goid_crosswalk`:
  - Filter by `file_path`, `start_line`, `end_line`
  - Retrieve the corresponding `goid`

### If you have a symbol name (e.g. `my_module.MyClass.my_method`)

- Use `goids`:
  - Filter by `qualname` (or suffix match)
  - Optionally narrow by `rel_path` or `kind`

### If you have a SCIP symbol

- Use `goid_crosswalk`:
  - Look up `scip_symbol`
  - Read `goid` and then join to `goids` for metadata

Once you have one or more GOIDs, treat them as your canonical anchors.

---

## Step 2: Reason About Call Relationships

Use `call_graph_nodes` and `call_graph_edges`.

### Questions you can answer

- “What does this function depend on?”
  - Treat as **fan-out**:
    - Use `call_edges` where `caller_goid_h128` = target GOID
    - Join to `goids` on `callee_goid_h128` for names and paths

- “Who depends on this function?”
  - Treat as **fan-in**:
    - Use `call_edges` where `callee_goid_h128` = target GOID
    - Join to `goids` on `caller_goid_h128`

- “Which functions are safe to change?”
  - Prefer:
    - Low fan-in (few callers)
    - Localized to a single module
  - Cross-reference with `hotspots` and `typedness` if needed

When reporting results, include:
- Callable qualname
- File path
- Callsite line numbers (from `call_edges`)

---

## Step 3: Reason About Control Flow

Use `cfg_blocks` and `cfg_edges`.

### How to think about CFG

- Each function has:
  - An entry block, several body/handler blocks, and an exit block
- Edges show how execution can flow between them:
  - `fallthrough`, `true`, `false`, `loop`, `exception`

### Questions you can answer

- “How complex is this function’s branching?”
  - Count blocks and edges for the function’s GOID
  - Look for many conditional edges (`true` / `false` / `exception`)

- “What are the possible paths to a given line?”
  - Map line → block(s) using `cfg_blocks.start_line/end_line`
  - Walk predecessor edges in `cfg_edges` towards the entry block

- “Where can this exception handler be reached from?”
  - Find blocks with `kind = 'handler'`
  - Walk incoming `exception` edges from other blocks

Always translate block-level findings into:
- File path
- Line ranges (`start_line`, `end_line`)
- Function name (`goids.qualname` joined via `function_goid_h128`)

---

## Step 4: Reason About Data Flow

Use `dfg_edges`.

### Questions you can answer

- “Where is variable X defined and read?”
  - Filter `dfg_edges` by `src_symbol = 'X'` or `dst_symbol = 'X'`
  - Map blocks back to line ranges via `cfg_blocks`

- “What values can reach this use-site?”
  - Identify the `dst_block_idx` and `dst_symbol` for the use
  - Walk backwards along `dfg_edges` where `dst_symbol` matches
  - Combine with `via_phi` flags to understand merges

When presenting results:
- Group definitions and uses
- Provide function name, file path, and line ranges for each block

---

## Step 5: Use Analytics to Prioritize and Summarize

Use `ast_metrics`, `hotspots`, `typedness`:

- To prioritize:
  - Favour hotspot files (`hotspots.score` high) for risk assessment
  - Identify low-typed files (`typedness.typed_ratio` low) for type migration

- To summarize:
  - Use `ast_metrics` to describe complexity:
    - e.g., “This file has X functions, Y classes, complexity Z”

Use these when asked:
- “What are the riskiest parts of the system?”
- “Where should we start improving types or refactors?”

---

## Step 6: Tag- and Ownership-Aware Reasoning

- Use `tags_index.yaml` and `modules.jsonl`:
  - Restrict analysis to specific tags (e.g., `api`, `infra`)
  - Identify owners for impacted modules

Example flows:
- “Impact of changing an API entrypoint”
  1. Resolve API function → GOID
  2. Traverse call graph to internal dependencies
  3. Map all involved modules → owners via tags/owners
  4. Output a summary grouped by owner or tag

---

## Answer Style Guidelines

When answering user queries:

1. **Ground responses** in:
   - File paths
   - Line ranges
   - Qualified names

2. **Explain how you derived the result** in high-level terms:
   - “By following incoming call edges to this function…”
   - “By examining CFG blocks covering lines 50–90…”

3. **Mention limitations** when appropriate:
   - Static call graph may miss dynamic dispatch or reflection
   - CFG/DFG are intra-procedural (within a single function)

4. **Propose next steps**:
   - “Consider adding tests around these high-fan-in functions…”
   - “This low-typed hotspot file is a good candidate for annotations.”

With these rules, you can use the precomputed datasets to provide precise, actionable answers about the repository without re-running any code analysis.
```

