## ADDED Requirements

### Requirement: Unified Observability Helper

The CodeIntel MCP adapters SHALL use a single shared observability helper from `codeintel_rev.mcp_server.common.observability` to eliminate code duplication and maintain consistency with the `kgfoundry_common.observability` infrastructure.

#### Scenario: Adapter uses shared observability helper

- **GIVEN** an adapter function needs to record operation duration metrics
- **WHEN** the adapter imports and uses `observe_duration` from the common module
- **THEN** metrics are recorded using `kgfoundry_common.observability.MetricsProvider`
- **AND** the adapter code contains zero local `_NoopObservation` or `_observe` definitions

#### Scenario: Metrics gracefully degrade when Prometheus unavailable

- **GIVEN** Prometheus metrics are not configured or histogram labels are disabled
- **WHEN** an adapter uses `observe_duration` context manager
- **THEN** a noop observation object is yielded
- **AND** the adapter operation completes successfully without errors
- **AND** zero metrics are recorded (graceful degradation)

#### Scenario: Metrics integrate with existing infrastructure

- **GIVEN** `kgfoundry_common.observability.MetricsProvider` is available
- **WHEN** an adapter uses `observe_duration("operation_name", "component_name")`
- **THEN** metrics are recorded in `kgfoundry_operation_duration_seconds` histogram
- **AND** labels include `component="component_name"` and `operation="operation_name"`
- **AND** behavior matches existing kgfoundry metrics patterns

### Requirement: Eliminated Code Duplication

The CodeIntel MCP adapters SHALL contain zero duplicated observability boilerplate code (no `_NoopObservation` classes or local `_observe` helpers).

#### Scenario: Text search adapter has no local observability boilerplate

- **GIVEN** `codeintel_rev/mcp_server/adapters/text_search.py` is refactored
- **WHEN** the file is inspected for observability code
- **THEN** it contains zero `_NoopObservation` class definitions
- **AND** it contains zero `_observe` function definitions
- **AND** it imports `observe_duration` from `codeintel_rev.mcp_server.common.observability`

#### Scenario: Semantic adapter has no local observability boilerplate

- **GIVEN** `codeintel_rev/mcp_server/adapters/semantic.py` is refactored
- **WHEN** the file is inspected for observability code
- **THEN** it contains zero `_NoopObservation` class definitions
- **AND** it contains zero `_observe` function definitions
- **AND** it imports `observe_duration` from `codeintel_rev.mcp_server.common.observability`

#### Scenario: Lines of code reduction verification

- **GIVEN** both text_search and semantic adapters are refactored
- **WHEN** lines of code are counted before and after
- **THEN** at least 60 lines of duplicated code are removed
- **AND** the codebase is more maintainable with single source of truth

### Requirement: Backward Compatible Metrics

The refactored observability implementation SHALL emit identical metrics (same names, labels, and values) as the original per-adapter implementations.

#### Scenario: Metrics names unchanged

- **GIVEN** adapters are refactored to use shared observability helper
- **WHEN** metrics are collected from `/metrics` endpoint
- **THEN** metric names match original implementation exactly
- **AND** no metrics are renamed or removed
- **AND** `kgfoundry_operation_duration_seconds` histogram exists with correct labels

#### Scenario: Metrics labels unchanged

- **GIVEN** adapters use shared observability helper
- **WHEN** metrics with labels are inspected
- **THEN** label names match original implementation (`component`, `operation`, `status`)
- **AND** label values match original implementation (e.g., `component="codeintel_mcp"`)
- **AND** no new labels are added that break existing queries

#### Scenario: Grafana dashboards continue working

- **GIVEN** Grafana dashboards query codeintel metrics
- **WHEN** adapters are refactored to use shared observability
- **THEN** all dashboard panels render correctly with no data gaps
- **AND** queries return identical results as before refactoring
- **AND** historical metrics remain queryable

### Requirement: Standardized Error Responses

