# enrich/ast_indexer.py

## Docstring

```
AST indexer producing join-ready Parquet datasets.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import ast
- from **(absolute)** import logging
- from **collections.abc** import Callable, Iterator, Sequence
- from **dataclasses** import asdict, dataclass
- from **pathlib** import Path
- from **typing** import cast
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `LOGGER` (line 16)
- class: `DefInfo` (line 20)
- class: `AstNodeRow` (line 30)
- class: `AstMetricsRow` (line 63)
- variable: `AST_NODE_SCHEMA` (line 89)
- variable: `AST_METRIC_SCHEMA` (line 108)
- function: `stable_module_path` (line 125)
- function: `_module_name_from_path` (line 159)
- function: `_safe_unparse` (line 170)
- function: `walk_defs_with_qualname` (line 179)
- function: `collect_ast_nodes` (line 224)
- function: `collect_ast_nodes_from_tree` (line 259)
- function: `compute_ast_metrics` (line 359)
- function: `empty_metrics_row` (line 406)
- function: `write_ast_parquet` (line 445)
- variable: `RowType` (line 459)
- function: `_table_from_rows` (line 462)
- class: `_MetricsVisitor` (line 470)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 91

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 6
- recent churn 90: 6

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

AST_METRIC_SCHEMA, AST_NODE_SCHEMA, AstMetricsRow, AstNodeRow, DefInfo, collect_ast_nodes, collect_ast_nodes_from_tree, compute_ast_metrics, empty_metrics_row, stable_module_path, walk_defs_with_qualname, write_ast_parquet

## Doc Health

- **summary**: AST indexer producing join-ready Parquet datasets.
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

- score: 1.99

## Side Effects

- filesystem

## Complexity

- branches: 26
- cyclomatic: 27
- loc: 608

## Doc Coverage

- `DefInfo` (class): summary=yes, examples=no — Intermediate representation for definition nodes with qualnames.
- `AstNodeRow` (class): summary=yes, examples=no — Row emitted to ast_nodes.parquet.
- `AstMetricsRow` (class): summary=yes, examples=no — Row emitted to ast_metrics.parquet.
- `stable_module_path` (function): summary=yes, params=ok, examples=no — Return a repo-relative POSIX path for the given file.
- `_module_name_from_path` (function): summary=no, examples=no
- `_safe_unparse` (function): summary=no, examples=no
- `walk_defs_with_qualname` (function): summary=yes, params=ok, examples=no — Yield definition nodes with fully-qualified names.
- `collect_ast_nodes` (function): summary=yes, params=ok, examples=no — Parse code and collect node rows for Parquet output.
- `collect_ast_nodes_from_tree` (function): summary=yes, params=ok, examples=no — Collect AstNodeRow entries from a pre-parsed AST module.
- `compute_ast_metrics` (function): summary=yes, params=ok, examples=no — Compute per-file metrics from a parsed AST.

## Tags

low-coverage, public-api, reexport-hub
