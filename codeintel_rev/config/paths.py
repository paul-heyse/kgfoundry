"""Pure path resolution utilities for CodeIntel applications."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from codeintel_rev.config.settings import PathsConfig, Settings

__all__ = ["ResolvedPaths", "resolve_application_paths"]

type PathInput = str | os.PathLike[str] | Path


@dataclass(frozen=True, slots=True)
class ResolvedPaths:
    """Immutable collection of canonical filesystem locations.

    Attributes
    ----------
    repo_root : Path
        Repository root directory path. All other paths are resolved relative
        to this root.
    config_dir : Path
        Directory path for application configuration files.
    config_file : Path
        Path to the main application configuration file (typically app.yml).
    data_dir : Path
        Directory path for application data files.
    vectors_dir : Path
        Directory path containing vector embedding Parquet files.
    faiss_index : Path
        Path to the FAISS vector index file.
    faiss_idmap_path : Path
        Path to the FAISS ID map Parquet file mapping FAISS row indices to
        external chunk IDs.
    lucene_dir : Path
        Directory path containing Lucene indexes (BM25, SPLADE).
    splade_dir : Path
        Directory path for SPLADE-specific indexes and artifacts.
    duckdb_path : Path
        Path to the DuckDB catalog database file.
    scip_index : Path
        Path to the SCIP symbol index file.
    coderank_vectors_dir : Path
        Directory path for CodeRank vector embeddings.
    coderank_faiss_index : Path
        Path to the CodeRank FAISS index file.
    warp_index_dir : Path
        Directory path for WARP XTR indexes.
    xtr_dir : Path
        Directory path for XTR token-level indexes.
    logs_dir : Path
        Directory path for application log files.
    cache_dir : Path
        Directory path for cached artifacts and temporary data.
    tmp_dir : Path
        Directory path for temporary files.
    plugins_dir : Path
        Directory path for application plugins.
    """

    repo_root: Path
    config_dir: Path
    config_file: Path
    data_dir: Path
    vectors_dir: Path
    faiss_index: Path
    faiss_idmap_path: Path
    lucene_dir: Path
    splade_dir: Path
    duckdb_path: Path
    scip_index: Path
    coderank_vectors_dir: Path
    coderank_faiss_index: Path
    warp_index_dir: Path
    xtr_dir: Path
    logs_dir: Path
    cache_dir: Path
    tmp_dir: Path
    plugins_dir: Path


def _to_path(value: PathInput) -> Path:
    """Convert path-like input to a Path object.

    This helper function normalizes various path input types (strings, os.PathLike,
    or Path objects) into a consistent Path instance. Used throughout the path
    resolution system to ensure uniform path handling regardless of input format.

    Parameters
    ----------
    value : PathInput
        Path input that can be a string, os.PathLike, or Path object. The value
        is converted to a Path instance for consistent processing.

    Returns
    -------
    Path
        Path object representing the input value. If already a Path, returns it
        unchanged; otherwise constructs a new Path from the input.

    Notes
    -----
    This function is a core utility in the path resolution system, enabling
    flexible input handling while maintaining type safety. It ensures that all
    downstream path operations work with Path objects, which provide better
    cross-platform compatibility and path manipulation capabilities.
    """
    if isinstance(value, Path):
        return value
    return Path(value)


def _norm(path: Path) -> Path:
    """Normalize a path by expanding user home directory and resolving to absolute form.

    This function performs comprehensive path normalization including home directory
    expansion, resolution to absolute paths, and platform-specific case normalization
    on Windows. The normalization ensures paths are in a canonical form suitable for
    comparison, storage, and cross-platform compatibility.

    Parameters
    ----------
    path : Path
        Input path to normalize. May be relative or absolute, and may contain
        user home directory references (e.g., ~/data).

    Returns
    -------
    Path
        Normalized path with home directory expanded, resolved to absolute form
        (when possible), and case-normalized on Windows. If resolution fails due
        to missing filesystem entries, returns the expanded path without resolution.

    Notes
    -----
    Path normalization is critical for ensuring consistent path handling across
    different operating systems and user environments. The function handles edge
    cases like missing filesystem entries gracefully by falling back to expanded
    paths. Windows case normalization ensures case-insensitive path comparisons
    work correctly.
    """
    expanded = path.expanduser()
    try:
        resolved = expanded.resolve(strict=False)
    except (OSError, RuntimeError):
        resolved = expanded
    if sys.platform.startswith("win"):
        return Path(os.path.normcase(str(resolved)))
    return resolved


def _resolve_relative(base: Path, candidate: PathInput) -> Path:
    """Resolve a candidate path relative to a base directory, handling both absolute and relative paths.

    This function resolves paths that may be either absolute or relative to a base
    directory. Absolute paths are normalized and returned as-is, while relative
    paths are joined with the base directory and normalized. This enables flexible
    path configuration where users can specify either absolute paths or paths
    relative to the repository root.

    Parameters
    ----------
    base : Path
        Base directory used for resolving relative paths. Typically the repository
        root directory. Must be an absolute, normalized path.
    candidate : PathInput
        Path candidate that may be absolute or relative. If absolute, used directly;
        if relative, joined with the base directory.

    Returns
    -------
    Path
        Resolved and normalized path. Absolute candidates are normalized and returned;
        relative candidates are joined with base and normalized.

    Notes
    -----
    This function is essential for the path resolution system, allowing configuration
    to specify paths either absolutely (for explicit control) or relatively (for
    portability). The normalization step ensures all returned paths are in canonical
    form suitable for filesystem operations and comparisons.
    """
    raw = _to_path(candidate)
    if raw.is_absolute():
        return _norm(raw)
    return _norm(base / raw)


def _default_repo_root() -> Path:
    """Determine the default repository root directory from the current module location.

    This function computes the repository root by traversing up the directory tree
    from the current module file location. It assumes a standard project layout
    where the config module is located at `codeintel_rev/config/paths.py`, and
    the repository root is two levels up. Used as a fallback when repository root
    is not explicitly configured.

    Returns
    -------
    Path
        Normalized absolute path to the repository root directory. The path is
        computed relative to this module's location and normalized for consistency.

    Notes
    -----
    The default repository root detection enables the application to work without
    explicit configuration in standard project layouts. This is particularly useful
    for development environments and when running from the repository directory.
    The function assumes a specific directory structure and may need adjustment
    if the project layout changes.
    """
    return _norm(Path(__file__).resolve().parents[2])


def _build_from_mapping(settings: Mapping[str, Any]) -> ResolvedPaths:
    """Build ResolvedPaths from a dictionary-like settings mapping.

    This function constructs a ResolvedPaths instance from a mapping (typically
    from environment variables or test fixtures) by extracting path configuration
    values and resolving them relative to the repository root. The function handles
    multiple repository root key names for compatibility and provides sensible
    defaults for all path components. Used primarily for testing and environment-based
    configuration.

    Parameters
    ----------
    settings : Mapping[str, Any]
        Dictionary-like object containing path configuration keys. Supports both
        uppercase (e.g., "DATA_DIR") and lowercase (e.g., "data_dir") key variants.
        Repository root can be specified via "BASE_DIR", "repo_root", or
        "paths_repo_root" keys.

    Returns
    -------
    ResolvedPaths
        Fully resolved paths instance with all application paths computed from
        the settings mapping. Paths are normalized and resolved relative to the
        repository root, with defaults applied for any missing configuration.

    Notes
    -----
    This function enables flexible configuration via environment variables or test
    fixtures without requiring a full Settings object. The dual key format (uppercase
    and lowercase) provides compatibility with different configuration styles. All
    paths are normalized and resolved to ensure consistency across different
    environments and operating systems.

    See Also
    --------
    _build_from_settings : Build ResolvedPaths from a Settings object.
    resolve_application_paths : Public API that delegates to this function.
    """
    repo_value = (
        settings.get("BASE_DIR") or settings.get("repo_root") or settings.get("paths_repo_root")
    )
    repo_root = (
        _norm(_to_path(cast("PathInput", repo_value)))
        if repo_value is not None
        else _default_repo_root()
    )

    def _setting(key: str, default: Path) -> Path:
        """Extract and resolve a path setting from the settings mapping.

        This nested helper function extracts a path value from the settings mapping,
        supporting both uppercase and lowercase key variants. If the key is found,
        the value is resolved relative to the repository root; otherwise, the default
        path is normalized and returned. This enables flexible configuration with
        fallback defaults.

        Parameters
        ----------
        key : str
            Configuration key to look up (e.g., "DATA_DIR"). The function checks
            both the exact key and its lowercase variant for compatibility.
        default : Path
            Default path to use if the key is not found in settings. The default
            is normalized before being returned.

        Returns
        -------
        Path
            Resolved path from settings if found, or normalized default path if
            the key is missing. All paths are normalized and resolved relative to
            the repository root.
        """
        raw = settings.get(key)
        if raw is None:
            raw = settings.get(key.lower())
        return (
            _resolve_relative(repo_root, cast("PathInput", raw))
            if raw is not None
            else _norm(default)
        )

    config_dir = _setting("CONFIG_DIR", repo_root / "config")
    config_file_default = config_dir / "app.yml"
    return ResolvedPaths(
        repo_root=repo_root,
        config_dir=config_dir,
        config_file=_setting("CONFIG_FILE", config_file_default),
        data_dir=_setting("DATA_DIR", repo_root / "data"),
        vectors_dir=_setting("VECTORS_DIR", repo_root / "data" / "vectors"),
        faiss_index=_setting(
            "FAISS_INDEX",
            repo_root / "data" / "faiss" / "code.ivfpq.faiss",
        ),
        faiss_idmap_path=_setting(
            "FAISS_IDMAP_PATH",
            repo_root / "data" / "faiss" / "faiss_idmap.parquet",
        ),
        lucene_dir=_setting("LUCENE_DIR", repo_root / "data" / "lucene"),
        splade_dir=_setting("SPLADE_DIR", repo_root / "data" / "splade"),
        duckdb_path=_setting("DUCKDB_PATH", repo_root / "data" / "catalog.duckdb"),
        scip_index=_setting("SCIP_INDEX", repo_root / "index.scip"),
        coderank_vectors_dir=_setting(
            "CODERANK_VECTORS_DIR",
            repo_root / "data" / "coderank_vectors",
        ),
        coderank_faiss_index=_setting(
            "CODERANK_FAISS_INDEX",
            repo_root / "data" / "faiss" / "coderank.ivfpq.faiss",
        ),
        warp_index_dir=_setting("WARP_INDEX_DIR", repo_root / "indexes" / "warp_xtr"),
        xtr_dir=_setting("XTR_DIR", repo_root / "data" / "xtr"),
        logs_dir=_setting("LOGS_DIR", repo_root / "logs"),
        cache_dir=_setting("CACHE_DIR", repo_root / ".cache"),
        tmp_dir=_setting("TMP_DIR", repo_root / ".tmp"),
        plugins_dir=_setting("PLUGINS_DIR", repo_root / "plugins"),
    )


def _build_from_settings(settings: Settings) -> ResolvedPaths:
    """Build ResolvedPaths from a fully constructed Settings object.

    This function constructs a ResolvedPaths instance from a Settings object by
    extracting path configuration from the PathsConfig component. All paths are
    resolved relative to the configured repository root and normalized for consistency.
    This is the primary path resolution method used in production code.

    Parameters
    ----------
    settings : Settings
        Fully constructed Settings object containing path configuration. The
        settings.paths attribute must contain a PathsConfig with all required
        path values.

    Returns
    -------
    ResolvedPaths
        Fully resolved paths instance with all application paths computed from
        the Settings object. Paths are normalized and resolved relative to the
        repository root specified in the settings.

    Notes
    -----
    This function is the preferred method for path resolution in production code,
    as it works with the fully typed Settings object and provides better type
    safety. The function ensures all paths are normalized and resolved, providing
    consistent path handling regardless of how paths are specified in configuration.

    See Also
    --------
    _build_from_mapping : Build ResolvedPaths from a dictionary mapping.
    resolve_application_paths : Public API that delegates to this function.
    """
    cfg: PathsConfig = settings.paths
    repo_root = _norm(_to_path(cfg.repo_root))

    def _resolve(value: str) -> Path:
        """Resolve a path string relative to the repository root.

        This nested helper function resolves path strings from the PathsConfig
        relative to the repository root. Used to convert relative path strings
        from configuration into absolute, normalized Path objects.

        Parameters
        ----------
        value : str
            Path string from configuration. May be absolute or relative to the
            repository root.

        Returns
        -------
        Path
            Resolved and normalized path relative to the repository root. The path
            is normalized for consistency across platforms.
        """
        return _resolve_relative(repo_root, value)

    config_dir = _norm(repo_root / "config")
    config_file_default = _norm(config_dir / "app.yml")
    return ResolvedPaths(
        repo_root=repo_root,
        config_dir=config_dir,
        config_file=config_file_default,
        data_dir=_resolve(cfg.data_dir),
        vectors_dir=_resolve(cfg.vectors_dir),
        faiss_index=_resolve(cfg.faiss_index),
        faiss_idmap_path=_resolve(cfg.faiss_idmap_path),
        lucene_dir=_resolve(cfg.lucene_dir),
        splade_dir=_resolve(cfg.splade_dir),
        duckdb_path=_resolve(cfg.duckdb_path),
        scip_index=_resolve(cfg.scip_index),
        coderank_vectors_dir=_resolve(cfg.coderank_vectors_dir),
        coderank_faiss_index=_resolve(cfg.coderank_faiss_index),
        warp_index_dir=_resolve(cfg.warp_index_dir),
        xtr_dir=_resolve(cfg.xtr_dir),
        logs_dir=_norm(repo_root / "logs"),
        cache_dir=_norm(repo_root / ".cache"),
        tmp_dir=_norm(repo_root / ".tmp"),
        plugins_dir=_norm(repo_root / "plugins"),
    )


def resolve_application_paths(settings: Settings | Mapping[str, Any]) -> ResolvedPaths:
    """Return canonical filesystem paths derived from ``settings``.

    Parameters
    ----------
    settings : Settings | Mapping[str, Any]
        Either a fully constructed :class:`Settings` instance or a mapping that
        mimics the environment layout (useful for tests and tooling).

    Returns
    -------
    ResolvedPaths
        Frozen dataclass capturing all filesystem inputs for the application.
        Paths are fully normalized (expanded, resolved, and case-normalized on
        Windows) so downstream consumers can rely on absolute locations.
    """
    if isinstance(settings, Mapping):
        return _build_from_mapping(settings)
    return _build_from_settings(settings)
