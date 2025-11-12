# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .libcst_bridge import DefEntry, ImportEntry, ModuleIndex, index_module
from .output_writers import write_json
from .scip_reader import Document, SCIPIndex


@dataclass(frozen=True)
class OverlayResult:
    """Result metadata for an overlay generation attempt."""

    pyi_path: Path | None
    exports_resolved: dict[str, set[str]]
    created: bool


def generate_overlay_for_file(
    py_file: Path,
    package_root: Path,
    scip: SCIPIndex | None,
) -> OverlayResult:
    """Create a `.pyi` overlay for ``py_file`` when public surface warrants it."""
    repo_root = _infer_repo_root(package_root)
    relative_path = _safe_relative(py_file, repo_root)
    code = py_file.read_text(encoding="utf-8", errors="ignore")
    module_index = index_module(str(relative_path), code)
    module_name = _module_name_from_path(py_file, repo_root)

    scip_by_file = scip.by_file() if scip else {}
    star_exports = _collect_star_reexports(module_name, module_index.imports, scip_by_file)
    public_defs = [d for d in module_index.defs if _is_public_def(d)]
    should_overlay = bool(star_exports or module_index.exports or public_defs)

    if not should_overlay:
        return OverlayResult(pyi_path=None, exports_resolved=star_exports, created=False)

    overlay_text = _build_overlay_text(module_name, module_index, public_defs, star_exports)
    stubs_root = repo_root / "stubs"
    pyi_path = stubs_root / relative_path.with_suffix(".pyi")
    pyi_path.parent.mkdir(parents=True, exist_ok=True)
    if pyi_path.exists():
        current = pyi_path.read_text(encoding="utf-8")
        if current == overlay_text:
            created = True
        else:
            pyi_path.write_text(overlay_text, encoding="utf-8")
            created = True
    else:
        pyi_path.write_text(overlay_text, encoding="utf-8")
        created = True

    _write_sidecar(
        pyi_path=pyi_path,
        module_name=module_name,
        source_path=str(relative_path),
        module_index=module_index,
        star_exports=star_exports,
    )
    return OverlayResult(pyi_path=pyi_path, exports_resolved=star_exports, created=created)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _infer_repo_root(root: Path) -> Path:
    root = root.resolve()
    if (root / "__init__.py").exists():
        return root.parent
    return root


def _safe_relative(path: Path, base: Path) -> Path:
    try:
        return path.resolve().relative_to(base.resolve())
    except ValueError:
        return Path(path.name)


def _module_name_from_path(py_file: Path, repo_root: Path) -> str:
    rel = _safe_relative(py_file, repo_root)
    parts = list(rel.parts)
    if not parts:
        return py_file.stem
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join(parts) if parts else py_file.stem


def _collect_star_reexports(
    this_module: str,
    imports: Iterable[ImportEntry],
    scip_by_file: Mapping[str, Document],
) -> dict[str, set[str]]:
    resolved: dict[str, set[str]] = {}
    if not scip_by_file:
        return resolved
    for imp in imports:
        if not imp.is_star:
            continue
        target = _resolve_target_module(this_module, imp)
        if not target:
            continue
        names = _names_from_scip(target, scip_by_file)
        if not names:
            continue
        resolved.setdefault(target, set()).update(names)
    return resolved


def _resolve_target_module(this_module: str, imp: ImportEntry) -> str | None:
    if imp.level == 0:
        return imp.module
    parts = this_module.split(".")
    if len(parts) < imp.level:
        return None
    prefix = parts[: len(parts) - imp.level]
    if imp.module:
        prefix.extend(imp.module.split("."))
    target = ".".join(part for part in prefix if part)
    return target or None


def _names_from_scip(module_name: str, scip_by_file: Mapping[str, Document]) -> set[str]:
    candidates = _candidate_file_paths_for_module(module_name)
    names: set[str] = set()
    for candidate in candidates:
        doc = scip_by_file.get(candidate)
        if not doc:
            continue
        for sym in doc.symbols:
            name = _simple_name_from_scip_symbol(sym.symbol)
            if name and not _is_private(name):
                names.add(name)
        if names:
            break
    return names


def _candidate_file_paths_for_module(module_name: str) -> list[str]:
    parts = [p for p in module_name.split(".") if p]
    candidates: list[str] = []
    prefixes = [
        parts,
        parts[1:] if len(parts) > 1 else [],
    ]
    seen: set[str] = set()
    for prefix in prefixes:
        if not prefix:
            continue
        base = "/".join(prefix)
        for stem in (
            f"{base}.py",
            f"{base}/__init__.py",
            f"src/{base}.py",
            f"src/{base}/__init__.py",
        ):
            if stem not in seen:
                candidates.append(stem)
                seen.add(stem)
    return candidates


def _simple_name_from_scip_symbol(symbol: str) -> str | None:
    if not symbol:
        return None
    tail = symbol.rsplit("/", 1)[-1]
    for delimiter in ("#", "?", "."):
        if delimiter in tail:
            tail = tail.split(delimiter, 1)[0]
    tail = tail.strip("`")
    return tail or None


def _is_private(name: str) -> bool:
    return name.startswith("_")


def _is_public_def(entry: DefEntry) -> bool:
    return entry.kind in {"function", "class"} and not _is_private(entry.name)


def _pyi_header(import_any: bool) -> list[str]:
    lines = ["from __future__ import annotations"]
    if import_any:
        lines.append("from typing import Any")
    lines.append("")
    lines.append("# Auto-generated overlay. Edit as needed for more precise types.")
    lines.append("")
    return lines


def _build_overlay_text(
    module_name: str,
    module_index: ModuleIndex,
    public_defs: list[DefEntry],
    star_exports: dict[str, set[str]],
) -> str:
    needs_any = any(entry.kind == "function" for entry in public_defs)
    lines = _pyi_header(import_any=needs_any)
    emitted_reexport = False
    for mod_name in sorted(star_exports):
        exports = star_exports[mod_name]
        if not exports:
            continue
        spec = ", ".join(sorted(f"{name} as {name}" for name in exports))
        lines.append(f"from {mod_name} import {spec}")
        emitted_reexport = True
    if emitted_reexport:
        lines.append("")
    for entry in public_defs:
        if entry.kind == "function":
            lines.append(
                f"def {entry.name}(*args: Any, **kwargs: Any) -> Any: ...  # line {entry.lineno}"
            )
        elif entry.kind == "class":
            lines.append(f"class {entry.name}: ...  # line {entry.lineno}")
    if public_defs:
        lines.append("")
    public_names: set[str] = set(n for n in module_index.exports if not _is_private(n))
    for names in star_exports.values():
        public_names.update(name for name in names if not _is_private(name))
    public_names.update(entry.name for entry in public_defs)
    if public_names:
        sorted_names = ", ".join(f'"{name}"' for name in sorted(public_names))
        lines.append(f"__all__ = [{sorted_names}]")
    return "\n".join(lines).rstrip() + "\n"


def _write_sidecar(
    pyi_path: Path,
    module_name: str,
    source_path: str,
    module_index: ModuleIndex,
    star_exports: dict[str, set[str]],
) -> None:
    sidecar = pyi_path.with_suffix(".pyi.json")
    payload = {
        "module": module_name,
        "source": source_path,
        "exports_resolved": {k: sorted(v) for k, v in star_exports.items()},
        "has_all": sorted(module_index.exports),
        "defs": [{"kind": d.kind, "name": d.name, "lineno": d.lineno} for d in module_index.defs],
        "parse_ok": module_index.parse_ok,
        "errors": module_index.errors,
    }
    write_json(sidecar, payload)
