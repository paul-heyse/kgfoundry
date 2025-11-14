# Removed Legacy Telemetry

## Summary

This document enumerates legacy telemetry modules and patterns that have been removed or consolidated as part of the OpenTelemetry migration.

## Status

**No legacy `telemetry.prom` or `telemetry.otel` modules were found** in the codebase. The migration focused on:

1. Ensuring all telemetry goes through `observability/otel.py` bootstrap
2. Consolidating metrics via `telemetry/otel_metrics.py` compatibility layer
3. Adding comprehensive domain spans across hot paths
4. Enhancing Run Report v2 with trace-anchored data

## Current Architecture

### Telemetry Modules (Active)

- **`observability/otel.py`** - Main OTel bootstrap (traces, metrics, logs)
- **`observability/metrics.py`** - Metrics provider setup with Prometheus reader
- **`telemetry/otel_metrics.py`** - Compatibility layer (CounterLike, HistogramLike, GaugeLike)
- **`metrics/registry.py`** - Centralized metric definitions
- **`telemetry/reporter.py`** - Run report generation (V1 and V2)
- **`telemetry/decorators.py`** - Span decorators
- **`telemetry/events.py`** - Event emission
- **`telemetry/context.py`** - Context management
- **`telemetry/steps.py`** - Step event tracking

### Import Patterns

All telemetry imports should use:
- `from codeintel_rev.observability.otel import ...` for bootstrap and span helpers
- `from codeintel_rev.telemetry.otel_metrics import ...` for metrics (compatibility layer)
- `from codeintel_rev.metrics.registry import ...` for metric instruments
- `from codeintel_rev.telemetry.decorators import ...` for span decorators

### Banned Imports

The following import patterns are **not allowed** and will fail tests:

- `from codeintel_rev.telemetry.prom import ...` (no such module)
- `from codeintel_rev.telemetry.otel import ...` (use `observability.otel` instead)
- Direct `prometheus_client` imports (except in `observability/metrics.py` for HTTP server)

## Migration Checklist

- [x] Verify no `telemetry.prom` imports exist
- [x] Verify no `telemetry.otel` imports exist  
- [x] All metrics use OTel via `telemetry/otel_metrics.py`
- [x] All bootstrap goes through `observability/otel.py`
- [x] Run Report v2 includes trace_id/span_id
- [x] Tests prevent regressions

## Testing

Run the following to verify no legacy imports:

```bash
uv run pytest tests/test_no_legacy_telemetry.py -v
```

This test will fail if any banned imports are detected.
