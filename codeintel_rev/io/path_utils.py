"""Path safety utilities for repository-scoped operations."""

from __future__ import annotations

from pathlib import Path


class PathOutsideRepositoryError(ValueError):
    """Raised when a path escapes the configured repository root."""


def resolve_within_repo(
    repo_root: Path,
    target: str | Path,
    *,
    allow_nonexistent: bool = True,
) -> Path:
    """Resolve ``target`` against ``repo_root`` and ensure it stays within bounds.

    Parameters
    ----------
    repo_root : Path
        Repository root directory.
    target : str | Path
        Requested path (relative or absolute).
    allow_nonexistent : bool, optional
        When ``False`` the resolved path must already exist on disk.

    Returns
    -------
    Path
        Absolute path inside ``repo_root``.

    Raises
    ------
    PathOutsideRepositoryError
        If the resolved path is outside the repository.
    FileNotFoundError
        When ``allow_nonexistent`` is ``False`` and the path does not exist.
    """
    resolved_root = repo_root.expanduser().resolve()
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = resolved_root / candidate
    candidate = candidate.expanduser().resolve()

    if not candidate.is_relative_to(resolved_root):
        msg = f"Path {candidate} escapes repository root {resolved_root}"
        raise PathOutsideRepositoryError(msg)

    if not allow_nonexistent and not candidate.exists():
        raise FileNotFoundError(candidate)

    return candidate
