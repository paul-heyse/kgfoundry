## Implementation Plan Overview

Our objective is to bring the end-to-end BM25 + SPLADE v3 playbook into the `codeintel_rev` platform so that we can build, maintain, and serve:

- classic BM25 indexes (Pyserini/Lucene),
- SPLADE v3 learned-sparse indexes with both GPU- and CPU-oriented training/encoding pathways,
- a production hybrid retrieval surface that fuses BM25, SPLADE, and our existing FAISS dense search.

We will implement this in phases so that each capability is production-ready (configuration, observability, tests, docs) before moving to the next.

---

## Phase 0 – Baseline Alignment

- **Code review:** confirm current state of `codeintel_rev` search stack (`FAISSManager`, DuckDB hydration, Pyserini dependencies, existing search API).
- **Dependency gap check:** update `pyproject.toml` / `uv.lock` to ensure Pyserini ≥ 1.3.0, Sentence-Transformers ≥ 5.1 (ONNX extras), ONNX Runtime, Java availability (document requirement).
- **Configuration scaffolding:** extend `codeintel_rev.config.settings` and related env var docs so BM25/SPLADE artifacts (paths, knobs) fit our standard settings object.

_Output:_ dependency diff, settings schema update, short design note referencing the end-to-end playbook.

---

## Phase 1 – BM25 Setup & Maintenance

1. **Index data model & storage**
   - Standardize corpus JSONL format (`{id, contents}`) under `codeintel_rev/io/corpora`.
   - Create `BM25IndexManager` (under `codeintel_rev/io`) providing:
     - `prepare_corpus()` (JSONL → Pyserini JsonCollection),
     - `build_index()` wrappers around `pyserini.index.lucene`,
     - incremental rebuild/merge helpers, index validation, metadata (version, build timestamp).
   - Persist index metadata under `indexes/bm25/metadata.json`.

2. **CLI integration**
   - Add `codeintel_rev/cli/bm25.py` (typer-based) exposing prepare/index/rebuild/validate commands.
   - Hook into existing CLI runner (`tools/_shared/cli_runtime.py`).

3. **Configuration**
   - Settings for BM25 index paths, k1/b defaults per environment, re-index schedule, optional turbo `threads`.

4. **Observability & logging**
   - Instrument build/rebuild commands with `observe_duration`, structured logs (index size, doc counts, corpus digest). Add metrics to `codeintel_rev/io/bm25_metrics.py`.

5. **Testing**
   - Unit tests: build BM25 against toy corpus (fixtures), ensure search returns expected doc IDs.
   - Integration smoke test: run CLI prepare/index on fixture corpus.

6. **Documentation**
   - `docs/architecture/bm25.md` (pipeline, maintenance checklist, disk layout).
   - Ops playbook: reindex instructions, validation steps (pyserini eval optional).

---

## Phase 2 – SPLADE v3 Setup & Maintenance

### 2A – Artifact management

- Create `SPLADEArtifactsManager` responsible for:
  - Downloading base HF checkpoint (with license guard),
  - Exporting ONNX artifacts (optimize/quantize) via Sentence-Transformers helpers,
  - Tracking versions and storing under `models/splade-v3/{onnx,...}` with metadata (quant scheme, provider compatibility).

### 2B – Encoding pathways

1. **GPU/CPU PyTorch encoding**
   - `SpladeEncoderService` (PyTorch backend) that batches doc/query encoding, with `device` autodetection and configurable batch/chunk size (for CPU memory control).
   - Provide incremental encoding (doc ID list) → JSON vector shards.

2. **ONNX / CPU pathway**
   - `SpladeONNXEncoderService` using `SparseEncoder(..., backend="onnx")` with dynamic quant artifacts.
   - Support provider selection (`CPUExecutionProvider`, optional GPU provider).
   - Add micro-benchmark command (`cli splade bench`) capturing P50/P95 latencies.

3. **Training/finetuning**
   - Two surfaces:
     - `splade train` CLI wrapper around Sentence-Transformers `SparseEncoderTrainer` (GPU optional). 
     - Document orchestration for Naver Hydra path (link to instructions, optional script to invoke remote training).
   - Write training output metadata (hyperparams, dataset digest).

### 2C – SPLADE index management

- `SpladeIndexManager` (mirroring BM25 manager):
  - Encode corpus → JsonVectorCollection shards,
  - Build Lucene impact index (`--impact --pretokenized`),
  - Manage incremental shards + reindex pipeline (swap new shards, track incremental doc IDs),
  - Provide hybrid metadata (quant factor, max clause count adjustments).

### 2D – CLI integration

- Extend CLI with subcommands (`splade export`, `encode`, `index`, `train`, `bench`) referencing playbook steps.
- Provide `Makefile`/`uv` tasks for quick start (adapting the provided makefile).

### 2E – Observability & testing

- Metrics: encoding throughput, index sizes, ONNX inference latency (histograms).
- Tests:
  - Unit tests mocking Pyserini to ensure JSON vector generation and indexing command building.
  - GPU-optional tests behind `HAS_FAISS_SUPPORT`/`HAS_GPU_STACK` gating.
  - End-to-end fixture: encode small corpus, build index, run Splade search (skipped if FAISS/Pyserini missing).

### 2F – Documentation

- `docs/architecture/splade.md`: training options, encoding pipeline, ONNX guidance, maintenance schedule.
- Appendix summarizing CPU vs GPU guidance (mirroring instructions).
- License warning surfaces (non-commercial usage note).

---

## Phase 3 – Hybrid BM25 + SPLADE + FAISS Search

