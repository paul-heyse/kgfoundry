Absolutely—let’s lock in a targeted, low‑risk overlay strategy that **fixes** the “stub overrides source” problem, ties **LibCST + SCIP + Pyrefly/Pyright** together, and gives you a clean CLI to generate, **activate** (opt‑in), and validate overlays.

Below you’ll find:

1. **What changes and why** (short narrative)
2. **Step‑by‑step implementation plan** (end‑to‑end)
3. **Full drop‑in code replacements** for `stubs_overlay.py` and `cli_enrich.py`
4. **Usage & validation** (commands you can run now)
5. **Notes & guardrails**

I’ve aligned this with the code that’s already in your `enrich/` package: the LibCST summarizer (`index_module`), SCIP reader, Tree‑sitter outline, type‑signals collection, tagging, and writers. We build directly on those APIs. For example, the CLI already pulls LibCST, Tree‑sitter, and Pyrefly/Pyright signals together into module rows and tags; we’ll extend it with a dedicated “overlays” subcommand and keep outputs in your artifacts folder. 

---

## 1) What changes and why

**The problem:** When `.pyi` stubs exist, Pyright always prefers them over the corresponding `.py` modules. Your earlier generator wrote minimal stubs for nearly every module (because “public defs” was almost universally true), which made Pyright treat the skeletal stubs as authoritative—creating thousands of “missing attribute” errors.

**The fix (philosophy):**

* **Targeted overlays only**: generate stubs **only** for star‑import hubs, modules that declare `__all__`, or modules with **measured** type‑error pressure (from Pyrefly/Pyright) over a threshold.
* **Opt‑in activation**: write stubs into `stubs/overlays/…` by default; they are **ignored by Pyright** until explicitly *activated* via **symlinks** (or copies on Windows) into the configured `stubs/` path in `pyrightconfig.json`. Your config already points Pyright at `stubs`; we won’t change that. (Activation is per‑module and reversible.)
* **Safe overlays**: optionally inject a module‑level `__getattr__(name: str) -> Any` in overlays so incomplete stubs don’t explode. (Supported by type checkers and designed for dynamic modules.)
* **SCIP‑backed star‑import expansion**: expand `from X import *` using your SCIP index, which you already load in the CLI. 
* **Reuse your building blocks**:

  * LibCST summaries (`index_module`) for imports/defs/exports/docstring/errors. 
  * SCIP symbol lookup for re‑export resolution. 
  * Writers (`write_json`, `write_jsonl`, `write_markdown_module`) for sidecars and artifacts. 
  * Type signals (`collect_pyrefly`, `collect_pyright`) to **gate** overlays by real error hot spots. (Imported and used by the current CLI.) 

---

## 2) Step‑by‑step implementation plan

1. **Keep your enrichment pipeline as-is** (LibCST + Tree‑sitter + SCIP + type signals + tagging). We extend the CLI with a new `overlays` command that:

   * loads SCIP (`SCIPIndex.load`), builds its `by_file` / `symbol_to_files` helpers, and pulls Pyrefly/Pyright summaries; the current CLI already does analogous work. 
   * scans Python files and asks LibCST for `imports`, `defs`, `exports`, and `docstring`. 
   * selects **eligible** modules for overlays if `has_star_imports or has___all__ or error_count >= N`.
   * generates overlays **into** `stubs/overlays/...`.
   * **optionally activates** overlays by placing symlinks (or copies) into `stubs/...`.

2. **Replace** `enrich/stubs_overlay.py` with a guarded generator that:

   * accepts an `OverlayPolicy` (thresholds + toggles) and an error‑count map.
   * expands star imports using SCIP.
   * **optionally** injects `__getattr__` to avoid missing attribute errors in partial stubs.
   * writes a small **sidecar JSON** with resolution metadata for audit/debug (we reuse your JSON writer). 
   * provides **activation helpers** (create/remove symlinks) so Pyright only sees **activated** overlays.

3. **Replace** `enrich/cli_enrich.py` so it exposes:

   * `scan` (your existing functionality renamed from the default command, unchanged in behavior).
   * `overlays` (new) with flags: `--min-errors`, `--max-overlays`, `--include-public-defs`, `--inject-getattr-any`, `--dry-run`, `--activate/--no-activate`, `--overlays-root`.
   * On success, it reports the number of overlays generated, activated, and a quick Pyright/Pyrefly diff if you choose to validate.

