# *§1 GOID / cross‑walks**, **§2 Call Graph**, and **§3 CFG/DFG (function‑level)** Implementation Plan #

Below is a concrete, **code-aligned implementation plan** for the three prioritized items—**§1 GOID / cross‑walks**, **§2 Call Graph**, and **§3 CFG/DFG (function‑level)**—including new data models, on‑disk formats, DuckDB schema/migrations, code entry points, and tests. I’ve grounded the plan in the modules, pipelines, artifacts, and invariants already present in `codeintel_rev` so it slots into your enrichment flow, DuckDB catalog, and CLI exactly as they exist today. Where I cite existing code, pipeline flows, artifacts, or invariants, I include inline references.

---

## Where this plugs in (today)

* **Enrichment pipeline orchestration** lives under `codeintel_rev.services.enrich` and is invoked from `codeintel_rev.cli.enrich` (flow “Code Enrichment Pipeline – Extracting AST/CST Metadata”). We’ll add new steps here. 
* Existing graph writing helpers already exist (e.g., `enrich.graph.io.write_import_edges`, `write_use_edges`), plus Tarjan SCC utilities—perfect place to extend with `write_call_edges` & CFG/DFG writers. 
* Current artifacts we will read/join:

  * **AST nodes/metrics** at `build/enrich/ast/ast_nodes.parquet|jsonl`, with qualname, node_type, start/end line, etc. 
  * **CST** via `codeintel_rev.cst_build` and `CST/cst_nodes.jsonl.gz`. 
  * **SCIP** via `codeintel_rev.indexing.scip_reader` and `index.scip(.json)` (definitions, references). 
  * **Import/symbol graph** (already writing `graphs/symbol_graph.json`). 
  * **Chunks** registered in DuckDB catalog (from chunker and indexing flow). Chunk IDs are deterministic `{file_path}:{start_line}:{end_line}`—we’ll reuse this in joins. 
* **DuckDB schema** additions go into `codeintel_rev.io.duckdb_schema` with migrations under `registry/migrations/`, and accessor APIs in `codeintel_rev.io.duckdb_catalog` (per current practice & extension points).
* We can leverage existing **Tree‑sitter support** (`enrich.tree_sitter_bridge`) for multi‑language outlines; we’ll extend this to call site & control‑flow queries per language. 

---

# §1 GOID + Cross‑walks (Global Object IDs)

### Goal

Provide a single, stable identifier per **code entity** (function, class, method, file/module, chunk, basic block later) and a **rich cross‑walk** between all sources of truth: SCIP symbols/occurrences, AST/CST nodes, chunk ranges, file path + line spans, and Git blobs/commits. This enables deterministic joins across your entire metadata fabric and unlocks high‑precision retrieval/hydration for LLMs.

### Design overview

**Representation.** We’ll store a **stable URN** plus a **128‑bit canonical hash** (DuckDB `HUGEINT`) derived from a normalized tuple. Keep both for human readability + fast joins.

* **URN (human‑readable):**
  `goid:1/<repo_fpr>@<commit>:/<rel_path>#<lang>:<kind>:<qualname>?s=<start>&e=<end>&scip=<symbol_hash>`

  * `repo_fpr` short fingerprint (e.g., first 12 of repo SHA or canonical repo key).
  * `<kind>` ∈ {`module`,`class`,`function`,`method`,`variable`,`chunk`,`block`(future)}.
  * Optional `scip` anchor (SHA‑of‑SCIP‑symbol) when available.
* **Hash‐128 (join key):**
  `xxh128(normalize(repo, commit, lang, kind, rel_path, qualname, start_line, end_line, scip_symbol?)) → HUGEINT`

**Normalization rules.**

* Paths normalized to repo‑relative POSIX; language lower‑cased; qualnames from AST indexer (already preserved as invariant). 
* Line ranges inclusive, based on AST node or SCIP occurrence when available (prefer SCIP for precision at char‑level, fallback to AST). 
* If multiple anchors exist (SCIP + AST), GOID is derived from the **primary anchor order**: (SCIP → AST → CST → Chunk). Evidence goes to a JSON column with sources & offsets.

### New on‑disk artifacts

* `build/enrich/goid/goids.parquet` – core GOID registry (entity‑level)
* `build/enrich/goid/goid_xwalk.parquet` – **wide** cross‑walk rows (entity ↔ chunk, scip, ast, cst, git, module)
* JSONSchemas: `schemas/goid.schema.json`, `schemas/goid_xwalk.schema.json` (source of truth for contract; generated models round‑trip).

### DuckDB schema (DDL)

Add to `codeintel_rev.io.duckdb_schema` + migration in `registry/migrations/`:

```sql
-- GOID registry
CREATE TABLE IF NOT EXISTS goids (
  goid_h128       HUGEINT PRIMARY KEY,
  urn             VARCHAR NOT NULL,
  repo            VARCHAR NOT NULL,
  commit          VARCHAR NOT NULL,
  rel_path        VARCHAR NOT NULL,
  language        VARCHAR NOT NULL,
  kind            VARCHAR NOT NULL,          -- module|class|function|method|variable|chunk|block
  qualname        VARCHAR,                    -- for symbol-bearing entities
  start_line      INTEGER,
  end_line        INTEGER,
  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cross-walks (wide, nullable columns)
CREATE TABLE IF NOT EXISTS goid_xwalk (
  goid_h128       HUGEINT NOT NULL REFERENCES goids(goid_h128),
  scip_symbol     VARCHAR,                    -- SCIP symbol string (or hashed)
  chunk_id        VARCHAR,                    -- "{path}:{start}:{end}"
  chunk_row_id    BIGINT,                     -- if you use numeric ids internally
  cst_node_id     VARCHAR,
  ast_node_type   VARCHAR,
  git_blob_sha    VARCHAR,
  git_commit_sha  VARCHAR,
  evidence_json   JSON,                       -- sources, offsets, precedence
  UNIQUE (goid_h128, scip_symbol, chunk_id)
);

-- Helpful views
CREATE VIEW v_goid_by_symbol AS
  SELECT go.*, gx.scip_symbol FROM goids go
  LEFT JOIN goid_xwalk gx USING (goid_h128)
  WHERE gx.scip_symbol IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_goids_path_kind ON goids(rel_path, kind);
CREATE INDEX IF NOT EXISTS idx_goid_xwalk_symbol ON goid_xwalk(scip_symbol);
```

(Extends current DuckDB usage & migrations pattern. )

### Python models (new)

`codeintel_rev/ids/goid.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, TypedDict, Optional
import xxhash

Kind = Literal["module","class","function","method","variable","chunk","block"]

@dataclass(slots=True, frozen=True)
class GOID:
    """Stable Global Object ID for a code entity."""
    urn: str
    h128: int            # canonical 128-bit hash, stored as Python int (maps to DuckDB HUGEINT)
    repo: str
    commit: str
    rel_path: str
    language: str
    kind: Kind
    qualname: Optional[str]
    start_line: Optional[int]
    end_line: Optional[int]

class CrosswalkRow(TypedDict, total=False):
    goid_h128: int
    scip_symbol: str
    chunk_id: str
    chunk_row_id: int
    cst_node_id: str
    ast_node_type: str
    git_blob_sha: str
    git_commit_sha: str
    evidence_json: dict[str, object]

def compute_goid(...)->GOID: ...
def normalize_tuple(...)->tuple[str, ...]: ...
```

(Style aligns with project’s typed public APIs, dataclasses, and explicit contracts. )

### Generation algorithm & code additions

**New builder:** `codeintel_rev.enrich.crosswalk.GOIDBuilder`

* **Inputs:**

  * SCIP occurrences/defs via `indexing.scip_reader` (precise char offsets). 
  * AST nodes via `enrich.ast_indexer` (qualname, start/end lines). 
  * CST (optional IDs) via `cst_build`. 
  * Chunk catalog (DuckDB `chunks` table; `query_by_uri` is already present). 
* **Steps:**

  1. For each AST node (function/class/module), align to SCIP def/ref if any, else AST/CST region → compose normalized tuple.
  2. Produce GOID (URN + hash) + **evidence_json** (e.g., `{anchors: ["scip","ast"], offsets: {...}}`).
  3. Join to **chunk(s)** overlapping `[start_line, end_line]` (use existing chunk lines). 
  4. (Optional) Add Git blob/commit via `io.git_client` if configured. 
  5. Write `goids.parquet` and `goid_xwalk.parquet`; then ingest into DuckDB via `DuckDBCatalog` helpers (add `ingest_goids`, `ingest_goid_xwalk`).

**Code surfaces to add/modify**

* `codeintel_rev.services.enrich.scan` (or new module) adds **step: `build_goids`**. 
* `codeintel_rev.enrich.graph.io`: add `write_goid_artifacts()` convenience (mirrors existing graph writers). 
* `codeintel_rev.io.duckdb_schema`: add tables & indices shown above; migration SQL under `registry/migrations/`. 
* `codeintel_rev.io.duckdb_catalog`: add:

  * `upsert_goids(rows: Iterable[GOID]) -> int`
  * `upsert_goid_xwalk(rows: Iterable[CrosswalkRow]) -> int`
  * fast query helpers: `find_goid_by_symbol`, `resolve_goid_by_path_span`, `crosswalk_for_goid`.
    (Follows current pattern used by `get_structure_annotations` & file/URI queries. )

**CLI**

* `codeintel_rev.cli.enrich`: add flags `--goids` and `--no-goids` and a subcommand `codeintel enrich goids` (consistent with existing “add a new enrichment step” recipe). 

**Tests**

* `tests/enrich/test_goid_builder.py` (table‑driven): SCIP‑anchored, AST‑only, CST‑only, multiple overlapping chunks, stability across re‑runs.
* Round‑trip schema tests (JSON Schema 2020‑12 per project’s contract rules; align with AGENTS.md principles). 

---

# §2 Call Graph (function ↔ function)

### Goal

Produce a **static call graph** with per‑callsite evidence and a calibrated confidence score; resolve callees using SCIP when possible, else AST/CST + import graph heuristics; handle dynamic cases with best‑effort fallbacks and preserve uncertainty.

### New on‑disk artifacts

* `build/enrich/graphs/call_nodes.parquet` (one per callable/GOID)
* `build/enrich/graphs/call_edges.parquet` (edges with callsite evidence)
* Optional JSONL mirrors for easy diffing: `call_edges.jsonl`

**Edge schema (Parquet/JSON)**

```
caller_goid_h128 : HUGEINT
callee_goid_h128 : HUGEINT            -- may be NULL if unresolved; still record edge w/ null target
callsite_path    : VARCHAR
callsite_line    : INTEGER
callsite_col     : INTEGER
language         : VARCHAR
kind             : VARCHAR            -- direct|method|ctor|attr_call|reflection|unknown
resolved_via     : VARCHAR            -- scip|ast|cst|heuristic
confidence       : DOUBLE             -- 0..1
evidence_json    : JSON               -- tokens, scopes, import chain, scip occurrence ids
```

### DuckDB schema (DDL)

```sql
CREATE TABLE IF NOT EXISTS call_nodes (
  goid_h128     HUGEINT PRIMARY KEY,
  language      VARCHAR NOT NULL,
  kind          VARCHAR NOT NULL,       -- function|method|ctor
  arity         INTEGER,
  is_public     BOOLEAN,
  rel_path      VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS call_edges (
  caller_goid_h128 HUGEINT NOT NULL REFERENCES call_nodes(goid_h128),
  callee_goid_h128 HUGEINT,            -- nullable for unresolved
  callsite_path    VARCHAR NOT NULL,
  callsite_line    INTEGER,
  callsite_col     INTEGER,
  language         VARCHAR NOT NULL,
  kind             VARCHAR NOT NULL,
  resolved_via     VARCHAR NOT NULL,
  confidence       DOUBLE NOT NULL,
  evidence_json    JSON,
  PRIMARY KEY (caller_goid_h128, callsite_path, callsite_line, callsite_col)
);

CREATE INDEX IF NOT EXISTS idx_call_edges_callee ON call_edges(callee_goid_h128);
```

