# enrich/scip_reader.py

## Docstring

```
Lightweight helpers for loading and querying SCIP JSON indices.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **dataclasses** import dataclass, field
- from **pathlib** import Path
- from **typing** import Any
- from **(absolute)** import orjson

## Definitions

- function: `_loads` (line 17)
- class: `Occurrence` (line 31)
- class: `SymbolInfo` (line 40)
- class: `Document` (line 50)
- class: `SCIPIndex` (line 59)
- function: `load` (line 66)
- function: `by_file` (line 89)
- function: `symbol_to_files` (line 99)
- function: `file_symbol_kinds` (line 113)
- function: `_parse_document` (line 129)

## Tags

overlay-needed
