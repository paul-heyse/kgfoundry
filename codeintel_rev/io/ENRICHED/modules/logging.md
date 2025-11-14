# telemetry/logging.py

## Docstring

```
Structured logging bridge + optional OTLP exporter.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import logging
- from **(absolute)** import os
- from **typing** import Any
- from **codeintel_rev.telemetry.otel** import _env_flag, build_resource
- from **kgfoundry_common.logging** import setup_logging

## Definitions

- variable: `LOGGER` (line 13)
- function: `_load_logging_dependencies` (line 17)
- function: `install_structured_logging` (line 50)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 2
- **cycle_group**: 54

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Structured logging bridge + optional OTLP exporter.
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

- score: 1.81

## Side Effects

- filesystem

## Complexity

- branches: 6
- cyclomatic: 7
- loc: 85

## Doc Coverage

- `_load_logging_dependencies` (function): summary=yes, params=ok, examples=no — Import OpenTelemetry logging modules lazily to keep deps optional.
- `install_structured_logging` (function): summary=yes, params=mismatch, examples=no — Install JSON logging and optional OTLP log export.

## Tags

low-coverage
