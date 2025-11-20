
# third data set implement plan #

Here’s a third implementation plan that’s structured and opinionated in the same spirit as your first two scope docs, and assumes those plans are implemented (function metrics/types, config_values, static_diagnostics, import & symbol graphs, etc.).

I’ll break it into:

1. Data models & file layout
2. Coverage ingestion → `coverage_lines.*`
3. Function-level coverage → `coverage_functions.*`
4. Test catalog from pytest → `test_catalog.*`
5. Dynamic test→function mapping → `test_coverage_edges.*`
6. GOID risk factors join → `goid_risk_factors.*`
7. Pipeline wiring (CLI + `generate_documents.sh` + DuckDB)
8. Testing & validation

I’ll use the same idioms as your existing plans: JSONL from enrichment, Parquet/JSONL in `Document Output/`, DuckDB catalog, GOIDs as the central join key.

---

## 0. Assumptions & overall flow

**Assumptions**

* You run tests with `coverage.py` enabled, producing a `.coverage` data file (or equivalent).
* You enable **dynamic contexts** in coverage (`dynamic_context = test_function`), so coverage data carries per-test contexts.
* You can get a pytest JSON report (e.g. via `pytest-json-report`) containing tests, outcomes, durations, markers.
* `goids.*`, `goid_crosswalk.*`, `hotspots.jsonl`, `typedness.jsonl`, `static_diagnostics.jsonl`, `function_metrics.jsonl`, `function_types.jsonl` are all in place per the earlier plans.

**New artifacts (all duplicated as Parquet + JSONL in `Document Output/`)**

* `coverage_lines.*` — per file + line coverage
* `coverage_functions.*` — per function GOID coverage
* `test_catalog.*` — per test node
* `test_coverage_edges.*` — test↔function coverage edges
* `goid_risk_factors.*` — per-function risk features + aggregate risk score

**High-level pipeline**

1. **Coverage analytics**: ingest `.coverage` and compute `coverage_lines` and `coverage_functions`.
2. **Test analytics**: ingest pytest JSON report and compute `test_catalog`.
3. **Test–coverage join**: use coverage contexts + GOID spans → `test_coverage_edges`.
4. **Risk factors join**: combine coverage, tests, function metrics/types, hotspots, typedness, static diagnostics → `goid_risk_factors`.
5. Register all of these in DuckDB + document them in `README_METADATA.md` / cheatsheet / playbook.

---

## 1. Data models & file layout

### 1.1 `coverage_lines.*`

**Row grain**: one row per *file × line*.

**Enriched path**

* `enriched/analytics/coverage/coverage_lines.jsonl`
* (Optionally `enriched/analytics/coverage/coverage_lines.parquet`)

**Document Output**

* `Document Output/coverage_lines.parquet`
* `Document Output/coverage_lines.jsonl`

**Schema (logical)**

```text
repo: string
commit: string
rel_path: string        # repo-relative path
line: int               # 1-based line number
is_executable: bool     # in coverage's "statements" set
is_covered: bool        # executed at least once
hits: int               # best-effort (1 if only boolean info available)
context_count: int      # number of distinct coverage contexts for this line
created_at: string      # ISO8601
```

This gives LLMs a simple per-line coverage view that can be joined to GOIDs via `goid_crosswalk.file_path + start_line/end_line`.

---

### 1.2 `coverage_functions.*`

**Row grain**: one row per *function GOID*.

**Enriched path**

* `enriched/analytics/coverage/coverage_functions.jsonl`

**Document Output**

* `Document Output/coverage_functions.parquet`
* `Document Output/coverage_functions.jsonl`

**Schema**

```text
function_goid_h128: string
urn: string
repo: string
commit: string
rel_path: string
language: string        # 'python'
kind: string            # 'function', 'method', 'async_function', etc.
qualname: string
start_line: int
end_line: int

executable_lines: int
covered_lines: int
coverage_ratio: float   # covered_lines / executable_lines, null if no exec lines

tested: bool            # coverage_ratio > 0
untested_reason: string # 'no_executable_code' | 'no_tests' | 'unknown' or ''
created_at: string
```

This is your canonical “coverage for this function” dataset that can be joined to `goids`, `function_metrics`, and `function_types`.

---

### 1.3 `test_catalog.*`

**Row grain**: one row per pytest test node.

**Enriched path**

* `enriched/analytics/tests/test_catalog.jsonl`

**Document Output**

* `Document Output/test_catalog.parquet`
* `Document Output/test_catalog.jsonl`

**Schema**

```text
test_id: string         # pytest nodeid: 'path/test_file.py::TestClass::test_func[param]'
test_goid_h128: string|null
urn: string|null
repo: string
commit: string
rel_path: string        # path of defining file (from nodeid)
qualname: string|null   # class.method or function name
kind: string            # 'function', 'method', 'parametrized_case', etc.

status: string          # 'passed' | 'failed' | 'error' | 'skipped' | 'xfailed' | ...
duration_ms: float
markers: list<string>   # pytest marks / keywords
parametrized: bool
flaky: bool             # derived from markers (marker name 'flaky' etc.)

created_at: string
```

This links runtime test behaviour back to GOIDs (where possible) and file paths.

---

### 1.4 `test_coverage_edges.*`

**Row grain**: one row per *test_id × function_goid* pair where the test executed at least one line of the function.

**Enriched path**

* `enriched/analytics/tests/test_coverage_edges.jsonl`

**Document Output**

* `Document Output/test_coverage_edges.parquet`
* `Document Output/test_coverage_edges.jsonl`

**Schema**

```text
test_id: string
test_goid_h128: string|null

function_goid_h128: string
urn: string
repo: string
commit: string
rel_path: string
qualname: string

covered_lines: int          # lines in this function executed by this test
executable_lines: int       # total executable lines in this function
coverage_ratio: float       # covered_lines / executable_lines (per test)
last_status: string         # status of this test in the run used

created_at: string
```

