# mcp_server/telemetry.py

## Docstring

```
Telemetry helpers for MCP tools.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import time
- from **collections.abc** import Iterator
- from **contextlib** import contextmanager
- from **codeintel_rev.app.middleware** import get_capability_stamp, get_session_id
- from **codeintel_rev.observability.otel** import as_span, record_span_event
- from **codeintel_rev.observability.timeline** import Timeline, current_or_new_timeline
- from **codeintel_rev.telemetry.context** import telemetry_context
- from **codeintel_rev.telemetry.prom** import observe_request_latency
- from **codeintel_rev.telemetry.reporter** import finalize_run, start_run

## Definitions

- function: `tool_operation_scope` (line 20)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 6
- **cycle_group**: 74

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 3
- recent churn 90: 3

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

tool_operation_scope

## Doc Health

- **summary**: Telemetry helpers for MCP tools.
- has summary: yes
- param parity: no
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

- score: 2.13

## Side Effects

- none detected

## Complexity

- branches: 7
- cyclomatic: 8
- loc: 123

## Doc Coverage

- `tool_operation_scope` (function): summary=yes, params=mismatch, examples=no — Emit start/end events for an MCP tool and yield the active timeline.

## Tags

low-coverage, public-api