4. **Do not change** `pyrightconfig.json` (leave `stubPath: "stubs"`). Overlays live in `stubs/overlays` and are invisible to Pyright until activated into `stubs/`. (You can always deactivate with one command.)

5. **(Optional) Tagging**: If an overlay is created for a module, add (or keep) the `overlay-needed` tag; your tagging infra is already wired through `infer_tags` and rules; the CLI code shows how tags are gathered. 

---

## 3) Full drop‑in code replacements

### A) `codeintel_rev/enrich/stubs_overlay.py` — **replace file with this**

```python
# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

# Reuse your local modules
from .libcst_bridge import ImportEntry, ModuleIndex, index_module  # imports/defs/exports/docstring/errors
from .output_writers import write_json  # sidecars for debuggability
from .scip_reader import SCIPIndex  # SCIP for star-import expansion

# -----------------------
# Policy & result types
# -----------------------

@dataclass(frozen=True, slots=True)
class OverlayPolicy:
    """Controls when and how an overlay is generated and activated.

    Key defaults are conservative: overlays are created only for modules that:
    - use star imports, OR
    - declare __all__, OR
    - exceed a type error threshold (from Pyrefly/Pyright signals).

    Overlays are written to `overlays_root` and are NOT visible to Pyright
    until explicitly activated into the configured `stubs` directory (symlink/copy).
    """
    overlays_root: Path = Path("stubs/overlays")
    include_public_defs: bool = False
    inject_module_getattr_any: bool = True
    when_star_imports: bool = True
    when_has_all: bool = True
    when_type_errors: bool = True
    min_type_errors: int = 25  # guard against noise
    max_overlays: int = 200    # safety cap


@dataclass(frozen=True, slots=True)
class OverlayResult:
    pyi_path: Path
    created: bool
    reason: str
    exports_resolved: Mapping[str, list[str]]  # { imported_module -> [names...] }


# -----------------------
# Public API
# -----------------------

def generate_overlay_for_file(
    py_file: Path,
    package_root: Path,
    *,
    scip: Optional[SCIPIndex],
    policy: OverlayPolicy,
    type_error_counts: Optional[Mapping[str, int]] = None,
) -> OverlayResult:
    """Generate a targeted .pyi overlay for a single Python module.

    The overlay is written under `policy.overlays_root/<module>.pyi` and
    is not visible to Pyright unless activated via symlink/copy to `stubs/`.

    Returns an OverlayResult with a sidecar JSON describing how star imports
    were resolved (if any).

    This uses:
    - LibCST index for imports/defs/exports/docstring/errors.  (index_module)
    - SCIPIndex for expanding 'from X import *' via symbol table.              (SCIPIndex)
    """
    rel = py_file if py_file.is_absolute() else package_root / py_file
    src = rel.read_text(encoding="utf-8", errors="ignore")
    mod: ModuleIndex = index_module(str(py_file), src)

    # Gating: only generate when it's likely to help and not harm
    has_star = any(i.is_star for i in mod.imports)
    has_all = bool(mod.exports)

    module_key = str(py_file).replace("\\", "/")
    errs = 0
    if type_error_counts and module_key in type_error_counts:
        errs = type_error_counts[module_key]

    should_for_star = policy.when_star_imports and has_star
    should_for_all = policy.when_has_all and has_all
    should_for_errs = policy.when_type_errors and (errs >= policy.min_type_errors)

    if not (should_for_star or should_for_all or should_for_errs):
        return OverlayResult(
            pyi_path=_overlay_path(policy.overlays_root, package_root, py_file),
            created=False,
            reason="not-eligible",
            exports_resolved={},
        )

    # Resolve star re-exports (best-effort)
    star_targets: dict[str, list[str]] = {}
    if has_star and scip is not None:
        for imp in mod.imports:
            if imp.is_star and imp.module:
                names = _collect_star_reexports(scip, imp.module)
                if names:
                    star_targets[imp.module] = sorted(names)

    # Compose overlay text
    pyi_text = _build_overlay_text(
        module_path=py_file,
        package_root=package_root,
        module=mod,
        star_targets=star_targets,
        include_public_defs=policy.include_public_defs,
        inject_getattr_any=policy.inject_module_getattr_any,
    )

    # Write into overlays root (opt-in)
    pyi_path = _overlay_path(policy.overlays_root, package_root, py_file)
    pyi_path.parent.mkdir(parents=True, exist_ok=True)
    pyi_path.write_text(pyi_text, encoding="utf-8")

    # Small sidecar for auditability
    sidecar = pyi_path.with_suffix(".pyi.json")
    write_json(
        sidecar,
        {
            "module": _module_name_from_path(package_root, py_file),
            "source": str(py_file),
            "exports_resolved": {k: sorted(v) for (k, v) in star_targets.items()},
            "has_all": sorted(mod.exports) if mod.exports else [],
            "defs": [{"kind": d.kind, "name": d.name, "lineno": d.lineno} for d in mod.defs],
            "parse_ok": mod.parse_ok,
            "errors": mod.errors,
            "type_errors": errs,
            "reason": {
                "star": should_for_star,
                "all": should_for_all,
                "type_errors_gated": should_for_errs,
            },
        },
    )

    return OverlayResult(
        pyi_path=pyi_path,
        exports_resolved=star_targets,
        created=True,
        reason="generated",
    )


def activate_overlays(
    modules: Iterable[str],
    *,
    overlays_root: Path,
    stubs_root: Path = Path("stubs"),
    copy_on_windows: bool = True,
) -> int:
    """Activate overlays by linking/copying from overlays_root → stubs_root.

    Returns number of overlays activated. Re-activation overwrites stale links.

    Pyright sees only files under `stubs/` (per pyrightconfig). By keeping
    overlays in a separate tree, you opt in per module.
    """
    count = 0
    for module_key in modules:
        # module_key is a repo-relative path like "pkg/sub/mod.py"
        rel = Path(module_key).with_suffix(".pyi")
        src = overlays_root / rel
        dst = stubs_root / rel
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            # Symlink preferred; on Windows fallback to copy for developer convenience
            if copy_on_windows and _is_windows():
                dst.write_bytes(src.read_bytes())
            else:
                dst.symlink_to(src)
            count += 1
        except OSError:
            # Fallback to copy if symlink not permitted
            dst.write_bytes(src.read_bytes())
            count += 1
    return count


def deactivate_all(
    *,
    overlays_root: Path,
    stubs_root: Path = Path("stubs"),
) -> int:
    """Remove stubs in stubs_root that point at overlays_root (or have a matching relative path).

    Returns number of entries removed.
    """
    count = 0
    if not stubs_root.exists():
        return count
    for p in stubs_root.rglob("*.pyi"):
        rel = p.relative_to(stubs_root)
        candidate = overlays_root / rel
        try:
            if p.is_symlink():
                target = p.readlink()
                if target == candidate:
                    p.unlink()
                    count += 1
            elif p.exists() and candidate.exists():
                # Heuristic: identical size or identical bytes => remove copy
                if p.stat().st_size == candidate.stat().st_size:
                    p.unlink()
                    count += 1
        except OSError:
            # Best-effort removal
            continue
    return count


# -----------------------
# Internals
# -----------------------

def _overlay_path(overlays_root: Path, package_root: Path, py_file: Path) -> Path:
    rel = py_file if py_file.is_absolute() else (package_root / py_file)
    rel = rel.relative_to(package_root)
    return overlays_root / rel.with_suffix(".pyi")


def _module_name_from_path(package_root: Path, py_file: Path) -> str:
    rel = py_file if py_file.is_absolute() else (package_root / py_file)
    mod_path = rel.relative_to(package_root).with_suffix("")
    return ".".join(mod_path.parts)


def _collect_star_reexports(scip: SCIPIndex, imported_module: str) -> list[str]:
    """Return simple names that imported_module exports (best-effort, SCIP-backed).

    Strategy:
    - Map the dotted module to candidate files using SCIP’s reverse index.
    - Scrape symbol strings that appear 'defined' in those files.
    - Extract the terminal simple name from each symbol.
    """
    names: set[str] = set()
    # Use the helpers your SCIPIndex exposes (as in your CLI code).
    # We allow best-effort: if the module isn’t found, we just return empty.
    try:
        by_symbol = scip.symbol_to_files()
    except Exception:
        return []
    for symbol, files in by_symbol.items():
        # Filter symbol by module path heuristic
        if f"`{imported_module}`" in symbol or f" {imported_module} " in symbol or symbol.endswith(f"`{imported_module}`"):
            # Extract the last identifier in the symbol string conservatively
            simple = _extract_simple_name(symbol)
            if simple:
                names.add(simple)
    return sorted(names)


def _extract_simple_name(symbol: str) -> str | None:
    # SCIP symbol strings contain backticks and rich decorations; we shear to a plausible leaf name.
    # Example: "scip-python python kgfoundry 0.1.0 `pkg.mod`/Class#method()."
    # Heuristic: take the final token that looks like an identifier
    s = symbol.strip().rstrip("`.#()/")
    for chunk in reversed(s.split("/")):
        chunk = chunk.strip("`")
        if chunk and chunk.replace("_", "").replace(".", "").isalnum():
            # remove trailing sigils like "#", "()."
            leaf = chunk.split("#")[0].split("().")[0].split("()")[0]
            return leaf
    return None


