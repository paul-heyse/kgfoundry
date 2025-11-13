# io/xtr_manager.py

## Docstring

```
Token-level XTR index manager with late-interaction scoring utilities.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **collections.abc** import Iterable
- from **dataclasses** import dataclass, field
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Any, Literal, TypedDict, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.config.settings** import XTRConfig
- from **codeintel_rev.runtime** import RuntimeCell
- from **codeintel_rev.typing** import NDArrayF32, TorchModule, gate_import
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import numpy

## Definitions

- variable: `np` (line 20)
- variable: `LOGGER` (line 22)
- class: `XTRMetadata` (line 25)
- class: `_XTRIndexRuntime` (line 37)
- class: `XTRIndex` (line 61)

## Graph Metrics

- **fan_in**: 8
- **fan_out**: 4
- **cycle_group**: 68

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 7
- recent churn 90: 7

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Token-level XTR index manager with late-interaction scoring utilities.
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

- score: 2.73

## Side Effects

- filesystem

## Complexity

- branches: 46
- cyclomatic: 47
- loc: 617

## Doc Coverage

- `XTRMetadata` (class): summary=yes, examples=no — Metadata persisted alongside the token memmap.
- `_XTRIndexRuntime` (class): summary=yes, examples=no — Mutable runtime artifacts for XTRIndex.
- `XTRIndex` (class): summary=yes, examples=no — Memory-mapped XTR token index with query encoding + scoring helpers.

## Tags

low-coverage
