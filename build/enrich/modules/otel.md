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

- variable: `LOGGER` (line 16)
- variable: `SpanAttribute` (line 18)
- class: `_TelemetryState` (line 21)
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

## Dependency Graph

- **fan_in**: 4
- **fan_out**: 1
- **cycle_group**: 28

## Declared Exports (__all__)

as_span, init_telemetry, record_span_event, telemetry_enabled

## Doc Metrics

- **summary**: Optional OpenTelemetry bootstrap helpers.
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

## Hotspot Score

- score: 2.33

## Side Effects

- filesystem

## Complexity

- branches: 33
- cyclomatic: 34
- loc: 244

## Doc Coverage

- `_TelemetryState` (class): summary=yes, examples=no — Mutable telemetry state shared across module functions.
- `SupportsState` (class): summary=yes, examples=no — Protocol describing FastAPI-style objects exposing ``state``.
- `_TraceHandles` (class): summary=no, examples=no
- `_env_flag` (function): summary=no, examples=no
- `_sanitize_span_attrs` (function): summary=no, examples=no
- `_coerce_span_value` (function): summary=no, examples=no
- `_should_enable` (function): summary=no, examples=no
- `_load_trace_modules` (function): summary=no, examples=no
- `_build_provider` (function): summary=no, examples=no
- `telemetry_enabled` (function): summary=yes, params=ok, examples=no — Return ``True`` when tracing has been configured for this process.

## Tags

low-coverage, public-api
