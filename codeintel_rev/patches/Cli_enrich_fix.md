You’re exactly right about the root cause: in **Typer** (Click), options are frozen into the command **at registration time**. When a function is first registered with `@app.command` (or `app.command(...)`), Typer inspects the function signature and builds a `Command` with the options/arguments it finds. If you later wrap that function and call `typer.Option(...)` “manually”, Typer doesn’t see those new parameters—your command keeps the original, option‑less signature. That’s why your `--root/--scip/...` flags disappeared.

Below is a **drop‑in fix** that:

* moves the shared flags to an **`@app.callback`** (global options), stored in `ctx.obj`
* adds explicit **subcommands** that read those values from `ctx.obj`
* avoids `Annotated[..., Option(...)=...]` edge cases by using the simpler, widely‑supported `param: Type = typer.Option(...)` form (works with your pinned `typer<0.20.0`) 
* keeps all of your existing enrichment logic (LibCST indexing, SCIP reading, Tree‑sitter outline, type integration) intact—the subcommands simply call the same helpers you already import and use in `cli_enrich.py`

---

## Why the manual “wrapper + `Option` calls” failed

* **Click** attaches options via decorators to a function **before** it becomes a `Command`. Wrapping a function *after* registration doesn’t mutate the already‑created `Command`’s parameters.
* **Typer** derives options from the function signature at decoration time and caches them; calling `Option(...)` inside another decorator won’t retrofit parameters into an already‑built command object.
* Using `Annotated[..., Option(...)] = ...` with `...` (Ellipsis) for required defaults can fail on older Typer versions and with complex defaults; the plain `param=typer.Option(...)` pattern is the least surprising and works well on Typer 0.9–0.12 (your pin). 

---

## Patch: make the shared flags global via `@app.callback`, read them in subcommands

> **What this does**
>
> * Declares global options one time (`--root`, `--scip`, `--out`, `--pyrefly-json`, `--tags-yaml`).
> * Stores them on `ctx.obj` for reuse across subcommands.
> * Provides a `run` subcommand that invokes your current enrichment pipeline exactly as before.
> * (Optional) Provides `overlay-one` and `overlay-batch` subcommands if you’ve kept overlay generation (they call your existing helpers).

