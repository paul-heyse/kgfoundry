# cst_build/cst_collect.py

## Docstring

```
LibCST traversal utilities that emit normalized node records.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import logging
- from **collections.abc** import Iterable, Mapping, Sequence
- from **dataclasses** import dataclass
- from **hashlib** import blake2s
- from **pathlib** import Path
- from **textwrap** import shorten
- from **typing** import Any, ClassVar, cast, final
- from **(absolute)** import libcst
- from **libcst** import metadata
- from **libcst.metadata** import FullRepoManager
- from **libcst.metadata.base_provider** import BaseMetadataProvider
- from **libcst.metadata.scope_provider** import ClassScope, ComprehensionScope, FunctionScope, GlobalScope
- from **codeintel_rev.cst_build.cst_schema** import CollectorStats, DocSnippet, ImportMetadata, NodeRecord, Span

## Definitions

- variable: `logger` (line 33)
- class: `CollectorConfig` (line 37)
- class: `_CollectorStatsBuilder` (line 47)
- class: `CSTCollector` (line 138)
- function: `index_file` (line 363)
- function: `_should_emit` (line 383)
- function: `_resolve_span` (line 410)
- function: `_node_id` (line 420)
- function: `_node_name` (line 426)
- function: `_definition_or_class_name` (line 437)
- function: `_assign_target_name` (line 443)
- function: `_annassign_target_name` (line 451)
- function: `_attribute_or_name` (line 457)
- function: `_call_target_name` (line 465)
- function: `_import_alias_name` (line 471)
- function: `_parent_chain` (line 489)
- function: `_scope` (line 518)
- function: `_extract_module_doc` (line 535)
- function: `_summarize` (line 542)
- function: `_doc_snippet` (line 549)
- function: `_preview_text` (line 560)
- function: `_decorators` (line 568)
- function: `_call_targets` (line 584)
- function: `_annotation` (line 596)
- function: `_import_metadata` (line 612)
- function: `_normalize_alias` (line 650)
- function: `_normalize_module_expr` (line 667)
- function: `_is_public` (line 677)
- function: `_resolve_lazy` (line 687)
- function: `_qualified_name_entries` (line 696)
- function: `_normalize_qnames` (line 715)
- function: `_module_name_from_path` (line 724)
- function: `_build_parse_error_node` (line 755)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 31

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 9
- recent churn 90: 9

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: LibCST traversal utilities that emit normalized node records.
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

- score: 2.49

## Side Effects

- filesystem

## Complexity

- branches: 101
- cyclomatic: 102
- loc: 794

## Doc Coverage

- `CollectorConfig` (class): summary=yes, examples=no — Configurable knobs for CST extraction.
- `_CollectorStatsBuilder` (class): summary=yes, examples=no — Mutable builder used while collecting CST stats.
- `CSTCollector` (class): summary=yes, examples=no — Collect LibCST node records for a repository.
- `index_file` (function): summary=yes, params=ok, examples=no — Index a single file and return node records.
- `_should_emit` (function): summary=no, examples=no
- `_resolve_span` (function): summary=no, examples=no
- `_node_id` (function): summary=no, examples=no
- `_node_name` (function): summary=no, examples=no
- `_definition_or_class_name` (function): summary=no, examples=no
- `_assign_target_name` (function): summary=no, examples=no

## Tags

low-coverage