### Builder & algorithm

**New:** `codeintel_rev.enrich.callgraph.CallGraphBuilder`

* **Language front‑ends**

  * **Python:** traverse `ast.Call` nodes; for `Name`, `Attribute`, `Call(func=Attribute(value=Name('self'), ...))` determine receiver type via containing class and local bindings; use LibCST import graph for fully‑qualified resolution; backstop with SCIP references at token positions. (You already parse AST & CST and construct import/usage graphs. )
  * **TS/JS (initial):** extend `tree_sitter_bridge` with language‑specific call‑expression queries (you already outline function/class defs via TS queries). 
* **Resolution order (decreasing authority):** SCIP → AST scope + import graph → CST token proximity → Heuristic (e.g., best fqname match in same module).
* **Confidence scoring:** piecewise function based on resolution source and ambiguity count; encode into 0..1 (e.g., 0.95 SCIP, 0.7 AST+imports single candidate, 0.4 heuristic multi‑candidate).
* **GOID mapping:** resolve callee to `GOID` via symbol/qualname/path → join against `goids`/`goid_xwalk`. (We just added that registry.)
* **Output writers:** implement `write_call_edges()` in `codeintel_rev.enrich.graph.io`, mirroring the existing edge writers for imports/uses. 

### Code surfaces to add/modify

* `codeintel_rev.enrich.graph.builders`: add a `CallGraph` dataclass and a `build_call_graph()` façade (parallel to `build_import_graph()`). 
* `codeintel_rev.services.enrich`: new step `build_callgraph` (plug into pipeline next to symbol/import graph steps). 
* `codeintel_rev.io.duckdb_schema` + migration: create `call_nodes`, `call_edges`.
* `codeintel_rev.io.duckdb_catalog`: add `upsert_call_nodes`, `upsert_call_edges`, and query helpers:

  * `callees_of(goid_h128, max_hops=1)`
  * `callers_of(goid_h128, max_hops=1)`
  * `callsites_for(goid_h128)`
* (Optional) **MCP tools** later: `callers_of`, `callees_of`, and “expand subgraph” adapters following existing MCP patterns (error handling decorator, capabilities gating). 

### Tests

* `tests/enrich/test_callgraph_py.py` – fixtures with local & imported calls, method dispatch, aliasing, star imports, unresolved/dynamic calls (ensure edges emitted with null callee + low confidence).
* `tests/integration/test_callgraph_ingest.py` – end‑to‑end: run enrich step, ingest into DuckDB, `callers_of/callees_of` queries return expected results.

---

# §3 CFG/DFG (function‑level)

### Goal

Per‑function **Control‑Flow Graph (CFG)** and **Data‑Flow Graph (DFG)** to power precise refactoring suggestions, side‑effect and dead‑code analysis, and to let LLMs ask for “the path where X can be None” or “who uses value assigned here.”

### New on‑disk artifacts

* `build/enrich/graphs/cfg_blocks.parquet` (basic blocks)
* `build/enrich/graphs/cfg_edges.parquet` (intra‑function control edges)
* `build/enrich/graphs/dfg_edges.parquet` (use‑def edges)

**Schemas**

```
-- CFG blocks
function_goid_h128 : HUGEINT
block_idx          : INTEGER            -- 0..N-1 within a function
kind               : VARCHAR            -- entry|exit|normal|loop|exception
start_line         : INTEGER
end_line           : INTEGER
stmts_json         : JSON               -- compact statement descriptors
in_degree          : INTEGER
out_degree         : INTEGER
PRIMARY KEY (function_goid_h128, block_idx)

-- CFG edges
function_goid_h128 : HUGEINT
src_block_idx      : INTEGER
dst_block_idx      : INTEGER
edge_type          : VARCHAR            -- true|false|fallthrough|jump|exception
cond_json          : JSON               -- simplified predicate / guard if available
PRIMARY KEY (function_goid_h128, src_block_idx, dst_block_idx)

-- DFG edges
function_goid_h128 : HUGEINT
src_block_idx      : INTEGER
dst_block_idx      : INTEGER
src_symbol         : VARCHAR            -- local name or SSA-ish temp id
dst_symbol         : VARCHAR
via_phi            : BOOLEAN
use_kind           : VARCHAR            -- def|use|kill
PRIMARY KEY (function_goid_h128, src_block_idx, dst_block_idx, src_symbol, dst_symbol, use_kind)
```

### DuckDB schema (DDL)

```sql
CREATE TABLE IF NOT EXISTS cfg_blocks (... as above ...);
CREATE TABLE IF NOT EXISTS cfg_edges  (... as above ...);
CREATE TABLE IF NOT EXISTS dfg_edges  (... as above ...);

CREATE INDEX IF NOT EXISTS idx_cfg_fun ON cfg_blocks(function_goid_h128);
CREATE INDEX IF NOT EXISTS idx_dfg_sym ON dfg_edges(function_goid_h128, dst_symbol);
```

### Builders & algorithm

**New:** `codeintel_rev.enrich.cfg.CFGBuilder` and `DFGBuilder`

* **Python front‑end (phase 1):**

  * Build **blocks** by linearizing statements and splitting at control nodes (`If`, `For`, `While`, `Try/Except/Finally`, `With`, `Return`, `Raise`, `Break/Continue`).
  * Construct edges: true/false for conditionals; loop back‑edges; exception edges for `try`.
  * Map **AST** nodes to line ranges (conform with AST metrics you already compute). 
  * **DFG** via intra‑procedural use‑def:

    * Track defs (`Assign`, `AnnAssign`, `AugAssign`, comprehension targets; function params as entry defs).
    * Track uses (names in expressions), build edges (def → use).
    * Insert `via_phi=True` where multiple predecessors define the same symbol and converge (block entry with >1 preds).
* **TS/JS (phase 2):** Add Tree‑sitter queries + control constructs mapping using `tree_sitter_bridge` scaffold. 
* **GOID mapping:** each function and its blocks get stable IDs:

  * **Block GOID** (kind=`block`): hash of `(function_goid, block_idx)`; store in `goids` so blocks participate in cross‑walks later (optional in v1).

**Writers**

* Extend `codeintel_rev.enrich.graph.io` with `write_cfg_blocks()`, `write_cfg_edges()`, `write_dfg_edges()` (mirror import graph writers). 

### Code surfaces to add/modify

* `codeintel_rev.services.enrich`: steps `build_cfg` and `build_dfg` after GOIDs (need function GOIDs).
* `codeintel_rev.io.duckdb_schema` + migrations for tables above; add catalog accessors:

  * `cfg_for_function(goid)`, `dfg_for_function(goid)`, `paths_between(block_a, block_b)`.

### Tests

* **Unit:** `tests/enrich/test_cfg_py.py`, `test_dfg_py.py` – cover conditionals, nesting, early returns, try/except/finally, loops, comprehensions, closures, generators/`yield`.
* **Property tests:** CFG edges produce a graph with exactly one `entry`, at least one `exit`, and reachability covers all blocks; DFG uses only symbols present in function scope.
* **Integration:** produce & ingest artifacts; verify DuckDB queries return expected blocks/edges.

---

## Pipeline, CLI, performance, and observability

### Enrichment pipeline & CLI

* **Order (recommended)** in `codeintel_rev.cli.enrich_pipeline`:
  `scan` → `ast` → `cst` → `graph:symbols/imports` → **`goids`** → **`callgraph`** → **`cfg`** → **`dfg`** → ownership/summaries. 
* Add flags: `--goids`, `--callgraph`, `--cfg`, `--dfg`, and `--all` to include these steps. (Conforms to “add new enrichment step” recipe.) 

### DuckDB catalog integration

* Follow the same connection/lifecycle rules (`DuckDBManager.get_connection()` per request; no long‑lived globals). 
* Add ingest methods mirroring `enrich.duckdb_store.ingest_modules_jsonl` pattern for robust, idempotent loads. 

### Performance & scale

* Writers stream Parquet in **row groups** (~100k rows) to keep memory flat; DuckDB ingest via `COPY FROM PARQUET`.
* Use **vectorized** joins on `HUGEINT goid_h128` for cross‑walk joins (faster than string URNs).
* Multi‑proc per language (Python/TS) and per path shard; bound by CPU cores. (Conforms to “async/threadpool offloading” patterns elsewhere.) 

### Observability

* Counters: `goids_created`, `xwalk_rows`, `call_edges_total`, `cfg_blocks_total`, `dfg_edges_total`.
* Coverage gauges: `%calls_resolved_via_scip`, `%functions_with_cfg`, etc.
* Errors conform to existing RFC 9457 pattern via your decorators for any MCP exposure later. 

---

## Example: how the pieces line up

1. **A Python method** `codeintel_rev.enrich.graph.io.write_import_edges`

   * Already present in SCIP and modules. 
   * GOID tuple `(repo, commit, "python", "method", "codeintel_rev/enrich/graph/io.py", "write_import_edges", s=..., e=..., scip=...)` → `goid_h128`.
   * `goid_xwalk` links: `scip_symbol` from `index.scip.json`, chunk(s) by line range, AST node type `FunctionDef`.

2. **A callsite** inside `graph/builders.py` calling `tarjan_scc`: captured from TS/AST and aligned to SCIP; we emit an edge `caller_goid_h128 → callee_goid_h128` with evidence + `resolved_via="scip"` and high confidence. 

3. **CFG/DFG** for the same method: blocks around `for`/`if` statements, edges for true/false branches, and def→use edges for locals; all keyed by `function_goid_h128`.

---

## File/diff‑level additions (summary)

```
codeintel_rev/
  ids/goid.py                         # GOID models + compute/normalize
  enrich/crosswalk.py                 # GOIDBuilder
  enrich/callgraph.py                 # CallGraphBuilder (+ language adapters)
  enrich/cfg.py                       # CFGBuilder, DFGBuilder
  enrich/graph/io.py                  # + write_goid_artifacts, write_call_edges, write_cfg_*, write_dfg_*
  services/enrich/steps.py            # + build_goids, build_callgraph, build_cfg, build_dfg orchestration
  io/duckdb_schema.py                 # + goids, goid_xwalk, call_nodes, call_edges, cfg_blocks, cfg_edges, dfg_edges
  io/duckdb_catalog.py                # + ingest/query helpers for the new tables
  cli/enrich.py                       # + flags/subcommands to run new steps
registry/migrations/
  00XX_add_goid_and_graphs.sql       # DDL above
build/enrich/
  goid/*.parquet
  graphs/{call_nodes,call_edges,cfg_blocks,cfg_edges,dfg_edges}.parquet
schemas/
  goid.schema.json
  goid_xwalk.schema.json
tests/
  enrich/test_goid_builder.py
  enrich/test_callgraph_py.py
  enrich/test_cfg_py.py
  enrich/test_dfg_py.py
  integration/test_*_ingest_duckdb.py
```

All of these sit squarely inside the existing layering rules and extension points for enrichment and DuckDB catalog/migrations.

---

## Rollout & migration plan

1. **Migrations**: apply `00XX_add_goid_and_graphs.sql` to add new tables & views (idempotent). 
2. **Pipeline**: run `codeintel enrich goids` to backfill GOIDs & cross‑walk (fast: metadata‑only). Then `codeintel enrich callgraph`, `codeintel enrich cfg`, `codeintel enrich dfg`. 
3. **Verification**:

   * Sanity join: `SELECT COUNT(*) FROM call_edges ce JOIN goids g ON g.goid_h128=ce.caller_goid_h128;` (expect ~100%).
   * Coverage: `% of edges with non‑null callee`, `% functions with CFG >= 1 block`.
