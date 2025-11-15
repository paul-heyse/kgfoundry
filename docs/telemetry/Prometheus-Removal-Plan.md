# Prometheus Removal & OpenTelemetry Migration Plan

## Overview

This plan removes **all Prometheus code and references** from the `codeintel_rev` package and replaces them with pure **OpenTelemetry Metrics API**. This aligns with the unified OTel design and eliminates the Prometheus dependency.

## Current State

### Prometheus Usage Found

1. **Direct Prometheus imports** (2 files):
   - `codeintel_rev/metrics/registry.py` - Uses `build_counter`, `build_gauge`, `build_histogram`
   - `codeintel_rev/embeddings/embedding_service.py` - Uses `build_counter`, `build_gauge`, `build_histogram`

2. **Prometheus references in comments/docs** (6+ files):
   - `codeintel_rev/io/faiss_manager.py` - Multiple Prometheus metric label comments
   - `codeintel_rev/metrics/registry.py` - Module docstring mentions Prometheus
   - `codeintel_rev/embeddings/embedding_service.py` - Comments about Prometheus gauges
   - `codeintel_rev/io/duckdb_catalog.py` - Prometheus metric label comments
   - `codeintel_rev/retrieval/telemetry.py` - Prometheus metrics comment
   - `codeintel_rev/mcp_server/common/observability.py` - Prometheus histogram comment
   - `codeintel_rev/app/capabilities.py` - Prometheus metrics placeholder comment
   - `codeintel_rev/mcp_server/scope_utils.py` - Prometheus metrics comment

3. **Broken telemetry imports** (8 files):
   - `telemetry.otel_metrics` → Should be replaced with OTel Metrics API
   - `telemetry.decorators` → Should use `observability.otel.as_span`
   - `telemetry.steps` → Should use `observability.otel.record_span_event`
   - `telemetry.reporter` → Should use `observability.timeline` helpers

## Migration Strategy

### Phase 1: Create OTel Metrics Helper Module

**File**: `codeintel_rev/observability/metrics.py` (new)

Create a helper module that provides Prometheus-like API backed by OTel Metrics:

```python
"""OpenTelemetry Metrics helpers for codeintel_rev.

Provides Prometheus-like API (build_counter, build_gauge, build_histogram)
backed by OpenTelemetry Metrics API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Sequence

if TYPE_CHECKING:
    from opentelemetry.metrics import Counter, Gauge, Histogram, Meter

# Protocol definitions matching Prometheus-like interface
class CounterLike(Protocol):
    def labels(self, **kwargs: str | int | float) -> CounterLike: ...
    def inc(self, value: float = 1.0) -> None: ...

class GaugeLike(Protocol):
    def labels(self, **kwargs: str | int | float) -> GaugeLike: ...
    def set(self, value: float) -> None: ...
    def inc(self, value: float = 1.0) -> None: ...
    def dec(self, value: float = 1.0) -> None: ...

class HistogramLike(Protocol):
    def labels(self, **kwargs: str | int | float) -> HistogramLike: ...
    def observe(self, value: float) -> None: ...

def build_counter(name: str, description: str, labelnames: Sequence[str] = ()) -> CounterLike:
    """Create an OTel Counter with Prometheus-like API."""
    # Implementation using OTel MeterProvider
    ...

def build_gauge(name: str, description: str, labelnames: Sequence[str] = ()) -> GaugeLike:
    """Create an OTel Gauge with Prometheus-like API."""
    ...

def build_histogram(
    name: str,
    description: str,
    labelnames: Sequence[str] = (),
    buckets: Sequence[float] | None = None,
    unit: str = "",
) -> HistogramLike:
    """Create an OTel Histogram with Prometheus-like API."""
    ...
```

### Phase 2: Replace Prometheus Imports

**Files to update**:
1. `codeintel_rev/metrics/registry.py`
   - Replace: `from kgfoundry_common.prometheus import ...`
   - With: `from codeintel_rev.observability.metrics import ...`

2. `codeintel_rev/embeddings/embedding_service.py`
   - Replace: `from kgfoundry_common.prometheus import ...`
   - With: `from codeintel_rev.observability.metrics import ...`

3. `codeintel_rev/mcp_server/scope_utils.py`
   - Replace: `from codeintel_rev.telemetry.otel_metrics import build_histogram`
   - With: `from codeintel_rev.observability.metrics import build_histogram`

4. `codeintel_rev/retrieval/rerank_flat.py`
   - Replace: `from codeintel_rev.telemetry.otel_metrics import build_histogram`
   - With: `from codeintel_rev.observability.metrics import build_histogram`

### Phase 3: Fix Broken Telemetry Imports

**Files to update**:

