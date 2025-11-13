# cli/splade.py

## Docstring

```
Command-line interface for SPLADE artifact management.
```

## Imports

- from **__future__** import annotations
- from **pathlib** import Path
- from **typing** import Annotated
- from **(absolute)** import msgspec
- from **(absolute)** import typer
- from **tools** import CliContext, EnvelopeBuilder, cli_operation, sha256_file
- from **codeintel_rev.config.settings** import load_settings
- from **codeintel_rev.io.splade_manager** import SpladeArtifactsManager, SpladeBenchmarkOptions, SpladeBuildOptions, SpladeEncodeOptions, SpladeEncoderService, SpladeExportOptions, SpladeIndexManager

## Definitions

- variable: `OptimizeFlag` (line 23)
- variable: `QuantizeFlag` (line 31)
- variable: `OverwriteFlag` (line 39)
- variable: `app` (line 48)
- function: `_create_artifacts_manager` (line 55)
- function: `_create_encoder_service` (line 66)
- function: `_create_index_manager` (line 77)
- function: `_add_metadata_artifact` (line 88)
- variable: `MODEL_ID_OPTION` (line 94)
- variable: `QUANTIZATION_OPTION` (line 99)
- function: `export_onnx` (line 107)
- variable: `SOURCE_ARGUMENT` (line 162)
- variable: `OUTPUT_DIR_OPTION` (line 166)
- variable: `BATCH_SIZE_OPTION` (line 172)
- variable: `QUANTIZATION_OPTION_ENCODE` (line 179)
- variable: `SHARD_SIZE_OPTION` (line 186)
- function: `encode` (line 196)
- variable: `VECTORS_DIR_OPTION` (line 254)
- variable: `INDEX_DIR_OPTION` (line 260)
- variable: `THREADS_OPTION` (line 266)
- variable: `MAX_CLAUSE_OPTION` (line 273)
- variable: `QUERY_OPTION` (line 280)
- variable: `QUERIES_FILE_OPTION` (line 286)
- variable: `WARMUP_OPTION` (line 291)
- variable: `RUNS_OPTION` (line 298)
- function: `build_index` (line 308)
- function: `bench` (line 369)
- function: `main` (line 480)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 3
- **cycle_group**: 136

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

- score: 1.73

## Side Effects

- filesystem

## Complexity

- branches: 6
- cyclomatic: 7
- loc: 487

## Doc Coverage

- `_create_artifacts_manager` (function): summary=yes, params=ok, examples=no — Construct an artifacts manager using the active settings.
- `_create_encoder_service` (function): summary=yes, params=ok, examples=no — Construct an encoder service using the active settings.
- `_create_index_manager` (function): summary=yes, params=ok, examples=no — Construct an index manager using the active settings.
- `_add_metadata_artifact` (function): summary=yes, params=mismatch, examples=no — Attach metadata artifacts to CLI envelopes when available.
- `export_onnx` (function): summary=yes, params=mismatch, examples=no — Export SPLADE ONNX artifacts (optimized and quantized).
- `encode` (function): summary=yes, params=mismatch, examples=no — Encode a corpus into SPLADE JsonVectorCollection shards.
- `build_index` (function): summary=yes, params=mismatch, examples=no — Build a SPLADE Lucene impact index from JsonVectorCollection shards.
- `bench` (function): summary=yes, params=ok, examples=no — Benchmark SPLADE query encoding latency.
- `main` (function): summary=yes, params=ok, examples=no — Run the SPLADE CLI directly.

## Tags

low-coverage
