"""Optional wrapper around the mkdocs-d2 plugin."""

from __future__ import annotations

import importlib
import logging
import shutil
from collections.abc import Callable
from typing import Any, cast

from mkdocs.config.base import (
    ConfigErrors,
    ConfigWarnings,
    LegacyConfig,
    PlainConfigSchema,
)
from mkdocs.plugins import BasePlugin

LOGGER = logging.getLogger("mkdocs.plugins.optional-d2")
LOGGER.addHandler(logging.NullHandler())


def _load_d2_plugin() -> type[BasePlugin[Any]] | None:
    """Return the mkdocs-d2 plugin class when the dependency is installed.

    Returns
    -------
    type[BasePlugin[Any]] | None
        The D2Plugin class if mkdocs-d2-plugin is installed, otherwise None.
    """
    try:
        module = importlib.import_module("mkdocs_d2_plugin.plugin")
    except ModuleNotFoundError:
        return None
    plugin = getattr(module, "D2Plugin", None)
    if plugin is None:
        return None
    return cast("type[BasePlugin[Any]]", plugin)


D2Plugin = _load_d2_plugin()


def _noop(*_args: object, **_kwargs: object) -> None:
    """Return ``None`` regardless of invocation arguments."""


class OptionalD2Plugin(BasePlugin[LegacyConfig]):
    """Conditionally delegate to the mkdocs-d2 plugin when available."""

    config_scheme: PlainConfigSchema = (
        D2Plugin.config_scheme if D2Plugin is not None else BasePlugin.config_scheme
    )

    def __init__(self) -> None:
        super().__init__()
        self._delegate: BasePlugin[Any] | None = None
        self._warned = False

    def load_config(
        self,
        options: dict[str, Any],
        config_file_path: str | None = None,
    ) -> tuple[ConfigErrors, ConfigWarnings]:
        """Prepare the wrapped mkdocs-d2 plugin when prerequisites are met.

        Parameters
        ----------
        options : dict[str, Any]
            MkDocs plugin configuration dictionary.
        config_file_path : str | None, optional
            Path to the originating configuration file when present.

        Returns
        -------
        tuple[ConfigErrors, ConfigWarnings]
            Combined validation errors and warnings from this wrapper and the
            underlying ``mkdocs-d2`` plugin when available.
        """
        errors, warnings = super().load_config(options, config_file_path)
        if D2Plugin is None:
            message = "mkdocs-d2-plugin is not installed; skipping D2 diagram rendering."
            self._warn_once(message)
            cast("list[object]", warnings).append(message)
            self._delegate = None
            return errors, warnings

        if shutil.which("d2") is None:
            message = (
                "The 'd2' executable was not found on PATH; existing diagrams will be "
                "served but new renders are skipped. Install the D2 CLI to refresh diagrams."
            )
            self._warn_once(message)
            cast("list[object]", warnings).append(message)
            self._delegate = None
            return errors, warnings

        delegate = D2Plugin()
        delegate_errors, delegate_warnings = delegate.load_config(options, config_file_path)
        errors.extend(delegate_errors)
        warnings.extend(delegate_warnings)
        self._delegate = delegate
        return errors, warnings

    def _warn_once(self, message: str) -> None:
        """Emit ``message`` at warning level exactly once per build."""
        if not self._warned:
            LOGGER.warning(message)
            self._warned = True

    def __getattr__(self, name: str) -> Callable[..., Any]:
        """Delegate mkdocs lifecycle hooks to the wrapped plugin when active.

        Parameters
        ----------
        name : str
            Attribute name to look up (must start with "on_" for lifecycle hooks).

        Returns
        -------
        Callable[..., Any]
            Lifecycle hook implementation sourced from the wrapped plugin or a
            no-op stub when delegation is disabled.

        Raises
        ------
        AttributeError
            If ``name`` does not resemble an MkDocs plugin lifecycle hook.
        """
        if not name.startswith("on_"):
            raise AttributeError(name)

        if self._delegate is None:
            return _noop

        return getattr(self._delegate, name)


__all__ = ["OptionalD2Plugin"]
