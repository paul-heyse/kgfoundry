## Observability Architecture Guide

This guide documents the unified observability helper, structured metrics, and
error handling patterns used across the CodeIntel MCP server. It is intended
for contributors implementing new adapters or extending existing surfaces with
observability instrumentation.

### Overview

All adapters SHALL record metrics through
`codeintel_rev.mcp_server.common.observability.observe_duration`. The helper
eliminates boilerplate while providing:

- **Consistency** – shared metric names and labels.
- **Resilience** – automatic no-op fallback when Prometheus collectors are
  disabled or lack label support.
- **Traceability** – operation/component metadata aligns metrics, logs, and
  Problem Details responses.

### Integration with `kgfoundry_common`

The helper wraps `kgfoundry_common.observability.observe_duration` and performs
additional safeguards:

1. Resolve a `MetricsProvider` (injectable for testing, defaults to the shared
   provider).
2. Verify the histogram supports labels.
3. Start a duration observation, yielding an object exposing `mark_success()`
   and `mark_error()`.
4. Emit debug logs when instrumentation is unavailable to aid diagnosis.

Adapters MUST import only `observe_duration` from
`codeintel_rev.mcp_server.common.observability`. Direct imports from
`kgfoundry_common` are prohibited; extend the shared helper when new behavior
is required.

### Usage Patterns

Wrap adapter operations inside the context manager:

```python
from codeintel_rev.mcp_server.common.observability import observe_duration

COMPONENT_NAME = "codeintel_mcp"

def _search_text_sync(...):
    with observe_duration("text_search", COMPONENT_NAME) as observation:
        try:
            stdout = run_subprocess(...)
        except SubprocessTimeoutError as exc:
            observation.mark_error()
            raise VectorSearchError("Search timed out", ...) from exc
        observation.mark_success()
        return stdout
```

Guidelines:

- Call `mark_success()` when the observed work completes.
- Call `mark_error()` before raising or returning fallback data.
- Reuse the observation when retrying or delegating to fallback logic.
- Avoid spanning unrelated operations; start a fresh observation per request.

### Metrics Naming Conventions

The helper emits two Prometheus metrics:

- `codeintel_operation_duration_seconds` (histogram): labeled by `operation`
  and `component`.
- `codeintel_runs_total` (counter): labeled by `operation`, `component`, and
  `outcome` (`success` / `error`).

Rules:

- Use lower-case snake_case for operations (e.g., `text_search`,
  `semantic_search`).
- Components correspond to the adapter surface (`codeintel_mcp`,
  `codeintel_duckdb`, etc.).
- Introduce new labels only by extending the shared helper and updating this
  document.

### Resource Cleanup Best Practices

Observability should mirror resource lifecycles:

- **HTTP / vLLM clients** – acquire clients via lifespan hooks, close them in
  `ApplicationContext.shutdown`, and instrument per-request work.
- **DuckDB catalog** – use `DuckDBCatalog.connection()` context managers so
  observations align with query execution rather than connection management.
- **FAISS manager** – instrument GPU clone/compaction operations with
  `component="faiss_manager"` and release resources in `finally` blocks.

Do not hold a single observation across multiple unrelated operations; start
a new observation for each user-visible request or catalog query.

### Error Handling (RFC 9457 Problem Details)

Adapters SHALL raise domain-specific exceptions (e.g., `PathNotFoundError`,
`VectorSearchError`). The shared error handling module converts these into RFC
9457 Problem Details responses with:

- `type` – canonical URI from `kgfoundry_common.errors.codes`.
- `title` – human-readable summary.
- `status` – HTTP status code.
- `detail` – verbose message for clients.
- `code` – stable, kebab-case error code.
- `extensions` – structured context (path, git command, etc.).

Never return dictionaries containing error payloads from adapters. Instead,
call `observation.mark_error()` and raise the appropriate exception.

### Testing Observability

Recommended strategy:

- Patch `observe_duration` in unit tests to assert operation/component labels
  and success/error tracking.
- Verify `mark_error()` is triggered before raising domain exceptions on failure
  paths.
- Use temporary DuckDB databases to test SQL filtering with the shared query
  builder.
- For integration coverage, emit metrics through a local `CollectorRegistry`
  to ensure exporters accept observations.

Leave Problem Details validation to
`tests/codeintel_rev/test_error_handling.py`; adapter tests need only assert
correct exception types and context metadata.

### Quick Reference Checklist

- [ ] Import `observe_duration` from the shared module.
- [ ] Call `mark_success()` on completion.
- [ ] Call `mark_error()` before raising/fallback.
- [ ] Raise domain exceptions; never return error dicts.
- [ ] Follow operation/component naming conventions.
- [ ] Add tests patching `observe_duration`.
- [ ] Update documentation when introducing new metrics or components.

