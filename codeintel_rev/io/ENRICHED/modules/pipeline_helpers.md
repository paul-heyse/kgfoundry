# enrich/pipeline_helpers.py

## Docstring

```
Shared helpers for enrichment pipeline stages and tagging.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import logging
- from **collections.abc** import Mapping
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Any
- from **codeintel_rev.enrich.ast_indexer** import stable_module_path
- from **codeintel_rev.enrich.errors** import IndexingError
- from **codeintel_rev.enrich.libcst_bridge** import ModuleIndex, index_module
- from **codeintel_rev.enrich.models** import ModuleRecord
- from **codeintel_rev.enrich.pathnorm** import module_name_from_path, stable_id_for_path
- from **codeintel_rev.enrich.tagging** import ModuleTraits, infer_tags
- from **codeintel_rev.enrich.tree_sitter_bridge** import build_outline
- from **codeintel_rev.export_resolver** import EXPORT_HUB_THRESHOLD
- from **codeintel_rev.cli.enrich_pipeline** import ScanInputs

## Definitions

- variable: `LOGGER` (line 22)
- function: `normalized_rel_path` (line 33)
- function: `build_module_row` (line 44)
- function: `outline_nodes_for` (line 104)
- function: `type_error_count` (line 135)
- function: `apply_tagging` (line 147)
- function: `_scip_symbols_and_edges` (line 160)
- function: `_index_module_safe` (line 171)
- function: `_read_module_source` (line 179)
- function: `_collect_outline_nodes` (line 206)
- function: `_apply_index_results` (line 219)
- function: `_coverage_value` (line 258)
- function: `_traits_from_row` (line 263)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 10
- **cycle_group**: 83

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 1
- recent churn 90: 1

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

apply_tagging, build_module_row, normalized_rel_path, outline_nodes_for, type_error_count

## Doc Health

- **summary**: Shared helpers for enrichment pipeline stages and tagging.
- has summary: yes
- param parity: no
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Config References

- enrich/tagging_rules.yaml
- enrich/PLAYBOOK.md
- enrich/README.md

## Hotspot

- score: 2.63

## Side Effects

- filesystem

## Complexity

- branches: 36
- cyclomatic: 37
- loc: 310

## Doc Coverage

- `normalized_rel_path` (function): summary=yes, params=mismatch, examples=no — Return the normalized relative path for ``path`` under ``root``.
- `build_module_row` (function): summary=yes, params=mismatch, examples=no — Construct a ModuleRecord and symbol edges for ``fp``.
- `outline_nodes_for` (function): summary=yes, params=mismatch, examples=no — Build Tree-sitter outline nodes for ``rel_path``.
- `type_error_count` (function): summary=yes, params=mismatch, examples=no — Return the type error count for ``rel_path``.
- `apply_tagging` (function): summary=yes, params=mismatch, examples=no — Apply tagging rules to module rows and update their tags in-place.
- `_scip_symbols_and_edges` (function): summary=no, examples=no
- `_index_module_safe` (function): summary=no, examples=no
- `_read_module_source` (function): summary=no, examples=no
- `_collect_outline_nodes` (function): summary=no, examples=no
- `_apply_index_results` (function): summary=no, examples=no

## Tags

low-coverage, public-api
