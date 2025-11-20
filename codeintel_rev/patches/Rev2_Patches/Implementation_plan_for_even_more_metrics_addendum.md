
# read me edits and coverage and risk queries #

Awesome, let’s add those extra artifacts.

I’ll give you **two concrete, drop‑in outputs**:

1. **New sections for `README_METADATA.md`** documenting the coverage + tests + risk datasets.
2. **A `COVERAGE_AND_RISK_QUERIES.sql` script** with DuckDB views + starter queries that join coverage, tests, and risk factors to the rest of your graph.

Both are structured to line up with your existing metadata & docs style.

---

## 1. Additions to `README_METADATA.md` (coverage, tests, risk)

Paste these near the end of `README_METADATA.md` (after the current section 15 on CST Nodes).

```markdown
## 16. Line Coverage (`coverage_lines.parquet` / `coverage_lines.jsonl`)

**Purpose**: Fine-grained line-level coverage information from test execution. Allows tools and AI agents to answer questions like “which lines in this file were exercised by tests?” and “what are the exact uncovered regions?”

**Origin**: Produced by the coverage analytics pipeline (`codeintel_rev.cli.enrich_analytics.coverage`) which ingests coverage reports (e.g., coverage.py) and normalizes them into per-file and per-line records. Integrated with GOIDs via `goid_crosswalk` when possible. :contentReference[oaicite:0]{index=6}

**Fields**

| Field                | Type        | Description |
|----------------------|-------------|-------------|
| `rel_path`           | string      | Repo-relative file path (e.g., `codeintel_rev/app/routes/catalog_read.py`). |
| `line`               | int         | 1-based line number. |
| `is_executed`        | bool        | True if the line was executed at least once in the coverage run. |
| `hit_count`          | int         | Number of execution hits recorded for the line (0 for uncovered). |
| `test_count`         | int         | Number of distinct test cases that executed this line (best-effort). |
| `function_goid_h128` | decimal(38) | GOID hash for the innermost function/method containing this line, if any. |
| `repo`               | string      | Repository slug. |
| `commit`             | string      | Commit SHA at analysis time. |
| `run_id`             | string/null | Identifier for the coverage run (useful when multiple runs are merged). |

**Notes**

* JSONL exports encode `function_goid_h128` as a string to preserve 128-bit precision, matching `goids.jsonl`. :contentReference[oaicite:2]{index=2}  
* Join to `goids` via `function_goid_h128` to recover qualnames and module metadata.
* Join to `goid_crosswalk` via `(rel_path, line)` to anchor coverage to GOIDs when `function_goid_h128` is null.

---

## 17. Function Coverage (`coverage_functions.parquet` / `coverage_functions.jsonl`)

**Purpose**: Aggregate coverage metrics per function/method. This is the main join point when asking “how well covered is this function?” or “which high-fan-in functions lack tests?”.

**Origin**: Derived from `coverage_lines` grouped by function spans. Uses `goids` (for function spans and metadata) plus `coverage_lines` to compute coverage percentages and coverage buckets.

**Fields**

| Field                  | Type        | Description |
|------------------------|-------------|-------------|
| `function_goid_h128`   | decimal(38) | GOID hash for the callable (matches `goids.goid_h128`). |
| `urn`                  | string      | GOID URN for the callable. |
| `repo`                 | string      | Repository slug. |
| `commit`               | string      | Commit SHA at analysis time. |
| `rel_path`             | string      | File containing the function. |
| `language`             | string      | Language tag (`python`). |
| `kind`                 | string      | Callable kind (`function`, `method`, `async_function`, etc.). |
| `qualname`             | string      | Dotted qualified name (e.g., `pkg.mod.Foo.bar`). |
| `start_line`           | int         | First line of the function span. |
| `end_line`             | int         | Last line of the function span. |

Coverage aggregates:

| Field                    | Type   | Description |
|--------------------------|--------|-------------|
| `total_lines`            | int    | Count of source lines in the function span (inclusive). |
| `coverable_lines`        | int    | Number of non-blank, non-comment lines considered coverable. |
| `executed_lines`         | int    | Number of coverable lines with `is_executed = true`. |
| `line_coverage_ratio`    | float  | `executed_lines / NULLIF(coverable_lines, 0)` in [0.0, 1.0]. |
| `distinct_tests`         | int    | Number of distinct tests that executed at least one line in this function. |
| `has_any_coverage`       | bool   | True if `executed_lines > 0`. |
| `coverage_bucket`        | string | Bucketized coverage (`none`, `low`, `medium`, `high`) based on configurable thresholds. |
| `created_at`             | string | ISO timestamp of aggregation. |

**Joins**

* `function_goid_h128` → `goids.goid_h128` for entity metadata. :contentReference[oaicite:3]{index=3}  
* `function_goid_h128` → `function_metrics.function_goid_h128` (when present) to mix structural complexity with coverage.

---

## 18. Test Catalog (`test_catalog.parquet` / `test_catalog.jsonl`)

**Purpose**: Canonical registry of test cases/functions discovered in the repo. Each row is a single test function or method, with pytest-style metadata (markers, parametrization, etc.) where available.

**Origin**: `codeintel_rev.services.enrich.analytics.test_catalog` walks AST/CST and/or pytest collection output to identify tests (e.g., functions named `test_*`, methods on `Test*` classes, or anything marked with `@pytest.mark`). GOIDs provide stable IDs for tests.

**Fields**

| Field              | Type        | Description |
|--------------------|-------------|-------------|
| `test_goid_h128`   | decimal(38) | GOID hash for the test callable. |
| `urn`              | string      | GOID URN for the test. |
| `repo`             | string      | Repository slug. |
| `commit`           | string      | Commit SHA at analysis time. |
| `rel_path`         | string      | File containing the test. |
| `language`         | string      | Language tag (`python`). |
| `kind`             | string      | Callable kind (`function`, `method`). |
| `qualname`         | string      | Qualified name (e.g., `tests.test_api.TestFoo.test_bar`). |
| `start_line`       | int         | First line of the test span. |
| `end_line`         | int         | Last line of the test span. |
| `framework`        | string      | Detected test framework (`pytest`, `unittest`, `unknown`). |
| `markers`          | array       | List of pytest markers (e.g., `["slow", "integration"]`). |
| `parametrized`     | bool        | True if the test is parametrized. |
| `parameters_json`  | json/null   | Optional structured representation of parameters (ids, values). |
| `tags`             | array       | Optional semantic tags (e.g., `["api", "e2e"]`) from tagging/ownership. |
| `created_at`       | string      | ISO timestamp. |

**Joins**

* `test_goid_h128` → `test_coverage_edges.test_goid_h128` to see what the test covers.
* `rel_path` and `qualname` can be used by test runners or dashboards to map from pytest node IDs back into this catalog.

---

## 19. Test Coverage Edges (`test_coverage_edges.parquet` / `test_coverage_edges.jsonl`)

**Purpose**: Bipartite graph between **tests** and **code entities** they exercise, derived from coverage plus GOID mappings. This is the primary artifact for test impact analysis (“which tests hit this function?” / “what code is covered by this test?”).

**Origin**: Combined from:

* Coverage signals (`coverage_lines`, `coverage_functions`),
* GOID span information (`goids`, `goid_crosswalk`), and
* The test catalog (`test_catalog`).

Edges are emitted when at least one line in a function/module is executed by a given test.

**Fields**

| Field                  | Type        | Description |
|------------------------|-------------|-------------|
| `test_goid_h128`       | decimal(38) | Source node: test function GOID. |
| `target_goid_h128`     | decimal(38) | Target node: covered entity GOID (usually a function, sometimes a module). |
| `target_kind`          | string      | Target kind (`function`, `method`, `module`). |
| `target_rel_path`      | string      | File containing the target entity. |
| `covered_lines`        | int         | Number of coverable lines within the target entity executed by this test. |
| `coverable_lines`      | int         | Total coverable lines within the target entity. |
| `line_coverage_ratio`  | float       | `covered_lines / NULLIF(coverable_lines, 0)` for just this test→target pair. |
| `evidence_json`        | json/null   | Optional detail (e.g., example line numbers, basic blocks). |
| `repo`                 | string      | Repository slug. |
| `commit`               | string      | Commit SHA. |
| `created_at`           | string      | ISO timestamp. |

**Joins**

* `test_goid_h128` → `test_catalog.test_goid_h128` for test metadata.
* `target_goid_h128` → `goids.goid_h128` for code entity metadata.
* Aggregate over `test_goid_h128` to see what each test hits, or over `target_goid_h128` to see “who tests this”.

---

## 20. GOID Risk Factors (`goid_risk_factors.parquet` / `goid_risk_factors.jsonl`)

**Purpose**: Precomputed, per-entity **risk profile** that combines structural complexity, churn, static diagnostics, typedness, and coverage. Intended as a one-stop “risk score” that AI agents and dashboards can use to prioritize refactors, tests, and reviews.

**Origin**: `codeintel_rev.services.enrich.analytics.risk_factors` joins:

* Structure & identity: `goids` / `goid_crosswalk`.   
* Complexity: `function_metrics`, `ast_metrics`.   
* Churn: `hotspots`.   
* Typedness: `typedness`, `function_types`. :contentReference[oaicite:7]{index=7}  
* Static analysis: `static_diagnostics`. :contentReference[oaicite:8]{index=8}  
* Test & coverage: `coverage_functions`, `test_coverage_edges`.  

It emits one row per GOID considered “interesting” (typically functions/methods, sometimes modules and classes).

**Fields (core)**

| Field                  | Type        | Description |
|------------------------|-------------|-------------|
| `goid_h128`            | decimal(38) | GOID hash for the entity. |
| `urn`                  | string      | GOID URN. |
| `repo`                 | string      | Repository slug. |
| `commit`               | string      | Commit SHA. |
| `rel_path`             | string      | File path. |
| `language`             | string      | `python`. |
| `kind`                 | string      | `function`, `method`, `class`, `module`, etc. |
| `qualname`             | string      | Dotted qualified name. |

Risk inputs:

| Field                     | Type   | Description |
|---------------------------|--------|-------------|
| `hotspot_score`           | float  | From `hotspots.score` (0+). |
| `typed_ratio`             | float  | From `typedness`/`function_types` (0–1). |
| `has_type_errors`         | bool   | True if `static_diagnostics.total_errors > 0`. |
| `type_error_count`        | int    | Sum of Pyright/Pyrefly errors for this entity’s file. |
| `cyclomatic_complexity`   | int    | From `function_metrics` where applicable. |
| `max_nesting_depth`       | int    | From `function_metrics`. |
| `cfg_block_count`         | int    | Approximate structural complexity, from `cfg_blocks`. |
| `fan_in`                  | int    | Number of distinct callers (`call_graph_edges`). |
| `fan_out`                 | int    | Number of distinct callees. |
| `line_coverage_ratio`     | float  | From `coverage_functions` (0–1). |
| `has_any_coverage`        | bool   | True if coverage exists. |
| `test_count`              | int    | Number of tests hitting the entity (`test_coverage_edges`). |

Aggregated outputs:

| Field           | Type   | Description |
|-----------------|--------|-------------|
| `risk_score`    | float  | Composite risk score normalized to [0, 1]. Higher = riskier. |
| `risk_bucket`   | string | `low`, `medium`, `high`, `critical`. |
| `explanation`   | string | Human-readable summary (e.g., “High hotspot score, low coverage, high fan-in, and type errors”). |
| `created_at`    | string | ISO timestamp. |

**Notes**

* Scoring logic is pluggable; typical weighting might emphasize **hotspot_score**, **fan_in**, and **line_coverage_ratio**.
* Intended to be the primary entrypoint for risk-aware AI agents (“show me high-risk, low-coverage functions in the API layer”).

```

---

## 2. `COVERAGE_AND_RISK_QUERIES.sql`

This complements your existing `DUCKDB_STARTER_QUERIES.sql` by focusing only on coverage, tests, and risk.

Save as `COVERAGE_AND_RISK_QUERIES.sql` (or append to your existing starter queries).