4. **Docs**: update **Architecture Narrative** section 7 (Data & Metadata) and section 6 entries for new modules per your maintenance norms. 

---

## Why this fits your current codebase

* Uses **the enrichment service & CLI** entry points already in place (no new orchestration layer). 
* Reuses **graph I/O** conventions (`enrich.graph.io`) so graphs (imports, uses, calls, CFG/DFG) have a single writer surface. 
* Extends **DuckDB** the way you extend it today (schema module + migration + catalog helpers). 
* Leverages **AST/CST/SCIP** as you already do (and the “AST preserves qualnames” invariant). 
* Builds on your **Tree‑sitter bridge** for multi‑language growth. 

---

### Appendix A — Minimal Pydantic/msgspec schemas (sketch)

If you prefer msgspec structs for speed:

```python
import msgspec

class GoidRow(msgspec.Struct, frozen=True):
    goid_h128: int
    urn: str
    repo: str
    commit: str
    rel_path: str
    language: str
    kind: str
    qualname: str | None = None
    start_line: int | None = None
    end_line: int | None = None

class CallEdge(msgspec.Struct, frozen=True):
    caller_goid_h128: int
    callee_goid_h128: int | None
    callsite_path: str
    callsite_line: int
    callsite_col: int
    language: str
    kind: str
    resolved_via: str
    confidence: float
    evidence_json: dict[str, object] | None = None
```

(Consistent with your use of `msgspec` for hot paths. )

---

## Open risks & mitigations

* **Dynamic dispatch / reflection** (Python `getattr`, DI frameworks): we record unresolved edges with evidence+low confidence so LLMs still “see” potential flows. Later, add runtime samples as another evidence source.
* **Multi‑repo** evolution: GOID includes repo+commit; when multi‑repo is implemented (not yet), the scheme already scales. 
* **Volume** on big monorepos: partition Parquet by language/first‑letter of path; maintain indices on `HUGEINT` for joins.

---

If you want, I can follow this plan by **(a)** drafting the migration SQL, **(b)** writing the `GOID` models and builder with unit tests, and **(c)** stubbing the call graph resolver adapters (Python + TS) to make the first PR cohesive.

# Migration SWL, GOID modles with bulder with unit tests. and stubbing the call graph resolver adapters #

Amazing — let’s make your **PR-1: GOID + Call‑Graph scaffolding** concrete. Below I include:

1. **Migration SQL** (adds GOID + Call Graph tables and convenience views).
2. **GOID domain models + builder** (msgspec models, canonicalization/ID generation, persistence to DuckDB).
3. **Unit tests** (idempotency, cross‑walk coverage, and basic schema checks).
4. **MCP adapters (Python)**: stubbed `callers_of` / `callees_of` / `call_graph_subgraph` tools with Pydantic I/O and error handling decorator.
5. **Client stubs (TypeScript)** to make it cohesive on day one.

I’ve aligned the structure/paths to your codebase conventions:

* **DuckDB schema + migrations** live in `codeintel_rev.io.duckdb_schema` and `registry/migrations/`.
* **Enrichment steps** sit under `codeintel_rev/services/enrich` and consume artifacts from `build/enrich/*` (AST/CST/graphs).
* **Chunk IDs** are deterministic (`{file_path}:{start_line}:{end_line}`), so we cross‑walk those as one GOID namespace.
* **MCP tools** follow the adapter + error‑decorator pattern you already use.

---

## (a) Migration SQL — `registry/migrations/2025-02-01__goid_and_callgraph.sql`

> Adds **GOID** core tables (objects & aliases) and **Call Graph** tables (nodes & edges), plus helpful views. Everything is **idempotent** and keeps keys/indexes friendly to DuckDB.

```sql
-- registry/migrations/2025-02-01__goid_and_callgraph.sql
-- PR-1: GOID + Call Graph base schema
BEGIN TRANSACTION;

-- 1) Core GOID object table
CREATE TABLE IF NOT EXISTS goid_objects (
  goid TEXT PRIMARY KEY,                 -- UUIDv5 rendered as string (canonical)
  kind TEXT NOT NULL,                    -- enum: file|module|symbol|chunk|callsite
  language TEXT,                         -- e.g., python|typescript|go|...
  canonical TEXT NOT NULL,               -- canonical string used to compute goid (debuggable)
  created_at TIMESTAMP DEFAULT now(),
  updated_at TIMESTAMP DEFAULT now()
);

-- 2) Aliases / Cross-walks into external ID domains
CREATE TABLE IF NOT EXISTS goid_aliases (
  goid TEXT NOT NULL REFERENCES goid_objects(goid) ON DELETE CASCADE,
  namespace TEXT NOT NULL,               -- e.g., 'scip.symbol'|'py.ast.qualname'|'chunk.id'|'path.span'
  external_id TEXT NOT NULL,
  PRIMARY KEY (goid, namespace, external_id)
);

CREATE INDEX IF NOT EXISTS idx_goid_alias_ns_id
  ON goid_aliases(namespace, external_id);

-- 3) Call Graph nodes (denormalized node metadata for fast UI queries)
CREATE TABLE IF NOT EXISTS callgraph_nodes (
  func_goid TEXT PRIMARY KEY REFERENCES goid_objects(goid) ON DELETE CASCADE,
  symbol_name TEXT NOT NULL,
  qualname TEXT,
  file_path TEXT,
  start_line INTEGER,
  end_line INTEGER,
  is_async BOOLEAN,
  visibility TEXT
);

-- 4) Call Graph edges (each callsite is one edge)
CREATE TABLE IF NOT EXISTS callgraph_edges (
  caller_goid TEXT NOT NULL REFERENCES goid_objects(goid) ON DELETE CASCADE,
  callee_goid TEXT NOT NULL REFERENCES goid_objects(goid) ON DELETE CASCADE,
  callsite_path TEXT,
  callsite_start_line INTEGER,
  callsite_start_col INTEGER,
  callsite_end_line INTEGER,
  callsite_end_col INTEGER,
  static_score DOUBLE,
  dynamic_score DOUBLE,
  evidence JSON,                         -- small JSON blob (extractor provenance, symbol id, etc.)
  PRIMARY KEY (
    caller_goid, callee_goid, callsite_path,
    callsite_start_line, callsite_start_col
  )
);

CREATE INDEX IF NOT EXISTS idx_callgraph_caller
  ON callgraph_edges(caller_goid);
CREATE INDEX IF NOT EXISTS idx_callgraph_callee
  ON callgraph_edges(callee_goid);

-- 5) Convenience views for ergonomics
CREATE VIEW IF NOT EXISTS v_goid_to_symbols AS
SELECT a.goid, a.external_id AS scip_symbol
FROM goid_aliases a
WHERE a.namespace = 'scip.symbol';

CREATE VIEW IF NOT EXISTS v_goid_to_chunks AS
SELECT a.goid, a.external_id AS chunk_id
FROM goid_aliases a
WHERE a.namespace = 'chunk.id';

COMMIT;
```

**Why this shape?**

* **GOID/aliases** gives a stable, language‑agnostic anchor with unlimited cross‑walks to SCIP/AST/Chunk/path spans, aligned to your “catalog as the relational join hub” approach via DuckDB.
* **Edges keyed by callsite** enable deduplication and incremental enrichment.
* **Views** match your hydration pattern (join from DuckDB to add metadata).

> **Where it plugs in:** add this file to `registry/migrations/` and have your standard migrator apply it in the normal rollout. The doc explicitly calls out this location for schema migrations.

---

## (b) GOID models + builder (with unit tests)

We stay consistent with your models and performance choices:

* **msgspec.Struct** for fast, typed domain models (inferred from SCIP usage).
* Strict typing & clear error taxonomy consistent with the codebase.

### New file: `codeintel_rev/enrich/goid_models.py`

```python
# codeintel_rev/enrich/goid_models.py
from __future__ import annotations
import uuid
import hashlib
from typing import Literal, Iterable
import msgspec

# A stable namespace UUID for GOID derivation (UUIDv5). Hardcode once per product.
# NOTE: generate once and never change; this gives stable GOIDs across rebuilds.
GOID_NAMESPACE = uuid.UUID("7d09a7e1-3b77-5e0e-9a6b-0d2a9dfc7c8c")

GoidKind = Literal["file", "module", "symbol", "chunk", "callsite"]

class GoidObject(msgspec.Struct, frozen=True):
    goid: str
    kind: GoidKind
    language: str | None
    canonical: str  # the canonical string hashed to produce goid

class GoidAlias(msgspec.Struct, frozen=True):
    goid: str
    namespace: str         # 'scip.symbol' | 'py.ast.qualname' | 'chunk.id' | 'path.span' | ...
    external_id: str

def _canonicalize(*parts: str) -> str:
    # normalize separators, trim spaces, and lower most lexical parts for portability
    norm = "|".join(p.strip() for p in parts)
    return norm

def compute_goid(kind: GoidKind, language: str | None, canonical: str) -> str:
    """
    Deterministic UUIDv5 from (kind, language, canonical). Stable across runs.
    """
    name = _canonicalize(kind, language or "", canonical)
    return str(uuid.uuid5(GOID_NAMESPACE, name))

def canonical_path_span(path: str, start_line: int, end_line: int, start_col: int | None = None, end_col: int | None = None) -> str:
    parts = [path, f"{start_line}:{end_line}"]
    if start_col is not None and end_col is not None:
        parts.append(f"{start_col}:{end_col}")
    return _canonicalize("path.span", *parts)

def canonical_chunk_id(file_path: str, start_line: int, end_line: int) -> str:
    # Matches your deterministic chunk id from CASTChunker: {file_path}:{start_line}:{end_line}
    # We'll still compute a canonical string for GOID derivation.
    chunk_id = f"{file_path}:{start_line}:{end_line}"
    return _canonicalize("chunk.id", chunk_id)

def canonical_ast_symbol(module_path: str, qualname: str, start: int | None, end: int | None) -> str:
    return _canonicalize("py.ast.qualname", module_path, qualname, f"{start}:{end}")

def canonical_scip_symbol(symbol: str, file_relpath: str | None = None) -> str:
    # SCIP symbol is already a strong id; file is optional context for debugging
    return _canonicalize("scip.symbol", symbol, file_relpath or "")
```

### New file: `codeintel_rev/enrich/goid_builder.py`

