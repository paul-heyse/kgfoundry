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

    Returns
    -------
    Path
        Resolved repository root, or ``start`` when no ``.git`` directory is found.
    """
    candidate = start.resolve()
    for path in (candidate, *candidate.parents):
        if (path / ".git").exists():
            return path
    return candidate


def to_repo_relative(path: Path, repo_root: Path) -> str:
    """Return a POSIX path for ``path`` relative to ``repo_root``.

    Returns
    -------
    str
        Normalized POSIX path relative to the repository root.
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

    Returns
    -------
    str
        Best-effort dotted module name (may be empty when outside the repo root).
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

    Returns
    -------
    str
        First 12 hexadecimal characters of the digest for deterministic joins.
    """
    digest = blake2s(rel_posix.encode("utf-8"))
    return digest.hexdigest()[:12]
