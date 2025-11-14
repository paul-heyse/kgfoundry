# Enrichment Pipeline Overview

The enrichment CLI (`codeintel_rev/cli_enrich.py`) orchestrates a composable set of
stages that merge SCIP, LibCST, Tree-sitter, type-checker signals, analytics, and
writers into a stable `modules/` artifact bundle. The stages are intentionally small,
idempotent, and logged via structured `stage=*` spans so operators can pinpoint where
time is spent or why a module failed.

## Stage flow

1. **discover** — Glob Python files (skipping `.` folders and matching any `--only`
   Globs), normalize to repo-relative POSIX paths, and log how many candidates were found.
2. **ingest** — Load the SCIP JSON index once via `SCIPIndex.load` and derive lookup
   tables (`by_file`, `symbol_to_files`). This stage is the only one that depends on
   `--scip` and fails fast with a clear error.
3. **type-signals** — Query Pyrefly/Pyright summaries (`collect_type_signals`), then
   normalize the results onto repo-relative paths. Missing reports simply yield zero
   errors so the run remains best-effort.
4. **coverage** — Parse Cobertura-style XML (when present) and emit per-file ratios.
   The stage is skipped when the file is absent, which keeps local runs fast.
5. **config-index** — Scan config files (YAML/TOML/JSON/Markdown) once and remember
   which module directories reference them. This feeds the slice packs and overlay hints.
6. **tagging-rules** — Load YAML overrides (or fall back to defaults) and validate the
   rule dictionary before tagging begins.
7. **index** — For every discovered file:
   - gather SCIP symbols,
   - enforce a `--max-file-bytes` limit,
   - run `libcst_bridge.index_module`,
   - call Tree-sitter for outlines,
   - merge type errors, doc metrics, annotation ratios, and AST traits into a
     `ModuleRecord`.
   Every failure (read errors, parser crashes, outline issues) is converted into a
   typed `EnrichmentError` token and stored on the row's `errors` list rather than
   aborting the run.
8. **analytics** — Attach graph metadata (import fan-in/out, SCCs), use-graph counts,
   config references, doc/coverage snapshots, hotspots, and overlay hints. Stage timings
   include counts for coverage rows and hotspot entries.
9. **tagging** — Feed module traits into the rule engine (`infer_tags`), record reasons,
   and add tags like `cli`, `tests`, or `overlay-needed`.
10. **write-*** — Emit JSONL/Markdown/Parquet artifacts. Each writer stage logs how
    many records were persisted (e.g., module rows, import edges, uses edges) and the
    final `repo_map.json` includes both `tags` and `tag_counts` for dashboards.

## CLI usage

```bash
codeintel-enrich \
  --root . \
  --scip build/index.scip.json \
  --out build/enrich \
  --pyrefly-json build/pyrefly.json \
  --tags-yaml codeintel_rev/enrich/tagging_rules.yaml \
  all
```

The `all`/`run` commands execute the entire stage flow described above. Narrow commands
(`graph`, `typedness`, `hotspots`, `overlays`, etc.) share the same discovery and ingestion
stages but only execute the writers relevant to that command. All options are declared on
the Typer command functions so `--help` always reflects the current surface.

To materialize the `modules.jsonl` data into DuckDB for downstream SQL analysis:

```bash
codeintel-enrich to-duckdb --modules-jsonl build/enrich/modules/modules.jsonl --db build/enrich/enrich.duckdb
```

The command is idempotent on `path` and will upsert rows as the scanner regenerates them.

Key options:

| Option | Description |
| --- | --- |
| `--root PATH` | Repository root or subdir to scan (defaults to `$PWD`). |
| `--scip PATH` | Path to the SCIP JSON index (`index.scip.json`). Required. |
| `--out PATH` | Output directory for modules, graphs, analytics, etc. |
| `--pyrefly-json PATH` | Optional Pyrefly JSON/JSONL report used in the type-signal stage. |
| `--tags-yaml PATH` | Optional YAML rules to override default tagging heuristics. |
| `--max-file-bytes N` | Skip files larger than `N` bytes but record a structured error. |

## Outputs

All artifacts live under `OUT_DIR/` (default `codeintel_rev/io/ENRICHED/`) and are
idempotent — re-running the CLI overwrites previous results with the same filenames:

| Path | Description |
| --- | --- |
| `modules/modules.jsonl` | Canonical `ModuleRecord` rows (LibCST + Tree-sitter + type signals). |
| `modules/*.md` | Per-module Markdown briefs (imports, defs, tags, coverage, owners). |
| `repo_map.json` | Summary (`module_count`, `symbol_edge_count`, `tag_counts`, timestamp). |
| `graphs/imports.parquet` | Import edges for DAG/SCC analysis. |
| `graphs/uses.parquet` | Use-graph linking definitions to references. |
| `graphs/symbol_graph.json` | SCIP symbol → file edges. |
| `analytics/typedness.parquet` | Annotation ratios, type error counts, untyped defs. |
| `analytics/hotspots.parquet` | Hotspot score + fan-in/out + usage counts. |
| `analytics/ownership.parquet` | Owners, churn, bus-factor metrics. |
| `docs/doc_health.parquet` | Doc summaries and coverage of doc sections. |
| `coverage/coverage.parquet` | Line and def coverage ratios per module. |
| `slices/` | LLM-ready slice packs (JSON + Markdown) keyed by stable slice IDs. |

All writers fall back to JSONL when optional dependencies (PyArrow, DuckDB) are missing,
keeping the pipeline runnable on minimal hosts.

## Failure handling & observability

- Every stage logs `stage=<name> event=start|finish` with counts and duration (in seconds).
- Module-level failures never crash the run — `ModuleRecord.add_error` records a token like
  `index|libcst|SyntaxError('...')` and the row stays in `modules.jsonl`.
- Stage-level failures (e.g., missing `--scip`) raise a typed `StageError` that Typer
  surfaces without a traceback and with a friendly `[stage] reason` message.
- `repo_map.json` can be used as a quick sanity check for dashboards. The smoke test asserts
  on its presence and correct counts.

For troubleshooting, rerun with `LOG_LEVEL=DEBUG` to see both start and finish events for
each stage, then inspect the `errors` list on the affected module rows.
