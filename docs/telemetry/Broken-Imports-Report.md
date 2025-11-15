# Broken Imports Report - Telemetry Module Deletion

## Summary

The `codeintel_rev/telemetry` directory was deleted, but **8 files** still have broken imports referencing the deleted modules. These imports will cause `ModuleNotFoundError` at runtime.

## Broken Imports Found

### 1. `telemetry.otel_metrics` (4 files)
**Missing**: `build_counter`, `build_gauge`, `build_histogram`

**Files affected**:
- `codeintel_rev/embeddings/embedding_service.py:18`
- `codeintel_rev/metrics/registry.py:5`
- `codeintel_rev/mcp_server/scope_utils.py:59`
- `codeintel_rev/retrieval/rerank_flat.py:12`

**Replacement**: Should use `kgfoundry_common.prometheus` helpers:
```python
from kgfoundry_common.prometheus import build_counter, build_gauge, build_histogram
```

### 2. `telemetry.decorators` (3 files)
**Missing**: `span_context` decorator

**Files affected**:
- `codeintel_rev/retrieval/mcp_search.py:27`
- `codeintel_rev/io/git_client.py:55`
- `codeintel_rev/retrieval/rerank_flat.py:11`

**Replacement**: Should use `observability.otel.as_span` context manager:
```python
from codeintel_rev.observability.otel import as_span
```

### 3. `telemetry.steps` (2 files)
**Missing**: `StepEvent`, `emit_step`

**Files affected**:
- `codeintel_rev/io/git_client.py:56`
- `codeintel_rev/retrieval/gating.py:19`

**Replacement**: Should use `observability.otel.record_span_event`:
```python
from codeintel_rev.observability.otel import record_span_event
```

### 4. `telemetry.reporter` (1 file)
**Missing**: `finalize_run`, `start_run`

**Files affected**:
- `codeintel_rev/cli/__init__.py:15`

**Replacement**: Should use `observability.timeline` helpers:
```python
from codeintel_rev.observability.timeline import bind_timeline, new_timeline
```

## Impact

- **Runtime failures**: All 8 files will fail to import
- **Test failures**: Any tests importing these modules will fail
- **Application startup**: Application may fail to start if these modules are imported at startup

## Recommended Actions

1. **Immediate**: Fix all broken imports using replacements above
2. **Verification**: Run `uv run pytest` to ensure no import errors
3. **CI**: Add import check to prevent future regressions

## Files Requiring Fixes

1. `codeintel_rev/embeddings/embedding_service.py`
2. `codeintel_rev/metrics/registry.py`
3. `codeintel_rev/mcp_server/scope_utils.py`
4. `codeintel_rev/retrieval/rerank_flat.py`
5. `codeintel_rev/retrieval/mcp_search.py`
6. `codeintel_rev/io/git_client.py`
7. `codeintel_rev/retrieval/gating.py`
8. `codeintel_rev/cli/__init__.py`

