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
- class: `WarpExecutorProtocol` (line 18)
- variable: `WarpExecutorFactory` (line 32)
- class: `WarpUnavailableError` (line 35)
- class: `WarpEngine` (line 39)
- function: `_safe_int` (line 166)
- function: `_safe_float` (line 190)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 67
