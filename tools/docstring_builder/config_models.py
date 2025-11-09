"""Public configuration models for docstring builder operations.

This module defines typed configuration objects for building, processing, and
managing docstrings. All configurations are immutable (frozen dataclasses) and
include built-in validation.

Examples
--------
>>> from tools.docstring_builder.config_models import DocstringBuildConfig
>>> config = DocstringBuildConfig(enable_plugins=True, emit_diff=False, timeout_seconds=600)
>>> config.timeout_seconds
600

Raises
------
ConfigurationError
    When configuration validation fails (e.g., timeout_seconds <= 0).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from kgfoundry_common.errors import ConfigurationError

__all__ = [
    "CachePolicy",
    "DocstringApplyConfig",
    "DocstringBuildConfig",
    "FileProcessConfig",
]


class CachePolicy(Enum):
    """Cache access policy for docstring builder operations.

    Attributes
    ----------
    READ_ONLY
        Only read from cache; do not write new entries.
    WRITE_ONLY
        Only write to cache; do not read existing entries.
    READ_WRITE
        Both read and write to cache (default).
    DISABLED
        Do not use cache at all.
    """

    READ_ONLY = "read_only"
    WRITE_ONLY = "write_only"
    READ_WRITE = "read_write"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class DocstringBuildConfig:
    """Configuration for docstring builder core operations.

    This configuration object controls the behavior of the docstring generation
    pipeline, including cache policy, plugin enablement, diff emission, and
    execution timeouts.

    Attributes
    ----------
    cache_policy : CachePolicy, optional
        Cache access mode. Defaults to READ_WRITE.
    enable_plugins : bool, optional
        Enable plugin system for extended functionality. Defaults to True.
    emit_diff : bool, optional
        Emit diff artifacts comparing old and new docstrings. Defaults to False.
    timeout_seconds : int, optional
        Maximum execution time in seconds. Must be positive. Defaults to 600.
    dynamic_probes : bool, optional
        Enable dynamic type introspection. Defaults to False.
    normalize_sections : bool, optional
        Normalize docstring section formatting. Defaults to False.

    Raises
    ------
    ConfigurationError
        If timeout_seconds <= 0.
    ConfigurationError
        If emit_diff=True and enable_plugins=False (conflicting options).

    Examples
    --------
    >>> config = DocstringBuildConfig(timeout_seconds=300)
    >>> config.cache_policy
    <CachePolicy.READ_WRITE: 'read_write'>

    >>> # This will raise ConfigurationError
    >>> try:
    ...     bad_config = DocstringBuildConfig(timeout_seconds=-1)
    ... except ConfigurationError as e:
    ...     print(f"Configuration error: {e}")
    Configuration error: timeout_seconds must be positive
    """

    cache_policy: CachePolicy = CachePolicy.READ_WRITE
    enable_plugins: bool = True
    emit_diff: bool = False
    timeout_seconds: int = 600
    dynamic_probes: bool = False
    normalize_sections: bool = False

    def __post_init__(self) -> None:
        """Validate configuration constraints.

        Raises
        ------
        ConfigurationError
            If ``timeout_seconds`` is not positive, or if ``emit_diff`` is True
            while ``enable_plugins`` is False.
        """
        if self.timeout_seconds <= 0:
            msg = "timeout_seconds must be positive"
            raise ConfigurationError(
                msg,
                context={
                    "timeout_seconds": self.timeout_seconds,
                    "field": "timeout_seconds",
                },
            )

        # Emit diff requires plugins to be enabled
        if self.emit_diff and not self.enable_plugins:
            msg = "emit_diff requires enable_plugins=True"
            raise ConfigurationError(
                msg,
                context={
                    "emit_diff": self.emit_diff,
                    "enable_plugins": self.enable_plugins,
                    "conflicting_fields": ["emit_diff", "enable_plugins"],
                },
            )


@dataclass(frozen=True, slots=True)
class FileProcessConfig:
    """Configuration for file-level docstring processing.

    Controls behavior when processing individual source files in the
    docstring builder pipeline.

    Attributes
    ----------
    skip_existing : bool, optional
        Skip files that already have docstrings. Defaults to False.
    skip_cache : bool, optional
        Ignore cache and reprocess all files. Defaults to False.
    max_errors_per_file : int, optional
        Maximum errors before stopping file processing. Defaults to 10.

    Examples
    --------
    >>> config = FileProcessConfig(skip_existing=True)
    >>> config.skip_existing
    True
    """

    skip_existing: bool = False
    skip_cache: bool = False
    max_errors_per_file: int = 10

    def __post_init__(self) -> None:
        """Validate file processing constraints.

        Raises
        ------
        ConfigurationError
            If ``max_errors_per_file`` is not positive.
        """
        if self.max_errors_per_file <= 0:
            msg = "max_errors_per_file must be positive"
            raise ConfigurationError(
                msg,
                context={"max_errors_per_file": self.max_errors_per_file},
            )


@dataclass(frozen=True, slots=True)
class DocstringApplyConfig:
    """Configuration for applying generated docstrings to source files.

    Controls how docstring updates are applied during the write phase.

    Attributes
    ----------
    write_changes : bool, optional
        Actually write changes to disk. If False, only dry-run. Defaults to True.
    create_backups : bool, optional
        Create backup files before modifying source. Defaults to True.
    atomic_writes : bool, optional
        Use atomic writes (temp-then-rename) for safety. Defaults to True.

    Examples
    --------
    >>> config = DocstringApplyConfig(write_changes=False)  # Dry-run
    >>> config.write_changes
    False
    """

    write_changes: bool = True
    create_backups: bool = True
    atomic_writes: bool = True

    def __post_init__(self) -> None:
        """Validate apply configuration constraints.

        Raises
        ------
        ConfigurationError
            If ``atomic_writes`` is True while ``write_changes`` is False.
        """
        # Atomic writes require actually writing changes
        if self.atomic_writes and not self.write_changes:
            msg = "atomic_writes requires write_changes=True"
            raise ConfigurationError(
                msg,
                context={
                    "atomic_writes": self.atomic_writes,
                    "write_changes": self.write_changes,
                    "conflicting_fields": ["atomic_writes", "write_changes"],
                },
            )
