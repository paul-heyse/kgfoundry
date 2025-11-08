% SPLADE Pipeline Architecture

# Overview

SPLADE provides learned sparse retrieval that complements our dense FAISS
pipeline. The implementation centers on three responsibilities:

- **Artifact management** for exporting, optimizing, and quantizing SPLADE
  checkpoints (`SpladeArtifactsManager`).
- **Corpus encoding** that emits Pyserini-compatible
  `JsonVectorCollection` shards (`SpladeEncoderService`).
- **Lucene impact index builds** using Pyserini's `JsonVectorCollection`
  recipe (`SpladeIndexManager`).

All logic lives under `codeintel_rev.io.splade_manager` and is surfaced through
CLI commands so operators can run the full pipeline without editing Python.

# Artifact management

`SpladeArtifactsManager.export_onnx` wraps the Sentence-Transformers ONNX export
APIs:

- Loads the configured checkpoint (default `naver/splade-v3`).
- Runs graph optimization (O3) when enabled.
- Applies dynamic quantization and records the preset (AVX2, AVX512, etc.).
- Persists metadata (`artifacts.json`) with the generator, timestamp, and file
  names for downstream validation.

Artifacts land under `models/splade-v3/onnx/`, matching the defaults in
`SPLADE_ONNX_DIR` and `SPLADE_ONNX_FILE`.

# Encoding pipeline

`SpladeEncoderService.encode_corpus` prepares a corpus for impact indexing:

1. Loads the quantized ONNX file (falling back to the default name if a custom
   file is not provided).
2. Streams the JSONL corpus, validating that each row includes an `id` and text.
3. Batches documents, runs `SparseEncoder.encode_document`, and decodes token
   impacts.
4. Quantizes the floating-point weights using the configured factor
   (`SPLADE_QUANTIZATION`) and writes JsonVectorCollection shards (rotation via
   `shard_size`).
5. Captures metadata (`vectors_metadata.json`) with document counts, shard
   counts, quantization, and provenance paths.

The metadata file drives downstream automation (nightly rebuild comparisons,
healthy ingest checks, etc.).

# Impact index builds

`SpladeIndexManager.build_index` shells out to Pyserini:

- Accepts overrides for vectors directory, index directory, thread count, and
  Lucene clause limit.
- Sets `JAVA_TOOL_OPTIONS` so `org.apache.lucene.maxClauseCount` matches our
  configuration.
- Calls `pyserini.index.lucene` with `--impact --pretokenized --optimize`.
- Writes `metadata.json` under the index directory (doc count, Pyserini
  version, index size, source vectors digest).

All subprocess execution flows through `kgfoundry_common.subprocess_utils`, so
timeouts, error handling, and structured logging mirror the rest of the
codebase.

# CLI workflow

The `codeintel` console script exposes the maintenance operations:

```console
# Export optimized and quantized ONNX artifacts
codeintel splade export-onnx --quantization-config avx512

# Encode corpus JSONL into JsonVectorCollection shards
codeintel splade encode data/corpus.jsonl --batch-size 16

# Build the Lucene impact index
codeintel splade build-index --vectors-dir data/splade_vectors

# Benchmark SPLADE ONNX latency using one or more queries
codeintel splade bench --query "solar incentives" --runs 25 --warmup 5
```

Each command writes an envelope under `docs/_data/cli/splade/` with the
arguments, environment, duration, and metadata file digests. That envelope is
the source of truth for automation (nightly rebuilds, dashboard updates) and
ensures reproducibility.

The `bench` command measures query encoding latency via ONNX Runtime. Pass
`--query` for a single string or `--queries-file path/to/queries.txt` (one query
per line) to benchmark batch scenarios. Results capture p50/p95/p99, min/max,
and mean latency so operators can detect regressions after model upgrades.

# Hybrid search integration

The `HybridSearchEngine` (see `codeintel_rev/io/hybrid_search.py`) fuses SPLADE
signals with BM25 and FAISS results using Reciprocal Rank Fusion (RRF). Query
execution flow:

1. Semantic adapter obtains dense hits from FAISS.
2. Hybrid engine lazily loads Pyserini searchers (`BM25SearchProvider`,
   `SpladeSearchProvider`) and gathers per-channel candidates
   (`HYBRID_TOP_K_PER_CHANNEL`).
3. RRF merges the three channels, producing fused chunk IDs and contribution
   metadata (channel, rank, raw score).
4. The adapter hydrates chunk metadata via DuckDB and annotates `Finding.why`
   with a hybrid explanation (e.g., `Hybrid RRF (k=60): semantic rank=1, bm25 rank=2`).

Operators can toggle channels with `HYBRID_ENABLE_BM25` / `HYBRID_ENABLE_SPLADE`.
When disabled, the engine bypasses the associated provider and the adapter falls
back to dense-only semantics without additional latency.

# Observability

- Structured logs emit operation names (`splade_export_onnx`,
  `splade_encode_corpus`, `splade_build_index`) with doc counts and output
  paths.
- Metadata files capture doc counts, quantization factors, and Pyserini versions
  so dashboards can track drift across rebuilds.
- All file writes go through `resolve_within_repo`, preventing path traversal.

# Next steps

- Integrate encoding/index metrics into the shared observability helpers so
  dashboards can surface durations and throughput.
- Extend the CLI with SPLADE finetuning helpers for on-premise retraining.
- Wire nightly automation to run `codeintel splade encode` +
  `codeintel splade build-index` on fixture corpora, publishing metadata diffs.