All CodeIntel MCP adapters SHALL return errors in consistent RFC 9457 Problem Details format using a centralized error mapping function.

#### Scenario: Path errors return Problem Details

- **GIVEN** an adapter operation encounters a path validation error
- **WHEN** the error is formatted for the client
- **THEN** the response contains a `problem` field conforming to RFC 9457
- **AND** the `problem.type` field is a valid URI (e.g., `https://kgfoundry.dev/problems/path_not_found`)
- **AND** the `problem.status` field matches HTTP status code (e.g., 404)
- **AND** the `problem.code` field is a machine-readable identifier (e.g., `"path_not_found"`)

#### Scenario: Search errors return Problem Details

- **GIVEN** a semantic search operation fails with VectorSearchError
- **WHEN** the error is formatted for the client
- **THEN** the response contains a `problem` field conforming to RFC 9457
- **AND** the `problem.code` is `"vector_search_failed"`
- **AND** the `problem.status` is 500
- **AND** the `problem.detail` contains the exception message

#### Scenario: Consistent error shape across adapters

- **GIVEN** multiple adapters (text_search, semantic, files, history)
- **WHEN** each adapter encounters an error condition
- **THEN** all adapters return errors in the same RFC 9457 format
- **AND** clients can parse errors using a single schema
- **AND** error handling code is not duplicated across adapters

### Requirement: Resource Cleanup Documentation

The CodeIntel MCP codebase SHALL document resource cleanup best practices in a centralized architecture guide accessible to junior developers.

#### Scenario: HTTP client cleanup documented

- **GIVEN** `codeintel_rev/docs/architecture/observability.md` exists
- **WHEN** a developer reads the resource cleanup section
- **THEN** they find clear guidance on HTTP client lifecycle management
- **AND** code examples show `VLLMClient.close()` in FastAPI lifespan shutdown
- **AND** the rationale for cleanup is explained (prevent connection pool exhaustion)

#### Scenario: DuckDB catalog cleanup documented

- **GIVEN** the architecture guide includes database connection patterns
- **WHEN** a developer needs to use DuckDB catalog
- **THEN** they find documented `open_catalog()` context manager pattern
- **AND** examples show proper usage with `with context.open_catalog() as catalog:`
- **AND** the guide explains auto-closing behavior

#### Scenario: Junior developer can onboard

- **GIVEN** a junior developer joins the team
- **WHEN** they read `codeintel_rev/docs/architecture/observability.md`
- **THEN** they understand how to add metrics to new adapters
- **AND** they understand resource cleanup lifecycle
- **AND** they can follow examples to implement correctly
- **AND** the guide answers common questions (FAQs section)

### Requirement: Quality Gates Compliance

The refactored observability code SHALL pass all AGENTS.MD quality gates with zero errors or suppressions.

#### Scenario: Ruff formatting clean

- **GIVEN** refactored observability code
- **WHEN** `uv run ruff format` is executed
- **THEN** zero formatting changes are required
- **AND** `uv run ruff check --fix` reports zero violations

#### Scenario: Type checking clean

- **GIVEN** refactored observability code
- **WHEN** `uv run pyright --warnings --pythonversion=3.13` is executed
- **THEN** zero type errors are reported
- **AND** `uv run pyrefly check` reports zero violations
- **AND** no type suppressions are added (no `# type: ignore` comments)

#### Scenario: Test coverage meets threshold

- **GIVEN** new `codeintel_rev/mcp_server/common/observability.py` module
- **WHEN** test coverage is measured
- **THEN** coverage is ≥ 95% on the new module
- **AND** all code paths are tested (including noop fallback)
- **AND** integration tests verify adapter usage

---

## MODIFIED Requirements

(None - this is a net new capability with only additions, no modifications to existing requirements)

---

## REMOVED Requirements

(None - this change does not remove any existing requirements)

---

## RENAMED Requirements

(None - this change does not rename any existing requirements)

