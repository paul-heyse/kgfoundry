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
- from **collections.abc** import Callable, Iterator, Mapping
- from **contextlib** import contextmanager
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING, Final
- from **codeintel_rev.io.faiss_compat** import load_faiss_module
- from **kgfoundry_common.typing.heavy_deps** import EXTRAS_HINT
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.errors** import RuntimeLifecycleError

## Definitions

- function: `_import_optional` (line 36)
- function: `override_capability_imports` (line 76)
- function: `override_capabilities` (line 118)
- function: `_path_exists` (line 143)
- class: `Capabilities` (line 166)

## Graph Metrics

- **fan_in**: 5
- **fan_out**: 4
- **cycle_group**: 30

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 14
- recent churn 90: 14

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

Capabilities, override_capabilities, override_capability_imports

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
- loc: 337

## Doc Coverage

- `_import_optional` (function): summary=yes, params=ok, examples=no — Return imported module when available, otherwise ``None``.
- `override_capability_imports` (function): summary=yes, params=ok, examples=no — Temporarily override optional imports used for capability detection.
- `override_capabilities` (function): summary=yes, params=ok, examples=no — Temporarily override the capability snapshot factory.
- `_path_exists` (function): summary=yes, params=ok, examples=no — Return True when ``path`` is populated and exists on the filesystem.
- `Capabilities` (class): summary=yes, examples=no — Capability snapshot used for MCP tool gating and the /capz endpoint.

## Tags

low-coverage, public-api
