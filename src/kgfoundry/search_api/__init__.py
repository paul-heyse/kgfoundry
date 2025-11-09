"""Namespace bridge that exposes the search_api package under kgfoundry."""

# [nav:section public-api]

from __future__ import annotations

from typing import cast

import search_api as _module
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
    """Provide lazy module loading for namespace bridge.

    Implements lazy loading for attributes from the underlying search_api
    module. This allows the namespace bridge to expose search_api symbols
    under the kgfoundry namespace.

    Parameters
    ----------
    name : str
        Attribute name to retrieve from the underlying module.

    Returns
    -------
    object
        Attribute value from the underlying search_api module.
    """
    return namespace_getattr(_module, name)


def __dir__() -> list[str]:
    """Return the combined attribute listing.

    Returns the sorted union of exports and implementation attributes
    from the namespace bridge.

    Returns
    -------
    list[str]
        Sorted union of exports and implementation attributes.
    """
    return namespace_dir(_module, _EXPORTS)
