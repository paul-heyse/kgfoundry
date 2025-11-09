"""Filesystem and selection helpers for the docstring builder."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from tools._shared.logging import get_logger
from tools._shared.proc import ToolExecutionError, run_tool
from tools.docstring_builder.harvest import iter_target_files
from tools.docstring_builder.paths import REPO_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from tools.docstring_builder.config import BuilderConfig

LOGGER = get_logger(__name__)

DEFAULT_IGNORE_PATTERNS: list[str] = [
    "tests/e2e/**",
    "tests/mock_servers/**",
    "tests/tools/**",
    "docs/_scripts/**",
    "docs/conf.py",
    "src/__init__.py",
]


class InvalidPathError(ValueError):
    """Raised when a user-supplied path falls outside the allowed workspace."""


@dataclass(slots=True, frozen=True)
class SelectionCriteria:
    """Selection filters for docstring builder file discovery."""

    module: str | None = None
    since: str | None = None
    changed_only: bool = False
    explicit_paths: Sequence[str] | None = None


def resolve_ignore_patterns(config: BuilderConfig) -> list[str]:
    """Combine default ignore patterns with configuration overrides.

    Parameters
    ----------
    config : BuilderConfig
        Builder configuration containing ignore patterns.

    Returns
    -------
    list[str]
        Combined list of ignore patterns with defaults and user overrides.
    """
    patterns = list(DEFAULT_IGNORE_PATTERNS)
    for pattern in config.ignore:
        if pattern not in patterns:
            patterns.append(pattern)
    return patterns


def normalize_input_path(raw: str, *, repo_root: Path = REPO_ROOT) -> Path:
    """Resolve ``raw`` into an absolute Python source path within ``repo_root``.

    Parameters
    ----------
    raw : str
        Input path string (can be relative or absolute).
    repo_root : Path, optional
        Repository root directory. Defaults to REPO_ROOT.

    Returns
    -------
    Path
        Absolute path to a Python source file within the repository.

    Raises
    ------
    InvalidPathError
        If the path doesn't exist, escapes the repository root, or is not a Python file.
    """
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:  # pragma: no cover - defensive guard
        message = f"Path '{raw}' does not exist"
        raise InvalidPathError(message) from exc
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        message = f"Path '{raw}' escapes the repository root"
        raise InvalidPathError(message) from exc
    if not resolved.is_file() or resolved.suffix != ".py":
        message = f"Path '{raw}' must reference a Python source file"
        raise InvalidPathError(message)
    return resolved


def module_to_path(module: str, *, repo_root: Path = REPO_ROOT) -> Path | None:
    """Best-effort mapping from dotted module name to a filesystem path.

    Parameters
    ----------
    module : str
        Dotted module name (e.g., "tools.docstring_builder").
    repo_root : Path, optional
        Repository root directory. Defaults to REPO_ROOT.

    Returns
    -------
    Path | None
        Filesystem path to the module file if found, None otherwise.
    """
    if not module:
        return None

    parts = module.split(".")
    fallback: Path | None = None

    for relative in _iter_search_candidates(parts, repo_root):
        resolved, candidate_fallback = _resolve_module_candidate(relative, repo_root)
        if resolved is not None:
            return resolved
        if fallback is None:
            fallback = candidate_fallback

    if fallback is not None:
        return fallback

    return _default_module_path(parts, repo_root)


def _iter_search_candidates(parts: Sequence[str], repo_root: Path) -> tuple[Path, ...]:
    """Generate candidate paths for module resolution.

    Parameters
    ----------
    parts : Sequence[str]
        Module name parts (e.g., ["tools", "docstring_builder"]).
    repo_root : Path
        Repository root directory.

    Returns
    -------
    tuple[Path, ...]
        Tuple of candidate relative paths to search.
    """
    roots: list[Path] = [Path("src"), Path("tools")]
    if (repo_root / "docs").exists():
        roots.append(Path("docs"))
    return tuple(_resolve_relative(parts, root) for root in roots)


def _resolve_relative(parts: Sequence[str], root: Path) -> Path:
    """Resolve module parts relative to a root directory.

    Parameters
    ----------
    parts : Sequence[str]
        Module name parts.
    root : Path
        Root directory path.

    Returns
    -------
    Path
        Relative path combining root and parts.
    """
    if parts and parts[0] == root.name:
        return Path(*parts)
    return root.joinpath(*parts)


def _resolve_module_candidate(
    relative: Path, repo_root: Path
) -> tuple[Path | None, Path]:
    """Resolve a module candidate path and return both resolved and fallback.

    Parameters
    ----------
    relative : Path
        Relative path candidate.
    repo_root : Path
        Repository root directory.

    Returns
    -------
    tuple[Path | None, Path]
        Tuple of (resolved_path, fallback_path) where resolved_path is None if not found.
    """
    candidate = repo_root / relative
    if candidate.suffix:
        return candidate, candidate

    module_file = candidate.with_suffix(".py")
    if module_file.exists():
        return module_file, module_file

    package_init = candidate / "__init__.py"
    if package_init.exists():
        return package_init, module_file

    return None, module_file


def _default_module_path(parts: Sequence[str], repo_root: Path) -> Path:
    """Generate default module path from parts.

    Parameters
    ----------
    parts : Sequence[str]
        Module name parts.
    repo_root : Path
        Repository root directory.

    Returns
    -------
    Path
        Default path with .py extension if missing.
    """
    candidate = repo_root.joinpath(*parts)
    return candidate if candidate.suffix else candidate.with_suffix(".py")


def module_name_from_path(path: Path, *, repo_root: Path = REPO_ROOT) -> str:
    """Derive a dotted module name from ``path`` relative to ``repo_root``.

    Parameters
    ----------
    path : Path
        Filesystem path to a Python file.
    repo_root : Path, optional
        Repository root directory. Defaults to REPO_ROOT.

    Returns
    -------
    str
        Dotted module name (e.g., "tools.docstring_builder").
    """
    rel = path.relative_to(repo_root)
    parts = rel.with_suffix("").parts
    if parts and parts[0] in {"src", "tools", "docs"}:
        parts = parts[1:]
    return ".".join(parts)


def dependents_for(path: Path) -> set[Path]:
    """Return potential dependent files that should be processed together.

    Parameters
    ----------
    path : Path
        Path to a Python file.

    Returns
    -------
    set[Path]
        Set of dependent file paths (e.g., __init__.py for packages).
    """
    dependents: set[Path] = set()
    if path.name == "__init__.py":
        for candidate in path.parent.glob("*.py"):
            if candidate != path and candidate.is_file():
                dependents.add(candidate.resolve())
    else:
        init_file = (path.parent / "__init__.py").resolve()
        if init_file.exists():
            dependents.add(init_file)
    return dependents


def matches_patterns(
    path: Path, patterns: Iterable[str], *, repo_root: Path = REPO_ROOT
) -> bool:
    """Return ``True`` when ``path`` matches any ``patterns`` relative to ``repo_root``.

    Parameters
    ----------
    path : Path
        File path to check.
    patterns : Iterable[str]
        Glob patterns to match against.
    repo_root : Path, optional
        Repository root directory. Defaults to REPO_ROOT.

    Returns
    -------
    bool
        True if path matches any pattern, False otherwise.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:  # pragma: no cover - defensive guard
        rel = path
    return any(rel.match(pattern) for pattern in patterns)


