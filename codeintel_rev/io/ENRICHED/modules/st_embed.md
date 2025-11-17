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
- from **collections.abc** import Iterable
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **(absolute)** import numpy
- from **(absolute)** import torch
- from **sentence_transformers** import SentenceTransformer
- from **codeintel_rev.config.settings** import load_settings

## Definitions

- class: `EmbedJob` (line 26)
- function: `_resolve_model_name` (line 38)
- function: `_resolve_device` (line 47)
- function: `_read_texts` (line 57)
- function: `_dump_jsonl` (line 67)
- function: `_parse_args` (line 73)
- function: `embed_file` (line 117)
- function: `main` (line 165)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 1
- **cycle_group**: 88

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Standalone sentence-transformers embedding helper.
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

## Hotspot

- score: 1.66

## Side Effects

- filesystem

## Complexity

- branches: 14
- cyclomatic: 15
- loc: 197

## Doc Coverage

- `EmbedJob` (class): summary=yes, examples=no — Configuration bundle for an embedding run.
- `_resolve_model_name` (function): summary=no, examples=no
- `_resolve_device` (function): summary=no, examples=no
- `_read_texts` (function): summary=no, examples=no
- `_dump_jsonl` (function): summary=no, examples=no
- `_parse_args` (function): summary=no, examples=no
- `embed_file` (function): summary=yes, params=ok, examples=no — Generate embeddings for text file using SentenceTransformer.
- `main` (function): summary=yes, params=ok, examples=no — Run the SentenceTransformer embedding CLI.

## Tags

low-coverage
