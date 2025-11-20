
# Implementation plan for export of helpful existing data in new datasets #

Here’s how I’d roll out those four new datasets in a way that’s structurally clean, aligned with your existing architecture, and easy to extend.

I’ll go one by one:

* `import_graph_edges.*`
* `symbol_use_edges.*`
* `config_values.*`
* `static_diagnostics.*`

…and for each I’ll cover:

* What it should look like (schema, semantics).
* Where it fits in the existing pipeline (which types/functions to use).
* Concrete code-level changes (new dataclasses/helpers/writers + where they live).
* How to hook it into DuckDB + `generate_documents.sh` so you get `.parquet` and `.jsonl` in `Document Output/` consistent with the current metadata spec.

I’ll keep this focused on “export what you already compute” – so no new heavy analysis, just surfacing data that’s already in memory or on disk.

---

## Cross‑cutting design choices

Before diving into each artifact, a few conventions I’ll reuse everywhere:

1. **No new “source of truth”**
   Everything is derived from existing in‑memory structs:

   * `ImportGraph` (`codeintel_rev.enrich.graph.builders.ImportGraph`).
   * `UseGraph` (`codeintel_rev.uses_builder.UseGraph`).
   * Config index & references (`index_config_files`, `ConfigReferenceState`).
   * Static type signals (`FileTypeSignals`, `ScanInputs.type_signals`, `LegacyPipelineContext.type_signals`).

2. **Keep GOID as join key, but don’t overcomplicate v1**
   GOIDs and the crosswalk already exist and are the canonical join point for call graph, CFG, DFG, etc.
   For v1 of these exports, I’d:

   * Make sure every row has at least **paths / modules / SCIP symbols** so it can be joined to `goid_crosswalk.*` later.
   * Not require the writers to eagerly join against GOIDs (that can be a v2 refinement).

3. **Reuse your existing IO primitives and layout**

   * Graph‑like tables live under `enriched/graphs/*.parquet`.
   * Analytics tables live under `enriched/analytics/*.parquet` or `.jsonl` and get mirrored into `Document Output/`.
   * For Parquet/JSONL, you already use:

     * `codeintel_rev.enrich.graph.io.write_parquet_or_jsonl` for graph tables.
     * `codeintel_rev.services.enrich.io.write_parquet` / `write_jsonl` for more general records.

---

## 1. `import_graph_edges.*` – module import graph

### 1.1. Schema

You already compute an `ImportGraph` with:

* `edges: Mapping[str, set[str]]` – adjacency by module name.
* `fan_in: Mapping[str, int]` / `fan_out: Mapping[str,int]`.
* `cycle_group: Mapping[str, int]` – SCC IDs from Tarjan.

Expose that as a simple edge table:

**File names**

* `enriched/graphs/import_graph_edges.parquet`
* `Document Output/import_graph_edges.jsonl` (via DuckDB `COPY` like other graph tables).

**Columns**

| Column        | Type   | Description                                                                 |
| ------------- | ------ | --------------------------------------------------------------------------- |
| `src_module`  | string | Source module name (`codeintel_rev.services.enrich.exports`).               |
| `dst_module`  | string | Target module name imported by `src_module`.                                |
| `src_fan_out` | int    | `fan_out[src_module]`: number of distinct modules imported by `src_module`. |
| `dst_fan_in`  | int    | `fan_in[dst_module]`: number of incoming imports into `dst_module`.         |
| `cycle_group` | int    | SCC / cycle ID for `src_module`. `-1` or `0` for acyclic nodes.             |

This mirrors the way `call_graph_edges.*` normalizes edges while keeping degree info on each row.

You can later add `src_path` / `dst_path` and `*_goid_h128`, but this is enough for v1 and keeps the writer simple.

### 1.2. Where the data lives today

* `ImportGraph` is produced inside the analytics pipeline (`compute_pipeline_analytics`) and stored on `PipelineResult.import_graph`.
* `services.enrich.exports.write_graph_outputs` already calls `write_import_graph(result.import_graph, out / "graphs" / "imports.parquet", ...)`.
* `enrich.graph.io.write_import_edges` is already a thin wrapper around `write_parquet_or_jsonl`.

So really this is about:

1. Locking in a schema.
2. Renaming and wiring the file to a stable name used by the DuckDB catalog + docs.
3. Making sure we also get JSONL out.

### 1.3. Code changes