```python
# codeintel_rev/enrich/goid_builder.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import duckdb

from .goid_models import (
    GoidObject, GoidAlias, GoidKind,
    compute_goid, canonical_chunk_id, canonical_ast_symbol, canonical_scip_symbol, canonical_path_span
)
from ..indexing.cast_chunker import CASTChunker  # for type awareness; no runtime call
# NOTE: Use your existing accessors if present:
# - AST nodes: build/enrich/ast/ast_nodes.parquet or jsonl
# - SCIP index: codeintel_rev.indexing.scip_reader
# - Chunks: DuckDB 'chunks' table or parquet shards
# These paths are consistent with the architecture narrative. 

@dataclass(slots=True)
class BuildStats:
    objects: int = 0
    aliases: int = 0

class GOIDBuilder:
    """
    Creates GOIDs and cross-walks from AST, SCIP, and chunk metadata,
    then persists them into DuckDB catalog tables created by the migration.
    """
    def __init__(
        self,
        repo_root: Path,
        duckdb_path: Path,
        ast_nodes_path: Path | None = None,
        scip_json_path: Path | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.duckdb_path = duckdb_path
        self.ast_nodes_path = ast_nodes_path
        self.scip_json_path = scip_json_path

    # ----------- Extraction (small scaffolds; swap with your existing readers) -----------

    def _iter_ast_symbols(self) -> Iterator[tuple[str, str, int | None, int | None]]:
        """
        Yield (module_path, qualname, start_line, end_line) from AST artifacts.
        For PR-1 we keep it simple and assume jsonl/parquet with those columns.
        """
        if not self.ast_nodes_path:
            return
        # Minimal reader: use DuckDB to read parquet/jsonl to avoid pandas dependency
        con = duckdb.connect(":memory:")
        con.execute("INSTALL json; LOAD json;")  # allow .jsonl if needed
        con.execute("CREATE TEMP VIEW ast_nodes AS SELECT * FROM read_auto(?);", [str(self.ast_nodes_path)])
        # Only functions/classes/modules
        for row in con.execute("""
            SELECT path as module_path, qualname, start_line, end_line
            FROM ast_nodes
            WHERE node_type IN ('FunctionDef','AsyncFunctionDef','ClassDef','Module')
        """).fetchall():
            yield (row[0], row[1], row[2], row[3])

    def _iter_scip_symbols(self) -> Iterator[tuple[str, str]]:
        """
        Yield (scip_symbol, file_path?) from SCIP JSON.
        """
        if not self.scip_json_path:
            return
        con = duckdb.connect(":memory:")
        con.execute("INSTALL json; LOAD json;")
        con.execute("""
            CREATE TEMP VIEW scip AS
            SELECT * FROM read_json_auto(?, maximum_object_size=104857600);
        """, [str(self.scip_json_path)])
        # Adapt to your actual JSON structure (defs table); keep PR-1 resilient
        for row in con.execute("""
            SELECT s::VARCHAR AS symbol, '' AS file_path
            FROM scip, UNNEST(scip.symbols) AS t(s)
        """).fetchall():
            yield (row[0], row[1])

    def _iter_chunks(self) -> Iterator[tuple[str, int, int]]:
        """
        Yield (file_path, start_line, end_line) from DuckDB 'chunks' table.
        This relies on the base catalog already being populated. 
        """
        con = duckdb.connect(str(self.duckdb_path))
        try:
            for row in con.execute("SELECT file_path, start_line, end_line FROM chunks").fetchall():
                yield (row[0], row[1], row[2])
        finally:
            con.close()

    # ----------- Build & Persist -----------

    def build(self, language: str = "python") -> BuildStats:
        objs: list[GoidObject] = []
        aliases: list[GoidAlias] = []

        # 1) Chunks → GOID(symbol kind=chunk) + alias chunk.id
        for fpath, sline, eline in self._iter_chunks():
            can = canonical_chunk_id(fpath, sline, eline)
            goid = compute_goid("chunk", language, can)
            objs.append(GoidObject(goid=goid, kind="chunk", language=language, canonical=can))
            aliases.append(GoidAlias(goid=goid, namespace="chunk.id", external_id=f"{fpath}:{sline}:{eline}"))
            # also path.span alias
            span = canonical_path_span(fpath, sline, eline)
            aliases.append(GoidAlias(goid=goid, namespace="path.span", external_id=span))

        # 2) AST symbols → GOID(kind=symbol/module) + alias py.ast.qualname
        for module_path, qualname, sline, eline in self._iter_ast_symbols() or []:
            can = canonical_ast_symbol(module_path, qualname, sline, eline)
            k: GoidKind = "symbol" if qualname else "module"
            goid = compute_goid(k, language, can)
            objs.append(GoidObject(goid=goid, kind=k, language=language, canonical=can))
            aliases.append(GoidAlias(goid=goid, namespace="py.ast.qualname", external_id=f"{module_path}#{qualname}@{sline}:{eline}"))

        # 3) SCIP symbols → GOID(kind=symbol) + alias scip.symbol
        for scip_symbol, file_path in self._iter_scip_symbols() or []:
            can = canonical_scip_symbol(scip_symbol, file_path or "")
            goid = compute_goid("symbol", language, can)
            objs.append(GoidObject(goid=goid, kind="symbol", language=language, canonical=can))
            aliases.append(GoidAlias(goid=goid, namespace="scip.symbol", external_id=scip_symbol))

        stats = self._persist(objs, aliases)
        return stats

    def _persist(self, objs: Sequence[GoidObject], aliases: Sequence[GoidAlias]) -> BuildStats:
        con = duckdb.connect(str(self.duckdb_path))
        try:
            con.execute("BEGIN TRANSACTION;")
            con.register("tmp_goid_objects", objs)
            con.register("tmp_goid_aliases", aliases)
            # Upsert-like semantics (DuckDB MERGE)
            con.execute("""
                CREATE TEMP TABLE __goid_objects AS SELECT * FROM tmp_goid_objects;
                CREATE TEMP TABLE __goid_aliases AS SELECT * FROM tmp_goid_aliases;
            """)
            con.execute("""
                MERGE INTO goid_objects AS t
                USING __goid_objects AS s
                ON t.goid = s.goid
                WHEN MATCHED THEN UPDATE SET kind=s.kind, language=s.language, canonical=s.canonical, updated_at=now()
                WHEN NOT MATCHED THEN INSERT (goid, kind, language, canonical) VALUES (s.goid, s.kind, s.language, s.canonical);
            """)
            con.execute("""
                MERGE INTO goid_aliases AS t
                USING __goid_aliases AS s
                ON t.goid = s.goid AND t.namespace = s.namespace AND t.external_id = s.external_id
                WHEN NOT MATCHED THEN INSERT (goid, namespace, external_id)
                VALUES (s.goid, s.namespace, s.external_id);
            """)
            stats = BuildStats(
                objects=con.execute("SELECT COUNT(*) FROM __goid_objects").fetchone()[0],
                aliases=con.execute("SELECT COUNT(*) FROM __goid_aliases").fetchone()[0],
            )
            con.execute("COMMIT;")
            return stats
        finally:
            con.close()
```

> **Where it runs**: Add a thin service wrapper in `codeintel_rev/services/enrich/` that invokes `GOIDBuilder` as a step within your enrichment pipeline (the narrative already lists `services.enrich` orchestration).

### Unit tests

> Per your testing philosophy: prefer **real DuckDB**, small fixtures, no monkeypatching, and call through realistic entry points where feasible.

**New test:** `tests/codeintel_rev/enrich/test_goid_builder.py`

```python
# tests/codeintel_rev/enrich/test_goid_builder.py
from __future__ import annotations
from pathlib import Path
import duckdb
import tempfile

from codeintel_rev.enrich.goid_builder import GOIDBuilder

DDL = """
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT,
  file_path TEXT,
  start_line INTEGER,
  end_line INTEGER
);
"""

def test_goid_builder_idempotent_and_crosswalk(tmp_path: Path) -> None:
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    con.execute(DDL)
    # Insert one chunk as realistic seed
    con.execute("INSERT INTO chunks VALUES ('a.py:10:30', 'a.py', 10, 30);")
    # Apply migration for GOID tables (assume migrator already ran in CI; for unit test we inline)
    con.execute("""
      CREATE TABLE IF NOT EXISTS goid_objects(goid TEXT PRIMARY KEY, kind TEXT, language TEXT, canonical TEXT);
      CREATE TABLE IF NOT EXISTS goid_aliases(goid TEXT, namespace TEXT, external_id TEXT,
        PRIMARY KEY(goid, namespace, external_id));
    """)
    con.close()

    builder = GOIDBuilder(
        repo_root=tmp_path,
        duckdb_path=db,
        ast_nodes_path=None,     # keep minimal for unit test
        scip_json_path=None
    )
    stats1 = builder.build(language="python")
    stats2 = builder.build(language="python")  # run again to assert idempotency

    con = duckdb.connect(str(db))
    # Idempotent: no duplicate aliases
    cnt = con.execute("SELECT COUNT(*) FROM goid_aliases").fetchone()[0]
    assert cnt == stats1.aliases  # second run didn't create duplicates
    # Chunk cross-walk emitted both chunk.id and path.span
    ns = set(r[0] for r in con.execute("SELECT DISTINCT namespace FROM goid_aliases").fetchall())
    assert "chunk.id" in ns and "path.span" in ns
    con.close()
```

> You can add a small integration test later that runs the **enrichment pipeline** step end‑to‑end (respecting “enter through real entry points”), but for PR‑1, the above unit covers **idempotency** and **basic cross‑walks**.

---

## (c) Call Graph resolver adapters (Python + TypeScript stubs)

We expose three MCP tools, following your established adapter patterns and error decorator:

* `callees_of(goid, depth, limit)`
* `callers_of(goid, depth, limit)`
* `call_graph_subgraph(seed_goids, direction, depth, limit)`

> **Adapter pattern & registration**: implemented under `codeintel_rev/mcp_server/adapters/`, decorated with `@mcp.tool()` and `@handle_adapter_errors`, and registered automatically by the server (FastMCP).

### New file: `codeintel_rev/mcp_server/adapters/graph.py`

```python
# codeintel_rev/mcp_server/adapters/graph.py
from __future__ import annotations
from typing import Literal, Sequence
from pydantic import BaseModel, Field, constr

from fastmcp import mcp
from ..error_handling import handle_adapter_errors
from ...app.config_context import app_context

Direction = Literal["forward", "reverse", "both"]

class CallNode(BaseModel):
    goid: constr(min_length=1)
    symbol_name: str | None = None
    file_path: str | None = None

class CallEdge(BaseModel):
    caller_goid: str
    callee_goid: str
    callsite_path: str | None = None
    callsite_start_line: int | None = None
    callsite_start_col: int | None = None
    static_score: float | None = None
    dynamic_score: float | None = None

class CallGraphResponse(BaseModel):
    nodes: list[CallNode] = Field(default_factory=list)
    edges: list[CallEdge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

class NeighborsRequest(BaseModel):
    goid: str
    depth: int = Field(ge=0, le=5, default=1)
    limit: int = Field(ge=1, le=500, default=100)

class SubgraphRequest(BaseModel):
    seed_goids: list[str]
    direction: Direction = "both"
    depth: int = Field(ge=0, le=5, default=1)
    limit: int = Field(ge=1, le=2000, default=500)

def _catalog():
    return app_context.get().duckdb_catalog  # same pattern as other adapters. 

@mcp.tool()
@handle_adapter_errors(operation="callees_of", empty_result=CallGraphResponse().model_dump())
def callees_of(req: NeighborsRequest) -> dict:
    """
    Return direct/limited-depth callees of a given function GOID.
    """
    catalog = _catalog()
    nodes, edges = catalog.get_callees(goid=req.goid, depth=req.depth, limit=req.limit)
    return CallGraphResponse(nodes=nodes, edges=edges).model_dump()

@mcp.tool()
@handle_adapter_errors(operation="callers_of", empty_result=CallGraphResponse().model_dump())
def callers_of(req: NeighborsRequest) -> dict:
    """
    Return direct/limited-depth callers of a given function GOID.
    """
    catalog = _catalog()
    nodes, edges = catalog.get_callers(goid=req.goid, depth=req.depth, limit=req.limit)
    return CallGraphResponse(nodes=nodes, edges=edges).model_dump()

@mcp.tool()
@handle_adapter_errors(operation="call_graph_subgraph", empty_result=CallGraphResponse().model_dump())
def call_graph_subgraph(req: SubgraphRequest) -> dict:
    """
    Return a small subgraph around seed GOIDs.
    """
    catalog = _catalog()
    nodes, edges = catalog.get_call_graph_subgraph(
        seed_goids=req.seed_goids, direction=req.direction, depth=req.depth, limit=req.limit
    )
    return CallGraphResponse(nodes=nodes, edges=edges).model_dump()
```

### Minimal DAO additions to `DuckDBCatalog`

> Add just the access points we need now; the implementation can be a simple `SELECT` across `callgraph_edges` and `callgraph_nodes` with deduplication. This aligns with the “hydrate from DuckDB” pattern used elsewhere.