def should_ignore(
    path: Path, config: BuilderConfig, *, repo_root: Path = REPO_ROOT
) -> bool:
    """Return ``True`` when ``path`` should be ignored according to ``config``.

    Parameters
    ----------
    path : Path
        File path to check.
    config : BuilderConfig
        Builder configuration with ignore patterns.
    repo_root : Path, optional
        Repository root directory. Defaults to REPO_ROOT.

    Returns
    -------
    bool
        True if path matches any ignore pattern, False otherwise.
    """
    rel = path.relative_to(repo_root)
    patterns = resolve_ignore_patterns(config)
    for pattern in patterns:
        if rel.match(pattern):
            LOGGER.debug(
                "Skipping %s because it matches ignore pattern %s", rel, pattern
            )
            return True
    return False


def changed_files_since(revision: str, *, repo_root: Path = REPO_ROOT) -> set[str]:
    """Return the set of file paths changed since ``revision``.

    Parameters
    ----------
    revision : str
        Git revision (commit hash, branch, tag, etc.).
    repo_root : Path, optional
        Repository root directory. Defaults to REPO_ROOT.

    Returns
    -------
    set[str]
        Set of relative file paths changed since the revision.
    """
    cmd = ["git", "-C", str(repo_root), "diff", "--name-only", revision, "HEAD", "--"]
    try:
        result = run_tool(cmd, timeout=20.0)
    except ToolExecutionError as exc:  # pragma: no cover - git missing
        LOGGER.warning("git diff failed: %s", exc)
        return set()
    if result.returncode != 0:
        LOGGER.warning("git diff failed: %s", result.stderr.strip())
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def default_since_revision(*, repo_root: Path = REPO_ROOT) -> str | None:
    """Return a sensible default revision for ``--changed-only`` runs.

    Parameters
    ----------
    repo_root : Path, optional
        Repository root directory. Defaults to REPO_ROOT.

    Returns
    -------
    str | None
        Revision string (commit hash) if found, None otherwise.
    """
    candidates = [
        ["git", "-C", str(repo_root), "merge-base", "HEAD", "origin/main"],
        ["git", "-C", str(repo_root), "rev-parse", "HEAD~1"],
    ]
    for cmd in candidates:
        try:
            result = run_tool(cmd, timeout=10.0)
        except ToolExecutionError:
            continue
        if result.returncode == 0:
            revision = result.stdout.strip()
            if revision:
                return revision
    return None


