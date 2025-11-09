"""Core configuration infrastructure for WARP.

This module provides DefaultVal wrapper for default values and CoreConfig
base class for managing configuration attributes with assignment tracking.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, fields

# Maximum length for list/dict representation in provenance
MAX_PROVENANCE_LENGTH = 100


@dataclass(frozen=True)
class DefaultVal:
    """Wrapper for default configuration values.

    Used to distinguish default values from explicitly assigned values
    in configuration classes. Supports hashing and equality comparison.

    Parameters
    ----------
    val : object
        Default value to wrap.
    """

    val: object

    def __hash__(self) -> int:
        """Compute hash based on wrapped value representation.

        Returns
        -------
        int
            Hash of value representation.
        """
        return hash(repr(self.val))

    def __eq__(self, other: object) -> bool:
        """Compare equality with another DefaultVal instance.

        Parameters
        ----------
        other : object
            Object to compare.

        Returns
        -------
        bool
            True if other is DefaultVal with equal value.
        """
        if not isinstance(other, DefaultVal):
            return False
        return self.val == other.val


@dataclass(frozen=True)
class CoreConfig:
    """Base configuration class with assignment tracking.

    Tracks which configuration attributes have been explicitly assigned
    versus using defaults. Supports dynamic configuration updates and export.

    Attributes
    ----------
    assigned : dict[str, bool]
        Dictionary tracking which fields have been explicitly assigned.
    """

    def __post_init__(self) -> None:
        """Initialize assignment tracking and resolve default values.

        Source: https://stackoverflow.com/a/58081120/1493011.

        Replaces DefaultVal wrappers with actual values and marks fields
        as assigned if they were not wrapped in DefaultVal.
        """
        self.assigned = {}

        for field in fields(self):
            field_val = getattr(self, field.name)

            if isinstance(field_val, DefaultVal) or field_val is None:
                setattr(self, field.name, field.default.val)

            if not isinstance(field_val, DefaultVal):
                self.assigned[field.name] = True

    def assign_defaults(self) -> None:
        """Assign all default values to configuration fields.

        Sets all fields to their default values and marks them as assigned.
        """
        for field in fields(self):
            setattr(self, field.name, field.default.val)
            self.assigned[field.name] = True

    def configure(self, *, ignore_unrecognized: bool = True, **kw_args: object) -> set[str]:
        """Configure multiple attributes from keyword arguments.

        Sets multiple configuration attributes at once, returning set of
        ignored unrecognized keys.

        Parameters
        ----------
        ignore_unrecognized : bool
            Whether to ignore unrecognized keys (default: True).
        **kw_args : object
            Keyword arguments mapping attribute names to values.

        Returns
        -------
        set[str]
            Set of ignored unrecognized keys.

        TODO
        ----
        Take a config object, not kw_args.
        """
        ignored = set()

        for key, value in kw_args.items():
            self.set(key, value, ignore_unrecognized=ignore_unrecognized) or ignored.update({key})

        return ignored

    def set(self, key: str, value: object, *, ignore_unrecognized: bool = False) -> bool | None:
        """Set a single configuration attribute.

        Sets attribute value and marks it as assigned. Raises exception
        if key is unrecognized and ignore_unrecognized is False.

        Parameters
        ----------
        key : str
            Attribute name to set.
        value : object
            Value to assign.
        ignore_unrecognized : bool
            Whether to ignore unrecognized keys (default: False).

        Returns
        -------
        bool | None
            True if key was set, None if ignored.

        Raises
        ------
        ValueError
            If key is unrecognized and ignore_unrecognized=False.
        """
        if hasattr(self, key):
            setattr(self, key, value)
            self.assigned[key] = True
            return True

        if not ignore_unrecognized:
            msg = f"Unrecognized key `{key}` for {type(self)}"
            raise ValueError(msg)
        return None

    def help(self) -> None:
        """Display help information for configuration (placeholder).

        Intended to display configuration documentation, but currently
        unimplemented.
        """

    @staticmethod
    def __export_value(v: object) -> object:
        """Export value with provenance and truncation for large collections.

        Parameters
        ----------
        v : object
            Value to export.

        Returns
        -------
        object
            Exported value, possibly truncated or with provenance.
        """
        v = v.provenance() if hasattr(v, "provenance") else v

        if isinstance(v, list) and len(v) > MAX_PROVENANCE_LENGTH:
            v = (f"list with {len(v)} elements starting with...", v[:3])

        if isinstance(v, dict) and len(v) > MAX_PROVENANCE_LENGTH:
            v = (f"dict with {len(v)} keys starting with...", list(v.keys())[:3])

        return v

    def export(self) -> dict[str, object]:
        """Export configuration as dictionary.

        Converts configuration to dictionary format, applying value
        transformations and truncation for large collections.

        Returns
        -------
        dict[str, object]
            Configuration dictionary.
        """
        d = dataclasses.asdict(self)

        for k, v in d.items():
            d[k] = self.__export_value(v)

        return d
