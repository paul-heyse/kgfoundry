# enrich/type_integration.py

## Docstring

```
Helpers for collecting Pyright/Pyrefly error summaries.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **(absolute)** import json
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass, field
- from **pathlib** import Path

## Definitions

- class: `TypeFileSummary` (line 14)
- class: `TypeSummary` (line 23)
- function: `_run_command_async` (line 29)
- function: `_try_run` (line 74)
- function: `collect_pyright` (line 104)
- function: `collect_pyrefly` (line 143)
- function: `_parse_pyrefly_jsonl` (line 174)
- function: `_parse_pyrefly_json` (line 183)
- function: `_apply_pyrefly_record` (line 190)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 0
- **cycle_group**: 7
