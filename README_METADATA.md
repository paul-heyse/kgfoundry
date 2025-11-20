# CodeIntel Metadata Outputs

This document describes the consolidated artifacts emitted by `generate_documents.sh` under `Document Output/`. Each dataset is produced by the CodeIntel enrichment pipeline and captures different facets of the repository graph. The intent is to give downstream AI agents enough semantic context to reason about the codebase without re-running the heavy analysis steps.

## 1. GOID Registry (`goids.parquet` / `goids.jsonl`)

**Purpose**: Stable identifier canonicalization for all Python entities (modules, functions, classes, and CFG blocks). Downstream graph tables reference GOIDs exclusively.

**Origin**: `codeintel_rev.enrich.goid_builder.GOIDBuilder` walks the AST index (`build/enrich/ast/ast_nodes.*`). For each module and code element it constructs an `EntityDescriptor` and hashes it via `codeintel_rev.ids.goid.compute_goid`, which embeds repo+commit, language, relative path, kind, and normalized qualname.

**Columns**

| Column        | Type        | Description |
|---------------|-------------|-------------|
| `goid_h128`   | decimal(38) | 128-bit integer hash key for the entity. This is the canonical foreign key in all other tables. |
| `urn`         | string      | Human-readable GOID URN: `goid:<repo>/<path>#<language>:<kind>:<qualname>?s=<start>&e=<end>`. |
| `repo`        | string      | Repository slug passed to the builder. |
| `commit`      | string      | Commit SHA at analysis time. |
| `rel_path`    | string      | Repo-relative file path. |
| `language`    | string      | Lowercase language tag (`python`). |
| `kind`        | string      | Entity kind (`module`, `function`, `class`, `method`, `block`). Blocks correspond to CFG basic blocks. |
| `qualname`    | string      | Dotted qualified name synthesized from AST scope. Modules use `pkg.module`. |
| `start_line`  | int         | First line (1-based) spanned by the entity in `rel_path`. |
| `end_line`    | int/null    | Last line if bounded; null for modules or unknown. |
| `created_at`  | timestamp   | Generation timestamp. |

## 2. GOID Crosswalk (`goid_crosswalk.parquet` / `goid_crosswalk.jsonl`)

**Purpose**: Anchor GOIDs to the multiple structural sources used during enrichment: AST nodes, SCIP symbols, chunk IDs, and future CST/CFG references. Allows reversible mapping from any identifier to a GOID.

**Origin**: Emitted alongside the registry from `GOIDBuilder.write_artifacts`. Each GOID may have multiple crosswalk entries (e.g., one per AST occurrence).

**Columns**

| Column          | Type        | Description |
|-----------------|-------------|-------------|
| `goid`          | string      | GOID URN (text form). |
| `lang`          | string      | Language tag. |
| `module_path`   | string/null | Dotted module path derived from `rel_path` sans `.py`. |
| `file_path`     | string/null | Repository-relative file path. |
| `start_line`    | int/null    | Start line of the associated AST/CST/CFG element. |
| `end_line`      | int/null    | End line. |
| `scip_symbol`   | string/null | SCIP symbol if this GOID was matched to a SCIP occurrence. Populated later when the pipeline cross-references SCIP JSON against GOIDs. |
| `ast_qualname`  | string/null | Qualified name reported by LibCST/AST. |
| `cst_node_id`   | string/null | Future hook for CST IDs (currently null unless CST pipeline emits anchors). |
| `chunk_id`      | int/string  | Chunk identifier used by embedding pipelines, typically `<path>:<start>:<end>`. |
| `symbol_id`     | string/null | Reserved for alternate symbol registries. |
| `updated_at`    | timestamp   | Last write time. |

## 3. Call Graph (`call_graph_nodes.*`, `call_graph_edges.*`)

**Purpose**: Static call graph capturing callables (nodes) and callsites (edges) across the repo. Used for impact analysis and topology-aware tooling.

**Origin**: `codeintel_rev.enrich.callgraph.CallGraphBuilder`. Inputs:
- AST + scope info per file (`collect_python_files`).
- Imports resolved via `_ImportResolver`.
- Optional SCIP signal for higher-confidence matches.

**Nodes Columns**

| Column         | Type         | Description |
|----------------|--------------|-------------|
| `goid_h128`    | decimal(38)  | GOID hash for the callable. |
| `language`     | string       | Language (python). |
| `kind`         | string       | Callable kind: `function`, `method`, `class` (for `__call__`), etc. |
| `arity`        | int          | Number of positional parameters detected. |
| `is_public`    | bool         | Heuristic based on naming (leading underscore => false). |
| `rel_path`     | string       | Repo-relative file path containing the callable. |

**Edges Columns**