```diff
--- a/codeintel_rev/cli_enrich.py
+++ b/codeintel_rev/cli_enrich.py
@@
-from collections.abc import Iterable, Mapping, Sequence
-from dataclasses import asdict, dataclass
-from datetime import UTC, datetime
-from pathlib import Path
-from typing import Any
-
-import typer
-
-from codeintel_rev.enrich.libcst_bridge import ImportEntry, index_module
-from codeintel_rev.enrich.output_writers import write_json, write_jsonl, write_markdown_module
-from codeintel_rev.enrich.scip_reader import Document, SCIPIndex
-from codeintel_rev.enrich.stubs_overlay import generate_overlay_for_file
-from codeintel_rev.enrich.tagging import ModuleTraits, infer_tags, load_rules
-from codeintel_rev.enrich.tree_sitter_bridge import build_outline
-from codeintel_rev.enrich.type_integration import TypeSummary, collect_pyrefly, collect_pyright
+from collections.abc import Iterable, Mapping, Sequence
+from dataclasses import asdict, dataclass
+from datetime import UTC, datetime
+from pathlib import Path
+from typing import Any, Optional, cast
+
+import typer
+
+from codeintel_rev.enrich.libcst_bridge import ImportEntry, index_module
+from codeintel_rev.enrich.output_writers import write_json, write_jsonl, write_markdown_module
+from codeintel_rev.enrich.scip_reader import Document, SCIPIndex
+from codeintel_rev.enrich.stubs_overlay import generate_overlay_for_file
+from codeintel_rev.enrich.tagging import ModuleTraits, infer_tags, load_rules
+from codeintel_rev.enrich.tree_sitter_bridge import build_outline
+from codeintel_rev.enrich.type_integration import TypeSummary, collect_pyrefly, collect_pyright
@@
-EXPORT_HUB_THRESHOLD = 10
-
-ROOT_OPTION = typer.Option(Path(), "--root", help="Repo or subfolder to scan.")
-SCIP_OPTION = typer.Option(..., "--scip", exists=True, help="Path to SCIP index.json")
-OUT_OPTION = typer.Option(
-    Path("codeintel_rev/io/ENRICHED"),
-    "--out",
-    help="Output directory for enrichment artifacts.",
-)
-PYREFLY_OPTION = typer.Option(
-    None,
-    "--pyrefly-json",
-    help="Optional path to a Pyrefly JSON/JSONL report.",
-)
-TAGS_OPTION = typer.Option(None, "--tags-yaml", help="Optional tagging rules YAML.")
+EXPORT_HUB_THRESHOLD = 10
@@
-app = typer.Typer(
-    add_completion=False,
-    help="Combine SCIP + LibCST + Tree-sitter + type checker signals into a repo map.",
-)
+app = typer.Typer(add_completion=False,
+    help="Combine SCIP + LibCST + Tree-sitter + type checker signals into a repo map.")
@@
-@dataclass(slots=True, frozen=True)
-class ScipContext:
-    """Convenience wrapper around SCIP lookup helpers."""
-
-    index: SCIPIndex
-    by_file: Mapping[str, Document]
+@dataclass(slots=True, frozen=True)
+class ScipContext:
+    """Convenience wrapper around SCIP lookup helpers."""
+    index: SCIPIndex
+    by_file: Mapping[str, Document]
@@
-@dataclass(slots=True, frozen=True)
-class TypeSignals:
-    """Aggregate Pyright and Pyrefly summaries."""
-
-    pyright: TypeSummary | None
-    pyrefly: TypeSummary | None
+@dataclass(slots=True, frozen=True)
+class TypeSignals:
+    """Aggregate Pyright and Pyrefly summaries."""
+    pyright: TypeSummary | None
+    pyrefly: TypeSummary | None
+
+@dataclass(slots=True, frozen=True)
+class CommonOpts:
+    root: Path
+    scip: Path
+    out: Path
+    pyrefly_json: Optional[Path]
+    tags_yaml: Optional[Path]
+
+@app.callback()
+def global_options(
+    ctx: typer.Context,
+    root: Path = typer.Option(Path("."), "--root", help="Repo or subfolder to scan.",
+                              exists=True, file_okay=False, dir_okay=True, readable=True),
+    scip: Path = typer.Option(..., "--scip", help="Path to SCIP index.json",
+                              exists=True, readable=True),
+    out: Path = typer.Option(Path("codeintel_rev/io/ENRICHED"),
+                              "--out", help="Output directory for artifacts."),
+    pyrefly_json: Optional[Path] = typer.Option(None, "--pyrefly-json",
+                              help="Optional path to a Pyrefly JSON/JSONL report."),
+    tags_yaml: Optional[Path] = typer.Option(None, "--tags-yaml",
+                              help="Optional tagging rules YAML."),
+) -> None:
+    """
+    Global options shared by all subcommands. Values are stored in ctx.obj.
+    """
+    ctx.obj = CommonOpts(root=root, scip=scip, out=out,
+                         pyrefly_json=pyrefly_json, tags_yaml=tags_yaml)
@@
-def main(
-    root: Path = ROOT_OPTION,
-    scip: Path = SCIP_OPTION,
-    out: Path = OUT_OPTION,
-    pyrefly_json: Path | None = PYREFLY_OPTION,
-    tags_yaml: Path | None = TAGS_OPTION,
-) -> None:
-    out.mkdir(parents=True, exist_ok=True)
-    scip_index = SCIPIndex.load(scip)
+def _run_pipeline(root: Path, scip: Path, out: Path,
+                  pyrefly_json: Optional[Path], tags_yaml: Optional[Path]) -> None:
+    out.mkdir(parents=True, exist_ok=True)
+    scip_index = SCIPIndex.load(scip)
@@
-    # Optional type check summaries
-    t_pyright = collect_pyright(str(root))
-    t_pyrefly = collect_pyrefly(str(pyrefly_json) if pyrefly_json else None)
+    # Optional type check summaries
+    t_pyright = collect_pyright(str(root))
+    t_pyrefly = collect_pyrefly(str(pyrefly_json) if pyrefly_json else None)
@@
-    rules = load_rules(str(tags_yaml) if tags_yaml else None)
+    rules = load_rules(str(tags_yaml) if tags_yaml else None)
@@
-    for fp in _iter_files(root):
+    for fp in _iter_files(root):
@@
-    # === write outputs (helpers unchanged) ===
+    # === write outputs (helpers unchanged) ===
     _write_module_outputs(module_rows, out)
     _write_graph_outputs(PipelineResult(use_graph=use_graph,
                                         import_graph=import_graph,
                                         symbol_edges=symbol_edges), out)
     _write_typedness_output(PipelineResult(module_rows=module_rows), out)
     _write_doc_output(PipelineResult(module_rows=module_rows), out)
     _write_coverage_output(PipelineResult(coverage_rows=coverage_rows), out)
     _write_hotspot_output(PipelineResult(hotspot_rows=hotspot_rows), out)
     _write_config_output(PipelineResult(config_index=config_records), out)
@@
+@app.command("run")
+def run(ctx: typer.Context) -> None:
+    """
+    Run the full enrichment pipeline using global options.
+    """
+    opts = cast(CommonOpts, ctx.obj)
+    _run_pipeline(opts.root, opts.scip, opts.out, opts.pyrefly_json, opts.tags_yaml)
+
+@app.command("overlay-one")
+def overlay_one(
+    ctx: typer.Context,
+    path: Path = typer.Argument(..., help="Python module path (under --root) to stub."),
+) -> None:
+    """
+    Generate a .pyi overlay for a single file (if warranted).
+    """
+    opts = cast(CommonOpts, ctx.obj)
+    py_file = (opts.root / path).resolve()
+    result = generate_overlay_for_file(py_file, opts.root, SCIPIndex.load(opts.scip))
+    meta_out = opts.out / "stubs" / (path.with_suffix(".json").name)
+    write_json(meta_out, {"created": result.created,
+                          "pyi_path": str(result.pyi_path) if result.pyi_path else None,
+                          "exports_resolved": {k: sorted(v) for k, v in result.exports_resolved.items()}})
+
+@app.command("overlay-batch")
+def overlay_batch(ctx: typer.Context) -> None:
+    """
+    Generate overlays for all modules under --root where policy deems useful.
+    """
+    opts = cast(CommonOpts, ctx.obj)
+    scip = SCIPIndex.load(opts.scip)
+    for fp in _iter_files(opts.root):
+        generate_overlay_for_file(fp, opts.root, scip)
@@
-def cli() -> None:  # optional alias if you expose as console_script
-    typer.run(main)
+def main() -> None:  # console_script entrypoint
+    app()
```

