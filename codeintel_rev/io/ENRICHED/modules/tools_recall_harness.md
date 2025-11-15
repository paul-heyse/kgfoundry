# patches/Supporting Documentation/BM25+SPLADEv3-patchfiles/tools_recall_harness.py

## Docstring

```
High-recall harness for BM25 + RM3 and (optionally) SPLADE.

This script evaluates Recall@K over a query set while sweeping BM25 (k1, b)
and RM3 configurations. It also supports an *auto* mode that applies the same
RM3 heuristics used in production to validate toggle decisions.

Usage
-----
python tools/recall_harness.py +  --bm25-index ~/indexes/bm25 +  --queries data/queries.jsonl +  --qrels data/qrels.tsv +  --k 10 +  --sweep-k1 0.6,0.9,1.2 +  --sweep-b 0.2,0.4,0.75 +  --rm3 off,10-10-0.5,20-10-0.5 +  --auto-rm3 true +  --outdir runs/2025-11-11

Input formats
-------------
* queries.jsonl: one JSON per line: {"qid": "...", "text": "..."}
* qrels.tsv: TREC qrels TSV: qid <tab> docid <tab> rel (rel>0 = relevant)

Outputs
-------
* summary.json        : per-configuration Recall@K, MRR@K (optional), decisions
* decisions.csv       : per-query RM3 decisions in auto mode (enable/disable)
* runs/*.tsv          : simple runs for debugging

Notes
-----
* Requires Pyserini for BM25/RM3. SPLADE evaluation is optional (provide
  --splade-index and --splade-encoder to enable; used for hybrid oracle).
* Designed to be run in CI/nightly as a regression guard.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import argparse
- from **(absolute)** import csv
- from **(absolute)** import dataclasses
- from **(absolute)** import json
- from **collections.abc** import Iterable, Mapping
- from **pathlib** import Path
- from **(absolute)** import re
- from **importlib** import import_module
- from **(absolute)** import math

## Definitions

- function: `_read_jsonl` (line 41)
- function: `_read_qrels` (line 52)
- class: `RM3Params` (line 65)
- class: `RM3Heuristics` (line 101)
- function: `_lucene_searcher` (line 156)
- function: `_apply_rm3` (line 168)
- function: `_recall_at_k` (line 179)
- function: `_mrr_at_k` (line 190)
- function: `_parse_rm3_list` (line 206)
- function: `_write_run` (line 218)
- function: `sweep` (line 225)
- function: `main` (line 362)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 0
- **cycle_group**: 162

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: High-recall harness for BM25 + RM3 and (optionally) SPLADE.
- has summary: yes
- param parity: yes
- examples present: no

## Typedness

- params annotated: 0.96
- returns annotated: 0.90
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Config References

- patches/Supporting Documentation/BM25+SPLADEv3-patchfiles/grafana_codeintel_retrieval.json
- patches/Supporting Documentation/BM25+SPLADEv3-patchfiles/grafana-codeintel-retrieval.json
- patches/Supporting Documentation/faiss_1_12_0_api_inventory.json
- patches/Supporting Documentation/FastAPI.md
- patches/Supporting Documentation/opentelemetry.md
- patches/Supporting Documentation/libcst.md
- patches/Supporting Documentation/vllm.md
- patches/Supporting Documentation/tree-sitter.md
- patches/Supporting Documentation/251111_FAISS_whl_overview_rev.md
- patches/Supporting Documentation/pyrarrow.md
- patches/Supporting Documentation/duckdb.md
- patches/Supporting Documentation/HyperCorn.md
- patches/Supporting Documentation/nginx.md
- patches/AST_CST_SCIP_data_pipeline_hardening.md
- patches/OpenTelemetry_ExtensionPhase2.md
- patches/CST_Data_Build.md
- patches/SCIP+CST+AST pipeline hardening.md
- patches/MCP_through_search_hardening_phase3.md
- patches/OpenTelemetry_ExtensionPhase4.md
- patches/Typing_gating_follow_small_architecture_changes.md
- patches/FAISS_detailed_implementation_plan.md
- patches/Enrich_Expansion.md
- patches/OpenTelemetry_ExtensionPhase2addon.md
- patches/OpenTelemetry_Reconfig_for_efficient_libraries_phase2.md
- patches/Front_End_Hardening_Phase2.md
- patches/Enrich_Extension.md
- patches/Startup - Chunking through Embedding and Storage.md
- patches/Telemetry_Execution_Ledger.md
- patches/Networking_Implementation.md
- patches/FAISS-Hardening.md
- patches/Type_Gating_Factory_Scope_phase2.md
- patches/BM25+SPLADEv3_Implementation.md
- patches/OpenTelemetry_ExtensionPhase1.md
- patches/Type_Gating_Factory_Scope.md
- patches/MCP_through_search_hardening_phase2.md
- patches/DuckDB_data_expansion_FAISS.md
- patches/Type_Gating_Followup.md
- patches/OpenTelemetry_Reconfig_for_efficient_libraries.md
- patches/Cli_enrich_fix.md
- patches/AST_Data_Build.md
- patches/audit_closeout.md
- patches/MCP_through_search_hardening.md
- patches/Index Lifecycle Manager and Concurrency.md
- patches/MCP_schema_implementation.md
- patches/OpenTelemetry_ExtensionPhase0.md
- patches/FAISS Implementation Phase 2 rev.md
- patches/warp_technical_overview.md
- patches/OpenTelemetry_ExtensionPhase3.md
- patches/Telemetry_Implementation.md
- patches/vllm scope.md
- patches/Enrich_scope_addendum.md
- patches/FAISS-Phase2-Refinements.md
- patches/SCIP+CST+AST pipeline hardening_phase2.md
- patches/Front_End_Hardening_Phase1.md
- patches/Enrich_Scope.md
- patches/Runtime_Cells_Followup_Scope.md
- patches/FAISS-Implementation-Stage2.md

## Hotspot

- score: 1.70

## Side Effects

- filesystem

## Complexity

- branches: 44
- cyclomatic: 45
- loc: 427

## Doc Coverage

- `_read_jsonl` (function): summary=no, examples=no
- `_read_qrels` (function): summary=no, examples=no
- `RM3Params` (class): summary=yes, examples=no — Parameters for RM3 (Relevance Model 3) query expansion.
- `RM3Heuristics` (class): summary=yes, examples=no — Copy of the production heuristic (kept self-contained here).
- `_lucene_searcher` (function): summary=no, examples=no
- `_apply_rm3` (function): summary=no, examples=no
- `_recall_at_k` (function): summary=no, examples=no
- `_mrr_at_k` (function): summary=no, examples=no
- `_parse_rm3_list` (function): summary=no, examples=no
- `_write_run` (function): summary=no, examples=no

## Tags

low-coverage