```sql
---------------------------------------------------------------------
-- COVERAGE_AND_RISK_QUERIES.sql
--
-- DuckDB helper script for working with:
--   - coverage_lines
--   - coverage_functions
--   - test_catalog
--   - test_coverage_edges
--   - goid_risk_factors
--
-- Assumes Parquet assets live under "Document Output/" following
-- the naming conventions in README_METADATA.md.
---------------------------------------------------------------------

---------------------------------------------------------------------
-- 0. Views
---------------------------------------------------------------------

CREATE OR REPLACE VIEW coverage_lines AS
    SELECT * FROM read_parquet('Document Output/coverage_lines.parquet');

CREATE OR REPLACE VIEW coverage_functions AS
    SELECT * FROM read_parquet('Document Output/coverage_functions.parquet');

CREATE OR REPLACE VIEW test_catalog AS
    SELECT * FROM read_parquet('Document Output/test_catalog.parquet');

CREATE OR REPLACE VIEW test_coverage_edges AS
    SELECT * FROM read_parquet('Document Output/test_coverage_edges.parquet');

CREATE OR REPLACE VIEW goid_risk_factors AS
    SELECT * FROM read_parquet('Document Output/goid_risk_factors.parquet');

-- You likely already have these views from DUCKDB_STARTER_QUERIES.sql:
CREATE OR REPLACE VIEW goids AS
    SELECT * FROM read_parquet('Document Output/goids.parquet');

CREATE OR REPLACE VIEW call_edges AS
    SELECT * FROM read_parquet('Document Output/call_graph_edges.parquet');

CREATE OR REPLACE VIEW call_nodes AS
    SELECT * FROM read_parquet('Document Output/call_graph_nodes.parquet');

CREATE OR REPLACE VIEW hotspots AS
    SELECT * FROM read_parquet('Document Output/hotspots.parquet');

CREATE OR REPLACE VIEW typedness AS
    SELECT * FROM read_parquet('Document Output/typedness.parquet');

---------------------------------------------------------------------
-- A. File-level coverage summaries
---------------------------------------------------------------------

-- A1. Per-file line coverage
SELECT
    rel_path,
    SUM(CASE WHEN is_executed THEN 1 ELSE 0 END)        AS executed_lines,
    COUNT(*)                                            AS total_lines,
    ROUND(
        SUM(CASE WHEN is_executed THEN 1 ELSE 0 END)::DOUBLE
        / NULLIF(COUNT(*), 0),
        3
    )                                                   AS line_coverage_ratio
FROM coverage_lines
GROUP BY rel_path
ORDER BY line_coverage_ratio ASC, total_lines DESC
LIMIT 100;

-- A2. Top N completely uncovered files (but with coverable lines)
WITH file_cov AS (
    SELECT
        rel_path,
        SUM(CASE WHEN is_executed THEN 1 ELSE 0 END) AS executed_lines,
        COUNT(*) AS total_lines
    FROM coverage_lines
    GROUP BY rel_path
)
SELECT *
FROM file_cov
WHERE executed_lines = 0
ORDER BY total_lines DESC
LIMIT 50;

---------------------------------------------------------------------
-- B. Function-level coverage & impact
---------------------------------------------------------------------

-- B1. Least-covered high-complexity functions (needs function_metrics view)
-- Assumes you've created a function_metrics view:
--   CREATE VIEW function_metrics AS
--     SELECT * FROM read_parquet('Document Output/function_metrics.parquet');

WITH cov AS (
    SELECT
        f.function_goid_h128,
        f.rel_path,
        f.qualname,
        f.line_coverage_ratio,
        f.coverable_lines,
        f.executed_lines
    FROM coverage_functions f
),
metrics AS (
    SELECT
        function_goid_h128,
        cyclomatic_complexity,
        max_nesting_depth,
        loc
    FROM function_metrics
)
SELECT
    c.rel_path,
    c.qualname,
    c.coverable_lines,
    c.executed_lines,
    ROUND(c.line_coverage_ratio, 3)        AS line_coverage_ratio,
    m.cyclomatic_complexity,
    m.max_nesting_depth,
    m.loc
FROM cov c
LEFT JOIN metrics m
  ON c.function_goid_h128 = m.function_goid_h128
WHERE c.coverable_lines >= 5                -- ignore tiny helpers
ORDER BY c.line_coverage_ratio ASC, m.cyclomatic_complexity DESC
LIMIT 100;

-- B2. High fan-in functions with low coverage (classic risk hotspots)
WITH fan_in AS (
    SELECT
        callee_goid_h128 AS function_goid_h128,
        COUNT(DISTINCT caller_goid_h128) AS fan_in
    FROM call_edges
    WHERE callee_goid_h128 IS NOT NULL
    GROUP BY callee_goid_h128
)
SELECT
    g.rel_path,
    g.qualname,
    fi.fan_in,
    ROUND(cf.line_coverage_ratio, 3) AS line_coverage_ratio,
    cf.coverable_lines,
    cf.executed_lines
FROM coverage_functions cf
JOIN fan_in fi
  ON cf.function_goid_h128 = fi.function_goid_h128
JOIN goids g
  ON cf.function_goid_h128 = g.goid_h128
WHERE fi.fan_in >= 3                    -- “widely depended on”
  AND cf.coverable_lines >= 5
ORDER BY cf.line_coverage_ratio ASC, fi.fan_in DESC
LIMIT 100;

---------------------------------------------------------------------
-- C. Test-centric views
---------------------------------------------------------------------

-- C1. Which code does a given test hit?
-- Replace the WHERE clause with your test's qualname or file.
SELECT
    t.rel_path           AS test_path,
    t.qualname           AS test_name,
    g.rel_path           AS target_path,
    g.qualname           AS target_name,
    e.covered_lines,
    e.coverable_lines,
    ROUND(e.line_coverage_ratio, 3) AS line_coverage_ratio
FROM test_coverage_edges e
JOIN test_catalog t
  ON e.test_goid_h128 = t.test_goid_h128
JOIN goids g
  ON e.target_goid_h128 = g.goid_h128
WHERE t.qualname LIKE '%test_%your_test_name_here%'
ORDER BY e.line_coverage_ratio DESC, e.covered_lines DESC
LIMIT 200;

-- C2. “Orphan” tests that don’t strongly cover anything
WITH per_test AS (
    SELECT
        test_goid_h128,
        SUM(covered_lines) AS total_covered,
        SUM(coverable_lines) AS total_coverable
    FROM test_coverage_edges
    GROUP BY test_goid_h128
)
SELECT
    t.rel_path,
    t.qualname,
    pt.total_covered,
    pt.total_coverable
FROM per_test pt
JOIN test_catalog t
  ON pt.test_goid_h128 = t.test_goid_h128
WHERE pt.total_covered = 0 OR pt.total_coverable = 0
ORDER BY pt.total_coverable DESC
LIMIT 100;

---------------------------------------------------------------------
-- D. Risk-aware triage via goid_risk_factors
---------------------------------------------------------------------

-- D1. Top high-risk, low-coverage functions
SELECT
    r.rel_path,
    r.qualname,
    r.kind,
    ROUND(r.risk_score, 3)          AS risk_score,
    r.risk_bucket,
    ROUND(r.line_coverage_ratio, 3) AS line_coverage_ratio,
    r.fan_in,
    r.hotspot_score,
    r.type_error_count,
    r.cyclomatic_complexity
FROM goid_risk_factors r
WHERE r.kind IN ('function', 'method')
  AND r.risk_bucket IN ('high', 'critical')
  AND (r.line_coverage_ratio IS NULL OR r.line_coverage_ratio < 0.3)
ORDER BY r.risk_score DESC
LIMIT 100;

-- D2. Risk by folder / module prefix (e.g., api layer only)
SELECT
    regexp_extract(rel_path, '^[^/]+/[^/]+') AS module_prefix,
    COUNT(*)                                  AS entity_count,
    AVG(risk_score)                           AS avg_risk_score,
    AVG(line_coverage_ratio)                  AS avg_line_coverage_ratio,
    SUM(CASE WHEN risk_bucket IN ('high', 'critical') THEN 1 ELSE 0 END) AS high_risk_entities
FROM goid_risk_factors
WHERE rel_path LIKE 'codeintel_rev/app/%'   -- adjust prefix as desired
GROUP BY module_prefix
ORDER BY avg_risk_score DESC
LIMIT 50;

---------------------------------------------------------------------
-- E. Coverage gaps intersected with hotspots & typedness
---------------------------------------------------------------------

-- E1. Files that are hot, poorly typed, and poorly covered
WITH file_cov AS (
    SELECT
        rel_path,
        SUM(CASE WHEN is_executed THEN 1 ELSE 0 END) AS executed_lines,
        COUNT(*) AS total_lines,
        SUM(CASE WHEN is_executed THEN 1 ELSE 0 END)::DOUBLE
            / NULLIF(COUNT(*), 0) AS line_coverage_ratio
    FROM coverage_lines
    GROUP BY rel_path
)
SELECT
    h.rel_path,
    h.score                 AS hotspot_score,
    t.typed_ratio,
    ROUND(fc.line_coverage_ratio, 3) AS line_coverage_ratio,
    h.commit_count,
    h.lines_added,
    h.lines_deleted
FROM hotspots h
JOIN typedness t
  ON h.rel_path = t.rel_path
LEFT JOIN file_cov fc
  ON h.rel_path = fc.rel_path
WHERE h.score > 0.7 * (SELECT MAX(score) FROM hotspots)   -- “very hot”
  AND t.typed_ratio < 0.5                                 -- poorly typed
  AND (fc.line_coverage_ratio IS NULL OR fc.line_coverage_ratio < 0.4)
ORDER BY h.score DESC
LIMIT 100;

---------------------------------------------------------------------
-- F. Quick sanity checks
---------------------------------------------------------------------

-- F1. Compare coverage_functions to coverage_lines rollup
WITH from_lines AS (
    SELECT
        function_goid_h128,
        COUNT(*) FILTER (WHERE is_executed) AS executed_lines_from_lines
    FROM coverage_lines
    WHERE function_goid_h128 IS NOT NULL
    GROUP BY function_goid_h128
)
SELECT
    f.function_goid_h128,
    f.executed_lines AS executed_lines_from_functions,
    l.executed_lines_from_lines
FROM coverage_functions f
JOIN from_lines l
  ON f.function_goid_h128 = l.function_goid_h128
ORDER BY ABS(f.executed_lines - l.executed_lines_from_lines) DESC
LIMIT 50;
```

---

If you’d like, I can next:

* Draft a small **risk scoring spec** (weights, bucketing, and calibration examples) for `goid_risk_factors`, and/or
* Sketch **concrete Python modules** (`risk_factors.py`, `coverage_analytics.py`) wired into your existing `enrich_analytics` CLI to actually produce these datasets.



# model layer and risk factors scoring #

Totally fair call-out — thanks for the nudge. Let’s actually do the two things I promised:

1. **Model layer** (Pydantic + a couple of dataclasses) for the risk datasets
2. **Concrete `risk_factors` scoring function** with weights, normalization, and a `risk_hotspots.compute_hotspot_score` integration

This assumes we’re consuming the existing analytics outputs (`hotspots.jsonl`, `typedness.jsonl`, call graph, etc.). 

---

## 1. Model layer: Pydantic + dataclasses

### 1.1 Core enums & row models (`risk_models.py`)

```python
# risk_models.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---- Enums -----------------------------------------------------------------


class RiskFactorKind(str, Enum):
    CHURN = "churn"
    COMPLEXITY = "complexity"
    OWNERSHIP = "ownership"
    TYPEDNESS = "typedness"
    CENTRALITY = "centrality"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---- Upstream analytics rows (inputs) --------------------------------------
# These mirror your existing analytics datasets. :contentReference[oaicite:1]{index=1}


class HotspotAnalyticsRow(BaseModel):
    """
    Row from hotspots.jsonl
    """
    rel_path: str
    commit_count: int
    author_count: int
    lines_added: int
    lines_deleted: int
    complexity: float
    score: float  # existing hotspot score


class TypednessRow(BaseModel):
    """
    Row from typedness.jsonl
    """
    rel_path: str
    function_count: int
    typed_functions: int
    partial_functions: int
    untyped_functions: int
    typed_ratio: float


# You can derive fan-in / fan-out from call_graph_edges.* and aggregate per file.
class CallGraphCentrality(BaseModel):
    rel_path: str
    fan_in: int
    fan_out: int


# ---- Aggregated per-file metrics view (in-memory) --------------------------


@dataclass
class FileRiskInput:
    """
    Aggregated metrics for a single file, used as the input to the risk
    scoring functions.
    """
    repo: str
    rel_path: str

    # From hotspots.jsonl
    commit_count: int
    author_count: int
    lines_added: int
    lines_deleted: int
    complexity: float

    # From typedness.jsonl (may be missing)
    typed_ratio: Optional[float] = None

    # From call graph aggregation (may be missing)
    call_fan_in: int = 0
    call_fan_out: int = 0


# ---- Risk datasets you’ll emit --------------------------------------------


class RiskFactorScore(BaseModel):
    """
    One row per (repo, file, factor).
    This is what you'd write to risk_factors.jsonl.
    """
    repo: str
    rel_path: str
    factor: RiskFactorKind

    raw_value: float = Field(
        ...,
        description="Underlying raw metric (e.g., churn, complexity, fan-in+fan-out).",
    )
    normalized_value: float = Field(
        ...,
        description="Raw value normalized into [0,1] where 1 is max risk.",
    )
    weight: float = Field(
        ...,
        description="Relative importance of this factor; all weights typically sum to 1.",
    )
    weighted_score: float = Field(
        ...,
        description="normalized_value * weight; contribution to overall risk_score.",
    )

    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form breakdown (commit_count, lines_added, etc.).",
    )
    computed_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When these values were computed.",
    )


class RiskHotspot(BaseModel):
    """
    One row per (repo, file) summarizing the combined risk score.
    This is what you'd write to risk_hotspots.jsonl.
    """
    repo: str
    rel_path: str

    risk_score: float = Field(
        ...,
        description="Final risk score in [0,1], aggregated from factor weighted_scores.",
    )
    risk_level: RiskLevel
    rank: Optional[int] = Field(
        default=None,
        description="1-based rank by risk_score within the repo (optional).",
    )

    # Top contributors to the score
    top_factors: List[RiskFactorKind] = Field(default_factory=list)
    factor_contributions: Dict[RiskFactorKind, float] = Field(
        default_factory=dict,
        description="Factor -> weighted_score contribution.",
    )

    # Convenience payload: raw metrics copied onto the row
    metrics: Dict[str, float] = Field(default_factory=dict)

    # Optional enrichment from tags_index / modules.jsonl, etc.
    tags: List[str] = Field(default_factory=list)
    owners: List[str] = Field(default_factory=list)

    computed_at: datetime = Field(default_factory=datetime.utcnow)
```

This gives you:

* Typed views over existing analytics: `HotspotAnalyticsRow`, `TypednessRow`, `CallGraphCentrality`
* An in-memory aggregation shape: `FileRiskInput`
* Persisted risk datasets: `RiskFactorScore` (per factor) and `RiskHotspot` (per file)

