"""Namespace bridge that exposes the docling_kg package under kgfoundry."""

# [nav:section public-api]

from __future__ import annotations

from typing import cast

import docling_kg as _module
from kgfoundry.namespace_bridge import (
    namespace_attach,
    namespace_dir,
    namespace_exports,
    namespace_getattr,
)

_EXPORTS = tuple(namespace_exports(_module))
_namespace = cast("dict[str, object]", globals())
namespace_attach(_module, _namespace, _EXPORTS)

__doc__ = _module.__doc__
if hasattr(_module, "__path__"):
    __path__ = list(_module.__path__)


def __getattr__(name: str) -> object:
    """Return attributes exposed by the docling_kg module.

    Parameters
    ----------
    name : str
        Attribute name to resolve.

    Returns
    -------
    object
        Attribute resolved from the underlying ``docling_kg`` namespace.
    """
    return namespace_getattr(_module, name)


def __dir__() -> list[str]:
    """Return the combined attribute listing.

    Returns
    -------
    list[str]
        Sorted list of attribute names provided by ``docling_kg``.
    """
    return namespace_dir(_module, _EXPORTS)
