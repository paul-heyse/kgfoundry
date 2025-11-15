# Complete Observability & Monitoring Removal Plan

## Overview

This plan removes **ALL observability and monitoring code** from the `codeintel_rev` package, including:
- Prometheus metrics
- OpenTelemetry tracing
- OpenTelemetry metrics
- All telemetry helpers
- All observability infrastructure

## Current State

### Observability Code to Remove

1. **OpenTelemetry Tracing** (`observability/otel.py`):
   - `as_span()` context manager
   - `record_span_event()`
   - `set_current_span_attrs()`
   - `current_trace_id()`, `current_span_id()`

2. **OpenTelemetry Metrics** (`observability/metrics.py` - just created):
   - `build_counter()`, `build_gauge()`, `build_histogram()`
   - All metric wrappers

3. **Telemetry Modules** (already deleted, but imports remain):
   - `telemetry.otel_metrics`
   - `telemetry.decorators`
   - `telemetry.steps`
   - `telemetry.reporter`

4. **Metrics Registry** (`metrics/registry.py`):
   - All metric definitions (FAISS, MCP, retrieval, etc.)

5. **Observability Helpers**:
   - `observability/semantic_conventions.py` - May keep if used elsewhere
   - `observability/timeline.py` - May keep if used for non-telemetry purposes
   - `observability/reporting.py` - May keep if used for non-telemetry purposes

## Migration Strategy

### Phase 1: Remove All Metrics

**Files to update**:
1. `codeintel_rev/metrics/registry.py` - Delete or replace with no-ops
2. `codeintel_rev/embeddings/embedding_service.py` - Remove metric calls
3. `codeintel_rev/mcp_server/scope_utils.py` - Remove metric calls
4. `codeintel_rev/retrieval/rerank_flat.py` - Remove metric calls
5. All other files using metrics from registry

**Approach**: Replace metric calls with no-ops or remove entirely.

### Phase 2: Remove All Tracing/Spans

**Files to update**:
1. `codeintel_rev/retrieval/mcp_search.py` - Remove `span_context()` calls
2. `codeintel_rev/io/git_client.py` - Remove `span_context()` calls
3. `codeintel_rev/retrieval/rerank_flat.py` - Remove `as_span()` calls
4. `codeintel_rev/io/hybrid_search.py` - Remove `span_context()` calls
5. All other files using spans

**Approach**: Remove span context managers entirely, keep business logic.

### Phase 3: Remove All Telemetry Imports

**Files to update**:
1. Remove all imports from deleted `telemetry.*` modules
2. Remove all imports from `observability.otel`
3. Remove all imports from `observability.metrics`

### Phase 4: Remove Observability Modules

**Files to delete**:
1. `codeintel_rev/observability/metrics.py` - Delete (just created)
2. `codeintel_rev/observability/otel.py` - Delete or keep minimal fallbacks
3. `codeintel_rev/metrics/registry.py` - Delete or replace with empty module

**Files to evaluate**:
- `codeintel_rev/observability/semantic_conventions.py` - Keep if used for non-telemetry
- `codeintel_rev/observability/timeline.py` - Keep if used for non-telemetry
- `codeintel_rev/observability/reporting.py` - Keep if used for non-telemetry

### Phase 5: Remove Step Events

**Files to update**:
1. `codeintel_rev/io/git_client.py` - Remove `emit_step()` calls
2. `codeintel_rev/retrieval/gating.py` - Remove `emit_step()` calls

**Approach**: Remove calls entirely.

### Phase 6: Remove Reporter Functions

**Files to update**:
1. `codeintel_rev/cli/__init__.py` - Remove `finalize_run()`, `start_run()` calls

**Approach**: Remove calls or replace with minimal logging if needed.

## Implementation Steps

1. ✅ Audit all observability code usage
2. ⏳ Remove all metric definitions and calls
3. ⏳ Remove all span/tracing calls
4. ⏳ Remove all telemetry imports
5. ⏳ Delete observability modules
6. ⏳ Remove step events
7. ⏳ Remove reporter functions
8. ⏳ Clean up comments/docs mentioning observability
9. ⏳ Verify no observability code remains

## Replacement Strategy

### Metrics
- **Before**: `FAISS_SEARCH_TOTAL.inc()`
- **After**: Remove call entirely

### Spans
- **Before**: 
  ```python
  with span_context("operation", attrs={...}):
      do_work()
  ```
- **After**:
  ```python
  do_work()
  ```

### Step Events
- **Before**: `emit_step(StepEvent(...))`
- **After**: Remove call entirely

### Reporter
- **Before**: `start_run(...)`, `finalize_run(...)`
- **After**: Remove calls or replace with minimal logging

## Files Requiring Changes

### Core Removal (15+ files)
1. `codeintel_rev/metrics/registry.py` - Delete or empty
2. `codeintel_rev/embeddings/embedding_service.py` - Remove metrics
3. `codeintel_rev/mcp_server/scope_utils.py` - Remove metrics
4. `codeintel_rev/retrieval/rerank_flat.py` - Remove metrics/spans
5. `codeintel_rev/retrieval/mcp_search.py` - Remove spans
6. `codeintel_rev/io/git_client.py` - Remove spans/steps
7. `codeintel_rev/retrieval/gating.py` - Remove steps
8. `codeintel_rev/cli/__init__.py` - Remove reporter calls
9. `codeintel_rev/io/hybrid_search.py` - Remove spans
10. `codeintel_rev/observability/metrics.py` - Delete
11. `codeintel_rev/observability/otel.py` - Delete or minimal fallback
12. Plus any other files importing/using observability

### Documentation Updates
- Remove all references to Prometheus, OpenTelemetry, metrics, tracing, spans
- Update docstrings that mention observability
- Clean up comments

## Verification

After removal, verify:

```bash
# No observability imports
grep -r "observability\|telemetry\|prometheus\|opentelemetry" codeintel_rev --include="*.py" | grep -v "__pycache__"

# No metric calls
grep -r "\.inc()\|\.observe()\|\.set()" codeintel_rev --include="*.py" | grep -v "__pycache__"

# No span calls
grep -r "span_context\|as_span\|record_span_event" codeintel_rev --include="*.py" | grep -v "__pycache__"

# All tests pass
uv run pytest tests/ -v
```

