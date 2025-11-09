"""Shared utilities for documentation build scripts."""

from __future__ import annotations

import json
import os
import sys
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, cast

from tools import get_logger, with_fields
from tools.detect_pkg import detect_packages, detect_primary
from tools.griffe_utils import resolve_griffe

__all__ = [
    "BuildEnvironment",
    "DocsSettings",
    "GriffeLoader",
    "LinkMode",
    "WarningLogger",
    "build_warning_logger",
    "detect_environment",
    "ensure_sys_paths",
    "load_settings",
    "make_loader",
    "make_logger",
    "resolve_git_sha",
    "safe_json_deserialize",
    "safe_json_serialize",
]

LOGGER = get_logger(__name__)

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    from griffe import Object as GriffeRuntimeObject
    from tools import StructuredLoggerAdapter

    GriffeObject = GriffeRuntimeObject
else:
    GriffeObject = object

LinkMode = Literal["editor", "github", "both"]

_LINK_MODE_MAP: dict[str, LinkMode] = {
    "editor": "editor",
    "github": "github",
    "both": "both",
}


@dataclass(frozen=True, slots=True)
class BuildEnvironment:
    """Repository paths used by docs tooling."""

    root: Path
    src: Path
    tools_dir: Path


@dataclass(frozen=True, slots=True)
class DocsSettings:
    """Normalised environment configuration for docs builds."""

    packages: tuple[str, ...]
    link_mode: LinkMode
    github_org: str | None
    github_repo: str | None
    github_sha: str | None
    docs_build_dir: Path
    navmap_candidates: tuple[Path, ...]


class GriffeLoader(Protocol):
    """Runtime loader capable of resolving packages into Griffe nodes."""

    def load(self, package: str) -> GriffeObject:  # pragma: no cover - runtime protocol
        """Return the module graph for ``package``."""
        ...


class WarningLogger(Protocol):
    """Logger interface supporting ``warning`` calls."""

    def warning(self, msg: str, *args: object, **kwargs: object) -> None:
        """Log a warning message."""


def _loader_factory() -> Callable[..., GriffeLoader]:
    return cast("Callable[..., GriffeLoader]", resolve_griffe().loader_type)


@lru_cache(maxsize=1)
def detect_environment() -> BuildEnvironment:
    """Return filesystem locations relevant to docs tooling.

    Returns
    -------
    BuildEnvironment
        Build environment with root, src, and tools_dir paths.
    """
    root = Path(__file__).resolve().parents[2]
    src = root / "src"
    tools_dir = root / "tools"
    return BuildEnvironment(root=root, src=src, tools_dir=tools_dir)


def ensure_sys_paths(env: BuildEnvironment) -> None:
    """Add docs-relevant paths to ``sys.path`` when missing."""
    for candidate in (env.src, env.root, env.tools_dir):
        path_str = str(candidate)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)


@lru_cache(maxsize=1)
def load_settings() -> DocsSettings:
    """Return docs settings derived from environment variables.

    Returns
    -------
    DocsSettings
        Documentation build settings.
    """
    env = detect_environment()

    env_pkgs = os.environ.get("DOCS_PKG")
    if env_pkgs:
        packages = tuple(pkg.strip() for pkg in env_pkgs.split(",") if pkg.strip())
    else:
        discovered = detect_packages()
        packages = tuple(discovered or [detect_primary()])

    link_mode_raw = os.environ.get("DOCS_LINK_MODE", "both").lower()
    link_mode = _LINK_MODE_MAP.get(link_mode_raw)
    if link_mode is None:
        LOGGER.warning("Unsupported DOCS_LINK_MODE '%s'; defaulting to 'both'", link_mode_raw)
        link_mode = "both"

    docs_build_dir = env.root / "docs" / "_build"
    navmap_candidates: tuple[Path, ...] = (
        docs_build_dir / "navmap.json",
        docs_build_dir / "navmap" / "navmap.json",
        env.root / "site" / "_build" / "navmap" / "navmap.json",
    )

    return DocsSettings(
        packages=packages,
        link_mode=link_mode,
        github_org=os.environ.get("DOCS_GITHUB_ORG"),
        github_repo=os.environ.get("DOCS_GITHUB_REPO"),
        github_sha=os.environ.get("DOCS_GITHUB_SHA"),
        docs_build_dir=docs_build_dir,
        navmap_candidates=navmap_candidates,
    )


def make_loader(env: BuildEnvironment) -> GriffeLoader:
    """Instantiate a Griffe loader configured for the repository layout.

    Parameters
    ----------
    env : BuildEnvironment
        Build environment configuration.

    Returns
    -------
    GriffeLoader
        Configured Griffe loader instance.
    """
    search_root = env.src if env.src.exists() else env.root
    loader_cls = _loader_factory()
    return loader_cls(search_paths=[str(search_root)])


def resolve_git_sha(
    env: BuildEnvironment,
    settings: DocsSettings,
    *,
    logger: WarningLogger,
) -> str:
    """Return the Git SHA used when rendering GitHub permalinks.

    Parameters
    ----------
    env : BuildEnvironment
        Build environment configuration.
    settings : DocsSettings
        Documentation settings.
    logger : WarningLogger
        Logger for warnings.

    Returns
    -------
    str
        Git commit SHA or "HEAD" if unavailable.
    """
    if settings.github_sha:
        return settings.github_sha

    git_dir = env.root / ".git"
    head_path = git_dir / "HEAD"
    try:
        head_contents = head_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning(
            "Git metadata missing; using HEAD sentinel",
            extra={"status": "fallback"},
        )
        return "HEAD"

    if head_contents.startswith("ref: "):
        ref_path = git_dir / head_contents.removeprefix("ref: ").strip()
        with suppress(FileNotFoundError):
            ref_contents = ref_path.read_text(encoding="utf-8").strip()
            if ref_contents:
                return ref_contents
        logger.warning(
            "Ref %s missing; using HEAD sentinel",
            ref_path,
            extra={"status": "fallback"},
        )
        return "HEAD"

    return head_contents or "HEAD"