You can derive `test_count` / `failing_test_count` per function by aggregating this table.

---

### 1.5 `goid_risk_factors.*`

**Row grain**: one row per *function GOID* with risk-related features.

**Enriched path**

* `enriched/analytics/risk/goid_risk_factors.jsonl`

**Document Output**

* `Document Output/goid_risk_factors.parquet`
* `Document Output/goid_risk_factors.jsonl`

**Schema (v1)**

```text
function_goid_h128: string
urn: string
repo: string
commit: string
rel_path: string
language: string
kind: string
qualname: string
start_line: int
end_line: int

# From function_metrics.jsonl
loc: int|null
logical_loc: int|null
cyclomatic_complexity: int|null
complexity_bucket: string|null      # low | medium | high

# From function_types.jsonl
typedness_bucket: string|null       # typed | partial | untyped
typedness_source: string|null       # annotations | mixed | unknown

# From hotspots.jsonl (file-level)
hotspot_score: float|null
commit_count: int|null
author_count: int|null

# From typedness.jsonl (file-level)
file_typed_ratio: float|null

# From static_diagnostics.jsonl (file-level)
static_error_count: int|null
has_static_errors: bool|null

# From coverage_functions.jsonl
executable_lines: int|null
covered_lines: int|null
coverage_ratio: float|null
tested: bool|null

# From test_coverage_edges.jsonl
test_count: int                    # distinct tests touching this function
failing_test_count: int
last_test_status: string           # 'all_passing' | 'some_failing' | 'untested'

# Derived risk
risk_score: float                  # 0..1
risk_level: string                 # low | medium | high

# Tags / ownership (optional)
tags: list<string>                 # from modules.jsonl / tags_index
owners: list<string>

created_at: string
```

This table is what you’ll hand directly to LLM agents when they ask “what should I fix first?” — they can sort by `risk_score` and then join out to the rest of the graph.

---

## 2. Coverage ingestion → `coverage_lines.*`

We’ll treat coverage ingestion as an analytics module that reads a `.coverage` file (or equivalent) and repo root, then emits normalized line-level rows.

### 2.1 New analytics module

Create `codeintel_rev/services/enrich/analytics/coverage_lines.py`:

```python
# codeintel_rev/services/enrich/analytics/coverage_lines.py
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Iterator

import coverage  # type: ignore[import]

from codeintel_rev.io.text import open_text_out
from codeintel_rev.services.enrich.pipeline_helpers import normalized_rel_path
from codeintel_rev.io.repo import find_repo_root  # or whatever helper you use


@dataclass
class CoverageLineRow:
    repo: str
    commit: str
    rel_path: str
    line: int
    is_executable: bool
    is_covered: bool
    hits: int
    context_count: int
    created_at: str


def _iter_coverage_lines_for_file(
    cov: coverage.Coverage,
    repo_root: Path,
    repo: str,
    commit: str,
    abs_path: str,
) -> Iterator[CoverageLineRow]:
    """Yield CoverageLineRow for a single file."""

    # Normalize path to repo-relative
    rel_path = normalized_rel_path(repo_root, Path(abs_path))

    # Using coverage's analysis API – adjust if you prefer analysis2()
    analysis = cov._analyze(abs_path)  # type: ignore[attr-defined]
    executable = set(analysis.statements)
    executed = set(analysis.executed)

    # Dynamic contexts (may not be present if not configured)
    data = cov.get_data()
    contexts_by_lineno = {}
    if hasattr(data, "contexts_by_lineno"):
        contexts_by_lineno = data.contexts_by_lineno(abs_path)  # type: ignore[attr-defined]

    now = datetime.datetime.utcnow().isoformat() + "Z"

    for line in sorted(executable):
        is_covered = line in executed
        ctxs = contexts_by_lineno.get(line, []) if contexts_by_lineno else []
        context_count = len(ctxs)
        # Many coverage backends don't track hit counts; treat as 1 if covered.
        hits = 1 if is_covered else 0

        yield CoverageLineRow(
            repo=repo,
            commit=commit,
            rel_path=str(rel_path),
            line=line,
            is_executable=True,
            is_covered=is_covered,
            hits=hits,
            context_count=context_count,
            created_at=now,
        )


def build_coverage_lines(
    *,
    repo: str,
    commit: str,
    repo_root: Path,
    coverage_file: Path,
) -> Iterable[CoverageLineRow]:
    cov = coverage.Coverage(data_file=str(coverage_file))
    cov.load()

    for abs_path in cov.get_data().measured_files():
        # Skip files not under repo_root (e.g., site-packages)
        try:
            Path(abs_path).relative_to(repo_root)
        except ValueError:
            continue

        yield from _iter_coverage_lines_for_file(
            cov=cov,
            repo_root=repo_root,
            repo=repo,
            commit=commit,
            abs_path=abs_path,
        )


def write_coverage_lines_jsonl(
    rows: Iterable[CoverageLineRow],
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open_text_out(out_path) as f:
        for row in rows:
            f.write(json.dumps(asdict(row), sort_keys=True))
            f.write("\n")
```

You can swap in your own `coverage_ingest` abstraction instead of importing `coverage` directly; the important part is the row shape.

---

## 3. Function-level coverage → `coverage_functions.*`

Now we aggregate lines into per-function coverage using GOIDs.

### 3.1 Build a function span index from GOIDs

Add a small helper to `codeintel_rev/enrich/goid_utils.py` (same module you used for function metrics).

