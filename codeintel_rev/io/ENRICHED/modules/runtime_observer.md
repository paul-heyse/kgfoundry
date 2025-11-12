# observability/runtime_observer.py

## Docstring

```
RuntimeCell observer that writes lifecycle events to the active timeline.
```

## Imports

- from **__future__** import annotations
- from **codeintel_rev.observability.timeline** import Timeline, current_timeline
- from **codeintel_rev.runtime.cells** import RuntimeCellCloseResult, RuntimeCellInitContext, RuntimeCellInitResult, RuntimeCellObserver

## Definitions

- class: `TimelineRuntimeObserver` (line 14)
- function: `__init__` (line 19)
- function: `_timeline` (line 22)
- function: `on_init_start` (line 27)
- function: `on_init_end` (line 45)
- function: `on_close_end` (line 76)
- function: `record_decision` (line 90)

## Tags

overlay-needed
