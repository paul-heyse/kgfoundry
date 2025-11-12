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

## Dependency Graph

- **fan_in**: 11
- **fan_out**: 2
- **cycle_group**: 15

## Declared Exports (__all__)

Timeline, bind_timeline, current_timeline, new_timeline

## Tags

public-api
