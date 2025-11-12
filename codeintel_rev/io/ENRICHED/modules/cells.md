# runtime/cells.py

## Docstring

```
Thread-safe runtime cell primitive for mutable subsystems.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import os
- from **(absolute)** import time
- from **collections.abc** import Callable
- from **dataclasses** import dataclass
- from **threading** import Condition, RLock
- from **typing** import Literal, Protocol, TypeVar, final, runtime_checkable
- from **codeintel_rev.errors** import RuntimeLifecycleError, RuntimeUnavailableError
- from **codeintel_rev.observability.timeline** import Timeline, current_timeline
- from **codeintel_rev.runtime.factory_adjustment** import FactoryAdjuster, NoopFactoryAdjuster
- from **codeintel_rev.runtime.request_context** import capability_stamp_var, session_id_var
- from **kgfoundry_common.logging** import get_logger

## Definitions

- class: `RuntimeCellCloseResult` (line 31)
- class: `RuntimeCellInitContext` (line 43)
- class: `RuntimeCellInitResult` (line 52)
- function: `_seed_allowed` (line 64)
- class: `RuntimeCellObserver` (line 71)
- function: `on_init_start` (line 74)
- function: `on_init_end` (line 83)
- function: `on_close_end` (line 86)
- class: `NullRuntimeCellObserver` (line 90)
- function: `on_init_start` (line 95)
- function: `on_init_end` (line 105)
- function: `on_close_end` (line 110)
- class: `RuntimeCell` (line 117)
- function: `__init__` (line 139)
- function: `__repr__` (line 164)
- function: `__bool__` (line 174)
- function: `peek` (line 184)
- function: `configure_observer` (line 195)
- function: `configure_adjuster` (line 200)
- function: `get_or_initialize` (line 208)
- function: `seed` (line 281)
- function: `close` (line 311)
- function: `invalidate` (line 437)
- function: `record_failure` (line 441)
- function: `_resolve_disposer` (line 454)
- function: `_run_close` (line 458)
- function: `_run_exit` (line 466)
- function: `_adjust_factory` (line 472)
- function: `_capture_init_context` (line 476)
- function: `_next_generation_locked` (line 488)
- function: `_clear_cooldown_locked` (line 492)
- function: `_cooldown_error_locked` (line 496)
- function: `_wait_for_initializer` (line 505)
- function: `_run_initializer` (line 530)
- function: `_handle_init_success` (line 549)
- function: `_handle_init_failure` (line 585)

## Tags

overlay-needed, public-api