---

## 2. Risk scoring function + integration

### 2.1 Config + normalization helpers (`risk_scoring.py`)

```python
# risk_scoring.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .risk_models import (
    CallGraphCentrality,
    FileRiskInput,
    RiskFactorKind,
    RiskFactorScore,
    RiskHotspot,
    RiskLevel,
)


@dataclass
class RiskScoringConfig:
    """
    Tunable weights and normalization anchors.

    The weights here add up to 1.0 so that the sum of weighted_scores will
    always be in [0,1].
    """
    churn_weight: float = 0.30
    complexity_weight: float = 0.25
    ownership_weight: float = 0.20
    typedness_weight: float = 0.15
    centrality_weight: float = 0.10

    # Anchors roughly correspond to (p50, p90) or similar quantiles across the repo.
    # You should tune these from real data.
    churn_low: float = 2.0
    churn_high: float = 10.0

    complexity_low: float = 5.0
    complexity_high: float = 20.0

    ownership_low: float = 2.0
    ownership_high: float = 5.0

    # For typed coverage, low is risky (e.g., p10 / p50).
    typed_coverage_low: float = 0.3
    typed_coverage_high: float = 0.7

    centrality_low: float = 5.0
    centrality_high: float = 20.0


def _linear_scale_high_is_risky(value: float, low: float, high: float) -> float:
    """
    Map a metric where "higher is riskier" into [0,1].

    <= low  => 0.0
    >= high => 1.0
    linear in between.
    """
    if high <= low:
        return 0.0
    if value <= low:
        return 0.0
    if value >= high:
        return 1.0
    return (value - low) / (high - low)


def _linear_scale_low_is_risky(value: float, low: float, high: float) -> float:
    """
    Map a metric where "lower is riskier" into [0,1].

    <= low  => 1.0
    >= high => 0.0
    linear in between.
    """
    if high <= low:
        return 0.0
    if value <= low:
        return 1.0
    if value >= high:
        return 0.0
    return (high - value) / (high - low)


def _risk_level_from_score(score: float) -> RiskLevel:
    """
    Simple banding of [0,1] into levels.
    You can tune these to your taste.
    """
    if score < 0.30:
        return RiskLevel.LOW
    if score < 0.55:
        return RiskLevel.MEDIUM
    if score < 0.80:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL
```

### 2.2 Computing per-factor scores

```python
# risk_scoring.py (continued)

def compute_risk_factors(
    metrics: FileRiskInput,
    cfg: RiskScoringConfig,
) -> Dict[RiskFactorKind, RiskFactorScore]:
    """
    Compute normalized + weighted scores for each factor for a single file.
    """
    factors: Dict[RiskFactorKind, RiskFactorScore] = {}

    # ----- Churn -------------------------------------------------------------
    # Simple composite: commits + scaled lines churn.
    churn_raw = metrics.commit_count + (metrics.lines_added + metrics.lines_deleted) / 200.0
    churn_norm = _linear_scale_high_is_risky(churn_raw, cfg.churn_low, cfg.churn_high)
    factors[RiskFactorKind.CHURN] = RiskFactorScore(
        repo=metrics.repo,
        rel_path=metrics.rel_path,
        factor=RiskFactorKind.CHURN,
        raw_value=churn_raw,
        normalized_value=churn_norm,
        weight=cfg.churn_weight,
        weighted_score=churn_norm * cfg.churn_weight,
        details={
            "commit_count": metrics.commit_count,
            "lines_added": metrics.lines_added,
            "lines_deleted": metrics.lines_deleted,
        },
    )

    # ----- Complexity --------------------------------------------------------
    complexity_raw = metrics.complexity
    complexity_norm = _linear_scale_high_is_risky(
        complexity_raw,
        cfg.complexity_low,
        cfg.complexity_high,
    )
    factors[RiskFactorKind.COMPLEXITY] = RiskFactorScore(
        repo=metrics.repo,
        rel_path=metrics.rel_path,
        factor=RiskFactorKind.COMPLEXITY,
        raw_value=complexity_raw,
        normalized_value=complexity_norm,
        weight=cfg.complexity_weight,
        weighted_score=complexity_norm * cfg.complexity_weight,
        details={"complexity": metrics.complexity},
    )

    # ----- Ownership diffusion ----------------------------------------------
    ownership_raw = metrics.author_count
    ownership_norm = _linear_scale_high_is_risky(
        ownership_raw,
        cfg.ownership_low,
        cfg.ownership_high,
    )
    factors[RiskFactorKind.OWNERSHIP] = RiskFactorScore(
        repo=metrics.repo,
        rel_path=metrics.rel_path,
        factor=RiskFactorKind.OWNERSHIP,
        raw_value=ownership_raw,
        normalized_value=ownership_norm,
        weight=cfg.ownership_weight,
        weighted_score=ownership_norm * cfg.ownership_weight,
        details={"author_count": metrics.author_count},
    )

    # ----- Typedness ---------------------------------------------------------
    # Lower type coverage => higher risk.
    if metrics.typed_ratio is None:
        # If we don't know, treat as "medium" risk.
        typed_ratio = (cfg.typed_coverage_low + cfg.typed_coverage_high) / 2.0
    else:
        typed_ratio = metrics.typed_ratio

    typed_norm = _linear_scale_low_is_risky(
        typed_ratio,
        cfg.typed_coverage_low,
        cfg.typed_coverage_high,
    )
    factors[RiskFactorKind.TYPEDNESS] = RiskFactorScore(
        repo=metrics.repo,
        rel_path=metrics.rel_path,
        factor=RiskFactorKind.TYPEDNESS,
        raw_value=typed_ratio,
        normalized_value=typed_norm,
        weight=cfg.typedness_weight,
        weighted_score=typed_norm * cfg.typedness_weight,
        details={"typed_ratio": metrics.typed_ratio},
    )

    # ----- Centrality (call graph) ------------------------------------------
    centrality_raw = metrics.call_fan_in + metrics.call_fan_out
    centrality_norm = _linear_scale_high_is_risky(
        centrality_raw,
        cfg.centrality_low,
        cfg.centrality_high,
    )
    factors[RiskFactorKind.CENTRALITY] = RiskFactorScore(
        repo=metrics.repo,
        rel_path=metrics.rel_path,
        factor=RiskFactorKind.CENTRALITY,
        raw_value=centrality_raw,
        normalized_value=centrality_norm,
        weight=cfg.centrality_weight,
        weighted_score=centrality_norm * cfg.centrality_weight,
        details={
            "call_fan_in": metrics.call_fan_in,
            "call_fan_out": metrics.call_fan_out,
        },
    )

    return factors
```

### 2.3 `risk_hotspots.compute_hotspot_score` and row construction

Here’s an implementation that:

* Keeps a **simple float-returning** `compute_hotspot_score` (for backwards compatibility)
* Provides a helper to build the **full `RiskHotspot` row** and companion factor rows

```python
# risk_hotspots.py
from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from .risk_models import FileRiskInput, RiskFactorKind, RiskFactorScore, RiskHotspot
from .risk_scoring import RiskScoringConfig, compute_risk_factors, _risk_level_from_score


def compute_hotspot_score(
    metrics: FileRiskInput,
    cfg: RiskScoringConfig | None = None,
) -> float:
    """
    Thin wrapper that just returns the final risk score in [0,1].

    This is the function other tooling can call without caring about the
    per-factor breakdown.
    """
    if cfg is None:
        cfg = RiskScoringConfig()

    factor_scores = compute_risk_factors(metrics, cfg)
    return sum(f.weighted_score for f in factor_scores.values())


def compute_hotspot_row(
    metrics: FileRiskInput,
    cfg: RiskScoringConfig | None = None,
) -> Tuple[RiskHotspot, Dict[RiskFactorKind, RiskFactorScore]]:
    """
    Rich version that returns:
      - a RiskHotspot row (ready to serialize)
      - a dict of RiskFactorScore rows keyed by factor
    """
    if cfg is None:
        cfg = RiskScoringConfig()

    factor_scores = compute_risk_factors(metrics, cfg)
    risk_score = sum(f.weighted_score for f in factor_scores.values())
    risk_level = _risk_level_from_score(risk_score)

    # Sort factors by contribution
    sorted_factors: List[RiskFactorKind] = sorted(
        factor_scores.keys(),
        key=lambda k: factor_scores[k].weighted_score,
        reverse=True,
    )

    hotspot = RiskHotspot(
        repo=metrics.repo,
        rel_path=metrics.rel_path,
        risk_score=risk_score,
        risk_level=risk_level,
        top_factors=sorted_factors[:3],
        factor_contributions={
            k: fs.weighted_score for k, fs in factor_scores.items()
        },
        metrics={
            "commit_count": metrics.commit_count,
            "author_count": metrics.author_count,
            "lines_added": metrics.lines_added,
            "lines_deleted": metrics.lines_deleted,
            "complexity": metrics.complexity,
            "typed_ratio": metrics.typed_ratio or 0.0,
            "call_fan_in": metrics.call_fan_in,
            "call_fan_out": metrics.call_fan_out,
        },
        # fill tags/owners later using tags_index/modules.jsonl if you want
        tags=[],
        owners=[],
    )

    return hotspot, factor_scores
```

### 2.4 Example: building `FileRiskInput` from existing datasets

Sketch of how this wires into your current outputs:

```python
# risk_pipeline.py
from pathlib import Path
import json
from typing import Dict, Optional

from .risk_models import (
    CallGraphCentrality,
    FileRiskInput,
    HotspotAnalyticsRow,
    TypednessRow,
)
from .risk_hotspots import compute_hotspot_row
from .risk_scoring import RiskScoringConfig
from .risk_models import RiskFactorScore, RiskHotspot


def _load_indexed_by_relpath(model, path: Path) -> Dict[str, object]:
    out: Dict[str, object] = {}
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            row = model.parse_obj(json.loads(line))
            out[row.rel_path] = row
    return out


def build_file_risk_inputs(
    repo: str,
    hotspots_path: Path,
    typedness_path: Optional[Path] = None,
    centrality_by_relpath: Optional[Dict[str, CallGraphCentrality]] = None,
):
    hotspots = _load_indexed_by_relpath(HotspotAnalyticsRow, hotspots_path)

    typedness = (
        _load_indexed_by_relpath(TypednessRow, typedness_path)
        if typedness_path is not None
        else {}
    )

    centrality_by_relpath = centrality_by_relpath or {}

    for rel_path, h in hotspots.items():
        t = typedness.get(rel_path)
        c = centrality_by_relpath.get(rel_path)

        yield FileRiskInput(
            repo=repo,
            rel_path=rel_path,
            commit_count=h.commit_count,
            author_count=h.author_count,
            lines_added=h.lines_added,
            lines_deleted=h.lines_deleted,
            complexity=h.complexity,
            typed_ratio=(t.typed_ratio if t else None),
            call_fan_in=(c.fan_in if c else 0),
            call_fan_out=(c.fan_out if c else 0),
        )


def run_risk_pipeline(
    repo: str,
    hotspots_path: Path,
    typedness_path: Optional[Path],
    risk_hotspots_out: Path,
    risk_factors_out: Path,
    cfg: Optional[RiskScoringConfig] = None,
):
    cfg = cfg or RiskScoringConfig()

    with risk_hotspots_out.open("w") as hotspots_f, risk_factors_out.open("w") as factors_f:
        for metrics in build_file_risk_inputs(
            repo=repo,
            hotspots_path=hotspots_path,
            typedness_path=typedness_path,
        ):
            hotspot, factor_scores = compute_hotspot_row(metrics, cfg)

            hotspots_f.write(hotspot.json() + "\n")
            for fs in factor_scores.values():
                factors_f.write(fs.json() + "\n")
```

---

If you’d like, I can next:

* Help you tune the **anchors** (low/high) and **weights** using a concrete sample of your repo’s metrics, or
* Fold this into your existing CLI / enrichment pipeline so `generate_documents.sh` also emits `risk_hotspots.jsonl` and `risk_factors.jsonl`.



# risk wiring through to enrichment pipeline #

Got it — let’s wire this all the way through so the **enrich pipeline + CLI** produce risk scores, and **generate_documents.sh** emits:

* `risk_factors.jsonl` (per‑function GOID risk info)
* `risk_hotspots.jsonl` (per‑file “where should I look first?” view)

I’ll assume the earlier plans are (or will be) implemented:

* Existing datasets: `goids`, `goid_crosswalk`, call graph, CFG/DFG, `ast_metrics`, `hotspots`, `typedness`, `modules`, `repo_map`.
* Newer ones: `import_graph_edges`, `symbol_use_edges`, `config_values`, `static_diagnostics` (analytics under `analytics/`).
* Per‑function: `function_metrics.jsonl`, `function_types.jsonl`.
* Coverage/tests: `coverage_lines.*`, `coverage_functions.*`, `test_catalog.*`, `test_coverage_edges.*` from the previous coverage plan.

Below is a drop‑in implementation plan.

---

## 0. High‑level design

We’ll add a **risk analytics layer** that:

1. **Builds per‑function risk**:

   * Input: `function_metrics`, `function_types`, `coverage_functions`, `test_coverage_edges`, `static_diagnostics`, `hotspots`, `typedness`, call graph.
   * Output: `analytics/risk_factors.parquet` + `analytics/risk_factors.jsonl`.

2. **Aggregates to per‑file risk hotspots**:

   * Input: `risk_factors` + per‑file analytics (`hotspots`, `typedness`, `static_diagnostics`, `modules`).
   * Output: `analytics/risk_hotspots.parquet` + `analytics/risk_hotspots.jsonl`.

