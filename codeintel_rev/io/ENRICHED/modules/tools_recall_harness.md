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
- from **pathlib** import Path
- from **typing** import Iterable, Mapping, Sequence
- from **(absolute)** import re
- from **importlib** import import_module
- from **(absolute)** import math

## Definitions

- function: `_read_jsonl` (line 40)
- function: `_read_qrels` (line 51)
- class: `RM3Params` (line 64)
- class: `RM3Heuristics` (line 70)
- function: `_lucene_searcher` (line 90)
- function: `_apply_rm3` (line 102)
- function: `_recall_at_k` (line 113)
- function: `_mrr_at_k` (line 124)
- function: `_parse_rm3_list` (line 140)
- function: `_write_run` (line 152)
- function: `sweep` (line 159)
- function: `main` (line 222)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 1
- **cycle_group**: 132

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 3
- recent churn 90: 3

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: High-recall harness for BM25 + RM3 and (optionally) SPLADE.
- has summary: yes
- param parity: no
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
- patches/Supporting Documentation/libcst.md
- patches/Supporting Documentation/tree-sitter.md
- patches/Supporting Documentation/251111_FAISS_whl_overview_rev.md
- patches/Supporting Documentation/pyrarrow.md
- patches/Supporting Documentation/duckdb.md
- patches/AST_CST_SCIP_data_pipeline_hardening.md
- patches/CST_Data_Build.md
- patches/Typing_gating_follow_small_architecture_changes.md
- patches/FAISS_detailed_implementation_plan.md
- patches/Enrich_Expansion.md
- patches/Enrich_Extension.md
- patches/Networking_Implementation.md
- patches/Type_Gating_Factory_Scope_phase2.md
- patches/BM25+SPLADEv3_Implementation.md
- patches/Type_Gating_Factory_Scope.md
- patches/DuckDB_data_expansion_FAISS.md
- patches/Type_Gating_Followup.md
- patches/AST_Data_Build.md
- patches/audit_closeout.md
- patches/Index Lifecycle Manager and Concurrency.md
- patches/FAISS Implementation Phase 2 rev.md
- patches/warp_technical_overview.md
- patches/Telemetry_Implementation.md
- patches/Enrich_scope_addendum.md
- patches/FAISS-Phase2-Refinements.md
- patches/Enrich_Scope.md
- patches/Runtime_Cells_Followup_Scope.md
- patches/FAISS-Implementation-Stage2.md

## Hotspot

- score: 1.97

## Side Effects

- filesystem

## Complexity

- branches: 44
- cyclomatic: 45
- loc: 258

## Doc Coverage

- `_read_jsonl` (function): summary=no, examples=no
- `_read_qrels` (function): summary=no, examples=no
- `RM3Params` (class): summary=no, examples=no
- `RM3Heuristics` (class): summary=yes, examples=no — Copy of the production heuristic (kept self-contained here).
- `_lucene_searcher` (function): summary=no, examples=no
- `_apply_rm3` (function): summary=no, examples=no
- `_recall_at_k` (function): summary=no, examples=no
- `_mrr_at_k` (function): summary=no, examples=no
- `_parse_rm3_list` (function): summary=no, examples=no
- `_write_run` (function): summary=no, examples=no

## Tags

low-coverage