1. **`telemetry.decorators.span_context`** (3 files):
   - `codeintel_rev/retrieval/mcp_search.py`
   - `codeintel_rev/io/git_client.py`
   - `codeintel_rev/retrieval/rerank_flat.py`
   - Replace with: `from codeintel_rev.observability.otel import as_span`
   - Update usage: `span_context("name", kind="...", attrs={...})` → `as_span("name", kind="...", **attrs)`

2. **`telemetry.steps.StepEvent, emit_step`** (2 files):
   - `codeintel_rev/io/git_client.py`
   - `codeintel_rev/retrieval/gating.py`
   - Replace with: `from codeintel_rev.observability.otel import record_span_event`
   - Update usage: `emit_step(StepEvent(...))` → `record_span_event("event.name", **payload)`

3. **`telemetry.reporter.finalize_run, start_run`** (1 file):
   - `codeintel_rev/cli/__init__.py`
   - Replace with: `from codeintel_rev.observability.timeline import new_timeline, bind_timeline`
   - Update usage: Use timeline operations instead

### Phase 4: Remove Prometheus References

**Files to update** (remove Prometheus mentions from comments/docs):

1. `codeintel_rev/metrics/registry.py` - Update module docstring
2. `codeintel_rev/io/faiss_manager.py` - Remove Prometheus metric label comments
3. `codeintel_rev/embeddings/embedding_service.py` - Remove Prometheus gauge comments
4. `codeintel_rev/io/duckdb_catalog.py` - Remove Prometheus metric label comments
5. `codeintel_rev/retrieval/telemetry.py` - Remove Prometheus metrics comment
6. `codeintel_rev/mcp_server/common/observability.py` - Remove Prometheus histogram comment
7. `codeintel_rev/app/capabilities.py` - Remove Prometheus metrics placeholder comment
8. `codeintel_rev/mcp_server/scope_utils.py` - Remove Prometheus metrics comment

### Phase 5: Remove PrometheusMetricReader

**File**: `codeintel_rev/observability/otel.py` (if it exists)

- Remove any `PrometheusMetricReader` setup
- Remove Prometheus HTTP server startup code
- Ensure only OTLP exporters are used

## Implementation Steps

1. ✅ Create `codeintel_rev/observability/metrics.py` with OTel Metrics helpers
2. ✅ Replace all Prometheus imports with OTel Metrics imports
3. ✅ Fix broken `telemetry.decorators` imports
4. ✅ Fix broken `telemetry.steps` imports
5. ✅ Fix broken `telemetry.reporter` imports
6. ✅ Remove Prometheus references from comments/docs
7. ✅ Verify no Prometheus imports remain
8. ✅ Run tests to ensure everything works

## Verification

After migration, verify:

```bash
# No Prometheus imports
grep -r "prometheus\|Prometheus\|PROMETHEUS" codeintel_rev --include="*.py" | grep -v "__pycache__"

# No broken telemetry imports
grep -r "telemetry\.(otel_metrics|decorators|steps|reporter)" codeintel_rev --include="*.py"

# All tests pass
uv run pytest tests/ -v
```

## Files Requiring Changes

### Core Changes (10 files)
1. `codeintel_rev/observability/metrics.py` - **NEW** - OTel Metrics helpers
2. `codeintel_rev/metrics/registry.py` - Replace Prometheus imports
3. `codeintel_rev/embeddings/embedding_service.py` - Replace Prometheus imports
4. `codeintel_rev/mcp_server/scope_utils.py` - Replace telemetry.otel_metrics import
5. `codeintel_rev/retrieval/rerank_flat.py` - Replace telemetry imports
6. `codeintel_rev/retrieval/mcp_search.py` - Replace telemetry.decorators import
7. `codeintel_rev/io/git_client.py` - Replace telemetry imports
8. `codeintel_rev/retrieval/gating.py` - Replace telemetry.steps import
9. `codeintel_rev/cli/__init__.py` - Replace telemetry.reporter import
10. `codeintel_rev/observability/otel.py` - Remove PrometheusMetricReader (if exists)

### Documentation Updates (8 files)
- Remove Prometheus references from comments/docstrings in:
  - `codeintel_rev/io/faiss_manager.py`
  - `codeintel_rev/io/duckdb_catalog.py`
  - `codeintel_rev/retrieval/telemetry.py`
  - `codeintel_rev/mcp_server/common/observability.py`
  - `codeintel_rev/app/capabilities.py`
  - `codeintel_rev/mcp_server/scope_utils.py`
  - Plus the 3 core files above

## Notes

- The OTel Metrics helper module should provide a **drop-in replacement** API that matches the Prometheus-like interface
- All metrics will be backed by OpenTelemetry MeterProvider
- Metrics will be exported via OTLP (not Prometheus scrape endpoint)
- The migration maintains backward compatibility at the API level while changing the underlying implementation

