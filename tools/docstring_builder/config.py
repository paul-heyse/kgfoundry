"""Configuration loading utilities for the docstring builder."""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from tools._shared.logging import get_logger

LOGGER = get_logger(__name__)

DEFAULT_CONFIG_PATH = Path("docstring_builder.toml")
DEFAULT_MARKER = "<!-- auto:docstring-builder v1 -->"
_CACHE_VERSION = "2025-02-06-indent"
_ENV_CONFIG = "KGF_DOCSTRINGS_CONFIG"
_LEGACY_ENV_CONFIG = "DOCSTRING_BUILDER_CONFIG"


@dataclass(slots=True, frozen=True)
class ConfigSelection:
    """Selected configuration path and its provenance."""

    path: Path
    source: str


@dataclass(slots=True, frozen=True)
class PackageSettings:
    """Per-package overrides to steer summaries and opt-outs."""

    summary_verbs: dict[str, str] = field(default_factory=dict)
    opt_out: set[str] = field(default_factory=set)


@dataclass(slots=True, frozen=True)
class BuilderConfig:
    """Runtime configuration resolved from ``docstring_builder.toml``."""

    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    ownership_marker: str = DEFAULT_MARKER
    dynamic_probes: bool = False
    normalize_sections: bool = False
    package_settings: PackageSettings = field(default_factory=PackageSettings)
    navmap_metadata: bool = True
    ignore: list[str] = field(default_factory=list)
    llm_summary_mode: str = "off"
    render_signature: bool = False

    @property
    def config_hash(self) -> str:
        """Return a stable hash representing the config values.

        Returns
        -------
        str
            SHA256 hash hex digest of the configuration payload.
        """
        payload = {
            "include": self.include,
            "exclude": self.exclude,
            "ownership_marker": self.ownership_marker,
            "dynamic_probes": self.dynamic_probes,
            "normalize_sections": self.normalize_sections,
            "summary_verbs": self.package_settings.summary_verbs,
            "opt_out": sorted(self.package_settings.opt_out),
            "navmap_metadata": self.navmap_metadata,
            "ignore": self.ignore,
            "llm_summary_mode": self.llm_summary_mode,
            "render_signature": self.render_signature,
            "builder_cache_version": _CACHE_VERSION,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


TomlMapping = dict[str, object]


def _load_toml(path: Path) -> TomlMapping:
    if not path.exists():
        LOGGER.debug("docstring_builder config missing at %s", path)
        return {}
    LOGGER.debug("Loading docstring builder config from %s", path)
    with path.open("rb") as stream:
        return cast("TomlMapping", tomllib.load(stream))


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value]
    msg = f"Unsupported list-like value: {value!r}"
    raise TypeError(msg)


def _package_settings_from(data: Mapping[str, object]) -> PackageSettings:
    packages_value = data.get("packages")
    packages_mapping = (
        cast("Mapping[str, object]", packages_value) if isinstance(packages_value, Mapping) else {}
    )
    summary_verbs_raw = packages_mapping.get("summary_verbs")
    if isinstance(summary_verbs_raw, Mapping):
        summary_verbs = {str(key): str(value) for key, value in summary_verbs_raw.items()}
    else:
        summary_verbs = {}
    opt_out_values = _as_list(packages_mapping.get("opt_out")) if packages_mapping else []
    return PackageSettings(
        summary_verbs=summary_verbs, opt_out={str(item) for item in opt_out_values}
    )


def _bool_option(data: Mapping[str, object], key: str, *, default: bool = False) -> bool:
    raw_value = data.get(key, default)
    return bool(raw_value)