3. **Integrates with doc generation**:

   * `duckdb_catalog` knows about both tables.
   * `generate_documents.sh` copies them into `Document Output/` as:

     * `Document Output/risk_factors.parquet` + `.jsonl`
     * `Document Output/risk_hotspots.parquet` + `.jsonl`

4. **CLI / pipeline integration**:

   * New analytics module: `codeintel_rev.services.enrich.analytics.risk`.
   * New pipeline runner: `run_risk_analytics(enriched_dir: str)`.
   * Hook into the main enrich pipeline so `enrich_pipeline all` runs risk analytics automatically.
   * Optional dedicated CLI subcommand: `codeintel_rev.cli.enrich_pipeline risk`.

---

## 1. Dataset specs

### 1.1 `risk_factors.*` (per‑function GOID)

**Row grain**: one callable/function GOID (`function_goid_h128`) – same universe as `function_metrics` / `function_types`.

**Files**:

* `enriched/analytics/risk_factors.parquet`
* `enriched/analytics/risk_factors.jsonl`
* Mirrored into doc root: `Document Output/risk_factors.parquet`, `Document Output/risk_factors.jsonl`.

**Schema (conceptual JSONL row)**

```jsonc
{
  "function_goid_h128": "12345678901234567890",
  "urn": "goid:repo/path#python:function:pkg.mod.Foo.bar?s=10&e=42",

  "repo": "kgfoundry",
  "commit": "deadbeef",
  "rel_path": "codeintel_rev/app/routes/catalog_read.py",
  "language": "python",
  "kind": "method",
  "qualname": "codeintel_rev.app.routes.catalog_read.CatalogReader.get",
  "start_line": 101,
  "end_line": 158,

  // raw function metrics
  "cyclomatic_complexity": 7,
  "max_nesting_depth": 3,
  "loc": 32,
  "logical_loc": 24,
  "stmt_count": 18,
  "decorator_count": 1,
  "has_docstring": true,

  // call graph structure
  "fan_in": 12,
  "fan_out": 5,

  // coverage / tests
  "covered_lines": 26,
  "total_lines": 32,
  "coverage_ratio": 0.8125,
  "tests_covering": 3,               // distinct tests that executed this function
  "indirect_tests_covering": 2,      // via call graph (optional)

  // typing / static analysis
  "typed_params_ratio": 1.0,
  "has_return_annotation": true,
  "typedness_bucket": "typed",       // typed | partial | untyped
  "file_typed_ratio": 0.9,           // from typedness.jsonl per file
  "static_error_count": 0,           // from static_diagnostics
  "has_static_errors": false,

  // file-level change metrics
  "file_hotspot_score": 0.76,        // normalized from hotspots.score
  "file_commit_count": 54,
  "file_author_count": 7,

  // normalized factor scores in [0,1]
  "complexity_risk": 0.6,
  "coupling_risk": 0.9,
  "coverage_risk": 0.3,
  "typing_risk": 0.1,
  "static_diagnostics_risk": 0.0,
  "change_risk": 0.75,

  // composite
  "total_risk_score": 0.68,          // weighted sum of above factors, [0,1]
  "risk_bucket": "high",             // low | medium | high

  // a bit of explanation for LLMs / UIs
  "top_reasons": [
    "High fan-in (12 callers)",
    "Lives in a high-churn file (54 commits, hotspot score 0.76)",
    "Complex function (cyclomatic 7, depth 3)"
  ],

  "created_at": "2025-01-01T00:00:00Z"
}
```

Notes:

* We reuse the *descriptor* fields (`repo`, `rel_path`, `kind`, `qualname`, `start_line`, `end_line`) from `function_metrics` / `function_types`, so we don’t need to re‑join to `goids` in code.
* `fan_in`/`fan_out` come from `call_graph_edges` grouped by `callee_goid_h128` / `caller_goid_h128`.
* Coverage fields come from `coverage_functions` (see earlier plan).
* File‑level metrics from `hotspots`, `typedness`, `static_diagnostics` are joined by `rel_path`.

### 1.2 `risk_hotspots.*` (per file)

**Row grain**: one file (`rel_path`).

**Files**:

* `enriched/analytics/risk_hotspots.parquet`
* `enriched/analytics/risk_hotspots.jsonl`
* Mirrored into doc root: `Document Output/risk_hotspots.parquet`, `Document Output/risk_hotspots.jsonl`.

**Schema (conceptual JSONL row)**

```jsonc
{
  "rel_path": "codeintel_rev/app/routes/catalog_read.py",
  "repo": "kgfoundry",
  "commit": "deadbeef",
  "language": "python",

  // aggregation from risk_factors
  "functions_total": 12,
  "high_risk_functions": 3,
  "medium_risk_functions": 5,
  "low_risk_functions": 4,
  "max_function_risk": 0.88,
  "mean_function_risk": 0.54,
  "p95_function_risk": 0.82,

  // coverage aggregation (file-level)
  "file_coverage_ratio": 0.76,
  "uncovered_functions": 4,

  // re‑expose hotspot & typedness analytics
  "hotspot_score": 0.81,          // normalized from hotspots.score
  "commit_count": 54,
  "author_count": 7,
  "ast_complexity": 132.0,        // from ast_metrics.complexity
  "file_typed_ratio": 0.90,       // from typedness.typed_ratio
  "static_error_count": 2,
  "has_static_errors": true,

  // ownership / tags
  "module": "codeintel_rev.app.routes.catalog_read",
  "tags": ["api"],
  "owners": ["team-api"],

  // final risk values
  "file_risk_score": 0.79,        // composite [0,1]
  "risk_bucket": "high",          // low | medium | high

  // top three risky functions for UX / LLM explanations
  "top_risky_functions": [
    {
      "function_goid_h128": "12345678901234567890",
      "qualname": "CatalogReader.get",
      "total_risk_score": 0.88,
      "risk_bucket": "high",
      "start_line": 100,
      "end_line": 158
    },
    ...
  ],

  "created_at": "2025-01-01T00:00:00Z"
}
```

---

## 2. Risk scoring: factors & weights

We’ll implement scoring in pure Python for clarity (no DuckDB dependency inside the pipeline itself), using a two‑pass normalization:

### 2.1 Feature extraction

For each function GOID, we build a “feature row”:

* **From `function_metrics`**

  * `cyclomatic_complexity`, `max_nesting_depth`, `loc`, `stmt_count`, `decorator_count`, `has_docstring`.
* **From `function_types`**

  * `total_params`, `annotated_params`, `param_typed_ratio`, `has_return_annotation`, `typedness_bucket`.
* **From `coverage_functions`**

  * `covered_lines`, `total_lines`, `coverage_ratio = covered/total` (0 if missing).
  * `tests_covering` (count of tests covering this function).
* **From call graph edges**

  * `fan_in` = count of distinct callers.
  * `fan_out` = count of distinct callees.
* **From file‑level analytics** (via `rel_path`)

  * `file_hotspot_score` = rescaled `hotspots.score` to [0,1].
  * `commit_count`, `author_count`, `ast_complexity` (from `ast_metrics`).
  * `file_typed_ratio` from `typedness.typed_ratio`.
  * `static_error_count` from `static_diagnostics.total_errors`.

### 2.2 Normalization strategy

For each numeric feature, we compute global stats across the repo:

* `max_cyclomatic`, `p95_cyclomatic`
* `max_fan_in_out` (based on `sqrt(fan_in^2 + fan_out^2)`)
* `max_hotspot_score`
* `max_commit_count`
* `max_ast_complexity`
* etc.

Then define helper:

```python
def normalize(value: float, hi: float, *, default: float = 0.0) -> float:
    if hi <= 0:
        return default
    return max(0.0, min(1.0, value / hi))
```

For features where **higher value means more risk**, we normalize directly. For “safety” metrics we invert:

* `coverage_risk = 1.0 - coverage_ratio`
* `typing_risk = 1.0 - param_typed_ratio`
* `file_typed_risk = 1.0 - file_typed_ratio`

### 2.3 Factor definitions

Per function:

* **Complexity risk**

  * `complexity_index = 0.7 * cyclomatic_complexity + 0.3 * max_nesting_depth`
  * `complexity_risk = normalize(complexity_index, p95_complexity_index)`

* **Coupling risk** (call graph centrality)

  * `degree = sqrt(fan_in**2 + fan_out**2)`
  * `coupling_risk = normalize(degree, p95_degree)`

* **Coverage risk**

  * `coverage_ratio = covered_lines / total_lines if total_lines > 0 else 0.0`
  * `coverage_risk = 1.0 - coverage_ratio`
  * Optionally bump when `tests_covering == 0` (e.g. `coverage_risk = min(1.0, coverage_risk + 0.15)`).

* **Typing risk**

  * `typing_risk = 1.0 - param_typed_ratio`
  * Bump for buckets:

    * `untyped` → `typing_risk = max(typing_risk, 0.8)`
    * `partial` → `typing_risk = max(typing_risk, 0.4)`
  * Optionally blend in file‑level type coverage:

    * `typing_risk = 0.7 * typing_risk + 0.3 * (1.0 - file_typed_ratio)`

* **Static diagnostics risk**

  * `static_diagnostics_risk = 1.0 if static_error_count > 0 else 0.0`
  * Or soften: `normalize(static_error_count, hi=5.0)`.

* **Change risk**

  * Normalize `file_hotspot_score` to [0,1] based on `p95_hotspot_score`.

You can later adjust these formulas without changing the schema.

### 2.4 Composite score & bucket

Define weights (sensible v1):

```python
WEIGHTS = {
    "complexity_risk":          0.25,
    "coupling_risk":            0.20,
    "coverage_risk":            0.25,
    "typing_risk":              0.15,
    "static_diagnostics_risk":  0.05,
    "change_risk":              0.10,
}
```

Compute:

```python
total_risk_score = sum(
    WEIGHTS[name] * getattr(row, name)
    for name in WEIGHTS
)
```

Bucket:

```python
if total_risk_score >= 0.66:
    risk_bucket = "high"
elif total_risk_score >= 0.33:
    risk_bucket = "medium"
else:
    risk_bucket = "low"
```

### 2.5 Explainability

`top_reasons` is built from thresholds:

* If `complexity_risk > 0.7` → `"High cyclomatic complexity (X, depth Y)"`
* If `coupling_risk > 0.7` → `"High fan-in/out (fan-in A, fan-out B)"`
* If `coverage_risk > 0.7` → `"Poor test coverage (ratio 0.xx)"`
* If `typing_risk > 0.7` → `"Missing type annotations"`
* If `static_diagnostics_risk > 0.5` → `"Static analysis errors present"`
* If `change_risk > 0.7` → `"Heavily changed hotspot file"`

Keep the top 3‑4 reasons so LLMs can quote them back directly.

---

## 3. Risk analytics module

Create a new module:

```text
codeintel_rev/services/enrich/analytics/risk.py
```

### 3.1 Dataclasses & schemas

```python
# codeintel_rev/services/enrich/analytics/risk.py

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

import json
import math
import datetime

from codeintel_rev.services.enrich.io import open_text_in, open_text_out
from codeintel_rev.enrich.output_writers import write_parquet
from codeintel_rev.services.enrich.io import write_jsonl as write_jsonl_legacy
```

**RiskFactorsRow**

```python
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

    cyclomatic_complexity: int
    max_nesting_depth: int
    loc: int
    logical_loc: int
    stmt_count: int
    decorator_count: int
    has_docstring: bool

    fan_in: int
    fan_out: int

    covered_lines: int
    total_lines: int
    coverage_ratio: float
    tests_covering: int

    total_params: int
    annotated_params: int
    param_typed_ratio: float
    has_return_annotation: bool
    typedness_bucket: str
    file_typed_ratio: float

    static_error_count: int
    file_hotspot_score: float
    commit_count: int
    author_count: int
    ast_complexity: float

    complexity_risk: float
    coupling_risk: float
    coverage_risk: float
    typing_risk: float
    static_diagnostics_risk: float
    change_risk: float

    total_risk_score: float
    risk_bucket: str
    top_reasons: List[str]

    created_at: str
```

You can keep a parallel Arrow schema dict like:

```python
RISK_FACTORS_SCHEMA = {
    "function_goid_h128": "DECIMAL(38,0)",
    "urn": "STRING",
    "repo": "STRING",
    ...
    "total_risk_score": "DOUBLE",
    "risk_bucket": "STRING",
    "top_reasons": "LIST<STRING>",
    "created_at": "TIMESTAMP",
}
```

**RiskHotspotRow**

```python
@dataclass
class RiskHotspotRow:
    rel_path: str
    repo: str
    commit: str
    language: str

    functions_total: int
    high_risk_functions: int
    medium_risk_functions: int
    low_risk_functions: int
    max_function_risk: float
    mean_function_risk: float
    p95_function_risk: float

    file_coverage_ratio: float
    uncovered_functions: int

    hotspot_score: float
    commit_count: int
    author_count: int
    ast_complexity: float
    file_typed_ratio: float
    static_error_count: int
    has_static_errors: bool

    module: Optional[str]
    tags: List[str]
    owners: List[str]

    file_risk_score: float
    risk_bucket: str

    top_risky_functions: List[Mapping[str, object]]

    created_at: str
```

### 3.2 Loading helpers

These helpers assume JSONL sources; tweak if your earlier plan wrote Parquet instead.