```python
# codeintel_rev/enrich/goid_utils.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from codeintel_rev.enrich.goid_builder import GOIDRegistry, EntityKind


@dataclass(frozen=True)
class FunctionSpan:
    goid_h128: str
    urn: str
    rel_path: str
    kind: str
    qualname: str
    start_line: int
    end_line: int


def build_function_span_index(registry: GOIDRegistry) -> Dict[str, List[FunctionSpan]]:
    """
    Build mapping: rel_path -> sorted list of FunctionSpan.

    Sorting by start_line allows cheap "which function owns this line" queries.
    """
    by_path: dict[str, list[FunctionSpan]] = {}

    for entity in registry.iter_entities(kind=EntityKind.FUNCTION):
        span = FunctionSpan(
            goid_h128=str(entity.goid_h128),
            urn=entity.urn,
            rel_path=entity.rel_path,
            kind=entity.kind,
            qualname=entity.qualname,
            start_line=entity.start_line or 0,
            end_line=entity.end_line or entity.start_line or 0,
        )
        by_path.setdefault(entity.rel_path, []).append(span)

    for spans in by_path.values():
        spans.sort(key=lambda s: (s.start_line, s.end_line))

    return by_path


def lookup_function_for_line(
    *,
    index_by_path: Dict[str, List[FunctionSpan]],
    rel_path: str,
    line: int,
) -> Optional[FunctionSpan]:
    """Find the innermost function span containing (rel_path, line)."""
    spans = index_by_path.get(rel_path)
    if not spans:
        return None

    # Simple linear search is likely fine; you can add bisect for huge files.
    best: Optional[FunctionSpan] = None
    for span in spans:
        if span.start_line <= line <= span.end_line:
            if best is None or (span.end_line - span.start_line) < (
                best.end_line - best.start_line
            ):
                best = span
    return best
```

This leans on GOID metadata fields already described in `README_METADATA.md`.

### 3.2 Aggregate coverage_lines into coverage_functions

New module: `codeintel_rev/services/enrich/analytics/coverage_functions.py`.

```python
# codeintel_rev/services/enrich/analytics/coverage_functions.py
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, Iterator, Tuple

from codeintel_rev.enrich.goid_builder import load_goid_registry
from codeintel_rev.enrich.goid_utils import (
    build_function_span_index,
    lookup_function_for_line,
    FunctionSpan,
)
from codeintel_rev.io.text import open_text_out
from codeintel_rev.services.enrich.analytics.coverage_lines import CoverageLineRow


@dataclass
class CoverageFunctionRow:
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

    executable_lines: int
    covered_lines: int
    coverage_ratio: float | None

    tested: bool
    untested_reason: str
    created_at: str


def aggregate_coverage_functions(
    *,
    enriched_dir: Path,
    coverage_lines_path: Path,
) -> Iterable[CoverageFunctionRow]:
    """Aggregate coverage_lines into per-function coverage."""
    registry = load_goid_registry(enriched_dir)
    index_by_path = build_function_span_index(registry)

    # Counters keyed by function_goid_h128
    counts: Dict[str, Dict[str, int]] = {}

    def _bump(goid: str, key: str) -> None:
        bucket = counts.setdefault(goid, {"exec": 0, "cov": 0})
        bucket[key] += 1

    # First pass: read coverage_lines and assign lines to functions
    with coverage_lines_path.open("r", encoding="utf-8") as f:
        for line in f:
            row = CoverageLineRow(**json.loads(line))
            if not row.is_executable:
                continue
            span = lookup_function_for_line(
                index_by_path=index_by_path,
                rel_path=row.rel_path,
                line=row.line,
            )
            if not span:
                continue
            _bump(span.goid_h128, "exec")
            if row.is_covered:
                _bump(span.goid_h128, "cov")

    now = datetime.datetime.utcnow().isoformat() + "Z"

    # Build final rows by joining counts back to GOID registry
    for rel_path, spans in index_by_path.items():
        for span in spans:
            c = counts.get(span.goid_h128, {"exec": 0, "cov": 0})
            exec_lines = c["exec"]
            cov_lines = c["cov"]
            coverage_ratio = (
                cov_lines / exec_lines if exec_lines > 0 else None
            )
            tested = cov_lines > 0
            if exec_lines == 0:
                untested_reason = "no_executable_code"
            elif not tested:
                untested_reason = "no_tests"
            else:
                untested_reason = ""

            yield CoverageFunctionRow(
                function_goid_h128=span.goid_h128,
                urn=span.urn,
                repo=registry.repo,
                commit=registry.commit,
                rel_path=span.rel_path,
                language="python",
                kind=span.kind,
                qualname=span.qualname,
                start_line=span.start_line,
                end_line=span.end_line,
                executable_lines=exec_lines,
                covered_lines=cov_lines,
                coverage_ratio=coverage_ratio,
                tested=tested,
                untested_reason=untested_reason,
                created_at=now,
            )


def write_coverage_functions_jsonl(
    rows: Iterable[CoverageFunctionRow], out_path: Path
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open_text_out(out_path) as f:
        for row in rows:
            f.write(json.dumps(asdict(row), sort_keys=True))
            f.write("\n")
```

---

## 4. Test catalog from pytest → `test_catalog.*`

We’ll assume you have a pytest JSON report stored somewhere like `build/pytest/pytest_report.json` (you can wire this in from your CI scripts).

### 4.1 New analytics module

`codeintel_rev/services/enrich/analytics/tests.py`:

```python
# codeintel_rev/services/enrich/analytics/tests.py
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, Iterator, Optional

from codeintel_rev.enrich.goid_builder import GOIDRegistry, EntityKind, load_goid_registry
from codeintel_rev.enrich.goid_utils import lookup_function_goid  # from metrics plan
from codeintel_rev.io.text import open_text_out
from codeintel_rev.services.enrich.pipeline_helpers import normalized_rel_path


@dataclass
class TestCatalogRow:
    test_id: str
    test_goid_h128: Optional[str]
    urn: Optional[str]
    repo: str
    commit: str
    rel_path: str
    qualname: Optional[str]
    kind: str

    status: str
    duration_ms: float
    markers: list[str]
    parametrized: bool
    flaky: bool

    created_at: str


def _parse_nodeid(nodeid: str) -> tuple[str, Optional[str]]:
    """
    Split pytest nodeid into (rel_path, qualname_suffix).

    Example:
        'tests/test_mod.py::TestClass::test_func[param]' ->
        ('tests/test_mod.py', 'TestClass.test_func')
    """
    path_part, *rest = nodeid.split("::")
    qualname = None
    if rest:
        # Drop parameterization bit in [] for qualname
        base = rest[0]
        if "[" in base:
            base = base.split("[", 1)[0]
        if len(rest) > 1:
            qualname = ".".join([rest[0], *rest[1:]])
        else:
            qualname = base
    return path_part, qualname


def _lookup_test_goid(
    registry: GOIDRegistry,
    rel_path: str,
    qualname: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    if not qualname:
        return None, None

    # Best-effort: assume function/method
    result = registry.lookup(
        rel_path=rel_path,
        language="python",
        kind=EntityKind.FUNCTION,
        qualname=qualname,
    )
    if not result:
        return None, None
    goid_h128, urn = result
    return str(goid_h128), urn


def build_test_catalog(
    *,
    enriched_dir: Path,
    pytest_report_path: Path,
) -> Iterable[TestCatalogRow]:
    registry = load_goid_registry(enriched_dir)
    report = json.loads(pytest_report_path.read_text(encoding="utf-8"))
    tests = report.get("tests", [])

    now = datetime.datetime.utcnow().isoformat() + "Z"

    for t in tests:
        nodeid: str = t["nodeid"]
        outcome: str = t.get("outcome", "unknown")
        duration: float = float(t.get("duration", 0.0)) * 1000.0
        keywords = t.get("keywords", {}) or {}

        rel_path_raw, qualname = _parse_nodeid(nodeid)
        rel_path = normalized_rel_path(Path("."), Path(rel_path_raw))

        test_goid_h128, urn = _lookup_test_goid(
            registry=registry,
            rel_path=str(rel_path),
            qualname=qualname,
        )

        markers = sorted(
            k for k, v in keywords.items() if v and not k.startswith("@")
        )
        parametrized = "[" in nodeid and "]" in nodeid
        flaky = "flaky" in markers

        yield TestCatalogRow(
            test_id=nodeid,
            test_goid_h128=test_goid_h128,
            urn=urn,
            repo=registry.repo,
            commit=registry.commit,
            rel_path=str(rel_path),
            qualname=qualname,
            kind="parametrized_case" if parametrized else "function",
            status=outcome,
            duration_ms=duration,
            markers=markers,
            parametrized=parametrized,
            flaky=flaky,
            created_at=now,
        )


def write_test_catalog_jsonl(
    rows: Iterable[TestCatalogRow],
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open_text_out(out_path) as f:
        for row in rows:
            f.write(json.dumps(asdict(row), sort_keys=True))
            f.write("\n")
```

You may need to adjust `registry.lookup` usage to match your actual API (as you did for function metrics).

---

## 5. Dynamic test→function coverage → `test_coverage_edges.*`

Here we leverage coverage **contexts**. If you cannot enable per-test contexts immediately, you can still implement this with a static callgraph-based approximation (callgraph from tests + `coverage_functions` gating), but the design below assumes contexts.

### 5.1 Build edges using coverage contexts + function spans

Add `codeintel_rev/services/enrich/analytics/test_coverage_edges.py`:

