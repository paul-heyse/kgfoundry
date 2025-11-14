## Unreleased

### Added

- Truth-preserving semantic rerank that hydrates embeddings from DuckDB,
  applies exact similarity, and records ANN/refine latency histograms.
- Automatic tuning profiles stored as `tuning.json` beside `faiss.index`,
  plus CLI helpers (`indexctl tune --quick/--full`, `indexctl show-profile`).
- Per-query pool schema now records channel explanations and ships DuckDB
  views (`v_faiss_pool`, `v_pool_coverage`) for coverage heatmaps.
- Lifecycle manager stages `faiss_idmap.parquet` + `tuning.json`, and the new
  operator runbook + SQL examples document the full workflow.
- Enrichment pipeline hardening: stage-scoped logging/metrics, `ModuleRecord`
  dataclass with structured error capture, per-stage unit tests, repo map tag
  counts, `docs/enrich_pipeline.md` describing the CLI workflow, DuckDB ingestion
  (`codeintel-enrich to-duckdb`) with schema validation, and new tests covering the
  LibCST/SCIP/tagging/writer stages.