```python
def _load_index_by_goid(path: Path) -> Dict[str, dict]:
    """Generic JSONL loader keyed by function_goid_h128."""
    index: Dict[str, dict] = {}
    if not path.is_file():
        return index
    with open_text_in(path) as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            goid = str(obj["function_goid_h128"])
            index[goid] = obj
    return index


def _load_index_by_rel_path(path: Path) -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    if not path.is_file():
        return index
    with open_text_in(path) as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            index[obj["rel_path"]] = obj
    return index
```

You’ll want special loaders for:

* call graph fan‑in/out (from Parquet or JSONL),
* coverage_functions,
* test_coverage_edges (if you want `tests_covering`),
* modules (for tags/owners).

### 3.3 Computing factor rows

Sketch:

```python
def build_risk_factor_rows(enriched_dir: Path) -> List[RiskFactorsRow]:
    enriched_dir = enriched_dir.resolve()

    metrics = _load_index_by_goid(enriched_dir / "function_metrics.jsonl")
    types = _load_index_by_goid(enriched_dir / "function_types.jsonl")

    hotspots = _load_index_by_rel_path(enriched_dir / "analytics" / "hotspots.jsonl")
    typedness = _load_index_by_rel_path(enriched_dir / "analytics" / "typedness.jsonl")
    diagnostics = _load_index_by_rel_path(enriched_dir / "analytics" / "static_diagnostics.jsonl")

    coverage = _load_index_by_goid(enriched_dir / "analytics" / "coverage_functions.jsonl")
    fan_in, fan_out = _load_call_graph_degrees(enriched_dir)
    coverage_tests = _load_tests_per_function(enriched_dir)

    # first pass: compute global stats
    stats = _compute_global_stats(metrics, coverage, fan_in, fan_out, hotspots)

    now = datetime.datetime.utcnow().isoformat() + "Z"
    rows: List[RiskFactorsRow] = []

    for goid, m in metrics.items():
        t = types.get(goid, {})
        cov = coverage.get(goid, {})
        rel_path = m["rel_path"]

        h = hotspots.get(rel_path, {})
        ty = typedness.get(rel_path, {})
        diag = diagnostics.get(rel_path, {})

        row = _build_single_risk_row(
            goid=goid,
            metrics=m,
            types=t,
            coverage=cov,
            tests_covering=coverage_tests.get(goid, 0),
            fan_in=fan_in.get(goid, 0),
            fan_out=fan_out.get(goid, 0),
            hotspot=h,
            typed=ty,
            diag=diag,
            stats=stats,
            created_at=now,
        )
        rows.append(row)

    return rows
```

`_build_single_risk_row` is where the formulas from §2.2–2.4 live.

### 3.4 Aggregating to risk hotspots

```python
def build_risk_hotspot_rows(
    risk_rows: Iterable[RiskFactorsRow],
    enriched_dir: Path,
) -> List[RiskHotspotRow]:
    by_file: Dict[str, List[RiskFactorsRow]] = {}
    for row in risk_rows:
        by_file.setdefault(row.rel_path, []).append(row)

    hotspots = _load_index_by_rel_path(enriched_dir / "analytics" / "hotspots.jsonl")
    typedness = _load_index_by_rel_path(enriched_dir / "analytics" / "typedness.jsonl")
    diagnostics = _load_index_by_rel_path(enriched_dir / "analytics" / "static_diagnostics.jsonl")
    modules = _load_modules(enriched_dir)

    now = datetime.datetime.utcnow().isoformat() + "Z"
    out: List[RiskHotspotRow] = []

    for rel_path, rows in by_file.items():
        scores = [r.total_risk_score for r in rows]
        scores_sorted = sorted(scores)
        n = len(rows)
        p95 = scores_sorted[int(0.95 * (n - 1))] if n > 0 else 0.0

        high = sum(1 for r in rows if r.risk_bucket == "high")
        med = sum(1 for r in rows if r.risk_bucket == "medium")
        low = sum(1 for r in rows if r.risk_bucket == "low")

        cov_nz = [r.coverage_ratio for r in rows if r.total_lines > 0]
        file_cov = sum(cov_nz) / len(cov_nz) if cov_nz else 0.0
        uncovered_funcs = sum(1 for r in rows if r.coverage_ratio < 1.0)

        h = hotspots.get(rel_path, {})
        ty = typedness.get(rel_path, {})
        diag = diagnostics.get(rel_path, {})
        mod = modules.get(rel_path, {})

        # combine mean function risk + hotspot score
        mean_risk = sum(scores) / n if n else 0.0
        hotspot_norm = h.get("score_norm", 0.0)  # or recompute
        file_risk_score = 0.7 * mean_risk + 0.3 * hotspot_norm

        if file_risk_score >= 0.66:
            bucket = "high"
        elif file_risk_score >= 0.33:
            bucket = "medium"
        else:
            bucket = "low"

        top_funcs = sorted(rows, key=lambda r: r.total_risk_score, reverse=True)[:3]
        top_risky_functions = [
            {
                "function_goid_h128": f.function_goid_h128,
                "qualname": f.qualname,
                "total_risk_score": f.total_risk_score,
                "risk_bucket": f.risk_bucket,
                "start_line": f.start_line,
                "end_line": f.end_line,
            }
            for f in top_funcs
        ]

        out.append(
            RiskHotspotRow(
                rel_path=rel_path,
                repo=rows[0].repo,
                commit=rows[0].commit,
                language=rows[0].language,

                functions_total=n,
                high_risk_functions=high,
                medium_risk_functions=med,
                low_risk_functions=low,
                max_function_risk=max(scores) if scores else 0.0,
                mean_function_risk=mean_risk,
                p95_function_risk=p95,

                file_coverage_ratio=file_cov,
                uncovered_functions=uncovered_funcs,

                hotspot_score=h.get("score", 0.0),
                commit_count=h.get("commit_count", 0),
                author_count=h.get("author_count", 0),
                ast_complexity=h.get("complexity", 0.0),
                file_typed_ratio=ty.get("typed_ratio", 0.0),
                static_error_count=diag.get("total_errors", 0),
                has_static_errors=bool(diag.get("has_errors", False)),

                module=mod.get("module"),
                tags=mod.get("tags", []),
                owners=mod.get("owners", []),

                file_risk_score=file_risk_score,
                risk_bucket=bucket,
                top_risky_functions=top_risky_functions,
                created_at=now,
            )
        )
    return out
```

Here `_load_modules` reads `modules.jsonl` under `enriched/modules/` and returns a mapping `rel_path -> {module, tags, owners}` as per README.

### 3.5 Writers

```python
def write_risk_factors(enriched_dir: Path, rows: Iterable[RiskFactorsRow]) -> None:
    analytics_dir = enriched_dir / "analytics"
    analytics_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = analytics_dir / "risk_factors.parquet"
    jsonl_path = analytics_dir / "risk_factors.jsonl"

    # Parquet
    write_parquet(parquet_path, (asdict(r) for r in rows), schema=RISK_FACTORS_SCHEMA)

    # JSONL
    write_jsonl_legacy(jsonl_path, (asdict(r) for r in rows))


def write_risk_hotspots(enriched_dir: Path, rows: Iterable[RiskHotspotRow]) -> None:
    analytics_dir = enriched_dir / "analytics"
    analytics_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = analytics_dir / "risk_hotspots.parquet"
    jsonl_path = analytics_dir / "risk_hotspots.jsonl"

    write_parquet(parquet_path, (asdict(r) for r in rows), schema=RISK_HOTSPOTS_SCHEMA)
    write_jsonl_legacy(jsonl_path, (asdict(r) for r in rows))
```

### 3.6 Orchestration entrypoint

Expose a single public function:

```python
def compute_and_write_risk(enriched_dir: Path) -> None:
    """Top-level entry: compute risk_factors & risk_hotspots and write both."""
    enriched_dir = enriched_dir.resolve()

    risk_rows = build_risk_factor_rows(enriched_dir)
    write_risk_factors(enriched_dir, risk_rows)

    hotspot_rows = build_risk_hotspot_rows(risk_rows, enriched_dir)
    write_risk_hotspots(enriched_dir, hotspot_rows)
```

---

## 4. Pipeline & CLI wiring

### 4.1 Pipeline runner

In `codeintel_rev/services/enrich/pipeline.py`, add:

```python
# codeintel_rev/services/enrich/pipeline.py

from pathlib import Path
from codeintel_rev.services.enrich.analytics.risk import compute_and_write_risk

def run_risk_analytics(*, enriched_dir: str) -> None:
    """Compute risk_factors & risk_hotspots analytics."""
    compute_and_write_risk(Path(enriched_dir))
```

### 4.2 Integrate into main pipeline

In the orchestration function where you already call:

* `write_graph_outputs`
* `write_uses_output`
* `write_config_output`
* `apply_ownership`
* `write_static_diagnostics_output`

(as in the earlier plan)  add a call at the end:

```python
from codeintel_rev.services.enrich.pipeline import run_risk_analytics

def run_pipeline(ctx: LegacyPipelineContext, steps: Sequence[GraphStep], out: Path) -> PipelineResult:
    result = _run_core_pipeline(ctx, steps, out)

    write_graph_outputs(result, out)
    write_uses_output(result, out)
    write_config_output(result, out)
    apply_ownership(result, out, history_window_days=..., commits_window=...)
    write_static_diagnostics_output(ctx, out)

    # NEW: risk analytics (uses files emitted above)
    run_risk_analytics(enriched_dir=str(out))

    return result
```

This ensures that **any** path which invokes `run_pipeline` (including `enrich_pipeline all`) will produce the risk datasets as part of the normal run.

### 4.3 CLI entrypoint

Extend `codeintel_rev/cli/enrich_pipeline.py` similarly to how you wired `function-metrics` / `function-types`.

```python
# codeintel_rev/cli/enrich_pipeline.py

import click
from codeintel_rev.services.enrich.pipeline import run_risk_analytics

@click.group()
def enrich():
    ...

@enrich.command("risk")
@click.option("--enriched-dir", required=True, help="Path to ENRICHED output dir")
def risk_cmd(enriched_dir: str) -> None:
    """Compute risk_factors & risk_hotspots analytics."""
    run_risk_analytics(enriched_dir=enriched_dir)
```

So you can either:

* Let the normal `all` pipeline call `run_risk_analytics`, **or**
* Run it standalone: `python -m codeintel_rev.cli.enrich_pipeline risk --enriched-dir path/to/io/ENRICHED`.

---

## 5. DuckDB catalog & `generate_documents.sh`

### 5.1 Register analytics tables

In `codeintel_rev/io/duckdb_catalog.py`, extend `ANALYTICS_TABLES` (following the config_values/static_diagnostics pattern).

```python
ANALYTICS_TABLES = {
    **ANALYTICS_TABLES,
    "risk_factors": {
        "path": "analytics/risk_factors.parquet",
        "ddl": """
            CREATE TABLE risk_factors AS
            SELECT
                *
            FROM read_parquet('{path}');
        """,
    },
    "risk_hotspots": {
        "path": "analytics/risk_hotspots.parquet",
        "ddl": """
            CREATE TABLE risk_hotspots AS
            SELECT
                *
            FROM read_parquet('{path}');
        """,
    },
}
```

This makes them available as DuckDB tables when the doc generator builds its database.

### 5.2 Update `generate_documents.sh`

Depending on how you currently mirror analytics to `Document Output/`, you have two common patterns:

#### Pattern A – via DuckDB `COPY`

If you already have a loop like this (as you do for graph tables):

```bash
for table in goids goid_crosswalk call_graph_nodes call_graph_edges \
             cfg_blocks cfg_edges dfg_edges import_graph_edges; do
  duckdb "$DB" "
    COPY ${table} TO '${DOC_OUT}/${table}.jsonl'
    (FORMAT JSON, ARRAY FALSE);
  "
done
```

Add a similar loop for analytics tables, including the new ones:

```bash
for table in ast_metrics hotspots typedness \
             config_values static_diagnostics \
             risk_factors risk_hotspots; do
  duckdb "$DB" "
    COPY ${table} TO '${DOC_OUT}/${table}.parquet' (FORMAT PARQUET);
    COPY ${table} TO '${DOC_OUT}/${table}.jsonl' (FORMAT JSON, ARRAY FALSE);
  "
done
```

This assumes you’ve already created `risk_factors` and `risk_hotspots` in the DuckDB catalog using `ANALYTICS_TABLES` above.

#### Pattern B – direct copy of JSONL

If you instead just **copy analytics JSONL files**, then keep the Parquet for DuckDB but copy JSONL like:

```bash
cp "${ENRICHED}/analytics/risk_factors.jsonl" "${DOC_OUT}/risk_factors.jsonl"
cp "${ENRICHED}/analytics/risk_hotspots.jsonl" "${DOC_OUT}/risk_hotspots.jsonl"
```

Either way, after `generate_documents.sh` runs, you will have:

* `Document Output/risk_factors.parquet` + `.jsonl`
* `Document Output/risk_hotspots.parquet` + `.jsonl`

consistent with the rest of the metadata outputs.

---

## 6. Documentation updates

Extend `README_METADATA.md` with new sections, following the style of `hotspots` and `typedness`.

### 6.1 Risk Factors (`risk_factors.*`)

Add under Analytics:

> **Risk Factors (`risk_factors.parquet` / `risk_factors.jsonl`)**
> **Purpose**: Per‑function composite risk score combining complexity, structural coupling, test coverage, typing, static diagnostics, and file‑level hotspot signals.
> **Origin**: `codeintel_rev.services.enrich.analytics.risk.compute_and_write_risk` after `function_metrics`, `function_types`, coverage, Hotspots, Typedness, and Static Diagnostics have been written.
> **Grain**: one row per callable GOID (`function_goid_h128`).
> **Key fields**:
>
> * `function_goid_h128`, `urn`, `rel_path`, `qualname`, `start_line`, `end_line`
> * raw metrics (`cyclomatic_complexity`, `fan_in`, `fan_out`, `coverage_ratio`, `param_typed_ratio`, `static_error_count`, `file_hotspot_score`, etc.)
> * normalized factor scores (`complexity_risk`, `coupling_risk`, `coverage_risk`, `typing_risk`, `static_diagnostics_risk`, `change_risk`)
> * `total_risk_score` in [0,1], `risk_bucket` (`low`/`medium`/`high`)
> * `top_reasons` (short textual explanations)

### 6.2 Risk Hotspots (`risk_hotspots.*`)

Add a section:

> **Risk Hotspots (`risk_hotspots.parquet` / `risk_hotspots.jsonl`)**
> **Purpose**: Per‑file rollup of function‑level risk, used to quickly identify “spicy” areas of the codebase for refactoring, testing, or type‑hinting.
> **Origin**: Same module (`analytics.risk`), aggregating `risk_factors` plus existing `hotspots`, `typedness`, `static_diagnostics`, and `modules`.
> **Grain**: one row per file (`rel_path`).
> **Key fields**:
>
> * `functions_total`, `high_risk_functions`, `max_function_risk`, `mean_function_risk`
> * `file_coverage_ratio`, `uncovered_functions`
> * `hotspot_score`, `commit_count`, `author_count`, `ast_complexity`
> * `file_typed_ratio`, `static_error_count`
> * `tags`, `owners`, `module`
> * `file_risk_score` in [0,1], `risk_bucket`
> * `top_risky_functions` (summary of the worst few callables in the file)

---

## 7. Sanity checks & tests (brief)

To keep this robust:

1. **Unit tests** for `_build_single_risk_row`:

   * Synthetic `function_metrics`/`function_types`/coverage rows where you can compute hand‑rolled risk factors and assert on:

     * risk contributions (e.g., untyped + uncovered ⇒ high coverage/typing risk),
     * bucket boundaries (e.g., known configuration yields “high”).

2. **Integration checks**:

   * Compare `risk_hotspots.file_risk_score` ordering with `hotspots.score` – they should correlate but not be identical.
   * Ensure every `function_goid_h128` present in `function_metrics` yields exactly one `risk_factors` row.
   * Verify that `risk_hotspots.rel_path` covers exactly the set of files in `risk_factors.rel_path`.

3. **DuckDB smoke test**:

   * After running `generate_documents.sh`, open DuckDB and confirm:

     ```sql
     SELECT COUNT(*) FROM read_parquet('Document Output/risk_factors.parquet');
     SELECT COUNT(*) FROM read_parquet('Document Output/risk_hotspots.parquet');
     ```

     both run and join cleanly with `goids` / `hotspots` as expected.

---

If you’d like, I can next:

* Tighten the risk factor formulas into a configurable YAML (so you can re‑weight factors without code changes), or
* Draft some DuckDB “starter queries” specifically for these risk tables (e.g., “top 50 high‑risk functions in API modules grouped by owner”).

# risk factor formula and DuckDB starter queries #

Let’s do both: first a concrete YAML config for the risk model, then a set of DuckDB starter queries that assume `goid_risk_factors` and `risk_hotspots` are wired into your catalog alongside the existing tables (`goids`, `hotspots`, `typedness`, `modules`, `static_diagnostics`, `function_metrics`, `function_types`, etc.).

---

## 1. Configurable YAML for risk factor formulas

### 1.1 Mental model

I’m assuming your risk builder already produces, or will produce, a per‑function row that looks roughly like this:

**Table**: `goid_risk_factors.*` (JSONL + Parquet)

**Grain**: one row per function GOID (`function_goid_h128`)

**Columns (raw metrics – from existing datasets)**

* `function_goid_h128`, `urn`, `repo`, `commit`, `rel_path`, `qualname`
* `cyclomatic_complexity`, `loc`, `max_nesting_depth`, etc. from `function_metrics.*`
* `file_hotspot_score` (joined from `hotspots.score` on `rel_path`)
* `typed_ratio` / `param_typed_ratio`, `fully_typed`, `partial_typed`, `untyped` from `function_types.*`
* `coverage_ratio` from `coverage_functions.*` (line / branch coverage per function)
* `diagnostic_error_count` from `static_diagnostics.total_errors` via `rel_path`
* `call_fan_in` (number of distinct callers, from `call_graph_edges.*` joined on `callee_goid_h128`)

**Columns (derived & normalized)**

* `f_complexity`, `f_size`, `f_churn`, `f_typedness`, `f_coverage`, `f_diagnostics`, `f_fan_in` — all normalized to [0, 1], “higher = riskier”
* `risk_score` ∈ [0, 1]
* `risk_bucket` ∈ {`low`, `medium`, `high`}
* `top_factors` – array of factor names contributing the most to `risk_score`

The **YAML config** controls:

* Which factors are active.
* How each factor normalizes its raw metric → [0, 1].
* How each factor is weighted.
* How the final `risk_score` and `risk_bucket` are computed.

The Python side just needs to:

1. Build a dict of raw metrics for each function, e.g.:

   ```python
   metrics = {
       "cyclomatic_complexity": 17,
       "loc": 120,
       "file_hotspot_score": 0.82,
       "typed_ratio": 0.2,
       "coverage_ratio": 0.35,
       "diagnostic_error_count": 5,
       "call_fan_in": 14,
   }
   ```

2. Feed that + global statistics (for quantiles/p95) into a `RiskModel` that is constructed from YAML.

Below is a **ready‑to‑use YAML file** that you can drop into e.g. `config/risk_model.yaml` and then wire into your `goid_risk_factors` builder.

---

### 1.2 `config/risk_model.yaml` (example)

```yaml
version: 1
model_id: function_risk_v1
entity_kind: function  # future: you can add a file-level model next to this

# How to interpret & combine factors overall
combination:
  method: weighted_sum          # currently only weighted_sum supported
  normalize_weights: true       # re-normalize active weights to sum to 1.0
  missing_factor_policy: renormalize  # ignore missing factors, renormalize weights
  bucket_edges:                 # thresholds on final risk_score
    low: 0.33
    medium: 0.66
    high: 1.0

# Optional global defaults used when factor-specific values are omitted
defaults:
  normalization:
    strategy: quantile          # or "min_max"
    q_low: 0.05                 # for quantile strategy
    q_high: 0.95
    min_value: 0.0              # used for min_max strategy
    max_value: null             # if null, use max observed
  epsilon: 1e-6                 # avoid division by zero

# Factor definitions:
# - name: logical identifier (used as column suffix f_<name> in goid_risk_factors)
# - metric: key into the raw metrics dict computed by the builder
# - direction: how to treat higher values
# - transform: how to normalize raw -> [0, 1]

factors:

  complexity:
    label: "Cyclomatic complexity"
    metric: cyclomatic_complexity
    direction: higher_is_riskier   # 1.0 = most complex
    weight: 0.22
    transform:
      kind: log1p_quantile         # y = normalize(log1p(x))
      q_low: 0.05
      q_high: 0.95
      clip_mode: hard              # hard/soft: soft can sigmoid instead
      epsilon: 1e-6

  size_loc:
    label: "Function size (LOC)"
    metric: loc
    direction: higher_is_riskier   # very long functions are risky
    weight: 0.08
    transform:
      kind: log1p_quantile
      q_low: 0.05
      q_high: 0.95

  churn:
    label: "Recent git churn / file hotspot"
    metric: file_hotspot_score     # derived from hotspots.score per rel_path
    direction: higher_is_riskier
    weight: 0.18
    transform:
      kind: linear                 # assume already 0..1-ish from hotspots
      min_value: 0.0
      max_value: 1.0
      clip_min: 0.0
      clip_max: 1.0

  typedness:
    label: "Type hint coverage"
    metric: typed_ratio            # 0.0 = untyped, 1.0 = fully typed
    direction: lower_is_riskier    # low typed_ratio => high risk
    weight: 0.12
    transform:
      kind: inverted_linear        # y = 1 - normalize(x)
      min_value: 0.0
      max_value: 1.0
      clip_min: 0.0
      clip_max: 1.0

  coverage:
    label: "Test coverage"
    metric: coverage_ratio         # 0.0 .. 1.0 for this function
    direction: lower_is_riskier
    weight: 0.18
    transform:
      kind: inverted_linear
      min_value: 0.0
      max_value: 1.0
      clip_min: 0.0
      clip_max: 1.0
      missing_as: 1.0              # treat missing coverage as 0% coverage => risk=1

  diagnostics:
    label: "Static analysis errors"
    metric: diagnostic_error_count # from static_diagnostics.total_errors joined by rel_path
    direction: higher_is_riskier
    weight: 0.10
    transform:
      kind: stepwise               # 0 errors => 0.0, 1-5 => 0.5, >5 => 1.0
      steps:
        - max_value: 0
          output: 0.0
        - max_value: 5
          output: 0.5
        - max_value: null          # null => infinity
          output: 1.0

  fan_in:
    label: "Call fan-in (number of callers)"
    metric: call_fan_in            # COUNT(DISTINCT caller_goid_h128)
    direction: higher_is_riskier   # heavily depended-on funcs are risky to change
    weight: 0.12
    transform:
      kind: log1p_quantile
      q_low: 0.05
      q_high: 0.95
      clip_mode: hard

  # Example of an optional "alert" factor: any extremely high metric
  extreme_complexity_guard:
    label: "Extreme complexity guardrail"
    metric: cyclomatic_complexity
    direction: higher_is_riskier
    weight: 0.0                     # 0-weight, used only for flags
    transform:
      kind: threshold_flag          # produces a boolean used to annotate top_factors
      threshold: 20                 # mark high-risk for c > 20
      output_if_below: 0.0
      output_if_above: 1.0
    flags:
      add_to_top_factors_if: 1.0
      label_override: "cyclomatic>20"
```

#### How the builder should interpret this

For each function:

1. Build `metrics: dict[str, float|int|None]` from joins over `function_metrics`, `hotspots`, `function_types`, `coverage_functions`, `static_diagnostics`, `call_graph_edges`.

2. For each `factor`:

   * Fetch raw `x = metrics[factor.metric]`.

   * Apply the `transform.kind`:

     * `linear`: `(x - min) / (max - min)`, then clamp.
     * `inverted_linear`: `1 - linear(x)`.
     * `log1p_quantile`:

       * Compute `y = log1p(x)`.
       * Compute global `q_low`, `q_high` over `log1p` across all functions, then map `y` into [0,1] using those.
     * `stepwise`: find the first `steps[i]` where `x <= max_value`, take `output`.
     * `threshold_flag`: output `output_if_below` vs `output_if_above`.

   * If `direction: lower_is_riskier` and transform did not already invert, just do `y = 1.0 - y`.

   * Store normalized value in e.g. `f_complexity`, `f_size_loc`, etc. in the row.

3. Combine:

   ```python
   active_factors = [f for f in cfg.factors if f.weight > 0]
   weights = np.array([f.weight for f in active_factors], dtype=float)
   if cfg.combination.normalize_weights:
       weights = weights / weights.sum()
   values = np.array([row[f"f_{f.name}"] for f in active_factors], dtype=float)
   risk_score = float((weights * values).sum())
   ```

4. Bucket:

   ```python
   if risk_score <= 0.33: risk_bucket = "low"
   elif risk_score <= 0.66: risk_bucket = "medium"
   else: risk_bucket = "high"
   ```

5. Derive `top_factors` as the factors with largest `weight * value` contributions (and add `extreme_complexity_guard` if its flag is 1.0).

Because **all numbers are in the YAML**, tweaking the model is:

* Changing weights.
* Changing transform kinds and parameters (e.g., tighten `coverage` to be harsher).
* Adding/removing factors.

No code changes required beyond the generic interpreter.

---

## 2. DuckDB starter queries for risk tables

These assume:

* `goid_risk_factors` is registered in DuckDB (e.g., via `analytics/goid_risk_factors.parquet` with a simple `CREATE TABLE` like other analytics tables).
* `risk_hotspots` exists as a file‑level aggregation of `goid_risk_factors` (grouped by `rel_path`) and is also in the catalog.
* `modules` is available with `module`, `path`, `tags` (LIST<VARCHAR>), `owners` (LIST<VARCHAR>).
* `hotspots` and `typedness` are in the catalog, as already described.

You can drop all of these into a `risk_queries.sql` file alongside your other starter queries.

---

### 2.1 Top 50 high-risk functions overall

```sql
-- A1. Top 50 highest-risk functions across the repo
SELECT
    r.urn,
    r.qualname,
    r.rel_path,
    r.risk_score,
    r.risk_bucket,
    r.cyclomatic_complexity,
    r.loc,
    r.coverage_ratio,
    r.typed_ratio,
    r.call_fan_in,
    r.file_hotspot_score
FROM goid_risk_factors AS r
ORDER BY r.risk_score DESC
LIMIT 50;
```

---

### 2.2 Top 50 high-risk functions in API modules, grouped by owner

This matches the example you mentioned.

