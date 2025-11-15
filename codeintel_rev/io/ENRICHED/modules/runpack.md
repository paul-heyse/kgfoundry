# observability/runpack.py

## Docstring

```
Helpers for building per-run diagnostic artifacts ("runpacks").
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import io
- from **(absolute)** import json
- from **(absolute)** import zipfile
- from **collections.abc** import Mapping
- from **dataclasses** import fields, is_dataclass
- from **pathlib** import Path
- from **time** import time
- from **typing** import Any
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.observability.otel** import telemetry_enabled
- from **codeintel_rev.observability.reporting** import build_timeline_run_report, latest_run_report, resolve_timeline_dir
- from **codeintel_rev.telemetry.reporter** import build_report, report_to_json
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 24)
- function: `_json_bytes` (line 29)
- function: `_write_bytes` (line 33)
- function: `_sanitize_dataclass` (line 39)
- function: `_settings_summary` (line 52)
- function: `_runtime_facts` (line 74)
- function: `_context_snapshot` (line 99)
- function: `_extract_budget` (line 108)
- function: `_structured_report` (line 123)
- function: `make_runpack` (line 138)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 6
- **cycle_group**: 49

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 1
- recent churn 90: 1

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

make_runpack

## Doc Health

- **summary**: Helpers for building per-run diagnostic artifacts ("runpacks").
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

- score: 2.44

## Side Effects

- filesystem

## Complexity

- branches: 27
- cyclomatic: 28
- loc: 237

## Doc Coverage

- `_json_bytes` (function): summary=no, examples=no
- `_write_bytes` (function): summary=no, examples=no
- `_sanitize_dataclass` (function): summary=no, examples=no
- `_settings_summary` (function): summary=no, examples=no
- `_runtime_facts` (function): summary=no, examples=no
- `_context_snapshot` (function): summary=no, examples=no
- `_extract_budget` (function): summary=no, examples=no
- `_structured_report` (function): summary=no, examples=no
- `make_runpack` (function): summary=yes, params=ok, examples=no — Build a zipped telemetry artifact for ``session_id``/``run_id``.

## Tags

low-coverage, public-api
