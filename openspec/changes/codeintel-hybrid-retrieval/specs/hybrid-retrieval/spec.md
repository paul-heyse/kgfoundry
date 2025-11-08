## Spec: Hybrid Retrieval Enablement

### Requirements

1. **BM25 toolchain**
   - Provide commands to prepare corpora, build indexes, validate success, and expose metadata.
   - Capture metrics (duration, corpus size, index size) and surface structured logs.

2. **SPLADE v3 toolchain**
   - Manage model exports (PyTorch → ONNX), encoding workflows, and impact index builds with both GPU
     and CPU execution paths.
   - Persist artifact metadata (model IDs, quantization config, provider compatibility).

3. **Hybrid search**
   - Support FAISS + BM25 + SPLADE RRF fusion with configurable per-channel fan-out, weights, and
     enablement flags.
   - Track latency per channel and emit observability data suitable for dashboards.

4. **Operations & documentation**
   - Deliver runbooks for reindexing, incremental updates, rollbacks, and evaluation checkpoints.
   - Update configuration documentation with new environment variables and prerequisites (Java 21,
     Hugging Face authentication).

### Acceptance

- All new code passes Ruff, Pyright, Pyrefly, and pytest (including optional sparse tests when
  dependencies are available).
- CI or manual workflows can build toy BM25 + SPLADE indexes end-to-end.
- Hybrid search endpoints expose combined results with documented response schema changes.
- Documentation and dashboards reflect the new retrieval stack and its maintenance workflows.

