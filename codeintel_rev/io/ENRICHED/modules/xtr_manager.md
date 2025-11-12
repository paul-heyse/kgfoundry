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
- from **typing** import TYPE_CHECKING, Any, Literal, Protocol, TypedDict, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.config.settings** import XTRConfig
- from **codeintel_rev.runtime** import RuntimeCell
- from **codeintel_rev.typing** import NDArrayF32, gate_import
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import numpy

## Definitions

- class: `XTRMetadata` (line 25)
- class: `_XTRIndexRuntime` (line 37)
- function: `__init__` (line 42)
- function: `close` (line 50)
- class: `XTRIndex` (line 61)
- function: `open` (line 72)
- function: `ready` (line 127)
- function: `metadata` (line 138)
- function: `encode_query_tokens` (line 151)
- function: `search` (line 193)
- function: `rescore` (line 269)
- function: `score_candidates` (line 343)
- function: `_ensure_encoder` (line 423)
- function: `_resolve_device` (line 447)
- function: `_parse_cuda_ordinal` (line 508)
- function: `_slice_chunk` (line 547)
- function: `_build_chunk_lookup` (line 585)
- function: `close` (line 608)
- function: `_ensure_state` (line 612)
- function: `_current_state` (line 615)
- class: `TorchDeviceModule` (line 619)
- class: `_CudaAPI` (line 622)
- function: `is_available` (line 646)
- function: `device_count` (line 657)
- function: `device` (line 670)

## Tags

overlay-needed
