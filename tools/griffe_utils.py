"""Griffe integration utilities for documentation generation."""

# pylint: disable=import-error,missing-docstring

from __future__ import annotations

import importlib
from dataclasses import dataclass, replace
from typing import cast

GriffeLoaderType = type[object]


@dataclass(frozen=True)
class GriffeAPIPackage:
    """Compatibility wrapper for Griffe module access across versions."""

    package: object
    object_type: object
    loader_type: object
    class_type: object
    function_type: object
    module_type: object


GriffeAPI = GriffeAPIPackage  # backwards compat


@dataclass(slots=True, frozen=True)
class _GriffeCache:
    """Singleton cache for Griffe API."""

    instance: GriffeAPI | None = None


_GRIFFE_CACHE: list[_GriffeCache] = [_GriffeCache()]


def resolve_griffe() -> GriffeAPI:
    """Return the ``griffe`` module along with key symbol/loader types.

    Newer versions of ``griffe`` expose ``GriffeLoader`` and the symbol classes
    (``Class``, ``Function``, and ``Module``) from the top-level package while
    older releases provide them under ``griffe.loader`` and
    ``griffe.dataclasses`` respectively. We import both variants eagerly and
    fall back to the top-level attributes whenever the nested modules are
    unavailable.

    Returns
    -------
    GriffeAPI
        Griffe API instance with loader and symbol types.
    """
    cached = _GRIFFE_CACHE[0].instance
    if cached is not None:
        return cached

    griffe_module = importlib.import_module("griffe")
    try:
        loader_module = importlib.import_module("griffe.loader")
    except ModuleNotFoundError:
        loader_module = None
    try:
        dataclasses_module = importlib.import_module("griffe.dataclasses")
    except ModuleNotFoundError:
        dataclasses_module = None

    if loader_module is not None:
        loader_cls = cast("GriffeLoaderType", loader_module.GriffeLoader)
    else:
        loader_cls = cast("GriffeLoaderType", griffe_module.GriffeLoader)

    symbols_source = dataclasses_module if dataclasses_module else griffe_module
    class_attr: object = symbols_source.Class
    function_attr: object = symbols_source.Function
    module_attr: object = symbols_source.Module
    object_attr: object = griffe_module.Object

    class_cls = cast("type", class_attr)
    function_cls = cast("type", function_attr)
    module_cls = cast("type", module_attr)
    object_cls = cast("type", object_attr)

    _GRIFFE_CACHE[0] = replace(
        _GRIFFE_CACHE[0],
        instance=GriffeAPI(
            package=griffe_module,
            object_type=object_cls,
            loader_type=loader_cls,
            class_type=class_cls,
            function_type=function_cls,
            module_type=module_cls,
        ),
    )
    return cast("GriffeAPI", _GRIFFE_CACHE[0].instance)
