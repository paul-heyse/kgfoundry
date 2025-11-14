# SPDX-License-Identifier: MIT
"""Targeted overlay generation with opt-in activation."""

from __future__ import annotations

import platform
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from codeintel_rev.enrich.libcst_bridge import DefEntry, ImportEntry, ModuleIndex, index_module
from codeintel_rev.enrich.output_writers import write_json
from codeintel_rev.enrich.scip_reader import SCIPIndex

DEFAULT_EXPORT_HUB_THRESHOLD = 10


@dataclass(frozen=True, slots=True)
class OverlayPolicy:
    """Controls when an overlay is generated and how it is written."""

    overlays_root: Path = Path("stubs/overlays")
    include_public_defs: bool = True
    inject_module_getattr_any: bool = True
    when_star_imports: bool = True
    when_type_errors: bool = False
    min_type_errors: int = 25
    max_overlays: int = 200
    export_hub_threshold: int = DEFAULT_EXPORT_HUB_THRESHOLD
    overlay_tag: str = "overlay-needed"


@dataclass(frozen=True, slots=True)
class OverlayResult:
    """Summary of overlay creation for a single module."""

    pyi_path: Path | None
    created: bool
    reason: str
    exports_resolved: Mapping[str, set[str]]


@dataclass(frozen=True, slots=True)
class OverlayInputs:
    """Runtime inputs influencing overlay generation."""

    scip: SCIPIndex | None = None
    type_error_counts: Mapping[str, int] | None = None
    force: bool = False
    overlay_tagged_paths: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class OverlayRenderContext:
    """Bundle of values required to render overlay text."""

    module_name: str
    module: ModuleIndex
    star_targets: Mapping[str, list[str]]
    import_reexports: list[str]
    include_public_defs: bool
    inject_getattr_any: bool


def generate_overlay_for_file(
    py_file: Path,
    package_root: Path,
    *,
    policy: OverlayPolicy,
    inputs: OverlayInputs | None = None,
) -> OverlayResult:
    """Generate a .pyi overlay for ``py_file`` when it meets the policy gates.

    This function generates a type stub overlay (.pyi file) for a Python source
    file when it meets the configured policy requirements (e.g., star re-exports,
    large ``__all__`` hubs, explicit overlay-needed tags, or type error thresholds).
    The function analyzes the source file, checks policy gates, and generates the
    overlay if conditions are met.

    Parameters
    ----------
    py_file : Path
        Path to the Python source file for which to generate an overlay.
        May be absolute or relative to package_root. The file must exist and
        be readable for overlay generation.
    package_root : Path
        Root directory of the package containing py_file. Used to compute
        relative module paths and determine overlay destination paths. The
        overlay is written relative to this root.
    policy : OverlayPolicy
        Policy controlling when overlays are generated and how they are written.
        Includes gates for star imports, export hubs, overlay-needed tags, and
        optional type error thresholds. The policy determines whether an overlay
        should be generated for the file.
    inputs : OverlayInputs | None, optional
        Optional bundle containing SCIP index, cached type error counts, and
        override flags (such as force). When omitted, defaults to OverlayInputs()
        with empty SCIP index and zero error counts. Used to provide symbol
        definitions and type error information for overlay generation.

    Returns
    -------
    OverlayResult
        Metadata describing whether an overlay was created, including
        the destination path, creation reason, and resolved exports.
    """
    overlay_inputs = inputs or OverlayInputs()
    source = py_file if py_file.is_absolute() else package_root / py_file
    if not source.exists():
        return OverlayResult(
            pyi_path=None,
            created=False,
            reason="missing-source",
            exports_resolved={},
        )

    rel_key = _normalized_module_key(package_root, source)
    error_count = 0
    if overlay_inputs.type_error_counts:
        error_count = overlay_inputs.type_error_counts.get(
            rel_key, overlay_inputs.type_error_counts.get(str(source), 0)
        )

    module = index_module(str(source), source.read_text(encoding="utf-8", errors="ignore"))

    has_star = any(entry.is_star for entry in module.imports)
    export_count = len(module.exports)
    export_hub = policy.export_hub_threshold > 0 and export_count >= policy.export_hub_threshold
    tagged_overlay = (
        bool(policy.overlay_tag)
        and bool(overlay_inputs.overlay_tagged_paths)
        and rel_key in overlay_inputs.overlay_tagged_paths
    )
    type_error_trigger = policy.when_type_errors and (error_count >= policy.min_type_errors)
    star_trigger = policy.when_star_imports and has_star
    if not overlay_inputs.force and not (
        star_trigger or export_hub or tagged_overlay or type_error_trigger
    ):
        return OverlayResult(
            pyi_path=None,
            created=False,
            reason="not-eligible",
            exports_resolved={},
        )

    star_targets: MutableMapping[str, set[str]] = {}
    if has_star and overlay_inputs.scip is not None:
        for entry in module.imports:
            if entry.is_star and entry.module:
                names = _collect_star_reexports(overlay_inputs.scip, entry)
                if names:
                    star_targets[entry.module] = names

    module_name = _module_name_from_path(package_root, source)
    render_ctx = OverlayRenderContext(
        module_name=module_name,
        module=module,
        star_targets={key: sorted(names) for key, names in star_targets.items()},
        import_reexports=_collect_import_reexports(module),
        include_public_defs=policy.include_public_defs,
        inject_getattr_any=policy.inject_module_getattr_any,
    )
    overlay_text = _build_overlay_text(render_ctx)

    pyi_path = _overlay_path(policy.overlays_root, package_root, py_file)
    pyi_path.parent.mkdir(parents=True, exist_ok=True)
    pyi_path.write_text(overlay_text, encoding="utf-8")

    sidecar = pyi_path.with_suffix(".pyi.json")
    write_json(
        sidecar,
        {
            "module": module_name,
            "source": str(source),
            "exports_resolved": {key: sorted(names) for key, names in star_targets.items()},
            "has_all": sorted(module.exports) if module.exports else [],
            "defs": [{"kind": d.kind, "name": d.name, "lineno": d.lineno} for d in module.defs],
            "parse_ok": module.parse_ok,
            "errors": module.errors,
            "type_errors": error_count,
            "forced": overlay_inputs.force,
        },
    )

    return OverlayResult(
        pyi_path=pyi_path,
        created=True,
        reason="generated",
        exports_resolved=star_targets,
    )


