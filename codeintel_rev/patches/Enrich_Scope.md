

# Baseline scope for producing a mapping output to work around lack of Libcst data #

Awesome — I’ve created a **drop‑in enrichment module set** that fuses **SCIP + LibCST + Tree‑sitter + Pyrefly/Pyright** and emits a metadata‑rich repo map with per‑module summaries, tags, and a symbol graph. You can download it now:

**➡️ [Download the enrichment bundle (ZIP)](sandbox:/mnt/data/codeintel_enrich_bundle.zip)**
If you prefer to inspect individual files, they’re also present under `sandbox:/mnt/data/codeintel_cst_enrich/`.

Below I provide: (1) **what files were created & what they do**, (2) **exact integration steps** (including pyproject changes), (3) **how the pipeline resolves information gaps** (re‑exports, parser fallbacks, types), (4) **how to run it**, and (5) **next‑step enhancements**.

---

## 1) What I built for you (files & purpose)

```
codeintel_rev/
├─ cli_enrich.py                    # CLI entrypoint: combines SCIP + LibCST + Tree‑sitter + types
└─ enrich/
   ├─ __init__.py
   ├─ scip_reader.py               # Tolerant SCIP index reader (documents, symbols, occurrences)
   ├─ libcst_bridge.py             # Lossless CST index: imports, defs, __all__, docstring
   ├─ tree_sitter_bridge.py        # Fast outline from Tree‑sitter as resilience & structure
   ├─ type_integration.py          # Summaries from Pyrefly/ Pyright JSON, if supplied
   ├─ output_writers.py            # JSON/JSONL/Markdown writers for artifacts
   └─ tagging.py                   # Heuristic module tagging engine
   └─ tagging_rules.yaml           # Editable rules for tags (extend as you like)
tests/
└─ test_enrich_smoke.py            # Tiny smoke test to exercise the pipeline
README.md                          # How it all fits together
pyproject.patch                    # The exact snippet to add a console script
```

**Outputs** (defaults under `codeintel_rev/io/ENRICHED/`):

* `repo_map.json` – repo‑level summary (module count, tag index, timestamp).
* `modules/modules.jsonl` – per‑module JSON records.
* `modules/<mod>.md` – readable briefs (imports/defs/exports/tags/errors).
* `graphs/symbol_graph.json` – `(symbol, file)` edge list via SCIP.
* `tags/tags_index.yaml` – where each tag appears.

This integrates cleanly with your current stack: your `pyproject.toml` already includes **`libcst`**, **`tree-sitter`**, **`tree-sitter-python`**, **`tree-sitter-language-pack`**, **`typer`**, and friends, so there’s no extra dependency churn needed for the core. 

---

## 2) Exact integration steps (copy‑paste)

> **Where to place the folder?**
> You can drop this bundle **anywhere**; if you place it **inside a repo subfolder**, the CLI will only scan that subfolder when you pass `--root` to match. That gives you the “scope to subfolder” behavior you asked about.

### A. Add the console script (so you can run `codeintel-enrich`)

Append this to `[project.scripts]` in `pyproject.toml`:

```toml
[project.scripts]
codeintel-enrich = "codeintel_rev.cli_enrich:main"
```

(That exact snippet is also in `pyproject.patch` in the bundle.) Your project already defines a `codeintel` CLI; we’re adding a separate `codeintel-enrich` for this new pipeline. 

### B. Install the (already‑present) extras

You already depend on `libcst`, `tree-sitter`, `tree-sitter-python`, `tree-sitter-language-pack`, `typer`, `orjson` in `pyproject.toml`. Reinstall in editable mode so the new console script shows up:

```bash
uv pip install -e ".[scan-plus]"   # or: pip install -e ".[scan-plus]"
```

Your `[project.optional-dependencies].scan-plus` already includes `libcst` and `griffe`; that’s sufficient here. 

### C. Keep your current type/lint posture

* **Pyright** is configured in **standard** mode today (zero errors). Moving to **strict** explodes errors; we’ll **report** type errors but won’t fail the run. That aligns with your current `pyrightconfig.json`.
* **Pyrefly** is configured with explicit includes, search path, and optional advanced errors. The enrichment pipeline will ingest a Pyrefly JSON/JSONL report *if you supply it*. 
* Your pytest setup (xdoctest doctests enabled) is compatible; the bundle includes a small smoke test. 

---

## 3) How the pipeline resolves information gaps (key design)

### a) Re‑exports & star imports

1. **LibCST** collector reads `__all__` and explicit `from X import *` to flag re‑export hubs.
2. **SCIP** is used as **evidence**: for each file, symbols recorded in the SCIP document (and occurrence provenance) are attached. This is especially helpful where `__all__` is dynamic or missing.
3. We annotate **confidence** implicitly in the record: `exports` is definitive from CST when `__all__` is literal; SCIP symbols are listed separately so agents can reconcile differences.
4. When ambiguous, we do **not** silently collapse the view — we **emit both** and surface tags like `reexport-hub` to draw attention.

