Hybrid Retrieval Operations Runbook
===================================

Overview
--------

This runbook captures the day-to-day operational workflow for keeping the hybrid
retrieval stack healthy. The stack combines three retrieval channels:

* **FAISS** – dense GPU/CPU search over chunk embeddings.
* **BM25** – classic lexical search built from JsonCollection corpora.
* **SPLADE v3** – learned sparse search using ONNX-exported Sentence-Transformers.

All operational tasks are driven by the *codeintel* CLI (`codeintel bm25 …`,
`codeintel splade …`) and the FAISS maintenance helpers in
``codeintel_rev.io.faiss_manager``. Each CLI command emits an envelope under
``docs/_data/cli`` with arguments, environment, duration, and artefact hashes.
Treat the envelope as the source of truth for audits and dashboards.

Daily / Nightly Maintenance
---------------------------

1. **Refresh corpora (optional)**

   .. code-block:: console

      codeintel bm25 prepare-corpus data/corpus.jsonl --output-dir data/jsonl

   *Validates JSONL schema, deduplicates IDs, records doc counts and SHA256
   digest in ``data/jsonl/metadata.json``.*

2. **Rebuild Lucene BM25 index**

   .. code-block:: console

      codeintel bm25 build-index --threads 12

   *Runs Pyserini ``JsonCollection`` → Lucene build. Metadata written to
   ``indexes/bm25/metadata.json`` plus CLI envelope.*

3. **Export / update SPLADE ONNX artefacts**

   .. code-block:: console

      codeintel splade export-onnx --quantization-config avx2

   *Persists ``models/splade-v3/onnx/artifacts.json`` describing optimisation and
   quantisation settings. Required if model weights or execution providers
   change.*

4. **Encode corpus into SPLADE vectors**

   .. code-block:: console

      codeintel splade encode data/corpus.jsonl --batch-size 32 --shard-size 50000

   *Produces JsonVectorCollection shards in ``data/splade_vectors`` and
   ``vectors_metadata.json`` summarising document counts, shard counts, and
   quantisation settings.*

5. **Build SPLADE impact index**

   .. code-block:: console

      codeintel splade build-index --threads 12 --max-clause-count 8192

   *Creates ``indexes/splade_v3_impact`` with Lucene impact postings and
   metadata (doc counts, index size, Pyserini version).*

6. **Verify FAISS metadata (optional)**

   .. code-block:: console

      python -m codeintel_rev.tools.faiss verify --index data/faiss/code.ivfpq.faiss

   *Ensures FAISS manifest is current and reports compaction thresholds.*

Incremental Updates
-------------------

When indexing delta corpora:

1. Run ``codeintel bm25 prepare-corpus`` against the delta JSONL.
2. Use ``codeintel splade encode`` with ``--output-dir`` pointing at a staging
   directory (do **not** clobber production vectors).
3. Run ``codeintel splade build-index --vectors-dir <staging> --index-dir <staging>``.
4. Validate metadata diff (doc counts, corpus digests).
5. Atomically swap directories (e.g., symlink switch or `mv` into place).
6. Trigger `ApplicationContext.get_hybrid_engine()` reload via application
   restart or management endpoint if available.

Observability
-------------

* CLI envelopes include ``duration_ms``, doc counts, shard counts, and index
  sizes. Ingest them into dashboards (e.g., Grafana via log forwarder).
* ``SpladeEncoderService`` and ``SpladeIndexManager`` log structured events with
  doc counts and metadata file paths. Forward to central logging.
* Semantic adapter appends hybrid warnings to the ``limits`` metadata list when
  BM25/SPLADE providers fail to initialise. Alert on repeated warnings.
* ``Finding["why"]`` now carries hybrid explanations (`Hybrid RRF …`) giving
  operators visibility into channel contributions for sampled queries.

Semantic Pro Budgets & Gating
-----------------------------

The semantic_pro adapter adds a GPU-centric CodeRank → WARP → reranker pipeline
with explicit latency budgets. Tune the following environment variables to
balance quality vs. responsiveness:

* ``CODERANK_TOP_K`` – Stage-A fanout before hybrid fusion (default 200).
* ``CODERANK_BUDGET_MS`` – Soft latency budget for the CodeRank embed + FAISS
  search span. If exceeded, Stage-B is skipped to keep tail latency bounded.
* ``CODERANK_MARGIN_THRESHOLD`` / ``CODERANK_MIN_STAGE2`` – Gate Stage-B when
  the CodeRank margin is already high or there are too few candidates.
* ``WARP_BUDGET_MS`` – Stage-B (WARP/XTR) budget. Exceeding the budget downgrades
  the response, emits a limit note, and records a metrics sample with status
  ``degraded``.
* ``CODERANK_LLM_BUDGET_MS`` – Stage-C (CodeRankLLM reranker) budget.
* ``RRF_WEIGHTS_JSON`` – Optional JSON map to override weighted-RRF channel
  weights (e.g., ``{"semantic": 1.0, "warp": 1.2}``).

Every stage exposes its measured duration via the response metadata and the
``kgfoundry_operation_duration_seconds`` Prometheus histogram (component:
``codeintel_mcp``, operation: stage name, status: ``success`` or ``degraded``).
Use these metrics to alert when gating skips Stage-B/C too frequently.

Rollback & Disaster Recovery
----------------------------

* Keep the previous generation of each artefact (BM25 index, SPLADE vectors,
  SPLADE index, FAISS manifest) on disk or in object storage.
* To roll back, flip symlinks/directories to the prior generation and restart
  the MCP service to flush cached searchers.
* If FAISS secondary index grows beyond the compaction threshold (configured via
  ``INDEX_COMPACTION_THRESHOLD``), schedule `FAISSDualIndexManager.merge_indexes`
  during a maintenance window to collapse secondary into primary.

Automation Hooks
----------------

* Add a nightly job (GitHub Actions / Jenkins) that:

  1. Checks out repository at HEAD.
  2. Runs the CLI sequence above against fixture corpora.
  3. Uploads CLI envelopes + metadata artefacts to object storage.
  4. Pushes summary metrics to dashboards (doc deltas, durations).

* Optionally post a summary message (doc counts, index versions) to the team
  Slack channel using the CLI envelope metadata.

Reference Paths
---------------

* BM25 corpus metadata: ``${BM25_JSONL_DIR}/metadata.json``
* BM25 index metadata: ``${BM25_INDEX_DIR}/metadata.json``
* SPLADE vector metadata: ``${SPLADE_VECTORS_DIR}/vectors_metadata.json``
* SPLADE index metadata: ``${SPLADE_INDEX_DIR}/metadata.json``
* CLI envelopes: ``docs/_data/cli/{bm25,splade}/<timestamp>.json``

Use these paths when triaging build drift, validating deployments, or wiring
automation.
