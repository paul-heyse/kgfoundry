# retrieval/gating.py

## Docstring

```
Adaptive gating helpers for multi-stage retrieval pipelines.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import re
- from **collections.abc** import Mapping
- from **dataclasses** import dataclass, field
- from **codeintel_rev.observability.otel** import record_span_event
- from **codeintel_rev.observability.timeline** import current_timeline
- from **codeintel_rev.retrieval.telemetry** import record_stage_decision
- from **codeintel_rev.retrieval.types** import StageDecision, StageSignals

## Definitions

- class: `StageGateConfig` (line 16)
- function: `should_run_secondary_stage` (line 65)
- class: `QueryProfile` (line 146)
- class: `BudgetDecision` (line 198)
- function: `_tokenize` (line 232)
- function: `_code_like_count` (line 236)
- function: `analyze_query` (line 245)
- function: `decide_budgets` (line 317)
- function: `describe_budget_decision` (line 371)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 4
- **cycle_group**: 61

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 7
- recent churn 90: 7

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

BudgetDecision, QueryProfile, StageGateConfig, analyze_query, decide_budgets, describe_budget_decision, should_run_secondary_stage

## Doc Health

- **summary**: Adaptive gating helpers for multi-stage retrieval pipelines.
- has summary: yes
- param parity: yes
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 2.35

## Side Effects

- none detected

## Complexity

- branches: 28
- cyclomatic: 29
- loc: 419

## Doc Coverage

- `StageGateConfig` (class): summary=yes, examples=no — Configuration inputs for deciding whether to invoke a follow-up stage.
- `should_run_secondary_stage` (function): summary=yes, params=ok, examples=no — Return a gating decision for a downstream stage based on upstream signals.
- `QueryProfile` (class): summary=yes, examples=no — Query characteristics profile for adaptive retrieval gating.
- `BudgetDecision` (class): summary=yes, examples=no — Retrieval budget decision for multi-stage search pipelines.
- `_tokenize` (function): summary=no, examples=no
- `_code_like_count` (function): summary=no, examples=no
- `analyze_query` (function): summary=yes, params=ok, examples=no — Analyze query characteristics to build a query profile.
- `decide_budgets` (function): summary=yes, params=ok, examples=no — Decide retrieval budgets based on query profile.
- `describe_budget_decision` (function): summary=yes, params=ok, examples=no — Serialize query profile and budget decision to a dictionary.

## Tags

low-coverage, public-api
