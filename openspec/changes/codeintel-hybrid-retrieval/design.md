## Design

### Summary

The goal is to extend CodeIntel with a first-class hybrid retrieval stack that pairs BM25, SPLADE v3,
and FAISS. We will operationalize the community playbook for BM25 + SPLADE v3 by adapting it to the
`codeintel_rev` architecture, ensuring that every capability is backed by configuration, metrics,
tests, and documentation.

### Current state

- Dense semantic search (FAISS + vLLM embeddings) is the only production-quality retrieval path.
- `PathsConfig` exposes `lucene_dir` and `splade_dir`, but there is no tooling for building or
  serving sparse indexes.
- Hybrid retrieval exists conceptually (`IndexConfig.rrf_k`) but FAISS remains the sole source.

### Goals

1. Deliver repeatable BM25 indexing flows (prepare → index → validate) managed inside `codeintel_rev`.
2. Provide SPLADE v3 setup, training, encoding, and indexing pathways for both GPU and CPU
   environments.
3. Expose production-ready hybrid search that fuses BM25, SPLADE, and FAISS via Reciprocal Rank
   Fusion (RRF).
4. Ship runbooks, observability, and docs so operations teams can maintain the new stack long term.

### Phased implementation

#### Phase 0 – Baseline alignment

- Audit dependencies: pin Pyserini (≥1.3.0), ensure Sentence-Transformers covers sparse support while
  remaining compatible with the existing Transformers constraint, and bump ONNX Runtime (≥1.18.0).
  Document the Java 21 requirement for Pyserini and Hugging Face authentication for SPLADE artifacts.
- Extend settings with dedicated BM25 and SPLADE sections to capture paths, model IDs, and runtime
  knobs.
- Record this plan in `openspec` and produce a design note summarizing the hybrid retrieval roadmap.

#### Phase 1 – BM25 setup & maintenance

1. **Index data model & storage**
   - Normalize corpus ingestion into a JSONL format managed under `codeintel_rev/io/corpora/`.
   - Implement `BM25IndexManager` to transform JSONL → Pyserini JsonCollection and to build Lucene
     indexes with metadata (version, corpus digest, build timestamp).
   - Store index metadata alongside the Lucene index directory to support drift detection.

2. **CLI integration**
   - Introduce `codeintel_rev/cli/bm25.py` with Typer commands for prepare/index/rebuild/validate.
   - Connect the CLI into the existing `tools/_shared/cli_runtime.py`.

3. **Configuration**
   - Surface BM25 paths, k1/b defaults, reindex cadence, and threading controls through settings.

4. **Observability & logging**
   - Instrument long-running commands with `observe_duration` and structured logs that record corpus
     size, index size, and elapsed time. Publish BM25 metrics under a dedicated namespace.

5. **Testing**
   - Build a toy corpus fixture and assert that BM25 search returns expected document hits.
   - Add a CLI smoke test that exercises prepare + index against the fixture.

6. **Documentation**
   - Author `docs/architecture/bm25.md` describing the pipeline, maintenance operations, and disk
     layout.
   - Provide an ops checklist for reindexing, validation (optionally using `pyserini.eval.trec_eval`),
     and on-call remediation.

#### Phase 2 – SPLADE v3 setup & maintenance

1. **Artifact management**
   - Create `SPLADEArtifactsManager` to download gated checkpoints, export ONNX artifacts (optimize +
     quantize), and track versions and compatibility metadata.

2. **Encoding pathways**
   - Implement `SpladeEncoderService` (PyTorch backend) with GPU/CPU autodetection and chunked
     encoding.
   - Provide `SpladeONNXEncoderService` leveraging `SparseEncoder(..., backend="onnx")`, with
     provider selection and a micro-benchmark command to capture p50/p95 query latency.

3. **Training & finetuning**
   - Offer a `splade train` CLI that wraps `SparseEncoderTrainer` for GPU or CPU training.
   - Document how to invoke the Naver Hydra pipeline when teams need the upstream flow.
   - Persist training metadata (hyperparameters, dataset hash, output artifact IDs).