def _resolve_explicit_paths(
    explicit_paths: Sequence[str],
    *,
    repo_root: Path,
) -> list[Path]:
    """Resolve explicit file paths from string inputs.

    Parameters
    ----------
    explicit_paths : Sequence[str]
        List of path strings to resolve.
    repo_root : Path
        Repository root directory.

    Returns
    -------
    list[Path]
        List of normalized absolute paths.
    """
    return [normalize_input_path(raw, repo_root=repo_root) for raw in explicit_paths]


def _discover_target_files(config: BuilderConfig, *, repo_root: Path) -> list[Path]:
    """Discover target files matching include/exclude patterns.

    Parameters
    ----------
    config : BuilderConfig
        Builder configuration with include/exclude patterns.
    repo_root : Path
        Repository root directory.

    Returns
    -------
    list[Path]
        List of resolved file paths matching the patterns.
    """
    files: list[Path] = []
    for path in iter_target_files(config, repo_root):
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError:  # pragma: no cover - stale glob entry
            continue
        try:
            resolved.relative_to(repo_root)
        except ValueError:
            LOGGER.warning("Ignoring path outside repository: %s", resolved)
            continue
        if should_ignore(resolved, config, repo_root=repo_root):
            continue
        files.append(resolved)
    return files


def _filter_by_module(
    files: Iterable[Path],
    module: str | None,
    *,
    repo_root: Path,
) -> list[Path]:
    """Filter files by module name prefix.

    Parameters
    ----------
    files : Iterable[Path]
        File paths to filter.
    module : str | None
        Module name prefix to match (e.g., "tools.docstring_builder").
    repo_root : Path
        Repository root directory.

    Returns
    -------
    list[Path]
        Filtered list of paths matching the module prefix.
    """
    if not module:
        return list(files)
    return [
        candidate
        for candidate in files
        if module_name_from_path(candidate, repo_root=repo_root).startswith(module)
    ]


def _filter_by_revision(
    files: Iterable[Path],
    since: str | None,
    *,
    repo_root: Path,
) -> list[Path]:
    """Filter files changed since a git revision.

    Parameters
    ----------
    files : Iterable[Path]
        File paths to filter.
    since : str | None
        Git revision to compare against.
    repo_root : Path
        Repository root directory.

    Returns
    -------
    list[Path]
        Filtered list of paths changed since the revision.
    """
    if not since:
        return list(files)
    changed = set(changed_files_since(since, repo_root=repo_root))
    if not changed:
        return []
    return [path for path in files if str(path.relative_to(repo_root)) in changed]