```python
# codeintel_rev/services/enrich/analytics/test_coverage_edges.py
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, Iterator, Tuple

import coverage  # type: ignore[import]

from codeintel_rev.enrich.goid_builder import load_goid_registry
from codeintel_rev.enrich.goid_utils import (
    build_function_span_index,
    lookup_function_for_line,
    FunctionSpan,
)
from codeintel_rev.io.text import open_text_out
from codeintel_rev.services.enrich.pipeline_helpers import normalized_rel_path
from codeintel_rev.services.enrich.analytics.tests import TestCatalogRow
from codeintel_rev.services.enrich.analytics.coverage_functions import CoverageFunctionRow


@dataclass
class TestCoverageEdgeRow:
    test_id: str
    test_goid_h128: str | None

    function_goid_h128: str
    urn: str
    repo: str
    commit: str
    rel_path: str
    qualname: str

    covered_lines: int
    executable_lines: int
    coverage_ratio: float | None
    last_status: str

    created_at: str


def _load_test_catalog_by_id(path: Path) -> Dict[str, TestCatalogRow]:
    rows: Dict[str, TestCatalogRow] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            row = TestCatalogRow(**json.loads(line))
            rows[row.test_id] = row
    return rows


def _load_function_coverage_by_goid(path: Path) -> Dict[str, CoverageFunctionRow]:
    rows: Dict[str, CoverageFunctionRow] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            row = CoverageFunctionRow(**json.loads(line))
            rows[row.function_goid_h128] = row
    return rows


def build_test_coverage_edges(
    *,
    repo_root: Path,
    enriched_dir: Path,
    coverage_file: Path,
    test_catalog_path: Path,
    coverage_functions_path: Path,
) -> Iterable[TestCoverageEdgeRow]:
    registry = load_goid_registry(enriched_dir)
    index_by_path = build_function_span_index(registry)
    tests_by_id = _load_test_catalog_by_id(test_catalog_path)
    func_cov_by_goid = _load_function_coverage_by_goid(coverage_functions_path)

    cov = coverage.Coverage(data_file=str(coverage_file))
    cov.load()
    data = cov.get_data()

    if not hasattr(data, "contexts_by_lineno"):
        # Fallback: no per-test coverage available; you could log and bail or
        # implement a static callgraph-based approximation here.
        return []

    # Accumulate covered lines per (test_id, function_goid)
    counts: Dict[tuple[str, str], int] = {}

    for abs_path in data.measured_files():
        try:
            rel_path = str(
                normalized_rel_path(repo_root, Path(abs_path))
            )
        except ValueError:
            continue

        contexts_by_lineno = data.contexts_by_lineno(abs_path)  # type: ignore[attr-defined]
        for line, contexts in contexts_by_lineno.items():
            span = lookup_function_for_line(
                index_by_path=index_by_path,
                rel_path=rel_path,
                line=line,
            )
            if not span:
                continue
            for ctx in contexts:
                test_id = ctx  # assume context string matches pytest nodeid
                if test_id not in tests_by_id:
                    continue
                key = (test_id, span.goid_h128)
                counts[key] = counts.get(key, 0) + 1

    now = datetime.datetime.utcnow().isoformat() + "Z"

    for (test_id, func_goid), covered_lines in counts.items():
        test_row = tests_by_id[test_id]
        func_row = func_cov_by_goid.get(func_goid)
        span = None
        # We can re-use the function span index to get qualname etc.,
        # but func_row already has that information.
        if not func_row:
            continue

        exec_lines = func_row.executable_lines
        coverage_ratio = (
            covered_lines / exec_lines if exec_lines > 0 else None
        )

        last_status = test_row.status

        yield TestCoverageEdgeRow(
            test_id=test_id,
            test_goid_h128=test_row.test_goid_h128,
            function_goid_h128=func_goid,
            urn=func_row.urn,
            repo=func_row.repo,
            commit=func_row.commit,
            rel_path=func_row.rel_path,
            qualname=func_row.qualname,
            covered_lines=covered_lines,
            executable_lines=exec_lines,
            coverage_ratio=coverage_ratio,
            last_status=last_status,
            created_at=now,
        )


def write_test_coverage_edges_jsonl(
    rows: Iterable[TestCoverageEdgeRow],
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open_text_out(out_path) as f:
        for row in rows:
            f.write(json.dumps(asdict(row), sort_keys=True))
            f.write("\n")
```

Notes:

* This assumes coverage **contexts** are equal to pytest nodeids. If your coverage config uses a different format, adjust the mapping `ctx -> test_id`.
* If contexts are not available, you can fallback to a static-approximation step later.

---

## 6. GOID risk factors → `goid_risk_factors.*`

This is a pure analytics join over existing datasets plus the new coverage + test tables.

### 6.1 New analytics module

`codeintel_rev/services/enrich/analytics/risk_factors.py`:

```python
# codeintel_rev/services/enrich/analytics/risk_factors.py
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, Optional

from codeintel_rev.io.text import open_text_out


@dataclass
class RiskFactorsRow:
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

    loc: Optional[int]
    logical_loc: Optional[int]
    cyclomatic_complexity: Optional[int]
    complexity_bucket: Optional[str]

    typedness_bucket: Optional[str]
    typedness_source: Optional[str]

    hotspot_score: Optional[float]
    commit_count: Optional[int]
    author_count: Optional[int]

    file_typed_ratio: Optional[float]

    static_error_count: Optional[int]
    has_static_errors: Optional[bool]

    executable_lines: Optional[int]
    covered_lines: Optional[int]
    coverage_ratio: Optional[float]
    tested: Optional[bool]

    test_count: int
    failing_test_count: int
    last_test_status: str

    risk_score: float
    risk_level: str

    tags: list[str]
    owners: list[str]

    created_at: str
```

### 6.2 Load helpers for upstream datasets

Small helper functions:

```python
def _load_jsonl_to_dict(path: Path, key_field: str) -> Dict[str, dict]:
    rows: Dict[str, dict] = {}
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            key = str(row[key_field])
            rows[key] = row
    return rows


def _load_file_index(path: Path, key_field: str = "rel_path") -> Dict[str, dict]:
    return _load_jsonl_to_dict(path, key_field=key_field)
```

### 6.3 Risk aggregation logic

```python
def _compute_risk_score(
    *,
    coverage_ratio: Optional[float],
    complexity_bucket: Optional[str],
    typedness_bucket: Optional[str],
    static_error_count: Optional[int],
    hotspot_score: Optional[float],
    test_count: int,
    failing_test_count: int,
) -> float:
    # Normalized features in [0, 1]
    cov_risk = 0.0
    if coverage_ratio is None:
        cov_risk = 0.7
    else:
        cov_risk = 1.0 - max(0.0, min(1.0, coverage_ratio))

    comp_risk = {
        "low": 0.1,
        "medium": 0.4,
        "high": 0.7,
        None: 0.3,
    }.get(complexity_bucket, 0.3)

    type_risk = {
        "typed": 0.1,
        "partial": 0.4,
        "untyped": 0.7,
        None: 0.4,
    }.get(typedness_bucket, 0.4)

    err = static_error_count or 0
    static_risk = min(err / 10.0, 1.0)

    test_risk = 0.0 if test_count > 0 else 0.6
    failing_risk = min(failing_test_count * 0.2, 0.8)

    # Hotspot is left mostly as-is but capped
    hotspot_norm = 0.0
    if hotspot_score is not None:
        # Heuristic normalization; you can refine using percentile ranks
        hotspot_norm = min(hotspot_score / 10.0, 1.0)

    # Weighted combination – tweak as desired
    score = (
        0.25 * cov_risk
        + 0.2 * comp_risk
        + 0.15 * type_risk
        + 0.15 * static_risk
        + 0.15 * hotspot_norm
        + 0.1 * test_risk
        + 0.0 * failing_risk  # or fold into test_risk if you prefer
    )
    return max(0.0, min(1.0, score))


def _bucket_risk(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"
```

