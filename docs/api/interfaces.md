# Interface Catalog

This catalog is generated from `_nav.json` sidecars and the shared interface registry.

| Interface | Type | Module | Owner | Stability | Spec | Description | Problem Details |
| --------- | ---- | ------ | ----- | -------- | ---- | ----------- | ---------------- |
| codeintel-indexer | cli | codeintel | @code-intel | experimental | [CLI Spec](../api/openapi-cli.md) | Tree-sitter powered developer tooling that exposes code-intelligence queries and symbol<br />extraction through the shared CLI contracts. The interface integrates with the OpenAPI<br />generator, MkDocs diagrams, and documentation lifecycles to keep metadata consistent.<br /> | schema/examples/problem_details/tool-execution-error.json |
| docs-symbol-index-cli | cli | docs.toolchain | @docs | experimental | [CLI Spec](../api/openapi-cli.md) | Documentation tooling CLI that builds the symbol index, by-file, and by-module artifacts used<br />throughout the documentation pipeline. Emits standardized CLI envelopes and Problem Details<br />for CI gating and observability.<br /> | schema/examples/problem_details/tool-execution-error.json |
| docs-validate-cli | cli | docs.toolchain | @docs | experimental | [CLI Spec](../api/openapi-cli.md) | Documentation tooling CLI that validates generated artifacts (symbol index, delta summaries,<br />and reverse lookups) against their canonical JSON Schemas. Emits standardized CLI envelopes<br />and Problem Details for CI gating and observability pipelines.<br /> | schema/examples/problem_details/tool-execution-error.json |
| docstring-builder-cli | cli | tools.docstring_builder | @docs | beta | [CLI Spec](../api/openapi-cli.md) | Command suite powering docstring synchronization, validation, policy enforcement, and<br />diagnostics. The CLI integrates with shared tooling metadata so documentation helpers,<br />diagrams, and automation emit consistent Problem Details and logging envelopes.<br /> | schema/examples/problem_details/tool-execution-error.json |
| download-cli | cli | [download](../modules/download.md) | @data-platform | experimental | [CLI Spec](../api/openapi-cli.md) | Downloader command suite that sources external corpora (currently OpenAlex) using the shared<br />CLI tooling contracts. Emits structured envelopes and metadata so downstream tooling (OpenAPI,<br />diagrams, documentation) remains in sync without bespoke glue.<br /> | schema/examples/problem_details/tool-execution-error.json |
| navmap-cli | cli | tools.navmap | @docs | experimental | [CLI Spec](../api/openapi-cli.md) | Documentation tooling CLI that generates the canonical navmap JSON artefact. The command<br />scans Python modules, resolves \`\`__navmap__\`\` declarations, and emits structured envelopes for<br />downstream automation, diagrams, and observability pipelines.<br /> | schema/examples/problem_details/tool-execution-error.json |
| orchestration-cli | cli | [orchestration](../modules/orchestration.md) | @orchestration | beta | [CLI Spec](../api/openapi-cli.md) | Primary Typer application for orchestration flows and indexing commands. | schema/examples/problem_details/tool-execution-error.json |
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

- [`codeintel.indexer.query`](openapi-cli.md#operation/codeintel.indexer.query) — Execute a Tree-sitter query against a source file.
    - Module docs: codeintel.cli
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

- [`docs.symbol_index.build`](openapi-cli.md#operation/docs.symbol_index.build) — Build documentation symbol index artifacts.
    - Module docs: docs.toolchain.build_symbol_index
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

- [`docs.validate_artifacts`](openapi-cli.md#operation/docs.validate_artifacts) — Validate documentation artifacts against canonical schemas.
    - Module docs: docs.toolchain.validate_artifacts
  - Tags: docs, docs-validation
  - Handler: `docs.toolchain.validate_artifacts:validate_artifacts`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m docs._scripts.validate_artifacts --docs-build-dir docs/_build`