def make_logger(
    operation: str,
    *,
    artifact: str | None = None,
    logger: logging.Logger | StructuredLoggerAdapter | None = None,
) -> StructuredLoggerAdapter:
    """Return a structured logger adapter enriched with docs metadata.

    Parameters
    ----------
    operation : str
        Operation name for logging.
    artifact : str | None, optional
        Artifact name for logging context.
    logger : logging.Logger | StructuredLoggerAdapter | None, optional
        Base logger instance, defaults to operation-specific logger.

    Returns
    -------
    StructuredLoggerAdapter
        Structured logger adapter with enriched metadata.
    """
    base_logger: logging.Logger | StructuredLoggerAdapter = (
        logger if logger is not None else get_logger(f"docs.{operation}")
    )

    fields: dict[str, object] = {"operation": operation}
    if artifact is not None:
        fields["artifact"] = artifact
    return with_fields(base_logger, **fields)


def build_warning_logger(
    operation: str,
    *,
    artifact: str | None = None,
) -> WarningLogger:
    """Return a logger satisfying the WarningLogger protocol for type safety.

    This helper creates a structured logger adapter that can be used wherever
    a WarningLogger protocol is required, ensuring type-safe logging throughout
    the documentation build pipeline.

    Parameters
    ----------
    operation : str
        The operation name for structured logging context.
    artifact : str | None, optional
        Optional artifact name to include in logging context.
        Defaults to None.

    Returns
    -------
    WarningLogger
        A logger satisfying the WarningLogger protocol with a warning() method.

    Examples
    --------
    >>> logger = build_warning_logger("symbol_index")
    >>> logger.warning("Operation started", extra={"status": "pending"})
    """
    logger = make_logger(operation, artifact=artifact)
    return cast("WarningLogger", logger)


def safe_json_serialize(
    data: object,
    path: Path,
    *,
    logger: WarningLogger | None = None,
) -> bool:
    """Write data as JSON to path with type safety and error handling.

    Writes data to a temporary file first, then atomically renames it to avoid
    partial writes. Logs errors and returns False on failure.

    Parameters
    ----------
    data : object
        Data to serialize to JSON.
    path : Path
        Output file path (uses pathlib for safe path handling).
    logger : WarningLogger | None, optional
        Logger for warnings and errors. If None, falls back to module logger.

    Returns
    -------
    bool
        True if write succeeded, False on error.

    Examples
    --------
    >>> from pathlib import Path
    >>> data = {"key": "value", "items": [1, 2, 3]}
    >>> success = safe_json_serialize(data, Path("/tmp/test.json"))
    >>> success
    True
    """
    dest_logger: WarningLogger = logger or cast("WarningLogger", LOGGER)
    temp_path = path.with_suffix(path.suffix + ".tmp")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp_path.replace(path)
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - I/O error
        dest_logger.warning(
            "Failed to write JSON to %s: %s",
            path,
            type(exc).__name__,
            extra={"status": "error", "path": str(path)},
        )
        with suppress(FileNotFoundError):
            temp_path.unlink()
        return False
    else:
        return True


def safe_json_deserialize(
    path: Path,
    *,
    logger: WarningLogger | None = None,
) -> dict[str, object] | list[object] | None:
    """Load JSON from path with type safety and error handling.

    Safely reads JSON files and logs errors on failure. Returns None if the
    file cannot be read or parsed.

    Parameters
    ----------
    path : Path
        Input file path (uses pathlib for safe path handling).
    logger : WarningLogger | None, optional
        Logger for warnings and errors. If None, falls back to module logger.

    Returns
    -------
    dict[str, object] | list[object] | None
        Parsed JSON object/array, or None on error.

    Examples
    --------
    >>> from pathlib import Path
    >>> data = safe_json_deserialize(Path("/tmp/test.json"))
    >>> isinstance(data, dict)
    True
    """
    dest_logger: WarningLogger = logger or cast("WarningLogger", LOGGER)

    try:
        if not path.exists():
            dest_logger.warning(
                "JSON file not found: %s",
                path,
                extra={"status": "not_found", "path": str(path)},
            )
            return None

        content = path.read_text(encoding="utf-8")
        result: object = json.loads(content)
        if not isinstance(result, (dict, list)):
            dest_logger.warning(
                "JSON root must be object or array, got: %s",
                type(result).__name__,
                extra={"status": "invalid_type", "path": str(path)},
            )
            return None
    except json.JSONDecodeError as exc:  # pragma: no cover - I/O error
        dest_logger.warning(
            "Failed to parse JSON from %s: %s",
            path,
            exc.msg,
            extra={"status": "parse_error", "path": str(path), "line": exc.lineno},
        )
        return None
    except OSError as exc:  # pragma: no cover - I/O error
        dest_logger.warning(
            "Failed to read JSON from %s: %s",
            path,
            type(exc).__name__,
            extra={"status": "error", "path": str(path)},
        )
        return None
    else:
        return result
