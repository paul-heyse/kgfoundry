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
- from **collections.abc** import Callable, Iterable, Mapping, Sequence
- from **dataclasses** import dataclass
- from **datetime** import UTC, datetime
- from **pathlib** import Path
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, TextIO, TypedDict, Unpack, cast
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
- class: `_SparseEncoderFactory` (line 202)
- class: `_OptimizerKwargs` (line 211)
- class: `_OptimizerFunction` (line 217)
- class: `_QuantizerKwargs` (line 224)
- class: `_QuantizerFunction` (line 230)
- variable: `GENERATOR_NAME` (line 255)
- variable: `ARTIFACT_METADATA_FILENAME` (line 256)
- variable: `ENCODING_METADATA_FILENAME` (line 257)
- variable: `INDEX_METADATA_FILENAME` (line 258)
- variable: `logger` (line 263)
- class: `SpladeArtifactMetadata` (line 266)
- class: `SpladeExportSummary` (line 281)
- class: `SpladeEncodingMetadata` (line 288)
- class: `SpladeEncodingSummary` (line 302)
- class: `SpladeBenchmarkOptions` (line 311)
- class: `SpladeBenchmarkSummary` (line 320)
- class: `SpladeExportOptions` (line 336)
- class: `SpladeEncodeOptions` (line 347)
- class: `SpladeBuildOptions` (line 358)
- class: `SpladeIndexMetadata` (line 368)
- class: `_ShardState` (line 383)
- class: `_ExportContext` (line 399)
- function: `_require_sparse_encoder` (line 410)
- function: `_require_export_helpers` (line 420)
- function: `_write_struct` (line 433)
- function: `_directory_size` (line 441)
- function: `_detect_pyserini_version` (line 469)
- class: `SpladeEncoderContext` (line 479)
- class: `SpladeArtifactsContext` (line 497)
- class: `SpladeIndexContext` (line 521)
- function: `_serialize_relative` (line 546)
- function: `_percentile_value` (line 553)
- function: `_quantize_tokens` (line 594)
- function: `_iter_corpus` (line 605)
- function: `_open_writer` (line 614)
- function: `_flush_batch` (line 644)
- function: `_persist_encoding_metadata` (line 710)
- function: `_encode_records` (line 776)
- function: `_optimize_export` (line 848)
- function: `_quantize_export` (line 902)
- function: `_persist_export_metadata` (line 972)
- class: `SpladeArtifactsManager` (line 1026)
- class: `SpladeEncoderService` (line 1129)
- class: `SpladeIndexManager` (line 1419)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 3
- **cycle_group**: 56

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 15
- recent churn 90: 15

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

- score: 2.65

## Side Effects

- filesystem

## Raises

NotImplementedError

## Complexity

- branches: 82
- cyclomatic: 83
- loc: 1576

## Doc Coverage

- `_SparseEncoderProtocol` (class): summary=yes, examples=no — Protocol defining the interface for SPLADE sparse encoders.
- `_SparseEncoderFactory` (class): summary=no, examples=no
- `_OptimizerKwargs` (class): summary=no, examples=no
- `_OptimizerFunction` (class): summary=no, examples=no
- `_QuantizerKwargs` (class): summary=no, examples=no
- `_QuantizerFunction` (class): summary=no, examples=no
- `SpladeArtifactMetadata` (class): summary=yes, examples=no — Metadata describing exported SPLADE ONNX artifacts.
- `SpladeExportSummary` (class): summary=yes, examples=no — Summary returned after exporting SPLADE artifacts.
- `SpladeEncodingMetadata` (class): summary=yes, examples=no — Metadata describing SPLADE vector encoding runs.
- `SpladeEncodingSummary` (class): summary=yes, examples=no — Summary describing SPLADE encoding output.

## Tags

low-coverage, public-api, reexport-hub