def activate_overlays(
    modules: Sequence[str],
    *,
    overlays_root: Path,
    stubs_root: Path = Path("stubs"),
    copy_on_windows: bool = True,
) -> int:
    """Activate overlays by linking or copying into ``stubs_root``.

    Parameters
    ----------
    modules : Sequence[str]
        Sequence of module names (dotted paths) to activate. Each module
        name is converted to a relative path under ``overlays_root``.
    overlays_root : Path
        Root directory containing generated overlay files (.pyi).
    stubs_root : Path, optional
        Destination directory for activated overlays. Overlays are linked
        (or copied on Windows) into this directory. Defaults to Path("stubs").
    copy_on_windows : bool, optional
        When True (default), copies overlay files on Windows instead of
        creating symlinks. On Unix systems, symlinks are always used.

    Returns
    -------
    int
        Number of overlays that were successfully activated.
    """
    activated = 0
    for rel in modules:
        rel_path = Path(rel).with_suffix(".pyi")
        src = overlays_root / rel_path
        if not src.exists():
            continue
        dst = stubs_root / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        try:
            if copy_on_windows and _is_windows():
                dst.write_bytes(src.read_bytes())
            else:
                dst.symlink_to(src)
        except OSError:
            dst.write_bytes(src.read_bytes())
        activated += 1
    return activated


