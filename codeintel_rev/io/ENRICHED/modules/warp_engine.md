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

- class: `WarpExecutorProtocol` (line 18)
- function: `search` (line 21)
- class: `WarpUnavailableError` (line 35)
- class: `WarpEngine` (line 39)
- function: `__init__` (line 42)
- function: `rerank` (line 51)
- function: `_load_executor_cls` (line 109)
- function: `_import_warp_executor_module` (line 130)
- function: `_ensure_executor` (line 135)
- function: `_safe_int` (line 166)
- function: `_safe_float` (line 190)

## Tags

overlay-needed
