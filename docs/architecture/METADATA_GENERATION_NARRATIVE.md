# Metadata Generation Architecture Narrative

## 0. How to Use This Document (For Humans & AI Agents)

**Audience**

- Primary: AI coding agents and engineers working on the CodeIntel metadata generation pipeline.
- Secondary: Stakeholders seeking understanding of how repository metadata artifacts are produced.

**Scope**

- This document describes the architecture of the **metadata generation pipeline** that produces the artifacts documented in `README_METADATA.md`.
- It is **normative**: if code disagrees with this narrative, treat the narrative as the desired target and propose refactors.
- Focus: How `codeintel_rev.cli.enrich` commands generate GOIDs, call graphs, CFG/DFG, analytics, and export artifacts.

**Reading Order**

- Start with Section 1 (System Purpose) and Section 3 (Architectural Principles).
- For understanding a specific artifact type:
  - Read Section 5 (Runtime Behavior) for the relevant flow.
  - Read Section 6 (Static Structure) for the modules involved.
  - Read Section 7 (Data Structures) for artifact schemas.
- For modifying the pipeline:
  - Read Section 9 (Change Patterns) for extension recipes.
  - Read Section 10 (Testing) for required tests.

**Conventions**

- File paths are written as: `codeintel_rev/cli/enrich/goids.py`.
- Symbols are written as: `codeintel_rev.enrich.goid_builder.GOIDBuilder.build`.
- Important invariants and "never do this" rules are explicitly labeled.
- Hypotheses or unclear areas are labeled with **(Hypothesis)** or **(Needs Review)**.

**Norms for AI Agents**

- Always ground your changes in this document and the actual code.
- If you detect discrepancies between this narrative and the code:
  - Explain the discrepancy.
  - Recommend a resolution (update narrative vs refactor code).
- Never silently violate stated invariants or principles.

---

## Table of Contents

