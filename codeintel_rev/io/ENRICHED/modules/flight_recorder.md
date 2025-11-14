# observability/flight_recorder.py

## Docstring

```
Trace-anchored flight recorder that mirrors run execution timelines.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import os
- from **(absolute)** import threading
- from **collections.abc** import Iterable, Mapping, Sequence
- from **dataclasses** import dataclass, field
- from **datetime** import UTC, datetime
- from **pathlib** import Path
- from **typing** import Any, cast
- from **codeintel_rev.observability.semantic_conventions** import Attrs
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 17)
- variable: `FlightEvent` (line 20)
- function: `_data_root` (line 23)
- function: `_date_segment` (line 34)
- function: `_scrub_value` (line 53)
- function: `_event_start_ns` (line 65)
- function: `_report_path` (line 70)
- function: `build_report_uri` (line 106)
- class: `_RunBuffer` (line 140)
- class: `_FlightRecorder` (line 152)
- class: `FlightRecorderSpanProcessor` (line 252)
- function: `install_flight_recorder` (line 290)
- function: `_trace_id` (line 310)
- function: `_span_id` (line 320)
- function: `_update_identities` (line 330)
- function: `_update_status` (line 340)
- function: `_is_root_span` (line 354)
- function: `_build_event` (line 362)
- function: `build_event_summary` (line 391)
- function: `_convert_span_events` (line 432)
- function: `_ts` (line 446)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 2
- **cycle_group**: 13

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 5
- recent churn 90: 5

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Trace-anchored flight recorder that mirrors run execution timelines.
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

- score: 2.55

## Side Effects

- filesystem

## Complexity

- branches: 72
- cyclomatic: 73
- loc: 451

## Doc Coverage

- `_data_root` (function): summary=yes, params=ok, examples=no — Return the base directory for diagnostic run artifacts.
- `_date_segment` (function): summary=yes, params=ok, examples=no — Return the YYYYMMDD segment for a run report.
- `_scrub_value` (function): summary=no, examples=no
- `_event_start_ns` (function): summary=no, examples=no
- `_report_path` (function): summary=yes, params=ok, examples=no — Return the filesystem path for a diagnostic run report.
- `build_report_uri` (function): summary=yes, params=ok, examples=no — Return the expected diagnostic report path for the provided identifiers.
- `_RunBuffer` (class): summary=no, examples=no
- `_FlightRecorder` (class): summary=yes, examples=no — Collect spans per-trace and emit ordered JSON reports.
- `FlightRecorderSpanProcessor` (class): summary=yes, examples=no — Minimal SpanProcessor-compatible shim.
- `install_flight_recorder` (function): summary=yes, params=mismatch, examples=no — Attach the flight recorder span processor exactly once.

## Tags

low-coverage