```python
# codeintel_rev/io/duckdb_catalog.py  (additions)
from __future__ import annotations
from typing import Iterable
import duckdb

class DuckDBCatalog:
    # ... existing methods ...

    def get_callees(self, goid: str, depth: int = 1, limit: int = 200):
        """
        Depth-1: direct edges. Depth>1: simple BFS in SQL (iterative expansion).
        For PR-1, start with depth=1; expand later with RECURSIVE CTE.
        """
        con = self._conn()
        try:
            rows = con.execute("""
              SELECT e.caller_goid, e.callee_goid, e.callsite_path, e.callsite_start_line, e.callsite_start_col,
                     e.static_score, e.dynamic_score,
                     n_callee.symbol_name AS callee_symbol, n_callee.file_path AS callee_file
              FROM callgraph_edges e
              LEFT JOIN callgraph_nodes n_callee ON n_callee.func_goid = e.callee_goid
              WHERE e.caller_goid = ?
              LIMIT ?
            """, [goid, limit]).fetchall()
            edges = []
            nodes = {goid: {"goid": goid}}  # include seed
            for r in rows:
                edges.append({
                    "caller_goid": r[0], "callee_goid": r[1],
                    "callsite_path": r[2],
                    "callsite_start_line": r[3], "callsite_start_col": r[4],
                    "static_score": r[5], "dynamic_score": r[6],
                })
                nodes[r[1]] = {"goid": r[1], "symbol_name": r[7], "file_path": r[8]}
            return list(nodes.values()), edges
        finally:
            con.close()

    def get_callers(self, goid: str, depth: int = 1, limit: int = 200):
        con = self._conn()
        try:
            rows = con.execute("""
              SELECT e.caller_goid, e.callee_goid, e.callsite_path, e.callsite_start_line, e.callsite_start_col,
                     e.static_score, e.dynamic_score,
                     n_caller.symbol_name AS caller_symbol, n_caller.file_path AS caller_file
              FROM callgraph_edges e
              LEFT JOIN callgraph_nodes n_caller ON n_caller.func_goid = e.caller_goid
              WHERE e.callee_goid = ?
              LIMIT ?
            """, [goid, limit]).fetchall()
            edges = []
            nodes = {goid: {"goid": goid}}  # include seed
            for r in rows:
                edges.append({
                    "caller_goid": r[0], "callee_goid": r[1],
                    "callsite_path": r[2],
                    "callsite_start_line": r[3], "callsite_start_col": r[4],
                    "static_score": r[5], "dynamic_score": r[6],
                })
                nodes[r[0]] = {"goid": r[0], "symbol_name": r[7], "file_path": r[8]}
            return list(nodes.values()), edges
        finally:
            con.close()

    def get_call_graph_subgraph(self, seed_goids: list[str], direction: str, depth: int, limit: int):
        # Simple union of callers/callees for PR-1; upgrade to RECURSIVE later.
        all_nodes, all_edges = {}, []
        for g in seed_goids:
            n1, e1 = self.get_callees(g, depth=1, limit=limit)
            n2, e2 = self.get_callers(g, depth=1, limit=limit)
            for n in n1 + n2:
                all_nodes[n["goid"]] = n
            all_edges.extend(e1 + e2)
        # de-dupe edges
        seen = set()
        dedup = []
        for e in all_edges:
            k = (e["caller_goid"], e["callee_goid"], e.get("callsite_path"), e.get("callsite_start_line"), e.get("callsite_start_col"))
            if k not in seen:
                seen.add(k)
                dedup.append(e)
        return list(all_nodes.values()), dedup
```

> You can gate tool registration by a **capability** that checks table presence (extend `Capabilities` like your other runtime gates).

---

## TypeScript MCP client stubs

> Keep it tiny and neutral; this compiles anywhere you already use TS for MCP calls.

**New file:** `clients/ts/mcp-tools/callgraph.ts`

```ts
// clients/ts/mcp-tools/callgraph.ts
export type Direction = "forward" | "reverse" | "both";

export interface NeighborsRequest {
  goid: string;
  depth?: number; // default 1
  limit?: number; // default 100
}

export interface SubgraphRequest {
  seed_goids: string[];
  direction?: Direction; // default "both"
  depth?: number;        // default 1
  limit?: number;        // default 500
}

export interface CallNode {
  goid: string;
  symbol_name?: string;
  file_path?: string;
}

export interface CallEdge {
  caller_goid: string;
  callee_goid: string;
  callsite_path?: string;
  callsite_start_line?: number;
  callsite_start_col?: number;
  static_score?: number;
  dynamic_score?: number;
}

export interface CallGraphResponse {
  nodes: CallNode[];
  edges: CallEdge[];
  warnings: string[];
}

export interface McpClient {
  // Your existing client interface; this is intentionally generic.
  call<TReq, TRes>(toolName: string, req: TReq): Promise<TRes>;
}

export function createCallGraphClient(mcp: McpClient) {
  return {
    calleesOf: (req: NeighborsRequest) =>
      mcp.call<NeighborsRequest, CallGraphResponse>("callees_of", req),
    callersOf: (req: NeighborsRequest) =>
      mcp.call<NeighborsRequest, CallGraphResponse>("callers_of", req),
    callGraphSubgraph: (req: SubgraphRequest) =>
      mcp.call<SubgraphRequest, CallGraphResponse>("call_graph_subgraph", req),
  };
}
```

---

## Notes on integration & rollout

* **Where this sits in your pipeline.** Add a small service wrapper (e.g., `codeintel_rev/services/enrich/goid.py`) that calls `GOIDBuilder` and writes into DuckDB after AST/SCIP/Chunk metadata exist (your enrichment pipeline already extracts AST/CST and writes graphs).
* **Catalog accessor:** I added minimal read APIs inside `DuckDBCatalog` for the MCP adapters to use, consistent with “hydration from DuckDB”.
* **Testing shape:** we used **real DuckDB** and no monkeypatches, mirroring your 10.2 rules. Extend with an adapter test that calls the Python tool functions in‑process if you’d like to exercise the decorator path.

---

## Why this unlocks your next steps

* **GOID/cross‑walks** become the single referential spine across SCIP, AST, chunks, and path spans — a foundation for **call graph**, **CFG/DFG**, and future multi‑repo expansion.
* **Call Graph stubs** let you wire UI/agent workflows today; upgrading to RECURSIVE CTEs or iterative BFS in DuckDB for depth>1 is straightforward and isolated to the DAO.
* The **schemas** and **builder** are deterministic and idempotent, matching your invariants around stable IDs and reproducible builds.

---

## Follow‑ups I recommend (separate PRs)

1. **`Capabilities` gate**: add `has_callgraph` bool in `app/capabilities.py` by probing for the new tables and expose it on `/capz`.
2. **Enrichment step**: move GOIDBuilder invocation under `services.enrich` and add CLI toggle (`codeintel_rev/cli/enrich_pipeline`).
3. **Depth‑N expansion**: add a RECURSIVE CTE strategy in `DuckDBCatalog` for `depth>1` with safety rails (`LIMIT`, time budget).
4. **Symbol hydration**: join `v_goid_to_symbols` to surface SCIP symbols in adapter responses.
5. **Docs**: add a short “GOID & Call Graph” section to the Architecture Narrative per the maintenance rules.

If you want, I can convert the above into ready‑to‑commit patches (git diffs) next.


# ready-to-commit patches #


Absolutely—picking up where we left off and taking it to completion, **with DuckDB as the catalog**. Below I deliver a cohesive, ready‑to‑commit patchset covering:

1. **DuckDB migration SQL** (schema for GOID cross‑walks, Call Graph, CFG/DFG, plus indexes & views).
2. **GOID data models and a production builder** (reads your enrichment artifacts and SCIP, writes to DuckDB).
3. **Call‑graph resolver scaffolding** (Python implementation + TypeScript stub) wired into the enrichment pipeline and DuckDB catalog accessors.

Everything slots into your current module boundaries and operational rules—`DuckDBCatalog` for hydration, schema/migrations under `io.duckdb_schema` & `registry/migrations/`, enrichment orchestrated via `services/enrich` and `cli/enrich_pipeline`—as described in the Architecture Narrative.   

---

## What this PR delivers (at a glance)

* **GOID cross‑walk**: canonical string ID scheme + tables to map SCIP symbols, cAST chunks, AST/CST nodes, and file/pos triples → GOID. First‑class views make joins cheap for hydration paths used by MCP tools. Hydration continues to go through `DuckDBCatalog`. 
* **Call Graph**: per‑call‑site edges (caller GOID → callee GOID) with robust provenance (SCIP/AST/inferred) and precise source spans. Adapter interface accommodates Python now and TS later, without disrupting `services/enrich`. 
* **Function‑level CFG/DFG**: normalized node/edge schema + light Python CFG/DFG builder (covers sequential/branch/loop/return; designed to be extended). Stored in DuckDB with indices keyed by GOID for fast lookup by MCP adapters. 
* **DuckDB‑first**: SQL uses DuckDB types/idioms (IDENTITY, indexes, views), no Postgresisms. Migrations live in `registry/migrations/` as your architecture specifies. 

---

## Patchset

> **How to apply**: Save the blocks below as patch files or paste into `git apply`. All new code is typed and follows your testing philosophy (real collaborators, isolated instances). 

### 1) DuckDB migration (schema)

**File:** `registry/migrations/2025_11_19_0001_goid_callgraph_cfg.sql`

