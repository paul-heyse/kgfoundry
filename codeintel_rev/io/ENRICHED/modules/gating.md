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
- from **codeintel_rev.retrieval.types** import StageDecision, StageSignals

## Definitions

- class: `StageGateConfig` (line 13)
- function: `should_run_secondary_stage` (line 62)
- class: `QueryProfile` (line 125)
- class: `BudgetDecision` (line 177)
- function: `_tokenize` (line 211)
- function: `_code_like_count` (line 215)
- function: `analyze_query` (line 224)
- function: `decide_budgets` (line 296)
- function: `describe_budget_decision` (line 343)

## Tags

overlay-needed, public-api