### 6.4 Builder function

```python
def build_goid_risk_factors(
    *,
    enriched_dir: Path,
) -> Iterable[RiskFactorsRow]:
    analytics_dir = enriched_dir / "analytics"

    function_metrics = _load_jsonl_to_dict(
        analytics_dir / "function_metrics.jsonl", key_field="function_goid_h128"
    )
    function_types = _load_jsonl_to_dict(
        analytics_dir / "function_types.jsonl", key_field="function_goid_h128"
    )
    cov_funcs = _load_jsonl_to_dict(
        analytics_dir / "coverage" / "coverage_functions.jsonl",
        key_field="function_goid_h128",
    )

    test_edges = _load_jsonl_to_dict(
        analytics_dir / "tests" / "test_coverage_edges.jsonl",
        key_field=None,
    )
    # For test_edges we aggregate per-function:
    test_counts: Dict[str, int] = {}
    failing_counts: Dict[str, int] = {}
    last_status: Dict[str, str] = {}

    tests_path = analytics_dir / "tests" / "test_coverage_edges.jsonl"
    if tests_path.exists():
        with tests_path.open("r", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                goid = str(row["function_goid_h128"])
                test_counts.setdefault(goid, 0)
                failing_counts.setdefault(goid, 0)
                test_counts[goid] += 1
                status = row.get("last_status", "unknown")
                last_status[goid] = status
                if status in {"failed", "error", "xfailed"}:
                    failing_counts[goid] += 1

    # File-level analytics
    hotspots_by_path = _load_file_index(analytics_dir / "hotspots.jsonl")
    typedness_by_path = _load_file_index(analytics_dir / "typedness.jsonl")
    static_diag_by_path = _load_file_index(analytics_dir / "static_diagnostics.jsonl")

    # Optional tags & ownership from modules.jsonl
    modules_index = _load_file_index(enriched_dir / "modules" / "modules.jsonl")

    now = datetime.datetime.utcnow().isoformat() + "Z"

    all_goids = set(function_metrics.keys()) | set(cov_funcs.keys())

    for goid in sorted(all_goids):
        m = function_metrics.get(goid, {})
        t = function_types.get(goid, {})
        c = cov_funcs.get(goid, {})

        rel_path = m.get("rel_path") or c.get("rel_path")
        if not rel_path:
            continue

        file_hotspot = hotspots_by_path.get(rel_path, {})
        file_typed = typedness_by_path.get(rel_path, {})
        file_diag = static_diag_by_path.get(rel_path, {})
        module_meta = modules_index.get(rel_path, {})

        exec_lines = c.get("executable_lines")
        cov_lines = c.get("covered_lines")
        cov_ratio = c.get("coverage_ratio")

        tc = test_counts.get(goid, 0)
        fc = failing_counts.get(goid, 0)
        status = last_status.get(goid, "untested" if tc == 0 else "unknown")

        risk_score = _compute_risk_score(
            coverage_ratio=cov_ratio,
            complexity_bucket=m.get("complexity_bucket"),
            typedness_bucket=t.get("typedness_bucket"),
            static_error_count=file_diag.get("total_errors"),
            hotspot_score=file_hotspot.get("score"),
            test_count=tc,
            failing_test_count=fc,
        )
        risk_level = _bucket_risk(risk_score)

        yield RiskFactorsRow(
            function_goid_h128=goid,
            urn=m.get("urn") or c.get("urn"),
            repo=m.get("repo") or c.get("repo"),
            commit=m.get("commit") or c.get("commit"),
            rel_path=rel_path,
            language="python",
            kind=m.get("kind") or c.get("kind") or "function",
            qualname=m.get("qualname") or c.get("qualname") or "",
            start_line=m.get("start_line") or c.get("start_line") or 0,
            end_line=m.get("end_line") or c.get("end_line") or 0,
            loc=m.get("loc"),
            logical_loc=m.get("logical_loc"),
            cyclomatic_complexity=m.get("cyclomatic_complexity"),
            complexity_bucket=m.get("complexity_bucket"),
            typedness_bucket=t.get("typedness_bucket"),
            typedness_source=t.get("typedness_source"),
            hotspot_score=file_hotspot.get("score"),
            commit_count=file_hotspot.get("commit_count"),
            author_count=file_hotspot.get("author_count"),
            file_typed_ratio=file_typed.get("typed_ratio"),
            static_error_count=file_diag.get("total_errors"),
            has_static_errors=file_diag.get("has_errors"),
            executable_lines=exec_lines,
            covered_lines=cov_lines,
            coverage_ratio=cov_ratio,
            tested=c.get("tested"),
            test_count=tc,
            failing_test_count=fc,
            last_test_status=status,
            risk_score=risk_score,
            risk_level=risk_level,
            tags=module_meta.get("tags", []),
            owners=module_meta.get("owners", []),
            created_at=now,
        )
```

And a writer:

```python
def write_risk_factors_jsonl(
    rows: Iterable[RiskFactorsRow],
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open_text_out(out_path) as f:
        for row in rows:
            f.write(json.dumps(asdict(row), sort_keys=True))
            f.write("\n")
```

---

## 7. Pipeline wiring

### 7.1 Enrich pipeline runners

Extend `codeintel_rev/services/enrich/pipeline.py` similarly to how you added function metrics/types.

