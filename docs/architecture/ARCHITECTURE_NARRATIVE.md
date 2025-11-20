# Architecture Narrative

## Table of Contents

- [0. How to Use This Document (For Humans & AI Agents)](#0-how-to-use-this-document-for-humans--ai-agents)
- [1. System Purpose & High-Level Overview](#1-system-purpose--high-level-overview)
- [2. Domain Model & Glossary](#2-domain-model--glossary)
- [3. Architectural Principles & Constraints](#3-architectural-principles--constraints)
- [4. System Context & External Integrations](#4-system-context--external-integrations)
- [5. Runtime Behavior & Key Flows](#5-runtime-behavior--key-flows)
- [6. Static Structure: Layers, Modules, and Dependencies](#6-static-structure-layers-modules-and-dependencies)
- [7. Data & Metadata Structures](#7-data--metadata-structures)
- [8. Cross-Cutting Concerns](#8-cross-cutting-concerns)
- [9. Change Patterns & Extension Recipes](#9-change-patterns--extension-recipes)
- [10. Testing & Quality Gates](#10-testing--quality-gates)
- [11. Operational & Deployment View](#11-operational--deployment-view)
- [12. Architectural Decisions & History](#12-architectural-decisions--history)
- [13. Indices & Cross-References](#13-indices--cross-references)

## Detailed Table of Contents

- [1. System Purpose & High-Level Overview](#1-system-purpose--high-level-overview)
	- [1.1 Mission](#11-mission) – Production-grade code intelligence platform overview
	- [1.2 Non-Goals](#12-non-goals) – What the system is not designed for
	- [1.3 Primary Use Cases](#13-primary-use-cases) – Core use cases (A-G) with code locations
	- [1.4 External Systems and Stakeholders](#14-external-systems-and-stakeholders) – Upstream inputs and downstream consumers
	- [1.5 Key Constraints](#15-key-constraints) – Performance, reliability, memory, type safety, configuration, security
- [2. Domain Model & Glossary](#2-domain-model--glossary)
	- [2.1 Glossary](#21-glossary) – Comprehensive term definitions with code representations
	- [2.2 Entity Relationships (Textual Overview)](#22-entity-relationships-textual-overview) – Domain entity relationships and connections
- [3. Architectural Principles & Constraints](#3-architectural-principles--constraints)
	- [3.1 Layering Rules](#31-layering-rules) – Five-layer architecture with dependency rules
	- [3.2 Configuration Management](#32-configuration-management) – Centralized configuration patterns and rules
	- [3.3 Error Handling](#33-error-handling) – Exception taxonomy and RFC 9457 Problem Details mapping
	- [3.4 Type Safety](#34-type-safety) – Strict typing requirements and pyright/pyrefly compliance
	- [3.5 Resource Management](#35-resource-management) – Lifecycle management for FAISS, DuckDB, vLLM
	- [3.6 Testing Philosophy](#36-testing-philosophy) – Production-like testing with real collaborators
- [4. System Context & External Integrations](#4-system-context--external-integrations)
	- [4.1 Inbound Interfaces](#41-inbound-interfaces) – HTTP API (FastAPI) and CLI (Typer) entry points
	- [4.2 Outbound Dependencies](#42-outbound-dependencies) – DuckDB, FAISS, vLLM, BM25, SPLADE, Git, SCIP, NGINX
	- [4.3 Trust Boundaries and Security](#43-trust-boundaries-and-security) – Input validation, authentication, error handling, secrets
- [5. Runtime Behavior & Key Flows](#5-runtime-behavior--key-flows)
	- [5.1 Flow: Application Startup – Initialization Sequence](#51-flow-application-startup--initialization-sequence) – FastAPI lifespan, context initialization, readiness checks
	- [5.2 Flow: Indexing Pipeline – Building Searchable Indexes](#52-flow-indexing-pipeline--building-searchable-indexes) – SCIP parsing, chunking, embedding, FAISS/BM25/SPLADE index building
	- [5.3 Flow: Semantic Search – Querying Code with Natural Language](#53-flow-semantic-search--querying-code-with-natural-language) – Stage 0 hybrid retrieval, Stage 1 gating, result hydration
	- [5.4 Flow: Hybrid Search – Combining Dense, Sparse, and Symbol Signals](#54-flow-hybrid-search--combining-dense-sparse-and-symbol-signals) – RRF fusion of FAISS, BM25, SPLADE, symbol signals
	- [5.5 Flow: Symbol Navigation – Finding Definitions and References](#55-flow-symbol-navigation--finding-definitions-and-references) – SCIP-based symbol search, definition_at, references_at
	- [5.6 Flow: Semantic Search Pro – Two-Stage Retrieval with Late Interaction](#56-flow-semantic-search-pro--two-stage-retrieval-with-late-interaction) – CodeRank + WARP late interaction + optional LLM reranking
	- [5.7 Flow: Deep Research Search/Fetch – Two-Phase Chunk Retrieval](#57-flow-deep-research-searchfetch--two-phase-chunk-retrieval) – Search returns chunk IDs, fetch hydrates full content
	- [5.8 Flow: Index Lifecycle Management – Staging and Publishing Versions](#58-flow-index-lifecycle-management--staging-and-publishing-versions) – Version staging, checksums, symlink-based publishing
	- [5.9 Flow: Code Enrichment Pipeline – Extracting AST/CST Metadata](#59-flow-code-enrichment-pipeline--extracting-astcst-metadata) – AST extraction, CST parsing, dependency graphs, ownership analytics
- [6. Static Structure: Layers, Modules, and Dependencies](#6-static-structure-layers-modules-and-dependencies)
	- [6.1 Layer Overview](#61-layer-overview) – Five-layer architecture summary
	- [6.2 Module Catalog](#62-module-catalog) – Detailed module entries with role, public surface, dependencies, invariants, extension points
- [7. Data & Metadata Structures](#7-data--metadata-structures)
	- [7.1 Primary Data Stores](#71-primary-data-stores) – DuckDB catalog, Parquet files, FAISS indexes, BM25/SPLADE indexes, SCIP indexes, enrichment artifacts, XTR index
	- [7.2 Index Versioning](#72-index-versioning) – Versioned directories, active symlink, metadata files
	- [7.3 Session Scope Storage](#73-session-scope-storage) – ScopeStore, session expiration, background pruning
- [8. Cross-Cutting Concerns](#8-cross-cutting-concerns)
	- [8.1 Configuration Management](#81-configuration-management) – Centralized config patterns and rules
	- [8.2 Logging & Observability](#82-logging--observability) – Structured logging with correlation IDs
	- [8.3 Error Handling](#83-error-handling) – Exception taxonomy and Problem Details mapping
	- [8.4 Concurrency & Parallelism](#84-concurrency--parallelism) – Async I/O, threadpool offloading for CPU-bound work
	- [8.5 Performance & Scaling](#85-performance--scaling) – Adaptive indexing, connection pooling, performance patterns
	- [8.6 Runtime Management](#86-runtime-management) – RuntimeCell abstraction, lazy loading, lifecycle management
	- [8.7 Scope Management](#87-scope-management) – Session-scoped query constraints, LRU cache, Redis backend
	- [8.8 Capabilities System](#88-capabilities-system) – Runtime capability detection, conditional tool registration, `/capz` endpoint
	- [8.9 Error Handling Decorator Pattern](#89-error-handling-decorator-pattern) – `@handle_adapter_errors` decorator for consistent error handling
- [9. Change Patterns & Extension Recipes](#9-change-patterns--extension-recipes)
	- [9.1 How to Add a New MCP Tool](#91-how-to-add-a-new-mcp-tool) – Tool implementation, registration, capability gating, testing
	- [9.2 How to Add a New Search Signal to Hybrid Search](#92-how-to-add-a-new-search-signal-to-hybrid-search) – Search manager implementation, RRF fusion integration
	- [9.3 How to Add a New Index Type to FAISS Manager](#93-how-to-add-a-new-index-type-to-faiss-manager) – Index type selection, training logic, search parameters, memory estimation
	- [9.4 How to Add a New Configuration Key](#94-how-to-add-a-new-configuration-key) – AppConfig field, environment variable mapping, validation, documentation
	- [9.5 How to Add a New HTTP Router](#95-how-to-add-a-new-http-router) – Router module creation, ApplicationContext dependency, admin gating, testing
	- [9.6 How to Add a New Enrichment Step](#96-how-to-add-a-new-enrichment-step) – Enrichment function implementation, artifact writing, pipeline integration
- [10. Testing & Quality Gates](#10-testing--quality-gates)
	- [10.1 Test Types](#101-test-types) – Unit tests, integration tests, end-to-end/smoke tests, performance/benchmark tests
	- [10.2 Rules for Writing Tests](#102-rules-for-writing-tests) – Real collaborators, no monkeypatching, real entry points, fixtures, parametrization
	- [10.3 CI & Quality Gates](#103-ci--quality-gates) – Linting, type checking, tests, dead code scanning, security audit
- [11. Operational & Deployment View](#11-operational--deployment-view)
	- [11.1 Deployment Model](#111-deployment-model) – Single-machine deployment, future multi-repository support
	- [11.2 Runtime Configuration](#112-runtime-configuration) – Environment variables, required/optional settings, secrets
	- [11.3 Monitoring & Observability](#113-monitoring--observability) – Health endpoints, logging, metrics (planned), tracing (planned)
	- [11.4 Migrations & Rollouts](#114-migrations--rollouts) – Index versioning, DuckDB migrations, backward compatibility, rollout strategy
	- [11.5 Startup & Shutdown](#115-startup--shutdown) – Startup sequence, shutdown sequence, resource cleanup
- [12. Architectural Decisions & History](#12-architectural-decisions--history)
	- [12.1 ADR Placeholder](#121-adr-placeholder) – Placeholder for future Architectural Decision Records
	- [12.2 Initial Decision Stubs](#122-initial-decision-stubs) – CPU-only FAISS decision (hypothesis) with rationale and consequences
- [13. Indices & Cross-References](#13-indices--cross-references)
	- [13.1 Symbol Index](#131-symbol-index) – Table mapping symbols to file paths and relevant sections
	- [13.2 Module Index](#132-module-index) – Table mapping module paths to layers and relevant sections
	- [13.3 Flow Index](#133-flow-index) – Table mapping flow names to sections and key modules

---

## 0. How to Use This Document (For Humans & AI Agents)

**Audience**

- Primary: AI coding agents and senior engineers working on this repository.
- Secondary: Stakeholders seeking a high-level understanding of the system.

**Scope**

- This document describes the intended architecture of the CodeIntel MCP code intelligence platform.
- It is **normative**: if code disagrees with this narrative, treat the narrative as the desired target and propose refactors.
- This is the first version of the Architecture Narrative; no prior architecture documents or ADRs exist.

**Reading Order**

- Start with Section 1 (System Purpose) and Section 3 (Architectural Principles).
- For code changes in a specific area:
  - Read Section 6 (Static Structure) for the relevant module/package.
  - Read Section 9 (Change Patterns) for instructions on how to modify or extend that area.
  - Read Section 10 (Testing & Quality Gates) for required tests.

**Conventions**

- File paths are written as: `package/subpackage/module.py`.
- Symbols are written as: `package.module.Class.method`.
- Important invariants and "never do this" rules are explicitly labeled.
- Hypotheses or unclear areas are labeled with **(Hypothesis)** or **(Needs Review)**.

**Norms for AI Agents**

- Always ground your changes in this document and the actual code.
- If you detect discrepancies between this narrative and the code:
  - Explain the discrepancy.
  - Recommend a resolution (update narrative vs refactor code).
- Never silently violate stated invariants or principles.
- Follow the patterns and recipes in Section 9 when making changes.

**Maintenance Rules (For AI Agents & Engineers)**

- When you make significant architectural changes (new layers, major refactors, new external systems), you **must** update this document in the same change set.
- If you modify a module that has a Section 6 entry:
  - Review and update that entry's Role, Public Surface, Dependencies, Invariants, and Extension Points.
- When you add a new major change pattern (e.g., new extensibility mechanism), add a recipe to Section 9.
- Do not remove content from this narrative without confirming it is outdated and reflected nowhere in the code.

---

## 1. System Purpose & High-Level Overview

### 1.1 Mission

CodeIntel MCP is a production-grade code intelligence platform that provides semantic search, symbol navigation, and code analysis capabilities via a Model Context Protocol (MCP) server. The system enables AI assistants (ChatGPT, Claude, etc.) to understand and navigate codebases through structured indexing, hybrid retrieval (combining dense vector search, sparse BM25/SPLADE, and symbol metadata), and precise symbol resolution using Sourcegraph SCIP indexes.

The platform solves the problem of making large codebases searchable and navigable for AI agents by:
- Indexing code using SCIP for precise symbol information
- Chunking code with structure-aware algorithms (cAST) that respect symbol boundaries
- Embedding code chunks using dense models (vLLM) and sparse models (BM25, SPLADE)
- Building efficient vector indexes (FAISS CPU) and metadata catalogs (DuckDB)
- Exposing search and navigation capabilities via HTTP/3 streaming MCP endpoints

### 1.2 Non-Goals

- **Not a general-purpose knowledge graph**: The system focuses on code intelligence, not general knowledge representation.
- **Not a code editor**: The system provides search and navigation APIs, not editing capabilities.
- **Not a build system**: The system indexes existing code but does not compile or build projects.
- **Not a version control system**: Git operations are used for history/blame but the system does not replace Git.
- **Not a multi-repository aggregator (current)**: Currently supports single-repository indexing; multi-repo support is planned for Phase 3.

### 1.3 Primary Use Cases

- **Use Case A** – Semantic Code Search
  - What: AI agents query codebases using natural language to find relevant code chunks.
  - Who: AI assistants (ChatGPT, Claude) via MCP protocol.
  - Where in code: `codeintel_rev.mcp_server.adapters.semantic`, `codeintel_rev.retrieval.hybrid_search`, `codeintel_rev.io.faiss_manager`.

- **Use Case B** – Symbol Navigation
  - What: Navigate to symbol definitions and find references using SCIP index data.
  - Who: AI assistants and developers via MCP tools.
  - Where in code: `codeintel_rev.mcp_server.adapters.symbols`, `codeintel_rev.io.duckdb_catalog`.

- **Use Case C** – Code Indexing Pipeline
  - What: Build searchable indexes from source code repositories using SCIP, chunking, and embedding.
  - Who: DevOps engineers and CI/CD pipelines.
  - Where in code: `codeintel_rev.bin.index_all`, `codeintel_rev.indexing.cast_chunker`, `codeintel_rev.cli.indexctl`.

- **Use Case D** – Hybrid Retrieval
  - What: Combine dense (FAISS), sparse (BM25/SPLADE), and symbol-based signals using RRF fusion.
  - Who: Search services internally.
  - Where in code: `codeintel_rev.retrieval.hybrid_search`, `codeintel_rev.io.rrf`.

- **Use Case E** – Code Enrichment & Analysis
  - What: Extract AST/CST metadata, build dependency graphs, and generate enriched documentation.
  - Who: Analysis pipelines and documentation generators.
  - Where in code: `codeintel_rev.enrich`, `codeintel_rev.cli.enrich`.

- **Use Case F** – Advanced Semantic Search (Pro)
  - What: Two-stage semantic retrieval with optional late interaction (WARP) and LLM reranking for high-precision code search.
  - Who: AI assistants requiring high-quality ranked results.
  - Where in code: `codeintel_rev.mcp_server.adapters.semantic_pro`, `codeintel_rev.retrieval.pipeline.stage0`, `codeintel_rev.retrieval.pipeline.gating`.

- **Use Case G** – Deep Research Search/Fetch
  - What: Two-phase search pattern: search returns chunk IDs, fetch hydrates full content. Used by Deep Research agents.
  - Who: Deep Research AI agents requiring chunk ID-based workflows.
  - Where in code: `codeintel_rev.mcp_server.adapters.deep_research`, `codeintel_rev.mcp_server.server_semantic`.

### 1.4 External Systems and Stakeholders

- **Upstream inputs**
  - **Sourcegraph SCIP**: Provides symbol definitions, references, and documentation metadata via `index.scip` files.
  - **vLLM Embedding Service**: Provides dense embeddings for code chunks via OpenAI-compatible HTTP API.
  - **Git Repository**: Provides source code files, commit history, and blame information.
  - **NGINX (Production)**: Acts as HTTP/3 edge proxy with OAuth 2.1 authentication.

- **Downstream consumers**
  - **AI Assistants (ChatGPT, Claude)**: Consume MCP tools for code search and navigation.
  - **CI/CD Pipelines**: Trigger indexing pipelines to rebuild indexes after code changes.
  - **Developers**: Use CLI tools (`codeintel indexctl`, `codeintel enrich`) for local development and analysis.

### 1.5 Key Constraints

- **Performance**: Must handle codebases with 100K+ code chunks; semantic search must complete in <100ms p95 latency.
- **Reliability**: Index operations must be atomic; failures must not corrupt existing index state. DuckDB catalog must maintain referential integrity.
- **Memory**: FAISS indexes must fit in available RAM; adaptive indexing selects appropriate index types (Flat/IVFFlat/IVF-PQ) based on corpus size.
- **Type Safety**: All public APIs must be fully typed; strict pyright and pyrefly compliance required.
- **Configuration**: Configuration loaded once at startup and treated as immutable; fail-fast on invalid configuration.
- **Security/Compliance**: Input validation at all boundaries; no `eval/exec`; secrets via environment variables only.

---

## 2. Domain Model & Glossary

### 2.1 Glossary

| Term | Definition (Plain Language) | Primary Code Representations |
|------|------------------------------|------------------------------|
| **Chunk** | A contiguous segment of code extracted from a source file, respecting symbol boundaries (cAST chunking). | `codeintel_rev.indexing.cast_chunker.Chunk`, `codeintel_rev.io.parquet_store` (Parquet columns) |
| **SCIP Index** | Sourcegraph SCIP protocol index file containing symbol definitions, references, and documentation. | `codeintel_rev.indexing.scip_reader`, `index.scip` / `index.scip.json` files |
| **FAISS Index** | Vector similarity search index built from chunk embeddings using Facebook AI Similarity Search. | `codeintel_rev.io.faiss_manager.FAISSManager`, `*.faiss` files |
| **DuckDB Catalog** | Relational catalog storing chunk metadata, symbol information, and index registration. | `codeintel_rev.io.duckdb_catalog.DuckDBCatalog`, `codeintel_rev.io.duckdb_manager.DuckDBManager`, `*.duckdb` files |
| **Embedding** | Dense vector representation of a code chunk (typically 2560-dimensional from Qwen3-Embedding-4B). | `codeintel_rev.embeddings.EmbeddingProvider`, `codeintel_rev.io.vllm_client.VLLMClient`, Parquet `embedding` column |
| **BM25 Index** | Sparse retrieval index using Best Matching 25 ranking function for keyword search. | `codeintel_rev.io.bm25_manager.BM25Manager`, `codeintel_rev.io.bm25_engine`, `_indices/bm25/` directory |
| **SPLADE Index** | Sparse Lexical and Expansion index for learned sparse retrieval. | `codeintel_rev.io.splade_manager.SPLADEManager`, `codeintel_rev.io.splade_onnx_encoder`, `_indices/splade_impact/` directory |
| **Hybrid Search** | Combined retrieval using RRF (Reciprocal Rank Fusion) to merge dense, sparse, and symbol signals. | `codeintel_rev.retrieval.hybrid_search.HybridSearchEngine`, `codeintel_rev.io.rrf` |
| **Scope** | Session-scoped query constraints (path patterns, languages, repositories) that filter search results. | `codeintel_rev.app.scope_store.ScopeStore`, `codeintel_rev.app.middleware.SessionScopeMiddleware` |
| **Index Version** | Versioned snapshot of FAISS/DuckDB/SCIP assets managed by `IndexLifecycleManager`. | `codeintel_rev.indexing.index_lifecycle.IndexLifecycleManager`, `codeintel_rev.cli.indexctl` |
| **MCP Tool** | Model Context Protocol tool exposed via FastMCP for AI assistants (e.g., `semantic_search`, `symbol_search`). | `codeintel_rev.mcp_server.server`, `codeintel_rev.mcp_server.adapters` |
| **Capabilities** | Runtime capability snapshot detecting available runtimes (FAISS, DuckDB, vLLM, XTR) and gating tool registration. | `codeintel_rev.app.capabilities.Capabilities`, `/capz` endpoint |
| **Stage 0** | First-stage hybrid retrieval combining dense (FAISS), sparse (BM25/SPLADE), and symbol signals using RRF fusion. | `codeintel_rev.retrieval.pipeline.stage0.run_stage0`, `codeintel_rev.retrieval.hybrid_search` |
| **Stage 1** | Optional second-stage retrieval (late interaction, reranking) gated by Stage-0 signals (candidate count, score margins). | `codeintel_rev.retrieval.pipeline.gating.decide_secondary_stage`, `codeintel_rev.mcp_server.adapters.semantic_pro` |
| **Error Handling Decorator** | `@handle_adapter_errors` decorator pattern that catches exceptions and converts them to RFC 9457 Problem Details with empty result fallbacks. | `codeintel_rev.mcp_server.error_handling.handle_adapter_errors` |
| **Application Context** | Immutable container holding configuration, clients, and runtime managers (FAISS, DuckDB, vLLM, etc.). | `codeintel_rev.app.config_context.ApplicationContext` |
| **Readiness Probe** | Health check system validating that dependent services (FAISS, DuckDB, vLLM) are available. | `codeintel_rev.app.runtime_readiness.ReadinessProbe` |
| **XTR (Cross-Token Reranking)** | Learned reranking model that reranks search results using cross-token attention. | `codeintel_rev.rerank.xtr.XTRReranker`, `codeintel_rev.io.xtr_manager.XTRIndex`, `indexes/warp_xtr/` directory |
| **Reranker** | Component that reranks search results to improve relevance (e.g., XTR, CodeRank). | `codeintel_rev.rerank.base.BaseReranker`, `codeintel_rev.rerank.xtr.XTRReranker` |
| **Enrichment** | Process of extracting metadata from code (AST, CST, dependency graphs, ownership) beyond basic indexing. | `codeintel_rev.enrich`, `codeintel_rev.cli.enrich`, `codeintel_rev.services.enrich` |
| **AST (Abstract Syntax Tree)** | Python AST nodes extracted from source files (functions, classes, imports, decorators). | `codeintel_rev.enrich.ast_indexer`, `build/enrich/ast/ast_nodes.parquet` |
| **CST (Concrete Syntax Tree)** | Lossless LibCST representation preserving exact source formatting and structure. | `codeintel_rev.cst_build`, `codeintel_rev.io/CST/cst_nodes.jsonl.gz` |
| **Runtime** | Lazy-loaded component manager (FAISS, DuckDB, vLLM, XTR, HybridSearch) with lifecycle management. | `codeintel_rev.runtime.cells.RuntimeCell`, `codeintel_rev.app.config_context.ApplicationContext` (runtime properties) |
| **Scope Store** | In-memory or Redis-backed storage for session-scoped query constraints (path patterns, languages). | `codeintel_rev.app.scope_store.ScopeStore`, `codeintel_rev.app.scope_store.LRUCache` |
| **Index Build Service** | Service orchestrating FAISS index construction from Parquet shards with step-based pipeline. | `codeintel_rev.services.index.build.run_index_build`, `codeintel_rev.services.index.steps` |
| **Enrichment Service** | Service orchestrating code enrichment pipeline (AST extraction, CST parsing, dependency graphs). | `codeintel_rev.services.enrich`, `codeintel_rev.cli.enrich` |

### 2.2 Entity Relationships (Textual Overview)

- A **Repository** contains many **Source Files**.
- Each **Source File** is parsed into a **SCIP Index** containing **Symbol** definitions and references.
- **Source Files** are chunked into **Chunk**s using cAST (structure-aware chunking respecting symbol boundaries).
- Each **Chunk** is embedded into an **Embedding** vector (dense) and optionally encoded into sparse vectors (BM25 tokens, SPLADE impact scores).
- **Chunk**s are stored in **Parquet** files with metadata (chunk_id, file_path, start_line, end_line, embedding, etc.).
- **Embedding**s are indexed in a **FAISS Index** for fast similarity search.
- **Chunk** metadata and **Symbol** information are stored in a **DuckDB Catalog** for relational queries.
- **BM25 Index** and **SPLADE Index** provide sparse retrieval signals.
- **Hybrid Search** combines FAISS, BM25, SPLADE, and symbol signals using RRF fusion.
- **Reranker**s (XTR, CodeRank) optionally rerank hybrid search results to improve relevance.
- **Enrichment** extracts AST/CST metadata, dependency graphs, and ownership information from source files.
- **AST** nodes represent Python functions, classes, imports extracted from source code.
- **CST** nodes represent lossless LibCST parse trees preserving exact source formatting.
- **Runtime**s are lazy-loaded component managers (FAISS, DuckDB, vLLM, XTR) with lifecycle management.
- **Scope Store** maintains session-scoped query constraints (path patterns, languages) for filtering.
- **MCP Tools** expose search and navigation capabilities to AI assistants.
- **Scope** constraints filter search results per session (path patterns, languages).
- **Index Version**s manage lifecycle of FAISS/DuckDB/SCIP assets.

---

## 3. Architectural Principles & Constraints

### 3.1 Layering Rules

The system is organized into five logical layers:

1. **Entrypoints Layer** (`codeintel_rev.app`, `codeintel_rev.cli`, `codeintel_rev.mcp_server`)
   - Responsibilities: HTTP endpoints, CLI commands, MCP tool registration.
   - Allowed dependencies: Services layer, Configuration layer.
   - Forbidden dependencies: Must not import IO/infrastructure directly (except via services).

2. **Services Layer** (`codeintel_rev.services`)
   - Responsibilities: Business logic orchestration (indexing pipelines, search coordination).
   - Allowed dependencies: Domain models, IO/infrastructure adapters, Configuration.
   - Forbidden dependencies: Must not import entrypoints.

3. **Domain Models Layer** (`codeintel_rev.indexing.cast_chunker`, `codeintel_rev.retrieval`)
   - Responsibilities: Pure domain logic (chunking algorithms, RRF fusion, search result ranking).
   - Allowed dependencies: Standard library, typing, shared utilities.
   - Forbidden dependencies: Must not import IO, services, or entrypoints.

4. **IO/Infrastructure Layer** (`codeintel_rev.io`, `codeintel_rev.embeddings`)
   - Responsibilities: External system adapters (FAISS, DuckDB, vLLM, file I/O, Git).
   - Allowed dependencies: Domain models (for data structures), Configuration.
   - Forbidden dependencies: Must not import services or entrypoints.

5. **Configuration Layer** (`codeintel_rev.config`)
   - Responsibilities: Configuration loading, path resolution, environment variable parsing.
   - Allowed dependencies: Standard library, pydantic-settings.
   - Forbidden dependencies: Must not import any other layers (pure configuration).

**Invariant**: Lower layers must never import higher layers. Violations indicate architectural drift.

### 3.2 Configuration Management

- **Pattern**: Configuration is centralized in `codeintel_rev.config` and loaded once at startup via `ApplicationContext.create()`.
- **Rules**:
  - Always access config via `ApplicationContext` or `AppConfig` objects, never directly via `os.environ` in business logic.
  - New configuration keys must be added to `codeintel_rev.config` with defaults and typed definitions.
  - Configuration is immutable after startup; changes require application restart.
- **Anti-Patterns**:
  - Do **not** read env vars directly in business logic (use `AppConfig`).
  - Do **not** modify configuration at runtime.
  - Do **not** create multiple configuration loading paths.

### 3.3 Error Handling

- **Pattern**: All domain errors inherit from `kgfoundry_common.errors.KgFoundryError` (base) or `codeintel_rev.errors.*` (domain-specific) and map to RFC 9457 Problem Details for HTTP responses.
- **Exception Taxonomy**:
  - **Base Exception**: `KgFoundryError` - All kgfoundry exceptions inherit from this base class.
  - **File Operations**: `FileOperationError`, `FileReadError`, `InvalidLineRangeError`, `PathNotFoundError`, `PathNotDirectoryError` (400 Bad Request).
  - **Git Operations**: `GitOperationError` (500 Internal Server Error).
  - **Search Operations**: `VectorSearchError`, `EmbeddingError` (from `kgfoundry_common.errors`) - FAISS/vLLM failures.
  - **Runtime Lifecycle**: `RuntimeLifecycleError`, `RuntimeUnavailableError`, `VectorIndexStateError`, `VectorIndexIncompatibleError` (500/503).
  - **Catalog Operations**: `CatalogConsistencyError`, `CatalogJoinError` (500 Internal Server Error).
  - **Request Context**: `RequestContextError` - Wraps non-HTTP exceptions with request context (500).
  - **Configuration**: `ConfigurationError` (from `kgfoundry_common.errors`) - Invalid configuration (500).
  - **Serialization**: `SerializationError`, `DeserializationError` (from `kgfoundry_common.errors`) - JSON/Pickle failures.
- **Error Codes**: All exceptions include `ErrorCode` enum values (e.g., `FILE_OPERATION_ERROR`, `GIT_OPERATION_ERROR`, `VECTOR_SEARCH_ERROR`) mapped to RFC 9457 Problem Details `type` URIs (`https://kgfoundry.dev/problems/{error-code}`).
- **Rules**:
  - Always use `raise ... from e` to preserve exception chains.
  - HTTP endpoints return Problem Details JSON with `type`, `title`, `status`, `detail`, and optional `instance`/`context` fields.
  - Log errors with structured logging (include request_id, session_id, run_id).
  - Include structured context in exceptions (path, git_command, runtime name, etc.) for debugging.
- **Anti-Patterns**:
  - Do **not** use bare `except:` clauses.
  - Do **not** swallow exceptions silently (at minimum, log them).
  - Do **not** return generic error messages without context.
  - Do **not** raise generic `Exception` or `RuntimeError` - use specific exception types from the taxonomy.

### 3.4 Type Safety

- **Pattern**: All public APIs must be fully typed; use strict pyright and pyrefly checking.
- **Rules**:
  - Every function must have type annotations for parameters and return types.
  - Prefer PEP 695 generics and `Protocol`/`TypedDict` over `Any`.
  - Use `from __future__ import annotations` for postponed evaluation.
  - Heavy dependencies (numpy, fastapi) must be guarded with `if TYPE_CHECKING:` blocks.
- **Anti-Patterns**:
  - Do **not** use `Any` without justification.
  - Do **not** suppress type errors with `# type: ignore` without explanation.
  - Do **not** import heavy dependencies at module scope if only used in type hints.

### 3.5 Resource Management

- **Pattern**: Use context managers and explicit lifecycle management for external resources.
- **Rules**:
  - FAISS indexes are loaded lazily unless `FAISS_PRELOAD=1` is set.
  - DuckDB connections are obtained per-request via `DuckDBManager` (thread-safe, optionally pooled).
  - vLLM HTTP clients use connection pooling and are closed during application shutdown.
  - ApplicationContext manages all runtime lifecycle via `close_all_runtimes()`.
- **Anti-Patterns**:
  - Do **not** hold global connections to DuckDB or FAISS indexes.
  - Do **not** leak file handles or HTTP connections.
  - Do **not** perform blocking I/O in async request handlers (use `asyncio.to_thread`).

### 3.6 Testing Philosophy

- **Pattern**: Tests must behave as close to production as possible; no monkeypatching of production code.
- **Rules**:
  - Use real collaborators (DuckDB, FAISS) with isolated instances (temporary directories, in-memory DBs).
  - Tests enter through real entry points (CLI commands, HTTP endpoints).
  - Configuration may differ (test-specific paths), but logic must not.
- **Anti-Patterns**:
  - Do **not** use `monkeypatch` or `unittest.mock.patch` on production code.
  - Do **not** create test-only code paths (`if TESTING:` branches).
  - Do **not** replace real systems (DuckDB, FAISS) with toy in-memory fakes.

---

## 4. System Context & External Integrations

### 4.1 Inbound Interfaces

- **HTTP API (FastAPI)**
  - Entry module: `codeintel_rev.app.main`.
  - Framework: FastAPI with Hypercorn ASGI server (HTTP/2, HTTP/3 support).
  - Endpoints:
    - `/healthz` - Network health check (always returns 200).
    - `/readyz` - Readiness probe (validates FAISS, DuckDB, vLLM availability, returns active index version).
    - `/capz` - Capability snapshot (returns available runtimes and indexes, used for conditional tool registration, supports `?refresh=true` query parameter).
    - `/mcp/*` - MCP tool endpoints (mounted via FastMCP).
    - `/sse` - Server-Sent Events streaming demo with keep-alive comments.
    - `/v1/catalog/goids` - GOID (Global Object Identifier) catalog query endpoint with pagination (cursor-based).
    - `/v1/graph/call` - Call graph query endpoint (returns caller-callee relationships).
    - `/v1/flow/cfg/{function_goid}` - Control flow graph (CFG) endpoint for a specific function GOID.
    - `/v1/flow/dfg/{function_goid}` - Data flow graph (DFG) endpoint for a specific function GOID.
    - `/admin/index/*` - Admin endpoints (gated by `CODEINTEL_ADMIN=1`):
      - `/admin/index/status` - Current index version and health status.
      - `/admin/index/publish` - Publish a staged index version (makes it active).
      - `/admin/index/rollback/{version}` - Rollback to a previous index version.
      - `/admin/index/tuning` - Session-scoped FAISS tuning overrides.
      - `/admin/index/tuning/faiss` - FAISS tuning parameter management (GET/POST/DELETE).
    - `/diagnostics/*` - Diagnostics endpoints (disabled, returns HTTP 501):
      - `/diagnostics/run_report/{run_id}` - Run report endpoint (disabled).
      - `/diagnostics/run_report/{run_id}.md` - Markdown run report endpoint (disabled).
  - Middleware (registered in order):
    - `CORSMiddleware` - CORS handling (allows origins, methods, headers, credentials).
    - `SessionScopeMiddleware` - Session ID extraction and context storage (extracts `X-Session-ID` header or generates UUID).
    - `TrustedHostMiddleware` - Host header validation (optional, enabled by default).
    - `inject_request_id` - Request ID injection (extracts `X-Request-Id` header or generates UUID, sets `X-Request-Id` response header).
    - `set_mcp_context` - ApplicationContext injection into context variable for MCP tools (sets `app_context` ContextVar).
    - `disable_nginx_buffering` - Sets `X-Accel-Buffering: no` header for streaming responses.
    - `ProxyFixMiddleware` - Proxy header handling (optional, enabled by default, supports `PROXY_TRUSTED_HOPS` env var).
  - Exception Handlers:
    - `http_exception_handler_with_request_id` - Formats HTTPException responses with request ID.
    - `unhandled_exception_handler` - Wraps unhandled exceptions in error envelope (status 500).
  - **MCP Tools Catalog** (exposed via `/mcp/tools`):
    - **Scope & Navigation**: `set_scope`, `list_paths`, `open_file`
    - **Search**: `search_text` (ripgrep-like), `semantic_search` (basic), `semantic_search_pro` (two-stage), `search` (deep research), `fetch` (deep research)
    - **Symbol Navigation**: `symbol_search`, `definition_at`, `references_at`
    - **History**: `blame_range`, `file_history`
    - **Telemetry**: `report:latest_run` (legacy placeholder), `telemetry_run_report` (disabled placeholder)
  - **MCP Resources** (exposed via `/mcp/resources`):
    - `file://{path}` - File content resource (serves file content via MCP resource protocol).
  - **MCP Prompts** (exposed via `/mcp/prompts`):
    - `prompt_code_review` - Code review prompt template (accepts `area` parameter).

- **CLI (Typer)**
  - Entry modules: `codeintel_rev.cli.*` (multiple commands).
  - Commands:
    - `codeintel indexctl` - Index lifecycle management:
      - `status` - Show current index version and health.
      - `stage` - Stage a new index version (FAISS, DuckDB, SCIP assets).
      - `publish` - Publish a staged version (makes it active).
      - `rollback` - Rollback to a previous version.
      - `ls` - List all staged versions.
      - `health` - Health check for index assets.
      - `export-idmap` - Export chunk ID mapping.
      - `materialize-join` - Materialize DuckDB join views.
      - `tune-params` - Tune FAISS search parameters.
      - `show-profile` - Display FAISS index profile.
      - `eval` - Run evaluation benchmarks.
      - `embeddings` - Embedding lifecycle subcommands (sub-typer).
    - `codeintel bm25` - BM25 sparse retrieval:
      - `prepare-corpus` - Prepare corpus for BM25 indexing.
      - `build-index` - Build BM25 inverted index.
    - `codeintel splade` - SPLADE learned sparse retrieval:
      - `export-onnx` - Export SPLADE model to ONNX format.
      - `encode` - Encode chunks using SPLADE ONNX encoder.
      - `build-index` - Build SPLADE impact index.
      - `bench` - Benchmark SPLADE encoding performance.
    - `codeintel enrich` - Code enrichment pipeline:
      - `scan` - Scan source files and extract metadata.
      - `analytics` - Generate analytics (ownership, metrics).
      - `callgraph` - Build call graph (caller-callee relationships).
      - `cfg` - Generate control flow graph (CFG).
      - `dfg` - Generate data flow graph (DFG).
      - `goids` - Generate Global Object Identifiers (GOIDs).
      - `audit` - Audit enrichment artifacts.
      - `to-duckdb` - Export enrichment artifacts to DuckDB.
      - `overlays` - Generate overlay metadata.
      - `exports` - Generate export metadata.
    - `codeintel build-indexes` - FAISS index building:
      - `bm25` - Build BM25 index.
      - `splade-impact` - Build SPLADE impact index.
      - `publish` - Publish built indexes.
  - Configuration: Loaded via `codeintel_rev.config.load_app_config()` from environment variables and optional config file.

### 4.2 Outbound Dependencies

- **DuckDB (Embedded Database)**
  - Client: `codeintel_rev.io.duckdb_manager.DuckDBManager`.
  - Used for: Chunk metadata catalog, symbol information, index registration, relational queries.
  - Connection pattern: Per-request connections via `DuckDBManager.get_connection()` (thread-safe, optionally pooled via `DUCKDB_POOL_SIZE`).
  - Schema: Defined in `codeintel_rev.io.duckdb_schema`; migrations in `registry/migrations/`.

- **FAISS (Vector Search)**
  - Client: `codeintel_rev.io.faiss_manager.FAISSManager`.
  - Used for: Dense vector similarity search over chunk embeddings.
  - Index types: Adaptive selection (Flat for <5K, IVFFlat for 5K-50K, IVF-PQ for >50K vectors).
  - Loading: Lazy by default; preload via `FAISS_PRELOAD=1` environment variable.

- **vLLM Embedding Service**
  - Client: `codeintel_rev.io.vllm_client.VLLMClient`.
  - Used for: Generating dense embeddings for code chunks (OpenAI-compatible API).
  - Connection pattern: HTTP connection pooling with persistent connections; closed during application shutdown.
  - Configuration: `VLLM_URL` environment variable (default: `http://127.0.0.1:8001/v1`).

- **BM25 Index (Sparse Retrieval)**
  - Client: `codeintel_rev.io.bm25_manager.BM25Manager`, `codeintel_rev.io.bm25_engine`.
  - Used for: Keyword-based sparse retrieval using Best Matching 25 ranking.
  - Storage: File-based index in `_indices/bm25/` directory.

- **SPLADE Index (Learned Sparse Retrieval)**
  - Client: `codeintel_rev.io.splade_manager.SPLADEManager`, `codeintel_rev.io.splade_onnx_encoder`.
  - Used for: Learned sparse retrieval using SPLADE expansion.
  - Storage: File-based impact index in `_indices/splade_impact/` directory.

- **Git Repository**
  - Client: `codeintel_rev.io.git_client.AsyncGitClient`.
  - Used for: File content retrieval, blame information, commit history.
  - Operations: Async via `asyncio.to_thread` to avoid blocking.

- **SCIP Index Files**
  - Parser: `codeintel_rev.indexing.scip_reader`.
  - Used for: Symbol definitions, references, documentation metadata.
  - Format: Protocol Buffers (`.scip`) or JSON (`.scip.json`).

- **NGINX (Production Edge)**
  - Role: HTTP/3 (QUIC) proxy, OAuth 2.1 authentication, streaming optimizations.
  - Configuration: `config/nginx/codeintel-mcp.conf`.
  - Integration: Sets `X-Accel-Buffering: no` header for streaming responses.

### 4.3 Trust Boundaries and Security

- **Input Validation**: All MCP tool inputs are validated via Pydantic models; path traversal prevented via `pathlib.Path.resolve()`. HTTP endpoint inputs validated via FastAPI/Pydantic request models.
- **Authentication**: OAuth 2.1 via NGINX (optional; configured per deployment). Admin endpoints (`/admin/index/*`) gated by `CODEINTEL_ADMIN=1` environment variable.
- **Error Handling**: Errors return RFC 9457 Problem Details; no stack traces exposed to clients. Unhandled exceptions wrapped in error envelope (status 500) with request ID.
- **Secrets**: All secrets via environment variables; never hardcoded or committed.
- **Host Header Validation**: `TrustedHostMiddleware` validates Host headers against `allowed_hosts` list (prevents host header injection attacks).
- **Proxy Trust**: `ProxyFixMiddleware` trusts up to `PROXY_TRUSTED_HOPS` proxy hops (default: 1) when parsing Forwarded headers.

---

## 5. Runtime Behavior & Key Flows

### 5.1 Flow: Application Startup – Initialization Sequence

**Trigger**

- FastAPI application startup via `lifespan()` context manager.
- Code entrypoints: `codeintel_rev.app.main.lifespan`, `codeintel_rev.app.main._initialize_context`.

**High-Level Steps**

1. Load configuration from environment variables via `ApplicationContext.create()` (fail-fast if invalid).
2. Run FAISS CPU health check (`check_faiss_health()`) to verify FAISS is importable and functional.
3. Initialize `ApplicationContext` containing:
   - `AppConfig` (immutable configuration)
   - `FAISSManager` (lazy-loaded)
   - `DuckDBManager` (connection manager)
   - `VLLMClient` (HTTP client with connection pooling)
   - `ScopeStore` (session-scoped query constraints)
   - `IndexLifecycleManager` (versioned index management)
4. Initialize `ReadinessProbe` and run initial readiness checks (validate FAISS index exists, DuckDB catalog accessible, vLLM reachable).
5. Optionally pre-load FAISS index if `FAISS_PRELOAD=1` (eager loading for production).
6. Optionally pre-load XTR index if `XTR_PRELOAD=1`.
7. Optionally pre-load HybridSearchEngine if `HYBRID_PRELOAD=1`.
8. Build capability snapshot (`Capabilities.from_context()`) and mount MCP HTTP app.
9. Start background task for session expiration pruning (runs every 10 minutes).
10. Install SIGHUP handler for index reload (Unix only).

**Components Involved**

- `codeintel_rev.app.main.lifespan`
- `codeintel_rev.app.config_context.ApplicationContext`
- `codeintel_rev.app.runtime_readiness.ReadinessProbe`
- `codeintel_rev.app.capabilities.Capabilities`
- `codeintel_rev.mcp_server.server.build_http_app`

**Key Invariants**

- Configuration is loaded once and treated as immutable.
- Application startup fails fast if required resources (FAISS index, DuckDB catalog) are missing.
- All runtime managers are initialized before accepting requests.

**Error Handling & Retries**

- Configuration errors propagate to `lifespan()` and cause FastAPI startup to fail.
- Readiness check failures are logged but do not prevent startup (readiness endpoint returns `ready: false`).
- Pre-load failures are logged but do not prevent startup (lazy loading will occur on first use).

### 5.2 Flow: Indexing Pipeline – Building Searchable Indexes

**Trigger**

- CLI command: `python codeintel_rev/bin/index_all.py` or `codeintel build-indexes all`.
- Code entrypoints: `codeintel_rev.bin.index_all`, `codeintel_rev.services.index.run_index_build`.

**High-Level Steps**

1. Load SCIP index (`index.scip` or `index.scip.json`) via `codeintel_rev.indexing.scip_reader`.
2. Parse SCIP documents and extract symbol information (definitions, references, documentation).
3. Chunk source files using cAST chunker (`codeintel_rev.indexing.cast_chunker.CASTChunker`):
   - Respect symbol boundaries (functions, classes, modules)
   - Target chunk size: ~2200 characters
   - Generate chunk IDs: `{file_path}:{start_line}:{end_line}`
4. Generate embeddings for chunks via vLLM client (`codeintel_rev.io.vllm_client.VLLMClient`):
   - Batch requests for efficiency
   - Store embeddings in Parquet files (`*.parquet` shards)
5. Build FAISS index (`codeintel_rev.io.faiss_manager.FAISSManager`):
   - Adaptive index type selection (Flat/IVFFlat/IVF-PQ based on corpus size)
   - Train index on sample vectors (up to `TRAINING_LIMIT` vectors)
   - Add all vectors to index in batches
   - Save index to disk (`*.faiss` file)
6. Build BM25 index (optional, via `codeintel bm25 build-index`):
   - Normalize corpus and build inverted index
   - Store in `_indices/bm25/` directory
7. Build SPLADE index (optional, via `codeintel splade build-index`):
   - Encode chunks using SPLADE ONNX encoder
   - Build impact index in `_indices/splade_impact/` directory
8. Register indexes in DuckDB catalog (`codeintel_rev.io.duckdb_catalog.DuckDBCatalog`):
   - Create chunk metadata records
   - Register FAISS index location and parameters
   - Create materialized views for joins (if `--materialize` flag set)

**Components Involved**

- `codeintel_rev.indexing.scip_reader`
- `codeintel_rev.indexing.cast_chunker.CASTChunker`
- `codeintel_rev.io.vllm_client.VLLMClient`
- `codeintel_rev.io.faiss_manager.FAISSManager`
- `codeintel_rev.io.parquet_store` (Parquet I/O)
- `codeintel_rev.io.duckdb_catalog.DuckDBCatalog`
- `codeintel_rev.cli.bm25`, `codeintel_rev.cli.splade` (sparse index building)

**Key Invariants**

- Chunk IDs must be deterministic and idempotent for a given (file_path, start_line, end_line).
- FAISS index training must use a representative sample of vectors.
- DuckDB catalog must maintain referential integrity (chunks reference files, indexes reference chunks).

**Error Handling & Retries**

- SCIP parsing errors are logged and skipped (file-level granularity).
- Embedding failures are retried with exponential backoff (via `tenacity`).
- FAISS index build failures are fatal (index is not created).
- DuckDB registration failures are logged but do not prevent index creation.

### 5.3 Flow: Semantic Search – Querying Code with Natural Language

**Trigger**

- MCP tool call: `semantic_search(query, limit)`.
- HTTP endpoint: `POST /mcp/tools/semantic_search`.
- Code entrypoints: `codeintel_rev.mcp_server.adapters.semantic.semantic_search`, `codeintel_rev.retrieval.pipeline.stage0.run_stage0`.

**High-Level Steps**

1. Extract query from MCP tool request and validate (non-empty string, limit > 0).
2. Apply session scope constraints (`codeintel_rev.app.scope_store.ScopeStore`):
   - Filter by path patterns (`include_globs`, `exclude_globs`)
   - Filter by languages (`languages`)
   - Override with explicit parameters if provided
3. Execute **Stage 0** hybrid retrieval (`codeintel_rev.retrieval.pipeline.stage0.run_stage0`):
   - Generate query embedding via vLLM client
   - Search dense index (FAISS) → top-K candidates (default: 200)
   - Search sparse indexes in parallel (BM25, SPLADE) → top-K candidates each
   - Fuse results using RRF (Reciprocal Rank Fusion)
   - Return Stage-0 result: `(ids, scores, warnings, method)`
4. Evaluate **Stage 1 gating** (`codeintel_rev.retrieval.pipeline.gating.decide_secondary_stage`):
   - Check candidate count, score margins, time budget
   - Decide whether to run optional Stage 1 (late interaction, reranking)
5. Hydrate results from DuckDB catalog (`codeintel_rev.io.duckdb_catalog.DuckDBCatalog`):
   - Join chunk IDs to chunk metadata (file_path, start_line, end_line, symbol info)
   - Filter by scope constraints (path patterns, languages)
6. Return results as MCP tool response (`AnswerEnvelope` with findings, answer, confidence).

**Components Involved**

- `codeintel_rev.mcp_server.adapters.semantic.semantic_search`
- `codeintel_rev.retrieval.pipeline.stage0.run_stage0` (Stage 0 execution)
- `codeintel_rev.retrieval.pipeline.gating.decide_secondary_stage` (Stage 1 gating)
- `codeintel_rev.app.scope_store.ScopeStore`
- `codeintel_rev.io.vllm_client.VLLMClient`
- `codeintel_rev.io.faiss_manager.FAISSManager`
- `codeintel_rev.io.duckdb_catalog.DuckDBCatalog`

**Key Invariants**

- Query embedding must use the same model as chunk embeddings (vector dimension must match).
- Stage-0 fusion must be deterministic (same inputs → same outputs).
- Scope constraints must be applied after fusion (not during individual searches).
- Error handling decorator (`@handle_adapter_errors`) converts exceptions to RFC 9457 Problem Details with empty result fallbacks.

**Error Handling & Retries**

- vLLM embedding failures are retried with exponential backoff.
- FAISS search failures return empty results (logged, handled by error decorator).
- DuckDB hydration failures return partial results (logged, handled by error decorator).
- All exceptions are caught by `@handle_adapter_errors` decorator and converted to structured error responses.

### 5.4 Flow: Hybrid Search – Combining Dense, Sparse, and Symbol Signals

**Trigger**

- Internal call from semantic search adapter or direct MCP tool.
- Code entrypoints: `codeintel_rev.retrieval.hybrid_search.HybridSearchEngine.search`, `codeintel_rev.io.rrf.reciprocal_rank_fusion`.

**High-Level Steps**

1. Generate query embedding via vLLM client.
2. Search dense index (FAISS) and return top-K candidates (default: 200).
3. Search sparse indexes in parallel:
   - BM25 search (`codeintel_rev.io.bm25_manager.BM25Manager.search`) → top-K candidates
   - SPLADE search (`codeintel_rev.io.splade_manager.SPLADEManager.search`) → top-K candidates
4. Search symbol index (DuckDB catalog) for symbol matches (optional).
5. Combine results using RRF (Reciprocal Rank Fusion):
   - Assign ranks to each candidate from each signal
   - Compute RRF score: `sum(1 / (k + rank))` for each candidate
   - Sort by RRF score descending
6. Apply scope constraints (path patterns, languages).
7. Hydrate final results from DuckDB catalog.
8. Return top-K fused results.

**Components Involved**

- `codeintel_rev.retrieval.hybrid_search.HybridSearchEngine`
- `codeintel_rev.io.faiss_manager.FAISSManager`
- `codeintel_rev.io.bm25_manager.BM25Manager`
- `codeintel_rev.io.splade_manager.SPLADEManager`
- `codeintel_rev.io.rrf.reciprocal_rank_fusion`
- `codeintel_rev.io.duckdb_catalog.DuckDBCatalog`

**Key Invariants**

- RRF fusion must be deterministic (same inputs → same outputs).
- All sparse indexes must use the same corpus normalization.
- Scope constraints must be applied after fusion (not during individual searches).

**Error Handling & Retries**

- Individual search failures (BM25, SPLADE) are logged and that signal is skipped (other signals still used).
- RRF fusion continues with available signals.

### 5.5 Flow: Symbol Navigation – Finding Definitions and References

**Trigger**

- MCP tool calls: `symbol_search(query, kind, language)`, `definition_at(path, line, char)`, `references_at(path, line, char)`.
- Code entrypoints: `codeintel_rev.mcp_server.adapters.symbols`.

**High-Level Steps**

1. Parse tool request and extract parameters (query, symbol kind, language, or file path + position).
2. Query DuckDB catalog (`codeintel_rev.io.duckdb_catalog.DuckDBCatalog`):
   - For `symbol_search`: Filter symbols by name, kind, language
   - For `definition_at`: Lookup symbol at file path + line/char position
   - For `references_at`: Lookup all references to symbol at position
3. Apply scope constraints (path patterns, languages).
4. Return results as MCP tool response (list of symbols with metadata: file_path, line, char, kind, documentation).

**Components Involved**

- `codeintel_rev.mcp_server.adapters.symbols`
- `codeintel_rev.io.duckdb_catalog.DuckDBCatalog`
- `codeintel_rev.app.scope_store.ScopeStore`

**Key Invariants**

- Symbol information must come from SCIP index (not inferred from source code).
- Position lookups (line, char) must be precise (SCIP provides exact character offsets).

**Error Handling & Retries**

- Missing symbols return empty results (logged).
- Invalid file paths return error responses.

### 5.6 Flow: Semantic Search Pro – Two-Stage Retrieval with Late Interaction

**Trigger**

- MCP tool call: `semantic_search_pro(query, limit, options)`.
- HTTP endpoint: `POST /mcp/tools/semantic_search_pro`.
- Code entrypoints: `codeintel_rev.mcp_server.adapters.semantic_pro.semantic_search_pro`.

**High-Level Steps**

1. Extract query and options from MCP tool request.
2. Execute **Stage 0** (CodeRank hybrid search):
   - Run hybrid retrieval (FAISS + BM25 + SPLADE) with RRF fusion
   - Return top-K candidates (default: 200)
3. Evaluate **Stage 1 gating** (`codeintel_rev.retrieval.pipeline.gating.decide_secondary_stage`):
   - Check candidate count, score margins, time budget
   - If gating passes and `use_warp=True`, run WARP late interaction (`codeintel_rev.rerank.xtr`):
     - Cross-token attention reranking using XTR index
     - Rerank Stage-0 candidates
4. Optionally run LLM reranker (`use_reranker=True`):
   - Send candidates to LLM reranking service
   - Return reranked results
5. Hydrate results from DuckDB catalog.
6. Return results as MCP tool response (`AnswerEnvelope`).

**Components Involved**

- `codeintel_rev.mcp_server.adapters.semantic_pro.semantic_search_pro`
- `codeintel_rev.retrieval.pipeline.stage0.run_stage0` (Stage 0)
- `codeintel_rev.retrieval.pipeline.gating.decide_secondary_stage` (Stage 1 gating)
- `codeintel_rev.rerank.xtr.XTRReranker` (WARP late interaction)
- `codeintel_rev.io.duckdb_catalog.DuckDBCatalog` (hydration)

**Key Invariants**

- Stage 1 (WARP/reranker) is optional and gated by Stage-0 signals.
- WARP requires XTR index to be available (checked via capabilities).
- LLM reranker is optional and requires external service.

**Error Handling & Retries**

- Stage-0 failures return empty results (handled by error decorator).
- WARP failures fall back to Stage-0 results (logged).
- LLM reranker failures fall back to Stage-0/WARP results (logged).

### 5.7 Flow: Deep Research Search/Fetch – Two-Phase Chunk Retrieval

**Trigger**

- MCP tool calls: `search(query, top_k, filters, rerank)` and `fetch(object_ids, max_tokens)`.
- HTTP endpoints: `POST /mcp/tools/search`, `POST /mcp/tools/fetch`.
- Code entrypoints: `codeintel_rev.mcp_server.adapters.deep_research.search`, `codeintel_rev.mcp_server.adapters.deep_research.fetch`.

**High-Level Steps**

**Phase 1: Search**
1. Extract query, top_k, filters from MCP tool request.
2. Execute semantic search (same as `semantic_search` flow):
   - Stage-0 hybrid retrieval (FAISS + BM25 + SPLADE)
   - Optional Stage-1 (WARP, reranker) if gating passes
3. Return `SearchStructuredContent` with chunk IDs, titles, URLs, snippets, scores (no full content).

**Phase 2: Fetch**
1. Extract object_ids (chunk ID strings) from MCP tool request.
2. Normalize chunk IDs to integers.
3. Query DuckDB catalog for full chunk content:
   - Join chunk IDs to chunk metadata
   - Retrieve full content (truncated to `max_tokens` if specified)
4. Return `FetchStructuredContent` with full chunk contents and provenance metadata.

**Components Involved**

- `codeintel_rev.mcp_server.adapters.deep_research.search`
- `codeintel_rev.mcp_server.adapters.deep_research.fetch`
- `codeintel_rev.retrieval.mcp_search.run_search` (search implementation)
- `codeintel_rev.retrieval.mcp_search.run_fetch` (fetch implementation)
- `codeintel_rev.io.duckdb_catalog.DuckDBCatalog`

**Key Invariants**

- Search returns chunk IDs only (no full content).
- Fetch requires chunk IDs from previous search (or known chunk IDs).
- Chunk content is truncated to `max_tokens` (default: 4000, clamped to [256, 16000]).

**Error Handling & Retries**

- Search failures return empty results (handled by error decorator).
- Fetch failures for missing chunk IDs omit those chunks (partial results).

### 5.8 Flow: Index Lifecycle Management – Staging and Publishing Versions

**Trigger**

- CLI command: `codeintel indexctl stage --version v1 --faiss ... --duckdb ... --scip ...`.
- Code entrypoints: `codeintel_rev.cli.indexctl`, `codeintel_rev.indexing.index_lifecycle.IndexLifecycleManager`.

**High-Level Steps**

1. Validate index assets (FAISS index exists, DuckDB catalog accessible, SCIP index exists).
2. Compute asset checksums (SHA256) for integrity verification.
3. Stage assets to versioned directory (`indexes/versions/v1/`):
   - Copy FAISS index file
   - Copy DuckDB catalog file
   - Copy SCIP index file
   - Write metadata JSON (`index_assets.json`) with checksums and paths
4. Register version in DuckDB catalog (if `--register` flag set).
5. Publish version (make it active) via `codeintel indexctl publish --version v1`:
   - Update symlink `indexes/active -> indexes/versions/v1`
   - Reload indexes in ApplicationContext (if server running, via SIGHUP)

**Components Involved**

- `codeintel_rev.cli.indexctl`
- `codeintel_rev.indexing.index_lifecycle.IndexLifecycleManager`
- `codeintel_rev.indexing.index_lifecycle.IndexAssets`
- `codeintel_rev.app.config_context.ApplicationContext.reload_indices`

**Key Invariants**

- Index versions must be immutable (no modifications after staging).
- Only one version can be active at a time (symlink-based).
- Asset checksums must match on load (integrity verification).

**Error Handling & Retries**

- Invalid assets (missing files, checksum mismatches) prevent staging.
- Publish failures do not corrupt existing active version.

### 5.9 Flow: Code Enrichment Pipeline – Extracting AST/CST Metadata

**Trigger**

- CLI command: `codeintel enrich pipeline` or `codeintel enrich scan`.
- Code entrypoints: `codeintel_rev.cli.enrich_pipeline`, `codeintel_rev.services.enrich`.

**High-Level Steps**

1. Load SCIP index (`index.scip` or `index.scip.json`) via `codeintel_rev.indexing.scip_reader`.
2. Parse source files and extract AST nodes (`codeintel_rev.enrich.ast_indexer`):
   - Extract functions, classes, imports, decorators using Python `ast` module
   - Generate qualnames (fully qualified names) for each node
   - Extract docstrings, bases, decorators
   - Compute metrics (cyclomatic complexity, cognitive complexity, branch counts)
3. Parse source files with LibCST (`codeintel_rev.cst_build`):
   - Build lossless CST preserving exact formatting
   - Extract imports, exports, `__all__` declarations
   - Resolve re-exports and star imports
4. Extract dependency graphs (`codeintel_rev.enrich.graph_builder`):
   - Build symbol-to-file edges from SCIP
   - Build import dependency graphs from LibCST
   - Generate `symbol_graph.json` with deduplicated edges
5. Compute ownership analytics (`codeintel_rev.enrich.ownership`):
   - Git blame analysis per file
   - Primary author identification
   - Bus factor calculation
   - Churn metrics (30-day, 90-day windows)
6. Generate module summaries (`codeintel_rev.enrich.module_meta`):
   - Per-module JSONL records with imports/exports/definitions
   - Human-readable Markdown briefs
   - Tag assignments (via `tagging_rules.yaml`)
7. Write enrichment artifacts:
   - `ast/ast_nodes.parquet` - AST node inventory
   - `ast/ast_metrics.parquet` - File-level metrics
   - `analytics/ownership.parquet` - Git ownership data
   - `modules/*.jsonl` - Module summaries
   - `modules/*.md` - Human-readable module briefs
   - `graphs/symbol_graph.json` - Symbol dependency graph
   - `tags/tags_index.yaml` - Tag catalog

**Components Involved**

- `codeintel_rev.enrich.ast_indexer.ASTIndexer`
- `codeintel_rev.cst_build.cst_collect` (LibCST parsing)
- `codeintel_rev.enrich.graph_builder.GraphBuilder`
- `codeintel_rev.enrich.ownership.OwnershipAnalyzer`
- `codeintel_rev.enrich.module_meta.ModuleMetaBuilder`
- `codeintel_rev.services.enrich` (orchestration)

**Key Invariants**

- AST extraction must preserve qualnames (fully qualified names) for symbol resolution.
- CST parsing must be lossless (round-trip to original source).
- Dependency graphs must be deduplicated (same edge appears once).

**Error Handling & Retries**

- AST parsing errors are logged and skipped (file-level granularity).
- CST parsing errors fall back to AST parsing (graceful degradation).
- Git operations failures are logged but do not prevent enrichment (ownership data may be missing).

---

## 6. Static Structure: Layers, Modules, and Dependencies

### 6.1 Layer Overview

We structure the system into five logical layers:

1. **Entrypoints Layer** – HTTP endpoints, CLI commands, MCP tool registration
2. **Services Layer** – Business logic orchestration
3. **Domain Models Layer** – Pure domain logic (algorithms, data structures)
4. **IO/Infrastructure Layer** – External system adapters
5. **Configuration Layer** – Configuration loading and path resolution

Each layer may only depend on layers below it (lower layers must not import higher layers).

### 6.2 Module Catalog

#### Module: `codeintel_rev/app/main.py`

**Role**

FastAPI application entrypoint providing HTTP endpoints (`/healthz`, `/readyz`, `/capz`, `/mcp/*`, `/v1/*`, `/admin/*`, `/diagnostics/*`), middleware (CORS, session scope, proxy fix, request ID injection, MCP context, NGINX buffering), exception handlers, and application lifecycle management (startup/shutdown).

**Public Surface**

- `codeintel_rev.app.main.app` - FastAPI application instance
- `codeintel_rev.app.main.asgi` - ASGI application (with optional ProxyFix middleware)
- `codeintel_rev.app.main.lifespan` - Application lifespan context manager
- `codeintel_rev.app.main.override_app_hooks` - Test-only context manager for overriding lifecycle hooks
- `codeintel_rev.app.main.AppLifecycleHooks` - Lifecycle hook override dataclass

**Dependencies**

- Calls into:
  - `codeintel_rev.app.config_context.ApplicationContext`
  - `codeintel_rev.app.runtime_readiness.ReadinessProbe`
  - `codeintel_rev.app.capabilities.Capabilities`
  - `codeintel_rev.mcp_server.server.build_http_app`
  - `codeintel_rev.app.routers.catalog_read` (catalog read APIs)
  - `codeintel_rev.app.routers.index_admin` (admin endpoints, gated by `CODEINTEL_ADMIN`)
  - `codeintel_rev.app.server_settings.ServerSettings` (server configuration)
- Used by:
  - Hypercorn/Uvicorn ASGI servers
  - NGINX reverse proxy

**Invariants**

- Configuration is loaded once at startup and treated as immutable.
- Application startup fails fast if required resources are missing.
- All middleware must be registered in correct order (CORS → SessionScope → TrustedHost → request_id → mcp_context → nginx_buffering).
- Request ID is always present in request state and response headers.
- ApplicationContext is always available in context variable for MCP tools.

**Extension Points**

- To add a new HTTP endpoint:
  - Add route handler to `app` instance in `main.py` or create a router in `codeintel_rev.app.routers.*`.
  - Follow RFC 9457 Problem Details for error responses.
  - Include request ID in response headers (automatic via middleware).
- To add a new router:
  - Create router module in `codeintel_rev.app.routers.*`.
  - Include router via `app.include_router()` in `main.py`.
  - Use `Depends(_context_dependency)` for ApplicationContext access.

**Anti-Patterns**

- Do **not** import IO/infrastructure modules directly (use ApplicationContext).
- Do **not** perform blocking I/O in request handlers (use `asyncio.to_thread`).
- Do **not** access ApplicationContext via request injection in MCP tools (use context variable).

#### Module: `codeintel_rev/app/config_context.py`

**Role**

Manages application-wide context containing configuration, clients, and runtime managers. Provides dependency injection for request handlers and MCP tools.

**Public Surface**

- `codeintel_rev.app.config_context.ApplicationContext` - Immutable context container
- `codeintel_rev.app.config_context.ApplicationContext.create()` - Factory method
- `codeintel_rev.app.config_context.ApplicationContext.close_all_runtimes()` - Cleanup method
- **Runtime Accessors** (lazy-loaded via RuntimeCell):
  - `get_hybrid_engine()` - Hybrid search engine (FAISS + BM25 + SPLADE fusion)
  - `get_coderank_faiss_manager(vec_dim)` - CodeRank FAISS manager for specific vector dimension
  - `get_xtr_index()` - XTR token-level index (optional, returns None if disabled)
  - `get_offline_recall_evaluator()` - Offline evaluation system for diagnostic runs
- **Catalog Access**:
  - `open_catalog()` - Context manager yielding DuckDBCatalog instance
- **Runtime Management**:
  - `reload_indices()` - Close runtime cells to force reload from active index version
  - `apply_factory_adjuster(adjuster)` - Update runtime tuning knobs (FAISS nprobe, RRF weights)
  - `ensure_faiss_ready()` - Thread-safe FAISS index loading (returns ready status, limits, error)
- **Hybrid Search Helpers**:
  - `hybrid_fusion_weights()` - Return per-channel fusion weights (bm25, splade, semantic)
  - `hybrid_search_settings()` - Return immutable SearchSettings from AppConfig
  - `clamp_hybrid_limit(requested)` - Clamp requested limit to configured bounds
  - `build_stage0_options(weights)` - Build Stage0Options from AppConfig search settings
- **Test Helpers**:
  - `with_overrides(**components)` - Create new context with component overrides
  - `seed_runtime_cells_for_tests(**runtimes)` - Seed runtime cells with test doubles (test-only)

**Dependencies**

- Calls into:
  - `codeintel_rev.config.load_app_config`
  - `codeintel_rev.io.faiss_manager.FAISSManager`
  - `codeintel_rev.io.duckdb_manager.DuckDBManager`
  - `codeintel_rev.io.vllm_client.VLLMClient`
  - `codeintel_rev.app.scope_store.ScopeStore`
  - `codeintel_rev.indexing.index_lifecycle.IndexLifecycleManager`
- Used by:
  - `codeintel_rev.app.main` (startup/shutdown)
  - `codeintel_rev.mcp_server.adapters` (via context variable)

**Invariants**

- ApplicationContext is created once at startup and shared across all requests.
- Configuration is immutable after creation.
- All runtime managers are initialized before first use (lazy loading).

**Extension Points**

- To add a new runtime manager:
  - Add property to `ApplicationContext` class.
  - Initialize in `ApplicationContext.create()`.
  - Close in `ApplicationContext.close_all_runtimes()`.

**Anti-Patterns**

- Do **not** create multiple ApplicationContext instances (singleton pattern).
- Do **not** modify configuration after creation.

#### Module: `codeintel_rev/io/faiss_manager.py`

**Role**

Manages FAISS vector similarity search indexes. Handles index building, loading, searching, and adaptive index type selection (Flat/IVFFlat/IVF-PQ).

**Public Surface**

- `codeintel_rev.io.faiss_manager.FAISSManager` - FAISS index manager
- `codeintel_rev.io.faiss_manager.FAISSManager.search()` - Vector similarity search
- `codeintel_rev.io.faiss_manager.FAISSManager.load_cpu_index()` - Load index from disk
- `codeintel_rev.io.faiss_manager.FAISSManager.build_index()` - Build index from vectors

**Dependencies**

- Calls into:
  - `faiss` (Facebook AI Similarity Search library)
  - `numpy` (vector operations)
  - `pyarrow.parquet` (reading embeddings from Parquet)
- Used by:
  - `codeintel_rev.services.index` (index building)
  - `codeintel_rev.retrieval.hybrid_search` (dense search)
  - `codeintel_rev.mcp_server.adapters.semantic` (semantic search)

**Invariants**

- FAISS indexes must be built with the same vector dimension as queries.
- Index type selection (Flat/IVFFlat/IVF-PQ) is deterministic based on corpus size.
- Search parameters (`nprobe`, `efSearch`) must be set appropriately for index type.

**Extension Points**

- To add a new index type:
  - Extend `FAISSManager._select_index_type()` method.
  - Add training and building logic.
  - Update `estimate_memory_usage()` method.

**Anti-Patterns**

- Do **not** hold global FAISS index objects (use lazy loading per ApplicationContext).
- Do **not** mix index types in a single search (each index has its own parameters).

#### Module: `codeintel_rev/io/duckdb_manager.py`

**Role**

Manages DuckDB database connections and provides thread-safe access to the catalog. Handles connection pooling (optional) and per-connection pragma configuration.

**Public Surface**

- `codeintel_rev.io.duckdb_manager.DuckDBManager` - Connection manager
- `codeintel_rev.io.duckdb_manager.DuckDBManager.get_connection()` - Get thread-safe connection
- `codeintel_rev.io.duckdb_manager.DuckDBConfig` - Configuration dataclass

**Dependencies**

- Calls into:
  - `duckdb` (embedded database)
- Used by:
  - `codeintel_rev.io.duckdb_catalog.DuckDBCatalog` (all catalog operations)
  - `codeintel_rev.services.index` (index registration)

**Invariants**

- Every request obtains its own connection (no shared global connections).
- Connection pragmas (`PRAGMA enable_object_cache`, `SET threads`) are applied on every new connection.
- Connection pooling (if enabled) is bounded (`DUCKDB_POOL_SIZE`).

**Extension Points**

- To add a new catalog table:
  - Add schema definition to `codeintel_rev.io.duckdb_schema`.
  - Add migration SQL to `registry/migrations/`.
  - Add accessor methods to `DuckDBCatalog`.

**Anti-Patterns**

- Do **not** hold connections across request boundaries.
- Do **not** modify schema without migrations.

#### Module: `codeintel_rev/indexing/cast_chunker.py`

**Role**

Chunks source code files using structure-aware algorithms (cAST) that respect symbol boundaries. Generates deterministic chunk IDs and maintains chunk metadata.

**Public Surface**

- `codeintel_rev.indexing.cast_chunker.CASTChunker` - Chunker class
- `codeintel_rev.indexing.cast_chunker.CASTChunker.chunk_file()` - Chunk a single file
- `codeintel_rev.indexing.cast_chunker.Chunk` - Chunk data model

**Dependencies**

- Calls into:
  - `codeintel_rev.indexing.scip_reader` (symbol information)
  - Standard library (file I/O, pathlib)
- Used by:
  - `codeintel_rev.bin.index_all` (indexing pipeline)
  - `codeintel_rev.services.index` (index building)

**Invariants**

- Chunk IDs must be deterministic: `{file_path}:{start_line}:{end_line}`.
- Chunks must respect symbol boundaries (functions, classes, modules).
- Target chunk size: ~2200 characters (configurable).

**Extension Points**

- To add a new chunking strategy:
  - Implement `Chunker` protocol.
  - Add to `CASTChunker` or create new chunker class.
  - Update indexing pipeline to use new chunker.

**Anti-Patterns**

- Do **not** chunk across symbol boundaries arbitrarily.
- Do **not** generate non-deterministic chunk IDs.

#### Module: `codeintel_rev/retrieval/hybrid_search.py`

**Role**

Orchestrates hybrid search combining dense (FAISS), sparse (BM25/SPLADE), and symbol signals using RRF (Reciprocal Rank Fusion).

**Public Surface**

- `codeintel_rev.retrieval.hybrid_search.HybridSearchEngine` - Hybrid search engine
- `codeintel_rev.retrieval.hybrid_search.HybridSearchEngine.search()` - Execute hybrid search
- `codeintel_rev.io.rrf.reciprocal_rank_fusion()` - RRF fusion algorithm

**Dependencies**

- Calls into:
  - `codeintel_rev.io.faiss_manager.FAISSManager` (dense search)
  - `codeintel_rev.io.bm25_manager.BM25Manager` (BM25 search)
  - `codeintel_rev.io.splade_manager.SPLADEManager` (SPLADE search)
  - `codeintel_rev.io.duckdb_catalog.DuckDBCatalog` (symbol search, result hydration)
  - `codeintel_rev.io.rrf` (fusion algorithm)
- Used by:
  - `codeintel_rev.mcp_server.adapters.semantic` (semantic search adapter)

**Invariants**

- RRF fusion must be deterministic (same inputs → same outputs).
- All search signals must use the same corpus normalization.
- Scope constraints must be applied after fusion.

**Extension Points**

- To add a new search signal:
  - Implement search method returning `list[SearchResult]`.
  - Add to `HybridSearchEngine.search()` method.
  - Include in RRF fusion.

**Anti-Patterns**

- Do **not** apply scope constraints during individual searches (apply after fusion).
- Do **not** mix different corpus normalizations across signals.

#### Module: `codeintel_rev/mcp_server/server.py`

**Role**

FastMCP server providing MCP tool registration and HTTP endpoint mounting. Manages tool catalog and capability gating. Registers scope/navigation, search, symbol, and history tools.

**Public Surface**

- `codeintel_rev.mcp_server.server.build_http_app()` - Build FastMCP HTTP app
- `codeintel_rev.mcp_server.server.app_context` - Context variable for ApplicationContext
- `codeintel_rev.mcp_server.server.get_context()` - Extract ApplicationContext from context variable

**Dependencies**

- Calls into:
  - `fastmcp` (FastMCP framework)
  - `codeintel_rev.mcp_server.adapters.*` (tool implementations)
  - `codeintel_rev.mcp_server.server_semantic` (semantic search tools)
  - `codeintel_rev.mcp_server.server_symbols` (symbol navigation tools)
- Used by:
  - `codeintel_rev.app.main` (mounted at `/mcp`)

**Invariants**

- MCP tools must be registered before server startup.
- Tool capabilities are gated by `Capabilities` snapshot.
- ApplicationContext is accessed via context variable (not request injection).
- All tool functions use `@handle_adapter_errors` decorator for consistent error handling.

**Registered Tools**

- **Scope & Navigation**: `set_scope`, `list_paths`, `open_file`
- **Search**: `search_text`, `semantic_search`, `semantic_search_pro`, `search` (deep research), `fetch` (deep research)
- **Symbols**: `symbol_search`, `definition_at`, `references_at` (registered in `server_symbols.py`)
- **History**: `blame_range`, `file_history`
- **Telemetry**: `report:latest_run`

**Extension Points**

- To add a new MCP tool:
  - Implement tool function in `codeintel_rev.mcp_server.adapters.*`.
  - Register tool via `@mcp.tool()` decorator (must be first decorator).
  - Apply `@handle_adapter_errors` decorator (must be second decorator).
  - Add capability gate if tool requires specific runtime.

**Anti-Patterns**

- Do **not** access ApplicationContext via request injection (use context variable).
- Do **not** register tools that require unavailable runtimes (gate by capabilities).
- Do **not** apply `@handle_adapter_errors` before `@mcp.tool()` (decorator order matters).

#### Module: `codeintel_rev/config/loader.py`

**Role**

Loads application configuration from environment variables and optional config file. Provides typed `AppConfig` dataclass.

**Public Surface**

- `codeintel_rev.config.load_app_config()` - Load configuration factory
- `codeintel_rev.config.AppConfig` - Configuration dataclass

**Dependencies**

- Calls into:
  - `pydantic_settings` (configuration loading)
  - Standard library (`os.environ`, `pathlib`)
- Used by:
  - `codeintel_rev.app.config_context.ApplicationContext.create()` (startup)
  - `codeintel_rev.cli.*` (CLI commands)

**Invariants**

- Configuration is loaded once and treated as immutable.
- Invalid configuration causes fail-fast (raises exception).
- Environment variables take precedence over config file.

**Extension Points**

- To add a new configuration key:
  - Add field to `AppConfig` dataclass with default value.
  - Document in `codeintel_rev.docs.CONFIGURATION.md`.
  - Add environment variable name to documentation.

**Anti-Patterns**

- Do **not** read environment variables directly in business logic (use `AppConfig`).
- Do **not** modify configuration at runtime.

#### Module: `codeintel_rev/app/server_settings.py`

**Role**

Centralizes HTTP listener parameters, CORS defaults, and proxy trust knobs for FastAPI + Hypercorn deployment. Settings are loaded from environment variables with `CODEINTEL_SERVER_` prefix.

**Public Surface**

- `codeintel_rev.app.server_settings.ServerSettings` - Server configuration dataclass
- `codeintel_rev.app.server_settings.get_server_settings()` - Cached settings factory

**Dependencies**

- Calls into:
  - `pydantic_settings.BaseSettings` (configuration loading)
- Used by:
  - `codeintel_rev.app.main` (middleware configuration, SSE settings)

**Invariants**

- Settings are loaded once and cached (LRU cache).
- SSE keep-alive interval is clamped to minimum 5.0 seconds.
- CORS defaults allow ChatGPT and localhost origins.

**Extension Points**

- To add a new server setting:
  - Add field to `ServerSettings` dataclass with default value.
  - Document environment variable name (with `CODEINTEL_SERVER_` prefix).
  - Add validation if needed (via `@model_validator`).

**Anti-Patterns**

- Do **not** access settings directly via `os.environ` (use `ServerSettings`).
- Do **not** modify settings at runtime (immutable after creation).

#### Module: `codeintel_rev/app/capabilities.py`

**Role**

Runtime capability detection system that checks for available runtimes (FAISS, DuckDB, vLLM, XTR) and generates capability snapshots. Used for conditional MCP tool registration and `/capz` endpoint.

**Public Surface**

- `codeintel_rev.app.capabilities.Capabilities` - Capability snapshot dataclass
- `codeintel_rev.app.capabilities.Capabilities.from_context()` - Build capability snapshot from ApplicationContext
- `codeintel_rev.app.capabilities.override_capabilities()` - Test-only capability override context manager
- `codeintel_rev.app.capabilities.override_capability_imports()` - Test-only import override context manager

**Dependencies**

- Calls into:
  - `codeintel_rev.io.faiss_compat.load_faiss_module` (FAISS import check)
  - Standard library (`importlib`, `hashlib`)
- Used by:
  - `codeintel_rev.app.main` (`/capz` endpoint)
  - `codeintel_rev.mcp_server.server` (capability gating)

**Invariants**

- Capability detection is import-based (checks if optional modules are importable).
- Capability snapshot is built once at startup and cached.
- Capability overrides are test-only (gated by context managers).

**Extension Points**

- To add a new capability check:
  - Add capability hint attribute to `_CAPABILITY_HINT_ATTRS` mapping.
  - Add capability field to `Capabilities` dataclass.
  - Update `Capabilities.from_context()` to check runtime availability.

**Anti-Patterns**

- Do **not** use capability overrides in production code (test-only).
- Do **not** bypass capability checks when registering tools.

#### Module: `codeintel_rev/mcp_server/error_handling.py`

**Role**

Provides `@handle_adapter_errors` decorator pattern for consistent MCP tool error handling. Converts exceptions to RFC 9457 Problem Details with empty result fallbacks.

**Public Surface**

- `codeintel_rev.mcp_server.error_handling.handle_adapter_errors()` - Error handling decorator
- `codeintel_rev.mcp_server.error_handling.format_error_response()` - Format exception as Problem Details
- `codeintel_rev.mcp_server.error_handling.convert_exception_to_envelope()` - Convert exception to error envelope

**Dependencies**

- Calls into:
  - `codeintel_rev.errors.*` (exception taxonomy)
  - `kgfoundry_common.errors.problem_details` (Problem Details helpers)
  - Standard library (`logging`, `traceback`)
- Used by:
  - All MCP tool adapters (via decorator)

**Invariants**

- Decorator must be applied **after** `@mcp.tool()` decorator.
- All exceptions are caught and converted to Problem Details.
- Empty result structure must match tool's success response schema.

**Extension Points**

- To customize error handling:
  - Extend `format_error_response()` to add custom exception mappings.
  - Add custom Problem Details types to exception taxonomy.

**Anti-Patterns**

- Do **not** apply `@handle_adapter_errors` before `@mcp.tool()` (decorator order matters).
- Do **not** catch exceptions manually in tool functions (let decorator handle them).

#### Module: `codeintel_rev/app/middleware.py`

**Role**

Provides FastAPI middleware for session management and request context propagation. Extracts or generates session IDs, stores them in ContextVar for MCP tool access, and manages capability stamps.

**Public Surface**

- `codeintel_rev.app.middleware.SessionScopeMiddleware` - Middleware class for session ID extraction
- `codeintel_rev.app.middleware.get_session_id()` - Helper to retrieve session ID from ContextVar
- `codeintel_rev.app.middleware.get_capability_stamp()` - Helper to retrieve capability stamp from ContextVar

**Dependencies**

- Calls into:
  - `codeintel_rev.runtime.request_context.session_id_var` (ContextVar for session ID)
  - `codeintel_rev.runtime.request_context.capability_stamp_var` (ContextVar for capability stamp)
  - Standard library (`uuid` for session ID generation)
- Used by:
  - `codeintel_rev.app.main` (middleware registration)
  - `codeintel_rev.mcp_server.adapters.*` (via `get_session_id()`)

**Invariants**

- Session ID is always present in request state and ContextVar after middleware execution.
- Session ID is extracted from `X-Session-ID` header or auto-generated as UUID.
- Capability stamp is set from `app.state.capability_stamp` if available.

**Extension Points**

- To access session ID in adapters:
  - Call `get_session_id()` within request handler context.
  - Session ID is automatically available via ContextVar.

**Anti-Patterns**

- Do **not** call `get_session_id()` outside request handler context (raises RuntimeError).
- Do **not** manually set session ID in adapters (use middleware).

#### Module: `codeintel_rev/app/runtime_readiness.py`

**Role**

Manages readiness checks across core dependencies (filesystem paths, indexes, external services). Checks are performed synchronously in a thread pool to avoid blocking the event loop. Maintains a cache of check results to avoid recomputing on every request.

**Public Surface**

- `codeintel_rev.app.runtime_readiness.ReadinessProbe` - Readiness probe manager
- `codeintel_rev.app.runtime_readiness.ReadinessProbe.initialize()` - Prime readiness state on startup
- `codeintel_rev.app.runtime_readiness.ReadinessProbe.refresh()` - Recompute readiness checks asynchronously
- `codeintel_rev.app.runtime_readiness.ReadinessProbe.snapshot()` - Get cached check results (non-blocking)
- `codeintel_rev.app.runtime_readiness.ReadinessProbe.shutdown()` - Clear readiness state on shutdown
- `codeintel_rev.app.runtime_readiness.CheckResult` - Check result dataclass (healthy, detail)

**Readiness Checks** (executed by `_run_checks()`):

- `repo_root` - Repository root directory exists
- `data_dir` - Data directory exists (created if missing)
- `vectors_dir` - Vectors directory exists (created if missing)
- `faiss_index` - FAISS index file exists and is readable
- `duckdb_catalog` - DuckDB catalog file exists and is accessible (validates materialization if configured)
- `scip_index` - SCIP index file exists (optional, doesn't fail readiness if missing)
- `vllm_service` - vLLM embedding service is reachable (HTTP health check with 2s timeout)
- `search_cli` - Search tooling available (ripgrep preferred, grep fallback)
- `xtr_artifacts` - XTR artifacts directory exists and contains required files (optional)

**Dependencies**

- Calls into:
  - `codeintel_rev.app.config_context.ApplicationContext` (for paths and configuration)
  - Standard library (`pathlib`, `shutil`, `asyncio`)
  - Optional: `httpx` (for vLLM health checks)
- Used by:
  - `codeintel_rev.app.main` (`/readyz` endpoint)

**Invariants**

- Readiness checks are cached and updated atomically via async lock.
- Optional resources (SCIP index, XTR artifacts) don't fail readiness if missing.
- HTTP health checks use short timeouts (2s) to prevent blocking.

**Extension Points**

- To add a new readiness check:
  - Add check function to `_run_checks()` method.
  - Return `CheckResult(healthy=True/False, detail=...)`.
  - Add check name to results dictionary.

**Anti-Patterns**

- Do **not** perform blocking I/O in readiness checks (use thread pool).
- Do **not** fail readiness for optional resources (mark as optional).

#### Module: `codeintel_rev/indexing/index_lifecycle.py`

**Role**

Manages staged/published index versions under a base directory. Provides atomic version switching via `CURRENT` pointer file and optional symlink updates. Tracks version metadata in manifest files (`manifest.json`).

**Public Surface**

- `codeintel_rev.indexing.index_lifecycle.IndexLifecycleManager` - Index lifecycle manager
- `codeintel_rev.indexing.index_lifecycle.IndexLifecycleManager.stage(version, assets)` - Stage a new index version (creates `versions/{version}.staging/` directory)
- `codeintel_rev.indexing.index_lifecycle.IndexLifecycleManager.publish(version)` - Publish a staged version (atomically updates `CURRENT` pointer and `current` symlink)
- `codeintel_rev.indexing.index_lifecycle.IndexLifecycleManager.rollback(version)` - Rollback to a previous version
- `codeintel_rev.indexing.index_lifecycle.IndexLifecycleManager.current_version()` - Get current active version (reads `CURRENT` file)
- `codeintel_rev.indexing.index_lifecycle.IndexLifecycleManager.list_versions()` - List all staged/published versions
- `codeintel_rev.indexing.index_lifecycle.IndexLifecycleManager.link_lucene_assets(version, assets)` - Link Lucene assets (BM25/SPLADE) into version directory
- `codeintel_rev.indexing.index_lifecycle.IndexAssets` - Asset bundle dataclass (faiss_index, duckdb_path, scip_index, bm25_dir, splade_dir, xtr_dir, faiss_idmap, tuning_profile)
- `codeintel_rev.indexing.index_lifecycle.LuceneAssets` - Lucene asset bundle (bm25_dir, splade_dir)
- `codeintel_rev.indexing.index_lifecycle.VersionMeta` - Version metadata (version, created_ts, attrs dict)

**Dependencies**

- Calls into:
  - Standard library (`pathlib`, `shutil`, `hashlib`, `json`, `time`)
  - `codeintel_rev.errors.RuntimeLifecycleError` (for lifecycle errors)
- Used by:
  - `codeintel_rev.cli.indexctl` (CLI commands)
  - `codeintel_rev.app.routers.index_admin` (admin endpoints)
  - `codeintel_rev.app.config_context.ApplicationContext` (index manager property)

**Invariants**

- Index versions must be immutable (no modifications after staging).
- Only one version can be active at a time (`CURRENT` pointer).
- Asset checksums must match on load (integrity verification).
- Version operations are atomic (publish/rollback don't corrupt state).

**Extension Points**

- To add a new asset type:
  - Add field to `IndexAssets` dataclass.
  - Update `ensure_exists()` validation.
  - Include in staging/publishing logic.

**Anti-Patterns**

- Do **not** modify staged versions after staging (immutable).
- Do **not** publish versions without validating asset checksums.

#### Module: `codeintel_rev/app/scope_store.py`

**Role**

Manages session-scoped query constraints (path patterns, languages, repositories) using in-memory LRU cache or optional Redis backend. Provides thread-safe scope storage with TTL-based expiration.

**Public Surface**

- `codeintel_rev.app.scope_store.ScopeStore` - Scope storage manager
- `codeintel_rev.app.scope_store.ScopeStore.get_scope()` - Retrieve scope for session
- `codeintel_rev.app.scope_store.ScopeStore.set_scope()` - Store scope for session
- `codeintel_rev.app.scope_store.LRUCache` - Thread-safe LRU cache with TTL

**Dependencies**

- Calls into:
  - `msgspec` (scope serialization)
  - Standard library (`threading.RLock`, `time.monotonic`)
  - Optional: Redis client (if `REDIS_URL` configured)
- Used by:
  - `codeintel_rev.app.middleware.SessionScopeMiddleware` (scope injection)
  - `codeintel_rev.mcp_server.adapters.*` (scope filtering)

**Invariants**

- Scope constraints are applied consistently across all search paths.
- Sessions expire after TTL (default: 1 hour) and are pruned by background task.
- Scope lookups are thread-safe (LRU cache uses `RLock`).

**Extension Points**

- To add Redis backend:
  - Implement `SupportsAsyncRedis` protocol.
  - Configure `REDIS_URL` environment variable.
  - ScopeStore automatically uses Redis if available.

**Anti-Patterns**

- Do **not** store scope constraints in request state (use ScopeStore).
- Do **not** bypass scope constraints in search adapters.

#### Module: `codeintel_rev/services/index/build.py`

**Role**

Orchestrates FAISS index building from Parquet shards using a step-based pipeline. Provides `run_index_build()` function that executes index build steps in sequence.

**Public Surface**

- `codeintel_rev.services.index.build.run_index_build()` - Execute index build pipeline
- `codeintel_rev.services.index.build.runner()` - Get step runner with default steps
- `codeintel_rev.services.index.steps.*` - Individual build step implementations

**Dependencies**

- Calls into:
  - `codeintel_rev.io.faiss_manager.FAISSManager` (index building)
  - `codeintel_rev.io.parquet_store` (reading embeddings)
  - `codeintel_rev.io.duckdb_catalog.DuckDBCatalog` (registration)
- Used by:
  - `codeintel_rev.cli.build_indexes` (CLI command)
  - `codeintel_rev.bin.index_all` (indexing pipeline)

**Invariants**

- Build steps execute in deterministic order (scan → train → add → persist → register).
- Index build is idempotent (rebuilding with same inputs produces same outputs).
- Build state is tracked through all steps (shard paths, row counts, index parameters).

**Extension Points**

- To add a new build step:
  - Implement step function in `codeintel_rev.services.index.steps`.
  - Register step in `StepRegistry` via `runner()`.
  - Add step name to `DEFAULT_STEPS` tuple.

**Anti-Patterns**

- Do **not** skip build steps arbitrarily (all steps are required for complete index).
- Do **not** modify build state outside of step functions.

#### Module: `codeintel_rev/services/enrich/`

**Role**

Orchestrates code enrichment pipeline extracting AST, CST, dependency graphs, and ownership metadata from source files. Provides service-layer functions for enrichment operations.

**Public Surface**

- `codeintel_rev.services.enrich.*` - Enrichment service modules (analytics, completeness, context, exports, io, models, overlays, scan, to_duckdb)
- `codeintel_rev.enrich.ast_indexer.ASTIndexer` - AST extraction
- `codeintel_rev.enrich.graph_builder.GraphBuilder` - Dependency graph construction
- `codeintel_rev.enrich.ownership.OwnershipAnalyzer` - Git ownership analysis

**Dependencies**

- Calls into:
  - `codeintel_rev.indexing.scip_reader` (symbol information)
  - `codeintel_rev.cst_build` (LibCST parsing)
  - `codeintel_rev.io.git_client` (Git operations)
  - Standard library (`ast`, `pathlib`)
- Used by:
  - `codeintel_rev.cli.enrich` (CLI commands)
  - `codeintel_rev.cli.enrich_pipeline` (pipeline orchestration)

**Invariants**

- AST extraction preserves qualnames for symbol resolution.
- CST parsing is lossless (round-trip to original source).
- Dependency graphs are deduplicated (same edge appears once).

**Extension Points**

- To add a new enrichment step:
  - Implement enrichment function in `codeintel_rev.services.enrich.*`.
  - Add to enrichment pipeline orchestration.
  - Write output artifacts to enrichment output directory.

**Anti-Patterns**

- Do **not** modify source files during enrichment (read-only operations).
- Do **not** skip error handling (enrichment should degrade gracefully).

#### Module: `codeintel_rev/retrieval/pipeline/stage0.py`

**Role**

Provides Stage-0 hybrid retrieval execution that combines dense (FAISS), sparse (BM25/SPLADE), and symbol signals using RRF fusion. Normalizes fusion outputs for downstream stages.

**Public Surface**

- `codeintel_rev.retrieval.pipeline.stage0.run_stage0()` - Execute Stage-0 hybrid retrieval
- `codeintel_rev.retrieval.pipeline.stage0.Stage0Result` - Normalized Stage-0 output (ids, scores, warnings, method)
- `codeintel_rev.retrieval.pipeline.stage0.Stage0Options` - Optional fusion configuration (weights, per_channel_k, fusion_k, rrf_base)

**Dependencies**

- Calls into:
  - `codeintel_rev.retrieval.hybrid_search.HybridSearchEngine` (fusion execution)
  - `codeintel_rev.io.rrf` (RRF algorithm)
- Used by:
  - `codeintel_rev.mcp_server.adapters.semantic` (basic semantic search)
  - `codeintel_rev.mcp_server.adapters.semantic_pro` (pro semantic search)

**Invariants**

- Stage-0 fusion must be deterministic (same inputs → same outputs).
- Fusion weights must be normalized (sum to 1.0).
- Stage-0 result includes method metadata describing fusion algorithm and parameters.

**Extension Points**

- To customize Stage-0 fusion:
  - Modify `Stage0Options` to add new fusion parameters.
  - Extend `run_stage0()` to support new fusion algorithms.

**Anti-Patterns**

- Do **not** modify fusion weights during execution (use immutable options).
- Do **not** skip method metadata in Stage-0 results.

#### Module: `codeintel_rev/retrieval/pipeline/gating.py`

**Role**

Provides Stage-1 gating logic that decides whether to run optional second-stage retrieval (late interaction, reranking) based on Stage-0 signals (candidate count, score margins, time budget).

**Public Surface**

- `codeintel_rev.retrieval.pipeline.gating.decide_secondary_stage()` - Evaluate Stage-1 gating decision
- `codeintel_rev.retrieval.pipeline.gating.StageDecision` - Gating decision (should_run, reason)
- `codeintel_rev.retrieval.pipeline.gating.StageGateConfig` - Gating configuration (time_budget_ms, min_candidates, high_margin_threshold)

**Dependencies**

- Calls into:
  - `codeintel_rev.retrieval.gating.should_run_secondary_stage` (core gating logic)
  - `codeintel_rev.retrieval.types.StageSignals` (normalized signals)
- Used by:
  - `codeintel_rev.mcp_server.adapters.semantic` (Stage-1 gating)
  - `codeintel_rev.mcp_server.adapters.semantic_pro` (Stage-1 gating)

**Invariants**

- Gating decision must be deterministic (same signals → same decision).
- Stage-1 is optional (search works without Stage-1).
- Gating reasons must be human-readable for debugging.

**Extension Points**

- To customize gating logic:
  - Modify `StageGateConfig` to adjust thresholds.
  - Extend `decide_secondary_stage()` to add new gating criteria.

**Anti-Patterns**

- Do **not** require Stage-1 for search to work (make it optional).
- Do **not** skip gating evaluation (always check before running Stage-1).

#### Module: `codeintel_rev/app/routers/catalog_read.py`

**Role**

FastAPI router providing catalog read APIs for GOIDs (Global Object Identifiers), call graphs, control flow graphs (CFG), and data flow graphs (DFG). All endpoints follow RFC 9457 Problem Details for error responses and support cursor-based pagination.

**Public Surface**

- `codeintel_rev.app.routers.catalog_read.router` - FastAPI router instance
- Endpoints:
  - `GET /v1/catalog/goids` - Query GOID catalog with pagination
  - `GET /v1/graph/call` - Query call graph (caller-callee relationships)
  - `GET /v1/flow/cfg/{function_goid}` - Get control flow graph for function
  - `GET /v1/flow/dfg/{function_goid}` - Get data flow graph for function

**Dependencies**

- Calls into:
  - `codeintel_rev.app.config_context.ApplicationContext` (via dependency injection)
  - `codeintel_rev.io.duckdb_catalog.DuckDBCatalog` (catalog queries)
- Used by:
  - `codeintel_rev.app.main` (router inclusion)

**Invariants**

- All endpoints return RFC 9457 Problem Details on error.
- Pagination uses cursor-based approach (not offset-based).
- Function GOIDs must be valid hexadecimal identifiers.

**Extension Points**

- To add a new catalog endpoint:
  - Add route handler to `router` instance.
  - Use `Depends(_context_dependency)` for ApplicationContext access.
  - Return Pydantic models for structured responses.

**Anti-Patterns**

- Do **not** perform blocking queries without `asyncio.to_thread`.
- Do **not** return raw database rows (use Pydantic models).

#### Module: `codeintel_rev/app/routers/index_admin.py`

**Role**

FastAPI router providing admin endpoints for index lifecycle management (staging, publishing, rollback, tuning). All endpoints are gated by `CODEINTEL_ADMIN=1` environment variable.

**Public Surface**

- `codeintel_rev.app.routers.index_admin.router` - FastAPI router instance
- Endpoints:
  - `GET /admin/index/status` - Current index version and health
  - `POST /admin/index/publish` - Publish a staged version
  - `POST /admin/index/rollback/{version}` - Rollback to previous version
  - `POST /admin/index/tuning` - Set session-scoped tuning overrides
  - `GET /admin/index/tuning/faiss` - Get FAISS tuning parameters
  - `POST /admin/index/tuning/faiss` - Set FAISS tuning parameters
  - `DELETE /admin/index/tuning/faiss` - Clear FAISS tuning parameters

**Dependencies**

- Calls into:
  - `codeintel_rev.app.config_context.ApplicationContext` (via dependency injection)
  - `codeintel_rev.indexing.index_lifecycle.IndexLifecycleManager` (index operations)
  - `codeintel_rev.app.scope_store.ScopeStore` (session tuning storage)
- Used by:
  - `codeintel_rev.app.main` (router inclusion, gated by `CODEINTEL_ADMIN`)

**Invariants**

- Admin endpoints return HTTP 403 if `CODEINTEL_ADMIN` is not enabled.
- Tuning overrides are stored per-session in ScopeStore.
- Index operations are atomic (publish/rollback don't corrupt state).

**Extension Points**

- To add a new admin endpoint:
  - Add route handler to `router` instance.
  - Use `Depends(_require_admin)` for admin gate.
  - Use `Depends(_context)` for ApplicationContext access.

**Anti-Patterns**

- Do **not** expose admin endpoints without `CODEINTEL_ADMIN` gate.
- Do **not** perform destructive operations without validation.

#### Module: `codeintel_rev/rerank/xtr.py`

**Role**

Provides XTR (Cross-Token Reranking) reranker that reranks search results using learned cross-token attention. Loads XTR index from `indexes/warp_xtr/` directory.

**Public Surface**

- `codeintel_rev.rerank.xtr.XTRReranker` - XTR reranker class
- `codeintel_rev.rerank.xtr.XTRReranker.rerank()` - Rerank search results
- `codeintel_rev.io.xtr_manager.XTRIndex` - XTR index manager

**Dependencies**

- Calls into:
  - `codeintel_rev.io.xtr_manager.XTRIndex` (index loading)
  - `codeintel_rev.io.warp_engine` (Warp engine for reranking)
- Used by:
  - `codeintel_rev.retrieval.hybrid_search` (optional reranking step)
  - `codeintel_rev.mcp_server.adapters.semantic` (semantic search)

**Invariants**

- XTR reranking is optional (search works without XTR index).
- Reranking preserves original result set (only reorders, doesn't filter).

**Extension Points**

- To add a new reranker:
  - Implement `BaseReranker` protocol from `codeintel_rev.rerank.base`.
  - Add reranker to `ApplicationContext` (lazy loading).
  - Integrate into hybrid search pipeline.

**Anti-Patterns**

- Do **not** require XTR index for search to work (make it optional).
- Do **not** rerank results that don't have required metadata.

---

## 7. Data & Metadata Structures

### 7.1 Primary Data Stores

- **DuckDB Catalog** (`*.duckdb` files)
  - Schema: Defined in `codeintel_rev.io.duckdb_schema`; migrations in `registry/migrations/`.
  - **Core Tables**:
    - `chunks` - Chunk metadata (chunk_id, file_path, start_line, end_line, embedding_dim)
    - `symbols` - Symbol definitions and references (from SCIP)
    - `faiss_indexes` - FAISS index registration (logical_index_id, index_uri, parameters)
    - `index_versions` - Index version metadata (version, checksums, created_at)
  - **GOID (Global Object Identifier) Tables**:
    - `goids` - GOID registry (goid_h128, urn, repo, commit, rel_path, language, kind, qualname, start_line, end_line)
    - `goid_xwalk` - GOID crosswalk linking GOIDs to SCIP symbols, chunk IDs, CST nodes, AST types, Git SHAs
    - Indexes: `idx_goids_path_kind` (rel_path, kind), `idx_goid_xwalk_symbol` (scip_symbol)
  - **Call Graph Tables**:
    - `call_nodes` - Function/method nodes (goid_h128, language, kind, arity, is_public, rel_path)
    - `call_edges` - Caller-callee relationships (caller_goid_h128, callee_goid_h128, callsite_path, callsite_line, callsite_col, language, kind, resolved_via, confidence, evidence_json)
    - Index: `idx_call_edges_callee` (callee_goid_h128)
  - **Control Flow Graph (CFG) Tables**:
    - `cfg_blocks` - Basic blocks within functions (function_goid_h128, block_idx, kind, start_line, end_line, stmts_json, in_degree, out_degree)
    - `cfg_edges` - Control flow edges (function_goid_h128, src_block_idx, dst_block_idx, edge_type, cond_json)
    - Index: `idx_cfg_blocks_function` (function_goid_h128)
  - **Data Flow Graph (DFG) Tables**:
    - `dfg_edges` - Data flow dependencies (function_goid_h128, src_block_idx, dst_block_idx, src_symbol, dst_symbol, via_phi, use_kind)
    - Index: `idx_dfg_symbol` (function_goid_h128, dst_symbol)
  - **Views**:
    - `goid_crosswalk` - GOID crosswalk view joining goids and goid_xwalk
    - `v_goid_by_symbol` - GOID lookup by SCIP symbol
    - `v_catalog_call_edges` - Call graph edges with GOID URNs
    - `v_catalog_cfg_blocks` - CFG blocks with function GOID URNs
    - `v_catalog_cfg_edges` - CFG edges with function GOID URNs
    - `v_catalog_dfg_nodes` - DFG nodes (function metadata)
    - `v_catalog_dfg_edges` - DFG edges with function GOID URNs
    - `v_chunk_symbols` - Chunk-to-symbol mapping (unnested from chunks.symbols array)
    - `v_pool_coverage` - Pool coverage view (with optional module joins)
    - `v_faiss_join` - FAISS ID map joined with chunks
  - **Materialized Tables** (for performance):
    - `chunks_materialized` - Materialized chunks table (with index on uri)
    - `faiss_idmap_mat` - Materialized FAISS ID map
    - `faiss_idmap_mat_meta` - ID map metadata (checksum, updated_at)
    - `faiss_join_mat` - Materialized v_faiss_join view
    - `modules_mat` - Materialized modules table
    - `modules_mat_meta` - Modules metadata (checksum, updated_at)
  - Access: Via `DuckDBManager.get_connection()` (thread-safe, optionally pooled).

- **Parquet Files** (`*.parquet` shards)
  - Schema: Chunk records with columns: `chunk_id`, `file_path`, `start_line`, `end_line`, `content`, `embedding` (FixedSizeList[float32]).
  - Storage: Sharded by file or batch (e.g., `chunks_000.parquet`, `chunks_001.parquet`).
  - Access: Via `codeintel_rev.io.parquet_store` (read/write utilities).

- **FAISS Indexes** (`*.faiss` files)
  - Format: Binary FAISS index files (Flat, IVFFlat, or IVF-PQ format).
  - Metadata: Index type, vector dimension, training parameters (`nlist`, `m`, `opq`) stored in DuckDB catalog.
  - Access: Via `FAISSManager.load_cpu_index()` (lazy loading).

- **BM25 Index** (`_indices/bm25/` directory)
  - Format: File-based inverted index (`.doc`, `.dvd`, `.idx` files).
  - Access: Via `BM25Manager` (lazy loading).

- **SPLADE Impact Index** (`_indices/splade_impact/` directory)
  - Format: File-based impact scores index.
  - Access: Via `SPLADEManager` (lazy loading).

- **SCIP Index** (`index.scip` or `index.scip.json`)
  - Format: Protocol Buffers (`.scip`) or JSON (`.scip.json`).
  - Content: Symbol definitions, references, documentation metadata.
  - Access: Via `codeintel_rev.indexing.scip_reader` (parsing utilities).

- **Enrichment Artifacts** (`build/enrich/` or `codeintel_rev/io/ENRICHED/`)
  - **AST Nodes** (`ast/ast_nodes.parquet`, `ast/ast_nodes.jsonl`):
    - Schema: `path`, `module`, `qualname`, `node_type`, `parent_qualname`, `decorators`, `bases`, `docstring`, `is_public`, `start_line`, `end_line`.
    - Purpose: Python AST node inventory for symbol resolution and code analysis.
  - **AST Metrics** (`ast/ast_metrics.parquet`, `ast/ast_metrics.jsonl`):
    - Schema: `path`, `func_count`, `class_count`, `assign_count`, `import_count`, `branch_nodes`, `cyclomatic`, `cognitive`, `max_nesting`, `statements`.
    - Purpose: File-level complexity and structure metrics.
  - **CST Nodes** (`CST/cst_nodes.jsonl.gz`):
    - Format: Gzip-compressed JSONL with LibCST node records.
    - Purpose: Lossless parse tree preserving exact source formatting.
  - **Module Summaries** (`modules/*.jsonl`, `modules/*.md`):
    - Format: JSONL per module with imports/exports/definitions, plus human-readable Markdown briefs.
    - Purpose: Per-module metadata for navigation and analysis.
  - **Symbol Graph** (`graphs/symbol_graph.json`):
    - Format: JSON with symbol-to-file edge list (deduplicated from SCIP).
    - Purpose: Dependency graph for symbol relationships.
  - **Ownership Analytics** (`analytics/ownership.parquet`):
    - Schema: `path`, `owner`, `primary_authors`, `bus_factor`, `recent_churn_30`, `recent_churn_90`.
    - Purpose: Git ownership and churn metrics per file.
  - **Tags Index** (`tags/tags_index.yaml`):
    - Format: YAML with per-module tags and global tag catalog.
    - Purpose: Custom tags for steering LLM agents (e.g., `refactor:io-bound`, `api:public`).

- **XTR Index** (`indexes/warp_xtr/` directory)
  - Format: Warp engine index files for cross-token reranking.
  - Purpose: Learned reranking model for improving search result relevance.
  - Access: Via `codeintel_rev.io.xtr_manager.XTRIndex` (lazy loading).

### 7.2 Index Versioning

- **Versioned Directories**: `indexes/versions/v1/`, `indexes/versions/v2/`, etc.
- **Active Symlink**: `indexes/active -> indexes/versions/v1` (points to current active version).
- **Metadata File**: `index_assets.json` in each version directory containing:
  - FAISS index path and SHA256 checksum
  - DuckDB catalog path and SHA256 checksum
  - SCIP index path and SHA256 checksum
  - Version identifier and creation timestamp
- **Lifecycle**: Managed by `IndexLifecycleManager` (stage, publish, status commands).

### 7.3 Session Scope Storage

- **ScopeStore**: In-memory storage (dict) mapping session_id → Scope constraints.
- **Session Expiration**: Sessions expire after 1 hour of inactivity (configurable via `SESSION_MAX_AGE_SECONDS`).
- **Background Pruning**: Background task runs every 10 minutes to remove expired sessions.

---

## 8. Cross-Cutting Concerns

### 8.1 Configuration Management

**Pattern**

Configuration is centralized in `codeintel_rev.config` and loaded once at startup via `ApplicationContext.create()`. Configuration is immutable after creation.

**Rules**

- Always access config via `AppConfig` or `ApplicationContext`, never directly via `os.environ`.
- New configuration keys must be added to `AppConfig` with defaults and typed definitions.
- Configuration is validated at load time (fail-fast on invalid values).

**Anti-Patterns**

- Do **not** read env vars directly in business logic.
- Do **not** modify configuration at runtime.

### 8.2 Logging & Observability

**Pattern**

Structured logging via standard library `logging` module. Log messages include request_id, session_id, run_id for correlation.

**Rules**

- Use module-level loggers: `logger = logging.getLogger(__name__)`.
- Include structured fields in log records (request_id, path, duration_ms).
- Never log secrets or PII.

**Anti-Patterns**

- Do **not** use `print()` for debugging (use logging).
- Do **not** log stack traces to production logs (use error tracking service).

### 8.3 Error Handling

**Pattern**

All domain errors inherit from `codeintel_rev.errors.KgFoundryError` and map to RFC 9457 Problem Details for HTTP responses.

**Rules**

- Always use `raise ... from e` to preserve exception chains.
- HTTP endpoints return Problem Details JSON with `type`, `title`, `status`, `detail`.
- Log errors with structured logging (include request_id, session_id).

**Anti-Patterns**

- Do **not** use bare `except:` clauses.
- Do **not** swallow exceptions silently (at minimum, log them).

### 8.4 Concurrency & Parallelism

**Pattern**

All I/O operations are asynchronous via `asyncio`. CPU-bound operations (FAISS search) are offloaded to threadpool via `asyncio.to_thread`.

**Rules**

- Use `async def` for request handlers and I/O operations.
- Use `asyncio.to_thread()` for CPU-bound work (FAISS, DuckDB queries).
- Git operations use `AsyncGitClient` (threadpool offload).

**Anti-Patterns**

- Do **not** perform blocking I/O in async request handlers.
- Do **not** hold locks across await points.

### 8.5 Performance & Scaling

**Pattern**

Adaptive indexing selects appropriate FAISS index types based on corpus size. Connection pooling (optional) reduces DuckDB connection overhead.

**Rules**

- FAISS index type selection: Flat (<5K), IVFFlat (5K-50K), IVF-PQ (>50K vectors).
- DuckDB connection pooling: Bounded pool size (`DUCKDB_POOL_SIZE`, default: disabled).
- vLLM HTTP client: Connection pooling with persistent connections.

**Anti-Patterns**

- Do **not** use Flat index for large corpora (>50K vectors).
- Do **not** create unbounded connection pools.

### 8.6 Runtime Management

**Pattern**

Runtimes (FAISS, DuckDB, vLLM, XTR, HybridSearch) are managed via `RuntimeCell` abstraction with lazy loading and lifecycle management. Runtimes are accessed via `ApplicationContext` properties.

**RuntimeCell Abstraction**

- **Thread-safe initialization**: `RuntimeCell` uses `RLock` to ensure thread-safe lazy initialization with single-flight semantics (only one thread initializes, others wait).
- **Generation tracking**: Each initialization attempt increments a generation counter (used for invalidation and tracking initialization cycles).
- **Lifecycle hooks**: `RuntimeCellObserver` protocol allows tracking initialization/close events:
  - `on_init_start(cell, generation, context)` - Invoked before initialization begins
  - `on_init_end(event)` - Invoked after initialization completes (success or failure)
  - `on_close_end(event)` - Invoked after close completes
- **Seed override**: `RuntimeCell.seed()` allows test-only pre-initialization (gated by `KGFOUNDRY_ALLOW_RUNTIME_SEED` environment variable or `allow_runtime_cell_seeding()` context manager).
- **Context capture**: Initialization captures request context (`RuntimeCellInitContext` with session_id, capability_stamp) for observability.
- **Failure tracking**: Failed initializations are tracked with TTL (default: 15 seconds) to prevent rapid retry loops.
- **Peek operation**: `peek()` allows checking if cell is initialized without triggering initialization.
- **Close operation**: `close()` releases resources and resets cell state (idempotent, thread-safe).

**Rules**

- Runtimes are loaded lazily on first access (unless preload flags are set).
- Runtime lifecycle is managed via `ApplicationContext.close_all_runtimes()`.
- Runtime availability is checked via `ReadinessProbe` (validates indexes exist, services reachable).
- Runtime errors are wrapped in `RuntimeLifecycleError` or `RuntimeUnavailableError`.
- Runtime initialization is thread-safe (multiple concurrent requests can trigger initialization safely).

**Anti-Patterns**

- Do **not** hold global runtime instances (use ApplicationContext properties).
- Do **not** access runtimes before ApplicationContext initialization.
- Do **not** call `RuntimeCell.seed()` in production code (test-only, gated by environment variable).

### 8.7 Scope Management

**Pattern**

Session-scoped query constraints (path patterns, languages, repositories) are stored in `ScopeStore` (in-memory LRU cache or Redis) and applied consistently across all search paths.

**Rules**

- Scope constraints are set via `set_scope` MCP tool and persist for session TTL (default: 1 hour).
- Scope is applied after search results are retrieved (not during individual searches).
- Explicit parameters override scope constraints (explicit `include_globs` overrides scope's `include_globs`).
- Scope lookups are thread-safe (LRU cache uses `RLock`).
- Background task prunes expired sessions every 10 minutes.

**Anti-Patterns**

- Do **not** apply scope constraints during individual search operations (apply after fusion).
- Do **not** store scope in request state (use ScopeStore).

### 8.8 Capabilities System

**Pattern**

Runtime capability detection system that checks for available runtimes (FAISS, DuckDB, vLLM, XTR) and gates MCP tool registration. Capabilities are exposed via `/capz` endpoint and used to conditionally register tools.

**Capabilities Detection**

- **Import-based detection**: Checks if optional modules (`faiss`, `duckdb`, `torch`, `onnxruntime`, `lucene`) are importable.
- **Runtime availability**: Checks if runtime managers are initialized and indexes exist.
- **Capability stamp**: Hash-based capability signature used for tracking capability changes across requests.

**Rules**

- Tools requiring specific runtimes are gated by capability checks (e.g., `semantic_search_pro` requires XTR).
- Capability snapshot is built once at startup (`Capabilities.from_context()`).
- Capability overrides are supported for testing (`override_capabilities`, `override_capability_imports`).

**Anti-Patterns**

- Do **not** register tools that require unavailable runtimes (gate by capabilities).
- Do **not** bypass capability checks in production code.

### 8.9 Error Handling Decorator Pattern

**Pattern**

`@handle_adapter_errors` decorator wraps MCP tool functions to catch exceptions and convert them to RFC 9457 Problem Details with empty result fallbacks.

**Decorator Behavior**

- **Exception catching**: Catches all exceptions raised by tool function.
- **Problem Details conversion**: Converts exceptions to RFC 9457 Problem Details JSON.
- **Empty result fallback**: Returns empty result structure (specified via `empty_result` parameter) on error.
- **Structured logging**: Logs exceptions with operation name, request context, and error details.
- **Error envelope**: Returns error envelope with `error` key containing Problem Details.

**Rules**

- Decorator must be applied **after** `@mcp.tool()` decorator (FastMCP requires `@mcp.tool()` first).
- All MCP tool adapters should use this decorator for consistent error handling.
- Empty result structure must match tool's success response schema.

**Anti-Patterns**

- Do **not** apply `@handle_adapter_errors` before `@mcp.tool()` (decorator order matters).
- Do **not** catch exceptions manually in tool functions (let decorator handle them).

---

## 9. Change Patterns & Extension Recipes

### 9.1 How to Add a New MCP Tool

**When to Use This**

You need to expose a new capability to AI assistants via the MCP protocol (e.g., a new search type, analysis tool, or code operation).

**Preconditions**

- Read:
  - Section 6 entry for `codeintel_rev/mcp_server/server.py`.
  - Section 5 flow descriptions for existing tools.
  - `codeintel_rev/mcp_server/adapters/` for tool implementation patterns.

**Steps**

1. Implement tool function in appropriate adapter module (`codeintel_rev/mcp_server/adapters/*.py`):
   - Use `@mcp.tool()` decorator from FastMCP.
   - Access `ApplicationContext` via `app_context.get()` (context variable).
   - Validate inputs via Pydantic models.
   - Return structured response (dict or Pydantic model).
2. Register tool in `codeintel_rev/mcp_server/server.py`:
   - Import tool function.
   - Add to MCP server instance (FastMCP auto-registers decorated functions).
3. Add capability gate (if tool requires specific runtime):
   - Update `codeintel_rev/app/capabilities.py` to check for required runtime.
   - Tool registration is gated by capabilities snapshot.
4. Add tests:
   - Unit tests: `tests/codeintel_rev/mcp_server/test_*.py`.
   - Integration tests: `tests/codeintel_rev/integration/test_*.py`.
5. Update documentation:
   - Add tool description to `codeintel_rev/README.md` (MCP Tools section).

**Required Tests & Checks**

- Tool function unit tests (mock ApplicationContext).
- Integration tests (real ApplicationContext, real runtimes).
- Type checking: `uv run pyright --warnings --pythonversion=3.13`.
- Linting: `uv run ruff format && uv run ruff check --fix`.

**Success Criteria**

- Tool is callable via MCP client.
- Tool returns expected response format.
- Tool respects scope constraints (if applicable).
- All tests pass.

### 9.2 How to Add a New Search Signal to Hybrid Search

**When to Use This**

You want to add a new retrieval signal (e.g., a new sparse model, semantic similarity metric, or code analysis signal) to the hybrid search pipeline.

**Preconditions**

- Read:
  - Section 6 entry for `codeintel_rev/retrieval/hybrid_search.py`.
  - Section 5.4 flow description for hybrid search.
  - `codeintel_rev/io/rrf.py` for RRF fusion algorithm.

**Steps**

1. Implement search manager class (e.g., `codeintel_rev/io/new_signal_manager.py`):
   - Implement `search(query: str, limit: int) -> list[SearchResult]` method.
   - Return results with `chunk_id` and `score` fields.
   - Use same corpus normalization as other signals.
2. Add search manager to `ApplicationContext`:
   - Add property to `ApplicationContext` class.
   - Initialize in `ApplicationContext.create()` (lazy loading).
   - Close in `ApplicationContext.close_all_runtimes()`.
3. Integrate into `HybridSearchEngine`:
   - Add search call to `HybridSearchEngine.search()` method.
   - Include results in RRF fusion.
4. Add configuration:
   - Add configuration fields to `AppConfig` (if needed).
   - Document in `codeintel_rev/docs/CONFIGURATION.md`.
5. Add tests:
   - Unit tests: `tests/codeintel_rev/retrieval/test_hybrid_search.py`.
   - Integration tests: `tests/codeintel_rev/integration/test_hybrid_search.py`.

**Required Tests & Checks**

- Search manager unit tests.
- Hybrid search integration tests (verify RRF fusion includes new signal).
- Type checking and linting.

**Success Criteria**

- New signal is included in hybrid search results.
- RRF fusion produces expected combined rankings.
- All tests pass.

### 9.3 How to Add a New Index Type to FAISS Manager

**When to Use This**

You need to support a new FAISS index type (e.g., a specialized index for a specific use case) or modify the adaptive index selection logic.

**Preconditions**

- Read:
  - Section 6 entry for `codeintel_rev/io/faiss_manager.py`.
  - Section 5.2 flow description for indexing pipeline.
  - FAISS documentation for index types.

**Steps**

1. Extend `FAISSManager._select_index_type()` method:
   - Add condition for new corpus size range or use case.
   - Return appropriate FAISS index factory string (e.g., `"IVF16384,PQ128"`).
2. Add training logic (if needed):
   - Extend `FAISSManager._train_index()` method.
   - Add training parameters to `FAISSManager.build_index()`.
3. Add search parameter logic:
   - Update `FAISSManager._get_search_params()` method.
   - Set appropriate `nprobe`, `efSearch` for new index type.
4. Update memory estimation:
   - Extend `FAISSManager.estimate_memory_usage()` method.
   - Add memory calculation for new index type.
5. Add tests:
   - Unit tests: `tests/codeintel_rev/io/test_faiss_manager.py`.
   - Integration tests: Verify index building and searching work correctly.

**Required Tests & Checks**

- Index building tests (verify new index type is created).
- Search tests (verify search parameters are correct).
- Memory estimation tests (verify estimates are accurate).
- Type checking and linting.

**Success Criteria**

- New index type is selected for appropriate corpus sizes.
- Index builds and searches correctly.
- Memory estimates are accurate.
- All tests pass.

### 9.4 How to Add a New Configuration Key

**When to Use This**

You need to add a new environment variable or configuration setting that affects application behavior.

**Preconditions**

- Read:
  - Section 6 entry for `codeintel_rev/config/loader.py`.
  - Section 8.1 cross-cutting concerns for configuration management.

**Steps**

1. Add field to `AppConfig` dataclass (`codeintel_rev/config/loader.py`):
   - Use typed field with default value.
   - Add field description docstring.
2. Add environment variable mapping:
   - Environment variable name should match field name (uppercase, underscores).
   - Use `pydantic_settings` field aliases if naming differs.
3. Update documentation:
   - Add entry to `codeintel_rev/docs/CONFIGURATION.md`.
   - Document default value, valid ranges, and usage.
4. Add validation (if needed):
   - Use Pydantic validators for complex validation.
   - Fail-fast on invalid values.
5. Add tests:
   - Unit tests: `tests/config/test_config_loader.py`.
   - Verify default value, environment variable override, invalid value handling.

**Required Tests & Checks**

- Configuration loading tests (default, env var override, invalid values).
- Type checking and linting.

**Success Criteria**

- Configuration key is loadable from environment variables.
- Default value is used when env var is unset.
- Invalid values cause fail-fast errors.
- All tests pass.

### 9.5 How to Add a New HTTP Router

**When to Use This**

You need to add a new set of HTTP endpoints that don't fit into existing routers (e.g., a new API surface for a specific feature).

**Preconditions**

- Read:
  - Section 6 entry for `codeintel_rev/app/main.py`.
  - Section 4.1 inbound interfaces for HTTP API patterns.
  - Existing router examples: `codeintel_rev/app/routers/catalog_read.py`, `codeintel_rev/app/routers/index_admin.py`.

**Steps**

1. Create router module in `codeintel_rev/app/routers/`:
   - Create `new_feature.py` with `router = APIRouter(prefix="/v1/feature", tags=["feature"])`.
   - Define Pydantic models for request/response schemas.
   - Implement route handlers with `@router.get()`, `@router.post()`, etc.
2. Add ApplicationContext dependency:
   - Create `_context_dependency(request: Request) -> ApplicationContext` function.
   - Extract context from `request.app.state.context`.
   - Raise HTTPException(503) if context unavailable.
3. Include router in `codeintel_rev/app/main.py`:
   - Import router module.
   - Call `app.include_router(new_feature.router)`.
4. Add admin gate (if needed):
   - Use `Depends(_require_admin)` for admin-only endpoints.
   - Document `CODEINTEL_ADMIN=1` requirement.
5. Add tests:
   - Unit tests: `tests/codeintel_rev/app/routers/test_new_feature.py`.
   - Integration tests: Verify endpoints work with real ApplicationContext.

**Required Tests & Checks**

- Router endpoint tests (verify request/response schemas).
- Error handling tests (verify RFC 9457 Problem Details).
- Admin gate tests (verify 403 when admin disabled).
- Type checking and linting.

**Success Criteria**

- Router endpoints are accessible via HTTP.
- Error responses follow RFC 9457 Problem Details format.
- Admin endpoints are properly gated.
- All tests pass.

### 9.6 How to Add a New Enrichment Step

**When to Use This**

You need to extract additional metadata from source code beyond AST/CST (e.g., code smells, security vulnerabilities, performance patterns).

**Preconditions**

- Read:
  - Section 6 entry for `codeintel_rev/services/enrich/`.
  - Section 5.9 flow description for enrichment pipeline.
  - `codeintel_rev/enrich/README.md` for enrichment patterns.

**Steps**

1. Implement enrichment function in appropriate service module (`codeintel_rev/services/enrich/*.py`):
   - Function should accept file path and return enrichment data (dict or Pydantic model).
   - Use SCIP index for symbol information if needed.
   - Use LibCST for import/export analysis if needed.
2. Add output artifact writing:
   - Write to Parquet file (if tabular data) or JSONL (if document-like).
   - Use consistent naming convention (`{artifact_name}.parquet` or `{artifact_name}.jsonl`).
   - Store in enrichment output directory (`build/enrich/{category}/`).
3. Integrate into enrichment pipeline:
   - Add enrichment step to `codeintel_rev.cli.enrich_pipeline` orchestration.
   - Add CLI flag to enable/disable new enrichment step.
4. Add tests:
   - Unit tests: `tests/enrich/test_*.py`.
   - Integration tests: Verify enrichment artifacts are written correctly.

**Required Tests & Checks**

- Enrichment function unit tests (verify metadata extraction).
- Integration tests (verify artifacts are written with correct schema).
- Type checking and linting.

**Success Criteria**

- New enrichment step runs as part of enrichment pipeline.
- Enrichment artifacts are written with correct schema.
- Artifacts can be loaded and queried (e.g., via DuckDB).
- All tests pass.

---

## 10. Testing & Quality Gates

### 10.1 Test Types

- **Unit tests**
  - Location: `tests/codeintel_rev/*/test_*.py`.
  - Purpose: Test individual functions/classes in isolation with mocked dependencies.
  - Markers: None (default).

- **Integration tests**
  - Location: `tests/codeintel_rev/integration/test_*.py`.
  - Purpose: Test coordinated behavior across multiple subsystems (FAISS + DuckDB + vLLM).
  - Markers: `@pytest.mark.integration`.

- **End-to-end / smoke tests**
  - Location: `tests/codeintel_rev/test_integration_smoke.py`, `tests/codeintel_rev/test_integration_full.py`.
  - Purpose: Test complete flows through real entry points (CLI commands, HTTP endpoints).
  - Markers: `@pytest.mark.smoke`, `@pytest.mark.e2e`.

- **Performance / benchmark tests**
  - Location: `tests/codeintel_rev/benchmarks/`.
  - Purpose: Measure performance characteristics (non-gating).
  - Markers: `@pytest.mark.benchmark`, `@pytest.mark.performance`.

### 10.2 Rules for Writing Tests

- **Prefer real collaborators over mocks**: Use real DuckDB, FAISS, and file I/O with isolated instances (temporary directories, in-memory DBs).
- **No monkeypatching**: Do not use `monkeypatch` or `unittest.mock.patch` on production code.
- **Enter through real entry points**: Tests should invoke CLI commands or HTTP endpoints, not internal helpers directly.
- **Use fixtures**: Leverage fixtures from `tests/_helpers/` and `tests/conftest.py` for common setup.
- **Parametrize edge cases**: Use `@pytest.mark.parametrize` for testing multiple inputs.

### 10.3 CI & Quality Gates

All changes must pass these checks:

- **Linting**: `uv run ruff format && uv run ruff check --fix`
- **Type checking**: 
  - `uv run pyright --warnings --pythonversion=3.13`
  - `uv run pyrefly check`
- **Tests**: `uv run pytest -q`
- **Dead code scanning**: `uv run vulture src tools stubs --min-confidence 90`
- **Security audit**: `uv run pip-audit` (on dependency changes)

**Pre-commit hooks**: Run via `uvx pre-commit run --all-files` (same checks as CI).

---

## 11. Operational & Deployment View

### 11.1 Deployment Model

- **Single-machine deployment** (current):
  - FastAPI application runs on single host.
  - FAISS indexes, DuckDB catalog, and SCIP indexes stored on local filesystem.
  - vLLM embedding service runs separately (local or remote).

- **Future (Phase 3)**: Multi-repository support planned (multiple indexes per server instance).

### 11.2 Runtime Configuration

- **Configuration source**: Environment variables (required) + optional config file (`CODEINTEL_CONFIG_FILE`).
- **Required environment variables**:
  - `REPO_ROOT` - Repository root path (must exist).
- **Optional environment variables**:
  - `FAISS_PRELOAD` - Preload FAISS index at startup (0 = lazy, 1 = eager).
  - `VLLM_URL` - vLLM embedding service URL (default: `http://127.0.0.1:8001/v1`).
  - `FAISS_INDEX` - FAISS index file path.
  - `DUCKDB_PATH` - DuckDB catalog file path.
  - `DUCKDB_POOL_SIZE` - DuckDB connection pool size (default: 0 = disabled).
  - `SESSION_MAX_AGE_SECONDS` - Session expiration time (default: 3600).
- **Secrets**: All secrets via environment variables (never hardcoded).

### 11.3 Monitoring & Observability

- **Health endpoints**:
  - `/healthz` - Network health check (always returns 200).
  - `/readyz` - Readiness probe (validates FAISS, DuckDB, vLLM availability).
  - `/capz` - Capability snapshot (returns available runtimes and indexes).
- **Logging**: Structured logging via standard library `logging` module (request_id, session_id correlation).
- **Metrics**: (Future) Prometheus metrics planned.
- **Tracing**: (Future) OpenTelemetry tracing planned.

### 11.4 Migrations & Rollouts

- **Index versioning**: Managed via `codeintel indexctl stage` and `codeintel indexctl publish` commands.
- **DuckDB migrations**: SQL migrations in `registry/migrations/` (applied manually or via migration tool).
- **Backward compatibility**: Index versions are immutable; new versions can be staged without affecting active version.
- **Rollout strategy**: Stage new version → validate → publish (updates symlink) → reload indexes (SIGHUP or restart).

### 11.5 Startup & Shutdown

- **Startup sequence**: See Section 5.1 (Application Startup flow).
- **Shutdown sequence**: 
  1. Cancel background tasks (session pruning).
  2. Close all runtime managers (`ApplicationContext.close_all_runtimes()`).
  3. Close DuckDB connections.
  4. Close vLLM HTTP client connections.
  5. Clear readiness state.

---

## 12. Architectural Decisions & History

### 12.1 ADR Placeholder

This section is reserved for future Architectural Decision Records (ADRs). No ADRs exist yet, but major decisions should be documented here as they are made.

**Planned ADRs** (to be created when decisions are finalized):

- **ADR-001**: Choice of FAISS for vector search (CPU-only, adaptive indexing)
- **ADR-002**: Choice of DuckDB for metadata catalog (embedded, thread-safe connections)
- **ADR-003**: Choice of SCIP for symbol indexing (Sourcegraph protocol)
- **ADR-004**: Hybrid search architecture (RRF fusion of dense/sparse/symbol signals)
- **ADR-005**: Session-scoped query constraints (scope management)

### 12.2 Initial Decision Stubs

**Decision: CPU-Only FAISS (Hypothesis)**

The system uses CPU-only FAISS indexes (no GPU support) with adaptive index type selection. This decision enables deployment on standard servers without GPU requirements, at the cost of potentially slower search for very large corpora.

**Rationale**: 
- Broader deployment compatibility (no GPU required).
- Adaptive indexing (Flat/IVFFlat/IVF-PQ) provides good performance for most codebase sizes.
- CPU FAISS is sufficient for code intelligence use cases (codebases typically <1M chunks).

**Alternatives Considered**:
- GPU FAISS (rejected: requires CUDA, limits deployment options).
- Alternative vector databases (Pinecone, Weaviate) - rejected: adds external dependency, higher operational complexity.

**Consequences**:
- Search latency scales with corpus size (mitigated by adaptive indexing).
- Memory usage is manageable (CPU indexes are memory-efficient).
- No GPU infrastructure required.

---

## 13. Indices & Cross-References

### 13.1 Symbol Index

| Symbol | Description | File Path | Relevant Sections |
|--------|-------------|-----------|-------------------|
| `codeintel_rev.app.main.app` | FastAPI application instance | `codeintel_rev/app/main.py` | 6.2, 5.1 |
| `codeintel_rev.app.config_context.ApplicationContext` | Application-wide context container | `codeintel_rev/app/config_context.py` | 6.2, 5.1 |
| `codeintel_rev.io.faiss_manager.FAISSManager` | FAISS vector search manager | `codeintel_rev/io/faiss_manager.py` | 6.2, 5.2, 5.3 |
| `codeintel_rev.io.duckdb_manager.DuckDBManager` | DuckDB connection manager | `codeintel_rev/io/duckdb_manager.py` | 6.2, 7.1 |
| `codeintel_rev.indexing.cast_chunker.CASTChunker` | Structure-aware code chunker | `codeintel_rev/indexing/cast_chunker.py` | 6.2, 5.2 |
| `codeintel_rev.retrieval.hybrid_search.HybridSearchEngine` | Hybrid search orchestrator | `codeintel_rev/retrieval/hybrid_search.py` | 6.2, 5.4 |
| `codeintel_rev.mcp_server.server.build_http_app` | FastMCP HTTP app builder | `codeintel_rev/mcp_server/server.py` | 6.2, 5.1 |
| `codeintel_rev.indexing.index_lifecycle.IndexLifecycleManager` | Index version lifecycle manager | `codeintel_rev/indexing/index_lifecycle.py` | 6.2, 5.6 |
| `codeintel_rev.app.scope_store.ScopeStore` | Session-scoped query constraints storage | `codeintel_rev/app/scope_store.py` | 6.2, 8.7 |
| `codeintel_rev.services.index.build.run_index_build` | Index build pipeline orchestrator | `codeintel_rev/services/index/build.py` | 6.2, 5.2 |
| `codeintel_rev.services.enrich` | Enrichment pipeline services | `codeintel_rev/services/enrich/` | 6.2, 5.7 |
| `codeintel_rev.rerank.xtr.XTRReranker` | XTR cross-token reranker | `codeintel_rev/rerank/xtr.py` | 6.2, 5.3 |

### 13.2 Module Index

| Module Path | Layer | Relevant Sections |
|-------------|-------|-------------------|
| `codeintel_rev/app/main.py` | Entrypoints | 6.2, 5.1 |
| `codeintel_rev/app/config_context.py` | Entrypoints | 6.2, 5.1 |
| `codeintel_rev/app/runtime_readiness.py` | Entrypoints | 6.2, 5.1 |
| `codeintel_rev/app/middleware.py` | Entrypoints | 6.2, 8.7 |
| `codeintel_rev/app/server_settings.py` | Entrypoints | 6.2, 11.2 |
| `codeintel_rev/app/routers/catalog_read.py` | Entrypoints | 6.2, 4.1 |
| `codeintel_rev/app/routers/index_admin.py` | Entrypoints | 6.2, 4.1 |
| `codeintel_rev/cli/indexctl.py` | Entrypoints | 4.1, 5.8 |
| `codeintel_rev/cli/bm25.py` | Entrypoints | 4.1, 5.2 |
| `codeintel_rev/cli/splade.py` | Entrypoints | 4.1, 5.2 |
| `codeintel_rev/cli/enrich/` | Entrypoints | 4.1, 5.9 |
| `codeintel_rev/services/index/` | Services | 5.2 |
| `codeintel_rev/indexing/cast_chunker.py` | Domain Models | 6.2, 5.2 |
| `codeintel_rev/indexing/scip_reader.py` | Domain Models | 5.2 |
| `codeintel_rev/retrieval/hybrid_search.py` | Domain Models | 6.2, 5.4 |
| `codeintel_rev/io/faiss_manager.py` | IO/Infrastructure | 6.2, 5.2, 5.3 |
| `codeintel_rev/io/duckdb_manager.py` | IO/Infrastructure | 6.2, 7.1 |
| `codeintel_rev/io/duckdb_catalog.py` | IO/Infrastructure | 5.3, 5.5 |
| `codeintel_rev/io/vllm_client.py` | IO/Infrastructure | 5.2, 5.3 |
| `codeintel_rev/io/bm25_manager.py` | IO/Infrastructure | 5.4 |
| `codeintel_rev/io/splade_manager.py` | IO/Infrastructure | 5.4 |
| `codeintel_rev/mcp_server/server.py` | Entrypoints | 6.2, 5.1 |
| `codeintel_rev/mcp_server/adapters/` | Entrypoints | 5.3, 5.5 |
| `codeintel_rev/config/loader.py` | Configuration | 6.2, 8.1 |
| `codeintel_rev/app/scope_store.py` | Entrypoints | 6.2, 8.7 |
| `codeintel_rev/services/index/build.py` | Services | 6.2, 5.2 |
| `codeintel_rev/services/enrich/` | Services | 6.2, 5.7 |
| `codeintel_rev/rerank/xtr.py` | Domain Models | 6.2, 5.3 |
| `codeintel_rev/enrich/` | Domain Models | 5.7 |

### 13.3 Flow Index

| Flow Name | Section | Key Modules |
|-----------|---------|-------------|
| Application Startup | 5.1 | `app/main.py`, `app/config_context.py`, `app/runtime_readiness.py` |
| Indexing Pipeline | 5.2 | `bin/index_all.py`, `indexing/cast_chunker.py`, `io/faiss_manager.py`, `io/vllm_client.py` |
| Semantic Search | 5.3 | `mcp_server/adapters/semantic.py`, `retrieval/hybrid_search.py`, `io/faiss_manager.py` |
| Hybrid Search | 5.4 | `retrieval/hybrid_search.py`, `io/faiss_manager.py`, `io/bm25_manager.py`, `io/splade_manager.py` |
| Symbol Navigation | 5.5 | `mcp_server/adapters/symbols.py`, `io/duckdb_catalog.py` |
| Index Lifecycle Management | 5.6 | `cli/indexctl.py`, `indexing/index_lifecycle.py` |
| Semantic Search Pro | 5.6 | `mcp_server/adapters/semantic_pro.py`, `retrieval/pipeline/stage0.py`, `retrieval/pipeline/gating.py`, `rerank/xtr.py` |
| Deep Research Search/Fetch | 5.7 | `mcp_server/adapters/deep_research.py`, `retrieval/mcp_search.py` |
| Index Lifecycle Management | 5.8 | `cli/indexctl.py`, `indexing/index_lifecycle.py` |
| Code Enrichment Pipeline | 5.9 | `enrich/ast_indexer.py`, `cst_build/`, `enrich/graph_builder.py`, `services/enrich/` |

---

## Appendix: Known Gaps & Open Questions

- **Multi-repository support**: Currently single-repository only; Phase 3 multi-repo architecture needs design.
- **Prometheus metrics**: Observability metrics are planned but not yet implemented.
- **OpenTelemetry tracing**: Distributed tracing is planned but not yet implemented.
- **Index sharding**: Large codebases (>1M chunks) may need index sharding strategy (not yet designed).
- **Incremental indexing**: Incremental FAISS index updates are partially implemented but need full design documentation.

---

**Document Version**: 1.0 (Initial Architecture Narrative)  
**Last Updated**: 2025-01-27  
**Maintainer**: Architecture team