- [`docs.build_graphs`](openapi-cli.md#operation/docs.build_graphs) — Build documentation dependency graphs.
    - Module docs: tools.docs.build_graphs
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

- [`docstrings.generate`](openapi-cli.md#operation/docstrings.generate) — Regenerate managed docstrings and DocFacts artifacts.
    - Module docs: tools.docstring_builder.cli
  - Tags: docstrings, docstrings-update
  - Handler: `tools.docstring_builder.cli:_command_generate`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli generate`
- [`docstrings.fix`](openapi-cli.md#operation/docstrings.fix) — Apply docstring updates while bypassing cache entries.
    - Module docs: tools.docstring_builder.cli
  - Tags: docstrings, docstrings-update
  - Handler: `tools.docstring_builder.cli:_command_fix`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli fix`
- [`docstrings.fmt`](openapi-cli.md#operation/docstrings.fmt) — Normalize docstring sections without regenerating content.
    - Module docs: tools.docstring_builder.cli
  - Tags: docstrings, docstrings-update
  - Handler: `tools.docstring_builder.cli:_command_fmt`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli fmt`
- [`docstrings.update`](openapi-cli.md#operation/docstrings.update) — Legacy alias for the generate pipeline.
    - Module docs: tools.docstring_builder.cli
  - Tags: docstrings, docstrings-update
  - Handler: `tools.docstring_builder.cli:_command_update`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli update`
- [`docstrings.check`](openapi-cli.md#operation/docstrings.check) — Validate docstrings without writing updates.
    - Module docs: tools.docstring_builder.cli
  - Tags: docstrings, docstrings-validate
  - Handler: `tools.docstring_builder.cli:_command_check`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli check`
- [`docstrings.diff`](openapi-cli.md#operation/docstrings.diff) — Show docstring drift previews without mutating files.
    - Module docs: tools.docstring_builder.cli
  - Tags: docstrings, docstrings-validate
  - Handler: `tools.docstring_builder.cli:_command_diff`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli diff`
- [`docstrings.lint`](openapi-cli.md#operation/docstrings.lint) — Alias for check with optional DocFacts skip.
    - Module docs: tools.docstring_builder.cli
  - Tags: docstrings, docstrings-validate
  - Handler: `tools.docstring_builder.cli:_command_lint`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli lint --no-docfacts`
- [`docstrings.measure`](openapi-cli.md#operation/docstrings.measure) — Execute validation and emit observability metrics.
    - Module docs: tools.docstring_builder.cli
  - Tags: docstrings, docstrings-observability
  - Handler: `tools.docstring_builder.cli:_command_measure`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli measure`
- [`docstrings.list`](openapi-cli.md#operation/docstrings.list) — List managed docstring targets detected by the pipeline.
    - Module docs: tools.docstring_builder.cli
  - Tags: docstrings, docstrings-observability
  - Handler: `tools.docstring_builder.cli:_command_list`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli list`
- [`docstrings.harvest`](openapi-cli.md#operation/docstrings.harvest) — Gather docstring metadata without writing changes.
    - Module docs: tools.docstring_builder.cli
  - Tags: docstrings, docstrings-utilities
  - Handler: `tools.docstring_builder.cli:_command_harvest`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli harvest`
- [`docstrings.schema`](openapi-cli.md#operation/docstrings.schema) — Export the docstring IR schema to disk.
    - Module docs: tools.docstring_builder.cli
  - Tags: docstrings, docstrings-utilities
  - Handler: `tools.docstring_builder.cli:_command_schema`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli schema --output docs/_build/docstring-schema.json`
- [`docstrings.clear_cache`](openapi-cli.md#operation/docstrings.clear_cache) — Remove cached docstring builder artifacts.
    - Module docs: tools.docstring_builder.cli
  - Tags: docstrings, docstrings-utilities
  - Handler: `tools.docstring_builder.cli:_command_clear_cache`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli clear-cache`
- [`docstrings.doctor`](openapi-cli.md#operation/docstrings.doctor) — Diagnose configuration, dependencies, and optional stubs.
    - Module docs: tools.docstring_builder.cli
  - Tags: docstrings, docstrings-diagnostics
  - Handler: `tools.docstring_builder.cli:_command_doctor`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.docstring_builder.cli doctor --stubs`

## download-cli

* **Type:** cli
* **Module:** [download](../modules/download.md)
* **Source:** [download](https://github.com/paul-heyse/kgfoundry/blob/main/src/download/__init__.py)
* **Owner:** @data-platform
* **Stability:** experimental
* **Description:** Downloader command suite that sources external corpora (currently OpenAlex) using the shared
CLI tooling contracts. Emits structured envelopes and metadata so downstream tooling (OpenAPI,
diagrams, documentation) remains in sync without bespoke glue.


### Operations

- [`cli.download.harvest`](openapi-cli.md#operation/cli.download.harvest) — Harvest OpenAlex works for downstream ingestion.
    - Module docs: [download.cli](../modules/download/cli.md)
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

- [`navmap.build`](openapi-cli.md#operation/navmap.build) — Build the documentation navmap JSON artefact.
    - Module docs: tools.navmap.build_navmap
  - Tags: navmap
  - Handler: `tools.navmap.build_navmap:main`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.navmap.build_navmap --write site/_build/navmap/navmap.json`
- [`navmap.check`](openapi-cli.md#operation/navmap.check) — Validate navmap declarations and inline metadata.
    - Module docs: tools.navmap.check_navmap
  - Tags: navmap
  - Handler: `tools.navmap.check_navmap:main`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `uv run python -m tools.navmap.check_navmap`

## orchestration-cli

* **Type:** cli
* **Module:** [orchestration](../modules/orchestration.md)
* **Source:** [orchestration](https://github.com/paul-heyse/kgfoundry/blob/main/src/orchestration/__init__.py)
* **Owner:** @orchestration
* **Stability:** beta
* **Description:** Primary Typer application for orchestration flows and indexing commands.

### Operations

- [`cli.index_bm25`](openapi-cli.md#operation/cli.index_bm25) — Build BM25 index from JSON/Parquet chunks.
    - Module docs: [orchestration.cli](../modules/orchestration/cli.md)
    - Source: [orchestration.cli](https://github.com/paul-heyse/kgfoundry/blob/main/src/orchestration/cli.py)
  - Tags: orchestration, index_bm25
  - Handler: `orchestration.cli:index_bm25`
  - Problem Details: schema/examples/problem_details/tool-execution-error.json
  - Code Samples:
    * (bash) `kgf index-bm25 data/chunks.parquet --backend lucene --index-dir ./_indices/bm25`
- [`cli.index_faiss`](openapi-cli.md#operation/cli.index_faiss) — Build FAISS index from dense vectors.
    - Module docs: [orchestration.cli](../modules/orchestration/cli.md)
    - Source: [orchestration.cli](https://github.com/paul-heyse/kgfoundry/blob/main/src/orchestration/cli.py)
  - Tags: orchestration, index_faiss
  - Handler: `orchestration.cli:index_faiss`
  - Env: KGF_FAISS_RESOURCES
  - Problem Details: schema/examples/problem_details/tool-execution-error.json, schema/examples/problem_details/faiss-index-build-timeout.json
  - Code Samples:
    * (bash) `kgf index-faiss artifacts/vectors.json --factory 'OPQ64,IVF8192,PQ64' --metric ip`
- [`cli.api`](openapi-cli.md#operation/cli.api) — Launch FastAPI search service.
    - Module docs: [orchestration.cli](../modules/orchestration/cli.md)
    - Source: [orchestration.cli](https://github.com/paul-heyse/kgfoundry/blob/main/src/orchestration/cli.py)
  - Tags: orchestration, api
  - Handler: `orchestration.cli:api`
  - Env: KGF_SEARCH_CONFIG
  - Problem Details: schema/examples/problem_details/public-api-invalid-config.json
  - Code Samples:
    * (bash) `kgf api --port 8080`
- [`cli.e2e`](openapi-cli.md#operation/cli.e2e) — Execute end-to-end orchestration demo.
    - Module docs: [orchestration.cli](../modules/orchestration/cli.md)
    - Source: [orchestration.cli](https://github.com/paul-heyse/kgfoundry/blob/main/src/orchestration/cli.py)
  - Tags: orchestration, e2e
  - Handler: `orchestration.cli:e2e`
  - Env: KGF_PROFILE
  - Problem Details: schema/examples/problem_details/public-api-invalid-config.json
  - Code Samples:
    * (bash) `kgf e2e`

## search-http

* **Type:** http
* **Module:** [search_api](../modules/search_api.md)
* **Source:** [search_api](https://github.com/paul-heyse/kgfoundry/blob/main/src/search_api/__init__.py)
* **Owner:** @search-api
* **Stability:** experimental
* **Description:** FastAPI application exposing search operations via the public HTTP API.

