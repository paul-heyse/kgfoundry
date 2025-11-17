# cli/splade.py

## Docstring

```
Command-line interface for SPLADE artifact management.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Callable
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import Annotated
- from **(absolute)** import click
- from **(absolute)** import msgspec
- from **(absolute)** import typer
- from **tools** import CliContext, EnvelopeBuilder, cli_operation, sha256_file
- from **codeintel_rev.config.settings** import load_settings
- from **codeintel_rev.io.splade_manager** import SpladeArtifactsManager, SpladeBenchmarkOptions, SpladeBuildOptions, SpladeEncodeOptions, SpladeEncoderService, SpladeExportOptions, SpladeIndexManager

## Definitions

- variable: `OptimizeFlag` (line 26)
- variable: `QuantizeFlag` (line 34)
- variable: `OverwriteFlag` (line 42)
- class: `SpladeCliContext` (line 53)
- function: `_default_artifacts_manager_factory` (line 76)
- function: `_default_encoder_service_factory` (line 87)
- function: `_default_index_manager_factory` (line 98)
- variable: `app` (line 109)
- function: `_cli_context` (line 117)
- function: `splade_callback` (line 137)
- function: `_create_artifacts_manager` (line 143)
- function: `_create_encoder_service` (line 154)
- function: `_create_index_manager` (line 165)
- function: `_add_metadata_artifact` (line 176)
- variable: `MODEL_ID_OPTION` (line 182)
- variable: `QUANTIZATION_OPTION` (line 187)
- function: `export_onnx` (line 195)
- variable: `SOURCE_ARGUMENT` (line 250)
- variable: `OUTPUT_DIR_OPTION` (line 254)
- variable: `BATCH_SIZE_OPTION` (line 260)
- variable: `QUANTIZATION_OPTION_ENCODE` (line 267)
- variable: `SHARD_SIZE_OPTION` (line 274)
- function: `encode` (line 284)
- variable: `VECTORS_DIR_OPTION` (line 342)
- variable: `INDEX_DIR_OPTION` (line 348)
- variable: `THREADS_OPTION` (line 354)
- variable: `MAX_CLAUSE_OPTION` (line 361)
- variable: `QUERY_OPTION` (line 368)
- variable: `QUERIES_FILE_OPTION` (line 374)
- variable: `WARMUP_OPTION` (line 379)
- variable: `RUNS_OPTION` (line 386)
- function: `build_index` (line 396)
- function: `bench` (line 457)
- function: `main` (line 568)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 3
- **cycle_group**: 89

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 6
- recent churn 90: 6

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Command-line interface for SPLADE artifact management.
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

- branches: 9
- cyclomatic: 10
- loc: 575

## Doc Coverage

- `SpladeCliContext` (class): summary=yes, examples=no — Dependency injection context for SPLADE CLI operations.
- `_default_artifacts_manager_factory` (function): summary=yes, params=ok, examples=no — Construct the default artifacts manager.
- `_default_encoder_service_factory` (function): summary=yes, params=ok, examples=no — Construct the default encoder service.
- `_default_index_manager_factory` (function): summary=yes, params=ok, examples=no — Construct the default index manager.
- `_cli_context` (function): summary=yes, params=mismatch, examples=no — Return the active CLI context.
- `splade_callback` (function): summary=yes, params=mismatch, examples=no — Ensure CLI context defaults are configured.
- `_create_artifacts_manager` (function): summary=yes, params=ok, examples=no — Construct an artifacts manager using the active settings.
- `_create_encoder_service` (function): summary=yes, params=ok, examples=no — Construct an encoder service using the active settings.
- `_create_index_manager` (function): summary=yes, params=ok, examples=no — Construct an index manager using the active settings.
- `_add_metadata_artifact` (function): summary=yes, params=mismatch, examples=no — Attach metadata artifacts to CLI envelopes when available.

## Tags

low-coverage
