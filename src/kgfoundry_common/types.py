"""Type aliases for kgfoundry_common.

This module provides shared type definitions without any dependencies, avoiding circular imports
across the package.
"""

# [nav:section public-api]

from __future__ import annotations

from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "JsonPrimitive",
    "JsonValue",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# Primitive JSON types (leaf values)
type JsonPrimitive = str | int | float | bool | None

# JSON value can be primitive or nested (dict/list)
type JsonValue = JsonPrimitive | dict[str, JsonValue] | list[JsonValue]
