# SPDX-License-Identifier: MIT
"""Helpers for converting between module paths and dotted names."""

from __future__ import annotations

from pathlib import Path


def normalize_module_name(path: str) -> str:
    """Return a dotted module name for a repo-relative path.

    Parameters
    ----------
    path : str
        Repository-relative file path (e.g., ``src/app/config.py``).

    Returns
    -------
    str
        Normalized dotted module name (e.g., ``app.config``).
    """
    p = Path(path)
    parts = list(p.parts)
    if not parts:
        return ""
    last = parts[-1]
    if last == "__init__.py":
        parts = parts[:-1]
    elif last.endswith(".py"):
        parts[-1] = last[:-3]
    return ".".join(part for part in parts if part)


def module_name_candidates(path: str, package_prefix: str | None) -> set[str]:
    """Return candidate module names (with and without prefix).

    Parameters
    ----------
    path : str
        Repository-relative file path.
    package_prefix : str | None
        Optional package prefix to prepend to module names.

    Returns
    -------
    set[str]
        Candidate module names that map to the provided path.
    """
    canonical = normalize_module_name(path)
    names: set[str] = set()
    if canonical:
        names.add(canonical)
    if package_prefix:
        prefixed = f"{package_prefix}.{canonical}" if canonical else package_prefix
        names.add(prefixed)
    return names


def resolve_relative_module(current: str, module: str | None, level: int) -> str:
    """Resolve a relative import into an absolute dotted module name.

    Parameters
    ----------
    current : str
        Current module name (e.g., ``app.config``).
    module : str | None
        Module name from import statement, or None for relative-only imports.
    level : int
        Relative import level (number of dots, e.g., 1 for ``from . import x``).

    Returns
    -------
    str
        Absolute dotted module string or empty string when unresolved.
    """
    if level <= 0:
        return module or ""
    parts = current.split(".")
    if level > len(parts):
        return module or ""
    base = parts[: len(parts) - level]
    if module:
        base.append(module)
    return ".".join(part for part in base if part)


def import_targets_for_entry(
    current_module: str,
    module: str | None,
    names: list[str],
    level: int,
) -> set[str]:
    """Return candidate absolute module names for a single import entry.

    Parameters
    ----------
    current_module : str
        Current module name where the import occurs.
    module : str | None
        Module name from import statement, or None for relative-only imports.
    names : list[str]
        List of imported symbol names (for ``from X import Y, Z``).
    level : int
        Relative import level (number of dots).

    Returns
    -------
    set[str]
        Candidate absolute modules referenced by the import entry.
    """
    targets: set[str] = set()
    absolute = resolve_relative_module(current_module, module, level) if current_module else module
    if absolute:
        targets.add(absolute)
    if not module and names:
        for name in names:
            absolute_name = (
                resolve_relative_module(current_module, name, level) if current_module else name
            )
            if absolute_name:
                targets.add(absolute_name)
    return targets
