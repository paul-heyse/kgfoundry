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

## Dependency Graph

- **fan_in**: 6
- **fan_out**: 4
- **cycle_group**: 40
