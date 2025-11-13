# io/splade_manager.py

## Docstring

```
SPLADE artifact management, encoding, and Lucene impact index builders.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import json
- from **(absolute)** import logging
- from **(absolute)** import math
- from **(absolute)** import os
- from **(absolute)** import shutil
- from **(absolute)** import statistics
- from **(absolute)** import sys
- from **collections.abc** import Iterable, Sequence
- from **dataclasses** import dataclass
- from **datetime** import UTC, datetime
- from **pathlib** import Path
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, TextIO, cast
- from **(absolute)** import msgspec
- from **codeintel_rev.io.path_utils** import resolve_within_repo
- from **kgfoundry_common.subprocess_utils** import run_subprocess
- from **typing** import Protocol
- from **codeintel_rev.config.settings** import Settings
- from **sentence_transformers** import SparseEncoder
- from **sentence_transformers** import export_dynamic_quantized_onnx_model
- from **sentence_transformers** import export_optimized_onnx_model

## Definitions

- class: `_SparseEncoderProtocol` (line 30)
- class: `_OptimizerFunction` (line 190)
- class: `_QuantizerFunction` (line 201)
- variable: `GENERATOR_NAME` (line 230)
- variable: `ARTIFACT_METADATA_FILENAME` (line 231)
- variable: `ENCODING_METADATA_FILENAME` (line 232)
- variable: `INDEX_METADATA_FILENAME` (line 233)
- variable: `logger` (line 238)
- class: `SpladeArtifactMetadata` (line 241)
- class: `SpladeExportSummary` (line 256)
- class: `SpladeEncodingMetadata` (line 263)
- class: `SpladeEncodingSummary` (line 277)
- class: `SpladeBenchmarkOptions` (line 286)
- class: `SpladeBenchmarkSummary` (line 295)
- class: `SpladeExportOptions` (line 311)
- class: `SpladeEncodeOptions` (line 322)
- class: `SpladeBuildOptions` (line 333)
- class: `SpladeIndexMetadata` (line 343)
- class: `_ShardState` (line 358)
- class: `_ExportContext` (line 374)
- function: `_require_sparse_encoder` (line 385)
- function: `_require_export_helpers` (line 395)
- function: `_write_struct` (line 408)
- function: `_directory_size` (line 416)
- function: `_detect_pyserini_version` (line 444)
- function: `_serialize_relative` (line 453)
- function: `_percentile_value` (line 460)
- function: `_quantize_tokens` (line 501)
- function: `_iter_corpus` (line 512)
- function: `_open_writer` (line 521)
- function: `_flush_batch` (line 551)
- function: `_persist_encoding_metadata` (line 617)
- function: `_encode_records` (line 683)
- function: `_optimize_export` (line 755)
- function: `_quantize_export` (line 805)
- function: `_persist_export_metadata` (line 871)
- class: `SpladeArtifactsManager` (line 921)
- class: `SpladeEncoderService` (line 1006)
- class: `SpladeIndexManager` (line 1287)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 3
- **cycle_group**: 112

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 11
- recent churn 90: 11

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

SpladeArtifactMetadata, SpladeArtifactsManager, SpladeBuildOptions, SpladeEncodeOptions, SpladeEncodingMetadata, SpladeEncodingSummary, SpladeExportOptions, SpladeExportSummary, SpladeIndexManager, SpladeIndexMetadata

## Doc Health

- **summary**: SPLADE artifact management, encoding, and Lucene impact index builders.
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

- score: 2.63

## Side Effects

- filesystem

## Complexity

- branches: 75
- cyclomatic: 76
- loc: 1437

## Doc Coverage

- `_SparseEncoderProtocol` (class): summary=yes, examples=no — Protocol defining the interface for SPLADE sparse encoders.
- `_OptimizerFunction` (class): summary=no, examples=no
- `_QuantizerFunction` (class): summary=no, examples=no
- `SpladeArtifactMetadata` (class): summary=yes, examples=no — Metadata describing exported SPLADE ONNX artifacts.
- `SpladeExportSummary` (class): summary=yes, examples=no — Summary returned after exporting SPLADE artifacts.
- `SpladeEncodingMetadata` (class): summary=yes, examples=no — Metadata describing SPLADE vector encoding runs.
- `SpladeEncodingSummary` (class): summary=yes, examples=no — Summary describing SPLADE encoding output.
- `SpladeBenchmarkOptions` (class): summary=yes, examples=no — Options controlling SPLADE encoder latency benchmarks.
- `SpladeBenchmarkSummary` (class): summary=yes, examples=no — Summary describing SPLADE encoder latency benchmarks.
- `SpladeExportOptions` (class): summary=yes, examples=no — Options controlling SPLADE ONNX export behaviour.

## Tags

low-coverage, public-api, reexport-hub
