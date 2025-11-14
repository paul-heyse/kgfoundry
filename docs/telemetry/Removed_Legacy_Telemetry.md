# Removed Legacy Telemetry

The legacy Prometheus/OTel shims have been fully removed in this migration. The
following modules were deleted and their call sites have been updated to use the
new observability stack:

| File | Replacement |
| --- | --- |
| `codeintel_rev/telemetry/prom.py` | Metrics now live under `codeintel_rev.metrics.registry` and the OTel meter is bootstrapped via `codeintel_rev.observability.metrics.install_metrics_provider`. |
| `codeintel_rev/telemetry/otel.py` | Programmatic bootstrap lives exclusively in `codeintel_rev.observability.otel`. |
| `tests/telemetry/test_prometheus_router.py` | Custom `/metrics` endpoint was removed; OTel’s Prometheus reader exposes metrics directly. |

## Migration notes

- Applications and tests should import counters/histograms from
  `codeintel_rev.metrics.registry` instead of `codeintel_rev.telemetry.prom`.
- Telemetry bootstrap is centralized in `codeintel_rev.observability.otel.init_otel`
  and `codeintel_rev.observability.metrics.install_metrics_provider` so there is
  a single source of truth for traces, metrics, and logs.
- Structured logging uses `codeintel_rev.observability.logs.init_otel_logging` via
  `install_structured_logging`, replacing the deleted `telemetry.otel` helpers.
