# io/warp_engine.py

## Docstring

```
Adapter for the optional WARP/XTR late interaction executor.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Callable, Sequence
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Protocol, cast
- from **codeintel_rev.typing** import gate_import
- from **kgfoundry_common.logging** import get_logger
- from **types** import ModuleType

## Definitions

- variable: `LOGGER` (line 15)
- class: `WarpExecutorProtocol` (line 19)
- variable: `WarpExecutorFactory` (line 33)
- class: `WarpUnavailableError` (line 36)
- class: `WarpEngine` (line 40)
- function: `_safe_int` (line 167)
- function: `_safe_float` (line 191)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 126

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 9
- recent churn 90: 9

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Adapter for the optional WARP/XTR late interaction executor.
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

- score: 1.84

## Side Effects

- filesystem

## Complexity

- branches: 15
- cyclomatic: 16
- loc: 213

## Doc Coverage

- `WarpExecutorProtocol` (class): summary=yes, examples=no — Protocol describing the WARP executor search surface.
- `WarpUnavailableError` (class): summary=yes, examples=no — Raised when the WARP executor or index artifacts are missing.
- `WarpEngine` (class): summary=yes, examples=no — Encapsulates interactions with the optional ``xtr-warp`` executor.
- `_safe_int` (function): summary=yes, params=ok, examples=no — Convert an object to int safely, falling back to the provided default.
- `_safe_float` (function): summary=yes, params=ok, examples=no — Convert an object to float safely, falling back to the provided default.

## Tags

low-coverage