4. **Index management**
   - Build `SpladeIndexManager` mirroring the BM25 manager: encode corpus → JsonVectorCollection →
     Lucene impact index, manage incremental shards, and record quantization/max clause settings.

5. **CLI integration**
   - Expand the CLI with `splade export`, `splade encode`, `splade index`, `splade train`, and
     `splade bench` commands, adapting the provided playbook.
   - Offer a convenience Makefile/`uv` workflow for quick start scenarios.

6. **Observability & testing**
   - Track encoding throughput, index sizes, and ONNX latency histograms.
   - Gate GPU-specific tests with `HAS_GPU_STACK` and `HAS_FAISS_SUPPORT`.
   - Add an end-to-end fixture that encodes a toy corpus, builds an impact index, and runs a SPLADE
     search (skipping when prerequisites are absent).

7. **Documentation**
   - Produce `docs/architecture/splade.md` covering training options, encoding pipelines, ONNX
     guidance, and the CPU/GPU decision matrix.
   - Mirror the appendix material from the playbook (licensing, query expansion limits, performance
     tips).

#### Phase 3 – Hybrid BM25 + SPLADE + FAISS search

1. **Search providers**
   - Implement `BM25SearchProvider` and `SpladeSearchProvider` abstractions that encapsulate Pyserini
     query execution and runtime caching of searchers/encoders.
   - Introduce a `HybridFusionEngine` (RRF-based) that fuses results across FAISS, BM25, and SPLADE
     with configurable weights and per-channel limits.

2. **Result composition**
   - Decide how to reconcile doc-level sparse hits with FAISS chunk-level hits: either augment the
     response envelope with doc-level entries or map doc IDs to chunk metadata via DuckDB.
   - Add configuration toggles to enable/disable each channel and to override fusion parameters.

3. **API schema updates**
   - Extend `AnswerEnvelope` (and client models) to include per-channel metadata, scores, and index
     versions.

4. **Observability**
   - Measure channel latencies, fusion latency, and the distribution of hits per channel.
   - Log structured events with index versions and fallback indicators.

5. **Testing**
   - Provide deterministic fusion tests for common scenarios (disjoint hits, overlapping hits).
   - Add integration tests that run queries against fixture indexes to confirm hybrid output ordering.

6. **Deployment considerations**
   - Ensure runtime validation verifies that Java 21 is present (for Pyserini) and that BM25/SPLADE
     indexes are readable.
   - Update readiness checks to confirm the presence and freshness of sparse indexes.

#### Phase 4 – Operations, maintenance, and documentation

1. **Operational runbooks**
   - Define reindex cadence, disk cleanup, and rollback strategies for both BM25 and SPLADE indexes.
   - Document incremental update workflows (delta encode + merge) and failure-handling procedures.

2. **Configuration & secrets**
   - Catalog required environment variables (HF token, Java path, index directories) and ship sample
     `.env` templates.

3. **Automation**
   - Optionally add CI smoke tests that build miniature indexes, guarded behind environment flags.
   - Provide scripts for scheduled reindex + evaluation pipelines, publishing metrics to the
     observability stack.

4. **Observability dashboards**
   - Extend dashboards with sparse index versions, build durations, inference latency, and per-channel
     success rates.

5. **Documentation**
   - Merge the appendix material from the provided playbook into official documentation and highlight
     licensing requirements for `naver/splade-v3`.

### Open questions

1. **Doc vs. chunk results** – Should sparse retrieval return doc-level hits alongside FAISS chunk
   hits, or should we project sparse hits onto chunks via metadata joins?
2. **Compute constraints** – Do we guarantee GPU availability for encoding/training, or must the ONNX
   CPU path be first-class for production?
3. **Index hosting** – Where do large Lucene indexes live in production (persistent volume, object
   storage, or artifact registry)?
4. **Quality gates** – What evaluation metrics (e.g., NDCG@10) must a new index meet before promotion?
5. **Licensing** – Confirm that the `naver/splade-v3` licensing terms align with our deployment model.

### Next steps

- Socialize this design with search stakeholders for approval.
- Finalize the document-vs-chunk fusion strategy.
- Kick off Phase 0 tasks (dependency updates, settings scaffolding, documentation refresh).