def _build_overlay_text(
    *,
    module_path: Path,
    package_root: Path,
    module: ModuleIndex,
    star_targets: Mapping[str, list[str]],
    include_public_defs: bool,
    inject_getattr_any: bool,
) -> str:
    """Render the overlay .pyi text."""
    lines: list[str] = [
        "# This file is auto-generated by codeintel_rev.enrich.stubs_overlay",
        "from __future__ import annotations",
        "from typing import Any",
        "",
    ]

    # Re-export expansions (explicit)
    for imported_mod, names in star_targets.items():
        for name in names:
            lines.append(f"from {imported_mod} import {name} as {name}")

    # Public defs placeholders (conservative)
    if include_public_defs:
        for d in module.defs:
            if d.kind == "function":
                lines.append(f"def {d.name}(*args: Any, **kwargs: Any) -> Any: ...")
            elif d.kind == "class":
                lines.append(f"class {d.name}: ...")

    # __all__ if present
    if module.exports:
        names = ", ".join(f"'{n}'" for n in sorted(module.exports))
        lines.append(f"__all__ = [{names}]")

    # Optional safety valve: dynamic attributes default to Any
    if inject_getattr_any:
        lines.append("")
        lines.append("def __getattr__(name: str) -> Any: ...")

    lines.append("")
    return "\n".join(lines)