- [0. How to Use This Document (For Humans & AI Agents)](#0-how-to-use-this-document-for-humans--ai-agents)
- [1. System Purpose & High-Level Overview](#1-system-purpose--high-level-overview)
    - [1.1 Mission](#11-mission)
    - [1.2 Non-Goals](#12-non-goals)
    - [1.3 Primary Use Cases](#13-primary-use-cases)
    - [1.4 External Systems and Stakeholders](#14-external-systems-and-stakeholders)
    - [1.5 Key Constraints](#15-key-constraints)
- [2. Domain Model & Glossary](#2-domain-model--glossary)
    - [2.1 Glossary](#21-glossary)
    - [2.2 Entity Relationships (Textual Overview)](#22-entity-relationships-textual-overview)
- [3. Architectural Principles & Constraints](#3-architectural-principles--constraints)
    - [3.1 Core Principles](#31-core-principles)
    - [3.2 Invariants](#32-invariants)
    - [3.3 Forbidden Patterns](#33-forbidden-patterns)
- [4. System Context & External Integrations](#4-system-context--external-integrations)
    - [4.1 Inbound Interfaces](#41-inbound-interfaces)
    - [4.2 Outbound Dependencies](#42-outbound-dependencies)
    - [4.3 Trust Boundaries & Security](#43-trust-boundaries--security)
- [5. Runtime Behavior & Key Flows](#5-runtime-behavior--key-flows)
    - [5.1 Flow: Full Pipeline Execution (`enrich_pipeline all`)](#51-flow-full-pipeline-execution-enrich_pipeline-all)
    - [5.2 Flow: GOID Generation (`enrich goids`)](#52-flow-goid-generation-enrich-goids)
    - [5.3 Flow: Call Graph Generation (`enrich callgraph`)](#53-flow-call-graph-generation-enrich-callgraph)
    - [5.4 Flow: CFG/DFG Generation (`enrich cfg` / `enrich dfg`)](#54-flow-cfgdfg-generation-enrich-cfg--enrich-dfg)
    - [5.5 Flow: Exports Generation (`enrich exports`)](#55-flow-exports-generation-enrich-exports)
- [6. Static Structure: Layers, Modules, and Dependencies](#6-static-structure-layers-modules-and-dependencies)
    - [6.1 Layer Overview](#61-layer-overview)
    - [6.2 Module Catalog](#62-module-catalog)
- [7. Data & Metadata Structures](#7-data--metadata-structures)
    - [7.1 GOID Registry Schema (`goids.parquet` / `goids.jsonl`)](#71-goid-registry-schema-goidsparquet--goidsjsonl)
    - [7.2 GOID Crosswalk Schema (`goid_xwalk.parquet` / `goid_xwalk.jsonl`)](#72-goid-crosswalk-schema-goid_xwalkparquet--goid_xwalkjsonl)
    - [7.3 Call Graph Nodes Schema (`call_nodes.parquet` / `call_nodes.jsonl`)](#73-call-graph-nodes-schema-call_nodesparquet--call_nodesjsonl)
    - [7.4 Call Graph Edges Schema (`call_edges.parquet` / `call_edges.jsonl`)](#74-call-graph-edges-schema-call_edgesparquet--call_edgesjsonl)
    - [7.5 CFG Blocks Schema (`cfg_blocks.parquet` / `cfg_blocks.jsonl`)](#75-cfg-blocks-schema-cfg_blocksparquet--cfg_blocksjsonl)
    - [7.6 CFG Edges Schema (`cfg_edges.parquet` / `cfg_edges.jsonl`)](#76-cfg-edges-schema-cfg_edgesparquet--cfg_edgesjsonl)
    - [7.7 DFG Edges Schema (`dfg_edges.parquet` / `dfg_edges.jsonl`)](#77-dfg-edges-schema-dfg_edgesparquet--dfg_edgesjsonl)
    - [7.8 Module Records Schema (`modules.jsonl`)](#78-module-records-schema-modulesjsonl)
    - [7.9 Import Graph Edges Schema (`import_graph_edges.parquet` / `import_graph_edges.jsonl`)](#79-import-graph-edges-schema-import_graph_edgesparquet--import_graph_edgesjsonl)
    - [7.10 Symbol Use Edges Schema (`symbol_use_edges.parquet` / `symbol_use_edges.jsonl`)](#710-symbol-use-edges-schema-symbol_use_edgesparquet--symbol_use_edgesjsonl)
    - [7.11 Coverage Lines Schema (`coverage_lines.parquet` / `coverage_lines.jsonl`)](#711-coverage-lines-schema-coverage_linesparquet--coverage_linesjsonl)
    - [7.12 Coverage Functions Schema (`coverage_functions.parquet` / `coverage_functions.jsonl`)](#712-coverage-functions-schema-coverage_functionsparquet--coverage_functionsjsonl)
    - [7.13 Test Catalog Schema (`test_catalog.parquet` / `test_catalog.jsonl`)](#713-test-catalog-schema-test_catalogparquet--test_catalogjsonl)
    - [7.14 Test Coverage Edges Schema (`test_coverage_edges.parquet` / `test_coverage_edges.jsonl`)](#714-test-coverage-edges-schema-test_coverage_edgesparquet--test_coverage_edgesjsonl)
    - [7.15 GOID Risk Factors Schema (`goid_risk_factors.parquet` / `goid_risk_factors.jsonl`)](#715-goid-risk-factors-schema-goid_risk_factorsparquet--goid_risk_factorsjsonl)
- [8. Cross-Cutting Concerns](#8-cross-cutting-concerns)
    - [8.1 Configuration Management](#81-configuration-management)
    - [8.2 Logging & Observability](#82-logging--observability)
    - [8.3 Error Handling](#83-error-handling)
    - [8.4 Concurrency & Parallelism](#84-concurrency--parallelism)
    - [8.5 Performance & Scaling](#85-performance--scaling)
- [9. Change Patterns & Extension Recipes](#9-change-patterns--extension-recipes)
    - [9.1 How to Add a New Graph Artifact Type](#91-how-to-add-a-new-graph-artifact-type)
    - [9.2 How to Add a New Analytics Export](#92-how-to-add-a-new-analytics-export)
    - [9.3 How to Extend GOID Crosswalk with New Sources](#93-how-to-extend-goid-crosswalk-with-new-sources)
- [10. Testing & Quality Gates](#10-testing--quality-gates)
    - [10.1 Test Types](#101-test-types)
    - [10.2 Rules for Writing Tests](#102-rules-for-writing-tests)
    - [10.3 CI & Quality Gates](#103-ci--quality-gates)
- [11. Operational & Deployment View](#11-operational--deployment-view)
    - [11.1 Deployment Model](#111-deployment-model)
    - [11.2 Runtime Configuration](#112-runtime-configuration)
    - [11.3 Monitoring & Observability](#113-monitoring--observability)
    - [11.4 Migrations & Rollouts](#114-migrations--rollouts)
- [12. Architectural Decisions & History](#12-architectural-decisions--history)
    - [ADR-001: Deterministic GOID Hashing](#adr-001-deterministic-goid-hashing)
    - [ADR-002: Dual Format Output (Parquet + JSONL)](#adr-002-dual-format-output-parquet--jsonl)
    - [ADR-003: Optional Graph Steps](#adr-003-optional-graph-steps)
- [13. Indices & Cross-References](#13-indices--cross-references)
    - [13.1 Symbol Index](#131-symbol-index)
    - [13.2 Module Index](#132-module-index)
    - [13.3 Artifact Index](#133-artifact-index)

---

## 1. System Purpose & High-Level Overview

### 1.1 Mission

The metadata generation pipeline transforms Python source code repositories into structured, queryable datasets that capture:

1. **Structural metadata**: AST nodes, modules, symbols, and their relationships.
2. **Graph metadata**: Call graphs, control-flow graphs (CFG), data-flow graphs (DFG), import graphs, and symbol use graphs.
3. **Analytics metadata**: Code metrics (complexity, typedness, hotspots), function-level metrics, ownership, coverage, and static diagnostics.
4. **Cross-reference metadata**: GOID (Global Object Identifier) registry and crosswalk tables linking identifiers across analysis sources.

These artifacts enable downstream AI agents and tools to reason about codebases to reason about code structure, dependencies, and quality without re-running heavy analysis steps.

### 1.2 Non-Goals

- **Not a real-time analysis tool**: The pipeline is designed for batch processing of repository snapshots, not incremental updates during development.
- **Not a language server**: While it produces symbol graphs similar to LSP, it does not provide live IDE features.
- **Not a test runner**: Coverage data is ingested from external tools (Cobertura XML), not computed by the pipeline.
- **Not a build system**: The pipeline analyzes source code but does not compile or execute it.

### 1.3 Primary Use Cases

- **Use Case A** – Full Repository Analysis
  - What: Generate all metadata artifacts for a repository snapshot.
  - Who: CI/CD pipelines, documentation generators, code intelligence tools.
  - Where in code: `codeintel_rev.cli.enrich_pipeline all` command orchestrates the full pipeline.

- **Use Case B** – Graph Artifact Generation
  - What: Build GOID registry, call graph, CFG, and DFG datasets independently.
  - Who: Graph analysis tools, impact analysis tools, code navigation systems.
  - Where in code: `codeintel_rev.cli.enrich goids|callgraph|cfg|dfg` commands.

- **Use Case C** – Analytics Export
  - What: Export module metadata, analytics tables, and summary reports.
  - Who: Code quality dashboards, ownership tracking systems, migration planning tools.
  - Where in code: `codeintel_rev.cli.enrich exports` and `codeintel_rev.cli.enrich analytics` commands.

### 1.4 External Systems and Stakeholders

- **Upstream inputs**
  - **SCIP index**: Language-agnostic symbol graph produced by `scip-python`. Required for symbol resolution and cross-referencing. Path: `codeintel_rev/index.scip.json`.
  - **Type checker reports**: Pyrefly JSON and Pyright JSON reports for typedness analytics. Optional.
  - **Coverage XML**: Cobertura-format coverage reports. Optional.
  - **Tagging rules**: YAML files defining semantic tags for modules. Optional.

- **Downstream consumers**
  - **Document generation scripts**: Repository-root `generate_documents.sh` orchestrates the full pipeline: (1) run `scip-python index` → `index.scip.json`, (2) run `python -m codeintel_rev.cli.enrich_pipeline all --emit-ast`, (3) run individual graph builders (`enrich goids|callgraph|cfg|dfg`), (4) run analytics CLIs for graphs/uses/typedness/function metrics/types and, if coverage assets exist, coverage/test/risk analytics, (5) build CST dataset via `codeintel_rev.cst_build.cst_cli`, (6) convert Parquet → JSONL via DuckDB `COPY`, (7) copy artifacts into `Document Output/`.
  - **DuckDB catalog**: Graph artifacts can be ingested into a DuckDB database for SQL queries via `--ingest` flag or `enrich to-duckdb` command.
  - **AI agents**: JSONL artifacts are consumed as streaming corpora for code understanding tasks.

### 1.5 Key Constraints

- **Performance**: Must handle repositories with thousands of Python files. Graph builders use streaming and batch processing to manage memory.
- **Reliability**: GOID generation must be deterministic and stable across runs for the same repository/commit. Hash collisions are prevented via content-based hashing using xxhash (XXH128) algorithm.
- **Accuracy**: Call graph resolution must handle dynamic dispatch gracefully; unresolved calls are still recorded with lower confidence scores.
- **Format compatibility**: All artifacts are emitted in both Parquet (for analytics) and JSONL (for LLM ingestion) formats.

---

## 2. Domain Model & Glossary

### 2.1 Glossary

| Term | Definition (Plain Language) | Primary Code Representations |
|------|----------------------------|------------------------------|
| **GOID** | Global Object Identifier: a stable, content-based hash identifier for code entities (modules, functions, classes, CFG blocks). | `codeintel_rev.ids.goid.GOID`, `codeintel_rev.enrich.goid_builder.GOIDBuilder` |
| **AST Node** | Abstract Syntax Tree node representing a code element (function, class, statement). | `codeintel_rev.enrich.ast_indexer.AstNodeRow`, `ast.AST` |
| **Call Graph** | Directed graph of function calls: nodes are callables, edges are callsites. | `codeintel_rev.enrich.callgraph.CallGraphArtifacts`, `CallNodeRow`, `CallEdgeRow` |
| **CFG Block** | Control-Flow Graph basic block: a sequence of statements with single entry/exit points. | `codeintel_rev.enrich.cfg.CFGBlockRow`, `_FunctionCFGBuilder._Block` |
| **DFG Edge** | Data-Flow Graph edge: tracks definition-to-use relationships for variables within a function. | `codeintel_rev.enrich.cfg.DFGEdgeRow`, `_DFGAnalyzer` |
| **Module Record** | Metadata row describing a Python module: path, tags, metrics, ownership. | `codeintel_rev.enrich.models.ModuleRecord`, `codeintel_rev.services.enrich.models.ModuleRecord` |
| **Symbol Edge** | Def→use relationship linking symbol definitions to their usage sites. | `tuple[str, str]` (symbol, file_path) |
| **Import Graph** | Directed graph of module imports: edges represent `import` statements. | `codeintel_rev.enrich.graph_builder.ImportGraph`, `import_graph_edges.parquet` |
| **Tag Index** | Mapping of semantic tags (e.g., "cli", "test", "api") to module paths. | `dict[str, list[str]]`, `tags_index.yaml` |
| **Pipeline Context** | Runtime state bundle: SCIP index, type signals, coverage maps, tagging rules. | `codeintel_rev.services.enrich.context.LegacyPipelineContext`, `PipelineContext` |

### 2.2 Entity Relationships (Textual Overview)

- A **Repository** contains many **Module**s (Python files).
- Each **Module** has many **AST Node**s (functions, classes, statements).
- **AST Node**s are assigned **GOID**s via content-based hashing.
- **GOID**s link to **Crosswalk** entries mapping identifiers across sources (AST, SCIP, chunk IDs).
- **Call Graph** edges connect **GOID**s (caller → callee) with callsite metadata.
- **CFG Block**s belong to a function **GOID** and are connected by **CFG Edge**s.
- **DFG Edge**s connect **CFG Block**s within a function, tracking variable def-use chains.
- **Module Record**s aggregate metrics, tags, and ownership for each module.
- **Symbol Edge**s link SCIP symbols to their definition and usage files.

---

## 3. Architectural Principles & Constraints

### 3.1 Core Principles

1. **Separation of Concerns**
   - **Builders** (`GOIDBuilder`, `CallGraphBuilder`, `CFGBuilder`) are pure transformation logic: they take inputs and produce artifacts.
   - **CLI commands** (`codeintel_rev.cli.enrich.*`) orchestrate builders and handle I/O.
   - **Services** (`codeintel_rev.services.enrich.*`) provide reusable pipeline stages and context management.

2. **Deterministic Outputs**
   - GOID generation is deterministic: same repository + commit + entity descriptor → same GOID hash.
   - Artifact ordering is deterministic: files are processed in sorted order, edges are sorted before writing.
   - No reliance on file system iteration order or hash table iteration order.

3. **Format Flexibility**
   - All graph artifacts are written in both Parquet (columnar, SQL-friendly) and JSONL (streaming, LLM-friendly).
   - Parquet is preferred for analytics; JSONL is generated via DuckDB `COPY` from Parquet.
   - Schema evolution is handled via optional fields and versioned writer functions.

4. **Incremental Processing**
   - Graph builders process files independently and can be run in parallel (future optimization).
   - DuckDB ingestion supports upserts, enabling incremental catalog updates.
   - Pipeline stages are composable: `scan` → `exports` → `goids` → `callgraph` can be run independently.

### 3.2 Invariants

- **GOID Stability**: GOIDs must not change for the same entity across runs on the same repository/commit. Violating this corrupts downstream graph joins. GOID hashing uses xxhash (XXH128) for deterministic content-based hashing; the hash includes repository fingerprint, commit, language, kind, path, qualname, line numbers, and optional SCIP symbol.
- **Crosswalk Completeness**: Every GOID must have at least one crosswalk entry linking it to an AST node or chunk ID.
- **CFG Soundness**: Every function must have exactly one entry block and one exit block. All blocks must be reachable from the entry block.
- **Call Graph Completeness**: Every call expression in source code must produce at least one edge (even if callee is unresolved).

### 3.3 Forbidden Patterns

- **Never** modify GOID hashing algorithm (xxhash XXH128) or URN format without a migration plan for existing artifacts. Changing the hash algorithm breaks all downstream graph joins.
- **Never** skip AST node collection for files that pass syntax checks; this breaks GOID generation.
- **Never** write graph artifacts without sorting edges/nodes; this breaks deterministic output.
- **Never** access SCIP index without error handling; missing SCIP files should degrade gracefully.

---

## 4. System Context & External Integrations

### 4.1 Inbound Interfaces

- **CLI Entry Point**: `codeintel_rev.cli_enrich.py` (compatibility shim) → `codeintel_rev.cli.enrich.__main__.py`
  - Commands: `scan`, `exports`, `goids`, `callgraph`, `cfg`, `dfg`, `analytics`, `to-duckdb`, `audit`
  - Framework: Typer (CLI framework)
  - Shared options: `--root`, `--scip`, `--out`, `--pyrefly-json`, `--tags-yaml`, `--coverage-xml`, `--only`, `--max-file-bytes`
  - Graph commands (`goids`, `callgraph`, `cfg`, `dfg`) use `--repo-root` and `--out-dir` instead of `--root`/`--out`; they share helpers in `codeintel_rev.cli.enrich._graph_utils`

- **Legacy Pipeline Entry Point**: `codeintel_rev.cli.enrich_pipeline` (compatibility shim)
  - Command: `all` (runs full pipeline: scan + analytics + exports)
  - Used by `generate_documents.sh` for end-to-end artifact generation

### 4.2 Outbound Dependencies

- **SCIP Index Reader**: `codeintel_rev.enrich.scip_reader.SCIPIndex`
  - Used for: Symbol resolution, cross-referencing GOIDs with SCIP symbols
  - File format: JSON export of SCIP binary index

- **DuckDB Catalog**: `codeintel_rev.io.duckdb_catalog.DuckDBCatalog`
  - Used for: Ingesting graph artifacts into SQL-queryable database
  - Schema: Tables for GOIDs, call nodes/edges, CFG blocks/edges, DFG edges

- **Parquet Writers**: `codeintel_rev.enrich.graph.io.write_*` functions
  - Used for: Writing columnar Parquet datasets
  - Fallback: JSONL writers when Parquet is unavailable

- **File System**: Python `pathlib.Path` for all I/O
  - Used for: Reading source files, writing artifacts, discovering Python files

### 4.3 Trust Boundaries & Security

- **Input Validation**: File paths are normalized relative to repository root to prevent path traversal.
- **Size Limits**: `--max-file-bytes` option prevents processing of extremely large files (default: 2MB).
- **Error Handling**: Syntax errors in source files are logged and skipped; they do not abort the pipeline.
- **SCIP Index**: SCIP JSON is parsed with error handling; missing or malformed SCIP files degrade gracefully (some features disabled).

---

## 5. Runtime Behavior & Key Flows

### 5.1 Flow: Full Pipeline Execution (`enrich_pipeline all`)

**Trigger**

- CLI command: `python -m codeintel_rev.cli.enrich_pipeline all --root <dir> --scip <path> --out <dir>`
- Code entrypoints: `codeintel_rev.cli.enrich_pipeline.execute_pipeline_or_exit`, `codeintel_rev.services.enrich.scan.run_pipeline`
- Also invoked by: `generate_documents.sh` script (line 95) as part of end-to-end document generation

**Integration with `generate_documents.sh`**

The `generate_documents.sh` script orchestrates the full metadata generation pipeline:

1. **SCIP Indexing** (lines 87-92): Runs `scip-python index` and exports to JSON
2. **Enrichment Pipeline** (lines 94-100): Runs `enrich_pipeline all` with `--emit-ast` flag
3. **Graph Artifacts** (lines 102-118): Sequentially runs `enrich goids`, `callgraph`, `cfg`, `dfg` commands
4. **CST Dataset** (lines 120-125): Builds CST nodes via `cst_cli`
5. **Parquet→JSONL Conversion** (lines 131-234): Uses DuckDB `COPY` to convert Parquet files to JSONL via `convert_parquet_to_jsonl()` function
6. **Artifact Consolidation** (lines 131-234): Copies artifacts to `Document Output/` directory structure

**High-Level Steps**

1. **Prepare Pipeline Context** (`prepare_pipeline`)
   - Load SCIP index from `--scip` path → `SCIPIndex`, `ScipContext`
   - Collect type signals from Pyrefly/Pyright JSON reports → `FileTypeSignals` mapping
   - Collect coverage metrics from Cobertura XML → `coverage_map` mapping
   - Index configuration files → `config_records` list
   - Load tagging rules from YAML → `tagging_rules` mapping
   - Discover Python files under `--root` matching `--only` globs

2. **Scan Modules** (`scan_modules`)
   - For each Python file:
     - Parse AST via LibCST → `ModuleRecord` with path, module name, tags, metrics
     - Extract symbol edges from SCIP index → `(symbol, file_path)` tuples
     - Apply tagging rules → add semantic tags to module record
     - Collect type error counts and annotation ratios → attach to module record
   - Aggregate module rows and symbol edges

3. **Compute Analytics** (`compute_pipeline_analytics`)
   - Build import graph from module imports → `ImportGraph` with edges and cycle groups
   - Build use graph from SCIP symbol references → `UseGraph` with def→use edges
   - Compute hotspot scores from git history + AST metrics → `hotspot_rows`
   - Prepare config value rows with reference paths → `config_index`

4. **Run Graph Steps** (`_run_requested_graph_steps`)
   - If `--goids` or `--all`: Build GOID registry and crosswalk
   - If `--callgraph` or `--all`: Build call graph nodes and edges
   - If `--cfg` or `--all`: Build CFG blocks and edges
   - If `--dfg` or `--all`: Build DFG edges

5. **Return Pipeline Result** (`PipelineResult`)
   - Bundle: `module_rows`, `symbol_edges`, `import_graph`, `use_graph`, `coverage_rows`, `hotspot_rows`, `tag_index`, `type_signals`

**Components Involved**

- `codeintel_rev.services.enrich.scan.prepare_pipeline`
- `codeintel_rev.services.enrich.scan.scan_modules`
- `codeintel_rev.services.enrich.analytics.compute_pipeline_analytics`
- `codeintel_rev.services.enrich.graph_steps.build_*_artifacts`

**Key Invariants**

- SCIP index must be present (raises `typer.BadParameter` if missing).
- Module records are validated via `ModuleRecordModel` before aggregation.
- Graph steps are optional and can be skipped if flags are not set.

**Error Handling & Retries**

- Syntax errors in source files are logged and skipped (file excluded from results).
- SCIP parsing errors are caught and logged; pipeline continues with degraded symbol resolution.
- Type signal collection failures raise `TypeSignalError` and abort the pipeline.

---

### 5.2 Flow: GOID Generation (`enrich goids`)

**Trigger**

- CLI command: `python -m codeintel_rev.cli.enrich goids --repo-root <dir> --out-dir <dir> [--ingest]`
- Code entrypoints: `codeintel_rev.cli.enrich.goids.build_goids_cli`, `codeintel_rev.services.enrich.graph_steps.build_goid_artifacts`

**High-Level Steps**

1. **Resolve Paths** (`resolve_paths`)
   - Resolve application paths from `repo_root` and `out_dir` via `resolve_application_paths()`
   - Validate paths via `validate_paths()`
   - Create `PipelineContext` from resolved paths

2. **Collect Python Files** (`collect_python_files`)
   - Discover Python files under `repo_root` matching optional `--include` globs (via `iter_python_files`)
   - Filter out excluded patterns (`.venv`, `build`, `dist` by default) via `fnmatch` pattern matching
   - Return sorted list of absolute file paths

3. **Detect Commit** (`detect_commit`)
   - Run `git -C {repo_root} rev-parse HEAD` to get commit hash
   - Fall back to `"unknown"` if Git command fails or repo is not a Git repository

4. **Collect AST Artifacts** (`collect_ast_artifacts`)
   - For each Python file:
     - Read file content with UTF-8 encoding, errors='ignore'
     - Parse AST via LibCST → extract `AstNodeRow` objects (functions, classes, modules) via `collect_ast_nodes_from_tree()`
     - Compute AST metrics → `AstMetricsRow` (node counts, complexity, depth) via `compute_ast_metrics()`
   - Aggregate node rows and metric rows into lists

5. **Build GOID Artifacts** (`GOIDBuilder.build`)
   - Initialize `GOIDBuilder` with repo name (stringified `repo_root`), commit hash, language="python"
   - For each unique file path: Create module GOID with `kind="module"`, `qualname` derived from path via `_module_qualname()`
   - For each AST node (function/class/method): Create element GOID with `kind` from `_kind_for_node()` mapping, `qualname` from AST scope
   - Deduplicate GOIDs by hash (`goid_h128`) using `goid_by_hash.setdefault()` → unique GOID registry
   - Build crosswalk rows: Link each GOID to AST node type (`ast_node_type`), chunk ID (`chunk_id` via `_chunk_id()`), evidence JSON (path, lineno, end_lineno, qualname, node_type)

6. **Write Artifacts** (`GOIDBuilder.write_artifacts`)
   - Create `out_dir/goid/` directory
   - Write `goids.parquet` (registry) via `write_goid_registry()`: converts GOID objects to dict rows with `Decimal(goid.h128)` for Parquet compatibility
   - Write `goid_xwalk.parquet` (crosswalk; alias exported as `goid_crosswalk.parquet` in `generate_documents.sh`) via `write_goid_crosswalk()`: normalizes `goid_h128` to Decimal
   - Fallback to JSONL (`goids.jsonl`, `goid_xwalk.jsonl`) if Parquet unavailable (handled by `write_parquet_or_jsonl()`)
   - Optionally ingest into DuckDB catalog if `--ingest` flag set (via `DuckDBCatalog.upsert_goids()` and `upsert_goid_xwalk()`)

**Components Involved**

- `codeintel_rev.cli.enrich._graph_utils.resolve_paths` (path resolution and context creation)
- `codeintel_rev.services.enrich.graph_support.collect_python_files` (file discovery with exclude patterns)
- `codeintel_rev.services.enrich.graph_support.detect_commit` (Git commit hash detection, falls back to "unknown")
- `codeintel_rev.services.enrich.io.collect_ast_artifacts` (AST node extraction via LibCST)
- `codeintel_rev.enrich.goid_builder.GOIDBuilder` (GOID computation and crosswalk generation)
- `codeintel_rev.enrich.graph.io.write_goid_registry`, `write_goid_crosswalk` (Parquet/JSONL writing)

**Key Invariants**

- GOID hashing is deterministic: same `RepoSnapshot` + `EntityDescriptor` → same `goid_h128`.
- Every GOID must have at least one crosswalk entry.
- Module GOIDs are created for every file path, even if the file has no code elements.

**Error Handling & Retries**

- Syntax errors skip the file (logged, no GOIDs generated for that file).
- Parquet write failures fall back to JSONL automatically.

---

### 5.3 Flow: Call Graph Generation (`enrich callgraph`)

**Trigger**

- CLI command: `python -m codeintel_rev.cli.enrich callgraph --repo-root <dir> --out-dir <dir> [--ingest]`
- Code entrypoints: `codeintel_rev.cli.enrich.callgraph.build_callgraph_cli`, `codeintel_rev.services.enrich.graph_steps.build_callgraph_artifacts`

**High-Level Steps**

1. **Resolve Paths** (`resolve_paths`)
   - Same as GOID flow: resolve paths and create `PipelineContext`

2. **Collect Python Files** (`collect_python_files`)
   - Same as GOID flow: discover and filter Python files

3. **Detect Commit** (`detect_commit`)
   - Same as GOID flow: get commit hash or "unknown"

4. **Collect Function Info** (`collect_function_info`)
   - For each Python file:
     - Parse AST via `ast.parse()` with `type_comments=True`
     - Extract function/method definitions with scope information (enclosing classes, nested functions)
     - Generate GOID for each function via `compute_goid()` → `FunctionInfo` objects with `goid`, `rel_path`, `qualname`, `class_stack`, `is_public` (heuristic: not starting with `_`)
   - Aggregate function info list

5. **Build Resolution Context** (`_ResolutionContext.build`)
   - Compute relative paths: `file_path` → repo-relative path via `_relative_path()`
   - Build module name map: `rel_path` → dotted module name via `_module_name_from_rel_path()` (handles `__init__.py` → package)
   - Group functions by module path → `module_functions` dict: `rel_path` → `{name: FunctionInfo}`
   - Group methods by `(module_path, class_name)` → `class_methods` dict: `(rel_path, "Class1.Class2")` → `{name: FunctionInfo}`
   - Build global function/method maps keyed by module name → `global_functions`, `global_class_methods` (for cross-module resolution)
   - Parse import statements per file → `_ImportResolver` objects with alias mappings:
     - `module_aliases`: local name → canonical module name
     - `attr_aliases`: local name → `(module_name, original_name)` tuple
   - Collect known modules set for validation

6. **Collect Call Edges** (`CallGraphBuilder.build`)
   - Initialize `node_map` dict (keyed by `goid_h128`) and `edges` list
   - For each function:
     - Create call graph node → `CallNodeRow` with `goid_h128`, `kind` ("function" or "method"), `arity` (from `info.node.args.args`), `is_public`, `rel_path`
     - Build `_CollectorInputs` with function maps and import resolver for the function's module
     - Visit function AST with `_CallCollector`:
       - `visit_Call()`: For each `ast.Call` node, resolve callee via `_resolve_callee()` → `(FunctionInfo | None, resolved_via, call_kind)`
       - Resolution strategies: `local-symbol`, `class-self`, `class-attr`, `imported-function`, `imported-module`, `imported-attr`, `unresolved`
       - Edge kinds: `direct`, `method`, `attr_call`, `attr` (fallback)
       - Create call edge → `CallEdgeRow` with `caller_goid_h128`, `callee_goid_h128` (nullable), `callsite_path`, `callsite_line`, `callsite_col`, `kind`, `resolved_via`, `confidence` (from `_confidence_for_resolution()`), `evidence_json` (AST unparse, resolver name)
      - `generic_visit()`: Skips nested function/class definitions to prevent incorrect call edges
   - Deduplicate nodes by `goid_h128` → sorted node list
   - Sort edges by `(callsite_path, callsite_line, callsite_col)` → deterministic edge list

7. **Write Artifacts** (`CallGraphBuilder.write_artifacts`)
   - Create `out_dir/graphs/` directory
   - Write `call_nodes.parquet` via `write_call_nodes()` (`call_nodes.jsonl` fallback): normalizes `goid_h128` to Decimal
   - Write `call_edges.parquet` via `write_call_edges()` (`call_edges.jsonl` fallback): normalizes both `caller_goid_h128` and `callee_goid_h128` to Decimal
   - Optionally ingest into DuckDB if `--ingest` flag set (via `DuckDBCatalog.upsert_goids()`, `upsert_call_nodes()`, `upsert_call_edges()`)

**Components Involved**

- `codeintel_rev.cli.enrich._graph_utils.resolve_paths` (path resolution)
- `codeintel_rev.services.enrich.graph_support.collect_python_files` (file discovery)
- `codeintel_rev.services.enrich.graph_support.detect_commit` (commit hash detection)
- `codeintel_rev.enrich.function_index.collect_function_info` (function extraction with GOID generation)
- `codeintel_rev.enrich.callgraph.CallGraphBuilder` (call graph construction)
- `codeintel_rev.enrich.callgraph._CallCollector` (AST visitor for call expressions)
- `codeintel_rev.enrich.callgraph._ImportResolver` (symbol resolution via import parsing)
- `codeintel_rev.enrich.callgraph._ResolutionContext` (function lookup maps and import resolvers)

**Key Invariants**

- Every function definition produces exactly one call graph node.
- Every call expression produces at least one edge (even if callee is unresolved → `callee_goid_h128=None`).
- Edge confidence scores are assigned based on resolution strategy: `local-symbol` (0.95) > `class-self` (0.9) > `imported-function` (0.85) > `imported-module`/`imported-attr`/`class-attr` (~0.8) > `unresolved` (0.25).

**Error Handling & Retries**

- Unresolved calls are recorded with `callee_goid_h128=None` and low confidence; they do not abort the pipeline.
- Import resolution failures degrade gracefully: resolver returns empty aliases, calls marked as `unresolved`.

---

### 5.4 Flow: CFG/DFG Generation (`enrich cfg` / `enrich dfg`)

**Trigger**

- CLI commands: `python -m codeintel_rev.cli.enrich cfg|dfg --repo-root <dir> --out-dir <dir> [--ingest]`
- Code entrypoints: `codeintel_rev.cli.enrich.cfg.build_cfg|build_dfg`, `codeintel_rev.services.enrich.graph_steps.build_cfg_artifacts`

**High-Level Steps**

1. **Resolve Paths** (`resolve_paths`)
   - Same as GOID/callgraph flows: resolve paths and create `PipelineContext`

2. **Collect Python Files** (`collect_python_files`)
   - Same as other graph flows: discover and filter Python files

3. **Detect Commit** (`detect_commit`)
   - Same as other graph flows: get commit hash or "unknown"

4. **Collect Function Info** (`collect_function_info`)
   - Same as call graph flow: extract functions with GOIDs and scope info

5. **Build CFG Per Function** (`_FunctionCFGBuilder.build`)
   - Initialize `_FunctionCFGBuilder` with `FunctionInfo` and `RepoSnapshot`
   - Create entry block (kind="entry") at function start line, exit block (kind="exit") at function end line
   - Create body block for function statements (kind="normal")
   - Add edge: entry → body block (edge_type="fallthrough")
   - Traverse function AST with statement handlers:
     - `_handle_If`: Create parent block, branch block (kind="branch") for condition, true/false blocks, join block; edges: parent→branch ("branch"), branch→true ("true"), branch→false ("false"), true→join ("fallthrough"), false→join ("fallthrough")
     - `_handle_For|While`: Create parent block, loop header block (kind="loop"), body block, back edge (edge_type="loop-back"), exit block; edges: parent→header ("loop-entry"), header→body ("true"), body→header ("loop-back"), header→exit ("false")
     - `_handle_Try`: Create try block, exception handler blocks (kind="exception"), finally block; edges: try→handlers (exception flow), handlers→finally ("fallthrough")
     - `_handle_Return`: Create return block, edge to exit block (edge_type="return"); create fresh continuation block after return for any unreachable statements
     - `_handle_simple`: Append statement to current block, update block line range
   - Record statement metadata in blocks → `stmts_json` array: each element has `kind`, `lineno`, `end_lineno`, `code` (via `_safe_unparse()`)
   - Build line-to-block mapping: `line_to_block` dict for DFG analysis
   - Compute block degrees (`in_degree`, `out_degree`) from edges via `_finalize_degrees()`

6. **Build DFG Edges** (`_DFGAnalyzer.build_edges`)
   - Initialize `_DFGAnalyzer` with `FunctionInfo`, `line_to_block` mapping, entry/exit block indices
   - Record function arguments as definitions in entry block: `_argument_names()` extracts all parameter names
   - Visit function AST tracking variable definitions and uses:
     - `visit_Name` (Load context): Record use → create DFG edge from def block(s) to use block
     - `visit_Assign`: Record def → update `def_blocks` map (variable name → set of block indices)
     - `visit_AugAssign`: Record both use and def (read before write)
     - `visit_For|AsyncFor`: Record def for loop target variable
     - `visit_With`: Record def for optional variable names
     - `visit_comprehension`: Record def for comprehension target
   - Handle phi nodes: If variable has multiple definitions reaching a use (`len(sources) > 1`), mark edge as `via_phi=True`
   - Create DFG edges → `DFGEdgeRow` with `src_block_idx`, `dst_block_idx`, `src_symbol`, `dst_symbol` (same symbol name), `via_phi`, `use_kind` ("def", "use", "read", "write", "update")
   - Sort edges by `(symbol, src_block, dst_block, use_kind)` for deterministic output

7. **Generate Block GOIDs** (`_FunctionCFGBuilder._block_goids`)
   - For each CFG block: Create GOID with `kind="block"`, `qualname` = `{function_qualname or function_name}::block{idx}`, `start_line`/`end_line` from block

8. **Write Artifacts** (`CFGBuilder.write_artifacts`)
   - Create `out_dir/graphs/` directory
   - Write `cfg_blocks.parquet` via `write_cfg_blocks()`: normalizes `function_goid_h128` to Decimal
   - Write `cfg_edges.parquet` via `write_cfg_edges()`: normalizes `function_goid_h128` to Decimal
   - Write `dfg_edges.parquet` via `write_dfg_edges()`: normalizes `function_goid_h128` to Decimal
   - Optionally ingest into DuckDB if flags set (`ingest_cfg` for blocks/edges, `ingest_dfg` for DFG edges)

**Components Involved**

- `codeintel_rev.cli.enrich._graph_utils.resolve_paths` (path resolution)
- `codeintel_rev.services.enrich.graph_support.collect_python_files` (file discovery)
- `codeintel_rev.services.enrich.graph_support.detect_commit` (commit hash detection)
- `codeintel_rev.enrich.function_index.collect_function_info` (function extraction with GOID generation)
- `codeintel_rev.enrich.cfg.CFGBuilder` (CFG/DFG construction orchestrator)
- `codeintel_rev.enrich.cfg._FunctionCFGBuilder` (per-function CFG construction with statement handlers)
- `codeintel_rev.enrich.cfg._DFGAnalyzer` (data-flow analysis via AST visitor)

**Key Invariants**

- Every function has exactly one entry block and one exit block.
- All blocks must be reachable from the entry block (enforced by construction).
- DFG edges connect blocks within the same function only (intra-procedural analysis).

**Error Handling & Retries**

- Functions with empty bodies still produce entry/exit blocks.
- Syntax errors skip the file (no CFG/DFG generated).

---

### 5.5 Flow: Exports Generation (`enrich exports`)

**Trigger**

- CLI command: `python -m codeintel_rev.cli.enrich exports --repo-root <dir> --out-dir <dir>`
- Code entrypoints: `codeintel_rev.cli.enrich.exports.exports`, `codeintel_rev.services.enrich.exports.run_all_exports`

**High-Level Steps**

1. **Scan Repository** (`scan_repo`)
   - Discover Python files matching include/exclude globs (default excludes: `.venv`, `build`, `dist`)
   - Parse each file to validate syntax (via `ast.parse`)
   - Create lightweight `ModuleRecord` objects with path, module name, LOC, inferred tags
   - Compute module name from file path: `_py_module_name()` handles `__init__.py` → package name

2. **Run All Exports** (`run_all_exports`)
   - **Emit Modules JSONL** (`emit_modules_jsonl`): Write `modules.jsonl` with module records (via `record_to_json()` conversion)
   - **Emit Repo Map** (`emit_repo_map`): Write `repo_map.json` with package→module mapping (groups modules by first package segment)
   - **Emit Tag Index** (`emit_tag_index`): Write `tag_index.json` with tag→count mapping
   - **Emit Markdown Sheets** (`emit_markdown_sheets`): Write `sheets/*.md` files summarizing each module (slugified module names as filenames)

**Components Involved**

- `codeintel_rev.services.enrich.scan.scan_repo` (lightweight repository scan)
- `codeintel_rev.services.enrich.exports.run_all_exports` (export orchestration)
- `codeintel_rev.services.enrich.exports.emit_modules_jsonl`, `emit_repo_map`, `emit_tag_index`, `emit_markdown_sheets` (individual export functions)
- `codeintel_rev.services.enrich.exports.record_to_json` (ModuleRecord → JSON conversion)

**Key Invariants**

- Module records are sorted by path for deterministic output.
- Tag inference is optional (`--infer-tags` flag, default: True); can be disabled for custom tagging.
- Markdown filenames use slugified module names (dots → dashes).

**Error Handling & Retries**

- Syntax errors skip the file (logged at WARNING level, file excluded from exports).
- File read errors are logged and skipped (file excluded from exports).

---

### 5.6 Flow: Analytics CLI (`python -m codeintel_rev.cli.enrich_analytics`)

**Trigger**

- CLI commands: `graph`, `uses`, `typedness`, `function-metrics`, `function-types`, `doc`
- Code entrypoint: `codeintel_rev.cli.enrich_analytics` (Typer app attaching `shared_options`)

**High-Level Steps**

1. Execute enrichment pipeline via `execute_pipeline_or_exit()` (reuses `enrich_pipeline all` behavior).
2. Depending on subcommand:
   - `graph`: `write_graph_outputs()` → symbol graph + import graph.
   - `uses`: `write_uses_output()` → symbol use edges.
   - `typedness`: `write_typedness_output()` + `write_static_diagnostics_output()`.
   - `function-metrics`: `write_function_metrics_output()`.
   - `function-types`: `write_function_types_output()`.
   - `doc`: `write_doc_output()` (docstring coverage/quality).
3. Each writer persists Parquet with JSONL fallback under `out/analytics/` or `out/graphs/`.

**Key Notes**

- Uses the same CLI flag surface as `enrich_pipeline` (`--root`, `--scip`, `--out`, `--emit-ast`, etc.).
- Dry-run mode validates configuration without writing artifacts.
- Graph/uses commands are used by `generate_documents.sh` as backfills when import/use graph files are missing.

---

### 5.7 Flow: Coverage, Test, and Risk Analytics (`enrich_analytics coverage-detailed|test-analytics|risk-factors`)

**Trigger**

- CLI commands (all under `codeintel_rev.cli.enrich_analytics`):
  - `coverage-detailed --coverage-file <.coverage>` → coverage lines + function aggregation.
  - `test-analytics --coverage-file <.coverage> --pytest-report <pytest-report.json>` → test catalog + test coverage edges.
  - `risk-factors` → GOID risk factors (requires coverage outputs).

**High-Level Steps**

1. **Coverage Detailed** (`run_coverage_analytics`)
   - Load `repo_map.json` and GOID registry from `<out>/goid/`.
   - Extract per-line coverage via `iter_coverage_lines()` → write `analytics/coverage/coverage_lines.parquet`.
   - Aggregate to per-function metrics via `aggregate_coverage_functions()` → write `analytics/coverage/coverage_functions.parquet`.
2. **Test Analytics** (`run_test_analytics`)
   - Load GOID registry and `coverage_functions.jsonl`.
   - Build test catalog from pytest JSON report via `build_test_catalog()` → `analytics/tests/test_catalog.parquet`.
   - Map dynamic coverage contexts to functions via `build_test_coverage_edges()` → `analytics/tests/test_coverage_edges.parquet`.
3. **Risk Factors** (`run_risk_factors`)
   - Load analytics inputs (coverage functions, function metrics, function types, hotspots, typedness, static diagnostics, module metadata, test counts).
   - Compute composite risk scores per function GOID via `build_goid_risk_factors()` → `analytics/risk/goid_risk_factors.parquet`.

**Key Invariants**

- Coverage analytics require coverage.py data collected with dynamic contexts for test edges.
- Test analytics depend on prior coverage aggregation (`coverage_functions.jsonl`) and pytest JSON report.
- Risk factors require coverage outputs and function analytics; missing inputs yield partial rows but never crash the pipeline (rows skip missing paths).

**Error Handling**

- Missing inputs cause warning logs and skipped outputs (e.g., no `.coverage` → no coverage artifacts).
- File normalization errors (paths outside repo) are skipped; processing continues for remaining files.

## 6. Static Structure: Layers, Modules, and Dependencies

### 6.1 Layer Overview

We structure the metadata generation system into the following logical layers:

1. **CLI Layer** (`codeintel_rev.cli.enrich.*`) – Entry points and command orchestration
2. **Service Layer** (`codeintel_rev.services.enrich.*`) – Reusable pipeline stages and context management
3. **Builder Layer** (`codeintel_rev.enrich.*`) – Pure transformation logic (GOID, call graph, CFG builders)
4. **IO Layer** (`codeintel_rev.enrich.graph.io`, `codeintel_rev.services.enrich.io`) – File format serialization (Parquet, JSONL)
5. **Foundation Layer** (`codeintel_rev.ids.goid`, `codeintel_rev.enrich.ast_indexer`) – Core algorithms (hashing, AST extraction)

**Dependency Rules**

- CLI layer may import from Service and Builder layers.
- Service layer may import from Builder and IO layers.
- Builder layer may import from Foundation layer only.
- IO layer may import from Foundation layer only.
- Foundation layer has no dependencies on other layers.

### 6.2 Module Catalog

#### Module: `codeintel_rev/cli/enrich/__main__.py`

**Role**

Typer application entry point registering all enrichment subcommands. Delegates to individual command modules.

**Public Surface**

- `app`: Typer application instance
- `main()`: Entry point function

**Dependencies**

- Imports subcommand modules for side effects (command registration)
- Uses: `codeintel_rev.cli.enrich.goids`, `callgraph`, `cfg`, `exports`, `scan`, `analytics`

**Invariants**

- All subcommands must be registered via `@app.command()` decorator.
- Shared options are defined in `codeintel_rev.cli.enrich.common.shared_options`.

**Extension Points**

- To add a new command: Create module in `codeintel_rev/cli/enrich/`, import it in `__main__.py`, register with `@app.command()`.

---

#### Module: `codeintel_rev/cli/enrich/common.py`

**Role**

Shared CLI helpers: option definitions, context state management, pipeline execution, error handling.

**Public Surface**

- `shared_options()`: Typer callback capturing global options (`--root`, `--scip`, `--out`, etc.)
- `ensure_state()`: Return or create `CLIContextState` from Typer context
- `execute_pipeline()`: Execute pipeline and return `PipelineResult`
- `handle_stage_error()`: Render `StageError` and exit with code 1
- `normalize_global_cli_args()`: Reorder argv to move global flags before command name

**Dependencies**

- Calls into: `codeintel_rev.services.enrich.scan.run_pipeline`
- Uses: `codeintel_rev.services.enrich.context.CLIContextState`, `PipelineOptions`

**Invariants**

- Global options must be normalized before Typer parses them (handled by `normalize_global_cli_args`).
- Pipeline execution must handle `StageError` exceptions and exit gracefully.

**Extension Points**

- To add a new global option: Add `typer.Option` to `common.py`, include in `shared_options()`, add to `_GLOBAL_VALUE_FLAGS` or `_GLOBAL_BOOL_FLAGS`.

---

#### Module: `codeintel_rev/cli/enrich/_graph_utils.py`

**Role**

Shared helpers for graph/GOID CLI commands: path resolution, DuckDB catalog access, Python file collection.

**Public Surface**

- `resolve_paths()`: Resolve application paths and create `PipelineContext` from repo root and output directory
- `open_catalog()`: Open or create DuckDB catalog for graph/GOID operations
- Re-exports: `DEFAULT_EXCLUDES`, `collect_python_files`, `detect_commit` from `codeintel_rev.services.enrich.graph_support`

**Dependencies**

- Uses: `codeintel_rev.config.paths.resolve_application_paths`, `ResolvedPaths`
- Uses: `codeintel_rev.services.enrich.context.PipelineContext`
- Uses: `codeintel_rev.io.duckdb_catalog.DuckDBCatalog`
- Uses: `codeintel_rev.services.enrich.graph_support.collect_python_files`, `detect_commit`

**Invariants**

- Path resolution validates paths via `validate_paths()` before creating context.
- DuckDB catalog creates vectors directory if it doesn't exist.

**Extension Points**

- Graph commands (`goids`, `callgraph`, `cfg`, `dfg`) use this module for consistent path resolution and catalog access.

---

#### Module: `codeintel_rev/cli/enrich/to_duckdb.py`

**Role**

CLI command for writing scan results directly to DuckDB tables.

**Public Surface**

- `to_duckdb()`: CLI command (`enrich to-duckdb`) that scans repository and persists module records to DuckDB

**Dependencies**

- Uses: `codeintel_rev.services.enrich.scan.scan_repo`
- Uses: `codeintel_rev.services.enrich.to_duckdb.write_to_duckdb`

**Invariants**

- DuckDB path defaults to `{out_dir}/enrich.duckdb` if not specified.
- Table name defaults to `"modules"` but can be overridden.

**Extension Points**

- To add new table types: Extend `write_to_duckdb()` service function, add CLI options if needed.

---

#### Module: `codeintel_rev/cli/enrich/audit.py`

**Role**

CLI command for running completeness audits on enrichment artifacts.

**Public Surface**

- `audit()`: CLI command (`enrich audit`) that validates completeness of modules.jsonl and emits a JSON report

**Dependencies**

- Uses: `codeintel_rev.services.enrich.completeness.run_completeness_audit`

**Invariants**

- Requires `modules.jsonl` file as input.
- Outputs JSON report to specified path.

**Extension Points**

- To add new audit checks: Extend `run_completeness_audit()` service function.

---

#### Module: `codeintel_rev/services/enrich/scan.py`

**Role**

Pipeline preparation and module scanning: loads SCIP index, type signals, coverage, config files, tagging rules; scans Python files and builds module records.

**Public Surface**

- `prepare_pipeline()`: Materialize `PreparedPipeline` with context and file list
- `scan_modules()`: Scan Python files and return `ModuleRecord` rows + symbol edges
- `run_pipeline()`: Execute full pipeline and return `PipelineResult`
- `scan_repo()`: Lightweight repository scan returning `ModuleRecord` list

**Dependencies**

- Calls into: `codeintel_rev.enrich.scip_reader.SCIPIndex.load`
- Calls into: `codeintel_rev.typedness.collect_type_signals`
- Calls into: `codeintel_rev.coverage_ingest.collect_coverage`
- Calls into: `codeintel_rev.config_indexer.index_config_files`
- Calls into: `codeintel_rev.enrich.tagging.load_rules`
- Calls into: `codeintel_rev.enrich.pipeline_helpers.build_module_row`
- Calls into: `codeintel_rev.services.enrich.analytics.compute_pipeline_analytics`
- Calls into: `codeintel_rev.services.enrich.graph_steps.build_*_artifacts`

**Invariants**

- SCIP index path is required (raises `typer.BadParameter` if missing).
- Module records are validated via `ModuleRecordModel` before aggregation.
- File discovery respects `--only` globs and default exclusions.

**Extension Points**

- To add a new pipeline input: Add collection function (e.g., `collect_*_map`), call in `prepare_pipeline()`, attach to `LegacyPipelineContext`.

---

#### Module: `codeintel_rev/enrich/goid_builder.py`

**Role**

GOID registry and crosswalk generation: transforms AST node rows into GOID artifacts with deterministic hashing.

**Public Surface**

- `GOIDBuilder`: Builder class with `build()` and `write_artifacts()` methods
- `run_goid_build()`: Convenience function for simple workflows

**Dependencies**

- Uses: `codeintel_rev.enrich.ast_indexer.AstNodeRow`
- Uses: `codeintel_rev.ids.goid.compute_goid`, `EntityDescriptor`, `RepoSnapshot`
- Uses: `codeintel_rev.enrich.graph.io.write_goid_registry`, `write_goid_crosswalk`

**Invariants**

- GOID hashing must be deterministic: same inputs → same hash.
- Every GOID must have at least one crosswalk entry.
- Module GOIDs are created for every unique file path.

**Extension Points**

- To add new GOID kinds: Extend `_kind_for_node()` to map AST node types to `GoidKind` values.
- To add crosswalk fields: Extend `CrosswalkRow` TypedDict, populate in `build()`.

---

#### Module: `codeintel_rev/enrich/callgraph.py`

**Role**

Static call graph construction: resolves function calls via symbol resolution heuristics and produces call nodes/edges.

**Public Surface**

- `CallGraphBuilder`: Builder class with `build()` and `write_artifacts()` methods
- `CallNodeRow`, `CallEdgeRow`: TypedDict definitions for serialized rows

**Dependencies**

- Uses: `codeintel_rev.enrich.function_index.collect_function_info`, `FunctionInfo`
- Uses: `codeintel_rev.ids.goid.GOID`
- Uses: `codeintel_rev.enrich.graph.io.write_call_nodes`, `write_call_edges`
- Uses: Python `ast` module for AST traversal

**Invariants**

- Every function definition produces exactly one call graph node.
- Every call expression produces at least one edge (unresolved calls have `callee_goid_h128=None`).
- Edge confidence scores are assigned based on resolution strategy.

**Extension Points**

- To improve call resolution: Extend `_CallCollector._resolve_callee()` with new heuristics.
- To add edge metadata: Extend `CallEdgeRow` TypedDict, populate in `visit_Call()`.

---

#### Module: `codeintel_rev/enrich/cfg.py`

**Role**

Control-flow and data-flow graph construction: builds CFG blocks/edges and DFG edges for Python functions.

**Public Surface**

- `CFGBuilder`: Builder class with `build()` and `write_artifacts()` methods
- `CFGBlockRow`, `CFGEdgeRow`, `DFGEdgeRow`: TypedDict definitions for serialized rows

**Dependencies**

- Uses: `codeintel_rev.enrich.function_index.collect_function_info`, `FunctionInfo`
- Uses: `codeintel_rev.ids.goid.compute_goid`, `EntityDescriptor`
- Uses: `codeintel_rev.enrich.graph.io.write_cfg_blocks`, `write_cfg_edges`, `write_dfg_edges`
- Uses: Python `ast` module for AST traversal

**Invariants**

- Every function has exactly one entry block and one exit block.
- All blocks must be reachable from the entry block.
- DFG edges are intra-procedural only (within the same function).

**Extension Points**

- To add new control-flow constructs: Add `_handle_*` method to `_FunctionCFGBuilder` for AST node type.
- To improve DFG analysis: Extend `_DFGAnalyzer` visitor methods for new AST patterns.

---

#### Module: `codeintel_rev/services/enrich/exports.py`

**Role**

Export orchestration: writes modules.jsonl, repo_map.json, tag_index.json, markdown sheets, analytics tables, graph outputs.

**Public Surface**

- `run_all_exports()`: Emit all export artifacts for simplified CLI
- `write_exports_outputs()`: Write modules, repo map, tag index, markdown
- `write_graph_outputs()`: Write symbol graph, import graph edges
- `write_uses_output()`: Write symbol use edges
- `write_function_metrics_output()`: Write per-function metrics
- `write_function_types_output()`: Write per-function typedness
- `write_typedness_output()`: Write file-level typedness analytics
- `write_hotspot_output()`: Write hotspot analytics
- `write_coverage_output()`: Write coverage analytics
- `write_config_output()`: Write config index and values
- `write_static_diagnostics_output()`: Write type checker error counts
- `write_ast_outputs()`: Write AST nodes and metrics

**Dependencies**

- Uses: `codeintel_rev.services.enrich.io.write_*` functions for file I/O
- Uses: `codeintel_rev.enrich.graph_builder.write_import_graph`
- Uses: `codeintel_rev.uses_builder.write_use_graph`
- Uses: `codeintel_rev.services.enrich.function_metrics.build_function_metrics`
- Uses: `codeintel_rev.services.enrich.function_types.build_function_types`

**Invariants**

- All exports write to deterministic paths under `out_dir`.
- Parquet files are written with JSONL fallback.
- Module records are sorted before writing for deterministic output.

**Extension Points**

- To add a new export format: Create `write_*_output()` function, call from appropriate CLI command or `run_all_exports()`.

---

#### Module: `codeintel_rev/services/enrich/graph_steps.py`

**Role**

Service-level graph artifact construction: orchestrates builders with context management and DuckDB ingestion.

**Public Surface**

- `build_goid_artifacts()`: Build GOID registry and crosswalk
- `build_callgraph_artifacts()`: Build call graph nodes and edges
- `build_cfg_artifacts()`: Build CFG blocks/edges and DFG edges

**Dependencies**

- Uses: `codeintel_rev.enrich.goid_builder.GOIDBuilder`
- Uses: `codeintel_rev.enrich.callgraph.CallGraphBuilder`
- Uses: `codeintel_rev.enrich.cfg.CFGBuilder`
- Uses: `codeintel_rev.services.enrich.graph_support.collect_python_files`
- Uses: `codeintel_rev.services.enrich.io.collect_ast_artifacts`
- Uses: `codeintel_rev.io.duckdb_catalog.DuckDBCatalog` for ingestion

**Invariants**

- Graph steps are optional and can be skipped if flags are not set.
- DuckDB ingestion is optional (`--ingest` flag).
- File discovery respects `--include` globs.

**Extension Points**

- To add a new graph type: Create builder class, add `build_*_artifacts()` function, register CLI command.

---

#### Module: `codeintel_rev/enrich/ast_indexer.py`

**Role**

AST node extraction: parses Python files via LibCST, extracts AST nodes with qualnames and metadata, computes AST metrics.

**Public Surface**

- `collect_ast_nodes_from_tree()`: Extract `AstNodeRow` objects from LibCST module
- `compute_ast_metrics()`: Compute `AstMetricsRow` from AST node list
- `AstNodeRow`, `AstMetricsRow`: Dataclass definitions for serialized rows
- `write_ast_parquet()`: Write AST nodes and metrics to Parquet

**Dependencies**

- Uses: `libcst` for parsing Python source code
- Uses: Python `ast` module for AST node types
- Uses: `pyarrow` for Parquet writing

**Invariants**

- AST nodes must preserve source location information (line numbers, column offsets).
- Qualnames must be computed correctly for nested scopes (classes, nested functions).

**Extension Points**

- To extract additional AST metadata: Extend `AstNodeRow` dataclass, populate in `collect_ast_nodes_from_tree()`.

---

#### Module: `codeintel_rev/ids/goid.py`

**Role**

GOID computation: deterministic hashing of code entities based on repository snapshot and entity descriptor.

**Public Surface**

- `compute_goid()`: Compute GOID hash from `RepoSnapshot` and `EntityDescriptor`
- `GOID`: Dataclass with `h128` (hash), `urn` (textual identifier)
- `EntityDescriptor`: Dataclass describing entity (language, kind, rel_path, qualname, line numbers)
- `RepoSnapshot`: Dataclass describing repository (repo name, commit hash)

**Dependencies**

- Uses: `xxhash` library for XXH128 hashing (fast, non-cryptographic hash)
- Uses: String formatting for URN construction

**Implementation Details**

- GOID hashing normalizes all inputs (repo name, commit, language, kind, path, qualname, line numbers, SCIP symbol) before hashing.
- URN format: `goid:1/{repo_fp}@{commit}:/{rel_path}#{language}:{kind}:{qual_segment}?s={start}&e={end}&scip={scip_fp}` where `repo_fp` is a 12-character hex fingerprint of the repo name (via XXH64).
- Hash is computed as a signed 128-bit integer (handles overflow by subtracting 2^128 if >= 2^127).

**Invariants**

- GOID hashing must be deterministic: same inputs → same hash.
- Hash collisions are prevented via content-based hashing (includes qualname, path, line numbers).

**Extension Points**

- To change hashing algorithm: Modify `compute_goid()` implementation (requires migration plan for existing artifacts).

---

## 7. Data & Metadata Structures

### 7.1 GOID Registry Schema (`goids.parquet` / `goids.jsonl`)

**Purpose**: Canonical registry of all code entities with stable identifiers.

**Columns**:

| Column | Type | Description |
|--------|------|-------------|
| `goid_h128` | decimal(38) | 128-bit integer hash key (canonical foreign key), computed via xxhash (XXH128) |
| `urn` | string | Human-readable GOID URN: `goid:1/{repo_fp}@{commit}:/{rel_path}#{language}:{kind}:{qual_segment}?s={start}&e={end}&scip={scip_fp}` where `repo_fp` is a 12-character hex fingerprint of the repo name |
| `repo` | string | Repository slug |
| `commit` | string | Commit SHA at analysis time |
| `rel_path` | string | Repo-relative file path |
| `language` | string | Language tag (`python`) |
| `kind` | string | Entity kind (`module`, `function`, `class`, `method`, `block`) |
| `qualname` | string | Dotted qualified name |
| `start_line` | int | First line (1-based) |
| `end_line` | int/null | Last line if bounded |

**Note**: `README_METADATA.md` documents a `created_at` timestamp field, but `write_goid_registry()` does not include this field in the written Parquet/JSONL files. Timestamps may be added downstream or represent a planned schema extension.

**Generation**: `codeintel_rev.enrich.goid_builder.GOIDBuilder.build()` → `codeintel_rev.enrich.graph.io.write_goid_registry()`

---

### 7.2 GOID Crosswalk Schema (`goid_xwalk.parquet` / `goid_xwalk.jsonl`)

**Purpose**: Maps GOIDs to multiple structural sources (AST nodes, SCIP symbols, chunk IDs).

**Columns**:

| Column | Type | Description |
|--------|------|-------------|
| `goid_h128` | decimal(38) | GOID hash (foreign key to `goids.parquet`) |
| `ast_node_type` | string/null | AST node type (`FunctionDef`, `ClassDef`, `Module`, etc.) |
| `chunk_id` | string/null | Chunk identifier (`<path>:<start>:<end>`) |
| `evidence_json` | json/null | Additional context (path, lineno, end_lineno, qualname, node_type) |

**Note**: The `CrosswalkRow` TypedDict definition (`codeintel_rev.ids.goid.CrosswalkRow`) includes additional optional fields (`scip_symbol`, `chunk_row_id`, `cst_node_id`, `git_blob_sha`, `git_commit_sha`) that are not currently populated by `GOIDBuilder.build()`. Output filenames use `goid_xwalk.*`; `generate_documents.sh` copies them to `goid_crosswalk.*` for compatibility.

**Generation**: `codeintel_rev.enrich.goid_builder.GOIDBuilder.build()` → `codeintel_rev.enrich.graph.io.write_goid_crosswalk()`

---

### 7.3 Call Graph Nodes Schema (`call_nodes.parquet` / `call_nodes.jsonl`)

**Purpose**: Callable entities (functions, methods) in the call graph.

**Columns**:

| Column | Type | Description |
|--------|------|-------------|
| `goid_h128` | decimal(38) | GOID hash for the callable |
| `language` | string | Language (`python`) |
| `kind` | string | Callable kind (`function`, `method`) |
| `arity` | int | Number of positional parameters |
| `is_public` | bool | Heuristic based on naming (leading underscore => false) |
| `rel_path` | string | Repo-relative file path |

**Generation**: `codeintel_rev.enrich.callgraph.CallGraphBuilder.build()` → `codeintel_rev.enrich.graph.io.write_call_nodes()`

---

### 7.4 Call Graph Edges Schema (`call_edges.parquet` / `call_edges.jsonl`)

**Purpose**: Call sites linking callers to callees.

**Columns**:

| Column | Type | Description |
|--------|------|-------------|
| `caller_goid_h128` | decimal(38) | GOID hash of the caller |
| `callee_goid_h128` | decimal(38)/null | GOID hash of the callee (null if unresolved) |
| `callsite_path` | string/null | File path holding the call expression |
| `callsite_line` | int/null | 1-based line number |
| `callsite_col` | int/null | Column offset |
| `language` | string | Language at the callsite |
| `kind` | string | Edge kind (`direct`, `method`, `attr_call`, `attr`) |
| `resolved_via` | string | Provenance (`local-symbol`, `class-self`, `class-attr`, `imported-function`, `imported-module`, `imported-attr`, `unresolved`) |
| `confidence` | float | Confidence score [0,1] derived from `resolved_via` |
| `evidence_json` | json | Additional context (AST text snippets, resolver name) |

**Generation**: `codeintel_rev.enrich.callgraph.CallGraphBuilder.build()` → `codeintel_rev.enrich.graph.io.write_call_edges()`

---

### 7.5 CFG Blocks Schema (`cfg_blocks.parquet` / `cfg_blocks.jsonl`)

**Purpose**: Basic blocks in control-flow graphs.

**Columns**:

| Column | Type | Description |
|--------|------|-------------|
| `function_goid_h128` | decimal(38) | GOID hash of the function owning the blocks |
| `block_idx` | int | Stable block index (0-based, assigned during CFG construction) |
| `kind` | string | Block kind (`entry`, `body`, `exit`, `branch`, `loop`, `exception`, `normal`) |
| `start_line` | int/null | First line covered by the block (1-based) |
| `end_line` | int/null | Last line covered by the block (1-based) |
| `stmts_json` | json | Serialized AST metadata array: each element has `kind`, `lineno`, `end_lineno`, `code` |
| `in_degree` | int | Number of predecessor edges (computed after all edges are added) |
| `out_degree` | int | Number of successor edges (computed after all edges are added) |

**Note**: `README_METADATA.md` documents additional fields (`block_id`, `label`, `file_path`) that are not present in the `CFGBlockRow` TypedDict or written by `write_cfg_blocks()`. These may be computed downstream or represent a planned schema extension.

**Generation**: `codeintel_rev.enrich.cfg.CFGBuilder.build()` → `codeintel_rev.enrich.graph.io.write_cfg_blocks()`

---

### 7.6 CFG Edges Schema (`cfg_edges.parquet` / `cfg_edges.jsonl`)

**Purpose**: Control-flow edges between blocks.

**Columns**:

| Column | Type | Description |
|--------|------|-------------|
| `function_goid_h128` | decimal(38) | Owner function |
| `src_block_idx` | int | Source block index |
| `dst_block_idx` | int | Destination block index |
| `edge_type` | string | Edge type (`fallthrough`, `true`, `false`, `loop`, `loop-entry`, `loop-back`, `exception`, `return`) |
| `cond_json` | json/null | Serialized AST of the guard if applicable (contains `expr`, `lineno`, `end_lineno`) |

**Note**: `README_METADATA.md` documents `src`/`dst` fields (canonical node IDs) that are not present in the `CFGEdgeRow` TypedDict or written by `write_cfg_edges()`. These may be computed downstream as `{function_goid}:block{idx}`.

**Generation**: `codeintel_rev.enrich.cfg.CFGBuilder.build()` → `codeintel_rev.enrich.graph.io.write_cfg_edges()`

---

### 7.7 DFG Edges Schema (`dfg_edges.parquet` / `dfg_edges.jsonl`)

**Purpose**: Data-flow edges tracking variable definitions and uses.

**Columns**:

| Column | Type | Description |
|--------|------|-------------|
| `function_goid_h128` | decimal(38) | Function owning the edge |
| `src_block_idx` | int | Block containing the definition |
| `dst_block_idx` | int | Block containing the use |
| `src_symbol` | string | Variable or temporary defined at the source |
| `dst_symbol` | string | Symbol referenced at the destination |
| `via_phi` | bool | True when this edge models a merge (phi) node |
| `use_kind` | string | Use kind (`read`, `write`, `update`, `def`) |

**Generation**: `codeintel_rev.enrich.cfg._DFGAnalyzer.build_edges()` → `codeintel_rev.enrich.graph.io.write_dfg_edges()`

---

### 7.8 Module Records Schema (`modules.jsonl`)

**Purpose**: Per-module metadata including path, tags, metrics, ownership.

**Fields**: See `codeintel_rev.enrich.models.ModuleRecord` and `codeintel_rev.services.enrich.models.ModuleRecord` for full schema. Key fields:

- `path`: Repo-relative file path
- `module`: Dotted module name
- `language`: Language tag (`python`)
- `loc`: Lines of code
- `tags`: List of semantic tags
- `meta`: Additional metadata (type errors, annotation ratios, ownership, etc.)

**Generation**: `codeintel_rev.services.enrich.scan.scan_modules()` → `codeintel_rev.services.enrich.exports.write_modules_json()`

---

### 7.9 Import Graph Edges Schema (`import_graph_edges.parquet` / `import_graph_edges.jsonl`)

**Purpose**: Directed edges between modules representing import statements.

**Columns**:

| Column | Type | Description |
|--------|------|-------------|
| `src_module` | string | Source module name |
| `dst_module` | string | Target module imported by the source |
| `src_fan_out` | int | Out-degree of the source module |
| `dst_fan_in` | int | In-degree of the destination module |
| `cycle_group` | int | Strongly connected component identifier |

**Generation**: `codeintel_rev.enrich.graph_builder.write_import_graph()` → `codeintel_rev.services.enrich.exports.write_graph_outputs()`

---

### 7.10 Symbol Use Edges Schema (`symbol_use_edges.parquet` / `symbol_use_edges.jsonl`)

**Purpose**: SCIP-based def→use relationships.

**Columns**:

| Column | Type | Description |
|--------|------|-------------|
| `symbol` | string | SCIP symbol identifier |
| `def_path` | string | Repo-relative path where the symbol is defined |
| `use_path` | string | Repo-relative path where the symbol is referenced |
| `same_file` | bool | True when definition and use share the same file |
| `same_module` | bool | True when both paths map to the same module |

**Generation**: `codeintel_rev.uses_builder.build_use_graph()` → `codeintel_rev.services.enrich.exports.write_uses_output()`

---

### 7.11 Coverage Lines Schema (`coverage_lines.parquet` / `coverage_lines.jsonl`)

**Purpose**: Line-level coverage measurements from coverage.py (with dynamic contexts when available).

**Columns**:

| Column | Type | Description |
|--------|------|-------------|
| `repo` | string | Repository identifier |
| `commit` | string | Commit hash used for analysis |
| `rel_path` | string | Repo-relative file path |
| `line` | int | Executable line number |
| `is_executable` | bool | True when coverage identifies the line as executable |
| `is_covered` | bool | True when executed in the collected coverage data |
| `hits` | int | Simple hit counter (1 for covered, 0 otherwise) |
| `context_count` | int | Number of dynamic contexts that hit the line (0 if contexts not available) |
| `created_at` | string | ISO8601 timestamp |

**Generation**: `codeintel_rev.services.enrich.coverage_pipeline.run_coverage_analytics()` → `iter_coverage_lines()` → `write_coverage_lines()`

---

### 7.12 Coverage Functions Schema (`coverage_functions.parquet` / `coverage_functions.jsonl`)

**Purpose**: Aggregated coverage metrics per function GOID.

**Columns**:

| Column | Type | Description |
|--------|------|-------------|
| `function_goid_h128` | string | Function GOID hash |
| `urn` | string | GOID URN |
| `repo` | string | Repository identifier |
| `commit` | string | Commit hash |
| `rel_path` | string | Repo-relative file path |
| `language` | string | `python` |
| `kind` | string | GOID kind (`function` or `method`) |
| `qualname` | string | Qualified function name |
| `start_line` | int | Function start line |
| `end_line` | int | Function end line |
| `executable_lines` | int | Executable line count within span |
| `covered_lines` | int | Covered line count within span |
| `coverage_ratio` | float/null | `covered_lines / executable_lines` or null if no executable lines |
| `tested` | bool | True when any line was covered |
| `untested_reason` | string | Empty when tested; `no_executable_code` or `no_tests` otherwise |
| `created_at` | string | ISO8601 timestamp |

**Generation**: `aggregate_coverage_functions()` → `write_coverage_functions()`

---

### 7.13 Test Catalog Schema (`test_catalog.parquet` / `test_catalog.jsonl`)

**Purpose**: Metadata for collected pytest tests and their GOID mappings.

**Columns**:

| Column | Type | Description |
|--------|------|-------------|
| `test_id` | string | Pytest node id (`path::qualname`) |
| `test_goid_h128` | string/null | GOID for the test function if resolved |
| `urn` | string/null | GOID URN for the test |
| `repo` | string | Repository identifier |
| `commit` | string | Commit hash |
| `rel_path` | string | Repo-relative path of the test file |
| `qualname` | string/null | Test qualified name (class + function) |
| `kind` | string | `function` or `parametrized_case` |
| `status` | string | Pytest outcome (`passed`, `failed`, etc.) |
| `duration_ms` | float | Duration in milliseconds |
| `markers` | array<string> | Sorted pytest markers |
| `parametrized` | bool | True when node id contained parameters |
| `flaky` | bool | True when `flaky` marker present |
| `created_at` | string | ISO8601 timestamp |

**Generation**: `codeintel_rev.services.enrich.coverage_pipeline.run_test_analytics()` → `build_test_catalog()` → `write_test_catalog()`

---

### 7.14 Test Coverage Edges Schema (`test_coverage_edges.parquet` / `test_coverage_edges.jsonl`)

**Purpose**: Edges linking tests to covered functions using dynamic coverage contexts.

**Columns**:

| Column | Type | Description |
|--------|------|-------------|
| `test_id` | string | Pytest node id |
| `test_goid_h128` | string/null | GOID for the test node if resolved |
| `function_goid_h128` | string | Target function GOID |
| `urn` | string | Function GOID URN |
| `repo` | string | Repository identifier |
| `commit` | string | Commit hash |
| `rel_path` | string | Function path |
| `qualname` | string | Function qualified name |
| `covered_lines` | int | Lines executed by the test within the function span |
| `executable_lines` | int | Executable lines within the function span |
| `coverage_ratio` | float/null | Covered/executable ratio for this test-function pair |
| `last_status` | string | Latest recorded status for the test (`passed`, `failed`, etc.) |
| `created_at` | string | ISO8601 timestamp |

**Generation**: `build_test_coverage_edges()` → `write_test_coverage_edges()`

---

### 7.15 GOID Risk Factors Schema (`goid_risk_factors.parquet` / `goid_risk_factors.jsonl`)

**Purpose**: Composite risk signals per function GOID derived from coverage, complexity, typedness, hotspots, static diagnostics, and test outcomes.

**Columns (selected)**:

| Column | Type | Description |
|--------|------|-------------|
| `function_goid_h128` | string | Function GOID |
| `urn` | string | GOID URN |
| `rel_path` | string | Repo-relative file path |
| `qualname` | string | Function qualified name |
| `loc` / `logical_loc` | int/null | Lines of code metrics from function metrics |
| `cyclomatic_complexity` | int/null | Complexity from function metrics |
| `complexity_bucket` | string/null | Complexity bucket |
| `typedness_bucket` | string/null | Typedness bucket for the function |
| `typedness_source` | string/null | Source of typedness data |
| `hotspot_score` | float/null | File-level hotspot score |
| `file_typed_ratio` | float/null | File-level typedness ratio |
| `static_error_count` | int/null | Static diagnostic count for file |
| `executable_lines` / `covered_lines` / `coverage_ratio` | numeric | Coverage metrics from coverage functions |
| `tested` | bool/null | Whether any test covered the function |
| `test_count` / `failing_test_count` | int | Number of tests touching the function |
| `last_test_status` | string | Last observed test status (`passed`, `failed`, `untested`, etc.) |
| `risk_score` | float | Composite weighted risk score |
| `risk_level` | string | `high`, `medium`, or `low` thresholded from `risk_score` |
| `tags` | array<string> | Tags from module metadata (e.g., `overlay-needed`) |
| `owners` | array<string> | Ownership labels when available |
| `created_at` | string | ISO8601 timestamp |

**Generation**: `codeintel_rev.services.enrich.coverage_pipeline.run_risk_factors()` → `build_goid_risk_factors()` → `write_risk_factors()`

---

## 8. Cross-Cutting Concerns

### 8.1 Configuration Management

**Pattern**

- Configuration is passed via CLI options (`--root`, `--scip`, `--out`, etc.).
- Options are captured in `PipelineOptions` dataclass and stored in `CLIContextState`.
- No global configuration files; all settings are explicit per command invocation.

**Rules**

- Always access config via `PipelineOptions` or `CLIContextState`, never directly via environment variables.
- New configuration options must be added to `codeintel_rev.cli.enrich.common` with `typer.Option` definitions.

**Anti-Patterns**

- Do **not**: Read env vars directly in business logic; use CLI options instead.
- Do **not**: Modify `PipelineOptions` at runtime; treat as immutable after creation.

---

### 8.2 Logging & Observability

**Pattern**

- Use Python `logging` module with module-level loggers: `LOGGER = logging.getLogger(__name__)`.
- Pipeline stages use `_stage()` context manager for structured logging with metadata.
- Log levels: `INFO` for progress, `WARNING` for skipped files, `ERROR` for failures.

**Rules**

- Log file processing progress at `INFO` level: "Processing N files", "Wrote M artifacts".
- Log syntax errors and skipped files at `WARNING` level with file path context.
- Log pipeline failures at `ERROR` level with exception details.

**Anti-Patterns**

- Do **not**: Use `print()` statements; use logging instead.
- Do **not**: Log sensitive data (API keys, file contents) at any level.

---

### 8.3 Error Handling

**Pattern**

- Pipeline stages raise `codeintel_rev.enrich.errors.StageError` for recoverable failures.
- CLI commands catch `StageError` and exit with code 1 after logging diagnostics.
- Syntax errors in source files are logged and skipped; they do not abort the pipeline.

**Rules**

- Always use `raise ... from e` to preserve exception chains.
- Unresolved calls in call graph are recorded with `callee_goid_h128=None`; they do not raise exceptions.
- Missing SCIP index raises `typer.BadParameter` and aborts the pipeline.

**Anti-Patterns**

- Do **not**: Catch and suppress exceptions silently; always log or re-raise.
- Do **not**: Use bare `except:` clauses; catch specific exception types.

---

### 8.4 Concurrency & Parallelism

**Pattern**

- Current implementation processes files sequentially.
- Graph builders are designed for future parallelization (files processed independently).
- DuckDB ingestion supports concurrent upserts via transactions.

**Rules**

- File processing order must be deterministic (sorted by path).
- Artifact writing must be atomic (write to temp file, then rename).

**Anti-Patterns**

- Do **not**: Rely on file system iteration order; always sort file lists.
- Do **not**: Write artifacts directly to final paths; use atomic writes.

---

### 8.5 Performance & Scaling

**Pattern**

- AST parsing uses LibCST (faster than pure AST for large files).
- Graph builders use streaming: process files one at a time, aggregate results.
- Parquet writing uses columnar format for efficient storage and querying.

**Rules**

- Large files (>2MB default) are skipped via `--max-file-bytes` option.
- GOID deduplication uses dictionary lookups (`goid_by_hash`) for O(1) checks.
- Edge deduplication uses set operations before sorting.

**Anti-Patterns**

- Do **not**: Load all files into memory simultaneously; process incrementally.
- Do **not**: Use inefficient data structures (lists for lookups); use dictionaries/sets.

---

## 9. Change Patterns & Extension Recipes

### 9.1 How to Add a New Graph Artifact Type

**When to Use This**

- You need to extract a new type of graph structure (e.g., dependency graph, inheritance graph).

**Preconditions**

- Read: Section 6 entries for `codeintel_rev/enrich/callgraph.py` and `codeintel_rev/services/enrich/graph_steps.py`.
- Understand: How builders transform inputs (files/AST) into artifacts (nodes/edges).

**Steps**

1. **Define Row Types** (`codeintel_rev/enrich/<new_graph>.py`)
   - Create `TypedDict` classes for node and edge rows (e.g., `NewGraphNodeRow`, `NewGraphEdgeRow`).
   - Include required fields: GOID references, source location, metadata.

2. **Implement Builder Class** (`codeintel_rev/enrich/<new_graph>.py`)
   - Create `NewGraphBuilder` class with `__init__(repo_root, repo, commit)`.
   - Implement `build(files: Sequence[Path]) -> NewGraphArtifacts`:
     - Collect function info or AST nodes as needed.
     - Traverse AST/files to extract graph structure.
     - Build node and edge rows.
     - Return `NewGraphArtifacts` dataclass.
   - Implement `write_artifacts(artifacts, out_dir) -> tuple[Path, Path]`:
     - Write Parquet files via `codeintel_rev.enrich.graph.io.write_*` helpers.
     - Return paths to written files.

3. **Add Service-Level Function** (`codeintel_rev/services/enrich/graph_steps.py`)
   - Create `build_newgraph_artifacts(ctx, out_dir, ingest, include)` function:
     - Collect Python files via `collect_python_files()`.
     - Instantiate builder with repo/commit from context.
     - Call `builder.build()` and `builder.write_artifacts()`.
     - Optionally ingest into DuckDB if `ingest=True`.
     - Return result dataclass with paths.

4. **Add CLI Command** (`codeintel_rev/cli/enrich/<new_graph>.py`)
   - Create `build_newgraph_cli()` function with `@app.command("newgraph")`.
   - Accept `--repo-root`, `--out-dir`, `--ingest` options.
   - Call `build_newgraph_artifacts()` and echo results.

5. **Register Command** (`codeintel_rev/cli/enrich/__main__.py`)
   - Import the new command module for side effects.

6. **Add IO Writers** (`codeintel_rev/enrich/graph/io.py`)
   - Add `write_newgraph_nodes()` and `write_newgraph_edges()` functions.
   - Use `write_parquet_or_jsonl()` helper for format flexibility.

**Required Tests & Checks**

- Unit tests: Test builder with sample AST/files, verify node/edge generation.
- Integration tests: Run CLI command on test repository, verify Parquet/JSONL output.
- Type checking: Ensure `TypedDict` definitions match Parquet schemas.

**Success Criteria**

- New graph artifacts are discoverable via `enrich newgraph` command.
- Artifacts are written in both Parquet and JSONL formats.
- Artifacts can be ingested into DuckDB if `--ingest` flag set.

---

### 9.2 How to Add a New Analytics Export

**When to Use This**

- You need to export a new type of analytics (e.g., code smell detection, security vulnerability scores).

**Preconditions**

- Read: Section 6 entry for `codeintel_rev/services/enrich/exports.py`.
- Understand: How analytics are computed from `PipelineResult` and written to files.

**Steps**

1. **Compute Analytics** (`codeintel_rev/services/enrich/analytics.py`)
   - Add function to compute analytics from `PipelineResult` or `LegacyPipelineContext`.
   - Return list of row dictionaries or dataclass objects.

2. **Add Export Function** (`codeintel_rev/services/enrich/exports.py`)
   - Create `write_<analytics>_output(result, out)` function:
     - Extract analytics rows from `result` or compute via analytics function.
     - Write to `out/analytics/<analytics>.parquet` via `write_tabular_records()`.
     - Optionally write JSONL via `simple_write_jsonl()`.

3. **Wire into Pipeline** (if needed)
   - If analytics should run automatically: Add call to `write_<analytics>_output()` in `run_pipeline()` or `write_exports_outputs()`.
   - If analytics should be optional: Add CLI flag and conditional call.

4. **Update Documentation** (`README_METADATA.md`)
   - Add section describing the new analytics artifact.
   - Document schema (columns/types) and generation flow.

**Required Tests & Checks**

- Unit tests: Test analytics computation with sample `PipelineResult`.
- Integration tests: Run export command, verify Parquet/JSONL output.
- Schema validation: Ensure Parquet schema matches documented columns.

**Success Criteria**

- Analytics are written to `analytics/<analytics>.parquet` and `.jsonl`.
- Analytics are documented in `README_METADATA.md`.
- Analytics can be queried via DuckDB if ingested.

---

### 9.3 How to Extend GOID Crosswalk with New Sources

**When to Use This**

- You need to link GOIDs to a new identifier system (e.g., LSP symbols, Tree-sitter nodes).

**Preconditions**

- Read: Section 6 entry for `codeintel_rev/enrich/goid_builder.py`.
- Understand: How crosswalk rows link GOIDs to AST nodes and chunk IDs.

**Steps**

1. **Extend CrosswalkRow TypedDict** (`codeintel_rev/ids/goid.py`)
   - Add optional field to `CrosswalkRow`: `new_source_id: string | null`.
   - Document the field in docstring.

2. **Populate Crosswalk in Builder** (`codeintel_rev/enrich/goid_builder.py`)
   - In `GOIDBuilder.build()`, when creating crosswalk rows:
     - Extract new source identifiers from inputs (e.g., LSP symbols from index).
     - Populate `new_source_id` field in crosswalk row.

3. **Update IO Writer** (`codeintel_rev/enrich/graph/io.py`)
   - Ensure `write_goid_crosswalk()` handles new optional field (should work automatically if using Parquet with nullable fields).

4. **Update Documentation** (`README_METADATA.md`)
   - Document new `new_source_id` field in GOID crosswalk schema.

**Required Tests & Checks**

- Unit tests: Test crosswalk generation with new source identifiers.
- Integration tests: Verify Parquet schema includes new field.
- Backward compatibility: Ensure existing crosswalk files without new field still parse.

**Success Criteria**

- New source identifiers are linked to GOIDs in crosswalk.
- Crosswalk Parquet schema includes new optional field.
- Documentation updated with new field description.

---

## 10. Testing & Quality Gates

### 10.1 Test Types

- **Unit tests**
  - Location: `tests/codeintel_rev/enrich/test_*.py`
  - Purpose: Test builder logic in isolation (mock inputs, verify outputs).
  - Examples: `test_goid_builder.py`, `test_callgraph.py`, `test_cfg.py`

- **Integration tests**
  - Location: `tests/codeintel_rev/cli/enrich/test_*.py`
  - Purpose: Test CLI commands end-to-end with real files and verify artifact generation.
  - Examples: `test_goids_cli.py`, `test_callgraph_cli.py`

- **Golden tests**
  - Location: `tests/codeintel_rev/enrich/test_*.py` (with golden file assertions)
  - Purpose: Verify deterministic output for known inputs (GOID hashing, artifact ordering).

### 10.2 Rules for Writing Tests

- Prefer real file fixtures over mocks: Create temporary Python files with known structure.
- Use deterministic inputs: Same repository/commit → same GOID hashes.
- Verify artifact schemas: Check Parquet column names and types match `TypedDict` definitions.
- Test error handling: Verify syntax errors skip files without aborting pipeline.

### 10.3 CI & Quality Gates

- Linting tools: Ruff (formatting + linting)
- Type checking: Pyright (strict mode), Pyrefly (sharp checks)
- Test execution: `pytest` with coverage reporting

All changes must pass these checks before merging.

---

## 11. Operational & Deployment View

### 11.1 Deployment Model

- **Local execution**: CLI commands run on developer machines or CI runners.
- **Batch processing**: Pipeline processes entire repository snapshots, not incremental updates.
- **Artifact storage**: Outputs written to local filesystem (`--out` directory) or DuckDB catalog.

### 11.2 Runtime Configuration

- Configuration provided via CLI options (no config files required).
- Required: `--root` (repository root), `--scip` (SCIP index path).
- Optional: `--out` (output directory, default: `codeintel_rev/io/ENRICHED`), `--pyrefly-json`, `--tags-yaml`, `--coverage-xml`.

### 11.3 Monitoring & Observability

- Logging: Python `logging` module with structured stage metadata.
- Progress tracking: Stage context managers log file counts and artifact counts.
- Error reporting: `StageError` exceptions include stage name, reason, and detail messages.

### 11.4 Migrations & Rollouts

- **GOID schema changes**: Require migration plan for existing artifacts (hash algorithm changes break backward compatibility). Changing from xxhash XXH128 to another algorithm would invalidate all existing GOID hashes.
- **Parquet schema evolution**: New optional fields can be added without breaking existing readers.
- **CLI option changes**: New options are additive (backward compatible); deprecated options emit warnings before removal.

---

## 12. Architectural Decisions & History

### ADR-001: Deterministic GOID Hashing

**Context**: Need stable identifiers for code entities across pipeline runs.

**Decision**: Use content-based hashing (xxhash XXH128) of repository snapshot + entity descriptor.

**Alternatives Considered**:
- Sequential IDs: Not stable across runs.
- UUIDs: Not deterministic.
- SHA256: Cryptographically secure but slower; unnecessary for deterministic identifiers.

**Consequences**:
- GOIDs are stable for same repository/commit → enables incremental updates.
- Hash collisions are prevented via comprehensive descriptor fields (path, qualname, line numbers, SCIP symbol).
- xxhash (XXH128) provides fast, deterministic hashing suitable for large-scale code analysis (non-cryptographic, ~10x faster than SHA256).

---

### ADR-002: Dual Format Output (Parquet + JSONL)

**Context**: Need both SQL-queryable format (Parquet) and LLM-ingestible format (JSONL).

**Decision**: Write all graph artifacts in both Parquet and JSONL formats.

**Alternatives Considered**:
- Parquet only: Requires conversion step for LLM ingestion.
- JSONL only: Inefficient for analytics queries.

**Consequences**:
- Parquet preferred for analytics (columnar, compressed).
- JSONL generated via DuckDB `COPY` from Parquet in `generate_documents.sh` (ensures schema consistency).
- Slight storage overhead (two files per artifact), but enables both use cases.
- Conversion happens post-generation: Parquet files are written first, then converted to JSONL via DuckDB `COPY` command.

---

### ADR-003: Optional Graph Steps

**Context**: Not all use cases need all graph artifacts (GOID, call graph, CFG, DFG).

**Decision**: Make graph steps optional via CLI flags (`--goids`, `--callgraph`, `--cfg`, `--dfg`, `--all`).

**Alternatives Considered**:
- Always build all graphs: Wastes compute for use cases that only need modules/analytics.

**Consequences**:
- Users can run lightweight scans without graph generation.
- Full pipeline (`--all`) builds all graphs for comprehensive analysis.
- Graph steps can be run independently for incremental updates.

---

## 13. Indices & Cross-References

### 13.1 Symbol Index

| Symbol | Description | File Path | Relevant Sections |
|--------|-------------|-----------|-------------------|
| `codeintel_rev.cli.enrich.__main__.app` | Typer application entry point | `codeintel_rev/cli/enrich/__main__.py` | 5.1, 6.2 |
| `codeintel_rev.enrich.goid_builder.GOIDBuilder` | GOID registry and crosswalk builder | `codeintel_rev/enrich/goid_builder.py` | 5.2, 6.2 |
| `codeintel_rev.enrich.callgraph.CallGraphBuilder` | Call graph builder | `codeintel_rev/enrich/callgraph.py` | 5.3, 6.2 |
| `codeintel_rev.enrich.cfg.CFGBuilder` | CFG/DFG builder | `codeintel_rev/enrich/cfg.py` | 5.4, 6.2 |
| `codeintel_rev.services.enrich.scan.run_pipeline` | Full pipeline orchestrator | `codeintel_rev/services/enrich/scan.py` | 5.1, 6.2 |
| `codeintel_rev.services.enrich.graph_steps.build_goid_artifacts` | Service-level GOID generation | `codeintel_rev/services/enrich/graph_steps.py` | 5.2, 6.2 |
| `codeintel_rev.services.enrich.exports.run_all_exports` | Export orchestrator | `codeintel_rev/services/enrich/exports.py` | 5.5, 6.2 |
| `codeintel_rev.ids.goid.compute_goid` | GOID hash computation (xxhash XXH128) | `codeintel_rev/ids/goid.py` | 5.2, 6.2 |
| `codeintel_rev.services.enrich.graph_support.detect_commit` | Git commit hash detection | `codeintel_rev/services/enrich/graph_support.py` | 5.2-5.4 |
| `codeintel_rev.cli.enrich._graph_utils.resolve_paths` | Path resolution for graph commands | `codeintel_rev/cli/enrich/_graph_utils.py` | 5.2-5.4 |

### 13.2 Module Index

| Module Path | Purpose | Relevant Sections |
|-------------|---------|-------------------|
| `codeintel_rev/cli/enrich/__main__.py` | CLI entry point | 5.1, 6.2 |
| `codeintel_rev/cli/enrich/common.py` | Shared CLI helpers | 5.1, 6.2 |
| `codeintel_rev/cli/enrich/goids.py` | GOID CLI command | 5.2 |
| `codeintel_rev/cli/enrich/callgraph.py` | Call graph CLI command | 5.3 |
| `codeintel_rev/cli/enrich/cfg.py` | CFG/DFG CLI commands | 5.4 |
| `codeintel_rev/cli/enrich/exports.py` | Exports CLI command | 5.5 |
| `codeintel_rev/cli/enrich/to_duckdb.py` | DuckDB ingestion CLI command | 6.2 |
| `codeintel_rev/cli/enrich/audit.py` | Completeness audit CLI command | 6.2 |
| `codeintel_rev/cli/enrich/_graph_utils.py` | Shared graph command helpers | 5.2-5.4, 6.2 |
| `codeintel_rev/services/enrich/scan.py` | Pipeline preparation and scanning | 5.1, 6.2 |
| `codeintel_rev/services/enrich/exports.py` | Export orchestration | 5.5, 6.2 |
| `codeintel_rev/services/enrich/graph_steps.py` | Graph artifact service layer | 5.2-5.4, 6.2 |
| `codeintel_rev/enrich/goid_builder.py` | GOID builder logic | 5.2, 6.2 |
| `codeintel_rev/enrich/callgraph.py` | Call graph builder logic | 5.3, 6.2 |
| `codeintel_rev/enrich/cfg.py` | CFG/DFG builder logic | 5.4, 6.2 |
| `codeintel_rev/enrich/ast_indexer.py` | AST node extraction | 5.2, 6.2 |
| `codeintel_rev/ids/goid.py` | GOID hashing algorithm (xxhash XXH128) | 5.2, 6.2 |
| `codeintel_rev/services/enrich/graph_support.py` | File collection and commit detection | 5.2-5.4 |

### 13.3 Artifact Index

| Artifact Name | Schema Location | Generation Flow | Relevant Sections |
|---------------|----------------|-----------------|-------------------|
| `goids.parquet` | Section 7.1 | `GOIDBuilder.build()` → `write_goid_registry()` | 5.2, 7.1 |
| `goid_xwalk.parquet` | Section 7.2 | `GOIDBuilder.build()` → `write_goid_crosswalk()` | 5.2, 7.2 |
| `call_nodes.parquet` | Section 7.3 | `CallGraphBuilder.build()` → `write_call_nodes()` | 5.3, 7.3 |
| `call_edges.parquet` | Section 7.4 | `CallGraphBuilder.build()` → `write_call_edges()` | 5.3, 7.4 |
| `cfg_blocks.parquet` | Section 7.5 | `CFGBuilder.build()` → `write_cfg_blocks()` | 5.4, 7.5 |
| `cfg_edges.parquet` | Section 7.6 | `CFGBuilder.build()` → `write_cfg_edges()` | 5.4, 7.6 |
| `dfg_edges.parquet` | Section 7.7 | `_DFGAnalyzer.build_edges()` → `write_dfg_edges()` | 5.4, 7.7 |
| `modules.jsonl` | Section 7.8 | `scan_modules()` → `write_modules_json()` | 5.1, 5.5, 7.8 |
| `import_graph_edges.parquet` | Section 7.9 | `write_import_graph()` → `write_graph_outputs()` | 5.1, 7.9 |
| `symbol_use_edges.parquet` | Section 7.10 | `build_use_graph()` → `write_uses_output()` | 5.1, 7.10 |
| `coverage_lines.parquet` | Section 7.11 | `run_coverage_analytics()` → `write_coverage_lines()` | 5.7, 7.11 |
| `coverage_functions.parquet` | Section 7.12 | `run_coverage_analytics()` → `write_coverage_functions()` | 5.7, 7.12 |
| `test_catalog.parquet` | Section 7.13 | `run_test_analytics()` → `write_test_catalog()` | 5.7, 7.13 |
| `test_coverage_edges.parquet` | Section 7.14 | `run_test_analytics()` → `write_test_coverage_edges()` | 5.7, 7.14 |
| `goid_risk_factors.parquet` | Section 7.15 | `run_risk_factors()` → `write_risk_factors()` | 5.7, 7.15 |

---

### Maintenance Rules (For AI Agents & Engineers)

- When you make significant architectural changes (new graph types, new analytics, schema changes), you **must** update this document in the same change set.
- If you modify a module that has a Section 6 entry:
  - Review and update that entry's Role, Public Surface, Dependencies, Invariants, and Extension Points.
- When you add a new major change pattern (e.g., new extensibility mechanism), add a recipe to Section 9.
- Do not remove content from this narrative without confirming it is outdated and reflected nowhere in the code.

---

**Document Version**: 1.1  
**Last Updated**: 2024-11-21  
**Maintainer**: CodeIntel Metadata Generation Team

**Revision History**:
- v1.1: Corrected GOID hashing algorithm (xxhash XXH128, not SHA256), fixed GOID URN format, added missing CLI commands (`to-duckdb`, `audit`), documented `_graph_utils.py` module, expanded flow descriptions with implementation details, noted schema discrepancies between code and README_METADATA.md.