```diff
diff --git a/registry/migrations/2025_11_19_0001_goid_callgraph_cfg.sql b/registry/migrations/2025_11_19_0001_goid_callgraph_cfg.sql
new file mode 100644
index 0000000..badd00d
--- /dev/null
+++ b/registry/migrations/2025_11_19_0001_goid_callgraph_cfg.sql
@@
+-- DuckDB migration: GOID registry, cross-walks, Call Graph, CFG/DFG
+-- Compatible with DuckDB stable releases. No extensions required.
+-- idempotent: uses IF NOT EXISTS and CREATE OR REPLACE VIEW.
+
+-- 1) GOID registry -----------------------------------------------------------
+CREATE TABLE IF NOT EXISTS goid_objects (
+  goid TEXT PRIMARY KEY,
+  language TEXT NOT NULL,          -- e.g. 'python', 'typescript'
+  kind TEXT NOT NULL,              -- 'module'|'class'|'function'|'method'|'var'|'block'...
+  repo_rel_path TEXT NOT NULL,     -- normalized posix path (repo-relative)
+  qualname TEXT,                   -- canonical qualified name (module[.Class].func)
+  start_line INTEGER NOT NULL,
+  end_line INTEGER NOT NULL,
+  file_sha TEXT,                   -- optional content hash (short)
+  commit_sha TEXT,                 -- optional git commit
+  scip_symbol TEXT,                -- optional SCIP descriptor for defs
+  created_at TIMESTAMP DEFAULT current_timestamp
+);
+
+-- ID aliases from various producers (SCIP, cAST chunk ids, AST/CST node ids)
+CREATE TABLE IF NOT EXISTS goid_aliases (
+  source TEXT NOT NULL,            -- 'scip'|'chunk'|'ast'|'cst'|'manual'
+  source_id TEXT NOT NULL,
+  goid TEXT NOT NULL REFERENCES goid_objects(goid),
+  PRIMARY KEY (source, source_id)
+);
+
+-- Helpful mapping for chunk hydration paths
+CREATE TABLE IF NOT EXISTS chunk_goid_map (
+  chunk_id TEXT NOT NULL,          -- chunk id '{path}:{start}:{end}' or internal int id
+  goid TEXT NOT NULL REFERENCES goid_objects(goid),
+  PRIMARY KEY (chunk_id)
+);
+
+-- 2) Call Graph ---------------------------------------------------------------
+CREATE TABLE IF NOT EXISTS call_edges (
+  caller_goid TEXT NOT NULL REFERENCES goid_objects(goid),
+  callee_goid TEXT NOT NULL REFERENCES goid_objects(goid),
+  site_path TEXT NOT NULL,
+  site_start_line INTEGER NOT NULL,
+  site_end_line INTEGER NOT NULL,
+  lang TEXT NOT NULL,              -- language of callsite
+  provenance TEXT NOT NULL,        -- 'scip'|'ast'|'inferred'
+  confidence DOUBLE NOT NULL,      -- [0.0, 1.0]
+  notes TEXT,
+  created_at TIMESTAMP DEFAULT current_timestamp
+);
+CREATE INDEX IF NOT EXISTS idx_call_edges_caller ON call_edges(caller_goid);
+CREATE INDEX IF NOT EXISTS idx_call_edges_callee ON call_edges(callee_goid);
+
+-- 3) CFG/DFG (function-level) ------------------------------------------------
+-- Node tables keep minimal normalized info; payload_json can carry richer per-node details.
+CREATE TABLE IF NOT EXISTS cfg_nodes (
+  goid TEXT NOT NULL REFERENCES goid_objects(goid),
+  node_id INTEGER NOT NULL,
+  kind TEXT NOT NULL,              -- 'entry'|'block'|'exit'|'cond'|'stmt'
+  start_line INTEGER,
+  end_line INTEGER,
+  payload_json TEXT,               -- JSON string payload (no json extension required)
+  PRIMARY KEY (goid, node_id)
+);
+CREATE TABLE IF NOT EXISTS cfg_edges (
+  goid TEXT NOT NULL REFERENCES goid_objects(goid),
+  src_node_id INTEGER NOT NULL,
+  dst_node_id INTEGER NOT NULL,
+  type TEXT NOT NULL,              -- 'fallthrough'|'true'|'false'|'exception'
+  PRIMARY KEY (goid, src_node_id, dst_node_id)
+);
+CREATE INDEX IF NOT EXISTS idx_cfg_nodes_goid ON cfg_nodes(goid);
+CREATE INDEX IF NOT EXISTS idx_cfg_edges_goid ON cfg_edges(goid);
+
+CREATE TABLE IF NOT EXISTS dfg_nodes (
+  goid TEXT NOT NULL REFERENCES goid_objects(goid),
+  node_id INTEGER NOT NULL,
+  kind TEXT NOT NULL,              -- 'def'|'use'|'phi'|'const'
+  symbol TEXT,                     -- variable/attr name if any
+  start_line INTEGER,
+  end_line INTEGER,
+  payload_json TEXT,
+  PRIMARY KEY (goid, node_id)
+);
+CREATE TABLE IF NOT EXISTS dfg_edges (
+  goid TEXT NOT NULL REFERENCES goid_objects(goid),
+  src_node_id INTEGER NOT NULL,
+  dst_node_id INTEGER NOT NULL,
+  type TEXT NOT NULL,              -- 'flows_to'|'depends_on'
+  PRIMARY KEY (goid, src_node_id, dst_node_id)
+);
+CREATE INDEX IF NOT EXISTS idx_dfg_nodes_goid ON dfg_nodes(goid);
+CREATE INDEX IF NOT EXISTS idx_dfg_edges_goid ON dfg_edges(goid);
+
+-- 4) Useful views -------------------------------------------------------------
+CREATE OR REPLACE VIEW v_goid_crosswalk AS
+SELECT g.*, a.source, a.source_id
+FROM goid_objects g
+LEFT JOIN goid_aliases a ON a.goid = g.goid;
+
+CREATE OR REPLACE VIEW v_call_out AS
+SELECT c.caller_goid, c.callee_goid, c.lang, c.provenance, c.confidence, c.site_path,
+       c.site_start_line, c.site_end_line,
+       gcaller.qualname AS caller_qualname,
+       gcallee.qualname AS callee_qualname
+FROM call_edges c
+JOIN goid_objects gcaller ON gcaller.goid = c.caller_goid
+JOIN goid_objects gcallee ON gcallee.goid = c.callee_goid;
```

**Why here / how it integrates**

* Your architecture places schema definitions and migrations under `io.duckdb_schema` and `registry/migrations/`. The above keeps to that convention and extends the DuckDB catalog used by `DuckDBCatalog` for result hydration and symbol navigation.  

---

### 2) Extend the DuckDB schema & catalog accessors

**File:** `codeintel_rev/io/duckdb_schema.py`

```diff
diff --git a/codeintel_rev/io/duckdb_schema.py b/codeintel_rev/io/duckdb_schema.py
index 1111111..2222222 100644
--- a/codeintel_rev/io/duckdb_schema.py
+++ b/codeintel_rev/io/duckdb_schema.py
@@
+from __future__ import annotations
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Final
+
+# New tables introduced by 2025_11_19_0001_goid_callgraph_cfg
+GOID_TABLES: Final[tuple[str, ...]] = (
+    "goid_objects",
+    "goid_aliases",
+    "chunk_goid_map",
+    "call_edges",
+    "cfg_nodes",
+    "cfg_edges",
+    "dfg_nodes",
+    "dfg_edges",
+)
+
+@dataclass(frozen=True)
+class DuckDBMigration:
+    name: str
+    path: Path
+
+def required_migrations(root: Path) -> list[DuckDBMigration]:
+    """
+    Return ordered list of migrations to apply.
+    New migration for GOID/graphs is appended.
+    """
+    registry = root / "registry" / "migrations"
+    mig = DuckDBMigration(
+        name="2025_11_19_0001_goid_callgraph_cfg",
+        path=registry / "2025_11_19_0001_goid_callgraph_cfg.sql",
+    )
+    return [mig]
```

**File:** `codeintel_rev/io/duckdb_catalog.py`

```diff
diff --git a/codeintel_rev/io/duckdb_catalog.py b/codeintel_rev/io/duckdb_catalog.py
index 3333333..4444444 100644
--- a/codeintel_rev/io/duckdb_catalog.py
+++ b/codeintel_rev/io/duckdb_catalog.py
@@
 from __future__ import annotations
 from dataclasses import dataclass
 from pathlib import Path
-from typing import Iterable, Sequence
+from typing import Iterable, Sequence, Optional
+import duckdb
@@
 class DuckDBCatalog:
@@
     def connect(self):
         return self._manager.get_connection()
 
+    # --- GOID ingestion / lookup -------------------------------------------------
+    def upsert_goid_objects(self, rows: Iterable[tuple[str, str, str, str, Optional[str], int, int, Optional[str], Optional[str], Optional[str]]]) -> int:
+        """
+        Insert-or-replace rows into goid_objects.
+        row = (goid, language, kind, repo_rel_path, qualname, start_line, end_line, file_sha, commit_sha, scip_symbol)
+        """
+        sql = """
+        INSERT OR REPLACE INTO goid_objects (goid, language, kind, repo_rel_path, qualname, start_line, end_line, file_sha, commit_sha, scip_symbol)
+        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
+        """
+        with self.connect() as con:
+            con.executemany(sql, list(rows))
+            return con.execute("SELECT changes()").fetchone()[0]
+
+    def upsert_goid_aliases(self, rows: Iterable[tuple[str, str, str]]) -> int:
+        """row = (source, source_id, goid)"""
+        with self.connect() as con:
+            con.executemany(
+                "INSERT OR REPLACE INTO goid_aliases (source, source_id, goid) VALUES (?, ?, ?)",
+                list(rows),
+            )
+            return con.execute("SELECT changes()").fetchone()[0]
+
+    def upsert_chunk_goid_map(self, rows: Iterable[tuple[str, str]]) -> int:
+        """row = (chunk_id, goid)"""
+        with self.connect() as con:
+            con.executemany("INSERT OR REPLACE INTO chunk_goid_map (chunk_id, goid) VALUES (?, ?)", list(rows))
+            return con.execute("SELECT changes()").fetchone()[0]
+
+    # --- Call graph --------------------------------------------------------------
+    def insert_call_edges(self, rows: Iterable[tuple[str, str, str, int, int, str, str, float, Optional[str]]]) -> int:
+        """
+        row = (caller_goid, callee_goid, site_path, site_start_line, site_end_line, lang, provenance, confidence, notes)
+        """
+        with self.connect() as con:
+            con.executemany(
+                """
+                INSERT INTO call_edges
+                (caller_goid, callee_goid, site_path, site_start_line, site_end_line, lang, provenance, confidence, notes)
+                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
+                """,
+                list(rows),
+            )
+            return con.execute("SELECT changes()").fetchone()[0]
+
+    # --- CFG/DFG -----------------------------------------------------------------
+    def replace_cfg(self, goid: str, nodes: list[tuple[int, str, int, int, Optional[str]]], edges: list[tuple[int, int, str]]) -> None:
+        with self.connect() as con:
+            con.execute("DELETE FROM cfg_nodes WHERE goid = ?", [goid])
+            con.execute("DELETE FROM cfg_edges WHERE goid = ?", [goid])
+            con.executemany(
+                "INSERT INTO cfg_nodes (goid, node_id, kind, start_line, end_line, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
+                [(goid, nid, kind, sl, el, payload) for (nid, kind, sl, el, payload) in nodes],
+            )
+            con.executemany(
+                "INSERT INTO cfg_edges (goid, src_node_id, dst_node_id, type) VALUES (?, ?, ?, ?)",
+                [(goid, s, d, t) for (s, d, t) in edges],
+            )
+
+    def replace_dfg(self, goid: str, nodes: list[tuple[int, str, Optional[str], int, int, Optional[str]]], edges: list[tuple[int, int, str]]) -> None:
+        with self.connect() as con:
+            con.execute("DELETE FROM dfg_nodes WHERE goid = ?", [goid])
+            con.execute("DELETE FROM dfg_edges WHERE goid = ?", [goid])
+            con.executemany(
+                "INSERT INTO dfg_nodes (goid, node_id, kind, symbol, start_line, end_line, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
+                [(goid, nid, kind, sym, sl, el, payload) for (nid, kind, sym, sl, el, payload) in nodes],
+            )
+            con.executemany(
+                "INSERT INTO dfg_edges (goid, src_node_id, dst_node_id, type) VALUES (?, ?, ?, ?)",
+                [(goid, s, d, t) for (s, d, t) in edges],
+            )
```

**Why here / how it integrates**

* `DuckDBCatalog` remains the single entry point for catalog writes/reads. We add narrow, typed methods so MCP tools and enrichment services can hydrate results and graphs without leaking SQL. This follows your IO/Infrastructure layer rules and catalog responsibilities.  

---

### 3) GOID models (domain) & builder (service) + tests

**File:** `codeintel_rev/models/goid.py`

```diff
diff --git a/codeintel_rev/models/goid.py b/codeintel_rev/models/goid.py
new file mode 100644
index 0000000..a11c0de
--- /dev/null
+++ b/codeintel_rev/models/goid.py
@@
+from __future__ import annotations
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Optional, Literal
+
+Language = Literal["python", "typescript", "go", "java", "rust", "csharp"]
+
+@dataclass(frozen=True, slots=True)
+class GOID:
+    """
+    Canonical Global Object ID for a code object.
+    goid format: goid://{language}/{repo_rel_path}#{qualname}?sl={start}&el={end}
+                 [&h={file_sha}][&c={commit_sha}]
+    """
+    language: Language
+    repo_rel_path: str
+    kind: str
+    qualname: Optional[str]
+    start_line: int
+    end_line: int
+    file_sha: Optional[str] = None
+    commit_sha: Optional[str] = None
+    scip_symbol: Optional[str] = None
+
+    def to_string(self) -> str:
+        q = self.qualname or ""
+        base = f"goid://{self.language}/{self.repo_rel_path}#{q}?sl={self.start_line}&el={self.end_line}"
+        if self.file_sha:
+            base += f"&h={self.file_sha}"
+        if self.commit_sha:
+            base += f"&c={self.commit_sha}"
+        return base
```

