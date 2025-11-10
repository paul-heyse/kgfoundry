# Interface Catalog

This catalog is generated from `_nav.json` sidecars and the shared interface registry.

| Interface | Type | Module | Owner | Stability | Spec | Description | Problem Details |
| --------- | ---- | ------ | ----- | -------- | ---- | ----------- | ---------------- |
| orchestration-cli | cli | [orchestration](../modules/orchestration.md) | @orchestration | beta | [CLI Spec](../api/openapi-cli.md) | Primary Typer application for orchestration flows and indexing commands. | — |
| search-http | http | [search_api](../modules/search_api.md) | @search-api | experimental | [HTTP API](../api/index.md) | FastAPI application exposing search operations via the public HTTP API. | schema/examples/problem_details/search-missing-index.json, schema/examples/problem_details/search-gpu-unavailable.json |

## codeintel-indexer

* **Type:** cli
* **Module:** codeintel
* **Owner:** @code-intel
* **Stability:** experimental
* **Description:** Tree-sitter powered developer tooling that exposes code-intelligence queries and symbol
extraction through the shared CLI contracts. The interface integrates with the OpenAPI
generator, MkDocs diagrams, and documentation lifecycles to keep metadata consistent.


### Operations

- [`codeintel.indexer.query`](../api/openapi-cli.md) — Execute a Tree-sitter query against a source file.
    - Module docs: [codeintel.cli](../modules/codeintel.cli.md)
  - Tags: codeintel
  - Handler: `codeintel.cli:query`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m codeintel.cli query src/example.py --language python --query queries/highlights.scm`

## docs-symbol-index-cli

* **Type:** cli
* **Module:** docs.toolchain
* **Owner:** @docs
* **Stability:** experimental
* **Description:** Documentation tooling CLI that builds the symbol index, by-file, and by-module artifacts used
throughout the documentation pipeline. Emits standardized CLI envelopes and Problem Details
for CI gating and observability.


### Operations

- [`docs.symbol_index.build`](../api/openapi-cli.md) — Build documentation symbol index artifacts.
    - Module docs: [docs.toolchain.build_symbol_index](../modules/docs.toolchain.build_symbol_index.md)
  - Tags: docs, docs-symbol-index
  - Handler: `docs.toolchain.build_symbol_index:build_symbol_index`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m docs.toolchain.build_symbol_index`

## docs-validate-cli

* **Type:** cli
* **Module:** docs.toolchain
* **Owner:** @docs
* **Stability:** experimental
* **Description:** Documentation tooling CLI that validates generated artifacts (symbol index, delta summaries,
and reverse lookups) against their canonical JSON Schemas. Emits standardized CLI envelopes
and Problem Details for CI gating and observability pipelines.


### Operations

- [`docs.validate_artifacts`](../api/openapi-cli.md) — Validate documentation artifacts against canonical schemas.
    - Module docs: [docs.toolchain.validate_artifacts](../modules/docs.toolchain.validate_artifacts.md)
  - Tags: docs, docs-validation
  - Handler: `docs.toolchain.validate_artifacts:validate_artifacts`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m docs._scripts.validate_artifacts --docs-build-dir docs/_build`
- [`docs.build_graphs`](../api/openapi-cli.md) — Build documentation dependency graphs.
    - Module docs: [tools.docs.build_graphs](../modules/tools.docs.build_graphs.md)
  - Tags: docs
  - Handler: `tools.docs.build_graphs:main`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docs.build_graphs --format svg`

## docstring-builder-cli

* **Type:** cli
* **Module:** tools.docstring_builder
* **Owner:** @docs
* **Stability:** beta
* **Description:** Command suite powering docstring synchronization, validation, policy enforcement, and
diagnostics. The CLI integrates with shared tooling metadata so documentation helpers,
diagrams, and automation emit consistent Problem Details and logging envelopes.


### Operations

- [`docstrings.generate`](../api/openapi-cli.md) — Regenerate managed docstrings and DocFacts artifacts.
    - Module docs: [tools.docstring_builder.cli](../modules/tools.docstring_builder.cli.md)
  - Tags: docstrings, docstrings-update
  - Handler: `tools.docstring_builder.cli:_command_generate`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli generate`
- [`docstrings.fix`](../api/openapi-cli.md) — Apply docstring updates while bypassing cache entries.
    - Module docs: [tools.docstring_builder.cli](../modules/tools.docstring_builder.cli.md)
  - Tags: docstrings, docstrings-update
  - Handler: `tools.docstring_builder.cli:_command_fix`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli fix`
