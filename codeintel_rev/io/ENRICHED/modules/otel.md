# observability/otel.py

## Docstring

```
Optional OpenTelemetry bootstrap helpers.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import os
- from **collections.abc** import Mapping
- from **contextlib** import AbstractContextManager
- from **dataclasses** import dataclass
- from **types** import ModuleType
- from **typing** import Any, Protocol
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.observability** import start_span

## Definitions

- class: `_TelemetryState` (line 21)
- function: `__init__` (line 26)
- class: `SupportsState` (line 32)
- class: `_TraceHandles` (line 39)
- function: `_env_flag` (line 51)
- function: `_sanitize_span_attrs` (line 58)
- function: `_coerce_span_value` (line 67)
- function: `_should_enable` (line 81)
- function: `_load_trace_modules` (line 85)
- function: `_build_provider` (line 107)
- function: `telemetry_enabled` (line 133)
- function: `init_telemetry` (line 144)
- function: `as_span` (line 191)
- function: `record_span_event` (line 219)

## Tags

overlay-needed, public-api
