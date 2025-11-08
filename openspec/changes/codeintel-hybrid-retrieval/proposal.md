## Proposal

### Why

Our current semantic search relies exclusively on FAISS dense retrieval. The
playbook provided for BM25 + SPLADE v3 demonstrates higher recall and enables
hybrid search deployments that fuse sparse and dense evidence. Adopting this
stack requires a structured migration that respects existing observability,
configuration, and quality gates.

### What

- Establish a supported BM25 indexing toolchain within `codeintel_rev`.
- Build SPLADE v3 artifact management, encoding, and impact indexing flows with
  GPU and CPU pathways.
- Integrate BM25 and SPLADE search providers alongside FAISS with configurable
  hybrid fusion.
- Deliver runbooks, metrics, docs, and CI hooks so the new retrieval stack is
  production ready.