- [`docstrings.fmt`](../api/openapi-cli.md) — Normalize docstring sections without regenerating content.
    - Module docs: [tools.docstring_builder.cli](../modules/tools.docstring_builder.cli.md)
  - Tags: docstrings, docstrings-update
  - Handler: `tools.docstring_builder.cli:_command_fmt`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli fmt`
- [`docstrings.update`](../api/openapi-cli.md) — Legacy alias for the generate pipeline.
    - Module docs: [tools.docstring_builder.cli](../modules/tools.docstring_builder.cli.md)
  - Tags: docstrings, docstrings-update
  - Handler: `tools.docstring_builder.cli:_command_update`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli update`
- [`docstrings.check`](../api/openapi-cli.md) — Validate docstrings without writing updates.
    - Module docs: [tools.docstring_builder.cli](../modules/tools.docstring_builder.cli.md)
  - Tags: docstrings, docstrings-validate
  - Handler: `tools.docstring_builder.cli:_command_check`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli check`
- [`docstrings.diff`](../api/openapi-cli.md) — Show docstring drift previews without mutating files.
    - Module docs: [tools.docstring_builder.cli](../modules/tools.docstring_builder.cli.md)
  - Tags: docstrings, docstrings-validate
  - Handler: `tools.docstring_builder.cli:_command_diff`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli diff`
- [`docstrings.lint`](../api/openapi-cli.md) — Alias for check with optional DocFacts skip.
    - Module docs: [tools.docstring_builder.cli](../modules/tools.docstring_builder.cli.md)
  - Tags: docstrings, docstrings-validate
  - Handler: `tools.docstring_builder.cli:_command_lint`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli lint --no-docfacts`
- [`docstrings.measure`](../api/openapi-cli.md) — Execute validation and emit observability metrics.
    - Module docs: [tools.docstring_builder.cli](../modules/tools.docstring_builder.cli.md)
  - Tags: docstrings, docstrings-observability
  - Handler: `tools.docstring_builder.cli:_command_measure`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli measure`
- [`docstrings.list`](../api/openapi-cli.md) — List managed docstring targets detected by the pipeline.
    - Module docs: [tools.docstring_builder.cli](../modules/tools.docstring_builder.cli.md)
  - Tags: docstrings, docstrings-observability
  - Handler: `tools.docstring_builder.cli:_command_list`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli list`
- [`docstrings.harvest`](../api/openapi-cli.md) — Gather docstring metadata without writing changes.
    - Module docs: [tools.docstring_builder.cli](../modules/tools.docstring_builder.cli.md)
  - Tags: docstrings, docstrings-utilities
  - Handler: `tools.docstring_builder.cli:_command_harvest`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli harvest`
- [`docstrings.schema`](../api/openapi-cli.md) — Export the docstring IR schema to disk.
    - Module docs: [tools.docstring_builder.cli](../modules/tools.docstring_builder.cli.md)
  - Tags: docstrings, docstrings-utilities
  - Handler: `tools.docstring_builder.cli:_command_schema`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli schema --output docs/_build/docstring-schema.json`
- [`docstrings.clear_cache`](../api/openapi-cli.md) — Remove cached docstring builder artifacts.
    - Module docs: [tools.docstring_builder.cli](../modules/tools.docstring_builder.cli.md)
  - Tags: docstrings, docstrings-utilities
  - Handler: `tools.docstring_builder.cli:_command_clear_cache`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli clear-cache`
