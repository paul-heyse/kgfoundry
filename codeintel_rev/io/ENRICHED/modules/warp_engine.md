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
- from **types** import ModuleType

## Definitions

- class: `WarpExecutorProtocol` (line 17)
- variable: `WarpExecutorFactory` (line 31)
- class: `WarpUnavailableError` (line 34)
- class: `WarpEngine` (line 38)
- function: `_safe_int` (line 161)
- function: `_safe_float` (line 185)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 113

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 10
- recent churn 90: 10

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
- loc: 207

## Doc Coverage

- `WarpExecutorProtocol` (class): summary=yes, examples=no — Protocol describing the WARP executor search surface.
- `WarpUnavailableError` (class): summary=yes, examples=no — Raised when the WARP executor or index artifacts are missing.
- `WarpEngine` (class): summary=yes, examples=no — Encapsulates interactions with the optional ``xtr-warp`` executor.
- `_safe_int` (function): summary=yes, params=ok, examples=no — Convert an object to int safely, falling back to the provided default.
- `_safe_float` (function): summary=yes, params=ok, examples=no — Convert an object to float safely, falling back to the provided default.

## Tags

low-coverage
