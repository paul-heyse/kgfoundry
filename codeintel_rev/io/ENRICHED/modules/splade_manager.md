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
- class: `_OptimizerKwargs` (line 202)
- class: `_OptimizerFunction` (line 208)
- class: `_QuantizerKwargs` (line 215)
- class: `_QuantizerFunction` (line 221)
- variable: `GENERATOR_NAME` (line 246)
- variable: `ARTIFACT_METADATA_FILENAME` (line 247)
- variable: `ENCODING_METADATA_FILENAME` (line 248)
- variable: `INDEX_METADATA_FILENAME` (line 249)
- variable: `logger` (line 254)
- class: `SpladeArtifactMetadata` (line 257)
- class: `SpladeExportSummary` (line 272)
- class: `SpladeEncodingMetadata` (line 279)
- class: `SpladeEncodingSummary` (line 293)
- class: `SpladeBenchmarkOptions` (line 302)
- class: `SpladeBenchmarkSummary` (line 311)
- class: `SpladeExportOptions` (line 327)
- class: `SpladeEncodeOptions` (line 338)
- class: `SpladeBuildOptions` (line 349)
- class: `SpladeIndexMetadata` (line 359)
- class: `_ShardState` (line 374)
- class: `_ExportContext` (line 390)
- function: `_require_sparse_encoder` (line 401)
- function: `_require_export_helpers` (line 411)
- function: `_write_struct` (line 424)
- function: `_directory_size` (line 432)
- function: `_detect_pyserini_version` (line 460)
- function: `_serialize_relative` (line 469)
- function: `_percentile_value` (line 476)
- function: `_quantize_tokens` (line 517)
- function: `_iter_corpus` (line 528)
- function: `_open_writer` (line 537)
- function: `_flush_batch` (line 567)
- function: `_persist_encoding_metadata` (line 633)
- function: `_encode_records` (line 699)
- function: `_optimize_export` (line 771)
- function: `_quantize_export` (line 821)
- function: `_persist_export_metadata` (line 887)
- class: `SpladeArtifactsManager` (line 937)
- class: `SpladeEncoderService` (line 1022)
- class: `SpladeIndexManager` (line 1303)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 3
- **cycle_group**: 54

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 14
- recent churn 90: 14

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

## Raises

NotImplementedError

## Complexity

- branches: 75
- cyclomatic: 76
- loc: 1453

## Doc Coverage

- `_SparseEncoderProtocol` (class): summary=yes, examples=no — Protocol defining the interface for SPLADE sparse encoders.
- `_OptimizerKwargs` (class): summary=no, examples=no
- `_OptimizerFunction` (class): summary=no, examples=no
- `_QuantizerKwargs` (class): summary=no, examples=no
- `_QuantizerFunction` (class): summary=no, examples=no
- `SpladeArtifactMetadata` (class): summary=yes, examples=no — Metadata describing exported SPLADE ONNX artifacts.
- `SpladeExportSummary` (class): summary=yes, examples=no — Summary returned after exporting SPLADE artifacts.
- `SpladeEncodingMetadata` (class): summary=yes, examples=no — Metadata describing SPLADE vector encoding runs.
- `SpladeEncodingSummary` (class): summary=yes, examples=no — Summary describing SPLADE encoding output.
- `SpladeBenchmarkOptions` (class): summary=yes, examples=no — Options controlling SPLADE encoder latency benchmarks.

## Tags

low-coverage, public-api, reexport-hub