#### (a) `codeintel_rev.enrich.graph.io`

Add a concrete schema + row iterator:

```python
# codeintel_rev/enrich/graph/io.py

from dataclasses import dataclass
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Iterator

import pyarrow as pa

from codeintel_rev.enrich.graph.builders import ImportGraph
from codeintel_rev.enrich.output_writers import write_parquet_or_jsonl

IMPORT_EDGES_SCHEMA = pa.schema(
    [
        pa.field("src_module", pa.string()),
        pa.field("dst_module", pa.string()),
        pa.field("src_fan_out", pa.int32()),
        pa.field("dst_fan_in", pa.int32()),
        pa.field("cycle_group", pa.int32()),
    ]
)


def write_import_edges(
    graph: ImportGraph,
    path: Path,
    *,
    jsonl_fallback: Path | None = None,
) -> Path:
    """Materialize ImportGraph adjacency as an edge table.

    Each row represents a directed import edge from ``src_module`` to
    ``dst_module`` with degree and cycle metadata attached.

    Parameters
    ----------
    graph :
        ImportGraph instance from analytics.
    path :
        Destination Parquet path (``*.parquet``).
    jsonl_fallback :
        Optional JSONL fallback path. When provided, a JSONL copy is emitted
        alongside the Parquet file.

    Returns
    -------
    Path
        Parquet path actually written.
    """

    def _rows() -> Iterator[Mapping[str, object]]:
        fan_in = graph.fan_in
        fan_out = graph.fan_out
        cycles = graph.cycle_group

        for src, dsts in graph.edges.items():
            src_out = fan_out.get(src, 0)
            cycle = cycles.get(src, -1)
            for dst in dsts:
                yield {
                    "src_module": src,
                    "dst_module": dst,
                    "src_fan_out": src_out,
                    "dst_fan_in": fan_in.get(dst, 0),
                    "cycle_group": cycle,
                }

    return write_parquet_or_jsonl(
        path=path,
        schema=IMPORT_EDGES_SCHEMA,
        rows=_rows(),
        jsonl_fallback=jsonl_fallback,
    )
```

If `write_import_edges` already exists, adjust it to match this schema instead of whatever ad‑hoc dict it currently emits.

#### (b) `codeintel_rev.graph_builder` (top‑level wrapper)

You already have a top‑level wrapper that delegates to `enrich.graph.io`.

Keep it thin:

```python
# codeintel_rev/graph_builder.py

from pathlib import Path
from codeintel_rev.enrich.graph.builders import ImportGraph
from codeintel_rev.enrich.graph.io import write_import_edges

def write_import_graph(
    graph: ImportGraph,
    path: Path,
    *,
    jsonl_fallback: Path | None = None,
) -> Path:
    """Public entrypoint for writing the import graph edges."""
    return write_import_edges(graph, path, jsonl_fallback=jsonl_fallback)
```

(If this wrapper already exists, just extend it with the `jsonl_fallback` parameter.)

#### (c) `codeintel_rev.services.enrich.exports.write_graph_outputs`

Update the callsite:

```python
# services/enrich/exports.py

from codeintel_rev.graph_builder import write_import_graph, write_symbol_graph
from pathlib import Path

def write_graph_outputs(result: PipelineResult, out: Path) -> None:
    ...
    graphs_dir = out / "graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)

    write_symbol_graph(
        result.symbol_edges,
        graphs_dir / "symbol_graph.parquet",
        # if you want a JSONL too:
        jsonl_fallback=graphs_dir / "symbol_graph.jsonl",
    )

    write_import_graph(
        result.import_graph,
        graphs_dir / "import_graph_edges.parquet",
        jsonl_fallback=graphs_dir / "import_graph_edges.jsonl",
    )
```

This replaces `imports.parquet` with `import_graph_edges.parquet` to align with the README naming pattern (`*_edges.*`).

If you want to preserve backwards compatibility, you can write both names for a release or two.

#### (d) DuckDB catalog

In `codeintel_rev.io.duckdb_catalog`, wherever you register graph tables (the same place that registers `call_graph_edges`, `cfg_edges`, `dfg_edges`), add:

```python
GRAPH_TABLES = {
    **GRAPH_TABLES,
    "import_graph_edges": {
        "path": "graphs/import_graph_edges.parquet",
        "ddl": """
            CREATE TABLE import_graph_edges AS
            SELECT
                src_module,
                dst_module,
                src_fan_out,
                dst_fan_in,
                cycle_group
            FROM read_parquet('{path}');
        """,
    },
}
```