| Column              | Type         | Description |
|---------------------|--------------|-------------|
| `caller_goid_h128`  | decimal(38)  | GOID hash of the caller. |
| `callee_goid_h128`  | decimal(38)  | GOID hash of the callee; null if unresolved/dynamic. |
| `callsite_path`     | string/null  | File path holding the call expression. |
| `callsite_line`     | int/null     | 1-based line number for the call. |
| `callsite_col`      | int/null     | Column offset. |
| `language`          | string       | Language at the callsite. |
| `kind`              | string       | Edge kind (`direct`, `builtin`, etc.). |
| `resolved_via`      | string       | Provenance of the match: `scip`, `scope`, `heuristic`. Higher confidence flows are prioritized when deduplicating. |
| `confidence`        | float        | Builder-assigned confidence in [0,1]. |
| `evidence_json`     | json         | Additional context (AST text snippets, import alias). |

Edges are deduplicated per `(caller, callee, line, column)` and sorted for deterministic output. Any unresolved call still carries the caller metadata and callsite span.

## 4. Control-Flow Graph (CFG) (`cfg_blocks.*`, `cfg_edges.*`)

**Purpose**: Per-function control-flow scaffolding capturing basic block structure and intra-procedural control edges.

**Origin**: `codeintel_rev.enrich.cfg.CFGBuilder`. Inputs:
- AST per function (via `collect_function_info`).
- Block splitting at control constructs (if/else, loops, break/continue, try/except/finally).
- Entry and exit blocks are synthesized for each function.
- GOID entries for both functions and blocks are created at build time.

**Blocks Columns**

| Column               | Type        | Description |
|----------------------|-------------|-------------|
| `function_goid_h128` | decimal(38) | GOID hash of the function owning the blocks. |
| `block_idx`          | int         | Stable block index generated during CFG construction. |
| `block_id`           | string      | Canonical identifier (`<function-goid>:block<idx>`). |
| `label`              | string      | `<kind>:<idx>` label summarizing entry/exit/conditional. |
| `file_path`          | string/null | Path to the file containing the block. |
| `start_line`         | int/null    | First line covered by the block. |
| `end_line`           | int/null    | Last line covered by the block. |
| `kind`               | string      | Block kind (`entry`, `body`, `exit`, `handler`). |
| `stmts_json`         | json        | Serialized AST metadata of statements in the block. |
| `in_degree`          | int         | Number of predecessor edges (computed when building). |
| `out_degree`         | int         | Number of successor edges. |

**Edges Columns**

| Column               | Type        | Description |
|----------------------|-------------|-------------|
| `function_goid_h128` | decimal(38) | Owner function. |
| `src_block_idx`      | int         | Source block index. |
| `dst_block_idx`      | int         | Destination block index. |
| `edge_type`          | string      | `fallthrough`, `true`, `false`, `loop`, `exception`. |
| `cond_json`          | json/null   | Serialized AST of the guard if applicable. |
| `src`/`dst`          | string      | Canonical node IDs mirroring `block_id`. |

## 5. Data-Flow Graph (DFG) (`dfg_edges.*`)

**Purpose**: Intra-procedural data-flow edges capturing definition/use relationships of symbols per block.

**Origin**: Same CFG builder; after block construction it performs a def-use walk tracking variable bindings, phi-like merges, and uses per block.

**Columns**

| Column               | Type        | Description |
|----------------------|-------------|-------------|
| `function_goid_h128` | decimal(38) | Function owning the edge. |
| `src_block_idx`      | int         | Block containing the definition. |
| `dst_block_idx`      | int         | Block containing the use. |
| `src_symbol`         | string      | Variable or temporary defined at the source. |
| `dst_symbol`         | string      | Symbol referenced at the destination. |
| `via_phi`            | bool        | True when this edge models a merge (phi) node from multiple predecessors. |
| `use_kind`           | string      | `read`, `write`, `update`, etc. |

DFG edges can be joined to CFG blocks (via `src_block_idx`/`dst_block_idx`) and to their own synthetic nodes via `dfg_nodes.*` (not exported separately). Each edge may produce corresponding nodes in `dfg_nodes.parquet` when multi-hop traversals are needed.

## 6. JSONL vs Parquet

Each dataset is written twice:
- **Parquet**: Columnar format aligned with the DuckDB catalog; best for analytics and SQL.
- **JSONL**: (Generated via DuckDB `COPY` from Parquet) for LLM ingestion, allowing streaming of each row as a JSON object.

The JSON files reside directly under `Document Output/` with names matching the Parquet base (`goids.jsonl`, `call_graph_edges.jsonl`, etc.). They contain the exact column/value pairs described above.

## 7. Generation Workflow Summary

1. `scip-python` indexes the repository and emits `codeintel_rev/index.scip` + JSON view.
2. `codeintel_rev.cli.enrich_pipeline all` runs LibCST, AST, analytics, and stores outputs under `codeintel_rev/io/ENRICHED`.
3. Dedicated graph commands (`codeintel_rev.cli.enrich goids|callgraph|cfg|dfg`) consume the repo and enrichment output, emitting the graph datasets.
4. `generate_documents.sh` copies all artifacts into `Document Output/` and runs the Parquet→JSONL conversion for the graph tables.

Downstream consumers can therefore:
- Join any dataset on `goid_h128`/`goid` to relate nodes, edges, and crosswalk entries.
- Use JSONL files as streaming corpora for LLM context windows.
- Re-run `generate_documents.sh` after code changes to refresh the datasets with new analyses.
