# observability/timeline.py

## Docstring

```
Lightweight per-session timeline recording utilities.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import contextvars
- from **(absolute)** import hashlib
- from **(absolute)** import json
- from **(absolute)** import os
- from **(absolute)** import secrets
- from **(absolute)** import threading
- from **(absolute)** import time
- from **(absolute)** import uuid
- from **collections.abc** import Iterator, Mapping, Sequence
- from **contextlib** import AbstractContextManager, contextmanager
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **types** import TracebackType
- from **typing** import Any, Self
- from **codeintel_rev.observability.otel** import as_span, record_span_event
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 23)
- function: `_env_float` (line 32)
- function: `_env_int` (line 43)
- function: `_clamp` (line 54)
- function: `_diagnostics_dir` (line 62)
- function: `_max_field_len` (line 68)
- class: `_FlightRecorder` (line 72)
- function: `_scrub_value` (line 180)
- function: `_scrub_attrs` (line 201)
- class: `Timeline` (line 206)
- class: `_TimelineScope` (line 315)
- function: `new_timeline` (line 368)
- function: `current_timeline` (line 403)
- function: `current_or_new_timeline` (line 414)
- function: `bind_timeline` (line 455)

## Graph Metrics

- **fan_in**: 11
- **fan_out**: 2
- **cycle_group**: 39

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 5
- recent churn 90: 5

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

Timeline, bind_timeline, current_timeline, new_timeline

## Doc Health

- **summary**: Lightweight per-session timeline recording utilities.
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

- score: 2.69

## Side Effects

- filesystem

## Complexity

- branches: 36
- cyclomatic: 37
- loc: 491

## Doc Coverage

- `_env_float` (function): summary=no, examples=no
- `_env_int` (function): summary=no, examples=no
- `_clamp` (function): summary=no, examples=no
- `_diagnostics_dir` (function): summary=no, examples=no
- `_max_field_len` (function): summary=no, examples=no
- `_FlightRecorder` (class): summary=yes, examples=no — Append-only JSONL recorder with sampling and rotation.
- `_scrub_value` (function): summary=no, examples=no
- `_scrub_attrs` (function): summary=no, examples=no
- `Timeline` (class): summary=yes, examples=no — Append-only JSONL event recorder for a single session/run pair.
- `_TimelineScope` (class): summary=yes, examples=no — Context manager that emits start/end events with duration.

## Tags

low-coverage, public-api