```sql
-- A2. Top high-risk functions in API modules, grouped by owner
WITH api_functions AS (
    SELECT
        r.*,
        m.module AS module_path,
        owner
    FROM goid_risk_factors AS r
    JOIN modules AS m
      ON r.rel_path = m.path
    -- Unnest tags and owners so we can filter by tag and group by owner
    CROSS JOIN UNNEST(m.tags)   AS t(tag)
    CROSS JOIN UNNEST(m.owners) AS o(owner)
    WHERE t.tag = 'api'
)
SELECT
    owner,
    module_path,
    COUNT(*)                      AS function_count,
    AVG(risk_score)              AS avg_risk_score,
    MAX(risk_score)              AS max_risk_score,
    MAX(risk_bucket)             AS worst_bucket, -- assuming ordered ENUM or string
    AVG(coverage_ratio)          AS avg_coverage,
    AVG(typed_ratio)             AS avg_typed_ratio
FROM api_functions
GROUP BY owner, module_path
ORDER BY avg_risk_score DESC
LIMIT 50;
```

If you want the **individual functions** per owner:

```sql
-- A3. Per-owner, per-function details for the most risky API functions
SELECT
    owner,
    module_path,
    qualname,
    rel_path,
    risk_score,
    risk_bucket,
    cyclomatic_complexity,
    coverage_ratio,
    typed_ratio,
    call_fan_in,
    file_hotspot_score
FROM api_functions
ORDER BY risk_score DESC
LIMIT 200;
```

---

### 2.3 High-risk functions that are poorly tested (test gap candidates)

```sql
-- B1. High-risk functions with low or missing coverage
SELECT
    r.urn,
    r.qualname,
    r.rel_path,
    r.risk_score,
    r.risk_bucket,
    r.coverage_ratio,
    r.cyclomatic_complexity,
    r.file_hotspot_score,
    r.call_fan_in
FROM goid_risk_factors AS r
WHERE r.risk_bucket = 'high'
  AND (r.coverage_ratio IS NULL OR r.coverage_ratio < 0.5)
ORDER BY r.risk_score DESC, r.coverage_ratio ASC NULLS FIRST
LIMIT 100;
```

---

### 2.4 High-risk functions with static analysis issues and weak typing

```sql
-- B2. High-risk functions that also have static errors and poor typedness
SELECT
    r.urn,
    r.qualname,
    r.rel_path,
    r.risk_score,
    r.diagnostic_error_count,
    r.typed_ratio,
    r.coverage_ratio,
    r.cyclomatic_complexity,
    r.file_hotspot_score
FROM goid_risk_factors AS r
WHERE r.risk_bucket = 'high'
  AND r.diagnostic_error_count > 0
  AND (r.typed_ratio IS NULL OR r.typed_ratio < 0.5)
ORDER BY r.risk_score DESC, r.diagnostic_error_count DESC
LIMIT 100;
```

---

### 2.5 File-level risk hotspots (joining to existing hotspots & typedness)

Assuming `risk_hotspots` is precomputed as an aggregation like:

* `rel_path`
* `function_count`
* `high_risk_function_count`
* `avg_risk_score`
* `max_risk_score`

You can easily enrich it with hotspot & typedness info.

```sql
-- C1. File-level risk hotspots, enriched with churn and typedness
SELECT
    rh.rel_path,
    rh.function_count,
    rh.high_risk_function_count,
    rh.avg_risk_score,
    rh.max_risk_score,
    h.score          AS file_hotspot_score,
    h.commit_count,
    h.author_count,
    h.lines_added,
    h.lines_deleted,
    t.typed_ratio    AS file_typed_ratio
FROM risk_hotspots AS rh
LEFT JOIN hotspots  AS h ON rh.rel_path = h.rel_path
LEFT JOIN typedness AS t ON rh.rel_path = t.rel_path
ORDER BY rh.avg_risk_score DESC
LIMIT 100;
```

---

### 2.6 Owner-level risk by file

```sql
-- C2. Owner-level risk summary using file-level risk_hotspots + modules
WITH file_risk AS (
    SELECT
        rh.rel_path,
        rh.avg_risk_score,
        rh.max_risk_score,
        rh.function_count
    FROM risk_hotspots AS rh
),
file_with_owners AS (
    SELECT
        f.rel_path,
        f.avg_risk_score,
        f.max_risk_score,
        f.function_count,
        m.module AS module_path,
        owner
    FROM file_risk AS f
    JOIN modules AS m
      ON f.rel_path = m.path
    CROSS JOIN UNNEST(m.owners) AS o(owner)
)
SELECT
    owner,
    COUNT(DISTINCT rel_path)         AS file_count,
    SUM(function_count)              AS function_count,
    AVG(avg_risk_score)              AS avg_file_risk,
    MAX(max_risk_score)              AS worst_file_risk
FROM file_with_owners
GROUP BY owner
ORDER BY avg_file_risk DESC
LIMIT 50;
```

---

### 2.7 Risk distribution by tag (api / infra / ml / etc.)

Tags come from `modules.tags` and are set via `tags_index.yaml`.

```sql
-- D1. Risk distribution by semantic tag (api, infra, ml...)
WITH function_with_tags AS (
    SELECT
        r.*,
        m.module AS module_path,
        tag
    FROM goid_risk_factors AS r
    JOIN modules AS m
      ON r.rel_path = m.path
    CROSS JOIN UNNEST(m.tags) AS t(tag)
)
SELECT
    tag,
    COUNT(*)                    AS function_count,
    AVG(risk_score)             AS avg_risk,
    MAX(risk_score)             AS max_risk,
    SUM(CASE WHEN risk_bucket = 'high' THEN 1 ELSE 0 END) AS high_risk_count
FROM function_with_tags
GROUP BY tag
ORDER BY avg_risk DESC
LIMIT 50;
```

---

### 2.8 Outliers: “surprisingly risky” despite good tests & types

These are great candidates for deeper human review.

```sql
-- D2. Functions with high risk, *despite* good coverage and decent typedness
SELECT
    r.urn,
    r.qualname,
    r.rel_path,
    r.risk_score,
    r.cyclomatic_complexity,
    r.file_hotspot_score,
    r.typed_ratio,
    r.coverage_ratio,
    r.call_fan_in,
    r.diagnostic_error_count
FROM goid_risk_factors AS r
WHERE r.risk_score >= 0.75
  AND r.coverage_ratio >= 0.8
  AND (r.typed_ratio IS NULL OR r.typed_ratio >= 0.7)
ORDER BY r.risk_score DESC
LIMIT 100;
```

---

If you’d like, the next natural step is to:

* Sketch the tiny Python “interpreter” that reads `risk_model.yaml` and computes the `f_*` columns + `risk_score` / `risk_bucket` (it’s only ~150–200 lines), and
* Nail down a concrete schema for `goid_risk_factors.*` and `risk_hotspots.*` (similar level of detail to your other implementation plans) so all of these pieces are locked in and discoverable.


## python interpreter of risk score and concrete scheme for goid_risk_factors and risk_hotspots ##

Perfect, let’s lock this in.

Below I’ll do two things:

1. **Define a small “risk model interpreter”** that reads `risk_model.yaml`, computes the `f_*` feature columns, a `risk_score`, and a `risk_bucket`.
2. **Nail down concrete schemas** for `goid_risk_factors.*` and `risk_hotspots.*` in the same style as your existing metadata docs. 

I’ll assume the rest of the pipeline we already discussed (coverage, tests, function metrics, typedness, hotspots, static_diagnostics) is in place and that we’re feeding this interpreter a per‑GOID, already‑joined row of base metrics.

---

## 1. `risk_model.yaml` – concrete format

This is the configuration your interpreter will read. It’s intentionally simple: **each feature is “one base column + a named transform”**, then the score is a **weighted sum of features**, then **buckets** are assigned from score.

Example `risk_model.yaml` (drop-in v1):

```yaml
version: 1
model_id: "default_python_risk_v1"

defaults:
  missing_value: 0.0        # when an input metric is missing
  clamp_min: 0.0            # global clamp for all feature outputs
  clamp_max: 1.0

features:
  # File-level hotspot score joined onto each GOID by rel_path
  - id: "f_hotspot"
    source_column: "hotspot_score"       # from hotspots.score
    transform: "linear"
    params:
      src_min: 0.0
      src_max: 10.0                      # assume hotspots.score ~ [0, 10]

  # Cyclomatic complexity → ~[0,1] via log scale
  - id: "f_complexity"
    source_column: "cyclomatic_complexity"  # function_metrics.cyclomatic_complexity
    transform: "log1p"
    params:
      src_max: 50.0

  # Lower typed_ratio => higher risk
  - id: "f_untypedness"
    source_column: "typed_ratio"         # 0..1
    transform: "invert"

  # More static errors => higher risk
  - id: "f_static_errors"
    source_column: "total_errors"        # static_diagnostics.total_errors
    transform: "capped_linear"
    params:
      src_max: 20.0                      # 20+ errors all map to 1.0

  # Lower test coverage => higher risk
  - id: "f_low_coverage"
    source_column: "coverage_ratio"      # coverage_lines.covered_ratio, 0..1
    transform: "invert"

score:
  aggregate: "weighted_sum"
  weights:
    f_hotspot:       0.30
    f_complexity:    0.20
    f_untypedness:   0.20
    f_static_errors: 0.20
    f_low_coverage:  0.10

buckets:
  # First bucket whose min_score <= risk_score wins (ordered top→bottom)
  - id: "critical"
    min_score: 0.85
  - id: "high"
    min_score: 0.65
  - id: "medium"
    min_score: 0.40
  - id: "low"
    min_score: 0.0
```

You can tweak weights and thresholds without code changes; adding/removing features is still “code + config” work, which I think is the right trade‑off for now.

---

## 2. Python “interpreter” for `risk_model.yaml`

### 2.1. Where it lives

I’ll place this under your existing analytics namespace so it parallels `function_metrics` / `function_types`: 

```text
codeintel_rev/
  services/
    enrich/
      analytics/
        risk_model.py    # <-- new
```

This module is deliberately **self-contained** (no DuckDB/IO). It works on in‑memory dict rows:

* Input row: `Mapping[str, Any]` containing base metrics for a single GOID

  * e.g. `{"goid_h128": ..., "hotspot_score": 7.3, "cyclomatic_complexity": 23, ...}`
* Output row: original columns **plus**:

  * `f_*` feature columns
  * `risk_score`
  * `risk_bucket`
  * optional `risk_model_id` & `risk_model_version`

### 2.2. Implementation sketch (≈150–200 LOC, concrete)