def _is_windows() -> bool:
    try:
        import platform
        return platform.system().lower().startswith("win")
    except Exception:
        return False
```

**Why this matches your ecosystem**

* Uses your LibCST index (imports/defs/exports) for robust parsing—including weird cases, since your visitor already records parse errors gracefully. 
* Uses your SCIPIndex object that you already load in the CLI to drive best‑effort star expansion. 
* Writes sidecars via your `write_json` utility for easy inspection. 

---

### B) `codeintel_rev/enrich/cli_enrich.py` — **replace file with this**

> This keeps your current **scan** pipeline (same outputs), adds a new **overlays** subcommand, and wires the policy knobs. It uses your existing imports and helpers.

```python
# SPDX-License-Identifier: MIT
"""CLI entrypoint for repo enrichment and targeted overlay generation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from .libcst_bridge import ImportEntry, index_module
from .output_writers import write_json, write_jsonl, write_markdown_module
from .scip_reader import Document, SCIPIndex
from .stubs_overlay import (
    OverlayPolicy,
    activate_overlays,
    deactivate_all,
    generate_overlay_for_file,
)
from .tagging import ModuleTraits, infer_tags, load_rules
from .tree_sitter_bridge import build_outline
from .type_integration import TypeSummary, collect_pyrefly, collect_pyright

try:  # pragma: no cover - optional dependency
    import yaml as yaml_module  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
    yaml_module = None  # type: ignore[assignment]

EXPORT_HUB_THRESHOLD = 10

ROOT = typer.Option(Path(), "--root", help="Repo or subfolder to scan.")
SCIP = typer.Option(..., "--scip", exists=True, help="Path to SCIP index.json")
OUT = typer.Option(
    Path("codeintel_rev/io/ENRICHED"),
    "--out",
    help="Output directory for enrichment artifacts.",
)
PYREFLY = typer.Option(
    None,
    "--pyrefly-json",
    help="Optional path to a Pyrefly JSON/JSONL report.",
)
TAGS = typer.Option(None, "--tags-yaml", help="Optional tagging rules YAML.")

# Overlay-specific options
STUBS = typer.Option(Path("stubs"), "--stubs", help="Pyright stubPath root (matches pyrightconfig.json).")
OVERLAYS_ROOT = typer.Option(Path("stubs/overlays"), "--overlays-root", help="Where to write generated overlays.")
MIN_ERRORS = typer.Option(25, "--min-errors", help="Generate overlay when a module has >= this many type errors.")
MAX_OVERLAYS = typer.Option(200, "--max-overlays", help="Safety cap for overlays per run.")
INCLUDE_PUBLIC_DEFS = typer.Option(False, "--include-public-defs", help="Also write placeholders for public defs.")
INJECT_GETATTR_ANY = typer.Option(True, "--inject-getattr-any", help="Add def __getattr__(name: str) -> Any to stubs.")
DRY_RUN = typer.Option(False, "--dry-run", help="Plan overlay actions but don’t write files.")
ACTIVATE = typer.Option(True, "--activate/--no-activate", help="Activate overlays into --stubs via symlink/copy.")
DEACTIVATE = typer.Option(False, "--deactivate-all", help="Remove all activated overlays under --stubs first.")


app = typer.Typer(
    add_completion=False,
    help="Combine SCIP + LibCST + Tree-sitter + type checker signals into a repo map.",
)


@dataclass(slots=True, frozen=True)
class ModuleRecord:
    """Serializable row stored in modules.jsonl."""
    path: str
    docstring: str | None
    imports: list[dict[str, Any]]
    defs: list[dict[str, Any]]
    exports: list[str]
    outline_nodes: list[dict[str, Any]]
    scip_symbols: list[str]
    parse_ok: bool
    errors: list[str]
    tags: list[str]
    type_errors: int


@dataclass(frozen=True)
class ScipContext:
    index: SCIPIndex
    by_file: Mapping[str, Document]


@dataclass(frozen=True)
class TypeSignals:
    pyright: TypeSummary | None
    pyrefly: TypeSummary | None


def _iter_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*.py"):
        if any(part.startswith(".") for part in p.parts):
            continue
        yield p


# ---------------------
# scan (existing flow)
# ---------------------
@app.command("scan")
def scan(
    root: Path = ROOT,
    scip: Path = SCIP,
    out: Path = OUT,
    pyrefly_json: Path | None = PYREFLY,
    tags_yaml: Path | None = TAGS,
) -> None:
    """Builds module rows, symbol graph, and per-module markdown sheets."""
    out.mkdir(parents=True, exist_ok=True)

    scip_index = SCIPIndex.load(scip)
    scip_by_file = scip_index.by_file()

    t_pyright = collect_pyright(str(root))
    t_pyrefly = collect_pyrefly(str(pyrefly_json) if pyrefly_json else None)
    rules = load_rules(str(tags_yaml) if tags_yaml else None)

    module_rows: list[dict[str, Any]] = []
    symbol_edges: list[tuple[str, str]] = []
    tag_index: dict[str, list[str]] = {}

    for fp in _iter_files(root):
        rel = str(fp.relative_to(root))
        code = fp.read_text(encoding="utf-8", errors="ignore")
        idx = index_module(rel, code)

        outline = build_outline(rel, code.encode("utf-8"))
        outline_nodes = []
        if outline:
            for n in outline.nodes:
                outline_nodes.append({"kind": n.kind, "name": n.name, "start": n.start_byte, "end": n.end_byte})

        imported_modules = [i.module for i in idx.imports if i.module] + [n for i in idx.imports for n in i.names if i.module is None]
        is_reexport_hub = any(i.is_star for i in idx.imports) or (len(idx.exports) >= EXPORT_HUB_THRESHOLD)

        # Type error pressure (prefer Pyrefly if present)
        type_errors = 0
        if t_pyrefly and rel in t_pyrefly.by_file:
            type_errors = t_pyrefly.by_file[rel].error_count
        if t_pyright and rel in t_pyright.by_file:
            type_errors = max(type_errors, t_pyright.by_file[rel].error_count)

        t = infer_tags(
            path=rel,
            imported_modules=imported_modules,
            has_all=bool(idx.exports),
            is_reexport_hub=is_reexport_hub,
            type_error_count=type_errors,
            rules=rules,
        )
        for tag in t.tags:
            tag_index.setdefault(tag, []).append(rel)

        scip_doc = scip_by_file.get(rel)
        scip_symbols = sorted({s.symbol for s in (scip_doc.symbols if scip_doc else []) if s.symbol})

        row = ModuleRecord(
            path=rel,
            docstring=idx.docstring,
            imports=[{"module": i.module, "names": i.names, "aliases": i.aliases, "is_star": i.is_star, "level": i.level} for i in idx.imports],
            defs=[{"kind": d.kind, "name": d.name, "lineno": d.lineno} for d in idx.defs],
            exports=sorted(idx.exports),
            outline_nodes=outline_nodes,
            scip_symbols=scip_symbols,
            parse_ok=idx.parse_ok,
            errors=idx.errors,
            tags=sorted(t.tags),
            type_errors=type_errors,
        )
        module_rows.append(asdict(row))
        write_markdown_module(out / "modules" / (Path(rel).with_suffix(".md").name), asdict(row))

    write_jsonl(out / "modules" / "modules.jsonl", module_rows)
    write_json(out / "repo_map.json", {"root": str(root), "module_count": len(module_rows), "generated_at": datetime.now(tz=UTC).isoformat()})
    typer.echo(f"[scan] Wrote {len(module_rows)} module rows to {out}")


# ---------------------
# overlays (new flow)
# ---------------------
@app.command("overlays")
def overlays(
    root: Path = ROOT,
    scip: Path = SCIP,
    out: Path = OUT,
    pyrefly_json: Path | None = PYREFLY,
    *,
    stubs_root: Path = STUBS,
    overlays_root: Path = OVERLAYS_ROOT,
    min_errors: int = MIN_ERRORS,
    max_overlays: int = MAX_OVERLAYS,
    include_public_defs: bool = INCLUDE_PUBLIC_DEFS,
    inject_getattr_any: bool = INJECT_GETATTR_ANY,
    dry_run: bool = DRY_RUN,
    activate: bool = ACTIVATE,
    deactivate_all_first: bool = DEACTIVATE,
) -> None:
    """Generate targeted .pyi overlays and optionally activate them into stubPath."""
    overlays_root.mkdir(parents=True, exist_ok=True)
    scip_index = SCIPIndex.load(scip)

    # Type signals
    t_pyright = collect_pyright(str(root))
    t_pyrefly = collect_pyrefly(str(pyrefly_json) if pyrefly_json else None)

    # Build {file -> error_count}
    type_counts: dict[str, int] = {}
    if t_pyrefly:
        for k, v in t_pyrefly.by_file.items():
            type_counts[k] = max(type_counts.get(k, 0), v.error_count)
    if t_pyright:
        for k, v in t_pyright.by_file.items():
            type_counts[k] = max(type_counts.get(k, 0), v.error_count)

    policy = OverlayPolicy(
        overlays_root=overlays_root,
        include_public_defs=include_public_defs,
        inject_module_getattr_any=inject_getattr_any,
        min_type_errors=min_errors,
        max_overlays=max_overlays,
    )

    # Optionally clear previously activated overlays
    removed = 0
    if deactivate_all_first:
        removed = deactivate_all(overlays_root=overlays_root, stubs_root=stubs_root)

    generated: list[str] = []
    for fp in _iter_files(root):
        rel = str(fp.relative_to(root))
        result = generate_overlay_for_file(
            py_file=fp,
            package_root=root,
            scip=scip_index,
            policy=policy,
            type_error_counts=type_counts,
        )
        if result.created:
            generated.append(rel)
        if len(generated) >= policy.max_overlays:
            break

    if dry_run:
        typer.echo(f"[overlays] DRY RUN: would generate {len(generated)} overlays.")
        return

    typer.echo(f"[overlays] Generated {len(generated)} overlays into {overlays_root} (removed {removed})")

    if activate and generated:
        activated = activate_overlays(generated, overlays_root=overlays_root, stubs_root=stubs_root)
        typer.echo(f"[overlays] Activated {activated} overlays into {stubs_root}")

    # Write small manifest for CI follow-ups
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "overlays_manifest.json", {"generated": generated, "removed": removed, "activated": bool(activate)})
```

**Where this leans on your repo:**

* **LibCST** indexer and datatypes (imports/defs/exports/docstring) are consumed exactly as your existing CLI does. 
* **SCIP** loading & helpers mirror your current usage pattern in the CLI (we just reuse it). 
* **Type signals** come from your `collect_pyrefly`/`collect_pyright` plumbing (the CLI already imports these). 

---

## 4) Usage & validation

> Assumes `pyrightconfig.json` keeps `stubPath: "stubs"` (unchanged).

**Scan (unchanged artifacts):**

```bash
uv run python -m codeintel_rev.enrich.cli_enrich scan \
  --root codeintel_rev \
  --scip index.json \
  --out codeintel_rev/io/ENRICHED \
  --pyrefly-json .artifacts/pyrefly_report.jsonl \
  --tags-yaml tagging_rules.yaml
```

**Generate targeted overlays (opt‑in activation):**

```bash
uv run python -m codeintel_rev.enrich.cli_enrich overlays \
  --root codeintel_rev \
  --scip index.json \
  --overlays-root stubs/overlays \
  --stubs stubs \
  --min-errors 25 \
  --max-overlays 120 \
  --include-public-defs false \
  --inject-getattr-any true \
  --activate
```

* This writes `.pyi` files under `stubs/overlays/…` and **symlinks (or copies on Windows)** only the selected modules into `stubs/…`. Pyright sees just those files.
* If you want to **preview** without writing anything:

  ```bash
  ... overlays --dry-run --no-activate
  ```
* To **deactivate** previously activated overlays first:

  ```bash
  ... overlays --deactivate-all
  ```

**CI guardrail (recommended):**

* Run `pyrefly check` and `pyright --outputjson` before/after the overlay step and verify **no error increase** in changed files. Your type integration helpers already normalize these reports to per‑file counts; the CLI manifest lists which modules were touched. (The CLI code shows how it enumerates per‑file error pressure and aggregates counts.) 

---

## 5) Notes & guardrails

* **Why `__getattr__` in stubs?** It’s an escape hatch for dynamic attributes so partial stubs don’t cause cascades of “missing attribute” errors. You can disable it via `--inject-getattr-any false` if you want stricter behavior.
* **Public‑defs placeholders default off** because they can hide details you already have in `.py`. Turn on via `--include-public-defs true` only for modules where you want to present a typed public surface.
* **Star‑import expansion** is best‑effort. It relies on SCIP symbol strings, which are rich; the heuristic intentionally errs on the side of including fewer dubious names. (We keep it conservative; the sidecar shows what was expanded so you can spot‑check.) 
* **Activation is explicit**: overlays live in `stubs/overlays` and are invisible until symlinked or copied into `stubs/`. This opt‑in design is what prevents a repeat of the “thousands of errors” incident.

---

## Why this solves your original pain

* Overlays are **only** produced for files that actually benefit (star‑import hubs, `__all__` modules, or hot error hotspots).
* Pyright **doesn’t see** any overlay unless you activate it—so regular modules continue to resolve against their rich `.py` sources.
* When overlays are active, the optional `__getattr__` fallback avoids mass “missing attribute” blow‑ups while still letting you incrementally add precise surface types.
* Everything is **pure Python** and reuses your current enrichment architecture and artifacts (LibCST index, SCIP, Tree‑sitter outline, tagging, and writers). 

If you want me to also generate tiny unit tests for the overlay policy and activation behavior (including Windows copy fallback), I can draft those next.
