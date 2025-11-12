# SPDX-License-Identifier: MIT
"""Stitch LibCST + SCIP + tagging outputs into enriched module records."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codeintel_rev.enrich.scip_reader import SCIPIndex

__all__ = ["stitch_records"]


def _module_name_from_path(path_str: str) -> str:
    path = Path(path_str)
    if not path.suffix:
        return ".".join(path.parts)
    parts = list(path.parts)
    if not parts:
        return ""
    last = parts[-1]
    if last == "__init__.py":
        parts = parts[:-1]
    elif last.endswith(".py"):
        parts[-1] = last[:-3]
    return ".".join(parts)


def _package_root(path_str: str) -> str:
    parts = Path(path_str).parts
    return parts[0] if parts else ""


def _candidate_init_path(modname: str) -> str:
    return str(Path(*modname.split(".")) / "__init__.py")


def _public_names_from_row(row: Mapping[str, Any]) -> set[str]:
    exports = row.get("exports") or []
    if exports:
        return {name for name in exports if isinstance(name, str)}
    names: set[str] = set()
    for definition in row.get("defs") or []:
        if not isinstance(definition, Mapping):
            continue
        kind = definition.get("kind")
        name = definition.get("name")
        if kind in {"function", "class"} and isinstance(name, str) and not name.startswith("_"):
            names.add(name)
    return names


def _resolve_absolute_module(src_module: str, module: str | None, level: int) -> str:
    if level <= 0:
        return module or ""
    parts = src_module.split(".")
    if level > len(parts):
        return module or ""
    base = parts[: len(parts) - level]
    if module:
        base = [*base, module]
    return ".".join(base)


def _possible_module_names(absolute_module: str, package_prefix: str | None) -> set[str]:
    names = {absolute_module}
    if package_prefix and absolute_module.startswith(f"{package_prefix}."):
        trimmed = absolute_module[len(package_prefix) + 1 :]
        if trimmed:
            names.add(trimmed)
    return names


def _target_path(
    absolute_module: str,
    module_to_path: dict[str, str],
    path_to_module: dict[str, str],
    package_prefix: str | None,
) -> str | None:
    for candidate in _possible_module_names(absolute_module, package_prefix):
        path = module_to_path.get(candidate)
        if path:
            return path
    for candidate in _possible_module_names(absolute_module, package_prefix):
        init_path = _candidate_init_path(candidate)
        if init_path in path_to_module:
            return init_path
    return None


def _import_targets(src_module: str | None, imp: Mapping[str, Any]) -> set[str]:
    level = int(imp.get("level") or 0)
    targets: set[str] = set()

    def resolve(name: str | None) -> str:
        if not name:
            return ""
        if src_module:
            return _resolve_absolute_module(src_module, name, level)
        return name

    module_name = imp.get("module")
    if isinstance(module_name, str):
        absolute = resolve(module_name)
        if absolute:
            targets.add(absolute)

    names = imp.get("names")
    if isinstance(names, list):
        for name in names:
            if isinstance(name, str):
                absolute = resolve(name)
                if absolute:
                    targets.add(absolute)
    return targets


@dataclass(frozen=True)
class _Graph:
    out_edges: dict[str, set[str]]
    in_edges: dict[str, set[str]]


@dataclass(frozen=True)
class _GraphContext:
    path_to_module: dict[str, str]
    module_to_path: dict[str, str]
    roots: set[str]
    package_prefix: str | None
    out_edges: dict[str, set[str]]
    in_edges: dict[str, set[str]]


def _build_import_graph(rows: list[dict[str, Any]], package_prefix: str | None) -> _Graph:
    out: dict[str, set[str]] = defaultdict(set)
    inn: dict[str, set[str]] = defaultdict(set)

    path_to_module = {row["path"]: _module_name_from_path(row["path"]) for row in rows}
    module_to_path = {mod: path for path, mod in path_to_module.items() if mod}
    roots = set() if package_prefix else {root for root in (_package_root(row["path"]) for row in rows) if root}
    context = _GraphContext(path_to_module, module_to_path, roots, package_prefix, out, inn)

    for row in rows:
        _process_imports_for_row(row, context)

    for row in rows:
        out.setdefault(row["path"], set())
        inn.setdefault(row["path"], set())
    return _Graph(out_edges=out, in_edges=inn)


def _process_imports_for_row(row: dict[str, Any], context: _GraphContext) -> None:
    src_path = row["path"]
    src_module = context.path_to_module.get(src_path)
    if not src_module and context.package_prefix:
        relative = _module_name_from_path(src_path)
        src_module = f"{context.package_prefix}.{relative}" if relative else context.package_prefix
    if not src_module:
        return

    for imp in row.get("imports") or []:
        if not isinstance(imp, Mapping):
            continue
        targets = _import_targets(src_module, imp)
        _add_edges(src_path, targets, context)


def _add_edges(src_path: str, targets: set[str], context: _GraphContext) -> None:
    for absolute in targets:
        if not absolute:
            continue
        if context.roots and absolute.split(".")[0] not in context.roots:
            continue
        dst_path = _target_path(
            absolute,
            context.module_to_path,
            context.path_to_module,
            context.package_prefix,
        )
        if not dst_path or dst_path == src_path:
            continue
        context.out_edges[src_path].add(dst_path)
        context.in_edges[dst_path].add(src_path)


def _module_rows_by_name(rows: list[dict[str, Any]], package_prefix: str | None) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        relative = _module_name_from_path(row["path"])
        names: set[str] = set()
        if relative:
            names.add(relative)
        if package_prefix:
            prefixed = f"{package_prefix}.{relative}" if relative else package_prefix
            names.add(prefixed)
        for name in names:
            mapping[name] = row
            mapping.setdefault(f"{name}.__init__", row)
    return mapping


def _tarjan_scc(nodes: Iterable[str], edges: Mapping[str, set[str]]) -> dict[str, int]:
    index = 0
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    component_id = 0
    assignment: dict[str, int] = {}

    def strongconnect(node: str) -> None:
        nonlocal index, component_id
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in edges.get(node, ()):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif neighbor in on_stack:
                lowlink[node] = min(lowlink[node], indices[neighbor])

        if lowlink[node] == indices[node]:
            while True:
                member = stack.pop()
                on_stack.remove(member)
                assignment[member] = component_id
                if member == node:
                    break
            component_id += 1

    for node in nodes:
        if node not in indices:
            strongconnect(node)
    return assignment


def _resolve_star_imports(
    row: dict[str, Any],
    modules_by_name: Mapping[str, dict[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, dict[str, str]]]:
    resolved: dict[str, list[str]] = {}
    reexports: dict[str, dict[str, str]] = {}
    src_module = _module_name_from_path(row["path"])

    for imp in row.get("imports") or []:
        if not isinstance(imp, Mapping) or not imp.get("is_star"):
            continue
        origin = imp.get("module")
        level = int(imp.get("level") or 0)
        if level and src_module:
            origin = _resolve_absolute_module(src_module, origin, level)
        if not origin:
            continue

        origin_row = modules_by_name.get(origin)
        if not origin_row:
            continue
        names = sorted(_public_names_from_row(origin_row))
        if not names:
            continue
        resolved[origin] = names
        local_defs = {definition.get("name") for definition in row.get("defs") or []}
        for name in names:
            if name in local_defs:
                continue
            reexports.setdefault(name, {"from": origin, "symbol": f"{origin}.{name}"})
    return resolved, reexports


def stitch_records(
    rows: list[dict[str, Any]],
    _scip_index: SCIPIndex | None = None,
    package_prefix: str | None = None,
) -> list[dict[str, Any]]:
    """Add graph metrics and re-export data to module records.

    Parameters
    ----------
    rows : list[dict[str, Any]]
        List of module records (dictionaries) containing at least a "path"
        key. Each record is enriched with graph metrics and re-export data.
    _scip_index : SCIPIndex | None, optional
        Unused parameter (reserved for future SCIP-based enhancements).
        Defaults to None.
    package_prefix : str | None, optional
        Optional package prefix for normalizing module names. When provided,
        module names are normalized relative to this prefix. Defaults to None.

    Returns
    -------
    list[dict[str, Any]]
        New list with stitched metadata attached to each record. Each record
        includes additional keys: "fan_in", "fan_out", "cycle_group",
        "exports_resolved", and "reexports".
    """
    graph = _build_import_graph(rows, package_prefix)
    cycle_groups = _tarjan_scc(graph.out_edges.keys(), graph.out_edges)
    modules_by_name = _module_rows_by_name(rows, package_prefix)

    stitched: list[dict[str, Any]] = []
    for row in rows:
        exports_resolved, reexports = _resolve_star_imports(row, modules_by_name)
        enriched = dict(row)
        enriched["fan_in"] = len(graph.in_edges.get(row["path"], ()))
        enriched["fan_out"] = len(graph.out_edges.get(row["path"], ()))
        enriched["cycle_group"] = cycle_groups.get(row["path"], -1)
        if exports_resolved:
            enriched["exports_resolved"] = {k: sorted(v) for k, v in exports_resolved.items()}
        if reexports:
            enriched["reexports"] = dict(sorted(reexports.items()))
        stitched.append(enriched)
    return stitched