def _expand_dependencies(
    candidates: Iterable[Path],
    config: BuilderConfig,
    *,
    repo_root: Path,
) -> list[Path]:
    """Expand candidate files to include their dependencies.

    Parameters
    ----------
    candidates : Iterable[Path]
        Initial file paths.
    config : BuilderConfig
        Builder configuration.
    repo_root : Path
        Repository root directory.

    Returns
    -------
    list[Path]
        Expanded list including dependencies (e.g., __init__.py files).
    """
    expanded: dict[Path, None] = {candidate.resolve(): None for candidate in candidates}
    for candidate in list(expanded.keys()):
        for dependent in dependents_for(candidate):
            if not should_ignore(dependent, config, repo_root=repo_root):
                expanded.setdefault(dependent, None)
    return sorted(expanded.keys())


def select_files(
    config: BuilderConfig,
    criteria: SelectionCriteria | None = None,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[Path]:
    """Return the set of candidate files based on CLI-style selection options.

    Parameters
    ----------
    config : BuilderConfig
        Builder configuration.
    criteria : SelectionCriteria | None, optional
        Selection criteria (module, since, explicit_paths, etc.).
    repo_root : Path, optional
        Repository root directory. Defaults to REPO_ROOT.

    Returns
    -------
    list[Path]
        Sorted list of selected file paths.
    """
    options = criteria or SelectionCriteria()
    if options.explicit_paths:
        return _resolve_explicit_paths(options.explicit_paths, repo_root=repo_root)

    files = _discover_target_files(config, repo_root=repo_root)
    filtered = _filter_by_module(files, options.module, repo_root=repo_root)
    filtered = _filter_by_revision(filtered, options.since, repo_root=repo_root)

    if options.changed_only or options.since:
        return _expand_dependencies(filtered, config, repo_root=repo_root)

    return sorted(filtered)


def hash_file(path: Path) -> str:
    """Return the SHA-256 digest for ``path``.

    Parameters
    ----------
    path : Path
        File path to hash.

    Returns
    -------
    str
        SHA-256 hex digest of the file contents.
    """
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def read_baseline_version(
    baseline: str, path: Path, *, repo_root: Path = REPO_ROOT
) -> str | None:
    """Return the file contents for ``path`` from ``baseline`` when available.

    Parameters
    ----------
    baseline : str
        Baseline identifier (git revision or directory path).
    path : Path
        File path to read.
    repo_root : Path, optional
        Repository root directory. Defaults to REPO_ROOT.

    Returns
    -------
    str | None
        File contents if found, None otherwise.
    """
    if not baseline:
        return None
    candidate = Path(baseline)
    relative = path.relative_to(repo_root)
    if candidate.exists():
        base_path = candidate / relative if candidate.is_dir() else candidate
        try:
            return base_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
    command = [
        "git",
        "-C",
        str(repo_root),
        "show",
        f"{baseline}:{relative.as_posix()}",
    ]
    try:
        result = run_tool(command, timeout=10.0)
    except ToolExecutionError as exc:  # pragma: no cover - git missing
        LOGGER.debug(
            "Unable to read %s from baseline %s: %s",
            relative,
            baseline,
            exc,
        )
        return None
    if result.returncode != 0:
        LOGGER.debug(
            "Unable to read %s from baseline %s: %s",
            relative,
            baseline,
            result.stderr,
        )
        return None
    return result.stdout


__all__ = [
    "DEFAULT_IGNORE_PATTERNS",
    "InvalidPathError",
    "SelectionCriteria",
    "changed_files_since",
    "default_since_revision",
    "dependents_for",
    "hash_file",
    "matches_patterns",
    "module_name_from_path",
    "module_to_path",
    "normalize_input_path",
    "read_baseline_version",
    "resolve_ignore_patterns",
    "select_files",
    "should_ignore",
]