### 3A – Search API architecture

- Extend `search_api` (or `codeintel_rev/mcp_server/adapters/semantic.py`) to support multi-channel retrieval:

  1. **BM25SearchProvider**
     - wraps Pyserini `LuceneSearcher`, uses settings to tune k1/b,
     - exposes `search(query, k)` returning doc IDs + scores.

  2. **SpladeSearchProvider**
     - handles query encoding (PyTorch or ONNX) and `LuceneImpactSearcher`,
     - configurable quant/max_terms,
     - caches query encoder (per provider) to avoid re-instantiation.

  3. **HybridFusionEngine**
     - Implements Reciprocal Rank Fusion (k configurable).
     - Accepts optional weights.

  4. **Existing FAISS path**
     - Already returns chunk IDs; need mapping between doc IDs (BM25/SPLADE) and chunk-level results. Two options:
       - Use DuckDB to map doc IDs to chunk IDs (embedding metadata).
       - Or treat BM25/SPLADE as separate doc-level channel, merge at result composition stage.

### 3B – Integration with FAISS Densely search

- Decide final response composition: combine FAISS chunk-level results with BM25/SPLADE doc-level hits:
  - Option 1: treat BM25/SPLADE as doc-level "snippets" appended to FAISS findings.
  - Option 2: precompute chunk→doc mapping and convert doc hits to chunk hits (requires index metadata).
- Provide configuration to enable/disable each channel and adjust scoring weights.

### 3C – API changes

- Extend `AnswerEnvelope` schema to include BM25/SPLADE metadata (scores, sources).
- Add new settings: `hybrid.enable_bm25`, `hybrid.enable_splade`, `hybrid.rrf_k`, `hybrid.top_k_per_channel`.

### 3D – Observability

- Record per-channel durations (BM25 search, SPLADE query encode + search, fusion).
- Surface metrics: hits count per channel, hybrid coverage, fallback usage, index version info.

### 3E – Testing

- Unit tests for fusion engine (RRF).
- Integration tests:
  - Build minimal BM25 + SPLADE indexes (fixture) and run hybrid search; verify outputs.
  - Validate configuration toggles (only FAISS, only BM25, etc.).
- Add regression tests ensuring hybrid search respects filters (scope filters, globs) similar to FAISS path.

### 3F – Deployment considerations

- Ensure runtime process handles Java dependency (`JAVA_HOME` requirement). Document in deployment pipeline.
- Provide health/readiness checks verifying presence of BM25/SPLADE artifacts and matching metadata versions.

---

## Phase 4 – Ops, Maintenance, & Docs

1. **Operational Runbooks**
   - Rebuild cadence (BM25, SPLADE), log retention, disk cleanup.
   - Incremental update workflow (delta corpora, re-encoding, index merge).
   - Fallback/rollback instructions (swap index directories, revert metadata).
   - Training pipeline documentation (when to re-train SPLADE, hyperparameter recordkeeping).

2. **Configuration & Secrets**
   - Document env vars controlling model IDs, license acceptance (HF token), Java path.
   - Provide sample `.env` for hybrid setup.

3. **CI & Automation**
   - Add optional CI jobs to smoke-test index build on tiny corpus (gated behind env).
   - Provide manual pipeline script for nightly re-index plus evaluation (trec_eval) posting results to observability (optional).

4. **Observability dashboards**
   - Add logs/metrics to Grafana dashboards (index versions, build durations, search latency per channel, success rate).
   - Ensure `observe_duration` instrumentation consistent.

5. **Docs & Knowledge Base**
   - Merge `bm25+spladev3_instructions+background.md` content into official docs, referencing original appendix for in-depth material.
   - Provide quickstart tutorials (CPU-only path, GPU-enabled path, ONNX path).
   - Include license notice prominently.

---

## Deliverables & Milestones Summary

| Milestone | Key Deliverables |
|-----------|------------------|
| M0 | Dependency alignment PR, settings schema updates, design note referencing provided playbook. |
| M1 | `BM25IndexManager`, CLI commands, observability/test suite, bm25 docs. |
| M2 | SPLADE artifact manager, encoding services (PyTorch + ONNX), index manager, training CLI, metrics/tests/docs. |
| M3 | Hybrid search implementation (providers, fusion engine, API changes), integration tests, observability, config toggles. |
| M4 | Ops runbooks, dashboards, docs update (merged playbook), optional CI automation. |

---

## Key Open Questions (to resolve before implementation)

1. **Document vs chunk alignment** – do we map BM25/SPLADE doc hits to the chunk-level structure already used by FAISS, or surface doc-level results alongside chunk-level? Decision impacts data model and UI.
2. **Compute constraints** – GPU availability for training/encoding; if limited, we may prioritize ONNX/CPU path for production query encoding.
3. **Index storage** – where to host large Lucene indexes (S3, local disk, ephemeral mount). Need to reconcile with deployment pipeline.
4. **Evaluation thresholds** – define acceptance metrics (e.g., reindex must beat baseline NDCG@10) for build pipelines.
5. **License compliance** – confirm non-commercial usage or secure appropriate license for `naver/splade-v3`.

---

## Next Steps

- Socialize this plan with search stakeholders for validation.
- Decide on doc-level vs chunk-level result fusion approach.
- Once approved, schedule Phase 0 tasks and create parallel JIRA tickets per phase.

This plan reuses the detailed end-to-end instructions you provided, mapping them into our `codeintel_rev` architecture with the necessary operational, observability, and testing frameworks so the new retrieval stack is production-grade.