# diagnostics/report_cli.py

## Docstring

```
CLI for rendering session timelines as Markdown diagnostics.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import argparse
- from **(absolute)** import json
- from **collections** import defaultdict
- from **collections.abc** import Callable, Iterable
- from **pathlib** import Path
- from **typing** import Any

## Definitions

- variable: `GLYPHS` (line 12)
- variable: `STAGE_EVENT_MAP` (line 13)
- variable: `HASH_PREVIEW_LEN` (line 19)
- function: `_load_events` (line 22)
- function: `_group_events_by_run` (line 37)
- function: `_select_run_events` (line 46)
- function: `_format_attrs` (line 59)
- function: `_build_operation_chain` (line 72)
- function: `_find_event` (line 87)
- function: `_find_last_success` (line 97)
- function: `_find_first_failure` (line 104)
- function: `_format_event_summary` (line 108)
- function: `_collect_stage_entries` (line 123)
- function: `_collect_skip_events` (line 133)
- function: `_collect_decisions` (line 137)
- function: `_render_header` (line 141)
- function: `_render_operations_section` (line 156)
- function: `_render_stage_section` (line 177)
- function: `_render_skip_section` (line 205)
- function: `_render_decisions_section` (line 219)
- function: `_render_report` (line 234)
- function: `main` (line 292)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 1
- **cycle_group**: 11