def deactivate_all(*, overlays_root: Path, stubs_root: Path = Path("stubs")) -> int:
    """Remove overlays under ``stubs_root`` that originated from ``overlays_root``.

    Parameters
    ----------
    overlays_root : Path
        Root directory containing source overlay files. Only overlays that
        match files in this directory are removed from ``stubs_root``.
    stubs_root : Path, optional
        Directory containing activated overlays to remove. Defaults to
        Path("stubs").

    Returns
    -------
    int
        Number of overlays removed from ``stubs_root``.
    """
    removed = 0
    if not stubs_root.exists():
        return removed
    for stub in stubs_root.rglob("*.pyi"):
        rel = stub.relative_to(stubs_root)
        candidate = overlays_root / rel
        try:
            if stub.is_symlink():
                target = stub.readlink()
                if target == candidate:
                    stub.unlink()
                    removed += 1
            elif stub.exists() and candidate.exists():
                if stub.read_bytes() == candidate.read_bytes():
                    stub.unlink()
                    removed += 1
        except OSError:
            continue
    return removed


def _overlay_path(overlays_root: Path, package_root: Path, py_file: Path) -> Path:
    """Return the overlay destination path for ``py_file``.

    Parameters
    ----------
    overlays_root : Path
        Root directory for overlay files.
    package_root : Path
        Root directory of the package containing ``py_file``.
    py_file : Path
        Python source file path (may be absolute or relative to ``package_root``).

    Returns
    -------
    Path
        Target .pyi path under ``overlays_root``, preserving the relative
        structure from ``package_root``.
    """
    target = py_file if py_file.is_absolute() else package_root / py_file
    rel = target.relative_to(package_root)
    root = overlays_root if overlays_root.is_absolute() else package_root.parent / overlays_root
    return root / rel.with_suffix(".pyi")


def _normalized_module_key(package_root: Path, py_file: Path) -> str:
    """Return a normalized module key used for lookups.

    Parameters
    ----------
    package_root : Path
        Root directory of the package.
    py_file : Path
        Python source file path (may be absolute or relative to ``package_root``).

    Returns
    -------
    str
        Forward-slash separated path relative to ``package_root``, normalized
        for use as a lookup key in type error mappings.
    """
    rel = py_file if py_file.is_absolute() else package_root / py_file
    return str(rel.relative_to(package_root)).replace("\\", "/")


def _module_name_from_path(package_root: Path, py_file: Path) -> str:
    """Return the dotted module name for ``py_file``.

    Parameters
    ----------
    package_root : Path
        Root directory of the package.
    py_file : Path
        Python source file path (may be absolute or relative to ``package_root``).

    Returns
    -------
    str
        Dotted module name (e.g., "package.submodule") derived from the
        relative path from ``package_root`` to ``py_file``.
    """
    full_path = py_file if py_file.is_absolute() else package_root / py_file
    rel = full_path.relative_to(package_root).with_suffix("")
    parts: list[str] = [package_root.name, *rel.parts]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(part for part in parts if part)


def _collect_star_reexports(scip: SCIPIndex, entry: ImportEntry) -> set[str]:
    """Return candidate names that a star import might re-export.

    Parameters
    ----------
    scip : SCIPIndex
        SCIP index containing symbol information for resolving re-exports.
    entry : ImportEntry
        Import entry representing a star import (``from module import *``).
        The ``module`` attribute must be set to the target module name.

    Returns
    -------
    set[str]
        Names resolved from the SCIP index that may be re-exported by the
        star import.
    """
    names: set[str] = set()
    target = entry.module or ""
    symbols = list(scip.symbol_to_files().keys())
    for doc in scip.documents:
        symbols.extend(sym.symbol for sym in doc.symbols)
    for symbol in symbols:
        if f"`{target}`" not in symbol:
            continue
        simple = _extract_simple_name(symbol)
        if simple:
            names.add(simple)
    return names


def _extract_simple_name(symbol: str) -> str | None:
    """Extract a plausible leaf identifier from a SCIP symbol string.

    Parameters
    ----------
    symbol : str
        SCIP symbol string (e.g., "package/module#Class.method()") from
        which to extract the leaf identifier.

    Returns
    -------
    str | None
        Leaf identifier (e.g., "method") if one can be inferred from
        ``symbol``, or None if extraction fails.
    """
    cleaned = symbol.strip().strip("`")
    for raw_chunk in reversed(cleaned.split("/")):
        candidate = raw_chunk.strip("`")
        if not candidate:
            continue
        base = candidate.split("#")[0]
        base = base.split("()")[0].rstrip(".")
        if base and base.replace("_", "").replace(".", "").isalnum():
            return base
    return None