Exact structure will match your existing `GRAPH_TABLES` map – just follow the pattern you use for `call_graph_edges`.

#### (e) `generate_documents.sh`

Add `import_graph_edges` to the loop that runs `COPY` to JSONL:

```bash
for table in goids goid_crosswalk call_graph_nodes call_graph_edges \
             cfg_blocks cfg_edges dfg_edges import_graph_edges; do
  duckdb "$DB" "
    COPY ${table} TO '${DOC_OUT}/${table}.jsonl'
    (FORMAT JSON, ARRAY FALSE);
  "
done
```

And document it in `README_METADATA.md` under a new section “Import Graph (`import_graph_edges.*`)”.

---

## 2. `symbol_use_edges.*` – SCIP‑based def‑use graph

### 2.1. Schema

`UseGraph` already aggregates def→use relationships extracted from the SCIP index:

* `def_to_use_paths: Mapping[str, Sequence[str]]`
* `use_to_def_paths: Mapping[str, Sequence[str]]`
* `symbols_by_file: Mapping[str, set[str]]`
* `edges: Sequence[tuple[str, str, str]]  # (def_path, use_path, symbol)`

We want a dataset that exposes those edges directly.

**File names**

* `enriched/graphs/symbol_use_edges.parquet`
* `Document Output/symbol_use_edges.jsonl`.

**Columns**

| Column        | Type   | Description                                                 |
| ------------- | ------ | ----------------------------------------------------------- |
| `symbol`      | string | SCIP symbol ID (e.g., `scip-python python ...`).            |
| `def_path`    | string | Repo‑relative file path where the symbol is defined.        |
| `use_path`    | string | Repo‑relative file path where it is referenced.             |
| `same_file`   | bool   | True if `def_path == use_path`.                             |
| `same_module` | bool   | True if both paths map to same module from `modules.jsonl`. |

This is intentionally minimal: it gives LLMs a def‑use graph with just enough context to join to:

* `index.scip.json` (by `symbol`).
* `goid_crosswalk.*` (by `file_path` + `scip_symbol`).
* `modules.jsonl` (by path→module).

### 2.2. Where the data lives today

* `UseGraph` constructed by `codeintel_rev.uses_builder.build_use_graph(scip_index)`.
* `PipelineResult.use_graph` holds it.
* `services.enrich.exports.write_uses_output` already writes graph data into `graphs/uses.parquet` via `write_use_graph`.

We’ll just standardize the schema and rename to `symbol_use_edges.*`.

### 2.3. Code changes

#### (a) `codeintel_rev.enrich.graph.io`

Define the schema and row iteration:

```python
# codeintel_rev/enrich/graph/io.py

from codeintel_rev.uses_builder import UseGraph

USE_EDGES_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string()),
        pa.field("def_path", pa.string()),
        pa.field("use_path", pa.string()),
        pa.field("same_file", pa.bool_()),
        pa.field("same_module", pa.bool_()),
    ]
)


def write_use_edges(
    graph: UseGraph,
    path: Path,
    *,
    jsonl_fallback: Path | None = None,
    module_by_path: Mapping[str, str] | None = None,
) -> Path:
    """Write SCIP def-use edges to Parquet/JSONL.

    Parameters
    ----------
    graph :
        UseGraph instance.
    path :
        Destination Parquet path.
    jsonl_fallback :
        Optional JSONL fallback path.
    module_by_path :
        Optional map from ``rel_path`` → dotted module name, derived from
        ``modules.jsonl`` or in-memory `ModuleRecord`s. Used to compute
        ``same_module`` cheaply.
    """

    modules = module_by_path or {}

    def _rows() -> Iterator[Mapping[str, object]]:
        for def_path, use_path, symbol in graph.edges:
            def_mod = modules.get(def_path)
            use_mod = modules.get(use_path)
            yield {
                "symbol": symbol,
                "def_path": def_path,
                "use_path": use_path,
                "same_file": def_path == use_path,
                "same_module": bool(def_mod and def_mod == use_mod),
            }

    return write_parquet_or_jsonl(
        path=path,
        schema=USE_EDGES_SCHEMA,
        rows=_rows(),
        jsonl_fallback=jsonl_fallback,
    )
```