**What to expect after applying the patch**

* `codeintel-enrich --help` now shows the **global flags** and the available **subcommands** (`run`, `overlay-one`, `overlay-batch`).
* `codeintel-enrich --root . --scip index.json run` executes the same pipeline you had in your previous single‑command `main`, just moved behind a subcommand that reads globals from `ctx.obj`.
* The overlay commands reuse your existing generator without re‑parsing options. They’re optional; you can keep just `run` if you prefer.
* All previously‑imported helpers stay the same; the code above only re‑plumbs the CLI layer. (Those imports and helpers are already present and used in your file: LibCST visitor/index, SCIP reader, Tree‑sitter outline, type integration.)

> **Note on optional imports**
> If you gate heavy dependencies elsewhere, you already have `gate_import` in `codeintel_rev.typing` to defend optional deps—keep using that strategy where needed; it’s orthogonal to the Typer fix. 

---

## Minimal CLI smoke test (ensures flags show up & a no‑op run works)

Add `tests/test_cli_enrich_cli.py`:

```python
# SPDX-License-Identifier: MIT
from pathlib import Path
from typer.testing import CliRunner

from codeintel_rev.cli_enrich import app

runner = CliRunner()

def test_help_shows_globals_and_subcommands():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "--root" in r.stdout
    assert "--scip" in r.stdout
    assert "run" in r.stdout

def test_run_with_empty_scip(tmp_path: Path, monkeypatch):
    # Minimal tree: one file + empty SCIP index
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text('"""pkg doc."""\n', encoding="utf-8")
    scip = tmp_path / "index.json"
    scip.write_text('{"documents": []}', encoding="utf-8")
    out = tmp_path / "out"

    result = runner.invoke(
        app,
        ["--root", str(tmp_path), "--scip", str(scip), "--out", str(out), "run"],
    )
    assert result.exit_code == 0, result.stdout
    # basic artifact directories created
    assert (out / "modules").exists()
```

This doesn’t need the whole repo—it verifies Typer wiring end‑to‑end.

---

## Guardrails & quick checks

* `--help` for the app and for subcommands should now list the shared flags.
* Running without a subcommand prints help (since options live on the callback).
* If you later add more subcommands, you **don’t** need to duplicate flags—just read `opts = cast(CommonOpts, ctx.obj)` again.

---

## Why this approach is robust

* **Typer‑native**: Global options live in `@app.callback`, the officially supported place for them.
* **No magic wrappers**: Every option is declared in the signature of the callback or subcommand that Typer registers.
* **Version‑compatible**: Uses the stable `param=typer.Option(...)` idiom, avoiding Annotated pitfalls on older Typer. (Your `pyproject.toml` pins Typer `<0.20.0`.) 

---

### References to the helpers this CLI calls (unchanged)

* **SCIP reader** with tolerant JSON schema handling. 
* **LibCST index** for imports/defs/exports/docstrings. 
* **Tree‑sitter outline** for fast structural hints. 
* **Type integration** for Pyrefly/Pyright summaries. 

If you want, I can also trim the `run` function body further by extracting the pipeline core into a standalone `_pipeline(root, scip, out, pyrefly_json, tags_yaml)` and keeping the CLI file very thin—but the patch above is enough to restore your flags and subcommands cleanly.
