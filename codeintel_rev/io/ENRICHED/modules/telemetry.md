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

## Dependency Graph

- **fan_in**: 3
- **fan_out**: 2
- **cycle_group**: 47

## Declared Exports (__all__)

tool_operation_scope

## Tags

public-api
