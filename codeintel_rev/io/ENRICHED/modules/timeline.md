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
- from **collections.abc** import Callable, Iterator, Mapping, Sequence
- from **contextlib** import AbstractContextManager, contextmanager
- from **dataclasses** import dataclass, field
- from **importlib** import import_module
- from **pathlib** import Path
- from **types** import TracebackType
- from **typing** import Any, Self, cast
- from **codeintel_rev.observability.otel** import as_span, record_span_event
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 24)
- function: `_env_float` (line 35)
- function: `_env_int` (line 46)
- function: `_clamp` (line 57)
- function: `_diagnostics_dir` (line 65)
- function: `_max_field_len` (line 71)
- class: `_FlightRecorder` (line 75)
- function: `_get_record_payload_fn` (line 183)
- function: `_scrub_value` (line 210)
- function: `_scrub_attrs` (line 231)
- class: `Timeline` (line 236)
- class: `_TimelineScope` (line 378)
- function: `new_timeline` (line 431)
- function: `current_timeline` (line 466)
- function: `current_or_new_timeline` (line 477)
- function: `bind_timeline` (line 518)

## Graph Metrics

- **fan_in**: 19
- **fan_out**: 2
- **cycle_group**: 47

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 9
- recent churn 90: 9

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

- score: 2.92

## Side Effects

- filesystem

## Complexity

- branches: 42
- cyclomatic: 43
- loc: 554

## Doc Coverage

- `_env_float` (function): summary=no, examples=no
- `_env_int` (function): summary=no, examples=no
- `_clamp` (function): summary=no, examples=no
- `_diagnostics_dir` (function): summary=no, examples=no
- `_max_field_len` (function): summary=no, examples=no
- `_FlightRecorder` (class): summary=yes, examples=no — Append-only JSONL recorder with sampling and rotation.
- `_get_record_payload_fn` (function): summary=yes, params=ok, examples=no — Return the cached reporter hook, importing lazily when required.
- `_scrub_value` (function): summary=no, examples=no
- `_scrub_attrs` (function): summary=no, examples=no
- `Timeline` (class): summary=yes, examples=no — Append-only JSONL event recorder for a single session/run pair.

## Tags

low-coverage, public-api