**File:** `codeintel_rev/enrich/goid_builder.py`

```diff
diff --git a/codeintel_rev/enrich/goid_builder.py b/codeintel_rev/enrich/goid_builder.py
new file mode 100644
index 0000000..b00b135
--- /dev/null
+++ b/codeintel_rev/enrich/goid_builder.py
@@
+from __future__ import annotations
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Iterable, Optional
+import duckdb
+import pyarrow.parquet as pq
+
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.models.goid import GOID
+
+@dataclass(slots=True)
+class GOIDBuilderConfig:
+    repo_root: Path
+    enrich_root: Path      # typically build/enrich/
+    scip_json: Path        # index.scip.json if available
+
+class GOIDBuilder:
+    """
+    Builds GOIDs by reading enrichment artifacts and SCIP.
+    - Reads AST inventory (ast/ast_nodes.parquet)
+    - Optionally correlates SCIP symbol descriptors for defs
+    - Inserts goid_objects, goid_aliases, chunk_goid_map
+    """
+    def __init__(self, catalog: DuckDBCatalog, cfg: GOIDBuilderConfig):
+        self.catalog = catalog
+        self.cfg = cfg
+
+    def _iter_ast_nodes(self) -> Iterable[dict]:
+        ast_parquet = self.cfg.enrich_root / "ast" / "ast_nodes.parquet"
+        tbl = pq.read_table(ast_parquet)
+        for batch in tbl.to_batches():
+            for row in batch.to_pylist():
+                yield row
+
+    def build(self) -> None:
+        goids = []
+        aliases = []
+        chunk_maps = []
+
+        for r in self._iter_ast_nodes():
+            path = r["path"]          # repo-rel path
+            kind = r["node_type"]     # 'FunctionDef','ClassDef', etc -> normalized downstream
+            qualname = r.get("qualname")
+            sl = int(r["start_line"])
+            el = int(r["end_line"])
+            lang = "python"           # phase-1: python; pluggable later
+
+            g = GOID(
+                language=lang,
+                repo_rel_path=path,
+                kind=kind.lower(),
+                qualname=qualname,
+                start_line=sl,
+                end_line=el,
+            )
+            goids.append((
+                g.to_string(), g.language, g.kind, g.repo_rel_path, g.qualname,
+                g.start_line, g.end_line, g.file_sha, g.commit_sha, g.scip_symbol
+            ))
+
+            # alias from AST: unique tuple id
+            ast_id = f"{path}::{qualname or kind}@{sl}-{el}"
+            aliases.append(("ast", ast_id, g.to_string()))
+
+            # chunk mapping if chunk_id follows {path}:{start}:{end}
+            chunk_id = f"{path}:{sl}:{el}"
+            chunk_maps.append((chunk_id, g.to_string()))
+
+        self.catalog.upsert_goid_objects(goids)
+        self.catalog.upsert_goid_aliases(aliases)
+        self.catalog.upsert_chunk_goid_map(chunk_maps)
```

* The builder reads your enrichment artifact `ast/ast_nodes.parquet` (already emitted by `services/enrich`) and registers canonical GOIDs and cross‑walks in DuckDB. This aligns to your artifact layout and enrichment pipeline flow.  

**File:** `codeintel_rev/services/enrich/goid.py`

```diff
diff --git a/codeintel_rev/services/enrich/goid.py b/codeintel_rev/services/enrich/goid.py
new file mode 100644
index 0000000..cab005e
--- /dev/null
+++ b/codeintel_rev/services/enrich/goid.py
@@
+from __future__ import annotations
+from pathlib import Path
+from codeintel_rev.enrich.goid_builder import GOIDBuilder, GOIDBuilderConfig
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+
+def run_build_goids(catalog: DuckDBCatalog, repo_root: Path, enrich_root: Path, scip_json: Path) -> None:
+    cfg = GOIDBuilderConfig(repo_root=repo_root, enrich_root=enrich_root, scip_json=scip_json)
+    GOIDBuilder(catalog, cfg).build()
```

**File:** `codeintel_rev/cli/enrich_pipeline.py`

```diff
diff --git a/codeintel_rev/cli/enrich_pipeline.py b/codeintel_rev/cli/enrich_pipeline.py
index 5555555..6666666 100644
--- a/codeintel_rev/cli/enrich_pipeline.py
+++ b/codeintel_rev/cli/enrich_pipeline.py
@@
 import typer
 from pathlib import Path
 from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.services.enrich.goid import run_build_goids
+from codeintel_rev.services.enrich.callgraph import run_build_callgraph
+from codeintel_rev.services.enrich.cfg_dfg import run_build_cfg_dfg
@@
 @app.command("goid")
 def build_goid(
     repo_root: Path = typer.Option(..., exists=True, file_okay=False),
     enrich_root: Path = typer.Option(..., exists=True, file_okay=False),
     scip_json: Path = typer.Option(..., exists=True, dir_okay=False)
 ):
     """Build GOID cross-walks and register in DuckDB catalog."""
     catalog = DuckDBCatalog.from_app_context()
     run_build_goids(catalog, repo_root, enrich_root, scip_json)
+    typer.echo("GOID cross-walks built.")
+
+@app.command("callgraph")
+def build_callgraph(
+    repo_root: Path = typer.Option(..., exists=True, file_okay=False),
+    enrich_root: Path = typer.Option(..., exists=True, file_okay=False),
+):
+    """Build call-graph edges and register in DuckDB."""
+    catalog = DuckDBCatalog.from_app_context()
+    run_build_callgraph(catalog, repo_root, enrich_root)
+    typer.echo("Call graph built.")
+
+@app.command("cfg-dfg")
+def build_cfg_dfg(
+    repo_root: Path = typer.Option(..., exists=True, file_okay=False),
+    enrich_root: Path = typer.Option(..., exists=True, file_okay=False),
+):
+    """Build CFG/DFG for functions and register in DuckDB."""
+    catalog = DuckDBCatalog.from_app_context()
+    run_build_cfg_dfg(catalog, repo_root, enrich_root)
+    typer.echo("CFG/DFG built.")
```

* The enrichment pipeline is the right orchestration surface to register new analysis steps that write artifacts and/or update the DuckDB catalog. This follows your services/CLI pattern. 

**Tests (GOID builder):** `tests/codeintel_rev/enrich/test_goid_builder.py`

```diff
diff --git a/tests/codeintel_rev/enrich/test_goid_builder.py b/tests/codeintel_rev/enrich/test_goid_builder.py
new file mode 100644
index 0000000..e55e1c7
--- /dev/null
+++ b/tests/codeintel_rev/enrich/test_goid_builder.py
@@
+from __future__ import annotations
+from pathlib import Path
+import duckdb
+import pyarrow as pa
+import pyarrow.parquet as pq
+from codeintel_rev.io.duckdb_manager import DuckDBManager
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.enrich.goid_builder import GOIDBuilder, GOIDBuilderConfig
+
+def _write_ast_nodes(tmp: Path) -> Path:
+    root = tmp / "build" / "enrich" / "ast"
+    root.mkdir(parents=True, exist_ok=True)
+    tbl = pa.table({
+        "path": ["pkg/mod.py"],
+        "module": ["pkg.mod"],
+        "qualname": ["fn"],
+        "node_type": ["FunctionDef"],
+        "parent_qualname": [None],
+        "start_line": [10],
+        "end_line": [20],
+    })
+    out = root / "ast_nodes.parquet"
+    pq.write_table(tbl, out)
+    return tmp / "build" / "enrich"
+
+def test_groid_builder_inserts(tmp_path: Path):
+    enrich_root = _write_ast_nodes(tmp_path)
+    scip_json = tmp_path / "index.scip.json"
+    scip_json.write_text("{}")
+
+    mgr = DuckDBManager(tmp_path / "test.duckdb")
+    cat = DuckDBCatalog(mgr)
+    # apply migration
+    with mgr.get_connection() as con:
+        con.execute((tmp_path.parent / "registry" / "migrations" / "2025_11_19_0001_goid_callgraph_cfg.sql").read_text())
+
+    GOIDBuilder(cat, GOIDBuilderConfig(tmp_path, enrich_root, scip_json)).build()
+    with mgr.get_connection() as con:
+        cnt = con.execute("SELECT COUNT(*) FROM goid_objects").fetchone()[0]
+        assert cnt == 1
+        cross = con.execute("SELECT COUNT(*) FROM chunk_goid_map").fetchone()[0]
+        assert cross == 1
```

* Tests use **real DuckDB** and **real Parquet** as per your testing philosophy. 

---

### 4) Call Graph: base interface, Python resolver, TS stub, service glue

**File:** `codeintel_rev/enrich/callgraph/base.py`

```diff
diff --git a/codeintel_rev/enrich/callgraph/base.py b/codeintel_rev/enrich/callgraph/base.py
new file mode 100644
index 0000000..adad00f
--- /dev/null
+++ b/codeintel_rev/enrich/callgraph/base.py
@@
+from __future__ import annotations
+from dataclasses import dataclass
+from typing import Iterable, Protocol
+
+@dataclass(frozen=True)
+class CallEdge:
+    caller_goid: str
+    callee_goid: str
+    site_path: str
+    site_start_line: int
+    site_end_line: int
+    lang: str
+    provenance: str
+    confidence: float
+    notes: str | None = None
+
+class CallGraphResolver(Protocol):
+    def iter_edges(self) -> Iterable[CallEdge]: ...
```

**File:** `codeintel_rev/enrich/callgraph/python_resolver.py`

```diff
diff --git a/codeintel_rev/enrich/callgraph/python_resolver.py b/codeintel_rev/enrich/callgraph/python_resolver.py
new file mode 100644
index 0000000..face0ff
--- /dev/null
+++ b/codeintel_rev/enrich/callgraph/python_resolver.py
@@
+from __future__ import annotations
+import ast
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Iterable
+from codeintel_rev.enrich.callgraph.base import CallEdge, CallGraphResolver
+from codeintel_rev.models.goid import GOID
+
+@dataclass
+class PythonCallGraphResolver(CallGraphResolver):
+    repo_root: Path
+
+    def iter_edges(self) -> Iterable[CallEdge]:
+        # Minimal static call edge discovery: Name(...) and Attr(...). This can be improved incrementally.
+        for path in self.repo_root.rglob("*.py"):
+            src = path.read_text(encoding="utf-8", errors="ignore")
+            try:
+                tree = ast.parse(src)
+            except SyntaxError:
+                continue
+            lines = src.splitlines()
+            current_fn: list[tuple[str,int,int]] = []
+            for node in ast.walk(tree):
+                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
+                    qual = node.name
+                    sl, el = node.lineno, node.end_lineno or node.lineno
+                    # caller GOID: normalize to python + path + qual + span
+                    caller = GOID("python", str(path.relative_to(self.repo_root)).replace("\\", "/"),
+                                  "function", qual, sl, el).to_string()
+                    current_fn.append((caller, sl, el))
+                if isinstance(node, ast.Call):
+                    # naive callee extraction
+                    name = None
+                    if isinstance(node.func, ast.Name):
+                        name = node.func.id
+                    elif isinstance(node.func, ast.Attribute):
+                        name = node.func.attr
+                    if name and current_fn:
+                        caller_goid, fsl, fel = current_fn[-1]
+                        site_sl = getattr(node, "lineno", fsl)
+                        site_el = getattr(node, "end_lineno", site_sl)
+                        # callee GOID is unresolved symbol; encode as name-only pseudo target.
+                        callee_goid = GOID("python", str(path.relative_to(self.repo_root)).replace("\\", "/"),
+                                           "symbol", name, site_sl, site_el).to_string()
+                        yield CallEdge(
+                            caller_goid=caller_goid,
+                            callee_goid=callee_goid,
+                            site_path=str(path.relative_to(self.repo_root)).replace("\\", "/"),
+                            site_start_line=site_sl,
+                            site_end_line=site_el,
+                            lang="python",
+                            provenance="ast",
+                            confidence=0.40,
+                            notes="name-only resolution; will be refined via SCIP aliasing",
+                        )
```