```python
# codeintel_rev/services/enrich/analytics/risk_model.py

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, MutableMapping

import math

import yaml  # add PyYAML to your deps if not already present


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RiskDefaults:
    missing_value: float = 0.0
    clamp_min: float = 0.0
    clamp_max: float = 1.0


@dataclass(frozen=True)
class FeatureSpec:
    """Definition of a single f_* feature."""

    id: str                      # e.g. "f_hotspot"
    source_column: str           # e.g. "hotspot_score"
    transform: str = "identity"  # key into TRANSFORMS
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BucketSpec:
    """Risk bucket definition (e.g. low/medium/high/critical)."""

    id: str              # "low", "medium", "high", "critical"
    min_score: float     # inclusive lower bound (0..1)


@dataclass(frozen=True)
class ScoreSpec:
    """Score aggregation config."""

    aggregate: str                     # currently only "weighted_sum"
    weights: Dict[str, float]         # feature_id -> weight


@dataclass(frozen=True)
class RiskModel:
    """Fully parsed risk model configuration."""

    model_id: str
    version: int
    defaults: RiskDefaults
    features: Dict[str, FeatureSpec]
    score: ScoreSpec
    buckets: list[BucketSpec]


# ---------------------------------------------------------------------------
# Transform primitives
# ---------------------------------------------------------------------------

TransformFn = Callable[[float, Dict[str, Any], RiskDefaults], float]


def _clamp(x: float, defaults: RiskDefaults) -> float:
    return max(defaults.clamp_min, min(defaults.clamp_max, x))


def _identity(value: float, params: Dict[str, Any], defaults: RiskDefaults) -> float:
    return _clamp(value, defaults)


def _linear(value: float, params: Dict[str, Any], defaults: RiskDefaults) -> float:
    """
    Map [src_min, src_max] linearly into [clamp_min, clamp_max].
    Values outside range are clamped.
    """
    src_min = float(params.get("src_min", 0.0))
    src_max = float(params.get("src_max", 1.0))
    if src_max <= src_min:
        return _clamp(value, defaults)
    scaled = (value - src_min) / (src_max - src_min)
    return _clamp(scaled, defaults)


def _log1p(value: float, params: Dict[str, Any], defaults: RiskDefaults) -> float:
    """
    Log-scale a non-negative metric into [0, 1] using log1p(value)/log1p(src_max).
    Useful when the metric has a long tail (complexity, error counts).
    """
    value = max(value, 0.0)
    src_max = float(params.get("src_max", 10.0))
    if src_max <= 0:
        return _clamp(0.0, defaults)
    scaled = math.log1p(value) / math.log1p(src_max)
    return _clamp(scaled, defaults)


def _invert(value: float, params: Dict[str, Any], defaults: RiskDefaults) -> float:
    """
    Interpret input as a "good" ratio in [0,1] and turn it into a "badness" score.
    """
    return _clamp(1.0 - value, defaults)


def _capped_linear(
    value: float, params: Dict[str, Any], defaults: RiskDefaults
) -> float:
    """
    Piecewise:
      - 0       when value <= 0
      - 1       when value >= src_max
      - linear in-between
    """
    value = max(value, 0.0)
    src_max = float(params.get("src_max", 10.0))
    if src_max <= 0:
        return _clamp(1.0 if value > 0 else 0.0, defaults)
    scaled = min(value, src_max) / src_max
    return _clamp(scaled, defaults)


TRANSFORMS: Dict[str, TransformFn] = {
    "identity": _identity,
    "linear": _linear,
    "log1p": _log1p,
    "invert": _invert,
    "capped_linear": _capped_linear,
}


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def load_risk_model(path: str | Path) -> RiskModel:
    """Load and validate a RiskModel from risk_model.yaml."""
    raw = yaml.safe_load(Path(path).read_text())

    version = int(raw.get("version", 1))
    model_id = str(raw.get("model_id", "unnamed"))

    defaults = raw.get("defaults", {}) or {}
    defaults_obj = RiskDefaults(
        missing_value=float(defaults.get("missing_value", 0.0)),
        clamp_min=float(defaults.get("clamp_min", 0.0)),
        clamp_max=float(defaults.get("clamp_max", 1.0)),
    )

    features_raw = raw.get("features", []) or []
    features: Dict[str, FeatureSpec] = {}
    for entry in features_raw:
        fid = str(entry["id"])
        features[fid] = FeatureSpec(
            id=fid,
            source_column=str(entry["source_column"]),
            transform=str(entry.get("transform", "identity")),
            params=dict(entry.get("params", {}) or {}),
        )

    score_raw = raw.get("score", {}) or {}
    score = ScoreSpec(
        aggregate=str(score_raw.get("aggregate", "weighted_sum")),
        weights={str(k): float(v) for k, v in (score_raw.get("weights") or {}).items()},
    )

    buckets_raw = raw.get("buckets", []) or []
    buckets = [
        BucketSpec(id=str(b["id"]), min_score=float(b["min_score"]))
        for b in buckets_raw
    ]
    # sort descending so first match is highest bucket
    buckets.sort(key=lambda b: b.min_score, reverse=True)

    return RiskModel(
        model_id=model_id,
        version=version,
        defaults=defaults_obj,
        features=features,
        score=score,
        buckets=buckets,
    )


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def compute_features(row: Mapping[str, Any], model: RiskModel) -> Dict[str, float]:
    """Compute all f_* feature values for a single GOID row."""
    out: Dict[str, float] = {}
    for fid, spec in model.features.items():
        raw_val = row.get(spec.source_column)
        if raw_val is None:
            value = model.defaults.missing_value
        else:
            try:
                value = float(raw_val)
            except (TypeError, ValueError):
                value = model.defaults.missing_value

        transform = TRANSFORMS.get(spec.transform)
        if transform is None:
            raise KeyError(f"Unknown transform: {spec.transform!r}")

        out[fid] = transform(value, spec.params, model.defaults)
    return out


def compute_score(features: Mapping[str, float], model: RiskModel) -> float:
    """Combine feature scores into a single risk_score in [0,1]."""
    if model.score.aggregate != "weighted_sum":
        raise ValueError(f"Unsupported aggregate: {model.score.aggregate!r}")

    weights = model.score.weights
    total_weight = sum(weights.values()) or 1.0

    accum = 0.0
    for fid, weight in weights.items():
        if weight <= 0:
            continue
        val = features.get(fid, model.defaults.missing_value)
        accum += weight * val

    score = accum / total_weight
    return max(0.0, min(1.0, score))


def assign_bucket(score: float, model: RiskModel) -> str:
    """Pick the highest bucket whose min_score <= score."""
    for bucket in model.buckets:
        if score >= bucket.min_score:
            return bucket.id
    return "unbucketed"


def score_row(
    row: Mapping[str, Any],
    model: RiskModel,
    *,
    mutate: bool = False,
) -> MutableMapping[str, Any]:
    """
    Compute f_* features + risk_score + risk_bucket for one row.

    Parameters
    ----------
    row :
        Input mapping with base metrics (hotspot_score, typed_ratio, etc.).
    model :
        Parsed RiskModel.
    mutate :
        If True and row is mutable, update in-place. Otherwise, return a new dict.

    Returns
    -------
    MutableMapping[str, Any]
        Row with additional keys:
          - f_* for each feature.id
          - risk_score
          - risk_bucket
          - risk_model_id
          - risk_model_version
    """
    if mutate and isinstance(row, dict):
        out: MutableMapping[str, Any] = row
    else:
        out = dict(row)

    features = compute_features(row, model)
    score = compute_score(features, model)
    bucket = assign_bucket(score, model)

    out.update(features)
    out["risk_score"] = score
    out["risk_bucket"] = bucket
    out["risk_model_id"] = model.model_id
    out["risk_model_version"] = model.version

    return out


def score_rows(
    rows: Iterable[Mapping[str, Any]],
    model: RiskModel,
) -> Iterable[Dict[str, Any]]:
    """Convenience wrapper for batch scoring."""
    for row in rows:
        yield dict(score_row(row, model, mutate=False))
```

That’s the full interpreter:

* It knows nothing about GOIDs, DuckDB, or paths.
* It’s deterministic and small enough to test easily.
* All **risk semantics** (feature definitions, weights, bucket thresholds) live in `risk_model.yaml`.

You’ll wire this into the actual analytics pipeline (the part that joins coverage/tests/types/etc.) the same way you wired `function_metrics` and `function_types`. 

---

## 3. Concrete schemas: `goid_risk_factors.*` and `risk_hotspots.*`

These are the two new datasets that sit alongside `goids.*`, `hotspots.jsonl`, `typedness.jsonl`, etc. in your metadata universe.

### 3.1. GOID Risk Factors (`goid_risk_factors.*`)

**Purpose**
Per‑entity risk model outputs: **one row per GOID**, with the **f_*** feature values, the overall `risk_score`, and the assigned `risk_bucket`. This is the canonical table you join into everything else.

**Files**

* `enriched/analytics/goid_risk_factors.parquet`
* `Document Output/goid_risk_factors.jsonl` (via DuckDB `COPY`, same pattern as others). 

**Row grain**

* **One row per GOID (code entity)**

**Primary key**

* `goid_h128` (matches `goids.goid_h128`)

**Columns (core)**

| Column               | Type        | Description                                                         |
| -------------------- | ----------- | ------------------------------------------------------------------- |
| `goid_h128`          | decimal(38) | Stable GOID hash key. Join to `goids`/graphs.                       |
| `urn`                | string      | GOID URN (copied from `goids.urn` for convenience).                 |
| `repo`               | string      | Repository slug (from `goids.repo`).                                |
| `commit`             | string      | Commit SHA at analysis time.                                        |
| `rel_path`           | string      | Repo‑relative file path (from `goids.rel_path`).                    |
| `language`           | string      | Language tag (`python`).                                            |
| `kind`               | string      | Entity kind (`function`, `method`, `class`, etc.).                  |
| `qualname`           | string      | Dotted qualified name of the entity.                                |
| `risk_model_id`      | string      | ID from `risk_model.yaml.model_id`.                                 |
| `risk_model_version` | int         | Version from `risk_model.yaml.version`.                             |
| `risk_score`         | float       | Final normalized risk score in `[0,1]`.                             |
| `risk_bucket`        | string      | Bucket ID assigned by the model (`low`/`medium`/`high`/`critical`). |
| `rank_in_repo`       | int         | 1‑based rank when sorting all GOIDs by `risk_score` desc.           |
| `rank_percentile`    | float       | Percentile in `[0,100]` (e.g. 95.0 == top 5%).                      |
| `created_at`         | timestamp   | Row generation timestamp.                                           |

**Columns (feature outputs – `f_*`)**

These are the **feature IDs from `risk_model.yaml`**, materialized as numeric columns. For the example config above:

| Column            | Type  | Description                                                                          |
| ----------------- | ----- | ------------------------------------------------------------------------------------ |
| `f_hotspot`       | float | Risk‑scaled hotspot score (from `hotspots.score` after transform).                   |
| `f_complexity`    | float | Risk‑scaled cyclomatic complexity (`function_metrics.cyclomatic_complexity` → 0..1). |
| `f_untypedness`   | float | 1 − typedness ratio (higher == riskier).                                             |
| `f_static_errors` | float | Normalized static error count (0 errors → 0, ≥src_max → 1).                          |
| `f_low_coverage`  | float | 1 − coverage ratio for this GOID / its file.                                         |

You can extend this list with more `f_*` features over time; they’ll be added as new columns and wired via `risk_model.yaml`.

**Joins**

* `goids`
  `goid_risk_factors.goid_h128` ↔ `goids.goid_h128` (metadata, paths, line spans). 
* `call_graph_nodes` / `call_graph_edges`
  For fan-in/out + impact analysis. 
* `cfg_blocks`, `cfg_edges`, `dfg_edges`
  For control/data‑flow inspection of high‑risk entities.
* `hotspots`
  Via `rel_path` to inspect underlying churn metrics. 
* `typedness`, `function_metrics`, `function_types`, `coverage_*`, `static_diagnostics`, `test_*`
  For root‑cause analysis and more detailed feature breakdowns.

**Typical questions**

* “Show me the **top 50 riskiest functions** in the repo.”
* “Within `codeintel_rev/app/routes`, which entities are **critical** risk?”
* “For this GOID, **which factors** (f_*) are driving its high risk score?”

---

### 3.2. Risk Hotspots (`risk_hotspots.*`)

**Purpose**
A **filtered + denormalized view** of `goid_risk_factors` containing only entities above a configured risk threshold (e.g. `risk_bucket` ∈ {`high`, `critical`}), with a few convenience columns for “what should I fix first?” dashboards and LLM prompts.

Think of it as: “top N GOIDs by risk, with their key attributes”.

**Files**

* `enriched/analytics/risk_hotspots.parquet`
* `Document Output/risk_hotspots.jsonl`

**Row grain**

* **One row per high‑risk GOID** (e.g. `risk_bucket IN ('high', 'critical')`), optionally truncated to top N per repo.

**Primary key**

* `goid_h128` (within a `(repo, commit)` pair)

**Columns**

| Column                 | Type        | Description                                                         |
| ---------------------- | ----------- | ------------------------------------------------------------------- |
| `goid_h128`            | decimal(38) | GOID hash of the entity.                                            |
| `urn`                  | string      | GOID URN.                                                           |
| `repo`                 | string      | Repository slug.                                                    |
| `commit`               | string      | Commit SHA.                                                         |
| `rel_path`             | string      | Repo‑relative file path.                                            |
| `language`             | string      | Language tag.                                                       |
| `kind`                 | string      | Entity kind (`function`, `method`, etc.).                           |
| `qualname`             | string      | Qualified name.                                                     |
| `risk_model_id`        | string      | Risk model ID used.                                                 |
| `risk_model_version`   | int         | Risk model version.                                                 |
| `risk_score`           | float       | Normalized risk score in `[0,1]`.                                   |
| `risk_bucket`          | string      | Bucket ID (`high` / `critical`, by construction).                   |
| `rank_in_repo`         | int         | Rank among all GOIDs (same as in `goid_risk_factors`).              |
| `rank_in_file`         | int         | Rank within the same `rel_path` by `risk_score` desc.               |
| `rank_in_module`       | int         | Rank within the same module (from `modules.jsonl`).                 |
| `primary_driver_id`    | string      | `id` of the `f_*` feature with highest contribution.                |
| `primary_driver_value` | float       | Value of that feature (0..1).                                       |
| `drivers_json`         | json        | Small JSON map: `{feature_id: value}`, subset of the `f_*` columns. |
| `created_at`           | timestamp   | Generation time.                                                    |

You can compute `primary_driver_*` from:

* `f_*` values directly, or
* `f_* * weight` if you want “weighted contribution”.

**Joins**

* `goid_risk_factors`
  `risk_hotspots.goid_h128` ↔ `goid_risk_factors.goid_h128` (if you want the full `f_*` set).
* `goids` / `goid_crosswalk`
  For converting into file+line spans or SCIP symbols for navigation.
* `hotspots`, `typedness`, `coverage_*`, etc.
  For deeper drill‑down into why this GOID is risky.

**Typical questions**

* “Show me the **top 20 risk hotspots** in the whole repo, with a one‑line explanation.”
* “Within the `api` tagged modules, which functions are **critical risk** and why?” 
* “For each owner team, which 10 GOIDs should they fix first?”

---

## 4. How this plugs into the existing pipeline (high level)

You already have patterns for:

* **Exporting analytics tables** (`ast_metrics`, `hotspots`, `typedness`, etc.).
* **Per‑function exports** (`function_metrics`, `function_types`). 
* **Graph tables** with DuckDB registration & JSONL mirroring.

For `goid_risk_factors` / `risk_hotspots`, you’ll:

1. Build a **joined per‑GOID “base metrics” table** (via DuckDB or Python) with columns:

   * GOID identity (`goid_h128`, `urn`, `rel_path`, `qualname`, `kind`, `repo`, `commit`).
   * Base metrics: `hotspot_score`, `cyclomatic_complexity`, `typed_ratio`, `total_errors`, `coverage_ratio`, etc.
2. Feed each row through `risk_model.score_row(row, model)` to add:

   * `f_*` features
   * `risk_score`
   * `risk_bucket`
   * `risk_model_id` / `risk_model_version`
3. Rank globally & per module/file to fill `rank_*` fields.
4. Write:

   * `goid_risk_factors.parquet/jsonl` with **all GOIDs**.
   * `risk_hotspots.parquet/jsonl` as a filtered view (bucket high/critical, maybe top N).

The mechanics of steps 1/3/4 will mirror the `function_metrics` and `config_values` plans you already have.

---

If you’d like, the next natural evolution would be:

* A small `risk_model_runner.py` that:

  * Opens DuckDB,
  * Reads the required analytics tables,
  * Produces `goid_risk_factors` and `risk_hotspots` in one go, and
  * Wires into `generate_documents.sh` exactly like your other exports.

But the core “brain” of the system is now cleanly captured in this `risk_model.yaml` + interpreter + two schemas.


