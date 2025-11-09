"""Namespace bridge that exposes the vectorstore_faiss package under kgfoundry."""

# [nav:section public-api]

from __future__ import annotations

from typing import cast

import vectorstore_faiss as _module
from kgfoundry.tooling_bridge import (
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
    """Return ``name`` from the proxied ``vectorstore_faiss`` module.

    Parameters
    ----------
    name : str
        Attribute name to look up.

    Returns
    -------
    object
        Attribute value from the proxied module.
    """
    return namespace_getattr(_module, name)


def __dir__() -> list[str]:
    """Return the combined attribute listing exposed by the namespace bridge.

    Returns
    -------
    list[str]
        Combined list of attributes from the module and exports.
    """
    return namespace_dir(_module, _EXPORTS)
