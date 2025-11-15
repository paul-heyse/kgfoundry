# observability/logs.py

## Docstring

```
OpenTelemetry logging bootstrap helpers.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import logging
- from **(absolute)** import os
- from **collections.abc** import Callable, Iterable
- from **dataclasses** import dataclass
- from **functools** import lru_cache
- from **typing** import Any
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 15)
- class: `_LoggingAPI` (line 22)
- function: `_load_logging_api` (line 32)
- function: `_should_enable` (line 70)
- function: `_instrument_stdlib_logging` (line 79)
- function: `init_otel_logging` (line 98)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 1
- **cycle_group**: 8

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

init_otel_logging

## Doc Health

- **summary**: OpenTelemetry logging bootstrap helpers.
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

- score: 2.00

## Side Effects

- filesystem

## Complexity

- branches: 18
- cyclomatic: 19
- loc: 150

## Doc Coverage

- `_LoggingAPI` (class): summary=no, examples=no
- `_load_logging_api` (function): summary=yes, params=ok, examples=no — Return Otel logging classes when the dependency is installed.
- `_should_enable` (function): summary=no, examples=no
- `_instrument_stdlib_logging` (function): summary=yes, params=ok, examples=no — Enable OpenTelemetry's stdlib logging bridge when the package is installed.
- `init_otel_logging` (function): summary=yes, params=mismatch, examples=no — Bridge stdlib logging into OpenTelemetry logs when available.

## Tags

low-coverage, public-api
