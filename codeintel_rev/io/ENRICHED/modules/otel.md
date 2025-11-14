# observability/otel.py

## Docstring

```
Optional OpenTelemetry bootstrap helpers.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import os
- from **collections.abc** import Mapping, Sequence
- from **contextlib** import AbstractContextManager, suppress
- from **dataclasses** import dataclass
- from **types** import ModuleType
- from **typing** import Any, Protocol
- from **codeintel_rev.observability.logs** import init_otel_logging
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.observability** import start_span
- from **codeintel_rev.observability.flight_recorder** import install_flight_recorder
- from **codeintel_rev.observability.metrics** import install_metrics_provider

## Definitions

- variable: `LOGGER` (line 24)
- variable: `SpanAttribute` (line 26)
- class: `_TelemetryState` (line 29)
- class: `SupportsState` (line 52)
- class: `_TraceHandles` (line 59)
- function: `_env_flag` (line 77)
- function: `_sanitize_span_attrs` (line 107)
- function: `_coerce_span_value` (line 116)
- function: `_should_enable` (line 130)
- function: `_optional_import` (line 136)
- function: `_load_trace_modules` (line 143)
- function: `_parse_sampler_spec` (line 170)
- function: `_build_sampler` (line 183)
- function: `_build_resource` (line 212)
- function: `_merge_detected_resources` (line 247)
- function: `_build_provider` (line 280)
- function: `telemetry_enabled` (line 308)
- function: `init_telemetry` (line 319)
- function: `init_otel` (line 401)
- function: `init_all_telemetry` (line 424)
- function: `as_span` (line 448)
- function: `record_span_event` (line 476)
- function: `_current_span` (line 500)
- function: `set_current_span_attrs` (line 513)
- function: `_current_span_context` (line 529)
- function: `current_trace_id` (line 542)
- function: `current_span_id` (line 558)
- function: `_install_logging_instrumentation` (line 574)
- function: `instrument_fastapi` (line 590)
- function: `instrument_httpx` (line 605)

## Graph Metrics

- **fan_in**: 22
- **fan_out**: 4
- **cycle_group**: 14

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 11
- recent churn 90: 11

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

as_span, current_span_id, current_trace_id, init_all_telemetry, init_otel, init_telemetry, instrument_fastapi, instrument_httpx, record_span_event, set_current_span_attrs, telemetry_enabled

## Doc Health

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

## Hotspot

- score: 3.26

## Side Effects

- filesystem

## Complexity

- branches: 102
- cyclomatic: 103
- loc: 633

## Doc Coverage

- `_TelemetryState` (class): summary=yes, examples=no — Mutable telemetry state shared across module functions.
- `SupportsState` (class): summary=yes, examples=no — Protocol describing FastAPI-style objects exposing ``state``.
- `_TraceHandles` (class): summary=no, examples=no
- `_env_flag` (function): summary=yes, params=ok, examples=no — Check if an environment variable is set to a truthy value.
- `_sanitize_span_attrs` (function): summary=no, examples=no
- `_coerce_span_value` (function): summary=no, examples=no
- `_should_enable` (function): summary=no, examples=no
- `_optional_import` (function): summary=no, examples=no
- `_load_trace_modules` (function): summary=no, examples=no
- `_parse_sampler_spec` (function): summary=no, examples=no

## Tags

low-coverage, public-api, reexport-hub