def load_config(path: Path | None = None) -> BuilderConfig:
    """Load configuration from the provided path or default location.

    Parameters
    ----------
    path : Path | None, optional
        Path to configuration file. If None, uses ``DEFAULT_CONFIG_PATH``.

    Returns
    -------
    BuilderConfig
        Loaded configuration instance with defaults applied for missing values.
    """
    config_path = path or DEFAULT_CONFIG_PATH
    data = _load_toml(config_path)

    include = [str(pattern) for pattern in _as_list(data.get("include")) or ["src/**/*.py"]]
    exclude = [
        str(pattern)
        for pattern in _as_list(data.get("exclude"))
        or ["tests/**", "site/**", "docs/_build/**", "tools/**"]
    ]
    ignore = [str(pattern) for pattern in _as_list(data.get("ignore"))]
    ownership_marker = str(data.get("ownership_marker", DEFAULT_MARKER))
    dynamic_probes = _bool_option(data, "dynamic_probes")
    normalize_sections = _bool_option(data, "normalize_sections")
    navmap_metadata = _bool_option(data, "navmap_metadata", default=True)
    package_settings = _package_settings_from(data)
    llm_summary_mode = str(data.get("llm_summary_mode", "off")).lower()
    render_signature = _bool_option(data, "render_signature")

    config = BuilderConfig(
        include=include,
        exclude=exclude,
        ownership_marker=ownership_marker,
        dynamic_probes=dynamic_probes,
        normalize_sections=normalize_sections,
        navmap_metadata=navmap_metadata,
        package_settings=package_settings,
        ignore=ignore,
        llm_summary_mode=llm_summary_mode,
        render_signature=render_signature,
    )

    LOGGER.debug("Loaded docstring builder config: include=%s exclude=%s", include, exclude)
    return config


def resolve_config_path(start: Path | None = None) -> Path:
    """Find configuration file by walking up the directory tree.

    Parameters
    ----------
    start : Path | None, optional
        Starting directory for search. If None, uses current working directory.

    Returns
    -------
    Path
        Path to found configuration file, or ``DEFAULT_CONFIG_PATH`` if not found.
    """
    current = start or Path.cwd()
    for directory in [current, *current.parents]:
        candidate = directory / DEFAULT_CONFIG_PATH
        if candidate.exists():
            return candidate
    return DEFAULT_CONFIG_PATH


def _coerce_path(value: str) -> Path:
    path = Path(value).expanduser()
    try:
        return path.resolve(strict=False)
    except FileNotFoundError:  # pragma: no cover - defensive guard for py<3.11
        return path


def select_config_path(override: str | Path | None = None) -> ConfigSelection:
    """Determine the configuration path honouring CLI and environment precedence.

    Parameters
    ----------
    override : str | Path | None, optional
        Explicit path override (typically from CLI).

    Returns
    -------
    ConfigSelection
        Selected configuration path and its source provenance.
    """
    if override:
        path = _coerce_path(str(override))
        return ConfigSelection(path=path, source="cli")

    env_override = os.environ.get(_ENV_CONFIG)
    if env_override:
        path = _coerce_path(env_override)
        return ConfigSelection(path=path, source=f"env:{_ENV_CONFIG}")

    legacy_override = os.environ.get(_LEGACY_ENV_CONFIG)
    if legacy_override:
        path = _coerce_path(legacy_override)
        return ConfigSelection(path=path, source=f"env:{_LEGACY_ENV_CONFIG}")

    default_path = resolve_config_path()
    return ConfigSelection(path=default_path, source="default")


def load_config_with_selection(
    override: str | Path | None = None,
) -> tuple[BuilderConfig, ConfigSelection]:
    """Load configuration while also returning metadata about the selection.

    Parameters
    ----------
    override : str | Path | None, optional
        Explicit path override (typically from CLI).

    Returns
    -------
    tuple[BuilderConfig, ConfigSelection]
        Loaded configuration and selection metadata.
    """
    selection = select_config_path(override)
    config = load_config(selection.path)
    return config, selection


def load_config_from_env() -> BuilderConfig:
    """Load configuration using backwards compatible environment precedence.

    Returns
    -------
    BuilderConfig
        Loaded configuration instance.
    """
    config, _ = load_config_with_selection(None)
    return config


__all__ = [
    "BuilderConfig",
    "ConfigSelection",
    "PackageSettings",
    "load_config",
    "load_config_from_env",
    "load_config_with_selection",
    "resolve_config_path",
    "select_config_path",
]