def _build_overlay_text(context: OverlayRenderContext) -> str:
    """Render overlay text from the collected module metadata.

    Parameters
    ----------
    context : OverlayRenderContext
        Rendering context bundling module metadata, expansion targets, and
        overlay feature flags.

    Returns
    -------
    str
        Completed overlay text content (Python stub file format) ready
        to write to a .pyi file.
    """
    lines: list[str] = [
        f"# Auto-generated overlay for {context.module_name}. Edit as needed for precise types.",
        "from __future__ import annotations",
        "from typing import Any",
        "",
    ]

    lines.extend(_render_star_exports(context.star_targets))
    if context.import_reexports:
        lines.extend(context.import_reexports)
        lines.append("")
    if context.include_public_defs:
        lines.extend(_render_public_defs(context.module.defs))
    overlay_exports: set[str] = set(context.module.exports)
    for names in context.star_targets.values():
        overlay_exports.update(names)
    if context.include_public_defs:
        overlay_exports.update(
            def_entry.name
            for def_entry in context.module.defs
            if not def_entry.name.startswith("_")
        )
    if overlay_exports:
        exports = ", ".join(f'"{name}"' for name in sorted(overlay_exports))
        lines.append(f"__all__ = [{exports}]")
        lines.append("")
    if context.inject_getattr_any:
        lines.append("def __getattr__(name: str) -> Any: ...")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_star_exports(star_targets: Mapping[str, list[str]]) -> list[str]:
    """Return overlay lines for expanded star imports.

    Parameters
    ----------
    star_targets : Mapping[str, list[str]]
        Mapping of imported module names to lists of resolved re-export names.
        Used to generate ``from module import name as name`` lines in the overlay.

    Returns
    -------
    list[str]
        Lines to embed into the overlay (may be empty when nothing resolved).
    """
    lines: list[str] = []
    for imported_mod, names in star_targets.items():
        if not names:
            continue
        aliased = ", ".join(f"{name} as {name}" for name in names)
        lines.append(f"from {imported_mod} import {aliased}")
    if lines:
        lines.append("")
    return lines


def _render_public_defs(defs: Sequence[DefEntry]) -> list[str]:
    """Return overlay lines for public defs when requested.

    Parameters
    ----------
    defs : Sequence[DefEntry]
        Sequence of definition entries (functions and classes) to render as
        stub definitions in the overlay.

    Returns
    -------
    list[str]
        Minimal definitions representing the module's public API (function
        and class stubs with ``Any`` types).
    """
    rendered: list[str] = []
    for definition in defs:
        if definition.name.startswith("_"):
            continue
        if definition.kind == "function":
            rendered.append(f"def {definition.name}(*args: Any, **kwargs: Any) -> Any: ...")
        elif definition.kind == "class":
            rendered.append(f"class {definition.name}:")
            rendered.append("    def __getattr__(self, name: str) -> Any: ...")
        elif definition.kind == "variable":
            rendered.append(f"{definition.name}: Any = ...")
    if rendered:
        rendered.append("")
    return rendered


def _collect_import_reexports(module: ModuleIndex) -> list[str]:
    """Return re-export lines for explicit imports that are listed in ``__all__``.

    Parameters
    ----------
    module : ModuleIndex
        Parsed module metadata containing imports and exports. The function
        checks which imported names are listed in ``module.exports`` (``__all__``)
        and generates re-export lines for them.

    Returns
    -------
    list[str]
        ``from module import name as alias`` lines to include in the overlay.
        Returns an empty list if the module has no exports or no matching imports.
    """
    if not module.exports:
        return []
    export_set = set(module.exports)
    lines: list[str] = []
    for entry in module.imports:
        if entry.is_star or not entry.module:
            continue
        for name in entry.names:
            alias = entry.aliases.get(name, name)
            if alias not in export_set:
                continue
            lines.append(f"from {entry.module} import {name} as {alias}")
    return lines


def _is_windows() -> bool:
    """Return True when running on Windows.

    Returns
    -------
    bool
        True when the current platform is Windows.
    """
    return platform.system().lower().startswith("win")