```python
# codeintel_rev/services/enrich/pipeline.py
from pathlib import Path

from codeintel_rev.io.repo_map import load_repo_map  # or existing helper
from codeintel_rev.services.enrich.analytics.coverage_lines import (
    build_coverage_lines,
    write_coverage_lines_jsonl,
)
from codeintel_rev.services.enrich.analytics.coverage_functions import (
    aggregate_coverage_functions,
    write_coverage_functions_jsonl,
)
from codeintel_rev.services.enrich.analytics.tests import (
    build_test_catalog,
    write_test_catalog_jsonl,
)
from codeintel_rev.services.enrich.analytics.test_coverage_edges import (
    build_test_coverage_edges,
    write_test_coverage_edges_jsonl,
)
from codeintel_rev.services.enrich.analytics.risk_factors import (
    build_goid_risk_factors,
    write_risk_factors_jsonl,
)


def run_coverage_analytics(
    *,
    repo_root: str,
    enriched_dir: str,
    coverage_file: str,
) -> None:
    repo_root_path = Path(repo_root)
    enriched_path = Path(enriched_dir)
    coverage_path = Path(coverage_file)

    repo_map = json.loads((enriched_path / "repo_map.json").read_text())
    repo = repo_map["repo"]
    commit = repo_map["commit"]

    analytics_cov_dir = enriched_path / "analytics" / "coverage"
    analytics_cov_dir.mkdir(parents=True, exist_ok=True)

    coverage_lines_path = analytics_cov_dir / "coverage_lines.jsonl"
    rows = build_coverage_lines(
        repo=repo,
        commit=commit,
        repo_root=repo_root_path,
        coverage_file=coverage_path,
    )
    write_coverage_lines_jsonl(rows, coverage_lines_path)

    coverage_funcs_path = analytics_cov_dir / "coverage_functions.jsonl"
    func_rows = aggregate_coverage_functions(
        enriched_dir=enriched_path,
        coverage_lines_path=coverage_lines_path,
    )
    write_coverage_functions_jsonl(func_rows, coverage_funcs_path)


def run_test_analytics(
    *,
    repo_root: str,
    enriched_dir: str,
    coverage_file: str,
    pytest_report_path: str,
) -> None:
    repo_root_path = Path(repo_root)
    enriched_path = Path(enriched_dir)
    cov_file = Path(coverage_file)
    pytest_report = Path(pytest_report_path)

    analytics_tests_dir = enriched_path / "analytics" / "tests"
    analytics_tests_dir.mkdir(parents=True, exist_ok=True)

    test_catalog_path = analytics_tests_dir / "test_catalog.jsonl"
    test_rows = build_test_catalog(
        enriched_dir=enriched_path,
        pytest_report_path=pytest_report,
    )
    write_test_catalog_jsonl(test_rows, test_catalog_path)

    coverage_funcs_path = (
        enriched_path / "analytics" / "coverage" / "coverage_functions.jsonl"
    )
    test_edges_path = analytics_tests_dir / "test_coverage_edges.jsonl"
    edge_rows = build_test_coverage_edges(
        repo_root=repo_root_path,
        enriched_dir=enriched_path,
        coverage_file=cov_file,
        test_catalog_path=test_catalog_path,
        coverage_functions_path=coverage_funcs_path,
    )
    write_test_coverage_edges_jsonl(edge_rows, test_edges_path)


def run_risk_factors(*, enriched_dir: str) -> None:
    enriched_path = Path(enriched_dir)
    analytics_risk_dir = enriched_path / "analytics" / "risk"
    analytics_risk_dir.mkdir(parents=True, exist_ok=True)

    out_path = analytics_risk_dir / "goid_risk_factors.jsonl"
    rows = build_goid_risk_factors(enriched_dir=enriched_path)
    write_risk_factors_jsonl(rows, out_path)
```

### 7.2 CLI wiring

Update `codeintel_rev/cli/enrich_analytics.py` (or whichever CLI you’re using today for analytics; you already have something here per the SCIP index).

```python
# codeintel_rev/cli/enrich_analytics.py
import click

from codeintel_rev.services.enrich.pipeline import (
    run_coverage_analytics,
    run_test_analytics,
    run_risk_factors,
)


@click.group()
def analytics() -> None:
    """Analytics helpers (function metrics, coverage, tests, risk, ...)."""


@analytics.command("coverage")
@click.option("--repo-root", required=True)
@click.option("--enriched-dir", required=True)
@click.option("--coverage-file", required=True, help="Path to .coverage data file")
def coverage_cmd(repo_root: str, enriched_dir: str, coverage_file: str) -> None:
    """Generate coverage_lines and coverage_functions analytics."""
    run_coverage_analytics(
        repo_root=repo_root,
        enriched_dir=enriched_dir,
        coverage_file=coverage_file,
    )


@analytics.command("tests")
@click.option("--repo-root", required=True)
@click.option("--enriched-dir", required=True)
@click.option("--coverage-file", required=True)
@click.option("--pytest-report", required=True, help="Path to pytest JSON report")
def tests_cmd(
    repo_root: str, enriched_dir: str, coverage_file: str, pytest_report: str
) -> None:
    """Generate test_catalog and test_coverage_edges analytics."""
    run_test_analytics(
        repo_root=repo_root,
        enriched_dir=enriched_dir,
        coverage_file=coverage_file,
        pytest_report_path=pytest_report,
    )


@analytics.command("risk-factors")
@click.option("--enriched-dir", required=True)
def risk_factors_cmd(enriched_dir: str) -> None:
    """Compute goid_risk_factors.jsonl from analytics tables."""
    run_risk_factors(enriched_dir=enriched_dir)
```

You can then call these from your existing orchestration (CI, `generate_documents.sh`, etc.).

---

## 8. DuckDB & `generate_documents.sh` integration

### 8.1 DuckDB catalog registration

Extend `codeintel_rev/io/duckdb_catalog.py` where you register analytics tables like `hotspots`, `typedness`, `config_values`, `static_diagnostics`.

