# SPDX-License-Identifier: MIT
"""Helpers for repo-relative path normalization and stable identifiers."""

from __future__ import annotations

from hashlib import blake2s
from pathlib import Path

__all__ = [
    "detect_repo_root",
    "module_name_from_path",
    "stable_id_for_path",
    "to_repo_relative",
]


def detect_repo_root(start: Path) -> Path:
    """Return the closest ancestor containing a ``.git`` directory.

    This function traverses up the directory tree from the starting path to find
    the repository root (directory containing .git). The function resolves the
    starting path to an absolute path and checks each parent directory until
    a .git directory is found or the filesystem root is reached.

    Parameters
    ----------
    start : Path
        Starting directory path to begin the search. The path is resolved to
        an absolute path, and the search proceeds upward through parent directories.
        Can be any path within the repository (file or directory).

    Returns
    -------
    Path
        Resolved repository root directory containing .git, or the resolved
        starting path when no .git directory is found in any ancestor. The path
        is always absolute and resolved.
    """
    candidate = start.resolve()
    for path in (candidate, *candidate.parents):
        if (path / ".git").exists():
            return path
    return candidate


def to_repo_relative(path: Path, repo_root: Path) -> str:
    """Return a POSIX path for ``path`` relative to ``repo_root``.

    This function converts an absolute or relative file path into a normalized
    POSIX-style path relative to the repository root. The function resolves both
    paths to absolute paths, computes the relative path, and normalizes it to
    use forward slashes (POSIX style) regardless of the platform.

    Parameters
    ----------
    path : Path
        File path to convert to repository-relative format. The path is resolved
        to an absolute path before computing the relative path from repo_root.
    repo_root : Path
        Root directory of the repository used for path normalization. The path
        is resolved to an absolute path before computing the relative path.

    Returns
    -------
    str
        Normalized POSIX path relative to the repository root, using forward
        slashes as path separators. If path is not within repo_root, returns
        the absolute path as a POSIX string (defensive fallback).
    """
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
    except ValueError:  # pragma: no cover - defensive fallback
        return path.resolve().as_posix()
    return rel.as_posix()


def module_name_from_path(
    repo_root: Path,
    path: Path,
    package_prefix: str | None = None,
) -> str:
    """Derive a dotted module name for ``path`` relative to ``repo_root``.

    This function converts a file path into a dotted module name by computing
    the repository-relative path, removing .py extension, handling __init__.py
    files, and converting path separators to dots. The function optionally
    prepends a package prefix when provided.

    Parameters
    ----------
    repo_root : Path
        Root directory of the repository used for path normalization. The path
        is resolved to an absolute path before computing the relative path.
    path : Path
        File path to convert to a module name. The path is converted to
        repository-relative format, .py extension is stripped, and __init__.py
        is handled specially (removed from the path).
    package_prefix : str | None, optional
        Optional package prefix to prepend to the module name (default: None).
        When provided, the prefix is prepended with a dot separator. Used to
        handle packages that are not at the repository root.

    Returns
    -------
    str
        Dotted module name derived from the path (e.g., "src.pkg.module").
        Empty string when path is outside repo_root and no package_prefix is
        provided. Path separators are converted to dots, .py extension is
        stripped, and __init__.py is removed from package paths.
    """
    rel = Path(to_repo_relative(path, repo_root))
    parts = list(rel.parts)
    if not parts:
        return package_prefix or ""
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    dotted = ".".join(part for part in parts if part)
    if not package_prefix:
        return dotted
    if dotted.startswith(f"{package_prefix}."):
        return dotted
    return f"{package_prefix}.{dotted}" if dotted else package_prefix


def stable_id_for_path(rel_posix: str) -> str:
    """Return a truncated BLAKE2s digest for ``rel_posix``.

    This function computes a stable, deterministic identifier for a POSIX path
    by hashing it with BLAKE2s and returning the first 12 hexadecimal characters.
    The function provides a short, collision-resistant identifier suitable for
    use in joins and lookups where full paths are too long.

    Parameters
    ----------
    rel_posix : str
        POSIX-style relative path string to hash (e.g., "src/pkg/module.py").
        The path is encoded as UTF-8 before hashing. Used to generate a stable
        identifier that is consistent across runs.

    Returns
    -------
    str
        First 12 hexadecimal characters of the BLAKE2s hash digest. The identifier
        is deterministic for the same input path and suitable for use in database
        joins or lookups. Example: "a1b2c3d4e5f6" for a typical path.
    """
    digest = blake2s(rel_posix.encode("utf-8"))
    return digest.hexdigest()[:12]
