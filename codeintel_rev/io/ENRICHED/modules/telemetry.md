# mcp_server/telemetry.py

## Docstring

```
Telemetry helpers for MCP tools.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterator
- from **contextlib** import contextmanager
- from **codeintel_rev.app.middleware** import get_capability_stamp, get_session_id
- from **codeintel_rev.observability.timeline** import Timeline, current_or_new_timeline

## Definitions

- function: `tool_operation_scope` (line 15)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 2
- **cycle_group**: 67

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

- score: 1.80

## Side Effects

- none detected

## Complexity

- branches: 4
- cyclomatic: 5
- loc: 62

## Doc Coverage

- `tool_operation_scope` (function): summary=yes, params=mismatch, examples=no — Emit start/end events for an MCP tool and yield the active timeline.

## Tags

low-coverage, public-api
