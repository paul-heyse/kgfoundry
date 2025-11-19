"""Public wrapper for :mod:`tools._shared.settings`."""

from __future__ import annotations

from tools._shared.settings import SettingsError, ToolRuntimeSettings, get_runtime_settings

__all__: tuple[str, ...] = (
    "SettingsError",
    "ToolRuntimeSettings",
    "get_runtime_settings",
)
