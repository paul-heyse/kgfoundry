# startup/run_startup_pipeline.py

## Docstring

```
Run the SCIP → chunk → embed → FAISS pipeline and summarize artifacts.

This script is a thin orchestrator around ``codeintel_rev.bin.index_all`` that
also reports the resulting DuckDB/FAISS state so you can confirm bootstrapping
worked. It assumes the environment variables consumed by ``load_settings()``
are already exported (e.g., ``REPO_ROOT``, ``SCIP_INDEX``, ``VLLM_URL``).
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import argparse
- from **(absolute)** import subprocess
- from **(absolute)** import sys
- from **pathlib** import Path
- from **typing** import Sequence
- from **codeintel_rev.app.config_context** import resolve_application_paths
- from **codeintel_rev.config.settings** import Settings, load_settings
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog

## Definitions

- variable: `REPO_ROOT` (line 18)
- variable: `SRC_ROOT` (line 19)
- function: `_run_index_pipeline` (line 29)
- function: `_summarize_artifacts` (line 37)
- function: `main` (line 69)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 4
- **cycle_group**: 168

## Ownership

- bus factor: 0.00
- recent churn 30: 0
- recent churn 90: 0

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Run the SCIP → chunk → embed → FAISS pipeline and summarize artifacts.
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

## Config References

- startup/vllm_expected_operations.md
- startup/vllm.md

## Hotspot

- score: 1.96

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 11
- cyclomatic: 12
- loc: 122

## Doc Coverage

- `_run_index_pipeline` (function): summary=yes, params=mismatch, examples=no — Invoke the existing indexing pipeline module with the requested flags.
- `_summarize_artifacts` (function): summary=yes, params=mismatch, examples=no — Print chunk counts, embedding dimensions, and FAISS file locations.
- `main` (function): summary=yes, params=ok, examples=no — Entry point for the startup pipeline runner.

## Tags

low-coverage