If `write_use_edges` already exists, update it to this schema and signature.

#### (b) `codeintel_rev.uses_builder` wrapper

Expose a wrapper similar to `write_import_graph`:

```python
# codeintel_rev/uses_builder.py

from pathlib import Path
from collections.abc import Mapping

from codeintel_rev.enrich.graph.io import write_use_edges

def write_use_graph(
    graph: UseGraph,
    path: Path,
    *,
    jsonl_fallback: Path | None = None,
    module_by_path: Mapping[str, str] | None = None,
) -> Path:
    return write_use_edges(
        graph,
        path,
        jsonl_fallback=jsonl_fallback,
        module_by_path=module_by_path,
    )
```

#### (c) `services.enrich.exports.write_uses_output`

You already have:

```python
def write_uses_output(result: PipelineResult, out: Path) -> None:
    if result.use_graph is None:
        LOGGER.info("No use graph to write")
        return
    path = out / "graphs" / "uses.parquet"
    write_use_graph(result.use_graph, path)
```

Update to:

```python
from codeintel_rev.pipeline_helpers import build_module_row  # already used elsewhere
from codeintel_rev.services.enrich.pipeline_helpers import normalized_rel_path

def write_uses_output(result: PipelineResult, out: Path) -> None:
    """Export SCIP def-use graph as symbol_use_edges.*."""
    if result.use_graph is None:
        LOGGER.info("No use graph to write")
        return

    graphs_dir = out / "graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)

    module_by_path = {row.path: row.module for row in result.module_rows}

    write_use_graph(
        result.use_graph,
        graphs_dir / "symbol_use_edges.parquet",
        jsonl_fallback=graphs_dir / "symbol_use_edges.jsonl",
        module_by_path=module_by_path,
    )
```

Again, if you want compatibility, you can still emit `uses.parquet` for now.

#### (d) DuckDB catalog

Register a graph table for it:

```python
GRAPH_TABLES = {
    **GRAPH_TABLES,
    "symbol_use_edges": {
        "path": "graphs/symbol_use_edges.parquet",
        "ddl": """
            CREATE TABLE symbol_use_edges AS
            SELECT
                symbol,
                def_path,
                use_path,
                same_file,
                same_module
            FROM read_parquet('{path}');
        """,
    },
}
```

#### (e) `generate_documents.sh`

Include it in the graph-table → JSONL loop:

```bash
for table in goids goid_crosswalk call_graph_nodes call_graph_edges \
             cfg_blocks cfg_edges dfg_edges import_graph_edges symbol_use_edges; do
  ...
done
```

Update `README_METADATA.md` with a “Symbol Use Graph (`symbol_use_edges.*`)" section with the above columns and note that consumers can join `symbol` to SCIP and to GOIDs through `goid_crosswalk.scip_symbol`.

---

## 3. `config_values.*` – normalized config keys + references

### 3.1. Schema

From `config_indexer.index_config_files` and `ConfigReferenceState` docs:

* Each raw record has:

  * `path`: config file `rel_path`.
  * `keys`: list of discovered config keys (string key paths).
  * `references`: config references (used by `ConfigReferenceState`).
* `ConfigReferenceState` adds:

  * `records`: the raw records.
  * `references: dict[str, set[str]]` mapping config key → set of `rel_path`s of referencing code files.
  * `by_dir`: directory‑level aggregations used by analytics.

We want a normalized per‑key view:

**File names**

* `enriched/analytics/config_values.parquet`
* `Document Output/config_values.jsonl`.

**Columns**

| Column              | Type   | Description                                                                 |
| ------------------- | ------ | --------------------------------------------------------------------------- |
| `config_path`       | string | Repo‑relative path to the config file.                                      |
| `format`            | string | Heuristic file format (`yaml`, `toml`, `json`, `ini`, `env`, `other`).      |
| `key`               | string | Normalized config key path (e.g. `service.database.host`).                  |
| `reference_paths`   | list   | Sorted list of `rel_path`s that reference this key anywhere in code.        |
| `reference_modules` | list   | Sorted list of dotted modules derived from `modules.jsonl` for those paths. |
| `reference_count`   | int    | Number of distinct referencing files.                                       |

This is deliberately per‑key, not per‑(key, code file) row, to be nice to LLMs: you can quickly see “who reads this config knob” with a single row.

### 3.2. Where data lives today

