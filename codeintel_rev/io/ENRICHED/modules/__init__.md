# telemetry/__init__.py

## Docstring

```
Phase-0 telemetry helpers (tracing, metrics, logging, run reports).
```

## Imports

- from **__future__** import annotations
- from **codeintel_rev.telemetry.context** import attach_context_attrs, current_run_id, current_session, current_stage, request_tool_var, run_id_var, session_id_var, set_request_stage, telemetry_context
- from **codeintel_rev.telemetry.decorators** import trace_span, trace_step
- from **codeintel_rev.telemetry.events** import RunCheckpoint, TimelineEvent, checkpoint_event
- from **codeintel_rev.telemetry.logging** import install_structured_logging
- from **codeintel_rev.telemetry.otel** import install_otel
- from **codeintel_rev.telemetry.prom** import MetricsConfig, build_metrics_router, observe_request_latency

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 6
- **cycle_group**: 19

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 1
- recent churn 90: 1

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

MetricsConfig, RunCheckpoint, TimelineEvent, attach_context_attrs, build_metrics_router, checkpoint_event, current_run_id, current_session, current_stage, install_otel, install_structured_logging, observe_request_latency, request_tool_var, run_id_var, session_id_var, set_request_stage, telemetry_context, trace_span, trace_step

## Doc Health

- **summary**: Phase-0 telemetry helpers (tracing, metrics, logging, run reports).
- has summary: yes
- param parity: yes
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 1.59

## Side Effects

- none detected

## Complexity

- branches: 0
- cyclomatic: 1
- loc: 47

## Tags

low-coverage, public-api, reexport-hub