```python
ANALYTICS_TABLES = {
    **ANALYTICS_TABLES,
    "coverage_lines": {
        "path": "analytics/coverage/coverage_lines.parquet",
        "ddl": """
            CREATE TABLE coverage_lines AS
            SELECT *
            FROM read_parquet('{path}');
        """,
    },
    "coverage_functions": {
        "path": "analytics/coverage/coverage_functions.parquet",
        "ddl": """
            CREATE TABLE coverage_functions AS
            SELECT *
            FROM read_parquet('{path}');
        """,
    },
    "test_catalog": {
        "path": "analytics/tests/test_catalog.parquet",
        "ddl": """
            CREATE TABLE test_catalog AS
            SELECT *
            FROM read_parquet('{path}');
        """,
    },
    "test_coverage_edges": {
        "path": "analytics/tests/test_coverage_edges.parquet",
        "ddl": """
            CREATE TABLE test_coverage_edges AS
            SELECT *
            FROM read_parquet('{path}');
        """,
    },
    "goid_risk_factors": {
        "path": "analytics/risk/goid_risk_factors.parquet",
        "ddl": """
            CREATE TABLE goid_risk_factors AS
            SELECT *
            FROM read_parquet('{path}');
        """,
    },
}
```

(Adjust `path` roots if your analytics Parquet files live under a slightly different layout.)

### 8.2 `generate_documents.sh`

Following the pattern you already use (DuckDB `COPY` from Parquet to JSONL), add:

```bash
# Inside generate_documents.sh (or equivalent)

# Create analytics tables
duckdb "$DB" <<'SQL'
-- existing ANALYTICS_TABLES creations...
CREATE OR REPLACE VIEW coverage_lines AS
    SELECT * FROM read_parquet('enriched/analytics/coverage/coverage_lines.parquet');

CREATE OR REPLACE VIEW coverage_functions AS
    SELECT * FROM read_parquet('enriched/analytics/coverage/coverage_functions.parquet');

CREATE OR REPLACE VIEW test_catalog AS
    SELECT * FROM read_parquet('enriched/analytics/tests/test_catalog.parquet');

CREATE OR REPLACE VIEW test_coverage_edges AS
    SELECT * FROM read_parquet('enriched/analytics/tests/test_coverage_edges.parquet');

CREATE OR REPLACE VIEW goid_risk_factors AS
    SELECT * FROM read_parquet('enriched/analytics/risk/goid_risk_factors.parquet');
SQL

# Export JSONL for LLMs
for table in \
    coverage_lines coverage_functions \
    test_catalog test_coverage_edges \
    goid_risk_factors
do
  duckdb "$DB" "
    COPY ${table} TO '${DOC_OUT}/${table}.jsonl'
    (FORMAT JSON, ARRAY FALSE);
  "
done
```

And Parquet copies if you’re mirroring analytics into `Document Output/` via DuckDB as well (mirroring how `hotspots` and `typedness` are handled).

### 8.3 README / docs updates

Extend `README_METADATA.md` with sections:

* **16. Coverage Lines (`coverage_lines.*`)**
* **17. Function Coverage (`coverage_functions.*`)**
* **18. Test Catalog (`test_catalog.*`)**
* **19. Test Coverage Edges (`test_coverage_edges.*`)**
* **20. GOID Risk Factors (`goid_risk_factors.*`)**

Modeled after existing sections for GOIDs, call graph, CFG/DFG, hotspots, typedness, and config_values.

You can also add the new datasets to `DATASET_CHEATSHEET.md` and `LLM_AGENT_PLAYBOOK.md` in the same style as the per-function metrics/types plan.

---

## 9. Testing & validation

### 9.1 Unit tests

1. **Coverage lines**: synthetic module + a small pytest suite run with coverage in a temp directory.

   * Ensure `coverage_lines.jsonl` has expected `is_executable` / `is_covered` lines.
   * Verify `rel_path` normalization.

2. **Coverage functions**:

   * Use a tiny registry fixture with one or two functions plus synthetic coverage_lines rows.
   * Assert `executable_lines` / `covered_lines` and `coverage_ratio` match expectations.

3. **Test catalog**:

   * Feed in a trimmed pytest JSON report with:

     * Simple function tests
     * Parametrized tests
     * Class-based tests
   * Assert `test_id`, `rel_path`, `qualname`, markers, and GOID matching behaviour.

4. **Test coverage edges**:

   * Use a fake coverage data object implementing `measured_files()` and `contexts_by_lineno()` to avoid depending on coverage internals in unit tests.
   * Validate that a given `(test_id, function_goid)` pair gets the correct `covered_lines` and `coverage_ratio`.

5. **Risk factors**:

   * Build small synthetic JSONL files for function_metrics, function_types, hotspots, typedness, static_diagnostics, coverage_functions, test_coverage_edges.
   * Assert:

     * Untested hot, untyped, complex functions get higher `risk_score`.
     * Fully tested, typed, low-complexity functions get low `risk_score`.
     * `risk_level` bucketing matches thresholds.

### 9.2 Cross-artifact sanity checks

Using DuckDB queries (in the same spirit as your `DUCKDB_STARTER_QUERIES.sql`):

* **Coverage alignment**: sum line-level coverage per function and compare with `coverage_functions` counts.

* **Risk ordering sanity**: list top 20 `risk_score` functions, and inspect:

  * Low coverage
  * High cyclomatic complexity
  * Untyped or partial
  * Hotspot files
  * Static diagnostics present

* **Coverage vs tests**: for each function, compare `tested` (from `coverage_functions`) with `test_count > 0` from aggregated `test_coverage_edges` to detect mismatches.

---

If you’d like, I can next:

* Draft the exact `README_METADATA.md` sections for these five datasets, or
* Design a few “LLM playbook” recipes showing how to use `goid_risk_factors` + the other graphs to answer questions like “what are the top 10 refactor targets in this repo?”


