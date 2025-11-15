# cli/st_embed.py

## Docstring

```
Standalone sentence-transformers embedding helper.

Invoke via:

    python -m codeintel_rev.cli.st_embed INPUT.txt         --output embeddings.npy         --jsonl embeddings.jsonl
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import argparse
- from **(absolute)** import json
- from **(absolute)** import logging
- from **(absolute)** import sys
- from **pathlib** import Path
- from **typing** import Iterable
- from **(absolute)** import numpy
- from **(absolute)** import torch
- from **sentence_transformers** import SentenceTransformer
- from **codeintel_rev.config.settings** import load_settings

## Definitions

- variable: `LOGGER` (line 25)
- function: `_resolve_model_name` (line 28)
- function: `_resolve_device` (line 37)
- function: `_read_texts` (line 47)
- function: `_dump_jsonl` (line 57)
- function: `_parse_args` (line 63)
- function: `embed_file` (line 107)
- function: `main` (line 146)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 2
- **cycle_group**: 80

## Ownership

- bus factor: 0.00
- recent churn 30: 0
- recent churn 90: 0

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Standalone sentence-transformers embedding helper.
- has summary: yes
- param parity: no
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 1.82

## Side Effects

- filesystem

## Complexity

- branches: 14
- cyclomatic: 15
- loc: 167

## Doc Coverage

- `_resolve_model_name` (function): summary=no, examples=no
- `_resolve_device` (function): summary=no, examples=no
- `_read_texts` (function): summary=no, examples=no
- `_dump_jsonl` (function): summary=no, examples=no
- `_parse_args` (function): summary=no, examples=no
- `embed_file` (function): summary=no, examples=no
- `main` (function): summary=no, examples=no

## Tags

low-coverage