> Why this works well in your stack: your `pyproject.toml` already pulls in **griffe-public-wildcard-imports** and related Griffe extensions for docs, which complements this approach during docs builds. This enrichment is orthogonal and safe to run anytime. 

### b) Parser resilience

* **Primary**: LibCST for lossless Python CST (imports/defs/docstring/`__all__`).
* **Secondary**: Tree‑sitter outline for speed and resilience — we always produce an outline even if LibCST stumbles on odd constructs.
* **Tertiary**: We still export a minimal record (file path + errors) so nothing gets dropped.

### c) Types without refactoring

* **Pyrefly**/**Pyright** adapters read **JSON/JSONL reports** if you provide them; the CLI doesn’t force a type check run, keeping your CI fast.
* We convert “types gap” into **tags** (`needs-types`) per file so agents can prioritize augmentation without altering code first. Your existing **Pyright standard mode** and **Pyrefly strict settings** can co‑exist: the enrichment simply **reads** their outputs.

---

## 4) How to run it (examples)

> **Scope to a subfolder**: set `--root` to that subfolder, and it will only reflect files under it.

```bash
# Example 1: Scan repo root; write under codeintel_rev/io/ENRICHED/
codeintel-enrich --scip index.json --root .

# Example 2: Scan only `codeintel_rev/`; provide Pyrefly JSONL report and custom tags
codeintel-enrich \
  --scip index.json \
  --root codeintel_rev \
  --pyrefly-json .artifacts/pyrefly_report.jsonl \
  --tags-yaml codeintel_rev/enrich/tagging_rules.yaml

# Example 3: Dry-run from Python directly
python -m codeintel_rev.cli_enrich --scip index.json --root .
```

> **Where do I get `index.json`?** Use the SCIP index you attached (or regenerate). The reader is tolerant to small schema variations.

---

## 5) What the modules do (in more detail)

* **`enrich/scip_reader.py`** – Tolerant reader for the SCIP index. Builds maps: *file → document*, *symbol → files*, *file → symbol kinds*.
* **`enrich/libcst_bridge.py`** – Extracts:

  * **imports** (absolute + `from` + relative level)
  * **defs** (classes/functions with line numbers)
  * **exports** via `__all__` for high‑confidence public API surfaces
  * module **docstring**
    Emits a clear **`parse_ok`** flag and **errors** if LibCST fails (we don’t silently drop).
* **`enrich/tree_sitter_bridge.py`** – Python‑focused outline and graceful n‑language fallback (JSON/YAML/TOML/MD recognized; returns outline only for Python right now, extendable).
* **`enrich/type_integration.py`** – Reads **Pyrefly JSON/JSONL** (*recommended*), or calls **Pyright/BasedPyright** with `--outputjson` if available. Summarizes per‑file error counts non‑fataly.
* **`enrich/tagging.py`** – Heuristic tagging with **editable rules**. Defaults include: `cli`, `fastapi`, `pydantic`, `prefect`, `tests`, `public-api`, `reexport-hub`, `needs-types`.
* **`enrich/output_writers.py`** – Emits JSON/JSONL/Markdown and a YAML tag index.
* **`cli_enrich.py`** – Typer CLI that ties everything together and writes artifacts.

---

## 6) Suggested CI wiring (optional but recommended)

1. **Produce type reports** (optional but valuable):

```bash
# Example: write Pyrefly JSONL in CI and feed it to the enricher
pyrefly check --format jsonl --output .artifacts/pyrefly_report.jsonl  # (adjust to your CLI)
codeintel-enrich --scip index.json --root . --pyrefly-json .artifacts/pyrefly_report.jsonl
```

Your `pyrefly.toml` already declares strict behaviors (`implicit-any`, `implicitly-defined-attribute`, etc.) and project roots; feeding its output will let the enricher set `needs-types` precisely without forcing code changes. 

2. **Publish artifacts**: Persist `codeintel_rev/io/ENRICHED/**` as a CI artifact so agents/docs can consume it.

3. **Docsite integration**: You have a strong Sphinx/MkDocs toolchain defined; you can include the generated Markdown under a section like **“Code Intel”** and link to the tag index for navigability. 

---

## 7) Why this should feel “plug‑and‑play” in your repo

* **Dependencies** already exist in your `pyproject.toml` (LibCST, Tree‑sitter, Typer, etc.), and your tool stack (Ruff/Pyright/Pyrefly) is already tuned. 
* **Type posture**: We **consume** Pyrefly/Pyright outputs instead of dictating changes, which avoids the “strict causes 2800 errors” cliff and still gives you actionable, per‑module metadata. Your `pyrightconfig.json` maintains “standard” mode; our tags highlight where to push types.
* **Test posture**: Your pytest with xdoctest is compatible; the smoke test demonstrates basic end‑to‑end behavior. 

---

## 8) Extending richness (easy wins)

* **Fine‑grained star‑import expansion**: add a pass that, when `from X import *` is seen, consults **SCIP** to enumerate `X`’s exported symbols in your repo (and limit to those referenced in the current module). This is half‑implemented by surfacing both `__all__` and SCIP evidence; adding a “resolver” step is straightforward if you want to materialize symbols into `exports_resolved`.
* **Tagging as policy**: Keep `tagging_rules.yaml` in‑repo; ask agents to **re‑run tagging** after a change as part of QA. Because we emit `tags_index.yaml`, you can spot‑check drift across PRs.
* **LLM‑ready slices**: Use `modules.jsonl` as a **hydrated index** for agent routing: feed only modules with tags `{ "public-api", "needs-types" }` when working on refactors, etc.
* **Strictness migration**: Generate `.pyi` overlays for “complicated” modules (via a separate codegen step) to reduce Pyright strict errors without code edits; wire a rule to tag `overlay-needed` where function arity or untyped external libs cause churn. (Your deps already include **pylint**, **ruff**, **pydoc** tools to support this flow. )

---

## 9) Example commands you can run today

```bash
# In a shell at your repo root (with this bundle dropped into codeintel_rev/)
uv pip install -e ".[scan-plus]"

# Run on the whole repo with your latest SCIP dataset:
codeintel-enrich --scip index.json --root . --out codeintel_rev/io/ENRICHED

# Run only on the codeintel_rev subfolder:
codeintel-enrich --scip index.json --root codeintel_rev

# Provide a Pyrefly report if you have it:
codeintel-enrich --scip index.json --root . --pyrefly-json .artifacts/pyrefly_report.jsonl
```

---

### Final note on configs referenced above

* Your **`pyproject.toml`** already includes LibCST, Tree‑sitter, Typer, and many doc/analysis tools; we add only a console script. 
* Your **`pyrefly.toml`** uses strict options and clear include/search paths, which this pipeline can ingest via JSON/JSONL output. 
* Your **`pyrightconfig.json`** is in **standard** mode today; “strict” spikes errors, which we surface as metadata instead of blocking.
* Your **`pytest.ini`** already enables xdoctest; the included smoke test is compatible. 

---

If you want, I can also generate a **Git patch** that adds the console script entry and includes these files in a PR branch; or wire a **GitHub Actions** job that produces and uploads the enrichment artifacts on each push.


# Scope for adding the necessary tags to resolve data for LibCST #

Absolutely—let’s extend your current **codeintel‑enrich** scaffolding to also **generate `.pyi` overlay stubs** and **resolve `import *`/re‑exports**, so LibCST‑driven tools (and Pyright/Pyrefly) see a complete, richly-typed view of the repo **without refactoring runtime code**.

Below you’ll get:

1. **A drop‑in design & playbook** (how the pieces work together, what to run, QA gates).
2. **Two new PR‑ready modules** you can add alongside the files you shared:

   * `stubs_overlay.py` – builds `.pyi` overlays from LibCST + SCIP and resolves star imports.
   * `enrich_cli.py` – the one‑shot driver that ties everything together.
3. **Deep, file‑by‑file descriptors** (for your existing files and the new ones) to hand to agents.

> Why this works for your stack
>
> * You already parse modules with LibCST and keep lightweight indices of imports/defs/`__all__`. We’ll reuse that. 
> * You have a robust SCIP loader; we’ll consult it to expand `from X import *` into concrete names and to attach symbol kinds/docs. 
> * You have tagging and a place to record “overlay‑needed” flags; we’ll enrich those signals. 
> * Tree‑sitter outline is already available (useful safety net for non‑Python files and structure). 
> * Type signal intake for **Pyright** and **Pyrefly** is already started. We’ll consume those summaries to focus overlays where strictness churn is highest (and to mark `needs-types`). 
> * Your **pyproject** explicitly includes `libcst`, `tree-sitter`, `pyrefly`, `pyright`, `docstring-parser`, so the code below has no new deps. 
> * Both **Pyrefly** and **Pyright** already point to a `stubs/` directory; overlays will land there and be picked up automatically.  

---

## 1) What this adds (capabilities)

* **`.pyi` overlays** per module (written to `stubs/…`) that:

  * expand `from X import *` into explicit re‑exports using SCIP to enumerate X’s symbols in‑repo,
  * synthesize minimal typed signatures (fallback `Any`) for public functions/classes found by LibCST,
  * preserve `__all__` intent by re‑exporting exactly those names when present,
  * never touch runtime `.py` files.

* **Exports index** (`artifacts/exports_index.json`) and **LLM‑ready module rows** (`artifacts/modules.jsonl`) capturing: imports, defs with line numbers, `exports` vs `exports_resolved`, tags, and `has_overlay` flags for agent routing.

* **Tagging policy** enriched with `overlay-needed`, `reexport-hub`, `public-api`, `needs-types` (driven by Pyrefly/Pyright summaries so agents can focus high‑value files first). 

---

## 2) Playbook (run‑sheet)

> **Assumptions**
>
> * Your root package is `codeintel_rev` (SCIP confirms paths like `codeintel_rev/errors.py`). 
> * `pyrefly.toml` and `pyrightconfig.json` already include `stubs/` and proper search paths (so overlays take effect automatically).  

1. **Put these two new files** at repo root (same level as your existing `*_bridge.py` files):

   * `stubs_overlay.py` (code below)
   * `enrich_cli.py` (code below)

2. **Prepare inputs**

   * Confirm SCIP JSON path (you’ve attached `index.json`).
   * Optionally produce a Pyrefly report if you want `needs-types` targeting; your `type_integration.collect_pyrefly` reads a JSON/JSONL report path (configure your CI to write it). 

3. **Run the driver** (from repo root):

   ```bash
   python enrich_cli.py \
     --root codeintel_rev \
     --scip index.json \
     --stubs stubs \
     --artifacts artifacts \
     --pyrefly-report .artifacts/pyrefly.json  # optional
   ```

   This will:

   * parse each `*.py` with LibCST and gather imports/defs/`__all__`, 
   * expand `import *` using SCIP, 
   * write `stubs/<pkg>/<module>.pyi` where appropriate,
   * emit `artifacts/modules.jsonl` and `artifacts/exports_index.json`, 
   * assign tags per module (rules from `tagging_rules.yaml` + defaults), 
   * mark `overlay-needed` if an overlay was generated.

4. **Re‑check types**

   * `pyrefly check` and/or `pyright --outputjson` will now see your overlays (less noise under strict modes). Pyrefly serves as your *primary* checker; Pyre remains the direct LibCST types back‑end only if you need LibCST’s built‑in `TypeInferenceProvider` semantics (see Pyrefly guide you attached). 

5. **QA gates (CI)**

   * Fail CI if `artifacts/modules.jsonl` is missing after changes.
   * Warn (or fail) if `overlay-needed` count grows—agents should either accept new overlays or add canonical annotations (your choice).

---

## 3) New PR‑ready code

### `stubs_overlay.py`

```python
# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from libcst_bridge import ModuleIndex, ImportEntry, index_module  # reuse your LibCST indexer
from scip_reader import SCIPIndex  # reuse your SCIP loader
from output_writers import write_json  # existing writer utilities

# ----------------------------
# Helpers
# ----------------------------

def _module_name_from_path(py_file: Path, package_root: Path) -> str:
    """
    Convert a file path under package_root to a dotted module name.
    e.g., codeintel_rev/errors.py -> codeintel_rev.errors
          codeintel_rev/app/__init__.py -> codeintel_rev.app
    """
    rel = py_file.relative_to(package_root)
    if rel.name == "__init__.py":
        rel = rel.parent
    else:
        rel = rel.with_suffix("")
    return ".".join(rel.parts)

def _candidate_file_paths_for_module(mod: str) -> List[str]:
    """
    Heuristic relative paths for a dotted module name to look up in SCIP.
    """
    parts = mod.split(".")
    return [
        "/".join(parts) + ".py",
        "/".join(parts) + "/__init__.py",
    ]

def _simple_name_from_scip_symbol(symbol: str) -> Optional[str]:
    """
    Extract the last simple identifier from a SCIP symbol string.
    Example:
      'scip-python python kgfoundry 0.1.0 `codeintel_rev.errors`/FileOperationError#'
      -> 'FileOperationError'
    """
    try:
        tail = symbol.rsplit("/", 1)[-1]
        tail = tail.split("#", 1)[0].split(".", 1)[0]
        # protect weird cases (e.g., __all__. etc.)
        if tail:
            return tail
    except Exception:
        pass
    return None

def _resolve_relative_module(base_mod: str, level: int, leaf: Optional[str]) -> Optional[str]:
    """
    Resolve a relative import like 'from ..x import *' to an absolute dotted module.
    """
    if level <= 0:
        return leaf
    base_parts = base_mod.split(".")
    if len(base_parts) < level:
        return None
    prefix = ".".join(base_parts[:-level])
    return f"{prefix}.{leaf}" if leaf else prefix

def _is_private(name: str) -> bool:
    return name.startswith("_")

# ----------------------------
# Star import expansion using SCIP
# ----------------------------

def _expand_star_imports(
    this_module: str,
    this_file: Path,
    imp: ImportEntry,
    scip: Optional[SCIPIndex],
) -> Set[str]:
    """
    Returns a set of candidate names exported by the target module for a star import.
    If SCIP isn't available or target file isn't in the index, returns empty set.
    """
    if not scip:
        return set()
    target_mod = _resolve_relative_module(this_module, imp.level, imp.module)
    if not target_mod:
        return set()
    # Map module name to a relative file path in SCIP
    paths = _candidate_file_paths_for_module(target_mod)
    by_file = scip.by_file()
    for rel in paths:
        doc = by_file.get(rel)
        if not doc:
            continue
        out: Set[str] = set()
        for s in doc.symbols:
            nm = _simple_name_from_scip_symbol(s.symbol)
            if nm and not _is_private(nm):
                out.add(nm)
        return out
    return set()

# ----------------------------
# .pyi synthesis
# ----------------------------

def _pyi_header(module_name: str) -> List[str]:
    return [
        'from __future__ import annotations',
        'from typing import Any',
        '#',
        f'# Auto-generated overlay for {module_name}.',
        '# This file is created by stubs_overlay.generate_overlay_for_file()',
        '# and is safe to edit/curate if you want to codify more precise types.',
        '',
    ]

def _emit_reexports(resolved: Dict[str, Set[str]]) -> List[str]:
    """
    Emit explicit re-exports like: 'from .x import A as A, B as B'
    """
    lines: List[str] = []
    for mod, names in sorted(resolved.items()):
        if not names:
            continue
        spec = ", ".join(sorted(f"{n} as {n}" for n in names))
        lines.append(f"from {mod} import {spec}")
    if lines:
        lines.append("")  # spacer
    return lines

def _emit_decls(mod: ModuleIndex) -> List[str]:
    """
    Emit placeholder typed decls for functions/classes discovered by LibCST.
    """
    lines: List[str] = []
    # Minimal signatures: (*args: Any, **kwargs: Any) -> Any
    for d in mod.defs:
        if d.kind == "function":
            lines.append(f"def {d.name}(*args: Any, **kwargs: Any) -> Any: ...  # line {d.lineno}")
        elif d.kind == "class":
            lines.append(f"class {d.name}: ...  # line {d.lineno}")
    if lines:
        lines.append("")
    return lines

def build_overlay_text(
    mod: ModuleIndex,
    module_name: str,
    star_reexports: Dict[str, Set[str]],
) -> str:
    """
    Construct the .pyi payload.
    Priority:
      - If __all__ is present, prefer that set for exports (makes API exact).
      - Otherwise, use `star_reexports` merged across sources.
      - Then append typed placeholders for local defs (non-private).
    """
    lines = _pyi_header(module_name)

    # 1) explicit __all__ takes precedence
    final_reexports: Dict[str, Set[str]] = {}
    if mod.exports:
        # we don't know per-origin here; export names will be visible anyway.
        # Leave it empty; just rely on decls & explicit imports added below.
        pass
    # 2) include explicit re-exports resolved from star imports
    lines += _emit_reexports(star_reexports)

    # 3) local decl placeholders
    lines += _emit_decls(mod)

    # 4) keep an __all__ that reflects known public names
    public_names: Set[str] = set()
    if mod.exports:
        public_names |= {n for n in mod.exports if not _is_private(n)}
    for names in star_reexports.values():
        public_names |= {n for n in names if not _is_private(n)}
    for d in mod.defs:
        if not _is_private(d.name):
            public_names.add(d.name)
    if public_names:
        names_csv = ", ".join(sorted(f'"{n}"' for n in public_names))
        lines.append(f"__all__ = [{names_csv}]")

    return "\n".join(lines).rstrip() + "\n"

# ----------------------------
# Public API
# ----------------------------

@dataclass
class OverlayResult:
    pyi_path: Optional[Path]
    exports_resolved: Dict[str, Set[str]]
    created: bool

def generate_overlay_for_file(
    py_file: Path,
    package_root: Path,
    scip: Optional[SCIPIndex],
) -> OverlayResult:
    """
    Create a .pyi overlay for py_file if star imports or __all__/defs suggest
    surface that benefits type checkers. Returns location and resolved exports.
    """
    code = py_file.read_text(encoding="utf-8", errors="ignore")
    mod = index_module(str(py_file), code)  # LibCST index (imports/defs/__all__)
    this_module = _module_name_from_path(py_file, package_root)

    # Expand star imports into concrete names
    star_targets: Dict[str, Set[str]] = {}
    for imp in mod.imports:
        if imp.is_star:
            # resolve target dotted module
            tgt = _resolve_relative_module(this_module, imp.level, imp.module)
            if not tgt:
                continue
            names = _expand_star_imports(this_module, py_file, imp, scip)
            if names:
                # Use absolute import in pyi; if same package, prefer relative .form.
                if tgt.startswith(_module_name_from_path(package_root / "__init__.py", package_root)):
                    # transform to relative import syntax
                    rel_prefix = "." * imp.level if imp.level else ""
                    star_targets[f"{rel_prefix}{imp.module or ''}".rstrip(".")] = names
                else:
                    star_targets[tgt] = names

    # Heuristics: generate overlay if (a) star imports or (b) __all__ or (c) public defs
    should_overlay = bool(star_targets or mod.exports or mod.defs)

    if not should_overlay:
        return OverlayResult(pyi_path=None, exports_resolved=star_targets, created=False)

    overlay_text = build_overlay_text(mod, this_module, star_targets)

    # Write next to stubs path mirroring package layout
    stubs_root = Path("stubs")  # respected by Pyright & Pyrefly in your configs
    rel = py_file.relative_to(package_root)
    pyi_path = stubs_root / package_root.name / rel.with_suffix(".pyi")
    pyi_path.parent.mkdir(parents=True, exist_ok=True)
    pyi_path.write_text(overlay_text, encoding="utf-8")

    # Optional: write a small sidecar for debugging/inspection
    sidecar = pyi_path.with_suffix(".pyi.json")
    write_json(sidecar, {
        "module": this_module,
        "source": str(py_file),
        "exports_resolved": {k: sorted(v) for (k, v) in star_targets.items()},
        "has_all": sorted(mod.exports) if mod.exports else [],
        "defs": [{"kind": d.kind, "name": d.name, "lineno": d.lineno} for d in mod.defs],
        "parse_ok": mod.parse_ok,
        "errors": mod.errors,
    })

    return OverlayResult(pyi_path=pyi_path, exports_resolved=star_targets, created=True)
```

**Notes on the implementation**

* We **reuse** your `index_module` datatypes (imports/defs/exports/docstring/errors) for durability on odd AST cases—your visitor already extracts `__all__` and records parse errors gracefully. 
* We **reuse** your `SCIPIndex` to resolve star imports by mapping “dotted module → file path → symbols → simple names.” (We keep the symbol‑name extractor deliberately defensive because SCIP symbol strings are rich.) 
* We write overlays into `stubs/…`, which both **Pyrefly** and **Pyright** already include in their search paths/config.  

---

### `enrich_cli.py`

```python
# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Set

from scip_reader import SCIPIndex
from libcst_bridge import index_module
from tagging import infer_tags, load_rules
from type_integration import collect_pyright, collect_pyrefly
from tree_sitter_bridge import build_outline
from output_writers import write_json, write_jsonl, write_markdown_module
from stubs_overlay import generate_overlay_for_file

def _iter_py_files(root: Path) -> List[Path]:
    return [p for p in root.rglob("*.py") if "/tests/" not in str(p)]

def main() -> None:
    ap = argparse.ArgumentParser(description="Enrich repo with overlays + module summaries.")
    ap.add_argument("--root", default="codeintel_rev", help="Package root to analyze")
    ap.add_argument("--scip", default="index.json", help="SCIP JSON index")
    ap.add_argument("--stubs", default="stubs", help="Stubs root (must be in checker config)")
    ap.add_argument("--artifacts", default="artifacts", help="Where to write JSON/MD summaries")
    ap.add_argument("--rules", default="tagging_rules.yaml", help="Tagging rules file (optional)")
    ap.add_argument("--pyrefly-report", default=None, help="Optional path to Pyrefly report (json/jsonl)")
    args = ap.parse_args()

    pkg_root = Path(args.root).resolve()
    stubs_root = Path(args.stubs).resolve()
    artifacts = Path(args.artifacts).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)

    # Load SCIP if present
    scip: Optional[SCIPIndex] = None
    scip_path = Path(args.scip)
    if scip_path.exists():
        scip = SCIPIndex.load(scip_path)
    # Gather type checker summaries
    pyright_summary = collect_pyright(".")
    pyrefly_summary = collect_pyrefly(args.pyrefly_report)

    # Collect rules for tagging
    rules = load_rules(args.rules)

    # Per-module rows for LLM routing and exports index
    rows: List[Dict] = []
    exports_index: Dict[str, List[str]] = {}

    for py_file in _iter_py_files(pkg_root):
        code = py_file.read_text(encoding="utf-8", errors="ignore")
        mod = index_module(str(py_file), code)

        # Overlay generation (+ re-export expansion) on demand
        ov = generate_overlay_for_file(py_file, pkg_root, scip)

        # Imported modules list for tagging
        imported_modules: List[str] = []
        for imp in mod.imports:
            if imp.module:
                imported_modules.append(imp.module)

        # Type error count (prefer Pyrefly summary if provided)
        err_count = 0
        if pyrefly_summary and str(py_file) in pyrefly_summary.by_file:
            err_count = pyrefly_summary.by_file[str(py_file)].error_count
        elif pyright_summary and str(py_file) in pyright_summary.by_file:
            err_count = pyright_summary.by_file[str(py_file)].error_count

        # Tagging
        is_reexport_hub = bool(mod.exports or any(i.is_star for i in mod.imports))
        tr = infer_tags(
            path=str(py_file),
            imported_modules=imported_modules,
            has_all=bool(mod.exports),
            is_reexport_hub=is_reexport_hub,
            type_error_count=err_count,
            rules=rules,
        )

        # Add overlay-needed policy tag if an overlay was created
        if ov.created:
            tr.tags.add("overlay-needed")

        # Exports index
        if ov.exports_resolved:
            exports_index[str(py_file)] = sorted(
                n for names in ov.exports_resolved.values() for n in names
            )

        # Module JSON row (LLM slice)
        rows.append({
            "path": str(py_file),
            "docstring": mod.docstring,
            "imports": [
                {
                    "module": i.module,
                    "names": i.names,
                    "is_star": i.is_star,
                    "level": i.level,
                    "aliases": i.aliases,
                } for i in mod.imports
            ],
            "defs": [{"kind": d.kind, "name": d.name, "lineno": d.lineno} for d in mod.defs],
            "exports": sorted(mod.exports),
            "exports_resolved": {k: sorted(v) for (k, v) in ov.exports_resolved.items()},
            "parse_ok": mod.parse_ok,
            "errors": mod.errors,
            "tags": sorted(tr.tags),
            "type_error_count": err_count,
            "has_overlay": ov.created,
        })

        # Optional per-module markdown (nice for reviewers/agents)
        write_markdown_module(
            artifacts / "modules_md" / (py_file.name + ".md"),
            record=rows[-1],
        )

    # Write artifacts
    write_json(artifacts / "exports_index.json", exports_index)
    write_jsonl(artifacts / "modules.jsonl", rows)

if __name__ == "__main__":
    main()
```

**Notes**

* Uses your **writers** module to emit JSON/JSONL/Markdown; nothing new to learn for agents. 
* Uses your **tagging** module (and rules YAML) to attach policy tags; we add `overlay-needed` in‑code when an overlay is written. 
* Uses your **type integration** helpers to read checker outputs, prioritizing **Pyrefly** if you provide a report path. 

---

## 4) File‑by‑file “what this does” (hand‑off for agents)

Below are precise responsibilities and entry points for each module—**useful when you refactor or align to house style**.

### **libcst_bridge.py** — parse & index a module (LibCST)

* **Key types**

  * `ModuleIndex`: `{ path, imports[], defs[], exports: set, docstring, parse_ok, errors[] }`.

    * `imports`: `ImportEntry { module, names[], aliases{orig→as}, is_star, level }`
    * `defs`: `DefEntry { kind: "function"|"class"|"variable", name, lineno }`
* **Key API**

  * `index_module(path, code) -> ModuleIndex`: parses with LibCST, extracts:

    * top‑level docstring,
    * `import` / `from … import …` (including star import flags & relative level),
    * `FunctionDef`, `ClassDef` names & line numbers (via `PositionProvider`),
    * `__all__` names from simple constant assignments,
    * falls back to `parse_ok=False` with a recorded error if the parser chokes (robust on broken files). 

### **scip_reader.py** — load & query SCIP JSON

* **Key types**: `SCIPIndex { documents[], external_symbols{} }`, where each `Document` has `path`, `occurrences[]`, `symbols[]`.
* **Key API**:

  * `SCIPIndex.load(path)`: tolerant loader for schema variants.
  * `by_file() -> { rel_path -> Document }` (used to resolve `import *`).
  * `symbol_to_files()` (reverse index), `file_symbol_kinds()` (map file → symbol → kind). 

### **tree_sitter_bridge.py** — structural outline (fast, best‑effort)

* **Key API**:

  * `build_outline(path, content_bytes) -> TSOutline | None`: builds a DFS outline (functions/classes for Python; noop for others unless language pack is present). Great for cheap structure & non‑Python files. 

### **output_writers.py** — serialization utilities

* `write_json`, `write_jsonl` (with optional `orjson`), `write_markdown_module` to produce readable module sheets (docstring, imports, defs, tags, parse errors). We use these to emit artifacts agents can browse. 

### **tagging.py** — policy tagging

* **Default rules** include `cli`, `fastapi`, `pydantic`, `prefect`, `tests`, `reexport-hub`, `public-api`, `needs-types` (type‑error sensitive).
* **Key API**:

  * `load_rules(path)` (falls back to built‑ins if missing),
  * `infer_tags(path, imported_modules, has_all, is_reexport_hub, type_error_count, rules)` → `{ tags, reasons }`.
* We add the **`overlay-needed`** tag in the driver when an overlay is created. 

### **type_integration.py** — collect type checker signals

* `collect_pyright(cwd)` → `TypeSummary(by_file: { file -> error_count })` via `pyright --outputjson`.
* `collect_pyrefly(report_path)` → same shape, parsed from a JSON/JSONL report you point to (produced in CI).
  *Both are optional; present signals improve `needs-types` and triage but aren’t required to create overlays.* 
* **Context**: Your Pyrefly guide (attached) outlines how Pyrefly differs from Pyre and how to wire LSP/CI/baselines. We lean on it here as your *primary* checker. 

### **stubs_overlay.py** (new) — generate `.pyi` overlays

* **What it solves**:

  * **Fine‑grained star‑import expansion** using SCIP.
  * **Re‑exports** are emitted as explicit `from X import A as A` lines.
  * **Minimal typed placeholders** (functions/classes) are synthesized from LibCST info.
  * **`__all__`** is preserved as the final list of public names.
* **Key API**:

  * `generate_overlay_for_file(py_file, package_root, scip) -> OverlayResult { pyi_path, exports_resolved, created }`.
* Writes sidecars with resolution metadata for debuggability.

### **enrich_cli.py** (new) — one‑shot enrich + overlays + artifacts

* Walks `--root`, builds LibCST indices, resolves re‑exports, writes overlays to `--stubs`, attaches tags (from `tagging_rules.yaml` or built‑ins), and produces:

  * `artifacts/modules.jsonl` (LLM slices),
  * `artifacts/exports_index.json` (for quick grep / agent lookup),
  * `artifacts/modules_md/*.md` (human‑friendly per‑module sheets).
* Honors optional Pyrefly/Pyright summaries for `needs-types` targeting.

---

## 5) QA, policies, and “strictness migration” via overlays

* **Policy switch**: keep the overlays until you decide to “burn in” annotations.

  * If you want to convert overlays → real annotations later, run Pyrefly’s auto‑typing tooling in a temporary workspace and selectively bring the edits over (your Pyrefly doc details `pyrefly infer` tradeoffs & baselines). 

* **CI checks** (recommended):

  * Verify `stubs/**/*.pyi` compiles (trivial import test).
  * `pyrefly check` baseline + `pyright --outputjson` must not **increase** error counts for modified files.
  * Ensure `artifacts/modules.jsonl` and `exports_index.json` are updated in PRs touching code.

* **Agent workflow hints**:

  * For refactors, feed only modules with tags `{ "public-api", "overlay-needed", "needs-types" }` from `modules.jsonl` to limit context and focus high‑leverage hotspots.
  * Re‑run `enrich_cli.py` post‑change and require `overlay-needed` to *not* grow unless intentional.

---

## 6) A few nudges on configuration & environment (already in place)

* Your **Pyrefly** config opts into `implicit-any`, `implicitly-defined-attribute`, etc., and uses `search-path = ["src", "stubs", "."]`—perfect for overlays. 
* Your **Pyright** config sets `"stubPath": "stubs"` and includes `codeintel_rev` in `executionEnvironments`, so overlays are “live” to Pylance/BasedPyright out of the box. 
* The project deps already include everything needed to run the pipeline. 

---

## 7) “Easy wins” you asked about (now enabled)

* **Fine‑grained `import *` expansion**: implemented via SCIP → `exports_resolved` → explicit overlay re‑exports (see `stubs_overlay.py`).
* **Tagging as policy**: still driven by `tagging_rules.yaml`; the driver adds `overlay-needed` automatically. Agents should re‑run tagging post‑change. 
* **LLM‑ready slices**: `artifacts/modules.jsonl` provides hydrated rows for agent routing (imports/defs/tags/exports). 
* **Strictness migration**: overlays let you flip Pyright to `strict` or tighten Pyrefly error families progressively with **zero runtime edits**; later you can delete overlays module‑by‑module as you accept real annotations. 

---

## 8) Handling information gaps, errors, edge cases

* **Ambiguous symbol names in SCIP**: we extract the last path segment defensively; it’s sufficient for re‑export lists. If a module exports names not captured by SCIP (generated attributes, runtime mutations), just add them by hand to the corresponding `.pyi`. 
* **Odd AST forms**: when LibCST parsing fails, we still emit a record with `parse_ok=False` and skip overlays for that file; the Markdown sheet will include the parse error for triage. 
* **Third‑party packages**: prefer published `-stubs` wheels where possible (you already include many), but nothing stops you from adding targeted overlays in `stubs/` for vendored modules as well. 
* **LibCST “full type metadata”**: today, LibCST’s built‑in `TypeInferenceProvider` is coupled to Pyre; your Pyrefly doc explains the gap. Overlays are the pragmatic, Python‑only route: once types exist (via stubs or annotations), most transforms can use LibCST scope/name providers without querying an external type server. 

---

### What you’ll see after the first run

* New files under `stubs/codeintel_rev/**/*.pyi` (and `.pyi.json` sidecars).
* `artifacts/modules.jsonl` with rows like:

```json
{
  "path": "codeintel_rev/app/capabilities.py",
  "defs": [{"kind": "class", "name": "Capabilities", "lineno": 189}, ...],
  "exports": [],
  "exports_resolved": {"codeintel_rev.app.some_module": ["Name1","Name2"]},
  "tags": ["public-api","overlay-needed", "..."],
  "has_overlay": true
}
```

* Pretty sheets at `artifacts/modules_md/*.md`, produced by your writer. 

---

If you want, I can also add a **tiny unit test** scaffold for `stubs_overlay._simple_name_from_scip_symbol` and `generate_overlay_for_file` (mocked SCIP doc) in your `tests/` layout—just say the word and I’ll include it inline.

Otherwise, you can drop the two files above into a branch and run the pipeline immediately.
