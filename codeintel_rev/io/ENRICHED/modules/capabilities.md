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
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.prometheus** import GaugeLike, build_gauge
- from **kgfoundry_common.typing.heavy_deps** import EXTRAS_HINT
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.errors** import RuntimeLifecycleError

## Definitions

- variable: `LOGGER` (line 24)
- function: `_build_capability_gauge` (line 27)
- function: `_import_optional` (line 89)
- function: `_probe_faiss_gpu` (line 124)
- function: `_path_exists` (line 161)
- function: `_record_metrics` (line 183)
- class: `Capabilities` (line 190)

## Graph Metrics

- **fan_in**: 6
- **fan_out**: 3
- **cycle_group**: 70

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 6
- recent churn 90: 6

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

- score: 2.43

## Side Effects

- filesystem

## Complexity

- branches: 23
- cyclomatic: 24
- loc: 369

## Doc Coverage

- `_build_capability_gauge` (function): summary=no, examples=no
- `_import_optional` (function): summary=yes, params=ok, examples=no — Return imported module when available, otherwise ``None``.
- `_probe_faiss_gpu` (function): summary=yes, params=ok, examples=no — Return FAISS GPU availability and optional reason for failure.
- `_path_exists` (function): summary=yes, params=ok, examples=no — Return True when ``path`` is populated and exists on the filesystem.
- `_record_metrics` (function): summary=yes, params=mismatch, examples=no — Update Prometheus gauges with the latest capability snapshot.
- `Capabilities` (class): summary=yes, examples=no — Capability snapshot used for MCP tool gating and the /capz endpoint.

## Tags

low-coverage, public-api
