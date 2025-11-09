"""Namespace bridge that exposes the ``search_client`` package under ``kgfoundry``."""

# [nav:section public-api]

from __future__ import annotations

from typing import cast

import kgfoundry.search_client as _module
from kgfoundry.namespace_bridge import (
    namespace_attach,
    namespace_dir,
    namespace_exports,
    namespace_getattr,
)
from search_client import KGFoundryClient as _KGFoundryClient

KGFoundryClient = _KGFoundryClient

_EXPORTS = tuple(namespace_exports(_module))
_namespace = cast("dict[str, object]", globals())
namespace_attach(_module, _namespace, _EXPORTS)

__doc__ = _module.__doc__
__path__ = list(_module.__path__)


def __getattr__(name: str) -> object:
    """Forward attribute lookups to the underlying module.

    Provides a fallback for unknown attribute lookups, delegating
    to the namespace bridge helper.

    Parameters
    ----------
    name : str
        Attribute name to look up.

    Returns
    -------
    object
        Attribute value from the underlying module.
    """
    return namespace_getattr(_module, name)


def __dir__() -> list[str]:
    """Return the combined attribute listing.

    Returns
    -------
    list[str]
        Sorted union of exports and implementation attributes.
    """
    return namespace_dir(_module, _EXPORTS)
