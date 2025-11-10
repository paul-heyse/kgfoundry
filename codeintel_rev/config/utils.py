"""Helpers for working with msgspec-based settings structs."""

from __future__ import annotations

from typing import cast

from msgspec import Struct, structs

from codeintel_rev.config.settings import Settings


def replace_settings(settings: Settings, **updates: object) -> Settings:
    """Return a new ``Settings`` instance with ``updates`` applied.

    Returns
    -------
    Settings
        Clone of ``settings`` with the provided fields overridden.
    """
    return structs.replace(settings, **updates)


def replace_struct[T: Struct](instance: T, **updates: object) -> T:
    """Clone ``instance`` with the provided field overrides applied.

    Returns
    -------
    T
        New struct instance containing the overrides.
    """
    return cast("T", structs.replace(instance, **updates))


__all__ = ["replace_settings", "replace_struct"]
