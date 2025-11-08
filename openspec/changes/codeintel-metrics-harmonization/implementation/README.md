# Implementation Reference

This directory contains reference implementations for the metrics harmonization change.

## Files

- `observability.py` - Shared observability helper (to be placed at `codeintel_rev/mcp_server/common/observability.py`)
- `README.md` - This file (junior developer guide)

## Quick Start

### For Junior Developers

This implementation consolidates duplicate metrics code from multiple adapters into a single shared module. Here's what you need to know:

#### Before (Duplicated in Each Adapter)

```python
# BEFORE: codeintel_rev/mcp_server/adapters/text_search.py
# 30+ lines of boilerplate repeated in semantic.py

class _NoopObservation:
    def mark_error(self) -> None:
        pass
    def mark_success(self) -> None:
        pass

@contextmanager
def _observe(operation: str) -> Iterator[DurationObservation | _NoopObservation]:
    if not _METRICS_ENABLED:
        yield _NoopObservation()
        return
    try:
        with observe_duration(METRICS, operation, component=COMPONENT_NAME) as observation:
            yield observation
    except ValueError:
        yield _NoopObservation()
```

#### After (Single Shared Helper)

```python
# AFTER: Import from common module
from codeintel_rev.mcp_server.common.observability import observe_duration

# Use directly
with observe_duration("search", "text_search") as obs:
    # perform operation
    obs.mark_success()
```

### How to Use in Your Adapter

1. **Import the helper**:
   ```python
   from codeintel_rev.mcp_server.common.observability import observe_duration
   ```

2. **Wrap your operation**:
   ```python
   with observe_duration("operation_name", "component_name") as obs:
       try:
           # Your code here
           result = perform_operation()
           obs.mark_success()
           return result
       except Exception as exc:
           obs.mark_error()
           raise
   ```

3. **Remove local boilerplate**:
   - Delete `_NoopObservation` class
   - Delete `_observe()` function
   - Delete `_supports_histogram_labels()` function
   - Delete `_METRICS_ENABLED` variable

### Metrics Behavior

- **Same metrics names**: `kgfoundry_operation_duration_seconds`
- **Same labels**: `component`, `operation`, `status`
- **Graceful degradation**: Noop when Prometheus unavailable
- **100% backward compatible**

### Testing Your Changes

```bash
# Run adapter tests
pytest tests/codeintel_rev/test_text_search_adapter.py -v

# Verify metrics still emitted
# Start server and check /metrics endpoint

# Run all quality gates
uv run ruff format codeintel_rev/mcp_server/adapters/text_search.py
uv run pyright codeintel_rev/mcp_server/adapters/text_search.py
uv run pyrefly check codeintel_rev/mcp_server/adapters/text_search.py
```

### Common Questions

**Q: Will this change metrics output?**  
A: No, metrics names, labels, and values remain identical.

**Q: What if metrics are disabled?**  
A: The helper gracefully falls back to noop, just like before.

**Q: Do I need to change my error handling?**  
A: No, error handling in adapters remains unchanged.

**Q: How do I test observability?**  
A: See `tests/codeintel_rev/test_observability_common.py` for examples.

## Architecture

```
Adapters (text_search, semantic)
        ↓
codeintel_rev/mcp_server/common/observability.py
        ↓
kgfoundry_common/observability.py (MetricsProvider)
        ↓
kgfoundry_common/prometheus.py
        ↓
prometheus_client (or noop stubs)
```

## Benefits

- ✅ **60+ lines removed** (30 per adapter)
- ✅ **Single source of truth** for metrics logic
- ✅ **Easier maintenance** (fix bugs once, not twice)
- ✅ **Consistency** with kgfoundry_common patterns
- ✅ **Better testing** (test once, reuse everywhere)

