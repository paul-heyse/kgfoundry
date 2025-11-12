# `modules.jsonl` Reference

This directory contains `modules.jsonl`, the canonical record of every Python module that was scanned by `codeintel_rev.cli_enrich`. Each record is a JSON object describing structure, typedness, documentation, coverage, usage, and tagging data for a single file. This page explains how the file is organised and how to interpret every field.

> **Note:** the file is prettified for readability (multi-line JSON objects separated by the literal sequence `'}\n{'`). When loading the data with a JSON parser, either treat it as JSON Lines that you split manually or wrap the content in `[` and `]` after replacing `}\n{` with `},{`.

```python
from pathlib import Path
import json

text = Path("build/enrich/modules/modules.jsonl").read_text()
records = json.loads(f"[{text.replace('}\\n{{', '},{')}]")
print(len(records), "modules")
```

## Top-Level Fields

Every record contains the fields below. Optional entries (which may be missing if the information doesn’t apply) are marked with “optional”.

| Field | Type | Description |
| --- | --- | --- |
| `path` | `str` | Repository-relative module path (e.g., `codeintel_rev/io/warp_engine.py`). |
| `docstring` | `str \| null` | Raw module docstring (trimmed) or `null` if absent. |
| `doc_has_summary`, `doc_param_parity`, `doc_examples_present` | `bool` | Quick flags extracted from the module-level docstring. |
| `imports` | `list[ImportEntry]` | All LibCST import statements (see *Nested Structures*). |
| `defs` | `list[DefEntry]` | Summary of top-level functions/classes (`kind`, `name`, `lineno`). |
| `exports`, `exports_declared` | `list[str]` | Names exported via `__all__`; both fields currently match. |
| `outline_nodes` | `list[OutlineNode]` | Tree-sitter outline entries (`kind`, `name`, `start`, `end` byte offsets). Empty when the outline parser didn’t return anything. |
| `scip_symbols` | `list[str]` | Set of SCIP symbols defined in the module (used for cross-reference graphs). |
| `parse_ok` | `bool` | Indicates whether LibCST parsing succeeded. |
| `errors` | `list[str]` | Parsing or indexing errors captured for the module. |
| `tags` | `list[str]` | Policy tags (e.g., `public-api`, `low-coverage`, `hotspot`). |
| `type_errors`, `type_error_count` | `int` | Maximum of Pyrefly/Pyright errors for the module (mirrored in both fields for backward compatibility). |
| `doc_summary` | `str \| null` | First line or parsed summary of the docstring. |
| `doc_metrics` | `{"has_summary": bool, "param_parity": bool, "examples_present": bool}` | Normalised doc health metrics. |
| `doc_items` | `list[DocItem]` | Function/class doc coverage details (see *Nested Structures*). |
| `annotation_ratio` | `{"params": float, "returns": float}` | Share of annotated parameters/return types (clamped `[0.0, 1.0]`). |
| `untyped_defs` | `int` | Count of public definitions missing type annotations. |
| `side_effects` | `{"filesystem": bool, "network": bool, "subprocess": bool, "database": bool}` | Flags inferred from static analysis. |
| `raises` | `list[str]` | Exception names mentioned in the module docstring. |
| `complexity` | `{"branches": int, "cyclomatic": int, "loc": int}` | Aggregate structural metrics derived from LibCST. |
| `covered_lines_ratio`, `covered_defs_ratio` | `float` | Coverage share from `coverage.xml` when available (0.0 if missing). |
| `config_refs` | `list[str]` | Relative paths to YAML/TOML/JSON/MD files located in ancestor directories (useful for linking code to config). |
| `overlay_needed` | `bool` | Whether the module qualifies for overlay generation (`True` when public, high fan-in, and missing annotations). |
| `fan_in`, `fan_out` | `int` | Import graph degrees within the repository. |
| `cycle_group` | `int` | Strongly connected component identifier in the import graph (`-1` when isolated). |
| `imports_internal`, `imports_intra_repo` | `list[str]` | Sorted list of repo-internal modules imported by this file. |
| `used_by_files` | `int` | Count of other files that reference definitions from this module (SCIP based). |
| `used_by_symbols` | `int` | Total number of cross-reference occurrences pointing to this module. |
| `hotspot_score` | `float` | Composite risk score ∈ `[0, 10]` derived from fan-in/out, complexity, coverage, churn, and type errors. |

## Nested Structures

- **`ImportEntry`** (elements of `imports`)
  ```json
  {
    "module": "__future__",        // absolute module or null for relative `from . import`
    "names": ["annotations"],      // imported names (empty for plain `import pkg`)
    "aliases": {},                 // alias mapping (`{"DataFrame": "DF"}`)
    "is_star": false,              // `True` for `from pkg import *`
    "level": 0                     // relative import level (0 for absolute)
  }
  ```

- **`DefEntry`** (elements of `defs`)
  ```json
  {
    "kind": "function",            // "class" or "function"
    "name": "compute_hotspot_score",
    "lineno": 14                   // 1-based source line
  }
  ```

- **`DocItem`** (elements of `doc_items`)
  ```json
  {
    "name": "compute_hotspot_score",
    "kind": "function",
    "public": true,
    "lineno": 14,
    "doc_summary": "Compute a heuristic hotspot score for a module record.",
    "doc_has_summary": true,
    "doc_param_parity": true,
    "doc_examples_present": false
  }
  ```

- **`OutlineNode`** (elements of `outline_nodes`, when available)
  ```json
  {
    "kind": "function",            // Tree-sitter node kind
    "name": "search",
    "start": 1024,                 // start byte offset
    "end": 2048                    // end byte offset
  }
  ```

## Interpreting the Data

- **Schema stability.** The CLI preserves these field names so downstream tooling (dashboards, analytics, LLM agents) can rely on them. Optional fields simply disappear rather than being set to `null`, so code should use `.get(...)` where appropriate.
- **Typedness view.** `annotation_ratio`, `type_error_count`, `untyped_defs`, `overlay_needed`, and `tags` give a quick glance at a file’s type health. Modules tagged `overlay-needed` are prime candidates for `.pyi` overlays.
- **Documentation health.** `doc_metrics` + `doc_items` explain whether the module and its public APIs are documented. Missing summaries or parameter parity will surface through the `docs-missing` tag.
- **Graph context.** `fan_in`, `fan_out`, `cycle_group`, `imports_intra_repo`, `used_by_files`, and `hotspot_score` are derived from the import/use graphs and help prioritise risky modules.
- **Coverage/config linkage.** Use `covered_lines_ratio` to spot untested files, and `config_refs` to tie modules back to YAML/TOML/JSON documents discovered in parent directories.

## Regenerating the File

Run the enrichment CLI whenever the source tree changes:

```bash
uv run python -m codeintel_rev.cli_enrich all \
  --root codeintel_rev \
  --scip codeintel_rev/index.scip.json \
  --out build/enrich
```

This rebuilds `modules.jsonl` along with the analytics tables under `build/enrich/`.
