"""Helpers for working with msgspec-based settings structs."""

from __future__ import annotations

from msgspec import Struct, structs

from codeintel_rev.config.settings import Settings


def replace_settings(settings: Settings, **updates: object) -> Settings:
    """Return a new Settings instance with updates applied.

    Extended Summary
    ----------------
    This function creates a new Settings instance by cloning the provided settings
    and applying field overrides via keyword arguments. It uses msgspec's structs.replace
    utility to perform immutable updates, ensuring the original settings object remains
    unchanged. This is useful for creating modified settings configurations for testing
    or specialized use cases without mutating the original.

    Parameters
    ----------
    settings : Settings
        Original Settings instance to clone and modify. The instance is not modified.
    **updates : object
        Keyword arguments mapping field names to new values. Only fields that exist
        in the Settings struct can be overridden. Invalid field names are ignored
        by msgspec.

    Returns
    -------
    Settings
        New Settings instance with the provided fields overridden. All other fields
        are copied from the original settings instance.

    Notes
    -----
    Time complexity O(1) for struct cloning. Space complexity O(1) aside from the
    new Settings object. The function performs no I/O and has no side effects.
    Thread-safe as it operates on immutable structs.
    """
    return structs.replace(settings, **updates)


def replace_struct[T: Struct](instance: T, **updates: object) -> T:
    """Clone a struct instance with the provided field overrides applied.

    Extended Summary
    ----------------
    This generic function creates a new struct instance by cloning the provided
    instance and applying field overrides via keyword arguments. It uses msgspec's
    structs.replace utility to perform immutable updates, ensuring the original
    instance remains unchanged. This is a type-safe way to create modified struct
    instances for any msgspec Struct type, useful for configuration overrides and
    test fixtures.

    Parameters
    ----------
    instance : T
        Original struct instance to clone and modify. Must be an instance of a
        class that inherits from msgspec.Struct. The instance is not modified.
    **updates : object
        Keyword arguments mapping field names to new values. Only fields that exist
        in the struct type T can be overridden. Invalid field names are ignored
        by msgspec.

    Returns
    -------
    T
        New struct instance of the same type as instance, with the provided fields
        overridden. All other fields are copied from the original instance.

    Notes
    -----
    Time complexity O(1) for struct cloning. Space complexity O(1) aside from the
    new struct object. The function performs no I/O and has no side effects.
    Thread-safe as it operates on immutable structs. Type-safe via generic type
    parameter T constrained to Struct.
    """
    return structs.replace(instance, **updates)


__all__ = ["replace_settings", "replace_struct"]
