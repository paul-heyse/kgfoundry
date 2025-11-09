"""Expose ``search_api.app`` inside the ``kgfoundry`` namespace."""

# [nav:section public-api]

from __future__ import annotations

from typing import cast

import search_api.app as _module
from kgfoundry.namespace_bridge import (
    namespace_attach,
    namespace_dir,
    namespace_exports,
    namespace_getattr,
)

_EXPORTS = tuple(namespace_exports(_module))
namespace_attach(_module, cast("dict[str, object]", globals()), _EXPORTS)

__doc__ = _module.__doc__
if hasattr(_module, "__path__"):
    __path__ = list(_module.__path__)


def __getattr__(name: str) -> object:
    """Delegate dynamic attribute lookup to the implementation module.

    Parameters
    ----------
    name : str
        Attribute name to look up.

    Returns
    -------
    object
        Attribute value from the implementation module.
    """
    return namespace_getattr(_module, name)


def __dir__() -> list[str]:
    """Return the combined attribute listing.

    Returns
    -------
    list[str]
        Combined list of attributes from the module and exports.
    """
    return namespace_dir(_module, _EXPORTS)