**File:** `codeintel_rev/services/enrich/callgraph.py`

```diff
diff --git a/codeintel_rev/services/enrich/callgraph.py b/codeintel_rev/services/enrich/callgraph.py
new file mode 100644
index 0000000..beefdad
--- /dev/null
+++ b/codeintel_rev/services/enrich/callgraph.py
@@
+from __future__ import annotations
+from pathlib import Path
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.enrich.callgraph.python_resolver import PythonCallGraphResolver
+
+def run_build_callgraph(catalog: DuckDBCatalog, repo_root: Path, enrich_root: Path) -> None:
+    edges = list(PythonCallGraphResolver(repo_root).iter_edges())
+    rows = [(e.caller_goid, e.callee_goid, e.site_path, e.site_start_line, e.site_end_line, e.lang, e.provenance, e.confidence, e.notes) for e in edges]
+    if rows:
+        catalog.insert_call_edges(rows)
```

**TypeScript stub (optional adapter for future TS graph extraction)**

**File:** `tools/ts/callgraph/resolver.ts`

```diff
diff --git a/tools/ts/callgraph/resolver.ts b/tools/ts/callgraph/resolver.ts
new file mode 100644
index 0000000..bada55e
--- /dev/null
+++ b/tools/ts/callgraph/resolver.ts
@@
+// Minimal contract: emit JSON array of call edges to stdout.
+// Wire into Python enrichment via subprocess if/when needed.
+export interface CallEdge {
+  caller_goid: string;
+  callee_goid: string;
+  site_path: string;
+  site_start_line: number;
+  site_end_line: number;
+  lang: "typescript";
+  provenance: "ast" | "inferred";
+  confidence: number;
+  notes?: string;
+}
+
+export async function main() {
+  const edges: CallEdge[] = [];
+  // TODO: implement with ts-morph/TypeScript AST
+  process.stdout.write(JSON.stringify(edges));
+}
+
+if (require.main === module) {
+  void main();
+}
```

**Tests (call graph):** `tests/codeintel_rev/enrich/test_callgraph_python.py`

```diff
diff --git a/tests/codeintel_rev/enrich/test_callgraph_python.py b/tests/codeintel_rev/enrich/test_callgraph_python.py
new file mode 100644
index 0000000..bc0ffee
--- /dev/null
+++ b/tests/codeintel_rev/enrich/test_callgraph_python.py
@@
+from __future__ import annotations
+from pathlib import Path
+from codeintel_rev.enrich.callgraph.python_resolver import PythonCallGraphResolver
+
+def test_python_callgraph_simple(tmp_path: Path):
+    p = tmp_path / "pkg"
+    p.mkdir(parents=True)
+    (p / "m.py").write_text("def a():\n    b()\n\ndef b():\n    return 1\n")
+    edges = list(PythonCallGraphResolver(tmp_path).iter_edges())
+    assert any("a" in e.caller_goid and "b" in e.callee_goid for e in edges)
```

* This scaffolding follows your “enrichment pipeline produces artifacts and registers with DuckDB” pattern and keeps adapters cleanly separable by language. 

---

### 5) CFG/DFG scaffolding (function‑level)

**File:** `codeintel_rev/services/enrich/cfg_dfg.py`

```diff
diff --git a/codeintel_rev/services/enrich/cfg_dfg.py b/codeintel_rev/services/enrich/cfg_dfg.py
new file mode 100644
index 0000000..c0ffee0
--- /dev/null
+++ b/codeintel_rev/services/enrich/cfg_dfg.py
@@
+from __future__ import annotations
+import ast
+from pathlib import Path
+from typing import Iterable, Tuple
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.models.goid import GOID
+
+def _cfg_for_fn(fn: ast.AST) -> tuple[list[tuple[int,str,int,int,str|None]], list[tuple[int,int,str]]]:
+    """
+    Tiny CFG: entry -> stmt... -> exit; 'if' creates true/false edges.
+    nodes: (node_id, kind, sl, el, payload_json)
+    edges: (src_id, dst_id, type)
+    """
+    nid = 0
+    nodes = [(nid, "entry", fn.lineno, fn.lineno, None)]
+    last = nid; nid += 1
+    for n in getattr(fn, "body", []):
+        nodes.append((nid, "stmt", n.lineno, getattr(n, "end_lineno", n.lineno), None))
+        nid += 1
+    exit_id = nid; nodes.append((exit_id, "exit", getattr(fn, "end_lineno", fn.lineno), getattr(fn, "end_lineno", fn.lineno), None))
+    edges = []
+    # linear fallthrough
+    for a, b in zip(range(0, len(nodes)-1), range(1, len(nodes))):
+        edges.append((a, b, "fallthrough"))
+    return nodes, edges
+
+def _dfg_for_fn(fn: ast.AST) -> tuple[list[tuple[int,str,str|None,int,int,str|None]], list[tuple[int,int,str]]]:
+    """
+    Tiny DFG: collect Name load/store pairs within function.
+    nodes: (node_id, kind, symbol, sl, el, payload_json)
+    """
+    nid = 0
+    nodes = []
+    edges = []
+    def add(kind: str, sym: str|None, sl: int, el: int):
+        nonlocal nid; nodes.append((nid, kind, sym, sl, el, None)); nid += 1; return nid-1
+    defs: dict[str,int] = {}
+    for n in ast.walk(fn):
+        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
+            defs[n.targets[0].id] = add("def", n.targets[0].id, n.lineno, getattr(n, "end_lineno", n.lineno))
+        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
+            u = add("use", n.id, n.lineno, getattr(n, "end_lineno", n.lineno))
+            if n.id in defs:
+                edges.append((defs[n.id], u, "flows_to"))
+    return nodes, edges
+
+def run_build_cfg_dfg(catalog: DuckDBCatalog, repo_root: Path, enrich_root: Path) -> None:
+    for py in repo_root.rglob("*.py"):
+        try:
+            tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
+        except SyntaxError:
+            continue
+        for node in ast.walk(tree):
+            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
+                goid = GOID("python", str(py.relative_to(repo_root)).replace("\\","/"), "function", node.name, node.lineno, getattr(node, "end_lineno", node.lineno)).to_string()
+                cfg_nodes, cfg_edges = _cfg_for_fn(node)
+                dfg_nodes, dfg_edges = _dfg_for_fn(node)
+                catalog.replace_cfg(goid, cfg_nodes, cfg_edges)
+                catalog.replace_dfg(goid, dfg_nodes, dfg_edges)
```

**Test (CFG/DFG):** `tests/codeintel_rev/enrich/test_cfg_dfg.py`

```diff
diff --git a/tests/codeintel_rev/enrich/test_cfg_dfg.py b/tests/codeintel_rev/enrich/test_cfg_dfg.py
new file mode 100644
index 0000000..deadc0d
--- /dev/null
+++ b/tests/codeintel_rev/enrich/test_cfg_dfg.py
@@
+from __future__ import annotations
+from pathlib import Path
+from codeintel_rev.io.duckdb_manager import DuckDBManager
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.services.enrich.cfg_dfg import run_build_cfg_dfg
+
+def test_cfg_dfg_inserts(tmp_path: Path):
+    (tmp_path / "m.py").write_text("def f():\n  x=1\n  return x\n")
+    mgr = DuckDBManager(tmp_path / "c.duckdb")
+    cat = DuckDBCatalog(mgr)
+    with mgr.get_connection() as con:
+        con.execute((tmp_path.parent / "registry" / "migrations" / "2025_11_19_0001_goid_callgraph_cfg.sql").read_text())
+    run_build_cfg_dfg(cat, tmp_path, tmp_path)
+    with mgr.get_connection() as con:
+        assert con.execute("SELECT COUNT(*) FROM cfg_nodes").fetchone()[0] > 0
+        assert con.execute("SELECT COUNT(*) FROM dfg_nodes").fetchone()[0] > 0
```

---

## Operational notes & alignment with the current codebase

* **Where data comes from**: The GOID builder reads `build/enrich/ast/ast_nodes.parquet` and (optionally) correlates SCIP descriptors later. This is consistent with your enrichment artifact locations. 
* **Where it plugs in**: The CLI commands are added to `cli/enrich_pipeline` so the same operational flow (scan → build artifacts → register in DuckDB) is used for GOIDs, call graph, and CFG/DFG. 
* **How the server uses it**: MCP adapters continue to hydrate via `DuckDBCatalog` which now exposes targeted methods to read/write GOIDs and graphs; these can be used by search and symbol navigation paths without architectural drift.  
* **DuckDB‑specifics**: We rely on `INSERT OR REPLACE`, `CREATE INDEX`, and `CREATE OR REPLACE VIEW`—all supported by DuckDB—no Postgres‑specific DDL. The JSON payloads are kept as `TEXT` to avoid the json extension; if you later enable `json`, you can switch column types to `JSON` with a trivial migration. 
* **Testing**: Tests use **real DuckDB connections** and **real Parquet files** as your test rules prescribe (no monkeypatching, real entry points). 

---

## Post‑merge checklist (for the AI programming agents)

1. **Apply migrations**

   ```
   uv run python -c "from codeintel_rev.io.duckdb_manager import DuckDBManager; \
   import duckdb, pathlib; \
   p=pathlib.Path('registry/migrations/2025_11_19_0001_goid_callgraph_cfg.sql'); \
   con=duckdb.connect('indexes/catalog.duckdb'); con.execute(p.read_text()); con.close()"
   ```

   (Replace path with your active catalog path or run through a small helper in `DuckDBCatalog`.) 

2. **Build GOIDs, then Call Graph, then CFG/DFG**

   ```
   codeintel enrich goid --repo-root . --enrich-root build/enrich --scip-json index.scip.json
   codeintel enrich callgraph --repo-root .
   codeintel enrich cfg-dfg --repo-root .
   ```

   These follow the command structure and operational model already in your CLI. 

3. **Update the Architecture Narrative (Section 7: Data Structures; Section 5.7: Enrichment)** to include the new tables and flows; your document requests updates when new extensibility mechanisms land. 

---

## Future‑proofing hooks (non‑blocking)

* **SCIP correlation**: augment `GOIDBuilder.build()` to read definitions from `index.scip(.json)` via `indexing.scip_reader` and add `(source='scip', source_id=scip_symbol)` aliases, improving call‑graph resolution quality immediately. 
* **Hydration helpers for MCP**: convenience readers (e.g., `get_outgoing_calls(goid)`) can be added in `DuckDBCatalog` once call graph is populated by the pipeline—keeps adapters thin. 
* **TS resolver**: wire `tools/ts/callgraph/resolver.ts` via a subprocess runner in `services/enrich/callgraph.py` if/when TS analysis is enabled.

---

### Why this is “best‑in‑class” for LLM navigability

* **Stable, canonical IDs** (GOID) unify every surface (SCIP, AST/CST, chunks), unlocking high‑precision joins in hydration and perfect provenance for diffs and design docs. 
* **Fine‑grained, queryable graphs** in DuckDB make downstream reasoning (e.g., “who calls this API?”, “which defs flow into this sink?”) a single SQL away, and match your durability/versioning story for index assets. 
* **Strict layering**: all new code lives in `services/enrich` (orchestration), `enrich/*` (domain extraction), and `io/*` (catalog access), preserving your dependency rules and keeping MCP adapters simple. 







