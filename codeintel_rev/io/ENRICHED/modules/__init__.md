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

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 4
- **cycle_group**: 16

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

RunCheckpoint, TimelineEvent, attach_context_attrs, checkpoint_event, current_run_id, current_session, current_stage, install_structured_logging, request_tool_var, run_id_var, session_id_var, set_request_stage, telemetry_context, trace_span, trace_step

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

- score: 1.47

## Side Effects

- none detected

## Complexity

- branches: 0
- cyclomatic: 1
- loc: 37

## Tags

low-coverage, public-api, reexport-hub
