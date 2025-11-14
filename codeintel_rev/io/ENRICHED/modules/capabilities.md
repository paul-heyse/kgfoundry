# app/capabilities.py

## Docstring

```
Capability snapshot helpers for conditional tool registration and /capz.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import hashlib
- from **(absolute)** import importlib
- from **(absolute)** import importlib.util
- from **(absolute)** import json
- from **collections.abc** import Callable
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING, Final, cast
- from **codeintel_rev.telemetry.otel_metrics** import GaugeLike, build_gauge
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.typing.heavy_deps** import EXTRAS_HINT
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.errors** import RuntimeLifecycleError
- from **codeintel_rev.observability.otel** import as_span, set_current_span_attrs

## Definitions

- variable: `LOGGER` (line 25)
- function: `_build_capability_gauge` (line 28)
- function: `_import_optional` (line 90)
- function: `_probe_faiss_gpu` (line 125)
- function: `_path_exists` (line 162)
- function: `_record_metrics` (line 184)
- class: `Capabilities` (line 191)

## Graph Metrics

- **fan_in**: 6
- **fan_out**: 5
- **cycle_group**: 78

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 8
- recent churn 90: 8

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

Capabilities

## Doc Health

- **summary**: Capability snapshot helpers for conditional tool registration and /capz.
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

## Config References

- app/hypercorn.toml

## Hotspot

- score: 2.53

## Side Effects

- filesystem

## Complexity

- branches: 25
- cyclomatic: 26
- loc: 382

## Doc Coverage

- `_build_capability_gauge` (function): summary=no, examples=no
- `_import_optional` (function): summary=yes, params=ok, examples=no — Return imported module when available, otherwise ``None``.
- `_probe_faiss_gpu` (function): summary=yes, params=ok, examples=no — Return FAISS GPU availability and optional reason for failure.
- `_path_exists` (function): summary=yes, params=ok, examples=no — Return True when ``path`` is populated and exists on the filesystem.
- `_record_metrics` (function): summary=yes, params=mismatch, examples=no — Update Prometheus gauges with the latest capability snapshot.
- `Capabilities` (class): summary=yes, examples=no — Capability snapshot used for MCP tool gating and the /capz endpoint.

## Tags

low-coverage, public-api
