# app/capabilities.py

## Docstring

```
Capability snapshot helpers for conditional tool registration and /capz.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import hashlib
- from **(absolute)** import importlib
- from **(absolute)** import util
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

- function: `_build_capability_gauge` (line 27)
- function: `_import_optional` (line 89)
- function: `_probe_faiss_gpu` (line 124)
- function: `_path_exists` (line 161)
- function: `_record_metrics` (line 183)
- class: `Capabilities` (line 190)
- function: `has_semantic` (line 212)
- function: `has_symbols` (line 223)
- function: `has_reranker` (line 234)
- function: `model_dump` (line 238)
- function: `stamp` (line 278)
- function: `from_context` (line 304)

## Tags

overlay-needed, public-api
