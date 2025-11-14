# cst_build/cst_serialize.py

## Docstring

```
Writers and helpers that persist CST datasets to disk.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import gzip
- from **(absolute)** import json
- from **collections.abc** import Iterable, Sequence
- from **contextlib** import ExitStack
- from **datetime** import UTC, datetime
- from **hashlib** import blake2s
- from **pathlib** import Path
- from **types** import TracebackType
- from **typing** import Self, TextIO
- from **codeintel_rev.cst_build.cst_resolve** import StitchCounters
- from **codeintel_rev.cst_build.cst_schema** import SCHEMA_VERSION, CollectorStats, NodeRecord
- from **codeintel_rev.enrich.output_writers** import write_json

## Definitions

- class: `DatasetWriter` (line 21)
- function: `write_index` (line 155)
- function: `write_join_examples` (line 184)
- function: `_module_slug` (line 215)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 4
- **cycle_group**: 111

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 3
- recent churn 90: 3

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Writers and helpers that persist CST datasets to disk.
- has summary: yes
- param parity: no
- examples present: yes

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 2.16

## Side Effects

- filesystem

## Complexity

- branches: 18
- cyclomatic: 19
- loc: 221

## Doc Coverage

- `DatasetWriter` (class): summary=yes, examples=no — Stream-oriented writer that materializes the dataset artifacts.
- `write_index` (function): summary=yes, params=mismatch, examples=no — Persist index.json summarizing the build.
- `write_join_examples` (function): summary=yes, params=mismatch, examples=yes — Write markdown examples linking nodes to SCIP symbols.
- `_module_slug` (function): summary=no, examples=no

## Tags

low-coverage