- [`docstrings.doctor`](../api/openapi-cli.md) — Diagnose configuration, dependencies, and optional stubs.
    - Module docs: [tools.docstring_builder.cli](../modules/tools.docstring_builder.cli.md)
  - Tags: docstrings, docstrings-diagnostics
  - Handler: `tools.docstring_builder.cli:_command_doctor`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli doctor --stubs`

## download-cli

* **Type:** cli
* **Module:** download
* **Owner:** @data-platform
* **Stability:** experimental
* **Description:** Downloader command suite that sources external corpora (currently OpenAlex) using the shared
CLI tooling contracts. Emits structured envelopes and metadata so downstream tooling (OpenAPI,
diagrams, documentation) remains in sync without bespoke glue.


### Operations

- [`cli.download.harvest`](../api/openapi-cli.md) — Harvest OpenAlex works for downstream ingestion.
    - Module docs: [download.cli](../modules/download.cli.md)
    - Source: [download.cli](https://github.com/paul-heyse/kgfoundry/blob/main/src/download/cli.py)
  - Tags: download
  - Handler: `download.cli:harvest`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `kgf download harvest 'foundation models' --years '>=2020' --max-works 5000`

## navmap-cli

* **Type:** cli
* **Module:** tools.navmap
* **Owner:** @docs
* **Stability:** experimental
* **Description:** Documentation tooling CLI that generates the canonical navmap JSON artefact. The command
scans Python modules, resolves ``__navmap__`` declarations, and emits structured envelopes for
downstream automation, diagrams, and observability pipelines.


### Operations

- [`navmap.build`](../api/openapi-cli.md) — Build the documentation navmap JSON artefact.
    - Module docs: [tools.navmap.build_navmap](../modules/tools.navmap.build_navmap.md)
  - Tags: navmap
  - Handler: `tools.navmap.build_navmap:main`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.navmap.build_navmap --write site/_build/navmap/navmap.json`
- [`navmap.check`](../api/openapi-cli.md) — Validate navmap declarations and inline metadata.
    - Module docs: [tools.navmap.check_navmap](../modules/tools.navmap.check_navmap.md)
  - Tags: navmap
  - Handler: `tools.navmap.check_navmap:main`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.navmap.check_navmap`

## orchestration-cli

* **Type:** cli
* **Module:** orchestration
* **Owner:** @orchestration
* **Stability:** beta
* **Description:** Typer-powered orchestration command suite covering indexing flows, API bootstrapping,
and end-to-end demonstrations. Each command maps to a generated OpenAPI operation
consumed by the MkDocs suite.


### Operations

- [`cli.index_bm25`](../api/openapi-cli.md) — Build BM25 index from JSON/Parquet chunks.
    - Module docs: [orchestration.cli](../modules/orchestration.cli.md)
    - Source: [orchestration.cli](https://github.com/paul-heyse/kgfoundry/blob/main/src/orchestration/cli.py)
  - Tags: orchestration, index_bm25
  - Handler: `orchestration.cli:index_bm25`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `kgf index-bm25 data/chunks.parquet --backend lucene --index-dir ./_indices/bm25`
- [`cli.index_faiss`](../api/openapi-cli.md) — Build FAISS index from dense vectors.
    - Module docs: [orchestration.cli](../modules/orchestration.cli.md)
    - Source: [orchestration.cli](https://github.com/paul-heyse/kgfoundry/blob/main/src/orchestration/cli.py)
  - Tags: orchestration, index_faiss
  - Handler: `orchestration.cli:index_faiss`
  - Env: KGF_FAISS_RESOURCES
  - Problem Details: schema/examples/problem_details/tool-execution-error.json, schema/examples/problem_details/faiss-index-build-timeout.json
  - Code Samples:
    * (bash) `kgf index-faiss artifacts/vectors.json --factory 'OPQ64,IVF8192,PQ64' --metric ip`
- [`cli.api`](../api/openapi-cli.md) — Launch FastAPI search service.
    - Module docs: [orchestration.cli](../modules/orchestration.cli.md)
    - Source: [orchestration.cli](https://github.com/paul-heyse/kgfoundry/blob/main/src/orchestration/cli.py)
  - Tags: orchestration, api
  - Handler: `orchestration.cli:api`
  - Env: KGF_SEARCH_CONFIG
  - Problem Details: schema/examples/problem_details/public-api-invalid-config.json
  - Code Samples:
    * (bash) `kgf api --port 8080`
- [`cli.e2e`](../api/openapi-cli.md) — Execute end-to-end orchestration demo.
    - Module docs: [orchestration.cli](../modules/orchestration.cli.md)
    - Source: [orchestration.cli](https://github.com/paul-heyse/kgfoundry/blob/main/src/orchestration/cli.py)
  - Tags: orchestration, e2e
  - Handler: `orchestration.cli:e2e`
  - Env: KGF_PROFILE
  - Problem Details: schema/examples/problem_details/public-api-invalid-config.json
  - Code Samples:
    * (bash) `kgf e2e`

## search-http

* **Type:** http
* **Module:** search_api
* **Owner:** @search-api
* **Stability:** experimental
* **Description:** FastAPI service exposing search endpoints, aggregation helpers, and Problem Details responses.


