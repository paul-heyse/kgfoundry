# config_indexer.py

## Docstring

```
Config awareness helpers (YAML/TOML/JSON/Markdown).
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import re
- from **pathlib** import Path
- from **typing** import Any

## Definitions

- variable: `CONFIG_EXTENSIONS` (line 11)
- function: `index_config_files` (line 14)
- function: `_extract_keys` (line 47)
- function: `_extract_yaml_keys` (line 60)
- function: `_extract_toml_keys` (line 73)
- function: `_extract_json_keys` (line 86)
- function: `_extract_markdown_headings` (line 112)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 6

## Doc Metrics

- **summary**: Config awareness helpers (YAML/TOML/JSON/Markdown).
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

## Hotspot Score

- score: 1.94

## Side Effects

- filesystem

## Complexity

- branches: 22
- cyclomatic: 23
- loc: 118

## Doc Coverage

- `index_config_files` (function): summary=yes, params=ok, examples=no — Return config metadata (path + extracted keys/headings).
- `_extract_keys` (function): summary=no, examples=no
- `_extract_yaml_keys` (function): summary=no, examples=no
- `_extract_toml_keys` (function): summary=no, examples=no
- `_extract_json_keys` (function): summary=no, examples=no
- `_extract_markdown_headings` (function): summary=no, examples=no

## Tags

low-coverage
