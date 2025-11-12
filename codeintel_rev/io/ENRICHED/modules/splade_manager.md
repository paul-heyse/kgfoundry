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
- function: `encode_document` (line 53)
- function: `encode_query` (line 86)
- function: `decode` (line 117)
- function: `save_pretrained` (line 161)
- class: `_OptimizerFunction` (line 190)
- function: `__call__` (line 191)
- class: `_QuantizerFunction` (line 201)
- function: `__call__` (line 202)
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
- function: `__init__` (line 924)
- function: `model_dir` (line 931)
- function: `onnx_dir` (line 942)
- function: `export_onnx` (line 952)
- class: `SpladeEncoderService` (line 1006)
- function: `__init__` (line 1009)
- function: `vectors_dir` (line 1016)
- function: `_resolve_vectors_dir` (line 1026)
- function: `_initialise_encoder` (line 1056)
- function: `_build_encoder` (line 1124)
- function: `encode_corpus` (line 1128)
- function: `benchmark_queries` (line 1201)
- class: `SpladeIndexManager` (line 1287)
- function: `__init__` (line 1290)
- function: `vectors_dir` (line 1297)
- function: `index_dir` (line 1308)
- function: `build_index` (line 1318)

## Tags

overlay-needed, public-api, reexport-hub