* Raw config records: `config_indexer.index_config_files` → list of dicts.
* Analytics stage calls `prepare_config_state(records) -> ConfigReferenceState`.
* `augment_module_rows` uses `ConfigReferenceState` to attach config metadata to module rows.
* `services.enrich.exports.write_config_output` currently just dumps `config_index` as JSON under `analytics/config_index.json`.

So we only need to:

1. Compute `ConfigReferenceState` in exports (if not already passed).
2. Flatten to `config_values` rows.
3. Write Parquet/JSONL.

### 3.3. Code changes

#### (a) `services.enrich.analytics.config` – add a flattener

Create a small helper to turn `ConfigReferenceState` into row dicts:

```python
# codeintel_rev/services/enrich/analytics/config.py

from dataclasses import dataclass
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .models import ConfigReferenceState, ModuleRecord  # names per your code

def _guess_format(path: str) -> str:
    if path.endswith((".yaml", ".yml")):
        return "yaml"
    if path.endswith(".toml"):
        return "toml"
    if path.endswith(".json"):
        return "json"
    if path.endswith((".ini", ".cfg")):
        return "ini"
    if path.endswith(".env"):
        return "env"
    return "other"


def build_config_value_rows(
    state: ConfigReferenceState,
    module_rows: Sequence[ModuleRecord],
) -> list[dict[str, object]]:
    """Flatten config index + references into config_values rows.

    Parameters
    ----------
    state :
        Prepared config reference state from ``prepare_config_state``.
    module_rows :
        Enriched module rows; used to map file paths to module names.

    Returns
    -------
    list[dict[str, object]]
        JSON-serializable rows for config_values.*.
    """
    path_to_module = {m.path: m.module for m in module_rows}
    rows: list[dict[str, object]] = []

    # state.records: list[dict[str, Any]] with at least keys: path, keys
    for record in state.records:
        config_path = record.get("path")
        if not config_path:
            continue
        fmt = record.get("format") or _guess_format(config_path)
        keys = record.get("keys") or []

        for key in keys:
            ref_paths = sorted(state.references.get(key, set()))
            ref_modules = sorted(
                {path_to_module[p] for p in ref_paths if p in path_to_module}
            )
            rows.append(
                {
                    "config_path": config_path,
                    "format": fmt,
                    "key": key,
                    "reference_paths": ref_paths,
                    "reference_modules": ref_modules,
                    "reference_count": len(ref_paths),
                }
            )

    return rows
```

This uses only structures you already have (`ConfigReferenceState.records` and `.references`).

#### (b) `services.enrich.exports.write_config_output`

Extend the export function to write `config_values.*`:

```python
# services/enrich/exports.py

from codeintel_rev.services.enrich.analytics.config import (
    prepare_config_state,
    build_config_value_rows,
)
from codeintel_rev.enrich.output_writers import write_parquet
from codeintel_rev.services.enrich.io import write_jsonl as write_jsonl_legacy

CONFIG_VALUES_SCHEMA = {
    "config_path": "STRING",
    "format": "STRING",
    "key": "STRING",
    "reference_paths": "LIST<STRING>",
    "reference_modules": "LIST<STRING>",
    "reference_count": "INTEGER",
}

def write_config_output(result: PipelineResult, out: Path) -> None:
    """Write config index debug JSON and normalized config_values graph."""
    if not result.config_index:
        LOGGER.info("No config index to write")
        return

    analytics_dir = out / "analytics"
    configs_dir = analytics_dir / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)

    # Existing debug JSON
    index_path = configs_dir / "config_index.json"
    index_path.write_text(json.dumps(result.config_index, indent=2, sort_keys=True))

    # New normalized config_values
    state = prepare_config_state(result.config_index)
    rows = build_config_value_rows(state, result.module_rows)

    parquet_path = analytics_dir / "config_values.parquet"
    write_parquet(parquet_path, rows, schema=CONFIG_VALUES_SCHEMA)

    jsonl_path = analytics_dir / "config_values.jsonl"
    write_jsonl_legacy(jsonl_path, rows)
```

If your Parquet writer uses Arrow schemas instead of this simple dict schema, swap accordingly; the main point is: one Parquet + one JSONL.

#### (c) DuckDB catalog

Add an analytics table:

```python
ANALYTICS_TABLES = {
    **ANALYTICS_TABLES,
    "config_values": {
        "path": "analytics/config_values.parquet",
        "ddl": """
            CREATE TABLE config_values AS
            SELECT
                config_path,
                format,
                key,
                reference_paths,
                reference_modules,
                reference_count
            FROM read_parquet('{path}');
        """,
    },
}
```

#### (d) `generate_documents.sh`

If you mirror analytics Parquet files into the document root via DuckDB, add `config_values` to that list. If you instead just copy JSONL files directly, ensure `analytics/config_values.jsonl` gets copied as `Document Output/config_values.jsonl`.

Update `README_METADATA.md` with a “Config Values (`config_values.*`)" section, anchored to `index_config_files` / `ConfigReferenceState`.

---

## 4. `static_diagnostics.*` – per‑file type checker signals

### 4.1. Schema

You already have:

* `FileTypeSignals` (in `typedness.py`):

  * `pyrefly_errors: int`
  * `pyright_errors: int`

* `ScanInputs.type_signals: Mapping[str, FileTypeSignals]` (path → signals).

* `LegacyPipelineContext.type_signals` hangs onto this map across the pipeline.

You also already compute per-file typedness (`typedness.jsonl`) and hotspots (`hotspots.jsonl`).

So a good v1 “static diagnostics” export is essentially “one row per file, with error counts from those two tools”:

**File names**

* `enriched/analytics/static_diagnostics.parquet`
* `Document Output/static_diagnostics.jsonl`.

**Columns**

| Column           | Type   | Description                           |
| ---------------- | ------ | ------------------------------------- |
| `rel_path`       | string | Repo‑relative path of the file.       |
| `pyrefly_errors` | int    | Number of errors reported by Pyrefly. |
| `pyright_errors` | int    | Number of errors reported by Pyright. |
| `total_errors`   | int    | `pyrefly_errors + pyright_errors`.    |
| `has_errors`     | bool   | `total_errors > 0`.                   |

Later you can evolve this with severity breakdowns, codes, or link it to GOIDs via `goid_crosswalk`, but this is enough to surface the static‑analysis signal you already aggregate.

### 4.2. Where data lives today

* `collect_type_signal_map(root, pyright_json)` reads Pyrefly/Pyright summaries and normalizes them into `Mapping[str, FileTypeSignals]`.
* `ScanInputs.type_signals` carries that mapping.
* `LegacyPipelineContext.type_signals` stores it through the pipeline.
* Typedness analytics uses it to compute per‑file annotation coverage but doesn’t expose the raw counts.

We just need a very small analytics writer.

### 4.3. Code changes

#### (a) `services.enrich.analytics.typedness` (or new `static_diagnostics.py`)

Add a simple row builder:

```python
# codeintel_rev/services/enrich/analytics/static_diagnostics.py

from collections.abc import Mapping
from typing import Any

from codeintel_rev.typedness import FileTypeSignals

def build_static_diagnostics_rows(
    type_signals: Mapping[str, FileTypeSignals],
) -> list[dict[str, Any]]:
    """Flatten FileTypeSignals into static_diagnostics rows."""
    rows: list[dict[str, Any]] = []

    for rel_path, sig in sorted(type_signals.items()):
        pyrefly_errs = getattr(sig, "pyrefly_errors", 0) or 0
        pyright_errs = getattr(sig, "pyright_errors", 0) or 0
        total = pyrefly_errs + pyright_errs
        rows.append(
            {
                "rel_path": rel_path,
                "pyrefly_errors": pyrefly_errs,
                "pyright_errors": pyright_errs,
                "total_errors": total,
                "has_errors": bool(total),
            }
        )

    return rows
```

#### (b) `services.enrich.exports` – new writer

We need access to `type_signals`. That’s on the `LegacyPipelineContext` rather than `PipelineResult`.

There are two reasonable options:

1. **Extend `PipelineResult`** to carry `type_signals`, and pass only `result` into exports.
2. **Add a new export function** that takes the context.

To minimize surface area, I’d add a dedicated function that accepts `LegacyPipelineContext`:

```python
# services/enrich/exports.py

from codeintel_rev.services.enrich.analytics.static_diagnostics import (
    build_static_diagnostics_rows,
)
from codeintel_rev.enrich.output_writers import write_parquet
from codeintel_rev.services.enrich.io import write_jsonl as write_jsonl_legacy
from codeintel_rev.services.enrich.context import LegacyPipelineContext

STATIC_DIAGNOSTICS_SCHEMA = {
    "rel_path": "STRING",
    "pyrefly_errors": "INTEGER",
    "pyright_errors": "INTEGER",
    "total_errors": "INTEGER",
    "has_errors": "BOOLEAN",
}

def write_static_diagnostics_output(ctx: LegacyPipelineContext, out: Path) -> None:
    """Persist per-file static diagnostics summary.

    Uses the already-collected FileTypeSignals map on the pipeline context.
    """
    if not ctx.type_signals:
        LOGGER.info("No static diagnostics to write")
        return

    analytics_dir = out / "analytics"
    analytics_dir.mkdir(parents=True, exist_ok=True)

    rows = build_static_diagnostics_rows(ctx.type_signals)

    parquet_path = analytics_dir / "static_diagnostics.parquet"
    write_parquet(parquet_path, rows, schema=STATIC_DIAGNOSTICS_SCHEMA)

    jsonl_path = analytics_dir / "static_diagnostics.jsonl"
    write_jsonl_legacy(jsonl_path, rows)
```

#### (c) Wire it into the pipeline

In `services/enrich.scan.run_pipeline` (or wherever you orchestrate steps like `write_graph_outputs`, `write_config_output`, `apply_ownership`), after the main pipeline completes:

```python
# services/enrich/scan.py (pseudo)

def run_pipeline(ctx: LegacyPipelineContext, steps: Sequence[GraphStep], out: Path) -> PipelineResult:
    result = _run_core_pipeline(ctx, steps, out)

    # existing exports:
    write_graph_outputs(result, out)
    write_uses_output(result, out)
    write_config_output(result, out)
    apply_ownership(result, out, history_window_days=..., commits_window=...)

    # new:
    write_static_diagnostics_output(ctx, out)

    return result
```

This keeps static diagnostics firmly in the “analytics” bucket, alongside hotspots/typedness, not as a graph step.

#### (d) DuckDB + docs

Register the analytics table in `duckdb_catalog`:

```python
ANALYTICS_TABLES = {
    **ANALYTICS_TABLES,
    "static_diagnostics": {
        "path": "analytics/static_diagnostics.parquet",
        "ddl": """
            CREATE TABLE static_diagnostics AS
            SELECT
                rel_path,
                pyrefly_errors,
                pyright_errors,
                total_errors,
                has_errors
            FROM read_parquet('{path}');
        """,
    },
}
```

In `generate_documents.sh`, include `static_diagnostics` in the list you mirror to JSONL (if you go via DuckDB) or copy the emitted JSONL directly.

Add a section to `README_METADATA.md`, under Analytics, right after Typedness:

> **Static Diagnostics (`static_diagnostics.*`)**
> Purpose: Per‑file static type error counts produced by Pyrefly/Pyright. Origin: `FileTypeSignals` via `collect_type_signal_map` and `LegacyPipelineContext.type_signals`. Fields: `rel_path`, `pyrefly_errors`, `pyright_errors`, `total_errors`, `has_errors`.

---

## 5. Summary & next steps

With the changes above you get four new, first‑class datasets that are:

* **Directly grounded in existing code paths and data structures**:

  * `ImportGraph`, `UseGraph`, `ConfigReferenceState`, `FileTypeSignals`, `LegacyPipelineContext`.
* **Consistent with the existing Document Output spec**:

  * Parquet under `enriched/graphs` / `enriched/analytics`, JSONL mirrored to `Document Output/`, naming and column style matching GOID/CFG/DFG/CallGraph.
* **Ready for LLM consumption**:

  * Simple row‑oriented schemas, explicit join keys (paths, modules, SCIP symbols) that tie back into `goid_crosswalk`, `index.scip.json`, and `modules.jsonl`.

Once these are in place and stable, the natural v2 enhancements would be:

* Attaching GOIDs directly onto import/use edges by joining against `goid_crosswalk` at build time.
* Enriching `config_values` with sampled values and per‑(key, code location) rows.
* Surfacing per‑diagnostic static analysis details (codes, messages, severities) as a second `static_diagnostics_events.*` table.

But even v1, as described here, already unlocks much deeper LLM reasoning about:

* Architectural coupling (`import_graph_edges` + `symbol_use_edges`).
* Config surface area and blast radius (`config_values`).
* Type‑safety hotspots (`static_diagnostics` + `typedness` + `hotspots`).

